import sqlite3
import time
from pathlib import Path


# ============================================================
# DATABASE LOCATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "app.db"


# ============================================================
# CONNECTION
# ============================================================

def get_connection():
    conn = sqlite3.connect(str(DB_PATH))

    # Enable foreign-key enforcement for this connection.
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


# ============================================================
# SHORT ID
# ============================================================

def get_next_short_id(mul_id):
    """
    Return the next human-friendly bag number for a MUL.

    Example:

        MUL 1:
            short_id 1
            short_id 2
            short_id 3

        MUL 2:
            short_id 1
            short_id 2
            short_id 3

    Short IDs are therefore unique within each MUL,
    but can be the same across different MULs.
    """

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT COALESCE(MAX(short_id), 0) + 1
            FROM bags
            WHERE mul_id = ?
        """, (mul_id,))

        row = cur.fetchone()

        return row[0]

    finally:
        conn.close()


# ============================================================
# INSERT BAG
# ============================================================

def insert_bag_record(
    mul_id,
    bag_short_id=None,
    barcode=None,
    flight_id=None,
    final_destination=None,
    manual_flag=False,
    photo_path=None,
    initial_status="scanned",
):

    conn = get_connection()
    cur = conn.cursor()

    timestamp = int(time.time())
    

    try:


        if bag_short_id is None:
            cur.execute("""
                SELECT COALESCE(MAX(short_id), 0) + 1
                FROM bags
                WHERE mul_id = ?
            """, (mul_id,))
    
            bag_short_id = cur.fetchone()[0]

        # ----------------------------------------------------
        # Insert bag
        # ----------------------------------------------------

        cur.execute("""
            INSERT INTO bags (
                short_id,
                barcode,
                final_destination,
                flight_id,
                mul_id,
                photo_path,
                scanned_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            str(bag_short_id),
            barcode,
            final_destination,
            flight_id,
            mul_id,
            photo_path,
            timestamp,
        ))

        bag_id = cur.lastrowid

        # ----------------------------------------------------
        # Initial status
        # ----------------------------------------------------

        cur.execute("""
            INSERT INTO bag_status (
                bag_id,
                status
            )
            VALUES (?, ?)
        """, (
            bag_id,
            initial_status
        ))

        # ----------------------------------------------------
        # Event history
        # ----------------------------------------------------

        event_type = "manual_scan" if manual_flag else "scanned"

        details = (
            f"Barcode scanned: {barcode}"
            if barcode
            else "No barcode detected"
        )

        cur.execute("""
            INSERT INTO bag_events (
                bag_id,
                event_type,
                user_id,
                timestamp,
                details
            )
            VALUES (?, ?, NULL, ?, ?)
        """, (
            bag_id,
            event_type,
            timestamp,
            details,
        ))

        conn.commit()

        print(
            f"[DB] Bag inserted: "
            f"bag_id={bag_id}, "
            f"short_id={bag_short_id}, "
            f"barcode={barcode}, "
            f"mul_id={mul_id}, "
            f"status={initial_status}, "
            f"photo={photo_path}"
        )

        return bag_id

    except sqlite3.IntegrityError as e:
        conn.rollback()

        print(
            f"[DB ERROR] Could not insert bag "
            f"{bag_short_id}: {e}"
        )

        return None

    finally:
        conn.close()


# ============================================================
# BAG LOOKUP
# ============================================================

def get_bag_by_short_id(short_id, mul_id):
    """
    Find a bag using the operator-facing short ID.
    """

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT
                bag_id,
                barcode,
                short_id,
                final_destination,
                flight_id,
                mul_id,
                photo_path,
                scanned_at
            FROM bags
            WHERE short_id = ?
              AND mul_id = ?
        """, (
            short_id,
            mul_id,
        ))

        return cur.fetchone()

    finally:
        conn.close()


def get_bag_by_barcode(barcode):
    """
    Find a bag using its actual physical barcode.
    """

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT
                bag_id,
                barcode,
                short_id,
                final_destination,
                flight_id,
                mul_id,
                photo_path,
                scanned_at
            FROM bags
            WHERE barcode = ?
        """, (barcode,))

        return cur.fetchone()

    finally:
        conn.close()


def get_bag_route(barcode):
    """
    Find the permanent routing configuration
    for a barcode.
    """

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT
                flight_id,
                mul_id,
                final_destination
            FROM bag_routes
            WHERE barcode = ?
        """, (barcode,))

        row = cur.fetchone()

        if row is None:
            return None

        return {
            "flight_id": row[0],
            "mul_id": row[1],
            "final_destination": row[2],
        }

    finally:
        conn.close()
