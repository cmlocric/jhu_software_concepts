import importlib
import runpy
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

pytestmark = [pytest.mark.db]

class DummyCursor:
    def __init__(self, results_by_query=None, default_results=None):
        self.results_by_query = results_by_query or {}
        self.default_results = [] if default_results is None else default_results
        self.current_query = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query):
        self.current_query = query

    def fetchall(self):
        return self.results_by_query.get(self.current_query, self.default_results)


class DummyConnection:
    def __init__(self, results_by_query=None, default_results=None):
        self.results_by_query = results_by_query or {}
        self.default_results = default_results
        self.closed = False

    def cursor(self):
        return DummyCursor(self.results_by_query, self.default_results)

    def close(self):
        self.closed = True


def import_fresh_query_data(monkeypatch, connection=None):
    connection = connection or DummyConnection()
    monkeypatch.setattr(psycopg, "connect", lambda **kwargs: connection)
    sys.modules.pop("query_data", None)
    module = importlib.import_module("query_data")
    return module, connection


def test_query_data_import_initializes_module_connection(monkeypatch):
    captured = {}
    connection = DummyConnection()

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    sys.modules.pop("query_data", None)

    module = importlib.import_module("query_data")

    assert captured == {"user": "postgres", "dbname": "applicant_db"}
    assert module.connection is connection

def test_convert_decimal_handles_decimal_and_other_values(monkeypatch):
    module, _ = import_fresh_query_data(monkeypatch)

    assert module.convert_decimal(Decimal("12.34")) == 12.34
    assert module.convert_decimal("abc") == "abc"


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ([], None),
        ([(Decimal("12.34"),)], 12.34),
        ([("Label", Decimal("12.34"))], ("Label", 12.34)),
        ([(Decimal("1.1"),), (Decimal("2.2"),)], [1.1, 2.2]),
        (
            [("A", Decimal("1.1")), ("B", Decimal("2.2"))],
            [("A", 1.1), ("B", 2.2)],
        ),
    ],
)
def test_execute_query_formats_results_by_shape(monkeypatch, results, expected):
    query = "SELECT 1"
    module, _ = import_fresh_query_data(monkeypatch, DummyConnection({query: results}))

    assert module.execute_query(module.connection, query) == expected

def test_query_data_import_uses_database_url_when_present(monkeypatch):
    captured = {}
    connection = DummyConnection()

    monkeypatch.setenv("DATABASE_URL", "postgresql://example-user@example-host/test_db")
    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda **kwargs: captured.update(kwargs) or connection,
    )
    sys.modules.pop("query_data", None)

    module = importlib.import_module("query_data")

    assert captured == {"conninfo": "postgresql://example-user@example-host/test_db"}
    assert module.connection is connection

def test_get_all_query_results_zips_questions_and_closes_connection(monkeypatch):
    module, connection = import_fresh_query_data(monkeypatch)
    module.question_query_dict = {
        "Question 1": "SELECT 1",
        "Question 2": "SELECT 2",
    }

    answers = iter([("Metric:", 1), ("Metric:", 2)])
    monkeypatch.setattr(module, "execute_query", lambda connection, query: next(answers))

    result = module.get_all_query_results(connection)

    assert result == [
        ("Question 1", ("Metric:", 1)),
        ("Question 2", ("Metric:", 2)),
    ]
    assert connection.closed is True


def test_query_data_main_block_prints_all_results(monkeypatch, capsys):
    connection = DummyConnection(default_results=[(1,)])

    monkeypatch.setattr(psycopg, "connect", lambda **kwargs: connection)
    sys.modules.pop("query_data", None)

    runpy.run_module("query_data", run_name="__main__")

    out = capsys.readouterr().out
    assert "1) How many entries do you have in your database who have applied for Fall 2026? Answer: 1" in out
    assert "11) For Computer Science applicants, which universities have the most acceptances" in out
