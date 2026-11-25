# This file was generated with the assistance of an AI coding tool.
"""ifc_cost must read a cost schedule whose cost items nest in a cycle.

These tests fail while expansion recurses without remembering items it has
already entered. They pass once that repeat stops, including when the caller
leaves depth unlimited or passes a very large depth.
"""

from __future__ import annotations

import inspect

import ifcopenshell
import ifcopenshell.api.cost
import ifcopenshell.api.nest
import ifcopenshell.api.owner.settings
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.unit
import pytest
from ifcmcp.core import IfcSession
from ifcmcp.server import build_server


@pytest.fixture
def tool_fns():
    server = build_server()
    return {tool.name: tool.fn for tool in server._tool_manager.list_tools()}


def _prepare() -> ifcopenshell.file:
    model = ifcopenshell.api.project.create_file()
    ifcopenshell.api.owner.settings.get_user = lambda ifc: (ifc.by_type("IfcPersonAndOrganization") or [None])[0]
    ifcopenshell.api.owner.settings.get_application = lambda ifc: (ifc.by_type("IfcApplication") or [None])[0]
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="P")
    ifcopenshell.api.unit.assign_unit(model)
    return model


def _item(model, *, schedule=None, parent=None, name: str):
    if parent is None:
        item = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=schedule)
    else:
        item = ifcopenshell.api.cost.add_cost_item(model, cost_item=parent)
    ifcopenshell.api.cost.edit_cost_item(model, cost_item=item, attributes={"Name": name})
    return item


def write_mutual_cycle(path) -> str:
    model = _prepare()
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="BoQ")
    item_a = _item(model, schedule=schedule, name="A")
    item_b = _item(model, parent=item_a, name="B")
    _item(model, parent=item_a, name="Sibling")
    ifcopenshell.api.nest.assign_object(model, related_objects=[item_a], relating_object=item_b)
    model.write(str(path))
    return str(path)


def write_self_cycle(path) -> str:
    model = _prepare()
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="BoQ")
    item = _item(model, schedule=schedule, name="Loop")
    ifcopenshell.api.nest.assign_object(model, related_objects=[item], relating_object=item)
    model.write(str(path))
    return str(path)


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

    for item in schedule["items"]:
        walk(item, set())
    assert required_names <= found


class TestSessionCostCycle:
    def test_max_depth_default_is_finite(self):
        default = inspect.signature(IfcSession.ifc_cost).parameters["max_depth"].default
        assert isinstance(default, int) and default >= 1

    def test_load_then_ifc_cost_reads_mutual_cycle(self, tmp_path):
        path = write_mutual_cycle(tmp_path / "mutual.ifc")
        before = {p.name for p in tmp_path.iterdir()}
        session = IfcSession()
        loaded = session.ifc_load(path)
        assert "IFC4" in loaded
        result = invoke(session.ifc_cost)
        assert {p.name for p in tmp_path.iterdir()} == before
        assert_listing(result, {"A", "B", "Sibling"})

    def test_explicit_none_reads_mutual_cycle(self, tmp_path):
        path = write_mutual_cycle(tmp_path / "mutual.ifc")
        session = IfcSession()
        session.ifc_load(path)
        result = invoke(lambda: session.ifc_cost(max_depth=None))
        assert_listing(result, {"A", "B", "Sibling"})

    def test_huge_max_depth_reads_mutual_cycle(self, tmp_path):
        path = write_mutual_cycle(tmp_path / "mutual.ifc")
        session = IfcSession()
        session.ifc_load(path)
        result = invoke(lambda: session.ifc_cost(max_depth=100_000))
        assert_listing(result, {"A", "B", "Sibling"})

    def test_dispatch_reads_mutual_cycle(self, tmp_path):
        path = write_mutual_cycle(tmp_path / "mutual.ifc")
        session = IfcSession()
        session.ifc_load(path)
        result = invoke(lambda: session.dispatch("ifc_cost", {}))
        assert_listing(result, {"A", "B", "Sibling"})
        deep = invoke(lambda: session.dispatch("ifc_cost", {"max_depth": 100_000}))
        assert_listing(deep, {"A", "B", "Sibling"})

    def test_self_cycle_is_listed_once(self, tmp_path):
        path = write_self_cycle(tmp_path / "self.ifc")
        session = IfcSession()
        session.ifc_load(path)
        result = invoke(lambda: session.ifc_cost(max_depth=None))
        assert_listing(result, {"Loop"})


class TestServerCostTool:
    def test_tool_default_is_finite(self, tool_fns):
        default = inspect.signature(tool_fns["ifc_cost"]).parameters["max_depth"].default
        assert isinstance(default, int) and default >= 1

    def test_tool_reads_mutual_cycle(self, tmp_path, tool_fns):
        path = write_mutual_cycle(tmp_path / "mutual.ifc")
        before = {p.name for p in tmp_path.iterdir()}
        loaded = tool_fns["ifc_load"](path)
        assert "IFC4" in loaded
        result = invoke(tool_fns["ifc_cost"])
        assert {p.name for p in tmp_path.iterdir()} == before
        assert_listing(result, {"A", "B", "Sibling"})

    def test_tool_huge_depth_reads_mutual_cycle(self, tmp_path, tool_fns):
        path = write_mutual_cycle(tmp_path / "mutual.ifc")
        tool_fns["ifc_load"](path)
        result = invoke(lambda: tool_fns["ifc_cost"](max_depth=100_000))
        assert_listing(result, {"A", "B", "Sibling"})
