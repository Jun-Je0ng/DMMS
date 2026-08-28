"""
Live feed -- writes the growing event list to JSON in the GUI's shape, so
gui/app.js can poll it the same way it already polls mock_events.json.

Atomic write (temp file + rename) so a poll mid-write never sees a truncated
or partially-written file.
"""

import json
import os
from pathlib import Path
from typing import Optional


class LiveFeed:
    def __init__(self, path: str = "live_events.json"):
        self.path = Path(path)
        self.events = []
        self._write()

    def add(
        self,
        id: str,
        timestamp: str,
        status: str,
        photo_path: Optional[str] = None,
        flight_number: Optional[str] = None,
        destination: Optional[str] = None,
    ):
        self.events.append(
            {
                "id": id,
                "timestamp": timestamp,
                "status": status,
                "flight_number": flight_number or None,
                "destination": destination or None,
                "photo_path": photo_path or None,
            }
        )
        self._write()

    def _write(self):
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp_path, "w") as f:
            json.dump(self.events, f, indent=2)
        os.replace(tmp_path, self.path)
