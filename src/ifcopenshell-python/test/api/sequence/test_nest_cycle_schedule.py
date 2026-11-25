# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2022 Dion Moult <dion@thinkmoult.com>
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

"""Nesting cycles must not exhaust the stack while a schedule is calculated.

An IfcRelNests cycle is data in an IFC model. Opening that model and
recalculating its work schedule walks IfcTask.IsNestedBy and, for an activity
under the cycle, the parent chain via derive_calendar and
get_sequence_assignment. Those walks keep no visited set, so the stack is
exhausted before the sequence-link attempt limit, and float / critical flags
are never written.

The same missing visited set is reachable from cascade_schedule,
edit_task_time, calculate_task_duration, guess_date_range, and
get_task_work_schedule. These tests are the expected behaviour once a task
already seen is ignored. Sequence-link cycles still raise the existing
critical-path RecursionError and still do not write floats.

Bonsai walks the same nesting links again in tool.sequence
(create_new_task_li, create_new_task_json, process_task_status, and
get_animation_product_frames). Those need Blender and are not executed here.
"""

import datetime

import pytest

import ifcopenshell
import ifcopenshell.api.resource
import ifcopenshell.api.root
import ifcopenshell.api.sequence
import ifcopenshell.util.sequence
import test.bootstrap


class TestNestCycleSchedule(test.bootstrap.IFC4):
    def test_mutual_nest_does_not_exhaust_the_stack(self):
        self._add_work_schedule()
        root = ifcopenshell.api.sequence.add_task(self.file, work_schedule=self.work_schedule, name="root")
        summary = self._bare_task("summary")
        other = self._bare_task("other")
        # root nests summary, and summary and other nest each other.
        self._nest(root, [summary])
        self._nest(summary, [other])
        self._nest(other, [summary])
        self._set_time(summary, start="1999-06-01T09:00:00", duration="P5D", finish=None)

        assert ifcopenshell.api.sequence.recalculate_schedule(self.file, work_schedule=self.work_schedule) is None
        assert summary.TaskTime.ScheduleStart == "1999-06-01T09:00:00"
        assert summary.TaskTime.ScheduleDuration == "P5D"
        assert summary.TaskTime.IsCritical is None
        assert summary.TaskTime.TotalFloat is None
        assert summary.TaskTime.FreeFloat is None

    def test_self_nest_does_not_exhaust_the_stack(self):
        self._add_work_schedule()
        root = ifcopenshell.api.sequence.add_task(self.file, work_schedule=self.work_schedule, name="root")
        self._nest(root, [root])

        assert ifcopenshell.api.sequence.recalculate_schedule(self.file, work_schedule=self.work_schedule) is None
        assert root.TaskTime is None

    def test_three_task_nest_cycle_still_calculates_a_sibling_activity(self):
        self._add_work_schedule()
        root = ifcopenshell.api.sequence.add_task(self.file, work_schedule=self.work_schedule, name="root")
        first = self._bare_task("first")
        second = self._bare_task("second")
        third = self._bare_task("third")
        # The cycle is the first child, so a walk with no memory of visited
        # tasks never reaches the sibling activity on the same schedule.
        self._nest(root, [first])
        self._nest(first, [second])
        self._nest(second, [third])
        self._nest(third, [first])
        self._set_time(first, start="1999-06-01T09:00:00", duration="P5D", finish=None)
        activity = self._scheduled_activity("activity")

        ifcopenshell.api.sequence.recalculate_schedule(self.file, work_schedule=self.work_schedule)

        self._assert_critical_day(activity)
        assert first.TaskTime.ScheduleStart == "1999-06-01T09:00:00"
        assert first.TaskTime.IsCritical is None
        assert first.TaskTime.TotalFloat is None

    def test_activity_under_a_cyclic_parent_chain_is_calculated(self):
        self._add_work_schedule()
        # The activity's first parent is inside the cycle, so the upward
        # calendar and sequence walks loop as well as the downward nest walk.
        # The cyclic child is listed before the activity.
        summary = ifcopenshell.api.sequence.add_task(self.file, work_schedule=self.work_schedule, name="summary")
        other = self._bare_task("other")
        activity = self._bare_task("activity")
        self._nest(summary, [other, activity])
        self._nest(other, [summary])
        self._set_time(activity)

        ifcopenshell.api.sequence.recalculate_schedule(self.file, work_schedule=self.work_schedule)

        self._assert_critical_day(activity)
        assert activity.TaskTime.ScheduleStart == "2000-01-01T09:00:00"
        assert activity.TaskTime.ScheduleDuration == "P1D"

    def test_reopened_ifc_nest_cycle_still_calculates_the_activity(self, tmp_path):
        self._add_work_schedule()
        root = ifcopenshell.api.sequence.add_task(self.file, work_schedule=self.work_schedule, name="root")
        summary = self._bare_task("summary")
        other = self._bare_task("other")
        self._nest(root, [summary])
        self._nest(summary, [other])
        self._nest(other, [summary])
        activity = self._scheduled_activity("activity")
        path = tmp_path / "nest-cycle.ifc"
        self.file.write(path)

        reopened = ifcopenshell.open(path)
        tasks = {task.Name: task for task in reopened.by_type("IfcTask")}
        assert tasks["other"] in self._nested_objects(tasks["summary"])
        assert tasks["summary"] in self._nested_objects(tasks["other"])
        work_schedule = reopened.by_type("IfcWorkSchedule")[0]

        ifcopenshell.api.sequence.recalculate_schedule(reopened, work_schedule=work_schedule)

        self._assert_critical_day(tasks["activity"])
        assert tasks["activity"].TaskTime.ScheduleStart == "2000-01-01T09:00:00"

    def test_acyclic_nested_activity_is_still_calculated(self):
        self._add_work_schedule()
        root = ifcopenshell.api.sequence.add_task(self.file, work_schedule=self.work_schedule, name="root")
        activity = ifcopenshell.api.sequence.add_task(self.file, parent_task=root, name="activity")
        task_time = ifcopenshell.api.sequence.add_task_time(self.file, task=activity)
        ifcopenshell.api.sequence.edit_task_time(
            self.file,
            task_time=task_time,
            attributes={"ScheduleStart": datetime.date(2000, 1, 1), "ScheduleDuration": "P1D"},
        )

        ifcopenshell.api.sequence.recalculate_schedule(self.file, work_schedule=self.work_schedule)

        self._assert_critical_day(activity)

    def test_sequence_link_cycle_still_raises_without_writing_floats(self):
        self._add_work_schedule()
        task = self._scheduled_activity("task")
        task2 = self._scheduled_activity("task2")
        task3 = self._scheduled_activity("task3")
        task4 = self._scheduled_activity("task4")
        self._create_sequence(task, task2)
        self._create_sequence(task, task4)
        self._create_sequence(task2, task3)
        with pytest.raises(RecursionError, match="Recursive tasks found"):
            self._create_sequence(task3, task2)

        with pytest.raises(RecursionError, match="Task graph is cyclic"):
            ifcopenshell.api.sequence.recalculate_schedule(self.file, work_schedule=self.work_schedule)

        assert task.TaskTime.IsCritical is None
        assert task.TaskTime.TotalFloat is None
        assert task2.TaskTime.IsCritical is None
        assert task3.TaskTime.IsCritical is None

    def test_cascade_schedule_reports_a_nest_cycle_without_exhausting_the_stack(self):
        self._add_work_schedule()
        summary = ifcopenshell.api.sequence.add_task(self.file, work_schedule=self.work_schedule, name="summary")
        other = self._bare_task("other")
        self._nest(summary, [other])
        self._nest(other, [summary])
        self._set_time(summary)
        self._set_time(other)

        with pytest.raises(RecursionError, match="Recursive tasks found"):
            ifcopenshell.api.sequence.cascade_schedule(self.file, task=summary)

    def test_edit_task_time_under_a_nest_cycle_writes_the_finish(self):
        self._add_work_schedule()
        summary = ifcopenshell.api.sequence.add_task(self.file, work_schedule=self.work_schedule, name="summary")
        other = self._bare_task("other")
        activity = self._bare_task("activity")
        self._nest(summary, [other, activity])
        self._nest(other, [summary])
        task_time = ifcopenshell.api.sequence.add_task_time(self.file, task=activity)

        ifcopenshell.api.sequence.edit_task_time(
            self.file,
            task_time=task_time,
            attributes={"ScheduleStart": datetime.date(2000, 1, 1), "ScheduleDuration": "P1D"},
        )

        assert activity.TaskTime.ScheduleStart == "2000-01-01T09:00:00"
        assert activity.TaskTime.ScheduleFinish == "2000-01-01T17:00:00"
        assert activity.TaskTime.ScheduleDuration == "P1D"

    def test_guess_date_range_reads_a_date_through_a_nest_cycle(self):
        self._add_work_schedule()
        summary = ifcopenshell.api.sequence.add_task(self.file, work_schedule=self.work_schedule, name="summary")
        other = self._bare_task("other")
        dated = self._bare_task("dated")
        self._nest(summary, [other])
        self._nest(other, [summary, dated])
        self._set_time(dated, start="2000-01-01T09:00:00", duration="P5D", finish="2000-01-05T17:00:00")
        wall = self.file.createIfcWall()
        ifcopenshell.api.sequence.assign_product(self.file, relating_product=wall, related_object=summary)

        earliest, latest = ifcopenshell.util.sequence.guess_date_range(self.work_schedule)

        assert earliest == datetime.datetime(2000, 1, 1, 9, 0)
        assert latest == datetime.datetime(2000, 1, 5, 17, 0)

    def test_calculate_task_duration_on_an_unassigned_nest_cycle(self):
        ifcopenshell.api.root.create_entity(self.file, ifc_class="IfcProject")
        task = ifcopenshell.api.sequence.add_task(self.file, name="task")
        other = ifcopenshell.api.sequence.add_task(self.file, name="other")
        self._nest(task, [other])
        self._nest(other, [task])
        resource = ifcopenshell.api.resource.add_resource(self.file, ifc_class="IfcLaborResource")
        resource_time = ifcopenshell.api.resource.add_resource_time(self.file, resource=resource)
        resource_time.ScheduleWork = "P2D"
        ifcopenshell.api.sequence.assign_process(self.file, relating_process=task, related_object=resource)

        ifcopenshell.api.sequence.calculate_task_duration(self.file, task=task)

        assert task.TaskTime.ScheduleDuration == "P2D"

    def test_get_task_work_schedule_finds_the_schedule_through_a_nest_cycle(self):
        self._add_work_schedule()
        summary = ifcopenshell.api.sequence.add_task(self.file, work_schedule=self.work_schedule, name="summary")
        other = self._bare_task("other")
        self._nest(summary, [other])
        self._nest(other, [summary])

        assert ifcopenshell.util.sequence.get_task_work_schedule(other) == self.work_schedule
        assert ifcopenshell.util.sequence.get_task_work_schedule(summary) == self.work_schedule

    def _add_work_schedule(self):
        ifcopenshell.api.root.create_entity(self.file, ifc_class="IfcProject")
        self.work_schedule = ifcopenshell.api.sequence.add_work_schedule(self.file)

    def _bare_task(self, name):
        task = ifcopenshell.api.root.create_entity(self.file, ifc_class="IfcTask", name=name)
        task.IsMilestone = False
        return task

    def _nest(self, parent, children):
        self.file.create_entity("IfcRelNests", RelatingObject=parent, RelatedObjects=list(children))

    def _nested_objects(self, task):
        return [obj for rel in task.IsNestedBy or [] for obj in rel.RelatedObjects]

    def _set_time(self, task, start="2000-01-01T09:00:00", duration="P1D", finish="2000-01-01T17:00:00"):
        task_time = ifcopenshell.api.sequence.add_task_time(self.file, task=task)
        task_time.ScheduleStart = start
        task_time.ScheduleDuration = duration
        task_time.ScheduleFinish = finish
        task_time.DurationType = "ELAPSEDTIME"
        return task_time

    def _scheduled_activity(self, name):
        task = ifcopenshell.api.sequence.add_task(self.file, work_schedule=self.work_schedule, name=name)
        task_time = ifcopenshell.api.sequence.add_task_time(self.file, task=task)
        ifcopenshell.api.sequence.edit_task_time(
            self.file,
            task_time=task_time,
            attributes={"ScheduleStart": datetime.date(2000, 1, 1), "ScheduleDuration": "P1D"},
        )
        return task

    def _create_sequence(self, predecessor, successor):
        return ifcopenshell.api.sequence.assign_sequence(
            self.file, relating_process=predecessor, related_process=successor, sequence_type="FINISH_START"
        )

    def _assert_critical_day(self, task):
        assert task.TaskTime.EarlyStart == "2000-01-01T09:00:00"
        assert task.TaskTime.EarlyFinish == "2000-01-01T17:00:00"
        assert task.TaskTime.LateStart == "2000-01-01T09:00:00"
        assert task.TaskTime.LateFinish == "2000-01-01T17:00:00"
        assert task.TaskTime.TotalFloat == "P0D"
        assert task.TaskTime.FreeFloat == "P0D"
        assert task.TaskTime.IsCritical is True
