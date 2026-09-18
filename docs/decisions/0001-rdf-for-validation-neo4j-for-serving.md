# 0001 — Validate in RDF, serve from a property graph

**Status:** accepted · **Sprint:** 1

## Context
Brick is an RDF/OWL ontology with SHACL shapes; the tooling for validation and inference is RDF tooling.
Localisation is multi-hop traversal and ranking, which is what property graphs and Cypher are built for. An earlier
project did localisation with SPARQL property paths plus a Python BFS on top, and that was the awkward part.

## Decision
- `rdflib` + the vendored Brick 1.3 shapes for load, validate, infer — the only RDF code in the repo.
- A custom exporter writes the inferred graph into Neo4j (or an in-memory networkx twin) as typed nodes and edges.
- The property graph is never edited by hand; a model change is re-validate + re-export (idempotent).
- Alerts are graph data: `Alert` nodes with `IMPLICATES` and `EVIDENCED_BY` edges, so "everything that has
  implicated AHU-1 this month" is one query.

## Alternatives rejected
- **RDF only (rdflib in memory or Fuseki):** traversal and ranking end up in application code; no natural place to
  store alerts as first-class graph objects; weak visual story.
- **Neo4j only:** loses SHACL validation and subclass inference unless re-implemented; cannot claim "this is
  valid Brick" once the model lives only as a property graph.

## Consequences
Two query surfaces to keep straight (documented in `docs/architecture.md`); Docker Compose gains a Neo4j service;
tests run on the in-memory backend and CI runs a separate Neo4j integration job.
