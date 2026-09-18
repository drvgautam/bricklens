"""FastAPI application: GraphQL at /graphql, health at /health."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from strawberry.fastapi import GraphQLRouter

from ..config import load_config
from ..engine import build_graph, load_telemetry
from .schema import schema


def create_app(config_path: str | None = None, load_data: bool = True) -> FastAPI:
    cfg = load_config(config_path or os.environ.get("BRICKLENS_CONFIG", "config/bricklens.yaml"))
    _model, graph, export_stats = build_graph(cfg)
    if load_data:
        store, _ = load_telemetry(cfg)
    else:
        from ..telemetry.store import TelemetryStore
        store = TelemetryStore(cfg.resolve(cfg.telemetry.store))
    state = {"cfg": cfg, "graph": graph, "store": store, "export_stats": export_stats}

    async def get_context():
        return state

    app = FastAPI(title="BrickLens", version="1.0.0")
    app.include_router(GraphQLRouter(schema, context_getter=get_context), prefix="/graphql")

    @app.get("/health")
    def health():
        return {"status": "ok", "graph": export_stats, "rows": store.bounds()["rows"]}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    web = Path(__file__).resolve().parents[3] / "web"
    if web.exists():
        app.mount("/", StaticFiles(directory=str(web), html=True), name="web")

    app.state.bricklens = state
    return app


app = None
if os.environ.get("BRICKLENS_AUTOSTART", "1") == "1" and __name__ != "__main__":
    try:
        app = create_app()
    except Exception:  # pragma: no cover - lazily created by the CLI instead
        app = None
