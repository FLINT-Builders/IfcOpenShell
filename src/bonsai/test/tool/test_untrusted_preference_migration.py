# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2022 Dion Moult <dion@thinkmoult.com>
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

"""Opened .blend files must not install executable preferences.

``tool.Blender.sync_old_preferences`` runs from ``load_post`` and copies raw
scene ID properties into the user's add-on preferences. With
``occurrence_name_style`` of ``CUSTOM``, ``tool.Model.generate_occurrence_name``
passes ``occurrence_name_function`` to ``eval``. These tests fail while that
chain accepts values stored in a document.

The occurrence-name sink is shared by every caller that does not first require
the ``TYPE`` style. This module exercises the sink once, after a real file
open. Callers that reach it the same way and are not invoked on their own:

- ``bonsai.bim.module.model.product`` (add element)
- ``bonsai.bim.module.model.wall.DumbWallGenerator.create_wall``
- ``bonsai.bim.module.model.slab`` ``create_slab``
- ``bonsai.bim.module.model.profile.DumbProfileGenerator.create_profile``
- ``bonsai.core.spatial`` space creation
- ``bonsai.bim.module.type.operator.AutoRenameOccurrences``

``AssignType`` and ``DuplicateType`` call ``generate_occurrence_name`` only when
the style is already ``TYPE``, which returns the type name and does not eval.
"""

from __future__ import annotations

import math
import tempfile
import uuid
from pathlib import Path

import bpy
import ifcopenshell

import bonsai.bim.handler
import bonsai.bim.schema
import bonsai.tool as tool
import bonsai.tool.model as model_mod

# Every entry of ``sync_old_preferences``'s remap. Values are stand-ins a
# document can store as ID properties; none of them are credentials.
_BOOL_PATHS = (
    "scene.BIMBSDDProperties.load_preview_dictionaries",
    "scene.BIMBSDDProperties.load_inactive_dictionaries",
    "scene.BIMBSDDProperties.load_test_dictionaries",
    "scene.BIMProjectProperties.should_disable_undo_on_save",
    "scene.BIMProjectProperties.should_stream",
)
_BOOL_TARGETS = (
    "preferences.bsdd_load_preview_dictionaries",
    "preferences.bsdd_load_inactive_dictionaries",
    "preferences.bsdd_load_test_dictionaries",
    "preferences.should_disable_undo_on_save",
    "preferences.should_stream",
)
_STRING_PATHS = (
    "scene.BIMProperties.pset_dir",
    "scene.BIMProperties.data_dir",
    "scene.BIMProperties.cache_dir",
    "scene.DocProperties.sheets_dir",
    "scene.DocProperties.layouts_dir",
    "scene.DocProperties.titleblocks_dir",
    "scene.DocProperties.drawings_dir",
    "scene.DocProperties.stylesheet_path",
    "scene.DocProperties.schedules_stylesheet_path",
    "scene.DocProperties.markers_path",
    "scene.DocProperties.symbols_path",
    "scene.DocProperties.patterns_path",
    "scene.DocProperties.shadingstyles_path",
    "scene.DocProperties.shadingstyle_default",
    "scene.DocProperties.drawing_font",
    "scene.DocProperties.imperial_precision",
    "scene.DocProperties.classes_to_wireframe",
    "scene.DocProperties.classes_no_cut",
)
_STRING_TARGETS = (
    "preferences.pset_dir",
    "preferences.data_dir",
    "preferences.cache_dir",
    "preferences.doc.sheets_dir",
    "preferences.doc.layouts_dir",
    "preferences.doc.titleblocks_dir",
    "preferences.doc.drawings_dir",
    "preferences.doc.stylesheet_path",
    "preferences.doc.schedules_stylesheet_path",
    "preferences.doc.markers_path",
    "preferences.doc.symbols_path",
    "preferences.doc.patterns_path",
    "preferences.doc.shadingstyles_path",
    "preferences.doc.shadingstyle_default",
    "preferences.doc.drawing_font",
    "preferences.doc.imperial_precision",
    "preferences.doc.classes_to_wireframe",
    "preferences.doc.classes_no_cut",
)
_FLOAT_PATHS = (
    "scene.DocProperties.magic_font_scale",
    "scene.DocProperties.tolerance",
)
_FLOAT_TARGETS = (
    "preferences.doc.magic_font_scale",
    "preferences.doc.tolerance",
)
_FLOAT_SENTINEL = 0.424242


def _resolve(path: str):
    return tool.Blender.resolve_data_path_to_data_attr(path)


def _is_set(path: str) -> bool:
    data, attr = _resolve(path)
    return data.is_property_set(attr)


def _read(path: str):
    data, attr = _resolve(path)
    return getattr(data, attr)


def _write_pref(path: str, value) -> None:
    data, attr = _resolve(path)
    setattr(data, attr, value)


def _unset(path: str) -> None:
    data, attr = _resolve(path)
    if data.is_property_set(attr):
        data.property_unset(attr)


def _snapshot(paths: tuple[str, ...]) -> list[tuple[str, bool, object]]:
    saved = []
    for path in paths:
        if _is_set(path):
            saved.append((path, True, _read(path)))
        else:
            saved.append((path, False, None))
    return saved


def _restore(saved: list[tuple[str, bool, object]]) -> None:
    for path, was_set, value in saved:
        if was_set:
            _write_pref(path, value)
        else:
            _unset(path)


def _plant_id_property(scene_path: str, value) -> None:
    data, attr = _resolve(scene_path)
    data[attr] = value


def _userpref_file() -> Path:
    return Path(bpy.utils.user_resource("CONFIG")) / "userpref.blend"


def test_opened_blend_cannot_install_executable_or_path_preferences() -> None:
    """A .blend opened with auto-run disabled must not change code or path prefs."""
    token = "untrusted_blend_" + uuid.uuid4().hex
    probe = f"(globals().__setitem__('{token}', 'hit') or '{token}')"
    string_sentinel = f"untrusted-doc-{token}"
    pref_paths = (
        "preferences.occurrence_name_style",
        "preferences.occurrence_name_function",
        *_BOOL_TARGETS,
        *_STRING_TARGETS,
        *_FLOAT_TARGETS,
    )
    saved = _snapshot(pref_paths)
    preferences = bpy.context.preferences
    saved_autoexec = preferences.filepaths.use_scripts_auto_execute
    saved_autosave = preferences.use_preferences_save
    blend_path = Path(tempfile.mkdtemp()) / "untrusted.blend"
    try:
        for path in pref_paths:
            _unset(path)
        if hasattr(model_mod, token):
            delattr(model_mod, token)

        _plant_id_property("scene.BIMModelProperties.occurrence_name_style", "CUSTOM")
        _plant_id_property("scene.BIMModelProperties.occurrence_name_function", probe)
        for scene_path in _BOOL_PATHS:
            _plant_id_property(scene_path, True)
        for scene_path in _STRING_PATHS:
            _plant_id_property(scene_path, string_sentinel)
        for scene_path in _FLOAT_PATHS:
            _plant_id_property(scene_path, _FLOAT_SENTINEL)

        # A script the file would run if auto-run were enabled. It must not run.
        autorun_key = "autorun_" + token
        text = bpy.data.texts.new(autorun_key)
        text.write(f"import bpy\nbpy.app.driver_namespace['{autorun_key}'] = 'ran'\n")
        text.use_module = True

        preferences.filepaths.use_scripts_auto_execute = False
        preferences.use_preferences_save = True
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

        # Drop anything a save-time depsgraph handler already copied, so the
        # open below is what installs the document values.
        for path in pref_paths:
            _unset(path)
        if hasattr(model_mod, token):
            delattr(model_mod, token)
        bpy.app.driver_namespace.pop(autorun_key, None)
        preferences.filepaths.use_scripts_auto_execute = False

        assert bonsai.bim.handler.load_post in bpy.app.handlers.load_post
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))

        scene = bpy.context.scene
        assert scene.BIMModelProperties["occurrence_name_function"] == probe
        assert math.isclose(scene.DocProperties["magic_font_scale"], _FLOAT_SENTINEL, rel_tol=1e-5, abs_tol=1e-5)
        assert preferences.filepaths.use_scripts_auto_execute is False
        assert bpy.app.driver_namespace.get(autorun_key) is None

        problems: list[str] = []
        if _read("preferences.occurrence_name_style") == "CUSTOM":
            problems.append("occurrence_name_style was set to CUSTOM from the file")
        function = _read("preferences.occurrence_name_function")
        if token in function:
            problems.append("occurrence_name_function was copied from the file")
        for target in _BOOL_TARGETS:
            if _read(target) is True:
                problems.append(f"{target} was enabled from the file")
        for target in _STRING_TARGETS:
            if _read(target) == string_sentinel:
                problems.append(f"{target} was copied from the file")
        for target in _FLOAT_TARGETS:
            # RNA floats are stored as float32, so the round trip is not exact.
            if math.isclose(_read(target), _FLOAT_SENTINEL, rel_tol=1e-5, abs_tol=1e-5):
                problems.append(f"{target} was copied from the file")

        userpref = _userpref_file()
        if userpref.is_file() and token.encode() in userpref.read_bytes():
            problems.append("user preferences on disk contain the document payload")

        ifc = ifcopenshell.file()
        element_type = ifc.create_entity("IfcWallType", Name="TypeName")
        generated = tool.Model.generate_occurrence_name(element_type, "IfcWall")
        if generated == token or getattr(model_mod, token, None) == "hit":
            problems.append("generate_occurrence_name evaluated the document expression")

        # Same preferences apply in a later, empty project.
        bpy.ops.wm.read_homefile(app_template="")
        generated_later = tool.Model.generate_occurrence_name(element_type, "IfcWall")
        if generated_later == token or getattr(model_mod, token, None) == "hit":
            problems.append("the expression still evaluates in a later project")

        assert not problems, "; ".join(problems)
    finally:
        _restore(saved)
        prefs = tool.Blender.get_addon_preferences()
        bonsai.bim.schema.ifc.data_dir = prefs.data_dir
        bonsai.bim.schema.ifc.cache_dir = prefs.cache_dir
        if hasattr(model_mod, token):
            delattr(model_mod, token)
        preferences.use_preferences_save = True
        bpy.ops.wm.save_userpref()
        preferences.use_preferences_save = saved_autosave
        preferences.filepaths.use_scripts_auto_execute = saved_autoexec
        blend_path.unlink(missing_ok=True)
        blend_path.parent.rmdir()
        bpy.ops.wm.read_homefile(app_template="")
