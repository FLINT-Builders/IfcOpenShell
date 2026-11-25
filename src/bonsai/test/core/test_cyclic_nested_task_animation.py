# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2022 Dion Moult <dion@thinkmoult.com>
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

# This file was generated with the assistance of an AI coding tool.

"""Cyclic IfcRelNests must not exhaust the stack during work-schedule walks.

These tests load a written IFC file and call the schedule operations that
recurse through nested tasks. They fail while a cycle is followed without a
visited set, and they pass once each task is processed once and the operation
still reports that task's own dates and products.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.sequence
import ifcopenshell.guid
import ifcopenshell.util.sequence
import pytest

BONSAI_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DATE = datetime(2020, 1, 5)
IN_CONSTRUCTION_START = "2020-01-01"
IN_CONSTRUCTION_FINISH = "2020-01-20"
COMPLETED_START = "2020-01-01"
COMPLETED_FINISH = "2020-01-02"
TO_BUILD_START = "2020-02-01"
TO_BUILD_FINISH = "2020-02-10"


class Product:
    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return f"Product({self.name})"


class TaskList:
    def __init__(self) -> None:
        self._items: list[types.SimpleNamespace] = []

    def clear(self) -> None:
        self._items.clear()

    def add(self) -> types.SimpleNamespace:
        item = types.SimpleNamespace()
        self._items.append(item)
        return item

    def __iter__(self):
        return iter(self._items)


class ScheduleProps:
    def __init__(self) -> None:
        self.show_nested_inputs = False
        self.show_nested_outputs = False
        self.contracted_tasks = "[]"
        self.sort_column = ""
        self.is_sort_reversed = False
        # The work-schedule UI stores dates as day-first %d/%m/%y. get_start_date
        # parses that with dayfirst=True, so 05/01/20 is 5 January 2020.
        self.visualisation_start = "05/01/20"
        self.visualisation_finish = "01/03/20"
        self.speed_types = "MULTIPLIER_SPEED"
        self.speed_multiplier = 1
        self.task_bars = "[]"
        self.active_work_schedule_id = 0
        self.highlighted_task_id = 0
        self.is_task_update_enabled = True
        self.active_task_index = 0


def _load_sequence_module():
    """Import the real sequence tool without starting Blender."""
    if str(BONSAI_ROOT) not in sys.path:
        sys.path.insert(0, str(BONSAI_ROOT))

    bpy = types.ModuleType("bpy")
    bpy.types = types.ModuleType("bpy.types")
    bpy.props = types.ModuleType("bpy.props")
    bpy.utils = types.ModuleType("bpy.utils")
    bpy.app = types.SimpleNamespace(version=(4, 2, 0))
    bpy.context = types.SimpleNamespace(
        scene=types.SimpleNamespace(render=types.SimpleNamespace(fps=1), frame_start=1, frame_end=2)
    )
    bpy.data = types.SimpleNamespace(objects=[])
    sys.modules["bpy"] = bpy
    sys.modules["bpy.types"] = bpy.types
    sys.modules["bpy.props"] = bpy.props
    sys.modules["bpy.utils"] = bpy.utils

    mathutils = types.ModuleType("mathutils")

    class Color(tuple):
        def __new__(cls, *values):
            return tuple.__new__(cls, values or (0, 0, 0))

    mathutils.Color = Color
    mathutils.Vector = lambda *args, **kwargs: args
    mathutils.Euler = lambda *args, **kwargs: args
    sys.modules["mathutils"] = mathutils

    import bonsai.core.sequence as core_sequence

    bim = types.ModuleType("bonsai.bim")
    bim.__path__ = []
    bim.__package__ = "bonsai.bim"
    sys.modules["bonsai.bim"] = bim
    sys.modules["bonsai.bim.helper"] = types.ModuleType("bonsai.bim.helper")

    tool_mod = types.ModuleType("bonsai.tool")

    class Ifc:
        file = None
        objects: dict[int, Product] = {}

        @classmethod
        def get(cls):
            return cls.file

        @classmethod
        def get_object(cls, element):
            return cls.objects[element.id()]

    tool_mod.Ifc = Ifc
    sys.modules["bonsai.tool"] = tool_mod

    spec = importlib.util.spec_from_file_location(
        "bonsai.tool.sequence", BONSAI_ROOT / "bonsai" / "tool" / "sequence.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["bonsai.tool.sequence"] = module
    spec.loader.exec_module(module)
    module.core_sequence = core_sequence
    module.tool_mod = tool_mod
    return module


@pytest.fixture(scope="module")
def sequence_module():
    return _load_sequence_module()


@pytest.fixture(autouse=True)
def _bound_recursion():
    previous = sys.getrecursionlimit()
    sys.setrecursionlimit(200)
    yield
    sys.setrecursionlimit(previous)


@pytest.fixture
def seq(sequence_module):
    props = ScheduleProps()
    tree = types.SimpleNamespace(tasks=TaskList())
    recorded: dict = {}

    def show_snapshot(cls, product_states):
        recorded["states"] = product_states

    def set_object_shading(cls):
        recorded["shaded"] = True

    sequence_module.Sequence.get_work_schedule_props = classmethod(lambda cls: props)
    sequence_module.Sequence.get_task_tree_props = classmethod(lambda cls: tree)
    sequence_module.Sequence.show_snapshot = classmethod(show_snapshot)
    sequence_module.Sequence.set_object_shading = classmethod(set_object_shading)
    return types.SimpleNamespace(
        Sequence=sequence_module.Sequence,
        core=sequence_module.core_sequence,
        props=props,
        tree=tree,
        recorded=recorded,
        Ifc=sequence_module.tool_mod.Ifc,
    )


def _project(model: ifcopenshell.file) -> None:
    model.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Project")


def _reload(model: ifcopenshell.file) -> ifcopenshell.file:
    with tempfile.NamedTemporaryFile(suffix=".ifc") as handle:
        model.write(handle.name)
        return ifcopenshell.open(handle.name)


def _task(model, schedule, name: str, start: str | None, finish: str | None, controlled: bool):
    task = ifcopenshell.api.sequence.add_task(
        model, work_schedule=schedule if controlled else None, name=name, predefined_type="CONSTRUCTION"
    )
    if start is not None:
        task_time = ifcopenshell.api.sequence.add_task_time(model, task=task)
        ifcopenshell.api.sequence.edit_task_time(
            model,
            task_time=task_time,
            attributes={"ScheduleStart": start, "ScheduleFinish": finish},
        )
    wall = model.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name=f"Wall-{name}")
    ifcopenshell.api.sequence.assign_product(model, relating_product=wall, related_object=task)
    return task


def _nest(model, parent, child) -> None:
    model.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        Name=f"{parent.Name}-{child.Name}",
        RelatingObject=parent,
        RelatedObjects=[child],
    )


def _bind(seq, model: ifcopenshell.file) -> dict[str, Product]:
    seq.Ifc.file = model
    seq.Ifc.objects = {}
    products = {}
    for wall in model.by_type("IfcWall"):
        product = Product(wall.Name)
        seq.Ifc.objects[wall.id()] = product
        products[wall.Name] = product
    return products


def _names(bucket) -> set[str]:
    return {product.name for product in bucket}


def _schedule_of(model: ifcopenshell.file):
    return model.by_type("IfcWorkSchedule")[0]


def _tasks(model: ifcopenshell.file) -> dict[str, ifcopenshell.entity_instance]:
    return {task.Name: task for task in model.by_type("IfcTask")}


def _dated_cycle_model():
    """One controlled task leads a 12-cycle. A separate task is not in the cycle.

    A fixed recursion cap below the cycle length classifies the early tasks and
    drops the rest. Processing each task once classifies every wall.
    """
    model = ifcopenshell.file(schema="IFC4")
    _project(model)
    schedule = ifcopenshell.api.sequence.add_work_schedule(model, name="Construction")
    cycle = [
        _task(
            model,
            schedule,
            f"Cycle-{index}",
            IN_CONSTRUCTION_START,
            IN_CONSTRUCTION_FINISH,
            controlled=index == 0,
        )
        for index in range(12)
    ]
    for index, task in enumerate(cycle):
        _nest(model, task, cycle[(index + 1) % len(cycle)])
    _task(model, schedule, "Independent", COMPLETED_START, COMPLETED_FINISH, controlled=True)
    return _reload(model)


def _pair_model():
    """Two controlled tasks nest each other, plus one task outside the cycle."""
    model = ifcopenshell.file(schema="IFC4")
    _project(model)
    schedule = ifcopenshell.api.sequence.add_work_schedule(model, name="Construction")
    first = _task(model, schedule, "First", IN_CONSTRUCTION_START, IN_CONSTRUCTION_FINISH, controlled=True)
    second = _task(model, schedule, "Second", TO_BUILD_START, TO_BUILD_FINISH, controlled=True)
    _task(model, schedule, "Independent", COMPLETED_START, COMPLETED_FINISH, controlled=True)
    _nest(model, first, second)
    _nest(model, second, first)
    return _reload(model)


def _undated_cycle_model():
    """A cycle whose tasks have no dates, followed by a dated controlled task."""
    model = ifcopenshell.file(schema="IFC4")
    _project(model)
    schedule = ifcopenshell.api.sequence.add_work_schedule(model, name="Construction")
    first = _task(model, schedule, "Undated-A", None, None, controlled=True)
    second = _task(model, schedule, "Undated-B", None, None, controlled=False)
    _task(model, schedule, "Independent", COMPLETED_START, COMPLETED_FINISH, controlled=True)
    _nest(model, first, second)
    _nest(model, second, first)
    return _reload(model)


def _self_nest_model():
    model = ifcopenshell.file(schema="IFC4")
    _project(model)
    schedule = ifcopenshell.api.sequence.add_work_schedule(model, name="Construction")
    task = _task(model, schedule, "Self", IN_CONSTRUCTION_START, IN_CONSTRUCTION_FINISH, controlled=True)
    _nest(model, task, task)
    return _reload(model)


def _acyclic_model():
    model = ifcopenshell.file(schema="IFC4")
    _project(model)
    schedule = ifcopenshell.api.sequence.add_work_schedule(model, name="Construction")
    parent = _task(model, schedule, "Parent", IN_CONSTRUCTION_START, IN_CONSTRUCTION_FINISH, controlled=True)
    child = _task(model, schedule, "Child", TO_BUILD_START, TO_BUILD_FINISH, controlled=False)
    _nest(model, parent, child)
    return _reload(model)


def _activate(seq, schedule) -> None:
    seq.props.active_work_schedule_id = schedule.id()
    seq.props.contracted_tasks = "[]"
    seq.props.task_bars = "[]"
    seq.props.highlighted_task_id = 0


def test_acyclic_nest_still_classifies_parent_and_child(seq):
    model = _acyclic_model()
    products = _bind(seq, model)
    seq.props.show_nested_inputs = False
    seq.core.visualise_work_schedule_date(seq.Sequence, work_schedule=_schedule_of(model))
    states = seq.recorded["states"]
    assert seq.recorded["shaded"] is True
    assert products["Wall-Parent"] in states["IN_CONSTRUCTION"]
    assert products["Wall-Child"] in states["TO_BUILD"]


def test_snapshot_classifies_every_task_in_a_long_nest_cycle(seq):
    model = _dated_cycle_model()
    products = _bind(seq, model)
    seq.props.show_nested_inputs = False
    seq.core.visualise_work_schedule_date(seq.Sequence, work_schedule=_schedule_of(model))
    states = seq.recorded["states"]
    for index in range(12):
        assert products[f"Wall-Cycle-{index}"] in states["IN_CONSTRUCTION"]
    assert products["Wall-Independent"] in states["COMPLETED"]
    assert _names(states["TO_BUILD"]) == set()


def test_snapshot_classifies_a_controlled_pair_that_nests_each_other(seq):
    model = _pair_model()
    products = _bind(seq, model)
    seq.props.show_nested_inputs = False
    states = seq.Sequence.process_construction_state(_schedule_of(model), SNAPSHOT_DATE)
    assert products["Wall-First"] in states["IN_CONSTRUCTION"]
    assert products["Wall-Second"] in states["TO_BUILD"]
    assert products["Wall-Independent"] in states["COMPLETED"]


def test_snapshot_reaches_later_tasks_when_a_cycle_has_no_dates(seq):
    model = _undated_cycle_model()
    products = _bind(seq, model)
    seq.props.show_nested_inputs = False
    states = seq.Sequence.process_construction_state(_schedule_of(model), SNAPSHOT_DATE)
    assert products["Wall-Independent"] in states["COMPLETED"]
    assert products["Wall-Undated-A"] not in states["IN_CONSTRUCTION"]
    assert products["Wall-Undated-B"] not in states["IN_CONSTRUCTION"]


def test_snapshot_classifies_a_task_that_nests_itself(seq):
    model = _self_nest_model()
    products = _bind(seq, model)
    states = seq.Sequence.process_construction_state(_schedule_of(model), SNAPSHOT_DATE)
    assert products["Wall-Self"] in states["IN_CONSTRUCTION"]


def test_snapshot_with_nested_inputs_still_classifies_the_cycle(seq):
    model = _dated_cycle_model()
    products = _bind(seq, model)
    seq.props.show_nested_inputs = True
    states = seq.Sequence.process_construction_state(_schedule_of(model), SNAPSHOT_DATE)
    for index in range(12):
        assert products[f"Wall-Cycle-{index}"] in states["IN_CONSTRUCTION"]
    assert products["Wall-Independent"] in states["COMPLETED"]


def test_date_range_frames_include_every_product_in_the_cycle(seq):
    model = _dated_cycle_model()
    products = _bind(seq, model)
    seq.props.show_nested_inputs = False
    settings = seq.Sequence.get_animation_settings()
    frames = seq.Sequence.get_animation_product_frames(_schedule_of(model), settings)
    for index in range(12):
        wall_id = next(wall.id() for wall in model.by_type("IfcWall") if wall.Name == f"Wall-Cycle-{index}")
        assert frames[wall_id][0]["relationship"] == "output"
        assert products[f"Wall-Cycle-{index}"].name == f"Wall-Cycle-{index}"
    independent_id = next(wall.id() for wall in model.by_type("IfcWall") if wall.Name == "Wall-Independent")
    assert independent_id in frames


def test_nested_task_walk_yields_each_task_in_a_cycle_once():
    model = _dated_cycle_model()
    tasks = _tasks(model)
    names = [task.Name for task in ifcopenshell.util.sequence.get_all_nested_tasks(tasks["Cycle-0"])]
    assert names.count("Cycle-1") == 1
    assert names.count("Cycle-11") == 1
    assert len(names) == len(set(names))
    assert len(names) <= 12


def test_derived_dates_come_from_the_dated_task_in_a_cycle():
    model = ifcopenshell.file(schema="IFC4")
    _project(model)
    schedule = ifcopenshell.api.sequence.add_work_schedule(model, name="Construction")
    dated = _task(model, schedule, "Dated", IN_CONSTRUCTION_START, IN_CONSTRUCTION_FINISH, controlled=True)
    undated = _task(model, schedule, "Undated", None, None, controlled=False)
    _nest(model, undated, dated)
    _nest(model, dated, undated)
    model = _reload(model)
    tasks = _tasks(model)
    start = ifcopenshell.util.sequence.derive_date(tasks["Undated"], "ScheduleStart", is_earliest=True)
    finish = ifcopenshell.util.sequence.derive_date(tasks["Undated"], "ScheduleFinish", is_latest=True)
    assert start == datetime(2020, 1, 1, 9, 0)
    assert finish == datetime(2020, 1, 20, 17, 0)


def test_guess_date_range_returns_dates_from_a_cyclic_schedule():
    model = _pair_model()
    earliest, latest = ifcopenshell.util.sequence.guess_date_range(_schedule_of(model))
    assert earliest == datetime(2020, 1, 1, 9, 0)
    assert latest == datetime(2020, 2, 10, 17, 0)


def test_work_schedule_task_iterator_lists_a_cycle_once():
    model = _dated_cycle_model()
    names = [task.Name for task in ifcopenshell.util.sequence.get_work_schedule_tasks(_schedule_of(model))]
    assert names.count("Cycle-0") == 1
    assert names.count("Cycle-11") == 1
    assert names.count("Independent") == 1
    assert len(names) == len(set(names))


def test_task_json_lists_each_cyclic_task(seq):
    model = _pair_model()
    _bind(seq, model)
    payload = seq.Sequence.create_tasks_json(_schedule_of(model))
    names = [row["pName"] for row in payload]
    assert names.count("First") >= 1
    assert names.count("Second") >= 1
    assert names.count("Independent") == 1
    assert len(payload) <= 5


def test_task_tree_lists_a_cyclic_pair(seq):
    model = _pair_model()
    _bind(seq, model)
    schedule = _schedule_of(model)
    _activate(seq, schedule)
    seq.Sequence.load_task_tree(schedule)
    listed = [item.ifc_definition_id for item in seq.tree.tasks]
    tasks = _tasks(model)
    assert tasks["First"].id() in listed
    assert tasks["Second"].id() in listed
    assert tasks["Independent"].id() in listed
    assert len(listed) <= 5


def test_go_to_task_opens_a_cyclic_task(seq):
    model = _pair_model()
    _bind(seq, model)
    schedule = _schedule_of(model)
    _activate(seq, schedule)
    task = _tasks(model)["Second"]
    seq.Sequence.go_to_task(task)
    listed = [item.ifc_definition_id for item in seq.tree.tasks]
    assert task.id() in listed
    assert seq.props.active_task_index == listed.index(task.id())


def test_calendar_derivation_stops_on_a_nest_cycle():
    model = _pair_model()
    task = _tasks(model)["First"]
    assert ifcopenshell.util.sequence.derive_calendar(task) is None


def test_task_work_schedule_resolves_inside_a_nest_cycle():
    model = _pair_model()
    schedule = _schedule_of(model)
    task = _tasks(model)["Second"]
    assert ifcopenshell.util.sequence.get_task_work_schedule(task) == schedule


def test_direct_work_schedule_lookup_stops_on_an_unassigned_cycle(seq):
    model = ifcopenshell.file(schema="IFC4")
    _project(model)
    schedule = ifcopenshell.api.sequence.add_work_schedule(model, name="Construction")
    first = _task(model, schedule, "Loose-A", IN_CONSTRUCTION_START, IN_CONSTRUCTION_FINISH, controlled=False)
    second = _task(model, schedule, "Loose-B", IN_CONSTRUCTION_START, IN_CONSTRUCTION_FINISH, controlled=False)
    _nest(model, first, second)
    _nest(model, second, first)
    model = _reload(model)
    _bind(seq, model)
    task = _tasks(model)["Loose-A"]
    assert seq.Sequence.get_work_schedule(task) is None


def test_recalculate_schedule_updates_a_task_outside_a_nest_cycle():
    pytest.importorskip("networkx")
    model = ifcopenshell.file(schema="IFC4")
    _project(model)
    schedule = ifcopenshell.api.sequence.add_work_schedule(model, name="Construction")
    first = _task(model, schedule, "Cycle-A", None, None, controlled=True)
    second = _task(model, schedule, "Cycle-B", None, None, controlled=False)
    _nest(model, first, second)
    _nest(model, second, first)
    leaf = ifcopenshell.api.sequence.add_task(model, work_schedule=schedule, name="Leaf")
    task_time = ifcopenshell.api.sequence.add_task_time(model, task=leaf)
    ifcopenshell.api.sequence.edit_task_time(
        model,
        task_time=task_time,
        attributes={"ScheduleStart": datetime(2000, 1, 1), "ScheduleDuration": "P1D"},
    )
    model = _reload(model)
    leaf = _tasks(model)["Leaf"]
    ifcopenshell.api.sequence.recalculate_schedule(model, work_schedule=_schedule_of(model))
    assert leaf.TaskTime.EarlyStart == "2000-01-01T09:00:00"
    assert leaf.TaskTime.IsCritical is True
