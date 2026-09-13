"""
sim.py — simulated barcode source for running the full pipeline without a scanner.

Generates a fake tag per trigger as "<flight_number>-<destination>"
(e.g. "QF298-SYD"), cycling through the flight list. Cycling a short list
means the same tag naturally repeats every len(flights) bags — combined with
Pairer's duplicate-detection logic, that exercises the "duplicate" status
realistically, not just "matched".
"""

import itertools
from typing import Dict, List


class SimulatedBarcodeSource:
    def __init__(self, flights: List[dict]):
        if not flights:
            raise ValueError("No flights to simulate barcodes from")
        self._cycle = itertools.cycle(flights)
        self._known: Dict[str, dict] = {}

    def next_tag(self) -> str:
        """Generate the next fake tag and remember which flight it encodes."""
        flight = next(self._cycle)
        tag    = f"{flight['flight_number']}-{flight['destination']}"
        self._known[tag] = flight
        return tag

    def lookup(self, tag_id: str) -> dict:
        """Pairer.flight_lookup callback — the tag already carries the flight."""
        return self._known.get(tag_id, {})
