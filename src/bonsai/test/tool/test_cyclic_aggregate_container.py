# This file was generated with the assistance of an AI coding tool.
# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

"""Container assignment must finish when aggregate or nest parents form a cycle.

An IFC file can contain two elements that aggregate each other, an element that
aggregates itself, or the same shapes expressed with IfcRelNests. Opening that
file and assigning one of the elements to a storey calls
``Spatial.get_root_element`` and then ``ifcopenshell.util.element.get_decomposition``.
Neither walk records elements it has already seen, so the assignment never
returns.

These tests fail while that is true. They pass once a repeated element id stops
the walk and the assignment call returns. The root that is contained is the
last element that was not already on the walk.
"""

from __future__ import annotations

import os
import signal
import tempfile

import bpy
import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.element
import pytest

import bonsai.core.spatial
import bonsai.tool as tool
from test.bim.bootstrap import NewFile


WALK_SECONDS = 2


class _Deadline:
    def __enter__(self):
        def _handle(signum, frame):
            raise TimeoutError("parent walk did not return")

        self._previous = signal.signal(signal.SIGALRM, _handle)
        signal.alarm(WALK_SECONDS)
        return self

    def __exit__(self, exc_type, exc, tb):
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self._previous)
        return False


def _reopen(ifc: ifcopenshell.file) -> ifcopenshell.file:
    handle = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
    handle.close()
    try:
        ifc.write(handle.name)
        return ifcopenshell.open(handle.name)
    finally:
        os.unlink(handle.name)


def _by_name(ifc: ifcopenshell.file, ifc_class: str, name: str) -> ifcopenshell.entity_instance:
    found = [element for element in ifc.by_type(ifc_class) if element.Name == name]
    assert len(found) == 1
    return found[0]


def _aggregate(ifc: ifcopenshell.file, parent, child) -> None:
    ifc.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=parent,
        RelatedObjects=[child],
    )


def _nest(ifc: ifcopenshell.file, parent, child) -> None:
    ifc.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=parent,
        RelatedObjects=[child],
    )


def _wall(ifc: ifcopenshell.file, name: str, ifc_class: str = "IfcWall"):
    return ifc.create_entity(ifc_class, GlobalId=ifcopenshell.guid.new(), Name=name)


def _contain(ifc: ifcopenshell.file, structure, products: list) -> None:
    ifc.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=ifcopenshell.guid.new(),
        RelatingStructure=structure,
        RelatedElements=products,
    )


def _use(ifc: ifcopenshell.file) -> ifcopenshell.file:
    opened = _reopen(ifc)
    tool.Ifc.set(opened)
    return opened


def _link(element: ifcopenshell.entity_instance) -> bpy.types.Object:
    obj = bpy.data.objects.new(element.Name or element.is_a(), None)
    bpy.context.scene.collection.objects.link(obj)
    tool.Ifc.link(element, obj)
    return obj


def _prepare_collector(project: ifcopenshell.entity_instance) -> None:
    tool.Collector.assign(_link(project))


@pytest.mark.spatial
class TestCyclicAggregateRoot(NewFile):
    def test_acyclic_aggregate_chain_still_reaches_the_top(self):
        ifc = ifcopenshell.file(schema="IFC4")
        top = _wall(ifc, "Top", "IfcElementAssembly")
        middle = _wall(ifc, "Middle", "IfcElementAssembly")
        part = _wall(ifc, "Part", "IfcBeam")
        _aggregate(ifc, top, middle)
        _aggregate(ifc, middle, part)
        opened = _use(ifc)

        with _Deadline():
            root = tool.Spatial.get_root_element(_by_name(opened, "IfcBeam", "Part"))

        assert root.Name == "Top"

    def test_self_aggregate_loaded_from_disk_returns_that_element(self):
        ifc = ifcopenshell.file(schema="IFC4")
        wall = _wall(ifc, "Loop")
        _aggregate(ifc, wall, wall)
        opened = _use(ifc)
        wall = _by_name(opened, "IfcWall", "Loop")
        assert ifcopenshell.util.element.get_aggregate(wall) == wall

        with _Deadline():
            assert tool.Spatial.get_root_element(wall) == wall

    def test_mutual_aggregate_returns_the_element_before_the_repeat(self):
        ifc = ifcopenshell.file(schema="IFC4")
        first = _wall(ifc, "First")
        second = _wall(ifc, "Second")
        _aggregate(ifc, second, first)
        _aggregate(ifc, first, second)
        opened = _use(ifc)
        first = _by_name(opened, "IfcWall", "First")
        second = _by_name(opened, "IfcWall", "Second")
        assert ifcopenshell.util.element.get_aggregate(first) == second
        assert ifcopenshell.util.element.get_aggregate(second) == first

        with _Deadline():
            assert tool.Spatial.get_root_element(first) == second

    def test_three_element_aggregate_cycle_returns_the_element_before_the_repeat(self):
        ifc = ifcopenshell.file(schema="IFC4")
        first = _wall(ifc, "First")
        second = _wall(ifc, "Second")
        third = _wall(ifc, "Third")
        _aggregate(ifc, second, first)
        _aggregate(ifc, third, second)
        _aggregate(ifc, first, third)
        opened = _use(ifc)

        with _Deadline():
            root = tool.Spatial.get_root_element(_by_name(opened, "IfcWall", "First"))

        assert root.Name == "Third"

    def test_aggregate_chain_that_enters_a_cycle_stops_at_the_last_new_element(self):
        ifc = ifcopenshell.file(schema="IFC4")
        start = _wall(ifc, "Start")
        left = _wall(ifc, "Left")
        right = _wall(ifc, "Right")
        _aggregate(ifc, left, start)
        _aggregate(ifc, right, left)
        _aggregate(ifc, left, right)
        opened = _use(ifc)

        with _Deadline():
            root = tool.Spatial.get_root_element(_by_name(opened, "IfcWall", "Start"))

        assert root.Name == "Right"

    def test_mutual_nest_returns_the_element_before_the_repeat(self):
        ifc = ifcopenshell.file(schema="IFC4")
        first = _wall(ifc, "First")
        second = _wall(ifc, "Second")
        _nest(ifc, second, first)
        _nest(ifc, first, second)
        opened = _use(ifc)
        first = _by_name(opened, "IfcWall", "First")
        assert ifcopenshell.util.element.get_nest(first).Name == "Second"

        with _Deadline():
            assert tool.Spatial.get_root_element(first).Name == "Second"

    def test_aggregate_then_nest_cycle_returns_the_element_before_the_repeat(self):
        ifc = ifcopenshell.file(schema="IFC4")
        first = _wall(ifc, "First")
        second = _wall(ifc, "Second")
        _aggregate(ifc, second, first)
        _nest(ifc, first, second)
        opened = _use(ifc)

        with _Deadline():
            root = tool.Spatial.get_root_element(_by_name(opened, "IfcWall", "First"))

        assert root.Name == "Second"

    def test_ifc2x3_mutual_aggregate_returns_the_element_before_the_repeat(self):
        ifc = ifcopenshell.file(schema="IFC2X3")
        first = _wall(ifc, "First")
        second = _wall(ifc, "Second")
        _aggregate(ifc, second, first)
        _aggregate(ifc, first, second)
        opened = _use(ifc)

        with _Deadline():
            root = tool.Spatial.get_root_element(_by_name(opened, "IfcWall", "First"))

        assert root.Name == "Second"


def _contained_pair(schema: str = "IFC4"):
    ifc = ifcopenshell.file(schema=schema)
    project = ifc.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Project")
    home = ifc.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Home")
    dest = ifc.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Dest")
    first = _wall(ifc, "First")
    second = _wall(ifc, "Second")
    _aggregate(ifc, second, first)
    _aggregate(ifc, first, second)
    _contain(ifc, home, [first, second])
    opened = _use(ifc)
    return opened


@pytest.mark.spatial
class TestCyclicAssignContainer(NewFile):
    def test_assign_container_contains_the_root_of_a_mutual_aggregate(self):
        ifc = _contained_pair()
        project = _by_name(ifc, "IfcProject", "Project")
        dest = _by_name(ifc, "IfcBuildingStorey", "Dest")
        first = _by_name(ifc, "IfcWall", "First")
        _prepare_collector(project)
        _link(dest)
        _link(_by_name(ifc, "IfcBuildingStorey", "Home"))
        first_obj = _link(first)
        _link(_by_name(ifc, "IfcWall", "Second"))

        with _Deadline():
            bonsai.core.spatial.assign_container(
                tool.Ifc, tool.Collector, tool.Spatial, container=dest, objs=[first_obj]
            )

        assert ifcopenshell.util.element.get_container(_by_name(ifc, "IfcWall", "Second")).Name == "Dest"

    def test_assign_container_contains_a_self_aggregated_wall(self):
        ifc = ifcopenshell.file(schema="IFC4")
        project = ifc.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Project")
        home = ifc.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Home")
        dest = ifc.create_entity("IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Dest")
        wall = _wall(ifc, "Loop")
        _aggregate(ifc, wall, wall)
        _contain(ifc, home, [wall])
        ifc = _use(ifc)
        _prepare_collector(_by_name(ifc, "IfcProject", "Project"))
        dest = _by_name(ifc, "IfcBuildingStorey", "Dest")
        _link(dest)
        wall_obj = _link(_by_name(ifc, "IfcWall", "Loop"))

        with _Deadline():
            bonsai.core.spatial.assign_container(
                tool.Ifc, tool.Collector, tool.Spatial, container=dest, objs=[wall_obj]
            )

        assert ifcopenshell.util.element.get_container(_by_name(ifc, "IfcWall", "Loop")).Name == "Dest"

    def test_assign_container_operator_contains_the_root_of_the_selected_element(self):
        ifc = _contained_pair()
        _prepare_collector(_by_name(ifc, "IfcProject", "Project"))
        dest = _by_name(ifc, "IfcBuildingStorey", "Dest")
        _link(dest)
        _link(_by_name(ifc, "IfcBuildingStorey", "Home"))
        first_obj = _link(_by_name(ifc, "IfcWall", "First"))
        _link(_by_name(ifc, "IfcWall", "Second"))
        bpy.ops.object.select_all(action="DESELECT")
        first_obj.select_set(True)
        bpy.context.view_layer.objects.active = first_obj

        with _Deadline():
            result = bpy.ops.bim.assign_container(container=dest.id())

        assert result == {"FINISHED"}
        assert ifcopenshell.util.element.get_container(_by_name(ifc, "IfcWall", "Second")).Name == "Dest"
