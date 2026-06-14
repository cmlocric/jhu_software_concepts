"""Shared PostgreSQL connection settings for the application."""

from __future__ import annotations

import os

import psycopg

DEFAULT_DBNAME = "applicant_db"


def get_database_url(dbname: str | None = None) -> str:
    """Build a PostgreSQL connection URL from environment variables.

    :param dbname: Optional database name override.
    :type dbname: str | None
    :returns: Connection URL suitable for ``psycopg.connect(conninfo=...)``.
    :rtype: str
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    user = os.environ.get("PGUSER") or os.environ.get("POSTGRES_USER") or "postgres"
    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    database = dbname or os.environ.get("PGDATABASE", DEFAULT_DBNAME)
    return f"postgresql://{user}@{host}:{port}/{database}"


def get_connect_kwargs(dbname: str | None = None, **overrides) -> dict:
    """Return psycopg connection keyword arguments from the environment.

    :param dbname: Optional database name override.
    :type dbname: str | None
    :param overrides: Additional connection keyword arguments.
    :type overrides: object
    :returns: Keyword arguments for ``psycopg.connect``.
    :rtype: dict
    """
    url = os.environ.get("DATABASE_URL")
    if url and not overrides and dbname is None:
        return {"conninfo": url}

    kwargs = {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "dbname": dbname or os.environ.get("PGDATABASE", DEFAULT_DBNAME),
        "user": os.environ.get("PGUSER") or os.environ.get("POSTGRES_USER") or "postgres",
    }
    kwargs.update(overrides)
    return kwargs


def connect(dbname: str | None = None, **overrides) -> psycopg.Connection:
    """Open a PostgreSQL connection using environment-based settings.

    :param dbname: Optional database name override.
    :type dbname: str | None
    :param overrides: Additional connection keyword arguments.
    :type overrides: object
    :returns: Active psycopg connection.
    :rtype: psycopg.Connection
    """
    kwargs = get_connect_kwargs(dbname=dbname, **overrides)
    return psycopg.connect(**kwargs)
