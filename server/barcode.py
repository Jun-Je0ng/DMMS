
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
