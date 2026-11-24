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

"""Untrusted IFC and BCF links must not reach the operating-system open action.

These tests fail while OpenUri hands project-controlled values to
webbrowser.open. On Windows that call uses os.startfile, which is ShellExecute.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import textwrap
import types as pytypes
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

SRC = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SRC / "bonsai"))
sys.path.insert(0, str(SRC / "bcf"))

# Document extensions a later fix may still open from inside the project folder.
# Executable and script extensions, UNC targets, and non-http(s) schemes are not.
_ALLOWED_FILE_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".txt", ".docx"}


def _flexible_class(name: str):
    return type(name, (), {})


class _BpyTypes:
    class Operator:
        def __init__(self, *args, **kwargs):
            pass

    class Panel:
        pass

    class UIList:
        pass

    class PropertyGroup:
        pass

    def __getattr__(self, name: str):
        cls = _flexible_class(name)
        setattr(self, name, cls)
        return cls


class _BpyProps:
    def __getattr__(self, name: str):
        def factory(*args, **kwargs):
            return None

        return factory


class _Bpy:
    types = _BpyTypes()
    props = _BpyProps()
    app = pytypes.SimpleNamespace(
        version=(4, 2, 0),
        version_string="4.2.0",
        timers=pytypes.SimpleNamespace(register=lambda *args, **kwargs: None),
    )
    context = pytypes.SimpleNamespace(active_object=None, scene=pytypes.SimpleNamespace())
    data = pytypes.SimpleNamespace(is_saved=False, filepath="", objects=[])
    path = pytypes.SimpleNamespace(abspath=lambda path: path)
    utils = pytypes.SimpleNamespace(
        previews=pytypes.SimpleNamespace(),
        user_resource=lambda *args, **kwargs: "/tmp",
    )
    ops = pytypes.SimpleNamespace()


def _install_bpy() -> _Bpy:
    bpy = _Bpy()
    module = pytypes.ModuleType("bpy")
    module.__path__ = []
    types_module = pytypes.ModuleType("bpy.types")
    for name in dir(bpy.types):
        if name.startswith("_"):
            continue
        setattr(types_module, name, getattr(bpy.types, name))
    types_module.__getattr__ = lambda name: getattr(bpy.types, name)
    props_module = pytypes.ModuleType("bpy.props")
    props_module.__getattr__ = lambda name: getattr(bpy.props, name)
    module.types = types_module
    module.props = props_module
    module.app = bpy.app
    module.context = bpy.context
    module.data = bpy.data
    module.path = bpy.path
    module.utils = bpy.utils
    module.ops = bpy.ops
    sys.modules["bpy"] = module
    sys.modules["bpy.types"] = types_module
    sys.modules["bpy.props"] = props_module
    extras = pytypes.ModuleType("bpy_extras")
    extras.__path__ = []
    io_utils = pytypes.ModuleType("bpy_extras.io_utils")
    io_utils.ImportHelper = type("ImportHelper", (), {})
    io_utils.ExportHelper = type("ExportHelper", (), {})
    sys.modules["bpy_extras"] = extras
    sys.modules["bpy_extras.io_utils"] = io_utils
    mathutils = pytypes.ModuleType("mathutils")
    mathutils.Euler = type("Euler", (), {})
    mathutils.Vector = type("Vector", (), {})
    mathutils.Matrix = type("Matrix", (), {})
    sys.modules["mathutils"] = mathutils
    sys.modules["bmesh"] = pytypes.ModuleType("bmesh")
    return bpy


class _Flexible:
    def __getattr__(self, name: str):
        return ""

    def __call__(self, *args, **kwargs):
        return _Flexible()


class _ToolModule(pytypes.ModuleType):
    def __getattr__(self, name: str):
        value = _Flexible()
        setattr(self, name, value)
        return value


def _ensure_package(name: str, path: Path | None) -> pytypes.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    module = _ToolModule(name) if name == "bonsai.tool" else pytypes.ModuleType(name)
    module.__package__ = name
    if path is not None:
        module.__path__ = [str(path)]
    if "." in name:
        parent_name, child = name.rsplit(".", 1)
        parent = sys.modules[parent_name]
        setattr(parent, child, module)
    sys.modules[name] = module
    return module


def _load(qualname: str, path: Path):
    spec = importlib.util.spec_from_file_location(qualname, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = qualname.rpartition(".")[0]
    sys.modules[qualname] = module
    parent_name, child = qualname.rsplit(".", 1)
    setattr(sys.modules[parent_name], child, module)
    spec.loader.exec_module(module)
    return module


class _Collection(list):
    def add(self):
        item = pytypes.SimpleNamespace()
        self.append(item)
        return item

    def clear(self):
        super().clear()

    def remove(self, index):
        del self[index]


class _Layout:
    def __init__(self):
        self.operators: list[pytypes.SimpleNamespace] = []
        self.alignment = "LEFT"

    def row(self, align=False):
        return self

    def column(self, align=False):
        return self

    def box(self):
        return self

    def split(self, factor=0.5):
        return self

    def label(self, **kwargs):
        return self

    def prop(self, *args, **kwargs):
        return self

    def separator(self):
        return None

    def template_list(self, *args, **kwargs):
        return None

    def operator(self, operator_id, **kwargs):
        operator = pytypes.SimpleNamespace(bl_idname=operator_id, uri=None, index=None, entity_type=None)
        self.operators.append(operator)
        return operator


def _prepare_modules(bpy: _Bpy):
    root = SRC
    _ensure_package("bonsai", root / "bonsai" / "bonsai")
    _ensure_package("bonsai.bim", root / "bonsai" / "bonsai" / "bim")
    _ensure_package("bonsai.bim.module", root / "bonsai" / "bonsai" / "bim" / "module")
    _ensure_package("bonsai.bim.module.document", root / "bonsai" / "bonsai" / "bim" / "module" / "document")
    _ensure_package(
        "bonsai.bim.module.classification",
        root / "bonsai" / "bonsai" / "bim" / "module" / "classification",
    )
    _ensure_package("bonsai.bim.module.bcf", root / "bonsai" / "bonsai" / "bim" / "module" / "bcf")
    _ensure_package("bonsai.tool", root / "bonsai" / "bonsai" / "tool")
    _ensure_package("bonsai.core", root / "bonsai" / "bonsai" / "core")

    helper = _ensure_package("bonsai.bim.helper", None)
    helper.draw_attributes = lambda *args, **kwargs: None
    helper.get_enum_items = lambda *args, **kwargs: []
    handler = _ensure_package("bonsai.bim.handler", None)
    prop = _ensure_package("bonsai.bim.prop", None)
    prop.StrProperty = type("StrProperty", (), {})
    ui = _ensure_package("bonsai.bim.ui", None)
    ui.IFCFileSelector = type("IFCFileSelector", (), {})
    import_ifc = _ensure_package("bonsai.bim.import_ifc", None)

    ifc_mod = _ensure_package("bonsai.bim.ifc", None)

    class IfcStore:
        path = ""
        file = None
        classification_file = None

        @staticmethod
        def get_file():
            return IfcStore.file

        @staticmethod
        def set_path(value: str) -> None:
            IfcStore.path = value

    ifc_mod.IfcStore = IfcStore

    core_tool = _load("bonsai.core.tool", root / "bonsai" / "bonsai" / "core" / "tool.py")
    document_tool = _load("bonsai.tool.document", root / "bonsai" / "bonsai" / "tool" / "document.py")
    bcf_tool = _load("bonsai.tool.bcf", root / "bonsai" / "bonsai" / "tool" / "bcf.py")
    sys.modules["bonsai.tool"].Document = document_tool.Document
    sys.modules["bonsai.tool"].Bcf = bcf_tool.Bcf
    sys.modules["bonsai.tool"].Ifc = pytypes.SimpleNamespace()
    class _Blender(_Flexible):
        BLENDER_ENUM_ITEMS = tuple
        operator_invoke_filepath_hotkeys_description = "hotkeys"

        @staticmethod
        def get_ifc_definition_id(obj):
            return getattr(obj, "ifc_definition_id", None)

        @staticmethod
        def get_object_bim_props(obj):
            return pytypes.SimpleNamespace()

    sys.modules["bonsai.tool"].Blender = _Blender()

    document_data = _load(
        "bonsai.bim.module.document.data",
        root / "bonsai" / "bonsai" / "bim" / "module" / "document" / "data.py",
    )
    bcfstore = _load(
        "bonsai.bim.module.bcf.bcfstore",
        root / "bonsai" / "bonsai" / "bim" / "module" / "bcf" / "bcfstore.py",
    )
    document_ui = _load(
        "bonsai.bim.module.document.ui",
        root / "bonsai" / "bonsai" / "bim" / "module" / "document" / "ui.py",
    )
    classification_data = _load(
        "bonsai.bim.module.classification.data",
        root / "bonsai" / "bonsai" / "bim" / "module" / "classification" / "data.py",
    )
    classification_ui = _load(
        "bonsai.bim.module.classification.ui",
        root / "bonsai" / "bonsai" / "bim" / "module" / "classification" / "ui.py",
    )
    bcf_ui = _load(
        "bonsai.bim.module.bcf.ui",
        root / "bonsai" / "bonsai" / "bim" / "module" / "bcf" / "ui.py",
    )
    operator_source = (root / "bonsai" / "bonsai" / "bim" / "operator.py").read_text()
    start = operator_source.index("class OpenUri(")
    end = operator_source.index("class OpenPath(")
    operator_namespace = {"bpy": sys.modules["bpy"], "webbrowser": webbrowser}
    exec(operator_source[start:end], operator_namespace)
    operator = pytypes.ModuleType("bonsai.bim.operator")
    operator.OpenUri = operator_namespace["OpenUri"]
    operator.webbrowser = webbrowser
    sys.modules["bonsai.bim.operator"] = operator
    return pytypes.SimpleNamespace(
        bpy=bpy,
        IfcStore=IfcStore,
        core_tool=core_tool,
        document_tool=document_tool,
        bcf_tool=bcf_tool,
        document_data=document_data,
        document_ui=document_ui,
        classification_data=classification_data,
        classification_ui=classification_ui,
        bcf_ui=bcf_ui,
        bcfstore=bcfstore,
        operator=operator,
        import_ifc=import_ifc,
        handler=handler,
    )


@pytest.fixture(scope="module")
def bonsai_modules():
    bpy = _install_bpy()
    return _prepare_modules(bpy)


def _windows_default_class():
    """Load the WindowsDefault controller from the stdlib webbrowser that is installed here.

    Blender 4.2 through 5.0 embed CPython 3.11, whose WindowsDefault.open also calls
    os.startfile and does not apply _check_url. The class executed below is the copy
    shipped with this interpreter (3.12), which calls os.startfile after rejecting only
    a leading dash.
    """
    source = Path(webbrowser.__file__).read_text()
    start = source.index("    class WindowsDefault")
    end = source.index("#\n# Platform support for MacOS", start)
    block = textwrap.dedent(source[start:end])
    namespace = {"os": os, "sys": sys, "BaseBrowser": webbrowser.BaseBrowser}
    exec(block, namespace)
    return namespace["WindowsDefault"]


@pytest.fixture
def launcher(monkeypatch):
    launched: list[str] = []

    def startfile(path, *args, **kwargs):
        launched.append(os.fsdecode(path) if isinstance(path, bytes) else path)

    monkeypatch.setattr(os, "startfile", startfile, raising=False)
    windows_default = _windows_default_class()
    webbrowser.register("windows-default-test", windows_default, instance=windows_default(), preferred=True)
    monkeypatch.setattr(webbrowser, "_tryorder", ["windows-default-test"])

    def popen(*args, **kwargs):
        launched.append(repr(args))
        raise AssertionError("subprocess.Popen was invoked")

    monkeypatch.setattr("subprocess.Popen", popen)
    yield launched
    webbrowser._tryorder = None


def _file_uri_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme.lower() != "file":
        return None
    netloc = unquote(parsed.netloc)
    raw_path = unquote(parsed.path)
    if netloc and len(netloc) >= 2 and netloc[1] == ":" and not raw_path:
        return Path(netloc)
    if netloc and netloc.lower() not in {"localhost"}:
        return Path("//" + netloc + raw_path)
    if len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
        raw_path = raw_path[1:]
    return Path(raw_path)


def _assert_launch_allowed(uri: str, project_dir: Path | None) -> None:
    """http and https may be opened. A file URI may be opened only for an allowlisted
    document that stays inside the project directory and is not a symlink.
    """
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    if scheme in {"http", "https"}:
        if not parsed.netloc or "\\" in uri or parsed.netloc.startswith("."):
            raise AssertionError(f"unsafe http(s) target {uri!r}")
        return
    if scheme == "file" and project_dir is not None:
        netloc = unquote(parsed.netloc)
        drive_in_netloc = len(netloc) >= 2 and netloc[1] == ":"
        if netloc and netloc.lower() not in {"localhost"} and not drive_in_netloc:
            raise AssertionError(f"remote file target {uri!r}")
        path = _file_uri_path(uri)
        if path is None or path.suffix.lower() not in _ALLOWED_FILE_SUFFIXES:
            raise AssertionError(f"file target is not an allowlisted document {uri!r}")
        if path.is_symlink():
            raise AssertionError(f"file target is a symlink {uri!r}")
        try:
            path.relative_to(project_dir)
        except ValueError as exc:
            raise AssertionError(f"file target is outside the project {uri!r}") from exc
        return
    raise AssertionError(f"refused to launch {uri!r}")


def _click(modules, uri: str):
    operator = modules.operator.OpenUri()
    operator.uri = uri
    return operator.execute(modules.bpy.context)


def _open_uris(layout: _Layout) -> list[str]:
    return [operator.uri for operator in layout.operators if operator.bl_idname == "bim.open_uri"]


def _assert_nothing_dangerous(launched: list[str], project_dir: Path | None) -> None:
    for uri in launched:
        _assert_launch_allowed(uri, project_dir)


def _click_all(modules, uris: list[str], launched: list[str], project_dir: Path | None) -> None:
    failures = []
    for uri in uris:
        launched.clear()
        _click(modules, uri)
        try:
            _assert_nothing_dangerous(launched, project_dir)
        except AssertionError as exc:
            failures.append(str(exc))
    assert not failures, "\n".join(failures)


def _write_ifc(path: Path, location: str, classification_location: str):
    import ifcopenshell
    import ifcopenshell.guid

    model = ifcopenshell.file(schema="IFC4")
    project = model.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Project")
    wall = model.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="Wall")
    information = model.create_entity(
        "IfcDocumentInformation",
        Identification="DOC",
        Name="Spec",
        Location=location,
    )
    reference = model.create_entity(
        "IfcDocumentReference",
        Identification="REF",
        Location=location,
        ReferencedDocument=information,
    )
    model.create_entity(
        "IfcRelAssociatesDocument",
        GlobalId=ifcopenshell.guid.new(),
        RelatingDocument=reference,
        RelatedObjects=[wall],
    )
    model.create_entity(
        "IfcRelAssociatesDocument",
        GlobalId=ifcopenshell.guid.new(),
        RelatingDocument=information,
        RelatedObjects=[project],
    )
    classification = model.create_entity("IfcClassification", Name="System", Location=classification_location)
    class_reference = model.create_entity(
        "IfcClassificationReference",
        Identification="ID",
        Name="Name",
        Location=classification_location,
        ReferencedSource=classification,
    )
    model.create_entity(
        "IfcRelAssociatesClassification",
        GlobalId=ifcopenshell.guid.new(),
        RelatingClassification=class_reference,
        RelatedObjects=[wall],
    )
    model.write(str(path))
    return ifcopenshell.open(str(path))


def _bind_ifc(modules, ifc_file, ifc_path: Path, wall_id: int):
    modules.IfcStore.file = ifc_file
    modules.IfcStore.path = str(ifc_path)
    tool = sys.modules["bonsai.tool"]

    def get_entity(obj):
        if not obj or not getattr(obj, "ifc_definition_id", None):
            return None
        return ifc_file.by_id(obj.ifc_definition_id)

    tool.Ifc.get = lambda: ifc_file
    tool.Ifc.get_path = lambda: str(ifc_path)
    tool.Ifc.get_schema = lambda: ifc_file.schema
    tool.Ifc.get_entity = get_entity
    tool.Ifc.get_object_by_identifier = lambda identifier: object()
    wall = pytypes.SimpleNamespace(ifc_definition_id=wall_id, name="Wall")
    modules.bpy.context.active_object = wall
    sys.modules["bpy"].context.active_object = wall
    return wall


def _document_locations(modules) -> list[str]:
    data = modules.document_data.ObjectDocumentData
    data.is_loaded = False
    data.load()
    return [document["location"] for document in data.data["documents"] if document["location"]]


def _document_list_uris(modules, location: str) -> list[str]:
    item = pytypes.SimpleNamespace(
        document_type="REFERENCE",
        tree_depth=1,
        has_children=False,
        is_expanded=False,
        location=location,
        description="Spec",
        name="Spec",
        identification="REF",
    )
    layout = _Layout()
    modules.document_ui.BIM_UL_documents().draw_item(None, layout, None, item, None, None, None)
    return _open_uris(layout)


def _object_panel_uris(modules) -> list[str]:
    panel = modules.document_ui.BIM_PT_object_documents()
    panel.layout = _Layout()
    props = pytypes.SimpleNamespace(
        is_object_editing=True,
        active_document=pytypes.SimpleNamespace(document_type="REFERENCE", ifc_definition_id=0),
        documents=[],
        active_document_index=0,
    )
    sys.modules["bonsai.tool"].Document.get_document_props = lambda: props
    modules.document_data.ObjectDocumentData.is_loaded = False
    panel.draw(modules.bpy.context)
    return _open_uris(panel.layout)


def _classification_uris(modules) -> list[str]:
    data = modules.classification_data.ObjectClassificationsData
    data.is_loaded = False
    data.load()
    panel = modules.classification_ui.ReferenceUI()
    panel.layout = _Layout()
    panel.file = sys.modules["bonsai.tool"].Ifc.get()
    panel.props = pytypes.SimpleNamespace(active_reference_id=0)
    panel.obj = "Wall"
    panel.data = pytypes.SimpleNamespace(obj_type="Object")
    for reference in data.data["references"]:
        panel.draw_reference_ui(reference)
    return _open_uris(panel.layout)


def _save_and_load_bcf(path: Path, version: str, targets: dict[str, str]):
    if version == "2":
        import bcf.v2.model as model
        from bcf.v2.bcfxml import BcfXml

        bcfxml = BcfXml.create_new("Attack project")
        topic = bcfxml.add_topic("Issue", "Open the link", "attacker@example.com")
        topic.topic.reference_link = [targets["reference_link"]]
        topic.topic.bim_snippet = model.BimSnippet(
            reference=targets["snippet"],
            reference_schema=targets["schema"],
            snippet_type="bcf",
            is_external=True,
        )
        topic.topic.document_reference = [
            model.TopicDocumentReference(
                referenced_document=targets["document"],
                description="Manual",
                is_external=True,
            )
        ]
        topic.header = model.Header(
            file=[
                model.HeaderFile(
                    filename="payload.hta",
                    reference=targets["header"],
                    is_external=True,
                )
            ]
        )
    else:
        import bcf.v3.model as model
        from bcf.v3.bcfxml import BcfXml

        bcfxml = BcfXml.create_new("Attack project")
        topic = bcfxml.add_topic("Issue", "Open the link", "attacker@example.com")
        topic.topic.reference_links = model.TopicReferenceLinks(reference_link=[targets["reference_link"]])
        topic.topic.bim_snippet = model.BimSnippet(
            reference=targets["snippet"],
            reference_schema=targets["schema"],
            snippet_type="bcf",
            is_external=True,
        )
        topic.topic.document_references = model.TopicDocumentReferences(
            document_reference=[
                model.DocumentReference(
                    guid=str(uuid.uuid4()),
                    url=targets["document"],
                    description="Manual",
                )
            ]
        )
        topic.header = model.Header(
            files=model.HeaderFiles(
                file=[
                    model.File(
                        filename="payload.hta",
                        reference=targets["header"],
                        is_external=True,
                    )
                ]
            )
        )
    bcfxml.save(path)
    return type(bcfxml).load(path)


def _bcf_open_uris(modules, bcfxml) -> list[str]:
    topic_handler = next(iter(bcfxml.topics.values()))
    blender_topic = pytypes.SimpleNamespace(
        name=topic_handler.guid,
        reference_links=_Collection(),
        labels=_Collection(),
        document_references=_Collection(),
        related_topics=_Collection(),
        bim_snippet=pytypes.SimpleNamespace(reference="", schema="", type="", is_external=False),
    )
    for link in modules.bcf_tool.Bcf.get_topic_reference_links(topic_handler):
        item = blender_topic.reference_links.add()
        item.name = link
    snippet = topic_handler.topic.bim_snippet
    if snippet:
        blender_topic.bim_snippet.type = snippet.snippet_type
        blender_topic.bim_snippet.is_external = snippet.is_external
        blender_topic.bim_snippet.reference = snippet.reference
        blender_topic.bim_snippet.schema = snippet.reference_schema
    for document in modules.bcf_tool.Bcf.get_topic_document_references(topic_handler):
        if document.__class__.__name__ == "TopicDocumentReference":
            reference = document.referenced_document
            is_external = document.is_external
        else:
            is_external = document.document_guid is None
            reference = document.url if is_external else document.document_guid
        item = blender_topic.document_references.add()
        item.reference = reference
        item.description = document.description
        item.is_external = is_external
    props = pytypes.SimpleNamespace(
        active_topic_index=0,
        topics=[blender_topic],
        active_topic=blender_topic,
        file_reference="",
        file_ifc_project="",
        file_ifc_spatial_structure_element="",
        reference_link="",
        label="",
        bim_snippet_reference="",
        bim_snippet_type="",
        bim_snippet_schema="",
        document_reference="",
        document_reference_description="",
        document_description="",
        bcf_file="",
    )
    sys.modules["bonsai.tool"].Bcf.get_bcf_props = lambda: props
    modules.bcfstore.BcfStore.bcfxml = bcfxml
    panel = modules.bcf_ui.BIM_PT_bcf_metadata()
    panel.layout = _Layout()
    panel.draw(modules.bpy.context)
    modules.bcfstore.BcfStore.bcfxml = None
    return _open_uris(panel.layout)


class TestOpenUriLauncher:
    def test_https_and_http_still_open(self, bonsai_modules, launcher, tmp_path):
        for uri in ("https://example.com/specification.pdf", "http://example.com/help"):
            launcher.clear()
            _click(bonsai_modules, uri)
            assert launcher == [uri]

    def test_rejects_script_file_uri_and_custom_scheme(self, bonsai_modules, launcher, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        targets = [
            (project / "payload.hta").as_uri(),
            (project / "payload.bat").as_uri(),
            (project / "payload.cmd").as_uri(),
            (project / "payload.exe").as_uri(),
            (project / "payload.ps1").as_uri(),
            (project / "payload.vbs").as_uri(),
            (project / "payload.js").as_uri(),
            (project / "payload.lnk").as_uri(),
            (project / "payload.HTA").as_uri(),
            (project / "report.pdf.hta").as_uri(),
            "file://attacker.example/share/payload.hta",
            "custom-scheme:payload.hta",
            "javascript:payload",
        ]
        _click_all(bonsai_modules, targets, launcher, project)

    def test_second_path_lookup_is_not_what_gets_launched(self, bonsai_modules, launcher, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        safe = project / "report.pdf"
        safe.write_bytes(b"%PDF-1.4\n")
        payload = project / "payload.hta"
        payload.write_text("<hta:application />", encoding="utf-8")
        lookups = {"abspath": 0, "resolve": 0}
        real_abspath = os.path.abspath
        real_resolve = Path.resolve

        def flipping_abspath(path):
            lookups["abspath"] += 1
            if lookups["abspath"] == 1:
                return str(safe)
            return str(payload)

        def flipping_resolve(self, *args, **kwargs):
            lookups["resolve"] += 1
            if lookups["resolve"] == 1:
                return real_resolve(self, *args, **kwargs)
            return payload

        os.path.abspath = flipping_abspath
        Path.resolve = flipping_resolve
        try:
            _click(bonsai_modules, "report.pdf")
        finally:
            os.path.abspath = real_abspath
            Path.resolve = real_resolve
        for uri in launcher:
            assert "payload.hta" not in uri.replace("\\", "/").lower()
            _assert_launch_allowed(uri, project)


class TestIfcDocumentAndClassificationLinks:
    def test_relative_document_beside_ifc_is_not_launched(self, bonsai_modules, launcher, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        ifc_path = project / "model.ifc"
        payload = project / "payload.hta"
        payload.write_text("<hta:application />", encoding="utf-8")
        ifc_file = _write_ifc(ifc_path, "payload.hta", r"\\attacker.example\share\x.hta")
        wall = ifc_file.by_type("IfcWall")[0]
        _bind_ifc(bonsai_modules, ifc_file, ifc_path, wall.id())

        object_uris = _document_locations(bonsai_modules)
        assert object_uris
        assert any(uri.startswith("file:") and uri.endswith("payload.hta") for uri in object_uris)
        panel_uris = _object_panel_uris(bonsai_modules)
        list_uris = _document_list_uris(bonsai_modules, "payload.hta")
        classification_uris = _classification_uris(bonsai_modules)
        assert classification_uris == [r"\\attacker.example\share\x.hta"]

        _click_all(
            bonsai_modules,
            object_uris + panel_uris + list_uris + classification_uris,
            launcher,
            project,
        )

    def test_windows_relative_location_becomes_file_uri_next_to_ifc(
        self, bonsai_modules, launcher, tmp_path, monkeypatch
    ):
        import ntpath

        project = tmp_path / "project"
        project.mkdir()
        data = bonsai_modules.document_data
        real_os = data.os

        class _WindowsOs:
            def __getattr__(self, name):
                if name == "path":
                    return ntpath
                return getattr(real_os, name)

        monkeypatch.setattr(data, "os", _WindowsOs())
        sys.modules["bonsai.tool"].Ifc.get_path = lambda: r"C:\proj\model.ifc"
        uri = data.ObjectDocumentData.convert_to_file_uri("payload.hta")
        assert uri == r"file://C:\proj\payload.hta"
        unc = data.ObjectDocumentData.convert_to_file_uri(r"\\attacker.example\share\x.hta")
        assert unc.startswith("file://")
        assert "attacker.example" in unc
        _click_all(
            bonsai_modules,
            [uri, unc, r"C:\proj\payload.bat", r"\\attacker.example\share\x.hta"],
            launcher,
            Path(r"C:\proj"),
        )


class TestBcfLinks:
    @pytest.mark.parametrize("version", ["2", "3"])
    def test_external_bcf_links_are_not_launched(self, bonsai_modules, launcher, tmp_path, version):
        project = tmp_path / "project"
        project.mkdir()
        targets = {
            "reference_link": r"\\attacker.example\share\x.hta",
            "snippet": r"C:\proj\payload.bat",
            "schema": "custom-scheme:run",
            "document": (project / "payload.hta").as_uri(),
            "header": r"\\attacker.example\share\payload.hta",
        }
        bcfxml = _save_and_load_bcf(project / "topic.bcf", version, targets)
        uris = _bcf_open_uris(bonsai_modules, bcfxml)
        assert set(targets.values()) <= set(uris)
        _click_all(bonsai_modules, uris, launcher, project)
