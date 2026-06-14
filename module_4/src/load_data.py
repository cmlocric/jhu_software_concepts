# This script reads a JSON or JSONL file and loads its contents into a PostgreSQL database.
# ========================================================================================
# Start sever and connect to database using psql command line tool -bash
#"/c/Program Files/PostgreSQL/18/bin/pg_ctl.exe" start -D "C:\PostgreSQL\18\data"
#"/c/Program Files/PostgreSQL/18/bin/psql.exe" -U postgres -h localhost -d studentcourses
# ========================================================================================
import argparse
import json
from datetime import datetime
from pathlib import Path
import psycopg

from db_config import get_connect_kwargs

SRC_DIR = Path(__file__).resolve().parent
DEFAULT_JSON_FILE = str(SRC_DIR / "json_files" / "applicant_data_updated_cleaned.json")
DEFAULT_TABLE_NAME = "applicants"

def clean_obj(obj):
    """Recursively normalize string encoding in nested JSON structures.

    :param obj: JSON-compatible value (dict, list, str, or scalar).
    :type obj: object
    :returns: Copy of ``obj`` with strings re-encoded via cp1252.
    :rtype: object
    """
    if isinstance(obj, dict):
        return {k: clean_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_obj(v) for v in obj]
    if isinstance(obj, str):
        return obj.encode("cp1252", errors="ignore").decode("cp1252")
    return obj

def parse_float(value):
    """Parse a value as a float, returning ``None`` on failure.

    :param value: Raw field value from a JSON record.
    :type value: object
    :returns: Parsed float, or ``None`` if empty or invalid.
    :rtype: float | None
    """
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def parse_date(value):
    """Parse a date string in ``"%B %d, %Y"`` format.

    :param value: Date string (e.g. ``"June 12, 2026"``).
    :type value: object
    :returns: Parsed date, or ``None`` if empty or invalid.
    :rtype: datetime.date | None
    """
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(value, "%B %d, %Y").date()
    except ValueError:
        return None

def normalize_records(parsed):
    """Convert parsed JSON into a flat list of cleaned record dicts.

    :param parsed: Top-level JSON object or list from a file.
    :type parsed: dict | list
    :returns: List of applicant record dictionaries.
    :rtype: list[dict]
    :raises TypeError: If ``parsed`` is neither a dict nor a list.
    """
    if isinstance(parsed, list):
        return [clean_obj(row) for row in parsed if isinstance(row, dict)]

    if isinstance(parsed, dict):
        if "rows" in parsed and isinstance(parsed["rows"], list):
            return [clean_obj(row) for row in parsed["rows"] if isinstance(row, dict)]

        list_values = [v for v in parsed.values() if isinstance(v, list)]
        if len(list_values) == 1:
            return [clean_obj(row) for row in list_values[0] if isinstance(row, dict)]

        return [clean_obj(parsed)]

    raise TypeError("JSON must be a dict or list of dicts")

def read_json_or_jsonl(file_path):
    """Read a JSON array/object file or JSONL file into record dicts.

    :param file_path: Path to the input file.
    :type file_path: str | pathlib.Path
    :returns: Normalized list of applicant records.
    :rtype: list[dict]
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    if not content:
        return []

    try:
        parsed = json.loads(content)
        print("Detected format: regular JSON")
        return normalize_records(parsed)
    except json.JSONDecodeError:
        pass

    print("Detected format: JSONL")
    data = []

    with open(file_path, "r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                parsed_line = json.loads(line)

                if isinstance(parsed_line, dict):
                    data.append(clean_obj(parsed_line))
                elif isinstance(parsed_line, list):
                    data.extend(clean_obj(row) for row in parsed_line if isinstance(row, dict))
                else:
                    print(f"Skipping non-dict JSON value on line {line_number}")

            except json.JSONDecodeError as e:
                print(f"Skipping invalid JSON on line {line_number}: {e}")

    return data

def pick(row, *keys):
    """Return the first non-empty value for any of the given keys.

    :param row: Source record dictionary.
    :type row: dict
    :param keys: Candidate field names, tried in order.
    :type keys: str
    :returns: First matching value, or ``None`` if none found.
    :rtype: object | None
    """
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None

def load_json_to_postgres(
    json_file=DEFAULT_JSON_FILE,
    table_name=DEFAULT_TABLE_NAME,
    delete_date=None,
):
    """Load applicant records from JSON/JSONL into a PostgreSQL table.

    Creates the destination table and unique index if they do not exist.
    Optionally deletes existing rows for a given date before inserting.

    :param json_file: Path to the JSON or JSONL input file.
    :type json_file: str | pathlib.Path
    :param table_name: Destination PostgreSQL table name.
    :type table_name: str
    :param delete_date: If set, delete rows with this ``date_added``
        (``YYYY-MM-DD``) before insert.
    :type delete_date: str | None
    :returns: ``None``
    :rtype: None
    """
    data = read_json_or_jsonl(json_file)

    print("Top-level normalized type:", type(data).__name__)
    print("Record count:", len(data))
    print("First record keys:", list(data[0].keys()) if data else [])

    if not data:
        print("No valid records found. Nothing inserted.")
        return

    limit = len(data)
    data = data[:limit]

    db_target = get_connect_kwargs()
    connection_ctx = psycopg.connect(**db_target)

    with connection_ctx as connection:
        with connection.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    p_id int GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    program text,
                    comments text,
                    date_added date,
                    url text UNIQUE,
                    status text,
                    term text,
                    us_or_international text,
                    gpa float,
                    gre float,
                    gre_v float,
                    gre_aw float,
                    degree text,
                    llm_generated_program text,
                    llm_generated_university text,
                    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS {table_name}_url_uniq_idx
                ON {table_name} (url)
            """)

            if delete_date:
                delete_dt = datetime.strptime(delete_date, "%Y-%m-%d").date()
                cur.execute(
                    f"DELETE FROM {table_name} WHERE date_added = %s",
                    (delete_dt,),
                )
                print(f"Deleted existing rows from {table_name} where date_added = {delete_date}")

            rows_to_insert = [
                (
                    pick(row, "Program Name", "program_name", "program"),
                    pick(row, "Comments", "comments"),
                    parse_date(pick(row, "Date of Information Added to Grad Cafe", "date_added", "date")),
                    pick(row, "URL link to applicant entry", "url", "url_link"),
                    pick(row, "Applicant Status", "status"),
                    pick(row, "Semester and Year of Program Start", "term", "program_start"),
                    pick(row, "International / American Student", "US/International", "us_or_international", "student_type"),
                    parse_float(pick(row, "GPA", "gpa")),
                    parse_float(pick(row, "GRE Score", "GRE", "gre", "gre_score")),
                    parse_float(pick(row, "GRE V Score", "GRE V", "gre_v", "gre_v_score")),
                    parse_float(pick(row, "GRE AW", "gre_aw")),
                    pick(row, "Masters or PhD", "Degree", "degree"),
                    pick(row, "llm-generated-program", "llm_generated_program"),
                    pick(row, "llm-generated-university", "llm_generated_university")
                )
                for row in data
            ]

            print("Rows prepared for insert:", len(rows_to_insert))

            cur.executemany(
                f"""
                INSERT INTO {table_name} (
                    program,
                    comments,
                    date_added,
                    url,
                    status,
                    term,
                    us_or_international,
                    gpa,
                    gre,
                    gre_v,
                    gre_aw,
                    degree,
                    llm_generated_program,
                    llm_generated_university
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO NOTHING
                """,
                rows_to_insert
            )
                
        connection.commit()

    print(f"Inserted {len(rows_to_insert)} rows into {table_name}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=DEFAULT_JSON_FILE, help="Path to JSON or JSONL file")
    parser.add_argument("--table", default=DEFAULT_TABLE_NAME, help="Destination table name")
    parser.add_argument("--delete-date", default=None, help="Delete existing rows for this date before insert (YYYY-MM-DD)")
    args = parser.parse_args()

    if not Path(args.input).exists():
        raise FileNotFoundError(f"Input file not found: {args.input}")

    load_json_to_postgres(
        json_file=args.input,
        table_name=args.table,
        delete_date=args.delete_date,
    )