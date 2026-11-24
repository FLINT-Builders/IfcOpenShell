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

"""Recursive group and aggregate walks must finish on cyclic models.

An IFC file can assign two groups to each other, or aggregate two elements
through each other, without either relationship pointing at itself. Opening
that file is enough to reach these walks: Bonsai's project importer calls
``get_grouped_by`` for every ``IfcGroup`` named ``BBIM_Linked_Aggregate``, and
Ifc2CA calls it for structural models and load groups. ``get_decomposition``
walks aggregate cycles the same way.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.element as element_util

TIMEOUT_SECONDS = 2
PACKAGE_ROOT = Path(__file__).resolve().parents[2]


def _new(file: ifcopenshell.file, ifc_class: str, **kwargs) -> ifcopenshell.entity_instance:
    kwargs.setdefault("GlobalId", ifcopenshell.guid.new())
    return file.create_entity(ifc_class, **kwargs)


def _model(schema: str = "IFC4") -> ifcopenshell.file:
    file = ifcopenshell.file(schema=schema)
    _new(file, "IfcProject", Name="Project")
    return file


def _assign(file: ifcopenshell.file, group, products: list) -> ifcopenshell.entity_instance:
    return _new(file, "IfcRelAssignsToGroup", RelatingGroup=group, RelatedObjects=products)


def _aggregate(file: ifcopenshell.file, whole, parts: list) -> ifcopenshell.entity_instance:
    return _new(file, "IfcRelAggregates", RelatingObject=whole, RelatedObjects=parts)


@contextmanager
def _saved(file: ifcopenshell.file):
    handle = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
    handle.close()
    file.write(handle.name)
    try:
        yield handle.name
    finally:
        os.unlink(handle.name)


def _assert_bounded(found: list[int], required: set[int], allowed: set[int]) -> None:
    assert len(found) == len(set(found))
    assert required <= set(found) <= allowed
    assert len(found) <= len(allowed)


def _run(path: str, payload: dict) -> dict:
    request = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    request.write(json.dumps({"path": path, **payload}).encode())
    request.close()
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(PACKAGE_ROOT), env.get("PYTHONPATH", "")])
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", request.name],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            env=env,
            cwd=str(PACKAGE_ROOT),
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{payload['fn']} did not return within {TIMEOUT_SECONDS}s")
    finally:
        os.unlink(request.name)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _worker() -> None:
    payload = json.loads(Path(sys.argv[2]).read_text())
    file = ifcopenshell.open(payload["path"])
    before = file.to_string()
    fn = payload["fn"]
    if fn == "linked_aggregates":
        # Same selection and call as IfcImporter.update_linked_aggregates.
        targets = [group for group in file.by_type("IfcGroup") if group.Name == "BBIM_Linked_Aggregate"]
        assert targets
        body = []
        for group in targets:
            members = element_util.get_grouped_by(file.by_id(group.id()), is_recursive=True)
            body.append({"group_id": group.id(), "ids": [member.id() for member in members]})
    elif fn == "get_grouped_by":
        element = file.by_id(payload["element_id"])
        if "recursive" in payload:
            members = element_util.get_grouped_by(element, is_recursive=payload["recursive"])
        else:
            # Ifc2CA passes the model or load group through with the default.
            members = element_util.get_grouped_by(element)
        body = [member.id() for member in members]
    elif fn == "get_decomposition":
        members = element_util.get_decomposition(file.by_id(payload["element_id"]), is_recursive=True)
        body = [member.id() for member in members]
    else:
        raise AssertionError(fn)
    if file.to_string() != before:
        raise SystemExit("traversal changed the model")
    json.dump(body, sys.stdout)


def test_parser_keeps_a_mutual_group_cycle_in_a_project():
    file = _model()
    first = _new(file, "IfcGroup", Name="BBIM_Linked_Aggregate")
    second = _new(file, "IfcGroup", Name="Other")
    wall = _new(file, "IfcWall", Name="Wall_0")
    first_rel = _assign(file, first, [second])
    second_rel = _assign(file, second, [first])
    _assign(file, first, [wall])
    with _saved(file) as path:
        opened = ifcopenshell.open(path)
        assert opened.by_type("IfcProject")
        reopened_first = opened.by_id(first.id())
        reopened_second = opened.by_id(second.id())
        assert reopened_first.Name == "BBIM_Linked_Aggregate"
        assigned = [rel.RelatedObjects for rel in reopened_first.IsGroupedBy]
        assert any(reopened_second in objects for objects in assigned)
        assert any(opened.by_id(wall.id()) in objects for objects in assigned)
        assert all(rel.RelatingGroup not in rel.RelatedObjects for rel in (first_rel, second_rel))
        assert reopened_first in reopened_second.IsGroupedBy[0].RelatedObjects


def test_linked_aggregate_import_returns_each_member_once():
    file = _model()
    plain = _new(file, "IfcGroup", Name="BBIM_Linked_Aggregate")
    wall = _new(file, "IfcWall", Name="Wall_0")
    _assign(file, plain, [wall])
    cyclic = _new(file, "IfcGroup", Name="BBIM_Linked_Aggregate")
    other = _new(file, "IfcGroup", Name="Other")
    door = _new(file, "IfcDoor", Name="Door_0")
    _assign(file, cyclic, [other])
    _assign(file, other, [cyclic, door])
    with _saved(file) as path:
        reports = _run(path, {"fn": "linked_aggregates"})
    by_group = {report["group_id"]: report["ids"] for report in reports}
    _assert_bounded(by_group[plain.id()], {wall.id()}, {wall.id()})
    _assert_bounded(by_group[cyclic.id()], {other.id(), door.id()}, {cyclic.id(), other.id(), door.id()})


def test_self_assigned_group_returns_each_member_once():
    file = _model()
    group = _new(file, "IfcGroup", Name="BBIM_Linked_Aggregate")
    wall = _new(file, "IfcWall", Name="Wall_0")
    _assign(file, group, [group, wall])
    with _saved(file) as path:
        found = _run(path, {"fn": "get_grouped_by", "element_id": group.id(), "recursive": True})
    _assert_bounded(found, {wall.id()}, {group.id(), wall.id()})


def test_three_group_cycle_reaches_the_far_member_once():
    file = _model()
    first = _new(file, "IfcGroup", Name="BBIM_Linked_Aggregate")
    second = _new(file, "IfcGroup", Name="Second")
    third = _new(file, "IfcGroup", Name="Third")
    wall = _new(file, "IfcWall", Name="Wall_0")
    _assign(file, first, [second])
    _assign(file, second, [third])
    _assign(file, third, [first, wall])
    with _saved(file) as path:
        found = _run(path, {"fn": "get_grouped_by", "element_id": first.id(), "recursive": True})
    _assert_bounded(
        found,
        {second.id(), third.id(), wall.id()},
        {first.id(), second.id(), third.id(), wall.id()},
    )


def test_shared_product_is_returned_once():
    file = _model()
    parent = _new(file, "IfcGroup", Name="Parent")
    left = _new(file, "IfcGroup", Name="Left")
    right = _new(file, "IfcGroup", Name="Right")
    wall = _new(file, "IfcWall", Name="Wall_0")
    _assign(file, parent, [left, right])
    _assign(file, left, [wall])
    _assign(file, right, [wall])
    found = [element.id() for element in element_util.get_grouped_by(parent, is_recursive=True)]
    _assert_bounded(found, {left.id(), right.id(), wall.id()}, {left.id(), right.id(), wall.id()})


def test_nested_groups_still_return_descendants():
    file = _model()
    parent = _new(file, "IfcGroup", Name="Parent")
    child = _new(file, "IfcGroup", Name="Child")
    wall = _new(file, "IfcWall", Name="Wall_0")
    _assign(file, parent, [child])
    _assign(file, child, [wall])
    before = file.to_string()
    found = [element.id() for element in element_util.get_grouped_by(parent, is_recursive=True)]
    assert file.to_string() == before
    _assert_bounded(found, {child.id(), wall.id()}, {child.id(), wall.id()})


def test_nonrecursive_lookup_stops_at_direct_members():
    file = _model()
    first = _new(file, "IfcGroup", Name="BBIM_Linked_Aggregate")
    second = _new(file, "IfcGroup", Name="Other")
    wall = _new(file, "IfcWall", Name="Wall_0")
    _assign(file, first, [second, wall])
    _assign(file, second, [first])
    before = file.to_string()
    found = [element.id() for element in element_util.get_grouped_by(first, is_recursive=False)]
    assert file.to_string() == before
    _assert_bounded(found, {second.id(), wall.id()}, {second.id(), wall.id()})


def test_structural_model_cycle_returns_each_member_once():
    file = _model()
    model = _new(file, "IfcStructuralAnalysisModel", Name="Model")
    group = _new(file, "IfcGroup", Name="Grouped")
    wall = _new(file, "IfcWall", Name="Wall_0")
    _assign(file, model, [group])
    _assign(file, group, [model, wall])
    with _saved(file) as path:
        found = _run(path, {"fn": "get_grouped_by", "element_id": model.id()})
    _assert_bounded(found, {group.id(), wall.id()}, {model.id(), group.id(), wall.id()})


def test_load_group_cycle_returns_each_member_once():
    file = _model()
    first = _new(file, "IfcStructuralLoadGroup", Name="Case", PredefinedType="LOAD_GROUP")
    second = _new(file, "IfcStructuralLoadGroup", Name="Combo", PredefinedType="LOAD_COMBINATION")
    wall = _new(file, "IfcWall", Name="Wall_0")
    _assign(file, first, [second])
    _assign(file, second, [first, wall])
    with _saved(file) as path:
        found = _run(path, {"fn": "get_grouped_by", "element_id": first.id()})
    _assert_bounded(found, {second.id(), wall.id()}, {first.id(), second.id(), wall.id()})


def test_cyclic_aggregation_returns_each_part_once():
    file = _model()
    whole = _new(file, "IfcElementAssembly", Name="Whole")
    part = _new(file, "IfcElementAssembly", Name="Part")
    wall = _new(file, "IfcWall", Name="Wall_0")
    _aggregate(file, whole, [part])
    _aggregate(file, part, [whole, wall])
    with _saved(file) as path:
        found = _run(path, {"fn": "get_decomposition", "element_id": whole.id()})
    _assert_bounded(found, {part.id(), wall.id()}, {whole.id(), part.id(), wall.id()})


if __name__ == "__main__" and "--worker" in sys.argv:
    _worker()
