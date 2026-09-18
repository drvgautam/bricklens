import os

from fastapi.testclient import TestClient

from bricklens.api.app import create_app
from tests.conftest import ROOT

os.environ["BRICKLENS_AUTOSTART"] = "0"
NS = "urn:bricklens:demo#"


def test_graphql_end_to_end():
    app = create_app(str(ROOT / "config/bricklens.yaml"))
    c = TestClient(app)
    assert c.get("/health").json()["status"] == "ok"
    q = lambda query: c.post("/graphql", json={"query": query}).json()

    r = q("{ ingestionStatus { pointsInModel seriesBound unboundSeries rows } }")["data"]["ingestionStatus"]
    assert r["pointsInModel"] == 34 and r["seriesBound"] == 34 and r["unboundSeries"] == []

    r = q("mutation { runDetection { id detector suspects { rank name } } }")["data"]["runDetection"]
    assert len(r) >= 15
    aid = next(a["id"] for a in r if a["detector"] == "damper_fault")

    fields = "explanation suspects { rank name reason } evidence { nodes { uri label } edges { rel } jsonLd } window"
    r = q('{ alert(id: "%s") { %s } }' % (aid, fields))["data"]["alert"]
    assert r["suspects"][0]["name"] == "VAV-2 damper"
    assert any(n["label"] == "Damper" for n in r["evidence"]["nodes"])
    assert "@graph" in r["evidence"]["jsonLd"]
    assert len(r["window"]) == 3

    r = q('{ equipmentHistory(uri: "%sAHU1") { detector } }' % NS)["data"]["equipmentHistory"]
    assert {a["detector"] for a in r} >= {"off_hours", "coil_fighting"}

    r = q('{ subgraph(seedUri: "%sZ3", depth: 1, relations: ["HAS_POINT"]) { nodes { label } } }' % NS)["data"]["subgraph"]
    assert len(r["nodes"]) == 5

    r = q('mutation { setDetectorConfig(name: "co2_high", config: {threshold_ppm: 900}) { config } }')["data"]["setDetectorConfig"]
    assert r["config"]["threshold_ppm"] == 900
    r = q("{ detectors { name enabled family } }")["data"]["detectors"]
    assert len(r) == 8
