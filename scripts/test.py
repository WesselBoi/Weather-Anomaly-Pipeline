import pandas as pd
from db_utils import get_engine

engine = get_engine()
df = pd.read_sql("SELECT * FROM daily_observations ORDER BY city, date", engine)
print(df.groupby("city").size())
print(df["city"].unique())