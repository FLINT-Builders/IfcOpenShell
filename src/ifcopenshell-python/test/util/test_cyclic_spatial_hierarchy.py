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
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

"""Spatial walks must finish on cyclic IFC relationships.

These tests fail while parent, container, decomposition, selector, IDS, and
COBie helpers follow cyclic links without a visited set. A finished call
returns None when no matching class exists, or each element once.
"""

import multiprocessing
import os
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[3]
for _extra in (_SRC / "ifcopenshell-python", _SRC / "ifctester", _SRC / "ifcfm"):
    _entry = str(_extra)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import ifcopenshell.api.aggregate
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.guid

_MP = multiprocessing.get_context("spawn")
_TIMEOUT_SECONDS = 0.75


def _relate(model, ifc_class, **kwargs):
    kwargs.setdefault("GlobalId", ifcopenshell.guid.new())
    return model.create_entity(ifc_class, **kwargs)


def _model(version="IFC4"):
    return ifcopenshell.api.project.create_file(version=version)


def _named(model, ifc_class, name):
    return ifcopenshell.api.root.create_entity(model, ifc_class=ifc_class, name=name)


def _units(model):
    length = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    area = model.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE")
    volume = model.create_entity("IfcSIUnit", UnitType="VOLUMEUNIT", Name="CUBIC_METRE")
    model.create_entity("IfcUnitAssignment", Units=[length, area, volume])


@lru_cache
def mutual_spaces():
    """Wall contained in S1, and S1 aggregates S2 while S2 aggregates S1."""
    model = _model()
    space_1 = _named(model, "IfcSpace", "S1")
    space_2 = _named(model, "IfcSpace", "S2")
    _named(model, "IfcWall", "W")
    wall = model.by_type("IfcWall")[0]
    _relate(model, "IfcRelAggregates", RelatingObject=space_1, RelatedObjects=[space_2])
    _relate(model, "IfcRelAggregates", RelatingObject=space_2, RelatedObjects=[space_1])
    _relate(model, "IfcRelContainedInSpatialStructure", RelatingStructure=space_1, RelatedElements=[wall])
    return model.to_string()


@lru_cache
def side_cycle():
    """S2 and S3 aggregate each other. S0 aggregates S2, and S1 (containing the wall) is a part of S2.

    get_aggregate keeps only the first aggregate parent, so the cycle edges are created
    before S2 aggregates S1. Walking up from the wall visits S1 once, then S2 and S3 forever.
    Walking down from S0 enters that cycle without S0 itself being repeated.
    """
    model = _model()
    outside = _named(model, "IfcSpace", "S0")
    space_1 = _named(model, "IfcSpace", "S1")
    space_2 = _named(model, "IfcSpace", "S2")
    space_3 = _named(model, "IfcSpace", "S3")
    wall = _named(model, "IfcWall", "W")
    _relate(model, "IfcRelAggregates", RelatingObject=space_2, RelatedObjects=[space_3])
    _relate(model, "IfcRelAggregates", RelatingObject=space_3, RelatedObjects=[space_2])
    _relate(model, "IfcRelAggregates", RelatingObject=outside, RelatedObjects=[space_2])
    _relate(model, "IfcRelAggregates", RelatingObject=space_2, RelatedObjects=[space_1])
    _relate(model, "IfcRelContainedInSpatialStructure", RelatingStructure=space_1, RelatedElements=[wall])
    return model.to_string()


@lru_cache
def self_aggregate():
    model = _model()
    space = _named(model, "IfcSpace", "S1")
    wall = _named(model, "IfcWall", "W")
    _relate(model, "IfcRelAggregates", RelatingObject=space, RelatedObjects=[space])
    _relate(model, "IfcRelContainedInSpatialStructure", RelatingStructure=space, RelatedElements=[wall])
    return model.to_string()


@lru_cache
def mutual_nests():
    model = _model()
    first = _named(model, "IfcBuildingElementProxy", "A")
    second = _named(model, "IfcBuildingElementProxy", "B")
    _relate(model, "IfcRelNests", RelatingObject=first, RelatedObjects=[second])
    _relate(model, "IfcRelNests", RelatingObject=second, RelatedObjects=[first])
    return model.to_string()


@lru_cache
def mutual_void_and_fill():
    model = _model()
    wall = _named(model, "IfcWall", "W")
    opening = _named(model, "IfcOpeningElement", "O")
    _relate(model, "IfcRelVoidsElement", RelatingBuildingElement=wall, RelatedOpeningElement=opening)
    _relate(model, "IfcRelFillsElement", RelatingOpeningElement=opening, RelatedBuildingElement=wall)
    return model.to_string()


@lru_cache
def mutual_containment():
    model = _model()
    space_1 = _named(model, "IfcSpace", "S1")
    space_2 = _named(model, "IfcSpace", "S2")
    _relate(model, "IfcRelContainedInSpatialStructure", RelatingStructure=space_1, RelatedElements=[space_2])
    _relate(model, "IfcRelContainedInSpatialStructure", RelatingStructure=space_2, RelatedElements=[space_1])
    return model.to_string()


@lru_cache
def mutual_groups():
    model = _model()
    group_1 = _named(model, "IfcGroup", "G1")
    group_2 = _named(model, "IfcGroup", "G2")
    _relate(model, "IfcRelAssignsToGroup", RelatingGroup=group_1, RelatedObjects=[group_2])
    _relate(model, "IfcRelAssignsToGroup", RelatingGroup=group_2, RelatedObjects=[group_1])
    return model.to_string()


@lru_cache
def mutual_buildings():
    model = _model()
    _named(model, "IfcProject", "Project")
    building_1 = _named(model, "IfcBuilding", "B1")
    building_2 = _named(model, "IfcBuilding", "B2")
    _relate(model, "IfcRelAggregates", RelatingObject=building_1, RelatedObjects=[building_2])
    _relate(model, "IfcRelAggregates", RelatingObject=building_2, RelatedObjects=[building_1])
    _units(model)
    return model.to_string()


@lru_cache
def mutual_surface_features():
    model = _model("IFC4X3")
    first = _named(model, "IfcSurfaceFeature", "F1")
    second = _named(model, "IfcSurfaceFeature", "F2")
    _relate(model, "IfcRelAdheresToElement", RelatingElement=first, RelatedSurfaceFeatures=[second])
    _relate(model, "IfcRelAdheresToElement", RelatingElement=second, RelatedSurfaceFeatures=[first])
    return model.to_string()


@lru_cache
def mutual_spaces_ifc2x3():
    model = _model("IFC2X3")

    def raw(ifc_class, name):
        element = model.create_entity(ifc_class, GlobalId=ifcopenshell.guid.new())
        element.Name = name
        return element

    space_1 = raw("IfcSpace", "S1")
    space_2 = raw("IfcSpace", "S2")
    wall = raw("IfcWall", "W")
    _relate(model, "IfcRelAggregates", RelatingObject=space_1, RelatedObjects=[space_2])
    _relate(model, "IfcRelAggregates", RelatingObject=space_2, RelatedObjects=[space_1])
    _relate(model, "IfcRelContainedInSpatialStructure", RelatingStructure=space_1, RelatedElements=[wall])
    return model.to_string()


@lru_cache
def straight_hierarchy():
    model = _model()
    _named(model, "IfcProject", "Project")
    building = _named(model, "IfcBuilding", "Building")
    storey = _named(model, "IfcBuildingStorey", "Storey")
    space = _named(model, "IfcSpace", "Space")
    wall = _named(model, "IfcWall", "W")
    project = model.by_type("IfcProject")[0]
    ifcopenshell.api.aggregate.assign_object(model, products=[building], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(model, products=[storey], relating_object=building)
    ifcopenshell.api.aggregate.assign_object(model, products=[space], relating_object=storey)
    ifcopenshell.api.spatial.assign_container(model, products=[wall], relating_structure=space)
    _units(model)
    return model.to_string()


def _execute(path, operation):
    import ifcopenshell
    import ifcopenshell.util.element as element
    import ifcopenshell.util.selector as selector

    model = ifcopenshell.open(path)
    named = {}
    for instance in model:
        instance_name = getattr(instance, "Name", None)
        if instance_name:
            named[instance_name] = instance
    kind, _, rest = operation.partition("|")

    def entity_name(instance):
        if instance is None:
            return None
        return instance.Name

    if kind == "aggregate":
        return entity_name(element.get_aggregate(named[rest]))
    if kind == "parent":
        ifc_class, _, target = rest.partition("|")
        return entity_name(element.get_parent(named[target], ifc_class=ifc_class or None))
    if kind == "container":
        ifc_class, _, target = rest.partition("|")
        return entity_name(element.get_container(named[target], ifc_class=ifc_class or None))
    if kind == "decomposition":
        target, _, recursive = rest.partition("|")
        found = element.get_decomposition(named[target], is_recursive=recursive != "direct")
        return sorted(item.Name for item in found)
    if kind == "grouped":
        found = element.get_grouped_by(named[rest])
        names = [item.Name for item in found]
        return sorted(names) if len(names) == len(set(names)) else names
    if kind == "value":
        query, _, target = rest.partition("|")
        return selector.get_element_value(named[target], query)
    if kind == "filter":
        found = selector.filter_elements(model, rest)
        return sorted(item.Name for item in found if getattr(item, "Name", None))
    if kind == "format":
        query, _, target = rest.partition("|")
        return selector.format(query, named[target])
    if kind == "set":
        query, _, target = rest.partition("|")
        before = {item.Name for item in model.by_type("IfcProduct") if item.Name}
        selector.set_element_value(model, named[target], query, "Renamed")
        after = {item.Name for item in model.by_type("IfcProduct") if item.Name}
        return {
            "storeys": len(model.by_type("IfcBuildingStorey")),
            "buildings": len(model.by_type("IfcBuilding")),
            "sites": len(model.by_type("IfcSite")),
            "same_names": before == after,
        }
    if kind == "partof":
        from ifctester.facet import PartOf

        result = PartOf(name=rest)(named["W"])
        return {"pass": bool(result.is_pass), "reason": None if result.reason is None else result.reason.get("type")}
    if kind == "fm":
        module_name, _, target = rest.partition("|")
        if module_name == "basic-facility":
            import ifcfm.basic as basic

            return basic.get_facility_data(model, named[target])["SiteName"]
        if module_name == "basic-space":
            import ifcfm.basic as basic

            return basic.get_space_data(model, named[target])["StoreyName"]
        if module_name == "cobie24":
            import ifcfm.cobie24 as cobie24

            return cobie24.get_facility_data(model, named[target])["SiteName"]
        if module_name == "cobie24legacy":
            import ifcfm.cobie24legacy as cobie24legacy

            return cobie24legacy.get_facility_data(model, named[target])["SiteName"]
        raise AssertionError(module_name)
    raise AssertionError(operation)


def _worker(path, operation, queue):
    try:
        queue.put(("ok", _execute(path, operation)))
    except BaseException as error:
        queue.put(("error", f"{type(error).__name__}: {error}"))


def invoke(text, operation, timeout=_TIMEOUT_SECONDS):
    descriptor, path = tempfile.mkstemp(suffix=".ifc")
    os.close(descriptor)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    queue = _MP.Queue()
    process = _MP.Process(target=_worker, args=(path, operation, queue))
    process.start()
    process.join(timeout)
    timed_out = process.is_alive()
    if timed_out:
        process.terminate()
        process.join(5)
    os.remove(path)
    if timed_out:
        pytest.fail(f"{operation} did not finish within {timeout}s")
    if queue.empty():
        pytest.fail(f"{operation} exited {process.exitcode} with no result")
    status, payload = queue.get()
    if status != "ok":
        pytest.fail(f"{operation} failed: {payload}")
    return payload


def test_parser_keeps_mutual_aggregates():
    assert invoke(mutual_spaces(), "aggregate|S1") == "S2"
    assert invoke(mutual_spaces(), "aggregate|S2") == "S1"


def test_direct_parent_and_container_stay_one_step():
    assert invoke(mutual_spaces(), "parent||W") == "S1"
    assert invoke(mutual_spaces(), "container||W") == "S1"
    assert invoke(mutual_spaces(), "parent|IfcSpace|W") == "S1"


@pytest.mark.parametrize("ifc_class", ["IfcBuildingStorey", "IfcBuilding", "IfcSite"])
def test_get_parent_class_filter_stops_on_mutual_spaces(ifc_class):
    assert invoke(mutual_spaces(), f"parent|{ifc_class}|W") is None


@pytest.mark.parametrize("ifc_class", ["IfcBuildingStorey", "IfcBuilding", "IfcSite"])
def test_get_container_class_filter_stops_on_mutual_spaces(ifc_class):
    assert invoke(mutual_spaces(), f"container|{ifc_class}|W") is None


def test_get_container_on_cyclic_space_returns_none():
    assert invoke(mutual_spaces(), "container||S1") is None


def test_get_parent_class_filter_on_cyclic_space_returns_none():
    assert invoke(mutual_spaces(), "parent|IfcBuildingStorey|S1") is None


def test_get_decomposition_of_mutual_spaces_is_finite():
    assert invoke(mutual_spaces(), "decomposition|S1|") == ["S1", "S2", "W"]


def test_direct_decomposition_does_not_follow_the_cycle():
    assert invoke(mutual_spaces(), "decomposition|S1|direct") == ["S2", "W"]


def test_parent_class_filter_stops_when_the_cycle_does_not_include_the_start():
    assert invoke(side_cycle(), "parent|IfcBuildingStorey|W") is None


def test_container_class_filter_stops_when_the_cycle_does_not_include_the_start():
    assert invoke(side_cycle(), "container|IfcBuildingStorey|W") is None


def test_decomposition_stops_when_the_cycle_does_not_include_the_start():
    assert invoke(side_cycle(), "decomposition|S0|") == ["S1", "S2", "S3", "W"]


def test_self_aggregate_parent_filter_stops():
    assert invoke(self_aggregate(), "parent|IfcBuildingStorey|W") is None


def test_self_aggregate_decomposition_is_finite():
    assert invoke(self_aggregate(), "decomposition|S1|") == ["S1", "W"]


def test_nested_cycle_parent_filter_stops():
    assert invoke(mutual_nests(), "parent|IfcBuildingStorey|A") is None


def test_nested_cycle_decomposition_is_finite():
    assert invoke(mutual_nests(), "decomposition|A|") == ["A", "B"]


def test_void_and_fill_parent_filters_stop():
    assert invoke(mutual_void_and_fill(), "parent|IfcBuildingStorey|W") is None
    assert invoke(mutual_void_and_fill(), "parent|IfcBuildingStorey|O") is None


def test_void_and_fill_decomposition_is_finite():
    assert invoke(mutual_void_and_fill(), "decomposition|W|") == ["O", "W"]


def test_containment_cycle_decomposition_is_finite():
    assert invoke(mutual_containment(), "decomposition|S1|") == ["S1", "S2"]


def test_grouped_by_cycle_lists_each_group_once():
    assert invoke(mutual_groups(), "grouped|G1") == ["G1", "G2"]


def test_surface_feature_parent_filter_stops():
    assert invoke(mutual_surface_features(), "parent|IfcBuildingStorey|F1") is None


def test_surface_feature_decomposition_is_finite():
    assert invoke(mutual_surface_features(), "decomposition|F1|") == ["F1", "F2"]


def test_ifc2x3_parent_class_filter_stops_on_mutual_spaces():
    assert invoke(mutual_spaces_ifc2x3(), "parent|IfcBuildingStorey|W") is None


@pytest.mark.parametrize("query", ["storey.Name", "building.Name", "site.Name"])
def test_selector_value_for_missing_spatial_level_is_none(query):
    assert invoke(mutual_spaces(), f"value|{query}|W") is None


def test_selector_value_for_space_and_container_is_the_direct_parent():
    assert invoke(mutual_spaces(), "value|space.Name|W") == "S1"
    assert invoke(mutual_spaces(), "value|container.Name|W") == "S1"


@pytest.mark.parametrize(
    "query",
    ['query:"storey.Name"=NULL', 'query:"building.Name"=NULL', 'query:"site.Name"=NULL'],
)
def test_selector_query_for_missing_spatial_level_finishes(query):
    assert invoke(mutual_spaces(), f"filter|IfcWall, {query}") == ["W"]


def test_selector_parent_filter_finishes():
    assert invoke(mutual_spaces(), "filter|parent=S1") == ["S1", "S2", "W"]


def test_selector_location_filter_finishes():
    assert invoke(mutual_spaces(), "filter|IfcWall, location=S1") == ["W"]
    assert invoke(mutual_spaces(), "filter|IfcWall, location=S2") == ["W"]


@pytest.mark.parametrize("query", ["{{storey.Name}}", "{{building.Name}}", "{{site.Name}}"])
def test_selector_format_for_missing_spatial_level_is_none(query):
    assert invoke(mutual_spaces(), f"format|{query}|W") is None


@pytest.mark.parametrize("query", ["storey.Name", "building.Name", "site.Name"])
def test_setting_missing_spatial_level_does_not_rename_or_create(query):
    assert invoke(mutual_spaces(), f"set|{query}|W") == {
        "storeys": 0,
        "buildings": 0,
        "sites": 0,
        "same_names": True,
    }


def test_ids_partof_stops_on_mutual_spaces():
    assert invoke(mutual_spaces(), "partof|IFCBUILDINGSTOREY") == {"pass": False, "reason": "ENTITY"}


def test_basic_facility_export_stops_on_aggregate_cycles():
    assert invoke(mutual_buildings(), "fm|basic-facility|B1") is None


def test_basic_space_export_stops_on_aggregate_cycles():
    assert invoke(mutual_spaces(), "fm|basic-space|S1") is None


def test_cobie24_facility_export_stops_on_aggregate_cycles():
    assert invoke(mutual_buildings(), "fm|cobie24|B1") is None


def test_cobie24legacy_facility_export_stops_on_aggregate_cycles():
    assert invoke(mutual_buildings(), "fm|cobie24legacy|B1") is None


def test_straight_hierarchy_still_resolves():
    assert invoke(straight_hierarchy(), "parent|IfcBuildingStorey|W") == "Storey"
    assert invoke(straight_hierarchy(), "parent|IfcBuilding|W") == "Building"
    assert invoke(straight_hierarchy(), "container|IfcBuilding|W") == "Building"
    assert invoke(straight_hierarchy(), "value|storey.Name|W") == "Storey"
    assert invoke(straight_hierarchy(), "format|{{storey.Name}}|W") == "Storey"
    assert invoke(straight_hierarchy(), 'filter|IfcWall, query:"storey.Name"=Storey') == ["W"]
    assert "W" in invoke(straight_hierarchy(), "filter|parent=Storey")
    assert invoke(straight_hierarchy(), "filter|IfcWall, location=Space") == ["W"]
    assert invoke(straight_hierarchy(), "decomposition|Building|") == ["Space", "Storey", "W"]
    assert invoke(straight_hierarchy(), "fm|basic-facility|Building") is None
