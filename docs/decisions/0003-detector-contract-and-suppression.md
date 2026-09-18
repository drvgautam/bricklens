# 0003 — Detectors declare required point classes; statistical alerts are suppressed by rule alerts

**Status:** accepted · **Sprint:** 2–3

## Decision
- A detector is a registered function with `requires = [Brick point classes]`. It runs on any building whose graph
  has them and is skipped (not failed) otherwise. This is what lets the same catalogue run on the demo building
  and on the CSIRO AHUs, which have no zone CO2.
- `pattern_deviation` is suppressed wherever a rule-based alert already explains the same zone/equipment in an
  overlapping window. It exists to catch what the rules do not (sensor drift, flatlines), not to double-count
  what they do.
- Its default method is a **weekly-profile residual** (median per 15-min slot × weekday/weekend over the first
  7 days, MAD-scaled with a floor at 5 % of the profile range, |z| > 4 for 60 min). Isolation Forest is kept as
  `method: iforest`.

## Why the residual method replaced Isolation Forest as the default
The first version used Isolation Forest (contamination 0.02) and scored perfectly on the synthetic data. Removing
an unused line in the generator changed the random-number sequence — same faults, different noise — and the
Isolation Forest run then flagged two spurious humidity hours and covered only one hour of a ten-hour sensor
drift. A detector whose result depends on the noise realisation is not one to gate a build on. The residual
method is deterministic, explainable ("4.3σ from the learned Tuesday-morning profile"), and scored 15/15 with 0
false alerts across seeds 1, 7, 13, 42, 99 and 2026; `tests/test_validation.py::test_stable_across_noise_seeds`
now guards this.

## Tuning record
| Parameter | From → to | Why |
| --- | --- | --- |
| `pattern_deviation.contamination` (iforest) | 0.01 → 0.02 | 0.01 missed the mid-day part of a CO2 flatline; 0.03 flagged normal evenings |
| `pattern_deviation` merge gap | 40 → 20 min | 40 min stitched scattered flags into false 60-min runs |
| `pattern_deviation.method` | iforest → residual | result depended on the noise seed (see above) |
| `pattern_deviation.zscore` (residual) | 4.0 | 3.0 flags an evening in Z4 and the AHU restart on the meter; 5.0 loses the tail of a damper-fault CO2 rise |
| `temp_band` merge gap | 15 → 30 min | a 20-min dip inside a four-hour fault is the same fault |
| `peak_volatility` sigma floor | 3 → 4 kW | an 8 kW AHU restart at night is not a demand spike; spikes of interest are ≥ 12 kW |
