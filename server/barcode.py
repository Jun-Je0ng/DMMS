"""
barcode.py — everything barcode-related in one place.

Three importable pieces:
  BurstDetector   distinguish a scanner's rapid keystroke burst from human typing.
  ScanReader      turn a completed keyboard-wedge string into a ScanEvent.
  BarcodeListener run the scanner capture window as a subprocess and feed every
                  scan into a Pairer.

Run as a script (subprocess target for BarcodeListener):
  python server/barcode.py
  → opens the scanner capture window (tkinter, global keyboard listener).
"""

import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional


# ── Burst detector ────────────────────────────────────────────────────────────

class BurstDetector:
    """Distinguish a barcode scanner's rapid keystroke burst from human typing.

    A USB keyboard-wedge scanner injects an entire tag's characters far faster
    than any person types (scanners: ~1-5 ms between keys; humans: 60-80 ms+).
    Only a fast burst terminated promptly by Enter is reported as a scan;
    everything else is discarded — this is what keeps global keyboard listening
    from behaving like a keylogger.

    max_gap: longest pause (seconds) allowed between consecutive keystrokes
        for them to still count as one burst. Tune here if real scans are
        missed (raise it) or human typing is mistaken for a scan (lower it).
    """

    def __init__(self, max_gap: float = 0.05):
        self.max_gap   = max_gap
        self._buffer:  List[str]       = []
        self._last_ts: Optional[float] = None

    def feed_char(self, ch: str, ts: float) -> None:
        if self._last_ts is not None and (ts - self._last_ts) > self.max_gap:
            self._buffer = []
        self._buffer.append(ch)
        self._last_ts = ts

    def feed_enter(self, ts: float) -> Optional[str]:
        """Returns the completed barcode if Enter arrived promptly; else None."""
        is_burst = self._last_ts is not None and (ts - self._last_ts) <= self.max_gap
        text = "".join(self._buffer)
        self.reset()
        return text if (is_burst and text) else None

    def reset(self) -> None:
        self._buffer   = []
        self._last_ts  = None


# ── Scan event / reader ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScanEvent:
    ts:      str    # when the scan completed (caller's clock)
    barcode: str    # the exact string the scanner read


class ScanReader:
    """Turn a completed keyboard-wedge string into a timestamped ScanEvent."""

    def __init__(self, on_scan: Callable, min_length: int = 1):
        self.on_scan    = on_scan
        self.min_length = min_length

    def submit(self, text: str, ts: float) -> Optional[ScanEvent]:
        barcode = text.strip()
        if len(barcode) < self.min_length:
            return None
        event = ScanEvent(ts=ts, barcode=barcode)
        self.on_scan(event)
        return event


# ── Barcode listener (subprocess manager) ────────────────────────────────────

# Points at this file itself — when run as __main__ it launches the capture window.
_SELF = Path(__file__).resolve()


class BarcodeListener:
    """Run the scanner capture window as a subprocess and feed every scan into a Pairer.

    The scanner capture window (see __main__ below) uses global keyboard
    listening and can't be imported cleanly, so it runs in its own process.
    It writes one line per scan to stdout:
      READY,scanner subsystem
      SCAN,<timestamp>,<barcode>
    """

    def __init__(
        self,
        pairer,
        on_unmatched: Callable[[float, str], None],
        on_scan:      Optional[Callable[[float, str], None]] = None,
        sweep_interval: float = 2.0,
    ):
        self.pairer         = pairer
        self.on_unmatched   = on_unmatched
        self.on_scan        = on_scan
        self.sweep_interval = sweep_interval
        self._proc: Optional[subprocess.Popen] = None
        self._stop  = threading.Event()

    def start(self) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-u", str(_SELF)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        threading.Thread(target=self._read_loop,   daemon=True).start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()
        threading.Thread(target=self._sweep_loop,  daemon=True).start()

    def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            line = line.strip()
            if not line or line.startswith("READY"):
                continue
            if line.startswith("SCAN,"):
                _, _scanner_ts, barcode = line.split(",", 2)
                ts = time.time()
                self.pairer.submit_scan(ts=ts, barcode=barcode)
                if self.on_scan:
                    self.on_scan(ts, barcode)
        if not self._stop.is_set():
            code = self._proc.poll()
            print(f"[barcode] subprocess exited unexpectedly (code {code}) — scanner is NOT running.")

    def _stderr_loop(self) -> None:
        assert self._proc and self._proc.stderr
        for line in self._proc.stderr:
            if line.rstrip():
                print(f"[barcode error] {line.rstrip()}")

    def _sweep_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(self.sweep_interval)
            for ts, barcode in self.pairer.sweep_unmatched(now=time.time()):
                self.on_unmatched(ts, barcode)

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()


# ── Scanner capture window (subprocess entry point) ───────────────────────────

def _scanner_main() -> None:
    """Global keyboard listener + tkinter status window.

    Output (one line per scan to stdout):
      READY,scanner subsystem
      SCAN,<timestamp>,<barcode>

    Genuinely always on: listens system-wide (via pynput), not just when this
    window has focus. A keyboard-wedge scanner types into whatever window the
    OS has focused, so focus-based capture would miss most scans. Global
    listening + BurstDetector timing is what makes this safe: only a fast
    burst terminated by Enter is ever reported — human typing is discarded.
    """
    from datetime import datetime as _dt
    import tkinter as tk
    from pynput import keyboard

    MAX_KEYSTROKE_GAP_S = 0.05
    MIN_SCAN_LENGTH     = 1

    def _modifier_keys():
        names = (
            "shift", "shift_l", "shift_r",
            "ctrl",  "ctrl_l",  "ctrl_r",
            "alt",   "alt_l",   "alt_r",  "alt_gr",
            "cmd",   "cmd_l",   "cmd_r",
            "caps_lock", "num_lock", "scroll_lock",
        )
        return {getattr(keyboard.Key, n) for n in names if hasattr(keyboard.Key, n)}

    MODIFIER_KEYS = _modifier_keys()

    root   = tk.Tk()
    root.title("Scanner capture")
    root.geometry("380x240")

    feed   = tk.Text(root, height=9, state="disabled")
    feed.pack(fill="both", expand=True, padx=8, pady=(8, 4))
    status = tk.Label(root, text="listening — always on, system-wide, scan a tag", anchor="w")
    status.pack(fill="x", padx=8, pady=(0, 6))

    def report(event) -> None:
        line = f"SCAN,{event.ts},{event.barcode}"
        print(line, flush=True)
        feed.configure(state="normal")
        feed.insert("end", line + "\n")
        feed.see("end")
        feed.configure(state="disabled")

    reader   = ScanReader(on_scan=report, min_length=MIN_SCAN_LENGTH)
    detector = BurstDetector(max_gap=MAX_KEYSTROKE_GAP_S)

    def on_press(key):
        ts = _dt.now().timestamp()
        if key in MODIFIER_KEYS:
            return
        if key == keyboard.Key.enter:
            text = detector.feed_enter(ts)
            if text is not None:
                reader.submit(text, ts=_dt.now().strftime("%Y-%m-%d %H:%M:%S"))
            return
        if key == keyboard.Key.space:
            detector.feed_char(" ", ts)
            return
        char = getattr(key, "char", None)
        if char and char.isprintable():
            detector.feed_char(char, ts)
        else:
            detector.reset()

    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    print("READY,scanner subsystem", flush=True)
    try:
        root.mainloop()
    finally:
        listener.stop()


if __name__ == "__main__":
    _scanner_main()
