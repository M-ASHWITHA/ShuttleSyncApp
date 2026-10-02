import unittest
from datetime import datetime

from shuttle import analytics as A
from shuttle.demand import build_default_model
from shuttle.network import Network


class InsightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.net = Network(build_default_model(), start=datetime(2026, 9, 21, 7, 30))   # a Monday
        for _ in range(300):
            cls.net.step(4.0)

    def test_options_sorted_available_first_and_have_badges(self):
        for stop in self.net.stops:
            o = self.net.stop_options(stop)
            self.assertTrue(o)
            self.assertTrue(all(x["badge"] in ("Available", "Full") for x in o))
            flags = [x["is_full"] for x in o]
            self.assertEqual(flags, sorted(flags))          # full shuttles are listed last

    def test_shuttles_have_unique_numbers(self):
        nums = [s["number"] for s in self.net.all_shuttle_ids()]
        self.assertEqual(sorted(nums), list(range(1, len(nums) + 1)))

    def test_heatmap_shape_and_levels(self):
        h = A.heatmap(self.net, 0)
        self.assertEqual(len(h["slots"]), 6)
        self.assertEqual([r["name"] for r in h["rows"]], ["Route A", "Route B", "Route C", "Route D"])
        levels = [c["level"] for r in h["rows"] for c in r["cells"]]
        self.assertTrue(all(1 <= x <= 5 for x in levels)); self.assertIn(5, levels)

    def test_reallocation_message(self):
        r = A.reallocation(self.net, 0)
        self.assertIn("Route", r["message"])
        if r["action"] == "MOVE":
            self.assertNotEqual(r["from_route"], r["to_route"])

    def test_slot_text(self):
        self.assertEqual(A.slot_text((17, 19)), "5–7 PM")
        self.assertEqual(A.slot_text((7, 9)), "7–9 AM")
        self.assertEqual(A.slot_text((11, 13)), "11 AM–1 PM")

    def test_driver_overview_has_header_fields(self):
        sid = self.net.all_shuttle_ids()[0]["id"]
        o = self.net.driver_overview(sid)
        self.assertIn(o["status_label"], ("Available", "Standing only", "Full"))
        self.assertTrue(o["route_name"].startswith("Route "))


if __name__ == "__main__":
    unittest.main()
