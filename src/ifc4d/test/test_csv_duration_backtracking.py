# Ifc4D - IFC scheduling utility
# Copyright (C) 2021-2022 Dion Moult <dion@thinkmoult.com>, Yassine Oualid <yassine@sigmadimensions.com>
#
# This file is part of Ifc4D.
#
# Ifc4D is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ifc4D is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Ifc4D.  If not, see <http://www.gnu.org/licenses/>.

# This file was generated with the assistance of an AI coding tool.

"""Work-schedule CSV import must not hang on a digit-only duration cell.

Csv2Ifc.execute is the function Bonsai's Import Work Schedule CSV operator
calls on the same thread that invoked the operator. It reads ScheduleDuration
and ActualDuration and passes each unchanged to
ifcopenshell.util.date.string_to_duration. These tests fail while a long digit
run makes that search backtrack, and pass once the import finishes quickly.
"""

import csv
import io
import locale
import signal

import ifcopenshell
import ifcopenshell.api.root
import pytest

from ifc4d.csv4d2ifc import Csv2Ifc

BOUND_SECONDS = 1.0
CSV_FIELD_LIMIT = 131_072
ATTACK_DIGITS = 50_000
HEADER = [
    "Hierarchy",
    "Identification",
    "Name",
    "Relationships",
    "ScheduleStart",
    "ScheduleFinish",
    "ScheduleDuration",
    "ActualStart",
    "ActualFinish",
    "ActualDuration",
]


class DurationBacktrackingTimeout(BaseException):
    """Raised when import is still running after BOUND_SECONDS.

    BaseException so a later ``except Exception`` around the match cannot
    swallow the failure and turn a hang into a passing test.
    """


def _must_finish(func):
    def handler(signum, frame):
        raise DurationBacktrackingTimeout(f"work schedule import still running after {BOUND_SECONDS}s")

    previous = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, BOUND_SECONDS)
    try:
        return func()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous)


def _write_schedule(path, schedule_duration, actual_duration):
    with open(path, "w", newline="", encoding="ISO-8859-1") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerow(["1", "T1", "Pour concrete", "", "", "", schedule_duration, "", "", actual_duration])


def _import_schedule(path):
    # Same sequence as ImportWorkScheduleCSV._execute: an already-open IFC
    # project is attached, then Csv2Ifc.execute reads the CSV.
    ifc_file = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcProject")
    tasks_before = len(ifc_file.by_type("IfcTask"))
    importer = Csv2Ifc()
    importer.csv = str(path)
    importer.file = ifc_file

    def run():
        importer.execute()
        return ifc_file

    try:
        return _must_finish(run)
    except DurationBacktrackingTimeout:
        assert len(ifc_file.by_type("IfcTask")) == tasks_before
        raise


@pytest.fixture
def saved_locale():
    previous = locale.setlocale(locale.LC_ALL)
    yield
    locale.setlocale(locale.LC_ALL, previous)


def test_csv_reader_delivers_a_max_length_digit_cell():
    """The default csv field limit does not drop this cell before import."""
    assert csv.field_size_limit() >= CSV_FIELD_LIMIT
    cell = "9" * CSV_FIELD_LIMIT
    line = ",".join(["1", "T1", "Pour concrete", "", "", "", cell, "", "", ""])
    rows = list(csv.reader(io.StringIO(",".join(HEADER) + "\n" + line + "\n")))
    assert rows[1][HEADER.index("ScheduleDuration")] == cell


@pytest.mark.parametrize("length", [ATTACK_DIGITS, CSV_FIELD_LIMIT])
def test_schedule_duration_digit_run_imports_quickly(tmp_path, saved_locale, length):
    path = tmp_path / "schedule.csv"
    _write_schedule(path, "9" * length, "")
    _import_schedule(path)


def test_actual_duration_digit_run_imports_quickly(tmp_path, saved_locale):
    path = tmp_path / "schedule.csv"
    _write_schedule(path, "1d", "9" * ATTACK_DIGITS)
    _import_schedule(path)


def test_ordinary_schedule_csv_still_imports(tmp_path, saved_locale):
    path = tmp_path / "schedule.csv"
    _write_schedule(path, "5d 2h", "30m")
    ifc_file = _import_schedule(path)
    task_time = ifc_file.by_type("IfcTask")[0].TaskTime
    assert task_time.ScheduleDuration == "P5DT2H"
    assert task_time.ActualDuration == "PT30M"
