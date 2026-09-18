"""Detection engine: run enabled detectors over a window, suppress redundant statistical
alerts, localise, and write alerts to the graph."""
from __future__ import annotations

import pandas as pd

from .config import Config
from .detectors import REGISTRY, DetectorContext
from .detectors.base import Anomaly, Schedule
from .graph.export import export, make_backend
from .localiser import Localiser
from .rdf.loader import infer, load_model, validate
from .telemetry.sources import make_source
from .telemetry.store import TelemetryStore


def build_graph(cfg: Config, do_validate: bool = True):
    model = load_model(cfg.resolve(cfg.building.model), cfg.resolve(cfg.building.brick_ontology))
    if do_validate:
        rep = validate(model)
        if not rep.conforms:
            raise ValueError(f"Brick model does not conform to Brick shapes:\n{rep.text}")
    infer(model)
    backend = make_backend(cfg)
    stats = export(model, backend, clear=True)
    return model, backend, stats


def load_telemetry(cfg: Config, store: TelemetryStore | None = None, start=None, end=None) -> tuple[TelemetryStore, int]:
    store = store or TelemetryStore(cfg.resolve(cfg.telemetry.store))
    src = make_source(cfg)
    n = 0
    store.clear()
    for frame in src.readings(start, end):
        n += store.append(frame)
    return store, n


def _suppress(anomalies: list[Anomaly], graph) -> list[Anomaly]:
    """Drop statistical anomalies already explained by a rule-based alert on the same
    zone/equipment in an overlapping window. Keeps alert volume honest."""
    rules = [a for a in anomalies if a.family != "statistical"]
    keep = list(rules)
    for a in anomalies:
        if a.family != "statistical":
            continue
        owners = {n.uri for n in graph.equipment_chain(a.point_uri, 2)}
        z = graph.zone_of(a.point_uri)
        if z:
            owners.add(z.uri)
        explained = False
        for r in rules:
            if not (a.start < r.end and r.start < a.end):
                continue
            r_owners = {n.uri for n in graph.equipment_chain(r.point_uri, 2)}
            rz = graph.zone_of(r.point_uri)
            if rz:
                r_owners.add(rz.uri)
            if owners & r_owners:
                explained = True
                break
        if not explained:
            keep.append(a)
    return keep


def run_detection(cfg: Config, graph, store: TelemetryStore, start=None, end=None, write: bool = True) -> list[dict]:
    ctx = DetectorContext(graph, store, Schedule.from_cfg(cfg), start, end)
    anomalies: list[Anomaly] = []
    for name, det in REGISTRY.items():
        dcfg = dict(cfg.detectors).get(name, {})
        if not dcfg.get("enabled", True):
            continue
        anomalies.extend(det.run(ctx, dcfg))
    anomalies = _suppress(anomalies, graph)
    loc = Localiser(graph, cfg.localiser.max_hops, cfg.localiser.shared_fault_min_siblings)
    alerts = []
    if write:
        graph.clear_alerts()
    for a in sorted(anomalies, key=lambda x: x.start):
        suspects, evidence = loc.localise(a, anomalies)
        z = graph.zone_of(a.point_uri)
        alert = {
            "id": a.id, "detector": a.detector, "family": a.family, "severity": a.severity,
            "start": a.start, "end": a.end, "minutes": round(a.minutes, 1),
            "point_uri": a.point_uri, "zone_uri": z.uri if z else None,
            "explanation": a.explanation, "metrics": a.metrics,
            "suspects": [s.to_dict() for s in suspects], "evidence_points": a.evidence_points, "evidence": evidence,
        }
        if write:
            graph.write_alert(alert)
        alerts.append(alert)
    return alerts


def alerts_frame(alerts: list[dict]) -> pd.DataFrame:
    rows = [{"id": a["id"], "detector": a["detector"], "family": a["family"], "severity": a["severity"],
             "start": a["start"], "end": a["end"], "minutes": a["minutes"],
             "top_suspect": a["suspects"][0]["name"] if a["suspects"] else None,
             "top_suspect_uri": a["suspects"][0]["uri"] if a["suspects"] else None,
             "explanation": a["explanation"]} for a in alerts]
    return pd.DataFrame(rows)
