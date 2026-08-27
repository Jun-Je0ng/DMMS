#!/usr/bin/env python3
"""Serve the kiosk GUI and open it in your default browser.

Usage:
    python3 run_gui.py

Stdlib only, no dependencies. Ctrl+C to stop the server.
"""
import http.server
import os
import socketserver
import threading
import webbrowser

PORT = 8080
# Served from the repo root (not gui/) so the page can also reach
# python/camera_subsystem/ for mock_events.json and captured photos.
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=REPO_ROOT, **kwargs)

    def log_message(self, format, *args):
        pass


def main():
    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        print(f"Could not bind to port {PORT}: {exc}")
        print(f"Something else may already be using it — stop that, or edit PORT in {__file__}.")
        return

    url = f"http://127.0.0.1:{PORT}/gui/"
    print(f"Serving MUL Baggage Verification GUI at {url}")
    print("Press Ctrl+C to stop.")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
