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

"""Import must not touch remote style or texture locations.

These tests fail while Bonsai resolves IfcExternallyDefinedSurfaceStyle.Location
and IfcImageTexture URL/UrlReference values during IfcImporter.create_style.
They pass once those locations are not looked up or opened unless they stay
inside the project directory and are not network paths.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import bpy

_REPO = Path(__file__).resolve().parents[4]
for _extra in (
    _REPO / "src" / "bonsai",
    _REPO / "src" / "bcf",
    _REPO / "src" / "bsdd",
    _REPO / "src" / "ifc4d",
    _REPO / "src" / "ifc5d",
    _REPO / "src" / "ifccityjson",
    _REPO / "src" / "ifcclash",
    _REPO / "src" / "ifccsv",
    _REPO / "src" / "ifcdiff",
    _REPO / "src" / "ifcfm",
    _REPO / "src" / "ifcpatch",
    _REPO / "src" / "ifctester",
):
    _entry = str(_extra)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import bonsai

if not getattr(bonsai, "REGISTERED_BBIM_PACKAGE", None):
    bonsai.REGISTERED_BBIM_PACKAGE = "bonsai"

# Schema import asks for addon preferences unless registration is in progress.
if "bonsai.bim" not in sys.modules:
    bonsai.is_registering = lambda: True

import ifcopenshell

import bonsai.bim.module.style.operator as style_operator
import bonsai.bim.module.style.prop as style_prop
import bonsai.bim.prop as bim_prop
import bonsai.tool as tool
from bonsai.bim.ifc import IfcStore
from bonsai.bim.import_ifc import IfcImporter, IfcImportSettings

_HOST = "credleak-probe.invalid"
_STYLE_COUNTER = 0

# 1x1 transparent PNG. Used only so a resolved texture path can be opened locally.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _ensure_style_types() -> None:
    if hasattr(bpy.types.Material, "BIMStyleProperties") and hasattr(bpy.types.Scene, "BIMStylesProperties"):
        return
    for cls in (
        bim_prop.StrProperty,
        bim_prop.MultipleFileSelect,
        bim_prop.Attribute,
        style_prop.ColourRgb,
        style_prop.Style,
        style_prop.Texture,
        style_prop.BIMStylesProperties,
        style_prop.BIMStyleProperties,
        style_operator.ActivateExternalStyle,
    ):
        if not getattr(cls, "is_registered", False):
            bpy.utils.register_class(cls)
    bpy.types.Material.BIMStyleProperties = bpy.props.PointerProperty(type=style_prop.BIMStyleProperties)
    bpy.types.Scene.BIMStylesProperties = bpy.props.PointerProperty(type=style_prop.BIMStylesProperties)


def _ensure_preferences() -> None:
    try:
        prefs = tool.Blender.get_addon_preferences()
        _ = prefs.doc.classes_to_wireframe
        return
    except Exception:
        pass

    class _Doc:
        classes_to_wireframe = ""

    class _Prefs:
        doc = _Doc()
        should_stream = False
        cache_dir = tempfile.gettempdir()
        tmp_dir = tempfile.gettempdir()
        save_metadata_blend_file = False

    tool.Blender.get_addon_preferences = classmethod(lambda cls: _Prefs())


class _FilesystemProbe:
    """Record filesystem lookups performed by the style import path.

    On Windows the real lookup is not performed: os.stat and Path.resolve of a
    UNC path ask the operating system to contact that host. The attempt is
    still recorded, which is what the assertions check.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self._real_stat = os.stat
        self._real_exists = Path.exists
        self._real_resolve = Path.resolve
        self._real_append = tool.Blender.append_data_block

    def __enter__(self) -> _FilesystemProbe:
        self.events = []
        probe = self

        def stat(path, *args, **kwargs):
            text = os.fspath(path)
            probe.events.append(("os.stat", text))
            if probe._skip_network(text):
                raise FileNotFoundError(text)
            return probe._real_stat(path, *args, **kwargs)

        def exists(path_obj, *args, **kwargs):
            probe.events.append(("Path.exists", str(path_obj)))
            if probe._skip_network(str(path_obj)):
                return False
            return probe._real_exists(path_obj, *args, **kwargs)

        def resolve(path_obj, *args, **kwargs):
            probe.events.append(("Path.resolve", str(path_obj)))
            if probe._skip_network(str(path_obj)):
                raise OSError(str(path_obj))
            return probe._real_resolve(path_obj, *args, **kwargs)

        def append(filepath, data_block_type, name, link=False, relative=False):
            probe.events.append(("append_data_block", str(filepath)))
            if probe._skip_network(str(filepath)):
                return {"data_block": None, "msg": "network path refused by test probe"}
            return probe._real_append(filepath, data_block_type, name, link=link, relative=relative)

        os.stat = stat
        Path.exists = exists
        Path.resolve = resolve
        tool.Blender.append_data_block = append
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        os.stat = self._real_stat
        Path.exists = self._real_exists
        Path.resolve = self._real_resolve
        tool.Blender.append_data_block = self._real_append

    def _skip_network(self, path: str) -> bool:
        if os.name != "nt":
            return False
        text = os.fspath(path).replace("/", "\\")
        return text.startswith("\\\\")


def _attacker_paths(events: list[tuple[str, str]]) -> list[tuple[str, str]]:
    token = _HOST.lower()
    found = []
    for kind, path in events:
        if kind == "exception":
            continue
        normalized = path.replace("\\", "/").lower()
        if token in normalized:
            found.append((kind, path))
    return found


def _project(schema: str) -> ifcopenshell.file:
    # create_style only reads surface styles. Skip project/owner setup so
    # IFC2X3 does not require an owner history before the style is imported.
    return ifcopenshell.file(schema=schema)


def _import_style(ifc: ifcopenshell.file, style: ifcopenshell.entity_instance) -> list[tuple[str, str]]:
    global _STYLE_COUNTER
    _STYLE_COUNTER += 1
    _ensure_style_types()
    _ensure_preferences()
    directory = Path(tempfile.mkdtemp(prefix="credleak-ifc-"))
    ifc_path = directory / f"probe-{_STYLE_COUNTER}.ifc"
    ifc.write(str(ifc_path))
    IfcStore.file = ifc
    IfcStore.path = str(ifc_path)
    settings = IfcImportSettings()
    settings.logger = __import__("logging").getLogger("ImportIFC")
    settings.input_file = str(ifc_path)
    importer = IfcImporter(settings)
    importer.file = ifc
    images_before = {image.name_full: image.filepath for image in bpy.data.images}
    with _FilesystemProbe() as probe:
        try:
            importer.create_style(style)
        except Exception as exc:
            probe.events.append(("exception", str(exc)))
    for image in bpy.data.images:
        if image.name_full not in images_before and _HOST.lower() in image.filepath.replace("\\", "/").lower():
            probe.events.append(("images.load", image.filepath))
        elif (
            images_before.get(image.name_full) != image.filepath
            and _HOST.lower() in (image.filepath or "").replace("\\", "/").lower()
        ):
            probe.events.append(("images.load", image.filepath))
    return probe.events


def _external_style(schema: str, location: str, identification: str = "materials/Any"):
    ifc = _project(schema)
    style = ifc.create_entity("IfcSurfaceStyle", Name=f"External-{_STYLE_COUNTER}", Side="BOTH")
    kwargs = {"Name": "ext", "Location": location}
    if schema == "IFC2X3":
        kwargs["ItemReference"] = identification
    else:
        kwargs["Identification"] = identification
    external = ifc.create_entity("IfcExternallyDefinedSurfaceStyle", **kwargs)
    style.Styles = (external,)
    return ifc, style


def _texture_style(schema: str, url: str):
    ifc = _project(schema)
    style = ifc.create_entity("IfcSurfaceStyle", Name=f"Texture-{_STYLE_COUNTER}", Side="BOTH")
    colour = ifc.create_entity("IfcColourRgb", Name=None, Red=0.2, Green=0.3, Blue=0.4)
    rendering_kwargs = {"SurfaceColour": colour, "ReflectanceMethod": "NOTDEFINED"}
    if schema != "IFC2X3":
        rendering_kwargs["Transparency"] = 0.0
    rendering = ifc.create_entity("IfcSurfaceStyleRendering", **rendering_kwargs)
    if schema == "IFC2X3":
        image = ifc.create_entity("IfcImageTexture", RepeatS=True, RepeatT=True, UrlReference=url)
    else:
        image = ifc.create_entity("IfcImageTexture", RepeatS=True, RepeatT=True, Mode="DIFFUSE", URLReference=url)
    textures = ifc.create_entity("IfcSurfaceStyleWithTextures", Textures=(image,))
    style.Styles = (rendering, textures)
    return ifc, style


def _assert_untouched(events: list[tuple[str, str]]) -> None:
    touched = _attacker_paths(events)
    assert touched == [], "import touched an attacker-controlled style or texture path: " + repr(touched)


def test_activate_external_style_operator_does_not_stat_unc():
    """The operator import calls must reject the UNC path itself.

    Guarding only IfcImporter.create_style still leaves this operator, which
    resolve_uri's the style Location and then checks and loads that path.
    """
    location = f"//{_HOST}/share/operator.blend"
    ifc, style = _external_style("IFC4", location)
    _import_style(ifc, style)
    material = next(mat for mat in bpy.data.materials if mat.BIMStyleProperties.ifc_definition_id == style.id())
    with _FilesystemProbe() as probe:
        try:
            bpy.ops.bim.activate_external_style(material_name=material.name)
        except Exception as exc:
            probe.events.append(("exception", str(exc)))
    _assert_untouched(probe.events)


def test_texture_loader_does_not_resolve_unc_url():
    """Loader.create_surface_style_with_textures is the shading-style lookup."""
    url = f"//{_HOST}/share/loader.png"
    ifc, style = _texture_style("IFC4", url)
    _ensure_style_types()
    _ensure_preferences()
    directory = Path(tempfile.mkdtemp(prefix="credleak-ifc-"))
    ifc_path = directory / "loader.ifc"
    ifc.write(str(ifc_path))
    IfcStore.file = ifc
    IfcStore.path = str(ifc_path)
    material = bpy.data.materials.new("DirectTexture")
    tool.Ifc.link(style, material)
    elements = tool.Style.get_style_elements(style)
    with _FilesystemProbe() as probe:
        try:
            tool.Loader.create_surface_style_rendering(material, elements["IfcSurfaceStyleRendering"])
            tool.Loader.create_surface_style_with_textures(
                material, elements["IfcSurfaceStyleRendering"], elements["IfcSurfaceStyleWithTextures"]
            )
        except Exception as exc:
            probe.events.append(("exception", str(exc)))
    _assert_untouched(probe.events)


def test_suggest_shade_does_not_open_unc_external_style():
    """Suggest Shade loads the external .blend with no separate exists check."""
    location = f"//{_HOST}/share/suggest.blend"
    ifc, style = _external_style("IFC4", location)
    _import_style(ifc, style)
    material = next(mat for mat in bpy.data.materials if mat.BIMStyleProperties.ifc_definition_id == style.id())
    elements = tool.Style.get_style_elements(material)

    class _Reporter:
        def report(self, _level, _message):
            return None

    with _FilesystemProbe() as probe:
        try:
            style_operator.SuggestShadeFromExternalStyle._apply_to_material(_Reporter(), material, elements)
        except Exception as exc:
            probe.events.append(("exception", str(exc)))
    _assert_untouched(probe.events)


def test_shading_style_without_remote_path_is_not_flagged():
    ifc = _project("IFC4")
    style = ifc.create_entity("IfcSurfaceStyle", Name="LocalShading", Side="BOTH")
    colour = ifc.create_entity("IfcColourRgb", Name=None, Red=0.1, Green=0.2, Blue=0.3)
    shading = ifc.create_entity("IfcSurfaceStyleShading", SurfaceColour=colour)
    style.Styles = (shading,)
    events = _import_style(ifc, style)
    _assert_untouched(events)


def test_import_does_not_stat_unc_external_style():
    location = f"//{_HOST}/share/style.blend"
    ifc, style = _external_style("IFC4", location)
    events = _import_style(ifc, style)
    _assert_untouched(events)


def test_import_does_not_load_unc_external_style_when_it_exists():
    # On POSIX, a leading double slash is collapsed by the kernel, so this
    # file makes Path.exists return true and the import continue into
    # libraries.load. The string passed in is still a UNC path.
    root = Path(tempfile.gettempdir()) / _HOST / "share"
    root.mkdir(parents=True, exist_ok=True)
    blend = root / "style.blend"
    blend.write_bytes(b"BLENDER")
    location = "/" + root.as_posix() + "/style.blend"
    ifc, style = _external_style("IFC4", location)
    events = _import_style(ifc, style)
    _assert_untouched(events)


def test_import_does_not_stat_backslash_unc_external_style():
    location = f"\\\\{_HOST}\\share\\style.blend"
    ifc, style = _external_style("IFC4", location)
    events = _import_style(ifc, style)
    _assert_untouched(events)


def test_import_does_not_resolve_unc_image_texture():
    url = f"//{_HOST}/share/tex.png"
    ifc, style = _texture_style("IFC4", url)
    events = _import_style(ifc, style)
    _assert_untouched(events)


def test_import_does_not_load_unc_image_texture_when_it_exists():
    root = Path(tempfile.gettempdir()) / _HOST / "textures"
    root.mkdir(parents=True, exist_ok=True)
    png = root / "tex.png"
    png.write_bytes(_PNG)
    url = "/" + root.as_posix() + "/tex.png"
    ifc, style = _texture_style("IFC4", url)
    events = _import_style(ifc, style)
    _assert_untouched(events)


def test_import_does_not_resolve_backslash_unc_image_texture():
    url = f"\\\\{_HOST}\\share\\tex.png"
    ifc, style = _texture_style("IFC4", url)
    events = _import_style(ifc, style)
    _assert_untouched(events)


def test_import_does_not_resolve_ifc2x3_unc_image_texture():
    url = f"//{_HOST}/share/tex.png"
    ifc, style = _texture_style("IFC2X3", url)
    events = _import_style(ifc, style)
    _assert_untouched(events)


def _main() -> None:
    failures = 0
    for name in sorted(n for n in globals() if n.startswith("test_")):
        try:
            globals()[name]()
        except Exception as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
        else:
            print(f"PASS {name}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    _main()
