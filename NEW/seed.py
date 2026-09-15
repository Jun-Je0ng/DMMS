import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "app.db"


conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
    INSERT INTO mul (mul_id, mul_name)
    VALUES (1, 'MUL 1')
""")

cur.execute("""
    INSERT INTO users (user_id, user_name, user_type)
    VALUES (1, 'Test Worker', 'worker')
""")

conn.commit()
conn.close()

print("Test data inserted.")
