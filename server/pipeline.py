"""
pipeline.py — the core data pipeline: pairing, logging, and live output feeds.

Four classes:
  Pairer       match sensor triggers with barcode scans using time proximity.
  EventLog     append one CSV row per trigger (success or failure).
  LiveFeed     write the growing event list to JSON for the GUI to poll.
  ActivityFeed rolling log of raw sensor/scanner activity for diagnostics.
"""

import csv
import json
import os
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ── Pairing ───────────────────────────────────────────────────────────────────

@dataclass
class Resolution:
    status: str                        # matched | manual | duplicate | ambiguous
    tag_id: Optional[str] = None
    flight_number: Optional[str] = None
    destination: Optional[str] = None


@dataclass
class _ActiveTag:
    flight_number: Optional[str]
    destination: Optional[str]
    last_seen: float


class Pairer:
    """Match sensor triggers with barcode scans using time proximity alone.

    pair_window: how close (seconds) a scan and a trigger must be to count as
        the same bag. Covers belt travel time between scanner and camera.
    loop_window: how long a tag is "still on the loop" for duplicate detection.
        Roughly one MUL loop (~3 minutes per the site visit notes).
    """

    def __init__(self, pair_window: float = 4.0, loop_window: float = 200.0, flight_lookup=None):
        self.pair_window   = pair_window
        self.loop_window   = loop_window
        self.flight_lookup = flight_lookup   # callable(tag_id) -> {"flight_number", "destination"}
        self.pending_scans: List[Tuple[float, str]] = []
        self.active_tags:   Dict[str, _ActiveTag]   = {}
        self._lock = threading.Lock()

    def submit_scan(self, ts: float, barcode: str) -> None:
        """Record a scan as it arrives. Unpaired until a nearby trigger claims it."""
        with self._lock:
            self.pending_scans.append((ts, barcode))

    def resolve_trigger(self, ts: float) -> Resolution:
        """Call once a photo has been captured for the bag detected at `ts`.
        A matching scan can land slightly before OR after the trigger, so
        this matches whatever's within pair_window seconds in either direction.
        """
        with self._lock:
            candidates = [p for p in self.pending_scans if abs(p[0] - ts) <= self.pair_window]
            for c in candidates:
                self.pending_scans.remove(c)
        return self._resolve_candidates(ts, candidates)

    def _resolve_candidates(self, ts: float, candidates: List[Tuple[float, str]]) -> Resolution:
        with self._lock:
            if not candidates:
                return Resolution(status="manual")
            if len(candidates) > 1:
                return Resolution(status="ambiguous")

            _, barcode = candidates[0]
            active = self.active_tags.get(barcode)
            if active is not None and (ts - active.last_seen) <= self.loop_window:
                active.last_seen = ts
                return Resolution(
                    status="duplicate", tag_id=barcode,
                    flight_number=active.flight_number,
                    destination=active.destination,
                )

            flight        = self.flight_lookup(barcode) if self.flight_lookup else {}
            flight_number = flight.get("flight_number")
            destination   = flight.get("destination")
            self.active_tags[barcode] = _ActiveTag(flight_number, destination, last_seen=ts)
            return Resolution(
                status="matched", tag_id=barcode,
                flight_number=flight_number, destination=destination,
            )

    def sweep_unmatched(self, now: float) -> List[Tuple[float, str]]:
        """Pull out scans that can no longer be paired (older than pair_window).
        Called periodically so orphaned scans don't accumulate forever.
        """
        with self._lock:
            stale = [p for p in self.pending_scans if now - p[0] > self.pair_window]
            for p in stale:
                self.pending_scans.remove(p)
            return stale


# ── Event log ─────────────────────────────────────────────────────────────────

class EventLog:
    """Appends one CSV row per trigger (success or failure).
    Logging every attempt lets the report quote a capture failure rate later.
    """

    FIELDS = [
        "id", "timestamp", "status",
        "tag_id", "flight_number", "destination",
        "trigger_source", "trigger_raw", "capture_ok", "capture_path",
    ]

    def __init__(self, path: str = "data/events_with_flights.csv"):
        self.path   = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        is_new      = not self.path.exists()
        self._file  = open(self.path, "a", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=self.FIELDS)
        if is_new:
            self._writer.writeheader()
            self._file.flush()

    def record(self, id: str, status: str, trigger_source: str = "",
               trigger_raw: str = "", capture_ok: bool = False,
               capture_path: str = "", tag_id: str = "",
               flight_number: str = "", destination: str = ""):
        self._writer.writerow({
            "id": id,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "status": status, "tag_id": tag_id,
            "flight_number": flight_number, "destination": destination,
            "trigger_source": trigger_source, "trigger_raw": trigger_raw,
            "capture_ok": capture_ok, "capture_path": capture_path,
        })
        self._file.flush()

    def close(self):
        self._file.close()


# ── Live feed ─────────────────────────────────────────────────────────────────

class LiveFeed:
    """Writes the growing event list to JSON so gui/app.js can poll it.
    Atomic write (temp + rename) so a mid-write poll never sees a broken file.
    """

    def __init__(self, path: str = "data/live_events.json"):
        self.path   = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events = []
        self._write()

    def add(self, id: str, timestamp: str, status: str,
            photo_path: Optional[str] = None,
            flight_number: Optional[str] = None,
            destination: Optional[str] = None):
        self.events.append({
            "id": id, "timestamp": timestamp, "status": status,
            "flight_number": flight_number or None,
            "destination":   destination   or None,
            "photo_path":    photo_path    or None,
        })
        self._write()

    def _write(self):
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w") as f:
            json.dump(self.events, f, indent=2)
        os.replace(tmp, self.path)


# ── Activity feed ─────────────────────────────────────────────────────────────

class ActivityFeed:
    """Rolling log of raw sensor/scanner activity for the diagnostics dashboard.
    Separate from LiveFeed: that one holds resolved (paired) bags; this one
    holds raw events before pairing, so diagnostics can show them instantly.
    Atomic write, same as LiveFeed.
    """

    def __init__(self, path: str = "data/activity.json", max_entries: int = 30):
        self.path    = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.entries = deque(maxlen=max_entries)
        self._write()

    def add(self, kind: str, ts: float, detail: str):
        """kind: 'trigger' | 'scan'"""
        self.entries.append({"kind": kind, "ts": ts, "detail": detail})
        self._write()

    def _write(self):
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w") as f:
            json.dump(list(self.entries), f, indent=2)
        os.replace(tmp, self.path)
