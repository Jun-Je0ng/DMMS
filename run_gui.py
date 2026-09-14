#!/usr/bin/env python3
"""Serve the kiosk GUI and open it in your default browser.

Usage:
    python3 run_gui.py

Stdlib only, no dependencies. Ctrl+C to stop the server.
"""
import glob
import http.server
import json
import os
import socket
import socketserver
import threading
import time
import uuid
import webbrowser
from urllib.parse import urlparse, parse_qs

PORT = 8080
# Served from the repo root (not gui/) so the page can also reach
# python/camera_subsystem/ for mock_events.json and captured photos.
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


FLIGHTS_JSON  = os.path.join(REPO_ROOT, "gui", "flights.json")
CANS_JSON     = os.path.join(REPO_ROOT, "gui", "cans.json")

# Settings page (gui/settings.html) — camera index, serial port/baud,
# trigger token, and pairing/timing values. run.py and sim_runner.py read
# this (merged over config.py's defaults — see server/settings.py) at
# their own startup, so a change here takes effect the next time either
# is (re)started, not live while one is already running.
SETTINGS_JSON = os.path.join(REPO_ROOT, "gui", "settings.json")

# "Loaded" confirmations coming from the mobile confirmation pages
# (mobile_swipe.html / mobile_keypad.html). Kept separate from the
# per-browser localStorage state on the main board so that a phone on
# the same network can mark a bag loaded and have the kiosk board (and
# any other phone) see it too. See /api/loaded* below.
DATA_DIR      = os.path.join(REPO_ROOT, "data")
LOADED_JSON   = os.path.join(DATA_DIR, "loaded.json")
CAPTURES_DIR  = os.path.join(DATA_DIR, "captures")

# Bags the operator has manually dismissed from the mobile gallery
# (Remove from List). Cleared on Reset Board, just like loaded.json.
DISMISSED_JSON = os.path.join(DATA_DIR, "dismissed.json")


def _read_loaded():
    if not os.path.exists(LOADED_JSON):
        return []
    try:
        with open(LOADED_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_loaded(records):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = LOADED_JSON + f".tmp-{uuid.uuid4().hex}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    os.replace(tmp, LOADED_JSON)


def _read_dismissed():
    if not os.path.exists(DISMISSED_JSON):
        return []
    try:
        with open(DISMISSED_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_dismissed(records):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DISMISSED_JSON + f".tmp-{uuid.uuid4().hex}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    os.replace(tmp, DISMISSED_JSON)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=REPO_ROOT, **kwargs)

    def log_message(self, format, *args):
        pass

    def _serve_json_file(self, filepath, default=b"[]"):
        if os.path.exists(filepath):
            with open(filepath, "rb") as f:
                data = f.read()
        else:
            data = default
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _serve_bytes(self, data, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _write_json_file(self, filepath):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        with open(filepath, "wb") as f:
            f.write(body)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _json_response(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        query  = parse_qs(parsed.query)

        if path == "/api/flights":
            self._serve_json_file(FLIGHTS_JSON)
        elif path == "/api/cans":
            self._serve_json_file(CANS_JSON)
        elif path == "/api/loaded":
            self._serve_json_file(LOADED_JSON)
        elif path == "/api/dismissed":
            self._serve_json_file(DISMISSED_JSON)
        elif path == "/api/settings":
            self._serve_json_file(SETTINGS_JSON, default=b"{}")
        elif path == "/api/config-defaults":
            self._json_response(200, _config_defaults())
        elif path == "/api/server-info":
            # Powers the "Mobile Access" QR-code popup on the main board —
            # it needs to know this machine's LAN IP (which changes from
            # network to network) to build the phone-facing URLs.
            self._json_response(200, {"lan_ip": _get_lan_ip() or None, "port": PORT})
        elif path == "/api/cameras":
            # Powers the Settings page's "Detect Cameras" button.
            self._json_response(200, _probe_cameras())
        elif path == "/api/camera-preview":
            # Powers the Settings page's live per-camera preview image.
            try:
                index = int(query.get("index", ["0"])[0])
            except ValueError:
                index = 0
            data, err = _camera_snapshot(index)
            if data is None:
                self._json_response(404, {"error": err})
            else:
                self._serve_bytes(data, "image/jpeg")
        elif path == "/api/serial-ports":
            # Powers the Settings page's "Refresh Ports" button.
            self._json_response(200, _list_serial_ports())
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/flights":
            self._write_json_file(FLIGHTS_JSON)
        elif self.path == "/api/cans":
            self._write_json_file(CANS_JSON)
        elif self.path == "/api/settings":
            os.makedirs(os.path.dirname(SETTINGS_JSON), exist_ok=True)
            self._write_json_file(SETTINGS_JSON)
        elif self.path == "/api/loaded/mark":
            body = self._read_json_body()
            bag_id = str(body.get("id", "")).strip()
            if not bag_id:
                self._json_response(400, {"error": "missing id"})
                return
            records = [r for r in _read_loaded() if r.get("id") != bag_id]
            records.append({
                "id":            bag_id,
                "flight_number": body.get("flight_number"),
                "tag":           body.get("tag"),
                "source":        body.get("source", "unknown"),
                "loaded_at":     time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            _write_loaded(records)
            self._json_response(200, {"ok": True, "loaded": records})
        elif self.path == "/api/loaded/unmark":
            body = self._read_json_body()
            bag_id = str(body.get("id", "")).strip()
            records = [r for r in _read_loaded() if r.get("id") != bag_id]
            _write_loaded(records)
            self._json_response(200, {"ok": True, "loaded": records})
        elif self.path == "/api/dismissed/add":
            body   = self._read_json_body()
            bag_id = str(body.get("id", "")).strip()
            if not bag_id:
                self._json_response(400, {"error": "missing id"})
                return
            records = [r for r in _read_dismissed() if r.get("id") != bag_id]
            records.append({
                "id":            bag_id,
                "flight_number": body.get("flight_number"),
                "tag":           body.get("tag"),
                "dismissed_at":  time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            _write_dismissed(records)
            self._json_response(200, {"ok": True, "dismissed": records})
        elif self.path == "/api/loaded/reset":
            _write_loaded([])
            _write_dismissed([])
            # Delete captured images but keep the folder so the camera can
            # still write new photos immediately after the reset.
            for f in glob.glob(os.path.join(CAPTURES_DIR, "*.jpg")):
                try:
                    os.remove(f)
                except OSError:
                    pass
            os.makedirs(CAPTURES_DIR, exist_ok=True)
            self._json_response(200, {"ok": True})
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def _probe_cameras(max_index=6):
    """Powers the Settings page's "Detect Cameras" button.

    cv2 is a soft dependency here on purpose — this file otherwise runs
    with zero third-party packages (its own docstring promises that), and
    the Settings page's camera tools are the one part of the kiosk that
    needs OpenCV. If it's missing, report that clearly instead of crashing
    the whole GUI server over a feature nobody may be using yet.
    """
    try:
        import cv2
    except ImportError:
        return {"available": False, "reason": "opencv (cv2) is not installed "
                "in this Python environment", "cameras": []}

    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        try:
            if cap.isOpened():
                ok, frame = cap.read()
                if ok and frame is not None:
                    h, w = frame.shape[:2]
                    found.append({"index": i, "width": w, "height": h})
        finally:
            cap.release()
    return {"available": True, "cameras": found}


def _camera_snapshot(index):
    """One JPEG frame from the given camera index, for the Settings page's
    live preview. Returns (bytes, None) on success or (None, error_message).
    """
    try:
        import cv2
    except ImportError:
        return None, "opencv (cv2) is not installed in this Python environment"

    cap = cv2.VideoCapture(index)
    try:
        if not cap.isOpened():
            return None, f"could not open camera index {index}"
        cap.read()  # discard a possibly-stale buffered frame, same as CameraCapture.capture()
        ok, frame = cap.read()
        if not ok or frame is None:
            return None, f"camera index {index} did not return a frame"
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            return None, "failed to encode frame as JPEG"
        return buf.tobytes(), None
    finally:
        cap.release()


def _list_serial_ports():
    """Powers the Settings page's "Refresh Ports" button.

    pyserial is a soft dependency for the same reason cv2 is above — see
    hardware.py's SerialTriggerSource, which also imports it lazily.
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return {"available": False, "reason": "pyserial is not installed "
                "in this Python environment", "ports": []}

    ports = [{"device": p.device, "description": p.description}
             for p in list_ports.comports()]
    return {"available": True, "ports": ports}


def _config_defaults():
    """Read-only snapshot of config.py's current values, so the Settings
    page can show what each field falls back to when left unset in
    gui/settings.json — without hardcoding those numbers a second time
    here and letting them drift out of sync with config.py.

    Loaded fresh from the file (not a top-level `import config`) so a
    typo in config.py reports an error from this one endpoint instead of
    taking down the whole GUI server at startup.
    """
    import importlib.util
    config_path = os.path.join(REPO_ROOT, "config.py")
    try:
        spec = importlib.util.spec_from_file_location("dmms_config", config_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        keys = ["SERIAL_PORT", "SERIAL_BAUD", "TRIGGER_TOKEN", "CAMERA_INDEX",
                "PHOTO_DELAY", "PAIR_WINDOW", "LOOP_WINDOW"]
        return {"ok": True, "values": {k: getattr(mod, k, None) for k in keys}}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _lan_ip():
    """Best-effort guess at this machine's LAN IP, so phones on the same
    Wi-Fi/network know what to type in. Doesn't actually send anything —
    UDP "connect" just makes the OS pick the outbound interface."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


# Cached after the first lookup — the kiosk PC's LAN IP won't change while
# the server is running, and re-detecting it on every QR-modal open (see
# GET /api/server-info, used by index.html's "Mobile Access" button) is
# needless work.
_lan_ip_cache = None


def _get_lan_ip():
    global _lan_ip_cache
    if _lan_ip_cache is None:
        _lan_ip_cache = _lan_ip() or ""
    return _lan_ip_cache


def main():
    socketserver.TCPServer.allow_reuse_address = True
    try:
        # Bind on all interfaces (not just 127.0.0.1) so phones on the same
        # LAN can reach mobile_swipe.html / mobile_keypad.html for the
        # bag-loading confirmation prototypes.
        httpd = socketserver.TCPServer(("0.0.0.0", PORT), Handler)
    except OSError as exc:
        print(f"Could not bind to port {PORT}: {exc}")
        print(f"Something else may already be using it — stop that, or edit PORT in {__file__}.")
        return

    url = f"http://127.0.0.1:{PORT}/gui/?live=1"
    print(f"Serving MUL Baggage Verification GUI at {url}")

    lan_ip = _lan_ip()
    if lan_ip:
        print(f"\nOn a phone on the same network, browse to:")
        print(f"  http://{lan_ip}:{PORT}/gui/mobile_swipe.html   (swipe-confirm prototype)")
        print(f"  http://{lan_ip}:{PORT}/gui/mobile_keypad.html  (keypad-confirm prototype)")
    else:
        print("\n(Could not detect a LAN IP for phone access — check your network connection")
        print(" and Windows Firewall if phones can't reach this server.)")

    print("\nPress Ctrl+C to stop.")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
