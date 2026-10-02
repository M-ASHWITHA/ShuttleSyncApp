"""Admin analytics: route x time demand heatmap, fleet reallocation advice, efficiency gains.

Routes are shown with their operations letters (A-D) on the admin screen, as in the design.
"""
from __future__ import annotations

import math

from . import config as C
from .network import Network

SLOTS = [(7, 9), (9, 11), (11, 13), (13, 15), (15, 17), (17, 19)]
LEVEL_EDGES = (0.25, 0.45, 0.65, 0.82)    # sqrt(pressure / busiest cell) -> heat level 1..5
TARGET_LOAD = 0.75
SERVICE_HOURS = range(6, 24)


def route_demand(net: Network, rid: str, weekday: int, hour: int) -> float:
    """Expected students/hour who will use this route (a stop's demand is split across the routes serving it)."""
    sim = net.sims[rid]
    return sum(net.demand.rate(s.id, hour, weekday) * net.demand_scale * sim.stop_share[s.id] for s in sim.stops)


def route_capacity_per_hour(net: Network, rid: str) -> float:
    sim = net.sims[rid]
    return len(sim.shuttles) * C.SHUTTLE_CAPACITY * 3600 / sim.loop_time_estimate()


def slot_demand(net: Network, rid: str, weekday: int, slot: tuple[int, int]) -> float:
    hrs = range(slot[0], slot[1])
    return sum(route_demand(net, rid, weekday, h) for h in hrs) / len(hrs)


def pressure(net: Network, rid: str, weekday: int, slot: tuple[int, int]) -> float:
    return slot_demand(net, rid, weekday, slot) / route_capacity_per_hour(net, rid)


def level(p: float, peak: float) -> int:
    """Heat shade 1 (lightest) .. 5 (darkest), relative to the busiest cell like the design's heatmap."""
    r = math.sqrt(max(p, 0) / peak) if peak > 0 else 0
    return 1 + sum(r >= e for e in LEVEL_EDGES)


def _h12(h: int) -> tuple[int, str]:
    return (h % 12 or 12), ("AM" if h < 12 else "PM")


def slot_text(slot: tuple[int, int]) -> str:
    (a, am), (b, bm) = _h12(slot[0]), _h12(slot[1])
    return f"{a}–{b} {bm}" if am == bm else f"{a} {am}–{b} {bm}"


def heatmap(net: Network, weekday: int) -> dict:
    rows = []
    peak = max(pressure(net, rid, weekday, slot) for rid in net.routes for slot in SLOTS)
    for rid, r in net.routes.items():
        cells = []
        for slot in SLOTS:
            p = pressure(net, rid, weekday, slot)
            cells.append({"level": level(p, peak), "pressure": round(p, 2), "demand": round(slot_demand(net, rid, weekday, slot))})
        rows.append({"route_id": rid, "route_code": r.code, "name": f"Route {r.code}", "cells": cells})
    return {"slots": [f"{a}–{b}" for a, b in SLOTS], "rows": rows}


def reallocation(net: Network, weekday: int) -> dict:
    """Find the most overloaded (route, window) and suggest moving a shuttle from the least-loaded route."""
    best = max(((pressure(net, rid, weekday, slot), rid, slot) for rid in net.routes for slot in SLOTS))
    p_hi, hi, slot = best
    donors = [r for r in net.routes if r != hi and len(net.sims[r].shuttles) > 1]
    lo = min(donors, key=lambda r: pressure(net, r, weekday, slot)) if donors else None
    hc = net.routes[hi].code
    if lo and p_hi > 1.0 and pressure(net, lo, weekday, slot) < 0.75:
        lc = net.routes[lo].code
        pct = round((p_hi - 1) * 100)
        return {"action": "MOVE", "from_route": lc, "to_route": hc, "window": slot_text(slot),
                "message": f"Move 1 shuttle from Route {lc} to Route {hc} between {slot_text(slot)} — "
                           f"Route {hc} demand is predicted {pct}% higher than fleet supply in that window."}
    return {"action": "NONE", "from_route": None, "to_route": None, "window": slot_text(slot),
            "message": f"Fleet supply covers predicted demand in every window — the busiest is Route {hc} "
                       f"between {slot_text(slot)} at {round(p_hi * 100)}% of capacity."}


def fleet_plan(net: Network, weekday: int) -> dict:
    fleet = sum(len(s.shuttles) for s in net.sims.values())
    per_shuttle = sum(route_capacity_per_hour(net, r) for r in net.routes) / fleet
    hours = []
    for h in range(24):
        total = sum(route_demand(net, r, weekday, h) for r in net.routes)
        need = max(1, math.ceil(total / (per_shuttle * TARGET_LOAD))) if h in SERVICE_HOURS else 0
        hours.append({"hour": h, "expected_demand": round(total), "recommended_shuttles": need})
    static = fleet * len(SERVICE_HOURS)
    dynamic = sum(min(x["recommended_shuttles"], fleet) for x in hours)
    return {"fleet": fleet, "hours": hours, "static_shuttle_hours": static, "recommended_shuttle_hours": dynamic,
            "shuttle_hours_saved_pct": round(100 * (static - dynamic) / static, 1)}


def efficiency(net: Network) -> dict:
    per_route = {net.routes[rid].code: sim.stats["skipped_stops"] for rid, sim in net.sims.items()}
    code, skipped = max(per_route.items(), key=lambda kv: kv[1])
    mins = round(skipped * C.SKIP_SAVING_S / 60)
    if skipped == 0:
        msg = "No stops skipped yet — accept the AI suggestions in the Driver app to save running time."
    else:
        msg = f"Skipping empty stops on Route {code} saved an estimated {mins} minutes of running time so far."
    return {"skipped_stops": sum(per_route.values()), "minutes_saved": round(sum(per_route.values()) * C.SKIP_SAVING_S / 60),
            "message": msg}


def alerts(net: Network) -> list[dict]:
    out = []
    for rid, sim in net.sims.items():
        for i, s in enumerate(sim.stops):
            w = sim.waiting[i]
            if w >= 0.6 * C.SHUTTLE_CAPACITY:
                out.append({"route_code": net.routes[rid].code, "stop": s.name, "waiting": w,
                            "message": f"{w} students waiting at {s.name} (Route {net.routes[rid].code}) — dispatch a relief shuttle."})
    return out
