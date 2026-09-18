# 0002 — Custom RDF→Neo4j mapper instead of the n10s plugin

**Status:** accepted · **Sprint:** 1

## Context
Neo4j's neosemantics (n10s) plugin imports RDF directly, but produces namespace-prefixed labels
(`brick__CO2_Sensor`), a `Resource` label on everything, and relationship types derived from full predicate IRIs.

## Decision
A ~40-line mapper (`graph/export.py`): node label = most specific Brick class local name, `classes` = the full
inferred class list, relationship types = upper-snake predicate names. `MERGE` on URI keeps it idempotent.

## Alternatives rejected
n10s: faster to start, noisier labels, and an extra plugin to install; the mapping is small enough to own.

## Consequences
The mapping table in `docs/architecture.md` is part of the contract; a new Brick relation needs one line in
`graph/backend.py::REL`.
