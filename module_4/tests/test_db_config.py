import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import db_config


def test_get_database_url_uses_database_url_when_set(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example-user@example-host/test_db")
    assert db_config.get_database_url() == "postgresql://example-user@example-host/test_db"


def test_get_database_url_builds_from_pg_environment(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PGUSER", "app_user")
    monkeypatch.setenv("PGHOST", "db.example.com")
    monkeypatch.setenv("PGPORT", "5433")
    monkeypatch.setenv("PGDATABASE", "custom_db")

    assert db_config.get_database_url() == "postgresql://app_user@db.example.com:5433/custom_db"


def test_get_connect_kwargs_honors_dbname_override(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PGDATABASE", raising=False)

    kwargs = db_config.get_connect_kwargs(dbname="override_db")

    assert kwargs["dbname"] == "override_db"
    assert kwargs["user"] == "postgres"


def test_connect_uses_env_kwargs(monkeypatch):
    captured = {}

    class DummyConnection:
        pass

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return DummyConnection()

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db_config.psycopg, "connect", fake_connect)

    connection = db_config.connect()

    assert connection.__class__.__name__ == "DummyConnection"
    assert captured["dbname"] == db_config.DEFAULT_DBNAME
