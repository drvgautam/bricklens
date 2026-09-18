# Validation protocol

Detection quality is measured against a labelled fault log and gated in CI, so the project makes a checkable
claim rather than a demo.

## Definitions

| Metric | Definition |
| --- | --- |
| True positive | an alert that intersects a labelled fault of the same type |
| Detected fault | same-type alerts cover ≥ 50 % of the fault window (`validation.overlap_min`) |
| Precision / recall | TP alerts ÷ alerts; detected faults ÷ faults — per type and overall |
| Localisation accuracy | TP alerts whose rank-1 suspect equals the fault's `target_uri` |
| Median time to detect | minutes from fault start to the start of the first overlapping alert window (alert windows start at the first exceedance, so dwell-time latency is not included — the `dwell_min` in config is the operational latency) |
| False alerts per zone-week | FP alerts ÷ (zones × weeks) |

Targets (config/bricklens.yaml): precision ≥ 0.80, recall ≥ 0.80, localisation ≥ 0.85, ≤ 2 false alerts per
zone-week. `bricklens validate` exits non-zero when any is missed; CI runs it on every push.

## Run 1 — synthetic (primary)

`telemetry/synthetic.py` generates four weeks at 5-minute resolution for the demo building with 15 scripted
faults covering all eight alert types, and writes `data/faults.csv` (`fault_type, target_uri, start, end`) as
ground truth. Results: `docs/validation_synthetic.md`. All metrics are 1.0 and the false-alert rate is 0.

Read that honestly: the faults are scripted to the signatures the detectors look for, so a perfect score is the
expected baseline, not evidence of generalisation. What the synthetic run *does* establish:

- every detector fires on its intended signature and on nothing else in four weeks of nominal operation;
- the localiser ranks the intended zone/equipment first for every alert type;
- the suppression rule removes statistical alerts that a rule already explains (11 → 2), and the two it keeps —
  supply-air-temperature drift and a CO2 sensor flatline — are the two faults no rule covers;
- the result is one alert per injected fault (15 for 15) and is stable across six noise seeds
  (`test_stable_across_noise_seeds`) — the Isolation Forest variant was not, which is why it is no longer the
  default (docs/decisions/0003);
- a threshold change that breaks any of this fails CI.

Tuning history (each also in `docs/decisions/0003`): `pattern_deviation` switched from Isolation Forest to a
weekly-profile residual at |z| > 4; `temp_band` merge gap 15 → 30 min because a 20-minute dip inside a four-hour
fault is the same fault; `peak_volatility` sigma floor 3 → 4 kW because an 8 kW AHU restart at night is not a
demand spike.

## Run 2 — CSIRO Newcastle AHU dataset (secondary)

Source: https://github.com/csiro-energy-systems/ahu-fault-detection-dataset (CC BY-SA 4.0). Two AHUs of a
four-storey office in Newcastle, Australia, April–November 2013; faults inserted through the BMS; ground truth in
`data/fault-experiments.parquet`. The data files are Git LFS objects and could not be fetched from the build
sandbox used to develop BrickLens, so this run is set up but not yet executed.

Recipe:

```bash
git clone https://github.com/csiro-energy-systems/ahu-fault-detection-dataset ../ahu-fault-detection-dataset
cd ../ahu-fault-detection-dataset && git lfs install && git lfs pull && cd -
python -c "import pandas as pd; print(list(pd.read_parquet('../ahu-fault-detection-dataset/data/AHU9.parquet').columns))"
# fill config/mapping.example.yaml with the real tag names, merge it into a config, then:
bricklens load --config config/csiro.yaml
python scripts/csiro_labels.py            # converts fault-experiments.parquet to the faults.csv schema
bricklens validate --config config/csiro.yaml --labels data/csiro_faults.csv --strict false
```

What to expect and why it differs from run 1: the CSIRO AHUs have no per-zone CO2 or humidity, so `co2_high`,
`humidity_band` and `damper_fault` will be skipped (their required point classes are absent) and the run scores
`temp_band`, `off_hours`, `coil_fighting`, `peak_volatility` and `pattern_deviation`. Fault labels are coarser
(a day-long "chilled water valve stuck 30 %") than the alerts, so overlap-based recall is the meaningful number
and time-to-detect is not. Report the numbers separately from run 1 with a short note on each gap.
