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

"""Selector and element walks must stop when aggregation or similar parents repeat.

These tests fail while a cyclic IFC model makes a location query, container
walk, or decomposition walk run without a bound. A fix has to return the
finite results asserted below.
"""

import os
import signal
import tempfile

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.element as element
import ifcopenshell.util.selector as selector

# Long enough that a finite walk of a handful of elements always returns, and
# short enough that an unbounded walk fails before it exhausts memory.
_DEADLINE_SECONDS = 2.0


class WalkDidNotFinish(AssertionError):
    pass


def _on_deadline(signum, frame):
    raise WalkDidNotFinish(f"walk did not finish within {_DEADLINE_SECONDS}s")


def finish(fn):
    previous = signal.signal(signal.SIGALRM, _on_deadline)
    signal.setitimer(signal.ITIMER_REAL, _DEADLINE_SECONDS)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def new_file(schema="IFC4"):
    return ifcopenshell.file(schema=schema)


def new_guid():
    return ifcopenshell.guid.new()


def make(file, ifc_class, name):
    return file.create_entity(ifc_class, GlobalId=new_guid(), Name=name)


def aggregate(file, whole, part):
    return file.create_entity(
        "IfcRelAggregates",
        GlobalId=new_guid(),
        RelatingObject=whole,
        RelatedObjects=[part],
    )


def contain(file, structure, product):
    return file.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=new_guid(),
        RelatingStructure=structure,
        RelatedElements=[product],
    )


def tree_names(file, container):
    transformer = selector.FacetTransformer(file, None)
    return [item.Name for item in transformer.get_container_tree(container)]


def reload_file(file):
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "cycle.ifc")
        file.write(path)
        return ifcopenshell.open(path)


def cyclic_storey_building():
    """Wall contained in a storey that aggregates a building that aggregates the storey."""
    file = new_file()
    wall = make(file, "IfcWall", "Wall")
    other = make(file, "IfcWall", "Other")
    storey = make(file, "IfcBuildingStorey", "Level 1")
    other_storey = make(file, "IfcBuildingStorey", "Level 2")
    building = make(file, "IfcBuilding", "Building")
    contain(file, storey, wall)
    contain(file, other_storey, other)
    aggregate(file, building, storey)
    aggregate(file, storey, building)
    return file, wall, other, storey, building


class TestCyclicAggregation:
    def test_acyclic_location_tree_stops_at_project(self):
        file = new_file()
        wall = make(file, "IfcWall", "Wall")
        storey = make(file, "IfcBuildingStorey", "Level 1")
        building = make(file, "IfcBuilding", "Building")
        project = make(file, "IfcProject", "Project")
        contain(file, storey, wall)
        aggregate(file, building, storey)
        aggregate(file, project, building)
        assert finish(lambda: tree_names(file, element.get_container(wall))) == ["Level 1", "Building"]
        assert finish(lambda: selector.filter_elements(file, 'IfcWall, location="Level 1"')) == {wall}
        assert finish(lambda: selector.filter_elements(file, "IfcWall, location=Project")) == set()

    def test_project_aggregate_cycle_stops_before_project(self):
        file = new_file()
        storey = make(file, "IfcBuildingStorey", "Level 1")
        project = make(file, "IfcProject", "Project")
        aggregate(file, project, storey)
        aggregate(file, storey, project)
        assert finish(lambda: tree_names(file, storey)) == ["Level 1"]

    def test_location_filter_on_cyclic_spatial_aggregates(self):
        file, wall, other, storey, building = cyclic_storey_building()
        assert element.get_container(wall) == storey
        assert finish(lambda: tree_names(file, storey)) == ["Level 1", "Building"]
        assert finish(lambda: selector.filter_elements(file, 'IfcWall, location="Level 1"')) == {wall}
        assert finish(lambda: selector.filter_elements(file, "IfcWall, location=Building")) == {wall}
        assert finish(lambda: selector.filter_elements(file, 'IfcWall, location="Level 2"')) == {other}
        assert finish(lambda: selector.filter_elements(file, f"IfcWall, location={storey.GlobalId}")) == {wall}
        assert finish(lambda: selector.get_element_value(wall, "storey")) == storey
        assert finish(lambda: selector.get_element_value(wall, "building")) == building
        assert finish(lambda: selector.get_element_value(wall, "site")) is None
        assert finish(lambda: element.get_container(wall, ifc_class="IfcSite")) is None
        assert finish(lambda: element.get_container(storey)) is None
        assert finish(lambda: element.get_parent(storey, ifc_class="IfcSite")) is None

    def test_location_filter_on_reloaded_cyclic_file(self):
        file, wall, other, storey, building = cyclic_storey_building()
        loaded = reload_file(file)
        walls = {item.Name: item for item in loaded.by_type("IfcWall")}
        storeys = {item.Name: item for item in loaded.by_type("IfcBuildingStorey")}
        assert finish(lambda: tree_names(loaded, storeys["Level 1"])) == ["Level 1", "Building"]
        assert finish(lambda: selector.filter_elements(loaded, 'IfcWall, location="Level 1"')) == {walls["Wall"]}
        assert finish(lambda: selector.filter_elements(loaded, 'IfcWall, location="Level 2"')) == {walls["Other"]}
        assert element.get_aggregate(storeys["Level 1"]).Name == "Building"
        assert element.get_aggregate(loaded.by_type("IfcBuilding")[0]).Name == "Level 1"

    def test_mutual_aggregate_without_containment(self):
        file = new_file()
        wall = make(file, "IfcWall", "Wall")
        assembly = make(file, "IfcElementAssembly", "Assembly")
        aggregate(file, assembly, wall)
        aggregate(file, wall, assembly)
        assert finish(lambda: element.get_container(wall)) is None
        assert finish(lambda: element.get_container(assembly)) is None
        assert finish(lambda: tree_names(file, assembly)) == ["Assembly", "Wall"]
        assert finish(lambda: tree_names(file, wall)) == ["Wall", "Assembly"]
        assert finish(lambda: selector.filter_elements(file, 'IfcWall, location="Level 1"')) == set()

    def test_self_aggregate_container_tree(self):
        file = new_file()
        wall = make(file, "IfcWall", "Wall")
        storey = make(file, "IfcBuildingStorey", "Level 1")
        contain(file, storey, wall)
        aggregate(file, storey, storey)
        assert finish(lambda: tree_names(file, storey)) == ["Level 1"]
        assert finish(lambda: selector.filter_elements(file, 'IfcWall, location="Level 1"')) == {wall}

    def test_six_element_aggregate_cycle(self):
        file = new_file()
        wall = make(file, "IfcWall", "Wall")
        storey = make(file, "IfcBuildingStorey", "Level 1")
        contain(file, storey, wall)
        parts = [make(file, "IfcElementAssembly", f"A{index}") for index in range(6)]
        aggregate(file, parts[0], storey)
        for index in range(5):
            aggregate(file, parts[index + 1], parts[index])
        aggregate(file, parts[0], parts[5])
        assert finish(lambda: tree_names(file, storey)) == ["Level 1", "A0", "A1", "A2", "A3", "A4", "A5"]
        assert finish(lambda: selector.filter_elements(file, 'IfcWall, location="Level 1"')) == {wall}
        assert finish(lambda: selector.filter_elements(file, "IfcWall, location=A5")) == {wall}

    def test_ifc2x3_location_filter_on_cyclic_aggregates(self):
        file = new_file("IFC2X3")
        wall = make(file, "IfcWall", "Wall")
        storey = make(file, "IfcBuildingStorey", "Level 1")
        building = make(file, "IfcBuilding", "Building")
        contain(file, storey, wall)
        aggregate(file, building, storey)
        aggregate(file, storey, building)
        loaded = reload_file(file)
        loaded_wall = loaded.by_type("IfcWall")[0]
        loaded_storey = loaded.by_type("IfcBuildingStorey")[0]
        assert finish(lambda: tree_names(loaded, loaded_storey)) == ["Level 1", "Building"]
        assert finish(lambda: selector.filter_elements(loaded, 'IfcWall, location="Level 1"')) == {loaded_wall}

    def test_decomposition_and_parent_filter_on_aggregate_cycle(self):
        file = new_file()
        wall = make(file, "IfcWall", "Wall")
        assembly = make(file, "IfcElementAssembly", "Assembly")
        aggregate(file, assembly, wall)
        aggregate(file, wall, assembly)
        found = finish(lambda: element.get_decomposition(assembly))
        assert found == {wall, assembly}
        assert finish(lambda: selector.filter_elements(file, "parent=Assembly")) == {wall, assembly}

    def test_openings_on_aggregate_cycle(self):
        file = new_file()
        wall = make(file, "IfcWall", "Wall")
        assembly = make(file, "IfcElementAssembly", "Assembly")
        opening = make(file, "IfcOpeningElement", "Opening")
        aggregate(file, assembly, wall)
        aggregate(file, wall, assembly)
        rel = file.create_entity(
            "IfcRelVoidsElement",
            GlobalId=new_guid(),
            RelatingBuildingElement=wall,
            RelatedOpeningElement=opening,
        )
        openings = finish(lambda: list(element.get_openings(wall)))
        assert openings == [rel]
        openings = finish(lambda: list(element.get_openings(assembly)))
        assert openings == [rel]

    def test_nest_cycle(self):
        file = new_file()
        wall = make(file, "IfcWall", "Wall")
        assembly = make(file, "IfcElementAssembly", "Assembly")
        file.create_entity("IfcRelNests", GlobalId=new_guid(), RelatingObject=assembly, RelatedObjects=[wall])
        file.create_entity("IfcRelNests", GlobalId=new_guid(), RelatingObject=wall, RelatedObjects=[assembly])
        assert finish(lambda: element.get_container(wall)) is None
        assert finish(lambda: element.get_parent(wall, ifc_class="IfcSite")) is None
        assert finish(lambda: selector.filter_elements(file, 'IfcWall, location="Level 1"')) == set()
        assert finish(lambda: element.get_decomposition(assembly)) == {wall, assembly}

    def test_void_and_fill_cycle(self):
        file = new_file()
        wall = make(file, "IfcWall", "Wall")
        opening = make(file, "IfcOpeningElement", "Opening")
        file.create_entity(
            "IfcRelVoidsElement",
            GlobalId=new_guid(),
            RelatingBuildingElement=wall,
            RelatedOpeningElement=opening,
        )
        file.create_entity(
            "IfcRelFillsElement",
            GlobalId=new_guid(),
            RelatingOpeningElement=opening,
            RelatedBuildingElement=wall,
        )
        assert finish(lambda: element.get_container(wall)) is None
        assert finish(lambda: element.get_parent(wall, ifc_class="IfcBuilding")) is None
        assert finish(lambda: element.get_decomposition(wall)) == {opening, wall}

    def test_surface_feature_cycle(self):
        file = new_file("IFC4X3")
        host = make(file, "IfcSurfaceFeature", "Host")
        feature = make(file, "IfcSurfaceFeature", "Feature")
        file.create_entity(
            "IfcRelAdheresToElement",
            GlobalId=new_guid(),
            RelatingElement=host,
            RelatedSurfaceFeatures=[feature],
        )
        file.create_entity(
            "IfcRelAdheresToElement",
            GlobalId=new_guid(),
            RelatingElement=feature,
            RelatedSurfaceFeatures=[host],
        )
        assert finish(lambda: element.get_container(feature)) is None
        assert finish(lambda: element.get_decomposition(host)) == {host, feature}

    def test_grouped_by_cycle(self):
        file = new_file()
        first = make(file, "IfcGroup", "First")
        second = make(file, "IfcGroup", "Second")
        file.create_entity(
            "IfcRelAssignsToGroup",
            GlobalId=new_guid(),
            RelatingGroup=first,
            RelatedObjects=[second],
        )
        file.create_entity(
            "IfcRelAssignsToGroup",
            GlobalId=new_guid(),
            RelatingGroup=second,
            RelatedObjects=[first],
        )
        grouped = finish(lambda: element.get_grouped_by(first))
        assert second in grouped
        assert len(grouped) == len(set(grouped))
        assert set(grouped) <= {first, second}
