#This file ingests predictions from 4 things (2 ML models along with persistence and seasonal naive) and logs them into the database for the next day's temperature which are then compared with the actuals in backfill_actuals.py to calculate the error for each model

import pandas as pd
from datetime import date, timedelta
from sklearn.linear_model import LinearRegression
from xgboost import XGBRegressor
from sqlalchemy import text
from cities import CITIES
from db_utils import get_engine

def upsert_forecast(engine, records):
    with engine.begin() as conn:
        for r in records:
            params = dict(r)
            params["predicted_temp"] = float(params["predicted_temp"])
            params["created_at"] = pd.Timestamp(params["created_at"]).to_pydatetime()
            conn.execute(text("""
                INSERT INTO forecast_predictions (city, target_date, predicted_temp, source, actual_temp, created_at)
                VALUES (:city, :target_date, :predicted_temp, :source, :actual_temp, :created_at)
                ON CONFLICT (city, target_date, source) DO UPDATE
                SET predicted_temp = EXCLUDED.predicted_temp,
                    created_at = EXCLUDED.created_at
            """), params)

engine = get_engine()
df = pd.read_sql("SELECT * FROM daily_observations ORDER BY city, date", engine)
df["date"] = pd.to_datetime(df["date"])

city_names = {c["city"] for c in CITIES}
actual_cities = set(df["city"].unique())
if actual_cities != city_names:
    raise ValueError(f"City mismatch! Expected {city_names}, found {actual_cities}")

def build_features(g):
    g = g.sort_values("date").copy()
    g["lag_1"] = g["temp_mean"].shift(1)
    g["lag_2"] = g["temp_mean"].shift(2)
    g["rolling_7"] = g["temp_mean"].shift(1).rolling(7).mean()
    g["target"] = g["temp_mean"].shift(-1)
    return g

feat_df = pd.concat([build_features(g) for _, g in df.groupby("city")])
feat_df = feat_df.dropna(subset=["lag_1", "lag_2", "rolling_7", "target"])
feat_df = pd.get_dummies(feat_df, columns=["city"], prefix="city")

city_cols = [c for c in feat_df.columns if c.startswith("city_")]
feature_cols = ["lag_1", "lag_2", "rolling_7", "day_of_year"] + city_cols
X, y = feat_df[feature_cols], feat_df["target"]

lin_model = LinearRegression().fit(X, y)
xgb_model = XGBRegressor(n_estimators=200, max_depth=4, learning_rate=0.05).fit(X, y)

target_date = (date.today() + timedelta(days=1)).isoformat()
records = []

for city, g in df.groupby("city"):
    g = g.sort_values("date")
    if len(g) < 8:
        print(f"Skipping {city}: only {len(g)} rows available")
        continue

    lag_1, lag_2 = g.iloc[-1]["temp_mean"], g.iloc[-2]["temp_mean"]
    rolling_7 = g["temp_mean"].tail(7).mean()
    doy = (int(g.iloc[-1]["day_of_year"]) % 366) + 1

    records.append(dict(city=city, target_date=target_date, predicted_temp=lag_1,
                         source="persistence", actual_temp=None, created_at=pd.Timestamp.now()))

    base = pd.read_sql(
        "SELECT temp_mean_avg FROM historical_baseline WHERE city=%(c)s AND day_of_year=%(d)s",
        engine, params={"c": city, "d": doy})
    seasonal_pred = base["temp_mean_avg"].iloc[0] if not base.empty else lag_1
    records.append(dict(city=city, target_date=target_date, predicted_temp=seasonal_pred,
                         source="seasonal_naive", actual_temp=None, created_at=pd.Timestamp.now()))

    row = {"lag_1": lag_1, "lag_2": lag_2, "rolling_7": rolling_7, "day_of_year": doy}
    for c in city_cols:
        row[c] = 1 if c == f"city_{city}" else 0
    X_pred = pd.DataFrame([row])[feature_cols]

    records.append(dict(city=city, target_date=target_date, predicted_temp=lin_model.predict(X_pred)[0],
                         source="linear_reg", actual_temp=None, created_at=pd.Timestamp.now()))
    records.append(dict(city=city, target_date=target_date, predicted_temp=xgb_model.predict(X_pred)[0],
                         source="xgboost", actual_temp=None, created_at=pd.Timestamp.now()))

upsert_forecast(engine, records)
print(f"Logged {len(records)} ML predictions for {target_date}")