Testing Guide
=============

The test suite lives in ``tests/`` and uses **pytest**. ``pytest.ini`` requires
**100% code coverage** on ``src/``:

.. code-block:: ini

   addopts = -q --cov=src --cov-report=term-missing --cov-fail-under=100

Run all tests from the project root:

.. code-block:: powershell

   python -m pytest -v

Markers
-------

Markers are declared in ``pytest.ini`` and applied at the module level with
``pytestmark``. Use them to run focused subsets:

.. code-block:: powershell

   python -m pytest -v -m web
   python -m pytest -v -m db
   python -m pytest -v -m integration

.. list-table::
   :header-rows: 1
   :widths: 20 35 45

   * - Marker
     - Test files
     - What it covers
   * - ``web``
     - ``test_flask_page.py``, ``test_app_helpers.py``, ``test_app_remaining.py``, ``test_analysis_format.py``, ``test_buttons.py``, ``test_integration_end_to_end.py``
     - Flask routes, page rendering, and HTTP responses
   * - ``buttons``
     - ``test_buttons.py``
     - Pull Data and Update Analysis button behavior (busy gating, script calls)
   * - ``analysis``
     - ``test_analysis_format.py``
     - Formatting and rounding of analysis output in templates
   * - ``db``
     - ``test_query_data.py``, ``test_load_data.py``, ``test_db_insert.py``, ``test_integration_end_to_end.py``
     - Database schema, inserts, selects, and loader logic
   * - ``integration``
     - ``test_integration_end_to_end.py``, ``test_db_insert.py``
     - End-to-end pull → update → render flows against a live database

Tests can carry multiple markers. For example, integration tests are tagged
``integration``, ``db``, and ``web`` because they exercise all three layers.

Selectors
---------

Web tests locate and assert on rendered HTML using several strategies.

**Stable element identifiers**

``templates/base.html`` exposes ``data-testid`` attributes for the primary action
buttons:

- ``data-testid="pull-data-btn"`` — Pull Data button
- ``data-testid="update-analysis-btn"`` — Update Analysis button

Element IDs used by client-side JavaScript:

- ``#pull-data-btn``
- ``#update-analysis-btn``
- ``#pull-data-status`` — status message area after Pull Data

**CSS classes and structure**

- ``.question`` — each analysis question block in ``index.html``
- ``.nav-item``, ``.nav-buttons`` — navigation layout
- ``.content`` — main page content wrapper

**Assertion strategies in tests**

Most web tests use the Flask test client and inspect response bodies directly:

.. code-block:: python

   response = client.get("/analysis")
   page = response.get_data(as_text=True)
   assert "Pull Data" in page
   assert "Answer:" in page

Integration tests normalize visible text with **BeautifulSoup** to avoid
whitespace and HTML-tag noise:

.. code-block:: python

   from bs4 import BeautifulSoup

   soup = BeautifulSoup(html, "html.parser")
   page_text = " ".join(soup.get_text(" ", strip=True).split())

This helper (``_page_text`` in ``test_integration_end_to_end.py``) is used to
assert on formatted analysis values such as ``Acceptance rate: 66.67%``.

Route-level tests assert on registered URL rules rather than DOM selectors:

.. code-block:: python

   routes = {rule.rule for rule in app_module.app.url_map.iter_rules()}
   assert "/pull-data" in routes

Fixtures
--------

Fixtures are defined in individual test modules (there is no shared ``conftest.py``).
Each module adds ``src/`` to ``sys.path`` so ``app`` and other modules import cleanly.

**Common fixtures**

``app_module``
   Imports and returns the ``app`` module via ``importlib.import_module("app")``.
   Used wherever tests need to monkeypatch module-level helpers or inspect the Flask
   application instance.

``client``
   Creates a Flask test client with ``TESTING=True``. Variants exist with and without
   pre-mocked database calls depending on the test file.

``db_connection``
   Opens a live PostgreSQL connection to ``applicant_db`` using ``DATABASE_URL`` or
   default local credentials. Used by ``db`` and ``integration`` tests.

``test_table_name``
   Generates a unique table name (``applicants_test_<uuid>`` or
   ``applicants_integration_<uuid>``) to avoid collisions across test runs.

``managed_test_table``
   Creates an isolated applicants-style table before the test and drops it afterward.
   Lets loader and route tests write real rows without touching production data.

**Built-in pytest fixtures used throughout**

- ``monkeypatch`` — replace functions, attributes, and environment variables
- ``tmp_path`` — temporary directories for watermark and JSON file tests
- ``capsys`` — capture stdout for CLI ``main`` block tests

Test doubles
------------

The suite avoids external services during unit tests by substituting fakes at the
module boundary.

**``monkeypatch.setattr``**

The primary technique for replacing collaborators:

.. code-block:: python

   monkeypatch.setattr(app_module, "run_python_script", fake_run_python_script)
   monkeypatch.setattr(app_module, "get_db_connection", lambda: DummyConnection())
   monkeypatch.setattr(psycopg, "connect", lambda **kwargs: connection)

Environment variables are controlled the same way:

.. code-block:: python

   monkeypatch.setenv("DATABASE_URL", "postgresql://example-user@example-host/test_db")
   monkeypatch.delenv("DATABASE_URL", raising=False)

**Dummy connection and cursor classes**

Lightweight stand-ins record calls without opening a real database:

- ``DummyConnection`` / ``DummyCursor`` in ``test_query_data.py`` and
  ``test_create_database.py`` — simulate ``cursor()``, ``execute()``, ``fetchall()``, and ``close()``
- Inline ``DummyConnection`` in ``test_flask_page.py`` — minimal object with only a ``close()`` method

**Fake subprocess results**

``test_buttons.py`` and integration tests use ``types.SimpleNamespace`` to mimic
``subprocess.CompletedProcess``:

.. code-block:: python

   from types import SimpleNamespace

   def _completed_process(returncode=0, stdout="", stderr=""):
       return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

**Fake script runners**

``fake_run_python_script`` functions record which scripts were invoked and return
successful (or failing) process results without spawning real subprocesses.

**Fake JSON and watermark I/O**

Pull-data tests replace file helpers to return controlled scrape batches:

.. code-block:: python

   monkeypatch.setattr(app_module, "read_json_records", fake_read_json_records)
   monkeypatch.setattr(app_module, "load_watermark", lambda: None)
   monkeypatch.setattr(app_module, "save_watermark", lambda value: saved.append(value))

**Module reload for isolation**

``test_query_data.py`` uses ``import_fresh_query_data()`` to pop ``query_data`` from
``sys.modules`` and re-import after patching ``psycopg.connect``, ensuring each test
gets a clean module state.

**Live database in integration tests**

``test_integration_end_to_end.py`` and ``test_db_insert.py`` combine real PostgreSQL
connections with faked scrape/clean subprocesses. Only the ETL scripts are doubled;
the loader and query layer run against an isolated test table created by the
``managed_test_table`` fixture.

Running tests by layer
----------------------

.. code-block:: powershell

   # Fast unit tests (no live database required for most web tests)
   python -m pytest -v -m "web and not db"

   # Database unit tests
   python -m pytest -v -m "db and not integration"

   # Full integration (requires PostgreSQL and DATABASE_URL / PG* vars)
   python -m pytest -v -m integration

Ensure PostgreSQL is running and environment variables are set before running
``db`` or ``integration`` markers.
