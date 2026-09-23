import pandas as pd
from datetime import date, timedelta
from sqlalchemy import text
from cities import CITIES
from db_utils import get_engine

engine = get_engine()
yesterday = (date.today() - timedelta(days=1)).isoformat()
doy = pd.Timestamp(yesterday).dayofyear

obs = pd.read_sql(
    "SELECT city, temp_mean, precipitation_sum, wind_speed FROM daily_observations WHERE date = %(d)s",
    engine, params={"d": yesterday}
)

flagged = 0
with engine.begin() as conn:
    for _, row in obs.iterrows():
        baseline = pd.read_sql(
            "SELECT temp_mean_avg, temp_mean_std FROM historical_baseline WHERE city=%(c)s AND day_of_year=%(d)s",
            engine, params={"c": row["city"], "d": doy}
        )
        if baseline.empty or baseline["temp_mean_std"].iloc[0] == 0:
            continue

        mean, std = baseline["temp_mean_avg"].iloc[0], baseline["temp_mean_std"].iloc[0]
        z = (row["temp_mean"] - mean) / std

        if abs(z) > 2:
            severity = "severe" if abs(z) > 3 else "moderate"
            conn.execute(text("""
                INSERT INTO anomalies (city, date, feature, z_score, severity)
                VALUES (:city, :date, 'temp_mean', :z, :severity)
                ON CONFLICT DO NOTHING
            """), {"city": row["city"], "date": yesterday, "z": float(z), "severity": severity})
            flagged += 1

print(f"Checked {len(obs)} cities for {yesterday}, flagged {flagged} anomalies")