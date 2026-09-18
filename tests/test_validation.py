import pandas as pd

from bricklens.engine import run_detection
from bricklens.validation import check_targets, evaluate
from tests.conftest import ROOT


def test_validation_meets_targets(cfg, graph, store):
    alerts = run_detection(cfg, graph, store, write=False)
    faults = pd.read_csv(ROOT / "data/faults.csv")
    res = evaluate(alerts, faults, n_zones=4, weeks=4, overlap_min=0.5)
    assert check_targets(res, dict(cfg.validation.targets)) == []
    assert res["overall"]["faults"] == 15


def test_false_positive_is_counted():
    alerts = [{"detector": "co2_high", "start": pd.Timestamp("2026-01-01 10:00"), "end": pd.Timestamp("2026-01-01 11:00"),
               "suspects": [{"uri": "z"}]}]
    faults = pd.DataFrame([{"fault_type": "co2_high", "target_uri": "z", "start": "2026-01-02 10:00", "end": "2026-01-02 11:00"}])
    res = evaluate(alerts, faults, n_zones=1, weeks=1)
    assert res["overall"]["precision"] == 0.0 and res["overall"]["recall"] == 0.0


def test_stable_across_noise_seeds(cfg, graph):
    """The synthetic score must not depend on the noise realisation (found the hard way: docs/decisions/0003)."""
    import copy

    from bricklens.engine import load_telemetry
    from bricklens.telemetry.store import TelemetryStore

    faults = pd.read_csv(ROOT / "data/faults.csv")
    for seed in (1, 13, 2026):
        c = copy.deepcopy(cfg)
        c["telemetry"]["source"]["seed"] = seed
        c["telemetry"]["source"]["faults"] = None
        st, _ = load_telemetry(c, TelemetryStore(":memory:"))
        res = evaluate(run_detection(c, graph, st, write=False), faults, n_zones=4, weeks=4)
        assert check_targets(res, dict(cfg.validation.targets)) == [], (seed, res["overall"])
