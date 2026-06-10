import importlib
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
import os
import psycopg
import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

pytestmark = [pytest.mark.web]

class DummyConnection:
    def close(self):
        pass

def fresh_app_module(monkeypatch):
    # pyrefly: ignore [missing-import]
    import create_database

    monkeypatch.setattr(create_database, "start_postgres", lambda: None)
    monkeypatch.setattr(psycopg, "connect", lambda **kwargs: DummyConnection())

    sys.modules.pop("query_data", None)
    sys.modules.pop("app", None)
    return importlib.import_module("app")

def test_get_database_url_and_create_app_use_env_and_test_config(monkeypatch):
    # pyrefly: ignore [missing-import]
    import create_database
    import psycopg
    import sys
    import importlib

    monkeypatch.setattr(create_database, "start_postgres", lambda: None)
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: DummyConnection())

    monkeypatch.setenv("DATABASE_URL", "postgresql://example-user@example-host/test_db")

    sys.modules.pop("query_data", None)
    sys.modules.pop("app", None)
    app_module = importlib.import_module("app")

    assert app_module.get_database_url() == "postgresql://example-user@example-host/test_db"

    created = app_module.create_app({"TESTING": True, "CUSTOM_FLAG": "yes"})
    assert created.config["TESTING"] is True
    assert created.config["CUSTOM_FLAG"] == "yes"

def test_get_db_connection_uses_database_url_when_no_dbname_or_user(monkeypatch):
    # pyrefly: ignore [missing-import]
    import create_database
    import psycopg
    import sys
    import importlib

    monkeypatch.setattr(create_database, "start_postgres", lambda: None)

    captured = {"args": None, "kwargs": None}

    class DummyConnection:
        def close(self):
            pass

    def fake_connect(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return DummyConnection()

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example-user@example-host/test_db")

    sys.modules.pop("query_data", None)
    sys.modules.pop("app", None)
    app_module = importlib.import_module("app")

    app_module.get_db_connection()

    assert (
        captured["args"] == ("postgresql://example-user@example-host/test_db",)
        or captured["kwargs"] == {"conninfo": "postgresql://example-user@example-host/test_db"}
    )

def test_get_db_connection_calls_psycopg_connect(monkeypatch):
    app_module = fresh_app_module(monkeypatch)
    captured = {}
    fake_connection = object()

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return fake_connection

    monkeypatch.setattr(psycopg, "connect", fake_connect)

    result = app_module.get_db_connection(dbname="applicant_db", user="postgres")

    assert result is fake_connection
    assert captured == {"dbname": "applicant_db", "user": "postgres"}

def test_format_analysis_value_formats_nested_list_values(monkeypatch):
    app_module = fresh_app_module(monkeypatch)

    value = [1.2345, ("Label", 7.5), ["x", 2.0]]
    result = app_module.format_analysis_value(value)

    assert result == ["1.23", ("Label", "7.50"), ["x", "2.00"]]

def test_pull_data_uses_watermark_and_removes_progress_file(monkeypatch, tmp_path):
    app_module = fresh_app_module(monkeypatch)

    raw_json = tmp_path / "applicant_data_updated.json"
    clean_json = tmp_path / "applicant_data_updated_cleaned.json"
    progress_json = Path(f"{clean_json}.progress.json")

    raw_json.parent.mkdir(parents=True, exist_ok=True)
    clean_json.write_text("old cleaned", encoding="utf-8")
    progress_json.write_text("old progress", encoding="utf-8")

    calls = []

    def fake_run_python_script(script_path, *args):
        calls.append((Path(script_path), list(args)))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(app_module, "RAW_JSON_OUTPUT", raw_json)
    monkeypatch.setattr(app_module, "CLEAN_JSON_OUTPUT", clean_json)
    monkeypatch.setattr(app_module, "try_start_pull_data", lambda: True)
    monkeypatch.setattr(app_module, "finish_pull_data", lambda: None)
    monkeypatch.setattr(app_module, "load_watermark", lambda: "2026-01-16")
    monkeypatch.setattr(app_module, "run_python_script", fake_run_python_script)
    monkeypatch.setattr(
        app_module,
        "read_json_records",
        lambda path: [{"Date of Information Added to Grad Cafe": "January 16, 2026"}],
    )
    monkeypatch.setattr(app_module, "get_latest_added_on", lambda path: None)

    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as client:
        response = client.post("/pull-data")

    assert response.status_code == 200

    scrape_call = calls[0]
    load_call = calls[2]

    assert "--min-added-on" in scrape_call[1]
    assert "2026-01-16" in scrape_call[1]

    assert "--delete-date" in load_call[1]
    assert "2026-01-16" in load_call[1]

    assert clean_json.exists() is False
    assert progress_json.exists() is False

def test_app_main_runs_flask(monkeypatch):
    # pyrefly: ignore [missing-import]
    import create_database

    monkeypatch.setattr(create_database, "start_postgres", lambda: None)
    monkeypatch.setattr(psycopg, "connect", lambda **kwargs: DummyConnection())

    captured = {}

    monkeypatch.setattr(
        Flask,
        "run",
        lambda self, host, port: captured.update({"host": host, "port": port}),
    )

    sys.modules.pop("query_data", None)
    sys.modules.pop("app", None)

    runpy.run_module("app", run_name="__main__")

    assert captured == {"host": "0.0.0.0", "port": 8000}