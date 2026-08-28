"""
Burst detector -- distinguishes a barcode scanner's rapid keystroke burst
from ordinary human typing, using inter-keystroke timing alone. A USB
keyboard-wedge scanner injects an entire tag's characters far faster than
any person types -- even a fast typist rarely goes below ~60-80ms between
keys, while scanners typically inject characters only a few ms apart.

This exists because global keyboard listening (scanner_capture.py) sees
EVERY keystroke typed anywhere on the machine while it runs, not just the
scanner's -- this is what keeps that from behaving like a keylogger: only a
fast burst terminated promptly by Enter is ever reported as a scan.

Pure logic: takes (char, ts) in, no clock reads, no I/O -- testable with
nothing attached (mirrors the style of scanner.py).
"""

from typing import List, Optional


class BurstDetector:
    """
    max_gap: the longest pause (seconds) allowed between consecutive
        keystrokes -- including the final one before Enter -- for them to
        still count as one scanner burst. Tune this here if real scans get
        missed (raise it) or ordinary typing gets mistaken for a scan
        (lower it).
    """

    def __init__(self, max_gap: float = 0.05):
        self.max_gap = max_gap
        self._buffer: List[str] = []
        self._last_ts: Optional[float] = None

    def feed_char(self, ch: str, ts: float) -> None:
        """Call for every regular character key press."""
        if self._last_ts is not None and (ts - self._last_ts) > self.max_gap:
            self._buffer = []  # gap too large -- previous chars weren't a burst with this one
        self._buffer.append(ch)
        self._last_ts = ts

    def feed_enter(self, ts: float) -> Optional[str]:
        """
        Call when Enter is pressed. Returns the completed barcode if Enter
        arrived promptly (within max_gap) after a non-empty burst;
        otherwise discards the buffer and returns None. Resets state
        either way, so the next character starts a fresh attempt.
        """
        is_burst = self._last_ts is not None and (ts - self._last_ts) <= self.max_gap
        text = "".join(self._buffer)
        self.reset()
        return text if (is_burst and text) else None

    def reset(self) -> None:
        """Call on any key that isn't part of a scan (Backspace, arrows, ...) to break a burst in progress."""
        self._buffer = []
        self._last_ts = None
