"""
etl_pipeline.py
---------------
Fed Dual Mandate Dashboard — ETL Pipeline & Data Quality Framework
MSBA 692 Pipelines to Insights | German Collado Blanco | Week 3

This script implements a fully reproducible ETL pipeline that:
  1. Extracts four FRED economic series from the Federal Reserve API
  2. Validates the raw API response
  3. Cleans and normalizes raw data (missing values, data types, dates)
  4. Computes derived metrics (CPI year-over-year inflation)
  5. Runs a multi-layer data quality validation framework
  6. Applies an incremental loading strategy (only new/updated records)
  7. Loads transformed data into PostgreSQL (Supabase)
  8. Exports an analytics-ready CSV snapshot for Power BI

Series loaded:
  - FEDFUNDS  Federal Funds Effective Rate (Percent, Monthly)
  - CPIAUCSL  Consumer Price Index, All Urban Consumers (Index, Monthly)
  - UNRATE    Unemployment Rate (Percent, Monthly)
  - USREC     NBER Recession Indicator (Binary 0/1, Monthly)

Requires a .env file with:
    FRED_API_KEY, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
"""

import os
import logging
import requests
import pandas as pd
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from psycopg2.extras import execute_values

# ── Load environment variables ────────────────────────────────────────────────

load_dotenv()

FRED_API_KEY  = os.getenv("FRED_API_KEY")
DB_USER       = os.getenv("DB_USER")
DB_PASSWORD   = os.getenv("DB_PASSWORD")
DB_HOST       = os.getenv("DB_HOST")
DB_PORT       = os.getenv("DB_PORT", "5432")
DB_NAME       = os.getenv("DB_NAME", "postgres")

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# Minimum expected observations per series (FEDFUNDS starts 1954, others vary)
MIN_EXPECTED_ROWS = {
    "FEDFUNDS": 800,
    "CPIAUCSL": 800,
    "UNRATE":   800,
    "USREC":    800,
}

# Expected value ranges for range validation
VALUE_RANGES = {
    "FEDFUNDS": (0, 25),      # Fed rate: 0% to 25%
    "CPIAUCSL": (1, 500),     # CPI index: always positive
    "UNRATE":   (0, 100),     # Unemployment: 0% to 100%
    "USREC":    (0, 1),       # Binary recession flag: 0 or 1 only
}

# Series metadata to load into dim_series
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
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Database ──────────────────────────────────────────────────────────────────

def get_engine():
    """Create and return a SQLAlchemy engine connected to Supabase PostgreSQL."""
    url = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(url, connect_args={"sslmode": "require"})


def create_tables(engine):
    """
    Create dim_series and fred_observations tables if they do not already exist,
    then create the macro_dashboard view that pivots observations for Power BI.
    Running this more than once is safe — all statements use IF NOT EXISTS.
    """
    ddl = """
    CREATE TABLE IF NOT EXISTS dim_series (
        series_id   VARCHAR(20)  PRIMARY KEY,
        series_name VARCHAR(100) NOT NULL,
        description TEXT,
        units       VARCHAR(50),
        frequency   VARCHAR(20),
        created_at  TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS fred_observations (
        observation_id SERIAL       PRIMARY KEY,
        series_id      VARCHAR(20)  NOT NULL REFERENCES dim_series(series_id),
        obs_date       DATE         NOT NULL,
        value          NUMERIC(12,4),
        loaded_at      TIMESTAMP    DEFAULT NOW(),
        updated_at     TIMESTAMP    DEFAULT NOW(),
        UNIQUE (series_id, obs_date)
    );

    CREATE INDEX IF NOT EXISTS idx_fred_obs_date ON fred_observations (obs_date);

    -- macro_dashboard: analytics-ready view for Power BI
    -- Pivots from long format to wide format (one row per month, four indicator columns)
    -- CPI year-over-year is calculated using LAG(12) to compare to same month prior year
    CREATE OR REPLACE VIEW macro_dashboard AS
    SELECT
        obs_date,
        MAX(CASE WHEN series_id = 'FEDFUNDS' THEN value END)        AS fed_funds_rate,
        ROUND(
            (MAX(CASE WHEN series_id = 'CPIAUCSL' THEN value END) /
             NULLIF(LAG(MAX(CASE WHEN series_id = 'CPIAUCSL' THEN value END), 12)
                    OVER (ORDER BY obs_date), 0) - 1) * 100, 2)     AS cpi_yoy,
        MAX(CASE WHEN series_id = 'UNRATE' THEN value END)          AS unemployment,
        MAX(CASE WHEN series_id = 'USREC'  THEN value END)::SMALLINT AS is_recession
    FROM fred_observations
    GROUP BY obs_date
    ORDER BY obs_date;
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))
    log.info("Tables and view created (or already exist).")


def load_series_metadata(engine):
    """Insert the four FRED series into dim_series. Skip rows that already exist."""
    sql = """
    INSERT INTO dim_series (series_id, series_name, description, units, frequency)
    VALUES (:series_id, :series_name, :description, :units, :frequency)
    ON CONFLICT (series_id) DO NOTHING;
    """
    with engine.begin() as conn:
        for row in SERIES_METADATA:
            conn.execute(text(sql), row)
    log.info("Series metadata loaded into dim_series.")

# ── Incremental Loading ───────────────────────────────────────────────────────

def get_last_loaded_date(series_id: str, engine) -> str:
    """
    Incremental loading strategy:
    Query the database for the most recent observation date already stored
    for this series. The FRED API will then be called only for dates after
    this point, avoiding redundant full reloads on every pipeline run.

    On the first run (no data yet), returns '1950-01-01' to fetch all history.
    """
    sql = """
    SELECT MAX(obs_date) FROM fred_observations WHERE series_id = :series_id;
    """
    with engine.connect() as conn:
        result = conn.execute(text(sql), {"series_id": series_id}).scalar()

    if result is None:
        # No data yet — perform initial full load
        log.info(f"  {series_id}: No existing data found. Performing full historical load.")
        return "1950-01-01"
    else:
        # Data exists — fetch only from the day after the last loaded date
        last_date = result + timedelta(days=1)
        log.info(f"  {series_id}: Last loaded date is {result}. Fetching from {last_date} onwards.")
        return str(last_date)

# ── Extraction ────────────────────────────────────────────────────────────────

def extract_series(series_id: str, observation_start: str) -> dict:
    """
    Extract raw observations from the FRED API for a given series.
    Returns the raw JSON response as a dictionary.

    API response validation is performed immediately after extraction.
    observation_start controls incremental loading — only records on or
    after this date are returned by the API.
    """
    params = {
        "series_id":         series_id,
        "api_key":           FRED_API_KEY,
        "file_type":         "json",
        "observation_start": observation_start,
    }
    try:
        response = requests.get(FRED_BASE_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        log.error(f"  {series_id}: API request failed — {e}")
        raise RuntimeError(f"Unable to extract data for {series_id}") from e


def validate_api_response(raw: dict, series_id: str) -> None:
    """
    Validation check 1 — API Response Validation:
    Confirm that the FRED API returned a valid structure containing
    the expected series. This catches authentication failures, rate
    limits, or contract changes before transformation begins.

    Why it matters: a silent API failure would load zero rows without error,
    making downstream dashboards show stale or missing data.
    If validation fails: raise immediately and skip this series.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{series_id}: API response is not a JSON object.")
    if "observations" not in raw:
        raise ValueError(f"{series_id}: API response missing 'observations' key. Raw: {raw}")
    if len(raw["observations"]) == 0:
        raise ValueError(f"{series_id}: API returned zero observations.")
    log.info(f"  {series_id}: API response validation passed ({len(raw['observations'])} records).")

# ── Transformation & Cleaning ─────────────────────────────────────────────────

def clean_and_normalize(raw: dict, series_id: str) -> pd.DataFrame:
    """
    Cleaning and normalization:
    Convert the raw API JSON into a clean, typed DataFrame.

    Steps performed:
    1. FRED returns '.' for missing values — convert to NaN using pd.to_numeric
    2. Date strings ('1954-07-01') are converted to Python date objects
    3. Add the series_id column for database insertion
    4. Drop rows where both date and value are missing (fully empty records)
    """
    observations = raw["observations"]
    df = pd.DataFrame(observations)[["date", "value"]]

    # Cleaning: convert FRED's '.' missing value marker to proper NaN
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # Normalization: convert date strings to Python date type
    df["obs_date"] = pd.to_datetime(df["date"]).dt.date
    df["series_id"] = series_id
    df = df[["series_id", "obs_date", "value"]].dropna(subset=["obs_date"])

    log.info(f"  {series_id}: {len(df)} rows cleaned and normalized.")
    return df


def compute_cpi_yoy(df_wide: pd.DataFrame) -> pd.DataFrame:
    """
    Derived metric — CPI Year-Over-Year Inflation:
    The raw CPIAUCSL series from FRED is an index (e.g. 320.4), not a
    percentage. This function computes the year-over-year percentage change
    by comparing each month to the same month 12 periods earlier.

    Formula: ((CPI_current / CPI_12_months_ago) - 1) * 100

    Why this matters: raw CPI index values are not directly comparable across
    time without this normalization. The Fed targets 2% inflation, so the YoY
    figure is the analytically meaningful variable for the dual mandate dashboard.
    """
    df_wide = df_wide.sort_values("obs_date").copy()
    df_wide["cpi_yoy"] = (
        (df_wide["CPIAUCSL"] / df_wide["CPIAUCSL"].shift(12) - 1) * 100
    ).round(2)
    log.info("  Derived metric computed: CPI year-over-year inflation (cpi_yoy).")
    return df_wide


def build_analytics_snapshot(engine) -> pd.DataFrame:
    """
    Aggregation layer — Analytics-Ready Snapshot:
    Pivot fred_observations from long format (one row per series per month)
    to wide format (one row per month, four indicator columns).
    Then compute the CPI YoY derived metric in Python.

    This snapshot is exported as a CSV for direct use in Power BI,
    matching the structure of the macro_dashboard SQL view.
    """
    sql = """
    SELECT series_id, obs_date, value
    FROM fred_observations
    ORDER BY obs_date, series_id;
    """
    with engine.connect() as conn:
        df_long = pd.read_sql(text(sql), conn)

    # Pivot long to wide: one column per series
    df_wide = df_long.pivot(index="obs_date", columns="series_id", values="value").reset_index()
    df_wide.columns.name = None

    # Compute CPI year-over-year derived metric in Python
    df_wide = compute_cpi_yoy(df_wide)

    # Rename columns to match Power BI dashboard naming conventions
    df_wide = df_wide.rename(columns={
        "FEDFUNDS": "fed_funds_rate",
        "UNRATE":   "unemployment",
        "USREC":    "is_recession",
        "CPIAUCSL": "cpi_index",
    })

    log.info(f"  Analytics snapshot built: {len(df_wide)} rows, {len(df_wide.columns)} columns.")
    return df_wide

# ── Data Validation Framework ─────────────────────────────────────────────────

def validate_dataframe(df: pd.DataFrame, series_id: str) -> bool:
    """
    Multi-layer data quality validation framework.
    Runs five validation checks against a cleaned DataFrame.
    Returns True if all checks pass, False if any critical check fails.

    Checks performed:
      1. Null value check
      2. Duplicate date detection
      3. Range validation
      4. Row count verification
      5. Data type (schema) validation
    """
    passed = True

    # -- Validation Check 1: Null Value Check ----------------------------------
    # Why: null values in key fields prevent correct dashboard rendering and
    #      can silently corrupt aggregations in Power BI.
    # If fails: log a warning but continue — FRED sometimes has gaps for recent months.
    null_count = df["value"].isna().sum()
    null_pct   = null_count / len(df) if len(df) > 0 else 0
    if null_pct > 0.05:
        log.warning(f"  VALIDATION WARNING [{series_id}] Null check: "
                    f"{null_count} nulls ({null_pct:.1%}) — exceeds 5% threshold.")
        passed = False
    else:
        log.info(f"  VALIDATION PASSED  [{series_id}] Null check: "
                 f"{null_count} nulls ({null_pct:.1%}) — within threshold.")

    # -- Validation Check 2: Duplicate Date Detection -------------------------
    # Why: duplicate (series_id, obs_date) pairs would violate the unique
    #      constraint and cause the upsert to behave unexpectedly.
    # If fails: raise immediately — duplicates must be resolved before loading.
    dup_count = df.duplicated(subset=["obs_date"]).sum()
    if dup_count > 0:
        log.error(f"  VALIDATION FAILED  [{series_id}] Duplicate check: "
                  f"{dup_count} duplicate dates found.")
        passed = False
    else:
        log.info(f"  VALIDATION PASSED  [{series_id}] Duplicate check: no duplicate dates.")

    # -- Validation Check 3: Range Validation ----------------------------------
    # Why: out-of-range values indicate data corruption or API contract changes.
    #      E.g. USREC = 2 or UNRATE = -5 are physically impossible.
    # If fails: log an error and flag for review — do not silently load bad data.
    if series_id in VALUE_RANGES:
        lo, hi = VALUE_RANGES[series_id]
        non_null_values = df["value"].dropna()
        out_of_range = non_null_values[(non_null_values < lo) | (non_null_values > hi)]
        if len(out_of_range) > 0:
            log.error(f"  VALIDATION FAILED  [{series_id}] Range check: "
                      f"{len(out_of_range)} values outside [{lo}, {hi}]. "
                      f"Samples: {out_of_range.head(3).tolist()}")
            passed = False
        else:
            log.info(f"  VALIDATION PASSED  [{series_id}] Range check: "
                     f"all values within [{lo}, {hi}].")

    # -- Validation Check 4: Row Count Verification ---------------------------
    # Why: a suspiciously low row count may indicate a partial API response,
    #      network truncation, or an API rate limit silently cutting the data.
    # If fails: log an error — too few rows means the historical load is incomplete.
    min_rows = MIN_EXPECTED_ROWS.get(series_id, 1)
    if len(df) < min_rows:
        log.error(f"  VALIDATION FAILED  [{series_id}] Row count check: "
                  f"{len(df)} rows received, expected at least {min_rows}. "
                  f"Note: on incremental runs only new rows are fetched — this is expected.")
    else:
        log.info(f"  VALIDATION PASSED  [{series_id}] Row count check: "
                 f"{len(df)} rows (minimum: {min_rows}).")

    # -- Validation Check 5: Data Type (Schema) Validation --------------------
    # Why: if 'value' arrives as object (string) instead of float, all numeric
    #      operations silently fail or produce NaN in Power BI.
    # If fails: log an error — the cleaning step did not enforce numeric types.
    if not pd.api.types.is_numeric_dtype(df["value"]):
        log.error(f"  VALIDATION FAILED  [{series_id}] Schema check: "
                  f"'value' column dtype is {df['value'].dtype}, expected numeric.")
        passed = False
    else:
        log.info(f"  VALIDATION PASSED  [{series_id}] Schema check: "
                 f"'value' column dtype is {df['value'].dtype}.")

    return passed

# ── Loading ───────────────────────────────────────────────────────────────────

def upsert(df: pd.DataFrame, engine) -> int:
    """
    Load transformed observations into fred_observations using psycopg2's
    execute_values for a single-round-trip multi-row INSERT.

    ON CONFLICT (series_id, obs_date) DO UPDATE ensures:
    - New records are inserted
    - Existing records are updated if FRED retroactively revised a value
    This pattern implements the incremental upsert strategy — running the
    pipeline twice will not create duplicate rows.
    """
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
        cursor   = raw_conn.cursor()
        execute_values(cursor, sql, records, page_size=500)
        raw_conn.commit()
        cursor.close()
    return len(records)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 65)
    log.info("Fed Dual Mandate Dashboard — ETL Pipeline & Validation")
    log.info("=" * 65)

    try:
        engine = get_engine()
        log.info("Connected to PostgreSQL (Supabase).")

        create_tables(engine)
        load_series_metadata(engine)

        total_rows = 0

        for meta in SERIES_METADATA:
            sid = meta["series_id"]
            log.info(f"\nProcessing {sid} ...")

            try:
                # -- Incremental loading: find last loaded date for this series
                observation_start = get_last_loaded_date(sid, engine)

                # -- Extract: call FRED API only for new data
                raw = extract_series(sid, observation_start)

                # -- Validate raw API response before any transformation
                validate_api_response(raw, sid)

                # -- Transform: clean, normalize, and type-enforce
                df = clean_and_normalize(raw, sid)

                # -- Validate cleaned data with full quality framework
                is_valid = validate_dataframe(df, sid)
                if not is_valid:
                    log.warning(f"  {sid}: Validation issues found — proceeding with caution.")

                # -- Load: upsert into PostgreSQL
                rows = upsert(df, engine)
                total_rows += rows
                log.info(f"  {sid}: {rows} rows upserted successfully.")

            except Exception as e:
                # Error handling: log full details but continue with next series
                # so one failed series does not abort the entire pipeline run.
                log.error(f"  {sid}: Pipeline step failed — {e}")
                log.exception(f"  {sid}: Full traceback:")
                continue

        log.info("\n" + "-" * 65)
        log.info(f"All series processed. Total rows upserted: {total_rows:,}")

        # -- Build analytics snapshot and export CSV for Power BI
        log.info("\nBuilding analytics snapshot for Power BI ...")
        snapshot_df = build_analytics_snapshot(engine)
        csv_path = "macro_dashboard_snapshot.csv"
        snapshot_df.to_csv(csv_path, index=False)
        log.info(f"Analytics snapshot saved to: {csv_path}")
        log.info(f"Snapshot preview:\n{snapshot_df.tail(5).to_string(index=False)}")

        log.info("\n" + "=" * 65)
        log.info("ETL pipeline completed successfully.")
        log.info("=" * 65)

    except Exception as e:
        log.exception(f"Pipeline failed with unrecoverable error: {e}")
        raise


if __name__ == "__main__":
    main()
