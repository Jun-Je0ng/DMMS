"""
Activity feed -- a small rolling log of raw sensor/scanner activity, for the
diagnostics dashboard (diagnostics_view.py) to poll. Separate from
live_feed.py: that one holds resolved bags (after pairing); this one holds
the raw events as they happen, before anything's been paired, so the
dashboard can show "scanner just read this" the instant it occurs.

Atomic write (temp file + rename), same as live_feed.py.
"""

import json
import os
from collections import deque
from pathlib import Path


class ActivityFeed:
    def __init__(self, path: str = "activity.json", max_entries: int = 30):
        self.path = Path(path)
        self.entries = deque(maxlen=max_entries)
        self._write()

    def add(self, kind: str, ts: float, detail: str):
        """kind: 'trigger' | 'scan'"""
        self.entries.append({"kind": kind, "ts": ts, "detail": detail})
        self._write()

    def _write(self):
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp_path, "w") as f:
            json.dump(list(self.entries), f, indent=2)
        os.replace(tmp_path, self.path)
