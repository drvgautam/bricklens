"""Neo4j backend. Every method is one Cypher statement; labels are Brick class names.

Requires Neo4j 5 (Docker Compose ships it). GDS is optional: the localiser's
tie-break uses shortestPath from core Cypher, which needs no plugin.
"""
from __future__ import annotations

from collections.abc import Iterable

from neo4j import GraphDatabase

from .backend import UPSTREAM_RELS, Edge, Node, Subgraph


class Neo4jGraph:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.db = database
        with self.driver.session(database=self.db) as s:
            s.run("CREATE CONSTRAINT entity_uri IF NOT EXISTS FOR (n:Entity) REQUIRE n.uri IS UNIQUE")
            s.run("CREATE CONSTRAINT alert_id IF NOT EXISTS FOR (a:Alert) REQUIRE a.id IS UNIQUE")

    def _run(self, q, **p):
        with self.driver.session(database=self.db) as s:
            return [r.data() for r in s.run(q, **p)]

    # -- export -----------------------------------------------------------------
    def clear(self):
        self._run("MATCH (n:Entity) DETACH DELETE n")

    def upsert_nodes(self, nodes: Iterable[Node]):
        rows = [{"uri": n.uri, "label": n.label, "classes": n.classes, "name": n.name, "unit": n.unit} for n in nodes]
        # MERGE on URI keeps the exporter idempotent; labels are added with APOC-free dynamic SET via classes
        self._run(
            "UNWIND $rows AS r MERGE (n:Entity {uri: r.uri}) "
            "SET n.label = r.label, n.classes = r.classes, n.name = r.name, n.unit = r.unit",
            rows=rows,
        )
        # add the most-specific class as a real label (one statement per distinct label; safe, no APOC)
        for label in {n.label for n in nodes}:
            self._run(f"MATCH (n:Entity) WHERE n.label = $l SET n:`{label}`", l=label)

    def upsert_edges(self, edges: Iterable[Edge]):
        by_rel: dict[str, list] = {}
        for e in edges:
            by_rel.setdefault(e.rel, []).append({"s": e.src, "d": e.dst})
        for rel, rows in by_rel.items():
            self._run(
                f"UNWIND $rows AS r MATCH (a:Entity {{uri: r.s}}), (b:Entity {{uri: r.d}}) MERGE (a)-[:`{rel}`]->(b)",
                rows=rows,
            )

    # -- topology ---------------------------------------------------------------
    @staticmethod
    def _node(r):
        return Node(uri=r["uri"], label=r["label"], classes=r.get("classes") or [], name=r.get("name") or "", unit=r.get("unit"))

    def node(self, uri):
        rows = self._run("MATCH (n:Entity {uri: $u}) RETURN n{.*}", u=uri)
        return self._node(rows[0]["n"]) if rows else None

    def nodes_with_class(self, cls):
        return [self._node(r["n"]) for r in self._run("MATCH (n:Entity) WHERE $c IN n.classes RETURN n{.*}", c=cls)]

    def points_of(self, equipment_uri):
        return [self._node(r["p"]) for r in self._run(
            "MATCH (e:Entity {uri: $u})-[:HAS_POINT]->(p) RETURN p{.*}", u=equipment_uri)]

    def equipment_chain(self, point_uri, max_hops=4):
        rels = "|".join(UPSTREAM_RELS)
        rows = self._run(
            f"MATCH path = (p:Entity {{uri: $u}})-[:{rels}*1..{max_hops}]->(e) "
            "WHERE NOT 'Point' IN e.classes "
            "WITH e, min(length(path)) AS d ORDER BY d RETURN e{.*} AS e",
            u=point_uri,
        )
        return [self._node(r["e"]) for r in rows]

    def zone_of(self, uri):
        rows = self._run(
            "MATCH (n:Entity {uri: $u}) "
            "OPTIONAL MATCH (n)-[:IS_POINT_OF|IS_PART_OF*0..3]->(e) "
            "OPTIONAL MATCH (e)-[:FEEDS]->(f) "
            "WITH n, e, f WHERE 'HVAC_Zone' IN n.classes OR 'HVAC_Zone' IN e.classes OR 'HVAC_Zone' IN f.classes "
            "RETURN CASE WHEN 'HVAC_Zone' IN n.classes THEN n{.*} WHEN 'HVAC_Zone' IN e.classes THEN e{.*} ELSE f{.*} END AS z "
            "LIMIT 1", u=uri)
        return self._node(rows[0]["z"]) if rows and rows[0]["z"] else None

    def subgraph(self, seed_uri, depth=2, rels=None):
        relf = "" if not rels else ":" + "|".join(rels)
        rows = self._run(
            f"MATCH (s:Entity {{uri: $u}}) OPTIONAL MATCH p = (s)-[{relf}*1..{depth}]-(m) "
            "WITH s, collect(p) AS paths "
            "RETURN s{.*} AS s, [p IN paths | [x IN nodes(p) | x{.*}]] AS ns, "
            "[p IN paths | [r IN relationships(p) | {s: startNode(r).uri, t: endNode(r).uri, rel: type(r)}]] AS rs",
            u=seed_uri,
        )
        if not rows:
            return Subgraph([], [])
        nodes, edges = {rows[0]["s"]["uri"]: self._node(rows[0]["s"])}, {}
        for path in rows[0]["ns"]:
            for n in path:
                nodes[n["uri"]] = self._node(n)
        for path in rows[0]["rs"]:
            for r in path:
                edges[(r["s"], r["rel"], r["t"])] = Edge(r["s"], r["rel"], r["t"])
        return Subgraph(list(nodes.values()), list(edges.values()))

    # -- alerts -----------------------------------------------------------------
    def write_alert(self, alert):
        a = {k: v for k, v in alert.items() if k not in ("suspects", "evidence_points", "evidence")}
        a["start"], a["end"] = str(a["start"]), str(a["end"])
        self._run("MERGE (x:Alert {id: $id}) SET x += $a", id=alert["id"], a=a)
        self._run("MATCH (x:Alert {id: $id})-[r:IMPLICATES|EVIDENCED_BY]->() DELETE r", id=alert["id"])
        self._run(
            "UNWIND $s AS s MATCH (x:Alert {id: $id}), (e:Entity {uri: s.uri}) "
            "MERGE (x)-[r:IMPLICATES]->(e) SET r.rank = s.rank, r.score = s.score, r.reason = s.reason",
            id=alert["id"], s=alert["suspects"],
        )
        self._run(
            "UNWIND $p AS u MATCH (x:Alert {id: $id}), (e:Entity {uri: u}) MERGE (x)-[:EVIDENCED_BY]->(e)",
            id=alert["id"], p=alert["evidence_points"],
        )

    def clear_alerts(self):
        self._run("MATCH (a:Alert) DETACH DELETE a")

    def _hydrate(self, rows):
        out = []
        for r in rows:
            a = dict(r["a"])
            a["suspects"] = sorted(r["suspects"], key=lambda s: s["rank"])
            a["evidence_points"] = r["points"]
            out.append(a)
        return out

    _ALERT_RETURN = (
        "OPTIONAL MATCH (a)-[i:IMPLICATES]->(e) "
        "WITH a, collect({uri: e.uri, rank: i.rank, score: i.score, reason: i.reason, label: e.label, name: e.name}) AS suspects "
        "OPTIONAL MATCH (a)-[:EVIDENCED_BY]->(p) RETURN a{.*} AS a, suspects, collect(p.uri) AS points ORDER BY a.start"
    )

    def alert(self, alert_id):
        rows = self._run("MATCH (a:Alert {id: $id}) " + self._ALERT_RETURN, id=alert_id)
        return self._hydrate(rows)[0] if rows else None

    def alerts(self, start=None, end=None, family=None, severity=None, zone=None, detector=None, limit=None):
        q = "MATCH (a:Alert) WHERE ($start IS NULL OR a.end >= $start) AND ($end IS NULL OR a.start <= $end) " \
            "AND ($family IS NULL OR a.family = $family) AND ($sev IS NULL OR a.severity = $sev) " \
            "AND ($zone IS NULL OR a.zone_uri = $zone) AND ($det IS NULL OR a.detector = $det) " + self._ALERT_RETURN
        if limit:
            q += f" LIMIT {int(limit)}"
        return self._hydrate(self._run(q, start=str(start) if start else None, end=str(end) if end else None,
                                       family=family, sev=severity, zone=zone, det=detector))

    def equipment_history(self, uri, start=None, end=None):
        return self._hydrate(self._run(
            "MATCH (a:Alert)-[:IMPLICATES]->(:Entity {uri: $u}) "
            "WHERE ($start IS NULL OR a.end >= $start) AND ($end IS NULL OR a.start <= $end) WITH DISTINCT a "
            + self._ALERT_RETURN, u=uri, start=str(start) if start else None, end=str(end) if end else None))
