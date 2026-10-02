"""Central configuration. Change values here (or via env vars) to tune the system."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Stop:
    id: str
    name: str
    lat: float
    lon: float
    kind: str  # academic | hostel | gate | food  (drives the demand profile)


# ---- Business rules ---------------------------------------------------------
FARE_INR = 20
PAYLATER_DAILY_LIMIT = 2          # Pay Later trips allowed per student per day
PASS_PLANS = {                    # digital mobility passes (backend only - no screen in the final design)
    "weekly": {"price": 100, "days": 7},
    "monthly": {"price": 350, "days": 30},
}
CASH_TIMEOUT_SECONDS = int(os.getenv("CASH_TIMEOUT_SECONDS", "600"))   # driver must confirm cash within 10 min
PAY_NOW_GRACE_SECONDS = int(os.getenv("PAY_NOW_GRACE_SECONDS", "120"))   # paying within this long of boarding = paid at boarding, not Pay Later
ONBOARD_WINDOW_SECONDS = 3600     # a boarding counts as "onboard" for cash payment for this long
UPI_APPS = ("Google Pay", "PhonePe", "Paytm")

# ---- Fleet / simulation -----------------------------------------------------
SHUTTLE_CAPACITY = 40             # total people (seated + standing)
SEATED_CAPACITY = 30              # above this the shuttle is 'Standing only'
FLEET_SIZE = 4
AVG_SPEED_MPS = 5.0               # ~18 km/h campus speed
DWELL_BASE_S = 8                  # seconds spent at a stop before people move
DWELL_PER_PERSON_S = 1.0          # extra seconds per person boarding/alighting
SIM_SPEEDUP = float(os.getenv("SIM_SPEEDUP", "4"))   # 1 real second = N simulated seconds
SMART_SKIP = os.getenv("SMART_SKIP", "0") == "1"     # auto-skip empty stops (default: AI suggests, driver taps Skip)
SKIP_SAVING_S = 60                # estimated time saved by skipping one empty stop (for driver hints)
DB_PATH = os.getenv("DB_PATH", "shuttlesync.db")
DEMAND_SCALE = float(os.getenv("DEMAND_SCALE", "1.5"))   # >1 = busier campus in the simulation


def _ring() -> list[Stop]:
    """Placeholder campus layout (ring around a centre).

    TODO: replace lat/lon with GPS-surveyed values, and check each stop's `kind`
    (kind drives the demand profile: academic | hostel | gate | food).
    """
    spec = [
        ("main_gate", "Main Gate", "gate"),
        ("prp", "PRP", "academic"),
        ("sjt", "SJT", "academic"),
        ("ladies_hostel", "Ladies Hostel", "hostel"),
        ("tt", "TT", "academic"),
        ("mens_hostel", "Men's Hostel", "hostel"),
    ]
    c_lat, c_lon = 12.9700, 79.1600
    stops = []
    for i, (sid, name, kind) in enumerate(spec):
        a = 2 * math.pi * i / len(spec)
        stops.append(Stop(sid, name, round(c_lat + 0.0045 * math.sin(a), 6),
                          round(c_lon + 0.0050 * math.cos(a), 6), kind))
    return stops


STOPS: list[Stop] = _ring()


@dataclass(frozen=True)
class Route:
    id: str                  # passenger-facing number ("1".."4")
    code: str                # operations letter used on the driver / admin screens ("A".."D")
    stops: tuple[str, ...]   # stop ids in loop order
    fleet: int


# Edit freely: which stops each route serves and how many shuttles run it.
ROUTES: list[Route] = [
    Route("1", "A", ("prp", "sjt", "ladies_hostel", "main_gate"), 2),
    Route("2", "B", ("main_gate", "tt", "sjt", "ladies_hostel", "prp"), 2),
    Route("3", "C", ("mens_hostel", "main_gate"), 1),
    Route("4", "D", ("main_gate", "mens_hostel"), 2),
]
