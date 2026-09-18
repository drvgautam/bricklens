import pandas as pd

from bricklens.detectors import REGISTRY, DetectorContext
from bricklens.detectors.base import Schedule, runs
from bricklens.engine import run_detection

NS = "urn:bricklens:demo#"


def test_runs_merges_small_gaps_and_respects_min_length():
    idx = pd.date_range("2026-01-01", periods=20, freq="5min")
    m = pd.Series([False] * 20, index=idx)
    m.iloc[2:8] = True          # 30 min
    m.iloc[9:12] = True         # 15 min, 5-min gap before it
    r = runs(m, 30, max_gap_minutes=10)
    assert r == [(idx[2], idx[11] + pd.Timedelta("5min"))]
    assert runs(m, 60) == []


def test_each_rule_detector_hits_its_fault(cfg, graph, store):
    ctx = DetectorContext(graph, store, Schedule.from_cfg(cfg))
    expect = {"co2_high": ("Z3.co2", "2026-08-04 13:00"), "temp_band": ("Z1.temp", "2026-08-12 10:00"),
              "humidity_band": ("Z2.rh", "2026-08-06 22:00"), "damper_fault": ("VAV2.dmp_pos", "2026-08-10 09:00"),
              "off_hours": ("AHU1.power", "2026-08-08 08:00"), "coil_fighting": ("AHU1.htg_cmd", "2026-08-13 10:00"),
              "peak_volatility": ("B1.power", "2026-08-17 11:00")}
    for name, (point, start) in expect.items():
        an = REGISTRY[name].run(ctx, cfg["detectors"][name])
        assert any(a.point_uri == NS + point and a.start == pd.Timestamp(start) for a in an), name


def test_detector_skipped_when_graph_lacks_points(cfg, store):
    from bricklens.graph.memory import MemoryGraph
    ctx = DetectorContext(MemoryGraph(), store, Schedule.from_cfg(cfg))
    assert REGISTRY["co2_high"].run(ctx, cfg["detectors"]["co2_high"]) == []


def test_engine_localises_and_suppresses(cfg, graph, store):
    alerts = run_detection(cfg, graph, store, write=True)
    by = {a["detector"]: a for a in sorted(alerts, key=lambda x: x["start"], reverse=True)}   # first occurrence of each detector
    assert by["damper_fault"]["suspects"][0]["name"] == "VAV-2 damper"
    assert by["co2_high"]["suspects"][0]["label"] == "HVAC_Zone"
    assert by["peak_volatility"]["suspects"][0]["label"] == "Building"
    stat = [a for a in alerts if a["family"] == "statistical"]
    # statistical alerts survive only where no rule explains them: SAT drift and CO2 flatline
    assert {a["point_uri"].split("#")[1] for a in stat} == {"AHU1.sat", "Z1.co2"}
    assert graph.alert(alerts[0]["id"]) is not None
    assert graph.equipment_history(NS + "AHU1")
