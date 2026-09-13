"""
hardware.py — trigger source (Arduino/simulated) and camera capture.

Two classes:
  TriggerSource / SimulatedTriggerSource / SerialTriggerSource
      Yield TriggerEvent objects whenever the ultrasonic sensor detects a bag.
  CameraCapture
      Context manager that holds an open webcam and exposes .capture().
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Tuple

import random
import sys
import time

import cv2


# ── Trigger sources ───────────────────────────────────────────────────────────

@dataclass
class TriggerEvent:
    timestamp: float
    source: str
    raw: str = ""
    # Simulate mode only: False means the operator pressed 'u' to deliberately
    # ask for a bag with no barcode this time, so main.py skips pairing a
    # simulated scan to it — producing a 'manual' (Needs Attention) bag on
    # purpose instead of always faking a clean match.
    barcode: bool = True


class TriggerSource(ABC):
    @abstractmethod
    def events(self) -> Iterator[TriggerEvent]:
        """Blocks until the sensor fires, then yields one event per fire, forever."""


class SimulatedTriggerSource(TriggerSource):
    """Fake trigger for testing without an Arduino attached.

    interval=None  → waits for a key press per bag (manual demo pacing):
      Enter  → normal bag (gets a simulated barcode under --barcode-mode simulate)
      u      → bag with barcode deliberately skipped → resolves to 'manual' /
               Needs Attention even under --barcode-mode simulate
    interval=(min, max)  → fires automatically at a random spacing (stress test).
    """

    def __init__(self, interval: Optional[Tuple[float, float]] = None):
        self.interval = interval

    def _read_key(self, prompt: str) -> str:
        print(prompt, end="", flush=True)
        if not sys.stdin.isatty():
            line = input()
            return line[:1]
        if sys.platform == "win32":
            import msvcrt
            while True:
                ch = msvcrt.getwch()
                if ch in ("\r", "\n", "u", "U"):
                    print()
                    if ch == "\x03":
                        raise KeyboardInterrupt
                    return ch.lower()
                if ch == "\x03":
                    raise KeyboardInterrupt
        else:
            import termios, tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            print()
            if ch == "\x03":
                raise KeyboardInterrupt
            return ch

    def events(self) -> Iterator[TriggerEvent]:
        count = 0
        while True:
            count += 1
            if self.interval is None:
                key = self._read_key(
                    f"Press Enter to simulate bag #{count} passing the sensor "
                    f"(barcoded), or 'u' for one with no barcode read... "
                )
                barcode = key.lower() != "u"
            else:
                time.sleep(random.uniform(*self.interval))
                barcode = True
            yield TriggerEvent(
                timestamp=time.time(), source="simulated",
                raw=f"bag_{count}", barcode=barcode,
            )


class SerialTriggerSource(TriggerSource):
    """Reads trigger events from the Arduino over serial.

    The Arduino prints a line containing `token` each time the ultrasonic
    sensor detects a bag. Debounce lives on the Arduino side.
    """

    def __init__(self, port: str, baud: int = 9600, token: str = "TRIGGER"):
        import serial  # soft dependency — simulate mode needs no pyserial
        self.token = token
        self._serial = serial.Serial(port, baud, timeout=1)

    def events(self) -> Iterator[TriggerEvent]:
        while True:
            line = self._serial.readline().decode("utf-8", errors="ignore").strip()
            if self.token in line:
                yield TriggerEvent(timestamp=time.time(), source="serial", raw=line)


# ── Camera capture ────────────────────────────────────────────────────────────

class CameraCapture:
    """Context manager: open on enter, release on exit, capture() in between."""

    def __init__(self, camera_index: int = 0, save_dir: str = "data/captures"):
        self.camera_index = camera_index
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self._cap = None

    def open(self):
        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open camera index {self.camera_index}")
        # Request max resolution via MJPG (many webcams cap raw/YUYV lower).
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  99999)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 99999)
        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"Camera opened at {w}x{h}")

    def close(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()

    def capture(self, label: str = "") -> Optional[Path]:
        """Grab one frame and save it. Returns the saved path, or None on failure."""
        if self._cap is None:
            raise RuntimeError("Camera not open — call open() first")
        self._cap.read()          # discard buffered frame
        ok, frame = self._cap.read()
        if not ok:
            return None
        stamp  = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        suffix = f"_{label}" if label else ""
        path   = self.save_dir / f"bag_{stamp}{suffix}.jpg"
        cv2.imwrite(str(path), frame)
        return path
