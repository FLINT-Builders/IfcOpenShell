# This file was generated with the assistance of an AI coding tool.
"""Filtered project import must finish when aggregate parents form a cycle.

Bonsai collects the spatial container of each filtered element and walks
aggregate parents while an element filter and Filter Spatial Elements are both
on. The same import also walks those parents for a decomposition filter, and
walks aggregate children and selector location/parent queries. None of those
walks record an element they have already seen.

These tests fail while that is true and pass once a repeated element stops the
walk. They execute the functions in import_ifc.py, project/operator.py, and
ifcopenshell.util.selector, after ifcopenshell has parsed a written IFC file.
"""

from __future__ import annotations

import ast
import os
import signal
import tempfile
from pathlib import Path
from types import SimpleNamespace

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.selector

REPO = Path(__file__).resolve().parents[4]
IMPORT_IFC = REPO / "src/bonsai/bonsai/bim/import_ifc.py"
PROJECT_OPERATOR = REPO / "src/bonsai/bonsai/bim/module/project/operator.py"
WALK_SECONDS = 2


def _load_methods(path: Path, class_name: str, names: set[str]) -> dict:
    tree = ast.parse(path.read_text())
    found = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in names:
                    found.append(item)
    missing = names - {node.name for node in found}
    if missing:
        raise AssertionError(f"{class_name} is missing {sorted(missing)} in {path}")
    code = "from __future__ import annotations\nimport ifcopenshell\n" + "\n\n".join(
        ast.unparse(node) for node in found
    )
    namespace = {"ifcopenshell": ifcopenshell}
    exec(compile(code, str(path), "exec"), namespace)
    return namespace


_IMPORTER = type(
    "IfcImporter",
    (),
    _load_methods(
        IMPORT_IFC,
        "IfcImporter",
        {"process_element_filter", "get_spatial_elements_filtered_by_elements"},
    ),
)
_OPERATOR = type(
    "LoadProjectElements",
    (),
    _load_methods(
        PROJECT_OPERATOR,
        "LoadProjectElements",
        {"get_decomposition_elements", "append_decomposed_elements"},
    ),
)


def _run_bounded(fn):
    def handler(signum, frame):
        raise AssertionError("import did not finish; an aggregate walk repeated an element forever")

    previous = signal.signal(signal.SIGALRM, handler)
    signal.alarm(WALK_SECONDS)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _create(file, ifc_class, **kwargs):
    kwargs.setdefault("GlobalId", ifcopenshell.guid.new())
    return file.create_entity(ifc_class, **kwargs)


def _reopen(file):
    handle = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
    handle.close()
    try:
        file.write(handle.name)
        return ifcopenshell.open(handle.name)
    finally:
        os.unlink(handle.name)


def _names(elements) -> set[str]:
    return {element.Name for element in elements}


def _by_name(file, ifc_class, name):
    return next(element for element in file.by_type(ifc_class) if element.Name == name)


def _mutual_buildings(schema="IFC4", *, project_first=False):
    """Two buildings aggregate each other. A project link is also written.

    The cyclic relationships are written first unless project_first is set, so
    get_aggregate follows the other building. Each building contains one wall.
    The file is written and opened again, so the inverses come from the parser.
    """
    file = ifcopenshell.file(schema=schema)
    project = _create(file, "IfcProject", Name="Project")
    building_a = _create(file, "IfcBuilding", Name="BuildingA")
    building_b = _create(file, "IfcBuilding", Name="BuildingB")
    wall_a = _create(file, "IfcWall", Name="WallA")
    wall_b = _create(file, "IfcWall", Name="WallB")

    def cycle():
        _create(file, "IfcRelAggregates", Name="AtoB", RelatingObject=building_a, RelatedObjects=[building_b])
        _create(file, "IfcRelAggregates", Name="BtoA", RelatingObject=building_b, RelatedObjects=[building_a])

    def project_link():
        _create(file, "IfcRelAggregates", Name="ProjectToA", RelatingObject=project, RelatedObjects=[building_a])

    if project_first:
        project_link()
        cycle()
    else:
        cycle()
        project_link()
    _create(file, "IfcRelContainedInSpatialStructure", RelatingStructure=building_a, RelatedElements=[wall_a])
    _create(file, "IfcRelContainedInSpatialStructure", RelatingStructure=building_b, RelatedElements=[wall_b])
    return _reopen(file)


def _filter_spatial(file, elements):
    importer = _IMPORTER()
    importer.file = file
    importer.ifc_import_settings = SimpleNamespace(
        has_filter=True,
        should_filter_spatial_elements=True,
        elements=list(elements),
        element_limit_mode="UNLIMITED",
        element_offset=0,
        element_limit=30000,
        void_limit=30,
    )

    def run():
        importer.process_element_filter()
        return importer.spatial_elements

    return _run_bounded(run)


def test_filtered_spatial_import_finishes_on_mutual_building_cycle():
    file = _mutual_buildings()
    wall = _by_name(file, "IfcWall", "WallA")
    # The project also aggregates BuildingA, but the cycle was written first.
    assert ifcopenshell.util.element.get_aggregate(_by_name(file, "IfcBuilding", "BuildingA")).Name == "BuildingB"
    spatial = _filter_spatial(file, [wall])
    assert _names(spatial) == {"BuildingA", "BuildingB"}


def test_filtered_spatial_import_walks_from_storey_into_building_cycle():
    file = ifcopenshell.file(schema="IFC4")
    project = _create(file, "IfcProject", Name="Project")
    building_a = _create(file, "IfcBuilding", Name="BuildingA")
    building_b = _create(file, "IfcBuilding", Name="BuildingB")
    storey = _create(file, "IfcBuildingStorey", Name="Storey")
    wall = _create(file, "IfcWall", Name="WallA")
    _create(file, "IfcRelAggregates", RelatingObject=building_a, RelatedObjects=[building_b, storey])
    _create(file, "IfcRelAggregates", RelatingObject=building_b, RelatedObjects=[building_a])
    _create(file, "IfcRelAggregates", RelatingObject=project, RelatedObjects=[building_a])
    _create(file, "IfcRelContainedInSpatialStructure", RelatingStructure=storey, RelatedElements=[wall])
    file = _reopen(file)
    spatial = _filter_spatial(file, [_by_name(file, "IfcWall", "WallA")])
    assert _names(spatial) == {"Storey", "BuildingA", "BuildingB"}


def test_filtered_spatial_import_finishes_on_three_building_cycle():
    file = ifcopenshell.file(schema="IFC4")
    project = _create(file, "IfcProject", Name="Project")
    building_a = _create(file, "IfcBuilding", Name="BuildingA")
    building_b = _create(file, "IfcBuilding", Name="BuildingB")
    building_c = _create(file, "IfcBuilding", Name="BuildingC")
    wall = _create(file, "IfcWall", Name="WallA")
    _create(file, "IfcRelAggregates", RelatingObject=building_a, RelatedObjects=[building_b])
    _create(file, "IfcRelAggregates", RelatingObject=building_b, RelatedObjects=[building_c])
    _create(file, "IfcRelAggregates", RelatingObject=building_c, RelatedObjects=[building_a])
    _create(file, "IfcRelAggregates", RelatingObject=project, RelatedObjects=[building_a])
    _create(file, "IfcRelContainedInSpatialStructure", RelatingStructure=building_a, RelatedElements=[wall])
    file = _reopen(file)
    spatial = _filter_spatial(file, [_by_name(file, "IfcWall", "WallA")])
    assert _names(spatial) == {"BuildingA", "BuildingB", "BuildingC"}


def test_filtered_spatial_import_finishes_on_self_aggregate():
    file = ifcopenshell.file(schema="IFC4")
    project = _create(file, "IfcProject", Name="Project")
    building = _create(file, "IfcBuilding", Name="BuildingA")
    wall = _create(file, "IfcWall", Name="WallA")
    _create(file, "IfcRelAggregates", RelatingObject=building, RelatedObjects=[building])
    _create(file, "IfcRelAggregates", RelatingObject=project, RelatedObjects=[building])
    _create(file, "IfcRelContainedInSpatialStructure", RelatingStructure=building, RelatedElements=[wall])
    file = _reopen(file)
    opened_building = _by_name(file, "IfcBuilding", "BuildingA")
    assert ifcopenshell.util.element.get_aggregate(opened_building) == opened_building
    spatial = _filter_spatial(file, [_by_name(file, "IfcWall", "WallA")])
    assert _names(spatial) == {"BuildingA"}


def test_filtered_spatial_import_keeps_acyclic_ancestors():
    file = ifcopenshell.file(schema="IFC4")
    project = _create(file, "IfcProject", Name="Project")
    site = _create(file, "IfcSite", Name="Site")
    building = _create(file, "IfcBuilding", Name="BuildingA")
    storey = _create(file, "IfcBuildingStorey", Name="Storey")
    wall = _create(file, "IfcWall", Name="WallA")
    _create(file, "IfcRelAggregates", RelatingObject=project, RelatedObjects=[site])
    _create(file, "IfcRelAggregates", RelatingObject=site, RelatedObjects=[building])
    _create(file, "IfcRelAggregates", RelatingObject=building, RelatedObjects=[storey])
    _create(file, "IfcRelContainedInSpatialStructure", RelatingStructure=storey, RelatedElements=[wall])
    file = _reopen(file)
    spatial = _filter_spatial(file, [_by_name(file, "IfcWall", "WallA")])
    assert _names(spatial) == {"Storey", "BuildingA", "Site"}


def test_unfiltered_import_finishes_on_building_cycle():
    file = _mutual_buildings()
    importer = _IMPORTER()
    importer.file = file
    importer.ifc_import_settings = SimpleNamespace(
        has_filter=False,
        should_filter_spatial_elements=True,
        elements=[],
        element_limit_mode="UNLIMITED",
        element_offset=0,
        element_limit=30000,
        void_limit=30,
    )

    def run():
        importer.process_element_filter()
        return importer.spatial_elements

    assert _names(_run_bounded(run)) == {"BuildingA", "BuildingB"}


def test_filter_without_spatial_filter_finishes_on_building_cycle():
    file = _mutual_buildings()
    importer = _IMPORTER()
    importer.file = file
    importer.ifc_import_settings = SimpleNamespace(
        has_filter=True,
        should_filter_spatial_elements=False,
        elements=[_by_name(file, "IfcWall", "WallA")],
        element_limit_mode="UNLIMITED",
        element_offset=0,
        element_limit=30000,
        void_limit=30,
    )

    def run():
        importer.process_element_filter()
        return importer.spatial_elements

    assert _names(_run_bounded(run)) == {"BuildingA", "BuildingB"}


def test_ifc2x3_filtered_spatial_import_finishes_on_building_cycle():
    file = _mutual_buildings("IFC2X3")
    spatial = _filter_spatial(file, [_by_name(file, "IfcWall", "WallA")])
    assert _names(spatial) == {"BuildingA", "BuildingB"}


def _decomposition_elements(file, selected):
    operator = _OPERATOR()
    operator.file = file
    operator.props = SimpleNamespace(
        filter_categories=[SimpleNamespace(is_selected=True, ifc_definition_id=element.id()) for element in selected]
    )
    return _run_bounded(operator.get_decomposition_elements)


def test_decomposition_filter_finishes_on_spatial_cycle():
    file = _mutual_buildings()
    elements = _decomposition_elements(file, [_by_name(file, "IfcBuilding", "BuildingA")])
    assert _names(elements) == {"WallA", "WallB"}


def test_decomposition_filter_finishes_on_cyclic_parts():
    file = ifcopenshell.file(schema="IFC4")
    project = _create(file, "IfcProject", Name="Project")
    building = _create(file, "IfcBuilding", Name="BuildingA")
    wall_a = _create(file, "IfcWall", Name="WallA")
    wall_b = _create(file, "IfcWall", Name="WallB")
    # The project link is first, so the spatial parent walk reaches IfcProject.
    # The parts still aggregate each other.
    _create(file, "IfcRelAggregates", RelatingObject=project, RelatedObjects=[building])
    _create(file, "IfcRelAggregates", RelatingObject=wall_a, RelatedObjects=[wall_b])
    _create(file, "IfcRelAggregates", RelatingObject=wall_b, RelatedObjects=[wall_a])
    _create(file, "IfcRelContainedInSpatialStructure", RelatingStructure=building, RelatedElements=[wall_a])
    file = _reopen(file)
    elements = _decomposition_elements(file, [_by_name(file, "IfcBuilding", "BuildingA")])
    assert _names(elements) == {"WallA", "WallB"}


def test_whitelist_location_filter_finishes_on_building_cycle():
    file = _mutual_buildings()
    elements = _run_bounded(lambda: ifcopenshell.util.selector.filter_elements(file, 'location="BuildingA"'))
    assert _names(elements) == {"BuildingA", "BuildingB", "WallA", "WallB"}


def test_whitelist_parent_filter_finishes_on_building_cycle():
    file = _mutual_buildings()
    elements = _run_bounded(lambda: ifcopenshell.util.selector.filter_elements(file, 'parent="BuildingA"'))
    assert _names(elements) == {"BuildingA", "BuildingB", "WallA", "WallB"}
