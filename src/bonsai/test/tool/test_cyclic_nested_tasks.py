# This file was generated with the assistance of an AI coding tool.
"""Cyclic IfcTask nesting must not exhaust the stack.

A work schedule saved in an IFC file can contain IfcRelNests relationships
that loop. Loading that schedule in the sequencing UI walks those relationships
with no record of tasks already entered. These tests open such a file and run
the walks the product runs. They fail while a walk recurses until the stack
is exhausted, and they pass when a task already on the stack is skipped and
every task is still emitted once.

Blender property storage is replaced with plain objects. The nest walk, the
IFC file, and the schedule functions are the product code.

Not covered here: cascade_schedule already raises when a task reappears in its
task_sequence; create_new_task_json on IFC2X3 reads IfcTask.TaskTime, which that
schema does not have, so it never reaches the walk; IfcCostItem and IfcResource
trees use the same unguarded nesting pattern on different entities.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import networkx

# ifcopenshell.api.sequence loads recalculate_schedule only when networkx is already imported.
_ = networkx.DiGraph

_REPO = Path(__file__).resolve().parents[4]
_CREATED_LINKS: list[Path] = []


def _prefer_checkout_sources() -> None:
    """Import this checkout's Python, using a built wrapper when the checkout has none."""
    pkg = _REPO / "src" / "ifcopenshell-python" / "ifcopenshell"
    wrapper_py = pkg / "ifcopenshell_wrapper.py"
    if not wrapper_py.exists() or not any(pkg.glob("_ifcopenshell_wrapper*.so")):
        import ifcopenshell as installed

        installed_dir = Path(installed.__file__).resolve().parent
        for name in list(sys.modules):
            if name == "ifcopenshell" or name.startswith("ifcopenshell."):
                del sys.modules[name]
        if not wrapper_py.exists():
            os.symlink(installed_dir / "ifcopenshell_wrapper.py", wrapper_py)
            _CREATED_LINKS.append(wrapper_py)
        for library in installed_dir.glob("_ifcopenshell_wrapper*.so"):
            dest = pkg / library.name
            if not dest.exists():
                os.symlink(library, dest)
                _CREATED_LINKS.append(dest)
    for entry in (
        _REPO / "src" / "ifcopenshell-python",
        _REPO / "src" / "bonsai",
        _REPO / "src" / "ifcquery",
    ):
        entry_s = str(entry)
        if entry_s not in sys.path:
            sys.path.insert(0, entry_s)


def _cleanup_links() -> None:
    for path in _CREATED_LINKS:
        if path.is_symlink():
            path.unlink()


_prefer_checkout_sources()
import atexit

atexit.register(_cleanup_links)

if "bpy" not in sys.modules:

    class _AnyAttr:
        def __getattr__(self, item):
            if item.startswith("__"):
                raise AttributeError(item)
            return type(item, (), {})

        def __call__(self, *args, **kwargs):
            return None

    bpy = ModuleType("bpy")
    bpy.__path__ = []
    bpy.context = SimpleNamespace(scene=SimpleNamespace())
    bpy.types = _AnyAttr()
    bpy.app = _AnyAttr()
    bpy.data = _AnyAttr()
    bpy.ops = _AnyAttr()
    bpy.props = _AnyAttr()
    sys.modules["bpy"] = bpy
    bpy_utils = ModuleType("bpy.utils")
    bpy_utils.previews = _AnyAttr()
    sys.modules["bpy.utils"] = bpy_utils

    mathutils = ModuleType("mathutils")

    class Color:
        def __init__(self, rgb=(0, 0, 0)):
            values = list(rgb) + [0, 0, 0]
            self.r, self.g, self.b = values[:3]

    mathutils.Color = Color
    sys.modules["mathutils"] = mathutils

if "bonsai.tool" not in sys.modules:
    tool_mod = ModuleType("bonsai.tool")
    tool_mod.__path__ = [str(_REPO / "src" / "bonsai" / "bonsai" / "tool")]
    tool_mod.__package__ = "bonsai.tool"
    sys.modules["bonsai.tool"] = tool_mod

if "bonsai.bim" not in sys.modules:
    bim_mod = ModuleType("bonsai.bim")
    bim_mod.__path__ = [str(_REPO / "src" / "bonsai" / "bonsai" / "bim")]
    bim_mod.__package__ = "bonsai.bim"
    sys.modules["bonsai.bim"] = bim_mod

import ifcopenshell
import ifcopenshell.api.sequence
import ifcopenshell.util.sequence as seq
import pytest
from ifcquery.schedule import schedule as query_schedule

import bonsai.core.sequence as core
import bonsai.tool as tool
import bonsai.tool.sequence as sequence_mod
from bonsai.tool.sequence import Sequence

assert Path(seq.__file__).resolve().is_relative_to(_REPO)
assert Path(sequence_mod.__file__).resolve().is_relative_to(_REPO)


class _Rows:
    def __init__(self):
        self._items = []

    def clear(self):
        self._items.clear()

    def add(self):
        row = SimpleNamespace(
            ifc_definition_id=0,
            is_expanded=True,
            level_index=0,
            has_children=False,
            name="",
            identification="",
            has_bar_visual=False,
            calendar="",
            derived_calendar="",
            start="",
            finish="",
            duration="",
            derived_start="",
            derived_finish="",
            derived_duration="",
        )
        self._items.append(row)
        return row

    def __iter__(self):
        return iter(self._items)


class _Props:
    def __init__(self):
        self.tasks = _Rows()
        self.contracted_tasks = "[]"
        self.sort_column = ""
        self.is_sort_reversed = False
        self.active_work_schedule_id = 0
        self.editing_type = ""
        self.task_bars = "[]"
        self.highlighted_task_id = 0
        self.is_task_update_enabled = False
        self.active_task_id = 0
        self.active_task_time_id = 0
        self.active_task_index = 0
        self.product_input_tasks = _Rows()
        self.product_output_tasks = _Rows()


class _Ifc:
    file = None

    @classmethod
    def get(cls):
        return cls.file


_SENT = []


class _Web:
    @classmethod
    def get_web_props(cls):
        # The sequencing page is already connected when it asks for a schedule.
        return SimpleNamespace(is_connected=True)

    @classmethod
    def send_webui_data(cls, data=None, data_key="data", event="data", namespace="/blender", use_web_data=True):
        _SENT.append({"data": data, "data_key": data_key, "event": event})


tool.Ifc = _Ifc
tool.Web = _Web
sequence_mod.tool.Ifc = _Ifc
sequence_mod.tool.Web = _Web

_WORK_PROPS = _Props()
_TREE_PROPS = _Props()


def _work_props(cls):
    return _WORK_PROPS


def _tree_props(cls):
    return _TREE_PROPS


Sequence.get_work_schedule_props = classmethod(_work_props)
Sequence.get_task_tree_props = classmethod(_tree_props)


def _reset_props():
    global _WORK_PROPS, _TREE_PROPS
    _WORK_PROPS = _Props()
    _TREE_PROPS = _Props()
    _SENT.clear()
    Sequence.contracted_tasks = []


@pytest.fixture(autouse=True)
def _fresh_props():
    _reset_props()
    yield
    _reset_props()


def _nest(model, parent, children):
    model.create_entity("IfcRelNests", RelatingObject=parent, RelatedObjects=list(children))


def _task(model, name):
    return model.create_entity("IfcTask", Name=name)


def _schedule_with(model, tasks):
    schedule = model.create_entity("IfcWorkSchedule", Name="Schedule")
    model.create_entity("IfcRelAssignsToControl", RelatingControl=schedule, RelatedObjects=list(tasks))
    return schedule


def _open_copy(model):
    handle, path = tempfile.mkstemp(suffix=".ifc")
    os.close(handle)
    try:
        model.write(path)
        spf = Path(path).read_text(encoding="utf-8", errors="replace")
        opened = ifcopenshell.open(path)
    finally:
        os.remove(path)
    return opened, spf


def _pair_model(schema="IFC4"):
    model = ifcopenshell.file(schema=schema)
    first = _task(model, "A")
    second = _task(model, "B")
    _nest(model, first, [second])
    _nest(model, second, [first])
    schedule = _schedule_with(model, [first])
    opened, spf = _open_copy(model)
    return opened, spf, schedule.id()


def _bind(model):
    _Ifc.file = model
    return model


def _by_name(model, name):
    return next(task for task in model.by_type("IfcTask") if task.Name == name)


def _schedule(model, schedule_id=None):
    if schedule_id is None:
        return model.by_type("IfcWorkSchedule")[0]
    return model.by_id(schedule_id)


def _ids(rows):
    return [row["pID"] for row in rows]


def test_listing_a_cyclic_schedule_does_not_walk_nesting():
    """The page lists schedules before the user opens one. That list must stay available."""
    model, spf, schedule_id = _pair_model()
    assert "IFCRELNESTS" in spf.upper()
    assert "IFCRELASSIGNSTOCONTROL" in spf.upper()
    schedule = _schedule(model, schedule_id)
    info = schedule.get_info(recursive=True)
    assert info["id"] == schedule.id()
    assert info["Name"] == "Schedule"


def test_acyclic_schedule_emits_parent_then_child():
    model = ifcopenshell.file(schema="IFC4")
    parent = _task(model, "Parent")
    child = _task(model, "Child")
    grandchild = _task(model, "Grandchild")
    _nest(model, parent, [child])
    _nest(model, child, [grandchild])
    schedule = _schedule_with(model, [parent])
    model, _spf = _open_copy(model)
    _bind(model)
    schedule = _schedule(model, schedule.id())
    rows = Sequence.create_tasks_json(schedule)
    assert _ids(rows) == [parent.id(), child.id(), grandchild.id()]
    Sequence.load_task_tree(schedule)
    assert [row.ifc_definition_id for row in _TREE_PROPS.tasks] == [parent.id(), child.id(), grandchild.id()]
    core.generate_gantt_chart(Sequence, work_schedule=schedule)
    assert _ids(_SENT[-1]["data"]["tasks"]) == [parent.id(), child.id(), grandchild.id()]


@pytest.mark.parametrize("schema", ["IFC4", "IFC4X3"])
def test_mutual_cycle_serializes_each_task_once(schema):
    model, _spf, schedule_id = _pair_model(schema)
    _bind(model)
    schedule = _schedule(model, schedule_id)
    rows = Sequence.create_tasks_json(schedule)
    assert _ids(rows) == [_by_name(model, "A").id(), _by_name(model, "B").id()]


def test_task_that_nests_itself_is_serialized_once():
    model = ifcopenshell.file(schema="IFC4")
    task = _task(model, "Loop")
    _nest(model, task, [task])
    schedule = _schedule_with(model, [task])
    model, _spf = _open_copy(model)
    _bind(model)
    rows = Sequence.create_tasks_json(_schedule(model, schedule.id()))
    assert _ids(rows) == [_by_name(model, "Loop").id()]


def test_three_task_cycle_serializes_each_task_once():
    model = ifcopenshell.file(schema="IFC4")
    first, second, third = _task(model, "A"), _task(model, "B"), _task(model, "C")
    _nest(model, first, [second])
    _nest(model, second, [third])
    _nest(model, third, [first])
    schedule = _schedule_with(model, [first])
    model, _spf = _open_copy(model)
    _bind(model)
    rows = Sequence.create_tasks_json(_schedule(model, schedule.id()))
    assert _ids(rows) == [_by_name(model, "A").id(), _by_name(model, "B").id(), _by_name(model, "C").id()]


def test_cycle_under_a_root_task_serializes_the_root_and_both_tasks():
    model = ifcopenshell.file(schema="IFC4")
    root = _task(model, "Root")
    first, second = _task(model, "A"), _task(model, "B")
    _nest(model, root, [first])
    _nest(model, first, [second])
    _nest(model, second, [first])
    schedule = _schedule_with(model, [root])
    model, _spf = _open_copy(model)
    _bind(model)
    rows = Sequence.create_tasks_json(_schedule(model, schedule.id()))
    assert _ids(rows) == [_by_name(model, "Root").id(), _by_name(model, "A").id(), _by_name(model, "B").id()]


def test_load_work_schedule_operator_finishes_and_sends_each_task_once():
    """handle_gantt_operator('loadWorkSchedule') enables editing, then builds the chart.

    Enabling editing loads the task tree before generate_gantt_chart runs.
    """
    model, _spf, schedule_id = _pair_model()
    _bind(model)
    schedule = model.by_id(schedule_id)
    core.enable_editing_work_schedule_tasks(Sequence, work_schedule=schedule)
    assert [row.ifc_definition_id for row in _TREE_PROPS.tasks] == [
        _by_name(model, "A").id(),
        _by_name(model, "B").id(),
    ]
    assert _WORK_PROPS.active_work_schedule_id == schedule.id()
    core.generate_gantt_chart(Sequence, work_schedule=schedule)
    assert _SENT[-1]["data_key"] == "gantt_data"
    assert _ids(_SENT[-1]["data"]["tasks"]) == [_by_name(model, "A").id(), _by_name(model, "B").id()]


def test_edit_task_rebuild_uses_the_same_task_json():
    model, _spf, schedule_id = _pair_model()
    _bind(model)
    rows = Sequence.create_tasks_json(model.by_id(schedule_id))
    assert _ids(rows) == [_by_name(model, "A").id(), _by_name(model, "B").id()]


def test_load_task_properties_derives_dates_for_a_cyclic_task():
    model, _spf, _schedule_id = _pair_model()
    _bind(model)
    task = _by_name(model, "A")
    row = _TREE_PROPS.tasks.add()
    row.ifc_definition_id = task.id()
    Sequence.load_task_properties()
    assert row.name == "A"
    assert row.derived_start == ""
    assert row.derived_finish == ""


def test_ifc2x3_nested_cycle_yields_the_other_task_once():
    """IFC2X3 stores nesting on IsDecomposedBy. create_new_task_json is not called here:
    IfcTask has no TaskTime attribute in IFC2X3, so that builder raises before the walk.
    """
    model = ifcopenshell.file(schema="IFC2X3")
    first, second = _task(model, "A"), _task(model, "B")
    _nest(model, first, [second])
    _nest(model, second, [first])
    model, _spf = _open_copy(model)
    first, second = _by_name(model, "A"), _by_name(model, "B")
    assert [task.Name for task in seq.get_nested_tasks(first)] == ["B"]
    assert [task.id() for task in seq.get_all_nested_tasks(first)] == [second.id()]


def test_nested_task_queries_visit_each_task_once():
    model, _spf, schedule_id = _pair_model()
    schedule = _schedule(model, schedule_id)
    first, second = _by_name(model, "A"), _by_name(model, "B")
    assert [task.id() for task in seq.get_all_nested_tasks(first)] == [second.id()]
    assert [task.id() for task in seq.get_work_schedule_tasks(schedule)] == [first.id(), second.id()]
    assert seq.get_task_outputs(first, is_recursive=True) == set()
    assert seq.get_task_inputs(first, is_recursive=True) == set()
    assert seq.get_task_resources(first, is_recursive=True) == set()
    assert seq.derive_date(first, "ScheduleStart", is_earliest=True) is None
    assert seq.derive_date(first, "ScheduleFinish", is_latest=True) is None
    assert seq.derive_calendar(first) is None
    assert seq.get_sequence_assignment(first) == []
    assert seq.guess_date_range(schedule) == (None, None)
    assert seq.get_task_work_schedule(first).id() == schedule.id()
    assert seq.get_task_work_schedule(second).id() == schedule.id()


def test_parent_walk_without_an_assignment_returns_no_schedule():
    model = ifcopenshell.file(schema="IFC4")
    first, second = _task(model, "A"), _task(model, "B")
    _nest(model, first, [second])
    _nest(model, second, [first])
    model, _spf = _open_copy(model)
    _bind(model)
    first = _by_name(model, "A")
    assert seq.get_task_work_schedule(first) is None
    assert Sequence.get_work_schedule(first) is None


def test_go_to_task_on_a_cycle_selects_the_task():
    model, _spf, schedule_id = _pair_model()
    _bind(model)
    schedule = _schedule(model, schedule_id)
    _WORK_PROPS.active_work_schedule_id = schedule.id()
    task = _by_name(model, "B")
    Sequence.go_to_task(task)
    assert _WORK_PROPS.active_task_index == [row.ifc_definition_id for row in _TREE_PROPS.tasks].index(task.id())


def test_animation_and_snapshot_walks_finish():
    model, _spf, schedule_id = _pair_model()
    _bind(model)
    schedule = _schedule(model, schedule_id)
    frames = Sequence.get_animation_product_frames(schedule, {})
    assert frames == {}
    moment = datetime(2020, 1, 1)
    states = Sequence.process_construction_state(schedule, moment)
    assert states["TO_BUILD"] == set()
    assert states["COMPLETED"] == set()


def test_schedule_query_lists_each_cyclic_task_once():
    model, _spf, schedule_id = _pair_model()
    result = query_schedule(model)
    assert len(result) == 1
    assert result[0]["id"] == schedule_id

    found = []

    def walk(nodes):
        for node in nodes:
            found.append(node["id"])
            children = node["subtasks"]
            if isinstance(children, list):
                walk(children)

    walk(result[0]["tasks"])
    assert found == [_by_name(model, "A").id(), _by_name(model, "B").id()]


def test_duplicate_task_copies_a_cycle_once():
    model, _spf, _schedule_id = _pair_model()
    original = _by_name(model, "A")
    originals, copies = ifcopenshell.api.sequence.duplicate_task(model, task=original)
    assert len(originals) == 2
    assert len(copies) == 2
    assert len({task.id() for task in copies}) == 2
    assert len(model.by_type("IfcTask")) == 4


def test_remove_task_deletes_a_cycle_without_growing_the_file():
    model = ifcopenshell.file(schema="IFC4")
    model.create_entity("IfcProject", Name="Project")
    first, second = _task(model, "A"), _task(model, "B")
    _nest(model, first, [second])
    _nest(model, second, [first])
    model, _spf = _open_copy(model)
    before = len(model.by_type("IfcTask"))
    ifcopenshell.api.sequence.remove_task(model, task=_by_name(model, "A"))
    assert before == 2
    assert len(model.by_type("IfcTask")) == 0


def test_recalculate_schedule_returns_on_a_nest_cycle():
    model, _spf, schedule_id = _pair_model()
    schedule = _schedule(model, schedule_id)
    assert ifcopenshell.api.sequence.recalculate_schedule(model, work_schedule=schedule) is None
    assert len(model.by_type("IfcTask")) == 2


def test_non_cyclic_schedule_still_finds_its_work_schedule():
    model = ifcopenshell.file(schema="IFC4")
    parent = _task(model, "Parent")
    child = _task(model, "Child")
    _nest(model, parent, [child])
    schedule = _schedule_with(model, [parent])
    model, _spf = _open_copy(model)
    child = _by_name(model, "Child")
    assert seq.get_task_work_schedule(child).id() == schedule.id()
    assert Sequence.get_work_schedule(child).id() == schedule.id()
