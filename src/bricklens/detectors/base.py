"""Detector contract. A detector is a stateless function over the graph + telemetry.

Each detector declares which Brick point classes it needs, so it runs automatically on
any building whose graph contains them and is skipped (not failed) on one that doesn't.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time

import pandas as pd


@dataclass
class Anomaly:
    detector: str
    family: str                       # ieq | energy | statistical
    point_uri: str                    # the point that triggered
    start: pd.Timestamp
    end: pd.Timestamp
    severity: str                     # info | warning | critical
    explanation: str
    evidence_points: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        h = hashlib.sha1(f"{self.detector}|{self.point_uri}|{self.start}".encode()).hexdigest()[:12]
        return f"{self.detector}-{h}"

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


@dataclass
class Schedule:
    occupied_start: time = time(7, 0)
    occupied_end: time = time(18, 0)
    weekdays_only: bool = True

    def occupied(self, idx: pd.DatetimeIndex) -> pd.Series:
        t = idx.time
        m = (t >= self.occupied_start) & (t < self.occupied_end)
        if self.weekdays_only:
            m &= idx.weekday < 5
        return pd.Series(m, index=idx)

    @classmethod
    def from_cfg(cls, cfg) -> Schedule:
        s = cfg.schedule
        h1, m1 = map(int, s["occupied_start"].split(":"))
        h2, m2 = map(int, s["occupied_end"].split(":"))
        return cls(time(h1, m1), time(h2, m2), bool(s.get("weekdays_only", True)))


@dataclass
class DetectorContext:
    graph: object                     # GraphBackend
    store: object                     # TelemetryStore
    schedule: Schedule
    start: datetime | None = None
    end: datetime | None = None

    def series(self, uri):
        return self.store.series(uri, self.start, self.end)

    def points_of_class(self, cls: str):
        return self.graph.nodes_with_class(cls)

    def sibling(self, uri: str, cls: str):
        """A point of class `cls` attached to the same zone or equipment as `uri`."""
        for owner in self.graph.equipment_chain(uri, max_hops=1):
            for p in self.graph.points_of(owner.uri):
                if cls in p.classes and p.uri != uri:
                    return p
        z = self.graph.zone_of(uri)
        if z:
            for p in self.graph.points_of(z.uri):
                if cls in p.classes and p.uri != uri:
                    return p
        return None


@dataclass
class Detector:
    name: str
    family: str
    requires: list[str]               # Brick point classes that must exist in the graph
    fn: Callable[[DetectorContext, dict], list[Anomaly]]
    description: str = ""

    def applicable(self, ctx: DetectorContext) -> bool:
        return all(ctx.points_of_class(c) for c in self.requires)

    def run(self, ctx: DetectorContext, cfg: dict) -> list[Anomaly]:
        return self.fn(ctx, cfg) if self.applicable(ctx) else []


REGISTRY: dict[str, Detector] = {}


def register(name: str, family: str, requires: list[str], description: str = ""):
    def deco(fn):
        REGISTRY[name] = Detector(name, family, requires, fn, description)
        return fn
    return deco


# --- shared helpers -----------------------------------------------------------

def runs(mask: pd.Series, min_minutes: float, max_gap_minutes: float | None = None) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Contiguous True runs of at least `min_minutes`. Gaps up to `max_gap_minutes` do not break a run."""
    mask = mask.astype(bool)
    if mask.empty or not mask.any():
        return []
    diffs = mask.index.to_series().diff().dropna()
    step = diffs.median() if not diffs.empty else pd.Timedelta(minutes=5)
    gap = pd.Timedelta(minutes=max_gap_minutes) if max_gap_minutes else step
    min_len = pd.Timedelta(minutes=min_minutes)
    out, start, last = [], None, None
    for ts in mask.index[mask.values]:
        if start is None:
            start = ts
        elif ts - last > gap:
            if (last + step - start) >= min_len:
                out.append((start, last + step))
            start = ts
        last = ts
    if start is not None and (last + step - start) >= min_len:
        out.append((start, last + step))
    return out


def severity_from_ratio(ratio: float, warn=1.0, crit=1.5) -> str:
    return "critical" if ratio >= crit else "warning" if ratio >= warn else "info"
