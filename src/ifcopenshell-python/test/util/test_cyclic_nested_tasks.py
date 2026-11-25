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

"""Cyclic IfcRelNests must not exhaust the stack while scheduling.

An IFC file can contain two IfcRelNests relationships that point at each
other. Opening that file does not reject the cycle. These tests reload such
a file and run the schedule walks that Bonsai and the sequence API use.

The walks must finish and still return every nested task, product, resource,
and stored schedule date. A task that is already on the stack is not visited
again, and a sibling listed after that back-edge still is.
"""

import ast
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.nest
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.sequence
import ifcopenshell.util.date
import ifcopenshell.util.sequence as subject


def _bonsai_get_work_schedule_products():
    """Compile Bonsai's product collector from its source file.

    The Bonsai tool module imports Blender, so the test executes the function
    body that Select Work Schedule Products calls, taken from that file.
    """
    path = Path(__file__).resolve().parents[3] / "bonsai" / "bonsai" / "tool" / "sequence.py"
    tree = ast.parse(path.read_text())
    function = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Sequence":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "get_work_schedule_products":
                    function = item
                    break
    assert function is not None
    function.decorator_list = []
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"ifcopenshell": ifcopenshell}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace["get_work_schedule_products"]


def _write_and_open(model, path):
    model.write(path)
    return ifcopenshell.open(path)


def _tasks_by_name(model):
    return {task.Name: task for task in model.by_type("IfcTask")}


def _build_schedule(tmp_path, close_cycle):
    """Work schedule whose root task nests a pair, with a leaf after the back-edge.

    A is the schedule root and nests B. B nests A and then C. C is the only
    task with stored schedule dates, and each task has its own product.
    """
    model = ifcopenshell.api.project.create_file()
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="P")
    schedule = ifcopenshell.api.sequence.add_work_schedule(model, name="Construction")
    task_a = ifcopenshell.api.sequence.add_task(model, work_schedule=schedule, name="A")
    task_b = ifcopenshell.api.sequence.add_task(model, parent_task=task_a, name="B")
    task_c = ifcopenshell.api.sequence.add_task(model, parent_task=task_b, name="C")
    task_time = ifcopenshell.api.sequence.add_task_time(model, task=task_c)
    ifcopenshell.api.sequence.edit_task_time(
        model,
        task_time=task_time,
        attributes={
            "ScheduleStart": "2020-02-01",
            "ScheduleDuration": "P5D",
            "DurationType": "ELAPSEDTIME",
        },
    )
    for name, task in (("input-on-a", task_a), ("input-on-b", task_b), ("input-on-c", task_c)):
        wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name=name)
        ifcopenshell.api.sequence.assign_process(model, relating_process=task, related_object=wall)
    output = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="output-on-b")
    ifcopenshell.api.sequence.assign_product(model, relating_product=output, related_object=task_b)
    crew = ifcopenshell.api.root.create_entity(model, ifc_class="IfcLaborResource", name="crew")
    ifcopenshell.api.sequence.assign_process(model, relating_process=task_b, related_object=crew)
    if close_cycle:
        ifcopenshell.api.nest.assign_object(model, related_objects=[task_a], relating_object=task_b)
        nest = task_b.IsNestedBy[0]
        nest.RelatedObjects = [task_a, task_c]
    reloaded = _write_and_open(model, tmp_path / ("cycle.ifc" if close_cycle else "tree.ifc"))
    tasks = _tasks_by_name(reloaded)
    schedule = reloaded.by_type("IfcWorkSchedule")[0]
    return reloaded, tasks, schedule


def _cyclic(tmp_path):
    model, tasks, schedule = _build_schedule(tmp_path, close_cycle=True)
    assert [task.Name for task in subject.get_nested_tasks(tasks["A"])] == ["B"]
    assert [task.Name for task in subject.get_nested_tasks(tasks["B"])] == ["A", "C"]
    assert subject.get_parent_task(tasks["A"]).Name == "B"
    assert subject.get_parent_task(tasks["B"]).Name == "A"
    assert [task.Name for task in subject.get_root_tasks(schedule)] == ["A"]
    return model, tasks, schedule


def _product_names(products):
    return sorted(product.Name for product in products)


class TestAcyclicNestedTasks:
    def test_recursive_inputs_include_every_nested_product(self, tmp_path):
        _model, tasks, _schedule = _build_schedule(tmp_path, close_cycle=False)
        assert _product_names(subject.get_task_inputs(tasks["A"], is_recursive=True)) == [
            "input-on-a",
            "input-on-b",
            "input-on-c",
        ]
        assert [task.Name for task in subject.get_all_nested_tasks(tasks["A"])] == ["B", "C"]


class TestCyclicNestedTasks:
    def test_nested_walk_yields_each_task_once_including_the_sibling_after_the_back_edge(self, tmp_path):
        _model, tasks, schedule = _cyclic(tmp_path)
        assert [task.Name for task in subject.get_all_nested_tasks(tasks["A"])] == ["B", "C"]
        assert [task.Name for task in subject.get_work_schedule_tasks(schedule)] == ["A", "B", "C"]

    def test_recursive_task_assignment_walks_return_products_and_resources(self, tmp_path):
        _model, tasks, _schedule = _cyclic(tmp_path)
        root = tasks["A"]
        assert _product_names(subject.get_task_inputs(root, is_recursive=True)) == [
            "input-on-a",
            "input-on-b",
            "input-on-c",
        ]
        assert _product_names(subject.get_task_outputs(root, is_recursive=True)) == ["output-on-b"]
        assert _product_names(subject.get_task_resources(root, is_recursive=True)) == ["crew"]

    def test_work_schedule_product_selection_returns_inputs_and_outputs(self, tmp_path):
        _model, _tasks, schedule = _cyclic(tmp_path)
        products = _bonsai_get_work_schedule_products()(None, schedule)
        assert _product_names(products) == [
            "input-on-a",
            "input-on-b",
            "input-on-c",
            "output-on-b",
        ]

    def test_date_derivation_returns_dates_stored_behind_the_cycle(self, tmp_path):
        _model, tasks, schedule = _cyclic(tmp_path)
        leaf_time = tasks["C"].TaskTime
        earliest = ifcopenshell.util.date.ifc2datetime(leaf_time.ScheduleStart)
        latest = ifcopenshell.util.date.ifc2datetime(leaf_time.ScheduleFinish)
        assert subject.derive_date(tasks["A"], "ScheduleStart", is_earliest=True) == earliest
        assert subject.derive_date(tasks["A"], "ScheduleFinish", is_latest=True) == latest
        assert subject.derive_date(tasks["B"], "ScheduleStart", is_earliest=True) == earliest
        assert subject.guess_date_range(schedule) == (earliest, latest)

    def test_parent_walks_stop_on_the_cycle(self, tmp_path):
        _model, tasks, schedule = _cyclic(tmp_path)
        assert subject.derive_calendar(tasks["A"]) is None
        assert subject.derive_calendar(tasks["C"]) is None
        assert subject.get_task_work_schedule(tasks["A"]) == schedule
        assert subject.get_task_work_schedule(tasks["C"]) == schedule
        assert list(subject.get_sequence_assignment(tasks["C"]) or []) == []

    def test_editing_task_time_on_a_cyclic_task_stores_the_start(self, tmp_path):
        model, tasks, _schedule = _cyclic(tmp_path)
        task_time = ifcopenshell.api.sequence.add_task_time(model, task=tasks["A"])
        ifcopenshell.api.sequence.edit_task_time(model, task_time=task_time, attributes={"ScheduleStart": "2020-03-01"})
        assert task_time.ScheduleStart == "2020-03-01T09:00:00"

    def test_recalculate_schedule_reaches_the_leaf_behind_the_cycle(self, tmp_path):
        model, tasks, schedule = _cyclic(tmp_path)
        stored_start = tasks["C"].TaskTime.ScheduleStart
        ifcopenshell.api.sequence.recalculate_schedule(model, schedule)
        assert tasks["C"].TaskTime.EarlyStart == stored_start

    def test_duplicate_task_copies_each_task_in_the_cycle_once(self, tmp_path):
        model, tasks, _schedule = _cyclic(tmp_path)
        originals, copies = ifcopenshell.api.sequence.duplicate_task(model, tasks["A"])
        assert [task.Name for task in originals] == ["A", "B", "C"]
        assert [task.Name for task in copies] == ["A", "B", "C"]
        assert len(model.by_type("IfcTask")) == 6


class TestSelfNestedTask:
    def test_task_that_nests_itself_still_reports_its_products(self, tmp_path):
        model = ifcopenshell.api.project.create_file()
        ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="P")
        schedule = ifcopenshell.api.sequence.add_work_schedule(model, name="Construction")
        task = ifcopenshell.api.sequence.add_task(model, work_schedule=schedule, name="Self")
        wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="self-wall")
        ifcopenshell.api.sequence.assign_process(model, relating_process=task, related_object=wall)
        ifcopenshell.api.nest.assign_object(model, related_objects=[task], relating_object=task)
        reloaded = _write_and_open(model, tmp_path / "self.ifc")
        task = reloaded.by_type("IfcTask")[0]
        schedule = reloaded.by_type("IfcWorkSchedule")[0]
        assert [nested.Name for nested in subject.get_nested_tasks(task)] == ["Self"]
        assert list(subject.get_all_nested_tasks(task)) == []
        assert _product_names(subject.get_task_inputs(task, is_recursive=True)) == ["self-wall"]
        assert [item.Name for item in subject.get_work_schedule_tasks(schedule)] == ["Self"]
        products = _bonsai_get_work_schedule_products()(None, schedule)
        assert _product_names(products) == ["self-wall"]
