from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, Optional, Tuple
import random
import time


@dataclass
class TriggerEvent:
    timestamp: float
    source: str
    raw: str = ""


class TriggerSource(ABC):
    @abstractmethod
    def events(self) -> Iterator[TriggerEvent]:
        """Blocks until the sensor fires, then yields one event per fire, forever."""


class SimulatedTriggerSource(TriggerSource):
    """Fake trigger for testing without an Arduino attached.

    interval=None waits for an Enter key press per bag (manual demo pacing).
    interval=(min, max) fires automatically at a random spacing (for stress testing
    and generating log data without a person at the keyboard).
    """

    def __init__(self, interval: Optional[Tuple[float, float]] = None):
        self.interval = interval

    def events(self) -> Iterator[TriggerEvent]:
        count = 0
        while True:
            if self.interval is None:
                input(f"Press Enter to simulate bag #{count + 1} passing the sensor...")
            else:
                time.sleep(random.uniform(*self.interval))
            count += 1
            yield TriggerEvent(timestamp=time.time(), source="simulated", raw=f"bag_{count}")


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
