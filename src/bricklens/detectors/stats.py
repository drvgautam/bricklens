"""Statistical detector: pattern deviation on any numeric sensor point.

Default method `residual`: a per-point weekly profile (median per 15-min slot × weekday/weekend)
is learned from the first `baseline_days`; the residual against that profile is scaled by a
robust (MAD) sigma with a floor, and runs of |z| > `zscore` lasting `min_run_min` are alerts.
Deterministic, explainable, and stable under re-seeded noise.

Alternative `iforest`: Isolation Forest on [value, sin(hour), cos(hour), occupied]. Kept because it
generalises to points without a clean weekly profile, but it proved sensitive to the noise
realisation on the synthetic data (docs/decisions/0003).

The engine suppresses statistical alerts where a rule-based alert already explains the same
zone/equipment and window.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Anomaly, DetectorContext, register, runs

SKIP = ("Setpoint", "Status", "Command")


def _profile_z(s: pd.Series, baseline_days: int, sigma_floor_frac: float) -> pd.Series:
    df = pd.DataFrame({"v": s})
    df["slot"] = df.index.hour * 4 + df.index.minute // 15
    df["wk"] = (df.index.weekday < 5).astype(int)
    cutoff = s.index[0] + pd.Timedelta(days=baseline_days)
    base = df[df.index < cutoff].groupby(["slot", "wk"])["v"]
    med, mad = base.median(), base.apply(lambda x: (x - x.median()).abs().median())
    prof_range = float(med.max() - med.min()) if len(med) else 0.0
    key = pd.MultiIndex.from_arrays([df["slot"], df["wk"]])
    m = med.reindex(key).to_numpy()
    sd = 1.4826 * mad.reindex(key).to_numpy()
    floor = max(sigma_floor_frac * prof_range, 1e-6)
    sd = np.maximum(np.nan_to_num(sd, nan=floor), floor)
    z = pd.Series((df["v"].to_numpy() - m) / sd, index=s.index)
    z[s.index < cutoff] = 0.0          # never score the baseline against itself
    return z


def _iforest_flags(s: pd.Series, occ: pd.Series, baseline_days: int, contamination: float) -> pd.Series:
    from sklearn.ensemble import IsolationForest

    h = (s.index.hour + s.index.minute / 60) / 24 * 2 * np.pi
    X = np.column_stack([s.values, np.sin(h), np.cos(h), occ.values.astype(float)])
    cutoff = s.index[0] + pd.Timedelta(days=baseline_days)
    train = X[s.index < cutoff]
    if len(train) < 100:
        return pd.Series(False, index=s.index)
    mu, sd = train.mean(0), train.std(0) + 1e-9
    model = IsolationForest(n_estimators=100, contamination=contamination, random_state=0).fit((train - mu) / sd)
    flags = pd.Series(model.predict((X - mu) / sd) == -1, index=s.index)
    flags[s.index < cutoff] = False
    return flags


@register("pattern_deviation", "statistical", ["Point"],
          "Residual against the point's own learned weekly profile (or Isolation Forest)")
def pattern_deviation(ctx: DetectorContext, cfg: dict) -> list[Anomaly]:
    method = cfg.get("method", "residual")
    out = []
    for p in ctx.points_of_class("Point"):
        if any(k in p.label for k in SKIP):
            continue
        s = ctx.series(p.uri).dropna()
        if len(s) < 200:
            continue
        if method == "iforest":
            flags = _iforest_flags(s, ctx.schedule.occupied(s.index), cfg["baseline_days"], cfg.get("contamination", 0.02))
            z = None
        else:
            z = _profile_z(s, cfg["baseline_days"], cfg.get("sigma_floor_frac", 0.05))
            flags = z.abs() > cfg.get("zscore", 4.0)
        for a, b in runs(flags, cfg["min_run_min"], max_gap_minutes=20):
            seg = s[a:b]
            zmax = float(z[a:b].abs().max()) if z is not None else None
            how = f"{zmax:.1f}σ from" if zmax is not None else "isolated from"
            out.append(Anomaly("pattern_deviation", "statistical", p.uri, a, b, "info",
                               f"{p.name}: values {seg.min():.1f}–{seg.max():.1f} are {how} the learned weekly profile "
                               f"for {int((b - a).total_seconds() / 60)} min",
                               [p.uri], {"mean_value": round(float(seg.mean()), 2), "zmax": zmax}))
    return out
