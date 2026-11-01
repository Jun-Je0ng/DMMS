"""
JSON API for creating and managing test data (flights, CANs, MULs, users,
bag routes and bags) without relying on seed.py.

Registered in web.py:

    from api import api_bp
    app.register_blueprint(api_bp)

All endpoints live under /api/v1 and accept / return JSON.
See API.md for examples.
"""

import sqlite3

from flask import Blueprint, jsonify, request

from database.db import get_connection, insert_bag_record


api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


BAG_STATUSES = (
    "scanned", "assigned", "in_can", "loaded",
    "needs_attention", "resolved", "rejected",
)
USER_TYPES = ("admin", "worker")


# ============================================================
# HELPERS
# ============================================================

class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


@api_bp.errorhandler(ApiError)
def _handle_api_error(e):
    return jsonify({"error": e.message}), e.status


@api_bp.errorhandler(sqlite3.IntegrityError)
def _handle_integrity_error(e):
    return jsonify({"error": f"Database constraint failed: {e}"}), 409


def db():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    return conn


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object")
    return data


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def text(data, key, required=False):
    value = data.get(key)
    if value is None:
        if required:
            raise ApiError(f"'{key}' is required")
        return None
    value = str(value).strip()
    if required and not value:
        raise ApiError(f"'{key}' cannot be empty")
    return value or None


def integer(data, key, required=False):
    value = data.get(key)
    if value is None or value == "":
        if required:
            raise ApiError(f"'{key}' is required")
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(f"'{key}' must be an integer")


def require_exists(cur, table, column, value, label):
    if value is None:
        return
    cur.execute(f"SELECT 1 FROM {table} WHERE {column} = ?", (value,))
    if cur.fetchone() is None:
        raise ApiError(f"{label} {value} does not exist", 404)


def resolve_flight(cur, data):
    """Accept flight_id, or flight_number (looked up)."""
    flight_id = integer(data, "flight_id")
    if flight_id is not None:
        require_exists(cur, "flights", "flight_id", flight_id, "Flight")
        return flight_id

    number = text(data, "flight_number")
    if number:
        cur.execute(
            "SELECT flight_id FROM flights WHERE flight_number = ? "
            "ORDER BY flight_id DESC LIMIT 1", (number,))
        row = cur.fetchone()
        if row is None:
            raise ApiError(f"No flight with number '{number}'", 404)
        return row["flight_id"]
    return None


def default_mul(cur, data):
    mul_id = integer(data, "mul_id")
    if mul_id is None:
        mul_id = 1
    require_exists(cur, "mul", "mul_id", mul_id, "MUL")
    return mul_id


def make_flight(cur, data):
    cur.execute("""
        INSERT INTO flights (flight_number, departure_time, destination, gate_number)
        VALUES (?, ?, ?, ?)
    """, (
        text(data, "flight_number", required=True),
        text(data, "departure_time"),
        text(data, "destination"),
        text(data, "gate_number"),
    ))
    return cur.lastrowid


def make_can(cur, mul_id, flight_id):
    cur.execute("INSERT INTO cans (mul_id, flight_id) VALUES (?, ?)",
                (mul_id, flight_id))
    return cur.lastrowid


def barcode_list(data):
    """
    Either an explicit list:   {"barcodes": ["B-1", "B-2"]}
    or a generated range:      {"prefix": "B-DEMO1", "count": 10,
                                "start": 1, "width": 2}
    -> B-DEMO101 ... B-DEMO110
    """
    if isinstance(data.get("barcodes"), list):
        return [str(b).strip() for b in data["barcodes"] if str(b).strip()]

    if data.get("prefix") is not None and data.get("count") is not None:
        prefix = str(data["prefix"])
        count = integer(data, "count", required=True)
        start = integer(data, "start") or 1
        width = integer(data, "width") or 2
        if not 0 < count <= 5000:
            raise ApiError("'count' must be between 1 and 5000")
        return [f"{prefix}{n:0{width}d}" for n in range(start, start + count)]

    raise ApiError("Provide 'barcodes' (list) or 'prefix' + 'count'")


def make_routes(cur, barcodes, flight_id, mul_id, destination):
    created, skipped = [], []
    for code in barcodes:
        cur.execute("""
            INSERT OR IGNORE INTO bag_routes
                (barcode, flight_id, mul_id, final_destination)
            VALUES (?, ?, ?, ?)
        """, (code, flight_id, mul_id, destination))
        (created if cur.rowcount else skipped).append(code)
    return created, skipped


def flight_destination(cur, flight_id):
    if flight_id is None:
        return None
    cur.execute("SELECT destination FROM flights WHERE flight_id = ?",
                (flight_id,))
    row = cur.fetchone()
    return row["destination"] if row else None


# ============================================================
# FLIGHTS
# ============================================================

@api_bp.get("/flights")
def list_flights():
    conn = db()
    try:
        cur = conn.execute("SELECT * FROM flights ORDER BY departure_time, flight_id")
        return jsonify(rows(cur))
    finally:
        conn.close()


@api_bp.get("/flights/<int:flight_id>")
def get_flight(flight_id):
    conn = db()
    try:
        cur = conn.execute("SELECT * FROM flights WHERE flight_id = ?", (flight_id,))
        row = cur.fetchone()
        if row is None:
            raise ApiError("Flight not found", 404)
        return jsonify(dict(row))
    finally:
        conn.close()


@api_bp.post("/flights")
def create_flights():
    """Body: one flight object, or a list of them."""
    payload = request.get_json(silent=True)
    items = payload if isinstance(payload, list) else [payload]
    if not items or not all(isinstance(i, dict) for i in items):
        raise ApiError("Body must be a flight object or a list of flight objects")

    conn = db()
    try:
        cur = conn.cursor()
        ids = [make_flight(cur, item) for item in items]
        conn.commit()
        out = [dict(cur.execute("SELECT * FROM flights WHERE flight_id = ?", (i,)).fetchone())
               for i in ids]
        return jsonify(out if isinstance(payload, list) else out[0]), 201
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@api_bp.route("/flights/<int:flight_id>", methods=["PATCH", "PUT"])
def update_flight(flight_id):
    data = body()
    fields = {k: text(data, k) for k in
              ("flight_number", "departure_time", "destination", "gate_number")
              if k in data}
    if not fields:
        raise ApiError("No updatable fields supplied")
    if "flight_number" in fields and not fields["flight_number"]:
        raise ApiError("'flight_number' cannot be empty")

    conn = db()
    try:
        sets = ", ".join(f"{k} = ?" for k in fields)
        cur = conn.execute(f"UPDATE flights SET {sets} WHERE flight_id = ?",
                           (*fields.values(), flight_id))
        if cur.rowcount == 0:
            raise ApiError("Flight not found", 404)
        conn.commit()
        return jsonify(dict(conn.execute(
            "SELECT * FROM flights WHERE flight_id = ?", (flight_id,)).fetchone()))
    finally:
        conn.close()


@api_bp.delete("/flights/<int:flight_id>")
def delete_flight(flight_id):
    conn = db()
    try:
        cur = conn.execute("DELETE FROM flights WHERE flight_id = ?", (flight_id,))
        if cur.rowcount == 0:
            raise ApiError("Flight not found", 404)
        conn.commit()
        return jsonify({"deleted": flight_id})
    finally:
        conn.close()


# ============================================================
# MULS
# ============================================================

@api_bp.get("/muls")
def list_muls():
    conn = db()
    try:
        return jsonify(rows(conn.execute("SELECT * FROM mul ORDER BY mul_id")))
    finally:
        conn.close()


@api_bp.post("/muls")
def create_mul():
    data = body()
    name = text(data, "mul_name", required=True)
    mul_id = integer(data, "mul_id")
    conn = db()
    try:
        if mul_id is None:
            cur = conn.execute("INSERT INTO mul (mul_name) VALUES (?)", (name,))
        else:
            cur = conn.execute("INSERT INTO mul (mul_id, mul_name) VALUES (?, ?)",
                               (mul_id, name))
        conn.commit()
        return jsonify({"mul_id": cur.lastrowid, "mul_name": name}), 201
    finally:
        conn.close()


@api_bp.delete("/muls/<int:mul_id>")
def delete_mul(mul_id):
    conn = db()
    try:
        cur = conn.execute("DELETE FROM mul WHERE mul_id = ?", (mul_id,))
        if cur.rowcount == 0:
            raise ApiError("MUL not found", 404)
        conn.commit()
        return jsonify({"deleted": mul_id})
    finally:
        conn.close()


# ============================================================
# CANS
# ============================================================

CAN_SELECT = """
    SELECT c.can_id, c.mul_id, c.flight_id,
           f.flight_number, f.destination
    FROM cans c
    LEFT JOIN flights f ON f.flight_id = c.flight_id
"""


@api_bp.get("/cans")
def list_cans():
    mul_id = request.args.get("mul_id", type=int)
    conn = db()
    try:
        if mul_id is not None:
            cur = conn.execute(CAN_SELECT + " WHERE c.mul_id = ? ORDER BY c.can_id",
                               (mul_id,))
        else:
            cur = conn.execute(CAN_SELECT + " ORDER BY c.can_id")
        return jsonify(rows(cur))
    finally:
        conn.close()


@api_bp.post("/cans")
def create_cans():
    """
    Body: {"mul_id": 1, "flight_id": 2}            (or "flight_number")
    Optional "count": N creates N identical CANs.
    Omit mul_id to leave the CAN unassigned ("inactive").
    """
    data = body()
    count = integer(data, "count") or 1
    if not 0 < count <= 100:
        raise ApiError("'count' must be between 1 and 100")

    conn = db()
    try:
        cur = conn.cursor()
        mul_id = integer(data, "mul_id")
        require_exists(cur, "mul", "mul_id", mul_id, "MUL")
        flight_id = resolve_flight(cur, data)
        ids = [make_can(cur, mul_id, flight_id) for _ in range(count)]
        conn.commit()
        out = rows(conn.execute(
            CAN_SELECT + f" WHERE c.can_id IN ({','.join('?' * len(ids))})", ids))
        return jsonify(out if count > 1 else out[0]), 201
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@api_bp.route("/cans/<int:can_id>", methods=["PATCH", "PUT"])
def update_can(can_id):
    data = body()
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM cans WHERE can_id = ?", (can_id,))
        existing = cur.fetchone()
        if existing is None:
            raise ApiError("CAN not found", 404)

        mul_id = existing["mul_id"]
        flight_id = existing["flight_id"]

        if "mul_id" in data:
            mul_id = integer(data, "mul_id")
            require_exists(cur, "mul", "mul_id", mul_id, "MUL")
        if "flight_id" in data or "flight_number" in data:
            flight_id = resolve_flight(cur, data)

        cur.execute("UPDATE cans SET mul_id = ?, flight_id = ? WHERE can_id = ?",
                    (mul_id, flight_id, can_id))
        conn.commit()
        return jsonify(dict(conn.execute(
            CAN_SELECT + " WHERE c.can_id = ?", (can_id,)).fetchone()))
    finally:
        conn.close()


@api_bp.delete("/cans/<int:can_id>")
def delete_can(can_id):
    conn = db()
    try:
        cur = conn.execute("DELETE FROM cans WHERE can_id = ?", (can_id,))
        if cur.rowcount == 0:
            raise ApiError("CAN not found", 404)
        conn.commit()
        return jsonify({"deleted": can_id})
    finally:
        conn.close()


# ============================================================
# USERS
# ============================================================

@api_bp.get("/users")
def list_users():
    conn = db()
    try:
        return jsonify(rows(conn.execute("SELECT * FROM users ORDER BY user_id")))
    finally:
        conn.close()


@api_bp.post("/users")
def create_user():
    data = body()
    name = text(data, "user_name", required=True)
    user_type = text(data, "user_type") or "worker"
    if user_type not in USER_TYPES:
        raise ApiError(f"'user_type' must be one of {list(USER_TYPES)}")
    conn = db()
    try:
        cur = conn.execute("INSERT INTO users (user_name, user_type) VALUES (?, ?)",
                           (name, user_type))
        conn.commit()
        return jsonify({"user_id": cur.lastrowid, "user_name": name,
                        "user_type": user_type}), 201
    finally:
        conn.close()


# ============================================================
# BAG ROUTES  (barcode -> flight / MUL / destination lookups)
# These are what the scanner looks up; a bag row is created on scan.
# ============================================================

@api_bp.get("/bag-routes")
def list_bag_routes():
    flight_id = request.args.get("flight_id", type=int)
    conn = db()
    try:
        sql = """
            SELECT r.barcode, r.flight_id, f.flight_number,
                   r.mul_id, r.final_destination
            FROM bag_routes r
            LEFT JOIN flights f ON f.flight_id = r.flight_id
        """
        if flight_id is not None:
            cur = conn.execute(sql + " WHERE r.flight_id = ? ORDER BY r.barcode",
                               (flight_id,))
        else:
            cur = conn.execute(sql + " ORDER BY r.barcode")
        return jsonify(rows(cur))
    finally:
        conn.close()


@api_bp.post("/bag-routes")
def create_bag_routes():
    """
    Body: {"flight_number": "QF401", "mul_id": 1, "prefix": "B-QF", "count": 10}
      or  {"flight_id": 2, "barcodes": ["ABC123", "DEF456"]}
    final_destination defaults to the flight's destination.
    Existing barcodes are skipped, not overwritten.
    """
    data = body()
    conn = db()
    try:
        cur = conn.cursor()
        flight_id = resolve_flight(cur, data)
        mul_id = default_mul(cur, data)
        destination = text(data, "final_destination") or flight_destination(cur, flight_id)
        created, skipped = make_routes(cur, barcode_list(data),
                                       flight_id, mul_id, destination)
        conn.commit()
        return jsonify({"created": created, "skipped_existing": skipped,
                        "flight_id": flight_id, "mul_id": mul_id,
                        "final_destination": destination}), 201
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@api_bp.delete("/bag-routes/<path:barcode>")
def delete_bag_route(barcode):
    conn = db()
    try:
        cur = conn.execute("DELETE FROM bag_routes WHERE barcode = ?", (barcode,))
        if cur.rowcount == 0:
            raise ApiError("Route not found", 404)
        conn.commit()
        return jsonify({"deleted": barcode})
    finally:
        conn.close()


# ============================================================
# BAGS  (actual scanned bags -- same path the hardware uses)
# ============================================================

@api_bp.get("/bags")
def list_bags():
    mul_id = request.args.get("mul_id", type=int)
    status = request.args.get("status")
    clauses, params = [], []
    if mul_id is not None:
        clauses.append("b.mul_id = ?"); params.append(mul_id)
    if status:
        clauses.append("s.status = ?"); params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    conn = db()
    try:
        cur = conn.execute(f"""
            SELECT b.bag_id, b.barcode, b.short_id, b.final_destination,
                   b.flight_id, f.flight_number, b.mul_id, b.photo_path,
                   b.scanned_at, s.status, s.can_id
            FROM bags b
            LEFT JOIN bag_status s ON s.bag_id = b.bag_id
            LEFT JOIN flights f ON f.flight_id = b.flight_id
            {where}
            ORDER BY b.bag_id DESC
        """, params)
        return jsonify(rows(cur))
    finally:
        conn.close()


@api_bp.post("/bags")
def create_bag():
    """
    Simulate a bag arriving on the line.

    Body (all optional except that something identifies the bag):
      {
        "barcode": "B-DEMO101",   # if it has a bag_route, flight/MUL/destination
                                  # are filled in from it unless overridden
        "mul_id": 1,
        "flight_id": 2,           # or "flight_number"
        "final_destination": "Perth",
        "status": "scanned",      # scanned|assigned|in_can|loaded|needs_attention|...
        "can_id": 3,
        "photo_path": "bag_photos/x.jpg"
      }
    No barcode -> status defaults to "needs_attention".
    """
    data = body()
    conn = db()
    try:
        cur = conn.cursor()
        barcode = text(data, "barcode")

        route = None
        if barcode:
            cur.execute("SELECT * FROM bag_routes WHERE barcode = ?", (barcode,))
            route = cur.fetchone()

        flight_id = resolve_flight(cur, data)
        if flight_id is None and route:
            flight_id = route["flight_id"]

        mul_id = integer(data, "mul_id")
        if mul_id is None:
            mul_id = route["mul_id"] if route else 1
        require_exists(cur, "mul", "mul_id", mul_id, "MUL")

        destination = text(data, "final_destination")
        if destination is None:
            destination = (route["final_destination"] if route
                           else flight_destination(cur, flight_id))

        status = text(data, "status") or ("scanned" if barcode else "needs_attention")
        if status not in BAG_STATUSES:
            raise ApiError(f"'status' must be one of {list(BAG_STATUSES)}")

        can_id = integer(data, "can_id")
        require_exists(cur, "cans", "can_id", can_id, "CAN")
    finally:
        conn.close()

    bag_id = insert_bag_record(
        mul_id=mul_id,
        barcode=barcode,
        flight_id=flight_id,
        final_destination=destination,
        photo_path=text(data, "photo_path"),
        initial_status=status,
        reason="Created via API",
    )
    if bag_id is None:
        raise ApiError("Could not create bag (duplicate barcode?)", 409)

    if can_id is not None:
        conn = db()
        try:
            conn.execute("UPDATE bag_status SET can_id = ? WHERE bag_id = ?",
                         (can_id, bag_id))
            conn.commit()
        finally:
            conn.close()

    conn = db()
    try:
        row = conn.execute("""
            SELECT b.*, s.status, s.can_id
            FROM bags b JOIN bag_status s ON s.bag_id = b.bag_id
            WHERE b.bag_id = ?
        """, (bag_id,)).fetchone()
        return jsonify(dict(row)), 201
    finally:
        conn.close()


@api_bp.delete("/bags/<int:bag_id>")
def delete_bag(bag_id):
    conn = db()
    try:
        cur = conn.execute("DELETE FROM bags WHERE bag_id = ?", (bag_id,))
        if cur.rowcount == 0:
            raise ApiError("Bag not found", 404)
        conn.commit()
        return jsonify({"deleted": bag_id})
    finally:
        conn.close()


# ============================================================
# ONE-SHOT SCENARIO SETUP  (replaces seed.py)
# ============================================================

@api_bp.post("/setup")
def setup_scenario():
    """
    Build a whole test scenario in one call.

    {
      "mul_id": 1,                     # default 1 (created if missing)
      "flights": [
        {"flight_number": "QF401", "destination": "Perth",
         "departure_time": "2026-10-30 14:00", "gate_number": "A1",
         "cans": 1,                    # CANs to create for this flight (default 1)
         "bags": 10,                   # bag routes to generate (default 0)
         "barcode_prefix": "B-QF401-"  # default "B-<flight_number>-"
        }
      ]
    }
    Existing flights (same flight_number) are reused rather than duplicated.
    """
    data = body()
    flights = data.get("flights")
    if not isinstance(flights, list) or not flights:
        raise ApiError("'flights' must be a non-empty list")

    conn = db()
    try:
        cur = conn.cursor()
        mul_id = integer(data, "mul_id") or 1
        cur.execute("INSERT OR IGNORE INTO mul (mul_id, mul_name) VALUES (?, ?)",
                    (mul_id, f"MUL {mul_id}"))

        summary = []
        for spec in flights:
            if not isinstance(spec, dict):
                raise ApiError("Each flight must be an object")
            number = text(spec, "flight_number", required=True)

            cur.execute("SELECT flight_id FROM flights WHERE flight_number = ?",
                        (number,))
            row = cur.fetchone()
            reused = row is not None
            flight_id = row["flight_id"] if reused else make_flight(cur, spec)

            can_count = integer(spec, "cans")
            can_count = 1 if can_count is None else can_count
            can_ids = [make_can(cur, mul_id, flight_id) for _ in range(can_count)]

            bag_count = integer(spec, "bags") or 0
            prefix = spec.get("barcode_prefix") or f"B-{number}-"
            created = []
            if bag_count:
                dest = text(spec, "destination") or flight_destination(cur, flight_id)
                codes = barcode_list({"prefix": prefix, "count": bag_count,
                                      "width": spec.get("barcode_width", 2)})
                created, _ = make_routes(cur, codes, flight_id, mul_id, dest)

            summary.append({
                "flight_id": flight_id, "flight_number": number,
                "flight_reused": reused, "can_ids": can_ids,
                "barcodes": created,
            })
        conn.commit()
        return jsonify({"mul_id": mul_id, "flights": summary}), 201
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# TAG REGISTRATION  (scan a bag tag -> attach it to a flight)
# Used by the /admin/register page.
# ============================================================

import time
from pathlib import Path

# While this file is fresh (<10s old), the hardware barcode listener
# ignores keystrokes, so registering tags doesn't create live bags.
# The register page refreshes it with a heartbeat every few seconds.
REGISTER_FLAG = Path(__file__).resolve().parent / ".register_mode"


@api_bp.post("/register-mode")
def register_mode_on():
    REGISTER_FLAG.touch()
    return jsonify({"register_mode": True})


@api_bp.delete("/register-mode")
def register_mode_off():
    try:
        REGISTER_FLAG.unlink()
    except FileNotFoundError:
        pass
    return jsonify({"register_mode": False})


@api_bp.post("/register-scan")
def register_scan():
    """
    Body: {"barcode": "0081234567", "flight_id": 3, "mul_id": 1}

    Creates (or re-points) the bag_route for this tag. Scanning the same
    tag again with a different flight reassigns it.
    Returns status: "registered" | "unchanged" | "reassigned".
    """
    data = body()
    barcode = text(data, "barcode", required=True)

    conn = db()
    try:
        cur = conn.cursor()
        flight_id = integer(data, "flight_id", required=True)
        require_exists(cur, "flights", "flight_id", flight_id, "Flight")
        mul_id = default_mul(cur, data)
        destination = flight_destination(cur, flight_id)

        cur.execute("""
            SELECT r.flight_id, r.mul_id, f.flight_number
            FROM bag_routes r
            LEFT JOIN flights f ON f.flight_id = r.flight_id
            WHERE r.barcode = ?
        """, (barcode,))
        old = cur.fetchone()

        cur.execute("""
            INSERT OR REPLACE INTO bag_routes
                (barcode, flight_id, mul_id, final_destination)
            VALUES (?, ?, ?, ?)
        """, (barcode, flight_id, mul_id, destination))

        if old is None:
            status = "registered"
        elif old["flight_id"] == flight_id and old["mul_id"] == mul_id:
            status = "unchanged"
        else:
            status = "reassigned"

        cur.execute("SELECT 1 FROM bags WHERE barcode = ?", (barcode,))
        already_on_line = cur.fetchone() is not None

        cur.execute("SELECT flight_number FROM flights WHERE flight_id = ?",
                    (flight_id,))
        conn.commit()
        return jsonify({
            "status": status,
            "barcode": barcode,
            "flight_id": flight_id,
            "flight_number": cur.fetchone()["flight_number"],
            "mul_id": mul_id,
            "final_destination": destination,
            "previous_flight": old["flight_number"] if status == "reassigned" else None,
            "already_on_line": already_on_line,
        }), 201 if status == "registered" else 200
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
