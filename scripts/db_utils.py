import os
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

def get_engine():
    url = os.environ["DATABASE_URL"]
    # Force psycopg2 explicitly — don't let SQLAlchemy auto-select a driver
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    return create_engine(
        url,
        connect_args={"sslmode": "require"},
    )