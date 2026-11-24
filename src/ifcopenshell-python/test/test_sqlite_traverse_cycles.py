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

"""Failing tests for cyclic forward references in the SQLite and stream traversals.

``sqlite.traverse`` and ``stream.traverse`` walk forward references with a work
list and no set of entities already queued. The in-memory file keeps that set
in ``ifcopenshell::traverse``. These tests open a model the way
``ifcopenshell.open`` does and require the same entity ids as
``file.traverse`` on that model. They time out while the work list grows
without bound.
"""

import signal
from pathlib import Path

from ifcpatch.recipes import Ifc2Sql

import ifcopenshell
import ifcopenshell.util.element

# A tight cycle spins at 100% CPU; a second is enough to show it does not return.
TRAVERSE_TIMEOUT_SECONDS = 1


class TraverseDidNotReturn(AssertionError):
    pass


def _run(fn):
    def handler(signum, frame):
        raise TraverseDidNotReturn("traverse did not return")

    previous = signal.signal(signal.SIGALRM, handler)
    signal.alarm(TRAVERSE_TIMEOUT_SECONDS)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _ids(entities) -> list[int]:
    return [entity.id() for entity in entities]


def _assert_same_ids(got, expected) -> None:
    got_ids = _ids(got)
    expected_ids = _ids(expected)
    assert len(got_ids) == len(set(got_ids))
    assert set(got_ids) == set(expected_ids)


def _write_sqlite(ifc: ifcopenshell.file, directory: Path, name: str) -> tuple[Path, Path]:
    ifc_path = directory / f"{name}.ifc"
    ifc.write(ifc_path)
    db_path = directory / f"{name}.ifcsqlite"
    # Same serializer Bonsai and ifcopenshell.open(.ifcSQLite) consume. Geometry
    # and pset tables are unrelated to forward-reference walking.
    Ifc2Sql.Patcher(
        ifcopenshell.open(ifc_path),
        database=str(db_path),
        full_schema=False,
        should_get_geometry=False,
        should_get_psets=False,
    ).patch()
    return ifc_path, db_path


def _placement_cycle(tmp_path: Path):
    ifc = ifcopenshell.file(schema="IFC4")
    first = ifc.create_entity("IfcLocalPlacement")
    second = ifc.create_entity("IfcLocalPlacement")
    first.PlacementRelTo = second
    second.PlacementRelTo = first
    unrelated = ifc.create_entity("IfcPerson", Identification="not-in-the-cycle")
    ifc_path, db_path = _write_sqlite(ifc, tmp_path, "placement-cycle")
    return ifcopenshell.open(ifc_path), ifcopenshell.open(db_path), first.id(), unrelated.id()


def _self_placement(tmp_path: Path):
    ifc = ifcopenshell.file(schema="IFC4")
    placement = ifc.create_entity("IfcLocalPlacement")
    placement.PlacementRelTo = placement
    ifc_path, db_path = _write_sqlite(ifc, tmp_path, "self-placement")
    return ifcopenshell.open(ifc_path), ifcopenshell.open(db_path), placement.id()


def _property_self_list(tmp_path: Path):
    ifc = ifcopenshell.file(schema="IFC4")
    prop = ifc.create_entity("IfcComplexProperty", Name="cycle", UsageName="usage")
    prop.HasProperties = (prop,)
    ifc_path, db_path = _write_sqlite(ifc, tmp_path, "property-self")
    return ifcopenshell.open(ifc_path), ifcopenshell.open(db_path), prop.id()


def _wide_properties(tmp_path: Path, cyclic: bool):
    """Root lists two properties, and each branch continues two steps further.

    ``max_levels`` is one shared counter, decremented once per popped entity,
    not a depth. The branch popped second is therefore expanded past the limit.
    With ``cyclic``, that second property lists itself, so the counter going
    negative also fails to stop the cycle.
    """
    ifc = ifcopenshell.file(schema="IFC4")

    def make(name):
        return ifc.create_entity("IfcComplexProperty", Name=name, UsageName="usage")

    root = make("root")
    left = make("left")
    right = make("right")
    left_child = make("left-child")
    right_child = make("right-child")
    left_grandchild = make("left-grandchild")
    right_grandchild = make("right-grandchild")
    left_child.HasProperties = (left_grandchild,)
    left.HasProperties = (left_child,)
    if cyclic:
        right.HasProperties = (right,)
    else:
        right_child.HasProperties = (right_grandchild,)
        right.HasProperties = (right_child,)
    # Listed second so the left branch is popped first and spends the shared
    # counter before the right branch is expanded.
    root.HasProperties = (right, left)
    ifc_path, db_path = _write_sqlite(ifc, tmp_path, "wide-cyclic" if cyclic else "wide-acyclic")
    return ifcopenshell.open(ifc_path), ifcopenshell.open(db_path), root.id()


def _mapped_representation(tmp_path: Path):
    """Shape representation whose mapped item points back at that representation.

    This is the graph ``tool.Geometry.get_ifc_representation_class`` walks with
    ``file.traverse(representation)`` and no depth limit.
    """
    ifc = ifcopenshell.file(schema="IFC4")
    wall = ifc.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="Wall")
    context = ifc.create_entity("IfcGeometricRepresentationContext", ContextType="Model")
    body = ifc.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=context,
        RepresentationIdentifier="Body",
        RepresentationType="MappedRepresentation",
    )
    origin = ifc.create_entity("IfcAxis2Placement3D")
    mapping = ifc.create_entity("IfcRepresentationMap", MappingOrigin=origin, MappedRepresentation=body)
    operator = ifc.create_entity("IfcCartesianTransformationOperator3D")
    mapped = ifc.create_entity("IfcMappedItem", MappingSource=mapping, MappingTarget=operator)
    body.Items = (mapped,)
    shape = ifc.create_entity("IfcProductDefinitionShape", Representations=(body,))
    wall.Representation = shape
    unrelated = ifc.create_entity("IfcPerson", Identification="not-in-the-representation")
    ifc_path, db_path = _write_sqlite(ifc, tmp_path, "mapped-representation")
    memory = ifcopenshell.open(ifc_path)
    sqlite_file = ifcopenshell.open(db_path)
    return memory, sqlite_file, wall.id(), body.id(), unrelated.id()


class TestSqliteTraverseCycles:
    def test_mutual_placement_matches_memory_file(self, tmp_path):
        memory, sqlite_file, start_id, unrelated_id = _placement_cycle(tmp_path)
        got = _run(lambda: sqlite_file.traverse(sqlite_file.by_id(start_id)))
        _assert_same_ids(got, memory.traverse(memory.by_id(start_id)))
        assert unrelated_id not in _ids(got)

    def test_mutual_placement_breadth_first_matches_memory_file(self, tmp_path):
        memory, sqlite_file, start_id, _unrelated_id = _placement_cycle(tmp_path)
        got = _run(lambda: sqlite_file.traverse(sqlite_file.by_id(start_id), breadth_first=True))
        _assert_same_ids(got, memory.traverse(memory.by_id(start_id), breadth_first=True))

    def test_self_placement_matches_memory_file(self, tmp_path):
        memory, sqlite_file, start_id = _self_placement(tmp_path)
        got = _run(lambda: sqlite_file.traverse(sqlite_file.by_id(start_id)))
        _assert_same_ids(got, memory.traverse(memory.by_id(start_id)))

    def test_self_list_matches_memory_file(self, tmp_path):
        memory, sqlite_file, start_id = _property_self_list(tmp_path)
        got = _run(lambda: sqlite_file.traverse(sqlite_file.by_id(start_id)))
        _assert_same_ids(got, memory.traverse(memory.by_id(start_id)))

    def test_self_list_at_one_level_records_the_entity_once(self, tmp_path):
        memory, sqlite_file, start_id = _property_self_list(tmp_path)
        got = _run(lambda: sqlite_file.traverse(sqlite_file.by_id(start_id), max_levels=1))
        _assert_same_ids(got, memory.traverse(memory.by_id(start_id), max_levels=1))

    def test_unlimited_sentinels_stay_finite(self, tmp_path):
        memory, sqlite_file, start_id, _unrelated_id = _placement_cycle(tmp_path)
        for max_levels in (0, -1):
            got = _run(lambda level=max_levels: sqlite_file.traverse(sqlite_file.by_id(start_id), max_levels=level))
            _assert_same_ids(got, memory.traverse(memory.by_id(start_id), max_levels=max_levels))

    def test_depth_limit_on_a_wide_graph_matches_memory_file(self, tmp_path):
        memory, sqlite_file, start_id = _wide_properties(tmp_path, cyclic=False)
        got = _run(lambda: sqlite_file.traverse(sqlite_file.by_id(start_id), max_levels=2))
        _assert_same_ids(got, memory.traverse(memory.by_id(start_id), max_levels=2))

    def test_depth_limit_stops_a_cycle_on_a_later_branch(self, tmp_path):
        memory, sqlite_file, start_id = _wide_properties(tmp_path, cyclic=True)
        got = _run(lambda: sqlite_file.traverse(sqlite_file.by_id(start_id), max_levels=2))
        _assert_same_ids(got, memory.traverse(memory.by_id(start_id), max_levels=2))

    def test_mapped_representation_walk_matches_reachable_entities(self, tmp_path):
        memory, sqlite_file, _wall_id, body_id, unrelated_id = _mapped_representation(tmp_path)
        body = sqlite_file.by_id(body_id)
        # Same filter as bonsai.tool.geometry.Geometry.get_ifc_representation_class.
        solids = _run(
            lambda: [entity for entity in sqlite_file.traverse(body) if entity.is_a() == "IfcExtrudedAreaSolid"]
        )
        assert solids == []
        got = _run(lambda: sqlite_file.traverse(body))
        got_ids = _ids(got)
        assert len(got_ids) == len(set(got_ids))
        assert unrelated_id not in got_ids
        # Select-typed attributes (for example IfcAxis2Placement) are not in
        # sqlite's reference list, so the result is the forward closure of the
        # references this backend already follows, and no more than the C++ walk.
        reachable = set(_ids(memory.traverse(memory.by_id(body_id))))
        assert set(got_ids) <= reachable
        assert {body_id, body.Items[0].id(), body.Items[0].MappingSource.id()} <= set(got_ids)

    def test_get_layers_on_a_cyclic_representation_returns(self, tmp_path):
        _memory, sqlite_file, wall_id, _body_id, _unrelated_id = _mapped_representation(tmp_path)
        wall = sqlite_file.by_id(wall_id)
        layers = _run(lambda: ifcopenshell.util.element.get_layers(sqlite_file, wall))
        assert layers == []


class TestStreamTraverseCycles:
    def test_mutual_placement_matches_memory_file(self, tmp_path):
        ifc = ifcopenshell.file(schema="IFC4")
        first = ifc.create_entity("IfcLocalPlacement")
        second = ifc.create_entity("IfcLocalPlacement")
        first.PlacementRelTo = second
        second.PlacementRelTo = first
        ifc_path = tmp_path / "placement-cycle.ifc"
        ifc.write(ifc_path)
        memory = ifcopenshell.open(ifc_path)
        stream = ifcopenshell.open(ifc_path, should_stream=True)
        got = _run(lambda: stream.traverse(stream.by_id(first.id())))
        _assert_same_ids(got, memory.traverse(memory.by_id(first.id())))

    def test_self_list_matches_memory_file(self, tmp_path):
        ifc = ifcopenshell.file(schema="IFC4")
        prop = ifc.create_entity("IfcComplexProperty", Name="cycle", UsageName="usage")
        prop.HasProperties = (prop,)
        ifc_path = tmp_path / "property-self.ifc"
        ifc.write(ifc_path)
        memory = ifcopenshell.open(ifc_path)
        stream = ifcopenshell.open(ifc_path, should_stream=True)
        got = _run(lambda: stream.traverse(stream.by_id(prop.id())))
        _assert_same_ids(got, memory.traverse(memory.by_id(prop.id())))

    def test_depth_limit_on_a_wide_graph_matches_memory_file(self, tmp_path):
        memory, _sqlite_file, start_id = _wide_properties(tmp_path, cyclic=False)
        ifc_path = tmp_path / "wide-acyclic.ifc"
        stream = ifcopenshell.open(ifc_path, should_stream=True)
        got = _run(lambda: stream.traverse(stream.by_id(start_id), max_levels=2))
        _assert_same_ids(got, memory.traverse(memory.by_id(start_id), max_levels=2))

    def test_depth_limit_stops_a_cycle_on_a_later_branch(self, tmp_path):
        memory, _sqlite_file, start_id = _wide_properties(tmp_path, cyclic=True)
        ifc_path = tmp_path / "wide-cyclic.ifc"
        stream = ifcopenshell.open(ifc_path, should_stream=True)
        got = _run(lambda: stream.traverse(stream.by_id(start_id), max_levels=2))
        _assert_same_ids(got, memory.traverse(memory.by_id(start_id), max_levels=2))
