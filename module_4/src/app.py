import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock

import psycopg
from flask import Flask, jsonify, render_template

from query_data import get_all_query_results
from create_database import start_postgres

# Start server if not started.
start_postgres()

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
SCRAPE_SCRIPT = BASE_DIR / "module_2" / "scrape.py"
CLEAN_SCRIPT = BASE_DIR / "module_2" / "clean.py"
LOAD_SCRIPT = BASE_DIR / "load_data.py"

RAW_JSON_OUTPUT = BASE_DIR / "json_files" / "applicant_data_updated.json"
CLEAN_JSON_OUTPUT = BASE_DIR / "json_files" / "applicant_data_updated_cleaned.json"
WATERMARK_FILE = BASE_DIR / "json_files" / "pull_watermark.json"
QUERY_SCRIPT = BASE_DIR / "query_data.py"

# Track whether a pull-data request is currently running on the server.
#
# This is needed because the "busy" logic in base.html only disables buttons
# in the browser. That helps normal users, but it does not protect the Flask
# routes themselves. A direct HTTP request could still hit the endpoint while a
# pull is already running unless we also enforce the rule on the backend.

pull_data_running = False

# Use a lock so checking/updating the busy flag is thread-safe.
#
# Without this, two requests arriving at almost the same time could both see
# pull_data_running == False and both start work. The lock ensures that the
# check-and-set happens as one protected operation.
pull_data_lock = Lock()

def try_start_pull_data() -> bool:
    """Attempt to mark pull-data as running."""
    global pull_data_running

    # Lock around the read/update so only one request can claim the job.
    with pull_data_lock:
        # If a pull is already running, reject the new request.
        if pull_data_running:
            return False

        # Mark the app as busy with pull-data.
        pull_data_running = True
        return True

def finish_pull_data() -> None:
    """Clear the server-side pull-data busy flag."""
    global pull_data_running

    # Reset the busy flag under the same lock for consistency.
    with pull_data_lock:
        pull_data_running = False

def is_pull_data_running() -> bool:
    """Return whether a pull-data job is currently running."""
    # Read the busy flag under the lock so the check is safe.
    with pull_data_lock:
        return pull_data_running

def get_db_connection(dbname, user):
    connection = psycopg.connect(
        dbname=dbname,
        user=user,
    )
    return connection

def run_python_script(script_path: Path, *args: str):
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
    )

def load_watermark() -> str | None:
    if not WATERMARK_FILE.exists():
        return None

    with open(WATERMARK_FILE, "r", encoding="utf-8") as f:
        payload = json.load(f)

    return payload.get("min_added_on")

def save_watermark(value: str) -> None:
    WATERMARK_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(WATERMARK_FILE, "w", encoding="utf-8") as f:
        json.dump({"min_added_on": value}, f, indent=2)

def parse_added_on_date(value: str):
    if not value:
        return None

    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    return None

def read_json_records(path: Path):
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
    records = read_json_records(path)

    dates = []
    for row in records:
        parsed = parse_added_on_date(row.get("Date of Information Added to Grad Cafe", ""))
        if parsed is not None:
            dates.append(parsed)

    if not dates:
        return None

    return max(dates).strftime("%Y-%m-%d")

@app.route("/")
def index():
    connection = get_db_connection(dbname="applicant_db", user="postgres")
    try:
        query_results = get_all_query_results(connection)
        return render_template("index.html", query_results=query_results)
    finally:
        connection.close()

@app.post("/pull-data")
def pull_data():
    # Reject a new pull request if one is already running.
    #
    # This gives the backend the same "wait until done" behavior that the UI
    # tries to enforce with disabled buttons, and it allows the busy-state unit
    # tests to verify real server behavior instead of only browser behavior.
    if not try_start_pull_data():
        return jsonify(
            ok=False,
            error="Pull Data is already in progress.",
        ), 409

    try:
        RAW_JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)

        saved_watermark = load_watermark()

        scrape_args = [
            "--output",
            str(RAW_JSON_OUTPUT),
        ]

        if saved_watermark:
            scrape_args.extend([
                "--min-added-on",
                saved_watermark,
            ])

        scrape_result = run_python_script(
            SCRAPE_SCRIPT,
            *scrape_args,
        )

        if scrape_result.returncode != 0:
            return jsonify(
                ok=False,
                error=scrape_result.stderr or scrape_result.stdout or "scrape.py failed",
            ), 500

        raw_records = read_json_records(RAW_JSON_OUTPUT)
        if not raw_records:
            return jsonify(
                ok=True,
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
                error=clean_result.stderr or clean_result.stdout or "clean.py failed",
            ), 500

        load_args = [
            "--input",
            str(CLEAN_JSON_OUTPUT),
            "--table",
            "applicants",
        ]

        if saved_watermark:
            load_args.extend([
                "--delete-date",
                saved_watermark,
            ])

        load_result = run_python_script(
            LOAD_SCRIPT,
            *load_args,
        )

        if load_result.returncode != 0:
            return jsonify(
                ok=False,
                error=load_result.stderr or load_result.stdout or "load_data.py failed",
            ), 500

        latest_added_on = get_latest_added_on(RAW_JSON_OUTPUT)
        if latest_added_on:
            save_watermark(latest_added_on)

        return jsonify(
            ok=True,
            message="Pull Data completed successfully",
        )
    finally:
        # Always clear the busy flag when the request finishes.
        #
        # Putting this in finally is important: even if scrape/clean/load fails,
        # the app should not stay stuck forever in a "busy" state.
        finish_pull_data()

@app.post("/update-analysis")
def update_analysis():
    # Block analysis updates while pull-data is running.
    #
    # This mirrors the front-end behavior in base.html where the Update Analysis
    # button is disabled during a pull. Enforcing the same rule on the server
    # makes it reliable even if the route is called directly.
    if is_pull_data_running():
        return jsonify(
            ok=False,
            error="Update Analysis is unavailable while Pull Data is running.",
        ), 409

    query_result = run_python_script(QUERY_SCRIPT)

    if query_result.returncode != 0:
        return jsonify(
            ok=False,
            error=query_result.stderr or query_result.stdout or "query_data.py failed",
        ), 500

    return jsonify(
        ok=True,
        message="Analysis updated successfully",
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)