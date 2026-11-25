# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026
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
#
# This file was generated with the assistance of an AI coding tool.

"""Active content in drawing symbol libraries must not reach the generated SVG.

EPset_Drawing Symbols, Markers, Patterns, and Stylesheet paths are resolved
from the IFC file and inlined by SvgWriter. These tests fail while that
inline copy preserves script, foreignObject, event handlers, external
references, or files outside the project directory. They pass once those
are dropped and only graphic elements from inside the project remain.

Run from src/bonsai, with ifcopenshell and svgwrite importable:

    python3 -m pytest -o addopts= --noconftest -p no:pytest-blender -p no:pytest-bdd \
        test/bim/module/drawing/test_drawing_svg_resource_xss.py
"""

from __future__ import annotations

import ast
import importlib.util
import os
import sys
import textwrap
import types
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.guid
import pytest

pytestmark = pytest.mark.drawing

BONSAI_SRC = Path(__file__).resolve().parents[4]
REPO_ROOT = BONSAI_SRC.parents[1]
SVGWRITER_PATH = BONSAI_SRC / "bonsai/bim/module/drawing/svgwriter.py"
OPERATOR_PATH = BONSAI_SRC / "bonsai/bim/module/drawing/operator.py"
IFC_TOOL_PATH = BONSAI_SRC / "bonsai/tool/ifc.py"
BLENDER_TOOL_PATH = BONSAI_SRC / "bonsai/tool/blender.py"
DRAWING_TOOL_PATH = BONSAI_SRC / "bonsai/tool/drawing.py"

HANDLER_ATTRIBUTES = {
    "onload",
    "onclick",
    "onmouseover",
    "onmousedown",
    "onmouseup",
    "onfocus",
    "onblur",
    "onerror",
    "onabort",
    "onbegin",
    "onend",
    "onrepeat",
}
ACTIVE_ELEMENTS = {
    "script",
    "foreignobject",
    "handler",
    "listener",
    "set",
    "animate",
    "animatetransform",
    "animatemotion",
}
EXTERNAL_MARKERS = ("javascript:", "https://evil.example", "http://evil.example", "data:image/svg+xml")


class _ProjectPath:
    path = ""


def _load_function(path: Path, class_name: str, function_name: str, namespace: dict) -> object:
    source = path.read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == function_name:
                    module = ast.Module(body=[item], type_ignores=[])
                    ast.fix_missing_locations(module)
                    exec(compile(module, str(path), "exec"), namespace)
                    return namespace[function_name]
    raise AssertionError(f"{class_name}.{function_name} not found in {path}")


def _class_constant(path: Path, class_name: str, attribute: str):
    source = path.read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == attribute:
                            return ast.literal_eval(item.value)
    raise AssertionError(f"{class_name}.{attribute} not found in {path}")


def _ensure_package(name: str, path: Path) -> types.ModuleType:
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "__path__"):
        return existing
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    module.__package__ = name
    module.__file__ = str(path / "__init__.py")
    sys.modules[name] = module
    return module


def _load_detached():
    """Import SvgWriter without Blender.

    bpy is not on the path from the IFC property to the serialized drawing.
    The writer, path resolver, and combine_svgs body are loaded from their
    source files. Blender-only helpers those functions do not call on this
    path are replaced with the real data-dir lookup where it is reached.
    """
    bonsai_root = BONSAI_SRC / "bonsai"
    _ensure_package("bonsai", bonsai_root)
    _ensure_package("bonsai.bim", bonsai_root / "bim")
    _ensure_package("bonsai.bim.module", bonsai_root / "bim/module")
    _ensure_package("bonsai.bim.module.drawing", bonsai_root / "bim/module/drawing")

    class _BpyTypes(types.ModuleType):
        def __getattr__(self, name):
            value = type(name, (), {})
            setattr(self, name, value)
            return value

    bpy = types.ModuleType("bpy")
    bpy.__path__ = []
    bpy_types = _BpyTypes("bpy.types")
    bpy.types = bpy_types
    sys.modules.setdefault("bpy", bpy)
    sys.modules.setdefault("bpy.types", bpy_types)
    sys.modules.setdefault("bmesh", types.ModuleType("bmesh"))

    mathutils = types.ModuleType("mathutils")

    class _Vector:
        def __init__(self, data=None):
            self.data = data

    mathutils.Vector = _Vector
    mathutils.geometry = types.ModuleType("mathutils.geometry")
    sys.modules.setdefault("mathutils", mathutils)
    sys.modules.setdefault("mathutils.geometry", mathutils.geometry)

    helper = types.ModuleType("bonsai.bim.module.drawing.helper")
    sys.modules.setdefault("bonsai.bim.module.drawing.helper", helper)
    data = types.ModuleType("bonsai.bim.module.drawing.data")
    data.DecoratorData = object
    data.DrawingsData = object
    sys.modules.setdefault("bonsai.bim.module.drawing.data", data)

    tool = types.ModuleType("bonsai.tool")
    tool.__package__ = "bonsai"

    class Ifc:
        pass

    ifc_namespace = {
        "classmethod": classmethod,
        "Union": object,
        "Path": Path,
        "os": os,
        "IfcStore": _ProjectPath,
        "__file__": str(IFC_TOOL_PATH),
    }
    for name in ("normalize_path", "resolve_uri", "get_path"):
        setattr(Ifc, name, _load_function(IFC_TOOL_PATH, "Ifc", name, ifc_namespace))

    class Blender:
        @classmethod
        def get_addon_preferences(cls):
            return SimpleNamespace(data_dir=str(BONSAI_SRC / "bonsai/bim/data"))

    blender_namespace = {
        "classmethod": classmethod,
        "Union": object,
        "Path": Path,
        "__file__": str(BLENDER_TOOL_PATH),
        "cls": Blender,
    }
    # get_internal_data_dir and get_data_dir_path call each other on the class.
    for name in ("get_internal_data_dir", "get_user_data_dir", "get_data_dir_path"):
        function = _load_function(BLENDER_TOOL_PATH, "Blender", name, blender_namespace)
        setattr(Blender, name, function)
        blender_namespace.setdefault("Blender", Blender)

    class Drawing:
        ResourceType = str
        RESOURCE_TYPES = _class_constant(DRAWING_TOOL_PATH, "Drawing", "RESOURCE_TYPES")

    tool.Ifc = Ifc
    tool.Blender = Blender
    tool.Drawing = Drawing
    sys.modules["bonsai.tool"] = tool

    spec = importlib.util.spec_from_file_location("bonsai.bim.module.drawing.svgwriter", SVGWRITER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    operator_namespace = {
        "Optional": __import__("typing").Optional,
        "bpy": bpy,
        "os": os,
        "shutil": __import__("shutil"),
        "__file__": str(OPERATOR_PATH),
    }
    combine_svgs = _load_function(OPERATOR_PATH, "CreateDrawing", "combine_svgs", operator_namespace)
    return module.SvgWriter, tool, combine_svgs, _ProjectPath


def _load_product():
    try:
        import bpy

        if not hasattr(bpy, "context") or hasattr(bpy, "_mock_name"):
            raise ImportError("bpy is not the Blender module")
        from bonsai.bim.ifc import IfcStore
        from bonsai.bim.module.drawing.operator import CreateDrawing
        from bonsai.bim.module.drawing.svgwriter import SvgWriter
        import bonsai.tool as tool

        return SvgWriter, tool, CreateDrawing.combine_svgs, IfcStore
    except Exception:
        return _load_detached()


SVG_WRITER, TOOL, COMBINE_SVGS, PROJECT_PATH = _load_product()


_OPEN_IFC_FILES: list = []


def _write_ifc(path: Path, properties: dict[str, str]):
    ifc = ifcopenshell.file(schema="IFC4")
    element = ifc.create_entity(
        "IfcAnnotation",
        GlobalId=ifcopenshell.guid.new(),
        Name="Drawing",
        ObjectType="DRAWING",
    )
    pset = ifcopenshell.api.pset.add_pset(ifc, product=element, name="EPset_Drawing")
    ifcopenshell.api.pset.edit_pset(ifc, pset=pset, properties=properties)
    ifc.write(str(path))
    # Keep the opened file alive. Dropping it collects the native file and
    # clears inverse attributes such as IsDefinedBy on the returned element.
    reloaded = ifcopenshell.open(str(path))
    _OPEN_IFC_FILES.append(reloaded)
    return reloaded.by_type("IfcAnnotation")[0]


def _writer_for(ifc_path: Path, element):
    PROJECT_PATH.path = str(ifc_path)
    writer = SVG_WRITER(
        camera_width=1.0,
        camera_height=1.0,
        camera=SimpleNamespace(),
        camera_projection=SimpleNamespace(),
        scale=1 / 100,
        human_scale="1:100",
    )
    writer.setup_drawing_resource_paths(element)
    return writer


def _combine(writer, output_path: Path) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    host = SimpleNamespace(svg_writer=writer, get_svg_path=lambda: str(output_path))
    COMBINE_SVGS(host, None, None, None, None)
    return output_path.read_text()


def _local(name: str) -> str:
    if "}" in name:
        return name.rsplit("}", 1)[1]
    return name


def _is_internal_fragment(value: str) -> bool:
    return value.startswith("#") and ":" not in value and "//" not in value


def _assert_drawing_is_inert(svg_text: str, kept: tuple[str, ...] = ()) -> None:
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as error:
        raise AssertionError(f"generated drawing is not XML: {error}\n{svg_text}") from error
    active = []
    handlers = []
    external = []
    for element in root.iter():
        tag = _local(element.tag).lower()
        if tag in ACTIVE_ELEMENTS:
            active.append(tag)
        for attribute, value in element.attrib.items():
            attribute_name = _local(attribute).lower()
            if attribute_name in HANDLER_ATTRIBUTES:
                handlers.append(attribute_name)
            if attribute_name in {"href", "src"} and value and not _is_internal_fragment(value):
                external.append(value)
    assert active == [], svg_text
    assert handlers == [], svg_text
    assert external == [], svg_text
    lowered = svg_text.lower()
    for marker in EXTERNAL_MARKERS:
        assert marker not in lowered, svg_text
    for snippet in kept:
        assert snippet in svg_text


SYMBOLS = textwrap.dedent(
    """\
    <?xml version="1.0"?>
    <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
      <script type="application/ecmascript" id="from-symbols">marker()</script>
      <symbol id="door">
        <path d="M1 1 L2 2"/>
        <script id="nested-symbol-script">marker()</script>
        <path d="M1 2 L2 3" onload="marker()" onclick="marker()"/>
        <a xlink:href="javascript:marker()"><path d="M0 1 L1 0"/></a>
        <use xlink:href="#door-keep"/>
        <set attributeName="onload" to="marker()"/>
        <animate attributeName="href" to="javascript:marker()"/>
      </symbol>
      <foreignObject width="10" height="10">
        <body xmlns="http://www.w3.org/1999/xhtml">x</body>
      </foreignObject>
    </svg>
    """
)

MARKERS = textwrap.dedent(
    """\
    <?xml version="1.0"?>
    <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
      <marker id="arrow" orient="auto">
        <path d="M3 3 L4 4" onmouseover="marker()" onbegin="marker()"/>
        <image xlink:href="https://evil.example/marker.png"/>
      </marker>
    </svg>
    """
)

_DATA_SVG = (
    "data:image/svg+xml,&lt;svg xmlns='http://www.w3.org/2000/svg'&gt;"
    "&lt;script&gt;marker()&lt;/script&gt;&lt;/svg&gt;"
)
PATTERNS = textwrap.dedent(
    f"""\
    <?xml version="1.0"?>
    <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
      <pattern id="hatch">
        <path d="M4 4 L5 5"/>
        <foreignObject width="8" height="8">
          <body xmlns="http://www.w3.org/1999/xhtml"><script>marker()</script></body>
        </foreignObject>
        <image href="{_DATA_SVG}"/>
        <use href="http://evil.example/lib.svg#icon"/>
      </pattern>
    </svg>
    """
)

STYLESHEET = (
    "]]></style><script id=\"from-stylesheet\">marker()</script><style><![CDATA[\n"
    ".sheet-ok { stroke: black; }\n"
)


def test_symbol_marker_pattern_and_stylesheet_markup_is_not_active(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "symbols.svg").write_text(SYMBOLS)
    (project / "markers.svg").write_text(MARKERS)
    (project / "patterns.svg").write_text(PATTERNS)
    (project / "safe.css").write_text(".sheet-ok { stroke: black; }\n")
    (project / "break.css").write_text(STYLESHEET)
    ifc_path = project / "model.ifc"
    element = _write_ifc(
        ifc_path,
        {
            "Symbols": "symbols.svg",
            "Markers": "markers.svg",
            "Patterns": "patterns.svg",
            "Stylesheet": "safe.css,break.css",
        },
    )
    writer = _writer_for(ifc_path, element)
    svg_text = _combine(writer, project / "drawings" / "PLAN.svg")
    _assert_drawing_is_inert(
        svg_text,
        kept=('d="M1 1 L2 2"', 'd="M3 3 L4 4"', 'd="M4 4 L5 5"', 'orient="auto"', "#door-keep", ".sheet-ok"),
    )
    assert "from-symbols" not in svg_text
    assert "from-stylesheet" not in svg_text
    assert "nested-symbol-script" not in svg_text


def test_find_xml_symbol_by_id_drops_nested_active_content(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "symbols.svg").write_text(SYMBOLS)
    ifc_path = project / "model.ifc"
    element = _write_ifc(ifc_path, {"Symbols": "symbols.svg"})
    writer = _writer_for(ifc_path, element)
    writer.create_blank_svg(str(project / "unused.svg"))
    symbol = writer.find_xml_symbol_by_id("door")
    assert symbol is not None
    writer.svg.add(symbol)
    svg_text = writer.svg.tostring()
    _assert_drawing_is_inert(svg_text, kept=('d="M1 1 L2 2"', "#door-keep"))
    assert "nested-symbol-script" not in svg_text


def test_relative_resource_outside_the_project_is_not_inlined(tmp_path: Path):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (outside / "symbols.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'><symbol id='x'><desc>OUTSIDE_RELATIVE_TOKEN</desc></symbol></svg>"
    )
    ifc_path = project / "model.ifc"
    element = _write_ifc(ifc_path, {"Symbols": "../outside/symbols.svg"})
    writer = _writer_for(ifc_path, element)
    svg_text = _combine(writer, project / "drawings" / "PLAN.svg")
    assert "OUTSIDE_RELATIVE_TOKEN" not in svg_text


def test_missing_outside_resource_does_not_create_a_directory(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "created-outside"
    ifc_path = project / "model.ifc"
    element = _write_ifc(ifc_path, {"Symbols": "../created-outside/nested/not-a-default-library.svg"})
    writer = SVG_WRITER(
        camera_width=1.0,
        camera_height=1.0,
        camera=SimpleNamespace(),
        camera_projection=SimpleNamespace(),
        scale=1 / 100,
        human_scale="1:100",
    )
    PROJECT_PATH.path = str(ifc_path)
    try:
        writer.setup_drawing_resource_paths(element)
        writer.create_blank_svg(str(project / "blank.svg")).define_boilerplate()
    except Exception:
        pass
    assert not outside.exists()


def test_absolute_path_outside_the_project_is_not_inlined(tmp_path: Path):
    project = tmp_path / "project"
    outside = tmp_path / "absolute-outside"
    project.mkdir()
    outside.mkdir()
    library = outside / "symbols.svg"
    library.write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'><symbol id='x'><desc>OUTSIDE_ABSOLUTE_TOKEN</desc></symbol></svg>"
    )
    ifc_path = project / "model.ifc"
    element = _write_ifc(ifc_path, {"Symbols": str(library)})
    writer = _writer_for(ifc_path, element)
    svg_text = _combine(writer, project / "drawings" / "PLAN.svg")
    assert "OUTSIDE_ABSOLUTE_TOKEN" not in svg_text


def test_absolute_path_inside_the_project_keeps_geometry(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    library = project / "symbols.svg"
    library.write_text(SYMBOLS)
    ifc_path = project / "model.ifc"
    element = _write_ifc(ifc_path, {"Symbols": str(library)})
    writer = _writer_for(ifc_path, element)
    svg_text = _combine(writer, project / "drawings" / "PLAN.svg")
    _assert_drawing_is_inert(svg_text, kept=('d="M1 1 L2 2"',))


def test_symlink_inside_the_project_pointing_outside_is_not_inlined(tmp_path: Path):
    project = tmp_path / "project"
    outside = tmp_path / "symlink-target"
    project.mkdir()
    outside.mkdir()
    target = outside / "real.svg"
    target.write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'><symbol id='x'><desc>OUTSIDE_SYMLINK_TOKEN</desc></symbol></svg>"
    )
    link = project / "symbols.svg"
    link.symlink_to(target)
    ifc_path = project / "model.ifc"
    element = _write_ifc(ifc_path, {"Symbols": "symbols.svg"})
    writer = _writer_for(ifc_path, element)
    svg_text = _combine(writer, project / "drawings" / "PLAN.svg")
    assert "OUTSIDE_SYMLINK_TOKEN" not in svg_text


def test_markers_and_patterns_are_filtered_when_symbols_are_absent(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "markers.svg").write_text(MARKERS)
    (project / "patterns.svg").write_text(PATTERNS)
    ifc_path = project / "model.ifc"
    element = _write_ifc(ifc_path, {"Markers": "markers.svg", "Patterns": "patterns.svg"})
    writer = _writer_for(ifc_path, element)
    writer.create_blank_svg(str(project / "blank.svg"))
    writer.add_markers()
    writer.add_patterns()
    _assert_drawing_is_inert(writer.svg.tostring(), kept=('d="M3 3 L4 4"', 'd="M4 4 L5 5"', 'orient="auto"'))
