Getting Started
===============

Overview
--------

This project is a Flask dashboard for **Grad Cafe applicant data**. It scrapes raw
records, cleans them with a local LLM service, loads them into PostgreSQL, and
displays SQL analysis results in the browser.

The end-to-end flow is:

1. **Scrape** raw applicant records (``src/module_2/scrape.py``)
2. **Clean** program and university names via a local LLM API
   (``src/module_2/clean.py`` + ``src/module_2/llm_hosting/``)
3. **Load** cleaned JSON into PostgreSQL (``src/load_data.py``)
4. **Query** the database for summary statistics (``src/query_data.py``)
5. **Display** results in a Flask dashboard (``src/app.py``)

Prerequisites
-------------

- **Python 3.11+**
- **PostgreSQL** installed and running
- **Google Chrome** (required by Selenium for scraping)
- For the full **Pull Data** pipeline: the **LLM hosting service** on port ``8080``

Project layout
--------------

.. code-block:: text

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
   ├── requirements.txt           # Full project dependencies
   └── pytest.ini

Setup
-----

Create and activate a virtual environment from the project root (``module_4/``):

**Windows (PowerShell):**

.. code-block:: powershell

   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt

**macOS / Linux:**

.. code-block:: bash

   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt

Environment variables
---------------------

Connection settings are read from environment variables via ``db_config.py``.

Option A — single connection URL (recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Windows (PowerShell):**

.. code-block:: powershell

   $env:DATABASE_URL = "postgresql://YOUR_USER@localhost:5432/applicant_db"

**macOS / Linux:**

.. code-block:: bash

   export DATABASE_URL="postgresql://YOUR_USER@localhost:5432/applicant_db"

Option B — individual variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Variable
     - Default
     - Description
   * - ``PGUSER`` or ``POSTGRES_USER``
     - ``postgres``
     - Database user
   * - ``PGHOST``
     - ``localhost``
     - Database host
   * - ``PGPORT``
     - ``5432``
     - Database port
   * - ``PGDATABASE``
     - ``applicant_db``
     - Database name

Additional variables used by other components:

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Variable
     - Used by
     - Purpose
   * - ``PG_CTL``
     - ``create_database.py``
     - Path to ``pg_ctl`` (Windows local startup)
   * - ``PGDATA``
     - ``create_database.py``
     - PostgreSQL data directory
   * - ``GRADCAFE_PROXY``
     - ``scrape.py``
     - Optional HTTP proxy for scraping
   * - ``HTTP_PROXY`` / ``HTTPS_PROXY``
     - ``scrape.py``
     - Standard proxy fallback
   * - ``PORT``
     - LLM hosting
     - LLM service port (default ``8080``)

Create the database
-------------------

Run once from ``src/`` to start local PostgreSQL (Windows only, when
``DATABASE_URL`` is not set) and create ``applicant_db``:

.. code-block:: powershell

   cd src
   python create_database.py

When ``DATABASE_URL`` is set, ``create_database.py`` skips local ``pg_ctl`` startup
and connects using your URL instead.

Run the Flask app
-----------------

.. code-block:: powershell

   cd src
   python app.py

The app starts at **http://127.0.0.1:8000**. Open **http://127.0.0.1:8000/analysis**
in your browser.

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Route
     - Method
     - Purpose
   * - ``/analysis``
     - GET
     - View analysis query results
   * - ``/pull-data``
     - POST
     - Run scrape → clean → load pipeline
   * - ``/update-analysis``
     - POST
     - Re-run analysis queries

Full Pull Data pipeline
~~~~~~~~~~~~~~~~~~~~~~~

The cleaner calls a local LLM service. Start it in a **separate terminal** before
using **Pull Data**:

.. code-block:: powershell

   cd src/module_2/llm_hosting
   pip install -r requirements.txt
   python app.py --serve

The LLM service listens on **http://127.0.0.1:8080** by default.

Run tests
---------

From the project root with the virtual environment activated:

.. code-block:: powershell

   python -m pytest -v

``pytest.ini`` enforces **100% code coverage** on ``src/``:

.. code-block:: ini

   addopts = -q --cov=src --cov-report=term-missing --cov-fail-under=100

Run a subset of tests by marker:

.. code-block:: powershell

   python -m pytest -v -m web          # Flask routes
   python -m pytest -v -m db           # Database tests (requires PostgreSQL)
   python -m pytest -v -m integration  # End-to-end flows

Database tests use the same ``DATABASE_URL`` / ``PG*`` environment variables
described above.

Build documentation
-------------------

Doc packages are included in the root ``requirements.txt``. To install docs only:

.. code-block:: powershell

   pip install -r docs/requirements.txt

**Windows (PowerShell):**

.. code-block:: powershell

   cd docs
   $env:SPHINXBUILD = "..\.venv\Scripts\sphinx-build.exe"
   .\make.bat html

**macOS / Linux / WSL:**

.. code-block:: bash

   cd docs
   make html

Open ``docs/build/html/index.html`` in a browser to view the generated site.

Typical workflow
----------------

1. Activate the virtual environment and set database environment variables.
2. Run ``python create_database.py`` from ``src/`` (first time only).
3. Start the LLM service (``python app.py --serve`` in ``src/module_2/llm_hosting/``).
4. Start the Flask app (``python app.py`` from ``src/``).
5. Open **http://127.0.0.1:8000/analysis**.
6. Click **Pull Data** to scrape, clean, and load new records.
7. Click **Update Analysis** (or refresh) to refresh displayed statistics.

Troubleshooting
---------------

**``role "postgres" does not exist``**
   Set ``PGUSER`` or ``DATABASE_URL`` to a valid PostgreSQL user on your machine.

**Flask starts but analysis page fails**
   Confirm PostgreSQL is running and ``applicant_db`` exists. Test with
   ``python query_data.py`` from ``src/``.

**Pull Data fails at clean step**
   Ensure the LLM hosting service is running on port ``8080``.

**Scraper fails behind a firewall**
   Set ``GRADCAFE_PROXY``, ``HTTP_PROXY``, or ``HTTPS_PROXY``.
