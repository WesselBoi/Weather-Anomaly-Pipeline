CREATE TABLE anomalies (
    id SERIAL PRIMARY KEY,
    city TEXT NOT NULL,
    date DATE NOT NULL,
    feature TEXT NOT NULL,
    z_score DOUBLE PRECISION,
    severity TEXT
);

CREATE TABLE forecast_predictions (
    id SERIAL PRIMARY KEY,
    city TEXT NOT NULL,
    target_date DATE NOT NULL,
    predicted_temp DOUBLE PRECISION,
    source TEXT NOT NULL,       -- 'open_meteo', 'persistence', 'seasonal_naive', 'linear_reg', 'xgboost'
    actual_temp DOUBLE PRECISION,
    error DOUBLE PRECISION,
    created_at TIMESTAMP DEFAULT now()
);