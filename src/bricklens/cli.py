"""bricklens CLI: validate-model, export, load, run, validate, serve."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from .config import load_config

app = typer.Typer(help="BrickLens — semantic fault detection and IEQ advisor.")


@app.command("validate-model")
def validate_model(model: Path = typer.Argument(None), config: Path = typer.Option("config/bricklens.yaml")):
    """SHACL-validate a Brick model against the vendored Brick 1.3 shapes."""
    from .rdf.loader import load_model, validate
    cfg = load_config(config)
    m = load_model(model or cfg.resolve(cfg.building.model), cfg.resolve(cfg.building.brick_ontology))
    rep = validate(m)
    typer.echo(f"conforms: {rep.conforms}  violations: {rep.violations}")
    if not rep.conforms:
        typer.echo(rep.text)
        raise typer.Exit(1)


@app.command()
def export(config: Path = typer.Option("config/bricklens.yaml"), backend: str = typer.Option(None, help="memory | neo4j")):
    """Validate, infer and export the Brick model into the graph backend."""
    from .engine import build_graph
    cfg = load_config(config)
    if backend:
        cfg["graph"]["backend"] = backend
    _, _, stats = build_graph(cfg)
    typer.echo(json.dumps(stats))


@app.command()
def load(config: Path = typer.Option("config/bricklens.yaml")):
    """Load telemetry from the configured source into the DuckDB store."""
    from .engine import build_graph, load_telemetry
    cfg = load_config(config)
    _, graph, _ = build_graph(cfg, do_validate=False)
    store, n = load_telemetry(cfg)
    typer.echo(json.dumps({"rows": n, **{k: (str(v) if k in ("start", "end") else v)
                                         for k, v in store.status([p.uri for p in graph.nodes_with_class("Point")]).items()}}, indent=2))


@app.command()
def run(config: Path = typer.Option("config/bricklens.yaml"), start: str = typer.Option(None), end: str = typer.Option(None),
        out: Path = typer.Option(None, help="write alerts JSON here")):
    """Run all enabled detectors over the loaded telemetry and write alerts to the graph."""
    from .engine import alerts_frame, build_graph, load_telemetry, run_detection
    cfg = load_config(config)
    _, graph, _ = build_graph(cfg)
    store, _ = load_telemetry(cfg)
    alerts = run_detection(cfg, graph, store, start, end)
    typer.echo(alerts_frame(alerts).to_string())
    if out:
        out.write_text(json.dumps(alerts, default=str, indent=2))


@app.command()
def validate(config: Path = typer.Option("config/bricklens.yaml"), labels: Path = typer.Option(None),
             report: Path = typer.Option(None, help="write markdown report here"), strict: bool = typer.Option(True)):
    """Run detection and score it against the labelled fault log; non-zero exit if targets are missed."""
    import pandas as pd

    from .engine import build_graph, load_telemetry, run_detection
    from .validation import check_targets, evaluate, markdown_table
    cfg = load_config(config)
    _, graph, _ = build_graph(cfg)
    store, _ = load_telemetry(cfg)
    alerts = run_detection(cfg, graph, store)
    labels = labels or cfg.resolve(cfg.telemetry.source.get("faults", "data/faults.csv"))
    faults = pd.read_csv(labels)
    b = store.bounds()
    weeks = (pd.Timestamp(b["end"]) - pd.Timestamp(b["start"])).days / 7
    res = evaluate(alerts, faults, n_zones=len(graph.nodes_with_class("HVAC_Zone")), weeks=weeks,
                   overlap_min=cfg.validation.overlap_min)
    table = markdown_table(res)
    typer.echo(table)
    if report:
        report.write_text(table + "\n")
    fails = check_targets(res, dict(cfg.validation.targets))
    if fails:
        typer.echo("TARGETS MISSED: " + "; ".join(fails))
        if strict:
            raise typer.Exit(1)
    else:
        typer.echo("all targets met")


@app.command()
def serve(config: Path = typer.Option("config/bricklens.yaml"), host: str = "0.0.0.0", port: int = 8000,
          detect: bool = typer.Option(True, help="run detection on startup so the web view has alerts (--no-detect to skip)")):
    """Start the GraphQL API and web view. Loads the model and telemetry, then runs detection unless --no-detect."""
    import uvicorn

    from .api.app import create_app
    from .engine import run_detection

    application = create_app(str(config))
    if detect:
        s = application.state.bricklens
        n = len(run_detection(s["cfg"], s["graph"], s["store"]))
        typer.echo(f"detection complete: {n} alerts — open http://localhost:{port}/")
    uvicorn.run(application, host=host, port=port)


if __name__ == "__main__":
    app()
