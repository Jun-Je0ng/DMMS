"""
Diagnostics view -- a separate live dashboard showing raw ultrasonic sensor
and barcode scanner activity as it happens.

This is deliberately NOT the handler-facing GUI (gui/): that one is a
kiosk display of resolved, paired bags routed into cans. This is an
engineer's view for watching the two raw subsystems work (or debugging why
they aren't) -- did the sensor fire, did the scanner read something, when.

Read-only: it never touches the serial port, the barcode scanner, or the
camera. It just polls activity.json, which main.py writes as events happen,
so running this alongside main.py is safe -- no resource contention.

Run:  python3 diagnostics_view.py     (while main.py is running separately)
Quit: q or Esc in the window.
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np


def hex_to_bgr(hex_color: str):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return (b, g, r)


PAGE_PLANE = hex_to_bgr("0d0d0d")
SURFACE_1 = hex_to_bgr("1a1a19")
BORDER = hex_to_bgr("3a3a38")
TEXT_PRIMARY = hex_to_bgr("ffffff")
TEXT_SECONDARY = hex_to_bgr("c3c2b7")
TEXT_MUTED = hex_to_bgr("898781")
ACCENT_SENSOR = hex_to_bgr("3987e5")   # same blue as the sensor accent in gui/
ACCENT_SCANNER = hex_to_bgr("d95926")  # categorical slot 2 (orange), distinct hue

FONT = cv2.FONT_HERSHEY_DUPLEX
ACTIVE_WINDOW_S = 1.2  # how long the indicator stays "lit" after an event


def load_activity(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def draw_panel(canvas, x, y, w, h, title, accent, active, count, log_lines):
    cv2.rectangle(canvas, (x, y), (x + w, y + h), SURFACE_1, -1)
    cv2.rectangle(canvas, (x, y), (x + w, y + h), BORDER, 1, cv2.LINE_AA)
    cv2.putText(canvas, title, (x + 20, y + 34), FONT, 0.65, TEXT_MUTED, 1, cv2.LINE_AA)

    dot_center = (x + 34, y + 78)
    color = accent if active else TEXT_MUTED
    cv2.circle(canvas, dot_center, 13, color, -1, cv2.LINE_AA)
    if active:
        cv2.circle(canvas, dot_center, 19, color, 2, cv2.LINE_AA)

    cv2.putText(canvas, "Active" if active else "Idle", (x + 62, y + 85), FONT, 0.75, TEXT_PRIMARY, 1, cv2.LINE_AA)
    cv2.putText(canvas, f"Count: {count}", (x + w - 150, y + 40), FONT, 0.55, TEXT_SECONDARY, 1, cv2.LINE_AA)

    cv2.line(canvas, (x + 20, y + 108), (x + w - 20, y + 108), BORDER, 1, cv2.LINE_AA)

    ly = y + 142
    if not log_lines:
        cv2.putText(canvas, "No activity yet", (x + 20, ly), FONT, 0.55, TEXT_MUTED, 1, cv2.LINE_AA)
    for line in log_lines:
        cv2.putText(canvas, line, (x + 20, ly), FONT, 0.55, TEXT_SECONDARY, 1, cv2.LINE_AA)
        ly += 28


def format_log_lines(entries, now, limit=9):
    lines = []
    for e in reversed(entries[-limit:]):
        age = now - e["ts"]
        lines.append(f"{e['detail']}   ({age:.1f}s ago)")
    return lines


def main():
    parser = argparse.ArgumentParser(description="Live diagnostics dashboard for the sensor + barcode subsystems.")
    parser.add_argument(
        "--activity-file",
        default="activity.json",
        help="Must match main.py's --activity-file (same default).",
    )
    parser.add_argument("--poll-interval", type=float, default=0.15)
    args = parser.parse_args()

    width, height = 980, 480
    panel_w, panel_h = 450, 380
    window = "DMMS Diagnostics"
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)

    while True:
        entries = load_activity(Path(args.activity_file))
        now = time.time()

        canvas = np.empty((height, width, 3), dtype=np.uint8)
        canvas[:] = PAGE_PLANE

        cv2.putText(canvas, "DMMS Diagnostics", (24, 38), FONT, 0.85, TEXT_PRIMARY, 1, cv2.LINE_AA)
        cv2.putText(
            canvas,
            "Raw sensor + scanner activity -- not the handler GUI. q / Esc to quit.",
            (24, 60), FONT, 0.5, TEXT_MUTED, 1, cv2.LINE_AA,
        )

        triggers = [e for e in entries if e["kind"] == "trigger"]
        scans = [e for e in entries if e["kind"] == "scan"]

        sensor_active = bool(triggers) and (now - triggers[-1]["ts"]) < ACTIVE_WINDOW_S
        scanner_active = bool(scans) and (now - scans[-1]["ts"]) < ACTIVE_WINDOW_S

        draw_panel(
            canvas, 24, 80, panel_w, panel_h, "ULTRASONIC SENSOR",
            ACCENT_SENSOR, sensor_active, len(triggers), format_log_lines(triggers, now),
        )
        draw_panel(
            canvas, 24 + panel_w + 24, 80, panel_w, panel_h, "BARCODE SCANNER",
            ACCENT_SCANNER, scanner_active, len(scans), format_log_lines(scans, now),
        )

        cv2.imshow(window, canvas)
        key = cv2.waitKey(max(1, int(args.poll_interval * 1000))) & 0xFF
        if key in (27, ord("q")):
            break
        if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
