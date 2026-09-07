from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Optional, Tuple
import random
import sys
import time


@dataclass
class TriggerEvent:
    timestamp: float
    source: str
    raw: str = ""
    # Simulate mode only: False means the operator pressed 'u' to deliberately ask
    # for a bag with no barcode this time, so main.py must skip pairing a simulated
    # scan to it even under --barcode-mode simulate, producing a 'manual' (Needs
    # Attention) bag on purpose instead of always faking a clean match.
    barcode: bool = True


class TriggerSource(ABC):
    @abstractmethod
    def events(self) -> Iterator[TriggerEvent]:
        """Blocks until the sensor fires, then yields one event per fire, forever."""


class SimulatedTriggerSource(TriggerSource):
    """Fake trigger for testing without an Arduino attached.

    interval=None waits for a single key press per bag (manual demo pacing):
      Enter -> a normal bag (gets a simulated barcode under --barcode-mode simulate)
      u     -> a bag with the barcode read deliberately skipped, so it resolves to
               'manual' / Needs Attention even under --barcode-mode simulate --
               lets you demo that tray on demand instead of waiting for the random
               weighting to produce one.
    interval=(min, max) fires automatically at a random spacing (for stress testing
    and generating log data without a person at the keyboard).
    """

    def __init__(self, interval: Optional[Tuple[float, float]] = None):
        self.interval = interval

    def _read_key(self, prompt: str) -> str:
        """Blocks for one key press, no Enter required for a real terminal ('u' fires
        immediately, same as Enter does). Falls back to line-buffered input() when
        stdin isn't a real tty (piped input, tests) -- first character decides there.

        Works on both Windows (msvcrt) and Unix (termios/tty).
        """
        print(prompt, end="", flush=True)
        if not sys.stdin.isatty():
            line = input()
            return line[:1]
        if sys.platform == "win32":
            import msvcrt
            while True:
                ch = msvcrt.getwch()
                if ch in ("\r", "\n", "u", "U"):
                    print()  # move to next line
                    if ch == "\x03":  # Ctrl+C
                        raise KeyboardInterrupt
                    return ch.lower()
                if ch == "\x03":  # Ctrl+C via msvcrt
                    raise KeyboardInterrupt
                # ignore other keys, wait for Enter or 'u'
        else:
            import termios
            import tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            print()  # raw mode doesn't echo the key itself
            if ch == "\x03":  # Ctrl+C -- raw mode disables the terminal's own SIGINT
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
            yield TriggerEvent(timestamp=time.time(), source="simulated", raw=f"bag_{count}", barcode=barcode)


class SerialTriggerSource(TriggerSource):
    """Reads trigger events from the Arduino over serial.

    Protocol: the Arduino sketch prints a line containing `token` each time the
    ultrasonic sensor detects a bag. Debounce lives on the Arduino side, this
    class just reacts to whatever lines it sends.
    """

    def __init__(self, port: str, baud: int = 9600, token: str = "TRIGGER"):
        import serial  # imported here so simulate mode has no hard dependency on pyserial

        self.token = token
        self._serial = serial.Serial(port, baud, timeout=1)

    def events(self) -> Iterator[TriggerEvent]:
        while True:
            line = self._serial.readline().decode("utf-8", errors="ignore").strip()
            if self.token in line:
                yield TriggerEvent(timestamp=time.time(), source="serial", raw=line)
