Architecture
============

This application is organized into three layers: **web**, **ETL**, and **database**.
``app.py`` orchestrates all three and serves as both the web front end and the
pipeline controller.

.. code-block:: text

   Browser (templates)
        │
        ▼
   ┌─────────────────────────────────────┐
   │  Web layer — app.py                 │
   │  GET /analysis, POST /pull-data,    │
   │  POST /update-analysis              │
   └──────────────┬──────────────────────┘
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
   ┌─────────────┐    ┌──────────────────┐
   │ ETL layer   │    │ Database layer   │
   │ scrape.py   │    │ db_config.py     │
   │ clean.py    │───▶│ load_data.py     │
   │ llm_hosting │    │ query_data.py    │
   └─────────────┘    │ create_database  │
                      └──────────────────┘

Web layer
---------

The web layer is implemented in ``app.py`` and ``src/templates/``.

**Responsibilities**

- Serve the analysis dashboard at ``GET /analysis``
- Trigger the full data pipeline at ``POST /pull-data``
- Re-run SQL analysis at ``POST /update-analysis``
- Manage concurrency with a pull-data lock so overlapping requests return HTTP 409

**Key modules**

- ``app.py`` — Flask application, route handlers, pipeline orchestration, watermark I/O
- ``templates/base.html`` — Navigation, Pull Data / Update Analysis buttons, client-side fetch logic
- ``templates/index.html`` — Renders query results as question/answer blocks

**Routes**

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Route
     - Method
     - Behavior
   * - ``/analysis``
     - GET
     - Opens a PostgreSQL connection, calls ``get_all_query_results()``, renders ``index.html``
   * - ``/pull-data``
     - POST
     - Runs scrape → clean → load; updates watermark; returns JSON status
   * - ``/update-analysis``
     - POST
     - Executes ``query_data.py``; returns JSON status

**Runtime flow**

1. User opens the dashboard — Flask queries PostgreSQL and renders current statistics.
2. User clicks **Pull Data** — the browser POSTs to ``/pull-data``; the server runs the ETL pipeline.
3. User clicks **Update Analysis** — the browser POSTs to ``/update-analysis``; the server refreshes query results.

ETL layer
---------

The ETL layer extracts raw applicant data, transforms it with an LLM, and loads it
into PostgreSQL. Each step is a standalone script invoked by ``app.py`` via
``subprocess``.

**Extract — ``module_2/scrape.py``**

- Scrapes The Grad Cafe using Selenium (requires Chrome)
- Writes raw JSON to ``json_files/applicant_data_updated.json``
- Supports incremental pulls via ``--min-added-on`` (driven by the watermark file)
- Optional proxy via ``GRADCAFE_PROXY``, ``HTTP_PROXY``, or ``HTTPS_PROXY``

**Transform — ``module_2/clean.py`` + ``module_2/llm_hosting/``**

- Reads raw JSON and calls the local LLM standardizer service (default port ``8080``)
- Normalizes program and university names into canonical fields
- Writes cleaned JSON to ``json_files/applicant_data_updated_cleaned.json``

**Load — ``load_data.py``**

- Reads JSON or JSONL input and normalizes records into a consistent schema
- Creates the target table if it does not exist
- Optionally deletes existing rows for a specific date before re-inserting
- Inserts rows with ``ON CONFLICT (url) DO NOTHING`` to prevent duplicates

**Pull Data pipeline (orchestrated by ``app.py``)**

1. Load watermark from ``json_files/pull_watermark.json``
2. Run ``scrape.py`` (with ``--min-added-on`` if a watermark exists)
3. Validate raw output; exit early if no new records
4. Run ``clean.py`` with ``--base-url http://127.0.0.1:8080``
5. Run ``load_data.py`` with ``--input`` and ``--table applicants``
6. Update watermark with the newest scraped date

**Intermediate files**

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - File
     - Purpose
   * - ``json_files/applicant_data_updated.json``
     - Raw scraped data
   * - ``json_files/applicant_data_updated_cleaned.json``
     - LLM-cleaned data ready for loading
   * - ``json_files/pull_watermark.json``
     - Incremental pull state (most recent date processed)

Database layer
--------------

The database layer handles connection management, schema creation, data loading,
and analytical queries.

**Connection — ``db_config.py``**

Centralizes PostgreSQL settings. All modules use ``get_database_url()``,
``get_connect_kwargs()``, or ``connect()`` to read from ``DATABASE_URL`` or
individual ``PG*`` environment variables.

**Schema creation — ``create_database.py``**

- Starts local PostgreSQL on Windows when ``DATABASE_URL`` is not set
- Creates the ``applicant_db`` database if it does not exist

**Data loading — ``load_data.py``**

Creates and populates the ``applicants`` table with columns including:

- ``p_id``, ``program``, ``comments``, ``date_added``, ``url`` (unique)
- ``status``, ``term``, ``us_or_international``
- ``gpa``, ``gre``, ``gre_v``, ``gre_aw``, ``degree``
- ``llm_generated_program``, ``llm_generated_university``, ``loaded_at``

**Analysis — ``query_data.py``**

- Defines business questions and SQL in ``question_query_dict``
- Executes queries via ``execute_query()`` and formats results for the Flask template
- Metrics include acceptance rates, GPA/GRE averages, international percentages, and program counts

**Design highlights**

- **Loose coupling** — Each pipeline step is an isolated script, making debugging easier.
- **Incremental loading** — The watermark avoids reprocessing all historical data.
- **Flexible JSON ingestion** — ``load_data.py`` handles multiple JSON layouts.
- **SQL-driven analysis** — New business questions are added by extending ``question_query_dict``.
