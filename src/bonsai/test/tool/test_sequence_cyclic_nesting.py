# This file was generated with the assistance of an AI coding tool.
# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 IfcOpenShell contributors
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

import datetime
import os
import tempfile

import ifcopenshell
import ifcopenshell.api.sequence
import ifcopenshell.util.sequence

import bonsai.core.sequence as core
import bonsai.tool as tool
from test.bim.bootstrap import NewFile


class TestCyclicWorkScheduleTasks(NewFile):
    def test_linear_nest_still_expands(self):
        model, schedule = self._model_with_schedule()
        parent = self._task(model, "Parent")
        child = self._task(model, "Child")
        self._assign(model, schedule, [parent])
        self._nest(model, parent, [child])

        model = self._reopen_and_activate(model)
        schedule = model.by_type("IfcWorkSchedule")[0]
        parent = self._by_name(model, "Parent")
        child = self._by_name(model, "Child")
        core.enable_editing_work_schedule_tasks(tool.Sequence, work_schedule=schedule)

        assert self._rows() == [("Parent", 0, parent.id()), ("Child", 1, child.id())]

    def test_enable_editing_mutual_cycle_lists_each_task_once(self):
        model, schedule, tasks = self._mutual_cycle()
        core.enable_editing_work_schedule_tasks(tool.Sequence, work_schedule=schedule)

        assert self._rows() == [("A", 0, tasks["A"].id()), ("B", 1, tasks["B"].id())]
        assert max(level for _, level, _ in self._rows()) == 1

    def test_enable_editing_self_cycle_lists_the_task_once(self):
        model, schedule = self._model_with_schedule()
        task = self._task(model, "Loop")
        self._assign(model, schedule, [task])
        self._nest(model, task, [task])

        model = self._reopen_and_activate(model)
        schedule = model.by_type("IfcWorkSchedule")[0]
        task = self._by_name(model, "Loop")
        core.enable_editing_work_schedule_tasks(tool.Sequence, work_schedule=schedule)

        assert self._rows() == [("Loop", 0, task.id())]

    def test_enable_editing_three_task_cycle(self):
        model, schedule = self._model_with_schedule()
        first, second, third = (self._task(model, name) for name in ("A", "B", "C"))
        self._assign(model, schedule, [first])
        self._nest(model, first, [second])
        self._nest(model, second, [third])
        self._nest(model, third, [first])

        model = self._reopen_and_activate(model)
        schedule = model.by_type("IfcWorkSchedule")[0]
        tasks = {name: self._by_name(model, name) for name in ("A", "B", "C")}
        core.enable_editing_work_schedule_tasks(tool.Sequence, work_schedule=schedule)

        assert self._rows() == [
            ("A", 0, tasks["A"].id()),
            ("B", 1, tasks["B"].id()),
            ("C", 2, tasks["C"].id()),
        ]

    def test_enable_editing_cycle_below_the_root(self):
        model, schedule = self._model_with_schedule()
        root, left, right = (self._task(model, name) for name in ("Root", "Left", "Right"))
        self._assign(model, schedule, [root])
        self._nest(model, root, [left])
        self._nest(model, left, [right])
        self._nest(model, right, [left])

        model = self._reopen_and_activate(model)
        schedule = model.by_type("IfcWorkSchedule")[0]
        names = ("Root", "Left", "Right")
        tasks = {name: self._by_name(model, name) for name in names}
        core.enable_editing_work_schedule_tasks(tool.Sequence, work_schedule=schedule)

        assert self._rows() == [
            ("Root", 0, tasks["Root"].id()),
            ("Left", 1, tasks["Left"].id()),
            ("Right", 2, tasks["Right"].id()),
        ]

    def test_enable_editing_cycle_that_returns_to_a_middle_task(self):
        model, schedule = self._model_with_schedule()
        first, second, third = (self._task(model, name) for name in ("A", "B", "C"))
        self._assign(model, schedule, [first])
        self._nest(model, first, [second])
        self._nest(model, second, [third])
        self._nest(model, third, [second])

        model = self._reopen_and_activate(model)
        schedule = model.by_type("IfcWorkSchedule")[0]
        tasks = {name: self._by_name(model, name) for name in ("A", "B", "C")}
        core.enable_editing_work_schedule_tasks(tool.Sequence, work_schedule=schedule)

        assert self._rows() == [
            ("A", 0, tasks["A"].id()),
            ("B", 1, tasks["B"].id()),
            ("C", 2, tasks["C"].id()),
        ]

    def test_enable_editing_dated_cycle_still_loads_dates(self):
        model, schedule, tasks = self._mutual_cycle(with_task_time=True)
        core.enable_editing_work_schedule_tasks(tool.Sequence, work_schedule=schedule)

        assert [name for name, _, _ in self._rows()] == ["A", "B"]
        props = tool.Sequence.get_task_tree_props()
        assert props.tasks[0].start not in {"", "-"}
        assert props.tasks[0].finish not in {"", "-"}
        assert props.tasks[0].calendar == ""

    def test_diamond_nest_still_reaches_the_shared_child(self):
        model, schedule = self._model_with_schedule()
        root, left, right, shared = (self._task(model, name) for name in ("Root", "Left", "Right", "Shared"))
        self._assign(model, schedule, [root])
        self._nest(model, root, [left, right])
        self._nest(model, left, [shared])
        self._nest(model, right, [shared])

        model = self._reopen_and_activate(model)
        schedule = model.by_type("IfcWorkSchedule")[0]
        core.enable_editing_work_schedule_tasks(tool.Sequence, work_schedule=schedule)

        names = [name for name, _, _ in self._rows()]
        assert names[0] == "Root"
        assert set(names) == {"Root", "Left", "Right", "Shared"}
        assert len(names) <= 5
        assert names.count("Shared") >= 1
        assert names.count("Shared") <= 2
        assert max(level for _, level, _ in self._rows()) <= 2

    def test_expand_all_tasks_reloads_a_contracted_cycle(self):
        model, schedule, tasks = self._mutual_cycle()
        props = tool.Sequence.get_work_schedule_props()
        props.active_work_schedule_id = schedule.id()
        props.contracted_tasks = f"[{tasks['A'].id()}]"
        core.load_task_tree(tool.Sequence, work_schedule=schedule)
        assert [name for name, _, _ in self._rows()] == ["A"]

        core.expand_all_tasks(tool.Sequence)

        assert self._rows() == [("A", 0, tasks["A"].id()), ("B", 1, tasks["B"].id())]

    def test_second_schedule_still_loads_after_a_cycle(self):
        model, schedule, _tasks = self._mutual_cycle()
        core.enable_editing_work_schedule_tasks(tool.Sequence, work_schedule=schedule)

        other, other_schedule = self._model_with_schedule()
        parent = self._task(other, "Later")
        child = self._task(other, "After")
        self._assign(other, other_schedule, [parent])
        self._nest(other, parent, [child])
        other = self._reopen_and_activate(other)
        other_schedule = other.by_type("IfcWorkSchedule")[0]
        parent = self._by_name(other, "Later")
        child = self._by_name(other, "After")
        core.enable_editing_work_schedule_tasks(tool.Sequence, work_schedule=other_schedule)

        assert self._rows() == [("Later", 0, parent.id()), ("After", 1, child.id())]

    def test_create_tasks_json_stops_on_a_cycle(self):
        _model, schedule, tasks = self._mutual_cycle()
        payload = tool.Sequence.create_tasks_json(schedule)

        assert [item["pID"] for item in payload] == [tasks["A"].id(), tasks["B"].id()]

    def test_process_construction_state_stops_on_a_cycle(self):
        _model, schedule, _tasks = self._mutual_cycle()
        state = tool.Sequence.process_construction_state(schedule, datetime.datetime(2020, 1, 1))

        assert set(state) == {
            "TO_BUILD",
            "IN_CONSTRUCTION",
            "COMPLETED",
            "TO_DEMOLISH",
            "IN_DEMOLITION",
            "DEMOLISHED",
        }
        assert all(len(products) == 0 for products in state.values())

    def test_guess_date_range_stops_on_a_cycle(self):
        _model, schedule, _tasks = self._mutual_cycle()
        core.guess_date_range(tool.Sequence, work_schedule=schedule)

    def test_go_to_task_stops_on_a_cycle(self):
        _model, schedule, tasks = self._mutual_cycle()
        props = tool.Sequence.get_work_schedule_props()
        props.active_work_schedule_id = schedule.id()

        assert core.go_to_task(tool.Sequence, tasks["B"]) is None
        assert self._rows() == [("A", 0, tasks["A"].id()), ("B", 1, tasks["B"].id())]
        tree = tool.Sequence.get_task_tree_props()
        assert tree.tasks[props.active_task_index].ifc_definition_id == tasks["B"].id()

    def test_select_schedule_products_stops_on_a_cycle(self):
        _model, schedule, _tasks = self._mutual_cycle()
        assert tool.Sequence.get_work_schedule_products(schedule) == []

    def test_task_work_schedule_lookup_stops_on_a_cycle(self):
        _model, schedule, tasks = self._mutual_cycle()
        assert ifcopenshell.util.sequence.get_task_work_schedule(tasks["B"]) == schedule
        assert ifcopenshell.util.sequence.get_task_work_schedule(tasks["A"]) == schedule

    def test_sequence_assignment_lookup_stops_on_a_cycle(self):
        _model, _schedule, tasks = self._mutual_cycle()
        assert ifcopenshell.util.sequence.get_sequence_assignment(tasks["B"], "predecessor") == []
        assert ifcopenshell.util.sequence.get_sequence_assignment(tasks["A"], "successor") == []

    def test_recalculate_schedule_stops_on_a_cycle(self):
        model, schedule, _tasks = self._mutual_cycle()
        assert core.recalculate_schedule(tool.Ifc, work_schedule=schedule) is None
        assert model.by_type("IfcTask")

    def test_cascade_schedule_does_not_recurse_without_bound(self):
        _model, _schedule, tasks = self._mutual_cycle(with_task_time=True)
        try:
            ifcopenshell.api.sequence.cascade_schedule(tasks["A"].file, task=tasks["A"])
        except RecursionError as exc:
            assert "Recursive tasks found" in str(exc)

    def test_ifc4x3_enable_editing_mutual_cycle(self):
        model, schedule, tasks = self._mutual_cycle(schema="IFC4X3_ADD2")
        core.enable_editing_work_schedule_tasks(tool.Sequence, work_schedule=schedule)
        assert self._rows() == [("A", 0, tasks["A"].id()), ("B", 1, tasks["B"].id())]

    def _mutual_cycle(self, schema="IFC4", with_task_time=False):
        model, schedule = self._model_with_schedule(schema)
        first = self._task(model, "A")
        second = self._task(model, "B")
        if with_task_time:
            for task, start in ((first, "2020-01-01T09:00:00"), (second, "2020-01-02T09:00:00")):
                task.TaskTime = model.create_entity(
                    "IfcTaskTime",
                    ScheduleStart=start,
                    ScheduleFinish="2020-01-03T17:00:00",
                    ScheduleDuration="P1D",
                    DurationType="ELAPSEDTIME",
                )
        self._assign(model, schedule, [first])
        self._nest(model, first, [second])
        self._nest(model, second, [first])
        model = self._reopen_and_activate(model)
        schedule = model.by_type("IfcWorkSchedule")[0]
        tasks = {name: self._by_name(model, name) for name in ("A", "B")}
        return model, schedule, tasks

    def _model_with_schedule(self, schema="IFC4"):
        model = ifcopenshell.file(schema=schema)
        schedule = model.create_entity("IfcWorkSchedule", Name="Cycle schedule")
        return model, schedule

    def _task(self, model, name):
        return model.create_entity("IfcTask", Name=name)

    def _assign(self, model, schedule, tasks):
        model.create_entity("IfcRelAssignsToControl", RelatingControl=schedule, RelatedObjects=list(tasks))

    def _nest(self, model, parent, children):
        model.create_entity("IfcRelNests", RelatingObject=parent, RelatedObjects=list(children))

    def _reopen_and_activate(self, model):
        descriptor, path = tempfile.mkstemp(suffix=".ifc")
        os.close(descriptor)
        try:
            model.write(path)
            reopened = ifcopenshell.open(path)
        finally:
            os.unlink(path)
        tool.Ifc.set(reopened)
        props = tool.Sequence.get_work_schedule_props()
        props.contracted_tasks = "[]"
        props.task_bars = "[]"
        props.sort_column = ""
        props.highlighted_task_id = 0
        props.active_work_schedule_id = 0
        props.is_task_update_enabled = True
        return reopened

    def _by_name(self, model, name):
        return next(task for task in model.by_type("IfcTask") if task.Name == name)

    def _rows(self):
        return [
            (item.name, item.level_index, item.ifc_definition_id) for item in tool.Sequence.get_task_tree_props().tasks
        ]
