"""AI demand forecasting: how many students will need a shuttle at each stop, each hour.

Trains a gradient-boosted regressor on historical boarding counts. With no real logs
available, `generate_history` produces realistic synthetic data (class-change peaks,
meal-time peaks, weekend dips) so the pipeline can be demonstrated end to end.
Swap in real logs via `load_csv` -- same columns.
"""
from __future__ import annotations

import csv
import math
from datetime import date, datetime, timedelta

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

from .config import STOPS, Stop

# (amplitude, peak hour, spread) per stop kind
PROFILES = {
    "academic": [(1.0, 8.5, 0.9), (0.7, 13.0, 0.8), (0.9, 17.0, 1.0)],
    "hostel": [(0.9, 7.8, 0.8), (0.6, 13.5, 0.7), (1.0, 18.0, 1.3), (0.5, 22.0, 1.0)],
    "gate": [(0.5, 8.0, 1.0), (0.6, 17.5, 1.2), (0.8, 20.0, 1.5)],
    "food": [(0.5, 8.0, 0.6), (1.0, 13.0, 0.8), (0.6, 17.0, 0.8), (1.0, 20.0, 1.0)],
}
PEAK_SCALE = {"academic": 140, "hostel": 120, "gate": 90, "food": 120}
WEEKDAY_FACTOR = [1.0, 1.0, 1.0, 1.0, 0.95, 0.55, 0.30]  # Mon..Sun


def _gauss(x: float, mu: float, sigma: float) -> float:
    return math.exp(-((x - mu) ** 2) / (2 * sigma ** 2))


def true_rate(kind: str, hour: int, weekday: int) -> float:
    """Ground-truth students/hour used only to synthesize training data."""
    h = hour + 0.5
    shape = sum(a * _gauss(h, mu, s) for a, mu, s in PROFILES[kind])
    rate = 8 + PEAK_SCALE[kind] * shape
    if hour < 6:
        rate *= 0.15
    return rate * WEEKDAY_FACTOR[weekday]


def generate_history(stops: list[Stop] = STOPS, days: int = 60, seed: int = 7,
                     start: date = date(2026, 1, 5)) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(days):
        day = start + timedelta(days=d)
        wd = day.weekday()
        day_noise = rng.normal(1.0, 0.07)  # exams, rain, events...
        for hour in range(24):
            for s in stops:
                lam = max(0.1, true_rate(s.kind, hour, wd) * day_noise)
                rows.append({"date": day.isoformat(), "hour": hour, "weekday": wd,
                             "stop_id": s.id, "students": int(rng.poisson(lam))})
    return rows


def save_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "hour", "weekday", "stop_id", "students"])
        w.writeheader()
        w.writerows(rows)


def load_csv(path: str) -> list[dict]:
    with open(path, newline="") as f:
        return [{"date": r["date"], "hour": int(r["hour"]), "weekday": int(r["weekday"]),
                 "stop_id": r["stop_id"], "students": int(r["students"])} for r in csv.DictReader(f)]


class DemandModel:
    def __init__(self, stops: list[Stop] = STOPS):
        self.stops = stops
        self.index = {s.id: i for i, s in enumerate(stops)}
        self.model = GradientBoostingRegressor(n_estimators=200, max_depth=4,
                                               learning_rate=0.1, random_state=0)
        self.table: dict[str, list[list[float]]] = {}
        self.metrics: dict = {}

    def _x(self, stop_id: str, hour: int, weekday: int) -> list[float]:
        oh = [0.0] * len(self.stops)
        oh[self.index[stop_id]] = 1.0
        return oh + [hour, weekday, math.sin(2 * math.pi * hour / 24),
                     math.cos(2 * math.pi * hour / 24), 1.0 if weekday >= 5 else 0.0]

    def fit(self, rows: list[dict]) -> dict:
        split = int(len(rows) * 0.8)  # chronological hold-out
        train, test = rows[:split], rows[split:]
        X = np.array([self._x(r["stop_id"], r["hour"], r["weekday"]) for r in train])
        y = np.array([r["students"] for r in train], dtype=float)
        self.model.fit(X, y)
        Xt = np.array([self._x(r["stop_id"], r["hour"], r["weekday"]) for r in test])
        yt = np.array([r["students"] for r in test], dtype=float)
        pred = np.clip(self.model.predict(Xt), 0, None)
        base = {}
        for r in train:
            base.setdefault(r["stop_id"], []).append(r["students"])
        base_pred = np.array([np.mean(base[r["stop_id"]]) for r in test])
        self.metrics = {"mae_model": float(np.mean(np.abs(pred - yt))),
                        "mae_baseline_stop_mean": float(np.mean(np.abs(base_pred - yt))),
                        "train_rows": len(train), "test_rows": len(test)}
        self._build_table()
        return self.metrics

    def _build_table(self) -> None:
        self.table = {}
        for s in self.stops:
            X = np.array([self._x(s.id, h, wd) for wd in range(7) for h in range(24)])
            p = np.clip(self.model.predict(X), 0, None).reshape(7, 24)
            self.table[s.id] = [[float(v) for v in row] for row in p]

    def rate(self, stop_id: str, hour: int, weekday: int) -> float:
        """Expected students/hour."""
        return self.table[stop_id][weekday][hour]

    def forecast(self, stop_id: str, start: datetime, hours: int = 6) -> list[dict]:
        out = []
        for i in range(hours):
            t = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=i)
            out.append({"time": t.isoformat(timespec="minutes"), "hour": t.hour,
                        "expected_students": round(self.rate(stop_id, t.hour, t.weekday()), 1)})
        return out

    def peak_hours(self, weekday: int, top: int = 3) -> list[int]:
        tot = [sum(self.table[s.id][weekday][h] for s in self.stops) for h in range(24)]
        return sorted(range(24), key=lambda h: -tot[h])[:top]


def build_default_model(days: int = 60) -> DemandModel:
    m = DemandModel()
    m.fit(generate_history(days=days))
    return m
