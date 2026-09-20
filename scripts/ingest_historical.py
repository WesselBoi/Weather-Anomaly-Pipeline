import os
import time
import requests
import pandas as pd
from db_utils import get_engine

# 1. Config & Cities
start_date = "2016-01-01"
end_date = "2026-01-01"
url = "https://archive-api.open-meteo.com/v1/archive"

cities = [
    {"city": "New York", "latitude": 40.7128, "longitude": -74.0060},
    {"city": "London", "latitude": 51.5074, "longitude": -0.1278},
    {"city": "Tokyo", "latitude": 35.6762, "longitude": 139.6503},
    {"city": "Sydney", "latitude": -33.8688, "longitude": 151.2093},
    {"city": "Mumbai", "latitude": 19.0760, "longitude": 72.8777},
    {"city": "Reykjavik", "latitude": 64.1466, "longitude": -21.9426}
]

MAX_RETRIES = 5
INITIAL_BACKOFF = 5.0
DELAY_BETWEEN_CITIES = 3.0

all_dataframes = []

# 2. Ingest Historical Data
print("Starting historical data ingestion from Open-Meteo...")
for item in cities:
    params = {
        "latitude": item["latitude"],
        "longitude": item["longitude"],
        "start_date": start_date,
        "end_date": end_date,
        "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum,wind_speed_10m_max",
        "hourly": "relative_humidity_2m",
        "timezone": "auto"
    }

    data = None

    # Retry loop with long timeout and adaptive backoff
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Increased timeout to 60s for 10-year hourly data payload
            response = requests.get(url, params=params, timeout=60)

            # Handle rate limiting explicitly (HTTP 429)
            if response.status_code == 429:
                # Use server-provided Retry-After header if available, else exponential backoff
                retry_after = response.headers.get("Retry-After")
                sleep_time = float(retry_after) if retry_after else INITIAL_BACKOFF * (2 ** (attempt - 1))
                print(f"[429 Rate Limit] {item['city']}: Waiting {sleep_time:.1f}s before retry (Attempt {attempt}/{MAX_RETRIES})...")
                time.sleep(sleep_time)
                continue

            response.raise_for_status()
            data = response.json()
            break  # Successful fetch

        except requests.exceptions.RequestException as e:
            sleep_time = INITIAL_BACKOFF * (2 ** (attempt - 1))
            print(f"[Attempt {attempt}/{MAX_RETRIES}] Error fetching {item['city']}: {e}")
            if attempt < MAX_RETRIES:
                print(f"Retrying in {sleep_time:.1f}s...")
                time.sleep(sleep_time)
            else:
                print(f"Skipping {item['city']} after {MAX_RETRIES} failed attempts.")

    # Parse valid response
    if data and "daily" in data and "hourly" in data:
        # Calculate daily relative humidity from hourly data
        hourly_times = pd.to_datetime(data["hourly"]["time"])
        humidity_df = pd.DataFrame({
            "date": hourly_times.date,
            "humidity": data["hourly"]["relative_humidity_2m"]
        })
        daily_humidity = humidity_df.groupby("date")["humidity"].mean().reset_index()
        daily_humidity["date"] = pd.to_datetime(daily_humidity["date"])

        # Base daily metrics
        city_df = pd.DataFrame({
            "date": pd.to_datetime(data["daily"]["time"]),
            "city": item["city"],
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "temp_min": data["daily"]["temperature_2m_min"],
            "temp_max": data["daily"]["temperature_2m_max"],
            "temp_mean": data["daily"]["temperature_2m_mean"],
            "precipitation_sum": data["daily"]["precipitation_sum"],
            "wind_speed": data["daily"]["wind_speed_10m_max"]
        })

        # Merge daily humidity into the city DataFrame on date
        city_df = pd.merge(city_df, daily_humidity, on="date", how="left")

        all_dataframes.append(city_df)
        print(f"Successfully ingested {item['city']}")

    # Pause briefly before querying the next city
    time.sleep(DELAY_BETWEEN_CITIES)

df = pd.concat(all_dataframes, ignore_index=True).sort_values(["city", "date"]).reset_index(drop=True)
df["day_of_year"] = df["date"].dt.dayofyear

# 3. Calculate Rolling Baseline Window (±7 days)
print("\nCalculating rolling baselines...")
def get_window_stats(df, city, doy, window=7):
    days = [(doy + i - 1) % 366 + 1 for i in range(-window, window + 1)]
    subset = df[(df["city"] == city) & (df["day_of_year"].isin(days))]
    return subset["temp_mean"].mean(), subset["temp_mean"].std()

baseline_records = []
for city in df["city"].unique():
    for doy in range(1, 367):
        mean_val, std_val = get_window_stats(df, city, doy, window=7)
        baseline_records.append({
            "city": city,
            "day_of_year": doy,
            "temp_mean_avg": mean_val,
            "temp_mean_std": std_val
        })

baseline_df = pd.DataFrame(baseline_records)

# Write to Supabase Postgres
print("\nUploading datasets to Supabase PostgreSQL...")
engine = get_engine()

# Save daily observations
df.to_sql("daily_observations", engine, if_exists="replace", index=False)
print(f"Loaded {len(df)} rows into 'daily_observations'")

# Save historical baseline
baseline_df.to_sql("historical_baseline", engine, if_exists="replace", index=False)
print(f"Loaded {len(baseline_df)} rows into 'historical_baseline'")

print("\nHistorical ingestion complete!")