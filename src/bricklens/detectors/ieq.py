"""IEQ detectors: the parameters the revised EPBD names (CO2, temperature, humidity) plus the
ventilation/damper fault that ties an IEQ symptom to an equipment cause."""
from __future__ import annotations

import pandas as pd

from .base import Anomaly, DetectorContext, register, runs, severity_from_ratio


@register("co2_high", "ieq", ["CO2_Sensor"], "Zone CO2 above threshold for longer than the dwell time")
def co2_high(ctx: DetectorContext, cfg: dict) -> list[Anomaly]:
    thr, dwell = cfg["threshold_ppm"], cfg["dwell_min"]
    out = []
    for p in ctx.points_of_class("CO2_Sensor"):
        s = ctx.series(p.uri)
        for a, b in runs(s > thr, dwell, max_gap_minutes=15):
            peak = float(s[a:b].max())
            out.append(Anomaly("co2_high", "ieq", p.uri, a, b, severity_from_ratio(peak / thr, 1.0, 1.3),
                               f"CO2 above {thr} ppm for {int((b - a).total_seconds() / 60)} min (peak {peak:.0f} ppm)",
                               [p.uri], {"peak_ppm": round(peak, 1), "threshold_ppm": thr}))
    return out


@register("temp_band", "ieq", ["Zone_Air_Temperature_Sensor", "Zone_Air_Temperature_Setpoint"],
          "Zone temperature outside setpoint ± tolerance during occupied hours")
def temp_band(ctx: DetectorContext, cfg: dict) -> list[Anomaly]:
    tol, dwell = cfg["tolerance_c"], cfg["dwell_min"]
    out = []
    for p in ctx.points_of_class("Zone_Air_Temperature_Sensor"):
        sp = ctx.sibling(p.uri, "Zone_Air_Temperature_Setpoint")
        if not sp:
            continue
        t, s = ctx.series(p.uri), ctx.series(sp.uri)
        df = pd.DataFrame({"t": t, "sp": s}).dropna()
        dev = (df["t"] - df["sp"]).abs()
        occ = ctx.schedule.occupied(df.index)
        for a, b in runs((dev > tol) & occ, dwell, max_gap_minutes=30):   # a 20-min dip mid-fault is the same fault
            worst = float(dev[a:b].max()); signed = float((df["t"] - df["sp"])[a:b].mean())
            out.append(Anomaly("temp_band", "ieq", p.uri, a, b, severity_from_ratio(worst / tol, 1.0, 2.0),
                               f"Zone temperature {'above' if signed > 0 else 'below'} setpoint by up to {worst:.1f} °C "
                               f"(tolerance ±{tol} °C) during occupied hours",
                               [p.uri, sp.uri], {"max_deviation_c": round(worst, 2), "mean_deviation_c": round(signed, 2)}))
    return out


@register("humidity_band", "ieq", ["Zone_Air_Humidity_Sensor"], "Relative humidity outside the comfort range")
def humidity_band(ctx: DetectorContext, cfg: dict) -> list[Anomaly]:
    lo, hi, dwell = cfg["low_pct"], cfg["high_pct"], cfg["dwell_min"]
    out = []
    for p in ctx.points_of_class("Zone_Air_Humidity_Sensor"):
        s = ctx.series(p.uri)
        for a, b in runs((s < lo) | (s > hi), dwell, max_gap_minutes=15):
            seg = s[a:b]; worst = float(seg.max() if seg.mean() > hi else seg.min())
            ratio = (worst - hi) / 10 + 1 if worst > hi else (lo - worst) / 10 + 1
            out.append(Anomaly("humidity_band", "ieq", p.uri, a, b, severity_from_ratio(ratio, 1.0, 1.5),
                               f"Relative humidity {worst:.0f}% outside {lo}–{hi}% for {int((b - a).total_seconds() / 60)} min",
                               [p.uri], {"worst_pct": round(worst, 1)}))
    return out


@register("damper_fault", "ieq", ["Damper_Position_Command", "Damper_Position_Sensor", "CO2_Sensor"],
          "Damper commanded open but position flat while zone CO2 is elevated → stuck damper")
def damper_fault(ctx: DetectorContext, cfg: dict) -> list[Anomaly]:
    out = []
    for cmd in ctx.points_of_class("Damper_Position_Command"):
        pos = ctx.sibling(cmd.uri, "Damper_Position_Sensor")
        if not pos:
            continue
        zone = ctx.graph.zone_of(cmd.uri)
        co2 = next((p for p in ctx.graph.points_of(zone.uri) if "CO2_Sensor" in p.classes), None) if zone else None
        if not co2:
            continue
        df = pd.DataFrame({"cmd": ctx.series(cmd.uri), "pos": ctx.series(pos.uri), "co2": ctx.series(co2.uri)}).dropna()
        cond = (df["cmd"] > cfg["cmd_open_pct"]) & ((df["cmd"] - df["pos"]) > cfg["position_delta_pct"]) & (df["co2"] > cfg["co2_ppm"])
        for a, b in runs(cond, cfg["dwell_min"], max_gap_minutes=15):
            gap = float((df["cmd"] - df["pos"])[a:b].mean())
            out.append(Anomaly("damper_fault", "ieq", pos.uri, a, b, "critical" if gap > 40 else "warning",
                               f"Damper commanded {df['cmd'][a:b].mean():.0f}% but position {df['pos'][a:b].mean():.0f}% "
                               f"while zone CO2 {df['co2'][a:b].mean():.0f} ppm — stuck damper",
                               [cmd.uri, pos.uri, co2.uri], {"cmd_pos_gap_pct": round(gap, 1)}))
    return out
