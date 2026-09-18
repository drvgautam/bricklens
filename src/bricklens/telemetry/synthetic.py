"""Synthetic telemetry for the demo building, with scripted faults and exact ground truth.

Why synthetic first: ground truth is known to the minute, so precision/recall/localisation
numbers are unambiguous. The public CSIRO dataset is the second, messier validation run.

The building: one AHU (AHU1) with a supply fan feeds four VAV terminals, one per zone.
Occupied 07:00–18:00 on weekdays. Baseline physics is deliberately simple (sinusoids,
first-order responses, Gaussian noise); what matters is that fault signatures match what
the detectors look for in a real BMS.

Fault targets follow the localiser's ranking convention:
- zone-level IEQ faults (CO2, temperature, humidity) target the HVAC_Zone
- damper faults target the Damper node
- off-hours and coil fighting target the AHU
- peak volatility targets the Building (main meter)
- sensor drift/flatline (pattern deviation) targets the zone or equipment that owns the point
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NS = "urn:bricklens:demo#"
ZONES = ["Z1", "Z2", "Z3", "Z4"]

OCC_START, OCC_END = 7, 18


def _occupied(idx: pd.DatetimeIndex) -> np.ndarray:
    return ((idx.weekday < 5) & (idx.hour >= OCC_START) & (idx.hour < OCC_END)).astype(float)


def _fault_windows(start: pd.Timestamp) -> list[dict]:
    """15 faults over four weeks, at least one per alert type. Times are local wall clock."""
    d = lambda week, weekday, hh, mm=0: start + pd.Timedelta(weeks=week, days=weekday, hours=hh, minutes=mm)
    F = []
    # CO2 high: overcrowded meeting rooms (Z3)
    F.append(dict(fault_type="co2_high", target_uri=NS + "Z3", start=d(0, 1, 13), end=d(0, 1, 15, 30), note="overcrowding"))
    F.append(dict(fault_type="co2_high", target_uri=NS + "Z3", start=d(2, 3, 9), end=d(2, 3, 11), note="overcrowding"))
    # Temperature band: reheat valve stuck open (Z1 hot), heating loss (Z4 cold)
    F.append(dict(fault_type="temp_band", target_uri=NS + "Z1", start=d(1, 2, 10), end=d(1, 2, 14), note="reheat stuck open +4C"))
    F.append(dict(fault_type="temp_band", target_uri=NS + "Z4", start=d(3, 0, 8), end=d(3, 0, 12), note="underheating -3C"))
    # Humidity: overnight humid air, Z2
    F.append(dict(fault_type="humidity_band", target_uri=NS + "Z2", start=d(0, 3, 22), end=d(0, 4, 6), note="RH 70%"))
    # Damper stuck: commanded open, position flat, CO2 creeps up (below the co2_high threshold)
    F.append(dict(fault_type="damper_fault", target_uri=NS + "VAV2.DMP", start=d(1, 0, 9), end=d(1, 0, 16), note="damper stuck at 15%"))
    F.append(dict(fault_type="damper_fault", target_uri=NS + "VAV4.DMP", start=d(3, 2, 10), end=d(3, 2, 15), note="damper stuck at 20%"))
    # Off-hours operation: AHU running on Saturday, and overnight
    F.append(dict(fault_type="off_hours", target_uri=NS + "AHU1", start=d(0, 5, 8), end=d(0, 5, 14), note="schedule override"))
    F.append(dict(fault_type="off_hours", target_uri=NS + "AHU1", start=d(2, 1, 20), end=d(2, 2, 2), note="schedule override"))
    # Coil fighting: heating and cooling valves open together
    F.append(dict(fault_type="coil_fighting", target_uri=NS + "AHU1", start=d(1, 3, 10), end=d(1, 3, 13), note="htg 40% while clg 50%"))
    F.append(dict(fault_type="coil_fighting", target_uri=NS + "AHU1", start=d(3, 4, 9), end=d(3, 4, 11), note="htg 35% while clg 45%"))
    # Peak load volatility: short demand spikes on the main meter
    F.append(dict(fault_type="peak_volatility", target_uri=NS + "B1", start=d(2, 0, 11), end=d(2, 0, 11, 45), note="+60 kW spike"))
    F.append(dict(fault_type="peak_volatility", target_uri=NS + "B1", start=d(3, 3, 14), end=d(3, 3, 14, 30), note="+70 kW spike"))
    # Pattern deviation: supply air temperature sensor drift; zone CO2 sensor flatline
    F.append(dict(fault_type="pattern_deviation", target_uri=NS + "AHU1", start=d(2, 4, 8), end=d(2, 4, 18), note="SAT sensor drift +6C"))
    F.append(dict(fault_type="pattern_deviation", target_uri=NS + "Z1", start=d(3, 1, 7), end=d(3, 1, 18), note="CO2 sensor flatline"))
    return F


def generate(seed=42, start="2026-08-03", weeks=4, resolution_min=5):
    rng = np.random.default_rng(seed)
    start = pd.Timestamp(start)
    idx = pd.date_range(start, start + pd.Timedelta(weeks=weeks) - pd.Timedelta(minutes=resolution_min),
                        freq=f"{resolution_min}min")
    n = len(idx)
    occ = _occupied(idx)
    hour = np.asarray(idx.hour + idx.minute / 60, dtype=float)
    day_cycle = np.sin((hour - 6) / 24 * 2 * np.pi)          # -1 at 00:00, +1 at 12:00-ish
    weekday = np.asarray(idx.weekday)
    faults = pd.DataFrame(_fault_windows(start))
    in_f = lambda ft, target: ((faults.fault_type == ft) & (faults.target_uri == target))

    def window_mask(ft, target):
        m = np.zeros(n, bool)
        for _, f in faults[in_f(ft, target)].iterrows():
            m |= (idx >= f.start) & (idx < f.end)
        return m

    series: dict[str, np.ndarray] = {}

    # --- AHU -------------------------------------------------------------------
    fan_on = np.maximum(occ, window_mask("off_hours", NS + "AHU1").astype(float))
    clg = np.where(fan_on > 0, np.clip(30 + 25 * day_cycle + rng.normal(0, 3, n), 0, 100), 0.0)
    htg = np.where((fan_on > 0) & (hour < 8.5) & (weekday < 5), np.clip(25 - 20 * (hour - 7), 0, 40), 0.0)
    htg = np.where(htg > 0, htg, 0.0)
    clg = np.where(htg > 0, 0.0, clg)                                # normal control: never both
    for f in faults[faults.fault_type == "coil_fighting"].itertuples():
        m = (idx >= f.start) & (idx < f.end)
        htg[m] = 40.0 if "40%" in f.note else 35.0
        clg[m] = 50.0 if "50%" in f.note else 45.0
    sat = np.where(fan_on > 0, 14 + 0.05 * (50 - clg) + rng.normal(0, 0.3, n), 22 + rng.normal(0, 0.3, n))
    drift = window_mask("pattern_deviation", NS + "AHU1")
    sat = sat + np.where(drift, 6.0, 0.0)
    ahu_power = 1.0 + np.where(fan_on > 0, 7.5 + 0.02 * clg + rng.normal(0, 0.4, n), rng.normal(0, 0.05, n))
    series[NS + "AHU1.SF.status"] = fan_on
    series[NS + "AHU1.sat"] = sat
    series[NS + "AHU1.clg_cmd"] = clg
    series[NS + "AHU1.htg_cmd"] = htg
    series[NS + "AHU1.power"] = ahu_power

    # --- Building meter --------------------------------------------------------
    b_power = 20 + 40 * occ + 5 * day_cycle * occ + ahu_power + rng.normal(0, 1.5, n)
    for f in faults[faults.fault_type == "peak_volatility"].itertuples():
        m = (idx >= f.start) & (idx < f.end)
        b_power[m] += 60.0 if "60" in f.note else 70.0
    series[NS + "B1.power"] = b_power

    # --- Zones -----------------------------------------------------------------
    for i, z in enumerate(ZONES):
        sp = np.full(n, 21.0)
        base_occ = 0.6 + 0.15 * i                                   # occupancy density differs per zone
        # CO2: outdoor 420 + first-order occupancy response
        load = base_occ * occ * (1 - np.exp(-np.clip(hour - OCC_START, 0, None) / 1.5)) * (hour < OCC_END)
        co2 = 420 + 450 * load + rng.normal(0, 15, n)
        temp = sp + 0.6 * day_cycle + 0.4 * occ + rng.normal(0, 0.15, n)
        rh = 42 + 5 * np.sin((hour - 3) / 24 * 2 * np.pi) + rng.normal(0, 1.0, n)
        dmp_cmd = np.where(occ > 0, np.clip(35 + 40 * load + 5 * day_cycle, 20, 95), 20.0)
        dmp_pos = dmp_cmd + rng.normal(0, 1.5, n)
        rht = np.where((occ > 0) & (hour < 8.5), np.clip(30 - 25 * (hour - 7), 0, 40), 0.0)
        rht = np.where(rht > 0, rht, 0.0)

        # scripted faults for this zone
        m = window_mask("co2_high", NS + z)
        co2 = np.where(m, 1250 + 100 * rng.random(n), co2)
        m = window_mask("temp_band", NS + z)
        for f in faults[in_f("temp_band", NS + z)].itertuples():
            mm = (idx >= f.start) & (idx < f.end)
            temp[mm] += 4.0 if "+4" in f.note else -3.0
            if "+4" in f.note:
                rht[mm] = 100.0
        m = window_mask("humidity_band", NS + z)
        rh = np.where(m, 70 + rng.normal(0, 1, n), rh)
        dmp_uri = NS + f"VAV{i + 1}.DMP"
        m = window_mask("damper_fault", dmp_uri)
        if m.any():
            stuck = 15.0 if i == 1 else 20.0
            dmp_cmd = np.where(m, 85.0 + rng.normal(0, 1, n), dmp_cmd)
            dmp_pos = np.where(m, stuck + rng.normal(0, 0.5, n), dmp_pos)
            co2 = np.where(m, 940 + 30 * rng.random(n), co2)     # elevated, below the co2_high threshold
        m = window_mask("pattern_deviation", NS + z)
        co2 = np.where(m, 420 + rng.normal(0, 0.5, n), co2)     # flatline at outdoor level during occupancy

        series[NS + f"{z}.temp"] = temp
        series[NS + f"{z}.temp_sp"] = sp
        series[NS + f"{z}.co2"] = co2
        series[NS + f"{z}.rh"] = rh
        series[NS + f"VAV{i + 1}.dmp_cmd"] = dmp_cmd
        series[NS + f"VAV{i + 1}.dmp_pos"] = dmp_pos
        series[NS + f"VAV{i + 1}.rht_cmd"] = rht

    units = {"temp": "DEG_C", "temp_sp": "DEG_C", "co2": "PPM", "rh": "PERCENT_RH", "sat": "DEG_C",
             "power": "KiloW", "status": None}
    frames = []
    for uri, vals in series.items():
        key = uri.rsplit(".", 1)[-1]
        frames.append(pd.DataFrame({"ts": idx, "point_uri": uri, "value": np.round(vals, 3),
                                    "unit": units.get(key, "PERCENT"), "quality": "good"}))
    df = pd.concat(frames, ignore_index=True)
    faults["start"] = faults["start"].astype(str)
    faults["end"] = faults["end"].astype(str)
    return df, faults
