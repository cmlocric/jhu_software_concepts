import importlib
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

class DummyCursor:
    def __init__(self, fetchone_value=None, fetchall_value=None):
        self.fetchone_value = fetchone_value
        self.fetchall_value = [] if fetchall_value is None else fetchall_value
        self.execute_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.execute_calls.append((query, params))

    def fetchone(self):
        return self.fetchone_value

    def fetchall(self):
        return self.fetchall_value

class DummyConnection:
    def __init__(self, cursor_obj):
        self.cursor_obj = cursor_obj
        self.autocommit = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True

    def commit(self):
        pass

def fresh_create_database_module():
    sys.modules.pop("create_database", None)
    return importlib.import_module("create_database")

def test_start_postgres_returns_early_when_already_running(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    module = fresh_create_database_module()

    calls = []

    def fake_run(command, text, capture_output):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="running", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.start_postgres()

    assert calls == [[module.PG_CTL, "status", "-D", module.PG_DATA]]
    assert "PostgreSQL server is already running." in capsys.readouterr().out
    
def test_start_postgres_skips_local_pg_ctl_when_database_url_is_set(monkeypatch, capsys):
    sys.modules.pop("create_database", None)
    module = importlib.import_module("create_database")

    called = {"run": False}

    def fake_run(*args, **kwargs):
        called["run"] = True
        raise AssertionError("subprocess.run should not be called when DATABASE_URL is set")

    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/applicant_db")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.start_postgres()

    assert called["run"] is False
    assert "DATABASE_URL set; skipping local pg_ctl startup." in capsys.readouterr().out

def test_start_postgres_starts_server_when_not_running(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    module = fresh_create_database_module()

    calls = []

    def fake_run(command, text, capture_output):
        calls.append(command)
        if len(calls) == 1:
            return SimpleNamespace(returncode=1, stdout="", stderr="not running")
        return SimpleNamespace(returncode=0, stdout="started ok", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    module.start_postgres()

    assert calls == [
        [module.PG_CTL, "status", "-D", module.PG_DATA],
        [module.PG_CTL, "start", "-D", module.PG_DATA, "-w"],
    ]

    out = capsys.readouterr().out
    assert "pg_ctl stdout:" in out
    assert "started ok" in out
    assert "pg_ctl stderr:" in out
    assert "PostgreSQL server started." in out

def test_start_postgres_raises_when_start_fails(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    module = fresh_create_database_module()

    calls = []

    def fake_run(command, text, capture_output):
        calls.append(command)
        if len(calls) == 1:
            return SimpleNamespace(returncode=1, stdout="", stderr="not running")
        return SimpleNamespace(returncode=3, stdout="bad", stderr="failed")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="PostgreSQL failed to start"):
        module.start_postgres()

    out = capsys.readouterr().out
    assert "pg_ctl stdout:" in out
    assert "bad" in out
    assert "pg_ctl stderr:" in out
    assert "failed" in out

def test_main_creates_database_when_missing(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    first_cursor = DummyCursor(fetchone_value=None)
    second_cursor = DummyCursor(fetchall_value=[("UTF8",)])

    first_conn = DummyConnection(first_cursor)
    second_conn = DummyConnection(second_cursor)

    connect_calls = []

    def fake_connect(**kwargs):
        connect_calls.append(kwargs)
        if len(connect_calls) == 1:
            return first_conn
        return second_conn

    def fake_run(command, text, capture_output):
        return SimpleNamespace(returncode=0, stdout="running", stderr="")

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    monkeypatch.setattr(subprocess, "run", fake_run)

    sys.modules.pop("create_database", None)
    runpy.run_module("create_database", run_name="__main__")

    assert connect_calls[0]["dbname"] == "postgres"
    assert connect_calls[0]["user"] == "postgres"
    assert connect_calls[0]["connect_timeout"] == 5
    assert connect_calls[1]["dbname"] == "applicant_db"
    assert connect_calls[1]["user"] == "postgres"
    assert connect_calls[1]["connect_timeout"] == 5

    assert first_conn.autocommit is True
    assert first_conn.closed is True
    assert second_conn.closed is True

    assert first_cursor.execute_calls == [
        ("SELECT 1 FROM pg_database WHERE datname = %s", ("applicant_db",)),
        ('CREATE DATABASE "applicant_db" WITH ENCODING \'UTF8\' TEMPLATE template0;', None),
    ]
    assert second_cursor.execute_calls == [
        ("SHOW server_encoding;", None),
    ]

    out = capsys.readouterr().out
    assert "PostgreSQL server is already running." in out
    assert "Database applicant_db created." in out
    assert "Server encoding:" in out

def test_main_skips_create_when_database_already_exists(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    first_cursor = DummyCursor(fetchone_value=(1,))
    second_cursor = DummyCursor(fetchall_value=[("UTF8",)])

    first_conn = DummyConnection(first_cursor)
    second_conn = DummyConnection(second_cursor)

    connect_calls = []

    def fake_connect(**kwargs):
        connect_calls.append(kwargs)
        if len(connect_calls) == 1:
            return first_conn
        return second_conn

    def fake_run(command, text, capture_output):
        return SimpleNamespace(returncode=0, stdout="running", stderr="")

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    monkeypatch.setattr(subprocess, "run", fake_run)

    sys.modules.pop("create_database", None)
    runpy.run_module("create_database", run_name="__main__")

    assert connect_calls[0]["dbname"] == "postgres"
    assert connect_calls[0]["user"] == "postgres"
    assert connect_calls[0]["connect_timeout"] == 5
    assert connect_calls[1]["dbname"] == "applicant_db"
    assert connect_calls[1]["user"] == "postgres"
    assert connect_calls[1]["connect_timeout"] == 5

    assert first_conn.autocommit is True
    assert first_conn.closed is True
    assert second_conn.closed is True

    assert first_cursor.execute_calls == [
        ("SELECT 1 FROM pg_database WHERE datname = %s", ("applicant_db",)),
    ]
    assert second_cursor.execute_calls == [
        ("SHOW server_encoding;", None),
    ]

    out = capsys.readouterr().out
    assert "PostgreSQL server is already running." in out
    assert "Database applicant_db already exists." in out
    assert "Server encoding:" in out