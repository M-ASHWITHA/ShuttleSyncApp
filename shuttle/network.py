"""Multi-route shuttle network: one Simulator per route, sharing a demand model.

Everything the student / driver / admin screens need is assembled here (pure Python,
no web framework), so it can be unit-tested and reused when real GPS replaces the simulator.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from . import config as C
from .demand import DemandModel
from .simulator import Simulator, load_level

LOAD_LABEL = {"SEATS_AVAILABLE": "Seats available", "FILLING": "Filling up", "STANDING": "Standing only", "FULL": "Full"}
DRIVER_LABEL = {"SEATS_AVAILABLE": "Available", "FILLING": "Available", "STANDING": "Standing only", "FULL": "Full"}


class Network:
    def __init__(self, demand: DemandModel, routes=C.ROUTES, stops=C.STOPS, seed: int = 1,
                 start: datetime | None = None, smart_skip: bool = C.SMART_SKIP,
                 demand_scale: float = C.DEMAND_SCALE):
        self.demand = demand
        self.demand_scale = demand_scale
        self.stops = {s.id: s for s in stops}
        self.routes = {r.id: r for r in routes}
        counts = Counter(sid for r in routes for sid in r.stops)
        self.sims: dict[str, Simulator] = {}
        for i, r in enumerate(routes):
            self.sims[r.id] = Simulator(
                stops=[self.stops[s] for s in r.stops], demand=demand, fleet_size=r.fleet, route_id=r.id,
                seed=seed + i, start=start, smart_skip=smart_skip, demand_scale=demand_scale,
                stop_share={s: 1 / counts[s] for s in r.stops})
        n = 0
        for sim in self.sims.values():          # fleet-wide shuttle numbers (#1, #2, ...)
            for sh in sim.shuttles:
                n += 1
                sh.number = n

    # ------------------------------------------------------------ basics
    @property
    def clock(self) -> datetime:
        return next(iter(self.sims.values())).clock

    def step(self, dt: float) -> None:
        for sim in self.sims.values():
            sim.step(dt)

    def find(self, shuttle_id: str):
        for sim in self.sims.values():
            for sh in sim.shuttles:
                if sh.id == shuttle_id:
                    return sim, sh
        raise KeyError(shuttle_id)

    def path_label(self, route_id: str, max_stops: int = 6) -> str:
        names = [self.stops[s].name for s in self.routes[route_id].stops]
        return " → ".join(names[:max_stops]) + (" → …" if len(names) > max_stops else "")

    def routes_serving(self, stop_id: str) -> list[str]:
        return [rid for rid, r in self.routes.items() if stop_id in r.stops]

    def total_waiting(self, stop_id: str) -> int:
        return sum(sim.waiting[sim.stop_index[stop_id]] for sim in self.sims.values() if stop_id in sim.stop_index)

    def add_waiting(self, stop_id: str, route_id: str | None = None, n: int = 1) -> None:
        rid = route_id if route_id in self.sims and stop_id in self.sims[route_id].stop_index else self.routes_serving(stop_id)[0]
        self.sims[rid].add_waiting(stop_id, n)

    def stops_info(self) -> list[dict]:
        return [{"id": s.id, "name": s.name, "lat": s.lat, "lon": s.lon, "kind": s.kind,
                 "routes": self.routes_serving(s.id), "waiting": self.total_waiting(s.id)}
                for s in self.stops.values()]

    def routes_info(self) -> list[dict]:
        return [{"id": r.id, "code": r.code, "name": f"Route {r.id}", "path": self.path_label(r.id, 99),
                 "stops": [{"id": s, "name": self.stops[s].name} for s in r.stops], "shuttles": r.fleet}
                for r in self.routes.values()]

    def snapshot(self) -> list[dict]:
        out = []
        for rid, sim in self.sims.items():
            for row in sim.snapshot():
                out.append({**row, "route_id": rid, "route_code": self.routes[rid].code})
        return out

    # ------------------------------------------------------------ student
    def stop_options(self, stop_id: str) -> list[dict]:
        """Soonest shuttle of each route serving the stop. Available shuttles first (soonest first), full ones last."""
        opts = []
        for rid in self.routes_serving(stop_id):
            a = self.sims[rid].arrivals(stop_id)[0]
            opts.append({**a, "route_id": rid, "route_code": self.routes[rid].code, "route_name": f"Route {rid}",
                         "path": self.path_label(rid), "badge": "Full" if a["is_full"] else "Available"})
        return sorted(opts, key=lambda o: (o["is_full"], o["eta_sim_seconds"]))

    def track(self, shuttle_id: str, stop_id: str | None = None) -> dict:
        sim, sh = self.find(shuttle_id)
        rid = sim.route_id
        upcoming = []
        for k in range(min(4, sim.n)):
            idx = (sh.next_idx + k) % sim.n
            eta, _ = sim._project(sh, idx)
            upcoming.append({"stop_id": sim.stops[idx].id, "stop": sim.stops[idx].name, "eta_sim_seconds": round(eta)})
        target = None
        if stop_id and stop_id in sim.stop_index:
            target = next((a for a in sim.arrivals(stop_id) if a["shuttle_id"] == shuttle_id), None)
        # bunching check vs. the other shuttles on this route
        status = "On schedule"
        others = [o for o in sim.shuttles if o.id != sh.id and o.active]
        if others:
            gap = min((o.pos - sh.pos) % sim.L for o in others)
            if gap / (sim.L / len(sim.shuttles)) < 0.5:
                status = "Close behind another shuttle"
        level = load_level(sh.occupancy, sh.capacity, sh.seated)
        free = sh.capacity - sh.occupancy
        return {"shuttle_id": shuttle_id, "number": sh.number, "route_id": rid, "route_code": self.routes[rid].code,
                "route_name": f"Route {rid}", "path": self.path_label(rid, 99),
                "seated": sh.seated, "free": free,
                "stops": [{"id": s.id, "name": s.name} for s in sim.stops],
                "start": sim.stops[0].name, "end": sim.stops[-1].name,
                "progress": (sh.pos % sim.L) / sim.L, "stop_fractions": [c / sim.L for c in sim.cum], "next_stop": sim.stops[sh.next_idx].name,
                "at_stop": sim.stops[sh.at_stop].name if sh.at_stop is not None else None,
                "schedule": status, "occupancy": sh.occupancy, "capacity": sh.capacity,
                "load": level, "status_label": LOAD_LABEL[level],
                "target": target, "upcoming": upcoming}

    # ------------------------------------------------------------ driver
    def driver_overview(self, shuttle_id: str) -> dict:
        sim, sh = self.find(shuttle_id)
        rows = sim.driver_view(shuttle_id, sim.n)
        suggestion = None
        skip = next((r for r in rows if r["recommendation"] == "SKIP" and not r["skip_confirmed"]), None)
        alert = next((r for r in rows if r["recommendation"] == "STOP_FULL"), None)
        if alert:
            suggestion = {"type": "ALERT", "stop_id": alert["stop_id"],
                          "message": f"{alert['note'][0].upper()}{alert['note'][1:]}. Consider requesting a relief shuttle."}
        elif skip:
            mins = max(1, round(C.SKIP_SAVING_S / 60))
            suggestion = {"type": "SKIP", "stop_id": skip["stop_id"], "stop": skip["stop"], "saving_minutes": mins,
                          "message": f"No students waiting at {skip['stop']}. Skip this stop to save "
                                     f"{mins} minute{'s' if mins != 1 else ''} on this run."}
        level = load_level(sh.occupancy, sh.capacity, sh.seated)
        return {"shuttle_id": shuttle_id, "number": sh.number, "name": sh.name, "route_id": sim.route_id,
                "route_code": self.routes[sim.route_id].code, "route_name": f"Route {self.routes[sim.route_id].code}",
                "status_pill": "Boarding" if sh.at_stop is not None else "On route",
                "occupancy": sh.occupancy, "capacity": sh.capacity, "load": level, "status_label": DRIVER_LABEL[level],
                "suggestion": suggestion, "upcoming": rows}

    def all_shuttle_ids(self) -> list[dict]:
        return [{"id": sh.id, "number": sh.number, "name": f"Shuttle #{sh.number}", "route_id": sim.route_id,
                 "route_code": self.routes[sim.route_id].code} for sim in self.sims.values() for sh in sim.shuttles]

    # ------------------------------------------------------------ admin
    def summary(self) -> dict:
        tot = Counter()
        wait_int = 0.0
        boarded = 0
        for sim in self.sims.values():
            tot.update(sim.stats)
            wait_int += sum(sim.wait_integral)
            boarded += sum(sim.boarded)
            tot["still_waiting"] += sum(sim.waiting.values())
        cap = tot["cap_seconds"] or 1
        return {"avg_wait_seconds": round(wait_int / boarded, 1) if boarded else 0.0,
                "students_boarded": boarded, "avg_load_factor": round(tot["occ_seconds"] / cap, 3),
                "left_behind_events": tot["left_behind"], "skipped_stops": tot["skipped_stops"],
                "still_waiting": tot["still_waiting"]}
