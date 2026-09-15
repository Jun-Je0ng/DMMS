import sqlite3
from pathlib import Path


# ============================================================
# DATABASE
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "app.db"


# ============================================================
# DEMO FLIGHTS
# ============================================================

flights = [
    {
        "flight_number": "DEMO101",
        "departure_time": "2026-09-15 14:00",
        "destination": "Melbourne",
        "gate_number": "A1",
    },
    {
        "flight_number": "DEMO202",
        "departure_time": "2026-09-15 14:30",
        "destination": "Brisbane",
        "gate_number": "A2",
    },
    {
        "flight_number": "DEMO303",
        "departure_time": "2026-09-15 15:00",
        "destination": "Perth",
        "gate_number": "B1",
    },
    {
        "flight_number": "DEMO404",
        "departure_time": "2026-09-15 15:30",
        "destination": "Adelaide",
        "gate_number": "B2",
    },
]


# ============================================================
# CONNECT
# ============================================================

conn = sqlite3.connect(DB_PATH)

conn.execute("PRAGMA foreign_keys = ON")

cur = conn.cursor()


try:

    # ========================================================
    # ENSURE MUL 1 EXISTS
    # ========================================================

    cur.execute("""
        INSERT OR IGNORE INTO mul (
            mul_id,
            mul_name
        )
        VALUES (
            1,
            'MUL 1'
        )
    """)


    # ========================================================
    # ENSURE TEST USER EXISTS
    # ========================================================

    cur.execute("""
        INSERT OR IGNORE INTO users (
            user_id,
            user_name,
            user_type
        )
        VALUES (
            1,
            'Test Worker',
            'worker'
        )
    """)


    # ========================================================
    # CREATE / FIND FLIGHTS
    # ========================================================

    created_flights = []


    for flight in flights:

        # Check whether this demo flight already exists.

        cur.execute("""
            SELECT flight_id
            FROM flights
            WHERE flight_number = ?
        """, (
            flight["flight_number"],
        ))

        row = cur.fetchone()


        if row:

            flight_id = row[0]

        else:

            cur.execute("""
                INSERT INTO flights (
                    flight_number,
                    departure_time,
                    destination,
                    gate_number
                )
                VALUES (?, ?, ?, ?)
            """, (
                flight["flight_number"],
                flight["departure_time"],
                flight["destination"],
                flight["gate_number"],
            ))

            flight_id = cur.lastrowid


        created_flights.append({
            "flight_id": flight_id,
            **flight
        })


    # ========================================================
    # CREATE BAG ROUTES
    #
    # 10 barcodes per flight.
    #
    # These are ROUTES only.
    #
    # No rows are inserted into:
    #
    #   bags
    #   bag_status
    #   bag_events
    #
    # ========================================================

    total_routes = 0


    for flight_index, flight in enumerate(
        created_flights,
        start=1
    ):

        for bag_number in range(1, 11):

            barcode = (
                f"B-DEMO{flight_index}"
                f"{bag_number:02d}"
            )

            cur.execute("""
                INSERT OR IGNORE INTO bag_routes (
                    barcode,
                    flight_id,
                    mul_id,
                    final_destination
                )
                VALUES (?, ?, ?, ?)
            """, (
                barcode,
                flight["flight_id"],
                1,
                flight["destination"],
            ))

            if cur.rowcount > 0:
                total_routes += 1


    # ========================================================
    # COMMIT
    # ========================================================

    conn.commit()


    # ========================================================
    # OUTPUT
    # ========================================================

    print()
    print("========================================")
    print("Demo data ready")
    print("========================================")
    print()

    for index, flight in enumerate(
        created_flights,
        start=1
    ):

        print(
            f"{flight['flight_number']} "
            f"(flight_id={flight['flight_id']})"
        )

        print(
            f"  Destination: {flight['destination']}"
        )

        print(
            f"  Gate: {flight['gate_number']}"
        )

        print(
            f"  Routes: "
            f"B-DEMO{index}01 "
            f"through "
            f"B-DEMO{index}10"
        )

        print()


    print(
        f"New routes inserted: {total_routes}"
    )

    print()
    print(
        "No bag records were created."
    )
    print(
        "Scan a B-DEMO barcode to create a bag."
    )
    print()


except Exception:

    conn.rollback()
    raise

finally:

    conn.close()