# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026
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
#
# This file was generated with the assistance of an AI coding tool.

"""Decomposition import filter must tolerate cyclic IFC relationships.

``LoadProjectElements.execute`` calls ``get_decomposition_elements`` when the
project filter mode is ``DECOMPOSITION``, then constructs ``IfcImporter`` and
runs it. These tests drive that collection on files re-opened from STEP
physical file text. Each element reached through containment, aggregation,
IFC2X3 nesting, or surface adherence must come back once, including when the
relationships form a cycle.

Not covered here, because this filter never reads them:

- ``HasOpenings`` / ``HasFillings`` (opening voids and fills)
- ``IsNestedBy`` on IFC4 and later (nesting is a separate inverse)
- ``IsDecomposedBy`` relationships after the first one on an element
- ``ifcopenshell.util.element.get_decomposition``
- aggregate selection in ``bim/module/aggregate/operator.py``
- search hierarchy paths in ``bim/module/search/operator.py``
"""

import ast
import signal
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.element

_OPERATOR_PATH = Path(__file__).resolve().parents[4] / "bonsai" / "bim" / "module" / "project" / "operator.py"
_METHOD_NAMES = ("get_decomposition_elements", "append_decomposed_elements")


class _FilterCategory:
    def __init__(self, ifc_definition_id: int, is_selected: bool = True) -> None:
        self.ifc_definition_id = ifc_definition_id
        self.is_selected = is_selected


class _ProjectProps:
    def __init__(self, categories: list[_FilterCategory]) -> None:
        self.filter_categories = categories


class _TimedOut(Exception):
    pass


def _load_filter_methods():
    source = _OPERATOR_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in _METHOD_NAMES]
    missing = set(_METHOD_NAMES) - {node.name for node in methods}
    if missing:
        raise AssertionError(f"{_OPERATOR_PATH} is missing {sorted(missing)}")
    module = ast.Module(body=methods, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"ifcopenshell": ifcopenshell}
    exec(compile(module, str(_OPERATOR_PATH), "exec"), namespace)

    class DecompositionFilter:
        get_decomposition_elements = namespace["get_decomposition_elements"]
        append_decomposed_elements = namespace["append_decomposed_elements"]

    return DecompositionFilter


_DecompositionFilter = _load_filter_methods()


def _timeout(seconds: float):
    if not hasattr(signal, "setitimer"):
        raise RuntimeError("A SIGALRM interval timer is required to bound a non-terminating walk.")

    def handler(signum, frame):
        raise _TimedOut(f"decomposition collection did not finish within {seconds} seconds")

    class _Guard:
        def __enter__(self):
            self._previous = signal.signal(signal.SIGALRM, handler)
            signal.setitimer(signal.ITIMER_REAL, seconds)
            return self

        def __exit__(self, exc_type, exc, tb):
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._previous)
            return False

    return _Guard()


def _new_file(schema: str) -> ifcopenshell.file:
    return ifcopenshell.file(schema=schema)


def _guid() -> str:
    return ifcopenshell.guid.new()


def _aggregate(file: ifcopenshell.file, whole, parts) -> None:
    file.create_entity(
        "IfcRelAggregates",
        GlobalId=_guid(),
        RelatingObject=whole,
        RelatedObjects=list(parts),
    )


def _contain(file: ifcopenshell.file, structure, elements) -> None:
    file.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_guid(),
        RelatingStructure=structure,
        RelatedElements=list(elements),
    )


def _spatial_chain(file: ifcopenshell.file):
    project = file.create_entity("IfcProject", GlobalId=_guid(), Name="Project")
    site = file.create_entity("IfcSite", GlobalId=_guid(), Name="Site")
    building = file.create_entity("IfcBuilding", GlobalId=_guid(), Name="Building")
    storey = file.create_entity("IfcBuildingStorey", GlobalId=_guid(), Name="Storey")
    _aggregate(file, project, [site])
    _aggregate(file, site, [building])
    _aggregate(file, building, [storey])
    return storey


def _reopen(file: ifcopenshell.file, path: Path) -> ifcopenshell.file:
    file.write(path)
    return ifcopenshell.open(path)


def _collect(file: ifcopenshell.file, container_id: int) -> set[str]:
    operator = _DecompositionFilter()
    operator.file = file
    operator.props = _ProjectProps([_FilterCategory(container_id)])
    with _timeout(2):
        elements = operator.get_decomposition_elements()
    return {element.Name for element in elements}


def test_acyclic_aggregate_includes_the_part(tmp_path: Path) -> None:
    file = _new_file("IFC4")
    storey = _spatial_chain(file)
    whole = file.create_entity("IfcWall", GlobalId=_guid(), Name="Whole")
    part = file.create_entity("IfcWall", GlobalId=_guid(), Name="Part")
    _aggregate(file, whole, [part])
    _contain(file, storey, [whole])
    opened = _reopen(file, tmp_path / "acyclic.ifc")
    storey_id = opened.by_type("IfcBuildingStorey")[0].id()

    assert _collect(opened, storey_id) == {"Whole", "Part"}


def test_shared_descendant_is_returned_once(tmp_path: Path) -> None:
    file = _new_file("IFC4")
    storey = _spatial_chain(file)
    whole = file.create_entity("IfcWall", GlobalId=_guid(), Name="Whole")
    left = file.create_entity("IfcWall", GlobalId=_guid(), Name="Left")
    right = file.create_entity("IfcWall", GlobalId=_guid(), Name="Right")
    shared = file.create_entity("IfcWall", GlobalId=_guid(), Name="Shared")
    _aggregate(file, whole, [left, right])
    _aggregate(file, left, [shared])
    _aggregate(file, right, [shared])
    _contain(file, storey, [whole])
    opened = _reopen(file, tmp_path / "diamond.ifc")
    storey_id = opened.by_type("IfcBuildingStorey")[0].id()

    assert _collect(opened, storey_id) == {"Whole", "Left", "Right", "Shared"}


def test_mutual_aggregates_under_a_storey_finish(tmp_path: Path) -> None:
    file = _new_file("IFC4")
    storey = _spatial_chain(file)
    first = file.create_entity("IfcWall", GlobalId=_guid(), Name="First")
    second = file.create_entity("IfcWall", GlobalId=_guid(), Name="Second")
    _aggregate(file, first, [second])
    _aggregate(file, second, [first])
    _contain(file, storey, [first])
    opened = _reopen(file, tmp_path / "mutual.ifc")
    storey_id = opened.by_type("IfcBuildingStorey")[0].id()

    assert _collect(opened, storey_id) == {"First", "Second"}


def test_element_that_aggregates_itself_finishes(tmp_path: Path) -> None:
    file = _new_file("IFC4")
    storey = _spatial_chain(file)
    wall = file.create_entity("IfcWall", GlobalId=_guid(), Name="Loop")
    _aggregate(file, wall, [wall])
    _contain(file, storey, [wall])
    opened = _reopen(file, tmp_path / "self.ifc")
    storey_id = opened.by_type("IfcBuildingStorey")[0].id()

    assert _collect(opened, storey_id) == {"Loop"}


def test_three_element_aggregate_cycle_finishes(tmp_path: Path) -> None:
    file = _new_file("IFC4")
    storey = _spatial_chain(file)
    first = file.create_entity("IfcWall", GlobalId=_guid(), Name="First")
    second = file.create_entity("IfcWall", GlobalId=_guid(), Name="Second")
    third = file.create_entity("IfcWall", GlobalId=_guid(), Name="Third")
    _aggregate(file, first, [second])
    _aggregate(file, second, [third])
    _aggregate(file, third, [first])
    _contain(file, storey, [first])
    opened = _reopen(file, tmp_path / "three.ifc")
    storey_id = opened.by_type("IfcBuildingStorey")[0].id()

    assert _collect(opened, storey_id) == {"First", "Second", "Third"}


def test_ifc2x3_mutual_aggregates_finish(tmp_path: Path) -> None:
    file = _new_file("IFC2X3")
    storey = _spatial_chain(file)
    first = file.create_entity("IfcWall", GlobalId=_guid(), Name="First")
    second = file.create_entity("IfcWall", GlobalId=_guid(), Name="Second")
    _aggregate(file, first, [second])
    _aggregate(file, second, [first])
    _contain(file, storey, [first])
    opened = _reopen(file, tmp_path / "ifc2x3-mutual.ifc")
    storey_id = opened.by_type("IfcBuildingStorey")[0].id()

    assert _collect(opened, storey_id) == {"First", "Second"}


def test_ifc2x3_mutual_nests_finish(tmp_path: Path) -> None:
    file = _new_file("IFC2X3")
    storey = _spatial_chain(file)
    first = file.create_entity("IfcWall", GlobalId=_guid(), Name="First")
    second = file.create_entity("IfcWall", GlobalId=_guid(), Name="Second")
    file.create_entity(
        "IfcRelNests",
        GlobalId=_guid(),
        RelatingObject=first,
        RelatedObjects=[second],
    )
    file.create_entity(
        "IfcRelNests",
        GlobalId=_guid(),
        RelatingObject=second,
        RelatedObjects=[first],
    )
    _contain(file, storey, [first])
    opened = _reopen(file, tmp_path / "ifc2x3-nests.ifc")
    reopened_first = next(element for element in opened.by_type("IfcWall") if element.Name == "First")
    assert [relationship.is_a() for relationship in reopened_first.IsDecomposedBy] == ["IfcRelNests"]
    storey_id = opened.by_type("IfcBuildingStorey")[0].id()

    assert _collect(opened, storey_id) == {"First", "Second"}


def test_cyclic_surface_features_finish(tmp_path: Path) -> None:
    file = _new_file("IFC4X3")
    storey = _spatial_chain(file)
    host = file.create_entity("IfcPavement", GlobalId=_guid(), Name="Host")
    first = file.create_entity("IfcSurfaceFeature", GlobalId=_guid(), Name="FirstMark")
    second = file.create_entity("IfcSurfaceFeature", GlobalId=_guid(), Name="SecondMark")
    file.create_entity(
        "IfcRelAdheresToElement",
        GlobalId=_guid(),
        RelatingElement=host,
        RelatedSurfaceFeatures=[first],
    )
    file.create_entity(
        "IfcRelAdheresToElement",
        GlobalId=_guid(),
        RelatingElement=first,
        RelatedSurfaceFeatures=[second],
    )
    file.create_entity(
        "IfcRelAdheresToElement",
        GlobalId=_guid(),
        RelatingElement=second,
        RelatedSurfaceFeatures=[first],
    )
    _contain(file, storey, [host])
    opened = _reopen(file, tmp_path / "surface.ifc")
    storey_id = opened.by_type("IfcBuildingStorey")[0].id()

    assert _collect(opened, storey_id) == {"Host", "FirstMark", "SecondMark"}


def test_cyclic_spatial_aggregates_finish(tmp_path: Path) -> None:
    file = _new_file("IFC4")
    # Bonsai refuses a file with no IfcProject before the filter runs. The project
    # is not the parent of these storeys: each storey's only aggregate parent is the other.
    file.create_entity("IfcProject", GlobalId=_guid(), Name="Project")
    first = file.create_entity("IfcBuildingStorey", GlobalId=_guid(), Name="FirstStorey")
    second = file.create_entity("IfcBuildingStorey", GlobalId=_guid(), Name="SecondStorey")
    wall = file.create_entity("IfcWall", GlobalId=_guid(), Name="Wall")
    _aggregate(file, first, [second])
    _aggregate(file, second, [first])
    _contain(file, first, [wall])
    opened = _reopen(file, tmp_path / "spatial-cycle.ifc")
    selected = next(element for element in opened.by_type("IfcBuildingStorey") if element.Name == "FirstStorey")
    assert ifcopenshell.util.element.get_aggregate(selected).Name == "SecondStorey"

    assert _collect(opened, selected.id()) == {"Wall"}


def test_unselected_cyclic_container_is_not_walked(tmp_path: Path) -> None:
    file = _new_file("IFC4")
    storey = _spatial_chain(file)
    first = file.create_entity("IfcWall", GlobalId=_guid(), Name="First")
    second = file.create_entity("IfcWall", GlobalId=_guid(), Name="Second")
    _aggregate(file, first, [second])
    _aggregate(file, second, [first])
    _contain(file, storey, [first])
    opened = _reopen(file, tmp_path / "unselected.ifc")
    operator = _DecompositionFilter()
    operator.file = opened
    operator.props = _ProjectProps([_FilterCategory(opened.by_type("IfcBuildingStorey")[0].id(), is_selected=False)])

    with _timeout(2):
        elements = operator.get_decomposition_elements()

    assert elements == set()
