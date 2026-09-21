# This file checks the actual temperature for the previous day from the open-meteo API and backfills it in the database in the actual_temp column of the forecast_predictions table. It also calculates the error for each model and backfills it in the error column of the forecast_predictions table. Finally, it backfills the daily_observations table with the actual temperature for the previous day. This leads to more data in the daily_observations table which is used to train the ML models in predict_ml.py. This file is run once a day after the open-meteo API has updated the actual temperature for the previous day.

from datetime import date, timedelta
import time
import pandas as pd
import requests
from sqlalchemy import text

from cities import CITIES
from db_utils import get_engine

url = "https://api.open-meteo.com/v1/forecast"
engine = get_engine()
yesterday = (date.today() - timedelta(days=1)).isoformat()

max_retries = 5
backoff_seconds = 5

for item in CITIES:
    params = {
        "latitude": item["latitude"],
        "longitude": item["longitude"],
        "daily": "temperature_2m_mean",
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

    actual = data["daily"]["temperature_2m_mean"][0]

    with engine.begin() as conn:
        conn.execute(
            text("""
            UPDATE forecast_predictions
            SET actual_temp = :actual,
                error = ABS(predicted_temp - :actual)
            WHERE city = :city AND target_date = :target_date AND actual_temp IS NULL
        """),
            {"actual": actual, "city": item["city"], "target_date": yesterday},
        )

        doy = pd.Timestamp(yesterday).dayofyear
        conn.execute(
            text("""
            INSERT INTO daily_observations (city, date, temp_mean, day_of_year)
            VALUES (:city, :date, :actual, :doy)
            ON CONFLICT (city, date) DO NOTHING
        """),
            {"city": item["city"], "date": yesterday, "actual": actual, "doy": doy},
        )

    print(f"Backfilled actuals for {item['city']} ({yesterday}): {actual}°C")

print(f"Completed backfill for {yesterday}")