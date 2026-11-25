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

"""Opening an IFC must not load an untrusted sibling metadata blend.

With "Save non ifc data to metadata blend File" enabled, Load Project treats an
IfcDocumentInformation whose Scope is BLEND_METADATA as permission to open
``<ifc-stem><metadata suffix>`` via ``bpy.ops.wm.open_mainfile``. The marker and
the blend are supplied with the project. These tests fail while that happens.

A passing implementation does not open that blend unless this Bonsai install
recorded the path and the file bytes when it saved the metadata, and the bytes
at the moment of opening are still those bytes. Re-reading the path after the
check and opening whatever is there now still fails. ``bim.load_blend_metadata_and_ifc``
and Revert IFC Project share the open and are covered here. Load-autosave
recovery calls ``bim.load_project`` and has no separate blend open.
"""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Iterator
from pathlib import Path

import bpy
import ifcopenshell
import ifcopenshell.api.document
import ifcopenshell.api.root
import pytest

import bonsai.tool as tool
from test.bim.bootstrap import NewFile

pytestmark = pytest.mark.project

PROBE = "bonsai_untrusted_blend_probe"


def _ensure_addon() -> None:
    try:
        tool.Blender.get_addon_preferences()
    except (AttributeError, KeyError):
        import addon_utils

        if addon_utils.enable("bonsai", default_set=True, persistent=True) is None:
            raise RuntimeError("Bonsai is not enabled")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_ifc(
    path: Path,
    *,
    schema: str = "IFC4",
    scope: str | None = "BLEND_METADATA",
    location: str = "",
) -> None:
    ifc = ifcopenshell.file(schema=schema)
    ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject", name="Project")
    if scope is not None:
        document = ifcopenshell.api.document.add_information(ifc)
        # IFC2X3 IfcDocumentInformation has DocumentId and no Location.
        # IFC4 renamed DocumentId to Identification and added Location.
        # Load Project only reads Scope, which both schemas have.
        attributes = {
            "Name": "Blend Metadata",
            "Description": "References to blend metadata file for this IFC project",
            "Scope": scope,
        }
        if schema == "IFC2X3":
            attributes["DocumentId"] = "BLEND_METADATA"
        else:
            attributes["Identification"] = "BLEND_METADATA"
            attributes["Location"] = location
        ifcopenshell.api.document.edit_information(ifc, information=document, attributes=attributes)
    ifc.write(str(path))


def _save_probe_blend(path: Path, token: str) -> None:
    scene = bpy.context.scene
    scene[PROBE] = token
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
    del scene[PROBE]


def _metadata_path(ifc_path: Path, suffix: str) -> Path:
    name = ifc_path.name
    if name.lower().endswith(".ifc"):
        return ifc_path.with_name(name[:-4] + suffix)
    return ifc_path.with_name(name + suffix)


def _assert_blend_not_loaded(*blends: tuple[Path, str]) -> None:
    probe = bpy.context.scene.get(PROBE)
    opened = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    for path, token in blends:
        assert probe != token, f"session came from untrusted blend {path.name}"
        if opened is not None:
            assert opened != path.resolve(), f"open_mainfile left {path} as the session"


class _SwapBlendAfterCheck:
    """After a Python existence or content check, replace the blend on disk.

    ``LoadProject`` stats the sibling and later asks Blender to open that same
    path. The replacement is what a second lookup returns.
    """

    def __init__(self, metadata_path: Path, replacement: Path):
        self.metadata_path = metadata_path.resolve()
        self.replacement_bytes = replacement.read_bytes()
        self.original_bytes = self.metadata_path.read_bytes()
        self.swapped = False
        self._is_file = Path.is_file
        self._read_bytes = Path.read_bytes

    def _same(self, path: Path) -> bool:
        try:
            return Path(path).resolve() == self.metadata_path
        except OSError:
            return False

    def _swap(self) -> None:
        if self.swapped:
            return
        self.swapped = True
        self.metadata_path.write_bytes(self.replacement_bytes)

    def __enter__(self) -> _SwapBlendAfterCheck:
        swap = self

        def is_file(path: Path) -> bool:
            result = swap._is_file(path)
            if result and swap._same(path):
                swap._swap()
            return result

        def read_bytes(path: Path) -> bytes:
            data = swap._read_bytes(path)
            if swap._same(path):
                observed = data
                swap._swap()
                return observed
            return data

        # Assigned as plain functions so Path.is_file(self) receives the path.
        Path.is_file = is_file
        Path.read_bytes = read_bytes
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        Path.is_file = self._is_file
        Path.read_bytes = self._read_bytes
        if self.metadata_path.exists() and self._read_bytes(self.metadata_path) != self.original_bytes:
            self.metadata_path.write_bytes(self.original_bytes)


class TestUntrustedBlendMetadata(NewFile):
    @pytest.fixture(autouse=True)
    def metadata_preferences(self, setup) -> Iterator[None]:
        _ensure_addon()
        prefs = tool.Blender.get_addon_preferences()
        saved = (
            prefs.save_metadata_blend_file,
            prefs.metadata_blend_file_suffix,
            prefs.should_play_chaching_sound,
        )
        prefs.should_play_chaching_sound = False
        recent_path = tool.Project.get_recent_ifc_projects_path()
        recent_existed = recent_path.exists()
        recent_bytes = recent_path.read_bytes() if recent_existed else b""
        yield
        _ensure_addon()
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = saved[0]
        prefs.metadata_blend_file_suffix = saved[1]
        prefs.should_play_chaching_sound = saved[2]
        if recent_existed:
            recent_path.write_bytes(recent_bytes)
        elif recent_path.exists():
            recent_path.unlink()

    def _project(
        self,
        directory: Path,
        *,
        ifc_name: str = "model.ifc",
        schema: str = "IFC4",
        scope: str | None = "BLEND_METADATA",
        suffix: str | None = None,
        token: str = "sibling-blend",
        location: str | None = None,
        write_blend: bool = True,
    ) -> tuple[Path, Path]:
        prefs = tool.Blender.get_addon_preferences()
        if suffix is not None:
            prefs.metadata_blend_file_suffix = suffix
        else:
            suffix = prefs.metadata_blend_file_suffix
        ifc_path = directory / ifc_name
        blend_path = _metadata_path(ifc_path, suffix)
        decoy = directory / "location-target.blend"
        _write_ifc(
            ifc_path,
            schema=schema,
            scope=scope,
            location=location if location is not None else decoy.name,
        )
        if write_blend:
            _save_probe_blend(blend_path, token)
        return ifc_path, blend_path

    def test_preference_off_does_not_open_sibling_blend(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = False
        ifc_path, blend_path = self._project(tmp_path, token="pref-off")
        digest = _sha256(blend_path)

        bpy.ops.bim.load_project(filepath=str(ifc_path))

        _assert_blend_not_loaded((blend_path, "pref-off"))
        assert _sha256(blend_path) == digest

    def test_missing_marker_does_not_open_sibling_blend(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = True
        ifc_path, blend_path = self._project(tmp_path, scope=None, token="no-marker")

        bpy.ops.bim.load_project(filepath=str(ifc_path))

        _assert_blend_not_loaded((blend_path, "no-marker"))

    def test_other_document_scope_does_not_open_sibling_blend(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = True
        ifc_path, blend_path = self._project(tmp_path, scope="OTHER", token="other-scope")

        bpy.ops.bim.load_project(filepath=str(ifc_path))

        _assert_blend_not_loaded((blend_path, "other-scope"))

    def test_advanced_mode_does_not_open_sibling_blend(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = True
        ifc_path, blend_path = self._project(tmp_path, token="advanced")

        bpy.ops.bim.load_project(filepath=str(ifc_path), is_advanced=True)

        _assert_blend_not_loaded((blend_path, "advanced"))

    def test_existing_session_does_not_open_sibling_blend(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = True
        ifc_path, blend_path = self._project(tmp_path, token="same-session")

        bpy.ops.bim.load_project(filepath=str(ifc_path), should_start_fresh_session=False)

        _assert_blend_not_loaded((blend_path, "same-session"))

    def test_missing_sibling_does_not_open_document_location(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = True
        ifc_path, blend_path = self._project(tmp_path, write_blend=False, location="location-target.blend")
        decoy = tmp_path / "location-target.blend"
        _save_probe_blend(decoy, "location-decoy")
        assert not blend_path.exists()

        bpy.ops.bim.load_project(filepath=str(ifc_path))

        _assert_blend_not_loaded((decoy, "location-decoy"))
        assert not blend_path.exists()

    def test_load_project_does_not_open_untrusted_sibling_blend(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = True
        ifc_path, blend_path = self._project(tmp_path, token="untrusted-sibling")
        decoy = tmp_path / "not-the-sibling.blend"
        _save_probe_blend(decoy, "location-decoy")
        # Location names a different blend. The open must not follow it, and
        # must not open the conventional sibling either.
        ifc = ifcopenshell.open(str(ifc_path))
        document = next(doc for doc in ifc.by_type("IfcDocumentInformation") if doc.Scope == "BLEND_METADATA")
        document.Location = decoy.name
        ifc.write(str(ifc_path))
        sibling_digest = _sha256(blend_path)
        decoy_digest = _sha256(decoy)

        bpy.ops.bim.load_project(filepath=str(ifc_path))

        _assert_blend_not_loaded((blend_path, "untrusted-sibling"), (decoy, "location-decoy"))
        assert _sha256(blend_path) == sibling_digest
        assert _sha256(decoy) == decoy_digest
        assert blend_path.exists() and decoy.exists()

    def test_ifc2x3_marker_does_not_open_sibling_blend(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = True
        ifc_path, blend_path = self._project(tmp_path, schema="IFC2X3", token="ifc2x3-sibling")

        bpy.ops.bim.load_project(filepath=str(ifc_path))

        _assert_blend_not_loaded((blend_path, "ifc2x3-sibling"))

    def test_uppercase_ifc_suffix_does_not_open_sibling_blend(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = True
        ifc_path, blend_path = self._project(tmp_path, ifc_name="Model.IFC", token="uppercase-sibling")

        bpy.ops.bim.load_project(filepath=str(ifc_path))

        _assert_blend_not_loaded((blend_path, "uppercase-sibling"))

    def test_custom_metadata_suffix_does_not_open_sibling_blend(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = True
        ifc_path, blend_path = self._project(tmp_path, suffix=".session.blend", token="custom-suffix")

        bpy.ops.bim.load_project(filepath=str(ifc_path))

        _assert_blend_not_loaded((blend_path, "custom-suffix"))

    def test_ifczip_does_not_open_appended_suffix_blend(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = True
        inner = tmp_path / "inner.ifc"
        _write_ifc(inner, location="ignored.blend")
        ifc_path = tmp_path / "model.ifczip"
        with zipfile.ZipFile(ifc_path, "w") as archive:
            archive.write(inner, arcname="inner.ifc")
        # Names that do not end in .ifc append the suffix to the whole filename.
        blend_path = _metadata_path(ifc_path, prefs.metadata_blend_file_suffix)
        _save_probe_blend(blend_path, "ifczip-sibling")

        bpy.ops.bim.load_project(filepath=str(ifc_path))

        _assert_blend_not_loaded((blend_path, "ifczip-sibling"))

    def test_blend_replaced_after_existence_check_is_not_opened(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = True
        ifc_path, blend_path = self._project(tmp_path, token="checked-bytes")
        replacement = tmp_path / "replacement.blend"
        _save_probe_blend(replacement, "replaced-bytes")
        checked_digest = _sha256(blend_path)

        with _SwapBlendAfterCheck(blend_path, replacement):
            bpy.ops.bim.load_project(filepath=str(ifc_path))

        probe = bpy.context.scene.get(PROBE)
        assert probe != "replaced-bytes", "open used the blend that appeared after the existence check"
        if probe == "checked-bytes":
            # Opening the bytes that were checked is only acceptable when those
            # bytes are still the bytes that were opened. The path now points
            # at the replacement, so the session must not be that path.
            assert not bpy.data.filepath or Path(bpy.data.filepath).resolve() != blend_path.resolve()
            assert _sha256(replacement) != checked_digest

    def test_revert_project_does_not_open_untrusted_sibling_blend(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = True
        ifc_path, blend_path = self._project(tmp_path, token="revert-sibling")
        tool.Blender.get_bim_props().ifc_file = str(ifc_path)

        bpy.ops.bim.revert_project()

        _assert_blend_not_loaded((blend_path, "revert-sibling"))

    def test_load_blend_metadata_operator_does_not_open_untrusted_sibling(self, tmp_path: Path):
        prefs = tool.Blender.get_addon_preferences()
        prefs.save_metadata_blend_file = True
        ifc_path, blend_path = self._project(tmp_path, token="operator-sibling")
        digest = _sha256(blend_path)

        bpy.ops.bim.load_blend_metadata_and_ifc(filepath=str(ifc_path))

        _assert_blend_not_loaded((blend_path, "operator-sibling"))
        assert _sha256(blend_path) == digest
        assert blend_path.exists()
