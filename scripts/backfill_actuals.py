# This file checks the actual temperature for the previous day from the open-meteo API and backfills it in the database in the actual_temp column of the forecast_predictions table. It also calculates the error for each model and backfills it in the error column of the forecast_predictions table. Finally, it backfills the daily_observations table with the actual temperature for the previous day. This leads to more data in the daily_observations table which is used to train the ML models in predict_ml.py. This file is run once a day after the open-meteo API has updated the actual temperature for the previous day.

from datetime import date, timedelta
import time
import pandas as pd
import requests
from sqlalchemy import text

from scripts.cities import CITIES
from scripts.db_utils import get_engine

url = "https://api.open-meteo.com/v1/forecast"
engine = get_engine()
yesterday = (date.today() - timedelta(days=1)).isoformat()

max_retries = 5
backoff_seconds = 5

for item in CITIES:
    params = {
        "latitude": item["latitude"],
        "longitude": item["longitude"],
        "daily": "temperature_2m_min,temperature_2m_max,temperature_2m_mean,precipitation_sum,wind_speed_10m_max",
        "hourly": "relative_humidity_2m",
        "start_date": yesterday,
        "end_date": yesterday,
        "timezone": "auto",
    }

    data = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=(30, 60))

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                wait_seconds = (
                    float(retry_after)
                    if retry_after
                    else backoff_seconds * (2 ** (attempt - 1))
                )
                print(
                    f"[429 Rate Limit] {item['city']}: retrying in {wait_seconds:.1f}s"
                )
                time.sleep(wait_seconds)
                continue

            resp.raise_for_status()
            data = resp.json()
            break

        except requests.exceptions.RequestException as error:
            wait_seconds = backoff_seconds * (2 ** (attempt - 1))
            print(f"[Attempt {attempt}/{max_retries}] {item['city']}: {error}")
            if attempt < max_retries:
                print(f"Retrying in {wait_seconds:.1f}s...")
                time.sleep(wait_seconds)

    if not data or "daily" not in data or not data["daily"].get("temperature_2m_mean"):
        print(f"Skipping {item['city']} for {yesterday} after failed attempts.")
        continue

    d = data["daily"]
    actual_mean = d["temperature_2m_mean"][0]
    temp_min = d["temperature_2m_min"][0]
    temp_max = d["temperature_2m_max"][0]
    precip = d["precipitation_sum"][0]
    wind = d["wind_speed_10m_max"][0]

    # Calculate average humidity for yesterday
    humidity_avg = None
    if "hourly" in data and "relative_humidity_2m" in data["hourly"]:
        humidity_vals = data["hourly"]["relative_humidity_2m"]
        if humidity_vals:
            humidity_avg = float(pd.Series(humidity_vals).mean())

    doy = pd.Timestamp(yesterday).dayofyear

    with engine.begin() as conn:
        # 1. Update forecast evaluations
        conn.execute(
            text("""
            UPDATE forecast_predictions
            SET actual_temp = :actual,
                error = ABS(predicted_temp - :actual)
            WHERE city = :city AND target_date = :target_date AND actual_temp IS NULL
        """),
            {"actual": actual_mean, "city": item["city"], "target_date": yesterday},
        )

        # 2. Insert full daily observation row
        conn.execute(
            text("""
            INSERT INTO daily_observations 
                (city, date, latitude, longitude, temp_min, temp_max, temp_mean, precipitation_sum, wind_speed, humidity, day_of_year)
            VALUES 
                (:city, :date, :latitude, :longitude, :temp_min, :temp_max, :temp_mean, :precipitation_sum, :wind_speed, :humidity, :day_of_year)
            ON CONFLICT (city, date) DO UPDATE SET
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                temp_min = EXCLUDED.temp_min,
                temp_max = EXCLUDED.temp_max,
                temp_mean = EXCLUDED.temp_mean,
                precipitation_sum = EXCLUDED.precipitation_sum,
                wind_speed = EXCLUDED.wind_speed,
                humidity = EXCLUDED.humidity,
                day_of_year = EXCLUDED.day_of_year
        """),
            {
                "city": item["city"],
                "date": yesterday,
                "latitude": item["latitude"],
                "longitude": item["longitude"],
                "temp_min": temp_min,
                "temp_max": temp_max,
                "temp_mean": actual_mean,
                "precipitation_sum": precip,
                "wind_speed": wind,
                "humidity": humidity_avg,
                "day_of_year": doy,
            },
        )

    print(f"Backfilled full actuals for {item['city']} ({yesterday}): {actual_mean}°C")

print(f"Completed backfill for {yesterday}")