import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Add the src directory to sys.path so pytest can import app.py as "app".
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

pytestmark = [pytest.mark.web, pytest.mark.buttons]

@pytest.fixture
def app_module():
    """Import and return the Flask app module.

    This fixture provides access to the imported ``app`` module so tests can
    reference the Flask application object, route helpers, and module-level
    state used by the busy-gating logic.

    :return: The imported ``app`` module.
    :rtype: module
    """
    return importlib.import_module("app")

@pytest.fixture
def client(app_module):
    """Create a Flask test client.

    The test client allows requests to be made against the Flask app without
    starting a real web server.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :yield: A Flask test client instance.
    :rtype: flask.testing.FlaskClient
    """
    original_testing = app_module.app.config.get("TESTING", False)
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as test_client:
        yield test_client

    app_module.app.config.update(TESTING=original_testing)

def _completed_process(returncode=0, stdout="", stderr=""):
    """Build a fake subprocess result object.

    This helper returns a lightweight object with the same attributes used by
    ``app.py`` when handling subprocess results.

    :param returncode: Simulated process return code.
    :type returncode: int
    :param stdout: Simulated standard output.
    :type stdout: str
    :param stderr: Simulated standard error.
    :type stderr: str
    :return: An object mimicking ``subprocess.CompletedProcess`` for test use.
    :rtype: types.SimpleNamespace
    """
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

def test_post_pull_data_returns_200_and_triggers_loader_with_scraped_rows(
    client,
    app_module,
    monkeypatch,
):
    """Test that ``POST /pull-data`` succeeds and runs the expected scripts.

    This test verifies that the pull-data endpoint:
    1. Returns HTTP 200
    2. Calls the scraper, cleaner, and loader scripts
    3. Passes the cleaned output into the loader step
    4. Saves the latest watermark value

    All file I/O and subprocess calls are mocked.

    :param client: Flask test client.
    :type client: flask.testing.FlaskClient
    :param app_module: Imported Flask app module.
    :type app_module: module
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: None
    :rtype: None
    """
    calls = []

    def fake_run_python_script(script_path, *args):
        """Record a fake script execution.

        :param script_path: Path of the script the app attempts to run.
        :type script_path: pathlib.Path | str
        :param args: Positional command-line arguments passed to the script.
        :type args: tuple[str, ...]
        :return: Fake successful process result.
        :rtype: types.SimpleNamespace
        """
        calls.append((Path(script_path), list(args)))
        return _completed_process(returncode=0, stdout="ok", stderr="")

    scraped_rows = [
        {"Date of Information Added to Grad Cafe": "January 15, 2026"},
        {"Date of Information Added to Grad Cafe": "January 16, 2026"},
    ]

    def fake_read_json_records(path):
        """Return fake scraped or cleaned records for the requested path.

        :param path: File path requested by the application.
        :type path: pathlib.Path | str
        :return: Fake records for known JSON paths, otherwise an empty list.
        :rtype: list[dict]
        """
        path = Path(path)

        if path == app_module.RAW_JSON_OUTPUT:
            return scraped_rows

        if path == app_module.CLEAN_JSON_OUTPUT:
            return scraped_rows

        return []

    saved_watermarks = []

    monkeypatch.setattr(app_module, "load_watermark", lambda: None)
    monkeypatch.setattr(app_module, "run_python_script", fake_run_python_script)
    monkeypatch.setattr(app_module, "read_json_records", fake_read_json_records)
    monkeypatch.setattr(app_module, "get_latest_added_on", lambda path: "2026-01-16")
    monkeypatch.setattr(
        app_module,
        "save_watermark",
        lambda value: saved_watermarks.append(value),
    )

    response = client.post("/pull-data")

    assert response.status_code == 200

    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["message"] == "Pull Data completed successfully"

    assert len(calls) == 3

    scrape_call = calls[0]
    clean_call = calls[1]
    load_call = calls[2]

    assert scrape_call[0] == app_module.SCRAPE_SCRIPT
    assert "--output" in scrape_call[1]
    assert str(app_module.RAW_JSON_OUTPUT) in scrape_call[1]

    assert clean_call[0] == app_module.CLEAN_SCRIPT
    assert str(app_module.RAW_JSON_OUTPUT) in clean_call[1]
    assert str(app_module.CLEAN_JSON_OUTPUT) in clean_call[1]

    assert load_call[0] == app_module.LOAD_SCRIPT
    assert "--input" in load_call[1]
    assert str(app_module.CLEAN_JSON_OUTPUT) in load_call[1]
    assert "--table" in load_call[1]
    assert "applicants" in load_call[1]

    assert saved_watermarks == ["2026-01-16"]

def test_post_update_analysis_returns_200_when_not_busy(
    client,
    app_module,
    monkeypatch,
):
    """Test that ``POST /update-analysis`` succeeds when not busy.

    This test verifies that the update-analysis endpoint returns HTTP 200 and
    triggers the query script when no pull-data request is in progress.

    :param client: Flask test client.
    :type client: flask.testing.FlaskClient
    :param app_module: Imported Flask app module.
    :type app_module: module
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: None
    :rtype: None
    """
    calls = []

    def fake_run_python_script(script_path, *args):
        """Record a fake update-analysis script execution.

        :param script_path: Path of the script being run.
        :type script_path: pathlib.Path | str
        :param args: Positional script arguments.
        :type args: tuple[str, ...]
        :return: Fake successful process result.
        :rtype: types.SimpleNamespace
        """
        calls.append((Path(script_path), list(args)))
        return _completed_process(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(app_module, "run_python_script", fake_run_python_script)
    monkeypatch.setattr(app_module, "pull_data_running", False, raising=False)

    response = client.post("/update-analysis")

    assert response.status_code == 200

    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["message"] == "Analysis updated successfully"

    assert calls == [(app_module.QUERY_SCRIPT, [])]

def test_post_update_analysis_returns_409_when_pull_is_in_progress(
    client,
    app_module,
    monkeypatch,
):
    """Test that ``POST /update-analysis`` is blocked while pull-data runs.

    This test verifies that when the server-side busy flag indicates a pull is
    already in progress, the update-analysis endpoint rejects the request with
    HTTP 409 and does not run the query script.

    :param client: Flask test client.
    :type client: flask.testing.FlaskClient
    :param app_module: Imported Flask app module.
    :type app_module: module
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: None
    :rtype: None
    """
    update_called = False

    def fake_run_python_script(script_path, *args):
        """Record whether the update script was incorrectly executed.

        :param script_path: Path of the script being run.
        :type script_path: pathlib.Path | str
        :param args: Positional script arguments.
        :type args: tuple[str, ...]
        :return: Fake successful process result.
        :rtype: types.SimpleNamespace
        """
        nonlocal update_called
        update_called = True
        return _completed_process(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(app_module, "run_python_script", fake_run_python_script)
    monkeypatch.setattr(app_module, "pull_data_running", True, raising=False)

    response = client.post("/update-analysis")

    assert response.status_code == 409

    payload = response.get_json()
    assert payload["ok"] is False
    assert "running" in payload["error"].lower()
    assert update_called is False

def test_post_pull_data_returns_409_when_busy(
    client,
    app_module,
    monkeypatch,
):
    """Test that ``POST /pull-data`` is blocked while another pull runs.

    This test verifies that when the server-side busy flag indicates pull-data
    is already running, the endpoint rejects a second pull request with HTTP
    409 and does not run any scripts.

    :param client: Flask test client.
    :type client: flask.testing.FlaskClient
    :param app_module: Imported Flask app module.
    :type app_module: module
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: None
    :rtype: None
    """
    pull_called = False

    def fake_run_python_script(script_path, *args):
        """Record whether the pull flow was incorrectly executed.

        :param script_path: Path of the script being run.
        :type script_path: pathlib.Path | str
        :param args: Positional script arguments.
        :type args: tuple[str, ...]
        :return: Fake successful process result.
        :rtype: types.SimpleNamespace
        """
        nonlocal pull_called
        pull_called = True
        return _completed_process(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(app_module, "run_python_script", fake_run_python_script)

    # Force the busy gate to reject the request before any script runs.
    monkeypatch.setattr(app_module, "pull_data_running", True, raising=False)

    response = client.post("/pull-data")

    assert response.status_code == 409

    payload = response.get_json()
    assert payload["ok"] is False
    assert "already in progress" in payload["error"].lower()
    assert pull_called is False