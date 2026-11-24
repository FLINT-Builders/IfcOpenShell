# This file was generated with the assistance of an AI coding tool.
# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 IfcOpenShell contributors
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Open IFC Document must pass the referenced path as data.

These tests fail while ``OpenIFCDocument`` interpolates the path into a
``--python-expr`` string. They pass when that path is data: either an
argument after ``--``, or a ``repr`` embedded so it cannot close the literal.

The child process is not Blender. It is a stand-in for Blender 4.2's
``--python-expr`` handling, which this file implements from the Blender 4.2.0
and CPython 3.11.11 sources cited in ``_write_harness``. The Bonsai operator,
URI conversion, document list, and object-document lookup are the real modules.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import sys
import textwrap
import time
import types
from pathlib import Path

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

REPO = Path(__file__).resolve().parents[4]
BONSAI = REPO / "src" / "bonsai" / "bonsai"
MARKER_ENV = "BONSAI_DOC_MARKER"
LOG_ENV = "BONSAI_DOC_LOAD_LOG"
DONE_ENV = "BONSAI_DOC_DONE"
ERROR_ENV = "BONSAI_DOC_ERROR"

# A quote in the filename closes the single-quoted filepath literal and the
# following expression runs. No slash: it is one path component.
QUOTE_NAME = "a'+open(__import__('os').environ['" + MARKER_ENV + "'],'w').close()+'.ifc"
# The backslash escapes only the first quote. A later quote in the same name
# still closes the literal.
BACKSLASH_QUOTE_NAME = "a\\'+open(__import__('os').environ['" + MARKER_ENV + "'],'w').close()+'.ifc"
NEWLINE_NAME = "line\nbreak.ifc"
BENIGN_NAME = "my model.ifc"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _package(name: str) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        module.__path__ = []
        module.__package__ = name
        sys.modules[name] = module
    parent_name, _, child = name.rpartition(".")
    if parent_name:
        setattr(_package(parent_name), child, module)
    return module


@pytest.fixture(scope="module")
def bonsai_document():
    """Load the real document modules without starting Blender."""
    bpy = types.ModuleType("bpy")
    bpy.__path__ = []
    bpy.app = types.SimpleNamespace(binary_path="", version=(4, 2, 0), version_string="4.2.0")
    bpy.context = types.SimpleNamespace(active_object=None)
    bpy.types = types.ModuleType("bpy.types")

    class _Operator:
        def __init__(self):
            self.report = lambda *args, **kwargs: None

    bpy.types.Operator = _Operator
    bpy.types.Panel = type("Panel", (), {})
    bpy.types.UIList = type("UIList", (), {})
    bpy.props = types.SimpleNamespace(
        StringProperty=lambda **kwargs: None,
        IntProperty=lambda **kwargs: None,
    )
    sys.modules["bpy"] = bpy
    sys.modules["bpy.types"] = bpy.types

    for name in (
        "bonsai",
        "bonsai.bim",
        "bonsai.bim.module",
        "bonsai.bim.module.document",
        "bonsai.core",
        "bonsai.tool",
    ):
        _package(name)
    helper = types.ModuleType("bonsai.bim.helper")
    sys.modules["bonsai.bim.helper"] = helper
    sys.modules["bonsai.bim"].helper = helper

    core_tool = _load("bonsai.core.tool", BONSAI / "core" / "tool.py")
    sys.modules["bonsai.core"].tool = core_tool
    document_tool = _load("bonsai.tool.document", BONSAI / "tool" / "document.py")
    sys.modules["bonsai.tool"].Document = document_tool.Document

    class _IfcOperator:
        pass

    sys.modules["bonsai.tool"].Ifc = types.SimpleNamespace(Operator=_IfcOperator)
    _load("bonsai.core.document", BONSAI / "core" / "document.py")
    data = _load("bonsai.bim.module.document.data", BONSAI / "bim" / "module" / "document" / "data.py")
    operator = _load(
        "bonsai.bim.module.document.operator",
        BONSAI / "bim" / "module" / "document" / "operator.py",
    )
    return types.SimpleNamespace(bpy=bpy, data=data, operator=operator, document_tool=document_tool)


def _write_harness(directory: Path) -> Path:
    """Write a Blender 4.2 ``--python-expr`` stand-in next to a recording ``bpy``.

    Blender 4.2.0 ``source/creator/creator_args.cc`` ``arg_handle_python_expr_run``
    calls ``BPY_run_string_exec(C, nullptr, argv[1])``. ``source/blender/python/intern/bpy_interface_run.cc``
    ``bpy_run_string_impl`` calls ``PyRun_String(expr, Py_file_input, py_dict, py_dict)``.
    CPython 3.11.11 ``Python/pythonrun.c`` ``PyRun_String`` / ``PyRun_StringFlags`` /
    ``run_mod`` compile that string and evaluate it. ``source/blender/blenlib/intern/BLI_args.c``
    ``BLI_args_parse`` passes the next argv element through unchanged and stops when
    ``--`` returns -1 (``arg_handle_arguments_end``). ``source/blender/python/intern/bpy_interface.cc``
    ``BPY_python_start`` installs the full argv as ``sys.argv`` with ``parse_argv = 0``.
    """
    stub = directory / "bpy_stub" / "bpy"
    stub.mkdir(parents=True)
    (stub / "__init__.py").write_text(
        textwrap.dedent(
            """\
            import os

            class _Bim:
                @staticmethod
                def load_project(filepath=""):
                    dest = os.environ.get("BONSAI_DOC_LOAD_LOG")
                    if dest:
                        with open(dest, "w", encoding="utf-8") as handle:
                            handle.write(filepath)

            class _Ops:
                bim = _Bim()

            ops = _Ops()
            """
        ),
        encoding="utf-8",
    )
    harness = directory / "blender_harness.py"
    harness.write_text(
        "#!/usr/bin/env python3\n"
        + textwrap.dedent(
            """\
            # This file was generated with the assistance of an AI coding tool.
            import os
            import sys
            import traceback
            from pathlib import Path

            sys.path.insert(0, str(Path(__file__).with_name("bpy_stub")))


            def run(argv):
                index = 1
                while index < len(argv):
                    arg = argv[index]
                    if arg == "--":
                        break
                    if arg == "--python-expr":
                        expr = argv[index + 1]
                        namespace = {"__name__": "<blender string>"}
                        exec(compile(expr, "<blender string>", "exec"), namespace, namespace)
                        index += 2
                        continue
                    index += 1
                return 0


            if __name__ == "__main__":
                code = 0
                try:
                    code = run(sys.argv)
                except Exception:
                    dest = os.environ.get("BONSAI_DOC_ERROR")
                    if dest:
                        with open(dest, "w", encoding="utf-8") as handle:
                            handle.write(traceback.format_exc())
                    code = 1
                finally:
                    dest = os.environ.get("BONSAI_DOC_DONE")
                    if dest:
                        with open(dest, "a", encoding="utf-8") as handle:
                            handle.write("done\\n")
                raise SystemExit(code)
            """
        ),
        encoding="utf-8",
    )
    harness.chmod(harness.stat().st_mode | stat.S_IEXEC)
    return harness


def _ifc_with_document(schema: str, kind: str, location: str, ifc_path: Path):
    ifc = ifcopenshell.file(schema=schema)
    ifc.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Project")
    wall = ifc.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="Wall")
    if kind == "reference":
        document = ifc.create_entity("IfcDocumentReference", Location=location, Name="Reference")
    else:
        document = ifc.create_entity("IfcDocumentInformation", Name="Information", Location=location)
    ifc.create_entity(
        "IfcRelAssociatesDocument",
        GlobalId=ifcopenshell.guid.new(),
        RelatingDocument=document,
        RelatedObjects=[wall],
    )
    ifc.write(str(ifc_path))
    opened = ifcopenshell.open(str(ifc_path))
    opened_wall = opened.by_type("IfcWall")[0]
    opened_document = opened.by_type("IfcDocumentReference" if kind == "reference" else "IfcDocumentInformation")[0]
    assert opened_document.Location == location
    return opened, opened_wall, opened_document


def _object_panel_uri(loaded, ifc_path: str, wall) -> str:
    """Same URI the object Documents panel assigns. See ui.py draw()."""
    tool = sys.modules["bonsai.tool"]
    bpy = sys.modules["bpy"]
    tool.Ifc.get_path = lambda: ifc_path
    tool.Ifc.get_schema = lambda: wall.file.schema
    tool.Ifc.get_entity = lambda obj: wall.file.by_id(obj.ifc_definition_id)
    bpy.context.active_object = types.SimpleNamespace(ifc_definition_id=wall.id())
    loaded.data.ObjectDocumentData.is_loaded = False
    documents = loaded.data.ObjectDocumentData.documents()
    assert len(documents) == 1
    location = documents[0]["location"]
    assert location
    assert location.lower().endswith(".ifc")
    return location


def _project_list_uri(loaded, ifc_path: str, document) -> str:
    """Same URI the project document list assigns. See ui.py draw_item()."""
    tool = sys.modules["bonsai.tool"]
    tool.Ifc.get_path = lambda: ifc_path

    class _Documents:
        def __init__(self):
            self.items = []

        def add(self):
            item = types.SimpleNamespace(
                ifc_definition_id=0,
                document_type="",
                tree_depth=0,
                name="",
                identification="",
                description="",
                location="",
                has_children=False,
                is_expanded=False,
            )
            self.items.append(item)
            return item

    props = types.SimpleNamespace(documents=_Documents())
    loaded.document_tool.Document._process_document(document, props, {}, [], 1)
    item = props.documents.items[-1]
    assert item.location == (document.Location or "")
    assert item.location.lower().endswith(".ifc")
    return loaded.data.ObjectDocumentData.convert_to_file_uri(item.location)


def _open(loaded, uri: str, directory: Path, monkeypatch: pytest.MonkeyPatch):
    marker = directory / "injection-marker"
    log_path = directory / "load-project.txt"
    done_path = directory / "harness-done.txt"
    error_path = directory / "harness-error.txt"
    for path in (marker, log_path, done_path, error_path):
        if path.exists():
            path.unlink()
    harness = _write_harness(directory)
    monkeypatch.setenv(MARKER_ENV, str(marker))
    monkeypatch.setenv(LOG_ENV, str(log_path))
    monkeypatch.setenv(DONE_ENV, str(done_path))
    monkeypatch.setenv(ERROR_ENV, str(error_path))
    loaded.bpy.app.binary_path = str(harness)

    operator = loaded.operator.OpenIFCDocument()
    operator.uri = uri
    operator.report = lambda *args, **kwargs: None
    result = operator.execute(None)

    deadline = time.time() + 5
    while time.time() < deadline and not done_path.exists():
        time.sleep(0.02)
    error = error_path.read_text(encoding="utf-8") if error_path.exists() else ""
    recorded = log_path.read_text(encoding="utf-8") if log_path.exists() else None
    return result, marker, recorded, done_path.exists(), error


def _assert_path_is_data(loaded, uri: str, expected: str, directory: Path, monkeypatch):
    assert uri[7:] == expected
    result, marker, recorded, done, error = _open(loaded, uri, directory, monkeypatch)
    assert result == {"FINISHED"}
    assert done, error or "the Blender stand-in did not run"
    assert not marker.exists(), "document path ran as Python: " + error
    assert recorded == expected, (recorded, expected, error)


@pytest.mark.parametrize(
    ("schema", "kind", "entry"),
    [
        ("IFC4", "reference", "object"),
        ("IFC4", "reference", "project"),
        ("IFC4", "information", "object"),
        ("IFC4", "information", "project"),
    ],
)
def test_quoted_document_name_is_not_executed(bonsai_document, tmp_path, monkeypatch, schema, kind, entry):
    ifc_path = tmp_path / "project.ifc"
    target = tmp_path / QUOTE_NAME
    target.write_bytes(b"ISO-10303-21;\n")
    _opened, wall, document = _ifc_with_document(schema, kind, QUOTE_NAME, ifc_path)
    uri = (
        _object_panel_uri(bonsai_document, str(ifc_path), wall)
        if entry == "object"
        else _project_list_uri(bonsai_document, str(ifc_path), document)
    )
    expected = os.path.abspath(os.path.join(os.path.dirname(str(ifc_path)), QUOTE_NAME))
    assert os.path.exists(expected)
    _assert_path_is_data(bonsai_document, uri, expected, tmp_path / "run", monkeypatch)


def test_backslash_before_quote_is_not_executed(bonsai_document, tmp_path, monkeypatch):
    ifc_path = tmp_path / "project.ifc"
    (tmp_path / BACKSLASH_QUOTE_NAME).write_bytes(b"ISO-10303-21;\n")
    _opened, wall, _document = _ifc_with_document("IFC4", "reference", BACKSLASH_QUOTE_NAME, ifc_path)
    uri = _object_panel_uri(bonsai_document, str(ifc_path), wall)
    expected = os.path.abspath(os.path.join(str(tmp_path), BACKSLASH_QUOTE_NAME))
    _assert_path_is_data(bonsai_document, uri, expected, tmp_path / "run", monkeypatch)


def test_newline_in_document_name_reaches_load_project(bonsai_document, tmp_path, monkeypatch):
    ifc_path = tmp_path / "project.ifc"
    (tmp_path / NEWLINE_NAME).write_bytes(b"ISO-10303-21;\n")
    _opened, wall, _document = _ifc_with_document("IFC4", "reference", NEWLINE_NAME, ifc_path)
    uri = _object_panel_uri(bonsai_document, str(ifc_path), wall)
    expected = os.path.abspath(os.path.join(str(tmp_path), NEWLINE_NAME))
    _assert_path_is_data(bonsai_document, uri, expected, tmp_path / "run", monkeypatch)


def test_ordinary_document_name_is_passed_unchanged(bonsai_document, tmp_path, monkeypatch):
    ifc_path = tmp_path / "project.ifc"
    (tmp_path / BENIGN_NAME).write_bytes(b"ISO-10303-21;\n")
    _opened, wall, document = _ifc_with_document("IFC4", "reference", BENIGN_NAME, ifc_path)
    object_uri = _object_panel_uri(bonsai_document, str(ifc_path), wall)
    project_uri = _project_list_uri(bonsai_document, str(ifc_path), document)
    assert object_uri == project_uri
    expected = os.path.abspath(os.path.join(str(tmp_path), BENIGN_NAME))
    _assert_path_is_data(bonsai_document, object_uri, expected, tmp_path / "run", monkeypatch)


def test_missing_document_does_not_start_blender(bonsai_document, tmp_path, monkeypatch):
    ifc_path = tmp_path / "project.ifc"
    _opened, wall, _document = _ifc_with_document("IFC4", "reference", QUOTE_NAME, ifc_path)
    uri = _object_panel_uri(bonsai_document, str(ifc_path), wall)
    result, marker, recorded, done, error = _open(bonsai_document, uri, tmp_path / "run", monkeypatch)
    assert result == {"CANCELLED"}
    assert recorded is None
    assert not done
    assert not marker.exists()
    assert error == ""
