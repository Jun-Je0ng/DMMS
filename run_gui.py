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
GUI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=GUI_DIR, **kwargs)

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

    url = f"http://127.0.0.1:{PORT}/"
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
