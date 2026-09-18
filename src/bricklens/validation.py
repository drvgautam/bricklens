"""Validation against a labelled fault log.

Definitions (docs/validation.md):
- an alert is a TRUE POSITIVE if it intersects a labelled fault of the same type
- a fault is DETECTED if same-type alerts cover ≥ overlap_min of its window
- precision = TP alerts / all alerts (per type and overall); recall = detected faults / faults
- localisation accuracy = share of TP alerts whose top-ranked suspect equals the fault's target_uri
- time to detect = median minutes from fault start to the first overlapping alert
- false alerts per zone-week = FP alerts / (zones × weeks)
"""
from __future__ import annotations

import pandas as pd


def _overlap(a0, a1, b0, b1) -> pd.Timedelta:
    lo, hi = max(a0, b0), min(a1, b1)
    return max(hi - lo, pd.Timedelta(0))


def evaluate(alerts: list[dict], faults: pd.DataFrame, n_zones: int, weeks: float, overlap_min=0.5) -> dict:
    faults = faults.copy()
    faults["start"] = pd.to_datetime(faults["start"]); faults["end"] = pd.to_datetime(faults["end"])
    al = pd.DataFrame(alerts) if alerts else pd.DataFrame(columns=["detector", "start", "end", "suspects"])
    per_type, tp_flags, ttd = {}, [], []
    for i, a in al.iterrows():
        same = faults[faults.fault_type == a["detector"]]
        hits = same[[_overlap(a["start"], a["end"], f.start, f.end) > pd.Timedelta(0) for f in same.itertuples()]]
        tp = not hits.empty
        loc_ok = tp and a["suspects"] and a["suspects"][0]["uri"] in set(hits.target_uri)
        tp_flags.append((a["detector"], tp, bool(loc_ok)))
    detected = []
    for f in faults.itertuples():
        same = al[al.detector == f.fault_type]
        covered = sum((_overlap(a.start, a.end, f.start, f.end) for a in same.itertuples()), pd.Timedelta(0))
        frac = covered / (f.end - f.start) if f.end > f.start else 0
        first = min((a.start for a in same.itertuples() if _overlap(a.start, a.end, f.start, f.end) > pd.Timedelta(0)), default=None)
        detected.append((f.fault_type, frac >= overlap_min))
        if first is not None:
            ttd.append((f.fault_type, max((first - f.start).total_seconds() / 60, 0.0)))
    types = sorted(set(faults.fault_type) | set(al.detector))
    for t in types:
        n_al = sum(1 for d, _, _ in tp_flags if d == t)
        n_tp = sum(1 for d, tp, _ in tp_flags if d == t and tp)
        n_loc = sum(1 for d, tp, ok in tp_flags if d == t and tp and ok)
        n_f = sum(1 for d, _ in detected if d == t)
        n_det = sum(1 for d, ok in detected if d == t and ok)
        t_ttd = [m for d, m in ttd if d == t]
        per_type[t] = {
            "alerts": n_al, "true_positives": n_tp, "false_positives": n_al - n_tp,
            "faults": n_f, "detected": n_det,
            "precision": round(n_tp / n_al, 3) if n_al else None,
            "recall": round(n_det / n_f, 3) if n_f else None,
            "localisation_accuracy": round(n_loc / n_tp, 3) if n_tp else None,
            "median_time_to_detect_min": round(float(pd.Series(t_ttd).median()), 1) if t_ttd else None,
        }
    n_al, n_tp = len(tp_flags), sum(1 for _, tp, _ in tp_flags if tp)
    n_loc = sum(1 for _, tp, ok in tp_flags if tp and ok)
    n_det, n_f = sum(1 for _, ok in detected if ok), len(detected)
    overall = {
        "alerts": n_al, "true_positives": n_tp, "false_positives": n_al - n_tp, "faults": n_f, "detected": n_det,
        "precision": round(n_tp / n_al, 3) if n_al else None,
        "recall": round(n_det / n_f, 3) if n_f else None,
        "localisation_accuracy": round(n_loc / n_tp, 3) if n_tp else None,
        "median_time_to_detect_min": round(float(pd.Series([m for _, m in ttd]).median()), 1) if ttd else None,
        "false_alerts_per_zone_week": round((n_al - n_tp) / (n_zones * weeks), 3) if n_zones and weeks else None,
    }
    return {"overall": overall, "per_type": per_type}


def check_targets(result: dict, targets: dict) -> list[str]:
    """Return a list of failed target descriptions (empty = pass)."""
    o = result["overall"]
    fails = []
    for k in ("precision", "recall", "localisation_accuracy"):
        if k in targets and (o[k] is None or o[k] < targets[k]):
            fails.append(f"{k} {o[k]} < {targets[k]}")
    if "false_alerts_per_zone_week" in targets and o["false_alerts_per_zone_week"] is not None \
            and o["false_alerts_per_zone_week"] > targets["false_alerts_per_zone_week"]:
        fails.append(f"false_alerts_per_zone_week {o['false_alerts_per_zone_week']} > {targets['false_alerts_per_zone_week']}")
    return fails


def markdown_table(result: dict) -> str:
    rows = ["| Alert type | Alerts | TP | FP | Faults | Detected | Precision | Recall | Localisation | Median TTD (min) |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for t, r in result["per_type"].items():
        rows.append(f"| {t} | {r['alerts']} | {r['true_positives']} | {r['false_positives']} | {r['faults']} | {r['detected']} | "
                    f"{r['precision']} | {r['recall']} | {r['localisation_accuracy']} | {r['median_time_to_detect_min']} |")
    o = result["overall"]
    rows.append(f"| **overall** | {o['alerts']} | {o['true_positives']} | {o['false_positives']} | {o['faults']} | {o['detected']} | "
                f"**{o['precision']}** | **{o['recall']}** | **{o['localisation_accuracy']}** | {o['median_time_to_detect_min']} |")
    rows.append(f"\nFalse alerts per zone-week: **{o['false_alerts_per_zone_week']}**")
    return "\n".join(rows)
