# Start sever and connect to database using psql command line tool -bash
#"/c/Program Files/PostgreSQL/18/bin/pg_ctl.exe" start -D "C:\PostgreSQL\18\data"
#"/c/Program Files/PostgreSQL/18/bin/psql.exe" -U postgres -h localhost -d studentcourses

import psycopg

DB_NAME = "applicant_db"

connection = psycopg.connect(
     user="postgres"
 )

connection.autocommit = True

#UTF8 to avoid encoding issues when inserting data with non-UTF8 characters into WIN1252 encoded PostgreSQL on Windows.
with connection.cursor() as cur:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
    exists = cur.fetchone()

    if not exists:
        cur.execute(f'CREATE DATABASE "{DB_NAME}" WITH ENCODING \'UTF8\' TEMPLATE template0;')
        print(f"Database {DB_NAME} created.")
    else:
        print(f"Database {DB_NAME} already exists.")

cur.close()
connection.close()

#Connect to the database we created to verify encoding and other settings.
connection = psycopg.connect(
dbname="applicant_db",
user="postgres"
)

with connection.cursor() as cur:
    print('Server encoding:',cur.execute('SHOW server_encoding;').fetchall())