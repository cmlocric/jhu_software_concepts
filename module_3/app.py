import psycopg
import json
from flask import Flask, render_template, jsonify
import sys
import subprocess
from pathlib import Path
from datetime import datetime

from query_data import get_all_query_results

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
SCRAPE_SCRIPT = BASE_DIR / "module_2\scrape.py"
CLEAN_SCRIPT  = BASE_DIR / "module_2\clean.py"
LOAD_SCRIPT = BASE_DIR / "load_data.py"

RAW_JSON_OUTPUT = BASE_DIR / "json_files" / "applicant_data_updated.json"
CLEAN_JSON_OUTPUT = BASE_DIR / "json_files" / "applicant_data_updated_cleaned.json"
WATERMARK_FILE = BASE_DIR / "json_files" / "pull_watermark.json"

def get_db_connection(dbname, user):
    connection = psycopg.connect(
        dbname=dbname,
        user=user
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

@app.route('/')
def index():
    connection = get_db_connection(dbname="applicant_db", user="postgres")
    try:
        query_results = get_all_query_results(connection)

        return render_template(
            'index.html',
            query_results=query_results
        )
    finally:
        connection.close()

@app.post("/pull-data")
def pull_data():
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

@app.route('/update-analysis')
def update_analysis():
    return "Update Analysis page"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)