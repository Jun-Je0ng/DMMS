import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "app.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"


# Delete existing database if it exists
if DB_PATH.exists():
    DB_PATH.unlink()
    print(f"Deleted existing database: {DB_PATH}")


conn = sqlite3.connect(DB_PATH)

with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
    schema = f.read()

conn.executescript(schema)

conn.commit()
conn.close()


print(f"Database created successfully:")
print(f"  {DB_PATH}")