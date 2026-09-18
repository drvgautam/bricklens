"""Energy-waste detectors modelled on the alert vocabulary of commercial building-intelligence
platforms: off-hours operation, simultaneous heating and cooling, peak-load volatility."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Anomaly, DetectorContext, register, runs, severity_from_ratio


def _equipment_points(ctx, equipment_cls: str, point_cls: str):
    for eq in ctx.graph.nodes_with_class(equipment_cls):
        for p in ctx.graph.points_of(eq.uri):
            if point_cls in p.classes:
                yield eq, p
        # also points on the equipment's parts (e.g. supply fan status)
        for part in ctx.graph.subgraph(eq.uri, depth=1, rels=["HAS_PART"]).nodes:
            if part.uri != eq.uri:
                for p in ctx.graph.points_of(part.uri):
                    if point_cls in p.classes:
                        yield eq, p


@register("off_hours", "energy", ["Electric_Power_Sensor"], "AHU running outside the occupancy schedule")
def off_hours(ctx: DetectorContext, cfg: dict) -> list[Anomaly]:
    out = []
    for eq, p in _equipment_points(ctx, "AHU", "Electric_Power_Sensor"):
        s = ctx.series(p.uri)
        occ = ctx.schedule.occupied(s.index)
        for a, b in runs((s > cfg["power_kw_min"]) & ~occ, cfg["dwell_min"], max_gap_minutes=15):
            kwh = float(s[a:b].mean() * (b - a).total_seconds() / 3600)
            out.append(Anomaly("off_hours", "energy", p.uri, a, b, "warning" if kwh < 50 else "critical",
                               f"{eq.name} drawing {s[a:b].mean():.1f} kW outside the schedule for "
                               f"{(b - a).total_seconds() / 3600:.1f} h (≈{kwh:.0f} kWh)",
                               [p.uri], {"kwh": round(kwh, 1), "mean_kw": round(float(s[a:b].mean()), 2)}))
    return out


@register("coil_fighting", "energy", ["Heating_Command", "Cooling_Command"],
          "Heating and cooling commands both open on the same unit")
def coil_fighting(ctx: DetectorContext, cfg: dict) -> list[Anomaly]:
    out = []
    for eq in ctx.graph.nodes_with_class("AHU") + ctx.graph.nodes_with_class("VAV"):
        pts = ctx.graph.points_of(eq.uri)
        htg = [p for p in pts if "Heating_Command" in p.classes]
        clg = [p for p in pts if "Cooling_Command" in p.classes]
        if not htg or not clg:
            continue
        h, c = ctx.series(htg[0].uri), ctx.series(clg[0].uri)
        df = pd.DataFrame({"h": h, "c": c}).dropna()
        cond = (df["h"] > cfg["valve_open_pct"]) & (df["c"] > cfg["valve_open_pct"])
        for a, b in runs(cond, cfg["dwell_min"], max_gap_minutes=10):
            out.append(Anomaly("coil_fighting", "energy", htg[0].uri, a, b, "warning",
                               f"{eq.name}: heating {df['h'][a:b].mean():.0f}% and cooling {df['c'][a:b].mean():.0f}% "
                               f"open simultaneously for {int((b - a).total_seconds() / 60)} min",
                               [htg[0].uri, clg[0].uri], {"heating_pct": round(float(df['h'][a:b].mean()), 1),
                                                          "cooling_pct": round(float(df['c'][a:b].mean()), 1)}))
    return out


@register("peak_volatility", "energy", ["Electric_Power_Sensor"],
          "Demand far above the same-time-of-day baseline on the main meter")
def peak_volatility(ctx: DetectorContext, cfg: dict) -> list[Anomaly]:
    out = []
    for eq, p in _equipment_points(ctx, "Building", "Electric_Power_Sensor"):
        s = ctx.series(p.uri)
        if s.empty:
            continue
        # baseline: median and MAD of the same 15-min slot on the same weekday-type over previous N days
        df = pd.DataFrame({"v": s})
        df["slot"] = df.index.hour * 4 + df.index.minute // 15
        df["wk"] = (df.index.weekday < 5).astype(int)
        base_days = cfg["baseline_days"]
        z = pd.Series(np.nan, index=s.index)
        for (slot, wk), g in df.groupby(["slot", "wk"]):
            v = g["v"]
            med = v.rolling(base_days, min_periods=3).median().shift(1)
            mad = (v - med).abs().rolling(base_days, min_periods=3).median().shift(1)
            sigma = np.maximum(1.4826 * mad, np.maximum(0.05 * med.abs(), 4.0))   # 4 kW floor: an 8 kW AHU restart is not a demand spike
            z[v.index] = (v - med) / sigma
        for a, b in runs(z > cfg["zscore"], cfg["dwell_min"], max_gap_minutes=10):
            zmax = float(z[a:b].max())
            out.append(Anomaly("peak_volatility", "energy", p.uri, a, b, severity_from_ratio(zmax / cfg["zscore"], 1.0, 2.0),
                               f"Demand {s[a:b].max():.0f} kW, {zmax:.1f}σ above the same-slot baseline for "
                               f"{int((b - a).total_seconds() / 60)} min",
                               [p.uri], {"zmax": round(zmax, 2), "peak_kw": round(float(s[a:b].max()), 1)}))
    return out
