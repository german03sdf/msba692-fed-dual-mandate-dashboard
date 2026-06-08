# Fed Dual Mandate Dashboard
### MSBA 692 — Pipelines to Insights | German Collado Blanco | University of Louisville

> **Can the Fed control inflation without destroying jobs?**

A Bloomberg-style interactive analytics dashboard built on 70 years of Federal Reserve economic data. This project demonstrates a complete data engineering pipeline: API extraction → PostgreSQL → ETL → interactive Dash visualization.

---

## Business Insights

The Federal Reserve operates under a **dual mandate** — keep inflation around 2% while maintaining maximum employment. These two goals often conflict:

- When the Fed **raises rates** to fight inflation → unemployment tends to rise
- When the Fed **cuts rates** to boost employment → inflation can accelerate

The **Phillips Curve** chart in this dashboard makes that trade-off visible across 7 decades of data. The current position (marked "NOW") shows where the US economy stands today relative to history.

---

## Dashboard Features

- **3 KPI Cards** — Live Fed Funds Rate, CPI Inflation (YoY), Unemployment Rate
- **Time Series Chart** — All three indicators from 1954 to present, with NBER recession periods shaded in red
- **Phillips Curve** — Scatter plot of inflation vs unemployment, each point colored by the Fed Funds Rate
- **Interactive Date Slider** — Filter any time period to explore specific economic eras (1970s stagflation, 2008 crisis, COVID, etc.)

---

## Data Sources

All data from the **FRED API** (Federal Reserve Bank of St. Louis — fred.stlouisfed.org):

| Series | Name | Description |
|--------|------|-------------|
| FEDFUNDS | Federal Funds Effective Rate | The Fed's primary policy tool |
| CPIAUCSL | Consumer Price Index | Used to compute YoY inflation |
| UNRATE | Unemployment Rate | Employment side of the dual mandate |
| USREC | NBER Recession Indicator | Binary flag for recession periods |

---

## Project Architecture

```
FRED API → etl_pipeline.py → PostgreSQL (Supabase) → macro_dashboard VIEW → app.py → Dash
```

---

## Setup Instructions

### 1. Clone the repository
```bash
git clone https://github.com/germancolladoblanco/msba692-fed-dual-mandate-dashboard.git
cd msba692-fed-dual-mandate-dashboard
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment variables
```bash
cp .env.example .env
```
Edit `.env` and fill in your credentials:
```
FRED_API_KEY=your_fred_api_key
DB_USER=postgres.your_project_ref
DB_PASSWORD=your_supabase_password
DB_HOST=aws-1-us-west-2.pooler.supabase.com
DB_PORT=5432
DB_NAME=postgres
```

### 4. Run the ETL pipeline (loads data into PostgreSQL)
```bash
python etl_pipeline.py
```

### 5. Launch the dashboard
```bash
python app.py
```

Open your browser at: **http://localhost:8050**

---

## Files

| File | Description |
|------|-------------|
| `app.py` | Dash dashboard application |
| `etl_pipeline.py` | ETL pipeline — extracts, transforms, validates, and loads FRED data |
| `initial_load.py` | Week 2 initial load script (historical reference) |
| `macro_dashboard_snapshot.csv` | CSV snapshot of the analytics-ready dataset |
| `.env.example` | Environment variable template |
| `requirements.txt` | Python dependencies |

---

## Week 2 — Database Schema Documentation

See `Week2_Schema_Documentation.docx` for full database schema documentation including ER diagram, table structures, normalization notes, and data source descriptions.

---

*Built for MSBA 692 Pipelines to Insights — Summer 2026 — University of Louisville*
