# This file was generated with the assistance of an AI coding tool.
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

"""IFC-supplied network paths must not be touched before the user asks.

Opening a project and drawing the Sheets panel both feed Locations and
BBIM_Documentation folders from the IFC file into pathlib and os.path.
On Windows those calls are os.stat / CreateFileW on the UNC path. These
tests fail while that happens and pass once every such call is gone.
"""

import builtins
import io
import ntpath
import os
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from typing import Any

import bpy
import ifcopenshell
import ifcopenshell.api.document
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.util.element

import bonsai.tool as tool
from bonsai.bim.ifc import IfcStore
from bonsai.bim.module.drawing.data import SheetsData
from bonsai.bim.module.drawing.prop import get_titleblocks, update_titleblocks
from bonsai.bim.module.project.operator import LoadLink
from bonsai.tool.project import Project as subject
from test.bim.bootstrap import NewFile

# .invalid is a reserved non-routable name. The tests only need the string.
_HOST = "attacker.invalid"
_FORWARD_UNC = f"//{_HOST}/share/model.ifc"
_BACKSLASH_UNC = f"\\\\{_HOST}\\share\\model.ifc"
_EXTENDED_UNC = f"\\\\?\\UNC\\{_HOST}\\share\\model.ifc"
_FORWARD_DIR = f"//{_HOST}/share/titleblocks"
_BACKSLASH_DIR = f"\\\\{_HOST}\\share\\titleblocks"
_IDENTITY = ",".join(["1", "0", "0", "0", "0", "1", "0", "0", "0", "0", "1", "0", "0", "0", "0", "1"])

# Every os entry point pathlib and os.path use to look at a path. A refusal
# that still calls one of these on the UNC path is still the bug.
_FILESYSTEM_OPS = (
    "stat",
    "lstat",
    "open",
    "scandir",
    "listdir",
    "access",
    "unlink",
    "remove",
    "mkdir",
    "makedirs",
    "rename",
    "replace",
    "link",
    "symlink",
    "truncate",
    "readlink",
)


def _is_unc(path: str) -> bool:
    """Windows UNC, including //server/share and \\\\?\\UNC\\server\\share.

    ntpath.splitroot is the parser CPython uses for Windows paths. The drive
    component of a UNC path is the server and share.
    """
    drive, _root, _tail = ntpath.splitroot(path)
    return drive.startswith("\\\\") or drive.startswith("//")


def _unc_hits(hits: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(op, path) for op, path in hits if _is_unc(path)]


@contextmanager
def _recording_filesystem() -> Generator[list[tuple[str, str]], None, None]:
    hits: list[tuple[str, str]] = []
    saved: dict[str, Any] = {}

    def wrap(name: str, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(path: Any, *args: Any, **kwargs: Any) -> Any:
            try:
                shown = os.fspath(path)
            except (TypeError, ValueError):
                shown = path
            if isinstance(shown, bytes):
                shown = os.fsdecode(shown)
            if isinstance(shown, str):
                hits.append((name, shown))
            return original(path, *args, **kwargs)

        return wrapped

    for name in _FILESYSTEM_OPS:
        original = getattr(os, name, None)
        if original is None:
            continue
        saved[name] = original
        setattr(os, name, wrap(name, original))
    # pathlib.Path.open and the cache reader call io.open. The _io module
    # does not go through the Python os.open wrapper, so record io.open too.
    original_io_open = io.open
    io.open = wrap("open", original_io_open)
    builtins.open = io.open
    try:
        yield hits
    finally:
        for name, original in saved.items():
            setattr(os, name, original)
        io.open = original_io_open
        builtins.open = original_io_open


@contextmanager
def _windows_path_parsing() -> Generator[None, None, None]:
    """Parse paths the way Blender's Python does on Windows.

    pathlib.WindowsPath cannot be constructed when os.name != 'nt'. The class
    below is PureWindowsPath (ntpath) plus the filesystem methods Path defines,
    which call os.stat. On Windows the real Path is already that combination.
    """
    if os.name == "nt":
        yield
        return

    from pathlib import Path as StdPath

    import bonsai.tool.ifc as ifc_mod

    class _WinPath(PureWindowsPath):
        stat = StdPath.stat
        exists = StdPath.exists
        is_file = StdPath.is_file
        is_dir = StdPath.is_dir
        open = StdPath.open

    saved_path = ifc_mod.Path
    saved_normpath = ifc_mod.os.path.normpath
    ifc_mod.Path = _WinPath
    ifc_mod.os.path.normpath = ntpath.normpath
    try:
        yield
    finally:
        ifc_mod.Path = saved_path
        ifc_mod.os.path.normpath = saved_normpath


def _write_and_reopen(ifc: ifcopenshell.file) -> tuple[Path, ifcopenshell.file]:
    handle = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
    handle.close()
    path = Path(handle.name)
    ifc.write(path)
    return path, ifcopenshell.open(path)


def _activate(path: Path, ifc: ifcopenshell.file) -> None:
    tool.Ifc.set(ifc)
    tool.Ifc.set_path(str(path))
    IfcStore.set_path(str(path))


def _linked_model_file(location: str, identification: str = "") -> tuple[Path, ifcopenshell.file]:
    ifc = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(ifc, "IfcProject")
    document = ifcopenshell.api.document.add_information(ifc)
    document.Scope = "LINKED_MODEL"
    reference = ifcopenshell.api.document.add_reference(ifc, information=document)
    reference.Location = location
    reference.Identification = identification
    return _write_and_reopen(ifc)


def _titleblock_file(location: str) -> tuple[Path, ifcopenshell.file]:
    ifc = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.root.create_entity(ifc, "IfcProject")
    pset = ifcopenshell.api.pset.add_pset(ifc, product=project, name="BBIM_Documentation")
    ifcopenshell.api.pset.edit_pset(ifc, pset=pset, properties={"TitleblocksDir": location})
    return _write_and_reopen(ifc)


def _assert_no_unc(hits: list[tuple[str, str]]) -> None:
    bad = _unc_hits(hits)
    assert not bad, f"filesystem operation on an IFC-supplied network path: {bad}"


class TestUntrustedNetworkPaths(NewFile):
    def test_import_does_not_probe_forward_unc_linked_model(self) -> None:
        path, ifc = _linked_model_file(_FORWARD_UNC)
        try:
            _activate(path, ifc)
            parsed = ifc.by_type("IfcDocumentReference")[0].Location
            assert _is_unc(parsed)
            with _recording_filesystem() as hits:
                subject.load_linked_models_from_ifc()
            _assert_no_unc(hits)
        finally:
            path.unlink(missing_ok=True)

    def test_import_does_not_probe_backslash_unc_linked_model(self) -> None:
        path, ifc = _linked_model_file(_BACKSLASH_UNC)
        try:
            _activate(path, ifc)
            parsed = ifc.by_type("IfcDocumentReference")[0].Location
            assert parsed.startswith("\\\\")
            with _windows_path_parsing():
                with _recording_filesystem() as hits:
                    subject.load_linked_models_from_ifc()
            _assert_no_unc(hits)
        finally:
            path.unlink(missing_ok=True)

    def test_import_does_not_probe_extended_unc_linked_model(self) -> None:
        path, ifc = _linked_model_file(_EXTENDED_UNC)
        try:
            _activate(path, ifc)
            with _windows_path_parsing():
                with _recording_filesystem() as hits:
                    subject.load_linked_models_from_ifc()
            _assert_no_unc(hits)
        finally:
            path.unlink(missing_ok=True)

    def test_import_does_not_probe_unc_when_identification_is_a_matrix(self) -> None:
        # Identification is read before the cache stat. A matrix must not
        # become a reason to touch the UNC sibling.
        path, ifc = _linked_model_file(_FORWARD_UNC, identification=_IDENTITY)
        try:
            _activate(path, ifc)
            with _recording_filesystem() as hits:
                subject.load_linked_models_from_ifc()
            _assert_no_unc(hits)
        finally:
            path.unlink(missing_ok=True)

    def test_relative_linked_model_is_not_a_network_path(self) -> None:
        path, ifc = _linked_model_file("sibling.ifc")
        try:
            _activate(path, ifc)
            with _recording_filesystem() as hits:
                subject.load_linked_models_from_ifc()
            _assert_no_unc(hits)
            props = tool.Project.get_project_props()
            assert len(props.links) == 1
            assert props.links[0].name == "sibling.ifc"
        finally:
            path.unlink(missing_ok=True)

    def test_sheets_panel_load_does_not_probe_unc_titleblocks_dir(self) -> None:
        path, ifc = _titleblock_file(_FORWARD_DIR)
        try:
            _activate(path, ifc)
            stored = ifcopenshell.util.element.get_pset(
                ifc.by_type("IfcProject")[0], "BBIM_Documentation", "TitleblocksDir"
            )
            assert stored == _FORWARD_DIR
            SheetsData.is_loaded = False
            with _recording_filesystem() as hits:
                # BIM_PT_sheets.draw calls SheetsData.load before it draws.
                SheetsData.load()
            _assert_no_unc(hits)
        finally:
            path.unlink(missing_ok=True)

    def test_sheets_panel_load_does_not_probe_backslash_titleblocks_dir(self) -> None:
        path, ifc = _titleblock_file(_BACKSLASH_DIR)
        try:
            _activate(path, ifc)
            SheetsData.is_loaded = False
            with _windows_path_parsing():
                with _recording_filesystem() as hits:
                    SheetsData.load()
            _assert_no_unc(hits)
        finally:
            path.unlink(missing_ok=True)

    def test_titleblock_enum_callbacks_do_not_probe_unc_dir(self) -> None:
        path, ifc = _titleblock_file(_FORWARD_DIR)
        try:
            _activate(path, ifc)
            SheetsData.is_loaded = False
            with _recording_filesystem() as hits:
                get_titleblocks(None, bpy.context)
                SheetsData.is_loaded = False
                update_titleblocks(None, bpy.context)
            _assert_no_unc(hits)
        finally:
            path.unlink(missing_ok=True)

    def test_explicit_link_load_does_not_probe_unc(self) -> None:
        path, ifc = _linked_model_file(_FORWARD_UNC)
        try:
            _activate(path, ifc)
            props = tool.Project.get_project_props()
            props.links.clear()
            link = props.links.add()
            link.filepath = _FORWARD_UNC
            link.query = ""

            class _Operator:
                link_index = 0
                query = ""

                def report(self, _level: set[str], _message: str) -> None:
                    return None

            with _recording_filesystem() as hits:
                LoadLink._execute(_Operator(), bpy.context)
            _assert_no_unc(hits)
        finally:
            path.unlink(missing_ok=True)

    def test_link_matrix_does_not_open_unc_cache(self) -> None:
        path, ifc = _linked_model_file(_BACKSLASH_UNC)
        try:
            _activate(path, ifc)
            props = tool.Project.get_project_props()
            props.links.clear()
            link = props.links.add()
            link.filepath = _BACKSLASH_UNC
            link.ifc_definition_id = ifc.by_type("IfcDocumentReference")[0].id()
            with _windows_path_parsing():
                with _recording_filesystem() as hits:
                    try:
                        subject.calculate_link_matrix(link)
                    except OSError:
                        pass
            _assert_no_unc(hits)
        finally:
            path.unlink(missing_ok=True)
