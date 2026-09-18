"""Localiser: turn an anomaly on one point into a ranked list of suspect equipment/zones,
with the evidence subgraph that justifies it.

Three steps, each a graph query:
1. chain    — the equipment/location chain that serves the point (nearest first)
2. siblings — other points on the same equipment that are also anomalous in the window
             (shared fault ⇒ equipment-level; isolated ⇒ sensor/zone-level)
3. scoring  — nearest owner wins by default; the upstream unit wins when several zones
             alert together; siblings raise their owner's score

Ranking convention (mirrors how a facilities engineer would read it):
- zone-level IEQ symptoms (CO2, temperature, humidity) implicate the zone first, its terminal unit second
- damper faults implicate the damper, then its VAV, then the AHU
- energy faults on AHU points implicate the AHU; main-meter faults implicate the building
"""
from __future__ import annotations

from dataclasses import dataclass

from .detectors.base import Anomaly

ZONE_FIRST = {"co2_high", "temp_band", "humidity_band"}
ZONE_POINT_CLASSES = {"CO2_Sensor", "Zone_Air_Temperature_Sensor", "Zone_Air_Humidity_Sensor", "Zone_Air_Temperature_Setpoint"}


@dataclass
class Suspect:
    uri: str
    label: str
    name: str
    rank: int
    score: float
    reason: str

    def to_dict(self):
        return self.__dict__.copy()


def _overlaps(a: Anomaly, b: Anomaly) -> bool:
    return a.start < b.end and b.start < a.end


class Localiser:
    def __init__(self, graph, max_hops=4, shared_min=2):
        self.graph, self.max_hops, self.shared_min = graph, max_hops, shared_min

    def localise(self, anomaly: Anomaly, all_anomalies: list[Anomaly]) -> tuple[list[Suspect], dict]:
        g = self.graph
        point = g.node(anomaly.point_uri)
        chain = g.equipment_chain(anomaly.point_uri, self.max_hops)
        zone = g.zone_of(anomaly.point_uri)
        scores: dict[str, tuple[float, str, object]] = {}

        # 1. distance prior: nearest owner first
        for d, n in enumerate(chain):
            scores[n.uri] = (1.0 / (1 + d), "in the equipment chain serving the point", n)
        if zone and zone.uri not in scores:
            scores[zone.uri] = (0.5, "zone containing the point", zone)

        # ranking conventions per detector family
        zone_point = point is not None and bool(ZONE_POINT_CLASSES & set(point.classes))
        if zone and (anomaly.detector in ZONE_FIRST or (anomaly.detector == "pattern_deviation" and zone_point)):
            s, _, n = scores[zone.uri]
            scores[zone.uri] = (s + 1.0, "zone-level IEQ symptom: the zone is the primary suspect", n)
        if anomaly.detector == "peak_volatility":
            for n in chain:
                if "Building" in n.classes:
                    s, _, _ = scores[n.uri]
                    scores[n.uri] = (s + 1.0, "main-meter anomaly implicates the whole building", n)
        if anomaly.detector == "damper_fault":
            for n in chain:
                if "Damper" in n.classes:
                    s, _, _ = scores[n.uri]
                    scores[n.uri] = (s + 1.0, "command/position mismatch is on this damper", n)

        # 2. sibling evidence: other anomalous points on the same owner in the same window
        anomalous_points = {a.point_uri for a in all_anomalies if a is not anomaly and _overlaps(a, anomaly)}
        for n in chain[:2]:
            sib = [p for p in g.points_of(n.uri) if p.uri != anomaly.point_uri and p.uri in anomalous_points]
            if len(sib) >= self.shared_min:
                s, _, _ = scores[n.uri]
                scores[n.uri] = (s + 1.0, f"{len(sib)} sibling points on this unit are also anomalous (shared fault)", n)

        # 3. multi-zone rule: the same detector firing in ≥2 zones at once points upstream
        if zone:
            zones_hit = {g.zone_of(a.point_uri).uri for a in all_anomalies
                         if a.detector == anomaly.detector and _overlaps(a, anomaly) and g.zone_of(a.point_uri)}
            if len(zones_hit) >= 2:
                for n in chain:
                    if "AHU" in n.classes:
                        s, _, _ = scores[n.uri]
                        scores[n.uri] = (s + 1.5, f"same symptom in {len(zones_hit)} zones served by this unit", n)

        ranked = sorted(scores.items(), key=lambda kv: -kv[1][0])
        suspects = [Suspect(uri, n.label, n.name, i + 1, round(s, 3), why)
                    for i, (uri, (s, why, n)) in enumerate(ranked)]
        evidence = g.subgraph(anomaly.point_uri, depth=2).to_dict()
        return suspects, evidence
