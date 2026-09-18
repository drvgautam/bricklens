NS = "urn:bricklens:demo#"


def test_export_counts(graph):
    assert len(graph.nodes_with_class("HVAC_Zone")) == 4
    assert len(graph.nodes_with_class("Point")) == 34
    assert len(graph.nodes_with_class("Temperature_Sensor")) == 5   # 4 zone temps + supply air temp (inferred class)


def test_equipment_chain_walks_upstream(graph):
    names = [n.name for n in graph.equipment_chain(NS + "VAV3.dmp_pos")]
    assert names[:3] == ["VAV-3 damper", "VAV-3", "AHU-1"]


def test_zone_of(graph):
    assert graph.zone_of(NS + "Z2.co2").uri == NS + "Z2"
    assert graph.zone_of(NS + "VAV4.dmp_cmd").uri == NS + "Z4"
    assert graph.zone_of(NS + "AHU1.sat") is None


def test_subgraph_depth_and_relations(graph):
    sg = graph.subgraph(NS + "AHU1", depth=1)
    assert any(n.uri == NS + "VAV1" for n in sg.nodes)
    only_feeds = graph.subgraph(NS + "AHU1", depth=1, rels=["FEEDS"])
    assert {e.rel for e in only_feeds.edges} == {"FEEDS"}
    assert len(only_feeds.nodes) == 5
