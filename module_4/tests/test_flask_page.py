import importlib
import sys
from pathlib import Path

import pytest
from flask import Flask

# Add the src directory to sys.path so pytest can import app.py as "app".
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

pytestmark = [pytest.mark.web]

@pytest.fixture
def app_module():
    """Import and return the Flask app module.

    This fixture provides access to the imported ``app`` module so tests can
    inspect the Flask application instance and monkeypatch module-level helpers.

    :return: The imported ``app`` module.
    :rtype: module
    """
    return importlib.import_module("app")

@pytest.fixture
def client(app_module, monkeypatch):
    """Create a Flask test client with database-dependent calls mocked.

    This fixture replaces the database connection function and query helper so
    the index route can be tested without opening a real database connection.

    :param app_module: The imported Flask app module.
    :type app_module: module
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :yield: A Flask test client instance.
    :rtype: flask.testing.FlaskClient
    """
    class DummyConnection:
        """Minimal stand-in for a database connection object.

        The application closes the connection after use, so the fake object only
        needs a ``close`` method.

        :return: None
        :rtype: None
        """

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

    monkeypatch.setattr(
        app_module,
        "get_all_query_results",
        lambda connection: [("Question 1", "Answer: 42")],
    )

    app_module.app.config.update(
        TESTING=True,
    )

    with app_module.app.test_client() as test_client:
        yield test_client

def test_flask_app_is_created_and_expected_routes_exist(app_module):
    """Verify that the Flask app is created and expected routes exist.

    This test confirms that:
    - ``app_module.app`` is a Flask application instance
    - testing mode is disabled by default
    - the expected routes are registered on the URL map

    :param app_module: The imported Flask app module.
    :type app_module: module
    :return: None
    :rtype: None
    """
    assert isinstance(app_module.app, Flask)
    assert app_module.app.config["TESTING"] is False

    routes = {rule.rule for rule in app_module.app.url_map.iter_rules()}

    assert "/" in routes
    assert "/pull-data" in routes
    assert "/update-analysis" in routes

def test_index_page_loads_successfully(client):
    """Verify that the index page loads successfully.

    This test sends a GET request to the home route and confirms the response
    status code is HTTP 200.

    :param client: Flask test client.
    :type client: flask.testing.FlaskClient
    :return: None
    :rtype: None
    """
    response = client.get("/")

    assert response.status_code == 200

def test_index_page_contains_required_buttons_and_text(client):
    """Verify that the index page contains required UI text.

    This test confirms that the rendered home page includes the expected button
    labels and analysis text shown to the user.

    :param client: Flask test client.
    :type client: flask.testing.FlaskClient
    :return: None
    :rtype: None
    """
    response = client.get("/")
    page = response.get_data(as_text=True)

    assert "Pull Data" in page
    assert "Update Analysis" in page
    assert "Analysis" in page
    assert "Answer:" in page