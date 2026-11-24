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

"""Paths that Bonsai writes into generated Python must stay data.

Save Blend Metadata File, Link IFC, and Open IFC Document each build a
Python program and hand it to a background Blender process. These tests
run that program. A filename or document location that contains a quote
must not run as code, and the path the script saves or opens must be the
full path, quote included.

The tests fail while those strings are interpolated into quoted literals.
"""

import ast
import os
import runpy
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import ifcopenshell
import pytest

pytestmark = pytest.mark.misc

BONSAI_ROOT = Path(__file__).resolve().parents[2]
OPERATOR_PY = BONSAI_ROOT / "bonsai" / "bim" / "operator.py"
PROJECT_OPERATOR_PY = BONSAI_ROOT / "bonsai" / "bim" / "module" / "project" / "operator.py"
PROJECT_TOOL_PY = BONSAI_ROOT / "bonsai" / "tool" / "project.py"
IFC_TOOL_PY = BONSAI_ROOT / "bonsai" / "tool" / "ifc.py"
DOCUMENT_OPERATOR_PY = BONSAI_ROOT / "bonsai" / "bim" / "module" / "document" / "operator.py"
DOCUMENT_DATA_PY = BONSAI_ROOT / "bonsai" / "bim" / "module" / "document" / "data.py"

# Blender 4.2.0 scripts/modules/bpy/path.py:333-355. Bonsai calls this before
# the metadata script is built. The body below is that function.
_ENSURE_EXT_SOURCE = textwrap.dedent(
    """
    def ensure_ext(filepath, ext, *, case_sensitive=False):
        if case_sensitive:
            if filepath.endswith(ext):
                return filepath
        else:
            if filepath[-len(ext):].lower().endswith(ext.lower()):
                return filepath
        return filepath + ext
    """
)


def _load_function(path: Path, class_name: str, function_name: str):
    """Compile one function out of a Bonsai module without importing bpy."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == function_name:
                    found = item
                    break
    if found is None:
        raise AssertionError(f"{class_name}.{function_name} not in {path}")
    found.decorator_list = []
    module = ast.Module(
        body=[ast.parse("from __future__ import annotations").body[0], found],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    namespace = {"__file__": str(path)}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[function_name]


def _ensure_ext(filepath, ext, *, case_sensitive=False):
    namespace = {}
    exec(_ENSURE_EXT_SOURCE, namespace)
    return namespace["ensure_ext"](filepath, ext, case_sensitive=case_sensitive)


class _IfcApi:
    normalize_path = classmethod(_load_function(IFC_TOOL_PY, "Ifc", "normalize_path"))
    resolve_uri = classmethod(_load_function(IFC_TOOL_PY, "Ifc", "resolve_uri"))

    @classmethod
    def get_path(cls):
        return ""


_IfcApi.normalize_path.__func__.__globals__.update({"Path": Path, "os": os})
_IfcApi.resolve_uri.__func__.__globals__.update({"Path": Path, "os": os})


class _OpCallable:
    """Stand-in for bpy.ops used only while a generated script runs.

    Operator calls return {'FINISHED'} and do not raise. That matches
    Blender 4.2 when a background script reaches the injected line:
    orphans_purge's poll returns true with no window area
    (outliner_edit.cc:2170-2177) and a CANCELLED result that only stores
    an info report does not become a Python exception
    (bpy_operator.cc:257, bpy_capi_utils.cc:25-40).
    """

    def __init__(self, name, saves, loads):
        self.name = name
        self.saves = saves
        self.loads = loads

    def __getattr__(self, name):
        return _OpCallable(f"{self.name}.{name}", self.saves, self.loads)

    def __call__(self, *args, **kwargs):
        filepath = kwargs.get("filepath")
        if self.name.endswith("save_as_mainfile"):
            self.saves.append(filepath)
        elif self.name.endswith("load_project") or self.name.endswith("load_linked_project"):
            self.loads.append(filepath)
        return {"FINISHED"}


class _ScriptRun:
    def __init__(self):
        self.saves = []
        self.loads = []
        self.error = None


def _install_script_modules(run: _ScriptRun):
    previous = {}
    modules = {}

    bpy_mod = types.ModuleType("bpy")
    bpy_mod.data = types.SimpleNamespace(collections=[], objects=[], scenes=[], materials={})
    bpy_mod.context = types.SimpleNamespace(scene=types.SimpleNamespace())
    bpy_mod.ops = _OpCallable("ops", run.saves, run.loads)
    bpy_mod.app = types.SimpleNamespace(binary_path="/usr/bin/blender")
    modules["bpy"] = bpy_mod

    bonsai = types.ModuleType("bonsai")
    bonsai.__path__ = []
    bim = types.ModuleType("bonsai.bim")
    bim.__path__ = []
    ifc_mod = types.ModuleType("bonsai.bim.ifc")

    class IfcStore:
        @staticmethod
        def purge():
            return None

    ifc_mod.IfcStore = IfcStore
    bonsai.bim = bim
    bim.ifc = ifc_mod
    modules["bonsai"] = bonsai
    modules["bonsai.bim"] = bim
    modules["bonsai.bim.ifc"] = ifc_mod

    tool_mod = types.ModuleType("bonsai.tool")

    class Georeference:
        @staticmethod
        def get_georeference_props():
            return types.SimpleNamespace()

    class Project:
        @staticmethod
        def get_project_props():
            return types.SimpleNamespace()

    tool_mod.Georeference = Georeference
    tool_mod.Project = Project
    bonsai.tool = tool_mod
    modules["bonsai.tool"] = tool_mod

    for name, module in modules.items():
        previous[name] = sys.modules.get(name)
        sys.modules[name] = module
    return previous


def _restore_modules(previous):
    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def _run_blender_python(command, run: _ScriptRun):
    """Run the Python Blender would run for this subprocess command.

    sys.argv is the process argv. Blender 4.2 sets it that way and does
    not let Python parse it (bpy_interface.cc:408-410). Arguments after
    '--' stay on sys.argv (creator_args.cc:923-926).
    """
    previous_modules = _install_script_modules(run)
    previous_argv = sys.argv
    try:
        sys.argv = [str(part) for part in command]
        if "--python-expr" in command:
            expr = command[command.index("--python-expr") + 1]
            exec(expr, {"__name__": "__main__"})
        elif "--python" in command:
            script = command[command.index("--python") + 1]
            runpy.run_path(script, run_name="__main__")
        else:
            raise AssertionError(f"command does not run Python: {command}")
    except SystemExit as caught:
        run.error = caught
    except Exception as caught:
        run.error = caught
    finally:
        sys.argv = previous_argv
        _restore_modules(previous_modules)


def _patched_subprocess(runs):
    real_run = subprocess.run
    real_popen = subprocess.Popen

    def run(command, *args, **kwargs):
        run = _ScriptRun()
        runs.append(run)
        _run_blender_python(list(command), run)
        return subprocess.CompletedProcess(list(command), 0, stdout="", stderr="")

    def popen(command, *args, **kwargs):
        run = _ScriptRun()
        runs.append(run)
        _run_blender_python(list(command), run)
        return types.SimpleNamespace(pid=0, args=list(command))

    subprocess.run = run
    subprocess.Popen = popen
    return real_run, real_popen


def _restore_subprocess(real_run, real_popen):
    subprocess.run = real_run
    subprocess.Popen = real_popen


def _quote_payload(marker_name: str) -> str:
    """Text that becomes a second statement if a single-quoted literal breaks.

    The marker name has no path separator, so the whole payload is one
    filename and the injected write lands in the test's working directory.
    """
    return "plan');__import__('pathlib').Path(" + repr(marker_name) + ").write_text('pwned');print('"


def _double_quote_payload(marker_name: str) -> str:
    """Text that becomes a second statement if a double-quoted literal breaks.

    The trailing ``#`` comments out the rest of the generated call
    (``, query=...``) so the broken-out line is still valid Python.
    """
    return 'link");__import__("pathlib").Path(' + repr(marker_name) + ').write_text("pwned") #'


def _host_props():
    bim_props = types.SimpleNamespace(ifc_file="", is_dirty=False)
    prefs = types.SimpleNamespace(
        save_metadata_blend_file=True,
        metadata_blend_file_suffix=".ifc.metadata.blend",
        should_disable_undo_on_save=False,
    )
    project_props = types.SimpleNamespace(
        should_save_metadata_for_this_file=True,
        use_relative_project_path=False,
        distance_limit=1000.0,
        false_origin_mode="AUTOMATIC",
        false_origin="0,0,0",
        project_north="0",
        links=[],
    )
    georef_props = types.SimpleNamespace(
        has_blender_offset=False,
        blender_offset_x="0",
        blender_offset_y="0",
        blender_offset_z="0",
        blender_x_axis_abscissa="1",
        blender_x_axis_ordinate="0",
    )

    class Ifc(_IfcApi):
        @staticmethod
        def set_path(value):
            bim_props.ifc_file = value

        @staticmethod
        def get():
            return None

    tool = types.SimpleNamespace(
        Blender=types.SimpleNamespace(
            get_bim_props=lambda: bim_props,
            get_addon_preferences=lambda: prefs,
            get_blender_addon_package_name=lambda: "bonsai",
            get_data_dir_path=lambda relative_path: Path("/tmp") / relative_path,
        ),
        Ifc=Ifc,
        Project=types.SimpleNamespace(
            get_project_props=lambda: project_props,
            get_metadata_document_information=lambda: object(),
            update_metadata_document_information=lambda name: None,
            create_metadata_document_information=lambda name: None,
            remove_metadata_document_information=lambda: None,
            add_recent_ifc_project=lambda path: None,
        ),
        Georeference=types.SimpleNamespace(get_georeference_props=lambda: georef_props),
        Parametric=types.SimpleNamespace(commit_pending_edits=lambda: (0, [])),
        Autosave=types.SimpleNamespace(reset_timer=lambda: None),
    )
    return tool, bim_props, prefs, project_props


def _operator_bpy(save_metadata):
    bpy = types.SimpleNamespace()
    bpy.app = types.SimpleNamespace(binary_path="/usr/bin/blender")
    bpy.data = types.SimpleNamespace(is_saved=False, filepath="")
    bpy.path = types.SimpleNamespace(ensure_ext=_ensure_ext, abspath=lambda value: value)
    bpy.ops = types.SimpleNamespace(
        wm=types.SimpleNamespace(save_as_mainfile=lambda **kwargs: {"FINISHED"}),
        bim=types.SimpleNamespace(save_blend_metadata_file=save_metadata),
    )
    return bpy


def _metadata_path(ifc_file: str, suffix: str = ".ifc.metadata.blend") -> str:
    if ifc_file.lower().endswith(".ifc"):
        return ifc_file[:-4] + suffix
    return ifc_file + suffix


def _assert_path_is_data(run: _ScriptRun, marker: Path, expected_paths):
    assert run.error is None, run.error
    assert not marker.exists()
    assert run.saves == list(expected_paths) or run.loads == list(expected_paths)


def test_benign_ifc_filename_is_saved_as_metadata_path(tmp_path):
    ifc_file = str(tmp_path / "plan.ifc")
    runs = []
    real = _patched_subprocess(runs)
    try:
        _run_save_blend_metadata(ifc_file)
    finally:
        _restore_subprocess(*real)

    assert len(runs) == 1
    _assert_path_is_data(runs[0], tmp_path / "absent", [_metadata_path(ifc_file)])


def test_ifc_filename_quote_does_not_run_as_python(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "metadata-marker"
    ifc_file = str(tmp_path / (_quote_payload(marker.name) + ".ifc"))
    runs = []
    real = _patched_subprocess(runs)
    try:
        _run_save_blend_metadata(ifc_file)
    finally:
        _restore_subprocess(*real)

    assert len(runs) == 1
    _assert_path_is_data(runs[0], marker, [_metadata_path(ifc_file)])


def test_export_ifc_runs_metadata_script_for_saved_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "export-marker"
    ifc_file = str(tmp_path / (_quote_payload(marker.name) + ".ifc"))
    (tmp_path / "ignored").mkdir(exist_ok=True)
    runs = []
    called = []
    real = _patched_subprocess(runs)
    try:
        tool, bim_props, prefs, project_props = _host_props()
        bim_props.ifc_file = ""
        prefs.save_metadata_blend_file = True
        project_props.should_save_metadata_for_this_file = True

        def save_metadata():
            called.append(bim_props.ifc_file)
            return _run_save_blend_metadata(bim_props.ifc_file)

        export_execute = _load_function(PROJECT_OPERATOR_PY, "ExportIFC", "_execute")
        namespace = _export_namespace(tool, save_metadata)
        export = types.SimpleNamespace(
            filepath=ifc_file,
            use_relative_path=False,
            skip_recent=True,
            json_version="4",
            json_compact=False,
            report=lambda *args, **kwargs: None,
        )
        export_execute.__globals__.update(namespace)
        export_execute(export, types.SimpleNamespace(scene=types.SimpleNamespace()))
    finally:
        _restore_subprocess(*real)

    assert called == [os.path.normpath(ifc_file).replace("\\", "/")] or called == [ifc_file]
    assert len(runs) == 1
    _assert_path_is_data(runs[0], marker, [_metadata_path(bim_props.ifc_file)])


def test_export_ifc_skips_metadata_script_when_preference_is_off(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "preference-marker"
    ifc_file = str(tmp_path / (_quote_payload(marker.name) + ".ifc"))
    runs = []
    called = []
    real = _patched_subprocess(runs)
    try:
        tool, bim_props, prefs, project_props = _host_props()
        prefs.save_metadata_blend_file = False
        project_props.should_save_metadata_for_this_file = True
        export_execute = _load_function(PROJECT_OPERATOR_PY, "ExportIFC", "_execute")
        export_execute.__globals__.update(_export_namespace(tool, lambda: called.append("save")))
        export = types.SimpleNamespace(
            filepath=ifc_file,
            use_relative_path=False,
            skip_recent=True,
            json_version="4",
            json_compact=False,
            report=lambda *args, **kwargs: None,
        )
        export_execute(export, types.SimpleNamespace(scene=types.SimpleNamespace()))
    finally:
        _restore_subprocess(*real)

    assert called == []
    assert runs == []
    assert not marker.exists()


def test_export_ifc_skips_metadata_script_without_file_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "flag-marker"
    ifc_file = str(tmp_path / (_quote_payload(marker.name) + ".ifc"))
    runs = []
    called = []
    real = _patched_subprocess(runs)
    try:
        tool, bim_props, prefs, project_props = _host_props()
        prefs.save_metadata_blend_file = True
        project_props.should_save_metadata_for_this_file = False
        export_execute = _load_function(PROJECT_OPERATOR_PY, "ExportIFC", "_execute")
        export_execute.__globals__.update(_export_namespace(tool, lambda: called.append("save")))
        export = types.SimpleNamespace(
            filepath=ifc_file,
            use_relative_path=False,
            skip_recent=True,
            json_version="4",
            json_compact=False,
            report=lambda *args, **kwargs: None,
        )
        export_execute(export, types.SimpleNamespace(scene=types.SimpleNamespace()))
    finally:
        _restore_subprocess(*real)

    assert called == []
    assert runs == []
    assert not marker.exists()


def test_linked_ifc_filename_quote_does_not_run_as_python(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "link-marker"
    ifc_path = tmp_path / (_double_quote_payload(marker.name) + ".ifc")
    ifc_path.write_text("ISO-10303-21;\nENDSEC;\nEND-ISO-10303-21;\n", encoding="utf-8")
    runs = []
    real = _patched_subprocess(runs)
    try:
        tool, bim_props, prefs, project_props = _host_props()
        link = types.SimpleNamespace(filepath=str(ifc_path), query="", is_loaded=False)
        project_props.links = [link]
        load_execute = _load_function(PROJECT_OPERATOR_PY, "LoadLink", "_execute")
        link_ifc = _load_function(PROJECT_OPERATOR_PY, "LoadLink", "link_ifc")
        operator = types.SimpleNamespace(
            link_index=0,
            query="",
            use_cache=True,
            report=lambda *args, **kwargs: None,
            set_model_origin_from_link=lambda: None,
            set_georeferencing_indicator=lambda: None,
            link_blend=lambda path: None,
        )
        operator.link_ifc = lambda: link_ifc(operator)
        namespace = {
            "tool": tool,
            "bpy": _operator_bpy(lambda: None),
            "Path": Path,
            "os": os,
            "json": __import__("json"),
            "time": __import__("time"),
            "tempfile": __import__("tempfile"),
            "subprocess": subprocess,
        }
        load_execute.__globals__.update(namespace)
        link_ifc.__globals__.update(namespace)
        result = load_execute(operator, types.SimpleNamespace())
    finally:
        _restore_subprocess(*real)

    assert result != {"CANCELLED"}
    assert len(runs) == 1
    _assert_path_is_data(runs[0], marker, [str(ifc_path)])


def test_document_location_quote_does_not_run_as_python(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    marker = tmp_path / "document-marker"
    document_path = tmp_path / (_quote_payload(marker.name) + ".ifc")
    document_path.write_text("ISO-10303-21;\nENDSEC;\nEND-ISO-10303-21;\n", encoding="utf-8")
    runs = []
    real = _patched_subprocess(runs)
    try:
        convert = _load_function(DOCUMENT_DATA_PY, "ObjectDocumentData", "convert_to_file_uri")
        open_document = _load_function(DOCUMENT_OPERATOR_PY, "OpenIFCDocument", "execute")
        tool, *_ = _host_props()
        convert.__globals__.update({"os": os, "tool": tool})
        uri = convert(str(document_path))
        bpy = _operator_bpy(lambda: None)
        open_document.__globals__.update({"bpy": bpy, "os": os, "subprocess": subprocess})
        operator = types.SimpleNamespace(uri=uri, report=lambda *args, **kwargs: None)
        result = open_document(operator, None)
    finally:
        _restore_subprocess(*real)

    assert result == {"FINISHED"}
    assert len(runs) == 1
    _assert_path_is_data(runs[0], marker, [str(document_path)])


def test_metadata_document_scope_selects_that_document():
    getter = _load_function(PROJECT_TOOL_PY, "Project", "get_metadata_document_information")

    def lookup(ifc_file):
        class Ifc:
            @staticmethod
            def get():
                return ifc_file

        getter.__globals__["tool"] = types.SimpleNamespace(Ifc=Ifc)
        return getter(None)

    assert lookup(None) is None

    plain = ifcopenshell.file(schema="IFC4")
    plain.create_entity("IfcDocumentInformation", Name="Spec", Scope="SPECIFICATION")
    assert lookup(plain) is None

    for schema in ("IFC4", "IFC2X3"):
        ifc_file = ifcopenshell.file(schema=schema)
        kwargs = {"Name": "Blend Metadata", "Scope": "BLEND_METADATA"}
        if schema == "IFC2X3":
            kwargs["DocumentId"] = "BLEND_METADATA"
        else:
            kwargs["Identification"] = "BLEND_METADATA"
        document = ifc_file.create_entity("IfcDocumentInformation", **kwargs)
        found = lookup(ifc_file)
        assert found is not None
        assert found.id() == document.id()
        assert found.Scope == "BLEND_METADATA"


def _run_save_blend_metadata(ifc_file: str):
    tool, bim_props, prefs, project_props = _host_props()
    bim_props.ifc_file = ifc_file
    execute = _load_function(OPERATOR_PY, "SaveBlendMetadataFile", "execute")
    execute.__globals__.update(
        {
            "tool": tool,
            "bpy": _operator_bpy(lambda: None),
            "os": os,
            "tempfile": __import__("tempfile"),
            "subprocess": subprocess,
        }
    )
    operator = types.SimpleNamespace(report=lambda *args, **kwargs: None)
    return execute(operator, None)


def _export_namespace(tool, save_metadata):
    preview_base = types.SimpleNamespace(discard_pending_previews=lambda scene: None)
    settings = types.SimpleNamespace(json_version=None, json_compact=None, logger=None)

    class Factory:
        @staticmethod
        def factory(context, output_file, logger):
            settings.logger = logger
            return settings

    class Exporter:
        def __init__(self, export_settings):
            self.export_settings = export_settings

        def export(self):
            return None

    export_ifc = types.SimpleNamespace(IfcExportSettings=Factory, IfcExporter=Exporter)
    bonsai = types.SimpleNamespace(
        bim=types.SimpleNamespace(handler=types.SimpleNamespace(refresh_ui_data=lambda: None))
    )
    return {
        "tool": tool,
        "bpy": _operator_bpy(save_metadata),
        "os": os,
        "Path": Path,
        "time": __import__("time"),
        "logging": __import__("logging"),
        "tempfile": __import__("tempfile"),
        "preview_base": preview_base,
        "export_ifc": export_ifc,
        "bonsai": bonsai,
    }
