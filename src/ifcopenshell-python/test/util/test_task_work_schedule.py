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

"""Work-schedule lookup must finish for nested tasks that have no schedule.

``get_task_work_schedule`` currently calls itself again on the same task when
that task has a parent and the parent chain is not assigned to an
``IfcWorkSchedule``. These tests are the expected behaviour after that
recursion is removed. They fail while the recursion is still present.
"""

import pytest

import ifcopenshell
import ifcopenshell.api.control
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.sequence
import ifcopenshell.guid
import ifcopenshell.util.sequence as subject


@pytest.fixture(params=["IFC4", "IFC4X3"])
def model(request) -> ifcopenshell.file:
    ifc = ifcopenshell.api.project.create_file(version=request.param)
    ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject", name="Project")
    return ifc


def _schedule(ifc: ifcopenshell.file, name: str) -> ifcopenshell.entity_instance:
    return ifcopenshell.api.sequence.add_work_schedule(ifc, name=name)


def _task(ifc: ifcopenshell.file, name: str, **kwargs) -> ifcopenshell.entity_instance:
    return ifcopenshell.api.sequence.add_task(ifc, name=name, **kwargs)


def _wall(ifc: ifcopenshell.file, name: str) -> ifcopenshell.entity_instance:
    return ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall", name=name)


def _by_name(ifc: ifcopenshell.file, ifc_class: str, name: str) -> ifcopenshell.entity_instance:
    return next(element for element in ifc.by_type(ifc_class) if element.Name == name)


def _assign_schedule(ifc: ifcopenshell.file, schedule, task) -> None:
    ifcopenshell.api.control.assign_control(ifc, relating_control=schedule, related_objects=[task])


def test_unassigned_parent_is_not_a_work_schedule(model):
    parent = _task(model, "Parent")
    child = _task(model, "Child", parent_task=parent)

    assert subject.get_parent_task(child) == parent
    assert subject.get_task_work_schedule(child) is None
    assert subject.get_task_work_schedule(parent) is None


def test_ancestor_schedule_is_used_when_the_task_has_none(model):
    active = _schedule(model, "Active")
    root = _task(model, "Root", work_schedule=active)
    parent = _task(model, "Parent", parent_task=root)
    child = _task(model, "Child", parent_task=parent)

    assert subject.get_task_work_schedule(child) == active
    assert subject.get_task_work_schedule(parent) == active


def test_ancestor_schedule_wins_when_the_task_also_has_one(model):
    ancestor_schedule = _schedule(model, "Ancestor")
    own_schedule = _schedule(model, "Own")
    parent = _task(model, "Parent", work_schedule=ancestor_schedule)
    child = _task(model, "Child", parent_task=parent)
    _assign_schedule(model, own_schedule, child)

    assert subject.get_task_work_schedule(child) == ancestor_schedule


def test_task_schedule_is_used_when_no_ancestor_has_one(model):
    active = _schedule(model, "Active")
    parent = _task(model, "Parent")
    child = _task(model, "Child", parent_task=parent)
    _assign_schedule(model, active, child)

    assert subject.get_parent_task(child) == parent
    assert subject.get_task_work_schedule(parent) is None
    assert subject.get_task_work_schedule(child) == active


def test_deep_unassigned_chain_returns_none(model):
    parent = _task(model, "Level-0")
    task = parent
    for index in range(1, 64):
        task = _task(model, f"Level-{index}", parent_task=task)

    assert task.Name == "Level-63"
    assert subject.get_parent_task(task).Name == "Level-62"
    assert subject.get_task_work_schedule(task) is None
    assert subject.get_task_work_schedule(task) is None


def test_deep_chain_still_finds_the_root_schedule(model):
    active = _schedule(model, "Active")
    task = _task(model, "Level-0", work_schedule=active)
    for index in range(1, 64):
        task = _task(model, f"Level-{index}", parent_task=task)

    assert subject.get_task_work_schedule(task) == active


def test_cycle_without_a_schedule_returns_none(model):
    first = _task(model, "First")
    second = _task(model, "Second")
    model.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=first,
        RelatedObjects=[second],
    )
    model.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=second,
        RelatedObjects=[first],
    )

    assert subject.get_parent_task(first) == second
    assert subject.get_parent_task(second) == first
    assert subject.get_task_work_schedule(first) is None
    assert subject.get_task_work_schedule(second) is None


def test_cycle_still_finds_a_schedule_assigned_to_one_task(model):
    active = _schedule(model, "Active")
    first = _task(model, "First")
    second = _task(model, "Second")
    _assign_schedule(model, active, first)
    model.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=first,
        RelatedObjects=[second],
    )
    model.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=second,
        RelatedObjects=[first],
    )

    assert subject.get_parent_task(first) == second
    assert subject.get_parent_task(second) == first
    assert subject.get_task_work_schedule(first) == active
    assert subject.get_task_work_schedule(second) == active


def test_task_nested_under_itself_uses_its_own_schedule(model):
    active = _schedule(model, "Active")
    task = _task(model, "Loop")
    _assign_schedule(model, active, task)
    model.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=task,
        RelatedObjects=[task],
    )

    assert subject.get_parent_task(task) == task
    assert subject.get_task_work_schedule(task) == active


def test_filtering_product_inputs_skips_a_task_whose_parent_has_no_schedule(model, tmp_path):
    active = _schedule(model, "Active")
    parent = _task(model, "Parent")
    child = _task(model, "Child", parent_task=parent)
    wall = _wall(model, "Wall")
    ifcopenshell.api.sequence.assign_process(model, relating_process=child, related_object=wall)
    path = tmp_path / "unassigned-parent.ifc"
    model.write(path)

    opened = ifcopenshell.open(path)
    wall = _by_name(opened, "IfcWall", "Wall")
    child = _by_name(opened, "IfcTask", "Child")
    active = _by_name(opened, "IfcWorkSchedule", "Active")
    assert subject.get_parent_task(child).Name == "Parent"
    assert [assignment.RelatingProcess for assignment in wall.HasAssignments] == [child]

    inputs, outputs = subject.get_tasks_for_product(wall, active)

    assert inputs == []
    assert outputs == []


def test_filtering_product_outputs_skips_a_task_whose_parent_has_no_schedule(model, tmp_path):
    active = _schedule(model, "Active")
    parent = _task(model, "Parent")
    child = _task(model, "Child", parent_task=parent)
    wall = _wall(model, "Wall")
    ifcopenshell.api.sequence.assign_product(model, relating_product=wall, related_object=child)
    path = tmp_path / "unassigned-parent-output.ifc"
    model.write(path)

    opened = ifcopenshell.open(path)
    wall = _by_name(opened, "IfcWall", "Wall")
    child = _by_name(opened, "IfcTask", "Child")
    active = _by_name(opened, "IfcWorkSchedule", "Active")
    assert subject.get_parent_task(child).Name == "Parent"
    assert list(wall.ReferencedBy[0].RelatedObjects) == [child]

    inputs, outputs = subject.get_tasks_for_product(wall, active)

    assert inputs == []
    assert outputs == []


def test_filter_keeps_a_nested_task_of_the_active_schedule_and_drops_another(model):
    active = _schedule(model, "Active")
    other = _schedule(model, "Other")
    root = _task(model, "Root", work_schedule=active)
    matching = _task(model, "Matching", parent_task=root)
    parent = _task(model, "Parent")
    unrelated = _task(model, "Unrelated", parent_task=parent)
    _assign_schedule(model, other, unrelated)
    wall = _wall(model, "Wall")
    ifcopenshell.api.sequence.assign_process(model, relating_process=unrelated, related_object=wall)
    ifcopenshell.api.sequence.assign_process(model, relating_process=matching, related_object=wall)
    ifcopenshell.api.sequence.assign_product(model, relating_product=wall, related_object=unrelated)
    ifcopenshell.api.sequence.assign_product(model, relating_product=wall, related_object=matching)

    inputs, outputs = subject.get_tasks_for_product(wall, active)

    assert inputs == [matching]
    assert outputs == [matching]


def test_filter_drops_a_nested_task_assigned_only_to_another_schedule(model):
    active = _schedule(model, "Active")
    other = _schedule(model, "Other")
    parent = _task(model, "Parent", work_schedule=other)
    child = _task(model, "Child", parent_task=parent)
    wall = _wall(model, "Wall")
    ifcopenshell.api.sequence.assign_process(model, relating_process=child, related_object=wall)

    inputs, outputs = subject.get_tasks_for_product(wall, active)

    assert inputs == []
    assert outputs == []
    assert subject.get_tasks_for_product(wall, other)[0] == [child]
