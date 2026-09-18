# 0004 — Localiser ranking conventions

**Status:** accepted · **Sprint:** 4

## Decision
Suspects are scored, not just listed: distance prior `1/(1+hops)`, then bonuses that encode how a facilities
engineer reads a symptom — the zone for zone-level IEQ symptoms, the damper for a command/position mismatch, the
building for a main-meter anomaly, an owner with ≥ 2 anomalous sibling points (shared fault), and the AHU when the
same symptom fires in ≥ 2 zones it serves. Every bonus carries a one-line `reason` that is returned with the
suspect, so the ranking is explainable in the UI and in Neo4j Browser.

`zone_of` walks up `IS_POINT_OF | IS_PART_OF` and takes one `FEEDS` hop into a zone; it never descends `FEEDS`
from an AHU, which serves many zones (found and fixed by `tests/test_graph.py::test_zone_of`).

## Alternatives rejected
Pure shortest-path ranking: puts the VAV ahead of the zone for a CO2 excursion caused by occupancy, which is wrong
for the reader. GDS community detection: overkill for a single-AHU building; reconsider for multi-AHU plants.
