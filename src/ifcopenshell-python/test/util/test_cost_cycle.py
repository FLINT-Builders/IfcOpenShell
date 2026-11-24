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

# This file was generated with the assistance of an AI coding tool.

"""Cyclic cost values and nested cost items must evaluate to a finite total.

A cost value that lists itself (or a partner that lists it back) as a component,
and cost items or construction resources that nest each other, are stored and
reloaded by the IFC parser. Evaluation treats a value already on the stack as
zero and still counts every acyclic operand and nested leaf. The same contract
applies to formula serialisation and to the callers that walk the same graph.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

import ifcopenshell
import ifcopenshell.api.cost
import ifcopenshell.guid
import ifcopenshell.util.cost as cost
import ifcopenshell.util.resource as resource

_REPO_SRC = Path(__file__).resolve().parents[3]


def _bounded(fn):
    """Run fn. Unbounded recursion is a failure; a finite return value is required."""
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(250)
    try:
        try:
            return fn()
        except RecursionError as exc:
            pytest.fail(f"cost evaluation recursed without a bound: {exc}")
        except SystemError as exc:
            cause = exc.__cause__ or exc.__context__
            if isinstance(cause, RecursionError):
                pytest.fail(f"cost evaluation recursed without a bound: {exc}")
            raise
    finally:
        sys.setrecursionlimit(limit)


def _model():
    return ifcopenshell.file(schema="IFC4")


def _gid():
    return ifcopenshell.guid.new()


def _money(model, amount):
    return model.create_entity("IfcMonetaryMeasure", float(amount))


def _cost_item(model, name):
    return model.create_entity("IfcCostItem", GlobalId=_gid(), Name=name)


def _nest(model, parent, children):
    return model.create_entity(
        "IfcRelNests",
        GlobalId=_gid(),
        RelatingObject=parent,
        RelatedObjects=list(children),
    )


def _reload(model, tmp_path):
    path = tmp_path / "cycle.ifc"
    model.write(str(path))
    return ifcopenshell.open(str(path))


def _load_module(module_name, path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_bonsai_stub():
    """Import Bonsai cost modules without Blender.

    The stub only supplies the tool attributes those modules touch while
    walking a cost value. get_assigned_rate_cost_item returns None, which is
    what the real tool method returns when the item has no cost-item assignment.
    """
    bonsai = types.ModuleType("bonsai")
    bonsai.__path__ = []

    class Cost:
        @staticmethod
        def get_assigned_rate_cost_item(element):
            return None

    class Tool(types.ModuleType):
        def __getattr__(self, name):
            return type(name, (), {"BLENDER_ENUM_ITEMS": object})

    tool = Tool("bonsai.tool")
    tool.Cost = Cost
    previous = {name: sys.modules.get(name) for name in ("bonsai", "bonsai.tool", "bpy")}
    sys.modules["bonsai"] = bonsai
    sys.modules["bonsai.tool"] = tool
    sys.modules["bpy"] = types.ModuleType("bpy")
    return previous


def _restore_modules(previous):
    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def test_acyclic_component_sum_is_unchanged():
    model = _model()
    item = _cost_item(model, "Item")
    total = model.create_entity("IfcCostValue", ArithmeticOperator="ADD")
    total.Components = [
        model.create_entity("IfcCostValue", AppliedValue=_money(model, 2)),
        model.create_entity("IfcCostValue", AppliedValue=_money(model, 3)),
    ]
    item.CostValues = [total]
    assert _bounded(lambda: cost.calculate_applied_value(item, total)) == 5.0
    assert _bounded(lambda: cost.serialise_cost_value(total)) == "2.0+3.0"


def test_self_component_from_reloaded_file_contributes_zero(tmp_path):
    model = _model()
    item = _cost_item(model, "Item")
    total = model.create_entity("IfcCostValue", Name="total", ArithmeticOperator="ADD")
    leaf = model.create_entity("IfcCostValue", Name="leaf", AppliedValue=_money(model, 10))
    total.Components = [leaf, total]
    item.CostValues = [total]

    reloaded = _reload(model, tmp_path)
    item = reloaded.by_type("IfcCostItem")[0]
    total = next(value for value in item.CostValues if value.Name == "total")
    assert any(component.id() == total.id() for component in total.Components)
    assert _bounded(lambda: cost.calculate_applied_value(item, total)) == 10.0
    assert _bounded(lambda: cost.serialise_cost_value(total)) == "10.0+0"
    assert _bounded(lambda: cost.get_cost_values(item))[0]["label"] == "10.00 = 10.0+0"


def test_mutual_components_keep_acyclic_operand():
    model = _model()
    item = _cost_item(model, "Item")
    left = model.create_entity("IfcCostValue", Name="left", ArithmeticOperator="ADD")
    right = model.create_entity("IfcCostValue", Name="right", ArithmeticOperator="ADD")
    leaf = model.create_entity("IfcCostValue", AppliedValue=_money(model, 4))
    left.Components = [right]
    right.Components = [left, leaf]
    item.CostValues = [left]
    assert _bounded(lambda: cost.calculate_applied_value(item, left)) == 4.0


def test_pure_self_component_is_zero():
    model = _model()
    item = _cost_item(model, "Item")
    total = model.create_entity("IfcCostValue", ArithmeticOperator="ADD")
    total.Components = [total]
    item.CostValues = [total]
    assert _bounded(lambda: cost.calculate_applied_value(item, total)) == 0.0
    assert _bounded(lambda: cost.serialise_cost_value(total)) == "0"


def test_nested_cost_items_sum_keeps_leaf_value():
    model = _model()
    parent = _cost_item(model, "Parent")
    child = _cost_item(model, "Child")
    _nest(model, parent, [child])
    _nest(model, child, [parent])
    parent_sum = model.create_entity("IfcCostValue", Category="*")
    child_sum = model.create_entity("IfcCostValue", Category="*")
    child_leaf = model.create_entity("IfcCostValue", AppliedValue=_money(model, 5))
    parent.CostValues = [parent_sum]
    child.CostValues = [child_sum, child_leaf]
    assert _bounded(lambda: cost.calculate_applied_value(parent, parent_sum)) == 5.0
    assert _bounded(lambda: cost.sum_child_root_elements(parent)) == 5.0


def test_acyclic_nested_sum_is_unchanged():
    model = _model()
    parent = _cost_item(model, "Parent")
    child = _cost_item(model, "Child")
    _nest(model, parent, [child])
    parent_sum = model.create_entity("IfcCostValue", Category="*")
    child.CostValues = [model.create_entity("IfcCostValue", AppliedValue=_money(model, 5))]
    parent.CostValues = [parent_sum]
    assert cost.calculate_applied_value(parent, parent_sum) == 5.0


def test_category_filter_nest_cycle_keeps_unrelated_leaf():
    model = _model()
    parent = _cost_item(model, "Parent")
    cycle = _cost_item(model, "Cycle")
    leaf = _cost_item(model, "Leaf")
    _nest(model, parent, [cycle, leaf])
    _nest(model, cycle, [parent])
    parent_labour = model.create_entity("IfcCostValue", Category="Labour")
    cycle.CostValues = [model.create_entity("IfcCostValue", Category="Labour")]
    leaf.CostValues = [model.create_entity("IfcCostValue", Category="Labour", AppliedValue=_money(model, 6))]
    parent.CostValues = [parent_labour]
    assert _bounded(lambda: cost.calculate_applied_value(parent, parent_labour)) == 6.0


def test_assigned_rate_cycle_keeps_fixed_value():
    model = _model()
    parent = _cost_item(model, "Parent")
    child = _cost_item(model, "Child")
    _nest(model, parent, [child])
    model.create_entity(
        "IfcRelAssignsToControl",
        GlobalId=_gid(),
        RelatingControl=parent,
        RelatedObjects=[child],
    )
    parent_sum = model.create_entity("IfcCostValue", Category="*")
    parent_fixed = model.create_entity("IfcCostValue", AppliedValue=_money(model, 2))
    parent.CostValues = [parent_sum, parent_fixed]
    assert _bounded(lambda: cost.sum_child_root_elements(parent)) == 2.0


def test_resource_base_cost_cycle():
    model = _model()
    crew = model.create_entity("IfcLaborResource", GlobalId=_gid(), Name="Crew")
    total = model.create_entity("IfcCostValue", ArithmeticOperator="ADD")
    total.Components = [
        model.create_entity("IfcCostValue", AppliedValue=_money(model, 3)),
        total,
    ]
    crew.BaseCosts = [total]
    assert _bounded(lambda: cost.calculate_applied_value(crew, total)) == 3.0
    assert _bounded(lambda: resource.get_cost(crew)) == (3.0, None)

    member = model.create_entity("IfcLaborResource", GlobalId=_gid(), Name="Member")
    _nest(model, crew, [member])
    assert _bounded(lambda: resource.get_parent_cost(member)) == (3.0, None)


def test_resource_nest_cycle_keeps_leaf_cost():
    model = _model()
    parent = model.create_entity("IfcCrewResource", GlobalId=_gid(), Name="Parent")
    child = model.create_entity("IfcCrewResource", GlobalId=_gid(), Name="Child")
    _nest(model, parent, [child])
    _nest(model, child, [parent])
    parent_sum = model.create_entity("IfcCostValue", Category="*")
    child.BaseCosts = [
        model.create_entity("IfcCostValue", Category="*"),
        model.create_entity("IfcCostValue", AppliedValue=_money(model, 8)),
    ]
    parent.BaseCosts = [parent_sum]
    assert _bounded(lambda: cost.calculate_applied_value(parent, parent_sum)) == 8.0


def test_get_all_nested_cost_items_cycle_is_finite():
    model = _model()
    parent = _cost_item(model, "Parent")
    child = _cost_item(model, "Child")
    _nest(model, parent, [child])
    _nest(model, child, [parent])
    found = _bounded(lambda: list(cost.get_all_nested_cost_items(parent)))
    assert child in found
    assert len(found) == len(set(found))
    assert set(found) <= {parent, child}


def test_get_cost_schedule_cycle_returns_none():
    model = _model()
    parent = _cost_item(model, "Parent")
    child = _cost_item(model, "Child")
    _nest(model, parent, [child])
    _nest(model, child, [parent])
    assert _bounded(lambda: cost.get_cost_schedule(parent)) is None


def test_get_cost_schedule_finds_schedule_above_a_cycle():
    model = _model()
    schedule = model.create_entity(
        "IfcCostSchedule",
        GlobalId=_gid(),
        Name="Schedule",
        PredefinedType="BUDGET",
    )
    parent = _cost_item(model, "Parent")
    child = _cost_item(model, "Child")
    _nest(model, parent, [child])
    _nest(model, child, [parent])
    model.create_entity(
        "IfcRelAssignsToControl",
        GlobalId=_gid(),
        RelatingControl=schedule,
        RelatedObjects=[parent],
    )
    assert cost.get_cost_schedule(child) == schedule


def test_calculate_cost_item_resource_value_cycle():
    model = _model()
    item = _cost_item(model, "Item")
    crew = model.create_entity("IfcLaborResource", GlobalId=_gid(), Name="Crew")
    total = model.create_entity("IfcCostValue", ArithmeticOperator="ADD")
    total.Components = [
        model.create_entity("IfcCostValue", AppliedValue=_money(model, 3)),
        total,
    ]
    crew.BaseCosts = [total]
    model.create_entity(
        "IfcRelAssignsToControl",
        GlobalId=_gid(),
        RelatingControl=item,
        RelatedObjects=[crew],
    )
    _bounded(lambda: ifcopenshell.api.cost.calculate_cost_item_resource_value(model, cost_item=item))
    assert len(item.CostValues) == 1
    formula = item.CostValues[0]
    assert formula.ArithmeticOperator == "MULTIPLY"
    assert [component.AppliedValue.wrappedValue for component in formula.Components] == [3.0, 1.0]


def test_bonsai_load_cost_value_component_cycle():
    previous = _install_bonsai_stub()
    try:
        module = _load_module(
            "bonsai.bim.module.cost.data",
            _REPO_SRC / "bonsai" / "bonsai" / "bim" / "module" / "cost" / "data.py",
        )
    finally:
        _restore_modules(previous)
    model = _model()
    item = _cost_item(model, "Item")
    total = model.create_entity("IfcCostValue", ArithmeticOperator="ADD")
    leaf = model.create_entity("IfcCostValue", AppliedValue=_money(model, 10))
    total.Components = [leaf, total]
    item.CostValues = [total]
    module.CostSchedulesData._cost_values = {}
    data = {"CategoryValues": {}}
    _bounded(lambda: module.CostSchedulesData._load_cost_value(item, data, total))
    stored = module.CostSchedulesData._cost_values
    assert stored[total.id()]["AppliedValue"] == 10.0
    assert stored[total.id()]["Formula"] == "10.0+0"
    assert set(stored) == {total.id(), leaf.id()}


def test_bonsai_resource_cost_values_component_cycle():
    previous = _install_bonsai_stub()
    try:
        module = _load_module(
            "bonsai.bim.module.resource.data",
            _REPO_SRC / "bonsai" / "bonsai" / "bim" / "module" / "resource" / "data.py",
        )
    finally:
        _restore_modules(previous)
    model = _model()
    crew = model.create_entity("IfcLaborResource", GlobalId=_gid(), Name="Crew")
    total = model.create_entity("IfcCostValue", ArithmeticOperator="ADD")
    total.Components = [
        model.create_entity("IfcCostValue", AppliedValue=_money(model, 3)),
        total,
    ]
    crew.BaseCosts = [total]

    class _Props:
        active_resource_id = crew.id()

    class _Resource:
        @staticmethod
        def get_resource_props():
            return _Props()

    class _Ifc:
        @staticmethod
        def get():
            return model

    module.tool.Resource = _Resource
    module.tool.Ifc = _Ifc
    rows = _bounded(module.ResourceData.cost_values)
    assert rows == [{"id": total.id(), "label": "3.00 = 3.0+0"}]
