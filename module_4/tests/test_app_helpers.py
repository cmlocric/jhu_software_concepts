import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Add the src directory to sys.path so pytest can import app.py as "app".
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

pytestmark = [pytest.mark.web]

@pytest.fixture
def app_module():
    """Import and return the Flask app module.

    :return: The imported ``app`` module.
    :rtype: module
    """
    return importlib.import_module("app")

@pytest.fixture
def client(app_module):
    """Create a Flask test client.

    This fixture enables Flask testing mode for the duration of the test and
    restores the prior values afterward to avoid leaking state across tests.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :yield: A Flask test client instance.
    :rtype: flask.testing.FlaskClient
    """
    original_testing = app_module.app.config.get("TESTING", False)
    original_pull_busy = getattr(app_module, "pull_data_running", False)

    app_module.app.config.update(TESTING=True)
    app_module.pull_data_running = False

    with app_module.app.test_client() as test_client:
        yield test_client

    app_module.app.config.update(TESTING=original_testing)
    app_module.pull_data_running = original_pull_busy

def _completed_process(returncode=0, stdout="", stderr=""):
    """Build a fake subprocess result object.

    :param returncode: Simulated process return code.
    :type returncode: int
    :param stdout: Simulated standard output.
    :type stdout: str
    :param stderr: Simulated standard error.
    :type stderr: str
    :return: Object mimicking a subprocess result.
    :rtype: types.SimpleNamespace
    """
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

class DummyConnection:
    """Minimal stand-in for a database connection object."""

    def close(self):
        """Pretend to close the connection.

        :return: None
        :rtype: None
        """
        return None

def test_try_start_pull_data_sets_busy_flag(app_module):
    """Verify that ``try_start_pull_data`` marks the app as busy.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :return: None
    :rtype: None
    """
    app_module.pull_data_running = False

    started = app_module.try_start_pull_data()

    assert started is True
    assert app_module.pull_data_running is True

def test_try_start_pull_data_returns_false_when_already_busy(app_module):
    """Verify that ``try_start_pull_data`` rejects a second active pull.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :return: None
    :rtype: None
    """
    app_module.pull_data_running = True

    started = app_module.try_start_pull_data()

    assert started is False
    assert app_module.pull_data_running is True

def test_finish_pull_data_clears_busy_flag(app_module):
    """Verify that ``finish_pull_data`` clears the busy flag.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :return: None
    :rtype: None
    """
    app_module.pull_data_running = True

    app_module.finish_pull_data()

    assert app_module.pull_data_running is False

def test_is_pull_data_running_reflects_current_flag(app_module):
    """Verify that ``is_pull_data_running`` returns the current busy state.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :return: None
    :rtype: None
    """
    app_module.pull_data_running = False
    assert app_module.is_pull_data_running() is False

    app_module.pull_data_running = True
    assert app_module.is_pull_data_running() is True

def test_load_watermark_returns_none_when_file_missing(app_module, tmp_path, monkeypatch):
    """Verify that ``load_watermark`` returns ``None`` when the file is absent.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :param tmp_path: Pytest temporary path fixture.
    :type tmp_path: pathlib.Path
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: None
    :rtype: None
    """
    watermark_file = tmp_path / "pull_watermark.json"
    monkeypatch.setattr(app_module, "WATERMARK_FILE", watermark_file)

    assert app_module.load_watermark() is None

def test_save_watermark_and_load_watermark_round_trip(app_module, tmp_path, monkeypatch):
    """Verify that ``save_watermark`` writes a value that ``load_watermark`` reads.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :param tmp_path: Pytest temporary path fixture.
    :type tmp_path: pathlib.Path
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: None
    :rtype: None
    """
    watermark_file = tmp_path / "json_files" / "pull_watermark.json"
    monkeypatch.setattr(app_module, "WATERMARK_FILE", watermark_file)

    app_module.save_watermark("2026-01-31")

    assert watermark_file.exists()
    assert app_module.load_watermark() == "2026-01-31"

    with open(watermark_file, "r", encoding="utf-8") as f:
        payload = json.load(f)

    assert payload == {"min_added_on": "2026-01-31"}

def test_parse_added_on_date_accepts_full_month_name(app_module):
    """Verify that ``parse_added_on_date`` handles full month names.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :return: None
    :rtype: None
    """
    parsed = app_module.parse_added_on_date("January 17, 2026")

    assert parsed is not None
    assert parsed.isoformat() == "2026-01-17"

def test_parse_added_on_date_accepts_abbreviated_month_name(app_module):
    """Verify that ``parse_added_on_date`` handles abbreviated month names.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :return: None
    :rtype: None
    """
    parsed = app_module.parse_added_on_date("Jan 17, 2026")

    assert parsed is not None
    assert parsed.isoformat() == "2026-01-17"

def test_parse_added_on_date_returns_none_for_invalid_value(app_module):
    """Verify that ``parse_added_on_date`` returns ``None`` for invalid input.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :return: None
    :rtype: None
    """
    assert app_module.parse_added_on_date("") is None
    assert app_module.parse_added_on_date("not-a-date") is None

def test_read_json_records_returns_empty_list_when_file_missing(app_module, tmp_path):
    """Verify that ``read_json_records`` returns an empty list for a missing file.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :param tmp_path: Pytest temporary path fixture.
    :type tmp_path: pathlib.Path
    :return: None
    :rtype: None
    """
    missing_file = tmp_path / "does_not_exist.json"

    assert app_module.read_json_records(missing_file) == []

def test_read_json_records_returns_list_payload(app_module, tmp_path):
    """Verify that ``read_json_records`` returns a top-level list unchanged.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :param tmp_path: Pytest temporary path fixture.
    :type tmp_path: pathlib.Path
    :return: None
    :rtype: None
    """
    payload = [{"a": 1}, {"a": 2}]
    json_file = tmp_path / "records.json"
    json_file.write_text(json.dumps(payload), encoding="utf-8")

    assert app_module.read_json_records(json_file) == payload

def test_read_json_records_returns_rows_list_from_dict(app_module, tmp_path):
    """Verify that ``read_json_records`` extracts ``rows`` from a dict payload.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :param tmp_path: Pytest temporary path fixture.
    :type tmp_path: pathlib.Path
    :return: None
    :rtype: None
    """
    payload = {"rows": [{"a": 1}, {"a": 2}]}
    json_file = tmp_path / "records.json"
    json_file.write_text(json.dumps(payload), encoding="utf-8")

    assert app_module.read_json_records(json_file) == payload["rows"]

def test_read_json_records_returns_empty_list_for_other_dict_shape(app_module, tmp_path):
    """Verify that ``read_json_records`` returns an empty list for other dict shapes.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :param tmp_path: Pytest temporary path fixture.
    :type tmp_path: pathlib.Path
    :return: None
    :rtype: None
    """
    payload = {"unexpected": "value"}
    json_file = tmp_path / "records.json"
    json_file.write_text(json.dumps(payload), encoding="utf-8")

    assert app_module.read_json_records(json_file) == []

def test_get_latest_added_on_returns_latest_date(app_module, tmp_path):
    """Verify that ``get_latest_added_on`` returns the max parsed date.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :param tmp_path: Pytest temporary path fixture.
    :type tmp_path: pathlib.Path
    :return: None
    :rtype: None
    """
    payload = [
        {"Date of Information Added to Grad Cafe": "January 01, 2026"},
        {"Date of Information Added to Grad Cafe": "Jan 15, 2026"},
        {"Date of Information Added to Grad Cafe": "January 10, 2026"},
    ]
    json_file = tmp_path / "records.json"
    json_file.write_text(json.dumps(payload), encoding="utf-8")

    assert app_module.get_latest_added_on(json_file) == "2026-01-15"

def test_get_latest_added_on_returns_none_when_no_valid_dates(app_module, tmp_path):
    """Verify that ``get_latest_added_on`` returns ``None`` when no dates parse.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :param tmp_path: Pytest temporary path fixture.
    :type tmp_path: pathlib.Path
    :return: None
    :rtype: None
    """
    payload = [
        {"Date of Information Added to Grad Cafe": ""},
        {"Date of Information Added to Grad Cafe": "not-a-date"},
    ]
    json_file = tmp_path / "records.json"
    json_file.write_text(json.dumps(payload), encoding="utf-8")

    assert app_module.get_latest_added_on(json_file) is None

def test_run_python_script_uses_base_dir_and_returns_process_result(app_module, monkeypatch):
    """Verify that ``run_python_script`` calls ``subprocess.run`` with expected args.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: None
    :rtype: None
    """
    captured = {}

    def fake_subprocess_run(command, cwd, capture_output, text):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["capture_output"] = capture_output
        captured["text"] = text
        return _completed_process(returncode=0, stdout="ok")

    monkeypatch.setattr(app_module.subprocess, "run", fake_subprocess_run)

    script_path = app_module.BASE_DIR / "dummy_script.py"
    result = app_module.run_python_script(script_path, "--flag", "value")

    assert result.returncode == 0
    assert captured["command"] == [sys.executable, str(script_path), "--flag", "value"]
    assert captured["cwd"] == app_module.BASE_DIR
    assert captured["capture_output"] is True
    assert captured["text"] is True

def test_pull_data_returns_500_when_scrape_fails(client, app_module, monkeypatch):
    """Verify that ``POST /pull-data`` returns 500 when scraping fails.

    :param client: Flask test client.
    :type client: flask.testing.FlaskClient
    :param app_module: The imported Flask app module.
    :type app_module: module
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: None
    :rtype: None
    """
    monkeypatch.setattr(
        app_module,
        "run_python_script",
        lambda script_path, *args: _completed_process(returncode=1, stderr="scrape broke"),
    )
    monkeypatch.setattr(app_module, "load_watermark", lambda: None)

    response = client.post("/pull-data")
    payload = response.get_json()

    assert response.status_code == 500
    assert payload["ok"] is False
    assert payload["error"] == "scrape broke"
    assert app_module.pull_data_running is False

def test_pull_data_returns_success_when_no_new_records_found(client, app_module, monkeypatch):
    """Verify that ``POST /pull-data`` returns success when no rows are scraped.

    :param client: Flask test client.
    :type client: flask.testing.FlaskClient
    :param app_module: The imported Flask app module.
    :type app_module: module
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: None
    :rtype: None
    """
    monkeypatch.setattr(
        app_module,
        "run_python_script",
        lambda script_path, *args: _completed_process(returncode=0, stdout="ok"),
    )
    monkeypatch.setattr(app_module, "load_watermark", lambda: None)
    monkeypatch.setattr(app_module, "read_json_records", lambda path: [])

    response = client.post("/pull-data")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["message"] == "Pull Data completed successfully. No new records found."
    assert app_module.pull_data_running is False

def test_pull_data_returns_500_when_clean_step_fails(client, app_module, monkeypatch):
    """Verify that ``POST /pull-data`` returns 500 when cleaning fails.

    :param client: Flask test client.
    :type client: flask.testing.FlaskClient
    :param app_module: The imported Flask app module.
    :type app_module: module
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: None
    :rtype: None
    """
    calls = {"count": 0}

    def fake_run_python_script(script_path, *args):
        calls["count"] += 1
        if calls["count"] == 1:
            return _completed_process(returncode=0, stdout="scraped")
        return _completed_process(returncode=1, stderr="clean broke")

    monkeypatch.setattr(app_module, "run_python_script", fake_run_python_script)
    monkeypatch.setattr(app_module, "load_watermark", lambda: None)
    monkeypatch.setattr(
        app_module,
        "read_json_records",
        lambda path: [{"Date of Information Added to Grad Cafe": "January 01, 2026"}],
    )

    response = client.post("/pull-data")
    payload = response.get_json()

    assert response.status_code == 500
    assert payload["ok"] is False
    assert payload["error"] == "clean broke"
    assert app_module.pull_data_running is False

def test_pull_data_returns_500_when_load_step_fails(client, app_module, monkeypatch):
    """Verify that ``POST /pull-data`` returns 500 when loading fails.

    :param client: Flask test client.
    :type client: flask.testing.FlaskClient
    :param app_module: The imported Flask app module.
    :type app_module: module
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: None
    :rtype: None
    """
    calls = {"count": 0}

    def fake_run_python_script(script_path, *args):
        calls["count"] += 1
        if calls["count"] in (1, 2):
            return _completed_process(returncode=0, stdout="ok")
        return _completed_process(returncode=1, stderr="load broke")

    monkeypatch.setattr(app_module, "run_python_script", fake_run_python_script)
    monkeypatch.setattr(app_module, "load_watermark", lambda: None)
    monkeypatch.setattr(
        app_module,
        "read_json_records",
        lambda path: [{"Date of Information Added to Grad Cafe": "January 01, 2026"}],
    )

    response = client.post("/pull-data")
    payload = response.get_json()

    assert response.status_code == 500
    assert payload["ok"] is False
    assert payload["error"] == "load broke"
    assert app_module.pull_data_running is False

def test_update_analysis_returns_500_when_query_script_fails(client, app_module, monkeypatch):
    """Verify that ``POST /update-analysis`` returns 500 when the query script fails.

    :param client: Flask test client.
    :type client: flask.testing.FlaskClient
    :param app_module: The imported Flask app module.
    :type app_module: module
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: None
    :rtype: None
    """
    monkeypatch.setattr(app_module, "pull_data_running", False, raising=False)
    monkeypatch.setattr(
        app_module,
        "run_python_script",
        lambda script_path, *args: _completed_process(returncode=1, stderr="query broke"),
    )

    response = client.post("/update-analysis")
    payload = response.get_json()

    assert response.status_code == 500
    assert payload["ok"] is False
    assert payload["error"] == "query broke"

def test_analysis_route_uses_formatted_query_results(client, app_module, monkeypatch):
    """Verify that ``GET /analysis`` renders query results from the app helpers.

    This test patches the DB connection and analysis results so the route can be
    exercised without real database access.

    :param client: Flask test client.
    :type client: flask.testing.FlaskClient
    :param app_module: The imported Flask app module.
    :type app_module: module
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: None
    :rtype: None
    """
    monkeypatch.setattr(
        app_module,
        "get_db_connection",
        lambda dbname, user: DummyConnection(),
    )
    monkeypatch.setattr(
        app_module,
        "get_all_query_results",
        lambda connection: [("Question 1", ("Metric:", "12.34%"))],
    )
    monkeypatch.setattr(app_module, "format_analysis_value", lambda answer: answer)

    response = client.get("/analysis")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Question 1" in page
    assert "Answer:" in page
    assert "Metric:" in page
    assert "12.34%" in page