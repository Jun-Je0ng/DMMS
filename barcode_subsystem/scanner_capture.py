"""
Scanner capture -- runnable program for the barcode reader subsystem.

Genuinely always on: listens to keyboard input system-wide (via pynput),
not just when its own window has focus. A keyboard-wedge scanner types into
whatever window has OS focus -- which usually isn't this program's own
window -- so focus-based capture was only "always on" as long as you kept
clicking back into this window. Global listening is what actually matches
the "always on" behavior of a real fixed/POS-style scanner.

Timing (burst_detector.py) separates a scanner's rapid character burst from
ordinary human typing, so this doesn't behave like a keylogger recording
everything typed anywhere -- only a fast burst terminated promptly by Enter
is ever reported as a scan; everything else is discarded, never stored or
printed.

Output (one line per scan):
  READY,scanner subsystem
  SCAN,<timestamp>,<barcode>

Run:  python scanner_capture.py
Needs: pynput (pip install pynput, or see requirements.txt)
"""

from datetime import datetime

import tkinter as tk
from pynput import keyboard

from burst_detector import BurstDetector
from scanner import ScanReader

# --- Config -----------------------------------------------------------------
MAX_KEYSTROKE_GAP_S = 0.05   # tune here if real scans are missed or human typing gets mistaken for one
MIN_SCAN_LENGTH      = 1     # ignore anything shorter (stray Enter, electrical noise)
WINDOW_TITLE          = "Scanner capture"
STATUS_LISTENING      = "listening -- always on, system-wide, scan a tag"


def _modifier_keys():
    # Shift/Ctrl/Alt/etc. are a normal part of typing a shifted character
    # (both for scanners and humans) -- they must NOT break a burst in
    # progress. Built defensively since not every pynput version has every
    # named key (e.g. some platforms lack shift_l).
    names = (
        "shift", "shift_l", "shift_r",
        "ctrl", "ctrl_l", "ctrl_r",
        "alt", "alt_l", "alt_r", "alt_gr",
        "cmd", "cmd_l", "cmd_r",
        "caps_lock", "num_lock", "scroll_lock",
    )
    return {getattr(keyboard.Key, n) for n in names if hasattr(keyboard.Key, n)}


MODIFIER_KEYS = _modifier_keys()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    root = tk.Tk()
    root.title(WINDOW_TITLE)
    root.geometry("380x240")

    # --- Display ------------------------------------------------------------
    feed = tk.Text(root, height=9, state="disabled")
    feed.pack(fill="both", expand=True, padx=8, pady=(8, 4))
    status = tk.Label(root, text=STATUS_LISTENING, anchor="w")
    status.pack(fill="x", padx=8, pady=(0, 6))

    def report(event) -> None:
        line = f"SCAN,{event.ts},{event.barcode}"
        print(line)                                   # the subsystem's output
        feed.configure(state="normal")
        feed.insert("end", line + "\n")
        feed.see("end")
        feed.configure(state="disabled")

    reader = ScanReader(on_scan=report, min_length=MIN_SCAN_LENGTH)
    detector = BurstDetector(max_gap=MAX_KEYSTROKE_GAP_S)

    # --- Global keyboard listener --------------------------------------------
    def on_press(key):
        ts = datetime.now().timestamp()

        if key in MODIFIER_KEYS:
            return  # part of typing a shifted character -- doesn't break a burst

        if key == keyboard.Key.enter:
            text = detector.feed_enter(ts)
            if text is not None:
                reader.submit(text, ts=now())
            return

        if key == keyboard.Key.space:
            detector.feed_char(" ", ts)
            return

        char = getattr(key, "char", None)
        if char is not None and char.isprintable():
            detector.feed_char(char, ts)
        else:
            detector.reset()  # Backspace, Tab, arrows, etc. -- not scanner output, breaks any burst

    listener = keyboard.Listener(on_press=on_press)
    listener.start()

    # --- Run ------------------------------------------------------------------
    print("READY,scanner subsystem")
    try:
        root.mainloop()
    finally:
        listener.stop()


if __name__ == "__main__":
    main()
