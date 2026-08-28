import json
import os
import tempfile
import unittest

from activity_feed import ActivityFeed


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class ActivityFeedTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_starts_empty(self):
        ActivityFeed(self.path)
        self.assertEqual(read_json(self.path), [])

    def test_add_appends_and_persists(self):
        feed = ActivityFeed(self.path)
        feed.add("trigger", 100.0, "bag_1")
        feed.add("scan", 100.5, "QA298-SYD")
        on_disk = read_json(self.path)
        self.assertEqual(len(on_disk), 2)
        self.assertEqual(on_disk[0]["kind"], "trigger")
        self.assertEqual(on_disk[1]["detail"], "QA298-SYD")

    def test_caps_at_max_entries(self):
        feed = ActivityFeed(self.path, max_entries=3)
        for i in range(5):
            feed.add("scan", float(i), f"TAG{i}")
        on_disk = read_json(self.path)
        self.assertEqual(len(on_disk), 3)
        self.assertEqual([e["detail"] for e in on_disk], ["TAG2", "TAG3", "TAG4"])


if __name__ == "__main__":
    unittest.main()
