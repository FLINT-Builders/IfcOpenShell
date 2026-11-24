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

"""ifc5d cost export must finish when a schedule contains a cost cycle."""

import sys

import ifcopenshell
import ifcopenshell.guid
import pytest

import ifc5d.ifc2json
import ifc5d.ifc5Dspreadsheet as spreadsheet


def _bounded(fn):
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


def _component_cycle():
    model = ifcopenshell.file(schema="IFC4")
    item = model.create_entity("IfcCostItem", GlobalId=ifcopenshell.guid.new(), Name="Item")
    total = model.create_entity("IfcCostValue", Name="total", ArithmeticOperator="ADD")
    leaf = model.create_entity(
        "IfcCostValue", Name="leaf", AppliedValue=model.create_entity("IfcMonetaryMeasure", 10.0)
    )
    total.Components = [leaf, total]
    item.CostValues = [total]
    return item, total, leaf


def test_get_cost_item_values_component_cycle():
    item, _total, _leaf = _component_cycle()
    values = _bounded(lambda: spreadsheet.IfcDataGetter.get_cost_item_values(item))
    assert values[0]["applied_value"] == 10.0


def test_get_cost_items_data_nest_cycle():
    model = ifcopenshell.file(schema="IFC4")
    parent = model.create_entity("IfcCostItem", GlobalId=ifcopenshell.guid.new(), Name="Parent")
    child = model.create_entity("IfcCostItem", GlobalId=ifcopenshell.guid.new(), Name="Child")
    model.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=parent,
        RelatedObjects=[child],
    )
    model.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=child,
        RelatedObjects=[parent],
    )
    parent.CostValues = [
        model.create_entity("IfcCostValue", AppliedValue=model.create_entity("IfcMonetaryMeasure", 1.0))
    ]
    child.CostValues = [
        model.create_entity("IfcCostValue", AppliedValue=model.create_entity("IfcMonetaryMeasure", 2.0))
    ]
    rows = _bounded(lambda: spreadsheet.IfcDataGetter.get_cost_items_data(model, parent))
    assert [row["Name"] for row in rows] == ["Parent", "Child"]


def test_ifc2json_extract_cost_value_component_cycle():
    item, total, leaf = _component_cycle()
    converter = ifc5d.ifc2json.ifc5D2json()
    converter._cost_values = {}
    data = {"CategoryValues": {}}
    _bounded(lambda: converter.extract_cost_value(item, data, total))
    stored = converter._cost_values
    assert stored[total.id()]["AppliedValue"] == 10.0
    assert stored[total.id()]["Formula"] == "10.0+0"
    assert set(stored) == {total.id(), leaf.id()}
