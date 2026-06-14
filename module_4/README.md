# Module 4 — Grad Cafe Applicant Data Pipeline

Flask web application that scrapes applicant data from The Grad Cafe, cleans and enriches it with a local LLM, loads it into PostgreSQL, and displays SQL analysis results in the browser.

## What this project does

1. **Scrape** raw applicant records (`src/module_2/scrape.py`)
2. **Clean** program/university names via a local LLM API (`src/module_2/clean.py` + `src/module_2/llm_hosting/`)
3. **Load** cleaned JSON into PostgreSQL (`src/load_data.py`)
4. **Query** the database for summary statistics (`src/query_data.py`)
5. **Display** results in a Flask dashboard (`src/app.py`)

## Project layout

```
module_4/
├── src/
│   ├── app.py                 # Flask app and pipeline orchestration
│   ├── create_database.py     # Start PostgreSQL (local) and create applicant_db
│   ├── db_config.py           # Shared database connection settings
│   ├── load_data.py           # JSON/JSONL → PostgreSQL loader
│   ├── query_data.py          # Analysis SQL queries
│   ├── json_files/            # Scraped, cleaned, and watermark files
│   ├── templates/             # Flask HTML templates
│   └── module_2/
│       ├── scrape.py          # Grad Cafe scraper
│       ├── clean.py           # Batch cleaner (calls LLM service)
│       └── llm_hosting/       # Local LLM standardizer service
├── tests/                     # Pytest suite (100% coverage required)
├── docs/                      # Sphinx documentation
├── requirements.txt           # Full project dependencies (app + tests + docs)
└── pytest.ini
```

## Prerequisites

- **Python 3.11+** (3.14 tested)
- **PostgreSQL** installed and running
- **Google Chrome** (required by Selenium for scraping)
- **Git** (optional, for cloning)

For the full **Pull Data** pipeline you also need the **LLM hosting service** running on port `8080` (see below).

---

## 1. Set up Python

From the project root (`module_4/`):

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

All commands below assume your virtual environment is activated and you are in the `module_4/` directory unless noted.

---

## 2. Configure PostgreSQL

Connection settings are read from environment variables via `src/db_config.py`. You do **not** need a user named `postgres` if you configure alternatives below.

### Option A — single connection URL (recommended)

```powershell
$env:DATABASE_URL = "postgresql://YOUR_USER@localhost:5432/applicant_db"
```

```bash
export DATABASE_URL="postgresql://YOUR_USER@localhost:5432/applicant_db"
```

### Option B — individual variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PGUSER` or `POSTGRES_USER` | `postgres` | Database user |
| `PGHOST` | `localhost` | Database host |
| `PGPORT` | `5432` | Database port |
| `PGDATABASE` | `applicant_db` | Database name |

Example (PowerShell):

```powershell
$env:PGUSER = "your_username"
$env:PGDATABASE = "applicant_db"
```

### Create the database

Run once to start local PostgreSQL (Windows only, when `DATABASE_URL` is not set) and create `applicant_db`:

```powershell
cd src
python create_database.py
```

On Windows, local PostgreSQL paths can be overridden:

```powershell
$env:PG_CTL = "C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe"
$env:PGDATA = "C:\PostgreSQL\18\data"
```

When `DATABASE_URL` is set, `create_database.py` skips local `pg_ctl` startup and connects using your URL instead.

### Load sample data manually (optional)

```powershell
cd src
python load_data.py --input json_files/applicant_data_updated_cleaned.json --table applicants
```

Duplicate rows are prevented by a unique constraint on `url` with `ON CONFLICT (url) DO NOTHING`.

---

## 3. Run the Flask app

```powershell
cd src
python app.py
```

The app starts at **http://127.0.0.1:8000**.

| Route | Method | Purpose |
|-------|--------|---------|
| `/analysis` | GET | View analysis query results |
| `/pull-data` | POST | Run scrape → clean → load pipeline |
| `/update-analysis` | POST | Re-run analysis queries |

Open **http://127.0.0.1:8000/analysis** in your browser.

### Full Pull Data pipeline (scrape + clean + load)

The cleaner calls a local LLM service. Start it in a **separate terminal** before using **Pull Data**:

```powershell
cd src/module_2/llm_hosting
pip install -r requirements.txt
python app.py --serve
```

The LLM service listens on **http://127.0.0.1:8080** by default.

Optional scraper proxy (corporate network):

```powershell
$env:GRADCAFE_PROXY = "http://your-proxy:8080"
# or use standard HTTP_PROXY / HTTPS_PROXY
```

Then use the **Pull Data** button on the analysis page, or:

```powershell
curl -X POST http://127.0.0.1:8000/pull-data
```

---

## 4. Run tests

From the project root with the virtual environment activated:

```powershell
python -m pytest -v
```

`pytest.ini` enforces **100% code coverage** on `src/`:

```ini
addopts = -q --cov=src --cov-report=term-missing --cov-fail-under=100
```

Run a subset of tests by marker:

```powershell
python -m pytest -v -m web          # Flask routes
python -m pytest -v -m db           # Database tests (requires PostgreSQL)
python -m pytest -v -m integration  # End-to-end flows
```

Database tests connect using the same `DATABASE_URL` / `PG*` environment variables described above.

---

## 5. Build and view documentation

Documentation is generated with **Sphinx** from `docs/source/`.

### Install doc dependencies

Doc packages are included in the root `requirements.txt`. To install docs only:

```powershell
pip install -r docs/requirements.txt
```

### Build HTML docs

**Windows (PowerShell):**

```powershell
cd docs
$env:SPHINXBUILD = "..\.venv\Scripts\sphinx-build.exe"   # adjust if needed
.\make.bat html
```

**macOS / Linux / WSL:**

```bash
cd docs
make html
```

### View the docs

Open the generated site in a browser:

```
docs/build/html/index.html
```

The docs use `sphinx.ext.autodoc` to document `app`, `query_data`, `create_database`, and `load_data`.

---

## Environment variables reference

| Variable | Used by | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | All DB modules | Full PostgreSQL connection string |
| `PGUSER` / `POSTGRES_USER` | `db_config.py` | Database username |
| `PGHOST` | `db_config.py` | Database host |
| `PGPORT` | `db_config.py` | Database port |
| `PGDATABASE` | `db_config.py` | Database name |
| `PG_CTL` | `create_database.py` | Path to `pg_ctl` (Windows) |
| `PGDATA` | `create_database.py` | PostgreSQL data directory |
| `GRADCAFE_PROXY` | `scrape.py` | Optional HTTP proxy for scraping |
| `HTTP_PROXY` / `HTTPS_PROXY` | `scrape.py` | Standard proxy fallback |
| `PORT` | LLM hosting | LLM service port (default `8080`) |

---

## Typical workflow

1. Activate the virtual environment and set database environment variables.
2. Run `python create_database.py` from `src/` (first time only).
3. Start the LLM service (`python app.py --serve` in `src/module_2/llm_hosting/`).
4. Start the Flask app (`python app.py` from `src/`).
5. Open **http://127.0.0.1:8000/analysis**.
6. Click **Pull Data** to scrape, clean, and load new records.
7. Click **Update Analysis** (or refresh) to refresh displayed statistics.

---

## Troubleshooting

**`role "postgres" does not exist`**  
Set `PGUSER` or `DATABASE_URL` to a valid PostgreSQL user on your machine.

**Flask starts but analysis page fails**  
Confirm PostgreSQL is running and `applicant_db` exists. Test with:

```powershell
cd src
python query_data.py
```

**Pull Data fails at clean step**  
Ensure the LLM hosting service is running on port `8080`.

**Scraper fails behind a firewall**  
Set `GRADCAFE_PROXY`, `HTTP_PROXY`, or `HTTPS_PROXY`.

**`./make html` not found on Windows**  
Use `.\make.bat html` from the `docs/` folder instead.

---

## Additional documentation

- Pipeline details: [`src/README.md`](src/README.md)
- Module 2 scraper/cleaner notes: [`src/module_2/README.md`](src/module_2/README.md)
