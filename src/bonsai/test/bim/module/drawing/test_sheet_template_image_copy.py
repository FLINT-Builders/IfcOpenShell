# This file was generated with the assistance of an AI coding tool.
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

"""Sheet builds must not copy arbitrary files or write outside the project.

Create Sheets and Open Sheet both call ``SheetBuilder.build``. That copies every
image linked from an embedded layout, titleblock, drawing, or schedule SVG into
the sheets directory, and the sheets directory comes from ``BBIM_Documentation``
``SheetsDir`` on the project. These tests drive that build. They fail while a
link or directory can read or write outside the project, or while a non-image
file is copied.

Run this file under Blender (its Python needs pytest and the Bonsai
dependencies). From the repository root::

    blender --background --python-exit-code 1 --python <this-file>
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
_NS = f'xmlns="{SVG_NS}" xmlns:xlink="{XLINK_NS}"'
_REPO_PACKAGES = (
    "bonsai",
    "bcf",
    "bsdd",
    "ifc4d",
    "ifc5d",
    "ifccityjson",
    "ifcclash",
    "ifccsv",
    "ifcdiff",
    "ifcfm",
    "ifcpatch",
    "ifctester",
)


def _bootstrap() -> None:
    """Import the sheet builder from this checkout when Blender has not registered Bonsai."""
    src = Path(__file__).resolve().parents[5]
    for name in _REPO_PACKAGES:
        entry = src / name if name != "bonsai" else src / "bonsai"
        # ``src/bonsai`` is the distribution directory that contains the ``bonsai`` package.
        text = str(entry)
        if text not in sys.path:
            sys.path.insert(0, text)

    import bonsai

    if not getattr(bonsai, "REGISTERED_BBIM_PACKAGE", None):
        bonsai.REGISTERED_BBIM_PACKAGE = "bonsai"
    # Schema import asks for addon preferences unless registration is in progress.
    # Sheet building does not consult that flag.
    previous = bonsai.is_registering
    bonsai.is_registering = lambda: True
    try:
        global sheeter, tool, IfcStore
        import bonsai.bim.module.drawing.sheeter as sheeter
        import bonsai.tool as tool
        from bonsai.bim.ifc import IfcStore
    finally:
        bonsai.is_registering = previous

    try:
        tool.Blender.get_addon_preferences().doc.sheets_dir
    except Exception:
        # Same default as ``DocPreferences.sheets_dir`` when the IFC value is empty.
        # ``SheetsDir`` is still read from the IFC before this fallback is used.
        class _Doc:
            sheets_dir = os.path.join("sheets") + os.sep

        class _Prefs:
            doc = _Doc()

        def _preferences(cls):
            return _Prefs()

        tool.Blender.get_addon_preferences = classmethod(_preferences)


_bootstrap()


def _svg(body: str, *, width: str = "10", height: str = "10") -> str:
    return f'<?xml version="1.0"?>\n<svg {_NS} width="{width}" height="{height}">{body}</svg>\n'


def _image(href: str, data_type: str | None = None) -> str:
    kind = f' data-type="{data_type}"' if data_type else ""
    return f'<image{kind} xlink:href="{href}" x="0" y="0" width="10" height="10"/>'


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _escapes(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
    except ValueError:
        return True
    return False


class _Writes:
    def __init__(self, project: Path):
        self.project = project
        self.events: list[tuple] = []
        self._makedirs = sheeter.os.makedirs
        self._copy = sheeter.shutil.copy
        self._had_open = "open" in sheeter.__dict__

    def __enter__(self):
        def makedirs(path, *args, **kwargs):
            self.events.append(("makedirs", Path(path)))
            return self._makedirs(path, *args, **kwargs)

        def copy(src, dst, *args, **kwargs):
            self.events.append(("copy", Path(src), Path(dst)))
            return self._copy(src, dst, *args, **kwargs)

        def watched_open(file, mode="r", *args, **kwargs):
            if any(flag in str(mode) for flag in ("w", "a", "x", "+")) and isinstance(file, (str, os.PathLike)):
                self.events.append(("open", Path(file)))
            return open(file, mode, *args, **kwargs)

        sheeter.os.makedirs = makedirs
        sheeter.shutil.copy = copy
        sheeter.open = watched_open
        return self

    def __exit__(self, exc_type, exc, tb):
        sheeter.os.makedirs = self._makedirs
        sheeter.shutil.copy = self._copy
        if not self._had_open:
            sheeter.__dict__.pop("open", None)
        return False

    def assert_inside_project(self) -> None:
        outside = []
        for event in self.events:
            for item in event[1:]:
                if isinstance(item, Path) and _escapes(item, self.project):
                    outside.append(f"{event[0]} {item}")
        assert not outside, "sheet build touched paths outside the project: " + "; ".join(outside)


def _load(project: Path, sheets_dir: str):
    import ifcopenshell.api.document
    import ifcopenshell.api.pset
    import ifcopenshell.api.root

    ifc_path = project / "project.ifc"
    ifc = ifcopenshell.file(schema="IFC4")
    ifc_project = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject", name="Project")
    pset = ifcopenshell.api.pset.add_pset(ifc, product=ifc_project, name="BBIM_Documentation")
    ifcopenshell.api.pset.edit_pset(ifc, pset=pset, properties={"SheetsDir": sheets_dir})
    sheet = ifcopenshell.api.document.add_information(ifc)
    layout_ref = ifcopenshell.api.document.add_reference(ifc, information=sheet)
    title_ref = ifcopenshell.api.document.add_reference(ifc, information=sheet)
    ifcopenshell.api.document.edit_information(
        ifc,
        information=sheet,
        attributes={"Identification": "A1", "Name": "Plan", "Scope": "SHEET"},
    )
    ifcopenshell.api.document.edit_reference(
        ifc,
        reference=layout_ref,
        attributes={"Location": "layouts/A1.svg", "Description": "LAYOUT"},
    )
    ifcopenshell.api.document.edit_reference(
        ifc,
        reference=title_ref,
        attributes={"Location": "titleblocks/tb.svg", "Description": "TITLEBLOCK"},
    )
    ifc.write(str(ifc_path))
    IfcStore.file = ifc
    IfcStore.path = str(ifc_path.resolve())
    return ifc, sheet


def _layout(project: Path, extra: str = "") -> None:
    body = f'<g data-type="titleblock">{_image("../titleblocks/tb.svg")}</g>{extra}'
    _write(project / "layouts" / "A1.svg", _svg(body, width="100", height="100"))


def _titleblock(project: Path, images: list[str]) -> None:
    _write(project / "titleblocks" / "tb.svg", _svg("".join(_image(href) for href in images)))


def _build(project: Path, sheet):
    # The product gate only checks that the layout and titleblock files exist.
    tool.Drawing.validate_sheet_files(sheet)
    with _Writes(project) as watched:
        sheeter.SheetBuilder().build(sheet)
    return watched


def _files_with_bytes(root: Path, payload: bytes) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in root.rglob("*") if path.is_file() and path.read_bytes() == payload]


def test_relative_image_link_cannot_leave_the_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    secret = tmp_path / "private" / "private-marker.txt"
    secret.parent.mkdir()
    secret.write_bytes(b"PRIVATE_MARKER")
    _ifc, sheet = _load(project, "sheets")
    logo = project / "titleblocks" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"PNGOK")
    href = Path(os.path.relpath(secret, project / "titleblocks")).as_posix()
    _titleblock(project, ["sub/../logo.png", href])
    _layout(project)
    watched = _build(project, sheet)
    watched.assert_inside_project()
    sheets = project / "sheets"
    assert (sheets / "logo.png").read_bytes() == b"PNGOK"
    assert _files_with_bytes(sheets, b"PRIVATE_MARKER") == []
    assert secret.read_bytes() == b"PRIVATE_MARKER"


def test_absolute_image_link_inside_project_is_not_copied(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _ifc, sheet = _load(project, "sheets")
    (project / "titleblocks").mkdir()
    (project / "titleblocks" / "logo.png").write_bytes(b"PNGOK")
    (project / "titleblocks" / "abs.png").write_bytes(b"ABS")
    absolute = (project / "titleblocks" / "abs.png").resolve().as_posix()
    _titleblock(project, ["logo.png", absolute])
    _layout(project)
    watched = _build(project, sheet)
    watched.assert_inside_project()
    assert (project / "sheets" / "logo.png").read_bytes() == b"PNGOK"
    assert _files_with_bytes(project / "sheets", b"ABS") == []


def test_absolute_image_link_outside_project_is_not_copied(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    secret = tmp_path / "private" / "private-marker.txt"
    secret.parent.mkdir()
    secret.write_bytes(b"PRIVATE_MARKER")
    _ifc, sheet = _load(project, "sheets")
    (project / "titleblocks").mkdir()
    (project / "titleblocks" / "logo.png").write_bytes(b"PNGOK")
    _titleblock(project, ["logo.png", secret.resolve().as_posix()])
    _layout(project)
    watched = _build(project, sheet)
    watched.assert_inside_project()
    assert (project / "sheets" / "logo.png").read_bytes() == b"PNGOK"
    assert _files_with_bytes(project / "sheets", b"PRIVATE_MARKER") == []


def test_symlink_in_the_template_is_not_followed_outside(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    secret = tmp_path / "private" / "private-marker.txt"
    secret.parent.mkdir()
    secret.write_bytes(b"PRIVATE_MARKER")
    _ifc, sheet = _load(project, "sheets")
    titleblocks = project / "titleblocks"
    titleblocks.mkdir()
    os.symlink(secret, titleblocks / "logo-link.png")
    (titleblocks / "logo.png").write_bytes(b"PNGOK")
    _titleblock(project, ["logo.png", "logo-link.png"])
    _layout(project)
    watched = _build(project, sheet)
    watched.assert_inside_project()
    assert (project / "sheets" / "logo.png").read_bytes() == b"PNGOK"
    assert _files_with_bytes(project / "sheets", b"PRIVATE_MARKER") == []


def test_non_image_file_in_the_template_is_not_copied(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _ifc, sheet = _load(project, "sheets")
    titleblocks = project / "titleblocks"
    titleblocks.mkdir()
    (titleblocks / "logo.png").write_bytes(b"PNGOK")
    (titleblocks / "marker.desktop").write_bytes(b"PLANTED_FILE")
    _titleblock(project, ["logo.png", "marker.desktop"])
    _layout(project)
    watched = _build(project, sheet)
    watched.assert_inside_project()
    assert (project / "sheets" / "logo.png").read_bytes() == b"PNGOK"
    assert _files_with_bytes(project / "sheets", b"PLANTED_FILE") == []
    assert list((project / "sheets").glob("*.desktop")) == []


def _assert_sheets_stay_inside(project: Path, sheet, outside: Path) -> None:
    before = sorted(path.relative_to(outside) for path in outside.rglob("*")) if outside.exists() else []
    watched = _build(project, sheet)
    watched.assert_inside_project()
    after = sorted(path.relative_to(outside) for path in outside.rglob("*")) if outside.exists() else []
    assert after == before


def test_relative_sheets_dir_cannot_write_outside_the_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    _ifc, sheet = _load(project, "../outside/autostart")
    titleblocks = project / "titleblocks"
    titleblocks.mkdir()
    (titleblocks / "logo.png").write_bytes(b"PNGOK")
    (titleblocks / "marker.desktop").write_bytes(b"PLANTED_FILE")
    _titleblock(project, ["logo.png", "marker.desktop"])
    _layout(project)
    _assert_sheets_stay_inside(project, sheet, outside)
    # A refusal may skip the in-project copy. A successful confined build must keep the image.
    if (project / "sheets").exists():
        assert (project / "sheets" / "logo.png").read_bytes() == b"PNGOK"


def test_absolute_sheets_dir_cannot_write_outside_the_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "abs-outside"
    _ifc, sheet = _load(project, str(outside / "autostart"))
    titleblocks = project / "titleblocks"
    titleblocks.mkdir()
    (titleblocks / "logo.png").write_bytes(b"PNGOK")
    (titleblocks / "marker.desktop").write_bytes(b"PLANTED_FILE")
    _titleblock(project, ["logo.png", "marker.desktop"])
    _layout(project)
    _assert_sheets_stay_inside(project, sheet, outside)


def test_symlinked_sheets_dir_cannot_write_outside_the_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, project / "sheets", target_is_directory=True)
    _ifc, sheet = _load(project, "sheets")
    titleblocks = project / "titleblocks"
    titleblocks.mkdir()
    (titleblocks / "logo.png").write_bytes(b"PNGOK")
    _titleblock(project, ["logo.png"])
    _layout(project)
    _assert_sheets_stay_inside(project, sheet, outside)
    assert (project / "sheets").is_symlink()
    assert list(outside.iterdir()) == []


def _document_reference(ifc, information):
    import ifcopenshell.api.document

    return ifcopenshell.api.document.add_reference(ifc, information=information)


def test_drawing_foreground_and_view_title_cannot_escape(tmp_path: Path) -> None:
    import ifcopenshell.api.root

    project = tmp_path / "project"
    project.mkdir()
    foreground_secret = tmp_path / "private" / "foreground.txt"
    view_secret = tmp_path / "private" / "view-title.txt"
    foreground_secret.parent.mkdir()
    foreground_secret.write_bytes(b"FOREGROUND_MARKER")
    view_secret.write_bytes(b"VIEW_MARKER")
    ifc, sheet = _load(project, "sheets")
    (project / "titleblocks").mkdir()
    (project / "titleblocks" / "logo.png").write_bytes(b"PNGOK")
    _titleblock(project, ["logo.png"])
    drawings = project / "drawings"
    drawings.mkdir()
    (drawings / "ink.png").write_bytes(b"INK")
    _write(
        drawings / "d.svg",
        _svg(
            "<defs><style>.x{}</style></defs>"
            + _image(Path(os.path.relpath(foreground_secret, drawings)).as_posix())
            + _image("ink.png")
        ),
    )
    _write(
        drawings / "title.svg",
        _svg(_image(Path(os.path.relpath(view_secret, drawings)).as_posix())),
    )
    drawing = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcAnnotation", name="Drawing")
    reference = _document_reference(ifc, sheet)
    extra = (
        f'<g data-type="drawing" data-id="{reference.id()}" data-drawing="{drawing.GlobalId}">'
        f"{_image('../drawings/d.svg', 'foreground')}"
        f"{_image('../drawings/title.svg', 'view-title')}"
        "</g>"
    )
    _layout(project, extra)
    watched = _build(project, sheet)
    watched.assert_inside_project()
    sheets = project / "sheets"
    assert (sheets / "ink.png").read_bytes() == b"INK"
    assert _files_with_bytes(sheets, b"FOREGROUND_MARKER") == []
    assert _files_with_bytes(sheets, b"VIEW_MARKER") == []


def test_schedule_and_reference_images_cannot_escape(tmp_path: Path) -> None:
    import ifcopenshell.api.document

    project = tmp_path / "project"
    project.mkdir()
    schedule_secret = tmp_path / "private" / "schedule.txt"
    reference_secret = tmp_path / "private" / "reference.txt"
    schedule_secret.parent.mkdir()
    schedule_secret.write_bytes(b"SCHEDULE_MARKER")
    reference_secret.write_bytes(b"REFERENCE_MARKER")
    ifc, sheet = _load(project, "sheets")
    (project / "titleblocks").mkdir()
    (project / "titleblocks" / "logo.png").write_bytes(b"PNGOK")
    _titleblock(project, ["logo.png"])
    schedules = project / "schedules"
    schedules.mkdir()
    (schedules / "cell.png").write_bytes(b"CELL")
    _write(
        schedules / "s.svg",
        _svg(_image(schedule_secret.resolve().as_posix()) + _image("cell.png")),
    )
    _write(schedules / "ref.svg", _svg("<rect width='1' height='1'/>"))
    _write(schedules / "ref-title.svg", _svg(_image(reference_secret.resolve().as_posix())))
    schedule = ifcopenshell.api.document.add_information(ifc)
    ifcopenshell.api.document.edit_information(
        ifc,
        information=schedule,
        attributes={"Identification": "S1", "Name": "Sched", "Scope": "SCHEDULE"},
    )
    schedule_ref = _document_reference(ifc, schedule)
    extra = (
        f'<g data-type="schedule" data-id="{schedule_ref.id()}" data-document="{schedule.id()}">'
        f"{_image('../schedules/s.svg', 'content')}"
        "</g>"
        f'<g data-type="reference" data-id="{schedule_ref.id()}" data-document="{schedule.id()}">'
        f"{_image('../schedules/ref.svg', 'content')}"
        f"{_image('../schedules/ref-title.svg', 'view-title')}"
        "</g>"
    )
    _layout(project, extra)
    watched = _build(project, sheet)
    watched.assert_inside_project()
    sheets = project / "sheets"
    assert (sheets / "cell.png").read_bytes() == b"CELL"
    assert _files_with_bytes(sheets, b"SCHEDULE_MARKER") == []
    assert _files_with_bytes(sheets, b"REFERENCE_MARKER") == []


def test_paths_are_classified_with_realpath_not_a_second_lexical_lookup(tmp_path: Path) -> None:
    """A confinement check that repeats a lexical lookup still follows this symlink."""
    project = tmp_path / "project"
    project.mkdir()
    secret = tmp_path / "private" / "private-marker.txt"
    secret.parent.mkdir()
    secret.write_bytes(b"PRIVATE_MARKER")
    link_dir = project / "titleblocks" / "nested"
    link_dir.parent.mkdir(parents=True)
    os.symlink(tmp_path / "private", link_dir, target_is_directory=True)
    _ifc, sheet = _load(project, "sheets")
    (project / "titleblocks" / "logo.png").write_bytes(b"PNGOK")
    _titleblock(project, ["logo.png", "nested/private-marker.txt"])
    _layout(project)
    watched = _build(project, sheet)
    watched.assert_inside_project()
    assert (project / "sheets" / "logo.png").read_bytes() == b"PNGOK"
    assert _files_with_bytes(project / "sheets", b"PRIVATE_MARKER") == []


def test_embedded_svg_namespace_is_the_one_the_builder_parses() -> None:
    # Keeps the fixtures aligned with the tags ``parse_embedded_svg`` searches for.
    root = ET.fromstring(_svg(_image("logo.png")))
    images = root.findall(f"{{{SVG_NS}}}image")
    assert len(images) == 1
    assert images[0].attrib[f"{{{XLINK_NS}}}href"] == "logo.png"


if __name__ == "__main__":
    here = str(Path(__file__).resolve().parent)
    raise SystemExit(
        pytest.main(
            [
                "-p",
                "no:pytest-blender",
                "-p",
                "no:pytest-bdd",
                "-o",
                "addopts=",
                "-o",
                "cache_dir=/tmp/sheet-image-pytest-cache",
                "--noconftest",
                "--confcutdir",
                here,
                __file__,
            ]
        )
    )
