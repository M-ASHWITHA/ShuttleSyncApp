"""Discrete-time campus shuttle simulator.

Stands in for real GPS feeds + boarding sensors so the whole platform can be demoed
and evaluated. In production, `Shuttle.pos`/`riders` would be fed by driver-app GPS
and boarding events; ETA, seat prediction and driver guidance stay the same.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from . import config as C
from .demand import DemandModel


def haversine(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_level(occupancy: int, capacity: int, seated: int | None = None) -> str:
    """SEATS_AVAILABLE -> FILLING -> STANDING (all seats taken) -> FULL."""
    seated = seated if seated is not None else round(capacity * 0.75)
    if occupancy >= capacity:
        return "FULL"
    if occupancy >= seated:
        return "STANDING"
    if occupancy >= 0.6 * seated:
        return "FILLING"
    return "SEATS_AVAILABLE"


@dataclass
class Shuttle:
    id: str
    name: str
    capacity: int
    pos: float                      # metres along the loop
    next_idx: int                   # index of next stop
    dwell_left: float = 0.0
    at_stop: int | None = None
    active: bool = True
    riders: Counter = field(default_factory=Counter)   # destination stop idx -> count
    skip_set: set = field(default_factory=set)         # stop idx the driver chose to skip
    number: int = 0                                    # fleet-wide shuttle number (#1, #2, ...)
    seated: int = C.SEATED_CAPACITY

    @property
    def occupancy(self) -> int:
        return sum(self.riders.values())


class Simulator:
    def __init__(self, stops=C.STOPS, demand: DemandModel | None = None, fleet_size=C.FLEET_SIZE,
                 capacity=C.SHUTTLE_CAPACITY, seed=1, start: datetime | None = None,
                 smart_skip=C.SMART_SKIP, demand_scale=1.0, route_id: str | None = None,
                 stop_share: dict | None = None):
        self.stops = list(stops)
        self.n = len(self.stops)
        self.demand = demand
        self.smart_skip = smart_skip
        self.demand_scale = demand_scale
        self.route_id = route_id
        self.stop_share = stop_share or {}   # fraction of a stop's demand served by this route
        self.rng = np.random.default_rng(seed)
        self.clock = start or datetime.now()
        self.speed = C.AVG_SPEED_MPS

        # route geometry (closed loop)
        self.seg = [haversine(self.stops[i].lat, self.stops[i].lon,
                              self.stops[(i + 1) % self.n].lat, self.stops[(i + 1) % self.n].lon)
                    for i in range(self.n)]
        self.cum = [sum(self.seg[:i]) for i in range(self.n)]
        self.L = sum(self.seg)
        self.stop_index = {s.id: i for i, s in enumerate(self.stops)}

        self.waiting = {i: 0 for i in range(self.n)}
        self.shuttles: list[Shuttle] = []
        for k in range(fleet_size):  # spread evenly around the loop
            idx = (k * self.n) // fleet_size
            sid, name = (f"R{route_id}-{k + 1}", f"Route {route_id}-{k + 1}") if route_id else (f"S{k + 1}", f"Shuttle {k + 1}")
            self.shuttles.append(Shuttle(sid, name, capacity, pos=self.cum[idx], next_idx=(idx + 1) % self.n))
        self.stats = Counter()
        self.wait_integral = [0.0] * self.n   # sum of waiting*dt per stop
        self.boarded = [0] * self.n

    # ---------------------------------------------------------------- helpers
    def dwell_time(self, people: int) -> float:
        return C.DWELL_BASE_S + C.DWELL_PER_PERSON_S * people

    def loop_time_estimate(self) -> float:
        return self.L / self.speed + self.n * self.dwell_time(8)

    def shuttle_by_id(self, sid: str) -> Shuttle:
        for s in self.shuttles:
            if s.id == sid:
                return s
        raise KeyError(sid)

    def seats(self, sid: str) -> int:
        s = self.shuttle_by_id(sid)
        return s.capacity - s.occupancy

    # ---------------------------------------------------------------- dynamics
    def add_waiting(self, stop_id: str, n: int = 1) -> None:
        self.waiting[self.stop_index[stop_id]] += n

    def request_skip(self, sid: str, stop_id: str) -> bool:
        """Driver taps 'Skip stop'. Only accepted if nobody is waiting or getting off."""
        sh = self.shuttle_by_id(sid)
        idx = self.stop_index[stop_id]
        if sh.riders.get(idx, 0) > 0 or self.waiting[idx] > 0:
            return False
        sh.skip_set.add(idx)
        return True

    def board_rider(self, sid: str, dest_stop_id: str | None = None, from_stop_id: str | None = None) -> bool:
        """A verified student boards (called by the driver-confirmation flow)."""
        s = self.shuttle_by_id(sid)
        if s.occupancy >= s.capacity:
            return False
        origin = self.stop_index.get(from_stop_id, s.at_stop if s.at_stop is not None else s.next_idx)
        dest = self.stop_index[dest_stop_id] if dest_stop_id else (origin + int(self.rng.integers(1, self.n))) % self.n
        s.riders[dest] += 1
        return True

    def step(self, dt: float) -> None:
        self.clock += timedelta(seconds=dt)
        hour, wd = self.clock.hour, self.clock.weekday()
        for i, stop in enumerate(self.stops):
            if self.demand is not None:
                lam = self.demand.rate(stop.id, hour, wd) * self.demand_scale * self.stop_share.get(stop.id, 1.0) * dt / 3600.0
                self.waiting[i] += int(self.rng.poisson(lam))
            self.wait_integral[i] += self.waiting[i] * dt
        for sh in self.shuttles:
            if not sh.active:
                continue
            self.stats["occ_seconds"] += sh.occupancy * dt
            self.stats["cap_seconds"] += sh.capacity * dt
            if sh.occupancy == 0:
                self.stats["empty_seconds"] += dt
            self._advance(sh, dt)

    def _advance(self, sh: Shuttle, dt: float) -> None:
        while dt > 1e-9:
            if sh.dwell_left > 0:
                used = min(dt, sh.dwell_left)
                sh.dwell_left -= used
                dt -= used
                if sh.dwell_left <= 1e-9:
                    sh.dwell_left, sh.at_stop = 0.0, None
                continue
            dist = (self.cum[sh.next_idx] - sh.pos) % self.L
            t_need = dist / self.speed
            if t_need <= dt:
                dt -= t_need
                idx = sh.next_idx
                sh.pos = self.cum[idx]
                sh.next_idx = (idx + 1) % self.n
                self._arrive(sh, idx)
            else:
                sh.pos = (sh.pos + self.speed * dt) % self.L
                dt = 0

    def _arrive(self, sh: Shuttle, idx: int) -> None:
        alight = sh.riders.pop(idx, 0)
        waiting = self.waiting[idx]
        skip_req = idx in sh.skip_set
        sh.skip_set.discard(idx)
        if (self.smart_skip or skip_req) and alight == 0 and waiting == 0:
            self.stats["skipped_stops"] += 1
            return
        board = min(waiting, sh.capacity - sh.occupancy)
        self.waiting[idx] -= board
        self.boarded[idx] += board
        self.stats["left_behind"] += waiting - board
        self.stats["trips_completed"] += alight
        self.stats["stops_served"] += 1
        for _ in range(board):
            sh.riders[(idx + int(self.rng.integers(1, self.n))) % self.n] += 1
        sh.dwell_left = self.dwell_time(alight + board)
        sh.at_stop = idx

    # ---------------------------------------------------------------- predictions
    def _project(self, sh: Shuttle, target: int):
        """Walk a shuttle forward to `target`; return (eta_seconds, predicted_occupancy)."""
        t = sh.dwell_left + ((self.cum[sh.next_idx] - sh.pos) % self.L) / self.speed
        occ = sh.occupancy
        riders = dict(sh.riders)
        i = sh.next_idx
        wait = dict(self.waiting)
        while i != target:
            alight = riders.pop(i, 0)
            w = wait[i]
            if not ((self.smart_skip or i in sh.skip_set) and alight == 0 and w == 0):
                board = min(w, sh.capacity - (occ - alight))
                occ = occ - alight + board
                t += self.dwell_time(alight + board)
            t += self.seg[i] / self.speed
            i = (i + 1) % self.n
        return t, occ

    def arrivals(self, stop_id: str) -> list[dict]:
        """ETA + predicted seat availability of every active shuttle for a stop."""
        target = self.stop_index[stop_id]
        out = []
        for sh in self.shuttles:
            if not sh.active:
                continue
            if sh.at_stop == target and sh.dwell_left > 0:
                eta, occ = 0.0, sh.occupancy
            else:
                eta, occ = self._project(sh, target)
            alight_here = dict(sh.riders).get(target, 0)
            seats = sh.capacity - max(0, occ - alight_here) if eta > 0 else sh.capacity - occ
            out.append({"shuttle_id": sh.id, "name": sh.name, "eta_sim_seconds": round(eta),
                        "seats_now": sh.capacity - sh.occupancy, "seats_on_arrival": max(0, seats),
                        "is_full": seats <= 0,
                        "load_on_arrival": load_level(sh.capacity - max(0, seats), sh.capacity, sh.seated)})
        return sorted(out, key=lambda a: a["eta_sim_seconds"])

    def position(self, sh: Shuttle) -> tuple[float, float]:
        d = sh.pos % self.L
        for i in range(self.n):
            if d <= self.cum[i] + self.seg[i] + 1e-6:
                f = (d - self.cum[i]) / self.seg[i] if self.seg[i] else 0
                a, b = self.stops[i], self.stops[(i + 1) % self.n]
                return a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f
        s = self.stops[0]
        return s.lat, s.lon

    def snapshot(self) -> list[dict]:
        out = []
        for sh in self.shuttles:
            lat, lon = self.position(sh)
            out.append({"id": sh.id, "name": sh.name, "lat": lat, "lon": lon, "active": sh.active,
                        "occupancy": sh.occupancy, "capacity": sh.capacity,
                        "number": sh.number, "load": load_level(sh.occupancy, sh.capacity, sh.seated),
                        "status": "BOARDING" if sh.at_stop is not None else "MOVING",
                        "next_stop": self.stops[sh.next_idx].name})
        return out

    def driver_view(self, sid: str, lookahead: int = 4) -> list[dict]:
        """Upcoming stops with waiting counts and a stop/skip recommendation."""
        sh = self.shuttle_by_id(sid)
        rows = []
        for k in range(lookahead):
            idx = (sh.next_idx + k) % self.n
            eta, occ_arrival = self._project(sh, idx)
            alight = sh.riders.get(idx, 0)
            waiting = self.waiting[idx]
            free_after_alight = sh.capacity - max(0, occ_arrival - alight)
            if alight == 0 and waiting == 0:
                rec, note = "SKIP", "Nobody waiting and nobody getting off"
            elif waiting > free_after_alight:
                rec, note = "STOP_FULL", f"{waiting - free_after_alight} will be left behind - alert control"
            else:
                rec, note = "STOP", ""
            rows.append({"stop_id": self.stops[idx].id, "stop": self.stops[idx].name,
                         "eta_sim_seconds": round(eta), "waiting": waiting, "alighting": alight,
                         "free_seats_on_arrival": max(0, free_after_alight),
                         "recommendation": rec, "note": note, "skip_confirmed": idx in sh.skip_set})
        return rows

    def summary(self) -> dict:
        boarded = sum(self.boarded)
        cap = self.stats["cap_seconds"] or 1
        served = self.stats["stops_served"]
        return {
            "avg_wait_seconds": round(sum(self.wait_integral) / boarded, 1) if boarded else 0.0,
            "students_boarded": boarded,
            "left_behind_events": self.stats["left_behind"],
            "avg_load_factor": round(self.stats["occ_seconds"] / cap, 3),
            "empty_shuttle_share": round(self.stats["empty_seconds"] / max(1, cap / self.shuttles[0].capacity), 3),
            "skipped_stops": self.stats["skipped_stops"],
            "stops_served": served,
            "still_waiting": sum(self.waiting.values()),
        }
