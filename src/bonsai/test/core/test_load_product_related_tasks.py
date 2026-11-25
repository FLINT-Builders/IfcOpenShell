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

"""Loading product tasks must finish when Filter by Active Schedule is on.

``LoadProductTasks`` and the ``filter_by_active_schedule`` update callback both
call ``load_product_related_tasks``. With the filter on, that passes the
product and the active schedule to ``get_tasks_for_product``. These tests
drive that core function, and the baseline gantt comparison that calls
``get_task_work_schedule`` on declared tasks. They fail while a nested task
with no schedule assignment recurses forever.
"""

import importlib.util
import sys
import types
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.sequence
import ifcopenshell.guid
import ifcopenshell.util.sequence
import pytest

import bonsai.core.sequence as subject


@pytest.fixture(params=["IFC4", "IFC4X3"])
def model(request) -> ifcopenshell.file:
    ifc = ifcopenshell.api.project.create_file(version=request.param)
    ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject", name="Project")
    return ifc


class ScheduleTool:
    """The parts of ``tool.Sequence`` this core function actually calls.

    ``get_tasks_for_product`` is the real util lookup. ``tool.Sequence`` forwards
    to that same function and does not transform the product or the schedule.
    """

    def __init__(self, schedule, filter_on=True):
        self.schedule = schedule
        self.filter_on = filter_on
        self.loaded = None

    def is_filter_by_active_schedule(self) -> bool:
        return self.filter_on

    def get_active_work_schedule(self):
        return self.schedule

    def get_tasks_for_product(self, product, work_schedule=None):
        return ifcopenshell.util.sequence.get_tasks_for_product(product, work_schedule)

    def load_product_related_tasks(self, task_inputs, task_outputs) -> None:
        self.loaded = (list(task_inputs), list(task_outputs))


def _task(ifc, name, **kwargs):
    return ifcopenshell.api.sequence.add_task(ifc, name=name, **kwargs)


def _unassigned_child(ifc):
    schedule = ifcopenshell.api.sequence.add_work_schedule(ifc, name="Active")
    parent = _task(ifc, "Parent")
    child = _task(ifc, "Child", parent_task=parent)
    wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall", name="Wall")
    ifcopenshell.api.sequence.assign_process(ifc, relating_process=child, related_object=wall)
    return schedule, parent, child, wall


def test_filtered_load_of_an_unassigned_nested_task_returns_no_tasks(model):
    schedule, parent, child, wall = _unassigned_child(model)
    tool = ScheduleTool(schedule)
    assert ifcopenshell.util.sequence.get_parent_task(child) == parent

    result = subject.load_product_related_tasks(tool, product=wall)

    assert result == []
    assert tool.loaded == ([], [])


def test_filtered_load_keeps_a_task_nested_under_the_active_schedule(model):
    schedule = ifcopenshell.api.sequence.add_work_schedule(model, name="Active")
    root = _task(model, "Root", work_schedule=schedule)
    child = _task(model, "Child", parent_task=root)
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Wall")
    ifcopenshell.api.sequence.assign_process(model, relating_process=child, related_object=wall)
    tool = ScheduleTool(schedule)

    result = subject.load_product_related_tasks(tool, product=wall)

    assert result == [child]
    assert tool.loaded == ([child], [])


def test_filtered_load_without_an_active_schedule_does_not_look_up_tasks(model):
    _schedule, _parent, child, wall = _unassigned_child(model)
    tool = ScheduleTool(schedule=None, filter_on=True)

    result = subject.load_product_related_tasks(tool, product=wall)

    assert result == "No active work schedule."
    assert tool.loaded is None
    assert child in ifcopenshell.util.sequence.get_tasks_for_product(wall)[0]


def test_unfiltered_load_still_returns_the_nested_task(model):
    schedule, _parent, child, wall = _unassigned_child(model)
    tool = ScheduleTool(schedule, filter_on=False)

    result = subject.load_product_related_tasks(tool, product=wall)

    assert result == [child]
    assert tool.loaded == ([child], [])


def _load_sequence_class():
    """Return ``bonsai.tool.sequence.Sequence`` from its source file.

    Blender is not required for ``create_new_task_json``. When ``bpy`` is
    absent, the modules that file imports and this method does not call are
    replaced with empty modules so the real method can run.
    """
    if "bpy" in sys.modules:
        from bonsai.tool.sequence import Sequence

        return Sequence

    bpy = types.ModuleType("bpy")
    bpy.__path__ = []
    utils = types.ModuleType("bpy.utils")
    previews = types.ModuleType("bpy.utils.previews")
    utils.previews = previews
    bpy.utils = utils
    sys.modules["bpy"] = bpy
    sys.modules["bpy.utils"] = utils
    sys.modules["bpy.utils.previews"] = previews

    mathutils = types.ModuleType("mathutils")

    class Color:
        def __init__(self, *args, **kwargs):
            self.r = self.g = self.b = self.a = 0

    mathutils.Color = Color
    sys.modules["mathutils"] = mathutils

    bim = types.ModuleType("bonsai.bim")
    bim.__path__ = []
    helper = types.ModuleType("bonsai.bim.helper")
    bim.helper = helper
    sys.modules["bonsai.bim"] = bim
    sys.modules["bonsai.bim.helper"] = helper

    tool_dir = Path(__file__).resolve().parents[2] / "bonsai" / "tool"
    tool_mod = types.ModuleType("bonsai.tool")
    tool_mod.__path__ = [str(tool_dir)]
    sys.modules["bonsai.tool"] = tool_mod

    path = tool_dir / "sequence.py"
    spec = importlib.util.spec_from_file_location("bonsai.tool.sequence", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bonsai.tool.sequence"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.Sequence


def _declare(ifc, relating, related) -> None:
    ifc.create_entity(
        "IfcRelDefinesByObject",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=relating,
        RelatedObjects=[related],
    )


def _task_time(ifc, task, start: str):
    task_time = ifcopenshell.api.sequence.add_task_time(ifc, task=task)
    task_time.ScheduleStart = start
    return task_time


def test_baseline_gantt_ignores_a_declared_task_with_no_schedule(model):
    baseline = ifcopenshell.api.sequence.add_work_schedule(model, name="Baseline", predefined_type="BASELINE")
    parent = _task(model, "Parent")
    declared = _task(model, "Declared", parent_task=parent)
    planned = _task(model, "Planned")
    _declare(model, planned, declared)
    _task_time(model, planned, "2024-01-02T00:00:00")
    assert ifcopenshell.util.sequence.get_parent_task(declared) == parent
    assert list(planned.Declares[0].RelatedObjects) == [declared]

    rows = []
    _load_sequence_class().create_new_task_json(planned, rows, {None: "FS"}, baseline_schedule=baseline)

    assert rows[0]["pID"] == planned.id()
    assert rows[0]["pPlanStart"] == "2024-01-02T00:00:00"


def test_baseline_gantt_keeps_a_declared_task_of_the_baseline_schedule(model):
    baseline = ifcopenshell.api.sequence.add_work_schedule(model, name="Baseline", predefined_type="BASELINE")
    declared = _task(model, "Declared", work_schedule=baseline)
    planned = _task(model, "Planned")
    _declare(model, planned, declared)
    _task_time(model, planned, "2024-01-02T00:00:00")
    _task_time(model, declared, "1999-01-01T00:00:00")

    rows = []
    _load_sequence_class().create_new_task_json(planned, rows, {None: "FS"}, baseline_schedule=baseline)

    assert rows[0]["pID"] == planned.id()
    assert rows[0]["pPlanStart"] == "2024-01-02T00:00:00"
