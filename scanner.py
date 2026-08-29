"""
Scanner subsystem -- barcode reader (PC side, USB keyboard wedge).

This subsystem has NO inputs and no trigger. The scanner is always on; whenever
it reads a tag it types the barcode into the focused field followed by Enter.
The subsystem's only output is, per scan, the barcode text and the timestamp it
was read at. What downstream does with that (pairing, lookup, display) is not
this subsystem's concern.

Pure logic: no window, no clock reads here -- the timestamp is passed in, so this
is testable with nothing attached (see test_scanner.py).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ScanEvent:
    ts: str        # when the scan completed, on the caller's clock (seconds)
    barcode: str     # the exact string the scanner read


class ScanReader:
    """Turns a completed keyboard-wedge string into a timestamped ScanEvent."""

    def __init__(self, on_scan, min_length: int = 1):
        self.on_scan = on_scan        # callback(ScanEvent) -> None
        self.min_length = min_length  # ignore anything shorter (stray Enter, noise)

    def submit(self, text: str, ts: float):
        """Call when the field receives Enter. `ts` is the read time."""
        barcode = text.strip()
        if len(barcode) < self.min_length:
            return None               # empty / too short -> not a real scan
        event = ScanEvent(ts=ts, barcode=barcode)
        self.on_scan(event)
        return event