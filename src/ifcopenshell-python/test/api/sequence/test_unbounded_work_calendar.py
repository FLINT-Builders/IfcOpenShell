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

"""Schedule calculations must stop when a work calendar has no working day.

A calendar whose working times cover every day, and whose exception times also
cover every day, applies to every date while ``is_working_day`` is false for
every date. The same is true of a weekly working time whose weekday list never
matches. ``offset_date``, ``get_soonest_working_day`` and
``get_recent_working_day`` then step one day at a time until the date overflows,
and the unbounded caches on ``is_working_day`` and ``is_calendar_applicable``
keep every visited day.

These tests fail while that behaviour is present. A fix should make every
operation below finish within a couple of seconds, raise or return without
walking to year 9999 or year 1, leave task-time attributes unchanged when it
raises, and keep the two caches bounded. An ordinary weekly calendar and an
elapsed-time task must keep their current results.
"""

import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import ifcopenshell
import ifcopenshell.api.control
import ifcopenshell.api.owner
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.sequence
import ifcopenshell.guid
import ifcopenshell.util.sequence as sequence

CALL_DEADLINE_SECONDS = 2
MAX_SHIFT_DAYS = 366 * 10
MAX_CACHE_GROWTH = 8000
MAX_REPEATED_CACHE = 16000
MAX_CACHE_SIZE = 4096
RESULT_PREFIX = "IFC_CALENDAR_RESULT "


class SetupError(Exception):
    """The fixture is not the calendar shape under test."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SetupError(message)


def _cache_currsize(fn) -> int:
    info = getattr(fn, "cache_info", None)
    if info is None:
        return 0
    return info().currsize


def _cache_total() -> int:
    return _cache_currsize(sequence.is_working_day) + _cache_currsize(sequence.is_calendar_applicable)


def _clear_caches() -> None:
    for fn in (sequence.is_working_day, sequence.is_calendar_applicable):
        clear = getattr(fn, "cache_clear", None)
        if clear is not None:
            clear()


def _reopen(file: ifcopenshell.file) -> ifcopenshell.file:
    fd, path = tempfile.mkstemp(suffix=".ifc")
    os.close(fd)
    try:
        file.write(path)
        return ifcopenshell.open(path)
    finally:
        os.remove(path)


def _work_time_covers_every_day(work_time: ifcopenshell.entity_instance) -> bool:
    return work_time.Start is None and work_time.Finish is None and work_time.RecurrencePattern is None


def _require_dead_calendar(calendar: ifcopenshell.entity_instance, *, weekly: bool) -> None:
    _require(bool(calendar.WorkingTimes), "calendar has no working times")
    if weekly:
        work_time = calendar.WorkingTimes[0]
        pattern = work_time.RecurrencePattern
        _require(pattern is not None and pattern.RecurrenceType == "WEEKLY", "weekly pattern missing")
        weekdays = set(pattern.WeekdayComponent or [])
        _require(weekdays.isdisjoint({1, 2, 3, 4, 5, 6, 7}), "weekly pattern still names a weekday")
        _require(work_time.Start is None and work_time.Finish is None, "weekly work time is bounded by dates")
        _require(not calendar.ExceptionTimes, "weekly case must not depend on exceptions")
        return
    _require(len(calendar.WorkingTimes) == 1 and _work_time_covers_every_day(calendar.WorkingTimes[0]), "working time")
    _require(bool(calendar.ExceptionTimes), "calendar has no exception times")
    _require(_work_time_covers_every_day(calendar.ExceptionTimes[0]), "exception time does not cover every day")


def _calendar_assigned_to(task: ifcopenshell.entity_instance) -> ifcopenshell.entity_instance | None:
    for rel in task.HasAssignments or []:
        if rel.is_a("IfcRelAssignsToControl") and rel.RelatingControl.is_a("IfcWorkCalendar"):
            return rel.RelatingControl
    return None


def _build_file(*, inherited: bool = False, weekly: bool = False) -> ifcopenshell.file:
    file = ifcopenshell.api.project.create_file()
    ifcopenshell.api.root.create_entity(file, ifc_class="IfcProject")
    schedule = ifcopenshell.api.sequence.add_work_schedule(file, name="Construction")
    parent = ifcopenshell.api.sequence.add_task(file, work_schedule=schedule, name="Parent")
    if inherited:
        task = ifcopenshell.api.sequence.add_task(file, parent_task=parent, name="Formwork")
    else:
        task = ifcopenshell.api.sequence.add_task(file, work_schedule=schedule, name="Formwork")
    calendar = ifcopenshell.api.sequence.add_work_calendar(file, name="Never")
    work_time = ifcopenshell.api.sequence.add_work_time(file, work_calendar=calendar, time_type="WorkingTimes")
    if weekly:
        pattern = ifcopenshell.api.sequence.assign_recurrence_pattern(file, parent=work_time, recurrence_type="WEEKLY")
        ifcopenshell.api.sequence.edit_recurrence_pattern(
            file, recurrence_pattern=pattern, attributes={"WeekdayComponent": []}
        )
    else:
        ifcopenshell.api.sequence.add_work_time(file, work_calendar=calendar, time_type="ExceptionTimes")
    assignee = parent if inherited else task
    ifcopenshell.api.control.assign_control(file, relating_control=calendar, related_objects=[assignee])
    task_time = ifcopenshell.api.sequence.add_task_time(file, task=task)
    task_time.DurationType = "WORKTIME"
    task_time.ScheduleStart = "2020-01-01T09:00:00"
    task_time.ScheduleDuration = "P5D"
    return file


def _load(*, inherited: bool = False, weekly: bool = False):
    file = _reopen(_build_file(inherited=inherited, weekly=weekly))
    task = next(entity for entity in file.by_type("IfcTask") if entity.Name == "Formwork")
    if inherited:
        _require(_calendar_assigned_to(task) is None, "child task should inherit its calendar")
        parent = next(entity for entity in file.by_type("IfcTask") if entity.Name == "Parent")
        calendar = _calendar_assigned_to(parent)
        _require(calendar is not None, "parent task has no work calendar")
        _require(any(rel.RelatingObject == parent for rel in task.Nests or []), "child is not nested in the parent")
    else:
        calendar = _calendar_assigned_to(task)
        _require(calendar is not None, "task has no work calendar")
    _require_dead_calendar(calendar, weekly=weekly)
    _require(task.TaskTime.DurationType == "WORKTIME", "duration type")
    _require(task.TaskTime.ScheduleDuration == "P5D", "duration")
    schedule = file.by_type("IfcWorkSchedule")[0]
    return file, schedule, task, calendar


def _attrs(task: ifcopenshell.entity_instance) -> list:
    task_time = task.TaskTime
    return [
        task_time.ScheduleStart,
        task_time.ScheduleFinish,
        task_time.ScheduleDuration,
        task_time.EarlyStart,
        task_time.EarlyFinish,
        task_time.LateStart,
        task_time.LateFinish,
        task_time.DurationType,
    ]


def _years_from_attrs(attrs: list | None) -> list[int]:
    years = []
    for value in attrs or []:
        if isinstance(value, str) and len(value) >= 4 and value[0:4].isdigit() and value[4:5] == "-":
            years.append(int(value[0:4]))
    return years


def _shift_days(origin: datetime.datetime, result) -> int | None:
    if isinstance(result, datetime.datetime):
        result_day = result.date()
    elif isinstance(result, datetime.date):
        result_day = result
    else:
        return None
    return (result_day - origin.date()).days


def _call(report: dict, task: ifcopenshell.entity_instance, origin: datetime.datetime, fn):
    report["before_attrs"] = _attrs(task)
    try:
        result = fn()
    except Exception:
        report["after_attrs"] = _attrs(task)
        raise
    report["after_attrs"] = _attrs(task)
    report["shift_days"] = _shift_days(origin, result)
    if report["shift_days"] is None:
        report["years"] = _years_from_attrs(report["after_attrs"])
    else:
        report["years"] = [result.year]


def _case_edit_start(report: dict) -> None:
    file, _schedule, task, _calendar = _load()
    origin = datetime.datetime(2020, 1, 6)

    def run():
        ifcopenshell.api.sequence.edit_task_time(file, task_time=task.TaskTime, attributes={"ScheduleStart": origin})

    _call(report, task, origin, run)


def _case_edit_finish(report: dict) -> None:
    file, _schedule, task, _calendar = _load()
    origin = datetime.datetime(2020, 1, 10)

    def run():
        ifcopenshell.api.sequence.edit_task_time(file, task_time=task.TaskTime, attributes={"ScheduleFinish": origin})

    _call(report, task, origin, run)


def _case_edit_duration(report: dict) -> None:
    file, _schedule, task, _calendar = _load()
    origin = datetime.datetime(2020, 1, 1)

    def run():
        ifcopenshell.api.sequence.edit_task_time(file, task_time=task.TaskTime, attributes={"ScheduleDuration": "P5D"})

    _call(report, task, origin, run)


def _case_edit_inherited(report: dict) -> None:
    file, _schedule, task, _calendar = _load(inherited=True)
    origin = datetime.datetime(2020, 2, 3)

    def run():
        ifcopenshell.api.sequence.edit_task_time(file, task_time=task.TaskTime, attributes={"ScheduleStart": origin})

    _call(report, task, origin, run)


def _case_recalculate(report: dict) -> None:
    file, schedule, task, _calendar = _load()
    origin = datetime.datetime(2020, 1, 1)

    def run():
        ifcopenshell.api.sequence.recalculate_schedule(file, work_schedule=schedule)

    _call(report, task, origin, run)


def _sequence(file: ifcopenshell.file, predecessor, successor) -> None:
    file.create_entity(
        "IfcRelSequence",
        GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=ifcopenshell.api.owner.create_owner_history(file),
        RelatingProcess=predecessor,
        RelatedProcess=successor,
        SequenceType="FINISH_START",
    )


def _predecessor_and_successor():
    file, _schedule, successor, _calendar = _load()
    predecessor = ifcopenshell.api.sequence.add_task(
        file, work_schedule=file.by_type("IfcWorkSchedule")[0], name="Pred"
    )
    predecessor_time = ifcopenshell.api.sequence.add_task_time(file, task=predecessor)
    predecessor_time.DurationType = "ELAPSEDTIME"
    predecessor_time.ScheduleStart = "2020-01-01T09:00:00"
    predecessor_time.ScheduleFinish = "2020-01-01T17:00:00"
    predecessor_time.ScheduleDuration = "P1D"
    return file, predecessor, successor


def _case_cascade(report: dict) -> None:
    file, predecessor, successor = _predecessor_and_successor()
    _sequence(file, predecessor, successor)
    origin = datetime.datetime(2020, 1, 1)

    def run():
        ifcopenshell.api.sequence.cascade_schedule(file, task=predecessor)

    _call(report, successor, origin, run)


def _case_assign_sequence(report: dict) -> None:
    file, predecessor, successor = _predecessor_and_successor()
    origin = datetime.datetime(2020, 1, 1)

    def run():
        ifcopenshell.api.sequence.assign_sequence(
            file, relating_process=predecessor, related_process=successor, sequence_type="FINISH_START"
        )

    _call(report, successor, origin, run)


def _case_offset_forward(report: dict) -> None:
    _file, _schedule, task, calendar = _load()
    origin = datetime.datetime(2020, 1, 1)

    def run():
        return sequence.offset_date(origin, datetime.timedelta(days=5), "WORKTIME", calendar)

    _call(report, task, origin, run)


def _case_offset_backward(report: dict) -> None:
    _file, _schedule, task, calendar = _load()
    origin = datetime.datetime(2020, 6, 1)

    def run():
        return sequence.offset_date(origin, datetime.timedelta(days=-5), "WORKTIME", calendar)

    _call(report, task, origin, run)


def _case_soonest(report: dict) -> None:
    _file, _schedule, task, calendar = _load()
    origin = datetime.datetime(2020, 1, 1)

    def run():
        return sequence.get_soonest_working_day(origin, "WORKTIME", calendar)

    _call(report, task, origin, run)


def _case_recent(report: dict) -> None:
    _file, _schedule, task, calendar = _load()
    origin = datetime.datetime(2020, 6, 1)

    def run():
        return sequence.get_recent_working_day(origin, "WORKTIME", calendar)

    _call(report, task, origin, run)


def _case_finish_date(report: dict) -> None:
    _file, _schedule, task, calendar = _load()
    origin = datetime.datetime(2020, 1, 1, 9)

    def run():
        return sequence.get_start_or_finish_date(
            origin, datetime.timedelta(days=5), "WORKTIME", calendar, date_type="FINISH"
        )

    _call(report, task, origin, run)


def _case_start_date(report: dict) -> None:
    _file, _schedule, task, calendar = _load()
    origin = datetime.datetime(2020, 6, 1, 17)

    def run():
        return sequence.get_start_or_finish_date(
            origin, datetime.timedelta(days=5), "WORKTIME", calendar, date_type="START"
        )

    _call(report, task, origin, run)


def _case_weekly(report: dict) -> None:
    _file, _schedule, task, calendar = _load(weekly=True)
    origin = datetime.datetime(2020, 1, 1)

    def run():
        return sequence.get_soonest_working_day(origin, "WORKTIME", calendar)

    _call(report, task, origin, run)


def _case_repeated(report: dict) -> None:
    years = []
    for year in range(2020, 2032):
        file, _schedule, task, _calendar = _load()
        origin = datetime.datetime(year, 3, 2)
        before = _attrs(task)
        try:
            ifcopenshell.api.sequence.edit_task_time(
                file, task_time=task.TaskTime, attributes={"ScheduleStart": origin}
            )
        except Exception as exc:
            if _attrs(task) != before:
                raise SetupError(f"task time changed before {type(exc).__name__}") from exc
            if type(exc) is OverflowError:
                raise
            continue
        years.extend(_years_from_attrs(_attrs(task)))
    report["years"] = years
    report["before_attrs"] = []
    report["after_attrs"] = []


CASES = {
    "edit_start": _case_edit_start,
    "edit_finish": _case_edit_finish,
    "edit_duration": _case_edit_duration,
    "edit_inherited": _case_edit_inherited,
    "recalculate": _case_recalculate,
    "cascade": _case_cascade,
    "assign_sequence": _case_assign_sequence,
    "offset_forward": _case_offset_forward,
    "offset_backward": _case_offset_backward,
    "soonest": _case_soonest,
    "recent": _case_recent,
    "finish_date": _case_finish_date,
    "start_date": _case_start_date,
    "weekly": _case_weekly,
    "repeated": _case_repeated,
}


def _execute(case: str) -> dict:
    _clear_caches()
    before = _cache_total()
    report = {
        "status": "ok",
        "before_attrs": None,
        "after_attrs": None,
        "shift_days": None,
        "years": [],
        "error_type": None,
        "error": None,
    }
    try:
        CASES[case](report)
    except Exception as exc:
        report["status"] = "error"
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)
    report["cache_growth"] = _cache_total() - before
    report["cache_total"] = _cache_total()
    return report


def _assert_bounded(report: dict, *, max_cache: int = MAX_CACHE_GROWTH) -> None:
    assert report["cache_growth"] <= max_cache, report
    assert report["cache_total"] <= max_cache, report
    if report["status"] == "error":
        assert report["error_type"] not in {"OverflowError", "SetupError", "MemoryError"}, report
        if report["before_attrs"] is not None:
            assert report["before_attrs"] == report["after_attrs"], report
        return
    assert report["status"] == "ok", report
    for year in report["years"]:
        assert 2 <= year <= 2200, report
    if report["shift_days"] is not None:
        assert abs(report["shift_days"]) <= MAX_SHIFT_DAYS, report


def _run(case: str, *, max_cache: int = MAX_CACHE_GROWTH) -> None:
    # The child has to import the same ifcopenshell the test process imported.
    # Running the file as a script would otherwise prefer a different install.
    package_root = str(Path(ifcopenshell.__file__).resolve().parent.parent)
    env = os.environ.copy()
    current_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = package_root if not current_path else package_root + os.pathsep + current_path
    try:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), case],
            check=False,
            capture_output=True,
            text=True,
            timeout=CALL_DEADLINE_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{case} did not finish within {CALL_DEADLINE_SECONDS}s; the day-stepping loop is unbounded")
    line = next((item for item in reversed(proc.stdout.splitlines()) if item.startswith(RESULT_PREFIX)), None)
    if line is None:
        pytest.fail(f"{case} produced no result\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    _assert_bounded(json.loads(line[len(RESULT_PREFIX) :]), max_cache=max_cache)


def test_edit_task_time_start_from_opened_ifc_is_bounded():
    _run("edit_start")


def test_edit_task_time_finish_is_bounded():
    _run("edit_finish")


def test_edit_task_time_duration_is_bounded():
    _run("edit_duration")


def test_edit_task_time_uses_calendar_inherited_from_parent():
    _run("edit_inherited")


def test_recalculate_schedule_is_bounded():
    _run("recalculate")


def test_cascade_schedule_is_bounded():
    _run("cascade")


def test_assign_sequence_is_bounded():
    _run("assign_sequence")


def test_offset_date_forward_is_bounded():
    _run("offset_forward")


def test_offset_date_backward_is_bounded():
    _run("offset_backward")


def test_get_soonest_working_day_is_bounded():
    _run("soonest")


def test_get_recent_working_day_is_bounded():
    _run("recent")


def test_get_finish_date_is_bounded():
    _run("finish_date")


def test_get_start_date_is_bounded():
    _run("start_date")


def test_weekly_pattern_with_no_weekday_is_bounded():
    _run("weekly")


def test_repeated_edits_do_not_grow_the_day_caches():
    _run("repeated", max_cache=MAX_REPEATED_CACHE)


def test_day_predicates_do_not_cache_without_a_bound():
    file = ifcopenshell.api.project.create_file()
    ifcopenshell.api.root.create_entity(file, ifc_class="IfcProject")
    calendar = ifcopenshell.api.sequence.add_work_calendar(file)
    work_time = ifcopenshell.api.sequence.add_work_time(file, work_calendar=calendar, time_type="WorkingTimes")
    pattern = ifcopenshell.api.sequence.assign_recurrence_pattern(file, parent=work_time, recurrence_type="WEEKLY")
    ifcopenshell.api.sequence.edit_recurrence_pattern(
        file, recurrence_pattern=pattern, attributes={"WeekdayComponent": [1, 2, 3, 4, 5]}
    )
    _clear_caches()
    try:
        day = datetime.date(2020, 1, 1)
        for offset in range(20000):
            current = day + datetime.timedelta(days=offset)
            sequence.is_working_day(current, calendar)
            sequence.is_calendar_applicable(current, calendar)
        assert _cache_currsize(sequence.is_working_day) <= MAX_CACHE_SIZE
        assert _cache_currsize(sequence.is_calendar_applicable) <= MAX_CACHE_SIZE
    finally:
        _clear_caches()


def test_ordinary_weekly_calendar_still_counts_only_working_days():
    file = ifcopenshell.api.project.create_file()
    ifcopenshell.api.root.create_entity(file, ifc_class="IfcProject")
    calendar = ifcopenshell.api.sequence.add_work_calendar(file)
    task = ifcopenshell.api.sequence.add_task(file, name="Formwork")
    ifcopenshell.api.control.assign_control(file, relating_control=calendar, related_objects=[task])
    work_time = ifcopenshell.api.sequence.add_work_time(file, work_calendar=calendar, time_type="WorkingTimes")
    pattern = ifcopenshell.api.sequence.assign_recurrence_pattern(file, parent=work_time, recurrence_type="WEEKLY")
    ifcopenshell.api.sequence.edit_recurrence_pattern(
        file, recurrence_pattern=pattern, attributes={"WeekdayComponent": [1, 2, 3, 4, 5]}
    )
    task_time = ifcopenshell.api.sequence.add_task_time(file, task=task)
    ifcopenshell.api.sequence.edit_task_time(
        file,
        task_time=task_time,
        attributes={
            "DurationType": "WORKTIME",
            "ScheduleDuration": "P7D",
            "ScheduleStart": datetime.datetime(2020, 1, 1),
        },
    )
    assert task_time.ScheduleStart == "2020-01-01T09:00:00"
    assert task_time.ScheduleFinish == "2020-01-09T17:00:00"
    assert task_time.ScheduleDuration == "P7D"


def test_elapsed_time_is_not_blocked_by_a_calendar_without_working_days():
    file, _schedule, task, _calendar = _load()
    ifcopenshell.api.sequence.edit_task_time(
        file,
        task_time=task.TaskTime,
        attributes={
            "DurationType": "ELAPSEDTIME",
            "ScheduleDuration": "P1D",
            "ScheduleStart": datetime.datetime(2020, 1, 1, 9),
        },
    )
    assert task.TaskTime.ScheduleStart == "2020-01-01T09:00:00"
    assert task.TaskTime.ScheduleFinish == "2020-01-01T17:00:00"
    assert task.TaskTime.ScheduleDuration == "P1D"


if __name__ == "__main__":
    print(RESULT_PREFIX + json.dumps(_execute(sys.argv[1])))
