# Start sever and connect to database using psql command line tool -bash
#"/c/Program Files/PostgreSQL/18/bin/pg_ctl.exe" start -D "C:\PostgreSQL\18\data"
#"/c/Program Files/PostgreSQL/18/bin/psql.exe" -U postgres -h localhost -d applicant_db

import subprocess
import os

from db_config import connect, DEFAULT_DBNAME

PG_CTL = os.environ.get("PG_CTL", r"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe")
PG_DATA = os.environ.get("PGDATA", r"C:\PostgreSQL\18\data")

def start_postgres():
    """Start the local PostgreSQL server if it is not already running.

    Skips startup when ``DATABASE_URL`` is set (remote database in use).

    :returns: ``None``
    :rtype: None
    :raises RuntimeError: If ``pg_ctl start`` exits with a non-zero code.
    """
    if os.environ.get("DATABASE_URL"):
        print("DATABASE_URL set; skipping local pg_ctl startup.")
        return

    status = subprocess.run(
        [PG_CTL, "status", "-D", PG_DATA],
        text=True,
        capture_output=True,
    )

    if status.returncode == 0:
        print("PostgreSQL server is already running.")
        return

    result = subprocess.run(
        [PG_CTL, "start", "-D", PG_DATA, "-w"],
        text=True,
        capture_output=True,
    )

    print("pg_ctl stdout:")
    print(result.stdout)
    print("pg_ctl stderr:")
    print(result.stderr)

    if result.returncode != 0:
        raise RuntimeError(f"PostgreSQL failed to start (exit {result.returncode})")

    print("PostgreSQL server started.")

if __name__ == "__main__":
    DB_NAME = DEFAULT_DBNAME
    start_postgres()

    connection = connect(dbname="postgres", connect_timeout=5)
    
    connection.autocommit = True

    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        exists = cur.fetchone()

        if not exists:
            cur.execute(f'CREATE DATABASE "{DB_NAME}" WITH ENCODING \'UTF8\' TEMPLATE template0;')
            print(f"Database {DB_NAME} created.")
        else:
            print(f"Database {DB_NAME} already exists.")

    connection.close()

    connection = connect(dbname=DB_NAME, connect_timeout=5)

    with connection.cursor() as cur:
        cur.execute("SHOW server_encoding;")
        print("Server encoding:", cur.fetchall())

    connection.close()