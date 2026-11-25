# This file was generated with the assistance of an AI coding tool.
"""Schedule and cost queries must not recurse forever on a cyclic nest.

These tests fail while a repeated task or cost item is expanded again, and
while the default depth is unlimited. A repeated item is a leaf: it is
present, with the same id, and its children are an empty list. The default
depth is finite, so a chain longer than the interpreter recursion limit is
cut with the existing truncation marker.
"""

from __future__ import annotations

import json
import subprocess
import sys

import ifcopenshell
import ifcopenshell.guid
import pytest

from ifcquery.cost import cost
from ifcquery.schedule import schedule


def _guid() -> str:
    return ifcopenshell.guid.new()


def _reopen(model: ifcopenshell.file, path) -> ifcopenshell.file:
    model.write(str(path))
    return ifcopenshell.open(str(path))


def _nest(model: ifcopenshell.file, parent, children) -> None:
    model.create_entity(
        "IfcRelNests",
        GlobalId=_guid(),
        RelatingObject=parent,
        RelatedObjects=list(children),
    )


def _assign(model: ifcopenshell.file, control, objects) -> None:
    model.create_entity(
        "IfcRelAssignsToControl",
        GlobalId=_guid(),
        RelatingControl=control,
        RelatedObjects=list(objects),
    )


def _chain(model: ifcopenshell.file, ifc_class: str, length: int):
    items = [model.create_entity(ifc_class, GlobalId=_guid(), Name=f"T{i}") for i in range(length)]
    for parent, child in zip(items, items[1:]):
        _nest(model, parent, [child])
    return items[0]


def _cyclic_items(model: ifcopenshell.file, ifc_class: str, names: list[str]):
    """`names` is the walk, with the last name repeating an earlier item."""
    items = {}
    for name in names[:-1]:
        items.setdefault(name, model.create_entity(ifc_class, GlobalId=_guid(), Name=name))
    for parent_name, child_name in zip(names[:-1], names[1:]):
        _nest(model, items[parent_name], [items[child_name]])
    return items[names[0]]


def cyclic_schedule(schema: str, names: list[str]) -> ifcopenshell.file:
    model = ifcopenshell.file(schema=schema)
    root = _cyclic_items(model, "IfcTask", names)
    schedule_entity = model.create_entity("IfcWorkSchedule", GlobalId=_guid(), Name="Programme")
    _assign(model, schedule_entity, [root])
    return model


def chain_schedule(schema: str, length: int) -> ifcopenshell.file:
    model = ifcopenshell.file(schema=schema)
    root = _chain(model, "IfcTask", length)
    schedule_entity = model.create_entity("IfcWorkSchedule", GlobalId=_guid(), Name="Programme")
    _assign(model, schedule_entity, [root])
    return model


def cyclic_cost(schema: str, names: list[str]) -> ifcopenshell.file:
    model = ifcopenshell.file(schema=schema)
    root = _cyclic_items(model, "IfcCostItem", names)
    schedule_entity = model.create_entity("IfcCostSchedule", GlobalId=_guid(), Name="BoQ")
    _assign(model, schedule_entity, [root])
    return model


def chain_cost(schema: str, length: int) -> ifcopenshell.file:
    model = ifcopenshell.file(schema=schema)
    root = _chain(model, "IfcCostItem", length)
    schedule_entity = model.create_entity("IfcCostSchedule", GlobalId=_guid(), Name="BoQ")
    _assign(model, schedule_entity, [root])
    return model


def schedule_with_later_straight_tree(schema: str = "IFC4") -> ifcopenshell.file:
    model = cyclic_schedule(schema, ["A", "B", "A"])
    parent = model.create_entity("IfcTask", GlobalId=_guid(), Name="Parent")
    child = model.create_entity("IfcTask", GlobalId=_guid(), Name="Child")
    _nest(model, parent, [child])
    straight = model.create_entity("IfcWorkSchedule", GlobalId=_guid(), Name="Straight")
    _assign(model, straight, [parent])
    return model


def assert_cycle_leaf(roots, child_key: str, names: list[str]) -> None:
    current = roots
    first_id: dict[str, int] = {}
    for index, name in enumerate(names):
        node = next(item for item in current if item["name"] == name)
        first_id.setdefault(name, node["id"])
        children = node[child_key]
        if index == len(names) - 1:
            assert node["id"] == first_id[name]
            assert children == []
            if child_key == "subtasks":
                assert node["outputs"] == []
                assert node["is_milestone"] is False
                assert node["start"] is None
                assert node["finish"] is None
            else:
                assert node["values"] == []
            return
        assert isinstance(children, list) and children
        current = children


def assert_truncated(roots, child_key: str, chain_length: int) -> None:
    depth = 0
    truncated = False

    def walk(nodes, level: int) -> None:
        nonlocal depth, truncated
        for node in nodes:
            depth = max(depth, level)
            children = node[child_key]
            if isinstance(children, dict):
                assert children["truncated"] is True
                assert children["count"] == 1
                truncated = True
            elif children:
                assert isinstance(children, list)
                walk(children, level + 1)

    walk(roots, 1)
    assert truncated
    assert depth < chain_length
    assert depth < sys.getrecursionlimit()


def assert_no_reexpansion(roots, child_key: str) -> None:
    expanded: set[int] = set()

    def walk(nodes) -> None:
        for node in nodes:
            children = node[child_key]
            if isinstance(children, dict):
                assert children["truncated"] is True
                continue
            assert isinstance(children, list)
            if not children:
                continue
            assert node["id"] not in expanded
            expanded.add(node["id"])
            walk(children)

    walk(roots)


def run_ifcquery(*args: str):
    result = subprocess.run(
        [sys.executable, "-m", "ifcquery", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


CYCLE_SHAPES = [
    ["A", "B", "A"],
    ["A", "A"],
    ["A", "B", "C", "A"],
]
SCHEMAS = ["IFC4", "IFC4X3"]


class TestScheduleCycles:
    @pytest.mark.parametrize("schema", SCHEMAS)
    @pytest.mark.parametrize("names", CYCLE_SHAPES)
    def test_unlimited_depth_treats_repeat_as_leaf(self, tmp_path, schema, names):
        model = _reopen(cyclic_schedule(schema, names), tmp_path / "cycle.ifc")
        result = schedule(model, max_depth=None)
        assert len(result) == 1
        assert result[0]["name"] == "Programme"
        assert_cycle_leaf(result[0]["tasks"], "subtasks", names)

    @pytest.mark.parametrize("schema", SCHEMAS)
    def test_task_nested_with_itself_and_a_sibling_is_a_leaf(self, tmp_path, schema):
        model = ifcopenshell.file(schema=schema)
        task_a = model.create_entity("IfcTask", GlobalId=_guid(), Name="A")
        task_b = model.create_entity("IfcTask", GlobalId=_guid(), Name="B")
        _nest(model, task_a, [task_b, task_a])
        work = model.create_entity("IfcWorkSchedule", GlobalId=_guid(), Name="Programme")
        _assign(model, work, [task_a])
        opened = _reopen(model, tmp_path / "fan.ifc")

        result = schedule(opened, max_depth=None)
        subtasks = result[0]["tasks"][0]["subtasks"]
        assert [item["name"] for item in subtasks] == ["B", "A"]
        assert subtasks[0]["subtasks"] == []
        assert subtasks[1]["id"] == result[0]["tasks"][0]["id"]
        assert subtasks[1]["subtasks"] == []

    def test_later_schedule_is_still_listed(self, tmp_path):
        model = _reopen(schedule_with_later_straight_tree(), tmp_path / "two.ifc")
        result = schedule(model, max_depth=None)
        assert [item["name"] for item in result] == ["Programme", "Straight"]
        assert_cycle_leaf(result[0]["tasks"], "subtasks", ["A", "B", "A"])
        parent = result[1]["tasks"][0]
        assert parent["name"] == "Parent"
        assert parent["subtasks"][0]["name"] == "Child"
        assert parent["subtasks"][0]["subtasks"] == []

    def test_default_depth_truncates_long_chain(self, tmp_path):
        length = sys.getrecursionlimit() + 30
        model = _reopen(chain_schedule("IFC4", length), tmp_path / "chain.ifc")
        result = schedule(model)
        assert_truncated(result[0]["tasks"], "subtasks", length)
        assert_no_reexpansion(result[0]["tasks"], "subtasks")

    def test_cli_large_depth_treats_repeat_as_leaf(self, tmp_path):
        path = tmp_path / "cycle.ifc"
        cyclic_schedule("IFC4", ["A", "B", "A"]).write(str(path))
        rc, stdout, stderr = run_ifcquery(str(path), "schedule", "--depth", "10000")
        assert rc == 0, stderr
        result = json.loads(stdout)
        assert_cycle_leaf(result[0]["tasks"], "subtasks", ["A", "B", "A"])

    def test_cli_default_depth_truncates_long_chain(self, tmp_path):
        length = sys.getrecursionlimit() + 30
        path = tmp_path / "chain.ifc"
        chain_schedule("IFC4", length).write(str(path))
        rc, stdout, stderr = run_ifcquery(str(path), "schedule")
        assert rc == 0, stderr
        result = json.loads(stdout)
        assert_truncated(result[0]["tasks"], "subtasks", length)


class TestCostCycles:
    @pytest.mark.parametrize("schema", SCHEMAS)
    @pytest.mark.parametrize("names", CYCLE_SHAPES)
    def test_unlimited_depth_treats_repeat_as_leaf(self, tmp_path, schema, names):
        model = _reopen(cyclic_cost(schema, names), tmp_path / "cycle.ifc")
        result = cost(model, max_depth=None)
        assert len(result) == 1
        assert result[0]["name"] == "BoQ"
        assert_cycle_leaf(result[0]["items"], "subitems", names)

    def test_default_depth_truncates_long_chain(self, tmp_path):
        length = sys.getrecursionlimit() + 30
        model = _reopen(chain_cost("IFC4", length), tmp_path / "chain.ifc")
        result = cost(model)
        assert_truncated(result[0]["items"], "subitems", length)
        assert_no_reexpansion(result[0]["items"], "subitems")

    def test_cli_large_depth_treats_repeat_as_leaf(self, tmp_path):
        path = tmp_path / "cycle.ifc"
        cyclic_cost("IFC4", ["A", "B", "A"]).write(str(path))
        rc, stdout, stderr = run_ifcquery(str(path), "cost", "--depth", "10000")
        assert rc == 0, stderr
        result = json.loads(stdout)
        assert_cycle_leaf(result[0]["items"], "subitems", ["A", "B", "A"])

    def test_cli_default_depth_truncates_long_chain(self, tmp_path):
        length = sys.getrecursionlimit() + 30
        path = tmp_path / "chain.ifc"
        chain_cost("IFC4", length).write(str(path))
        rc, stdout, stderr = run_ifcquery(str(path), "cost")
        assert rc == 0, stderr
        result = json.loads(stdout)
        assert_truncated(result[0]["items"], "subitems", length)
