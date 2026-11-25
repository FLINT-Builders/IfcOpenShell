# This file was generated with the assistance of an AI coding tool.

import os
import tempfile

import pytest

import ifcopenshell
import ifcopenshell.api.alignment
import ifcopenshell.guid

try:
    ifcopenshell.file(schema="IFC4X3")
    IFC4X3_AVAILABLE = True
except RuntimeError:
    IFC4X3_AVAILABLE = False


def _reopen(model: ifcopenshell.file) -> ifcopenshell.file:
    descriptor, path = tempfile.mkstemp(suffix=".ifc")
    os.close(descriptor)
    try:
        model.write(path)
        return ifcopenshell.open(path)
    finally:
        os.unlink(path)


def _alignment(model: ifcopenshell.file, name: str) -> ifcopenshell.entity_instance:
    return model.create_entity("IfcAlignment", GlobalId=ifcopenshell.guid.new(), Name=name)


def _aggregate(model: ifcopenshell.file, parent, child) -> None:
    model.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=parent,
        RelatedObjects=[child],
    )


def _mutual_cycle() -> ifcopenshell.file:
    model = ifcopenshell.file(schema="IFC4X3")
    first = _alignment(model, "A0")
    second = _alignment(model, "A1")
    _aggregate(model, first, second)
    _aggregate(model, second, first)
    return _reopen(model)


def _follows_parent_to_self(alignment) -> bool:
    seen = set()
    current = alignment
    while current.id() not in seen:
        seen.add(current.id())
        if len(current.Decomposes) == 0:
            return False
        current = current.Decomposes[0].RelatingObject
    return True


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_mutual_aggregate_cycle_returns_no_basis_curve():
    model = _mutual_cycle()
    alignments = model.by_type("IfcAlignment")
    assert len(alignments) == 2
    for alignment in alignments:
        assert alignment.Representation is None
        assert _follows_parent_to_self(alignment)
        assert ifcopenshell.api.alignment.get_basis_curve(alignment) is None


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_three_alignment_cycle_returns_no_basis_curve():
    model = ifcopenshell.file(schema="IFC4X3")
    alignments = [_alignment(model, name) for name in ("A0", "A1", "A2")]
    for index, alignment in enumerate(alignments):
        _aggregate(model, alignment, alignments[(index + 1) % 3])
    model = _reopen(model)
    opened = model.by_type("IfcAlignment")
    assert len(opened) == 3
    for alignment in opened:
        assert alignment.Representation is None
        assert _follows_parent_to_self(alignment)
        assert ifcopenshell.api.alignment.get_basis_curve(alignment) is None


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_self_aggregate_returns_no_basis_curve():
    model = ifcopenshell.file(schema="IFC4X3")
    alignment = _alignment(model, "A0")
    _aggregate(model, alignment, alignment)
    model = _reopen(model)
    alignment = model.by_type("IfcAlignment")[0]
    assert alignment.Representation is None
    assert alignment.Decomposes[0].RelatingObject == alignment
    assert ifcopenshell.api.alignment.get_basis_curve(alignment) is None


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_non_axis_representation_still_stops_on_cycle():
    model = ifcopenshell.file(schema="IFC4X3")
    first = _alignment(model, "A0")
    second = _alignment(model, "A1")
    _aggregate(model, first, second)
    _aggregate(model, second, first)
    polyline = model.create_entity(
        "IfcPolyline",
        Points=[
            model.createIfcCartesianPoint((0.0, 0.0)),
            model.createIfcCartesianPoint((1.0, 0.0)),
        ],
    )
    body = model.create_entity(
        "IfcShapeRepresentation",
        RepresentationIdentifier="Body",
        RepresentationType="Curve2D",
        Items=[polyline],
    )
    first.Representation = model.create_entity("IfcProductDefinitionShape", Representations=[body])
    model = _reopen(model)
    named = {alignment.Name: alignment for alignment in model.by_type("IfcAlignment")}
    assert named["A0"].Representation.Representations[0].RepresentationIdentifier == "Body"
    assert _follows_parent_to_self(named["A0"])
    assert ifcopenshell.api.alignment.get_basis_curve(named["A0"]) is None
    assert ifcopenshell.api.alignment.get_basis_curve(named["A1"]) is None


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_acyclic_parent_chain_still_returns_ancestor_curve():
    model = ifcopenshell.file(schema="IFC4X3")
    grandparent = _alignment(model, "G")
    parent = _alignment(model, "P")
    child = _alignment(model, "C")
    _aggregate(model, grandparent, parent)
    _aggregate(model, parent, child)
    polyline = model.create_entity(
        "IfcPolyline",
        Points=[
            model.createIfcCartesianPoint((0.0, 0.0)),
            model.createIfcCartesianPoint((10.0, 0.0)),
        ],
    )
    axis = model.create_entity(
        "IfcShapeRepresentation",
        RepresentationIdentifier="Axis",
        RepresentationType="Curve2D",
        Items=[polyline],
    )
    grandparent.Representation = model.create_entity("IfcProductDefinitionShape", Representations=[axis])
    model = _reopen(model)
    named = {alignment.Name: alignment for alignment in model.by_type("IfcAlignment")}
    curve = ifcopenshell.api.alignment.get_basis_curve(named["C"])
    assert curve is not None
    assert curve.is_a("IfcPolyline")
    assert curve == named["G"].Representation.Representations[0].Items[0]


@pytest.mark.skipif(not IFC4X3_AVAILABLE, reason="IFC4X3 not available")
def test_add_stationing_referent_on_cycle_does_not_recurse():
    model = _mutual_cycle()
    alignment = model.by_type("IfcAlignment")[0]
    assert _follows_parent_to_self(alignment)
    referent = ifcopenshell.api.alignment.add_stationing_referent(
        model,
        name="0+000",
        alignment=alignment,
        distance_along=0.0,
        station=0.0,
    )
    assert referent.is_a("IfcReferent")
    assert referent.ObjectPlacement.is_a("IfcLocalPlacement")
