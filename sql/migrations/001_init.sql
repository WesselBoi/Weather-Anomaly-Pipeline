CREATE TABLE cities (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL
);

CREATE TABLE daily_observations (
    id SERIAL PRIMARY KEY,
    city TEXT NOT NULL,
    date DATE NOT NULL,
    temp_min DOUBLE PRECISION,
    temp_max DOUBLE PRECISION,
    temp_mean DOUBLE PRECISION,
    precipitation_sum DOUBLE PRECISION,
    wind_speed DOUBLE PRECISION,
    humidity DOUBLE PRECISION,
    day_of_year INT,
    UNIQUE (city, date)
);

CREATE TABLE historical_baseline (
    city TEXT NOT NULL,
    day_of_year INT NOT NULL,
    temp_mean_avg DOUBLE PRECISION,
    temp_mean_std DOUBLE PRECISION,
    PRIMARY KEY (city, day_of_year)
);