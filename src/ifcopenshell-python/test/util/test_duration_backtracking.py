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

# This file was generated with the assistance of an AI coding tool.

"""string_to_duration must not backtrack on a long run of digits.

The helper searches four patterns shaped like digits, an optional dot, more
digits, then a unit letter. A cell of digits with no d, h, m, or s letter makes
CPython's regex engine take cubic time. These tests fail while that is true
and pass once a digit run of CSV-field length is accepted or rejected quickly.
"""

import signal

import pytest

import ifcopenshell.util.date as subject

# csv.field_size_limit() on this interpreter is 131072. A work-schedule cell of
# that size is still one field, so the bound has to cover it.
BOUND_SECONDS = 1.0
CSV_FIELD_LIMIT = 131_072
ATTACK_DIGITS = 50_000


class DurationBacktrackingTimeout(BaseException):
    """Raised when parsing is still running after BOUND_SECONDS.

    BaseException so a later ``except Exception`` around the match cannot
    swallow the failure and turn a hang into a passing test.
    """


def _must_finish(func):
    def handler(signum, frame):
        raise DurationBacktrackingTimeout(f"duration parsing still running after {BOUND_SECONDS}s")

    previous = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, BOUND_SECONDS)
    try:
        return func()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize("length", [ATTACK_DIGITS, CSV_FIELD_LIMIT])
def test_digit_run_without_unit_finishes_quickly(length):
    """Every unit pattern is searched; none of them can match a digit run."""
    _must_finish(lambda: subject.string_to_duration("9" * length))


def test_digit_run_with_non_unit_suffix_finishes_quickly():
    """A trailing letter other than d, h, m, or s takes the same failing search."""
    _must_finish(lambda: subject.string_to_duration("9" * ATTACK_DIGITS + "x"))


def test_ordinary_durations_still_parse():
    assert subject.string_to_duration("2d") == "P2D"
    assert subject.string_to_duration("2.5d") == "P2DT12H"
    assert subject.string_to_duration("1h") == "PT1H"
    assert subject.string_to_duration("3m") == "PT3M"
    assert subject.string_to_duration("4s") == "PT4S"
    assert subject.string_to_duration("5d 2h 30m 10.5s") == "P5DT2H30M10.5S"
