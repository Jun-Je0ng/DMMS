"""
Scanner capture -- runnable program for the barcode reader subsystem.

Always on: keeps an off-screen field focused so every scan is caught, timestamps
each read, and emits it. No trigger, no camera, no Arduino.

Output (one line per scan):
  READY,scanner subsystem
  SCAN,<timestamp>,<barcode>

Run:  python scanner_capture.py      (no extra libraries needed)
"""

from datetime import datetime

import tkinter as tk

from scanner import ScanReader

# --- Config -----------------------------------------------------------------
SCAN_SUFFIX      = "<Return>"   # key the scanner sends after each tag (Enter by default)
MIN_SCAN_LENGTH  = 1            # ignore anything shorter (stray Enter, electrical noise)
REFOCUS_DELAY_MS = 1            # how soon to grab keyboard focus back if it wanders
WINDOW_TITLE     = "Scanner capture"
STATUS_LISTENING = "listening -- always on, scan a tag"

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

    # --- Always-focused field that catches the wedge keystrokes -------------
    # 1x1 px in the corner: present and focusable, effectively invisible.
    field = tk.Entry(root)
    field.place(x=0, y=0, width=1, height=1)
    field.focus_set()

    # --- Event handlers -----------------------------------------------------
    def on_scan_complete(event):
        text = field.get()
        field.delete(0, "end")
        reader.submit(text, ts=now())                 # timestamp the instant Enter lands
        return "break"

    def keep_focus(event=None):
        field.after(REFOCUS_DELAY_MS, field.focus_set)  # grab focus back if it wanders

    field.bind(SCAN_SUFFIX, on_scan_complete)
    field.bind("<FocusOut>", keep_focus)
    root.bind("<Button>", keep_focus)                 # ...including after any mouse click

    # --- Run ----------------------------------------------------------------
    print("READY,scanner subsystem")
    root.mainloop()


if __name__ == "__main__":
    main()