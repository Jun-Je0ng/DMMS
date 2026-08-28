import unittest

from simulated_barcode import SimulatedBarcodeSource

FLIGHTS = [
    {"flight_number": "QA298", "destination": "SYD"},
    {"flight_number": "LM219", "destination": "CGK"},
]


class SimulatedBarcodeSourceTest(unittest.TestCase):
    def test_tag_format(self):
        src = SimulatedBarcodeSource(FLIGHTS)
        self.assertEqual(src.next_tag(), "QA298-SYD")

    def test_lookup_matches_generated_tag(self):
        src = SimulatedBarcodeSource(FLIGHTS)
        tag = src.next_tag()
        self.assertEqual(src.lookup(tag), FLIGHTS[0])

    def test_cycles_and_repeats(self):
        src = SimulatedBarcodeSource(FLIGHTS)
        tags = [src.next_tag() for _ in range(4)]
        self.assertEqual(tags, ["QA298-SYD", "LM219-CGK", "QA298-SYD", "LM219-CGK"])

    def test_unknown_tag_returns_empty(self):
        src = SimulatedBarcodeSource(FLIGHTS)
        self.assertEqual(src.lookup("NEVER-SEEN"), {})

    def test_empty_flights_rejected(self):
        with self.assertRaises(ValueError):
            SimulatedBarcodeSource([])


if __name__ == "__main__":
    unittest.main()
