import json
import psycopg
from psycopg.types.json import Jsonb

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "studentcourses",
    "user": "postgres",
    "password": "mypassword",
}

JSON_FILE = "data.json"
TABLE_NAME = "raw_json_data"

def load_json_to_postgres():
    # Read JSON file
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Normalize single object -> list
    if isinstance(data, dict):
        data = [data]

    # Connect and insert
    with psycopg.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            # Create table if needed
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                    id SERIAL PRIMARY KEY,
                    payload JSONB NOT NULL,
                    loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Insert rows
            cur.executemany(
                f"INSERT INTO {TABLE_NAME} (payload) VALUES (%s)",
                [(Jsonb(row),) for row in data]
            )

        conn.commit()

    print(f"Inserted {len(data)} rows into {TABLE_NAME}")

if __name__ == "__main__":
    load_json_to_postgres()
