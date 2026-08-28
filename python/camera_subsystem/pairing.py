"""
Pairing -- matches sensor-triggered photo captures with barcode scans.

The ultrasonic sensor and the barcode scanner are two independent subsystems
with no wiring between them: the sensor fires when a bag passes underneath it,
the scanner fires whenever *any* tag gets read, on its own clock, with no
notion of "this scan belongs to that bag." This module is the piece that
turns those two independent timelines into one bag identity per trigger,
using proximity in time as the only signal available.

Pure logic: takes timestamps in, no clock reads, no I/O -- testable with
nothing attached (mirrors the style of barcode_subsystem/scanner.py). The one
concession to being used from real threads (a barcode listener thread writes,
the trigger loop thread reads) is an internal lock -- not I/O, just making
the pure logic safe to call concurrently.
"""

import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


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
    """
    pair_window: how close (seconds) a scan and a trigger must be to belong
        to the same bag. Covers belt travel time between the scanner and the
        camera, not the whole loop.
    loop_window: how long a tag is considered "still on the loop" after a
        match, for duplicate detection. Should be roughly one MUL loop
        (~3 minutes per the site visit notes) -- shorter risks flagging a
        second, unrelated bag that happens to reuse a tag number as a
        duplicate; longer risks missing a real duplicate.
    """

    def __init__(self, pair_window: float = 4.0, loop_window: float = 200.0, flight_lookup=None):
        self.pair_window = pair_window
        self.loop_window = loop_window
        self.flight_lookup = flight_lookup  # callable(tag_id) -> {"flight_number", "destination"}, or None
        self.pending_scans: List[Tuple[float, str]] = []
        self.active_tags: Dict[str, _ActiveTag] = {}
        self._lock = threading.Lock()

    def submit_scan(self, ts: float, barcode: str) -> None:
        """Record a scan as it arrives. Unpaired until a nearby trigger claims it."""
        with self._lock:
            self.pending_scans.append((ts, barcode))

    def resolve_trigger(self, ts: float) -> Resolution:
        """
        Call once a photo has been captured for a bag detected at `ts`, when
        the scan could have arrived slightly before OR after the trigger
        (e.g. a simulated scan submitted around the same instant). For a real
        scanner that should only start counting once the sensor fires, use
        take_since()/resolve_candidates() instead -- see main.py.
        """
        with self._lock:
            candidates = [p for p in self.pending_scans if abs(p[0] - ts) <= self.pair_window]
            for c in candidates:
                self.pending_scans.remove(c)
        return self.resolve_candidates(ts, candidates)

    def candidates_since(self, ts: float) -> List[Tuple[float, str]]:
        """Non-mutating peek at scans that arrived at/after `ts` -- for a caller polling to decide when to stop waiting."""
        with self._lock:
            return [p for p in self.pending_scans if p[0] >= ts]

    def take_since(self, ts: float) -> Tuple[List[Tuple[float, str]], List[Tuple[float, str]]]:
        """
        Remove and split pending scans by `ts`: those at/after it (candidates
        for the trigger at `ts`) and those strictly before it (orphaned --
        they arrived before this trigger "activated" the scanner, so they
        can't belong to it, and there's no earlier trigger left to claim them).
        Returns (candidates, expired).
        """
        with self._lock:
            candidates = [p for p in self.pending_scans if p[0] >= ts]
            expired = [p for p in self.pending_scans if p[0] < ts]
            for p in candidates + expired:
                self.pending_scans.remove(p)
            return candidates, expired

    def resolve_candidates(self, ts: float, candidates: List[Tuple[float, str]]) -> Resolution:
        """
        Decide matched/manual/duplicate/ambiguous from a set of candidate
        scans already picked out for the trigger at `ts` (by resolve_trigger
        or by a caller using take_since). Candidates should already be
        removed from pending_scans -- this only touches active_tags.
        """
        with self._lock:
            if not candidates:
                return Resolution(status="manual")

            if len(candidates) > 1:
                # Can't tell which scan belongs to this bag -- surface it
                # rather than guess.
                return Resolution(status="ambiguous")

            _, barcode = candidates[0]
            active = self.active_tags.get(barcode)
            if active is not None and (ts - active.last_seen) <= self.loop_window:
                active.last_seen = ts
                return Resolution(
                    status="duplicate", tag_id=barcode,
                    flight_number=active.flight_number, destination=active.destination,
                )

            flight = self.flight_lookup(barcode) if self.flight_lookup else {}
            flight_number = flight.get("flight_number")
            destination = flight.get("destination")
            self.active_tags[barcode] = _ActiveTag(flight_number, destination, last_seen=ts)
            return Resolution(
                status="matched", tag_id=barcode, flight_number=flight_number, destination=destination
            )

    def sweep_unmatched(self, now: float) -> List[Tuple[float, str]]:
        """
        Pull out scans that can no longer be paired with any future trigger
        (older than pair_window, so even a trigger arriving right now would
        fall outside the window). Called periodically, since a scan with no
        trigger ever near it would otherwise sit pending forever.
        """
        with self._lock:
            stale = [p for p in self.pending_scans if now - p[0] > self.pair_window]
            for p in stale:
                self.pending_scans.remove(p)
            return stale
