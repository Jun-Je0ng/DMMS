import unittest

from burst_detector import BurstDetector


class BurstDetectorTest(unittest.TestCase):
    def test_fast_burst_terminated_by_enter_is_a_scan(self):
        d = BurstDetector(max_gap=0.05)
        d.feed_char("A", 100.00)
        d.feed_char("B", 100.01)
        d.feed_char("1", 100.02)
        result = d.feed_enter(100.03)
        self.assertEqual(result, "AB1")

    def test_slow_typing_is_not_a_scan(self):
        d = BurstDetector(max_gap=0.05)
        d.feed_char("h", 100.0)
        d.feed_char("i", 100.2)   # 200ms gap -- ordinary typing speed
        result = d.feed_enter(100.4)
        self.assertIsNone(result)

    def test_enter_arriving_late_after_a_fast_burst_is_not_a_scan(self):
        # Someone typed fast then paused before hitting Enter -- common for
        # a human, not how a scanner behaves (it sends Enter immediately).
        d = BurstDetector(max_gap=0.05)
        d.feed_char("A", 100.00)
        d.feed_char("B", 100.01)
        result = d.feed_enter(100.50)
        self.assertIsNone(result)

    def test_empty_enter_is_not_a_scan(self):
        d = BurstDetector(max_gap=0.05)
        result = d.feed_enter(100.0)
        self.assertIsNone(result)

    def test_gap_mid_burst_discards_only_the_earlier_chars(self):
        d = BurstDetector(max_gap=0.05)
        d.feed_char("X", 100.00)
        d.feed_char("Y", 100.30)  # big gap -- discards "X"
        d.feed_char("Z", 100.31)
        result = d.feed_enter(100.32)
        self.assertEqual(result, "YZ")

    def test_reset_clears_in_progress_buffer(self):
        d = BurstDetector(max_gap=0.05)
        d.feed_char("A", 100.00)
        d.feed_char("B", 100.01)
        d.reset()
        d.feed_char("C", 100.02)
        result = d.feed_enter(100.03)
        self.assertEqual(result, "C")

    def test_state_resets_after_a_completed_scan(self):
        d = BurstDetector(max_gap=0.05)
        d.feed_char("A", 100.00)
        d.feed_enter(100.01)
        d.feed_char("B", 200.00)  # unrelated, much later
        result = d.feed_enter(200.01)
        self.assertEqual(result, "B")


if __name__ == "__main__":
    unittest.main()
