"""RDF layer: the only place BrickLens touches the ontology directly.

Responsibilities
- load a Brick Turtle model
- validate it against the Brick SHACL shapes (vendor/Brick.ttl)
- materialise the inferences the property-graph export relies on:
  * the rdfs:subClassOf closure for every entity (so a Zone_Air_Temperature_Sensor
    is also a Temperature_Sensor and a Point)
  * inverse relations (hasPoint/isPointOf, feeds/isFedBy, hasPart/isPartOf,
    hasLocation/isLocationOf), so the exporter sees a symmetric picture

Everything downstream works on the *inferred* graph.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from rdflib import RDF, RDFS, Graph, Namespace, URIRef

BRICK = Namespace("https://brickschema.org/schema/Brick#")

INVERSES = {
    BRICK.hasPoint: BRICK.isPointOf,
    BRICK.feeds: BRICK.isFedBy,
    BRICK.hasPart: BRICK.isPartOf,
    BRICK.hasLocation: BRICK.isLocationOf,
}
INVERSES.update({v: k for k, v in list(INVERSES.items())})


@dataclass
class ValidationReport:
    conforms: bool
    text: str
    violations: int = 0


@dataclass
class BrickModel:
    graph: Graph
    ontology: Graph
    inferred: bool = False
    validation: ValidationReport | None = None
    superclasses: dict[URIRef, set[URIRef]] = field(default_factory=dict)

    # -- helpers used by the exporter ------------------------------------------
    def entities(self):
        """Yield (uri, most_specific_class, all_classes) for every Brick-typed subject."""
        seen = set()
        for s, cls in self.graph.subject_objects(RDF.type):
            if s in seen or not str(cls).startswith(str(BRICK)):
                continue
            seen.add(s)
            direct = [c for c in self.graph.objects(s, RDF.type) if str(c).startswith(str(BRICK))]
            specific = self._most_specific(direct)
            all_classes = set(direct)
            for c in direct:
                all_classes |= self.superclasses.get(c, set())
            yield s, specific, all_classes

    def _most_specific(self, classes):
        # the class that is not a superclass of any other in the list
        for c in classes:
            if not any(c in self.superclasses.get(o, set()) for o in classes if o != c):
                return c
        return classes[0]

    def label(self, uri: URIRef) -> str:
        v = self.graph.value(uri, RDFS.label)
        return str(v) if v else _local(uri)

    def relations(self):
        """Yield (subject, predicate, object) for Brick object properties between entities."""
        for p in (BRICK.hasPoint, BRICK.isPointOf, BRICK.feeds, BRICK.isFedBy,
                  BRICK.hasPart, BRICK.isPartOf, BRICK.hasLocation, BRICK.isLocationOf):
            for s, o in self.graph.subject_objects(p):
                yield s, p, o

    def unit(self, uri: URIRef) -> str | None:
        v = self.graph.value(uri, BRICK.hasUnit)
        return _local(v) if v else None


def _local(uri) -> str:
    s = str(uri)
    for sep in ("#", "/"):
        if sep in s:
            s = s.rsplit(sep, 1)[1]
    return s


@lru_cache(maxsize=2)
def load_ontology(path: str) -> Graph:
    g = Graph()
    g.parse(path, format="turtle")
    return g


def superclass_closure(ontology: Graph) -> dict[URIRef, set[URIRef]]:
    parents: dict[URIRef, set[URIRef]] = {}
    for c, p in ontology.subject_objects(RDFS.subClassOf):
        if isinstance(p, URIRef):
            parents.setdefault(c, set()).add(p)
    closure: dict[URIRef, set[URIRef]] = {}

    def walk(c):
        if c in closure:
            return closure[c]
        out: set[URIRef] = set()
        for p in parents.get(c, ()):
            out.add(p)
            out |= walk(p)
        closure[c] = out
        return out

    for c in list(parents):
        walk(c)
    return closure


def load_model(model_path: str | Path, ontology_path: str | Path) -> BrickModel:
    g = Graph()
    g.parse(str(model_path), format="turtle")
    onto = load_ontology(str(ontology_path))
    return BrickModel(graph=g, ontology=onto, superclasses=superclass_closure(onto))


def validate(model: BrickModel) -> ValidationReport:
    """SHACL-validate the instance model against the Brick shapes.

    Brick.ttl carries its own shapes (bsh: namespace); pyshacl uses the ontology as
    both shapes graph and ont graph. RDFS inference is done by our own closure, so
    pyshacl runs with inference off to keep validation fast on a 1.6 MB ontology.
    """
    from pyshacl import validate as shacl_validate

    conforms, _, text = shacl_validate(
        model.graph, shacl_graph=model.ontology, ont_graph=model.ontology,
        inference="none", abort_on_first=False, allow_warnings=True,
    )
    violations = 0 if conforms else text.count("Constraint Violation")
    model.validation = ValidationReport(conforms=conforms, text=str(text), violations=violations)
    return model.validation


def infer(model: BrickModel) -> BrickModel:
    """Materialise superclass types and inverse relations into the instance graph."""
    g = model.graph
    for s, c in list(g.subject_objects(RDF.type)):
        for sup in model.superclasses.get(c, ()):
            g.add((s, RDF.type, sup))
    for p, inv in INVERSES.items():
        for s, o in list(g.subject_objects(p)):
            g.add((o, inv, s))
    model.inferred = True
    return model
