from flask import Flask, render_template, request, redirect
from database.db import get_connection

from config.settings import settings

app = Flask(__name__)

@app.route("/")
def main_dashboard():
    conn = get_connection()
    cur = conn.cursor()

    # Get flights
    cur.execute("""
        SELECT flight_id, flight_number, destination, gate_number, departure_time
        FROM flights
        ORDER BY departure_time ASC
    """)
    flights = cur.fetchall()

    # Get bags + status
    cur.execute("""
        SELECT b.bag_id, b.bag_short_id, b.photo_path, b.flight_id,
               s.status
        FROM bags b
        LEFT JOIN bag_status s ON b.bag_id = s.bag_id
        ORDER BY b.scanned_at DESC
    """)
    bags = cur.fetchall()

    # Build flight → bags mapping
    flight_map = {}
    for f in flights:
        fid = f[0]
        flight_map[fid] = {
            "flight_id": fid,
            "flight_number": f[1],
            "destination": f[2],
            "gate_number": f[3],
            "departure_time": f[4],
            "bags": []
        }

    for b in bags:
        bag_id, bag_short_id, photo_path, flight_id, status = b
        if flight_id in flight_map:
            flight_map[flight_id]["bags"].append({
                "bag_id": bag_id,
                "bag_short_id": bag_short_id,
                "photo_path": photo_path,
                "status": status or "scanned"
            })

    # Stats
    cur.execute("SELECT COUNT(*) FROM bags")
    total_scanned = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM bag_status WHERE status = 'loaded'")
    loaded = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM bag_status WHERE status = 'needs_attention'")
    needs_attention = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM bag_status WHERE status = 'in_can'")
    in_can = cur.fetchone()[0]

    conn.close()

    return render_template(
        "main_dashboard.html",
        flights=list(flight_map.values()),
        stats={
            "total_scanned": total_scanned,
            "loaded": loaded,
            "needs_attention": needs_attention,
            "in_can": in_can,
        }
    )


@app.route("/worker/<int:mul_id>")
def worker_dashboard(mul_id):
    conn = get_connection()
    cur = conn.cursor()

    # Get bags for this MUL that are not yet loaded
    cur.execute("""
        SELECT b.bag_id, b.bag_short_id, b.photo_path, b.flight_id,
               f.flight_number, f.destination,
               s.status, c.can_id
        FROM bags b
        LEFT JOIN bag_status s ON b.bag_id = s.bag_id
        LEFT JOIN flights f ON b.flight_id = f.flight_id
        LEFT JOIN cans c ON c.flight_id = b.flight_id
        WHERE b.mul_id = ?
          AND (s.status IS NULL OR s.status != 'loaded')
        ORDER BY b.scanned_at DESC
    """, (mul_id,))

    bags = cur.fetchall()
    conn.close()

    return render_template("worker_dashboard.html", bags=bags, mul_id=mul_id)



@app.route("/worker/load", methods=["POST"])
def worker_load():
    bag_id = int(request.form["bag_id"])
    mul_id = int(request.form["mul_id"])
    user_id = 1  # TODO: replace with real login system

    conn = get_connection()
    cur = conn.cursor()

    # Get CAN assignment
    cur.execute("""
        SELECT c.can_id
        FROM cans c
        JOIN bags b ON b.flight_id = c.flight_id
        WHERE b.bag_id = ?
    """, (bag_id,))
    row = cur.fetchone()
    can_id = row[0] if row else None

    # Update bag_status
    cur.execute("""
        INSERT INTO bag_status (bag_id, status, loaded_by, loaded_at, can_id)
        VALUES (?, 'loaded', ?, strftime('%s','now'), ?)
        ON CONFLICT(bag_id) DO UPDATE SET
            status='loaded',
            loaded_by=excluded.loaded_by,
            loaded_at=excluded.loaded_at,
            can_id=excluded.can_id
    """, (bag_id, user_id, can_id))

    # Insert bag event
    cur.execute("""
        INSERT INTO bag_events (bag_id, event_type, user_id, timestamp, details)
        VALUES (?, 'loaded', ?, strftime('%s','now'), ?)
    """, (bag_id, user_id, f"Loaded into CAN {can_id}"))

    conn.commit()
    conn.close()

    return redirect(f"/worker/{mul_id}")


@app.route("/attention")
def needs_attention():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT b.bag_id, b.bag_short_id, b.photo_path, b.flight_id,
               f.flight_number, f.destination,
               e.details, e.timestamp
        FROM bag_status s
        JOIN bags b ON b.bag_id = s.bag_id
        LEFT JOIN flights f ON f.flight_id = b.flight_id
        LEFT JOIN bag_events e ON e.bag_id = b.bag_id
        WHERE s.status = 'needs_attention'
        ORDER BY e.timestamp DESC
    """)

    bags = cur.fetchall()
    conn.close()

    return render_template("needs_attention.html", bags=bags)

@app.route("/attention/resolve", methods=["POST"])
def resolve_bag():
    bag_id = int(request.form["bag_id"])
    user_id = 1  # TODO: real login

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE bag_status
        SET status='resolved', loaded_by=?, loaded_at=strftime('%s','now')
        WHERE bag_id=?
    """, (user_id, bag_id))

    cur.execute("""
        INSERT INTO bag_events (bag_id, event_type, user_id, timestamp, details)
        VALUES (?, 'resolved', ?, strftime('%s','now'), 'Bag resolved')
    """, (bag_id, user_id))

    conn.commit()
    conn.close()

    return redirect("/attention")

@app.route("/attention/reject", methods=["POST"])
def reject_bag():
    bag_id = int(request.form["bag_id"])
    user_id = 1

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE bag_status
        SET status='rejected', loaded_by=?, loaded_at=strftime('%s','now')
        WHERE bag_id=?
    """, (user_id, bag_id))

    cur.execute("""
        INSERT INTO bag_events (bag_id, event_type, user_id, timestamp, details)
        VALUES (?, 'rejected', ?, strftime('%s','now'), 'Bag rejected')
    """, (bag_id, user_id))

    conn.commit()
    conn.close()

    return redirect("/attention")

@app.route("/attention/assign", methods=["POST"])
def assign_flight():
    bag_id = int(request.form["bag_id"])
    flight_id = int(request.form["flight_id"])
    user_id = 1

    conn = get_connection()
    cur = conn.cursor()

    # Update bag flight
    cur.execute("""
        UPDATE bags
        SET flight_id=?
        WHERE bag_id=?
    """, (flight_id, bag_id))

    # Update status
    cur.execute("""
        UPDATE bag_status
        SET status='assigned'
        WHERE bag_id=?
    """, (bag_id,))

    # Log event
    cur.execute("""
        INSERT INTO bag_events (bag_id, event_type, user_id, timestamp, details)
        VALUES (?, 'assigned', ?, strftime('%s','now'), ?)
    """, (bag_id, user_id, f"Assigned to flight {flight_id}"))

    conn.commit()
    conn.close()

    return redirect("/attention")

@app.route("/admin")
def admin_home():
    return render_template("admin/dashboard.html")

@app.route("/admin/flights")
def admin_flights():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM flights ORDER BY departure_time ASC")
    flights = cur.fetchall()
    conn.close()
    return render_template("admin/flights.html", flights=flights)

@app.route("/admin/cans")
def admin_cans():
    conn = get_connection()
    cur = conn.cursor()

    # Get CANs
    cur.execute("""
        SELECT can_id, mul_id, flight_id
        FROM cans
        ORDER BY can_id ASC
    """)
    cans = cur.fetchall()

    # Get MULs
    cur.execute("SELECT mul_id, mul_name FROM mul ORDER BY mul_id ASC")
    muls = cur.fetchall()

    # Get flights
    cur.execute("""
        SELECT flight_id, flight_number, destination
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

    cur.execute("""
        UPDATE cans
        SET mul_id = ?, flight_id = ?
        WHERE can_id = ?
    """, (mul_id, flight_id, can_id))

    conn.commit()
    conn.close()

    return redirect("/admin/cans")


@app.route("/admin/muls")
def admin_muls():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM mul")
    muls = cur.fetchall()
    conn.close()
    return render_template("admin/muls.html", muls=muls)

@app.route("/admin/users")
def admin_users():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users")
    users = cur.fetchall()
    conn.close()
    return render_template("admin/users.html", users=users)

@app.route("/admin/bag-lookup")
def bag_lookup():
    return render_template("admin/bag_lookup.html")

@app.route("/admin/bag-search", methods=["POST"])
def bag_search():
    query = request.form["query"]

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT b.bag_id, b.bag_short_id, b.photo_path, b.flight_id,
               f.flight_number, f.destination
        FROM bags b
        LEFT JOIN flights f ON b.flight_id = f.flight_id
        WHERE b.bag_id = ? OR b.bag_short_id = ?
    """, (query, query))

    bag = cur.fetchone()

    if not bag:
        return "Bag not found"

    cur.execute("""
        SELECT event_type, user_id, timestamp, details
        FROM bag_events
        WHERE bag_id = ?
        ORDER BY timestamp ASC
    """, (bag[0],))

    events = cur.fetchall()
    conn.close()

    return render_template("admin/bag_detail.html", bag=bag, events=events)

@app.route("/admin/settings")
def admin_settings():
    mul_id = settings.get("active_mul")
    mul_cfg = settings.get("mul_settings")[str(mul_id)]
    return render_template("admin/settings.html", mul_id=mul_id, cfg=mul_cfg)

@app.route("/admin/settings/update", methods=["POST"])
def admin_settings_update():
    mul_id = settings.get("active_mul")
    key = str(mul_id)

    settings.data["mul_settings"][key]["laser_serial_port"] = request.form["laser_serial_port"]
    settings.data["mul_settings"][key]["barcode_serial_port"] = request.form["barcode_serial_port"]
    settings.data["mul_settings"][key]["camera_device_index"] = int(request.form["camera_device_index"])
    settings.data["mul_settings"][key]["camera_resolution"] = [
        int(request.form["camera_width"]),
        int(request.form["camera_height"])
    ]
    settings.data["mul_settings"][key]["laser_timeout"] = float(request.form["laser_timeout"])

    settings.save()

    return redirect("/admin/settings")
