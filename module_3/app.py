import psycopg
from flask import Flask, render_template, jsonify
from query_data import get_all_query_results
import sys
import subprocess
from pathlib import Path

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
SCRAPE_SCRIPT = r"C:\Users\hz98yb\Training_Files\jhu_software_concepts\module_3\module_2\scrape.py"
CLEAN_SCRIPT  = r"C:\Users\hz98yb\Training_Files\jhu_software_concepts\module_3\module_2\clean.py"
LOAD_SCRIPT = BASE_DIR / "load_data.py"

RAW_JSON_OUTPUT = BASE_DIR / "json_files" / "applicant_data_updated.json"
CLEAN_JSON_OUTPUT = BASE_DIR / "json_files" / "applicant_data_updated_cleaned.json"


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

    scrape_result = run_python_script(
        SCRAPE_SCRIPT,
        "--output",
        str(RAW_JSON_OUTPUT),
    )

    print("SCRAPE STDOUT:", scrape_result.stdout)
    print("SCRAPE STDERR:", scrape_result.stderr)

    if scrape_result.returncode != 0:
        return jsonify(
            ok=False,
            error=scrape_result.stderr or scrape_result.stdout or "scrape.py failed",
        ), 500

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

    print("CLEAN STDOUT:", clean_result.stdout)
    print("CLEAN STDERR:", clean_result.stderr)

    if clean_result.returncode != 0:
        return jsonify(
            ok=False,
            error=clean_result.stderr or clean_result.stdout or "clean.py failed",
        ), 500

    load_result = run_python_script(
        LOAD_SCRIPT,
        "--input",
        str(CLEAN_JSON_OUTPUT),
        "--table",
        "applicants",
    )

    print("LOAD STDOUT:", load_result.stdout)
    print("LOAD STDERR:", load_result.stderr)

    if load_result.returncode != 0:
        return jsonify(
            ok=False,
            error=load_result.stderr or load_result.stdout or "load_data.py failed",
        ), 500

    return jsonify(
        ok=True,
        message="Pull Data completed successfully",
    )

@app.route('/update-analysis')
def update_analysis():
    return "Update Analysis page"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
