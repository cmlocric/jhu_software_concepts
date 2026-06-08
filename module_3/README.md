# Applicant Data Pipeline and Flask Dashboard

## Overview

This project builds a small end-to-end data application that:

1. Scrapes applicant data
2. Cleans and enriches the raw data (using a locally hosted LLM)
3. Loads the cleaned data into a PostgreSQL table
4. Queries the database for summary statistics
5. Displays the results in a Flask web application

The workflow is orchestrated by `app.py`, which serves as both the web front end and the controller for the data pipeline.

---

## Project Components

### `app.py`
This is the main Flask application. It does two jobs:

- serves the web interface
- triggers the data pipeline scripts

It defines three major application behaviors:

- `GET /` renders the dashboard page using query results from PostgreSQL
- `POST /pull-data` runs the scrape -> clean -> load pipeline
- `POST /update-analysis` reruns the query logic so the displayed analysis reflects the latest database contents

### `load_data.py`
This script loads cleaned applicant data from a JSON or JSONL file into PostgreSQL.

Its responsibilities include:

- reading either JSON or JSONL input
- normalizing records into a consistent list of dictionaries
- cleaning character encoding issues
- parsing numeric and date fields
- creating the target table if it does not already exist
- optionally deleting existing rows for a specific date before re-inserting
- inserting all processed rows into the `applicants` table

### `query_data.py`
This script contains the SQL analysis layer.

It:

- connects to the `applicant_db` PostgreSQL database
- defines a reusable `execute_query()` function
- stores business questions and SQL statements in `question_query_dict`
- runs all queries and formats their results
- returns those results to `app.py` for rendering in the Flask UI

---

## End-to-End Process

### 1. User opens the Flask app
When `app.py` runs, Flask starts on:

- `http://0.0.0.0:8000`

The `/` route:

- opens a PostgreSQL connection
- calls `get_all_query_results(connection)` from `query_data.py`
- passes the query results into `index.html`
- renders the results in the browser

### 2. User triggers `Pull Data`
When the `/pull-data` route is called, `app.py` executes the full ETL-style pipeline.

#### Step 2.1: Load the watermark
`app.py` checks `json_files/pull_watermark.json` to see the most recent `min_added_on` value.

This watermark is used to avoid pulling older records again.

- If the watermark file does not exist, the app performs a full pull.
- If it exists, the saved date is passed to the scraper with `--min-added-on`.

#### Step 2.2: Run the scraper
`app.py` runs:

- `module_2/scrape.py`

The scraper writes raw results to:

- `json_files/applicant_data_updated.json`

If a watermark exists, the scraper is called with:

- `--min-added-on <saved date>`

This means only newer or relevant records should be pulled.

#### Step 2.3: Validate raw output
After scraping, `app.py` reads the raw JSON output.

- If no records are returned, the route responds with a success message saying no new records were found.
- If records do exist, the pipeline continues.

#### Step 2.4: Run the cleaner
`app.py` next runs:

- `module_2/clean.py`

Input:
- `json_files/applicant_data_updated.json`

Output:
- `json_files/applicant_data_updated_cleaned.json`

Additional argument:
- `--base-url http://127.0.0.1:8080`

Before cleaning starts, the app deletes any previous cleaned output file and progress file so the clean step starts fresh.

#### Step 2.5: Load into PostgreSQL
After cleaning succeeds, `app.py` runs:

- `load_data.py`

It passes:

- `--input <cleaned json path>`
- `--table applicants`

If a saved watermark exists, it also passes:

- `--delete-date <saved watermark>`

This helps prevent duplicate rows for that date by deleting existing rows for the matching `date_added` before inserting refreshed data.

#### Step 2.6: Update the watermark
After the load completes, `app.py` scans the raw JSON data to find the newest `Date of Information Added to Grad Cafe` value.

That date is saved back to:

- `json_files/pull_watermark.json`

This becomes the watermark for the next incremental pull.

---

## Database Load Process

`load_data.py` is responsible for translating cleaned JSON into relational data.

### Input handling
The script supports:

- regular JSON
- JSONL

It attempts to parse the whole file as JSON first.
If that fails, it falls back to line-by-line JSONL parsing.

### Record normalization
The loader supports several shapes of JSON input:

- a list of dictionaries
- a dictionary containing a `rows` list
- a dictionary with one list-valued field
- a single dictionary record

All valid records are normalized into a list of dictionaries before loading.

### Data cleaning
The script includes helper functions to:

- remove unsupported characters with `cp1252` encoding cleanup
- parse numeric values like GPA and GRE scores into floats
- parse dates like `August 15, 2025` into PostgreSQL `date` values

### Table creation
If the table does not already exist, the script creates `applicants` with the following columns:

- `p_id`
- `program`
- `comments`
- `date_added`
- `url`
- `status`
- `term`
- `us_or_international`
- `gpa`
- `gre`
- `gre_v`
- `gre_aw`
- `degree`
- `llm_generated_program`
- `llm_generated_university`
- `loaded_at`

### Insert behavior
For each JSON row, the loader maps various possible field names into the target schema.

Examples:

- program fields map into `program`
- `Date of Information Added to Grad Cafe` maps into `date_added`
- GPA and GRE-related fields are parsed into numeric columns
- LLM-enriched fields map into `llm_generated_program` and `llm_generated_university`

Rows are then inserted into PostgreSQL using `executemany()`.

---

## Query and Analysis Process

`query_data.py` contains the analytical layer for the app.

### How it works
1. Open a PostgreSQL connection to `applicant_db`
2. Loop through all SQL queries stored in `question_query_dict`
3. Execute each query
4. Format the result into a Python-friendly structure
5. Return a list of `(question, answer)` pairs
6. Send those pairs back to Flask for rendering

### Types of questions answered
The queries calculate metrics such as:

- total Fall 2026 applicants
- percentage of international applicants
- average GPA and GRE metrics
- acceptance rate for Fall 2026
- average GPA for accepted applicants
- counts for specific schools and degree programs
- comparison of downloaded fields versus LLM-generated fields
- acceptance rate by applicant type
- universities with the highest Computer Science acceptance counts

### Result formatting
The helper function `execute_query()` converts PostgreSQL results into cleaner Python values:

- single scalar values become a simple value
- one-row results become tuples
- one-column multi-row results become lists
- multi-row multi-column results become lists of tuples
- `Decimal` values are converted to `float`

This makes the results easier to render in the Flask template.

---

## Flask Routes Summary

### `/`
Purpose:
- display query results in the web app

What happens:
- connect to PostgreSQL
- run all analysis queries
- render `index.html`

### `/pull-data`
Purpose:
- refresh the full data pipeline

What happens:
- load watermark
- run scraper
- read raw JSON
- run cleaner
- load cleaned data into PostgreSQL
- update watermark
- return JSON success or error response

### `/update-analysis`
Purpose:
- rerun the SQL analysis layer

What happens:
- execute `query_data.py`
- return success or failure as JSON

---

## Expected Runtime Flow

A typical usage sequence looks like this:

1. Start PostgreSQL
2. Start the Flask app with `python app.py`
3. Open the web interface in a browser
4. Trigger `Pull Data`
5. Scrape, clean, and load records into PostgreSQL
6. Trigger `Update Analysis` or refresh the page
7. View updated metrics and query results in the Flask dashboard

---

## Setup Requirements

To run this project successfully, you need:

- Python with the required packages installed
- PostgreSQL running locally
- a PostgreSQL database named `applicant_db`
- a PostgreSQL user named `postgres`
- Flask
- psycopg
- the supporting scripts:
  - `module_2/scrape.py`
  - `module_2/clean.py`
- a Flask template file such as `templates/index.html`

Example package install:

```bash
pip install flask psycopg
```

---

## Important Files Produced During Execution

### Raw scraped data
- `json_files/applicant_data_updated.json`

### Cleaned data
- `json_files/applicant_data_updated_cleaned.json`

### Watermark state
- `json_files/pull_watermark.json`

These files allow the app to:

- preserve intermediate outputs
- support incremental pulls
- reload or inspect the pipeline state

---

## Notes and Design Highlights

### Incremental loading
The watermark mechanism is a useful design choice because it avoids reprocessing all historical data every time.

### Loose coupling between steps
Each major step is isolated into its own script:

- scrape
- clean
- load
- query
- render

That makes the workflow easier to debug and maintain.

### Flexible JSON ingestion
`load_data.py` can handle multiple JSON layouts, which makes the pipeline more robust when upstream output formats vary.

### SQL-driven analysis
The business questions are easy to extend because they are centralized in a single dictionary in `query_data.py`.

---

## Example Commands

### Start PostgreSQL
Use your local PostgreSQL start command.

### Run the Flask app
```bash
python app.py
```

### Run the loader directly
```bash
python load_data.py --input json_files/applicant_data_updated_cleaned.json --table applicants
```

### Run the query script directly
```bash
python query_data.py
```

---

## In Summary

This application is a complete mini data pipeline and simple dashboard:

- `app.py` orchestrates the workflow and serves the front end
- `load_data.py` loads cleaned applicant data into PostgreSQL
- `query_data.py` analyzes the database contents
- Flask displays the query results in the browser

The overall flow is:

run Flask app displaying initial SQL results -> on button press scrape data -> clean data -> load into PostgreSQL -> on button press run updated SQL analysis -> render updated results in Flask
