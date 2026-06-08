"""
initial_load.py
---------------
Fed Dual Mandate Dashboard — Week 2 Initial Load Script
MSBA 692 Pipelines to Insights | German Collado Blanco

Pulls four FRED series (FEDFUNDS, CPIAUCSL, UNRATE, USREC) from the
Federal Reserve Economic Data API and loads them into a PostgreSQL
database hosted on Supabase.

Usage:
    python initial_load.py

Requires a .env file with:
    FRED_API_KEY, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
"""

import os
import logging
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ── Configuration ─────────────────────────────────────────────────────────────

load_dotenv()

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_API_KEY  = os.getenv("FRED_API_KEY")

DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST     = os.getenv("DB_HOST")
DB_PORT     = os.getenv("DB_PORT", "5432")
DB_NAME     = os.getenv("DB_NAME", "postgres")

SERIES_METADATA = [
    {
        "series_id":   "FEDFUNDS",
        "series_name": "Federal Funds Effective Rate",
        "description": "The interest rate at which depository institutions lend reserve balances "
                       "to other depository institutions overnight. Primary tool the Fed uses to "
                       "influence economic activity and inflation.",
        "units":       "Percent",
        "frequency":   "Monthly",
    },
    {
        "series_id":   "CPIAUCSL",
        "series_name": "Consumer Price Index for All Urban Consumers: All Items",
        "description": "Measures the average change over time in prices paid by urban consumers "
                       "for a market basket of goods and services. Used to compute year-over-year "
                       "inflation for the dual mandate inflation target.",
        "units":       "Index 1982-1984=100",
        "frequency":   "Monthly",
    },
    {
        "series_id":   "UNRATE",
        "series_name": "Unemployment Rate",
        "description": "Percentage of the labor force that is jobless, actively seeking work, "
                       "and available to take a job. Represents the employment side of the "
                       "Fed's dual mandate.",
        "units":       "Percent",
        "frequency":   "Monthly",
    },
    {
        "series_id":   "USREC",
        "series_name": "NBER Based Recession Indicators for the United States",
        "description": "Binary indicator (1 = recession, 0 = expansion) based on NBER business "
                       "cycle dates. Used to shade recession periods on dashboard time series charts.",
        "units":       "Binary (0/1)",
        "frequency":   "Monthly",
    },
]

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Database helpers ──────────────────────────────────────────────────────────

def get_engine():
    """Create and return a SQLAlchemy engine connected to the Supabase PostgreSQL instance."""
    url = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(url, connect_args={"sslmode": "require"})


def create_tables(engine):
    """
    Create dim_series and fred_observations tables if they do not already exist,
    then create the macro_dashboard view that pivots observations for Power BI.
    """
    ddl = """
    -- Dimension table: one row per FRED series
    CREATE TABLE IF NOT EXISTS dim_series (
        series_id   VARCHAR(20)  PRIMARY KEY,
        series_name VARCHAR(100) NOT NULL,
        description TEXT,
        units       VARCHAR(50),
        frequency   VARCHAR(20),
        created_at  TIMESTAMP    DEFAULT NOW()
    );

    -- Fact table: one row per series per month
    CREATE TABLE IF NOT EXISTS fred_observations (
        observation_id SERIAL          PRIMARY KEY,
        series_id      VARCHAR(20)     NOT NULL REFERENCES dim_series(series_id),
        obs_date       DATE            NOT NULL,
        value          NUMERIC(12, 4),
        loaded_at      TIMESTAMP       DEFAULT NOW(),
        updated_at     TIMESTAMP       DEFAULT NOW(),
        UNIQUE (series_id, obs_date)
    );

    -- Index to speed up date-range queries from Power BI
    CREATE INDEX IF NOT EXISTS idx_fred_obs_date
        ON fred_observations (obs_date);

    -- View: one row per month with all four indicators as columns
    -- CPI is converted to year-over-year % change using LAG(12)
    CREATE OR REPLACE VIEW macro_dashboard AS
    SELECT
        obs_date,
        MAX(CASE WHEN series_id = 'FEDFUNDS' THEN value END)                   AS fed_funds_rate,
        ROUND(
            (MAX(CASE WHEN series_id = 'CPIAUCSL' THEN value END) /
             NULLIF(LAG(MAX(CASE WHEN series_id = 'CPIAUCSL' THEN value END), 12)
                    OVER (ORDER BY obs_date), 0) - 1) * 100,
        2)                                                                       AS cpi_yoy,
        MAX(CASE WHEN series_id = 'UNRATE'  THEN value END)                    AS unemployment,
        MAX(CASE WHEN series_id = 'USREC'   THEN value END)::SMALLINT          AS is_recession
    FROM fred_observations
    GROUP BY obs_date
    ORDER BY obs_date;
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))
    log.info("Tables and view created (or already exist).")


def load_series_metadata(engine):
    """Insert the four FRED series into dim_series. Skip if the row already exists."""
    sql = """
    INSERT INTO dim_series (series_id, series_name, description, units, frequency)
    VALUES (:series_id, :series_name, :description, :units, :frequency)
    ON CONFLICT (series_id) DO NOTHING;
    """
    with engine.begin() as conn:
        for row in SERIES_METADATA:
            conn.execute(text(sql), row)
    log.info("Series metadata loaded into dim_series.")

# ── FRED API helpers ──────────────────────────────────────────────────────────

def fetch_series(series_id: str) -> pd.DataFrame:
    """
    Fetch all available observations for a FRED series and return a clean DataFrame
    with columns: series_id, obs_date, value.
    """
    params = {
        "series_id":     series_id,
        "api_key":       FRED_API_KEY,
        "file_type":     "json",
        "observation_start": "1950-01-01",
    }
    response = requests.get(FRED_BASE_URL, params=params, timeout=30)
    response.raise_for_status()

    data = response.json().get("observations", [])
    df = pd.DataFrame(data)[["date", "value"]].rename(columns={"date": "obs_date"})

    # FRED returns "." for missing values — convert to NaN
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["obs_date"] = pd.to_datetime(df["obs_date"]).dt.date
    df["series_id"] = series_id

    log.info(f"  {series_id}: {len(df):,} observations fetched.")
    return df[["series_id", "obs_date", "value"]]


# ── Data quality checks ───────────────────────────────────────────────────────

def validate(df: pd.DataFrame, series_id: str) -> bool:
    """
    Run basic data quality checks on a fetched DataFrame.
    Returns True if the data passes all checks, False otherwise.
    """
    passed = True

    if df.empty:
        log.error(f"  VALIDATION FAILED [{series_id}]: DataFrame is empty.")
        return False

    null_pct = df["value"].isna().mean()
    if null_pct > 0.05:
        log.warning(f"  VALIDATION WARNING [{series_id}]: {null_pct:.1%} null values (threshold 5%).")
        passed = False

    duplicate_dates = df.duplicated(subset=["obs_date"]).sum()
    if duplicate_dates > 0:
        log.error(f"  VALIDATION FAILED [{series_id}]: {duplicate_dates} duplicate dates found.")
        passed = False

    if passed:
        log.info(f"  {series_id}: All validation checks passed.")
    return passed


# ── Upsert ────────────────────────────────────────────────────────────────────

def upsert(df: pd.DataFrame, engine) -> int:
    """
    Insert all observations in a single multi-row INSERT using psycopg2's
    execute_values — one network round trip instead of one per row.
    This is orders of magnitude faster than executemany and avoids
    Session Pooler timeouts.
    If a (series_id, obs_date) combination already exists, update the value and
    updated_at timestamp — this handles FRED retroactive revisions.
    Returns the number of rows processed.
    """
    from psycopg2.extras import execute_values

    sql = """
    INSERT INTO fred_observations (series_id, obs_date, value)
    VALUES %s
    ON CONFLICT (series_id, obs_date)
    DO UPDATE SET
        value      = EXCLUDED.value,
        updated_at = NOW()
    """
    records = [
        (row["series_id"], row["obs_date"], row["value"])
        for row in df.to_dict(orient="records")
    ]
    with engine.connect() as conn:
        raw_conn = conn.connection
        cursor = raw_conn.cursor()
        execute_values(cursor, sql, records, page_size=500)
        raw_conn.commit()
        cursor.close()
    return len(records)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("Fed Dual Mandate Dashboard — Initial Load")
    log.info("=" * 60)

    engine = get_engine()
    log.info("Connected to PostgreSQL (Supabase).")

    create_tables(engine)
    load_series_metadata(engine)

    total_rows = 0
    for meta in SERIES_METADATA:
        sid = meta["series_id"]
        log.info(f"Processing {sid} ...")

        df = fetch_series(sid)

        if not validate(df, sid):
            log.warning(f"  Skipping upsert for {sid} due to validation issues.")
            continue

        rows = upsert(df, engine)
        total_rows += rows
        log.info(f"  {sid}: {rows:,} rows upserted.")

    log.info("-" * 60)
    log.info(f"Load complete. Total rows upserted: {total_rows:,}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
