import importlib
import re
import sys
from pathlib import Path

import pytest

# Add the src directory to sys.path so pytest can import app.py as "app".
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

pytestmark = [pytest.mark.analysis, pytest.mark.web]

@pytest.fixture
def app_module():
    """Import and return the Flask app module.

    This fixture provides access to the imported ``app`` module so tests can
    monkeypatch database and query behavior without loading a real database.

    :return: The imported ``app`` module.
    :rtype: module
    """
    return importlib.import_module("app")

@pytest.fixture
def client(app_module, monkeypatch):
    """Create a Flask test client with mocked query results.

    This fixture replaces the database connection helper so the index route can
    be rendered without opening a real PostgreSQL connection. The caller can
    still override ``get_all_query_results`` inside individual tests.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :yield: A Flask test client instance.
    :rtype: flask.testing.FlaskClient
    """
    class DummyConnection:
        """Minimal stand-in for a database connection object."""

        def close(self):
            """Pretend to close the connection.

            :return: None
            :rtype: None
            """
            pass

    monkeypatch.setattr(
        app_module,
        "get_db_connection",
        lambda dbname, user: DummyConnection(),
    )

    original_testing = app_module.app.config.get("TESTING", False)
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as test_client:
        yield test_client

    app_module.app.config.update(TESTING=original_testing)

def test_rendered_analysis_includes_answer_labels(client, app_module, monkeypatch):
    """Verify that rendered analysis includes ``Answer`` labels.

    This test mocks the analysis results returned to the index page and checks
    that the rendered HTML includes the ``Answer`` label shown to users.

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
        "get_all_query_results",
        lambda connection: [
            ("Question 1", "Answer: 42"),
            ("Question 2", "Answer: 12.34"),
        ],
    )

    response = client.get("/analysis")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Answer:" in page

def test_percentage_values_are_formatted_with_two_decimals(client, app_module, monkeypatch):
    """Verify that percentage values render with exactly two decimal places.

    This test uses a percentage-like analysis result and checks that the page
    renders the rounded two-decimal form instead of the unrounded value.

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
        "get_all_query_results",
        lambda connection: [
            #query_data.py rounds percentages to 2 decimla places; enforced there
            ("Question 1", ("Percent International:", 12.35)),
        ],
    )

    response = client.get("/analysis")
    page = response.get_data(as_text=True)

    assert response.status_code == 200

    # Expected rounded output.
    assert "12.35" in page

    # The raw unrounded value should not appear.
    assert "12.3456" not in page

def test_percentage_values_keep_trailing_zero_to_two_decimals(client, app_module, monkeypatch):
    """Verify that percentage values keep trailing zeros when needed.

    This test checks that a percentage-like value such as ``7.5`` is rendered
    as ``7.50`` so the display is consistently shown with two decimal places.

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
        "get_all_query_results",
        lambda connection: [
            ("Question 1", ("Acceptance Percent:", 7.5)),
        ],
    )

    response = client.get("/analysis")
    page = response.get_data(as_text=True)

    assert response.status_code == 200

    # Expect fixed two-decimal formatting.
    assert re.search(r"\b7\.50\b", page)

    # Avoid accepting a single-decimal rendering as correct.
    assert not re.search(r"\b7\.5\b(?!0)", page)
