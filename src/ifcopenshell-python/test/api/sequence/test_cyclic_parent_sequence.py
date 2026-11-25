# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
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

import sys

import ifcopenshell.api.control
import ifcopenshell.api.root
import ifcopenshell.api.sequence
import ifcopenshell.guid
import ifcopenshell.util.sequence
import test.bootstrap

# Parent walks must stay proportional to the nest chain. A handler that follows
# the cycle until Python raises, then swallows that error, still fails this cap.
_MAX_PARENT_WALKS = 8


class TestCyclicParentSequence(test.bootstrap.IFC4):
    def test_predecessor_lookup_stops_on_mutual_nest(self):
        parent, child = self._mutual_nest()

        result = self._bounded_assignment(child, "predecessor")

        assert result == []
        assert self._bounded_assignment(parent, "predecessor") == []

    def test_successor_lookup_stops_on_mutual_nest(self):
        parent, child = self._mutual_nest()

        assert self._bounded_assignment(child, "successor") == []
        assert self._bounded_assignment(parent, "successor") == []

    def test_lookup_stops_on_three_task_nest_cycle(self):
        first, second, third = [self._task(name) for name in ("First", "Second", "Third")]
        # Parent chain is first <- third <- second <- first.
        self._nest(first, [second])
        self._nest(second, [third])
        self._nest(third, [first])

        assert self._bounded_assignment(second, "predecessor") == []
        assert self._bounded_assignment(second, "successor") == []

    def test_lookup_stops_when_ancestor_cycle_excludes_the_task(self):
        leaf, parent, other = [self._task(name) for name in ("Leaf", "Parent", "Other")]
        self._nest(parent, [leaf])
        self._nest(other, [parent])
        self._nest(parent, [other])

        assert self._bounded_assignment(leaf, "predecessor") == []
        assert self._bounded_assignment(leaf, "successor") == []

    def test_ancestor_sequence_is_kept_when_a_later_parent_repeats(self):
        leaf, parent, other, predecessor = [self._task(name) for name in ("Leaf", "Parent", "Other", "Predecessor")]
        self._nest(parent, [leaf])
        self._nest(other, [parent])
        self._nest(parent, [other])
        sequence = self._sequence(predecessor, parent, "START_START")

        result = self._bounded_assignment(leaf, "predecessor")

        assert list(result) == [sequence]

    def test_cascade_updates_successor_loaded_from_cyclic_file(self, tmp_path):
        parent, child = self._mutual_nest()
        successor = self._task("Successor")
        self._set_time(child, "P1D", finish="2000-01-01T17:00:00")
        self._set_time(successor, "P2D", finish="2000-01-02T17:00:00")
        self._sequence(child, successor, "FINISH_START")
        path = tmp_path / "cyclic-nests.ifc"
        self.file.write(path)
        reloaded = ifcopenshell.open(path)
        child = self._by_name(reloaded, "Child")
        successor = self._by_name(reloaded, "Successor")

        self._bounded_call(lambda: ifcopenshell.api.sequence.cascade_schedule(reloaded, task=child))

        assert child.TaskTime.ScheduleStart == "2000-01-01T09:00:00"
        assert child.TaskTime.ScheduleFinish == "2000-01-01T17:00:00"
        assert successor.TaskTime.ScheduleStart == "2000-01-02T09:00:00"
        assert successor.TaskTime.ScheduleFinish == "2000-01-03T17:00:00"

    def test_edit_task_time_updates_successor_when_parents_cycle(self):
        ifcopenshell.api.root.create_entity(self.file, ifc_class="IfcProject")
        _parent, child = self._mutual_nest()
        successor = self._task("Successor")
        child_time = self._set_time(child, "P1D", finish="2000-01-01T17:00:00")
        self._set_time(successor, "P2D", finish="2000-01-02T17:00:00")
        self._sequence(child, successor, "FINISH_START")
        calendar = ifcopenshell.api.sequence.add_work_calendar(self.file, name="Calendar")
        ifcopenshell.api.control.assign_control(self.file, relating_control=calendar, related_objects=[child])

        self._bounded_call(
            lambda: ifcopenshell.api.sequence.edit_task_time(
                self.file,
                task_time=child_time,
                attributes={"ScheduleStart": "2000-01-01", "ScheduleDuration": "P1D"},
            )
        )

        assert successor.TaskTime.ScheduleStart == "2000-01-02T09:00:00"
        assert successor.TaskTime.ScheduleFinish == "2000-01-03T17:00:00"

    def test_recalculate_schedule_finishes_when_ancestor_nests_cycle(self):
        ifcopenshell.api.root.create_entity(self.file, ifc_class="IfcProject")
        work_schedule = ifcopenshell.api.sequence.add_work_schedule(self.file, name="Schedule")
        leaf = ifcopenshell.api.sequence.add_task(self.file, work_schedule=work_schedule, name="Leaf")
        parent = self._task("Parent")
        other = self._task("Other")
        self._nest(parent, [leaf])
        self._nest(other, [parent])
        self._nest(parent, [other])
        task_time = self._set_time(leaf, "P1D", finish="2000-01-01T17:00:00")
        calendar = ifcopenshell.api.sequence.add_work_calendar(self.file, name="Calendar")
        ifcopenshell.api.control.assign_control(self.file, relating_control=calendar, related_objects=[leaf])

        self._bounded_call(
            lambda: ifcopenshell.api.sequence.recalculate_schedule(self.file, work_schedule=work_schedule),
            limit=12,
        )

        assert task_time.EarlyStart == "2000-01-01T09:00:00"
        assert task_time.EarlyFinish == "2000-01-01T17:00:00"
        assert task_time.LateStart == "2000-01-01T09:00:00"
        assert task_time.LateFinish == "2000-01-01T17:00:00"
        assert task_time.TotalFloat == "P0D"
        assert task_time.FreeFloat == "P0D"
        assert task_time.IsCritical is True

    def _task(self, name):
        task = ifcopenshell.api.root.create_entity(self.file, ifc_class="IfcTask", name=name)
        task.IsMilestone = False
        return task

    def _mutual_nest(self):
        parent = self._task("Parent")
        child = self._task("Child")
        self._nest(parent, [child])
        self._nest(child, [parent])
        return parent, child

    def _nest(self, parent, children):
        return self.file.create_entity(
            "IfcRelNests",
            GlobalId=ifcopenshell.guid.new(),
            RelatingObject=parent,
            RelatedObjects=list(children),
        )

    def _sequence(self, predecessor, successor, sequence_type):
        return self.file.create_entity(
            "IfcRelSequence",
            GlobalId=ifcopenshell.guid.new(),
            RelatingProcess=predecessor,
            RelatedProcess=successor,
            SequenceType=sequence_type,
        )

    def _set_time(self, task, duration, start="2000-01-01T09:00:00", finish="2000-01-01T17:00:00"):
        task_time = ifcopenshell.api.sequence.add_task_time(self.file, task=task)
        task_time.ScheduleStart = start
        task_time.ScheduleDuration = duration
        task_time.ScheduleFinish = finish
        task_time.DurationType = "WORKTIME"
        return task_time

    def _by_name(self, file, name):
        return next(task for task in file.by_type("IfcTask") if task.Name == name)

    def _bounded_assignment(self, task, sequence):
        return self._bounded_call(lambda: ifcopenshell.util.sequence.get_sequence_assignment(task, sequence))

    def _bounded_call(self, fn, limit=_MAX_PARENT_WALKS):
        calls = 0
        code = ifcopenshell.util.sequence.get_sequence_assignment.__code__

        def tracer(frame, event, arg):
            nonlocal calls
            if event == "call" and frame.f_code is code:
                calls += 1
            return tracer

        previous = sys.gettrace()
        sys.settrace(tracer)
        try:
            result = fn()
        finally:
            sys.settrace(previous)
        assert calls <= limit, calls
        return result
