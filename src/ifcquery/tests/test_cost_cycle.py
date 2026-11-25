# This file was generated with the assistance of an AI coding tool.
"""Cyclic IfcCostItem nests must not exhaust the stack when a cost schedule is read.

These tests fail while the query walks IsNestedBy forever. They pass once a
repeat is not expanded again, including when depth is left unlimited.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys

import ifcopenshell
import ifcopenshell.api.cost
import ifcopenshell.api.nest
import ifcopenshell.api.owner.settings
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.unit
import ifcopenshell.guid
import pytest
from ifcquery.cost import cost


def _prepare(schema: str) -> ifcopenshell.file:
    model = ifcopenshell.api.project.create_file(schema)
    ifcopenshell.api.owner.settings.get_user = lambda ifc: (ifc.by_type("IfcPersonAndOrganization") or [None])[0]
    ifcopenshell.api.owner.settings.get_application = lambda ifc: (ifc.by_type("IfcApplication") or [None])[0]
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="P")
    ifcopenshell.api.unit.assign_unit(model)
    return model


def _item(model, *, schedule=None, parent=None, name: str, identification: str | None = None):
    if parent is None:
        item = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=schedule)
    else:
        item = ifcopenshell.api.cost.add_cost_item(model, cost_item=parent)
    attributes = {"Name": name}
    if identification is not None:
        attributes["Identification"] = identification
    ifcopenshell.api.cost.edit_cost_item(model, cost_item=item, attributes=attributes)
    return item


def _write(model, path) -> str:
    model.write(str(path))
    return str(path)


def write_mutual_cycle(path, schema: str = "IFC4") -> str:
    """A and B nest each other. A also has an ordinary child, Sibling."""
    model = _prepare(schema)
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="BoQ")
    item_a = _item(model, schedule=schedule, name="A", identification="A")
    item_b = _item(model, parent=item_a, name="B", identification="B")
    _item(model, parent=item_a, name="Sibling", identification="S")
    ifcopenshell.api.nest.assign_object(model, related_objects=[item_a], relating_object=item_b)
    return _write(model, path)


def write_self_cycle(path, schema: str = "IFC4") -> str:
    model = _prepare(schema)
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="BoQ")
    item = _item(model, schedule=schedule, name="Loop", identification="L")
    ifcopenshell.api.nest.assign_object(model, related_objects=[item], relating_object=item)
    return _write(model, path)


def write_three_cycle(path, schema: str = "IFC4") -> str:
    model = _prepare(schema)
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="BoQ")
    item_a = _item(model, schedule=schedule, name="A", identification="A")
    item_b = _item(model, parent=item_a, name="B", identification="B")
    item_c = _item(model, parent=item_b, name="C", identification="C")
    ifcopenshell.api.nest.assign_object(model, related_objects=[item_a], relating_object=item_c)
    return _write(model, path)


def write_shared_child_cycle(path, schema: str = "IFC4") -> str:
    """B and C both nest D, and D nests A, so the cycle is not a single edge."""
    model = _prepare(schema)
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="BoQ")
    item_a = _item(model, schedule=schedule, name="A", identification="A")
    item_b = _item(model, parent=item_a, name="B", identification="B")
    item_c = _item(model, parent=item_a, name="C", identification="C")
    item_d = _item(model, parent=item_b, name="D", identification="D")
    model.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[item_d],
        RelatingObject=item_c,
    )
    ifcopenshell.api.nest.assign_object(model, related_objects=[item_a], relating_object=item_d)
    return _write(model, path)


def load(path) -> ifcopenshell.file:
    return ifcopenshell.open(path)


def invoke(func):
    try:
        return func()
    except RecursionError as exc:
        pytest.fail(f"cyclic nested cost items exhausted the stack: {exc}")


def assert_listing(result, required_names: set[str]) -> None:
    assert isinstance(result, list) and len(result) == 1
    schedule = result[0]
    assert schedule["name"] == "BoQ"
    found: set[str] = set()

    def walk(node: dict, ancestors: set[int]) -> None:
        assert isinstance(node, dict)
        node_id = node["id"]
        assert isinstance(node_id, int)
        assert node_id not in ancestors
        found.add(node["name"])
        subitems = node["subitems"]
        if isinstance(subitems, dict):
            assert subitems.get("truncated") is True
            assert isinstance(subitems.get("count"), int) and subitems["count"] >= 0
            return
        assert isinstance(subitems, list)
        for child in subitems:
            walk(child, ancestors | {node_id})

    assert isinstance(schedule["items"], list) and schedule["items"]
    for item in schedule["items"]:
        walk(item, set())
    assert required_names <= found


def run_cli(ifc_path: str, *args: str, cwd: str):
    return subprocess.run(
        [sys.executable, "-m", "ifcquery", ifc_path, "cost", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=20,
        check=False,
    )


@pytest.mark.parametrize("schema", ["IFC4", "IFC4X3"])
class TestCyclicCostQuery:
    def test_default_call_reads_mutual_cycle(self, tmp_path, schema):
        path = write_mutual_cycle(tmp_path / "mutual.ifc", schema)
        before = {p.name for p in tmp_path.iterdir()}
        result = invoke(lambda: cost(load(path)))
        assert {p.name for p in tmp_path.iterdir()} == before
        assert_listing(result, {"A", "B", "Sibling"})

    def test_explicit_none_reads_mutual_cycle(self, tmp_path, schema):
        path = write_mutual_cycle(tmp_path / "mutual.ifc", schema)
        result = invoke(lambda: cost(load(path), max_depth=None))
        assert_listing(result, {"A", "B", "Sibling"})

    def test_huge_max_depth_reads_mutual_cycle(self, tmp_path, schema):
        path = write_mutual_cycle(tmp_path / "mutual.ifc", schema)
        result = invoke(lambda: cost(load(path), max_depth=100_000))
        assert_listing(result, {"A", "B", "Sibling"})

    def test_self_cycle_is_listed_once(self, tmp_path, schema):
        path = write_self_cycle(tmp_path / "self.ifc", schema)
        result = invoke(lambda: cost(load(path), max_depth=None))
        assert_listing(result, {"Loop"})
        assert result[0]["items"][0]["name"] == "Loop"

    def test_three_item_cycle_is_listed(self, tmp_path, schema):
        path = write_three_cycle(tmp_path / "three.ifc", schema)
        result = invoke(lambda: cost(load(path), max_depth=None))
        assert_listing(result, {"A", "B", "C"})

    def test_shared_child_cycle_is_listed(self, tmp_path, schema):
        path = write_shared_child_cycle(tmp_path / "shared.ifc", schema)
        result = invoke(lambda: cost(load(path), max_depth=None))
        assert_listing(result, {"A", "B", "C", "D"})


class TestCostDepthDefault:
    def test_max_depth_default_is_finite(self):
        default = inspect.signature(cost).parameters["max_depth"].default
        assert isinstance(default, int) and default >= 1


class TestCyclicCostCli:
    def test_cli_without_depth_reads_mutual_cycle(self, tmp_path):
        ifc_path = write_mutual_cycle(tmp_path / "mutual.ifc")
        before = {p.name for p in tmp_path.iterdir()}
        proc = run_cli(ifc_path, cwd=str(tmp_path))
        assert {p.name for p in tmp_path.iterdir()} == before
        assert proc.returncode == 0, proc.stderr
        assert_listing(json.loads(proc.stdout), {"A", "B", "Sibling"})

    def test_cli_huge_depth_reads_mutual_cycle(self, tmp_path):
        ifc_path = write_mutual_cycle(tmp_path / "mutual.ifc")
        before = {p.name for p in tmp_path.iterdir()}
        proc = run_cli(ifc_path, "--depth", "100000", cwd=str(tmp_path))
        assert {p.name for p in tmp_path.iterdir()} == before
        assert proc.returncode == 0, proc.stderr
        assert_listing(json.loads(proc.stdout), {"A", "B", "Sibling"})

    def test_cli_self_cycle(self, tmp_path):
        ifc_path = write_self_cycle(tmp_path / "self.ifc")
        proc = run_cli(ifc_path, cwd=str(tmp_path))
        assert proc.returncode == 0, proc.stderr
        assert_listing(json.loads(proc.stdout), {"Loop"})
