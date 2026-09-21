import time
from datetime import date, timedelta
import pandas as pd
import requests
from sqlalchemy import text

from cities import CITIES
from db_utils import get_engine

engine = get_engine()
archive_url = "https://archive-api.open-meteo.com/v1/archive"
forecast_url = "https://api.open-meteo.com/v1/forecast"

start_repair = date(2026, 1, 2)
yesterday = date.today() - timedelta(days=1)
archive_end = date.today() - timedelta(days=6)

print(f"Repairing NULL columns in daily_observations from {start_repair} to {yesterday}...")

for item in CITIES:
    records = []

    # Part 1: Bulk historical repair from Archive API
    if start_repair <= archive_end:
        params = {
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "start_date": start_repair.isoformat(),
            "end_date": archive_end.isoformat(),
            "daily": "temperature_2m_min,temperature_2m_max,temperature_2m_mean,precipitation_sum,wind_speed_10m_max",
            "hourly": "relative_humidity_2m",
            "timezone": "auto",
        }
        resp = requests.get(archive_url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if "daily" in data and "hourly" in data:
            hourly_df = pd.DataFrame({
                "date": pd.to_datetime(data["hourly"]["time"]).date,
                "humidity": data["hourly"]["relative_humidity_2m"],
            })
            daily_humidity = hourly_df.groupby("date")["humidity"].mean().to_dict()

            d = data["daily"]
            for idx, dt_str in enumerate(d["time"]):
                dt = pd.Timestamp(dt_str).date()
                records.append({
                    "city": item["city"],
                    "date": dt_str,
                    "latitude": item["latitude"],
                    "longitude": item["longitude"],
                    "temp_min": d["temperature_2m_min"][idx],
                    "temp_max": d["temperature_2m_max"][idx],
                    "temp_mean": d["temperature_2m_mean"][idx],
                    "precipitation_sum": d["precipitation_sum"][idx],
                    "wind_speed": d["wind_speed_10m_max"][idx],
                    "humidity": daily_humidity.get(dt, None),
                    "day_of_year": pd.Timestamp(dt_str).dayofyear,
                })

    # Part 2: Recent days repair from Forecast API past_days
    recent_start = max(start_repair, archive_end + timedelta(days=1))
    if recent_start <= yesterday:
        past_days_needed = (date.today() - recent_start).days
        params = {
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "daily": "temperature_2m_min,temperature_2m_max,temperature_2m_mean,precipitation_sum,wind_speed_10m_max",
            "hourly": "relative_humidity_2m",
            "past_days": past_days_needed,
            "forecast_days": 1,
            "timezone": "auto",
        }
        resp = requests.get(forecast_url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if "daily" in data and "hourly" in data:
            hourly_df = pd.DataFrame({
                "date": pd.to_datetime(data["hourly"]["time"]).date,
                "humidity": data["hourly"]["relative_humidity_2m"],
            })
            daily_humidity = hourly_df.groupby("date")["humidity"].mean().to_dict()

            d = data["daily"]
            for idx, dt_str in enumerate(d["time"]):
                dt = pd.Timestamp(dt_str).date()
                if recent_start <= dt <= yesterday:
                    records.append({
                        "city": item["city"],
                        "date": dt_str,
                        "latitude": item["latitude"],
                        "longitude": item["longitude"],
                        "temp_min": d["temperature_2m_min"][idx],
                        "temp_max": d["temperature_2m_max"][idx],
                        "temp_mean": d["temperature_2m_mean"][idx],
                        "precipitation_sum": d["precipitation_sum"][idx],
                        "wind_speed": d["wind_speed_10m_max"][idx],
                        "humidity": daily_humidity.get(dt, None),
                        "day_of_year": pd.Timestamp(dt_str).dayofyear,
                    })

    # UPSERT to update existing NULL fields
    with engine.begin() as conn:
        for r in records:
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
                r,
            )

    print(f"{item['city']}: repaired {len(records)} days")
    time.sleep(1.5)

print("Repair complete! All NULL fields updated.")