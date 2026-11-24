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

# This file was generated with the assistance of an AI coding tool.

"""Document and drawing-resource paths from an IFC file must stay inside the project.

These tests open a real IFC file and run the Bonsai functions that turn
``IfcDocumentReference.Location`` and ``EPset_Drawing`` resource paths into
filesystem writes. A path is confined only when ``os.path.realpath`` of the
final file stays inside the IFC file's directory (or a drawings directory the
test set under that directory). Absolute locations are refused. Drawing output
must use a ``.svg`` name. A symlink that sits inside the project and points
outside is refused, including when an earlier lexical check would still see the
path as inside the project: the file that is created or replaced has to be the
realpath that was accepted.

``CreateDrawing.generate_underlay``, ``generate_linework``,
``generate_freestyle_linework`` and ``generate_annotation`` write the SVG (and
the underlay PNG) returned by ``get_svg_path``. Those generators need a
Blender render or the geometry serializer, so they are not executed here. They
remain unsafe if ``get_svg_path`` still creates or returns a path outside the
project. ``SheetBuilder.build`` also copies images named by hrefs inside an
existing layout; that copy is not given its own case beyond the sheet path
``build`` writes.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[3]
for _pkg in (
    "bonsai",
    "bcf",
    "ifctester",
    "ifcpatch",
    "ifc5d",
    "bsdd",
    "ifcclash",
    "ifcdiff",
    "ifcfm",
    "ifc4d",
    "ifccsv",
):
    _path = _SRC / _pkg
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.guid
import ifcopenshell.util.element
from mathutils import Vector

import bonsai

if not getattr(bonsai, "REGISTERED_BBIM_PACKAGE", None):
    bonsai.is_registering = lambda: True
    bonsai.REGISTERED_BBIM_PACKAGE = "bonsai"

import bonsai.bim
import bonsai.bim.module.drawing.operator as operator
import bonsai.bim.module.drawing.sheeter as sheeter
import bonsai.bim.module.drawing.svgwriter as svgwriter
import bonsai.core.drawing as core
import bonsai.tool as tool
from bonsai.bim.ifc import IfcStore

_DATA_DIR = Path(bonsai.bim.__file__).resolve().parent / "data"
_SENTINEL = "ORIGINAL-SENTINEL\n"
_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm"></svg>\n'


class _DocPrefs:
    drawings_dir = "Drawings"
    layouts_dir = "Layouts"
    titleblocks_dir = "Titleblocks"
    sheets_dir = "Sheets"
    shadingstyle_default = "default"
    schedules_stylesheet_path = ""


class _Prefs:
    data_dir = str(_DATA_DIR)

    def __init__(self):
        self.doc = _DocPrefs()


def _ensure_data_dir() -> None:
    """Point resource lookups at the add-on's real data directory when the add-on is not registered."""
    try:
        prefs = tool.Blender.get_addon_preferences()
        if getattr(prefs, "data_dir", None):
            return
    except Exception:
        pass

    def _prefs(cls):
        return _Prefs()

    tool.Blender.get_addon_preferences = classmethod(_prefs)


_ensure_data_dir()


class _Host:
    """Attribute bag ``CreateDrawing`` methods read. The methods themselves are the real ones."""

    def __init__(self, document, name, writer):
        self.camera_document = document
        self.drawing_name = name
        self.svg_writer = writer

    def get_svg_path(self, cache_type=None):
        return operator.CreateDrawing.get_svg_path(self, cache_type)


def _blank_writer():
    writer = svgwriter.SvgWriter(
        camera_width=1.0,
        camera_height=1.0,
        camera=None,
        camera_projection=Vector((0, 0, -1)),
        scale=0.01,
        human_scale="1:100",
    )
    for resource in tool.Drawing.RESOURCE_TYPES:
        writer.resource_paths[resource] = None
    return writer


def _call(fn) -> None:
    try:
        fn()
    except Exception:
        return


def _assert_unchanged(path: Path, original: str | None) -> None:
    if original is None:
        assert not path.exists(), f"{path} was created"
        return
    assert path.is_file(), f"{path} is missing"
    assert path.read_text() == original, f"{path} was modified: {path.read_text()[:80]!r}"


def _load(ifc: ifcopenshell.file, dest: Path) -> ifcopenshell.file:
    dest.parent.mkdir(parents=True, exist_ok=True)
    ifc.write(str(dest))
    opened = ifcopenshell.open(str(dest))
    tool.Ifc.set(opened)
    try:
        tool.Ifc.set_path(str(dest))
    except Exception:
        IfcStore.set_path(str(dest))
    assert tool.Ifc.get_path() == str(dest)
    return opened


def _project(ifc: ifcopenshell.file, documentation: dict | None = None):
    project = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject", name="Project")
    if documentation:
        pset = ifcopenshell.api.pset.add_pset(ifc, product=project, name="BBIM_Documentation")
        ifcopenshell.api.pset.edit_pset(ifc, pset=pset, properties=documentation)
    return project


def _drawing(ifc: ifcopenshell.file, location: str, resources: dict | None = None, schema: str = "IFC4"):
    drawing = ifc.create_entity(
        "IfcAnnotation",
        GlobalId=ifcopenshell.guid.new(),
        Name="PLAN",
        ObjectType="DRAWING",
    )
    reference = ifc.create_entity("IfcDocumentReference", Location=location)
    if schema == "IFC2X3":
        reference.Name = "DRAWING"
    ifc.create_entity(
        "IfcRelAssociatesDocument",
        GlobalId=ifcopenshell.guid.new(),
        RelatingDocument=reference,
        RelatedObjects=[drawing],
    )
    if resources:
        pset = ifcopenshell.api.pset.add_pset(ifc, product=drawing, name="EPset_Drawing")
        ifcopenshell.api.pset.edit_pset(ifc, pset=pset, properties=resources)
    return drawing


def _sheet(ifc: ifcopenshell.file, references: list[tuple[str, str]]):
    information = ifc.create_entity(
        "IfcDocumentInformation",
        Identification="S1",
        Name="Sheet",
        Scope="SHEET",
    )
    created = []
    for location, description in references:
        reference = ifc.create_entity(
            "IfcDocumentReference",
            Location=location,
            Description=description,
        )
        reference.ReferencedDocument = information
        created.append(reference)
    return information, created


def _opened_drawing(ifc_file: ifcopenshell.file):
    return next(element for element in ifc_file.by_type("IfcAnnotation") if element.ObjectType == "DRAWING")


def _host(ifc_file: ifcopenshell.file) -> _Host:
    drawing = _opened_drawing(ifc_file)
    document = tool.Drawing.get_drawing_document(drawing)
    assert document is not None
    assert document.Location
    return _Host(document, drawing.Name, _blank_writer())


@pytest.fixture
def ws(tmp_path: Path):
    project = tmp_path / "project"
    victim = tmp_path / "victim"
    project.mkdir()
    victim.mkdir()
    (project / "sub").mkdir()
    (project / "Drawings").mkdir()
    state = {"project": project, "victim": victim, "ifc": project / "model.ifc"}
    yield state
    IfcStore.file = None
    IfcStore.path = ""


def test_relative_drawing_inside_project_is_written(ws):
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _drawing(ifc, "Drawings/../Drawings/PLAN.svg")
    opened = _load(ifc, ws["ifc"])
    host = _host(opened)
    operator.CreateDrawing.combine_svgs(host, None, None, None, None)
    written = ws["project"] / "Drawings" / "PLAN.svg"
    assert written.is_file()
    assert written.read_text().lstrip().startswith("<svg")
    assert os.path.realpath(written) == str(written.resolve())
    assert os.path.commonpath([os.path.realpath(written), str(ws["project"])]) == str(ws["project"])


def test_absolute_location_does_not_overwrite_existing_file(ws):
    target = ws["victim"] / "evil.svg"
    target.write_text(_SENTINEL)
    underlay = ws["project"] / "under.svg"
    underlay.write_text(_SVG)
    (ws["project"] / "under.png").write_bytes(b"\x89PNG\r\n")
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _drawing(ifc, str(target))
    opened = _load(ifc, ws["ifc"])
    host = _host(opened)
    _call(lambda: operator.CreateDrawing.combine_svgs(host, None, str(underlay), None, None))
    _assert_unchanged(target, _SENTINEL)
    _assert_unchanged(ws["victim"] / "evil-underlay.png", None)


def test_absolute_location_inside_project_is_refused(ws):
    target = ws["project"] / "Drawings" / "ABS.svg"
    target.write_text(_SENTINEL)
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _drawing(ifc, str(target))
    opened = _load(ifc, ws["ifc"])
    _call(lambda: operator.CreateDrawing.combine_svgs(_host(opened), None, None, None, None))
    _assert_unchanged(target, _SENTINEL)


def test_relative_parent_segments_do_not_leave_project(ws):
    target = ws["victim"] / "evil.svg"
    target.write_text(_SENTINEL)
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _drawing(ifc, "../victim/evil.svg")
    opened = _load(ifc, ws["ifc"])
    _call(lambda: operator.CreateDrawing.combine_svgs(_host(opened), None, None, None, None))
    _assert_unchanged(target, _SENTINEL)


def test_drawing_output_must_use_svg_extension(ws):
    target = ws["project"] / "Drawings" / "PLAN.txt"
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _drawing(ifc, "Drawings/PLAN.txt")
    opened = _load(ifc, ws["ifc"])
    _call(lambda: operator.CreateDrawing.combine_svgs(_host(opened), None, None, None, None))
    _assert_unchanged(target, None)


def test_symlink_inside_project_is_not_followed(ws):
    """Lexical abspath stays inside the project; open() would follow the symlink."""
    target = ws["victim"] / "evil.svg"
    target.write_text(_SENTINEL)
    link = ws["project"] / "sub" / "plan.svg"
    link.symlink_to(target)
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _drawing(ifc, "sub/plan.svg")
    opened = _load(ifc, ws["ifc"])
    resolved = tool.Drawing.get_document_uri(_host(opened).camera_document)
    assert os.path.abspath(resolved) == str(link)
    assert os.path.realpath(resolved) == str(target)
    _call(lambda: operator.CreateDrawing.combine_svgs(_host(opened), None, None, None, None))
    _assert_unchanged(target, _SENTINEL)


def test_directory_symlink_is_not_used_for_drawing_or_cache(ws):
    outside = ws["victim"] / "linkdir"
    outside.mkdir()
    (ws["project"] / "sub" / "outdir").symlink_to(outside)
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _drawing(ifc, "sub/outdir/plan.svg")
    opened = _load(ifc, ws["ifc"])
    host = _host(opened)
    _call(lambda: operator.CreateDrawing.get_svg_path(host, "linework"))
    _call(lambda: operator.CreateDrawing.combine_svgs(host, None, None, None, None))
    assert list(outside.rglob("*")) == []
    _assert_unchanged(outside / "plan.svg", None)
    _assert_unchanged(outside / "cache" / "PLAN-linework.svg", None)


def test_new_directory_outside_project_is_not_created(ws):
    target = ws["victim"] / "newdir" / "plan.svg"
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _drawing(ifc, str(target))
    opened = _load(ifc, ws["ifc"])
    _call(lambda: operator.CreateDrawing.get_svg_path(_host(opened)))
    assert not (ws["victim"] / "newdir").exists()
    _assert_unchanged(target, None)


def test_ifc2x3_absolute_location_is_refused(ws):
    target = ws["victim"] / "ifc2x3.svg"
    target.write_text(_SENTINEL)
    ifc = ifcopenshell.file(schema="IFC2X3")
    ifc.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Project")
    _drawing(ifc, str(target), schema="IFC2X3")
    opened = _load(ifc, ws["ifc"])
    _call(lambda: operator.CreateDrawing.combine_svgs(_host(opened), None, None, None, None))
    _assert_unchanged(target, _SENTINEL)


def test_resource_paths_are_not_created_outside_project(ws):
    outside_css = ws["victim"] / "nested" / "default.css"
    outside_markers = ws["victim"] / "linkdir" / "markers.svg"
    outside_symbols = ws["victim"] / "symbols.svg"
    outside_shading = ws["victim"] / "shade" / "shading_styles.json"
    (ws["victim"] / "linkdir").mkdir()
    (ws["project"] / "sub" / "outdir").symlink_to(ws["victim"] / "linkdir")
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _drawing(
        ifc,
        "Drawings/PLAN.svg",
        resources={
            "Stylesheet": "../victim/nested/default.css, ../victim/also/default.css",
            "Markers": "sub/outdir/markers.svg",
            "Symbols": str(outside_symbols),
            "Patterns": "../victim/patterns.svg",
            "ShadingStyles": "../victim/shade/shading_styles.json",
        },
    )
    opened = _load(ifc, ws["ifc"])
    writer = _blank_writer()
    _call(lambda: writer.setup_drawing_resource_paths(_opened_drawing(opened)))
    for path in (
        outside_css,
        ws["victim"] / "also" / "default.css",
        outside_markers,
        outside_symbols,
        ws["victim"] / "patterns.svg",
        outside_shading,
    ):
        _assert_unchanged(path, None)
    assert not (ws["victim"] / "nested").exists()
    assert not (ws["victim"] / "also").exists()
    assert not (ws["victim"] / "shade").exists()
    assert list((ws["victim"] / "linkdir").rglob("*")) == []


def test_shading_styles_helper_does_not_create_outside_project(ws):
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _drawing(ifc, "Drawings/PLAN.svg", resources={"ShadingStyles": "../victim/helper/shading_styles.json"})
    opened = _load(ifc, ws["ifc"])
    shading = ifcopenshell.util.element.get_pset(_opened_drawing(opened), "EPset_Drawing")["ShadingStyles"]
    _call(lambda: tool.Drawing.setup_shading_styles_path(shading))
    assert not (ws["victim"] / "helper").exists()
    _assert_unchanged(ws["victim"] / "helper" / "shading_styles.json", None)


@contextmanager
def _ui_for(drawing, styles):
    class _Props:
        def get_active_drawing(self):
            return drawing

        drawing_styles = styles

    class _CameraProps:
        active_drawing_style_index = 0

    original_props = tool.Drawing.get_document_props
    original_camera = tool.Drawing.get_camera_props
    tool.Drawing.get_document_props = classmethod(lambda cls: _Props())
    tool.Drawing.get_camera_props = classmethod(lambda cls, camera: _CameraProps())
    try:
        yield
    finally:
        tool.Drawing.get_document_props = original_props
        tool.Drawing.get_camera_props = original_camera


def test_reload_drawing_styles_does_not_copy_outside_project(ws):
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _drawing(ifc, "Drawings/PLAN.svg", resources={"ShadingStyles": "../victim/reload/shading_styles.json"})
    opened = _load(ifc, ws["ifc"])
    drawing = _opened_drawing(opened)

    class _Styles(list):
        def add(self):
            item = {}
            self.append(item)
            return item

    context = type("Context", (), {})()
    context.scene = type("Scene", (), {"camera": object()})()

    class _Operator:
        def report(self, level, message):
            return None

    with _ui_for(drawing, _Styles()):
        _call(lambda: operator.ReloadDrawingStyles.execute(_Operator(), context))
    assert not (ws["victim"] / "reload").exists()
    _assert_unchanged(ws["victim"] / "reload" / "shading_styles.json", None)


def test_save_drawing_styles_does_not_overwrite_outside_project(ws):
    target = ws["victim"] / "shading_styles.json"
    target.write_text(_SENTINEL)
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _drawing(
        ifc,
        "Drawings/PLAN.svg",
        resources={"ShadingStyles": str(target), "CurrentShadingStyle": "Default"},
    )
    opened = _load(ifc, ws["ifc"])
    drawing = _opened_drawing(opened)
    styles = [type("Style", (), {"name": "Default", "render_type": "DEFAULT", "raster_style": "{}"})()]
    with _ui_for(drawing, styles):
        _call(
            lambda: operator.SaveDrawingStylesData._execute(
                type("Op", (), {"skip_updating_current_style": False, "rename_style": False})(),
                None,
            )
        )
    _assert_unchanged(target, _SENTINEL)


def test_sheet_layout_and_titleblock_are_not_written_outside_project(ws):
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc, {"TitleblocksDir": str(ws["victim"] / "titleblocks")})
    _sheet(ifc, [(str(ws["victim"] / "layout.svg"), "LAYOUT")])
    opened = _load(ifc, ws["ifc"])
    sheet = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SHEET")
    _call(lambda: tool.Drawing.create_svg_sheet(sheet, "A3"))
    _assert_unchanged(ws["victim"] / "layout.svg", None)
    assert not (ws["victim"] / "titleblocks").exists()


def test_remove_sheet_does_not_delete_outside_project(ws):
    target = ws["victim"] / "layout.svg"
    target.write_text(_SENTINEL)
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _sheet(ifc, [(str(target), "LAYOUT")])
    opened = _load(ifc, ws["ifc"])
    sheet = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SHEET")
    _call(lambda: core.remove_sheet(tool.Ifc, tool.Drawing, sheet))
    _assert_unchanged(target, _SENTINEL)


def test_rename_sheet_does_not_move_outside_project(ws):
    old = ws["victim"] / "old-layout.svg"
    old.write_text(_SENTINEL)
    layouts = ws["victim"] / "layouts"
    layouts.mkdir()
    destination = layouts / "S2 - Renamed.svg"
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc, {"LayoutsDir": str(layouts)})
    _sheet(ifc, [(str(old), "LAYOUT")])
    opened = _load(ifc, ws["ifc"])
    sheet = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SHEET")
    refs = [
        (tool.Drawing.get_reference_description(reference), reference.Location)
        for reference in tool.Drawing.get_document_references(sheet)
    ]
    assert refs, "sheet references were not loaded from the IFC file"
    _call(lambda: core.rename_sheet(tool.Ifc, tool.Drawing, sheet, "S2", "Renamed"))
    _assert_unchanged(old, _SENTINEL)
    _assert_unchanged(destination, None)


def test_add_drawing_does_not_rewrite_outside_layout(ws):
    layout = ws["victim"] / "layout.svg"
    layout.write_text(_SVG)
    drawing_svg = ws["project"] / "Drawings" / "PLAN.svg"
    drawing_svg.write_text(_SVG)
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    _drawing(ifc, "Drawings/PLAN.svg")
    _info, references = _sheet(ifc, [(str(layout), "LAYOUT")])
    opened = _load(ifc, ws["ifc"])
    sheet = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SHEET")
    reference = tool.Drawing.get_document_references(sheet)[0]
    drawing = _opened_drawing(opened)
    _call(lambda: sheeter.SheetBuilder().add_drawing(reference, drawing, sheet))
    _assert_unchanged(layout, _SVG)
    assert not (ws["victim"] / "assets").exists()
    assert references


def test_sheet_build_does_not_write_outside_sheets_dir(ws):
    ifc = ifcopenshell.file(schema="IFC4")
    _project(
        ifc,
        {
            "TitleblocksDir": "Titleblocks",
            "SheetsDir": "Sheets",
        },
    )
    _sheet(ifc, [("Layouts/S1.svg", "LAYOUT")])
    opened = _load(ifc, ws["ifc"])
    sheet = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SHEET")
    tool.Drawing.create_svg_sheet(sheet, "A3")
    assert (ws["project"] / "Layouts" / "S1.svg").is_file()
    project = opened.by_type("IfcProject")[0]
    pset = opened.by_id(ifcopenshell.util.element.get_pset(project, "BBIM_Documentation")["id"])
    ifcopenshell.api.pset.edit_pset(
        opened, pset=pset, properties={"SheetsDir": str(ws["victim"] / "sheets")}
    )
    _call(lambda: sheeter.SheetBuilder().build(sheet))
    assert not (ws["victim"] / "sheets").exists()


def test_schedule_svg_is_not_written_outside_project(ws):
    import openpyxl

    workbook = ws["victim"] / "schedule.xlsx"
    book = openpyxl.Workbook()
    book.active["A1"] = "Name"
    book.save(workbook)
    original = workbook.read_bytes()
    ifc = ifcopenshell.file(schema="IFC4")
    _project(ifc)
    information = ifc.create_entity(
        "IfcDocumentInformation",
        Identification="SCH",
        Name="Schedule",
        Scope="SCHEDULE",
    )
    reference = ifc.create_entity("IfcDocumentReference", Location=str(workbook))
    reference.ReferencedDocument = information
    opened = _load(ifc, ws["ifc"])
    schedule = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SCHEDULE")
    _call(lambda: tool.Drawing.create_svg_schedule(schedule))
    _assert_unchanged(ws["victim"] / "schedule.svg", None)
    assert workbook.read_bytes() == original
