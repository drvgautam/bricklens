"""In-memory graph backend on networkx. Same query semantics as the Neo4j backend."""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable

import networkx as nx

from .backend import UPSTREAM_RELS, Edge, Node, Subgraph

LOCATION_CLASSES = {"HVAC_Zone", "Room", "Floor", "Building", "Location", "Space"}


class MemoryGraph:
    def __init__(self):
        self.g = nx.MultiDiGraph()
        self._alerts: dict[str, dict] = {}

    # -- export -----------------------------------------------------------------
    def clear(self):
        self.g.clear()

    def upsert_nodes(self, nodes: Iterable[Node]):
        for n in nodes:
            self.g.add_node(n.uri, data=n)

    def upsert_edges(self, edges: Iterable[Edge]):
        for e in edges:
            if not self.g.has_edge(e.src, e.dst, key=e.rel):
                self.g.add_edge(e.src, e.dst, key=e.rel)

    # -- topology ---------------------------------------------------------------
    def node(self, uri):
        return self.g.nodes[uri]["data"] if uri in self.g else None

    def nodes_with_class(self, cls):
        return [d["data"] for _, d in self.g.nodes(data=True) if cls in d["data"].classes]

    def _out(self, uri, rel):
        return [v for _, v, k in self.g.out_edges(uri, keys=True) if k == rel]

    def points_of(self, equipment_uri):
        return [self.node(v) for v in self._out(equipment_uri, "HAS_POINT")]

    def equipment_chain(self, point_uri, max_hops=4):
        chain, seen, frontier = [], {point_uri}, deque([(point_uri, 0)])
        while frontier:
            u, d = frontier.popleft()
            if d >= max_hops:
                continue
            for rel in UPSTREAM_RELS:
                for v in self._out(u, rel):
                    if v in seen:
                        continue
                    seen.add(v)
                    n = self.node(v)
                    if n and "Point" not in n.classes:
                        chain.append(n)
                    frontier.append((v, d + 1))
        return chain

    def zone_of(self, uri):
        """The HVAC zone a point/equipment belongs to. Walks up IS_POINT_OF / IS_PART_OF, then
        one FEEDS hop into a zone (a terminal unit feeds its zone). Never descends FEEDS
        from an AHU, which serves many zones."""
        n = self.node(uri)
        if n is None:
            return None
        if "HVAC_Zone" in n.classes:
            return n
        for v in self._out(uri, "FEEDS"):
            z = self.node(v)
            if z and "HVAC_Zone" in z.classes:
                return z
        for v in self._out(uri, "IS_POINT_OF") + self._out(uri, "IS_PART_OF"):
            z = self.zone_of(v)
            if z:
                return z
        return None

    def subgraph(self, seed_uri, depth=2, rels=None):
        if seed_uri not in self.g:
            return Subgraph([], [])
        rels = set(rels) if rels else None
        seen, frontier, edges = {seed_uri}, deque([(seed_uri, 0)]), []
        while frontier:
            u, d = frontier.popleft()
            if d >= depth:
                continue
            for _, v, k in list(self.g.out_edges(u, keys=True)) + [(a, b, c) for b, a, c in self.g.in_edges(u, keys=True)]:
                if rels and k not in rels:
                    continue
                src, dst = (u, v) if self.g.has_edge(u, v, key=k) else (v, u)
                edges.append(Edge(src, k, dst))
                if v not in seen:
                    seen.add(v)
                    frontier.append((v, d + 1))
        uniq = {(e.src, e.rel, e.dst): e for e in edges}
        return Subgraph([self.node(u) for u in seen], list(uniq.values()))

    # -- alerts -----------------------------------------------------------------
    def write_alert(self, alert):
        self._alerts[alert["id"]] = alert

    def clear_alerts(self):
        self._alerts.clear()

    def alert(self, alert_id):
        return self._alerts.get(alert_id)

    def alerts(self, start=None, end=None, family=None, severity=None, zone=None, detector=None, limit=None):
        out = []
        for a in self._alerts.values():
            if start and a["end"] < start:
                continue
            if end and a["start"] > end:
                continue
            if family and a["family"] != family:
                continue
            if severity and a["severity"] != severity:
                continue
            if detector and a["detector"] != detector:
                continue
            if zone and a.get("zone_uri") != zone:
                continue
            out.append(a)
        out.sort(key=lambda a: a["start"])
        return out[:limit] if limit else out

    def equipment_history(self, uri, start=None, end=None):
        return [a for a in self.alerts(start=start, end=end)
                if any(s["uri"] == uri for s in a["suspects"])]
