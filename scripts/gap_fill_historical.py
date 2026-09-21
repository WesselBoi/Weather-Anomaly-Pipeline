import pandas as pd
import requests
import time
from datetime import date, timedelta
from sqlalchemy import text
from cities import CITIES
from db_utils import get_engine

engine = get_engine()

# Find the last date we actually have, per city
existing = pd.read_sql("SELECT city, MAX(date) as last_date FROM daily_observations GROUP BY city", engine)
print(existing)

archive_url = "https://archive-api.open-meteo.com/v1/archive"
forecast_url = "https://api.open-meteo.com/v1/forecast"

for item in CITIES:
    last_date_row = existing[existing["city"] == item["city"]]
    if last_date_row.empty:
        print(f"No existing data for {item['city']}, skipping — run ingest_historical.py first")
        continue

    last_date = pd.to_datetime(last_date_row["last_date"].iloc[0]).date()
    gap_start = last_date + timedelta(days=1)
    # Archive API typically has a ~5 day lag, be conservative
    archive_end = date.today() - timedelta(days=6)
    yesterday = date.today() - timedelta(days=1)

    records = []

    # Part 1: Archive API for the bulk of the gap
    if gap_start <= archive_end:
        params = {
            "latitude": item["latitude"], "longitude": item["longitude"],
            "start_date": gap_start.isoformat(), "end_date": archive_end.isoformat(),
            "daily": "temperature_2m_mean", "timezone": "auto",
        }
        resp = requests.get(archive_url, params=params, timeout=15)
        resp.raise_for_status()
        d = resp.json()["daily"]
        for dt, temp in zip(d["time"], d["temperature_2m_mean"]):
            records.append({"city": item["city"], "date": dt, "temp_mean": temp,
                             "day_of_year": pd.Timestamp(dt).dayofyear})

    # Part 2: Forecast API's past_days for the recent tail the archive doesn't have yet
    recent_start = max(gap_start, archive_end + timedelta(days=1))
    if recent_start <= yesterday:
        past_days_needed = (date.today() - recent_start).days
        params = {
            "latitude": item["latitude"], "longitude": item["longitude"],
            "daily": "temperature_2m_mean", "past_days": past_days_needed,
            "forecast_days": 1, "timezone": "auto",
        }
        resp = requests.get(forecast_url, params=params, timeout=15)
        resp.raise_for_status()
        d = resp.json()["daily"]
        for dt, temp in zip(d["time"], d["temperature_2m_mean"]):
            if recent_start.isoformat() <= dt <= yesterday.isoformat():
                records.append({"city": item["city"], "date": dt, "temp_mean": temp,
                                 "day_of_year": pd.Timestamp(dt).dayofyear})

    with engine.begin() as conn:
        for r in records:
            conn.execute(text("""
                INSERT INTO daily_observations (city, date, temp_mean, day_of_year)
                VALUES (:city, :date, :temp_mean, :day_of_year)
                ON CONFLICT (city, date) DO NOTHING
            """), r)

    print(f"{item['city']}: filled {len(records)} days ({gap_start} to {yesterday})")
    time.sleep(2)

print("Gap fill complete.")