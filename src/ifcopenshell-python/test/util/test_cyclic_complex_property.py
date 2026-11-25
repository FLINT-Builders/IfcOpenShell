# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 Dion Moult <dion@thinkmoult.com>
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

"""Property and quantity walks must tolerate cyclic complex values.

A supplied IFC file can put two IfcComplexProperty entities in each other's
HasProperties list, or point an IfcComplexProperty at itself. The parser
accepts that file. get_properties, get_property, and get_quantities then
recurse with no record of entities already visited.

These tests fail while that recursion is present and pass once a repeated
entity is skipped. A depth cap that still nests the same entity again fails
the re-entry check. Dropping the whole nested list fails the sibling-value
check. An acyclic nest several levels deep must still be returned in full.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.element as element

IFCDIFF_DIR = Path(__file__).resolve().parents[3] / "ifcdiff"
if str(IFCDIFF_DIR) not in sys.path:
    sys.path.insert(0, str(IFCDIFF_DIR))

import ifcdiff

LEAF = "ok"
QUANTITY_LEAF = 1.25
SCHEMAS = ("IFC2X3", "IFC4", "IFC4X3")


def _roundtrip(model: ifcopenshell.file) -> ifcopenshell.file:
    fd, path = tempfile.mkstemp(suffix=".ifc")
    os.close(fd)
    try:
        model.write(path)
        return ifcopenshell.open(path)
    finally:
        os.remove(path)


def _label(model: ifcopenshell.file, value: str) -> ifcopenshell.entity_instance:
    return model.create_entity("IfcLabel", value)


def _complex_cycle(model: ifcopenshell.file, kind: str) -> ifcopenshell.entity_instance:
    leaf = model.create_entity("IfcPropertySingleValue", Name="Leaf", NominalValue=_label(model, LEAF))
    cycle_a = model.create_entity("IfcComplexProperty", Name="CycleA", UsageName="ua", HasProperties=[])
    if kind == "self":
        cycle_a.HasProperties = [cycle_a, leaf]
        return cycle_a
    cycle_b = model.create_entity("IfcComplexProperty", Name="CycleB", UsageName="ub", HasProperties=[])
    cycle_a.HasProperties = [cycle_b, leaf]
    cycle_b.HasProperties = [cycle_a]
    return cycle_a


def _quantity_cycle(model: ifcopenshell.file, kind: str) -> ifcopenshell.entity_instance:
    leaf = model.create_entity("IfcQuantityLength", Name="LeafQ", LengthValue=QUANTITY_LEAF)
    cycle_a = model.create_entity("IfcPhysicalComplexQuantity", Name="CycleA", Discrimination="x", HasQuantities=[])
    if kind == "self":
        cycle_a.HasQuantities = [cycle_a, leaf]
        return cycle_a
    cycle_b = model.create_entity("IfcPhysicalComplexQuantity", Name="CycleB", Discrimination="y", HasQuantities=[])
    cycle_a.HasQuantities = [cycle_b, leaf]
    cycle_b.HasQuantities = [cycle_a]
    return cycle_a


def _wall(model: ifcopenshell.file, guid: str | None = None) -> ifcopenshell.entity_instance:
    return model.create_entity("IfcWall", GlobalId=guid or ifcopenshell.guid.new(), Name="Wall")


def _assign(model: ifcopenshell.file, product, definition) -> None:
    model.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=ifcopenshell.guid.new(),
        RelatingPropertyDefinition=definition,
        RelatedObjects=[product],
    )


def _product_with_pset(schema: str, kind: str) -> tuple[ifcopenshell.file, ifcopenshell.entity_instance]:
    model = ifcopenshell.file(schema=schema)
    wall = _wall(model)
    pset = model.create_entity(
        "IfcPropertySet",
        GlobalId=ifcopenshell.guid.new(),
        Name="Pset_WallCommon",
        HasProperties=[_complex_cycle(model, kind)],
    )
    _assign(model, wall, pset)
    opened = _roundtrip(model)
    return opened, opened.by_type("IfcWall")[0]


def _assert_cycle_survived_parse(prop: ifcopenshell.entity_instance, kind: str) -> None:
    nested = prop.HasProperties
    assert any(item.is_a("IfcPropertySingleValue") and item.Name == "Leaf" for item in nested)
    if kind == "self":
        assert any(item.id() == prop.id() for item in nested)
        return
    other = next(item for item in nested if item.is_a("IfcComplexProperty"))
    assert any(item.id() == prop.id() for item in other.HasProperties)


def _assert_bounded(payload, expected) -> None:
    """The same entity id must not appear twice along one nesting path.

    Verbose results repeat an id on the wrapper and its immediate value. That
    pair is one property, not a cycle. A later repeat is a re-entry.
    """

    found = False

    def walk(node, id_path: tuple[int, ...]) -> None:
        nonlocal found
        if node == expected:
            found = True
        if isinstance(node, dict):
            next_path = id_path
            prop_id = node.get("id")
            if isinstance(prop_id, int):
                if not id_path or prop_id != id_path[-1]:
                    assert prop_id not in id_path
                    next_path = id_path + (prop_id,)
            for value in node.values():
                walk(value, next_path)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value, id_path)

    walk(payload, ())
    assert found


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("kind", ("two", "self"))
def test_parsed_file_keeps_the_cycle(schema, kind):
    model, wall = _product_with_pset(schema, kind)
    pset = model.by_type("IfcPropertySet")[0]
    assert pset.Name == "Pset_WallCommon"
    _assert_cycle_survived_parse(pset.HasProperties[0], kind)
    assert wall.is_a("IfcWall")


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("kind", ("two", "self"))
def test_get_psets_verbose_matches_bonsai_property_panel(schema, kind):
    # bonsai/bim/module/pset/data.py Data.psetqtos calls get_psets with these arguments.
    _, wall = _product_with_pset(schema, kind)
    psets = element.get_psets(wall, psets_only=True, qtos_only=False, should_inherit=False, verbose=True)
    _assert_bounded(psets, LEAF)


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("kind", ("two", "self"))
def test_get_psets_default_matches_ifcdiff(schema, kind):
    _, wall = _product_with_pset(schema, kind)
    _assert_bounded(element.get_psets(wall), LEAF)


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("kind", ("two", "self"))
def test_get_pset_and_single_property_stop_on_cycle(schema, kind):
    model, wall = _product_with_pset(schema, kind)
    _assert_bounded(element.get_pset(wall, "Pset_WallCommon"), LEAF)
    _assert_bounded(element.get_pset(wall, "Pset_WallCommon", "CycleA"), LEAF)
    pset = model.by_type("IfcPropertySet")[0]
    _assert_bounded(element.get_property_definition(pset), LEAF)
    _assert_bounded(element.get_property_definition(pset, prop="CycleA"), LEAF)
    _assert_bounded(element.get_properties(pset.HasProperties), LEAF)
    _assert_bounded(element.get_property(pset.HasProperties, "CycleA"), LEAF)


@pytest.mark.parametrize("kind", ("two", "self"))
def test_material_and_profile_properties_stop_on_cycle(kind):
    model = ifcopenshell.file(schema="IFC4")
    material = model.create_entity("IfcMaterial", Name="Concrete")
    model.create_entity(
        "IfcMaterialProperties",
        Name="Pset_MaterialCommon",
        Material=material,
        Properties=[_complex_cycle(model, kind)],
    )
    profile = model.create_entity("IfcRectangleProfileDef", ProfileType="AREA", XDim=1.0, YDim=2.0)
    model.create_entity(
        "IfcProfileProperties",
        Name="Pset_ProfileCommon",
        ProfileDefinition=profile,
        Properties=[_complex_cycle(model, kind)],
    )
    opened = _roundtrip(model)
    material = opened.by_type("IfcMaterial")[0]
    profile = opened.by_type("IfcRectangleProfileDef")[0]
    _assert_bounded(element.get_psets(material), LEAF)
    _assert_bounded(element.get_pset(material, "Pset_MaterialCommon", "CycleA"), LEAF)
    _assert_bounded(element.get_psets(profile), LEAF)
    _assert_bounded(element.get_pset(profile, "Pset_ProfileCommon", "CycleA"), LEAF)


@pytest.mark.parametrize("kind", ("two", "self"))
def test_ifc2x3_extended_material_properties_stop_on_cycle(kind):
    model = ifcopenshell.file(schema="IFC2X3")
    material = model.create_entity("IfcMaterial", Name="Concrete")
    model.create_entity(
        "IfcExtendedMaterialProperties",
        Name="Pset_MaterialCommon",
        Material=material,
        ExtendedProperties=[_complex_cycle(model, kind)],
    )
    opened = _roundtrip(model)
    material = opened.by_type("IfcMaterial")[0]
    _assert_bounded(element.get_psets(material), LEAF)
    _assert_bounded(element.get_pset(material, "Pset_MaterialCommon", "CycleA"), LEAF)


@pytest.mark.parametrize("kind", ("two", "self"))
def test_inherited_type_pset_stops_on_cycle(kind):
    model = ifcopenshell.file(schema="IFC4")
    wall = _wall(model)
    wall_type = model.create_entity(
        "IfcWallType",
        GlobalId=ifcopenshell.guid.new(),
        Name="WallType",
        PredefinedType="NOTDEFINED",
    )
    model.create_entity(
        "IfcRelDefinesByType",
        GlobalId=ifcopenshell.guid.new(),
        RelatingType=wall_type,
        RelatedObjects=[wall],
    )
    wall_type.HasPropertySets = [
        model.create_entity(
            "IfcPropertySet",
            GlobalId=ifcopenshell.guid.new(),
            Name="Pset_WallCommon",
            HasProperties=[_complex_cycle(model, kind)],
        )
    ]
    opened = _roundtrip(model)
    wall = opened.by_type("IfcWall")[0]
    _assert_bounded(element.get_psets(wall, should_inherit=True), LEAF)


@pytest.mark.parametrize("kind", ("two", "self"))
def test_physical_complex_quantity_cycle_stops(kind):
    model = ifcopenshell.file(schema="IFC4")
    wall = _wall(model)
    qset = model.create_entity(
        "IfcElementQuantity",
        GlobalId=ifcopenshell.guid.new(),
        Name="Qto_WallBaseQuantities",
        Quantities=[_quantity_cycle(model, kind)],
    )
    _assign(model, wall, qset)
    opened = _roundtrip(model)
    wall = opened.by_type("IfcWall")[0]
    qset = opened.by_type("IfcElementQuantity")[0]
    _assert_bounded(element.get_psets(wall, qtos_only=True), QUANTITY_LEAF)
    _assert_bounded(element.get_psets(wall), QUANTITY_LEAF)
    _assert_bounded(element.get_quantities(qset.Quantities), QUANTITY_LEAF)
    _assert_bounded(element.get_quantity(qset.Quantities, "CycleA"), QUANTITY_LEAF)
    _assert_bounded(element.get_property_definition(qset), QUANTITY_LEAF)


def test_acyclic_complex_property_is_fully_expanded():
    model = ifcopenshell.file(schema="IFC4")
    wall = _wall(model)
    leaf = model.create_entity("IfcPropertySingleValue", Name="Leaf", NominalValue=_label(model, "deep"))
    current = leaf
    for name in ("L3", "L2", "L1", "L0"):
        current = model.create_entity("IfcComplexProperty", Name=name, UsageName=name, HasProperties=[current])
    pset = model.create_entity(
        "IfcPropertySet",
        GlobalId=ifcopenshell.guid.new(),
        Name="Pset_WallCommon",
        HasProperties=[current],
    )
    _assign(model, wall, pset)
    opened = _roundtrip(model)
    wall = opened.by_type("IfcWall")[0]
    psets = element.get_psets(wall)
    nested = psets["Pset_WallCommon"]["L0"]["properties"]["L1"]["properties"]["L2"]["properties"]["L3"]
    assert nested["properties"]["Leaf"] == "deep"
    verbose = element.get_psets(wall, verbose=True)
    _assert_bounded(verbose, "deep")


def _cyclic_wall_file(guid: str) -> ifcopenshell.file:
    model = ifcopenshell.file(schema="IFC4")
    wall = _wall(model, guid)
    pset = model.create_entity(
        "IfcPropertySet",
        GlobalId=ifcopenshell.guid.new(),
        Name="Pset_WallCommon",
        HasProperties=[_complex_cycle(model, "two")],
    )
    _assign(model, wall, pset)
    return _roundtrip(model)


def test_ifcdiff_property_comparison_finishes_on_identical_cycles():
    guid = ifcopenshell.guid.new()
    old = _cyclic_wall_file(guid)
    new = _cyclic_wall_file(guid)
    diff = ifcdiff.IfcDiff(old, new, relationships=["property"])
    diff.diff()
    assert "properties_changed" not in diff.change_register.get(guid, {})


def test_ifcdiff_property_comparison_reports_a_cyclic_pset():
    guid = ifcopenshell.guid.new()
    old_model = ifcopenshell.file(schema="IFC4")
    _wall(old_model, guid)
    old = _roundtrip(old_model)
    new = _cyclic_wall_file(guid)
    diff = ifcdiff.IfcDiff(old, new, relationships=["property"])
    diff.diff()
    assert diff.change_register[guid]["properties_changed"]
