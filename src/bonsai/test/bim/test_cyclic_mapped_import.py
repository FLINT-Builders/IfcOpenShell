# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 Dion Moult <dion@thinkmoult.com>
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

"""Opening a project must finish when a body representation maps back to itself.

``IfcImporter.parse_native_elements`` follows ``IfcMappedItem.MappingSource.MappedRepresentation``
with no set of representations already seen. The same unbounded walk is in
``ifcopenshell.util.representation.resolve_representation``, ``resolve_items``, and
``resolve_base_items``, which the native-element decision calls after the loop.
These tests run that import path on an IFC file that has been written and read
back. They time out while the walk does not stop.
"""

from __future__ import annotations

import ast
import importlib.util
import logging
import signal
import subprocess
import sys
import traceback
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
BONSAI_ROOT = REPO / "src" / "bonsai"
REPO_REPRESENTATION = REPO / "src" / "ifcopenshell-python" / "ifcopenshell" / "util" / "representation.py"
CASE_TIMEOUT_SECONDS = 2.0


def _run(action: str, kind: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), action, kind],
        check=False,
        capture_output=True,
        text=True,
        timeout=CASE_TIMEOUT_SECONDS + 2.0,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_load_geometry_defaults_on() -> None:
    """Project import leaves Load Geometry enabled unless the user turns it off."""
    tree = ast.parse((REPO / "src" / "bonsai" / "bonsai" / "bim" / "module" / "project" / "prop.py").read_text())
    defaults = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "should_load_geometry" or not isinstance(node.annotation, ast.Call):
            continue
        for keyword in node.annotation.keywords:
            if keyword.arg == "default" and isinstance(keyword.value, ast.Constant):
                defaults.append(keyword.value.value)
    assert defaults == [True]
    _run("defaults", "none")


def test_false_origin_scan_returns_when_a_near_wall_precedes_the_cycle() -> None:
    """The offset scan meshes the wall and returns, so native parsing still runs."""
    _run("offset", "self")


def test_self_mapped_body_finishes_native_parsing() -> None:
    _run("parse", "self")


def test_scaled_self_mapped_body_finishes_native_parsing() -> None:
    _run("parse", "scale")


def test_two_representation_cycle_finishes_native_parsing() -> None:
    _run("parse", "pair")


def test_three_representation_cycle_finishes_native_parsing() -> None:
    _run("parse", "triple")


def test_legitimate_mapped_swept_disk_stays_native() -> None:
    _run("parse", "legit")


def test_two_step_mapped_swept_disk_stays_native() -> None:
    _run("parse", "chain")


def test_resolve_representation_finishes_on_a_cycle() -> None:
    _run("resolve_representation", "self")


def test_resolve_items_finishes_on_a_cycle() -> None:
    _run("resolve_items", "self")


def test_resolve_base_items_finishes_on_a_cycle() -> None:
    _run("resolve_base_items", "self")


def test_resolve_representation_keeps_a_mapped_swept_disk() -> None:
    _run("resolve_representation", "legit")


def test_pointcloud_lookup_finishes_on_a_mapped_cycle() -> None:
    _run("pointcloud", "self")


class _Alarm(Exception):
    pass


def _alarm(signum, frame) -> None:
    raise _Alarm()


def _install_blender_stubs() -> None:
    class NS(types.ModuleType):
        def __init__(self, name: str) -> None:
            super().__init__(name)
            self.__path__ = []
            self.__package__ = name
            self.__file__ = f"<stub {name}>"

        def __getattr__(self, name: str):
            if name.startswith("__"):
                raise AttributeError(name)
            child = NS(f"{self.__name__}.{name}")
            setattr(self, name, child)
            sys.modules[child.__name__] = child
            return child

        def __call__(self, *args, **kwargs):
            return None

        def __iter__(self):
            return iter(())

        def __bool__(self) -> bool:
            return True

        def __mro_entries__(self, bases):
            return (object,)

    def install(name: str) -> types.ModuleType:
        parent = None
        for index in range(name.count(".") + 1):
            qualified = ".".join(name.split(".")[: index + 1])
            if qualified not in sys.modules:
                sys.modules[qualified] = NS(qualified)
            if parent is not None:
                setattr(parent, qualified.rsplit(".", 1)[-1], sys.modules[qualified])
            parent = sys.modules[qualified]
        return sys.modules[name]

    for module_name in ("bpy", "bmesh", "mathutils", "ifcpatch"):
        install(module_name)
    bpy = sys.modules["bpy"]
    bpy.types = install("bpy.types")
    for type_name in ("Mesh", "Curve", "Material", "Collection", "Object", "Context", "Operator", "PropertyGroup"):
        setattr(bpy.types, type_name, type(type_name, (), {}))
    bpy.app = install("bpy.app")
    bpy.app.version = (4, 2, 0)
    bpy.app.handlers = install("bpy.app.handlers")
    bpy.app.handlers.persistent = lambda fn: fn
    mathutils = sys.modules["mathutils"]

    class Matrix:
        def __init__(self, data=None) -> None:
            self.data = data

    mathutils.Matrix = Matrix
    mathutils.Vector = lambda *args, **kwargs: None
    kdtree = install("mathutils.kdtree")
    kdtree.KDTree = type("KDTree", (), {"__init__": lambda self, *args, **kwargs: None})
    mathutils.kdtree = kdtree


def _load(qualified: str, path: Path):
    spec = importlib.util.spec_from_file_location(qualified, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    parent_name, _, child = qualified.rpartition(".")
    setattr(sys.modules[parent_name], child, module)
    spec.loader.exec_module(module)
    return module


def _overlay_repo_representation() -> None:
    """Bind the repository's representation helpers, not another copy of them."""
    importlib.import_module("ifcopenshell.util.placement")

    _load(
        "ifcopenshell.util.placement", REPO / "src" / "ifcopenshell-python" / "ifcopenshell" / "util" / "placement.py"
    )
    _load("ifcopenshell.util.representation", REPO_REPRESENTATION)


def _load_importer():
    sys.path.insert(0, str(BONSAI_ROOT))
    _overlay_repo_representation()
    _install_blender_stubs()
    import bonsai

    bim = types.ModuleType("bonsai.bim")
    bim.__path__ = [str(BONSAI_ROOT / "bonsai" / "bim")]
    bim.__package__ = "bonsai.bim"
    sys.modules["bonsai.bim"] = bim
    bonsai.bim = bim
    tool_mod = types.ModuleType("bonsai.tool")
    tool_mod.__path__ = [str(BONSAI_ROOT / "bonsai" / "tool")]
    tool_mod.__package__ = "bonsai.tool"
    sys.modules["bonsai.tool"] = tool_mod
    bonsai.tool = tool_mod
    core = types.ModuleType("bonsai.core")
    core.__path__ = [str(BONSAI_ROOT / "bonsai" / "core")]
    core.__package__ = "bonsai.core"
    sys.modules["bonsai.core"] = core
    bonsai.core = core
    _load("bonsai.core.tool", BONSAI_ROOT / "bonsai" / "core" / "tool.py")

    ifc_mod = types.ModuleType("bonsai.bim.ifc")
    ifc_mod.IFC_CONNECTED_TYPE = object
    ifc_mod.IfcStore = type("IfcStore", (), {})
    sys.modules["bonsai.bim.ifc"] = ifc_mod
    bim.ifc = ifc_mod
    for helper_name in ("bonsai.bim.helper", "bonsai.bim.schema"):
        helper = types.ModuleType(helper_name)
        sys.modules[helper_name] = helper
        setattr(bim, helper_name.rsplit(".", 1)[-1], helper)

    loader_stub = types.ModuleType("bonsai.tool.loader")
    loader_stub.OBJECT_DATA_TYPE = object
    sys.modules["bonsai.tool.loader"] = loader_stub
    tool_mod.loader = loader_stub
    import_ifc = _load("bonsai.bim.import_ifc", BONSAI_ROOT / "bonsai" / "bim" / "import_ifc.py")
    del sys.modules["bonsai.tool.loader"]
    loader = _load("bonsai.tool.loader", BONSAI_ROOT / "bonsai" / "tool" / "loader.py")
    tool_mod.Loader = loader.Loader
    tool_mod.Pset = _load("bonsai.tool.pset", BONSAI_ROOT / "bonsai" / "tool" / "pset.py").Pset
    tool_mod.Parametric = _load("bonsai.tool.parametric", BONSAI_ROOT / "bonsai" / "tool" / "parametric.py").Parametric

    class Project:
        @staticmethod
        def get_project_props():
            return types.SimpleNamespace(geometry_library="opencascade")

    tool_mod.Project = Project
    return import_ifc, tool_mod


def _axes(ifc):
    zero = ifc.createIfcCartesianPoint((0.0, 0.0, 0.0))
    x_axis = ifc.createIfcDirection((1.0, 0.0, 0.0))
    y_axis = ifc.createIfcDirection((0.0, 1.0, 0.0))
    z_axis = ifc.createIfcDirection((0.0, 0.0, 1.0))
    return zero, x_axis, y_axis, z_axis


def _operator(ifc, scale: float = 1.0, origin=None):
    zero, x_axis, y_axis, z_axis = _axes(ifc)
    return ifc.createIfcCartesianTransformationOperator3D(x_axis, y_axis, origin or zero, scale, z_axis)


def _placement(ifc):
    zero, x_axis, _y_axis, z_axis = _axes(ifc)
    return ifc.createIfcAxis2Placement3D(zero, z_axis, x_axis)


def _mapped_item(ifc, target_representation, scale: float = 1.0, origin=None):
    return ifc.createIfcMappedItem(
        ifc.createIfcRepresentationMap(_placement(ifc), target_representation),
        _operator(ifc, scale, origin),
    )


def _shape(ifc, body, items, representation_type: str):
    return ifc.createIfcShapeRepresentation(body, "Body", representation_type, items)


def _product(ifc, ifc_class: str, name: str, representations: list) -> None:
    import ifcopenshell.api.root

    element = ifcopenshell.api.root.create_entity(ifc, ifc_class=ifc_class, name=name)
    element.Representation = ifc.createIfcProductDefinitionShape(None, None, representations)


def _build(kind: str):
    import ifcopenshell
    import ifcopenshell.api.context
    import ifcopenshell.api.root
    import ifcopenshell.api.unit

    ifc = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject", name="P")
    ifcopenshell.api.unit.assign_unit(ifc)
    model = ifcopenshell.api.context.add_context(ifc, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        ifc, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model
    )
    profile = ifc.createIfcRectangleProfileDef(
        "AREA",
        None,
        ifc.createIfcAxis2Placement2D(ifc.createIfcCartesianPoint((0.0, 0.0))),
        1.0,
        0.2,
    )
    solid = ifc.createIfcExtrudedAreaSolid(
        profile,
        ifc.createIfcAxis2Placement3D(
            ifc.createIfcCartesianPoint((0.0, 0.0, 0.0)),
            ifc.createIfcDirection((0.0, 0.0, 1.0)),
            ifc.createIfcDirection((1.0, 0.0, 0.0)),
        ),
        ifc.createIfcDirection((0.0, 0.0, 1.0)),
        3.0,
    )
    _product(ifc, "IfcWall", "Wall", [_shape(ifc, body, [solid], "SweptSolid")])
    polyline = ifc.createIfcPolyline(
        [ifc.createIfcCartesianPoint((0.0, 0.0, 0.0)), ifc.createIfcCartesianPoint((1.0, 0.0, 0.0))]
    )
    disk_rep = _shape(ifc, body, [ifc.createIfcSweptDiskSolid(polyline, 0.01)], "SweptSolid")
    _product(ifc, "IfcReinforcingBar", "Bar", [disk_rep])

    if kind == "legit":
        origin = ifc.createIfcCartesianPoint((1.0, 0.0, 0.0))
        mapped = _shape(ifc, body, [_mapped_item(ifc, disk_rep, origin=origin)], "MappedRepresentation")
        _product(ifc, "IfcBuildingElementProxy", "MappedBar", [mapped])
    elif kind == "chain":
        middle = _shape(ifc, body, [], "MappedRepresentation")
        middle.Items = [_mapped_item(ifc, disk_rep)]
        outer = _shape(ifc, body, [_mapped_item(ifc, middle)], "MappedRepresentation")
        _product(ifc, "IfcBuildingElementProxy", "MappedBar", [outer])
    elif kind == "self":
        representation = _shape(ifc, body, [], "MappedRepresentation")
        representation.Items = [_mapped_item(ifc, representation)]
        _product(ifc, "IfcBuildingElementProxy", "Cyc", [representation])
    elif kind == "scale":
        representation = _shape(ifc, body, [], "MappedRepresentation")
        representation.Items = [_mapped_item(ifc, representation, scale=2.0)]
        _product(ifc, "IfcBuildingElementProxy", "Cyc", [representation])
    elif kind == "pair":
        first = _shape(ifc, body, [], "MappedRepresentation")
        second = _shape(ifc, body, [], "MappedRepresentation")
        first.Items = [_mapped_item(ifc, second)]
        second.Items = [_mapped_item(ifc, first, scale=3.0)]
        _product(ifc, "IfcBuildingElementProxy", "Cyc", [first])
    elif kind == "triple":
        first = _shape(ifc, body, [], "MappedRepresentation")
        second = _shape(ifc, body, [], "MappedRepresentation")
        third = _shape(ifc, body, [], "MappedRepresentation")
        first.Items = [_mapped_item(ifc, second)]
        second.Items = [_mapped_item(ifc, third)]
        third.Items = [_mapped_item(ifc, first)]
        _product(ifc, "IfcBuildingElementProxy", "Cyc", [first])
    else:
        raise AssertionError(kind)

    path = Path(f"/tmp/bonsai-cyclic-mapped-{kind}.ifc")
    ifc.write(str(path))
    import ifcopenshell

    return ifcopenshell.open(str(path))


def _cyclic_body(ifc):
    for element in ifc.by_type("IfcBuildingElementProxy"):
        for representation in element.Representation.Representations:
            if representation.RepresentationType == "MappedRepresentation":
                return representation
    raise AssertionError("reopened file has no mapped body")


def _assert_cycle_survived(ifc, kind: str) -> None:
    if kind in ("legit", "chain"):
        return
    representation = _cyclic_body(ifc)
    seen = []
    current = representation
    for _ in range(6):
        if current.id() in seen:
            return
        seen.append(current.id())
        item = current.Items[0]
        assert item.is_a("IfcMappedItem")
        current = item.MappingSource.MappedRepresentation
    raise AssertionError("mapped body did not repeat a representation id")


def _importer(import_ifc, tool_mod, ifc):
    settings = import_ifc.IfcImportSettings()
    settings.should_load_geometry = True
    settings.logger = logging.getLogger("cyclic-mapped-import")
    tool_mod.Loader.set_settings(settings)
    tool_mod.Loader.unit_scale = 1.0
    importer = import_ifc.IfcImporter.__new__(import_ifc.IfcImporter)
    importer.ifc_import_settings = settings
    importer.file = ifc
    importer.unit_scale = 1.0
    importer.elements = set()
    importer.native_elements = set()
    importer.native_data = {}
    importer.annotations = set()
    importer.gross_elements = set()
    importer.element_types = set()
    importer.spatial_elements = set()
    importer.process_context_filter()
    importer.process_element_filter()
    return importer


def _worker(action: str, kind: str) -> None:
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, CASE_TIMEOUT_SECONDS)
    try:
        if action == "defaults":
            import_ifc, _tool_mod = _load_importer()
            assert import_ifc.IfcImportSettings().should_load_geometry is True
            return
        ifc = _build(kind)
        _assert_cycle_survived(ifc, kind)
        import_ifc, tool_mod = _load_importer()
        importer = _importer(import_ifc, tool_mod, ifc)
        if action == "offset":
            # process_context_filter has filled the same settings object execute() uses
            # before calculate_model_offset calls get_offset_point.
            assert tool_mod.Loader.get_offset_point(ifc) is None
            return
        if action == "parse":
            importer.parse_native_elements()
            names = {element.Name for element in importer.native_elements}
            assert "Bar" in names
            if kind in ("legit", "chain"):
                assert "MappedBar" in names
            else:
                assert "Cyc" not in names
                representation_util = sys.modules["ifcopenshell.util.representation"]
                for native in importer.native_data.values():
                    assert representation_util.resolve_items(native["representation"])
            return
        representation = _cyclic_body(ifc)
        util = sys.modules["ifcopenshell.util.representation"]
        if action == "resolve_representation":
            resolved = util.resolve_representation(representation)
            assert resolved is not None
            if kind == "legit":
                assert any(item.is_a("IfcSweptDiskSolid") for item in resolved.Items)
            return
        if action == "resolve_items":
            assert isinstance(util.resolve_items(representation), list)
            return
        if action == "resolve_base_items":
            assert isinstance(list(util.resolve_base_items(representation)), list)
            return
        if action == "pointcloud":
            assert importer.get_pointcloud_representation(ifc.by_type("IfcBuildingElementProxy")[0]) is None
            return
        raise AssertionError(action)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def _main() -> None:
    action, kind = sys.argv[1], sys.argv[2]
    try:
        _worker(action, kind)
    except _Alarm:
        print("timed out", file=sys.stderr)
        sys.exit(2)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    _main()


# Imported for the pytest marker below; the worker process never collects tests.
pytest.importorskip("ifcopenshell")
