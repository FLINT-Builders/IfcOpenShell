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

"""Style import must not allocate an image from uncapped IFC texture dimensions.

Loading a project calls ``IfcImporter.create_styles``, which sets
``active_style_type`` and therefore ``tool.Style.switch_shading``. That calls
``Loader.create_surface_style_with_textures``. For an ``IfcPixelTexture`` the
loader allocates ``Width * Height * 4`` float32 values and asks Blender for an
image of that size. For an ``IfcBlobTexture`` it uses the decoded image size
the same way.

Required behaviour, before any of those allocations:

- ``Width`` and ``Height`` are positive integers
- neither dimension is greater than 8192
- ``Width * Height`` is not greater than ``8192 * 8192``
- an ``IfcPixelTexture`` has exactly ``Width * Height`` ``Pixel`` entries

Otherwise the texture is skipped with a warning and no buffer or Blender image
is requested. A texture that already meets the limit still loads.

``get_image`` is shared by every supported mode. ``DIFFUSE`` covers
``PHYSICAL`` / ``NOTDEFINED``; ``EMISSIVE`` covers ``FLAT``. ``NORMAL``,
``METALLICROUGHNESS`` and ``OCCLUSION`` call that same ``get_image`` before
building their nodes.
"""

import io
import logging
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

import bpy
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.style
import ifcopenshell.api.unit
import numpy as np
from PIL import Image

import bonsai.bim.import_ifc as import_ifc
import bonsai.tool as tool
import bonsai.tool.loader as loader_mod
from bonsai.bim.ifc import IfcStore
from test.bim.bootstrap import NewFile

MAX_DIMENSION = 8192
MAX_PIXELS = 8192 * 8192
# Large enough to be the reported attack, small enough that the guard below
# refuses it before numpy or Blender reserves the buffer.
ATTACK_DIMENSION = 30000
# Over the dimension cap, but small enough that a real allocation is safe.
OVER_DIMENSION = 9000


def _exceeds_cap(width, height) -> bool:
    return (
        not isinstance(width, (int, np.integer))
        or not isinstance(height, (int, np.integer))
        or width <= 0
        or height <= 0
        or width > MAX_DIMENSION
        or height > MAX_DIMENSION
        or int(width) * int(height) > MAX_PIXELS
    )


def _unsafe_to_allocate(width, height) -> bool:
    if not isinstance(width, (int, np.integer)) or not isinstance(height, (int, np.integer)):
        return True
    if width <= 0 or height <= 0:
        return True
    return int(width) * int(height) > 1_000_000


@contextmanager
def _allocation_guard():
    """Record texture allocations and refuse only the ones that would exhaust memory."""
    calls = {"ones": [], "images": [], "converts": []}
    real_ones = loader_mod.np.ones
    real_bpy = loader_mod.bpy
    real_convert = Image.Image.convert

    def spy_ones(shape, dtype=None, *args, **kwargs):
        n = int(shape) if isinstance(shape, (int, np.integer)) else int(np.prod(shape))
        calls["ones"].append(n)
        if n <= 0 or n > MAX_PIXELS * 4:
            raise MemoryError(f"refusing float buffer of {n}")
        return real_ones(shape, dtype, *args, **kwargs)

    class _Images:
        def new(self, name, width=None, height=None, **kwargs):
            calls["images"].append((name, width, height))
            if _unsafe_to_allocate(width, height):
                raise MemoryError(f"refusing image {width}x{height}")
            return bpy.data.images.new(name, width=width, height=height, **kwargs)

        def __getattr__(self, name):
            return getattr(bpy.data.images, name)

    class _Data:
        def __getattr__(self, name):
            if name == "images":
                return _Images()
            return getattr(bpy.data, name)

    class _Bpy:
        def __getattr__(self, name):
            if name == "data":
                return _Data()
            return getattr(real_bpy, name)

    def spy_convert(self, mode=None, *args, **kwargs):
        calls["converts"].append((tuple(self.size), mode))
        width, height = self.size
        if _unsafe_to_allocate(width, height):
            raise MemoryError(f"refusing blob convert {width}x{height}")
        return real_convert(self, mode, *args, **kwargs)

    loader_mod.np.ones = spy_ones
    loader_mod.bpy = _Bpy()
    Image.Image.convert = spy_convert
    try:
        yield calls
    finally:
        loader_mod.np.ones = real_ones
        loader_mod.bpy = real_bpy
        Image.Image.convert = real_convert


def _assert_within_cap(calls) -> None:
    for n in calls["ones"]:
        assert 0 < n <= MAX_PIXELS * 4, f"np.ones requested {n} values"
    for name, width, height in calls["images"]:
        assert not _exceeds_cap(width, height), f"{name} requested at {width}x{height}"
    for (width, height), _mode in calls["converts"]:
        assert not _exceeds_cap(width, height), f"blob convert requested at {width}x{height}"
    for image in bpy.data.images:
        if image.name in {"Render Result", "Viewer Node"}:
            continue
        assert not _exceeds_cap(image.size[0], image.size[1]), f"image {image.name} is {tuple(image.size)}"


def _texture_images():
    return [image for image in bpy.data.images if image.name not in {"Render Result", "Viewer Node"}]


def _write_project(schema, method, texture_builder, directory: Path) -> Path:
    ifc = ifcopenshell.api.project.create_file(schema)
    ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject", name="Texture Limits")
    ifcopenshell.api.unit.assign_unit(ifc)
    style = ifcopenshell.api.style.add_style(ifc, name="Limited")
    ifcopenshell.api.style.add_surface_style(
        ifc,
        style=style,
        ifc_class="IfcSurfaceStyleRendering",
        attributes={
            "ReflectanceMethod": method,
            "SurfaceColour": {"Red": 0.2, "Green": 0.2, "Blue": 0.2},
        },
    )
    texture_builder(ifc, style)
    path = directory / "texture-limits.ifc"
    ifc.write(str(path))
    return path


def _add_pixel(ifc, style, width, height, pixels, mode):
    texture = ifc.create_entity(
        "IfcPixelTexture",
        RepeatS=True,
        RepeatT=True,
        Mode=mode,
        Width=width,
        Height=height,
        ColourComponents=4,
        Pixel=pixels,
    )
    ifc.create_entity("IfcTextureCoordinateGenerator", Maps=[texture], Mode="COORD")
    ifcopenshell.api.style.add_surface_style(
        ifc,
        style=style,
        ifc_class="IfcSurfaceStyleWithTextures",
        attributes={"Textures": [texture]},
    )


def _pixel(count):
    # One opaque red pixel, as a bit string IfcBinary.
    return ["11111111000000000000000011111111"] * count


def _load(path: Path, calls_box: dict):
    IfcStore.purge()
    tool.Ifc.set_path(str(path))
    logger = logging.getLogger("ImportIFC")
    settings = import_ifc.IfcImportSettings.factory(bpy.context, str(path), logger)
    importer = import_ifc.IfcImporter(settings)
    # Same entry Load Project uses. create_styles runs before any geometry.
    importer.execute()
    calls_box["importer"] = importer


class TestUncappedSurfaceTextures(NewFile):
    def setup_method(self, method):
        self.directory = Path(bpy.app.tempdir)

    def _import(self, schema, method, texture_builder):
        path = _write_project(schema, method, texture_builder, self.directory)
        stdout = io.StringIO()
        with _allocation_guard() as calls, redirect_stdout(stdout):
            _load(path, calls)
        return calls, stdout.getvalue()

    def test_load_project_does_not_allocate_attack_pixel_texture(self):
        def build(ifc, style):
            _add_pixel(ifc, style, ATTACK_DIMENSION, ATTACK_DIMENSION, _pixel(1), "DIFFUSE")

        calls, output = self._import("IFC4", "NOTDEFINED", build)
        _assert_within_cap(calls)
        assert calls["ones"] == []
        assert "WARNING" in output
        assert _texture_images() == []
        assert tool.Ifc.get().by_type("IfcPixelTexture")[0].Width == ATTACK_DIMENSION

    def test_physical_reflectance_is_capped(self):
        def build(ifc, style):
            _add_pixel(ifc, style, OVER_DIMENSION, 2, _pixel(1), "DIFFUSE")

        calls, output = self._import("IFC4X3", "PHYSICAL", build)
        _assert_within_cap(calls)
        assert "WARNING" in output
        assert _texture_images() == []

    def test_flat_emissive_pixel_texture_is_capped(self):
        def build(ifc, style):
            _add_pixel(ifc, style, OVER_DIMENSION, 1, _pixel(1), "EMISSIVE")

        calls, output = self._import("IFC4", "FLAT", build)
        _assert_within_cap(calls)
        assert "WARNING" in output
        assert _texture_images() == []

    def test_pixel_count_must_match_dimensions(self):
        def build(ifc, style):
            _add_pixel(ifc, style, 8, 8, _pixel(1), "DIFFUSE")

        calls, output = self._import("IFC4", "NOTDEFINED", build)
        assert calls["ones"] == []
        assert calls["images"] == []
        assert "WARNING" in output
        assert _texture_images() == []

    def test_non_positive_dimensions_are_not_allocated(self):
        for width, height in ((0, 4), (-5, 4)):

            def build(ifc, style, width=width, height=height):
                _add_pixel(ifc, style, width, height, _pixel(1), "DIFFUSE")

            calls, output = self._import("IFC4", "NOTDEFINED", build)
            assert calls["ones"] == [], (width, height, calls["ones"])
            assert calls["images"] == []
            assert "WARNING" in output
            assert _texture_images() == []

    def test_blob_texture_dimensions_are_capped(self):
        def build(ifc, style):
            image = Image.new("RGBA", (OVER_DIMENSION, 1), (255, 0, 0, 255))
            encoded = io.BytesIO()
            image.save(encoded, format="PNG")
            raster = "".join(f"{byte:08b}" for byte in encoded.getvalue())
            texture = ifc.create_entity(
                "IfcBlobTexture",
                RepeatS=True,
                RepeatT=True,
                Mode="DIFFUSE",
                RasterFormat="PNG",
                RasterCode=raster,
            )
            ifc.create_entity("IfcTextureCoordinateGenerator", Maps=[texture], Mode="COORD")
            ifcopenshell.api.style.add_surface_style(
                ifc,
                style=style,
                ifc_class="IfcSurfaceStyleWithTextures",
                attributes={"Textures": [texture]},
            )

        calls, output = self._import("IFC4", "NOTDEFINED", build)
        _assert_within_cap(calls)
        assert calls["images"] == []
        assert calls["converts"] == []
        assert "WARNING" in output
        assert _texture_images() == []

    def test_pixel_texture_within_the_cap_still_loads(self):
        def build(ifc, style):
            _add_pixel(ifc, style, 2, 2, _pixel(4), "DIFFUSE")

        calls, _output = self._import("IFC4", "NOTDEFINED", build)
        _assert_within_cap(calls)
        assert calls["ones"] == [2 * 2 * 4]
        images = _texture_images()
        assert len(images) == 1
        assert tuple(images[0].size) == (2, 2)
        assert len(images[0].pixels) == 2 * 2 * 4
