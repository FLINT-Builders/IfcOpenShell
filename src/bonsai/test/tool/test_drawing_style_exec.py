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

import json
import os
from pathlib import Path

import bpy
import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.util.element

import bonsai.tool as tool
from test.bim.bootstrap import NewFile

os.environ.setdefault("PYTEST_VERSION", "1")

STYLE_NAME = "Injected"
SAFE_RESOLUTION = 37


def _statement(marker: Path) -> str:
    """Python that records execution. Double quotes only, so it survives the single-quoted exec string."""
    return f'__import__("pathlib").Path("{marker.as_posix()}").write_text("ran")'


def _string_breakout(marker: Path) -> str:
    """Value that closes the quote wrapped around string style values and then runs `_statement`."""
    return f"BLENDER_WORKBENCH'; {_statement(marker)}; y='"


def _styles(raster_style: dict) -> dict:
    return {STYLE_NAME: {"render_type": "VIEWPORT", "raster_style": raster_style}}


def _string_injection_styles(marker: Path) -> dict:
    return _styles(
        {
            "scene.render.resolution_percentage": SAFE_RESOLUTION,
            "scene.render.engine": _string_breakout(marker),
        }
    )


def _key_injection_styles(marker: Path) -> dict:
    # Non-string values are interpolated unquoted, so the key itself is executed.
    key = f"{_statement(marker)}; scene.render.resolution_percentage"
    return _styles(
        {
            "scene.render.engine": "BLENDER_WORKBENCH",
            key: SAFE_RESOLUTION,
        }
    )


def _safe_styles() -> dict:
    return _styles(
        {
            "scene.render.engine": "BLENDER_WORKBENCH",
            "scene.render.resolution_percentage": SAFE_RESOLUTION,
        }
    )


class TestDrawingStyleExec(NewFile):
    def setup_project_with_drawing(self):
        bpy.ops.bim.create_project()
        tool.Project.save_test_project()
        bpy.ops.bim.load_drawings()
        bpy.ops.bim.add_drawing()
        ifc = tool.Ifc.get()
        drawing = next(element for element in ifc.by_type("IfcAnnotation") if element.ObjectType == "DRAWING")
        props = tool.Drawing.get_document_props()
        for index, item in enumerate(props.drawings):
            if item.ifc_definition_id == drawing.id():
                props.active_drawing_index = index
                break
        bpy.ops.bim.activate_drawing(drawing=drawing.id())
        return drawing

    def point_drawing_at_styles(self, drawing, styles_path: Path, stored_path: str) -> None:
        styles_path.parent.mkdir(parents=True, exist_ok=True)
        ifc = tool.Ifc.get()
        pset_id = ifcopenshell.util.element.get_pset(drawing, "EPset_Drawing")["id"]
        pset = ifc.by_id(pset_id)
        ifcopenshell.api.pset.edit_pset(
            ifc,
            pset=pset,
            properties={"ShadingStyles": stored_path, "CurrentShadingStyle": STYLE_NAME},
        )
        # The path has to survive being stored in the IFC, which is how a received project carries it.
        roundtrip_path = styles_path.parent / "roundtrip.ifc"
        ifc.write(roundtrip_path)
        reopened = ifcopenshell.open(roundtrip_path)
        reopened_drawing = reopened.by_id(drawing.id())
        assert ifcopenshell.util.element.get_pset(reopened_drawing, "EPset_Drawing", "ShadingStyles") == stored_path
        assert (
            ifcopenshell.util.element.get_pset(reopened_drawing, "EPset_Drawing", "CurrentShadingStyle") == STYLE_NAME
        )
        assert tool.Ifc.resolve_uri(stored_path) == styles_path.as_posix()

    def write_styles(self, styles_path: Path, styles: dict, stored_path: str):
        drawing = self.setup_project_with_drawing()
        self.point_drawing_at_styles(drawing, styles_path, stored_path)
        styles_path.write_text(json.dumps(styles))
        return drawing

    def assert_styles_loaded(self, marker: Path) -> None:
        props = tool.Drawing.get_document_props()
        result = bpy.ops.bim.reload_drawing_styles()
        assert result == {"FINISHED"}
        names = [style.name for style in props.drawing_styles]
        assert names == [STYLE_NAME]
        # The marker path is inside the style JSON, so reload really picked up this file.
        assert marker.as_posix() in props.drawing_styles[0].raster_style

    def assert_activation_does_not_run_code(self, marker: Path, activate) -> None:
        marker.unlink(missing_ok=True)
        try:
            activate()
        except Exception:
            # Rejection may raise. Execution has already landed if the marker exists.
            pass
        assert not marker.exists(), "shading style data was executed as Python"

    def test_safe_style_properties_are_applied(self):
        ifc_dir = Path(tool.Project.TEMP_PROJECT_PATH).parent
        styles_path = ifc_dir / "drawings" / "safe-styles.json"
        # save_test_project wipes this directory, so write the file after the project exists.
        self.write_styles(styles_path, _safe_styles(), "drawings/safe-styles.json")
        props = tool.Drawing.get_document_props()
        result = bpy.ops.bim.reload_drawing_styles()
        assert result == {"FINISHED"}
        assert [style.name for style in props.drawing_styles] == [STYLE_NAME]
        result = bpy.ops.bim.activate_drawing_style()
        assert result == {"FINISHED"}
        scene = bpy.context.scene
        assert scene.render.resolution_percentage == SAFE_RESOLUTION
        assert scene.render.engine == "BLENDER_WORKBENCH"

    def test_activate_drawing_does_not_execute_string_style_values(self, tmp_path: Path):
        marker = tmp_path / "string-value.txt"
        ifc_dir = Path(tool.Project.TEMP_PROJECT_PATH).parent
        styles_path = ifc_dir / "drawings" / "styles.json"
        drawing = self.write_styles(styles_path, _string_injection_styles(marker), "drawings/styles.json")
        self.assert_styles_loaded(marker)

        def activate():
            bpy.ops.bim.activate_drawing(drawing=drawing.id())

        self.assert_activation_does_not_run_code(marker, activate)

    def test_activate_drawing_style_does_not_execute_style_keys(self, tmp_path: Path):
        marker = tmp_path / "style-key.txt"
        ifc_dir = Path(tool.Project.TEMP_PROJECT_PATH).parent
        styles_path = ifc_dir / "drawings" / "key-styles.json"
        styles = _key_injection_styles(marker)
        self.write_styles(styles_path, styles, "drawings/key-styles.json")
        self.assert_styles_loaded(marker)
        self.assert_activation_does_not_run_code(marker, bpy.ops.bim.activate_drawing_style)

    def test_absolute_shading_styles_path_outside_project_is_not_executed(self, tmp_path: Path):
        marker = tmp_path / "absolute.txt"
        styles_path = tmp_path / "outside-project" / "styles.json"
        self.write_styles(styles_path, _string_injection_styles(marker), styles_path.as_posix())
        self.assert_styles_loaded(marker)
        self.assert_activation_does_not_run_code(marker, bpy.ops.bim.activate_drawing_style)

    def test_relative_shading_styles_path_outside_project_is_not_executed(self, tmp_path: Path):
        marker = tmp_path / "relative-escape.txt"
        styles_path = tmp_path / "escaped" / "styles.json"
        drawing = self.setup_project_with_drawing()
        ifc_dir = Path(tool.Ifc.get_path()).parent
        stored_path = Path(os.path.relpath(styles_path, ifc_dir)).as_posix()
        assert stored_path.startswith(".."), stored_path
        self.point_drawing_at_styles(drawing, styles_path, stored_path)
        styles_path.write_text(json.dumps(_string_injection_styles(marker)))
        self.assert_styles_loaded(marker)
        self.assert_activation_does_not_run_code(marker, bpy.ops.bim.activate_drawing_style)

    def test_enabling_underlay_does_not_execute_shading_styles(self, tmp_path: Path):
        marker = tmp_path / "underlay.txt"
        ifc_dir = Path(tool.Project.TEMP_PROJECT_PATH).parent
        styles_path = ifc_dir / "drawings" / "underlay-styles.json"
        self.write_styles(styles_path, _string_injection_styles(marker), "drawings/underlay-styles.json")
        self.assert_styles_loaded(marker)
        scene = bpy.context.scene
        assert scene and scene.camera
        camera_props = tool.Drawing.get_camera_props(scene.camera)
        if camera_props.has_underlay:
            camera_props.has_underlay = False
        marker.unlink(missing_ok=True)

        def activate():
            camera_props.has_underlay = True

        self.assert_activation_does_not_run_code(marker, activate)

    def test_activate_drawing_from_sheet_does_not_execute_shading_styles(self, tmp_path: Path):
        marker = tmp_path / "from-sheet.txt"
        ifc_dir = Path(tool.Project.TEMP_PROJECT_PATH).parent
        styles_path = ifc_dir / "drawings" / "sheet-styles.json"
        drawing = self.write_styles(styles_path, _key_injection_styles(marker), "drawings/sheet-styles.json")
        props = tool.Drawing.get_document_props()
        item = props.sheets.add()
        item.name = f"{drawing.Name}.svg"
        item.reference_type = "DRAWING"
        item.is_sheet = False
        props.active_sheet_index = len(props.sheets) - 1
        assert bpy.ops.bim.activate_drawing_from_sheet.poll()
        self.assert_styles_loaded(marker)

        def activate():
            bpy.ops.bim.activate_drawing_from_sheet(drawing=drawing.id())

        self.assert_activation_does_not_run_code(marker, activate)
