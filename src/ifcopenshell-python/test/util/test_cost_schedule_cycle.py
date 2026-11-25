# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
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

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

# The source tree has no compiled wrapper. Import the installed package, then
# overlay the repository modules under test.
_LOCAL_PACKAGE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path[:] = [entry for entry in sys.path if os.path.abspath(entry or ".") != _LOCAL_PACKAGE_ROOT]

import pytest

import ifcopenshell
import ifcopenshell.util

REPO_ROOT = Path(__file__).resolve().parents[4]
COST_SOURCE = REPO_ROOT / "src" / "ifcopenshell-python" / "ifcopenshell" / "util" / "cost.py"
IFC2JSON_SOURCE = REPO_ROOT / "src" / "ifc5d" / "ifc5d" / "ifc2json.py"


def _load_source_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Load the repository copies so a fix in this tree is what these tests run.
cost = _load_source_module("ifcopenshell.util.cost", COST_SOURCE)
ifcopenshell.util.cost = cost
ifc2json = _load_source_module("ifc5d.ifc2json", IFC2JSON_SOURCE)


def _reopen(model: ifcopenshell.file) -> ifcopenshell.file:
    handle, path = tempfile.mkstemp(suffix=".ifc")
    os.close(handle)
    try:
        model.write(path)
        return ifcopenshell.open(path)
    finally:
        os.unlink(path)


def _item(model: ifcopenshell.file, name: str) -> ifcopenshell.entity_instance:
    return next(item for item in model.by_type("IfcCostItem") if item.Name == name)


def _mutual_cost_items(schema: str) -> ifcopenshell.file:
    """Two cost items, each the IfcRelNests parent of the other, and no schedule assignment."""
    model = ifcopenshell.file(schema=schema)
    model.create_entity("IfcCostSchedule", Name="Unused", PredefinedType="BUDGET")
    item_a = model.create_entity("IfcCostItem", Name="A")
    item_b = model.create_entity("IfcCostItem", Name="B")
    model.create_entity("IfcRelNests", RelatingObject=item_a, RelatedObjects=[item_b])
    model.create_entity("IfcRelNests", RelatingObject=item_b, RelatedObjects=[item_a])
    return _reopen(model)


def _assert_mutual_parents(item_a, item_b) -> None:
    assert any(rel.RelatingObject == item_b for rel in item_a.Nests or [])
    assert any(rel.RelatingObject == item_a for rel in item_b.Nests or [])


def _schedule_with_nested_cycle(schema: str) -> ifcopenshell.file:
    """A real schedule whose nested items parent each other."""
    model = ifcopenshell.file(schema=schema)
    schedule = model.create_entity("IfcCostSchedule", Name="Budget", PredefinedType="BUDGET")
    root = model.create_entity("IfcCostItem", Name="root")
    item_a = model.create_entity("IfcCostItem", Name="A")
    item_b = model.create_entity("IfcCostItem", Name="B")
    model.create_entity("IfcRelAssignsToControl", RelatingControl=schedule, RelatedObjects=[root])
    model.create_entity("IfcRelNests", RelatingObject=item_a, RelatedObjects=[item_b])
    model.create_entity("IfcRelNests", RelatingObject=item_b, RelatedObjects=[item_a])
    model.create_entity("IfcRelNests", RelatingObject=root, RelatedObjects=[item_a])
    return _reopen(model)


def _walk_json_names(nodes) -> list[str]:
    names = []
    for node in nodes or []:
        names.append(node["Name"])
        names.extend(_walk_json_names(node.get("IsNestedBy")))
    return names


@pytest.mark.parametrize("schema", ["IFC4", "IFC4X3"])
def test_cyclic_parents_resolve_without_recursion(schema):
    model = _mutual_cost_items(schema)
    item_a = _item(model, "A")
    item_b = _item(model, "B")
    _assert_mutual_parents(item_a, item_b)

    # CostSchedulesData.cost_items asks for the parent schedule of every IfcCostItem.
    for item in model.by_type("IfcCostItem"):
        assert cost.get_cost_schedule(item) is None
        assert cost.get_cost_rate(model, item) is None


def test_self_nested_cost_item_resolves_without_recursion():
    model = ifcopenshell.file(schema="IFC4")
    item = model.create_entity("IfcCostItem", Name="A")
    model.create_entity("IfcRelNests", RelatingObject=item, RelatedObjects=[item])
    model = _reopen(model)
    item = _item(model, "A")
    assert any(rel.RelatingObject == item for rel in item.Nests or [])
    assert cost.get_cost_schedule(item) is None


def test_acyclic_nest_still_returns_its_schedule():
    model = ifcopenshell.file(schema="IFC4")
    schedule = model.create_entity("IfcCostSchedule", Name="Budget", PredefinedType="BUDGET")
    root = model.create_entity("IfcCostItem", Name="root")
    child = model.create_entity("IfcCostItem", Name="child")
    model.create_entity("IfcRelAssignsToControl", RelatingControl=schedule, RelatedObjects=[root])
    model.create_entity("IfcRelNests", RelatingObject=root, RelatedObjects=[child])
    model = _reopen(model)
    assert cost.get_cost_schedule(_item(model, "child")).Name == "Budget"
    assert cost.get_cost_schedule(_item(model, "root")).Name == "Budget"


def test_two_level_nest_still_returns_its_schedule():
    model = ifcopenshell.file(schema="IFC4")
    schedule = model.create_entity("IfcCostSchedule", Name="Budget", PredefinedType="BUDGET")
    root = model.create_entity("IfcCostItem", Name="root")
    item_a = model.create_entity("IfcCostItem", Name="A")
    child = model.create_entity("IfcCostItem", Name="child")
    model.create_entity("IfcRelAssignsToControl", RelatingControl=schedule, RelatedObjects=[root])
    model.create_entity("IfcRelNests", RelatingObject=root, RelatedObjects=[item_a])
    model.create_entity("IfcRelNests", RelatingObject=item_a, RelatedObjects=[child])
    model = _reopen(model)
    assert cost.get_cost_schedule(_item(model, "child")).Name == "Budget"


@pytest.mark.parametrize("schema", ["IFC4", "IFC4X3"])
def test_cycle_whose_first_parent_is_not_the_schedule_does_not_recurse(schema):
    model = _schedule_with_nested_cycle(schema)
    item_a = _item(model, "A")
    # The back-edge to B is stored before the nest under root.
    assert [rel.RelatingObject.Name for rel in item_a.Nests] == ["B", "root"]
    found = cost.get_cost_schedule(item_a)
    assert found is None or found.is_a("IfcCostSchedule")
    assert cost.get_cost_rate(model, item_a) is None


@pytest.mark.parametrize("schema", ["IFC4", "IFC4X3"])
def test_nested_cycle_is_enumerated_once(schema):
    model = _schedule_with_nested_cycle(schema)
    schedule = model.by_type("IfcCostSchedule")[0]
    root = _item(model, "root")
    names = [item.Name for item in cost.get_schedule_cost_items(schedule)]
    assert names[0] == "root"
    assert set(names) == {"root", "A", "B"}
    assert len(names) == len(set(names))

    nested = [item.Name for item in cost.get_all_nested_cost_items(root)]
    assert set(nested) == {"A", "B"}
    assert len(nested) == len(set(nested))
    assert cost.get_nested_cost_items(root, is_deep=True)
    assert cost.get_cost_item_assignments(root, filter_by_type="PRODUCT", is_deep=True) == []


@pytest.mark.parametrize("schema", ["IFC4", "IFC4X3"])
def test_costing_json_load_survives_nested_cycle(schema):
    model = _schedule_with_nested_cycle(schema)
    schedule = model.by_type("IfcCostSchedule")[0]
    converter = ifc2json.ifc5D2json()
    converter.file_path = model
    converter.cost_schedule = schedule
    data = converter.convert_ifc_to_json()
    names = _walk_json_names(data[0]["cost_items"])
    assert set(names) == {"root", "A", "B"}
    assert len(names) == len(set(names))


def test_sum_cost_value_on_a_cycle_is_finite():
    model = ifcopenshell.file(schema="IFC4")
    item_a = model.create_entity("IfcCostItem", Name="A")
    item_b = model.create_entity("IfcCostItem", Name="B")
    model.create_entity("IfcRelNests", RelatingObject=item_a, RelatedObjects=[item_b])
    model.create_entity("IfcRelNests", RelatingObject=item_b, RelatedObjects=[item_a])
    value_a = model.create_entity("IfcCostValue", Category="*")
    value_b = model.create_entity("IfcCostValue", Category="*")
    item_a.CostValues = [value_a]
    item_b.CostValues = [value_b]
    model = _reopen(model)
    item_a = _item(model, "A")
    value_a = item_a.CostValues[0]
    assert cost.calculate_applied_value(item_a, value_a) == 0.0
