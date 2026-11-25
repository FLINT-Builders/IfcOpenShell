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

"""Cycles in IfcBooleanResult.FirstOperand must not hang extrusion lookup.

These tests fail while the unbounded operand walks are still present. They
open an IFC file (the same bytes an untrusted model would contain) and call
the product functions that follow FirstOperand.

Not covered here, because they already stop on a repeated id:
``bonsai.bim.module.geometry.operator`` item-mode queue (``processed_ids``).
The C++ geometry mapping walk is not invoked by this module.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import types
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.representation
import pytest

REPO = Path(__file__).resolve().parents[4]
BONSAI = REPO / "src" / "bonsai" / "bonsai"
IFC_PY = REPO / "src" / "ifcopenshell-python" / "ifcopenshell"
WALK_TIMEOUT_SECONDS = 12


def _context(file: ifcopenshell.file) -> ifcopenshell.entity_instance:
    origin = file.createIfcCartesianPoint((0.0, 0.0, 0.0))
    placement = file.createIfcAxis2Placement3D(origin)
    context = file.createIfcGeometricRepresentationContext(
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1e-5,
        WorldCoordinateSystem=placement,
    )
    return file.createIfcGeometricRepresentationSubContext(
        ContextIdentifier="Body",
        ContextType="Model",
        TargetView="MODEL_VIEW",
        ParentContext=context,
    )


def _product(file: ifcopenshell.file, item: ifcopenshell.entity_instance) -> None:
    body = _context(file)
    representation = file.createIfcShapeRepresentation(body, "Body", "CSG", (item,))
    wall = file.createIfcWall(ifcopenshell.guid.new(), None, "Cyclic", None, None, None, None, None, None)
    wall.Representation = file.createIfcProductDefinitionShape(None, None, (representation,))


def _half_space(file: ifcopenshell.file) -> ifcopenshell.entity_instance:
    return file.createIfcHalfSpaceSolid()


def write_fixture(path: Path, kind: str) -> Path:
    """Write an IFC file and return the path. The caller re-opens it."""
    file = ifcopenshell.file(schema="IFC4")
    if kind == "self":
        boolean = file.createIfcBooleanResult("DIFFERENCE", None, None)
        boolean.FirstOperand = boolean
        boolean.SecondOperand = boolean
        _product(file, boolean)
    elif kind == "pair":
        first = file.createIfcBooleanResult("DIFFERENCE", None, None)
        second = file.createIfcBooleanResult("UNION", None, None)
        half = _half_space(file)
        first.FirstOperand = second
        second.FirstOperand = first
        first.SecondOperand = half
        second.SecondOperand = half
        _product(file, first)
    elif kind == "triple":
        first = file.createIfcBooleanResult("DIFFERENCE", None, None)
        second = file.createIfcBooleanResult("UNION", None, None)
        third = file.createIfcBooleanResult("INTERSECTION", None, None)
        half = _half_space(file)
        first.FirstOperand = second
        second.FirstOperand = third
        third.FirstOperand = first
        first.SecondOperand = half
        second.SecondOperand = half
        third.SecondOperand = half
        _product(file, first)
    elif kind == "clip":
        boolean = file.createIfcBooleanClippingResult("DIFFERENCE", None, None)
        boolean.FirstOperand = boolean
        boolean.SecondOperand = _half_space(file)
        _product(file, boolean)
    elif kind == "chain":
        solid = file.createIfcExtrudedAreaSolid()
        outer = file.createIfcBooleanResult("DIFFERENCE", None, None)
        inner = file.createIfcBooleanResult("UNION", None, None)
        half = _half_space(file)
        outer.FirstOperand = inner
        inner.FirstOperand = solid
        outer.SecondOperand = half
        inner.SecondOperand = half
        _product(file, outer)
    else:
        raise AssertionError(kind)
    file.write(str(path))
    return path


def _open_wall(path: str):
    file = ifcopenshell.open(path)
    wall = file.by_type("IfcWall")[0]
    representation = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
    assert representation is not None
    return file, wall, representation


def _class_from_source(path: Path, class_name: str, namespace: dict) -> type:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            methods = [item for item in node.body if isinstance(item, ast.FunctionDef)]
            replacement = ast.ClassDef(
                name=class_name,
                bases=[],
                keywords=[],
                body=methods or [ast.Pass()],
                decorator_list=[],
            )
            module = ast.Module(body=[replacement], type_ignores=[])
            ast.fix_missing_locations(module)
            exec(compile(module, str(path), "exec"), namespace)
            return namespace[class_name]
    raise AssertionError(f"{class_name} not in {path}")


def _function_from_source(path: Path, function_name: str, namespace: dict):
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            module = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(module)
            exec(compile(module, str(path), "exec"), namespace)
            return namespace[function_name]
    raise AssertionError(f"{function_name} not in {path}")


def _load_repo_module(module_name: str, path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Vector(tuple):
    def __new__(cls, data=(0.0, 0.0, 0.0)):
        return tuple.__new__(cls, tuple(data))


class _BoolItems(list):
    def add(self):
        item = types.SimpleNamespace()
        self.append(item)
        return item

    def clear(self) -> None:
        list.clear(self)


def _stub_module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []
    module.__package__ = name.rpartition(".")[0]
    sys.modules[name] = module
    return module


def _install_blender_stubs() -> None:
    if "bpy" in sys.modules and hasattr(sys.modules["bpy"], "types"):
        return

    def _missing(module_name: str):
        def _getattr(name: str):
            if name.startswith("__"):
                raise AttributeError(name)
            return types.SimpleNamespace()

        module = _stub_module(module_name)
        module.__getattr__ = _getattr  # type: ignore[attr-defined]
        return module

    bpy = _missing("bpy")
    bpy.types = types.SimpleNamespace(Object=object, Operator=object, ID=object, Mesh=object, UILayout=object)
    bpy.context = types.SimpleNamespace(active_object=None, mode="OBJECT", workspace=None, scene=None)
    bpy.props = types.SimpleNamespace(BoolProperty=lambda **kwargs: False)
    _missing("bmesh")
    mathutils = _stub_module("mathutils")
    mathutils.Vector = _Vector
    mathutils.Matrix = lambda *args, **kwargs: args
    mathutils.geometry = _stub_module("mathutils.geometry")


def _load_model():
    import importlib.util

    _install_blender_stubs()
    bonsai = _stub_module("bonsai")
    bonsai.__path__ = [str(BONSAI)]
    core = _stub_module("bonsai.core")
    core_geometry = _stub_module("bonsai.core.geometry")
    core_model = _stub_module("bonsai.core.model")
    core_tool = _stub_module("bonsai.core.tool")
    bonsai.core = core
    core.geometry = core_geometry
    core.model = core_model
    core.tool = core_tool

    class _CoreModel:
        pass

    core_tool.Model = _CoreModel
    tool = _stub_module("bonsai.tool")
    bonsai.tool = tool

    class _Blender:
        @staticmethod
        def V_(*args):
            return _Vector(args)

        @staticmethod
        def get_active_object():
            return tool._active_object

    class _Geometry:
        @staticmethod
        def get_active_representation(obj):
            return tool._active_representation

    tool.Blender = _Blender
    tool.Geometry = _Geometry
    tool._active_object = object()
    tool._active_representation = None
    cad = _stub_module("bonsai.tool.cad")
    cad.VTX_PRECISION = 1.0e-5
    cad.WELD_TOLERANCE = 1.0e-4
    bim = _stub_module("bonsai.bim")
    bonsai.bim = bim
    bim.import_ifc = _stub_module("bonsai.bim.import_ifc")
    tool.cad = cad

    spec = importlib.util.spec_from_file_location("bonsai.tool.model", BONSAI / "tool" / "model.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["bonsai.tool.model"] = module
    spec.loader.exec_module(module)
    tool.Model = module.Model
    return module.Model, tool


def _loaded():
    model, tool = _load_model()
    data = _load_repo_module("bonsai_model_data_under_test", BONSAI / "bim" / "module" / "model" / "data.py")
    # data.py captured whichever bonsai.tool was first imported. Force the stub.
    data.tool = sys.modules["bonsai.tool"]
    shape = _load_repo_module("repo_ifcopenshell_util_shape", IFC_PY / "util" / "shape.py")
    representation = _load_repo_module(
        "repo_ifcopenshell_util_representation", IFC_PY / "util" / "representation.py"
    )
    element = _load_repo_module("repo_ifcopenshell_util_element", IFC_PY / "util" / "element.py")
    return {
        "Model": model,
        "tool": tool,
        "AuthoringData": data.AuthoringData,
        "shape": shape,
        "representation": representation,
        "element": element,
    }


def _run_operation(op: str, path: str) -> None:
    state = _loaded()
    model = state["Model"]
    tool = state["tool"]
    _file, wall, representation = _open_wall(path)
    item = representation.Items[0]

    if op == "get_extrusion_none":
        assert model.get_extrusion(representation) is None
    elif op == "get_extrusion_solid":
        found = model.get_extrusion(representation)
        assert found is not None and found.is_a("IfcExtrudedAreaSolid")
    elif op == "has_extrusion_false":
        tool._active_representation = representation
        assert state["AuthoringData"].has_extrusion() is False
    elif op == "has_extrusion_true":
        tool._active_representation = representation
        assert state["AuthoringData"].has_extrusion() is True
    elif op == "read_headers":
        namespace = {
            "ifcopenshell": ifcopenshell,
            "tool": tool,
            "AuthoringData": types.SimpleNamespace(is_loaded=True, data={}),
            "core_model": types.SimpleNamespace(),
            "Vector": _Vector,
        }
        reader = _function_from_source(BONSAI / "bim" / "handler.py", "_read_headers_into_props", namespace)
        assert reader(object(), wall) is None
    elif op == "get_booleans":
        found = model.get_booleans(representation=representation)
        assert [boolean.id() for boolean in found].count(item.id()) == 1
        assert len(found) == len({boolean.id() for boolean in found})
        assert len(found) <= 3
    elif op == "shape_extrusions":
        assert state["shape"].get_extrusions(wall) == []
    elif op == "shape_base_extrusions":
        assert state["shape"].get_base_extrusions(wall) == []
    elif op == "shape_chain":
        found = state["shape"].get_extrusions(wall)
        assert len(found) == 1 and found[0].is_a("IfcExtrudedAreaSolid")
        assert len(state["shape"].get_base_extrusions(wall)) == 1
    elif op == "resolve_base_items":
        assert list(state["representation"].resolve_base_items(representation)) == []
    elif op == "resolve_base_items_chain":
        resolved = list(state["representation"].resolve_base_items(representation))
        assert any(resolved_item.is_a("IfcExtrudedAreaSolid") for resolved_item in resolved)
        assert len(resolved) <= 4
    elif op == "get_styles":
        assert state["element"].get_styles(wall) == []
    elif op == "loader_vector":
        namespace = {"ifcopenshell": ifcopenshell, "Vector": _Vector}
        loader = _class_from_source(BONSAI / "tool" / "loader.py", "Loader", namespace)
        assert loader.get_extrusion_vector(wall) == (0.0, 0.0, 1.0)
    elif op == "drawing_vector":
        namespace = {"ifcopenshell": ifcopenshell, "Vector": _Vector}
        drawing = _class_from_source(BONSAI / "tool" / "drawing.py", "Drawing", namespace)
        assert drawing.get_extrusion_vector(wall) == (0.0, 0.0, 1.0)
    elif op == "wall_extrusion_data":
        namespace = {"ifcopenshell": ifcopenshell, "tool": tool, "Vector": _Vector, "core": types.SimpleNamespace()}
        joiner = _class_from_source(BONSAI / "bim" / "module" / "model" / "wall.py", "DumbWallJoiner", namespace)
        result = joiner.get_extrusion_data(types.SimpleNamespace(unit_scale=1.0), representation)
        assert result["item"] is None
    elif op == "regenerator_vectors":
        import numpy as np

        namespace = {
            "ifcopenshell": ifcopenshell,
            "np": np,
            "sin": __import__("math").sin,
            "cos": __import__("math").cos,
        }
        regenerator_cls = _class_from_source(
            IFC_PY / "api" / "geometry" / "regenerate_wall_representation.py",
            "Regenerator",
            namespace,
        )
        regenerator = regenerator_cls()
        regenerator.fallback_angle = None
        regenerator.fallback_height = 3.0
        regenerator.is_angled = False
        result = regenerator.get_wall_vectors(wall)
        assert result["h"] == 3.0 and result["d"] == 3.0
    elif op == "stylable_items":
        namespace = {"ifcopenshell": ifcopenshell, "np": __import__("numpy")}
        creator_cls = _class_from_source(BONSAI / "bim" / "import_ifc.py", "MaterialCreator", namespace)
        found = creator_cls.resolve_all_stylable_representation_items(None, representation)
        assert found and found[-1].id() == item.id()
        assert len(found) <= 4
    elif op == "representation_styles":
        namespace = {"ifcopenshell": ifcopenshell}
        geometry = _class_from_source(BONSAI / "tool" / "geometry.py", "Geometry", namespace)
        assert geometry.get_representation_styles(representation) == set()
    elif op == "cross_section":
        namespace = {
            "tool": tool,
            "get_end_area": lambda obj: 0.0,
            "create_mesh_from_shape": lambda item: (_ for _ in ()).throw(AssertionError("no mesh")),
            "get_mesh_area": lambda mesh: 0.0,
            "delete_mesh": lambda mesh: None,
        }
        tool._active_representation = representation
        function = _function_from_source(
            BONSAI / "bim" / "module" / "qto" / "calculator.py",
            "get_cross_section_area",
            namespace,
        )
        assert function(object()) == 0.0
    elif op == "nested_items":
        namespace = {"tool": tool, "ifcopenshell": ifcopenshell}
        selector_cls = _class_from_source(
            BONSAI / "bim" / "module" / "geometry" / "operator.py",
            "SelectRepresentationItem",
            namespace,
        )
        assert selector_cls().get_nested_item_ids(item) == set()
    elif op == "select_boolean":
        props = types.SimpleNamespace(active_boolean=types.SimpleNamespace(ifc_definition_id=item.id()))
        geometry_props = types.SimpleNamespace(item_objs=[])
        tool.Feature = types.SimpleNamespace(get_boolean_props=lambda: props)
        tool.Ifc = types.SimpleNamespace(get=lambda: _file)
        tool.Geometry.get_geometry_props = lambda: geometry_props
        namespace = {"tool": tool, "ifcopenshell": ifcopenshell}
        selector_cls = _class_from_source(
            BONSAI / "bim" / "module" / "model" / "opening.py",
            "SelectBoolean",
            namespace,
        )
        operator = selector_cls()
        operator.is_recursive = True
        assert operator.execute(None) == {"FINISHED"}
    elif op == "edit_booleans":
        booleans = _BoolItems()
        props = types.SimpleNamespace(booleans=booleans, is_editing=False)
        rep_obj = object()
        tool.Feature = types.SimpleNamespace(get_boolean_props=lambda: props)
        tool.Geometry.get_geometry_props = lambda: types.SimpleNamespace(representation_obj=rep_obj)
        tool.Geometry.get_active_representation = lambda obj: representation
        namespace = {"tool": tool, "ifcopenshell": ifcopenshell}
        editor_cls = _class_from_source(
            BONSAI / "bim" / "module" / "void" / "operator.py",
            "EnableEditingBooleans",
            namespace,
        )
        assert editor_cls().execute(None) == {"FINISHED"}
        assert 1 <= len(booleans) <= 4
    else:
        raise AssertionError(op)


def _run(op: str, path: Path) -> None:
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "worker", op, str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=WALK_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{op} did not finish within {WALK_TIMEOUT_SECONDS}s on a cyclic boolean operand")
    assert completed.returncode == 0, completed.stderr or completed.stdout


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    directory = tmp_path_factory.mktemp("cyclic-boolean")
    return {kind: write_fixture(directory / f"{kind}.ifc", kind) for kind in ("self", "pair", "triple", "clip", "chain")}


def test_reopened_file_keeps_self_operand(fixtures: dict[str, Path]) -> None:
    _file, _wall, representation = _open_wall(str(fixtures["self"]))
    boolean = representation.Items[0]
    assert boolean.is_a("IfcBooleanResult")
    assert boolean.FirstOperand.id() == boolean.id()
    assert boolean.SecondOperand.id() == boolean.id()


def test_reopened_file_keeps_operand_cycles(fixtures: dict[str, Path]) -> None:
    _file, _wall, representation = _open_wall(str(fixtures["pair"]))
    first = representation.Items[0]
    second = first.FirstOperand
    assert first.id() != second.id()
    assert second.FirstOperand.id() == first.id()

    _file, _wall, representation = _open_wall(str(fixtures["triple"]))
    first = representation.Items[0]
    second = first.FirstOperand
    third = second.FirstOperand
    assert third.FirstOperand.id() == first.id()
    assert len({first.id(), second.id(), third.id()}) == 3

    _file, _wall, representation = _open_wall(str(fixtures["clip"]))
    clipping = representation.Items[0]
    assert clipping.is_a("IfcBooleanClippingResult")
    assert clipping.is_a("IfcBooleanResult")
    assert clipping.FirstOperand.id() == clipping.id()


def test_get_extrusion_returns_solid_through_boolean_chain(fixtures: dict[str, Path]) -> None:
    _run("get_extrusion_solid", fixtures["chain"])
    _run("has_extrusion_true", fixtures["chain"])
    _run("shape_chain", fixtures["chain"])
    _run("resolve_base_items_chain", fixtures["chain"])


def test_get_extrusion_self_cycle_returns_none(fixtures: dict[str, Path]) -> None:
    _run("get_extrusion_none", fixtures["self"])


def test_get_extrusion_pair_cycle_returns_none(fixtures: dict[str, Path]) -> None:
    _run("get_extrusion_none", fixtures["pair"])


def test_get_extrusion_triple_cycle_returns_none(fixtures: dict[str, Path]) -> None:
    _run("get_extrusion_none", fixtures["triple"])


def test_get_extrusion_clipping_cycle_returns_none(fixtures: dict[str, Path]) -> None:
    _run("get_extrusion_none", fixtures["clip"])


def test_has_extrusion_is_false_for_self_cycle(fixtures: dict[str, Path]) -> None:
    _run("has_extrusion_false", fixtures["self"])


def test_header_refresh_returns_on_self_cycle(fixtures: dict[str, Path]) -> None:
    _run("read_headers", fixtures["self"])


def test_get_booleans_stops_on_pair_cycle(fixtures: dict[str, Path]) -> None:
    _run("get_booleans", fixtures["pair"])


def test_shape_extrusion_helpers_stop_on_cycles(fixtures: dict[str, Path]) -> None:
    _run("shape_extrusions", fixtures["self"])
    _run("shape_base_extrusions", fixtures["triple"])


def test_resolve_base_items_stops_on_self_cycle(fixtures: dict[str, Path]) -> None:
    _run("resolve_base_items", fixtures["self"])


def test_get_styles_stops_on_self_cycle(fixtures: dict[str, Path]) -> None:
    _run("get_styles", fixtures["self"])


def test_loader_and_drawing_vectors_stop_on_self_cycle(fixtures: dict[str, Path]) -> None:
    _run("loader_vector", fixtures["self"])
    _run("drawing_vector", fixtures["self"])


def test_wall_extrusion_data_stops_on_self_cycle(fixtures: dict[str, Path]) -> None:
    _run("wall_extrusion_data", fixtures["self"])


def test_regenerator_wall_vectors_stop_on_pair_cycle(fixtures: dict[str, Path]) -> None:
    _run("regenerator_vectors", fixtures["pair"])


def test_style_walks_stop_on_self_cycle(fixtures: dict[str, Path]) -> None:
    _run("stylable_items", fixtures["self"])
    _run("representation_styles", fixtures["self"])


def test_cross_section_area_stops_on_clipping_cycle(fixtures: dict[str, Path]) -> None:
    _run("cross_section", fixtures["clip"])


def test_nested_item_ids_stop_on_self_cycle(fixtures: dict[str, Path]) -> None:
    _run("nested_items", fixtures["self"])


def test_select_boolean_stops_on_self_cycle(fixtures: dict[str, Path]) -> None:
    _run("select_boolean", fixtures["self"])


def test_edit_booleans_stops_on_self_cycle(fixtures: dict[str, Path]) -> None:
    _run("edit_booleans", fixtures["self"])


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "worker":
        _run_operation(sys.argv[2], sys.argv[3])
