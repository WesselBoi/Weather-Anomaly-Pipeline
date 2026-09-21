from datetime import date, timedelta
import time
import pandas as pd
import requests
from sqlalchemy import text

from cities import CITIES
from db_utils import get_engine


def upsert_forecast(engine, records):
    with engine.begin() as conn:
        for r in records:
            conn.execute(
                text("""
                INSERT INTO forecast_predictions (city, target_date, predicted_temp, source, actual_temp, created_at)
                VALUES (:city, :target_date, :predicted_temp, :source, :actual_temp, :created_at)
                ON CONFLICT (city, target_date, source) DO UPDATE
                SET predicted_temp = EXCLUDED.predicted_temp,
                    created_at = EXCLUDED.created_at
            """),
                r,
            )


url = "https://api.open-meteo.com/v1/forecast"
engine = get_engine()
records = []
max_retries = 5
backoff_seconds = 5

# Fixed target date (tomorrow) applied across all cities
target_date = (date.today() + timedelta(days=1)).isoformat()

for item in CITIES:
    params = {
        "latitude": item["latitude"],
        "longitude": item["longitude"],
        "daily": "temperature_2m_mean",
        "forecast_days": 3,
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

    if not data or "daily" not in data:
        print(f"Skipping {item['city']} after {max_retries} failed attempts.")
        continue

    d = data["daily"]

    # Match exact target_date position instead of hardcoding array index
    if target_date in d["time"]:
        idx = d["time"].index(target_date)
        predicted_temp = d["temperature_2m_mean"][idx]
    else:
        print(
            f"WARNING: {target_date} not found in response for {item['city']}, skipping"
        )
        continue

    records.append({
        "city": item["city"],
        "target_date": target_date,
        "predicted_temp": predicted_temp,
        "source": "open_meteo",
        "actual_temp": None,
        "created_at": pd.Timestamp.now(),
    })

upsert_forecast(engine, records)
print(f"Logged {len(records)} open_meteo forecasts for {target_date}")