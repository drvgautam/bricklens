"""The query surface every graph backend must offer.

The localiser and the API only ever talk to this Protocol. Two implementations ship:
- MemoryGraph (networkx): zero-dependency, used in tests and the default demo
- Neo4jGraph: the production/serving backend, same semantics expressed in Cypher

Node labels are Brick class local names (AHU, VAV, HVAC_Zone, CO2_Sensor, ...).
Relationship types are upper-snake versions of Brick predicates (FEEDS, HAS_POINT, ...).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

REL = {
    "hasPoint": "HAS_POINT", "isPointOf": "IS_POINT_OF",
    "feeds": "FEEDS", "isFedBy": "IS_FED_BY",
    "hasPart": "HAS_PART", "isPartOf": "IS_PART_OF",
    "hasLocation": "HAS_LOCATION", "isLocationOf": "IS_LOCATION_OF",
}
UPSTREAM_RELS = ("IS_POINT_OF", "IS_PART_OF", "IS_FED_BY")   # from a point towards the equipment that serves it


@dataclass
class Node:
    uri: str
    label: str                       # most specific Brick class
    classes: list[str] = field(default_factory=list)
    name: str = ""
    unit: str | None = None
    props: dict = field(default_factory=dict)


@dataclass
class Edge:
    src: str
    rel: str
    dst: str


@dataclass
class Subgraph:
    nodes: list[Node]
    edges: list[Edge]

    def to_dict(self) -> dict:
        return {
            "nodes": [{"uri": n.uri, "label": n.label, "classes": n.classes, "name": n.name, "unit": n.unit} for n in self.nodes],
            "edges": [{"source": e.src, "rel": e.rel, "target": e.dst} for e in self.edges],
        }


class GraphBackend(Protocol):
    # --- export ---------------------------------------------------------------
    def clear(self) -> None: ...
    def upsert_nodes(self, nodes: Iterable[Node]) -> None: ...
    def upsert_edges(self, edges: Iterable[Edge]) -> None: ...

    # --- topology queries used by the localiser and the API --------------------
    def node(self, uri: str) -> Node | None: ...
    def nodes_with_class(self, cls: str) -> list[Node]: ...
    def points_of(self, equipment_uri: str) -> list[Node]:
        """Points directly attached to an equipment/location node."""
        ...
    def equipment_chain(self, point_uri: str, max_hops: int = 4) -> list[Node]:
        """Ordered nearest-first: the equipment/location chain that serves a point
        (point -IS_POINT_OF-> damper -IS_PART_OF-> VAV -IS_FED_BY-> AHU ...)."""
        ...
    def zone_of(self, uri: str) -> Node | None: ...
    def subgraph(self, seed_uri: str, depth: int = 2, rels: list[str] | None = None) -> Subgraph: ...

    # --- alerts ----------------------------------------------------------------
    def write_alert(self, alert: dict) -> None: ...
    def alerts(self, **filters) -> list[dict]: ...
    def alert(self, alert_id: str) -> dict | None: ...
    def equipment_history(self, uri: str, start=None, end=None) -> list[dict]: ...
    def clear_alerts(self) -> None: ...
