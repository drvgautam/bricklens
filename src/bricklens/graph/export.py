"""RDF → property-graph exporter.

Decision (docs/decisions/0001): a custom mapper rather than the n10s plugin, because we
want Brick class local names as node labels and predicate names as relationship types,
which reads well in Cypher and in Neo4j Browser. The mapping is one function, and it is
idempotent (MERGE on URI) so re-exporting after a model change is safe.
"""
from __future__ import annotations

from ..rdf.loader import BrickModel, _local
from .backend import REL, Edge, GraphBackend, Node


def to_nodes_and_edges(model: BrickModel) -> tuple[list[Node], list[Edge]]:
    if not model.inferred:
        raise ValueError("run rdf.loader.infer(model) before exporting")
    nodes = [
        Node(uri=str(uri), label=_local(specific), classes=sorted(_local(c) for c in classes),
             name=model.label(uri), unit=model.unit(uri))
        for uri, specific, classes in model.entities()
    ]
    edges = [Edge(str(s), REL[_local(p)], str(o)) for s, p, o in model.relations() if _local(p) in REL]
    return nodes, edges


def export(model: BrickModel, backend: GraphBackend, clear: bool = False) -> dict:
    nodes, edges = to_nodes_and_edges(model)
    if clear:
        backend.clear()
    backend.upsert_nodes(nodes)
    backend.upsert_edges(edges)
    return {"nodes": len(nodes), "edges": len(edges)}


def make_backend(cfg) -> GraphBackend:
    kind = cfg.graph.backend
    if kind == "neo4j":
        from .neo4j_backend import Neo4jGraph
        n = cfg.graph.neo4j
        return Neo4jGraph(n["uri"], n["user"], n["password"], n.get("database", "neo4j"))
    from .memory import MemoryGraph
    return MemoryGraph()
