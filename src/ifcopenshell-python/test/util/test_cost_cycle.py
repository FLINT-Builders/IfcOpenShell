# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 IfcOpenShell contributors
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Deep cost-item walks must stop when nested cost items form a cycle."""

from __future__ import annotations

import ifcopenshell
import ifcopenshell.api.control
import ifcopenshell.api.cost
import ifcopenshell.api.nest
import ifcopenshell.api.owner.settings
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.unit
import ifcopenshell.util.cost as cost_util
import pytest


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
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="RatedWall")
    ifcopenshell.api.control.assign_control(model, relating_control=item_b, related_objects=[wall])
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


def load(path) -> ifcopenshell.file:
    return ifcopenshell.open(path)


def invoke(func):
    try:
        return func()
    except RecursionError as exc:
        pytest.fail(f"cyclic nested cost items exhausted the stack: {exc}")


def _schedule(model):
    return model.by_type("IfcCostSchedule")[0]


def _root(model):
    return cost_util.get_root_cost_items(_schedule(model))[0]


class TestCyclicCostWalk:
    def test_schedule_items_are_unique(self, tmp_path):
        model = load(write_mutual_cycle(tmp_path / "mutual.ifc"))
        found = invoke(lambda: list(cost_util.get_schedule_cost_items(_schedule(model))))
        names = [item.Name for item in found]
        assert names.count("A") == 1
        assert set(names) == {"A", "B", "Sibling"}
        assert len(names) == len({item.id() for item in found})

    def test_deep_nested_items_skip_the_repeat(self, tmp_path):
        model = load(write_mutual_cycle(tmp_path / "mutual.ifc"))
        root = _root(model)
        found = invoke(lambda: cost_util.get_nested_cost_items(root, is_deep=True))
        names = [item.Name for item in found]
        assert root.Name not in names
        assert set(names) == {"B", "Sibling"}
        assert len(names) == len({item.id() for item in found})

    def test_all_nested_items_skip_the_repeat(self, tmp_path):
        model = load(write_mutual_cycle(tmp_path / "mutual.ifc"))
        root = _root(model)
        found = invoke(lambda: list(cost_util.get_all_nested_cost_items(root)))
        names = [item.Name for item in found]
        assert root.Name not in names
        assert set(names) == {"B", "Sibling"}

    def test_deep_assignments_include_nested_product_once(self, tmp_path):
        model = load(write_mutual_cycle(tmp_path / "mutual.ifc"))
        root = _root(model)
        found = invoke(lambda: cost_util.get_cost_item_assignments(root, "PRODUCT", is_deep=True))
        names = [item.Name for item in found]
        assert names == ["RatedWall"]

    def test_self_cycle_schedule_lists_the_item_once(self, tmp_path):
        model = load(write_self_cycle(tmp_path / "self.ifc"))
        found = invoke(lambda: list(cost_util.get_schedule_cost_items(_schedule(model))))
        assert [item.Name for item in found] == ["Loop"]
        nested = invoke(lambda: cost_util.get_nested_cost_items(found[0], is_deep=True))
        assert nested == []
