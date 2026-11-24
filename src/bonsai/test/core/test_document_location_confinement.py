# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
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

"""Document Location paths must stay inside the opened IFC directory.

Remove Drawing, Remove Sheet, and the drawing and sheet rename actions take a
filesystem path from the IFC file. These tests open a file written to disk and
call the same core functions the operators call. A path is acceptable only when
its real path is inside the directory that contains the IFC file and, for
drawings, sheets, layouts and revisions, the file name ends in ``.svg``.

Directories named by BBIM_Documentation are not an extra root: DrawingsDir,
SheetsDir and LayoutsDir may be used only when they themselves resolve inside
that IFC directory. The addon preference directories are not consulted for
these cases; the tests point them at a folder that must not receive a file the
IFC tried to place elsewhere.

``regenerate_sheet`` deletes a layout Location too, but only after
``SheetBuilder.create`` rewrites that path. That writer needs Blender titleblock
templates, so it is not covered here.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.guid
import pytest

INSIDE_MARKER = "inside-project-marker"
OUTSIDE_MARKER = "outside-project-marker"

_PRODUCT = None


def _install_blender_stubs() -> None:
    """Let the real Bonsai modules import where Blender is not installed.

    The stubs satisfy ``import bpy`` and friends. They are not used for path
    resolution, deletion, or moving: those calls stay on the real functions.
    """

    roots = {
        "bpy",
        "bmesh",
        "mathutils",
        "bpy_extras",
        "gpu",
        "gpu_extras",
        "blf",
        "bpy_restrict_state",
        "_bpy_restrict_state",
    }

    class Finder:
        def find_spec(self, fullname, path, target=None):
            if fullname.split(".")[0] in roots:
                return importlib.util.spec_from_loader(fullname, self)
            return None

        def create_module(self, spec):
            module = types.ModuleType(spec.name)
            module.__path__ = []
            module.__package__ = spec.name.rpartition(".")[0]
            module.__spec__ = spec
            module.__loader__ = self

            def missing(attr, module=module):
                if attr.startswith("__"):
                    raise AttributeError(attr)
                value = MagicMock(name=f"{module.__name__}.{attr}")
                setattr(module, attr, value)
                return value

            module.__getattr__ = missing
            return module

        def exec_module(self, module):
            if module.__name__ == "mathutils":

                class Vector:
                    def __init__(self, value=(0, 0, 0)):
                        self.value = tuple(value)

                    def __iter__(self):
                        return iter(self.value)

                    def cross(self, other):
                        return self

                module.Vector = Vector
                module.Matrix = MagicMock()
            if module.__name__ == "bpy":
                module.app = MagicMock()
                module.app.version = (4, 2, 0)
                module.app.background = True
            if module.__name__ == "bpy_restrict_state":

                class _RestrictContext:
                    pass

                module._RestrictContext = _RestrictContext

    sys.meta_path.insert(0, Finder())


def _package(name: str, path: Path):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    module.__package__ = name
    module.__file__ = str(path / "__init__.py")
    sys.modules[name] = module
    return module


def _stub(name: str):
    module = types.ModuleType(name)
    module.__package__ = name.rpartition(".")[0]
    sys.modules[name] = module
    return module


def _load_product():
    global _PRODUCT
    if _PRODUCT is not None:
        return _PRODUCT

    bonsai_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(bonsai_root))
    try:
        import bpy
    except ImportError:
        bpy = None
    if bpy is None:
        _install_blender_stubs()

    import bonsai

    if bonsai.__file__ is None:
        raise RuntimeError("bonsai package did not load")

    # Skip bonsai.bim and bonsai.tool package initialisers. Those import every
    # Blender operator. The modules loaded below are the real source files.
    if "bonsai.bim" not in sys.modules:
        _package("bonsai.bim", bonsai_root / "bonsai" / "bim")
    if "bonsai.tool" not in sys.modules:
        _package("bonsai.tool", bonsai_root / "bonsai" / "tool")
    schema = sys.modules.get("bonsai.bim.schema") or _stub("bonsai.bim.schema")
    schema.reload = lambda schema_identifier: None
    if "bonsai.bim.handler" not in sys.modules:
        _stub("bonsai.bim.handler")
    if "bonsai.bim.import_ifc" not in sys.modules:
        _stub("bonsai.bim.import_ifc")
    if "bonsai.tool.brick" not in sys.modules:
        brick = _stub("bonsai.tool.brick")

        class BrickStore:
            pass

        brick.BrickStore = BrickStore

    import bonsai.bim.ifc as bim_ifc
    import bonsai.core.drawing as core
    import bonsai.tool as tool
    import bonsai.tool.document as tool_document
    import bonsai.tool.drawing as tool_drawing
    import bonsai.tool.ifc as tool_ifc

    tool.Ifc = tool_ifc.Ifc
    tool.Document = tool_document.Document
    tool.Drawing = tool_drawing.Drawing

    class DocPrefs:
        drawings_dir = ""
        sheets_dir = ""
        layouts_dir = ""
        titleblocks_dir = ""

    class AddonPrefs:
        doc = DocPrefs()

    class Blender:
        @classmethod
        def get_addon_preferences(cls):
            return AddonPrefs()

    tool.Blender = Blender

    class DrawingTool(tool_drawing.Drawing):
        """Real drawing tool with the Blender UI callbacks left idle.

        ``is_active_drawing`` reads the active drawing id from Blender and does
        not look at Location. Rename and remove still run when it is false,
        which is the state of a drawing that is listed but not activated.
        ``import_drawings``, ``import_sheets`` and ``is_editing_sheets`` only
        refresh the properties panel after the file operation.
        """

        @classmethod
        def is_active_drawing(cls, drawing):
            return False

        @classmethod
        def import_drawings(cls):
            return None

        @classmethod
        def import_sheets(cls):
            return None

        @classmethod
        def is_editing_sheets(cls):
            return False

    assert tool_drawing.Drawing.delete_file.__code__.co_filename.endswith("bonsai/tool/drawing.py")
    assert tool_ifc.Ifc.resolve_uri.__code__.co_filename.endswith("bonsai/tool/ifc.py")
    assert core.remove_drawing.__code__.co_filename.endswith("bonsai/core/drawing.py")
    _PRODUCT = types.SimpleNamespace(
        IfcStore=bim_ifc.IfcStore,
        Ifc=tool_ifc.Ifc,
        core=core,
        drawing_module=tool_drawing,
        DrawingTool=DrawingTool,
        Blender=Blender,
        AddonPrefs=AddonPrefs,
    )
    return _PRODUCT


@pytest.fixture(autouse=True)
def product():
    loaded = _load_product()
    loaded.IfcStore.file = None
    loaded.IfcStore.path = ""
    loaded.IfcStore.id_map = {}
    loaded.IfcStore.guid_map = {}
    loaded.Blender.get_addon_preferences = classmethod(lambda cls: loaded.AddonPrefs())
    yield loaded
    loaded.IfcStore.file = None
    loaded.IfcStore.path = ""


def _guid() -> str:
    return ifcopenshell.guid.new()


def _write(path: Path, marker: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(marker)
    return path


def _preferences_inside(product, project: Path) -> None:
    prefs = product.AddonPrefs()
    approved = project / "user-approved"
    approved.mkdir(parents=True, exist_ok=True)
    prefs.doc.drawings_dir = str(approved / "drawings")
    prefs.doc.sheets_dir = str(approved / "sheets")
    prefs.doc.layouts_dir = str(approved / "layouts")
    prefs.doc.titleblocks_dir = str(approved / "titleblocks")
    product.Blender.get_addon_preferences = classmethod(lambda cls: prefs)


def _open_ifc(product, ifc_file, ifc_path: Path):
    ifc_path.parent.mkdir(parents=True, exist_ok=True)
    ifc_file.write(str(ifc_path))
    opened = ifcopenshell.open(str(ifc_path))
    product.IfcStore.file = opened
    product.IfcStore.path = str(ifc_path)
    product.IfcStore.id_map = {}
    product.IfcStore.guid_map = {}
    return opened


def _new_ifc():
    ifc_file = ifcopenshell.file(schema="IFC4")
    project = ifc_file.create_entity("IfcProject", GlobalId=_guid(), Name="Project")
    return ifc_file, project


def _set_documentation_dirs(ifc_file, project, drawings: str, sheets: str, layouts: str) -> None:
    pset = ifcopenshell.api.pset.add_pset(ifc_file, product=project, name="BBIM_Documentation")
    ifcopenshell.api.pset.edit_pset(
        ifc_file,
        pset=pset,
        properties={"DrawingsDir": drawings, "SheetsDir": sheets, "LayoutsDir": layouts},
    )


def _add_drawing(ifc_file, name: str, location: str):
    annotation = ifc_file.create_entity("IfcAnnotation", GlobalId=_guid(), Name=name, ObjectType="DRAWING")
    information = ifc_file.create_entity("IfcDocumentInformation", Identification="X", Name=name, Scope="DRAWING")
    reference = ifc_file.create_entity(
        "IfcDocumentReference", Location=location, Identification="X", Description="DRAWING"
    )
    reference.ReferencedDocument = information
    ifc_file.create_entity(
        "IfcRelAssociatesDocument",
        GlobalId=_guid(),
        RelatingDocument=reference,
        RelatedObjects=[annotation],
    )
    group = ifc_file.create_entity("IfcGroup", GlobalId=_guid(), Name=name, ObjectType="DRAWING")
    ifc_file.create_entity("IfcRelAssignsToGroup", GlobalId=_guid(), RelatingGroup=group, RelatedObjects=[annotation])
    return annotation


def _add_sheet(ifc_file, identification: str, name: str, references: list[tuple[str, str]]):
    sheet = ifc_file.create_entity("IfcDocumentInformation", Identification=identification, Name=name, Scope="SHEET")
    for description, location in references:
        reference = ifc_file.create_entity(
            "IfcDocumentReference", Location=location, Identification="X", Description=description
        )
        reference.ReferencedDocument = sheet
    return sheet


def _drawing(opened, name: str):
    element = next(item for item in opened.by_type("IfcAnnotation") if item.Name == name)
    return opened.by_id(element.id())


def _sheet(opened, identification: str):
    element = next(
        item
        for item in opened.by_type("IfcDocumentInformation")
        if item.Scope == "SHEET" and item.Identification == identification
    )
    return opened.by_id(element.id())


def _assert_unchanged(path: Path, marker: str) -> None:
    assert path.is_file(), f"{path} was removed"
    assert path.read_text() == marker


def _assert_marker_missing(directory: Path, marker: str) -> None:
    if not directory.exists():
        return
    for candidate in directory.rglob("*"):
        if candidate.is_symlink():
            continue
        if candidate.is_file() and candidate.read_text() == marker:
            raise AssertionError(f"{marker} was written to {candidate}")


@contextmanager
def _retarget_parent_before_path_use(parent: Path, replacement: Path) -> Generator[None, None, None]:
    """Replace ``parent`` with a symlink when the file operation walks it again.

    ``os.remove``, ``os.unlink``, ``os.rename`` and ``os.replace`` look up the
    path they are given. If that lookup is a second one, after a check against
    an earlier result, the directory entry can now point somewhere else. Calls
    that pass an already opened directory descriptor (``dir_fd`` or
    ``src_dir_fd``) keep that descriptor, so they are left alone.
    """

    originals = {name: getattr(os, name) for name in ("remove", "unlink", "rename", "replace")}
    state = {"done": False}

    def retarget() -> None:
        if state["done"] or not parent.is_dir() or parent.is_symlink():
            return
        state["done"] = True
        aside = parent.with_name(parent.name + "-aside")
        originals["rename"](parent, aside)
        parent.symlink_to(replacement, target_is_directory=True)

    def under_parent(path) -> bool:
        try:
            Path(os.fspath(path)).resolve().relative_to(parent.resolve())
        except (ValueError, OSError):
            return str(path).startswith(str(parent))
        return True

    def wrap_remove(real):
        def inner(path, *args, dir_fd=None, **kwargs):
            if dir_fd is None and under_parent(path):
                retarget()
            return real(path, *args, dir_fd=dir_fd, **kwargs)

        return inner

    def wrap_rename(real):
        def inner(src, dst, *args, src_dir_fd=None, dst_dir_fd=None, **kwargs):
            if src_dir_fd is None and under_parent(src):
                retarget()
            return real(src, dst, *args, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd, **kwargs)

        return inner

    os.remove = wrap_remove(originals["remove"])
    os.unlink = wrap_remove(originals["unlink"])
    os.rename = wrap_rename(originals["rename"])
    os.replace = wrap_rename(originals["replace"])
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(os, name, original)


def _remove_drawing(product, opened, name: str, retarget: tuple[Path, Path] | None = None) -> None:
    drawing = _drawing(opened, name)
    if retarget is None:
        product.core.remove_drawing(product.Ifc, product.DrawingTool, drawing)
        return
    parent, replacement = retarget
    with _retarget_parent_before_path_use(parent, replacement):
        product.core.remove_drawing(product.Ifc, product.DrawingTool, drawing)


def test_remove_drawing_deletes_svg_inside_project(product, tmp_path: Path):
    project = tmp_path / "proj"
    ifc_path = project / "model.ifc"
    drawing_path = _write(project / "plan.svg", INSIDE_MARKER)
    ifc_file, _project = _new_ifc()
    _add_drawing(ifc_file, "Plan", str(drawing_path))
    opened = _open_ifc(product, ifc_file, ifc_path)
    _preferences_inside(product, project)

    _remove_drawing(product, opened, "Plan")

    assert not drawing_path.exists()


def test_remove_drawing_keeps_absolute_location_outside_project(product, tmp_path: Path):
    project = tmp_path / "proj"
    outside = _write(tmp_path / "outside" / "secret.svg", OUTSIDE_MARKER)
    ifc_file, _project = _new_ifc()
    _add_drawing(ifc_file, "Plan", str(outside))
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    _remove_drawing(product, opened, "Plan")

    _assert_unchanged(outside, OUTSIDE_MARKER)


def test_remove_drawing_keeps_sibling_directory_with_shared_name_prefix(product, tmp_path: Path):
    project = tmp_path / "proj"
    outside = _write(tmp_path / "proj-other" / "secret.svg", OUTSIDE_MARKER)
    ifc_file, _project = _new_ifc()
    _add_drawing(ifc_file, "Plan", str(outside))
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    _remove_drawing(product, opened, "Plan")

    _assert_unchanged(outside, OUTSIDE_MARKER)


def test_remove_drawing_keeps_relative_location_with_parent_segments(product, tmp_path: Path):
    project = tmp_path / "proj"
    outside = _write(tmp_path / "outside" / "secret.svg", OUTSIDE_MARKER)
    ifc_file, _project = _new_ifc()
    _add_drawing(ifc_file, "Plan", "../outside/secret.svg")
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    _remove_drawing(product, opened, "Plan")

    _assert_unchanged(outside, OUTSIDE_MARKER)


def test_remove_drawing_keeps_absolute_location_with_parent_segments(product, tmp_path: Path):
    project = tmp_path / "proj"
    outside = _write(tmp_path / "outside" / "secret.svg", OUTSIDE_MARKER)
    ifc_file, _project = _new_ifc()
    _add_drawing(ifc_file, "Plan", f"{project}/../outside/secret.svg")
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    _remove_drawing(product, opened, "Plan")

    _assert_unchanged(outside, OUTSIDE_MARKER)


def test_remove_drawing_keeps_file_reached_through_a_directory_symlink(product, tmp_path: Path):
    project = tmp_path / "proj"
    outside = _write(tmp_path / "outside" / "secret.svg", OUTSIDE_MARKER)
    project.mkdir()
    (project / "escape").symlink_to(outside.parent, target_is_directory=True)
    ifc_file, _project = _new_ifc()
    _add_drawing(ifc_file, "Plan", "escape/secret.svg")
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    _remove_drawing(product, opened, "Plan")

    _assert_unchanged(outside, OUTSIDE_MARKER)


def test_remove_drawing_keeps_non_svg_inside_project(product, tmp_path: Path):
    project = tmp_path / "proj"
    document = _write(project / "notes.docx", INSIDE_MARKER)
    ifc_file, _project = _new_ifc()
    _add_drawing(ifc_file, "Plan", str(document))
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    _remove_drawing(product, opened, "Plan")

    _assert_unchanged(document, INSIDE_MARKER)


def test_remove_drawing_does_not_follow_a_parent_replaced_before_unlink(product, tmp_path: Path):
    project = tmp_path / "proj"
    parent = project / "drawings"
    inside = _write(parent / "plan.svg", INSIDE_MARKER)
    outside = _write(tmp_path / "outside" / "plan.svg", OUTSIDE_MARKER)
    ifc_file, _project = _new_ifc()
    _add_drawing(ifc_file, "Plan", str(inside))
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    _remove_drawing(product, opened, "Plan", retarget=(parent, outside.parent))

    _assert_unchanged(outside, OUTSIDE_MARKER)


def test_remove_sheet_keeps_outside_layout_sheet_revision_and_raster(product, tmp_path: Path):
    project = tmp_path / "proj"
    outside_dir = tmp_path / "outside"
    layout = _write(outside_dir / "layout.svg", "layout")
    sheet_file = _write(outside_dir / "sheet.svg", "sheet")
    revision = _write(outside_dir / "revision.svg", "revision")
    raster = _write(outside_dir / "raster.png", "raster")
    project.mkdir()
    (project / "escape").symlink_to(outside_dir, target_is_directory=True)
    ifc_file, _project = _new_ifc()
    _add_sheet(
        ifc_file,
        "A01",
        "Sheet",
        [
            ("LAYOUT", str(layout)),
            ("SHEET", "../outside/sheet.svg"),
            ("REVISION", f"{project}/../outside/revision.svg"),
            ("RASTER", "escape/raster.png"),
        ],
    )
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    product.core.remove_sheet(product.Ifc, product.DrawingTool, _sheet(opened, "A01"))

    _assert_unchanged(layout, "layout")
    _assert_unchanged(sheet_file, "sheet")
    _assert_unchanged(revision, "revision")
    _assert_unchanged(raster, "raster")


def test_remove_sheet_deletes_svg_layout_inside_project(product, tmp_path: Path):
    project = tmp_path / "proj"
    layout = _write(project / "sheets" / "layout.svg", INSIDE_MARKER)
    ifc_file, _project = _new_ifc()
    _add_sheet(ifc_file, "A01", "Sheet", [("LAYOUT", str(layout))])
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    product.core.remove_sheet(product.Ifc, product.DrawingTool, _sheet(opened, "A01"))

    assert not layout.exists()


def test_rename_drawing_moves_svg_within_project(product, tmp_path: Path):
    project = tmp_path / "proj"
    drawings = project / "drawings"
    source = _write(drawings / "Old.svg", INSIDE_MARKER)
    ifc_file, ifc_project = _new_ifc()
    _set_documentation_dirs(ifc_file, ifc_project, str(drawings), str(drawings), str(drawings))
    _add_drawing(ifc_file, "Old", str(source))
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    product.core.update_drawing_name(product.Ifc, product.DrawingTool, _drawing(opened, "Old"), "New")

    destination = drawings / "New.svg"
    assert not source.exists()
    _assert_unchanged(destination, INSIDE_MARKER)


def test_rename_drawing_does_not_move_file_from_outside_location(product, tmp_path: Path):
    project = tmp_path / "proj"
    drawings = project / "drawings"
    drawings.mkdir(parents=True)
    outside = _write(tmp_path / "outside" / "secret.svg", OUTSIDE_MARKER)
    ifc_file, ifc_project = _new_ifc()
    _set_documentation_dirs(ifc_file, ifc_project, str(drawings), str(drawings), str(drawings))
    _add_drawing(ifc_file, "Old", str(outside))
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    product.core.update_drawing_name(product.Ifc, product.DrawingTool, _drawing(opened, "Old"), "New")

    _assert_unchanged(outside, OUTSIDE_MARKER)
    _assert_marker_missing(project, OUTSIDE_MARKER)


def test_rename_drawing_does_not_move_into_drawings_dir_outside_project(product, tmp_path: Path):
    project = tmp_path / "proj"
    source = _write(project / "drawings" / "Old.svg", INSIDE_MARKER)
    shared = tmp_path / "shared"
    shared.mkdir()
    ifc_file, ifc_project = _new_ifc()
    _set_documentation_dirs(ifc_file, ifc_project, str(shared), str(shared), str(shared))
    _add_drawing(ifc_file, "Old", str(source))
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    product.core.update_drawing_name(product.Ifc, product.DrawingTool, _drawing(opened, "Old"), "New")

    _assert_marker_missing(shared, INSIDE_MARKER)
    _assert_marker_missing(tmp_path / "outside", INSIDE_MARKER)
    assert any(
        candidate.is_file() and candidate.read_text() == INSIDE_MARKER
        for candidate in project.rglob("*")
        if not candidate.is_symlink()
    )


def test_rename_drawing_does_not_follow_a_parent_replaced_before_move(product, tmp_path: Path):
    project = tmp_path / "proj"
    parent = project / "drawings"
    source = _write(parent / "Old.svg", INSIDE_MARKER)
    outside = _write(tmp_path / "outside" / "Old.svg", OUTSIDE_MARKER)
    ifc_file, ifc_project = _new_ifc()
    _set_documentation_dirs(ifc_file, ifc_project, str(parent), str(parent), str(parent))
    _add_drawing(ifc_file, "Old", str(source))
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    with _retarget_parent_before_path_use(parent, outside.parent):
        product.core.update_drawing_name(product.Ifc, product.DrawingTool, _drawing(opened, "Old"), "New")

    _assert_unchanged(outside, OUTSIDE_MARKER)


def test_rename_sheet_moves_svg_within_project(product, tmp_path: Path):
    project = tmp_path / "proj"
    sheets = project / "sheets"
    layouts = project / "layouts"
    sheet_file = _write(sheets / "A01 - Old.svg", "sheet")
    layout = _write(layouts / "A01 - Old.svg", "layout")
    ifc_file, ifc_project = _new_ifc()
    _set_documentation_dirs(ifc_file, ifc_project, str(sheets), str(sheets), str(layouts))
    _add_sheet(
        ifc_file,
        "A01",
        "Old",
        [("SHEET", str(sheet_file)), ("LAYOUT", str(layout))],
    )
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    product.core.rename_sheet(product.Ifc, product.DrawingTool, _sheet(opened, "A01"), "A02", "New")

    assert not sheet_file.exists()
    assert not layout.exists()
    _assert_unchanged(sheets / "A02 - New.svg", "sheet")
    _assert_unchanged(layouts / "A02 - New.svg", "layout")


def test_rename_sheet_does_not_move_sheet_or_layout_from_outside_location(product, tmp_path: Path):
    project = tmp_path / "proj"
    sheets = project / "sheets"
    layouts = project / "layouts"
    sheets.mkdir(parents=True)
    layouts.mkdir(parents=True)
    sheet_file = _write(tmp_path / "outside" / "sheet.svg", "sheet")
    layout = _write(tmp_path / "outside" / "layout.svg", "layout")
    ifc_file, ifc_project = _new_ifc()
    _set_documentation_dirs(ifc_file, ifc_project, str(sheets), str(sheets), str(layouts))
    _add_sheet(
        ifc_file,
        "A01",
        "Old",
        [("SHEET", str(sheet_file)), ("LAYOUT", str(layout))],
    )
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    product.core.rename_sheet(product.Ifc, product.DrawingTool, _sheet(opened, "A01"), "A02", "New")

    _assert_unchanged(sheet_file, "sheet")
    _assert_unchanged(layout, "layout")
    _assert_marker_missing(project, "sheet")
    _assert_marker_missing(project, "layout")


def test_rename_sheet_does_not_move_into_directories_outside_project(product, tmp_path: Path):
    project = tmp_path / "proj"
    sheet_file = _write(project / "sheets" / "A01 - Old.svg", "sheet")
    layout = _write(project / "layouts" / "A01 - Old.svg", "layout")
    shared = tmp_path / "shared"
    shared.mkdir()
    ifc_file, ifc_project = _new_ifc()
    _set_documentation_dirs(ifc_file, ifc_project, str(shared), str(shared), str(shared))
    _add_sheet(
        ifc_file,
        "A01",
        "Old",
        [("SHEET", str(sheet_file)), ("LAYOUT", str(layout))],
    )
    opened = _open_ifc(product, ifc_file, project / "model.ifc")
    _preferences_inside(product, project)

    product.core.rename_sheet(product.Ifc, product.DrawingTool, _sheet(opened, "A01"), "A02", "New")

    _assert_marker_missing(shared, "sheet")
    _assert_marker_missing(shared, "layout")
    assert (sheet_file.is_file() and sheet_file.read_text() == "sheet") or any(
        candidate.is_file() and candidate.read_text() == "sheet" for candidate in project.rglob("*")
    )
    assert (layout.is_file() and layout.read_text() == "layout") or any(
        candidate.is_file() and candidate.read_text() == "layout" for candidate in project.rglob("*")
    )
