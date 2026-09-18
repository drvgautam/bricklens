"""GraphQL schema. Every resolver reads the graph backend (Neo4j or memory); none touches RDF."""
from __future__ import annotations

import json
from datetime import datetime

import strawberry
from strawberry.scalars import JSON
from strawberry.types import Info


@strawberry.type
class Suspect:
    uri: str
    label: str
    name: str
    rank: int
    score: float
    reason: str


@strawberry.type
class GraphNode:
    uri: str
    label: str
    name: str
    classes: list[str]
    unit: str | None


@strawberry.type
class GraphEdge:
    source: str
    rel: str
    target: str


@strawberry.type
class EvidenceSubgraph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]

    @strawberry.field
    def json_ld(self) -> JSON:
        """A JSON-LD view keyed by Brick URI, for tools that speak RDF."""
        ctx = {"brick": "https://brickschema.org/schema/Brick#"}
        nodes = {n.uri: {"@id": n.uri, "@type": [f"brick:{c}" for c in n.classes], "rdfs:label": n.name} for n in self.nodes}
        for e in self.edges:
            key = "brick:" + "".join(w.capitalize() if i else w.lower() for i, w in enumerate(e.rel.lower().split("_")))
            nodes.setdefault(e.source, {"@id": e.source}).setdefault(key, []).append({"@id": e.target})
        return {"@context": ctx, "@graph": list(nodes.values())}


@strawberry.type
class Alert:
    id: str
    detector: str
    family: str
    severity: str
    start: datetime
    end: datetime
    minutes: float
    point_uri: str
    zone_uri: str | None
    explanation: str
    metrics: JSON
    suspects: list[Suspect]
    evidence_points: list[str]

    @strawberry.field
    def evidence(self, info: Info, depth: int = 2) -> EvidenceSubgraph:
        sg = info.context["graph"].subgraph(self.point_uri, depth=depth)
        return _subgraph(sg)

    @strawberry.field
    def window(self, info: Info) -> JSON:
        """The time-series that triggered the alert (all evidence points, alert window)."""
        st = info.context["store"]
        out = {}
        for u in self.evidence_points:
            s = st.series(u, self.start, self.end)
            out[u] = [{"ts": str(t), "value": float(v)} for t, v in s.items()]
        return out


@strawberry.type
class DetectorInfo:
    name: str
    family: str
    description: str
    requires: list[str]
    enabled: bool
    config: JSON


@strawberry.type
class IngestionStatus:
    points_in_model: int
    series_bound: int
    unbound_series: list[str]
    points_without_data: list[str]
    rows: int
    start: datetime | None
    end: datetime | None
    last_export: JSON


def _subgraph(sg) -> EvidenceSubgraph:
    d = sg.to_dict()
    return EvidenceSubgraph(
        nodes=[GraphNode(uri=n["uri"], label=n["label"], name=n["name"], classes=n["classes"], unit=n["unit"]) for n in d["nodes"]],
        edges=[GraphEdge(source=e["source"], rel=e["rel"], target=e["target"]) for e in d["edges"]],
    )


def _alert(a: dict) -> Alert:
    import pandas as pd
    return Alert(
        id=a["id"], detector=a["detector"], family=a["family"], severity=a["severity"],
        start=pd.Timestamp(a["start"]).to_pydatetime(), end=pd.Timestamp(a["end"]).to_pydatetime(),
        minutes=float(a.get("minutes", 0)), point_uri=a["point_uri"], zone_uri=a.get("zone_uri"),
        explanation=a["explanation"],
        metrics=a.get("metrics") if isinstance(a.get("metrics"), dict) else json.loads(a.get("metrics") or "{}"),
        suspects=[Suspect(**{k: s[k] for k in ("uri", "label", "name", "rank", "score", "reason")}) for s in a["suspects"]],
        evidence_points=a.get("evidence_points", []),
    )


@strawberry.type
class Query:
    @strawberry.field
    def alerts(self, info: Info, start: datetime | None = None, end: datetime | None = None, family: str | None = None,
               severity: str | None = None, zone: str | None = None, detector: str | None = None,
               limit: int | None = None) -> list[Alert]:
        g = info.context["graph"]
        rows = g.alerts(start=start, end=end, family=family, severity=severity, zone=zone, detector=detector, limit=limit)
        return [_alert(a) for a in rows]

    @strawberry.field
    def alert(self, info: Info, id: str) -> Alert | None:
        a = info.context["graph"].alert(id)
        return _alert(a) if a else None

    @strawberry.field
    def subgraph(self, info: Info, seed_uri: str, depth: int = 2, relations: list[str] | None = None) -> EvidenceSubgraph:
        return _subgraph(info.context["graph"].subgraph(seed_uri, depth=depth, rels=relations))

    @strawberry.field
    def equipment_history(self, info: Info, uri: str, start: datetime | None = None, end: datetime | None = None) -> list[Alert]:
        return [_alert(a) for a in info.context["graph"].equipment_history(uri, start, end)]

    @strawberry.field
    def detectors(self, info: Info) -> list[DetectorInfo]:
        from ..detectors import REGISTRY
        cfg = info.context["cfg"]
        out = []
        for name, d in REGISTRY.items():
            c = dict(cfg.detectors).get(name, {})
            out.append(DetectorInfo(name=name, family=d.family, description=d.description, requires=d.requires,
                                    enabled=bool(c.get("enabled", True)), config={k: v for k, v in c.items() if k != "enabled"}))
        return out

    @strawberry.field
    def ingestion_status(self, info: Info) -> IngestionStatus:
        g, st = info.context["graph"], info.context["store"]
        s = st.status([n.uri for n in g.nodes_with_class("Point")])
        return IngestionStatus(**s, last_export=info.context.get("export_stats") or {})


@strawberry.type
class Mutation:
    @strawberry.field
    def run_detection(self, info: Info, start: datetime | None = None, end: datetime | None = None) -> list[Alert]:
        from ..engine import run_detection
        c = info.context
        return [_alert(a) for a in run_detection(c["cfg"], c["graph"], c["store"], start, end)]

    @strawberry.field
    def set_detector_config(self, info: Info, name: str, config: JSON) -> DetectorInfo:
        cfg = info.context["cfg"]
        from ..detectors import REGISTRY
        if name not in REGISTRY:
            raise ValueError(f"unknown detector {name}")
        cfg["detectors"].setdefault(name, {}).update(config)
        c = cfg["detectors"][name]
        d = REGISTRY[name]
        return DetectorInfo(name=name, family=d.family, description=d.description, requires=d.requires,
                            enabled=bool(c.get("enabled", True)), config={k: v for k, v in c.items() if k != "enabled"})


schema = strawberry.Schema(query=Query, mutation=Mutation)
