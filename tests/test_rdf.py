from rdflib import RDF

from bricklens.rdf.loader import BRICK, infer, load_model, validate
from tests.conftest import ROOT

MODEL, ONTO = ROOT / "models/demo_building.ttl", ROOT / "vendor/Brick.ttl"


def test_demo_model_conforms():
    m = load_model(MODEL, ONTO)
    rep = validate(m)
    assert rep.conforms, rep.text


def test_bad_model_is_rejected(tmp_path):
    # a sensor that "feeds" a zone violates the Brick feeds domain (Equipment/Location only)
    bad = tmp_path / "bad.ttl"
    bad.write_text("""@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix ex: <urn:x#> .
ex:s a brick:CO2_Sensor ; brick:feeds ex:z .
ex:z a brick:HVAC_Zone .
ex:z brick:hasPoint ex:vav .
ex:vav a brick:VAV .
""")
    m = load_model(bad, ONTO)
    rep = validate(m)
    assert not rep.conforms


def test_infer_adds_superclasses_and_inverses():
    m = infer(load_model(MODEL, ONTO))
    g = m.graph
    co2 = next(s for s in g.subjects(RDF.type, BRICK.CO2_Sensor))
    assert (co2, RDF.type, BRICK.Sensor) in g
    assert (co2, RDF.type, BRICK.Point) in g
    assert (co2, BRICK.isPointOf, None) in g
    ahu = next(s for s in g.subjects(RDF.type, BRICK.AHU))
    assert any(True for _ in g.objects(ahu, BRICK.feeds))
    assert any(True for _ in g.subjects(BRICK.isFedBy, ahu))
