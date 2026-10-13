"""
One-command launcher for DMMS.

Starts the web server (web.py) and the hardware loop (app.py) together,
then opens the MUL board on the left 60% of the screen and Needs
Attention on the right 40%.

    python3 run.py

Ctrl+C stops everything.
"""

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from config.settings import settings


HERE = Path(__file__).resolve().parent
SERVER_PORT = 5000
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"

# Each window gets its own browser profile so Chrome treats them as
# separate processes and actually honours the position/size flags
# (a second launch into an already-running profile ignores them).
PROFILE_DIR = Path.home() / ".cache" / "dmms-browser"

BROWSERS = ["chromium-browser", "chromium", "google-chrome", "google-chrome-stable"]


def screen_size():
    """Screen width/height in pixels, falling back to 1920x1080."""
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        size = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        return size
    except Exception:
        return 1920, 1080


def wait_for_server(timeout=30):
    """Block until web.py is accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", SERVER_PORT), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def open_windows():
    """Open MUL board (left 60%) and Needs Attention (right 40%)."""
    mul_id = settings.get("active_mul")
    urls = [
        f"{BASE_URL}/mul/{mul_id}",
        f"{BASE_URL}/attention?mul_id={mul_id}",
    ]

    browser = next((b for b in BROWSERS if shutil.which(b)), None)
    if browser is None:
        print("[RUN] Chrome/Chromium not found - opening in default browser "
              "(windows won't be tiled).")
        for url in urls:
            webbrowser.open_new(url)
        return []

    width, height = screen_size()
    left_width = int(width * 0.6)
    # (x position, width) for each window, in the same order as urls
    layout = [(0, left_width), (left_width, width - left_width)]

    procs = []
    for i, url in enumerate(urls):
        procs.append(subprocess.Popen(
            [
                browser,
                f"--app={url}",
                f"--user-data-dir={PROFILE_DIR / str(i)}",
                f"--window-position={layout[i][0]},0",
                f"--window-size={layout[i][1]},{height}",
                # Native Wayland ignores window positions; XWayland doesn't.
                "--ozone-platform=x11",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ))
    return procs


def port_in_use():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", SERVER_PORT)) == 0


def main():
    if port_in_use():
        print(f"[RUN] Port {SERVER_PORT} is already in use - an old web.py "
              f"is probably still running.\n"
              f"      Stop it with:  pkill -f web.py   then run this again.")
        return

    env = dict(os.environ, DMMS_NO_BROWSER="1")

    web = subprocess.Popen([sys.executable, "web.py"], cwd=HERE, env=env)
    hardware = subprocess.Popen([sys.executable, "app.py"], cwd=HERE)
    browsers = []

    try:
        if not wait_for_server():
            print("[RUN] Web server didn't start - check the output above.")
            return

        browsers = open_windows()

        hardware_reported = False
        while web.poll() is None:
            if hardware.poll() is not None and not hardware_reported:
                print("[RUN] app.py (hardware) has stopped - web server "
                      "is still running.")
                hardware_reported = True
            time.sleep(1)

        print("[RUN] web.py has stopped.")

    except KeyboardInterrupt:
        print("\n[RUN] Shutting down...")

    finally:
        for proc in [hardware, web, *browsers]:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
        for proc in [hardware, web, *browsers]:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
