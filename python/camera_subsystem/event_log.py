import csv
from datetime import datetime
from pathlib import Path


class EventLog:
    """Appends one row per trigger, success or failure, to a CSV file.

    Logging every attempt, not just successful captures, is what lets the
    report quote a capture failure rate later.

    Fields split into two groups: id/status/tag_id/flight_number/destination
    are the pairing result (what the GUI cares about), trigger_source through
    capture_path are the raw camera-side detail behind it.
    """

    FIELDS = [
        "id",
        "timestamp",
        "status",
        "tag_id",
        "flight_number",
        "destination",
        "trigger_source",
        "trigger_raw",
        "capture_ok",
        "capture_path",
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
        id: str,
        status: str,
        trigger_source: str = "",
        trigger_raw: str = "",
        capture_ok: bool = False,
        capture_path: str = "",
        tag_id: str = "",
        flight_number: str = "",
        destination: str = "",
    ):
        self._writer.writerow(
            {
                "id": id,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "status": status,
                "tag_id": tag_id,
                "flight_number": flight_number,
                "destination": destination,
                "trigger_source": trigger_source,
                "trigger_raw": trigger_raw,
                "capture_ok": capture_ok,
                "capture_path": capture_path,
            }
        )
        self._file.flush()

    def close(self):
        self._file.close()
