import unittest
from datetime import datetime

from shuttle.demand import DemandModel, generate_history
from shuttle.network import Network

_model = DemandModel()
_model.fit(generate_history(days=30))


def make(hour=8):
    n = Network(_model, start=datetime(2026, 3, 2, hour, 0))
    for _ in range(600):
        n.step(4.0)
    return n


class NetworkTests(unittest.TestCase):
    def test_options_one_per_route_sorted(self):
        n = make()
        opts = n.stop_options("main_gate")
        self.assertEqual(sorted(o["route_id"] for o in opts), ["1", "2", "3", "4"])
        etas = [o["eta_sim_seconds"] for o in opts]
        self.assertEqual(etas, sorted(etas))
        self.assertEqual(sorted(o["route_id"] for o in n.stop_options("ladies_hostel")), ["1", "2"])

    def test_route_paths_match_design(self):
        n = make()
        self.assertEqual(n.path_label("1"), "PRP → SJT → Ladies Hostel → Main Gate")
        self.assertEqual(n.path_label("4"), "Main Gate → Men's Hostel")

    def test_demand_is_split_not_duplicated(self):
        n = make()
        self.assertAlmostEqual(sum(sim.stop_share["main_gate"] for sim in n.sims.values()), 1.0)

    def test_track_details(self):
        n = make()
        t = n.track("R1-1", "sjt")
        self.assertEqual(t["route_id"], "1")
        self.assertTrue(0 <= t["progress"] < 1 and len(t["stop_fractions"]) == len(t["stops"]))
        self.assertIsNotNone(t["target"])
        self.assertEqual((t["start"], t["end"]), ("PRP", "Main Gate"))
        self.assertLessEqual(len(t["upcoming"]), 4)

    def test_capacity_never_exceeded(self):
        n = make()
        for _ in range(1800):
            n.step(2.0)
            for sim in n.sims.values():
                for s in sim.shuttles:
                    self.assertLessEqual(s.occupancy, s.capacity)

    def test_checkin_adds_waiting(self):
        n = make()
        before = n.total_waiting("main_gate")
        n.add_waiting("main_gate", "1")
        self.assertEqual(n.total_waiting("main_gate"), before + 1)


if __name__ == "__main__":
    unittest.main()
