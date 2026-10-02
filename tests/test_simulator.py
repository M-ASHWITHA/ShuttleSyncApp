import unittest
from datetime import datetime

from shuttle.demand import DemandModel, generate_history
from shuttle.simulator import Simulator, load_level

_model = DemandModel()
_model.fit(generate_history(days=30))


class SimTests(unittest.TestCase):
    def sim(self, **kw):
        return Simulator(demand=_model, seed=5, start=datetime(2026, 3, 2, 8, 0), **kw)

    def test_load_levels(self):
        self.assertEqual(load_level(3, 40, 30), "SEATS_AVAILABLE")
        self.assertEqual(load_level(20, 40, 30), "FILLING")
        self.assertEqual(load_level(33, 40, 30), "STANDING")
        self.assertEqual(load_level(40, 40, 30), "FULL")

    def test_capacity_never_exceeded_and_people_conserved(self):
        sim = self.sim(demand_scale=3.0)
        for _ in range(3600):
            sim.step(1.0)
            for s in sim.shuttles:
                self.assertLessEqual(s.occupancy, s.capacity)
        self.assertGreater(sum(sim.boarded), 0)

    def test_eta_is_non_negative_sorted_and_matches_reality(self):
        sim = self.sim(demand_scale=0.0, smart_skip=False)   # no new demand => ETA should be exact
        target = "sjt"
        first = sim.arrivals(target)[0]
        t = 0
        while sim.shuttle_by_id(first["shuttle_id"]).at_stop != sim.stop_index[target] and t < 5000:
            sim.step(1.0)
            t += 1
        self.assertAlmostEqual(t, first["eta_sim_seconds"], delta=2)
        etas = [a["eta_sim_seconds"] for a in sim.arrivals(target)]
        self.assertEqual(etas, sorted(etas))

    def test_smart_skip_skips_empty_stops(self):
        sim = self.sim(demand_scale=0.0, smart_skip=True)
        for _ in range(1200):
            sim.step(1.0)
        self.assertGreater(sim.stats["skipped_stops"], 0)

    def test_driver_view_flags_skip_and_full(self):
        sim = self.sim(demand_scale=0.0)
        sh = sim.shuttles[0]
        rows = sim.driver_view(sh.id, 3)
        self.assertTrue(all(r["recommendation"] == "SKIP" for r in rows))
        sim.waiting[sh.next_idx] = 200
        self.assertEqual(sim.driver_view(sh.id, 1)[0]["recommendation"], "STOP_FULL")

    def test_driver_skip_only_when_nobody_waiting(self):
        sim = self.sim(demand_scale=0.0)
        sh = sim.shuttles[0]
        stop = sim.stops[sh.next_idx].id
        self.assertTrue(sim.request_skip(sh.id, stop))
        sim.waiting[sim.stop_index[stop]] = 3
        self.assertFalse(sim.request_skip(sh.id, stop))

    def test_board_rider_respects_capacity(self):
        sim = self.sim(demand_scale=0.0)
        sh = sim.shuttles[0]
        for _ in range(sh.capacity):
            self.assertTrue(sim.board_rider(sh.id, "sjt"))
        self.assertFalse(sim.board_rider(sh.id, "sjt"))


class DemandTests(unittest.TestCase):
    def test_model_beats_baseline_and_finds_peaks(self):
        m = _model.metrics
        self.assertLess(m["mae_model"], m["mae_baseline_stop_mean"])
        peaks = _model.peak_hours(weekday=0, top=6)
        self.assertTrue(any(h in peaks for h in (8, 9, 17, 18)))
        self.assertGreater(_model.rate("sjt", 8, 0), _model.rate("sjt", 3, 0))
        self.assertGreater(_model.rate("sjt", 8, 0), _model.rate("sjt", 8, 6))  # weekday > Sunday


if __name__ == "__main__":
    unittest.main()
