# # """
# # barcode.py — everything barcode-related in one place.

# # Three importable pieces:
# #   BurstDetector   distinguish a scanner's rapid keystroke burst from human typing.
# #   ScanReader      turn a completed keyboard-wedge string into a ScanEvent.
# #   BarcodeListener run the scanner capture window as a subprocess and feed every
# #                   scan into a Pairer.

# # Run as a script (subprocess target for BarcodeListener):
# #   python server/barcode.py
# #   → opens the scanner capture window (tkinter, global keyboard listener).
# # """

# # import subprocess
# # import sys
# # import threading
# # import time
# # from dataclasses import dataclass
# # from pathlib import Path
# # from typing import Callable, List, Optional


# # # ── Burst detector ────────────────────────────────────────────────────────────

# # class BurstDetector:
# #     """Distinguish a barcode scanner's rapid keystroke burst from human typing.

# #     A USB keyboard-wedge scanner injects an entire tag's characters far faster
# #     than any person types (scanners: ~1-5 ms between keys; humans: 60-80 ms+).
# #     Only a fast burst terminated promptly by Enter is reported as a scan;
# #     everything else is discarded — this is what keeps global keyboard listening
# #     from behaving like a keylogger.

# #     max_gap: longest pause (seconds) allowed between consecutive keystrokes
# #         for them to still count as one burst. Tune here if real scans are
# #         missed (raise it) or human typing is mistaken for a scan (lower it).
# #     """

# #     def __init__(self, max_gap: float = 0.05):
# #         self.max_gap   = max_gap
# #         self._buffer:  List[str]       = []
# #         self._last_ts: Optional[float] = None

# #     def feed_char(self, ch: str, ts: float) -> None:
# #         if self._last_ts is not None and (ts - self._last_ts) > self.max_gap:
# #             self._buffer = []
# #         self._buffer.append(ch)
# #         self._last_ts = ts

# #     def feed_enter(self, ts: float) -> Optional[str]:
# #         """Returns the completed barcode if Enter arrived promptly; else None."""
# #         is_burst = self._last_ts is not None and (ts - self._last_ts) <= self.max_gap
# #         text = "".join(self._buffer)
# #         self.reset()
# #         return text if (is_burst and text) else None

# #     def reset(self) -> None:
# #         self._buffer   = []
# #         self._last_ts  = None


# # # ── Scan event / reader ───────────────────────────────────────────────────────

# # @dataclass(frozen=True)
# # class ScanEvent:
# #     ts:      str    # when the scan completed (caller's clock)
# #     barcode: str    # the exact string the scanner read


# # class ScanReader:
# #     """Turn a completed keyboard-wedge string into a timestamped ScanEvent."""

# #     def __init__(self, on_scan: Callable, min_length: int = 1):
# #         self.on_scan    = on_scan
# #         self.min_length = min_length

# #     def submit(self, text: str, ts: float) -> Optional[ScanEvent]:
# #         barcode = text.strip()
# #         if len(barcode) < self.min_length:
# #             return None
# #         event = ScanEvent(ts=ts, barcode=barcode)
# #         self.on_scan(event)
# #         return event


# # # ── Barcode listener (subprocess manager) ────────────────────────────────────

# # # Points at this file itself — when run as __main__ it launches the capture window.
# # _SELF = Path(__file__).resolve()


# # class BarcodeListener:
# #     """Run the scanner capture window as a subprocess and feed every scan into a Pairer.

# #     The scanner capture window (see __main__ below) uses global keyboard
# #     listening and can't be imported cleanly, so it runs in its own process.
# #     It writes one line per scan to stdout:
# #       READY,scanner subsystem
# #       SCAN,<timestamp>,<barcode>
# #     """

# #     def __init__(
# #         self,
# #         pairer,
# #         on_unmatched:      Callable[[float, str], None],
# #         on_immediate_scan: Optional[Callable[[float, str], None]] = None,
# #         on_scan:           Optional[Callable[[float, str], None]] = None,
# #         sweep_interval:    float = 2.0,
# #     ):
# #         self.pairer            = pairer
# #         self.on_unmatched      = on_unmatched
# #         self.on_immediate_scan = on_immediate_scan
# #         self.on_scan           = on_scan
# #         self.sweep_interval    = sweep_interval
# #         self._proc: Optional[subprocess.Popen] = None
# #         self._stop  = threading.Event()

# #     def start(self) -> None:
# #         self._proc = subprocess.Popen(
# #             [sys.executable, "-u", str(_SELF)],
# #             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
# #             text=True, bufsize=1,
# #         )
# #         threading.Thread(target=self._read_loop,   daemon=True).start()
# #         threading.Thread(target=self._stderr_loop, daemon=True).start()
# #         threading.Thread(target=self._sweep_loop,  daemon=True).start()

# #     def _read_loop(self) -> None:
# #         assert self._proc and self._proc.stdout
# #         for line in self._proc.stdout:
# #             line = line.strip()
# #             if not line or line.startswith("READY"):
# #                 continue
# #             if line.startswith("SCAN,"):
# #                 _, _scanner_ts, barcode = line.split(",", 2)
# #                 ts = time.time()
# #                 if self.on_scan:
# #                     self.on_scan(ts, barcode)
# #                 if self.on_immediate_scan is not None:
# #                     # Barcode-first design: claim_for_trigger routes the scan
# #                     # to a waiting sensor trigger (returns True) or tells us
# #                     # no sensor is waiting so we should take the photo now
# #                     # (returns False).  The scan is NOT added to pending_scans
# #                     # in the False case, preventing a later sensor trigger from
# #                     # pairing with an already-handled bag.
# #                     claimed = self.pairer.claim_for_trigger(ts, barcode)
# #                     if not claimed:
# #                         self.on_immediate_scan(ts, barcode)
# #                 else:
# #                     # Legacy path: submit to the pending pool; _sweep_loop
# #                     # calls on_unmatched for scans that never get a trigger.
# #                     self.pairer.submit_scan(ts=ts, barcode=barcode)
# #         if not self._stop.is_set():
# #             code = self._proc.poll()
# #             print(f"[barcode] subprocess exited unexpectedly (code {code}) — scanner is NOT running.")

# #     def _stderr_loop(self) -> None:
# #         assert self._proc and self._proc.stderr
# #         for line in self._proc.stderr:
# #             if line.rstrip():
# #                 print(f"[barcode error] {line.rstrip()}")

# #     def _sweep_loop(self) -> None:
# #         while not self._stop.is_set():
# #             time.sleep(self.sweep_interval)
# #             for ts, barcode in self.pairer.sweep_unmatched(now=time.time()):
# #                 self.on_unmatched(ts, barcode)

# #     def stop(self) -> None:
# #         self._stop.set()
# #         if self._proc:
# #             self._proc.terminate()
# #             try:
# #                 self._proc.wait(timeout=2)
# #             except subprocess.TimeoutExpired:
# #                 self._proc.kill()


# # # ── Scanner capture window (subprocess entry point) ───────────────────────────

# # def _scanner_main() -> None:
# #     """Global keyboard listener + tkinter status window.

# #     Output (one line per scan to stdout):
# #       READY,scanner subsystem
# #       SCAN,<timestamp>,<barcode>

# #     Genuinely always on: listens system-wide (via pynput), not just when this
# #     window has focus. A keyboard-wedge scanner types into whatever window the
# #     OS has focused, so focus-based capture would miss most scans. Global
# #     listening + BurstDetector timing is what makes this safe: only a fast
# #     burst terminated by Enter is ever reported — human typing is discarded.
# #     """
# #     from datetime import datetime as _dt
# #     import tkinter as tk
# #     from pynput import keyboard

# #     MAX_KEYSTROKE_GAP_S = 0.05
# #     MIN_SCAN_LENGTH     = 1

# #     def _modifier_keys():
# #         names = (
# #             "shift", "shift_l", "shift_r",
# #             "ctrl",  "ctrl_l",  "ctrl_r",
# #             "alt",   "alt_l",   "alt_r",  "alt_gr",
# #             "cmd",   "cmd_l",   "cmd_r",
# #             "caps_lock", "num_lock", "scroll_lock",
# #         )
# #         return {getattr(keyboard.Key, n) for n in names if hasattr(keyboard.Key, n)}

# #     MODIFIER_KEYS = _modifier_keys()

# #     root   = tk.Tk()
# #     root.title("Scanner capture")
# #     root.geometry("380x240")

# #     feed   = tk.Text(root, height=9, state="disabled")
# #     feed.pack(fill="both", expand=True, padx=8, pady=(8, 4))
# #     status = tk.Label(root, text="listening — always on, system-wide, scan a tag", anchor="w")
# #     status.pack(fill="x", padx=8, pady=(0, 6))

# #     def report(event) -> None:
# #         line = f"SCAN,{event.ts},{event.barcode}"
# #         print(line, flush=True)
# #         feed.configure(state="normal")
# #         feed.insert("end", line + "\n")
# #         feed.see("end")
# #         feed.configure(state="disabled")

# #     reader   = ScanReader(on_scan=report, min_length=MIN_SCAN_LENGTH)
# #     detector = BurstDetector(max_gap=MAX_KEYSTROKE_GAP_S)

# #     def on_press(key):
# #         ts = _dt.now().timestamp()
# #         if key in MODIFIER_KEYS:
# #             return
# #         if key == keyboard.Key.enter:
# #             text = detector.feed_enter(ts)
# #             if text is not None:
# #                 reader.submit(text, ts=_dt.now().strftime("%Y-%m-%d %H:%M:%S"))
# #             return
# #         if key == keyboard.Key.space:
# #             detector.feed_char(" ", ts)
# #             return
# #         char = getattr(key, "char", None)
# #         if char and char.isprintable():
# #             detector.feed_char(char, ts)
# #         else:
# #             detector.reset()

# #     listener = keyboard.Listener(on_press=on_press)
# #     listener.start()
# #     print("READY,scanner subsystem", flush=True)
# #     try:
# #         root.mainloop()
# #     finally:
# #         listener.stop()


# # if __name__ == "__main__":
# #     _scanner_main()


# """
# barcode.py — keyboard-wedge barcode scanner.

# This module has one job:
#     listen for a USB barcode scanner and report completed scans.

# The scanner is assumed to behave like a keyboard:
#     867 + Enter

# A scan is accepted only when the characters arrive as a rapid burst,
# which prevents ordinary human typing from being treated as a scan.

# When run as a subprocess, it writes:

#     READY
#     SCAN,<timestamp>,<barcode>
# """

# import subprocess
# import sys
# import threading
# import time
# from dataclasses import dataclass
# from pathlib import Path
# from typing import Callable, List, Optional


# # ── Burst detector ────────────────────────────────────────────────────────────

# class BurstDetector:
#     """
#     Detect rapid keyboard bursts produced by a barcode scanner.

#     Scanner keystrokes normally arrive within a few milliseconds.
#     Human typing is much slower.

#     A completed scan must:
#       1. contain at least one character
#       2. have no gap larger than max_gap between characters
#       3. be followed by Enter within max_gap
#     """

#     def __init__(self, max_gap: float = 0.05):
#         self.max_gap = max_gap
#         self._buffer: List[str] = []
#         self._last_ts: Optional[float] = None

#     def feed_char(self, ch: str, ts: float) -> None:
#         if (
#             self._last_ts is not None
#             and (ts - self._last_ts) > self.max_gap
#         ):
#             self.reset()

#         self._buffer.append(ch)
#         self._last_ts = ts

#     def feed_enter(self, ts: float) -> Optional[str]:
#         if not self._buffer or self._last_ts is None:
#             self.reset()
#             return None

#         is_burst = (ts - self._last_ts) <= self.max_gap
#         text = "".join(self._buffer)

#         self.reset()

#         if is_burst and text:
#             return text

#         return None

#     def reset(self) -> None:
#         self._buffer = []
#         self._last_ts = None


# # ── Scan event ────────────────────────────────────────────────────────────────

# @dataclass(frozen=True)
# class ScanEvent:
#     ts: str
#     barcode: str


# class ScanReader:
#     """
#     Convert a completed scanner string into a ScanEvent.
#     """

#     def __init__(
#         self,
#         on_scan: Callable[[ScanEvent], None],
#         min_length: int = 1,
#     ):
#         self.on_scan = on_scan
#         self.min_length = min_length

#     def submit(self, text: str, ts: str) -> Optional[ScanEvent]:
#         barcode = text.strip()

#         if len(barcode) < self.min_length:
#             return None

#         event = ScanEvent(
#             ts=ts,
#             barcode=barcode,
#         )

#         self.on_scan(event)
#         return event


# # ── Barcode listener ─────────────────────────────────────────────────────────

# _SELF = Path(__file__).resolve()


# class BarcodeListener:
#     """
#     Start barcode.py as a subprocess and deliver scans to run.py.

#     run.py only needs to provide:

#         BarcodeListener(on_scan=my_callback)

#     The callback receives:

#         timestamp, barcode
#     """

#     def __init__(
#         self,
#         on_scan: Callable[[float, str], None],
#     ):
#         self.on_scan = on_scan

#         self._proc: Optional[subprocess.Popen] = None
#         self._stop = threading.Event()

#     def start(self) -> None:
#         if self._proc is not None:
#             return

#         self._proc = subprocess.Popen(
#             [sys.executable, "-u", str(_SELF)],
#             stdout=subprocess.PIPE,
#             stderr=subprocess.PIPE,
#             text=True,
#             bufsize=1,
#         )

#         threading.Thread(
#             target=self._read_loop,
#             daemon=True,
#         ).start()

#         threading.Thread(
#             target=self._stderr_loop,
#             daemon=True,
#         ).start()

#     def _read_loop(self) -> None:
#         assert self._proc is not None
#         assert self._proc.stdout is not None

#         for line in self._proc.stdout:
#             line = line.strip()

#             if not line:
#                 continue

#             if line == "READY":
#                 continue

#             if line.startswith("SCAN,"):
#                 try:
#                     _, scanner_ts, barcode = line.split(",", 2)
#                 except ValueError:
#                     print(
#                         f"[barcode] malformed scanner line: {line}",
#                         file=sys.stderr,
#                     )
#                     continue

#                 # Use local receipt time for DMMS event timing.
#                 ts = time.time()

#                 self.on_scan(ts, barcode)

#         if not self._stop.is_set():
#             code = self._proc.poll()
#             print(
#                 f"[barcode] scanner subprocess exited "
#                 f"(code {code}) — scanner is NOT running."
#             )

#     def _stderr_loop(self) -> None:
#         assert self._proc is not None
#         assert self._proc.stderr is not None

#         for line in self._proc.stderr:
#             line = line.rstrip()

#             if line:
#                 print(f"[barcode error] {line}")

#     def stop(self) -> None:
#         self._stop.set()

#         proc = self._proc

#         if proc is None:
#             return

#         try:
#             proc.terminate()
#             proc.wait(timeout=2)
#         except subprocess.TimeoutExpired:
#             proc.kill()
#             proc.wait(timeout=2)
#         except Exception:
#             pass

#         self._proc = None


# # ── Scanner capture window ───────────────────────────────────────────────────

# def _scanner_main() -> None:
#     """
#     Global keyboard listener + small tkinter status window.

#     The scanner is system-wide and does not require the scanner window
#     to have focus.
#     """

#     from datetime import datetime
#     import tkinter as tk
#     from pynput import keyboard

#     MAX_KEYSTROKE_GAP_S = 0.05
#     MIN_SCAN_LENGTH = 1

#     def _modifier_keys():
#         names = (
#             "shift",
#             "shift_l",
#             "shift_r",
#             "ctrl",
#             "ctrl_l",
#             "ctrl_r",
#             "alt",
#             "alt_l",
#             "alt_r",
#             "alt_gr",
#             "cmd",
#             "cmd_l",
#             "cmd_r",
#             "caps_lock",
#             "num_lock",
#             "scroll_lock",
#         )

#         return {
#             getattr(keyboard.Key, name)
#             for name in names
#             if hasattr(keyboard.Key, name)
#         }

#     MODIFIER_KEYS = _modifier_keys()

#     root = tk.Tk()
#     root.title("DMMS Scanner")
#     root.geometry("420x280")

#     feed = tk.Text(
#         root,
#         height=11,
#         state="disabled",
#     )
#     feed.pack(
#         fill="both",
#         expand=True,
#         padx=8,
#         pady=(8, 4),
#     )

#     status = tk.Label(
#         root,
#         text="Scanner ready — waiting for barcode",
#         anchor="w",
#     )
#     status.pack(
#         fill="x",
#         padx=8,
#         pady=(0, 8),
#     )

#     def report(event: ScanEvent) -> None:
#         line = f"SCAN,{event.ts},{event.barcode}"

#         print(line, flush=True)

#         feed.configure(state="normal")
#         feed.insert("end", line + "\n")
#         feed.see("end")
#         feed.configure(state="disabled")

#         status.configure(
#             text=f"Last scan: {event.barcode}"
#         )

#     reader = ScanReader(
#         on_scan=report,
#         min_length=MIN_SCAN_LENGTH,
#     )

#     detector = BurstDetector(
#         max_gap=MAX_KEYSTROKE_GAP_S
#     )

#     def on_press(key):
#         ts = time.monotonic()

#         if key in MODIFIER_KEYS:
#             return

#         if key == keyboard.Key.enter:
#             text = detector.feed_enter(ts)

#             if text is not None:
#                 reader.submit(
#                     text,
#                     ts=datetime.now().strftime(
#                         "%Y-%m-%d %H:%M:%S"
#                     ),
#                 )

#             return

#         if key == keyboard.Key.space:
#             detector.feed_char(" ", ts)
#             return

#         char = getattr(key, "char", None)

#         if char and char.isprintable():
#             detector.feed_char(char, ts)
#         else:
#             detector.reset()

#     listener = keyboard.Listener(
#         on_press=on_press
#     )

#     listener.start()

#     print("READY", flush=True)

#     try:
#         root.mainloop()
#     finally:
#         listener.stop()


# if __name__ == "__main__":
#     _scanner_main()

"""
barcode.py — simple keyboard-wedge barcode scanner.

The USB barcode scanner behaves like a keyboard:
    867123456 + Enter

Every completed scan is sent to run.py as:

    timestamp, barcode
"""

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional


_SELF = Path(__file__).resolve()


class BarcodeListener:
    """
    Starts the scanner capture window as a subprocess.

    run.py provides one callback:

        BarcodeListener(on_scan=my_callback)

    The callback receives:

        timestamp, barcode
    """

    def __init__(self, on_scan: Callable[[float, str], None]):
        self.on_scan = on_scan
        self._proc: Optional[subprocess.Popen] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._proc is not None:
            return

        self._proc = subprocess.Popen(
            [sys.executable, "-u", str(_SELF)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        threading.Thread(
            target=self._read_loop,
            daemon=True,
        ).start()

        threading.Thread(
            target=self._stderr_loop,
            daemon=True,
        ).start()

    def _read_loop(self) -> None:
        assert self._proc is not None
        assert self._proc.stdout is not None

        for line in self._proc.stdout:
            line = line.strip()

            if not line:
                continue

            if line == "READY":
                continue

            if line.startswith("SCAN,"):
                try:
                    _, scanner_ts, barcode = line.split(",", 2)
                except ValueError:
                    print(
                        f"[barcode] malformed scanner line: {line}"
                    )
                    continue

                self.on_scan(
                    time.time(),
                    barcode.strip(),
                )

        if not self._stop.is_set():
            code = self._proc.poll()
            print(
                f"[barcode] scanner subprocess exited "
                f"(code {code}) — scanner is NOT running."
            )

    def _stderr_loop(self) -> None:
        assert self._proc is not None
        assert self._proc.stderr is not None

        for line in self._proc.stderr:
            line = line.rstrip()

            if line:
                print(f"[barcode error] {line}")

    def stop(self) -> None:
        self._stop.set()

        proc = self._proc

        if proc is None:
            return

        try:
            proc.terminate()
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass

        self._proc = None


def _scanner_main() -> None:
    """
    Global keyboard listener.

    The scanner types characters globally and finishes with Enter.
    """

    from datetime import datetime
    import tkinter as tk
    from pynput import keyboard

    root = tk.Tk()
    root.title("DMMS Scanner")
    root.geometry("420x280")

    feed = tk.Text(
        root,
        height=11,
        state="disabled",
    )
    feed.pack(
        fill="both",
        expand=True,
        padx=8,
        pady=(8, 4),
    )

    status = tk.Label(
        root,
        text="Scanner ready — waiting for barcode",
        anchor="w",
    )
    status.pack(
        fill="x",
        padx=8,
        pady=(0, 8),
    )

    buffer = []

    def report(barcode: str) -> None:
        barcode = barcode.strip()

        if not barcode:
            return

        timestamp = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        line = f"SCAN,{timestamp},{barcode}"

        print(line, flush=True)

        feed.configure(state="normal")
        feed.insert("end", line + "\n")
        feed.see("end")
        feed.configure(state="disabled")

        status.configure(
            text=f"Last scan: {barcode}"
        )

    def on_press(key):
        nonlocal buffer

        if key == keyboard.Key.enter:
            barcode = "".join(buffer)
            buffer = []

            report(barcode)
            return

        if key == keyboard.Key.backspace:
            if buffer:
                buffer.pop()
            return

        char = getattr(key, "char", None)

        if char and char.isprintable():
            buffer.append(char)

    listener = keyboard.Listener(
        on_press=on_press
    )

    listener.start()

    print("READY", flush=True)

    try:
        root.mainloop()
    finally:
        listener.stop()


if __name__ == "__main__":
    _scanner_main()
