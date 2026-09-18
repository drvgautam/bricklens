import pytest

from bricklens.config import load_config
from bricklens.engine import build_graph, load_telemetry
from bricklens.telemetry.store import TelemetryStore

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def cfg():
    c = load_config(ROOT / "config" / "bricklens.yaml")
    c["graph"]["backend"] = "memory"
    return c


@pytest.fixture(scope="session")
def graph(cfg):
    _, g, stats = build_graph(cfg)
    assert stats["nodes"] > 0
    return g


@pytest.fixture(scope="session")
def store(cfg):
    st, n = load_telemetry(cfg, TelemetryStore(":memory:"))
    assert n > 0
    return st
