# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2021 Thomas Krijnen <thomas@aecgeeks.com>
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

"""Cyclic entity graphs must not exhaust the stack during recursive get_info.

These tests fail while recursive entity export walks a reference it is already
expanding. Each case is a file a user can open. The cost-quantity case is the
graph Bonsai builds when a product is assigned to a cost item quantity and the
costing UI enables quantity editing. The ifc5d case is the graph converted when
a cost value lists itself as a component.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

# The source tree next to this file has no compiled wrapper. Keep the
# installed ifcopenshell, which is the build under test, on the import path.
_SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path[:] = [entry for entry in sys.path if Path(entry or os.getcwd()).resolve() != _SOURCE_ROOT]

import ifcopenshell
import ifcopenshell.api.cost
import ifcopenshell.api.pset
import ifcopenshell.api.root

_REPO_SRC = Path(__file__).resolve().parents[2]


def test_acyclic_placement_still_expands():
    run_scenario("acyclic_placement")


def test_self_referential_placement_get_info():
    run_scenario("placement_self")


def test_self_referential_placement_omits_identifier():
    run_scenario("placement_self_no_id")


def test_two_placement_cycle_get_info():
    run_scenario("placement_pair")


def test_python_get_info_fallback_on_placement_cycle():
    run_scenario("placement_python")


def test_cost_value_component_cycle_get_info():
    run_scenario("cost_value")


def test_cost_quantities_stop_on_product_placement_cycle():
    run_scenario("cost_quantities")


def test_ifc5d_export_stops_on_cost_value_cycle():
    run_scenario("ifc5d")


def test_cross_file_equality_stops_on_placement_cycle():
    run_scenario("equality")


def run_scenario(name: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), name],
        cwd=tempfile.gettempdir(),
        timeout=30,
        capture_output=True,
        text=True,
    )
    details = f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-4000:]}"
    assert proc.returncode == 0, f"{name} exited {proc.returncode}\n{details}"
    assert proc.stdout.strip().endswith("PASS"), f"{name} did not finish\n{details}"


def _reopen(model: ifcopenshell.file) -> ifcopenshell.file:
    handle, filename = tempfile.mkstemp(suffix=".ifc")
    os.close(handle)
    model.write(filename)
    return ifcopenshell.open(filename)


def _local_placement(model: ifcopenshell.file, coordinates: tuple[float, float, float]):
    placement = model.create_entity("IfcLocalPlacement")
    point = model.create_entity("IfcCartesianPoint", Coordinates=coordinates)
    axis = model.create_entity("IfcAxis2Placement3D", Location=point)
    placement.RelativePlacement = axis
    return placement


def _assert_reference(node, entity_id: int | None, entity_type: str, include_identifier: bool = True) -> None:
    assert isinstance(node, dict), node
    assert node.get("type") == entity_type
    if include_identifier:
        assert node.get("id") == entity_id
        assert set(node) == {"id", "type"}
    else:
        assert "id" not in node
        assert set(node) == {"type"}


def _scenario_acyclic_placement() -> None:
    model = ifcopenshell.file(schema="IFC4")
    placement = _local_placement(model, (1.0, 2.0, 3.0))
    info = placement.get_info(recursive=True)
    assert info["PlacementRelTo"] is None
    assert info["RelativePlacement"]["Location"]["Coordinates"] == (1.0, 2.0, 3.0)
    assert info["type"] == "IfcLocalPlacement"


def _scenario_placement_self() -> None:
    model = _reopen(_placement_cycle_model("self"))
    placement = model.by_type("IfcLocalPlacement")[0]
    assert placement.PlacementRelTo.id() == placement.id()
    info = placement.get_info(recursive=True)
    _assert_reference(info["PlacementRelTo"], placement.id(), "IfcLocalPlacement")
    assert info["RelativePlacement"]["type"] == "IfcAxis2Placement3D"
    assert info["RelativePlacement"]["Location"]["Coordinates"] == (0.0, 0.0, 0.0)
    assert info["id"] == placement.id()


def _scenario_placement_self_no_id() -> None:
    model = _reopen(_placement_cycle_model("self"))
    placement = model.by_type("IfcLocalPlacement")[0]
    info = placement.get_info(recursive=True, include_identifier=False)
    assert "id" not in info
    _assert_reference(info["PlacementRelTo"], None, "IfcLocalPlacement", include_identifier=False)
    assert "id" not in info["RelativePlacement"]
    assert info["RelativePlacement"]["Location"]["Coordinates"] == (0.0, 0.0, 0.0)


def _scenario_placement_pair() -> None:
    model = _reopen(_placement_cycle_model("pair"))
    first, second = model.by_type("IfcLocalPlacement")
    # Reopen preserves file order, which is creation order: first, then second.
    assert first.PlacementRelTo.id() == second.id()
    assert second.PlacementRelTo.id() == first.id()
    info = first.get_info(recursive=True)
    _assert_reference(info["PlacementRelTo"]["PlacementRelTo"], first.id(), "IfcLocalPlacement")
    assert info["PlacementRelTo"]["id"] == second.id()
    assert info["PlacementRelTo"]["RelativePlacement"]["type"] == "IfcAxis2Placement3D"
    assert "Location" in info["PlacementRelTo"]["RelativePlacement"]
    own_axis = info["RelativePlacement"]
    assert own_axis["type"] == "IfcAxis2Placement3D"
    if "Location" in own_axis:
        assert own_axis["Location"]["Coordinates"] == (0.0, 0.0, 0.0)
    else:
        _assert_reference(own_axis, second.RelativePlacement.id(), "IfcAxis2Placement3D")


def _scenario_placement_python() -> None:
    model = _reopen(_placement_cycle_model("self"))
    placement = model.by_type("IfcLocalPlacement")[0]
    # A non-empty ignore list is the pure Python recursive implementation.
    info = placement.get_info(recursive=True, ignore=["Description"])
    _assert_reference(info["PlacementRelTo"], placement.id(), "IfcLocalPlacement")
    assert info["RelativePlacement"]["Location"]["Coordinates"] == (0.0, 0.0, 0.0)


def _scenario_cost_value() -> None:
    model = _reopen(_cost_value_cycle_model())
    item = model.by_type("IfcCostItem")[0]
    value = item.CostValues[0]
    assert [component.id() for component in value.Components] == [value.id()]
    info = item.get_info(recursive=True)
    expanded = info["CostValues"][0]
    assert expanded["id"] == value.id()
    assert expanded["Name"] == "Labour"
    assert expanded["ArithmeticOperator"] == "ADD"
    _assert_reference(expanded["Components"][0], value.id(), "IfcCostValue")


def _scenario_cost_quantities() -> None:
    model = _reopen(_product_quantity_model())
    item = model.by_type("IfcCostItem")[0]
    wall = model.by_type("IfcWall")[0]
    assert wall.ObjectPlacement.PlacementRelTo.id() == wall.ObjectPlacement.id()
    cost = _load_cost_class()
    cost.Ifc.file = model
    results = cost.Cost.get_cost_quantities(item)
    assert len(results["quantities"]) == 1
    product = results["quantities"][0]["fromProduct"]
    assert product["id"] == wall.id()
    assert product["type"] == "IfcWall"
    placement = product["ObjectPlacement"]
    assert placement["id"] == wall.ObjectPlacement.id()
    _assert_reference(placement["PlacementRelTo"], wall.ObjectPlacement.id(), "IfcLocalPlacement")
    assert placement["RelativePlacement"]["type"] == "IfcAxis2Placement3D"


def _scenario_ifc5d() -> None:
    sys.path.insert(0, str(_REPO_SRC / "ifc5d"))
    from ifc5d.ifc2json import ifc5D2json

    model = _reopen(_cost_value_cycle_model())
    value = model.by_type("IfcCostValue")[0]
    converter = ifc5D2json()
    converter.file_path = model
    converter.cost_schedule = model.by_type("IfcCostSchedule")[0]
    data = converter.convert_ifc_to_json()
    assert len(data) == 1
    expanded = data[0]["cost_items"][0]["CostValues"][0]
    assert expanded["id"] == value.id()
    _assert_reference(expanded["Components"][0], value.id(), "IfcCostValue")


def _scenario_equality() -> None:
    left = _reopen(_placement_cycle_model("self", (0.0, 0.0, 0.0)))
    right = _reopen(_placement_cycle_model("self", (0.0, 0.0, 0.0)))
    other = _reopen(_placement_cycle_model("self", (4.0, 0.0, 0.0)))
    assert left.by_type("IfcLocalPlacement")[0] == right.by_type("IfcLocalPlacement")[0]
    assert left.by_type("IfcLocalPlacement")[0] != other.by_type("IfcLocalPlacement")[0]


def _placement_cycle_model(kind: str, coordinates: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> ifcopenshell.file:
    model = ifcopenshell.file(schema="IFC4")
    if kind == "self":
        placement = _local_placement(model, coordinates)
        placement.PlacementRelTo = placement
        return model
    first = _local_placement(model, coordinates)
    second = _local_placement(model, coordinates)
    first.PlacementRelTo = second
    second.PlacementRelTo = first
    return model


def _product_quantity_model() -> ifcopenshell.file:
    model = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject")
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Cyclic wall")
    placement = _local_placement(model, (0.0, 0.0, 0.0))
    placement.PlacementRelTo = placement
    wall.ObjectPlacement = placement
    qto = ifcopenshell.api.pset.add_qto(model, product=wall, name="Qto_WallBaseQuantities")
    ifcopenshell.api.pset.edit_qto(model, qto=qto, properties={"Length": 2.0})
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="Schedule")
    item = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=schedule)
    ifcopenshell.api.cost.assign_cost_item_quantity(model, cost_item=item, products=[wall], prop_name="Length")
    return model


def _cost_value_cycle_model() -> ifcopenshell.file:
    model = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject")
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="Schedule")
    item = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=schedule)
    value = ifcopenshell.api.cost.add_cost_value(model, parent=item)
    value.Name = "Labour"
    value.ArithmeticOperator = "ADD"
    value.Components = [value]
    return model


def _load_cost_class():
    """Load bonsai.tool.cost.Cost without Blender.

    bpy is not on the path from the opened IFC file to get_info. The quantity
    export itself is the real Cost.get_cost_quantities method.
    """

    root = _REPO_SRC / "bonsai" / "bonsai"
    package = types.ModuleType("bonsai")
    package.__path__ = [str(root)]
    package.__package__ = "bonsai"
    sys.modules["bonsai"] = package
    core = types.ModuleType("bonsai.core")
    core.__path__ = [str(root / "core")]
    core.__package__ = "bonsai.core"
    sys.modules["bonsai.core"] = core
    package.core = core
    importlib.import_module("bonsai.core.tool")

    for name in ("aud", "bpy", "bonsai.bim", "bonsai.bim.helper", "bonsai.tool"):
        module = types.ModuleType(name)
        module.__package__ = name
        sys.modules[name] = module
    package.bim = sys.modules["bonsai.bim"]
    package.tool = sys.modules["bonsai.tool"]
    sys.modules["bonsai.bim"].helper = sys.modules["bonsai.bim.helper"]

    class Ifc:
        file = None

        @staticmethod
        def get():
            return Ifc.file

    sys.modules["bonsai.tool"].Ifc = Ifc
    spec = importlib.util.spec_from_file_location("bonsai.tool.cost", root / "tool" / "cost.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["bonsai.tool.cost"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.Ifc = Ifc
    return module


_SCENARIOS = {
    "acyclic_placement": _scenario_acyclic_placement,
    "placement_self": _scenario_placement_self,
    "placement_self_no_id": _scenario_placement_self_no_id,
    "placement_pair": _scenario_placement_pair,
    "placement_python": _scenario_placement_python,
    "cost_value": _scenario_cost_value,
    "cost_quantities": _scenario_cost_quantities,
    "ifc5d": _scenario_ifc5d,
    "equality": _scenario_equality,
}


if __name__ == "__main__":
    _SCENARIOS[sys.argv[1]]()
    print("PASS")
