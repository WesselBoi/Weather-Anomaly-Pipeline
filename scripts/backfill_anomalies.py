import pandas as pd
from datetime import date, timedelta
from sqlalchemy import text
from cities import CITIES
from db_utils import get_engine

engine = get_engine()

NUM_DAYS = 15
end_date = date(2026, 9, 21)
start_date = end_date - timedelta(days=NUM_DAYS - 1)

obs = pd.read_sql("""
    SELECT city, date, temp_mean, day_of_year 
    FROM daily_observations 
    WHERE date BETWEEN %(start)s AND %(end)s
    ORDER BY city, date
""", engine, params={"start": start_date.isoformat(), "end": end_date.isoformat()})

baseline = pd.read_sql("SELECT city, day_of_year, temp_mean_avg, temp_mean_std FROM historical_baseline", engine)

flagged = 0
checked = 0

with engine.begin() as conn:
    for _, row in obs.iterrows():
        checked += 1
        base_row = baseline[(baseline["city"] == row["city"]) & (baseline["day_of_year"] == row["day_of_year"])]
        if base_row.empty or base_row["temp_mean_std"].iloc[0] == 0:
            continue

        mean = base_row["temp_mean_avg"].iloc[0]
        std = base_row["temp_mean_std"].iloc[0]
        z = (row["temp_mean"] - mean) / std

        if abs(z) > 2:
            severity = "severe" if abs(z) > 3 else "moderate"
            target_date = row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"])
            conn.execute(text("""
                INSERT INTO anomalies (city, date, feature, z_score, severity)
                VALUES (:city, :date, 'temp_mean', :z, :severity)
                ON CONFLICT (city, date, feature) DO UPDATE
                SET z_score = EXCLUDED.z_score, severity = EXCLUDED.severity
            """), {"city": row["city"], "date": target_date, "z": float(z), "severity": severity})
            flagged += 1

print(f"Checked {checked} city-days from {start_date} to {end_date}, flagged {flagged} anomalies")