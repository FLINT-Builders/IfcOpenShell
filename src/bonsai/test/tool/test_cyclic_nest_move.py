# This file was generated with the assistance of an AI coding tool.
# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 Bonsai contributors
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Cyclic IfcRelNests and IfcRelAggregates must not hang Bonsai's move expansion.

The IFC move command (G, ``bim.override_move_macro``) and the linked-aggregate
duplicate macro both run ``OverrideMoveSelect._execute``. That method expands a
selected nest with ``Nest.get_components_recursively`` and an aggregate with
``Aggregate.get_parts_recursively`` / ``get_aggregates_recursively``. None of
those walks record an element id before expanding it.

These tests open a file the parser accepts, then run those walks. They fail
while a repeated id is expanded again. They pass once each walk records ids
before expanding and skips an id it has already seen, without dropping an
unseen sibling of the cycle. Acyclic chains keep today's results.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.cost
import ifcopenshell.util.element as installed_element
import ifcopenshell.util.sequence

REPO = Path(__file__).resolve().parents[4]
BONSAI_ROOT = REPO / "src" / "bonsai"
ELEMENT_PATH = REPO / "src" / "ifcopenshell-python" / "ifcopenshell" / "util" / "element.py"
OPERATOR_PATH = BONSAI_ROOT / "bonsai" / "bim" / "module" / "geometry" / "operator.py"
WALK_SECONDS = 3


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_repo_element():
    # Bind the walks to this checkout. The native parser still comes from the
    # installed ifcopenshell wrapper, which this commit's pure-Python helpers match.
    module = _load_module("repo_ifcopenshell_element", ELEMENT_PATH)
    for name in (
        "get_aggregate",
        "get_components",
        "get_decomposition",
        "get_nest",
        "get_parts",
        "get_pset",
    ):
        setattr(installed_element, name, getattr(module, name))
    return module


def _stub(name: str, **attrs):
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _load_tool_class(filename: str, class_name: str):
    if "bonsai.core.tool" not in sys.modules:
        sys.path.insert(0, str(BONSAI_ROOT))
        import bonsai.core.tool  # ruff: ignore[unused-import]

    _stub("bpy")
    tool_stub = _stub("bonsai.tool")
    tool_stub.__path__ = []
    module_name = f"bonsai.tool.{filename[:-3]}"
    module = _load_module(module_name, BONSAI_ROOT / "bonsai" / "tool" / filename)
    setattr(tool_stub, class_name, getattr(module, class_name))
    return getattr(module, class_name)


def _load_project_class():
    sys.path.insert(0, str(BONSAI_ROOT))
    import bonsai.core.aggregate  # ruff: ignore[unused-import]
    import bonsai.core.context  # ruff: ignore[unused-import]
    import bonsai.core.owner  # ruff: ignore[unused-import]
    import bonsai.core.root  # ruff: ignore[unused-import]
    import bonsai.core.tool  # ruff: ignore[unused-import]
    import bonsai.core.unit  # ruff: ignore[unused-import]

    _stub("bpy")
    _stub("mathutils", Matrix=object, Vector=object)
    _stub("bonsai.tool")
    _stub("bonsai.bim.schema")
    _stub("bonsai.bim.ifc", IfcStore=types.SimpleNamespace())
    module = _load_module("bonsai.tool.project", BONSAI_ROOT / "bonsai" / "tool" / "project.py")
    return module.Project


def _running_in_blender() -> bool:
    bpy = sys.modules.get("bpy")
    return bpy is not None and hasattr(bpy, "context") and hasattr(bpy, "types")


def _override_move_select_execute():
    source = OPERATOR_PATH.read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "OverrideMoveSelect":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_execute":
                    namespace = {"ifcopenshell": ifcopenshell, "tool": sys.modules["bonsai.tool"]}
                    exec(textwrap.dedent(ast.get_source_segment(source, item)), namespace)
                    return namespace["_execute"]
    raise AssertionError("OverrideMoveSelect._execute is missing")


ELEMENT = _load_repo_element()
if _running_in_blender():
    from bonsai.bim.module.geometry.operator import OverrideMoveSelect
    from bonsai.tool.aggregate import Aggregate as AGGREGATE
    from bonsai.tool.nest import Nest as NEST
    from bonsai.tool.project import Project as PROJECT

    MOVE_SELECT = OverrideMoveSelect._execute
else:
    NEST = _load_tool_class("nest.py", "Nest")
    AGGREGATE = _load_tool_class("aggregate.py", "Aggregate")
    PROJECT = _load_project_class()
    MOVE_SELECT = _override_move_select_execute()


def _run_child(op: str, text: str, ifc_class: str, name: str):
    """Run one walk in a fresh interpreter and kill it if it is still going.

    A fresh interpreter keeps the parsed file alive for the walk. Killing that
    process does not disturb the parser in this one.
    """
    runner = (
        "import importlib.util, json, sys\n"
        f"spec = importlib.util.spec_from_file_location('cyclic_nest_move', {str(Path(__file__).resolve())!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "request = json.load(sys.stdin)\n"
        "print(json.dumps(module.dispatch(request['op'], request['text'], request['ifc_class'], request['name'])))\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", runner],
            input=json.dumps({"op": op, "text": text, "ifc_class": ifc_class, "name": name}),
            text=True,
            capture_output=True,
            timeout=WALK_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise AssertionError("walk did not finish; a repeated element id was expanded again") from None
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise AssertionError(f"walk crashed: {detail}")
    return json.loads(completed.stdout)


def _ids(entities) -> set[int]:
    return {entity.id() for entity in entities}


def _descendants(start, children_fn) -> set[int]:
    """Ids reachable by recording ``start`` before expanding and skipping a repeat."""
    seen = {start.id()}
    found: set[int] = set()
    queue = [start]
    while queue:
        current = queue.pop()
        for child in children_fn(current):
            if child.id() in seen:
                continue
            seen.add(child.id())
            found.add(child.id())
            queue.append(child)
    return found


def _decomposition_children(element):
    children = []
    for rel in getattr(element, "ContainsElements", []):
        children.extend(rel.RelatedElements)
    for rel in getattr(element, "IsDecomposedBy", []):
        children.extend(rel.RelatedObjects)
    for rel in getattr(element, "HasOpenings", []):
        children.append(rel.RelatedOpeningElement)
    for rel in getattr(element, "HasFillings", []):
        children.append(rel.RelatedBuildingElement)
    for rel in getattr(element, "IsNestedBy", []):
        children.extend(rel.RelatedObjects)
    for rel in getattr(element, "HasSurfaceFeatures", []):
        children.extend(rel.RelatedSurfaceFeatures)
    return children


def _reopen(model: ifcopenshell.file) -> ifcopenshell.file:
    # Serialize and parse in memory. The SPF writer and parser are the same
    # path as opening a file a user was given.
    return ifcopenshell.file.from_string(model.to_string())


def _named(model: ifcopenshell.file, ifc_class: str, name: str):
    return model.create_entity(ifc_class, GlobalId=ifcopenshell.guid.new(), Name=name)


def _relate(model: ifcopenshell.file, ifc_class: str, parent, children) -> None:
    model.create_entity(
        ifc_class,
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=parent,
        RelatedObjects=list(children),
    )


class _Elements(dict):
    """Named entities plus the file that owns them.

    The file has to stay referenced. Dropping it frees the native model and
    later inverse lookups fault.
    """

    file: ifcopenshell.file
    text: str


def _model(schema: str, ifc_class: str, rel_class: str, links: dict[str, list[str]]) -> _Elements:
    model = ifcopenshell.file(schema=schema)
    _named(model, "IfcProject", "Project")
    names = {parent for parent in links}
    for children in links.values():
        names.update(children)
    elements = _Elements({name: _named(model, ifc_class, name) for name in names})
    for parent, children in links.items():
        _relate(model, rel_class, elements[parent], [elements[child] for child in children])
    elements.text = model.to_string()
    elements.file = _reopen(model)
    elements.clear()
    elements.update({entity.Name: entity for entity in elements.file.by_type(ifc_class)})
    return elements


class _Obj:
    def __init__(self, name: str):
        self.name = name
        self.selected = False

    def select_set(self, selected: bool) -> None:
        self.selected = selected


class _Props:
    def __init__(self):
        self.not_editing_objects = []
        self.editing_aggregate = None
        self.editing_nest = None
        self.in_aggregate_mode = False
        self.in_nest_mode = False


class _Context:
    def __init__(self, selected):
        self.selected_objects = selected


def _bind_objects(elements: dict):
    objects = {name: _Obj(name) for name in elements}
    by_obj = {objects[name]: elements[name] for name in elements}
    tool = sys.modules["bonsai.tool"]
    props = _Props()

    class _Ifc:
        @staticmethod
        def get():
            return next(iter(elements.values())).file

        @staticmethod
        def get_entity(obj):
            return by_obj.get(obj)

        @staticmethod
        def get_object(element):
            for name, entity in elements.items():
                if entity == element or entity.id() == element.id():
                    return objects[name]
            return None

    class _AggregateFacade:
        get_parts_recursively = staticmethod(AGGREGATE.get_parts_recursively)
        get_aggregates_recursively = staticmethod(AGGREGATE.get_aggregates_recursively)

        @staticmethod
        def get_aggregate_props():
            return props

    class _NestFacade:
        get_components_recursively = staticmethod(NEST.get_components_recursively)

        @staticmethod
        def get_nest_props():
            return props

    class _Array:
        @staticmethod
        def get_all_objects(element):
            raise AssertionError("array expansion is not part of this file")

    tool.Ifc = _Ifc
    tool.Aggregate = _AggregateFacade
    tool.Nest = _NestFacade
    tool.Array = _Array
    return objects


def _run_move(elements: dict, selected_name: str):
    objects = _bind_objects(elements)
    objects[selected_name].selected = True
    operator = types.SimpleNamespace(new_active_obj=None)
    result = MOVE_SELECT(operator, _Context([objects[selected_name]]))
    selected = sorted(name for name, obj in objects.items() if obj.selected)
    return [sorted(result), selected, None if operator.new_active_obj is None else operator.new_active_obj.name]


def dispatch(op: str, text: str, ifc_class: str, name: str):
    opened = ifcopenshell.file.from_string(text)
    elements = {entity.Name: entity for entity in opened.by_type(ifc_class)}
    element = elements[name]
    if op == "components":
        return sorted(entity.Name for entity in NEST.get_components_recursively(element))
    if op == "parts":
        return sorted(entity.Name for entity in AGGREGATE.get_parts_recursively(element))
    if op == "aggregates":
        return [entity.Name for entity in AGGREGATE.get_aggregates_recursively(element)]
    if op == "decomposition":
        return sorted(entity.Name for entity in ELEMENT.get_decomposition(element))
    if op == "tasks":
        return [task.Name for task in ifcopenshell.util.sequence.get_all_nested_tasks(element)]
    if op == "costs":
        return [item.Name for item in ifcopenshell.util.cost.get_all_nested_cost_items(element)]
    if op == "move":
        return _run_move(elements, name)
    if op == "remove-library":
        PROJECT.remove_project_library(element)
        return [len(opened.by_type("IfcProjectLibrary")), len(opened.by_type("IfcRelNests"))]
    raise AssertionError(f"unknown walk {op}")


def _component_names(elements: _Elements, name: str):
    return _run_child("components", elements.text, "IfcWall", name)


def _part_names(elements: _Elements, name: str):
    return _run_child("parts", elements.text, "IfcElementAssembly", name)


def _aggregate_names(elements: _Elements, name: str):
    return _run_child("aggregates", elements.text, "IfcElementAssembly", name)


def _decomposition_names(elements: _Elements, name: str):
    return _run_child("decomposition", elements.text, elements[name].is_a(), name)


def _move(elements: _Elements, selected_name: str):
    return _run_child("move", elements.text, elements[selected_name].is_a(), selected_name)


def test_parser_reopens_mutual_and_self_nests():
    mutual = _model("IFC4", "IfcWall", "IfcRelNests", {"A": ["B"], "B": ["A"]})
    assert _ids(ELEMENT.get_components(mutual["A"])) == {mutual["B"].id()}
    assert _ids(ELEMENT.get_components(mutual["B"])) == {mutual["A"].id()}

    self_nest = _model("IFC4", "IfcWall", "IfcRelNests", {"A": ["A"]})
    assert _ids(ELEMENT.get_components(self_nest["A"])) == {self_nest["A"].id()}

    ifc2x3 = _model("IFC2X3", "IfcWall", "IfcRelNests", {"A": ["B"], "B": ["A"]})
    assert _ids(ELEMENT.get_components(ifc2x3["A"])) == {ifc2x3["B"].id()}
    assert getattr(ifc2x3["A"], "IsNestedBy", None) in (None, [])
    assert ifc2x3["A"].IsDecomposedBy[0].is_a("IfcRelNests")


def test_components_recursive_acyclic_chain_is_unchanged():
    elements = _model("IFC4", "IfcWall", "IfcRelNests", {"A": ["B"], "B": ["C"]})
    assert _component_names(elements, "A") == ["B", "C"]
    assert _descendants(elements["A"], ELEMENT.get_components) == {elements["B"].id(), elements["C"].id()}


def test_components_recursive_mutual_nest_skips_repeated_id():
    elements = _model("IFC4", "IfcWall", "IfcRelNests", {"A": ["B"], "B": ["A"]})
    assert _component_names(elements, "A") == ["B"]


def test_components_recursive_self_nest_skips_repeated_id():
    elements = _model("IFC4", "IfcWall", "IfcRelNests", {"A": ["A"]})
    assert _component_names(elements, "A") == []


def test_components_recursive_three_cycle_keeps_unseen_members():
    elements = _model("IFC4", "IfcWall", "IfcRelNests", {"A": ["B"], "B": ["C"], "C": ["A"]})
    assert _component_names(elements, "A") == ["B", "C"]


def test_components_recursive_keeps_sibling_off_the_cycle():
    elements = _model("IFC4", "IfcWall", "IfcRelNests", {"A": ["B"], "B": ["A", "C"]})
    assert _component_names(elements, "A") == ["B", "C"]


def test_components_recursive_ifc2x3_mutual_nest():
    elements = _model("IFC2X3", "IfcWall", "IfcRelNests", {"A": ["B"], "B": ["A"]})
    assert _component_names(elements, "A") == ["B"]


def test_components_recursive_ifc4x3_mutual_nest():
    elements = _model("IFC4X3", "IfcWall", "IfcRelNests", {"A": ["B"], "B": ["A"]})
    assert _component_names(elements, "A") == ["B"]


def test_move_select_acyclic_nest_selects_whole_and_components():
    elements = _model("IFC4", "IfcWall", "IfcRelNests", {"A": ["B"], "B": ["C"]})
    assert _move(elements, "A") == [["FINISHED"], ["A", "B", "C"], "A"]
    assert _move(elements, "C") == [["FINISHED"], ["B", "C"], "B"]


def test_move_select_mutual_nest_finishes_and_selects_both():
    elements = _model("IFC4", "IfcWall", "IfcRelNests", {"A": ["B"], "B": ["A"]})
    assert _move(elements, "A") == [["FINISHED"], ["A", "B"], "A"]


def test_move_select_self_nest_finishes():
    elements = _model("IFC4", "IfcWall", "IfcRelNests", {"A": ["A"]})
    assert _move(elements, "A") == [["FINISHED"], ["A"], "A"]


def test_move_select_ifc2x3_mutual_nest_finishes():
    elements = _model("IFC2X3", "IfcWall", "IfcRelNests", {"A": ["B"], "B": ["A"]})
    assert _move(elements, "B") == [["FINISHED"], ["A", "B"], "B"]


def test_parts_recursive_aggregate_cycle_skips_repeated_id():
    elements = _model("IFC4", "IfcElementAssembly", "IfcRelAggregates", {"A": ["B"], "B": ["A", "C"]})
    assert _part_names(elements, "A") == ["B", "C"]
    assert _descendants(elements["A"], ELEMENT.get_parts) == {elements["B"].id(), elements["C"].id()}


def test_aggregates_recursive_cycle_skips_repeated_id():
    elements = _model("IFC4", "IfcElementAssembly", "IfcRelAggregates", {"A": ["B"], "B": ["A"]})
    assert sorted(_aggregate_names(elements, "A")) == ["A", "B"]


def test_aggregates_recursive_acyclic_chain_is_unchanged():
    elements = _model("IFC4", "IfcElementAssembly", "IfcRelAggregates", {"A": ["B"], "B": ["C"]})
    assert _aggregate_names(elements, "C") == ["B", "A"]


def test_move_select_aggregate_cycle_finishes_and_selects_parts():
    elements = _model("IFC4", "IfcWall", "IfcRelAggregates", {"A": ["B"], "B": ["A"]})
    assert _move(elements, "A") == [["FINISHED"], ["A", "B"], "A"]


def test_get_decomposition_nest_cycle_skips_repeated_id():
    elements = _model("IFC4", "IfcWall", "IfcRelNests", {"A": ["B"], "B": ["A", "C"]})
    assert _decomposition_names(elements, "A") == ["B", "C"]
    assert _descendants(elements["A"], _decomposition_children) == {elements["B"].id(), elements["C"].id()}


def test_get_decomposition_ifc2x3_nest_cycle_skips_repeated_id():
    elements = _model("IFC2X3", "IfcWall", "IfcRelNests", {"A": ["B"], "B": ["A"]})
    assert _decomposition_names(elements, "A") == ["B"]


def test_all_nested_tasks_cycle_skips_repeated_id():
    elements = _model("IFC4", "IfcTask", "IfcRelNests", {"A": ["B"], "B": ["A", "C"]})
    found = _run_child("tasks", elements.text, "IfcTask", "A")
    assert found == ["B", "C"]


def test_all_nested_tasks_acyclic_chain_is_unchanged():
    elements = _model("IFC4", "IfcTask", "IfcRelNests", {"A": ["B"], "B": ["C"]})
    found = _run_child("tasks", elements.text, "IfcTask", "A")
    assert found == ["B", "C"]


def test_all_nested_cost_items_cycle_skips_repeated_id():
    elements = _model("IFC4", "IfcCostItem", "IfcRelNests", {"A": ["B"], "B": ["A"]})
    found = _run_child("costs", elements.text, "IfcCostItem", "A")
    assert found == ["B"]


def test_remove_project_library_nest_cycle_removes_each_library_once():
    elements = _model("IFC4", "IfcProjectLibrary", "IfcRelNests", {"A": ["B"], "B": ["A"]})
    assert _run_child("remove-library", elements.text, "IfcProjectLibrary", "A") == [0, 0]
