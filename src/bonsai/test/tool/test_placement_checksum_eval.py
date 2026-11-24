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

"""Placement checksum strings must be decoded as data, never with eval().

These tests fail while the vulnerability is present. A stored checksum is an
arbitrary string in a .blend file. Opening that file with Blender's auto-run
scripts disabled still restores the string, and saving the project passes it
to eval(). The tests pass once those strings are decoded without executing
code (for example ast.literal_eval or bytes.fromhex) and a value that is not
a literal is treated as moved.
"""

import logging
import tempfile
from pathlib import Path

import bpy
import ifcopenshell
import ifcopenshell.guid

import bonsai.bim.handler
import bonsai.tool as tool
import test.bim.bootstrap
from bonsai.bim.export_ifc import IfcExporter, IfcExportSettings
from bonsai.bim.module.drawing.data import DecoratorData
from bonsai.bim.module.drawing.decoration import CutDecorator


def _payload(marker: Path) -> str:
    return f"__import__('pathlib').Path({str(marker)!r}).write_text('executed')"


def _or_payload(marker: Path) -> str:
    # b'' is a bytes literal, so a check that eval()s anything looking like
    # one still runs the expression. ast.literal_eval rejects it.
    return f"b'' or {_payload(marker)}"


def _assert_not_executed(marker: Path, moved) -> None:
    assert not marker.exists()
    assert moved is True


def _call_is_moved(obj: bpy.types.Object, *, ifc_only: bool = True):
    try:
        return tool.Ifc.is_moved(obj, ifc_only=ifc_only)
    except Exception:
        return None


def _link_wall(name: str) -> bpy.types.Object:
    ifc = ifcopenshell.file()
    element = ifc.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new())
    tool.Ifc.set(ifc)
    obj = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(obj)
    tool.Ifc.link(element, obj)
    return obj


def _record_then(obj: bpy.types.Object, **checksums: str) -> None:
    tool.Geometry.record_object_position(obj)
    props = tool.Blender.get_object_bim_props(obj)
    for name, value in checksums.items():
        setattr(props, name, value)


class TestPlacementChecksumEval(test.bim.bootstrap.NewFile):
    def test_untrusted_blend_location_checksum_is_not_executed_on_export(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            exec_marker = directory / "location-exec"
            script_marker = directory / "autorun-script"
            ifc_path = directory / "project.ifc"
            blend_path = directory / "project.blend"
            payload = _payload(exec_marker)

            ifc = ifcopenshell.file()
            element = ifc.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new())
            ifc.write(str(ifc_path))
            tool.Ifc.set(ifc)
            tool.Blender.get_bim_props().ifc_file = str(ifc_path)

            obj = bpy.data.objects.new("Wall", None)
            bpy.context.scene.collection.objects.link(obj)
            tool.Ifc.link(element, obj)
            _record_then(obj, location_checksum=payload)

            text = bpy.data.texts.new("untrusted_autorun")
            text.write(f"from pathlib import Path\nPath({str(script_marker)!r}).write_text('script')\n")
            text.use_module = True
            bpy.context.preferences.filepaths.use_scripts_auto_execute = False
            bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

            bpy.ops.wm.open_mainfile(filepath=str(blend_path), use_scripts=False)
            bonsai.bim.handler.loadIfcStore(bpy.context.scene)

            assert not script_marker.exists()
            assert not exec_marker.exists()
            obj = bpy.data.objects["Wall"]
            props = tool.Blender.get_object_bim_props(obj)
            assert props.location_checksum == payload
            assert tool.Ifc.get_entity(obj) is not None

            logger = logging.getLogger("placement-checksum")
            settings = IfcExportSettings.factory(bpy.context, str(directory / "out.ifc"), logger)
            try:
                IfcExporter(settings).export()
            except Exception:
                pass
            assert not exec_marker.exists()

    def test_rotation_checksum_from_blend_is_not_executed(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            marker = directory / "rotation-exec"
            ifc_path = directory / "project.ifc"
            blend_path = directory / "project.blend"
            payload = _payload(marker)

            ifc = ifcopenshell.file()
            element = ifc.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new())
            ifc.write(str(ifc_path))
            tool.Ifc.set(ifc)
            tool.Blender.get_bim_props().ifc_file = str(ifc_path)

            obj = bpy.data.objects.new("Wall", None)
            bpy.context.scene.collection.objects.link(obj)
            tool.Ifc.link(element, obj)
            _record_then(obj, rotation_checksum=payload)
            bpy.context.preferences.filepaths.use_scripts_auto_execute = False
            bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
            bpy.ops.wm.open_mainfile(filepath=str(blend_path), use_scripts=False)
            bonsai.bim.handler.loadIfcStore(bpy.context.scene)

            obj = bpy.data.objects["Wall"]
            props = tool.Blender.get_object_bim_props(obj)
            assert props.rotation_checksum == payload
            assert props.location_checksum.startswith("b")
            moved = _call_is_moved(obj)
            _assert_not_executed(marker, moved)

    def test_or_expression_checksum_is_not_executed(self):
        marker = Path(tempfile.mkdtemp()) / "or-exec"
        obj = _link_wall("Wall")
        _record_then(obj, location_checksum=_or_payload(marker))
        moved = _call_is_moved(obj)
        _assert_not_executed(marker, moved)

    def test_unlinked_checksum_is_not_executed_when_ifc_only_is_false(self):
        # The clipping-plane modal calls is_moved(..., ifc_only=False), so a checksum
        # is eval()'d even when the object is not linked to an IFC element.
        marker = Path(tempfile.mkdtemp()) / "ifc-only-exec"
        obj = bpy.data.objects.new("Loose", None)
        bpy.context.scene.collection.objects.link(obj)
        props = tool.Blender.get_object_bim_props(obj)
        props.location_checksum = _payload(marker)
        props.rotation_checksum = "b''"
        moved = _call_is_moved(obj, ifc_only=False)
        _assert_not_executed(marker, moved)

    def test_camera_location_checksum_is_not_executed(self):
        marker = Path(tempfile.mkdtemp()) / "camera-location-exec"
        camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
        bpy.context.scene.collection.objects.link(camera)
        bpy.context.scene.camera = camera
        DecoratorData.camera_location_checksum = _payload(marker)
        DecoratorData.camera_rotation_checksum = "b''"
        try:
            moved = CutDecorator().is_camera_moved()
        except Exception:
            moved = None
        finally:
            DecoratorData.camera_location_checksum = ""
            DecoratorData.camera_rotation_checksum = ""
        _assert_not_executed(marker, moved)

    def test_camera_rotation_checksum_is_not_executed(self):
        marker = Path(tempfile.mkdtemp()) / "camera-rotation-exec"
        camera = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
        bpy.context.scene.collection.objects.link(camera)
        bpy.context.scene.camera = camera
        location = repr(tool.Blender.np_array_legacy(camera.matrix_world.translation).tobytes())
        DecoratorData.camera_location_checksum = location
        DecoratorData.camera_rotation_checksum = _or_payload(marker)
        try:
            moved = CutDecorator().is_camera_moved()
        except Exception:
            moved = None
        finally:
            DecoratorData.camera_location_checksum = ""
            DecoratorData.camera_rotation_checksum = ""
        _assert_not_executed(marker, moved)

    def test_recorded_literal_checksum_detects_movement(self):
        obj = _link_wall("Wall")
        assert tool.Ifc.is_moved(obj) is True
        tool.Geometry.record_object_position(obj)
        assert tool.Ifc.is_moved(obj) is False
        obj.matrix_world.translation.x += 1
        assert tool.Ifc.is_moved(obj) is True
