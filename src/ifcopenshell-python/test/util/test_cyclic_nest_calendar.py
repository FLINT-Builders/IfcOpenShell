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

"""Calendar inheritance must stop when an IfcRelNests parent repeats.

`derive_calendar` follows `Nests` by calling itself. A repeated task has to
yield None, and a task that already has an IfcWorkCalendar has to yield that
calendar without walking further. The tests below load that function from this
checkout, then open an IFC file that contains the cycle.

Not asserted here, because a visited set on `derive_calendar` does not make
these callers finish:

- `Ifc2Msp.create_task` and `Ifc2P6.create_wbs` still walk `IsNestedBy` with
  no visited set, so two IfcTasks that nest each other still exhaust the stack
  during export. Primavera's walk happens before `create_activity`, so that
  shape never reaches `derive_calendar`. The export tests use a task nested
  with an IfcWorkPlan: the child walk stops, and the calendar walk is the one
  that loops.
- `cascade_schedule` reaches `derive_calendar` when the task has its own
  predecessor, then walks `IsNestedBy` with no visited set.
- `recalculate_schedule` walks `IsNestedBy` before it asks for a calendar.
- Bonsai `Sequence.load_task_properties` calls `derive_calendar`, and it needs
  Blender. The date edit in Bonsai calls `sequence.edit_task_time`, which is
  covered below.
"""

import datetime
import importlib.util
import sys
from pathlib import Path

# pytest puts this package on sys.path. That copy has no compiled wrapper, so
# the installed ifcopenshell has to be the one that opens the IFC file.
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
sys.path[:] = [entry for entry in sys.path if not entry or Path(entry).resolve() != _PACKAGE_ROOT]

import ifcopenshell
import ifcopenshell.guid

REPO_ROOT = Path(__file__).resolve().parents[4]
SEQUENCE_SOURCE = REPO_ROOT / "src/ifcopenshell-python/ifcopenshell/util/sequence.py"


def _load_repository_sequence():
    spec = importlib.util.spec_from_file_location("ifcopenshell.util.sequence", SEQUENCE_SOURCE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ifcopenshell.util.sequence"] = module
    spec.loader.exec_module(module)
    ifcopenshell.util.sequence = module
    return module


sequence = _load_repository_sequence()

import ifcopenshell.api.sequence

sys.path.insert(0, str(REPO_ROOT / "src" / "ifc4d"))
from ifc4d.ifc2msp import Ifc2Msp
from ifc4d.ifc2p6 import Ifc2P6


def _guid():
    return ifcopenshell.guid.new()


def _reopen(file, path):
    file.write(str(path))
    return ifcopenshell.open(str(path))


def _task(file, name):
    return file.create_entity("IfcTask", GlobalId=_guid(), Name=name)


def _nest(file, parent, child):
    return file.create_entity(
        "IfcRelNests",
        GlobalId=_guid(),
        RelatingObject=parent,
        RelatedObjects=[child],
    )


def _mutual_tasks(path):
    file = ifcopenshell.file(schema="IFC4")
    file.create_entity("IfcProject", GlobalId=_guid(), Name="Project")
    first = _task(file, "First")
    second = _task(file, "Second")
    _nest(file, second, first)
    _nest(file, first, second)
    task_time = ifcopenshell.api.sequence.add_task_time(file, task=first)
    task_time.ScheduleStart = "1999-05-05T09:00:00"
    task_time.DurationType = "ELAPSEDTIME"
    reopened = _reopen(file, path)
    first = next(task for task in reopened.by_type("IfcTask") if task.Name == "First")
    second = next(task for task in reopened.by_type("IfcTask") if task.Name == "Second")
    assert [rel.RelatingObject.Name for rel in first.Nests] == ["Second"]
    assert [rel.RelatingObject.Name for rel in second.Nests] == ["First"]
    return reopened, first


def _self_nested_task(path):
    file = ifcopenshell.file(schema="IFC4")
    file.create_entity("IfcProject", GlobalId=_guid(), Name="Project")
    task = _task(file, "Loop")
    _nest(file, task, task)
    task_time = ifcopenshell.api.sequence.add_task_time(file, task=task)
    task_time.ScheduleStart = "1999-05-05T09:00:00"
    task_time.DurationType = "ELAPSEDTIME"
    reopened = _reopen(file, path)
    task = reopened.by_type("IfcTask")[0]
    assert [rel.RelatingObject.Name for rel in task.Nests] == ["Loop"]
    assert [obj.Name for rel in task.IsNestedBy for obj in rel.RelatedObjects] == ["Loop"]
    return reopened, task


def _task_cycled_with_work_plan(path, with_calendar):
    file = ifcopenshell.file(schema="IFC4")
    file.create_entity("IfcProject", GlobalId=_guid(), Name="Project")
    task = _task(file, "Formwork")
    plan = file.create_entity("IfcWorkPlan", GlobalId=_guid(), Name="Plan")
    _nest(file, plan, task)
    _nest(file, task, plan)
    task_time = ifcopenshell.api.sequence.add_task_time(file, task=task)
    task_time.ScheduleStart = "2000-01-01T09:00:00"
    task_time.DurationType = "ELAPSEDTIME"
    schedule = file.create_entity("IfcWorkSchedule", GlobalId=_guid(), Name="Schedule")
    file.create_entity(
        "IfcRelAssignsToControl",
        GlobalId=_guid(),
        RelatingControl=schedule,
        RelatedObjects=[task],
    )
    if with_calendar:
        calendar = file.create_entity("IfcWorkCalendar", GlobalId=_guid(), Name="Calendar")
        calendar.WorkingTimes = ()
    reopened = _reopen(file, path)
    task = next(item for item in reopened.by_type("IfcTask") if item.Name == "Formwork")
    assert [rel.RelatingObject.is_a() for rel in task.Nests] == ["IfcWorkPlan"]
    assert [rel.RelatingObject.Name for rel in task.Nests[0].RelatingObject.Nests] == ["Formwork"]
    return reopened, task


def test_derive_calendar_on_mutual_task_nest_returns_none(tmp_path):
    _, task = _mutual_tasks(tmp_path / "mutual.ifc")
    assert sequence.derive_calendar(task) is None


def test_derive_calendar_on_self_nest_returns_none(tmp_path):
    _, task = _self_nested_task(tmp_path / "self.ifc")
    assert sequence.derive_calendar(task) is None


def test_edit_task_time_updates_mutual_nested_task(tmp_path):
    _, task = _mutual_tasks(tmp_path / "mutual-edit.ifc")
    assert task.TaskTime.ScheduleStart == "1999-05-05T09:00:00"
    ifcopenshell.api.sequence.edit_task_time(
        task.file,
        task_time=task.TaskTime,
        attributes={"DurationType": "ELAPSEDTIME", "ScheduleStart": "2000-02-02T00:00:00"},
    )
    assert task.TaskTime.ScheduleStart == "2000-02-02T09:00:00"


def test_edit_task_time_updates_self_nested_task(tmp_path):
    _, task = _self_nested_task(tmp_path / "self-edit.ifc")
    assert task.TaskTime.ScheduleStart == "1999-05-05T09:00:00"
    ifcopenshell.api.sequence.edit_task_time(
        task.file,
        task_time=task.TaskTime,
        attributes={"DurationType": "ELAPSEDTIME", "ScheduleStart": "2000-02-02T00:00:00"},
    )
    assert task.TaskTime.ScheduleStart == "2000-02-02T09:00:00"


def test_derive_calendar_keeps_calendar_found_on_a_cyclic_parent(tmp_path):
    file = ifcopenshell.file(schema="IFC4")
    child = _task(file, "Child")
    parent = _task(file, "Parent")
    _nest(file, parent, child)
    _nest(file, child, parent)
    calendar = file.create_entity("IfcWorkCalendar", Name="ParentCalendar")
    file.create_entity(
        "IfcRelAssignsToControl",
        GlobalId=_guid(),
        RelatingControl=calendar,
        RelatedObjects=[parent],
    )
    reopened = _reopen(file, tmp_path / "parent-calendar.ifc")
    child = next(task for task in reopened.by_type("IfcTask") if task.Name == "Child")
    assert [rel.RelatingObject.Name for rel in child.Nests] == ["Parent"]
    assert sequence.derive_calendar(child).Name == "ParentCalendar"


def test_derive_calendar_keeps_the_tasks_own_calendar(tmp_path):
    file = ifcopenshell.file(schema="IFC4")
    task = _task(file, "Owned")
    other = _task(file, "Other")
    _nest(file, other, task)
    _nest(file, task, other)
    calendar = file.create_entity("IfcWorkCalendar", Name="OwnCalendar")
    file.create_entity(
        "IfcRelAssignsToControl",
        GlobalId=_guid(),
        RelatingControl=calendar,
        RelatedObjects=[task],
    )
    reopened = _reopen(file, tmp_path / "own-calendar.ifc")
    task = next(item for item in reopened.by_type("IfcTask") if item.Name == "Owned")
    assert sequence.derive_calendar(task).Name == "OwnCalendar"


def test_derive_calendar_inherits_an_acyclic_parent_calendar(tmp_path):
    file = ifcopenshell.file(schema="IFC4")
    child = _task(file, "Child")
    parent = _task(file, "Parent")
    _nest(file, parent, child)
    calendar = file.create_entity("IfcWorkCalendar", Name="Inherited")
    file.create_entity(
        "IfcRelAssignsToControl",
        GlobalId=_guid(),
        RelatingControl=calendar,
        RelatedObjects=[parent],
    )
    reopened = _reopen(file, tmp_path / "acyclic.ifc")
    child = next(task for task in reopened.by_type("IfcTask") if task.Name == "Child")
    assert sequence.derive_calendar(child).Name == "Inherited"


def test_msp_export_completes_for_cyclic_nest(tmp_path):
    file, _ = _task_cycled_with_work_plan(tmp_path / "msp-source.ifc", with_calendar=False)
    output = tmp_path / "msp.xml"
    exporter = Ifc2Msp()
    exporter.file = file
    exporter.work_schedule = file.by_type("IfcWorkSchedule")[0]
    exporter.xml = str(output)
    exporter.holiday_start_date = datetime.date(2022, 1, 1)
    exporter.holiday_finish_date = datetime.date(2022, 1, 3)
    exporter.execute()
    written = output.read_text()
    assert "Formwork" in written
    assert "<CalendarUID>" not in written


def test_p6_export_completes_for_cyclic_nest(tmp_path):
    file, _ = _task_cycled_with_work_plan(tmp_path / "p6-source.ifc", with_calendar=True)
    output = tmp_path / "p6.xml"
    exporter = Ifc2P6()
    exporter.file = file
    exporter.xml = str(output)
    exporter.holiday_start_date = datetime.date(2022, 1, 1)
    exporter.holiday_finish_date = datetime.date(2022, 1, 3)
    exporter.execute()
    written = output.read_text()
    assert "Formwork" in written
    assert "Calendar" in written
