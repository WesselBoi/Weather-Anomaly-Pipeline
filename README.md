# Weather Anomaly Detection & Forecast Accuracy Pipeline
<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white" alt="Supabase" />
  <img src="https://img.shields.io/badge/Grafana-F46800?style=for-the-badge&logo=grafana&logoColor=white" alt="Grafana" />
  <img src="https://img.shields.io/badge/XGBoost-EB5424?style=for-the-badge&logo=xgboost&logoColor=white" alt="XGBoost" />
  <img src="https://img.shields.io/badge/scikit_learn-F7931E?style=for-the-badge&logo=scikit-learn&logoColor=white" alt="scikit-learn" />
  <img src="https://img.shields.io/badge/Pandas-150458?style=for-the-badge&logo=pandas&logoColor=white" alt="Pandas" />
  <img src="https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=github-actions&logoColor=white" alt="GitHub Actions" />
</p>

An end-to-end data pipeline that ingests daily weather data for six cities worldwide, detects statistically anomalous weather using historical baselines, and benchmarks four forecasting methods (including two ML models) against real physics-based weather forecasts.

Built to demonstrate the full data lifecycle: ingestion → storage → transformation → modeling → automation → visualization — not just a notebook.

## What this project does

1. **Ingests** 10 years of historical daily weather data for 6 cities from the [Open-Meteo](https://open-meteo.com/) API
2. **Detects anomalies** by comparing each day's actual weather against a rolling 10-year historical baseline, using z-scores
3. **Predicts** next-day temperature using four methods — a naive persistence baseline, a seasonal-naive baseline, Linear Regression, and XGBoost — and logs each prediction
4. **Benchmarks** all four methods against Open-Meteo's own physics-based forecast once the actual weather is known, computing Mean Absolute Error (MAE) per method
5. **Automates** the daily cycle (backfill → anomaly check → forecast → predict) via GitHub Actions
6. **Visualizes** everything in a live Grafana dashboard connected directly to the database

## Cities tracked

Chosen deliberately for climate and hemisphere diversity, not convenience — this matters because it stress-tests the anomaly detection logic against genuinely different seasonal patterns (including an inverted Southern Hemisphere season):

| City | Climate type |
|---|---|
| New York | Temperate / continental |
| London | Temperate oceanic |
| Tokyo | Humid subtropical |
| Sydney | Temperate oceanic (Southern Hemisphere — inverted seasons) |
| Mumbai | Tropical monsoon |
| Reykjavik | Subarctic |

## Architecture

```
Open-Meteo API (Archive + Forecast)
        │
        ▼
Python ingestion scripts (requests, pandas)
        │
        ▼
PostgreSQL (Supabase) ── daily_observations, historical_baseline,
                          forecast_predictions, anomalies
        │
        ├──► GitHub Actions (daily cron: backfill → detect → forecast → predict)
        │
        └──► Grafana dashboard (live queries)
```

## Tech stack

| Layer | Technology |
|---|---|
| Data source | Open-Meteo Forecast API + Historical Archive API (free, no key) |
| Ingestion / transformation | Python, `pandas`, `requests` |
| Modeling | `scikit-learn` (Linear Regression), `xgboost` |
| Database | PostgreSQL (hosted on Supabase) |
| Orchestration | GitHub Actions (scheduled + manual trigger) |
| Dashboard | Grafana Cloud, connected directly to Postgres |
| ORM / DB access | SQLAlchemy, psycopg2 |

## Anomaly detection methodology

An anomaly is flagged when a day's actual mean temperature deviates from its historical norm by more than 2 standard deviations:

```
z = (actual_temp - historical_mean) / historical_std
```

`|z| > 2` → flagged as anomalous, `|z| > 3` → flagged as severe.

**Design decision:** the historical mean/std for a given calendar day is computed using a **±7-day rolling window** across 10 years of data (≈150 samples), rather than an exact day-of-year match (≈10 samples). An exact-day match produces noisy, unreliable standard deviations at this sample size — the rolling window trades a small amount of temporal precision for a much more statistically sound baseline.

**Validation:** backtested against the full 10-year historical dataset (21,924 city-days). Flag rate came out to 3.2%–4.1% across all six cities — consistent with the ~4.5% expected under a normal distribution at `|z|>2`, confirming the baseline calculation is well-calibrated rather than systematically over- or under-flagging.

## Forecast comparison — methodology

Every day, five predictions are logged for next-day temperature, per city:

| Method | How it works |
|---|---|
| `open_meteo` | Open-Meteo's own physics-based forecast (real NWP models — NOAA GFS, ECMWF, etc.) |
| `persistence` | Naive baseline: predicts tomorrow = today |
| `seasonal_naive` | Predicts tomorrow = the 10-year historical average for that calendar day |
| `linear_reg` | Linear Regression trained on lagged features |
| `xgboost` | Gradient-boosted trees trained on the same features |

**Features used:** `lag_1`, `lag_2` (previous 1–2 days' temp), `rolling_7` (7-day average), `day_of_year`, city (one-hot encoded), plus lagged `temp_min`, `temp_max`, `temp_range`, `precipitation`, `wind_speed`, and `humidity`.

Once the actual weather is known (next day), each prediction's error is computed as `|predicted - actual|`, enabling a direct MAE comparison across methods.

### Key finding: feature importance

After adding six additional lagged weather variables (precipitation, humidity, wind speed, temp min/max/range) to the ML models, XGBoost's feature importances showed:

- `rolling_7` (7-day average): **61.2%**
- `lag_1` (previous day): **28.0%**
- All other features combined (including all six newly added variables): **~11%**, none individually exceeding 7%

**Interpretation:** next-day mean temperature is dominated by short-term persistence — recent trend carries almost all the predictive signal. Precipitation, humidity, and wind speed, as single-day lagged snapshots, added negligible value. This suggests that meaningfully closing the gap with physics-based forecasting would require *rate-of-change* features (e.g., falling pressure, shifting wind direction over several days) rather than single-day values — closer to what actual numerical weather prediction models do, and a good explanation for why Open-Meteo's forecasts diverge from the statistical methods specifically during unstable weather (an incoming front, for example), when lagged daily data hasn't "seen" the change yet.

### Key finding: where statistical methods break down

On at least one observed date, Open-Meteo's forecast diverged sharply from all four statistical/ML methods (13.6°C vs. ~19.7–19.8°C predicted by persistence/seasonal_naive/linear_reg/xgboost for the same city and date) — consistent with an incoming weather system that only a physics-based model could detect. This is a clean illustration of the structural difference between numerical weather prediction and statistical time-series extrapolation: the latter assumes tomorrow resembles the recent past, which breaks down exactly when it matters most.

## Results


| Source | MAE (°C) | Predictions evaluated |
|---|---|---|
| open_meteo | 1.015 | 96 |
| xgboost | 1.265 | 96 |
| linear_reg | 1.252 | 96 |
| seasonal_naive | 1.868 | 96 |
| persistence | 1.584 | 96 |

## Dashboard

Live dashboard (Grafana): https://sprywildebeest305.grafana.net/public-dashboards/4403f5f9b5a14b79a9676ca378f89813

Includes: temperature trends per city, flagged anomalies table, forecast accuracy by method (MAE bar chart), per-city accuracy breakdown, and a running anomaly count.

## Project structure

```
weather-anomaly-pipeline/
├── .github/workflows/
│   └── daily_pipeline.yml       # GitHub Actions automation
├── scripts/
│   ├── cities.py                 # single source of truth for tracked cities
│   ├── db_utils.py               # shared DB connection
│   ├── ingest_historical.py      # one-time 10-year backfill
│   ├── ingest_forecast.py        # daily: logs Open-Meteo's forecast
│   ├── predict_ml.py             # daily: logs 4 statistical/ML predictions
│   ├── backfill_actuals.py       # daily: fills in actuals + computes error
│   ├── detect_anomalies.py       # daily: z-score anomaly flagging
│   └── gap_fill_historical.py    # one-time: fills any date gaps
├── sql/migrations/
│   ├── 001_init.sql
│   └── 002_add_anomalies_forecasts.sql
├── notebooks/
│   └── exploration.ipynb
├── requirements.txt
└── README.md
```

## Setup

1. Clone the repo, create a virtual environment, install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Create a free [Supabase](https://supabase.com) Postgres project, run the SQL migrations in `sql/migrations/` in order
3. Create a `.env` file:
   ```
   DATABASE_URL=postgresql://user:password@host:5432/postgres
   ```
4. Run the one-time historical backfill:
   ```bash
   python scripts/ingest_historical.py
   ```
5. Run the daily pipeline manually, or set up the GitHub Actions workflow (add `DATABASE_URL` as a repo secret):
   ```bash
   python scripts/backfill_actuals.py
   python scripts/detect_anomalies.py
   python scripts/ingest_forecast.py
   python scripts/predict_ml.py
   ```

## Known limitations

- **Free-tier rate limits:** Open-Meteo's non-commercial free tier (~10,000 requests/day) comfortably covers this project's usage, but a production version at larger scale would need a commercial plan.
- **Demo data window:** to enable building and testing the dashboard without waiting weeks for live data to accumulate, forecast predictions for [DATE RANGE] were backfilled using real historical actuals and real historical baselines, with synthetic (noise-based) prediction values calibrated to realistic error distributions per method. Live, non-synthetic tracking began [DATE]. This is disclosed here for transparency — real accuracy figures should be read from data after that date.
- **Model simplicity:** Linear Regression and XGBoost use only lagged daily aggregates, not live atmospheric data (pressure, satellite, radar) — this is a deliberate scope decision to compare "what can be learned from historical patterns alone" against a real physics-based forecast, not an attempt to outperform it.
- **GitHub Actions scheduling:** scheduled (cron) triggers on GitHub Actions are best-effort and can be delayed by several hours during periods of high platform load; the pipeline is currently run via a combination of manual and scheduled triggers.

## Possible future improvements

- Rate-of-change features (multi-day pressure/humidity trends) to better detect incoming weather system shifts
- An Express.js API layer exposing this data as REST endpoints (`/cities/:city/history`, `/forecast-accuracy`, `/anomalies/recent`)
- Slack/email alerting when a severe anomaly (`|z|>3`) is flagged
- Expanding beyond temperature to build separate anomaly models for precipitation and wind speed
