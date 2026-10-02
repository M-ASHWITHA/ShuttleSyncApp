"""ShuttleSync API: student app, driver app and admin dashboard + static web UI.

Run:  python -m uvicorn shuttle.main:app --reload      then open http://localhost:8000
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analytics
from . import config as C
from .demand import build_default_model
from .network import Network
from .payments import PaymentError, PaymentService

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class State:
    demand = None
    net: Network = None
    pay: PaymentService = None


S = State()


async def _ticker():
    """Advance the simulated campus once per real second (SIM_SPEEDUP sim-seconds each)."""
    while True:
        await asyncio.sleep(1.0)
        S.net.step(C.SIM_SPEEDUP)


def _demo_start() -> datetime | None:
    """Demo clock starts at 07:30 on the next weekday so the morning rush is visible.
    Set SIM_REALTIME=1 to follow the real wall clock instead."""
    if os.getenv("SIM_REALTIME") == "1":
        return None
    d = datetime.now().replace(hour=7, minute=30, second=0, microsecond=0)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


@asynccontextmanager
async def lifespan(app: FastAPI):
    S.demand = build_default_model()
    S.net = Network(S.demand, start=_demo_start())
    for _ in range(900):               # warm-up so the demo starts with realistic crowds
        S.net.step(4.0)
    S.pay = PaymentService(C.DB_PATH)
    task = asyncio.create_task(_ticker())
    yield
    task.cancel()


app = FastAPI(title="ShuttleSync - Smart Campus Shuttle", version="1.0.0", lifespan=lifespan)


def _real(sim_seconds: float) -> int:
    """Simulated seconds -> real seconds (the sim runs SIM_SPEEDUP x faster than the clock)."""
    return round(sim_seconds / C.SIM_SPEEDUP)


def _stop(stop_id: str):
    if stop_id not in S.net.stops:
        raise HTTPException(404, "Unknown stop")
    return S.net.stops[stop_id]


def _shuttle(shuttle_id: str):
    try:
        return S.net.find(shuttle_id)
    except KeyError:
        raise HTTPException(404, "Unknown shuttle")


def _err(e: PaymentError):
    raise HTTPException(e.http, e.to_dict())


def _real_etas(rows: list[dict]) -> list[dict]:
    for r in rows:
        r["eta_seconds"] = _real(r.pop("eta_sim_seconds"))
    return rows


# ------------------------------------------------------------------ live data (student)
@app.get("/api/config")
def get_config():
    return {"fare": C.FARE_INR, "paylater_daily_limit": C.PAYLATER_DAILY_LIMIT, "cash_timeout_seconds": C.CASH_TIMEOUT_SECONDS,
            "upi_apps": list(C.UPI_APPS), "sim_speedup": C.SIM_SPEEDUP, "demand_model": S.demand.metrics}


@app.get("/api/stops")
def list_stops():
    return S.net.stops_info()


@app.get("/api/routes")
def list_routes():
    return S.net.routes_info()


@app.get("/api/shuttles")
def list_shuttles():
    return S.net.snapshot()


@app.get("/api/stops/{stop_id}/options")
def stop_options(stop_id: str):
    """'Closest shuttle' + 'Also on this route' for a stop."""
    stop = _stop(stop_id)
    return {"stop_id": stop_id, "stop": stop.name, "waiting": S.net.total_waiting(stop_id),
            "options": _real_etas(S.net.stop_options(stop_id))}


@app.get("/api/stops/{stop_id}/forecast")
def stop_forecast(stop_id: str, hours: int = Query(6, ge=1, le=24)):
    _stop(stop_id)
    return S.demand.forecast(stop_id, S.net.clock, hours)


@app.get("/api/shuttles/{shuttle_id}/track")
def track(shuttle_id: str, stop_id: str | None = None):
    _shuttle(shuttle_id)
    t = S.net.track(shuttle_id, stop_id)
    _real_etas(t["upcoming"])
    if t["target"]:
        t["target"]["eta_seconds"] = _real(t["target"].pop("eta_sim_seconds"))
    return t


class Checkin(BaseModel):
    student_id: str | None = None
    route_id: str | None = None


@app.post("/api/stops/{stop_id}/checkin")
def checkin(stop_id: str, body: Checkin = Checkin()):
    """Student taps 'I'm waiting here' - the driver sees the head-count."""
    _stop(stop_id)
    counted = S.pay.record_checkin(body.student_id, stop_id) if body.student_id else True
    if counted:
        S.net.add_waiting(stop_id, body.route_id)
    return {"counted": counted, "waiting": S.net.total_waiting(stop_id)}


# ------------------------------------------------------------------ student: boarding, payment, profile
class BoardBody(BaseModel):
    shuttle_id: str
    stop_id: str


@app.post("/api/students/{student_id}/board")
def board(student_id: str, body: BoardBody):
    """'I'm in the shuttle': creates today's trip (Pay Later by default). 3rd Pay Later of the day
    is refused until previous dues are cleared."""
    sim, _ = _shuttle(body.shuttle_id)
    _stop(body.stop_id)
    arrival = next((a for a in sim.arrivals(body.stop_id) if a["shuttle_id"] == body.shuttle_id), None)
    if arrival and arrival["is_full"]:          # same rule as the Available / Full badge: seats when it reaches your stop
        raise HTTPException(409, {"code": "SHUTTLE_FULL", "message": "This shuttle is full. Wait for the next one."})
    label = f"Route {sim.route_id} · {sim.stops[0].name} → {sim.stops[-1].name}"
    try:
        trip = S.pay.board(student_id, body.shuttle_id, sim.route_id, body.stop_id, label)
    except PaymentError as e:
        _err(e)
    if not trip["existing"]:
        sim.board_rider(body.shuttle_id, from_stop_id=body.stop_id)   # (adds one rider if there is room right now)
    return trip


@app.get("/api/students/{student_id}/state")
def student_state(student_id: str):
    return S.pay.state(student_id)


@app.get("/api/students/{student_id}/trips/{trip_id}")
def get_trip(student_id: str, trip_id: int):
    try:
        return S.pay.get_trip(student_id, trip_id)
    except PaymentError as e:
        _err(e)


class UpiBody(BaseModel):
    app: str


@app.post("/api/students/{student_id}/trips/{trip_id}/pay-upi")
def pay_upi(student_id: str, trip_id: int, body: UpiBody):
    try:
        return S.pay.pay_upi(student_id, trip_id, body.app)
    except PaymentError as e:
        _err(e)


@app.post("/api/students/{student_id}/trips/{trip_id}/pay-cash")
def pay_cash(student_id: str, trip_id: int):
    """Sends a cash confirmation request to the driver and starts the 10-minute timer."""
    try:
        return S.pay.request_cash(student_id, trip_id)
    except PaymentError as e:
        _err(e)


class PassPurchase(BaseModel):
    plan: str


@app.post("/api/students/{student_id}/pass")
def buy_pass(student_id: str, body: PassPurchase):
    try:
        return S.pay.buy_pass(student_id, body.plan)
    except PaymentError as e:
        _err(e)


# ------------------------------------------------------------------ driver
@app.get("/api/driver/shuttles")
def driver_shuttles():
    return S.net.all_shuttle_ids()


@app.get("/api/driver/{shuttle_id}/overview")
def driver_overview(shuttle_id: str):
    _shuttle(shuttle_id)
    o = S.net.driver_overview(shuttle_id)
    _real_etas(o["upcoming"])
    o["paylater_today"] = S.pay.paylater_today_for_shuttle(shuttle_id)
    o["queue"] = S.pay.driver_queue(shuttle_id)
    return o


class SkipBody(BaseModel):
    stop_id: str


@app.post("/api/driver/{shuttle_id}/skip")
def driver_skip(shuttle_id: str, body: SkipBody):
    sim, _ = _shuttle(shuttle_id)
    if not sim.request_skip(shuttle_id, body.stop_id):
        raise HTTPException(409, {"code": "CANNOT_SKIP", "message": "Students are waiting or getting off at that stop."})
    return {"ok": True}


@app.post("/api/driver/{shuttle_id}/trips/{trip_id}/confirm-cash")
def driver_confirm_cash(shuttle_id: str, trip_id: int):
    _shuttle(shuttle_id)
    try:
        return S.pay.confirm_cash(trip_id)
    except PaymentError as e:
        _err(e)


@app.post("/api/driver/{shuttle_id}/trips/{trip_id}/verify")
def driver_verify(shuttle_id: str, trip_id: int):
    _shuttle(shuttle_id)
    try:
        return S.pay.verify_boarding(trip_id)
    except PaymentError as e:
        _err(e)


# ------------------------------------------------------------------ admin
@app.get("/api/admin/insights")
def admin_insights():
    wd = S.net.clock.weekday()
    ops = S.net.summary()
    pay = S.pay.summary()
    return {"sim_time": S.net.clock.isoformat(timespec="minutes"),
            "kpis": {"avg_wait_minutes": round(ops["avg_wait_seconds"] / 60, 1),
                     "trips_today": ops["students_boarded"] + pay["trips_today"],
                     "fleet_utilization_pct": round(ops["avg_load_factor"] * 100),
                     "paylater_outstanding": pay["outstanding_dues"]},
            "heatmap": analytics.heatmap(S.net, wd),
            "reallocation": analytics.reallocation(S.net, wd),
            "efficiency": analytics.efficiency(S.net),
            "alerts": analytics.alerts(S.net),
            "demand_model": S.demand.metrics}


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Static UI last so /api/* wins.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
