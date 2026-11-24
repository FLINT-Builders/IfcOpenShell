# This file was generated with the assistance of an AI coding tool.
"""IFC document locations must not be handed to the OS file handler.

Open Drawing, Open Sheet Layout, Open Schedule, and Open Reference take a
path from IfcDocumentReference.Location (or IfcDocumentInformation.Location)
and, when the matching preference is blank, pass it to os.startfile, open,
or xdg-open. These tests fail while that path is still unchecked.

Not covered here, and why:
- CreateDrawing's open-viewer branch (operator.py, after SVG generation)
  calls the same helper, but only once linework generation has run.
- OpenSheet and CreateSheets open the SVG or PDF that SheetBuilder just
  wrote under the sanitised default sheet name, not the raw IFC location.
- build_schedule rewrites the location's extension to .svg before opening.
- Blender.open_file_or_folder and the cost-schedule exporter open a path
  the user picked or the add-on just wrote, not an IFC document location.
"""

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import bpy
import ifcopenshell
import ifcopenshell.guid
import pytest

import bonsai.bim.module.drawing.operator as operator_mod
import bonsai.tool as tool
import bonsai.tool.drawing as drawing_mod
from test.tool.launch_original import ORIGINAL_OPEN_WITH_USER_COMMAND

MINIMAL_SVG = "<svg xmlns='http://www.w3.org/2000/svg'></svg>"
SCRIPT_EXTENSIONS = (".bat", ".lnk", ".command", ".app", ".desktop", ".exe", ".sh")


@pytest.fixture
def real_launcher():
    """Run the real opener. Other tool tests leave a no-op in its place."""
    previous = tool.Drawing.__dict__["open_with_user_command"]
    tool.Drawing.open_with_user_command = ORIGINAL_OPEN_WITH_USER_COMMAND
    yield
    tool.Drawing.open_with_user_command = previous


@pytest.fixture
def launch_record(monkeypatch, real_launcher):
    """Record every OS launch and do not start a process."""
    calls = []

    def record_call(args, *args_, **kwargs):
        calls.append(tuple(args))
        return 0

    def record_popen(args, *args_, **kwargs):
        calls.append(tuple(args))

        class _Process:
            def wait(self, *a, **k):
                return 0

            def poll(self):
                return 0

        return _Process()

    def record_startfile(path, *args_, **kwargs):
        calls.append(("startfile", os.fspath(path)))

    monkeypatch.setattr(drawing_mod.subprocess, "call", record_call)
    monkeypatch.setattr(drawing_mod.subprocess, "Popen", record_popen)
    monkeypatch.setattr(drawing_mod.os, "startfile", record_startfile, raising=False)
    return calls


@pytest.fixture
def blank_open_preferences():
    prefs = tool.Blender.get_addon_preferences()
    # The attack uses the shipped default, which is an empty command.
    for name in ("svg_command", "layout_svg_command", "pdf_command", "spreadsheet_command"):
        assert prefs.bl_rna.properties[name].default == ""
    names = ("svg_command", "layout_svg_command", "pdf_command", "spreadsheet_command")
    saved = {name: getattr(prefs, name) for name in names}
    prefs.svg_command = ""
    prefs.layout_svg_command = ""
    prefs.pdf_command = ""
    prefs.spreadsheet_command = ""
    yield prefs
    for name, value in saved.items():
        setattr(prefs, name, value)


def _clear_documents(props):
    props.drawings.clear()
    props.sheets.clear()
    props.schedules.clear()
    props.references.clear()


def _use_ifc(ifc, ifc_path: Path):
    ifc.write(str(ifc_path))
    tool.Ifc.set(ifc)
    tool.Ifc.set_path(str(ifc_path))
    _clear_documents(tool.Drawing.get_document_props())


def _associate(ifc, element, document):
    ifc.create_entity(
        "IfcRelAssociatesDocument",
        GlobalId=ifcopenshell.guid.new(),
        RelatingDocument=document,
        RelatedObjects=[element],
    )


def _add_drawing_item(drawing, *, name="PLAN", selected=True):
    props = tool.Drawing.get_document_props()
    item = props.drawings.add()
    item.name = name
    item.is_drawing = True
    item.is_selected = selected
    item.ifc_definition_id = drawing.id()
    props.active_drawing_index = len(props.drawings) - 1
    return item


def _make_drawing(ifc, name, location):
    drawing = ifc.create_entity(
        "IfcAnnotation",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        ObjectType="DRAWING",
    )
    reference = ifc.create_entity("IfcDocumentReference", Location=location)
    _associate(ifc, drawing, reference)
    return drawing, reference


def _project_dir(ifc_path: Path) -> Path:
    return ifc_path.parent.resolve()


def _allowed_drawing_target(path: str, project_dir: Path) -> bool:
    """The path actually handed to the OS must be an SVG inside the project.

    realpath is taken at check time so a symlink, or a second lookup of the
    IFC location, cannot point the launch at another file.
    """
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    if not resolved.is_file():
        return False
    if resolved.suffix.lower() != ".svg":
        return False
    try:
        resolved.relative_to(project_dir)
    except ValueError:
        return False
    return True


def _launched_paths(calls) -> list[str]:
    paths = []
    for call in calls:
        if not call:
            continue
        if call[0] == "startfile":
            paths.append(call[1])
        elif call[0] in {"xdg-open", "open"}:
            paths.append(call[1])
        else:
            paths.append(call[-1])
    return paths


def _assert_only_allowed(calls, project_dir: Path):
    for path in _launched_paths(calls):
        assert _allowed_drawing_target(path, project_dir), path


@pytest.mark.parametrize("system", ["Linux", "Windows", "Darwin"])
@pytest.mark.parametrize("extension", SCRIPT_EXTENSIONS)
def test_open_drawing_does_not_launch_script_from_document_location(
    tmp_path, monkeypatch, launch_record, blank_open_preferences, system, extension
):
    monkeypatch.setattr(drawing_mod.platform, "system", lambda: system)
    project = tmp_path / "project"
    drawings = project / "drawings"
    drawings.mkdir(parents=True)
    ifc_path = project / "model.ifc"
    payload = drawings / f"PLAN{extension}"
    if extension == ".app":
        payload.mkdir()
        (payload / "payload").write_text("#!/bin/sh\n", encoding="utf-8")
    else:
        payload.write_text("payload\n", encoding="utf-8")

    ifc = ifcopenshell.file(schema="IFC4")
    drawing, _reference = _make_drawing(ifc, "PLAN", f"drawings/PLAN{extension}")
    _use_ifc(ifc, ifc_path)
    _add_drawing_item(drawing)

    before = {p.name for p in project.rglob("*")}
    bpy.ops.bim.open_drawing(view="PLAN")
    after = {p.name for p in project.rglob("*")}

    assert after == before
    _assert_only_allowed(launch_record, _project_dir(ifc_path))
    assert launch_record == []


@pytest.mark.parametrize("system", ["Linux", "Windows", "Darwin"])
def test_open_drawing_does_not_launch_absolute_or_parent_path(
    tmp_path, monkeypatch, launch_record, blank_open_preferences, system
):
    monkeypatch.setattr(drawing_mod.platform, "system", lambda: system)
    project = tmp_path / "project"
    (project / "drawings").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    ifc_path = project / "model.ifc"
    absolute = outside / "PLAN.bat"
    absolute.write_text("payload\n", encoding="utf-8")
    escaped = tmp_path / "PLAN.command"
    escaped.write_text("payload\n", encoding="utf-8")

    ifc = ifcopenshell.file(schema="IFC4")
    absolute_drawing, _abs_ref = _make_drawing(ifc, "ABSOLUTE", str(absolute))
    escaped_drawing, _esc_ref = _make_drawing(ifc, "ESCAPED", "drawings/../../PLAN.command")
    _use_ifc(ifc, ifc_path)
    _add_drawing_item(absolute_drawing, name="ABSOLUTE")
    bpy.ops.bim.open_drawing(view="ABSOLUTE")
    _assert_only_allowed(launch_record, _project_dir(ifc_path))

    launch_record.clear()
    props = tool.Drawing.get_document_props()
    props.drawings.clear()
    _add_drawing_item(escaped_drawing, name="ESCAPED")
    bpy.ops.bim.open_drawing(view="ESCAPED")
    _assert_only_allowed(launch_record, _project_dir(ifc_path))
    assert launch_record == []


def test_open_drawing_does_not_follow_symlink_out_of_the_project(
    tmp_path, monkeypatch, launch_record, blank_open_preferences
):
    monkeypatch.setattr(drawing_mod.platform, "system", lambda: "Linux")
    project = tmp_path / "project"
    drawings = project / "drawings"
    drawings.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "PLAN.bat"
    target.write_text("payload\n", encoding="utf-8")
    link = drawings / "PLAN.svg"
    link.symlink_to(target)
    ifc_path = project / "model.ifc"

    ifc = ifcopenshell.file(schema="IFC4")
    drawing, _reference = _make_drawing(ifc, "PLAN", "drawings/PLAN.svg")
    _use_ifc(ifc, ifc_path)
    _add_drawing_item(drawing)

    bpy.ops.bim.open_drawing(view="PLAN")
    _assert_only_allowed(launch_record, _project_dir(ifc_path))


def test_open_drawing_rechecks_the_path_it_launches(tmp_path, monkeypatch, launch_record, blank_open_preferences):
    """A check of one location must not be followed by opening another.

    os.path.exists is where Open Drawing currently looks at the path. While
    that check runs, the IFC location is pointed at a script. The launch has
    to refuse that script even if an earlier lookup saw the SVG.
    """
    monkeypatch.setattr(drawing_mod.platform, "system", lambda: "Linux")
    project = tmp_path / "project"
    drawings = project / "drawings"
    drawings.mkdir(parents=True)
    svg = drawings / "PLAN.svg"
    svg.write_text(MINIMAL_SVG, encoding="utf-8")
    script = drawings / "PLAN.bat"
    script.write_text("payload\n", encoding="utf-8")
    ifc_path = project / "model.ifc"

    ifc = ifcopenshell.file(schema="IFC4")
    drawing, reference = _make_drawing(ifc, "PLAN", "drawings/PLAN.svg")
    _use_ifc(ifc, ifc_path)
    _add_drawing_item(drawing)

    real_exists = os.path.exists

    def exists_then_retarget(path):
        found = real_exists(path)
        # Only the drawing path's existence check may retarget. Other checks,
        # such as the IFC file itself, happen while the location is still read.
        try:
            checked = Path(path).resolve()
        except OSError:
            checked = None
        if checked == svg.resolve():
            reference.Location = "drawings/PLAN.bat"
        return found

    monkeypatch.setattr(operator_mod.os.path, "exists", exists_then_retarget)
    monkeypatch.setattr(drawing_mod.os.path, "exists", exists_then_retarget)

    bpy.ops.bim.open_drawing(view="PLAN")
    _assert_only_allowed(launch_record, _project_dir(ifc_path))
    for path in _launched_paths(launch_record):
        assert Path(path).resolve() == svg.resolve()


def test_open_drawing_still_opens_svg_inside_the_project(tmp_path, monkeypatch, launch_record, blank_open_preferences):
    monkeypatch.setattr(drawing_mod.platform, "system", lambda: "Linux")
    project = tmp_path / "project"
    drawings = project / "drawings"
    drawings.mkdir(parents=True)
    svg = drawings / "PLAN.svg"
    svg.write_text(MINIMAL_SVG, encoding="utf-8")
    ifc_path = project / "model.ifc"

    ifc = ifcopenshell.file(schema="IFC4")
    drawing, _reference = _make_drawing(ifc, "PLAN", "drawings/PLAN.svg")
    _use_ifc(ifc, ifc_path)
    _add_drawing_item(drawing)

    result = bpy.ops.bim.open_drawing(view="PLAN")
    assert result == {"FINISHED"}
    launched = [Path(path).resolve() for path in _launched_paths(launch_record)]
    assert launched == [svg.resolve()]
    _assert_only_allowed(launch_record, _project_dir(ifc_path))


def test_open_all_drawings_skips_a_script_among_svgs(tmp_path, monkeypatch, launch_record, blank_open_preferences):
    monkeypatch.setattr(drawing_mod.platform, "system", lambda: "Windows")
    project = tmp_path / "project"
    drawings = project / "drawings"
    drawings.mkdir(parents=True)
    (drawings / "SAFE.svg").write_text(MINIMAL_SVG, encoding="utf-8")
    (drawings / "EVIL.bat").write_text("payload\n", encoding="utf-8")
    ifc_path = project / "model.ifc"

    ifc = ifcopenshell.file(schema="IFC4")
    safe, _safe_ref = _make_drawing(ifc, "SAFE", "drawings/SAFE.svg")
    evil, _evil_ref = _make_drawing(ifc, "EVIL", "drawings/EVIL.bat")
    _use_ifc(ifc, ifc_path)
    _add_drawing_item(safe, name="SAFE")
    _add_drawing_item(evil, name="EVIL")

    bpy.ops.bim.open_drawing(view="SAFE", open_all=True)
    _assert_only_allowed(launch_record, _project_dir(ifc_path))


def _sheet_with_layout(ifc, location, *, on_information=False):
    sheet = ifc.create_entity(
        "IfcDocumentInformation",
        Identification="A01",
        Name="PLAN",
        Scope="SHEET",
    )
    if on_information:
        sheet.Location = location
    ifc.create_entity(
        "IfcDocumentReference",
        Location=location,
        Description="LAYOUT",
        ReferencedDocument=sheet,
    )
    return sheet


def _select_sheet(sheet):
    props = tool.Drawing.get_document_props()
    props.sheets.clear()
    item = props.sheets.add()
    item.name = sheet.Name
    item.identification = sheet.Identification
    item.is_sheet = True
    item.ifc_definition_id = sheet.id()
    props.active_sheet_index = 0


@pytest.mark.parametrize("on_information", [False, True])
def test_open_layout_does_not_launch_script_location(
    tmp_path, monkeypatch, launch_record, blank_open_preferences, on_information
):
    monkeypatch.setattr(drawing_mod.platform, "system", lambda: "Darwin")
    project = tmp_path / "project"
    layouts = project / "layouts"
    layouts.mkdir(parents=True)
    payload = layouts / "A01.command"
    payload.write_text(MINIMAL_SVG, encoding="utf-8")
    ET.parse(payload)  # the operator parses the layout before opening it
    ifc_path = project / "model.ifc"

    ifc = ifcopenshell.file(schema="IFC4")
    sheet = _sheet_with_layout(ifc, "layouts/A01.command", on_information=on_information)
    _use_ifc(ifc, ifc_path)
    _select_sheet(sheet)

    before = {p.name for p in project.rglob("*")}
    bpy.ops.bim.open_layout()
    after = {p.name for p in project.rglob("*")}
    assert after == before
    _assert_only_allowed(launch_record, _project_dir(ifc_path))
    assert launch_record == []


def test_open_layout_still_opens_svg_inside_the_project(tmp_path, monkeypatch, launch_record, blank_open_preferences):
    monkeypatch.setattr(drawing_mod.platform, "system", lambda: "Linux")
    project = tmp_path / "project"
    layouts = project / "layouts"
    layouts.mkdir(parents=True)
    svg = layouts / "A01.svg"
    svg.write_text(MINIMAL_SVG, encoding="utf-8")
    ifc_path = project / "model.ifc"

    ifc = ifcopenshell.file(schema="IFC4")
    sheet = _sheet_with_layout(ifc, "layouts/A01.svg")
    _use_ifc(ifc, ifc_path)
    _select_sheet(sheet)

    bpy.ops.bim.open_layout()
    _assert_only_allowed(launch_record, _project_dir(ifc_path))
    assert _launched_paths(launch_record)


def _information_with_reference(ifc, scope, location):
    information = ifc.create_entity(
        "IfcDocumentInformation",
        Identification="X",
        Name="DOC",
        Scope=scope,
    )
    ifc.create_entity(
        "IfcDocumentReference",
        Location=location,
        ReferencedDocument=information,
    )
    return information


@pytest.mark.parametrize(
    ("operator", "scope", "collection", "extension"),
    [
        ("bim.open_schedule", "SCHEDULE", "schedules", ".bat"),
        ("bim.open_schedule", "SCHEDULE", "schedules", ".command"),
        ("bim.open_reference", "REFERENCE", "references", ".desktop"),
        ("bim.open_reference", "REFERENCE", "references", ".lnk"),
    ],
)
def test_open_schedule_and_reference_do_not_launch_scripts(
    tmp_path, monkeypatch, launch_record, blank_open_preferences, operator, scope, collection, extension
):
    monkeypatch.setattr(drawing_mod.platform, "system", lambda: "Windows")
    project = tmp_path / "project"
    docs = project / "docs"
    docs.mkdir(parents=True)
    payload = docs / f"DOC{extension}"
    payload.write_text("payload\n", encoding="utf-8")
    ifc_path = project / "model.ifc"

    ifc = ifcopenshell.file(schema="IFC4")
    document = _information_with_reference(ifc, scope, f"docs/DOC{extension}")
    _use_ifc(ifc, ifc_path)
    props = tool.Drawing.get_document_props()
    item = getattr(props, collection).add()
    item.ifc_definition_id = document.id()
    item.name = "DOC"

    if operator == "bim.open_schedule":
        bpy.ops.bim.open_schedule(schedule=document.id())
    else:
        bpy.ops.bim.open_reference(reference=document.id())
    _assert_only_allowed(launch_record, _project_dir(ifc_path))
    assert launch_record == []


def test_open_reference_still_opens_svg_inside_the_project(
    tmp_path, monkeypatch, launch_record, blank_open_preferences
):
    monkeypatch.setattr(drawing_mod.platform, "system", lambda: "Linux")
    project = tmp_path / "project"
    docs = project / "docs"
    docs.mkdir(parents=True)
    svg = docs / "DOC.svg"
    svg.write_text(MINIMAL_SVG, encoding="utf-8")
    ifc_path = project / "model.ifc"

    ifc = ifcopenshell.file(schema="IFC4")
    document = _information_with_reference(ifc, "REFERENCE", "docs/DOC.svg")
    _use_ifc(ifc, ifc_path)
    props = tool.Drawing.get_document_props()
    item = props.references.add()
    item.ifc_definition_id = document.id()
    item.name = "DOC"

    bpy.ops.bim.open_reference(reference=document.id())
    _assert_only_allowed(launch_record, _project_dir(ifc_path))
    assert _launched_paths(launch_record)


def test_open_schedule_still_opens_spreadsheet_inside_the_project(
    tmp_path, monkeypatch, launch_record, blank_open_preferences
):
    monkeypatch.setattr(drawing_mod.platform, "system", lambda: "Linux")
    project = tmp_path / "project"
    docs = project / "docs"
    docs.mkdir(parents=True)
    sheet = docs / "DOC.xlsx"
    sheet.write_bytes(b"PK\x03\x04")
    ifc_path = project / "model.ifc"

    ifc = ifcopenshell.file(schema="IFC4")
    document = _information_with_reference(ifc, "SCHEDULE", "docs/DOC.xlsx")
    _use_ifc(ifc, ifc_path)
    props = tool.Drawing.get_document_props()
    item = props.schedules.add()
    item.ifc_definition_id = document.id()
    item.name = "DOC"

    bpy.ops.bim.open_schedule(schedule=document.id())
    launched = _launched_paths(launch_record)
    assert launched
    for path in launched:
        resolved = Path(path).resolve()
        assert resolved == sheet.resolve()
        resolved.relative_to(_project_dir(ifc_path))
