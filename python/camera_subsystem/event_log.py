import csv
from datetime import datetime
from pathlib import Path


class EventLog:
    """Appends one row per trigger, success or failure, to a CSV file.

    Logging every attempt, not just successful captures, is what lets the
    report quote a capture failure rate later.
    """

    FIELDS = [
        "timestamp",
        "trigger_source",
        "trigger_raw",
        "capture_ok",
        "capture_path",
        "flight_number",
        "destination",
    ]

    def __init__(self, path: str = "events_with_flights.csv"):
        self.path = Path(path)
        is_new = not self.path.exists()
        self._file = open(self.path, "a", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=self.FIELDS)
        if is_new:
            self._writer.writeheader()
            self._file.flush()

    def record(
        self,
        trigger_source: str,
        trigger_raw: str,
        capture_ok: bool,
        capture_path: str = "",
        flight_number: str = "",
        destination: str = "",
    ):
        self._writer.writerow(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "trigger_source": trigger_source,
                "trigger_raw": trigger_raw,
                "capture_ok": capture_ok,
                "capture_path": capture_path,
                "flight_number": flight_number,
                "destination": destination,
            }
        )
        self._file.flush()

    def close(self):
        self._file.close()
