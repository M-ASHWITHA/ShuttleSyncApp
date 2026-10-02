"""Trips, UPI, cash verification and Pay Later (SQLite backed).

Implements the logic from the reference designs:

UPI     Student picks Pay via UPI -> chooses Google Pay / PhonePe / Paytm -> UPI app confirms ->
        trip is marked paid with the app name and timestamp.          (gateway is mocked)
Cash    Student picks Pay with Cash -> app checks the student is onboard (else "Board the shuttle to
        pay by cash") -> request goes to the driver and a 10-minute timer starts -> driver confirms in
        the Driver app => Paid; no confirmation in 10 min => Unpaid, the trip stays on the Pay Later page.
Pay Later  Boarding a shuttle without paying at boarding is Pay Later. Max 2 Pay Later trips per day, verified by the
        driver. Trying to board a 3rd time asks the student to clear previous dues first; after that the new
        trip has to be paid now.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta

from . import config as C

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE students (id TEXT PRIMARY KEY, created_at TEXT);
CREATE TABLE trips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id TEXT NOT NULL, shuttle_id TEXT, route_id TEXT, stop_id TEXT, label TEXT,
  fare INTEGER NOT NULL,
  status TEXT NOT NULL,             -- unpaid | waiting (cash awaiting driver) | paid
  method TEXT,                      -- upi | cash | pass
  upi_app TEXT,
  paylater INTEGER NOT NULL DEFAULT 1,      -- 1 = boarded on Pay Later (counts to the daily limit), 0 = must pay now
  pl_verified INTEGER NOT NULL DEFAULT 0,   -- driver verified the Pay Later boarding
  cash_requested_at TEXT, cash_expired INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, day TEXT NOT NULL, paid_at TEXT
);
CREATE INDEX idx_trips_student ON trips(student_id, day);
CREATE TABLE checkins (id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL, stop_id TEXT NOT NULL, ts TEXT NOT NULL);
CREATE TABLE passes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL, plan TEXT NOT NULL, price INTEGER NOT NULL,
  valid_from TEXT NOT NULL, valid_until TEXT NOT NULL
);
"""


class PaymentError(Exception):
    def __init__(self, code: str, message: str, http: int = 400, **extra):
        super().__init__(message)
        self.code, self.message, self.http, self.extra = code, message, http, extra

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, **self.extra}


class PaymentService:
    def __init__(self, db_path: str = ":memory:", now_fn=datetime.now, cash_timeout: int | None = None):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.now = now_fn
        self.cash_timeout = C.CASH_TIMEOUT_SECONDS if cash_timeout is None else cash_timeout
        if self.db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            for t in ("trips", "checkins", "passes", "students"):     # older prototype schema -> start fresh
                self.db.execute(f"DROP TABLE IF EXISTS {t}")
            self.db.executescript(SCHEMA)
            self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self.db.commit()

    # ------------------------------------------------------------ helpers
    def _ts(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def _today(self) -> str:
        return self.now().date().isoformat()

    def ensure_student(self, sid: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO students VALUES (?,?)", (sid, self._ts()))
        self.db.commit()

    def _trip(self, trip_id: int, sid: str | None = None):
        r = self.db.execute("SELECT * FROM trips WHERE id=?", (trip_id,)).fetchone()
        if not r or (sid is not None and r["student_id"] != sid):
            raise PaymentError("NOT_FOUND", "Trip not found.", 404)
        return r

    def _latest_id(self, sid: str):
        r = self.db.execute("SELECT MAX(id) m FROM trips WHERE student_id=?", (sid,)).fetchone()
        return r["m"]

    def _is_onboard(self, r) -> bool:
        age = (self.now() - datetime.fromisoformat(r["created_at"])).total_seconds()
        return r["id"] == self._latest_id(r["student_id"]) and age <= C.ONBOARD_WINDOW_SECONDS

    def view(self, r) -> dict:
        """Row -> dict for the apps (includes cash timer info)."""
        d = {k: r[k] for k in ("id", "student_id", "shuttle_id", "route_id", "stop_id", "label", "fare", "status",
                               "method", "upi_app", "created_at", "paid_at")}
        d.update({"paylater": bool(r["paylater"]), "pl_verified": bool(r["pl_verified"]),
                  "cash_expired": bool(r["cash_expired"]), "onboard": self._is_onboard(r)})
        if r["status"] == "waiting" and r["cash_requested_at"]:
            el = max(0, int((self.now() - datetime.fromisoformat(r["cash_requested_at"])).total_seconds()))
            d["cash_elapsed_seconds"] = el
            d["cash_elapsed_minutes"] = el // 60
            d["cash_remaining_seconds"] = max(0, self.cash_timeout - el)
        d["cash_timeout_seconds"] = self.cash_timeout
        return d

    def expire_cash(self) -> int:
        """Cash requests the driver did not confirm within the timeout become Unpaid (still due)."""
        cutoff = (self.now() - timedelta(seconds=self.cash_timeout)).isoformat(timespec="seconds")
        cur = self.db.execute("UPDATE trips SET status='unpaid', method=NULL, cash_expired=1 "
                              "WHERE status='waiting' AND cash_requested_at <= ?", (cutoff,))
        self.db.commit()
        return cur.rowcount

    # ------------------------------------------------------------ counts
    def paylater_used_today(self, sid: str) -> int:
        """Trips today that used Pay Later: still unpaid, verified by the driver as a Pay Later boarding,
        or paid later than PAY_NOW_GRACE_SECONDS after boarding (i.e. not paid at boarding)."""
        return self.db.execute(
            "SELECT COUNT(*) c FROM trips WHERE student_id=? AND day=? AND paylater=1 AND ("
            "status IN ('unpaid','waiting') OR pl_verified=1 OR "
            "(status='paid' AND (julianday(paid_at)-julianday(created_at))*86400 > ?))",
            (sid, self._today(), C.PAY_NOW_GRACE_SECONDS)).fetchone()["c"]

    def outstanding(self, sid: str) -> tuple[int, int]:
        r = self.db.execute("SELECT COUNT(*) c, COALESCE(SUM(fare),0) s FROM trips "
                            "WHERE student_id=? AND status IN ('unpaid','waiting')", (sid,)).fetchone()
        return r["c"], r["s"]

    def active_pass(self, sid: str):
        return self.db.execute("SELECT * FROM passes WHERE student_id=? AND valid_from<=? AND valid_until>=? "
                               "ORDER BY valid_until DESC LIMIT 1", (sid, self._today(), self._today())).fetchone()

    # ------------------------------------------------------------ boarding ("I'm in the shuttle")
    def board(self, sid: str, shuttle_id: str, route_id: str, stop_id: str, label: str) -> dict:
        self.expire_cash()
        self.ensure_student(sid)
        # same shuttle tapped again within 5 minutes -> same trip (no double charge / double count)
        last = self.db.execute("SELECT * FROM trips WHERE student_id=? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
        if last and last["shuttle_id"] == shuttle_id and \
                (self.now() - datetime.fromisoformat(last["created_at"])).total_seconds() < 300:
            return {**self.view(last), "existing": True}

        now, day = self._ts(), self._today()
        if self.active_pass(sid):
            cur = self.db.execute(
                "INSERT INTO trips (student_id,shuttle_id,route_id,stop_id,label,fare,status,method,paylater,created_at,day,paid_at) "
                "VALUES (?,?,?,?,?,0,'paid','pass',0,?,?,?)", (sid, shuttle_id, route_id, stop_id, label, now, day, now))
        else:
            paylater = 1
            if self.paylater_used_today(sid) >= C.PAYLATER_DAILY_LIMIT:
                n_due, amount = self.outstanding(sid)
                if n_due > 0:
                    raise PaymentError(
                        "CLEAR_DUES_FIRST",
                        f"You've used Pay Later for {C.PAYLATER_DAILY_LIMIT} trips today. "
                        f"Clear your previous dues (₹{amount}) first, then pay for this trip.",
                        402, dues_amount=amount, dues_trips=n_due)
                paylater = 0                                 # dues clear: allowed to ride, but this one is pay-now
            cur = self.db.execute(
                "INSERT INTO trips (student_id,shuttle_id,route_id,stop_id,label,fare,status,paylater,created_at,day) "
                "VALUES (?,?,?,?,?,?,'unpaid',?,?,?)",
                (sid, shuttle_id, route_id, stop_id, label, C.FARE_INR, paylater, now, day))
        self.db.commit()
        return {**self.view(self._trip(cur.lastrowid)), "existing": False}

    # ------------------------------------------------------------ paying
    def pay_upi(self, sid: str, trip_id: int, app: str) -> dict:
        self.expire_cash()
        if app not in C.UPI_APPS:
            raise PaymentError("BAD_APP", f"Choose one of: {', '.join(C.UPI_APPS)}.")
        t = self._trip(trip_id, sid)
        if t["status"] == "paid":
            raise PaymentError("ALREADY_PAID", "This trip is already paid.", 409)
        # mocked UPI gateway: the UPI app returns success instantly
        self.db.execute("UPDATE trips SET status='paid', method='upi', upi_app=?, paid_at=?, cash_expired=0 WHERE id=?",
                        (app, self._ts(), trip_id))
        self.db.commit()
        return self.view(self._trip(trip_id))

    def request_cash(self, sid: str, trip_id: int) -> dict:
        self.expire_cash()
        t = self._trip(trip_id, sid)
        if t["status"] == "paid":
            raise PaymentError("ALREADY_PAID", "This trip is already paid.", 409)
        if not self._is_onboard(t):
            raise PaymentError("NOT_ONBOARD", "Board the shuttle to pay by cash.", 409)
        if t["status"] != "waiting":
            self.db.execute("UPDATE trips SET status='waiting', method='cash', cash_requested_at=?, cash_expired=0 WHERE id=?",
                            (self._ts(), trip_id))
            self.db.commit()
        return self.view(self._trip(trip_id))

    def confirm_cash(self, trip_id: int) -> dict:
        """Driver confirms the student handed over the cash."""
        self.expire_cash()
        t = self._trip(trip_id)
        if t["status"] != "waiting":
            raise PaymentError("NOT_WAITING", "No cash request is waiting for this trip (it may have timed out).", 409)
        self.db.execute("UPDATE trips SET status='paid', method='cash', paid_at=? WHERE id=?", (self._ts(), trip_id))
        self.db.commit()
        return self.view(self._trip(trip_id))

    def verify_boarding(self, trip_id: int) -> dict:
        """Driver verifies a Pay Later boarding."""
        t = self._trip(trip_id)
        if t["paylater"] and t["status"] in ("unpaid", "waiting"):
            self.db.execute("UPDATE trips SET pl_verified=1 WHERE id=?", (trip_id,))
            self.db.commit()
        return self.view(self._trip(trip_id))

    # ------------------------------------------------------------ student views
    def state(self, sid: str) -> dict:
        self.expire_cash()
        self.ensure_student(sid)
        today = [self.view(r) for r in self.db.execute(
            "SELECT * FROM trips WHERE student_id=? AND day=? ORDER BY id DESC", (sid, self._today()))]
        dues = [self.view(r) for r in self.db.execute(
            "SELECT * FROM trips WHERE student_id=? AND status IN ('unpaid','waiting') ORDER BY id DESC", (sid,))]
        used = self.paylater_used_today(sid)
        return {"student_id": sid, "fare": C.FARE_INR, "today_trip": today[0] if today else None, "history": today,
                "dues": dues, "dues_amount": sum(d["fare"] for d in dues),
                "paylater_used_today": used, "paylater_left_today": max(0, C.PAYLATER_DAILY_LIMIT - used),
                "cash_timeout_seconds": self.cash_timeout}

    def get_trip(self, sid: str, trip_id: int) -> dict:
        self.expire_cash()
        return self.view(self._trip(trip_id, sid))

    def record_checkin(self, sid: str, stop_id: str) -> bool:
        """'I'm waiting here' alert. Repeats for the same stop within 60 s are ignored."""
        self.ensure_student(sid)
        last = self.db.execute("SELECT ts FROM checkins WHERE student_id=? AND stop_id=? ORDER BY id DESC LIMIT 1",
                               (sid, stop_id)).fetchone()
        if last and (self.now() - datetime.fromisoformat(last["ts"])).total_seconds() < 60:
            return False
        self.db.execute("INSERT INTO checkins (student_id, stop_id, ts) VALUES (?,?,?)", (sid, stop_id, self._ts()))
        self.db.commit()
        return True

    # ------------------------------------------------------------ driver views
    def driver_queue(self, shuttle_id: str) -> list[dict]:
        """Things the driver has to act on: cash to confirm, Pay Later boardings to verify."""
        self.expire_cash()
        rows = self.db.execute(
            "SELECT * FROM trips WHERE shuttle_id=? AND day=? AND (status='waiting' OR "
            "(status='unpaid' AND paylater=1 AND pl_verified=0)) ORDER BY id", (shuttle_id, self._today())).fetchall()
        out = []
        for r in rows:
            v = self.view(r)
            v["kind"] = "cash" if r["status"] == "waiting" else "boarding"
            out.append(v)
        return out

    def paylater_today_for_shuttle(self, shuttle_id: str) -> dict:
        q = "SELECT COUNT(*) c FROM trips WHERE shuttle_id=? AND day=? AND paylater=1 AND {}"
        verified = self.db.execute(q.format("pl_verified=1"), (shuttle_id, self._today())).fetchone()["c"]
        pending = self.db.execute(q.format("pl_verified=0 AND status IN ('unpaid','waiting')"),
                                  (shuttle_id, self._today())).fetchone()["c"]
        return {"verified": verified, "pending": pending, "total": verified + pending}

    # ------------------------------------------------------------ passes (backend only)
    def buy_pass(self, sid: str, plan: str) -> dict:
        if plan not in C.PASS_PLANS:
            raise PaymentError("BAD_PLAN", f"plan must be one of {list(C.PASS_PLANS)}")
        self.ensure_student(sid)
        p = C.PASS_PLANS[plan]
        start = self.now().date()
        end = start + timedelta(days=p["days"] - 1)
        self.db.execute("INSERT INTO passes (student_id,plan,price,valid_from,valid_until) VALUES (?,?,?,?,?)",
                        (sid, plan, p["price"], start.isoformat(), end.isoformat()))
        self.db.commit()
        return {"plan": plan, "price": p["price"], "valid_from": start.isoformat(), "valid_until": end.isoformat(),
                "txn_ref": f"MOCK-{uuid.uuid4().hex[:10]}"}

    # ------------------------------------------------------------ analytics
    def summary(self) -> dict:
        self.expire_cash()
        dues = self.db.execute("SELECT COALESCE(SUM(fare),0) s, COUNT(*) c FROM trips WHERE status IN ('unpaid','waiting')").fetchone()
        today = self.db.execute("SELECT COUNT(*) c FROM trips WHERE day=?", (self._today(),)).fetchone()["c"]
        paid = self.db.execute("SELECT COALESCE(SUM(fare),0) s FROM trips WHERE status='paid'").fetchone()["s"]
        return {"outstanding_dues": dues["s"], "outstanding_trips": dues["c"], "trips_today": today, "collected": paid}
