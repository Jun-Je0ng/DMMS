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
    on_late_match: optional callback(bag_id, Resolution), fired when a scan
        arrives AFTER resolve_trigger() already had to call a bag 'manual'
        for lack of any scan yet. This is the normal real-world ordering —
        sensor fires first, barcode gets read a moment later as the bag
        keeps moving — and resolve_trigger() can't wait for a scan that
        hasn't happened yet, so it makes its best call immediately (needed
        so the photo timing / board update isn't delayed) and may have to
        say 'manual' at first. Passing `bag_id` to resolve_trigger() opts
        that trigger into a second chance: if a scan lands within
        pair_window seconds afterwards, on_late_match reports the upgrade
        (normally 'matched') so the caller can update the board in place
        instead of leaving it stuck in Needs Attention.
    """

    def __init__(self, pair_window: float = 4.0, loop_window: float = 200.0,
                 flight_lookup=None, on_late_match=None):
        self.pair_window   = pair_window
        self.loop_window   = loop_window
        self.flight_lookup = flight_lookup   # callable(tag_id) -> {"flight_number", "destination"}
        self.on_late_match = on_late_match   # callable(bag_id, Resolution)
        self.pending_scans: List[Tuple[float, str]] = []
        self.active_tags:   Dict[str, _ActiveTag]   = {}
        self._open_triggers: Dict[str, float] = {}   # bag_id -> trigger ts, still open for a late scan
        self._lock = threading.Lock()

    def submit_scan(self, ts: float, barcode: str) -> None:
        """Record a scan as it arrives.

        First checks whether it lands within pair_window of a trigger that
        already resolved as 'manual' and is still open for a late match (see
        on_late_match above) — if so, it claims that trigger instead of
        joining the ordinary pending-scan pool that resolve_trigger() draws
        from for brand-new triggers.
        """
        late_target = None
        with self._lock:
            open_candidates = [
                (bag_id, trig_ts) for bag_id, trig_ts in self._open_triggers.items()
                if abs(ts - trig_ts) <= self.pair_window
            ]
            if open_candidates:
                # Nearest in time wins if more than one trigger is still open.
                bag_id, trig_ts = min(open_candidates, key=lambda bt: abs(ts - bt[1]))
                del self._open_triggers[bag_id]
                late_target = (bag_id, trig_ts)
            else:
                self.pending_scans.append((ts, barcode))

        if late_target is not None:
            bag_id, trig_ts = late_target
            resolution = self._resolve_candidates(trig_ts, [(ts, barcode)])
            if self.on_late_match:
                self.on_late_match(bag_id, resolution)

    def resolve_trigger(self, ts: float, bag_id: Optional[str] = None) -> Resolution:
        """Call once a photo has been captured for the bag detected at `ts`.
        A matching scan can land slightly before OR after the trigger, so
        this matches whatever's within pair_window seconds in either direction.

        Pass `bag_id` (the id this trigger will be logged/displayed under) to
        opt into a late-match second chance — see on_late_match above. Safe
        to omit; without it a trigger that resolves 'manual' here just stays
        'manual', exactly as before.
        """
        with self._lock:
            candidates = [p for p in self.pending_scans if abs(p[0] - ts) <= self.pair_window]
            for c in candidates:
                self.pending_scans.remove(c)
        resolution = self._resolve_candidates(ts, candidates)

        if resolution.status == "manual" and bag_id is not None:
            with self._lock:
                self._open_triggers[bag_id] = ts
            timer = threading.Timer(self.pair_window, self._expire_open_trigger, args=(bag_id,))
            timer.daemon = True
            timer.start()

        return resolution

    def _expire_open_trigger(self, bag_id: str) -> None:
        with self._lock:
            self._open_triggers.pop(bag_id, None)

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

    def update(self, id: str, **fields) -> bool:
        """Update an already-added event in place, e.g. a late-arriving scan
        (see Pairer.on_late_match) upgrading a 'manual' bag to 'matched'
        after its photo was already on the board. Only overwrites keys given
        a non-None value, so callers can pass through a Resolution's fields
        (some of which may be None) without blanking out what's already
        there. Returns True if a matching event was found and updated.
        """
        for ev in self.events:
            if ev.get("id") == id:
                for k, v in fields.items():
                    if v is not None:
                        ev[k] = v
                self._write()
                return True
        return False

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
