import sqlite3
import time

DB_PATH = "app.db"

def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def get_flight_id_from_bag_short_id(bag_short_id, mul_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT flight_id
        FROM bags
        WHERE bag_short_id = ? AND mul_id = ?
        ORDER BY bag_id DESC
        LIMIT 1
    """, (bag_short_id, mul_id))

    row = cur.fetchone()
    conn.close()

    return row[0] if row else None


def insert_bag_record(bag_short_id, mul_id, manual_flag, photo_path):
    conn = get_connection()
    cur = conn.cursor()

    # Determine flight_id if barcode exists
    if bag_short_id is not None:
        flight_id = get_flight_id_from_bag_short_id(bag_short_id, mul_id)
    else:
        flight_id = None

    timestamp = int(time.time())

    try:
        cur.execute("""
            INSERT INTO bags (bag_short_id, final_destination, flight_id, mul_id)
            VALUES (?, ?, ?, ?)
        """, (bag_short_id, None, flight_id, mul_id))

        bag_id = cur.lastrowid

        # Insert photo record into a separate table later if needed
        cur.execute("""
            UPDATE bags
            SET final_destination = ?, flight_id = ?
            WHERE bag_id = ?
        """, (None, flight_id, bag_id))

        conn.commit()

        print(f"[DB] Bag inserted: bag_id={bag_id}, short_id={bag_short_id}, flight_id={flight_id}")

    except sqlite3.IntegrityError as e:
        print(f"[DB ERROR] Integrity error: {e}")

    finally:
        conn.close()
