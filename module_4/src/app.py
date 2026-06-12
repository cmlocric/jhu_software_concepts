import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock

import psycopg
from flask import Flask, jsonify, render_template

from query_data import get_all_query_results
from create_database import start_postgres

BASE_DIR = Path(__file__).resolve().parent
SCRAPE_SCRIPT = BASE_DIR / "module_2" / "scrape.py"
CLEAN_SCRIPT = BASE_DIR / "module_2" / "clean.py"
LOAD_SCRIPT = BASE_DIR / "load_data.py"

RAW_JSON_OUTPUT = BASE_DIR / "json_files" / "applicant_data_updated.json"
CLEAN_JSON_OUTPUT = BASE_DIR / "json_files" / "applicant_data_updated_cleaned.json"
WATERMARK_FILE = BASE_DIR / "json_files" / "pull_watermark.json"
QUERY_SCRIPT = BASE_DIR / "query_data.py"

pull_data_running = False
pull_data_lock = Lock()

def get_database_url() -> str:
    """Return the PostgreSQL connection URL for the Flask app.

    :returns: ``DATABASE_URL`` environment variable, or a local default.
    :rtype: str
    """
    return os.environ.get("DATABASE_URL", "postgresql://postgres@localhost/applicant_db")

def try_start_pull_data() -> bool:
    """Attempt to acquire the pull-data lock.

    :returns: ``True`` if the lock was acquired; ``False`` if a pull is
        already in progress.
    :rtype: bool
    """
    global pull_data_running
    with pull_data_lock:
        if pull_data_running:
            return False
        pull_data_running = True
        return True

def finish_pull_data() -> None:
    """Release the pull-data lock after a scrape/load run completes.

    :returns: ``None``
    :rtype: None
    """
    global pull_data_running
    with pull_data_lock:
        pull_data_running = False

def is_pull_data_running() -> bool:
    """Check whether a pull-data job is currently in progress.

    :returns: ``True`` if pull data is running.
    :rtype: bool
    """
    with pull_data_lock:
        return pull_data_running

def get_db_connection(dbname=None, user=None):
    """Open a PostgreSQL connection using URL or explicit credentials.

    :param dbname: Optional database name override.
    :type dbname: str | None
    :param user: Optional database user override.
    :type user: str | None
    :returns: Active psycopg connection.
    :rtype: psycopg.Connection
    """
    if dbname is not None or user is not None:
        kwargs = {}
        if dbname is not None:
            kwargs["dbname"] = dbname
        if user is not None:
            kwargs["user"] = user
        return psycopg.connect(**kwargs)
    return psycopg.connect(get_database_url())

def run_python_script(script_path: Path, *args: str):
    """Run a Python script as a subprocess and capture its output.

    :param script_path: Path to the script to execute.
    :type script_path: pathlib.Path
    :param args: Additional command-line arguments.
    :type args: str
    :returns: Completed subprocess result.
    :rtype: subprocess.CompletedProcess
    """
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
    )

def load_watermark() -> str | None:
    """Load the saved minimum ``added_on`` date from the watermark file.

    :returns: ISO date string (``YYYY-MM-DD``), or ``None`` if missing.
    :rtype: str | None
    """
    if not WATERMARK_FILE.exists():
        return None
    with open(WATERMARK_FILE, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("min_added_on")

def save_watermark(value: str) -> None:
    """Persist the latest ``added_on`` date to the watermark file.

    :param value: ISO date string (``YYYY-MM-DD``) to store.
    :type value: str
    :returns: ``None``
    :rtype: None
    """
    WATERMARK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(WATERMARK_FILE, "w", encoding="utf-8") as f:
        json.dump({"min_added_on": value}, f, indent=2)

def parse_added_on_date(value: str):
    """Parse a Grad Cafe ``added_on`` date string.

    :param value: Date string in long or abbreviated month format.
    :type value: str
    :returns: Parsed date, or ``None`` if empty or unparseable.
    :rtype: datetime.date | None
    """
    if not value:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None

def read_json_records(path: Path):
    """Read applicant records from a JSON file.

    :param path: Path to a JSON file containing a list or ``{"rows": [...]}``.
    :type path: pathlib.Path
    :returns: List of record dictionaries; empty list if file is missing.
    :rtype: list[dict]
    """
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload["rows"]
    return []

def get_latest_added_on(path: Path) -> str | None:
    """Find the most recent ``added_on`` date in a JSON record file.

    :param path: Path to the JSON record file.
    :type path: pathlib.Path
    :returns: Latest date as ``YYYY-MM-DD``, or ``None`` if none found.
    :rtype: str | None
    """
    records = read_json_records(path)
    dates = []
    for row in records:
        parsed = parse_added_on_date(row.get("Date of Information Added to Grad Cafe", ""))
        if parsed is not None:
            dates.append(parsed)
    if not dates:
        return None
    return max(dates).strftime("%Y-%m-%d")

def format_analysis_value(value):
    """Format query result values for HTML display.

    :param value: Scalar, tuple, or list from a query result.
    :type value: object
    :returns: Formatted value with floats rounded to two decimal places.
    :rtype: object
    """
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, tuple):
        return tuple(format_analysis_value(v) for v in value)
    if isinstance(value, list):
        return [format_analysis_value(v) for v in value]
    return value

def create_app(test_config=None):
    """Create and configure the Flask application.

    :param test_config: Optional dict of Flask config overrides for testing.
    :type test_config: dict | None
    :returns: Configured Flask app with analysis and data-pull routes.
    :rtype: flask.Flask
    """
    if "sphinx" not in sys.modules:
        start_postgres()

    app = Flask(__name__)
    if test_config:
        app.config.update(test_config)

    @app.route("/analysis")
    def index():
        """Render the analysis page with all query results.

        :returns: Rendered ``index.html`` template with query results.
        :rtype: str
        """
        connection = get_db_connection(dbname="applicant_db", user="postgres")
        try:
            query_results = get_all_query_results(connection)
            query_results = [
                (question, format_analysis_value(answer))
                for question, answer in query_results
            ]
            return render_template("index.html", query_results=query_results)
        finally:
            connection.close()

    @app.post("/pull-data")
    def pull_data():
        """Run scrape, clean, and load pipeline to refresh applicant data.

        :returns: JSON response indicating success, busy state, or error.
        :rtype: flask.Response
        """
        if not try_start_pull_data():
            return jsonify(
                ok=False,
                busy=True,
                error="Pull Data is already in progress.",
            ), 409

        try:
            RAW_JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)

            saved_watermark = load_watermark()

            scrape_args = ["--output", str(RAW_JSON_OUTPUT)]
            if saved_watermark:
                scrape_args.extend(["--min-added-on", saved_watermark])

            scrape_result = run_python_script(SCRAPE_SCRIPT, *scrape_args)
            if scrape_result.returncode != 0:
                return jsonify(
                    ok=False,
                    busy=False,
                    error=scrape_result.stderr or scrape_result.stdout or "scrape.py failed",
                ), 500

            raw_records = read_json_records(RAW_JSON_OUTPUT)
            if not raw_records:
                return jsonify(
                    ok=True,
                    busy=False,
                    message="Pull Data completed successfully. No new records found.",
                )

            clean_progress = Path(f"{CLEAN_JSON_OUTPUT}.progress.json")
            if CLEAN_JSON_OUTPUT.exists():
                CLEAN_JSON_OUTPUT.unlink()
            if clean_progress.exists():
                clean_progress.unlink()

            clean_result = run_python_script(
                CLEAN_SCRIPT,
                str(RAW_JSON_OUTPUT),
                str(CLEAN_JSON_OUTPUT),
                "--base-url",
                "http://127.0.0.1:8080",
            )
            if clean_result.returncode != 0:
                return jsonify(
                    ok=False,
                    busy=False,
                    error=clean_result.stderr or clean_result.stdout or "clean.py failed",
                ), 500

            load_args = [
                "--input", str(CLEAN_JSON_OUTPUT),
                "--table", "applicants",
            ]
            if saved_watermark:
                load_args.extend(["--delete-date", saved_watermark])

            load_result = run_python_script(LOAD_SCRIPT, *load_args)
            if load_result.returncode != 0:
                return jsonify(
                    ok=False,
                    busy=False,
                    error=load_result.stderr or load_result.stdout or "load_data.py failed",
                ), 500

            latest_added_on = get_latest_added_on(RAW_JSON_OUTPUT)
            if latest_added_on:
                save_watermark(latest_added_on)

            return jsonify(
                ok=True,
                busy=False,
                message="Pull Data completed successfully",
            )
        finally:
            finish_pull_data()

    @app.post("/update-analysis")
    def update_analysis():
        """Re-run analysis queries by executing ``query_data.py``.

        :returns: JSON response indicating success, busy state, or error.
        :rtype: flask.Response
        """
        if is_pull_data_running():
            return jsonify(
                ok=False,
                busy=True,
                error="Update Analysis is unavailable while Pull Data is running.",
            ), 409

        query_result = run_python_script(QUERY_SCRIPT)
        if query_result.returncode != 0:
            return jsonify(
                ok=False,
                busy=False,
                error=query_result.stderr or query_result.stdout or "query_data.py failed",
            ), 500

        return jsonify(
            ok=True,
            busy=False,
            message="Analysis updated successfully",
        )

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)