# This file ingests all the data of temp from 2016 to 2026 and creates a historical baseline for each day

import pandas as pd
import requests
import time
from cities import CITIES
from db_utils import get_engine

url = "https://archive-api.open-meteo.com/v1/archive"
start_date = "2016-01-01"
end_date = "2026-01-01"

MAX_RETRIES = 5
BACKOFF_FACTOR = 5
DELAY_BETWEEN_CITIES = 3.0

all_dataframes = []

for item in CITIES:
    params = {
        "latitude": item["latitude"],
        "longitude": item["longitude"],
        "start_date": start_date,
        "end_date": end_date,
        "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum,wind_speed_10m_max",
        "hourly": "relative_humidity_2m",
        "timezone": "auto",
    }

    data = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 429:
                sleep_time = BACKOFF_FACTOR ** attempt
                print(f"[429 Rate Limit] {item['city']}: Retrying in {sleep_time}s...")
                time.sleep(sleep_time)
                continue
            response.raise_for_status()
            data = response.json()
            break
        except requests.exceptions.RequestException as e:
            sleep_time = BACKOFF_FACTOR ** attempt
            print(f"[Attempt {attempt}/{MAX_RETRIES}] Error fetching {item['city']}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(sleep_time)
            else:
                print(f"Skipping {item['city']} after {MAX_RETRIES} failed attempts.")

    if data and "daily" in data:
        city_df = pd.DataFrame({
            "date": pd.to_datetime(data["daily"]["time"]),
            "city": item["city"],
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "temp_min": data["daily"]["temperature_2m_min"],
            "temp_max": data["daily"]["temperature_2m_max"],
            "temp_mean": data["daily"]["temperature_2m_mean"],
            "precipitation_sum": data["daily"]["precipitation_sum"],
            "wind_speed": data["daily"]["wind_speed_10m_max"],
        })

        # Aggregate hourly humidity into daily mean
        hourly_times = pd.to_datetime(data["hourly"]["time"])
        humidity_df = pd.DataFrame({
            "date": hourly_times.date,
            "humidity": data["hourly"]["relative_humidity_2m"]
        })
        daily_humidity = humidity_df.groupby("date")["humidity"].mean().reset_index()
        daily_humidity["date"] = pd.to_datetime(daily_humidity["date"])

        city_df = city_df.merge(daily_humidity, on="date", how="left")
        all_dataframes.append(city_df)
        print(f"Successfully ingested {item['city']}")

    time.sleep(DELAY_BETWEEN_CITIES)

# Combine all cities
df = pd.concat(all_dataframes, ignore_index=True).sort_values(["city", "date"]).reset_index(drop=True)
df["day_of_year"] = df["date"].dt.dayofyear

print(f"Combined Dataset shape: {df.shape}")
print(f"Cities included: {df['city'].unique().tolist()}")

# Build rolling-window historical baseline (±7 days)
def get_window_stats(df, city, doy, window=7):
    days = [(doy + i - 1) % 366 + 1 for i in range(-window, window + 1)]
    subset = df[(df["city"] == city) & (df["day_of_year"].isin(days))]
    return subset["temp_mean"].mean(), subset["temp_mean"].std()

print("Building rolling window baselines...")
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

# Load into Postgres
engine = get_engine()
df.to_sql("daily_observations", engine, if_exists="append", index=False)
baseline_df.to_sql("historical_baseline", engine, if_exists="append", index=False)
print(f"Loaded {len(df)} observations and {len(baseline_df)} baseline rows into Postgres.")