import requests
import pandas as pd
from datetime import date, timedelta
from db_utils import get_engine
from sqlalchemy import text

cities = [
    {"city": "Denver", "latitude": 39.7392, "longitude": -104.9903},
    {"city": "Mumbai", "latitude": 19.0760, "longitude": 72.8777},
    {"city": "Reykjavik", "latitude": 64.1466, "longitude": -21.9426},
    {"city": "Tokyo", "latitude": 35.6762, "longitude": 139.6503},
    {"city": "Cairo", "latitude": 30.0444, "longitude": 31.2357},
    {"city": "São Paulo", "latitude": -23.5505, "longitude": -46.6333},
]

url = "https://api.open-meteo.com/v1/forecast"
engine = get_engine()
yesterday = (date.today() - timedelta(days=1)).isoformat()

for item in cities:
    params = {
        "latitude": item["latitude"],
        "longitude": item["longitude"],
        "daily": "temperature_2m_mean",
        "start_date": yesterday,
        "end_date": yesterday,
        "timezone": "auto",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    d = resp.json()["daily"]
    actual = d["temperature_2m_mean"][0]

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE forecast_predictions
            SET actual_temp = :actual,
                error = ABS(predicted_temp - :actual)
            WHERE city = :city AND target_date = :target_date AND actual_temp IS NULL
        """), {"actual": actual, "city": item["city"], "target_date": yesterday})

print(f"Backfilled actuals for {yesterday}")