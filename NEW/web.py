from flask import Flask, render_template, request, redirect, jsonify, Response
from database.db import get_connection
from config.settings import settings
from datetime import datetime
from pathlib import Path
import socket
import cv2
import serial.tools.list_ports


app = Flask(__name__)

SERVER_PORT = 5000


def get_lan_ip():
    """
    Best-effort LAN IP for this machine, so a QR code can point a phone
    at this server regardless of which network it's plugged into.

    Opens a UDP "connection" to a public address without sending any
    data — this just makes the OS pick the outbound interface/IP it
    would use, which is normally the LAN IP. Falls back to localhost
    if there's no network at all (e.g. offline dev machine).
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()



@app.template_filter("datetime")
def format_datetime(timestamp):
    if timestamp is None:
        return ""

    return datetime.fromtimestamp(
        int(timestamp)
    ).strftime("%Y-%m-%d %H:%M:%S")



# ============================================================
# MAIN DASHBOARD
# ============================================================

@app.route("/")
def main_dashboard():
    conn = get_connection()
    cur = conn.cursor()

    # --------------------------------------------------------
    # CANs — only CANs that currently have a flight assigned.
    # A flight with no CAN assignment has nowhere to be shown,
    # so it is left out of the board entirely.
    # --------------------------------------------------------

    cur.execute("""
        SELECT
            c.can_id,
            c.mul_id,
            c.flight_id,
            f.flight_number,
            f.destination,
            f.gate_number,
            f.departure_time
        FROM cans c
        JOIN flights f
            ON f.flight_id = c.flight_id
        WHERE c.flight_id IS NOT NULL
        ORDER BY f.departure_time ASC
    """)

    cans = cur.fetchall()

    # --------------------------------------------------------
    # Bags + status, matched to the CAN that handles their
    # flight/MUL combination.
    # --------------------------------------------------------

    cur.execute("""
        SELECT
            b.bag_id,
            b.short_id,
            b.barcode,
            b.photo_path,
            b.flight_id,
            b.mul_id,
            s.status,
            c.can_id
        FROM bags b
        JOIN cans c
            ON c.flight_id = b.flight_id
            AND c.mul_id = b.mul_id
        LEFT JOIN bag_status s
            ON b.bag_id = s.bag_id
        WHERE s.status IS NULL
        OR s.status != 'loaded'
        ORDER BY b.scanned_at DESC
    """)

    bags = cur.fetchall()

    # --------------------------------------------------------
    # Build CAN → bags mapping
    # --------------------------------------------------------

    can_map = {}

    for c in cans:
        can_id = c[0]

        can_map[can_id] = {
            "can_id": can_id,
            "mul_id": c[1],
            "flight_id": c[2],
            "flight_number": c[3],
            "destination": c[4],
            "gate_number": c[5],
            "departure_time": c[6],
            "bags": []
        }

    for can_id in can_map:

        cur.execute("""
            SELECT COUNT(*)
            FROM bag_status s
            WHERE s.can_id = ?
            AND s.status = 'loaded'
        """, (can_id,))

        can_map[can_id]["in_can"] = cur.fetchone()[0]

    for b in bags:
        (
            bag_id,
            short_id,
            barcode,
            photo_path,
            flight_id,
            mul_id,
            status,
            can_id
        ) = b

        if can_id in can_map:
            can_map[can_id]["bags"].append({
                "bag_id": bag_id,
                "short_id": short_id,
                "barcode": barcode,
                "mul_id": mul_id,
                "photo_path": photo_path,
                "status": status or "scanned"
            })

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    cur.execute("""
        SELECT COUNT(*)
        FROM bags
    """)

    total_scanned = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM bag_status
        WHERE status = 'loaded'
    """)

    loaded = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM bag_status
        WHERE status = 'needs_attention'
    """)

    needs_attention = cur.fetchone()[0]



    conn.close()

    return render_template(
        "main_dashboard.html",
        cans=list(can_map.values()),
        stats={
            "total_scanned": total_scanned,
            "loaded": loaded,
            "needs_attention": needs_attention,
        }
    )


# ============================================================
# WORKER DASHBOARD
# ============================================================

@app.route("/worker/<int:mul_id>")
def worker_dashboard(mul_id):
    conn = get_connection()
    cur = conn.cursor()

    # --------------------------------------------------------
    # Optional filters from the side menu (CAN) and the short-ID
    # search box at the top of the page.
    # --------------------------------------------------------

    can_id_raw = request.args.get("can_id", "").strip()
    can_id = int(can_id_raw) if can_id_raw else None

    short_id_raw = request.args.get("short_id", "").strip()
    short_id = int(short_id_raw) if short_id_raw else None

    # --------------------------------------------------------
    # CANs for this MUL — powers the side menu so a worker can
    # narrow the view down to just the CAN/flight they're loading.
    # --------------------------------------------------------

    cur.execute("""
        SELECT
            c.can_id,
            c.flight_id,
            f.flight_number,
            f.destination
        FROM cans c
        LEFT JOIN flights f
            ON f.flight_id = c.flight_id
        WHERE c.mul_id = ?
        ORDER BY c.can_id ASC
    """, (mul_id,))

    cans = cur.fetchall()

    # --------------------------------------------------------
    # Bags — filtered to the selected CAN and/or short ID
    # when the worker has picked one.
    # --------------------------------------------------------

    query = """
        SELECT
            b.bag_id,
            b.short_id,
            b.barcode,
            b.photo_path,
            b.flight_id,
            f.flight_number,
            f.destination,
            s.status,
            c.can_id
        FROM bags b

        LEFT JOIN bag_status s
            ON b.bag_id = s.bag_id

        LEFT JOIN flights f
            ON b.flight_id = f.flight_id

        LEFT JOIN cans c
            ON c.flight_id = b.flight_id
            AND c.mul_id = b.mul_id

        WHERE b.mul_id = ?
          AND (
              s.status IS NULL
              OR s.status != 'loaded'
          )
    """

    params = [mul_id]

    if can_id is not None:
        query += " AND c.can_id = ?"
        params.append(can_id)

    if short_id is not None:
        query += " AND b.short_id = ?"
        params.append(short_id)

    query += " ORDER BY b.scanned_at DESC"

    cur.execute(query, params)

    bags = cur.fetchall()

    # --------------------------------------------------------
    # Loaded bags for the selected CAN — lets a worker reverse a
    # wrong confirmation. Most recent first. Only fetched when a
    # CAN is actually selected (it's meaningless for "All CANs").
    # --------------------------------------------------------

    loaded_bags = []

    if can_id is not None:

        cur.execute("""
            SELECT
                b.bag_id,
                b.short_id,
                f.flight_number,
                f.destination,
                s.loaded_at,
                b.photo_path
            FROM bags b

            JOIN bag_status s
                ON b.bag_id = s.bag_id

            LEFT JOIN flights f
                ON b.flight_id = f.flight_id

            WHERE b.mul_id = ?
              AND s.status = 'loaded'
              AND s.can_id = ?

            ORDER BY s.loaded_at DESC
        """, (mul_id, can_id))

        loaded_bags = cur.fetchall()

    conn.close()

    return render_template(
        "worker_dashboard.html",
        bags=bags,
        mul_id=mul_id,
        cans=cans,
        selected_can_id=can_id,
        short_id_query=short_id_raw,
        loaded_bags=loaded_bags
    )


# ============================================================
# LOAD BAG
# ============================================================

@app.route("/worker/load", methods=["POST"])
def worker_load():

    bag_id = int(request.form["bag_id"])
    mul_id = int(request.form["mul_id"])

    # Preserve whichever CAN the worker had selected, so confirming a
    # load doesn't bounce them back out to the unfiltered "All CANs" view.
    can_id_raw = request.form.get("can_id", "").strip()

    # TODO: replace with actual authenticated user
    user_id = 1

    conn = get_connection()
    cur = conn.cursor()

    try:

        # ----------------------------------------------------
        # Get CAN assigned to this bag's flight/MUL
        # ----------------------------------------------------

        cur.execute("""
            SELECT c.can_id
            FROM cans c
            JOIN bags b
                ON b.flight_id = c.flight_id
               AND b.mul_id = c.mul_id
            WHERE b.bag_id = ?
        """, (bag_id,))

        row = cur.fetchone()

        can_id = row[0] if row else None

        # ----------------------------------------------------
        # Update bag status
        # ----------------------------------------------------

        cur.execute("""
            INSERT INTO bag_status (
                bag_id,
                status,
                loaded_by,
                loaded_at,
                can_id
            )
            VALUES (
                ?,
                'loaded',
                ?,
                strftime('%s', 'now'),
                ?
            )

            ON CONFLICT(bag_id)
            DO UPDATE SET
                status = 'loaded',
                loaded_by = excluded.loaded_by,
                loaded_at = excluded.loaded_at,
                can_id = excluded.can_id
        """, (
            bag_id,
            user_id,
            can_id
        ))

        # ----------------------------------------------------
        # Event history
        # ----------------------------------------------------

        cur.execute("""
            INSERT INTO bag_events (
                bag_id,
                event_type,
                user_id,
                timestamp,
                details
            )
            VALUES (
                ?,
                'loaded',
                ?,
                strftime('%s', 'now'),
                ?
            )
        """, (
            bag_id,
            user_id,
            f"Loaded into CAN {can_id}"
        ))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    if can_id_raw:
        return redirect(f"/worker/{mul_id}?can_id={can_id_raw}")

    return redirect(f"/worker/{mul_id}")


# ============================================================
# UNDO LOAD
# ============================================================
# Lets a worker reverse a bag they confirmed by mistake — puts it
# back to "scanned" so it reappears in the loading list instead of
# staying stuck as "loaded" into the wrong CAN.

@app.route("/worker/undo-load", methods=["POST"])
def worker_undo_load():

    bag_id = int(request.form["bag_id"])
    mul_id = int(request.form["mul_id"])
    can_id_raw = request.form.get("can_id", "").strip()

    # TODO: replace with actual authenticated user
    user_id = 1

    conn = get_connection()
    cur = conn.cursor()

    try:

        cur.execute("""
            UPDATE bag_status
            SET
                status = 'scanned',
                loaded_by = NULL,
                loaded_at = NULL,
                can_id = NULL
            WHERE bag_id = ?
        """, (bag_id,))

        cur.execute("""
            INSERT INTO bag_events (
                bag_id,
                event_type,
                user_id,
                timestamp,
                details
            )
            VALUES (
                ?,
                'unloaded',
                ?,
                strftime('%s', 'now'),
                'Load reversed by worker'
            )
        """, (
            bag_id,
            user_id
        ))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    if can_id_raw:
        return redirect(f"/worker/{mul_id}?can_id={can_id_raw}")

    return redirect(f"/worker/{mul_id}")


# ============================================================
# NEEDS ATTENTION
# ============================================================

@app.route("/attention")
def needs_attention():

    conn = get_connection()
    cur = conn.cursor()

    # Get the latest event for each bag.
    cur.execute("""
        SELECT
            b.bag_id,
            b.short_id,
            b.barcode,
            b.photo_path,
            b.flight_id,
            f.flight_number,
            f.destination,
            e.details,
            e.timestamp
        FROM bag_status s

        JOIN bags b
            ON b.bag_id = s.bag_id

        LEFT JOIN flights f
            ON f.flight_id = b.flight_id

        LEFT JOIN bag_events e
            ON e.bag_id = b.bag_id
           AND e.timestamp = (
                SELECT MAX(e2.timestamp)
                FROM bag_events e2
                WHERE e2.bag_id = b.bag_id
           )

        WHERE s.status = 'needs_attention'

        ORDER BY e.timestamp DESC
    """)

    bags = cur.fetchall()

    cur.execute("""
        SELECT
            flight_id,
            flight_number,
            destination
        FROM flights
        ORDER BY departure_time ASC
    """)

    flights_ = cur.fetchall()


    conn.close()

    return render_template(
        "needs_attention.html",
        bags=bags,
        flights=flights_
    )


# ============================================================
# RESOLVE BAG
# ============================================================

@app.route("/attention/resolve", methods=["POST"])
def resolve_bag():

    bag_id = int(request.form["bag_id"])

    # TODO: actual authenticated user
    user_id = 1

    conn = get_connection()
    cur = conn.cursor()

    try:

        cur.execute("""
            UPDATE bag_status
            SET
                status = 'resolved',
                loaded_by = ?,
                loaded_at = strftime('%s', 'now')
            WHERE bag_id = ?
        """, (
            user_id,
            bag_id
        ))

        cur.execute("""
            INSERT INTO bag_events (
                bag_id,
                event_type,
                user_id,
                timestamp,
                details
            )
            VALUES (
                ?,
                'resolved',
                ?,
                strftime('%s', 'now'),
                'Bag resolved'
            )
        """, (
            bag_id,
            user_id
        ))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return redirect("/attention")


# ============================================================
# REJECT BAG
# ============================================================

@app.route("/attention/reject", methods=["POST"])
def reject_bag():

    bag_id = int(request.form["bag_id"])

    # TODO: actual authenticated user
    user_id = 1

    conn = get_connection()
    cur = conn.cursor()

    try:

        cur.execute("""
            UPDATE bag_status
            SET
                status = 'rejected',
                loaded_by = ?,
                loaded_at = strftime('%s', 'now')
            WHERE bag_id = ?
        """, (
            user_id,
            bag_id
        ))

        cur.execute("""
            INSERT INTO bag_events (
                bag_id,
                event_type,
                user_id,
                timestamp,
                details
            )
            VALUES (
                ?,
                'rejected',
                ?,
                strftime('%s', 'now'),
                'Bag rejected'
            )
        """, (
            bag_id,
            user_id
        ))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return redirect("/attention")


# ============================================================
# ASSIGN FLIGHT
# ============================================================

@app.route("/attention/assign", methods=["POST"])
def assign_flight():

    bag_id = int(request.form["bag_id"])
    flight_id = int(request.form["flight_id"])

    # TODO: actual authenticated user
    user_id = 1

    conn = get_connection()
    cur = conn.cursor()

    try:

        # ----------------------------------------------------
        # Assign flight
        # ----------------------------------------------------

        cur.execute("""
            UPDATE bags
            SET flight_id = ?
            WHERE bag_id = ?
        """, (
            flight_id,
            bag_id
        ))

        # ----------------------------------------------------
        # Update status
        # ----------------------------------------------------

        cur.execute("""
            UPDATE bag_status
            SET status = 'assigned'
            WHERE bag_id = ?
        """, (bag_id,))

        # ----------------------------------------------------
        # Event
        # ----------------------------------------------------

        cur.execute("""
            INSERT INTO bag_events (
                bag_id,
                event_type,
                user_id,
                timestamp,
                details
            )
            VALUES (
                ?,
                'assigned',
                ?,
                strftime('%s', 'now'),
                ?
            )
        """, (
            bag_id,
            user_id,
            f"Assigned to flight {flight_id}"
        ))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return redirect("/attention")


# ============================================================
# ADMIN
# ============================================================

@app.route("/admin")
def admin_home():
    return render_template("admin/dashboard.html")


# ============================================================
# ADMIN — FLIGHTS
# ============================================================

@app.route("/admin/flights")
def admin_flights():

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM flights
        ORDER BY departure_time ASC
    """)

    flights = cur.fetchall()

    conn.close()

    return render_template(
        "admin/flights.html",
        flights=flights
    )

# ============================================================
# ADMIN — ADD FLIGHT
# ============================================================

@app.route("/admin/flights/add", methods=["GET", "POST"])
def admin_flight_add():

    if request.method == "GET":
        return render_template("admin/flight_form.html")

    flight_number = request.form["flight_number"].strip()
    destination = request.form["destination"].strip()
    gate_number = request.form["gate_number"].strip()
    departure_time = request.form["departure_time"].strip()

    conn = get_connection()
    cur = conn.cursor()

    try:

        cur.execute("""
            INSERT INTO flights (
                flight_number,
                departure_time,
                destination,
                gate_number
            )
            VALUES (?, ?, ?, ?)
        """, (
            flight_number,
            departure_time,
            destination,
            gate_number
        ))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return redirect("/admin/flights")


# ============================================================
# ADMIN — EDIT FLIGHT
# ============================================================

@app.route("/admin/flights/edit/<int:flight_id>", methods=["GET", "POST"])
def admin_flight_edit(flight_id):

    conn = get_connection()
    cur = conn.cursor()

    if request.method == "GET":

        cur.execute("""
            SELECT
                flight_id,
                flight_number,
                departure_time,
                destination,
                gate_number
            FROM flights
            WHERE flight_id = ?
        """, (flight_id,))

        flight = cur.fetchone()
        conn.close()

        if not flight:
            return "Flight not found", 404

        return render_template(
            "admin/flight_form.html",
            flight=flight
        )

    # --------------------------------------------------------
    # POST — update flight
    # --------------------------------------------------------

    flight_number = request.form["flight_number"].strip()
    destination = request.form["destination"].strip()
    gate_number = request.form["gate_number"].strip()
    departure_time = request.form["departure_time"].strip()

    try:

        cur.execute("""
            UPDATE flights
            SET
                flight_number = ?,
                departure_time = ?,
                destination = ?,
                gate_number = ?
            WHERE flight_id = ?
        """, (
            flight_number,
            departure_time,
            destination,
            gate_number,
            flight_id
        ))

        if cur.rowcount == 0:
            conn.rollback()
            conn.close()
            return "Flight not found", 404

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return redirect("/admin/flights")


# ============================================================
# ADMIN — DELETE FLIGHT
# ============================================================

@app.route("/admin/flights/delete/<int:flight_id>", methods=["POST"])
def admin_flight_delete(flight_id):

    conn = get_connection()
    cur = conn.cursor()

    try:

        cur.execute("""
            DELETE FROM flights
            WHERE flight_id = ?
        """, (flight_id,))

        if cur.rowcount == 0:
            conn.rollback()
            conn.close()
            return "Flight not found", 404

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return redirect("/admin/flights")


# ============================================================
# ADMIN — CANS
# ============================================================

@app.route("/admin/cans")
def admin_cans():

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            can_id,
            mul_id,
            flight_id
        FROM cans
        ORDER BY can_id ASC
    """)

    cans = cur.fetchall()

    cur.execute("""
        SELECT
            mul_id,
            mul_name
        FROM mul
        ORDER BY mul_id ASC
    """)

    muls = cur.fetchall()

    cur.execute("""
        SELECT
            flight_id,
            flight_number,
            destination
        FROM flights
        ORDER BY departure_time ASC
    """)

    flights = cur.fetchall()

    conn.close()

    return render_template(
        "admin/cans.html",
        cans=cans,
        muls=muls,
        flights=flights
    )


@app.route("/admin/cans/update", methods=["POST"])
def admin_cans_update():

    can_id = int(request.form["can_id"])
    mul_id = int(request.form["mul_id"])
    flight_id = int(request.form["flight_id"])

    conn = get_connection()
    cur = conn.cursor()

    try:

        cur.execute("""
            UPDATE cans
            SET
                mul_id = ?,
                flight_id = ?
            WHERE can_id = ?
        """, (
            mul_id,
            flight_id,
            can_id
        ))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return redirect("/admin/cans")


# ============================================================
# ADMIN — ADD CAN
# ============================================================

@app.route("/admin/cans/add", methods=["POST"])
def admin_cans_add():

    mul_id = int(request.form["mul_id"])

    flight_id = request.form.get("flight_id", "").strip()
    flight_id = int(flight_id) if flight_id else None

    conn = get_connection()
    cur = conn.cursor()

    try:

        cur.execute("""
            INSERT INTO cans (
                mul_id,
                flight_id
            )
            VALUES (?, ?)
        """, (
            mul_id,
            flight_id
        ))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return redirect("/admin/cans")


# ============================================================
# ADMIN — MULS
# ============================================================

@app.route("/admin/muls")
def admin_muls():

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM mul
        ORDER BY mul_id ASC
    """)

    muls = cur.fetchall()

    conn.close()

    return render_template(
        "admin/muls.html",
        muls=muls
    )


# ============================================================
# ADMIN — USERS
# ============================================================

@app.route("/admin/users")
def admin_users():

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM users
        ORDER BY user_id ASC
    """)

    users = cur.fetchall()

    conn.close()

    return render_template(
        "admin/users.html",
        users=users
    )


# ============================================================
# ADMIN — BAG LOOKUP
# ============================================================

@app.route("/admin/bag-lookup")
def bag_lookup():
    return render_template(
        "admin/bag_lookup.html"
    )


# ============================================================
# ADMIN — BAG SEARCH
# ============================================================

@app.route("/admin/bag-search", methods=["POST"])
def bag_search():

    query = request.form["query"].strip()

    conn = get_connection()
    cur = conn.cursor()

    # --------------------------------------------------------
    # Search by:
    #
    #   1. bag_id
    #   2. barcode
    #
    # Short IDs require a MUL because they are only unique
    # within a MUL.
    # --------------------------------------------------------

    cur.execute("""
        SELECT
            b.bag_id,
            b.short_id,
            b.barcode,
            b.photo_path,
            b.flight_id,
            b.mul_id,
            f.flight_number,
            f.destination
        FROM bags b

        LEFT JOIN flights f
            ON b.flight_id = f.flight_id

        WHERE
            CAST(b.bag_id AS TEXT) = ?
            OR b.barcode = ?
            OR CAST(b.short_id AS TEXT) = ?
    """, (
        query,
        query,
        query
    ))


    bags = cur.fetchall()

    # --------------------------------------------------------
    # If exactly one result, get its events.
    # --------------------------------------------------------

    if len(bags) == 1:

        bag = bags[0]

        cur.execute("""
            SELECT
                event_type,
                user_id,
                timestamp,
                details
            FROM bag_events
            WHERE bag_id = ?
            ORDER BY timestamp ASC
        """, (bag[0],))

        events = cur.fetchall()

        conn.close()

        return render_template(
            "admin/bag_detail.html",
            bag=bag,
            events=events
        )

    conn.close()

    if not bags:
        return "Bag not found"

    return render_template(
        "admin/bag_search_results.html",
        bags=bags,
        query=query
    )


# ============================================================
# ADMIN — SETTINGS
# ============================================================

@app.route("/admin/settings")
def admin_settings():

    mul_id = settings.get("active_mul")

    mul_cfg = settings.get(
        "mul_settings"
    )[str(mul_id)]

    return render_template(
        "admin/settings.html",
        mul_id=mul_id,
        cfg=mul_cfg
    )


@app.route("/admin/settings/update", methods=["POST"])
def admin_settings_update():

    mul_id = settings.get("active_mul")
    key = str(mul_id)

    settings.data["mul_settings"][key][
        "laser_serial_port"
    ] = request.form["laser_serial_port"]

    settings.data["mul_settings"][key][
        "barcode_serial_port"
    ] = request.form["barcode_serial_port"]

    settings.data["mul_settings"][key][
        "camera_device_index"
    ] = int(
        request.form["camera_device_index"]
    )

    settings.data["mul_settings"][key][
        "camera_resolution"
    ] = [
        int(request.form["camera_width"]),
        int(request.form["camera_height"])
    ]

    settings.data["mul_settings"][key][
        "laser_timeout"
    ] = float(
        request.form["laser_timeout"]
    )

    settings.save()

    return redirect("/admin/settings")


# ============================================================
# ADMIN — CAMERA DETECTION / PREVIEW
# ============================================================
# Used by the "Camera Detection" panel on the settings page. Best-effort
# only: a camera that's slow, busy, or missing at a given index is just
# skipped rather than blocking the scan or crashing the request.

@app.route("/api/cameras")
def api_cameras():

    found = []

    for index in range(5):

        cap = cv2.VideoCapture(index)

        try:
            if cap.isOpened():
                found.append({"index": index})
        finally:
            cap.release()

    return jsonify({"cameras": found})


@app.route("/api/camera-preview")
def api_camera_preview():

    index = request.args.get("index", type=int)

    if index is None:
        return "Missing index", 400

    cap = cv2.VideoCapture(index)

    try:

        if not cap.isOpened():
            return f"Camera {index} not available", 404

        ret, frame = cap.read()

        if not ret or frame is None:
            return f"Failed to read from camera {index}", 500

        ok, buffer = cv2.imencode(".jpg", frame)

        if not ok:
            return "Failed to encode preview", 500

        return Response(buffer.tobytes(), mimetype="image/jpeg")

    finally:
        cap.release()


# ============================================================
# ADMIN — SERIAL PORT SCANNER
# ============================================================

@app.route("/api/serial-ports")
def api_serial_ports():

    ports = [
        {
            "device": p.device,
            "description": p.description
        }
        for p in serial.tools.list_ports.comports()
    ]

    return jsonify({"ports": ports})


# ============================================================
# ADMIN — RESET BAG ACTIVITY
# ============================================================


@app.route("/admin/reset-bag-activity", methods=["POST"])
def reset_bag_activity():

    conn = get_connection()
    cur = conn.cursor()

    # --------------------------------------------------------
    # Bag photo directory
    # --------------------------------------------------------

    base_dir = Path(__file__).resolve().parent
    photo_dir = base_dir / "static" / "bag_photos"

    try:

        # ----------------------------------------------------
        # Get all existing photo paths before deleting bags.
        #
        # This lets us remove the actual files from disk.
        # ----------------------------------------------------

        cur.execute("""
            SELECT photo_path
            FROM bags
            WHERE photo_path IS NOT NULL
        """)

        photo_rows = cur.fetchall()

        # ----------------------------------------------------
        # Delete bag events first.
        #
        # bag_events references bags.
        # ----------------------------------------------------

        cur.execute("""
            DELETE FROM bag_events
        """)

        # ----------------------------------------------------
        # Delete bag statuses.
        #
        # bag_status references bags.
        # ----------------------------------------------------

        cur.execute("""
            DELETE FROM bag_status
        """)

        # ----------------------------------------------------
        # Delete all bag records.
        #
        # This also resets the active bag dataset.
        #
        # Flights, MULs, CANs and users are NOT touched.
        # ----------------------------------------------------

        cur.execute("""
            DELETE FROM bags
        """)

        # ----------------------------------------------------
        # Commit database changes.
        # ----------------------------------------------------

        conn.commit()

        # ----------------------------------------------------
        # Delete old bag photos from disk.
        #
        # Only files recorded in the bags table are removed.
        # ----------------------------------------------------

        deleted_photos = 0

        for row in photo_rows:

            photo_path = row[0]

            if not photo_path:
                continue

            # Convert database path such as:
            #
            # static/bag_photos/1789433160.jpg
            #
            # into an absolute filesystem path.

            file_path = base_dir / photo_path

            try:

                if file_path.is_file():
                    file_path.unlink()
                    deleted_photos += 1

            except OSError as e:

                print(
                    f"[RESET WARNING] "
                    f"Could not delete photo "
                    f"{file_path}: {e}"
                )

        # ----------------------------------------------------
        # Optional cleanup:
        #
        # Remove any remaining files in bag_photos.
        #
        # This ensures old photos that may have been left
        # behind by previous versions are also removed.
        # ----------------------------------------------------

        if photo_dir.exists():

            for file_path in photo_dir.iterdir():

                if file_path.is_file():

                    try:
                        file_path.unlink()

                    except OSError as e:

                        print(
                            f"[RESET WARNING] "
                            f"Could not delete old photo "
                            f"{file_path}: {e}"
                        )

        print(
            "[RESET] Bag activity reset successfully"
        )

        print(
            f"[RESET] Deleted {len(photo_rows)} "
            f"bag photo references"
        )

        print(
            f"[RESET] Removed {deleted_photos} "
            f"photo files"
        )

    except Exception as e:

        # ----------------------------------------------------
        # Something failed.
        #
        # Roll back database changes.
        # ----------------------------------------------------

        conn.rollback()

        print(
            f"[RESET ERROR] "
            f"Failed to reset bag activity: {e}"
        )

        raise

    finally:

        conn.close()

    return redirect("/admin")




# ============================================================
# SERVER INFO (for the "Scan for Worker View" QR code)
# ============================================================

@app.route("/api/server-info")
def api_server_info():
    return jsonify({
        "lan_ip": get_lan_ip(),
        "port": SERVER_PORT
    })


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":
    app.run(
        # 0.0.0.0 (not 127.0.0.1) so phones on the same network can
        # actually reach this server — required for the worker QR code
        # to work from another device.
        host="0.0.0.0",
        port=SERVER_PORT,
        debug=False
    )
