import unittest

from pairing import Pairer


def flight_lookup(tag_id):
    return {"flight_number": "QF1", "destination": "SYD"}


class PairerTest(unittest.TestCase):
    def test_matched(self):
        p = Pairer(pair_window=4.0, flight_lookup=flight_lookup)
        p.submit_scan(ts=100.0, barcode="TAG1")
        r = p.resolve_trigger(ts=101.0)
        self.assertEqual(r.status, "matched")
        self.assertEqual(r.tag_id, "TAG1")
        self.assertEqual(r.flight_number, "QF1")
        self.assertEqual(p.pending_scans, [])  # scan is claimed, not left pending

    def test_manual_when_no_scan_nearby(self):
        p = Pairer(pair_window=4.0, flight_lookup=flight_lookup)
        r = p.resolve_trigger(ts=100.0)
        self.assertEqual(r.status, "manual")
        self.assertIsNone(r.tag_id)

    def test_scan_outside_window_is_not_claimed(self):
        p = Pairer(pair_window=4.0, flight_lookup=flight_lookup)
        p.submit_scan(ts=100.0, barcode="TAG1")
        r = p.resolve_trigger(ts=200.0)  # far outside the 4s window
        self.assertEqual(r.status, "manual")
        self.assertEqual(len(p.pending_scans), 1)  # scan still pending, untouched

    def test_ambiguous_with_two_candidates(self):
        p = Pairer(pair_window=4.0, flight_lookup=flight_lookup)
        p.submit_scan(ts=99.0, barcode="TAG1")
        p.submit_scan(ts=101.0, barcode="TAG2")
        r = p.resolve_trigger(ts=100.0)
        self.assertEqual(r.status, "ambiguous")
        self.assertIsNone(r.tag_id)
        self.assertEqual(p.pending_scans, [])  # both candidates consumed

    def test_duplicate_within_loop_window(self):
        p = Pairer(pair_window=4.0, loop_window=200.0, flight_lookup=flight_lookup)
        p.submit_scan(ts=100.0, barcode="TAG1")
        first = p.resolve_trigger(ts=100.0)
        self.assertEqual(first.status, "matched")

        p.submit_scan(ts=150.0, barcode="TAG1")
        second = p.resolve_trigger(ts=150.0)
        self.assertEqual(second.status, "duplicate")
        self.assertEqual(second.tag_id, "TAG1")
        self.assertEqual(second.flight_number, "QF1")  # reuses the original match, doesn't re-roll

    def test_same_tag_after_loop_window_is_a_fresh_match(self):
        p = Pairer(pair_window=4.0, loop_window=50.0, flight_lookup=flight_lookup)
        p.submit_scan(ts=100.0, barcode="TAG1")
        p.resolve_trigger(ts=100.0)

        p.submit_scan(ts=200.0, barcode="TAG1")  # 100s later, past the 50s loop window
        r = p.resolve_trigger(ts=200.0)
        self.assertEqual(r.status, "matched")

    def test_sweep_unmatched_expires_stale_scans(self):
        p = Pairer(pair_window=4.0)
        p.submit_scan(ts=100.0, barcode="TAG1")
        # Not stale yet: a trigger at ts=103 would still be within the window.
        self.assertEqual(p.sweep_unmatched(now=103.0), [])
        # Stale now: even a trigger at "now" (110) is outside the window.
        stale = p.sweep_unmatched(now=110.0)
        self.assertEqual(stale, [(100.0, "TAG1")])
        self.assertEqual(p.pending_scans, [])

    # -- Sequential pairing: "the scanner only counts once the sensor fires" --

    def test_take_since_splits_candidates_from_earlier_orphans(self):
        p = Pairer(pair_window=4.0)
        p.submit_scan(ts=95.0, barcode="STALE")   # arrived before this trigger
        p.submit_scan(ts=101.0, barcode="FRESH")  # arrived after
        candidates, expired = p.take_since(ts=100.0)
        self.assertEqual(candidates, [(101.0, "FRESH")])
        self.assertEqual(expired, [(95.0, "STALE")])
        self.assertEqual(p.pending_scans, [])  # both removed either way

    def test_candidates_since_does_not_mutate(self):
        p = Pairer(pair_window=4.0)
        p.submit_scan(ts=101.0, barcode="FRESH")
        seen = p.candidates_since(ts=100.0)
        self.assertEqual(seen, [(101.0, "FRESH")])
        self.assertEqual(p.pending_scans, [(101.0, "FRESH")])  # still pending

    def test_resolve_candidates_matched(self):
        p = Pairer(flight_lookup=flight_lookup)
        r = p.resolve_candidates(ts=100.0, candidates=[(100.5, "TAG1")])
        self.assertEqual(r.status, "matched")
        self.assertEqual(r.tag_id, "TAG1")

    def test_sequential_flow_end_to_end(self):
        p = Pairer(pair_window=4.0, loop_window=200.0, flight_lookup=flight_lookup)
        p.submit_scan(ts=95.0, barcode="OLD")     # leftover from before this bag
        p.submit_scan(ts=101.5, barcode="TAG1")   # the real scan for this bag

        candidates, expired = p.take_since(ts=100.0)
        self.assertEqual(expired, [(95.0, "OLD")])
        r = p.resolve_candidates(ts=100.0, candidates=candidates)
        self.assertEqual(r.status, "matched")
        self.assertEqual(r.tag_id, "TAG1")


if __name__ == "__main__":
    unittest.main()
