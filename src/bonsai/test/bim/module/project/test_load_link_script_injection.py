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

"""Scene strings pasted into the Load Link background script must not run.

LoadLink.link_ifc writes a temporary Python file and launches Blender with
--python. Georeference offsets, false origin, project north, and the linked
file path are interpolated into that source. These tests open a .blend that
already holds the strings (auto-run stays off), then call the real operators.
Each payload closes the generated quotes and writes a marker file. The marker
must not appear. The tests fail while the strings are still executed.
"""

import sys
from pathlib import Path

import addon_utils
import bpy
import ifcopenshell
import ifcopenshell.api.root
import pytest


def _enable_addon_preferences() -> None:
    """Register Bonsai before importing it.

    Importing bonsai.bim outside register() loads pset templates and reads
    addon preferences. ``--addons`` enables the module without adding that
    preferences entry; ``default_set=True`` creates it, which ``load_post``
    requires.
    """
    if "bonsai" not in bpy.context.preferences.addons:
        addon_utils.enable("bonsai", default_set=True, persistent=True)


_enable_addon_preferences()

import bonsai.bim.handler
import bonsai.tool as tool
from test.bim.bootstrap import NewFile

pytestmark = pytest.mark.project

# Quoted assignments in link_ifc. false_origin_mode is an enum and is covered
# separately; distance_limit and has_blender_offset are not strings.
_GEOREFERENCE_FIELDS = (
    "blender_offset_x",
    "blender_offset_y",
    "blender_offset_z",
    "blender_x_axis_abscissa",
    "blender_x_axis_ordinate",
)
_PROJECT_FIELDS = (
    "false_origin",
    "project_north",
)


def _quoted_breakout(marker: Path) -> str:
    """Close `= "<value>"`, write ``marker``, and reopen a string literal.

    The continuation stays at the assignment's indent so the rest of the
    generated function remains valid Python. Braces are avoided so the host
    f-string builds the script instead of raising while formatting it.
    """
    return '0"\n    open(%r, "w").write("executed")\n    ignored = "' % str(marker)


def _filepath_breakout_name(marker: Path) -> str:
    """Filename ending in ``.ifc`` that runs while the raw-string argument is evaluated.

    link_ifc embeds the path as ``filepath=r"<path>"``. This closes that raw
    string, writes ``marker`` because the empty string is false, and opens a
    second raw string that the template's closing quote terminates. The cache
    path only changes the suffix, so the same text is valid in both insertions.
    """
    statement = "open(%r, 'w').write('executed')" % str(marker)
    return '" and %s or r"ignored.ifc' % statement


def _run_operator(operator) -> None:
    """Operator failures after the background script still leave its marker."""
    try:
        operator()
    except RuntimeError:
        pass


def _write_linked_ifc(path: Path) -> None:
    ifc = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
    path.parent.mkdir(parents=True, exist_ok=True)
    ifc.write(str(path))
    cache = path.with_suffix(".ifc.cache.blend")
    cache.unlink(missing_ok=True)


def _remember_load_post(scene) -> None:
    before = _scene_strings(scene)
    try:
        bonsai.bim.handler.load_post(scene)
    except Exception:
        pass
    assert _scene_strings(scene) == before


def _scene_strings(scene) -> dict[str, str]:
    gprops = scene.BIMGeoreferenceProperties
    pprops = scene.BIMProjectProperties
    values = {name: getattr(gprops, name) for name in _GEOREFERENCE_FIELDS}
    values.update({name: getattr(pprops, name) for name in _PROJECT_FIELDS})
    return values


def _open_saved_blend(blend: Path) -> None:
    # use_scripts=False is Blender's auto-run switch for this open. The payload
    # lives in scene properties, not in a text block.
    bpy.ops.wm.open_mainfile(filepath=str(blend), use_scripts=False)


class TestLoadLinkScriptInjection(NewFile):
    def _save_armed_blend(self, blend: Path, ifc_path: Path, assignments: dict[str, str]) -> None:
        gprops = tool.Georeference.get_georeference_props()
        pprops = tool.Project.get_project_props()
        for name, value in assignments.items():
            if name in _GEOREFERENCE_FIELDS:
                setattr(gprops, name, value)
            else:
                setattr(pprops, name, value)
        link = pprops.links.add()
        link.name = ifc_path.name
        link.filepath = str(ifc_path)
        link.is_loaded = False
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))

    def test_load_link_does_not_execute_scene_strings(self, tmp_path):
        markers = {name: tmp_path / f"{name}.marker" for name in (*_GEOREFERENCE_FIELDS, *_PROJECT_FIELDS)}
        for marker in markers.values():
            marker.unlink(missing_ok=True)
        ifc_path = tmp_path / "linked.ifc"
        _write_linked_ifc(ifc_path)
        assignments = {name: _quoted_breakout(marker) for name, marker in markers.items()}
        blend = tmp_path / "host.blend"
        self._save_armed_blend(blend, ifc_path, assignments)

        _open_saved_blend(blend)
        scene = bpy.context.scene
        restored = _scene_strings(scene)
        assert restored == assignments
        _remember_load_post(scene)
        assert not ifc_path.with_suffix(".ifc.cache.blend").exists()

        _run_operator(lambda: bpy.ops.bim.load_link(link_index=0, use_cache=True))

        executed = sorted(name for name, marker in markers.items() if marker.exists())
        assert executed == []

    def test_reload_link_does_not_execute_scene_strings(self, tmp_path):
        marker = tmp_path / "reload.marker"
        marker.unlink(missing_ok=True)
        ifc_path = tmp_path / "linked.ifc"
        _write_linked_ifc(ifc_path)
        # A cache file forces ReloadLink's use_cache=False path to delete it
        # and build a new background script from the current scene strings.
        ifc_path.with_suffix(".ifc.cache.blend").write_bytes(b"BLENDER")
        blend = tmp_path / "host.blend"
        self._save_armed_blend(
            blend,
            ifc_path,
            {"blender_offset_x": _quoted_breakout(marker)},
        )

        _open_saved_blend(blend)
        scene = bpy.context.scene
        assert scene.BIMGeoreferenceProperties.blender_offset_x == _quoted_breakout(marker)
        _remember_load_post(scene)

        _run_operator(lambda: bpy.ops.bim.reload_link("EXEC_DEFAULT", link_index=0))

        assert not marker.exists()

    @pytest.mark.skipif(sys.platform == "win32", reason="The linked path contains a newline and a quote")
    def test_linked_filepath_is_not_executed(self, tmp_path):
        marker = tmp_path / "filepath.marker"
        marker.unlink(missing_ok=True)
        ifc_path = tmp_path / _filepath_breakout_name(marker)
        _write_linked_ifc(ifc_path)
        blend = tmp_path / "host.blend"
        self._save_armed_blend(blend, ifc_path, {})

        _open_saved_blend(blend)
        reloaded = Path(bpy.context.scene.BIMProjectProperties.links[0].filepath)
        assert reloaded == ifc_path
        assert reloaded.exists()
        assert not reloaded.with_suffix(".ifc.cache.blend").exists()
        _remember_load_post(bpy.context.scene)

        _run_operator(lambda: bpy.ops.bim.load_link(link_index=0, use_cache=True))

        assert not marker.exists()

    def test_selector_query_is_not_executed(self, tmp_path):
        marker = tmp_path / "query.marker"
        marker.unlink(missing_ok=True)
        ifc_path = tmp_path / "linked.ifc"
        _write_linked_ifc(ifc_path)
        blend = tmp_path / "host.blend"
        self._save_armed_blend(blend, ifc_path, {})
        _open_saved_blend(blend)
        link = bpy.context.scene.BIMProjectProperties.links[0]
        # Same breakout shape. link_ifc passes this through repr(), so it must
        # stay data even if the other fields are fixed by a different method.
        link.query = _quoted_breakout(marker)
        _remember_load_post(bpy.context.scene)

        _run_operator(lambda: bpy.ops.bim.load_link(link_index=0, use_cache=True, query=link.query))

        assert not marker.exists()

    def test_false_origin_mode_rejects_breakout(self):
        pprops = tool.Project.get_project_props()
        pprops.false_origin_mode = "MANUAL"
        payload = _quoted_breakout(Path("/tmp/false-origin-mode-not-written"))
        with pytest.raises(TypeError):
            pprops.false_origin_mode = payload
        assert pprops.false_origin_mode == "MANUAL"
