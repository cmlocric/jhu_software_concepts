import importlib
import json
import runpy
import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

pytestmark = [pytest.mark.db]

class RecordingCursor:
    def __init__(self):
        self.execute_calls = []
        self.executemany_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.execute_calls.append((query, params))

    def executemany(self, query, rows):
        self.executemany_calls.append((query, list(rows)))


class RecordingConnection:
    def __init__(self):
        self.cursor_obj = RecordingCursor()
        self.commit_called = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commit_called = True


def test_clean_obj_parse_helpers_and_pick():
    load_data = importlib.import_module("load_data")

    cleaned = load_data.clean_obj(
        {
            "text": "ok😀",
            "items": ["hi😀", {"nested": "bye😀"}],
            "count": 3,
        }
    )

    assert cleaned == {
        "text": "ok",
        "items": ["hi", {"nested": "bye"}],
        "count": 3,
    }

    assert load_data.parse_float("3.5") == 3.5
    assert load_data.parse_float(7) == 7.0
    assert load_data.parse_float("") is None
    assert load_data.parse_float("abc") is None

    assert str(load_data.parse_date("January 17, 2026")) == "2026-01-17"
    assert load_data.parse_date("") is None
    assert load_data.parse_date("Jan 17, 2026") is None

    row = {"a": "", "b": None, "c": "value"}
    assert load_data.pick(row, "a", "b", "c") == "value"
    assert load_data.pick(row, "missing") is None


def test_normalize_records_covers_all_supported_shapes():
    load_data = importlib.import_module("load_data")

    assert load_data.normalize_records([{"a": 1}, {"a": 2}, "skip"]) == [{"a": 1}, {"a": 2}]
    assert load_data.normalize_records({"rows": [{"a": 1}, {"a": 2}]}) == [{"a": 1}, {"a": 2}]
    assert load_data.normalize_records({"payload": [{"a": 1}, {"a": 2}]}) == [{"a": 1}, {"a": 2}]
    assert load_data.normalize_records({"a": 1}) == [{"a": 1}]

    with pytest.raises(TypeError):
        load_data.normalize_records("not-json")


def test_read_json_or_jsonl_handles_json_and_jsonl_variants(tmp_path, capsys):
    load_data = importlib.import_module("load_data")

    json_file = tmp_path / "records.json"
    json_file.write_text(json.dumps({"rows": [{"a": 1}, {"a": 2}]}), encoding="utf-8")
    assert load_data.read_json_or_jsonl(json_file) == [{"a": 1}, {"a": 2}]
    assert "Detected format: regular JSON" in capsys.readouterr().out

    jsonl_file = tmp_path / "records.jsonl"
    jsonl_file.write_text(
        "\n".join(
            [
                json.dumps({"a": 1, "text": "ok😀"}),
                "",
                json.dumps([{"a": 2}, {"a": 3}]),
                json.dumps("skip me"),
                "{bad json",
            ]
        ),
        encoding="utf-8",
    )

    assert load_data.read_json_or_jsonl(jsonl_file) == [
        {"a": 1, "text": "ok"},
        {"a": 2},
        {"a": 3},
    ]
    out = capsys.readouterr().out
    assert "Detected format: JSONL" in out
    assert "Skipping non-dict JSON value" in out
    assert "Skipping invalid JSON" in out

    empty_file = tmp_path / "empty.json"
    empty_file.write_text("", encoding="utf-8")
    assert load_data.read_json_or_jsonl(empty_file) == []


def test_load_json_to_postgres_returns_early_when_no_data(monkeypatch, capsys):
    load_data = importlib.import_module("load_data")

    monkeypatch.setattr(load_data, "read_json_or_jsonl", lambda path: [])
    monkeypatch.setattr(psycopg, "connect", lambda **kwargs: pytest.fail("DB should not be opened"))

    load_data.load_json_to_postgres(json_file="ignored.json", table_name="applicants_test")

    out = capsys.readouterr().out
    assert "Record count: 0" in out
    assert "No valid records found. Nothing inserted." in out


def test_load_json_to_postgres_executes_create_delete_insert_and_index(monkeypatch, capsys):
    load_data = importlib.import_module("load_data")
    connection = RecordingConnection()

    sample_rows = [
        {
            "Program Name": "MIT Computer Science",
            "Comments": "Accepted",
            "Date of Information Added to Grad Cafe": "January 16, 2026",
            "URL link to applicant entry": "https://example.com/1",
            "Applicant Status": "Accepted",
            "Semester and Year of Program Start": "Fall 2026",
            "International / American Student": "International",
            "GPA": "3.80",
            "GRE Score": "330",
            "GRE V Score": "162",
            "GRE AW": "5.0",
            "Masters or PhD": "PhD",
            "llm-generated-program": "Computer Science",
            "llm-generated-university": "MIT",
        }
    ]

    monkeypatch.setattr(load_data, "read_json_or_jsonl", lambda path: sample_rows)
    monkeypatch.setattr(psycopg, "connect", lambda **kwargs: connection)

    load_data.load_json_to_postgres(
        json_file="ignored.json",
        table_name="applicants_test",
        delete_date="2026-01-16",
    )

    assert connection.commit_called is True
    assert len(connection.cursor_obj.executemany_calls) == 1

    insert_sql, inserted_rows = connection.cursor_obj.executemany_calls[0]
    assert "INSERT INTO applicants_test" in insert_sql
    assert inserted_rows == [
        (
            "MIT Computer Science",
            "Accepted",
            load_data.datetime.strptime("January 16, 2026", "%B %d, %Y").date(),
            "https://example.com/1",
            "Accepted",
            "Fall 2026",
            "International",
            3.8,
            330.0,
            162.0,
            5.0,
            "PhD",
            "Computer Science",
            "MIT",
        )
    ]

    execute_sql = "\n".join(query for query, _ in connection.cursor_obj.execute_calls)
    assert "CREATE TABLE IF NOT EXISTS applicants_test" in execute_sql
    assert "DELETE FROM applicants_test WHERE date_added = %s" in execute_sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS applicants_test_uniq_idx" in execute_sql

    delete_call = next(params for query, params in connection.cursor_obj.execute_calls if "DELETE FROM applicants_test" in query)
    assert str(delete_call[0]) == "2026-01-16"

    out = capsys.readouterr().out
    assert "Rows prepared for insert: 1" in out
    assert "Inserted 1 rows into applicants_test" in out


def test_load_data_main_block_runs_for_existing_input(monkeypatch, tmp_path, capsys):
    input_file = tmp_path / "input.json"
    input_file.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "load_data.py",
            "--input",
            str(input_file),
            "--table",
            "applicants_cli",
            "--delete-date",
            "2026-01-31",
        ],
    )

    runpy.run_module("load_data", run_name="__main__")

    out = capsys.readouterr().out
    assert "Record count: 0" in out
    assert "No valid records found. Nothing inserted." in out


def test_load_data_main_block_raises_when_input_missing(monkeypatch, tmp_path):
    missing_file = tmp_path / "missing.json"
    monkeypatch.setattr(sys, "argv", ["load_data.py", "--input", str(missing_file)])

    with pytest.raises(FileNotFoundError):
        runpy.run_module("load_data", run_name="__main__")
