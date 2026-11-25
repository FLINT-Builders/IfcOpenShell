# This file was generated with the assistance of an AI coding tool.
# Ifc4D - IFC scheduling utility
# Copyright (C) 2026 IfcOpenShell Contributors
#
# This file is part of Ifc4D.
#
# Ifc4D is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Microsoft Project XML whose outline cycles must be rejected.

MSP2Ifc derives each row's parent from OutlineLevel and then
MSPIfcGenerator.create_node walks that tree. A file can list the same UID
again under one of its own descendants, or under itself. The walk has to stop
and reject the schedule. It must not follow the cycle until Python raises
RecursionError, and it must not write an output file or emit the same
breakdown id twice.

The expected failure, until that rejection exists, is RecursionError (or an
IfcTask count higher than the number of distinct UIDs).
"""

import re
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.root
import pytest

from ifc4d.msp2ifc import MSP2Ifc

NS = "http://schemas.microsoft.com/project"
CYCLE_WORD = re.compile(r"cycle|circular|loop", re.I)


def _msp(tasks, path, ifc):
    rows = []
    for uid, level, name in tasks:
        rows.append(
            "<Task>"
            f"<UID>{uid}</UID>"
            f"<Name>{name}</Name>"
            f"<OutlineLevel>{level}</OutlineLevel>"
            "<OutlineNumber>1</OutlineNumber>"
            "<IsNull>0</IsNull>"
            "<Start>2024-01-01T08:00:00</Start>"
            "<Finish>2024-01-02T17:00:00</Finish>"
            "<CalendarUID>1</CalendarUID>"
            "</Task>"
        )
    # One base calendar so a leaf activity has somewhere to land. The cyclic
    # cases never reach a leaf; the calendar is there so the same document
    # shape is what a real export carries.
    document = (
        f'<Project xmlns="{NS}">'
        "<Title>Outline</Title>"
        "<CalendarUID>1</CalendarUID>"
        "<MinutesPerDay>480</MinutesPerDay>"
        "<Calendars><Calendar>"
        "<UID>1</UID><Name>Standard</Name><IsBaseCalendar>1</IsBaseCalendar>"
        "<WeekDays><WeekDay><DayType>2</DayType>"
        "<WorkingTimes><WorkingTime>"
        "<FromTime>08:00:00</FromTime><ToTime>17:00:00</ToTime>"
        "</WorkingTime></WorkingTimes>"
        "</WeekDay></WeekDays>"
        "</Calendar></Calendars>"
        "<Tasks>" + "".join(rows) + "</Tasks>"
        "</Project>"
    )
    path.write_text(document, encoding="utf-8")
    converter = MSP2Ifc()
    converter.xml = str(path)
    converter.file = ifc
    converter.output = str(path.with_suffix(".ifc"))
    return converter


def _ifc():
    ifc = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
    return ifc


def _assert_rejected(converter, ifc, distinct_ids):
    output = Path(converter.output)
    with pytest.raises(Exception) as caught:
        converter.execute()
    error = caught.value
    assert not isinstance(error, RecursionError), "import followed the outline cycle until the stack ran out"
    assert CYCLE_WORD.search(str(error)), error
    assert not output.exists(), "output was written before the cycle was rejected"
    # One emit per breakdown id. A walk that notices the repeat only after
    # RecursionError has already created one task per recursive call.
    assert len(ifc.by_type("IfcTask")) <= distinct_ids


def test_mutual_outline_cycle_is_rejected(tmp_path):
    """A root, and two rows that become each other's parent, one UID repeated.

    Row 1 (UID 1, level 1) is the root. Row 2 (UID 2, level 2) hangs under it.
    Row 3 reuses UID 1 at level 3, so UID 1 is recorded as a child of UID 2
    while UID 1 is still the root. Following children returns to UID 1.
    """
    ifc = _ifc()
    tasks = [(1, 1, "Root"), (2, 2, "Branch"), (1, 3, "Root again")]
    converter = _msp(tasks, tmp_path / "mutual.xml", ifc)
    _assert_rejected(converter, ifc, distinct_ids=2)


def test_self_parent_outline_is_rejected(tmp_path):
    """The same UID is its own child and is still reachable from the root."""
    ifc = _ifc()
    tasks = [(1, 1, "Root"), (1, 2, "Root again")]
    converter = _msp(tasks, tmp_path / "self.xml", ifc)
    _assert_rejected(converter, ifc, distinct_ids=1)


def test_acyclic_outline_imports(tmp_path):
    """A normal two-level outline still imports, including its leaf activity."""
    ifc = _ifc()
    tasks = [(1, 1, "Root"), (2, 2, "Leaf")]
    converter = _msp(tasks, tmp_path / "tree.xml", ifc)
    converter.execute()
    output = Path(converter.output)
    assert output.exists()
    written = ifcopenshell.open(str(output))
    names = sorted(task.Name for task in written.by_type("IfcTask"))
    assert names == ["Leaf", "Root"]
