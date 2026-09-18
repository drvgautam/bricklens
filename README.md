# BrickLens

**Semantic fault detection and indoor-environmental-quality (IEQ) advisor for a Brick-modelled building.**
Validates the building model in RDF, serves it from a property graph, runs eight detectors over bound sensor
time-series, and localises every alert to the zone and equipment responsible — with the evidence subgraph to
show why.

```
Brick TTL ──► rdflib + brickschema shapes ──► RDF→graph exporter ──► Neo4j / in-memory graph
                 (validate, infer)                                        ▲          │
CSV · Parquet · synthetic · CSIRO · BMS ──► DuckDB telemetry store ──► detectors ──► localiser ──► GraphQL API + web view
```

Built as a portfolio piece for an *Advisor in AI and Semantic Technologies* role in a zero-emission-building
research group. It is scoped to show three things in working code: semantic models plus ML for decision support,
integration of building data from more than one source, and a design that a facilities team could validate and
plug a real BMS into.

## Quick start (no Neo4j needed)

```bash
pip install -e ".[dev]"
bricklens validate-model            # SHACL-validate models/demo_building.ttl against Brick 1.3
bricklens validate                  # generate 4 weeks of telemetry, run detection, score against ground truth
bricklens serve                     # runs detection on startup; web view at http://localhost:8000/, GraphQL at /graphql
```

The web view is populated by the server itself (`serve` runs detection on startup, and the **Run detection** button
re-runs it). With the default in-memory backend, `bricklens run` in a terminal writes to its own process, not to a
running server — only the Neo4j backend shares alerts between the CLI and the server.

With Neo4j (graph served from Neo4j, Neo4j Browser at http://localhost:7474, user `neo4j` / `bricklens`):

```bash
docker compose up --build
```

Then open http://localhost:8000/, or in Neo4j Browser:

```cypher
MATCH (a:Alert)-[i:IMPLICATES]->(e) WHERE i.rank = 1 RETURN a.detector, a.start, e.name ORDER BY a.start;
MATCH p = (:Alert {detector:'damper_fault'})-[:EVIDENCED_BY]->(:Entity)-[:IS_POINT_OF|IS_PART_OF*1..3]->() RETURN p;
```

## What it detects

| Alert | Family | Needs (Brick point classes) | Rule | Localised to |
| --- | --- | --- | --- | --- |
| `co2_high` | IEQ | `CO2_Sensor` | > 1000 ppm for 30 min | zone → VAV → AHU |
| `temp_band` | IEQ | `Zone_Air_Temperature_Sensor` + `_Setpoint` | outside setpoint ± 2 °C while occupied | zone → VAV |
| `humidity_band` | IEQ | `Zone_Air_Humidity_Sensor` | outside 30–60 % RH for 60 min | zone → AHU |
| `damper_fault` | IEQ/FDD | `Damper_Position_Command`, `_Sensor`, `CO2_Sensor` | commanded > 60 %, position lags > 10 %, CO2 > 900 | damper → VAV → AHU |
| `off_hours` | energy | `Electric_Power_Sensor` on an AHU | > 2 kW outside the schedule for 60 min | AHU |
| `coil_fighting` | energy | `Heating_Command` + `Cooling_Command` | both > 10 % for 15 min | AHU or VAV |
| `peak_volatility` | energy | `Electric_Power_Sensor` on the building | > 3σ above the same-slot baseline | building |
| `pattern_deviation` | statistical | any sensor | residual against the point's own weekly profile, \|z\| > 4 for 60 min (Isolation Forest optional) | point's owner |

A detector declares the point classes it needs and is skipped, not failed, on a building that lacks them.
Statistical alerts are suppressed where a rule-based alert already explains the same zone/equipment and window.

## Validation (synthetic ground truth, 4 weeks, 15 injected faults)

| Alert type | Alerts | TP | FP | Faults | Detected | Precision | Recall | Localisation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **overall** | 15 | 15 | 0 | 15 | 15 | **1.0** | **1.0** | **1.0** |

Perfect scores on synthetic data are expected, not impressive: the faults are scripted to the signatures the
detectors look for. What the run does establish is one alert per injected fault, correct localisation for every
alert type, stability across six noise seeds (the Isolation Forest variant failed this — `docs/decisions/0003`),
and a CI gate (`bricklens validate`) that fails when a threshold change breaks any of it. The second run on the
public CSIRO dataset is where detection quality gets a real test (`docs/validation.md`). Per-type figures:
`docs/validation_synthetic.md`.

## Repository layout

```
src/bricklens/
  rdf/loader.py        load · SHACL-validate · infer (subclass closure, inverse relations)   — the only RDF code
  graph/backend.py     the query surface (Protocol) both backends implement
  graph/memory.py      networkx backend (tests, default demo)
  graph/neo4j_backend.py  Cypher backend; alerts stored as nodes with IMPLICATES / EVIDENCED_BY edges
  graph/export.py      RDF → property-graph mapper (idempotent, MERGE on URI)
  telemetry/store.py   DuckDB store keyed by Brick point URI
  telemetry/sources.py TelemetrySource protocol: Csv · Parquet · Synthetic · Csiro · BmsRest (stub)
  telemetry/synthetic.py  4-week generator with 15 scripted faults and a faults.csv ground truth
  detectors/           ieq.py · energy.py · stats.py, all registered through base.py
  localiser.py         chain → siblings → scoring; returns ranked suspects + evidence subgraph
  engine.py            build graph, load telemetry, run, suppress, localise, write
  validation.py        precision / recall / localisation / time-to-detect / false alerts per zone-week
  api/schema.py        GraphQL: alerts · alert · subgraph · equipmentHistory · detectors · ingestionStatus · runDetection · setDetectorConfig
  cli.py               validate-model · export · load · run · validate · serve
models/demo_building.ttl   one floor, one AHU, four VAV zones, 34 points (Brick 1.3)
config/bricklens.yaml      every threshold with a one-line rationale
config/mapping.example.yaml  tag → Brick URI mapping for a real BMS or the CSIRO dataset
docs/decisions/            one entry per design decision
web/index.html             alert list + force-directed evidence subgraph (d3)
```

## Feeding it a real building

1. Write (or export) the building in Brick; `bricklens validate-model your.ttl`.
2. Implement `TelemetrySource` (two methods) against your historian, or map a CSV/Parquet export with a
   tag → URI mapping (`config/mapping.example.yaml`). Unit normalisation belongs there, never in a detector.
3. `bricklens load` reports `unbound_series` (telemetry with no Brick point) and `points_without_data`.
4. Tune thresholds in `config/bricklens.yaml`; record why in `docs/decisions/`.
5. If you have a fault log, `bricklens validate --labels faults.csv` scores it.

## Public dataset

The second validation run targets the [CSIRO Newcastle AHU fault dataset](https://github.com/csiro-energy-systems/ahu-fault-detection-dataset)
(CC BY-SA 4.0): eight months of BMS data from two AHUs in an operating office building with faults inserted
through the BMS (stuck valves and dampers, sensor offsets, fan-belt slip) and a ground-truth table. Its data
files are behind Git LFS; `CsiroSource` reads them after `git lfs pull`. See `docs/validation.md` for the run
recipe and the mapping notes.

## Licence

MIT. Brick 1.3 (`vendor/Brick.ttl`) is BSD-3-Clause, © Brick Consortium.
