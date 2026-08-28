"""
Barcode listener -- runs barcode_subsystem/scanner_capture.py as a subprocess
and feeds every scan it reports into a Pairer.

The barcode scanner has no trigger and no relationship to the sensor: it's
always on, per its own docstring, and just emits `SCAN,<timestamp>,<barcode>`
lines to stdout whenever a tag is read. Running it as a subprocess (rather
than importing it) sidesteps that it isn't set up as an importable package,
and matches the contract it already documents for itself.
"""

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from pairing import Pairer

BARCODE_SCRIPT = Path(__file__).resolve().parent.parent.parent / "barcode_subsystem" / "scanner_capture.py"


class BarcodeListener:
    def __init__(
        self,
        pairer: Pairer,
        on_unmatched: Callable[[float, str], None],
        script_path: Path = BARCODE_SCRIPT,
        sweep_interval: float = 2.0,
    ):
        self.pairer = pairer
        self.on_unmatched = on_unmatched
        self.script_path = script_path
        self.sweep_interval = sweep_interval
        self._proc: Optional[subprocess.Popen] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if not self.script_path.exists():
            raise FileNotFoundError(f"Barcode scanner script not found: {self.script_path}")

        self._proc = subprocess.Popen(
            # -u: unbuffered, so `print()` in scanner_capture.py reaches this
            # pipe as each scan happens instead of sitting in a buffer.
            [sys.executable, "-u", str(self.script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._sweep_loop, daemon=True).start()

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line or line.startswith("READY"):
                continue
            if line.startswith("SCAN,"):
                # scanner_capture.py's own timestamp is for its display only;
                # pairing uses local receive time so both sides of the
                # comparison are on the same clock.
                _, _scanner_ts, barcode = line.split(",", 2)
                self.pairer.submit_scan(ts=time.time(), barcode=barcode)

    def _sweep_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(self.sweep_interval)
            for ts, barcode in self.pairer.sweep_unmatched(now=time.time()):
                self.on_unmatched(ts, barcode)

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
