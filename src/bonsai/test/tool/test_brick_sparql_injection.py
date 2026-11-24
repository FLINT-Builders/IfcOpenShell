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

"""SPARQL built from Brick IRIs, class names, and IFC GlobalIds must not fetch remote endpoints.

These tests fail while entity IRIs, class fragments, and IfcProject.GlobalId are concatenated
into query text. They pass when those values are bound as terms, or rejected, before a query runs.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import ifcopenshell
import pytest

BONSAI_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_STUB = BONSAI_ROOT / "test" / "files" / "BrickStub.ttl"
SPARQL_JSON = b'{"head":{"vars":["a","b","c"]},"results":{"bindings":[]}}'


def _turtle_escape(text: str) -> str:
    """Encode characters that terminate a Turtle IRI, leaving the decoded value unchanged."""
    special = set('<>"{}|^`\\ \t\r\n')
    return "".join(ch if ch.isascii() and ch not in special else "\\u%04X" % ord(ch) for ch in text)


def _entity_iri(service: str) -> str:
    # Closes the template's IRI, finishes that triple, inserts SERVICE, then opens the IRI the template closes.
    return f"http://example.org/victim> ?pred ?obj . SERVICE <{service}> {{ ?a ?b ?c }} <http://example.org/tail"


def _class_fragment(service: str, anchor: str = "Equipment") -> str:
    # The token before SERVICE has to match data already in the graph, or rdflib never evaluates SERVICE.
    # Prefixed-name templates already supply the trailing " .".
    return f"{anchor} .\nSERVICE <{service}> {{ ?a ?b ?c }} .\n?class ?class ?class"


def _global_id(service: str) -> str:
    # Closes the quoted literal and comments out the template's closing quote on that line.
    return f'x" . SERVICE <{service}> {{ ?a ?b ?c }} #'


class _BrickItem:
    def __init__(self) -> None:
        self.name = ""
        self.label = ""
        self.uri = ""
        self.total_items = 0


class _Collection(list):
    def add(self):
        item = _BrickItem()
        self.append(item)
        return item

    def clear(self) -> None:
        super().clear()


class _Props:
    def __init__(self) -> None:
        self.bricks = _Collection()
        self.split_screen_bricks = _Collection()
        self.active_brick_index = 0
        self.split_screen_active_brick_index = 0
        self.add_brick_relation_failed = False
        self.new_brick_relation_type = ""
        self.active_brick_class = ""
        self.split_screen_active_brick_class = ""


def _load_headless():
    root = BONSAI_ROOT

    def pkg(name: str, path: Path):
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        module.__package__ = name
        module.__name__ = name
        sys.modules[name] = module
        if "." in name:
            parent, child = name.rsplit(".", 1)
            setattr(sys.modules[parent], child, module)
        return module

    pkg("bonsai", root / "bonsai")
    pkg("bonsai.core", root / "bonsai" / "core")
    toolmod = pkg("bonsai.tool", root / "bonsai" / "tool")
    pkg("bonsai.bim", root / "bonsai" / "bim")
    pkg("bonsai.bim.module", root / "bonsai" / "bim" / "module")
    pkg("bonsai.bim.module.brick", root / "bonsai" / "bim" / "module" / "brick")

    bpy = types.ModuleType("bpy")
    bpy.__path__ = []
    sys.modules["bpy"] = bpy

    def load(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        parent, child = name.rsplit(".", 1)
        setattr(sys.modules[parent], child, module)
        spec.loader.exec_module(module)
        return module

    load("bonsai.core.tool", root / "bonsai" / "core" / "tool.py")
    load("bonsai.core.brick", root / "bonsai" / "core" / "brick.py")

    class _Ifc:
        file = None

        @classmethod
        def get(cls):
            return cls.file

        @classmethod
        def get_schema(cls):
            return "IFC4"

    class _Blender:
        @classmethod
        def get_bim_props(cls):
            return types.SimpleNamespace(ifc_file="project.ifc")

    toolmod.Ifc = _Ifc
    toolmod.Blender = _Blender
    toolmod.Document = types.SimpleNamespace()
    brick = load("bonsai.tool.brick", root / "bonsai" / "tool" / "brick.py")
    toolmod.Brick = brick.Brick
    data = load("bonsai.bim.module.brick.data", root / "bonsai" / "bim" / "module" / "brick" / "data.py")
    return brick, data


def _load_targets():
    bpy = sys.modules.get("bpy")
    if bpy is not None and getattr(getattr(bpy, "app", None), "binary_path", None):
        import bonsai.bim.module.brick.data as data
        import bonsai.tool.brick as brick

        return brick, data
    return _load_headless()


BRICK, DATA = _load_targets()


class _ServiceHandler(BaseHTTPRequestHandler):
    def _respond(self) -> None:
        self.server.hits.append(self.path.split("?", 1)[0])  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "application/sparql-results+json")
        self.send_header("Content-Length", str(len(SPARQL_JSON)))
        self.end_headers()
        self.wfile.write(SPARQL_JSON)

    def do_GET(self) -> None:
        self._respond()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        self._respond()

    def log_message(self, fmt: str, *args) -> None:
        return


@pytest.fixture(scope="module")
def service():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ServiceHandler)
    server.hits = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _reset_brick_store():
    BRICK.BrickStore.purge()
    yield
    BRICK.BrickStore.purge()


@pytest.fixture
def props(service):
    service.hits.clear()
    value = _Props()
    BRICK.Brick.get_brick_props = classmethod(lambda cls: value)
    return value


def _endpoint(service, path: str) -> str:
    host, port = service.server_address
    return f"http://{host}:{port}{path}"


def _write_ttl(text: str) -> str:
    handle, path = tempfile.mkstemp(suffix=".ttl")
    os.write(handle, text.encode())
    os.close(handle)
    return path


def _load(text: str) -> str:
    path = _write_ttl(text)
    BRICK.BrickStore.schema = str(SCHEMA_STUB)
    BRICK.Brick.load_brick_file(path)
    return path


def _call(fn) -> None:
    try:
        fn()
    except Exception:
        return


def _assert_not_requested(service, path: str) -> None:
    requested = [hit for hit in service.hits if hit == path or hit.endswith(path)]
    assert requested == [], f"query fetched {requested}"


def test_active_relations_keeps_absolute_iri_local(service, props):
    _load(
        """
        @prefix brick: <https://brickschema.org/schema/Brick#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        <http://example.org/safe> a brick:Equipment ;
            rdfs:label "SafeLabel" .
        """
    )
    BRICK.Brick.import_brick_items("Equipment")
    props.active_brick_index = 0
    relations = DATA.BrickschemaData.active_relations()
    assert any(str(row["object_name"]) == "SafeLabel" for row in relations)
    assert service.hits == []


def test_active_relations_does_not_fetch_service_from_entity_iri(service, props):
    iri = _entity_iri(_endpoint(service, "/relations"))
    _load(
        f"""
        @prefix brick: <https://brickschema.org/schema/Brick#> .
        <http://example.org/victim> a brick:Equipment .
        <{_turtle_escape(iri)}> a brick:Equipment .
        """
    )
    service.hits.clear()
    BRICK.Brick.import_brick_items("Equipment")
    planted = [item for item in props.bricks if item.uri == iri]
    if planted:
        props.active_brick_index = props.bricks.index(planted[0])
        _call(DATA.BrickschemaData.active_relations)
    _assert_not_requested(service, "/relations")


def test_get_item_class_does_not_fetch_service_from_entity_iri(service, props):
    iri = _entity_iri(_endpoint(service, "/item-class"))
    _load(
        f"""
        @prefix brick: <https://brickschema.org/schema/Brick#> .
        <http://example.org/victim> a brick:Equipment .
        <{_turtle_escape(iri)}> a brick:Equipment .
        """
    )
    service.hits.clear()
    _call(lambda: BRICK.Brick.get_item_class(iri))
    _assert_not_requested(service, "/item-class")


def test_export_brick_attributes_does_not_fetch_service_from_entity_iri(service, props):
    iri = _entity_iri(_endpoint(service, "/export"))
    _load(
        f"""
        @prefix brick: <https://brickschema.org/schema/Brick#> .
        <http://example.org/victim> a brick:Equipment .
        <{_turtle_escape(iri)}> a brick:Equipment .
        """
    )
    service.hits.clear()
    _call(lambda: BRICK.Brick.export_brick_attributes(iri))
    _assert_not_requested(service, "/export")


def test_add_relation_does_not_fetch_service_from_object_iri(service, props):
    iri = _entity_iri(_endpoint(service, "/relation"))
    _load(
        f"""
        @prefix brick: <https://brickschema.org/schema/Brick#> .
        <http://example.org/victim> a brick:Equipment .
        <{_turtle_escape(iri)}> a brick:Equipment .
        """
    )
    service.hits.clear()
    _call(
        lambda: BRICK.Brick.add_relation(
            "http://example.org/source",
            "https://brickschema.org/schema/Brick#feeds",
            iri,
        )
    )
    _assert_not_requested(service, "/relation")


def test_import_brick_classes_does_not_fetch_service_from_class_name(service, props):
    fragment = _class_fragment(_endpoint(service, "/classes"))
    iri = "http://example.org/evil#" + fragment
    _load(
        f"""
        @prefix brick: <https://brickschema.org/schema/Brick#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        <{_turtle_escape(iri)}> rdfs:subClassOf brick:Equipment .
        <http://example.org/inst> a <{_turtle_escape(iri)}> .
        """
    )
    service.hits.clear()
    BRICK.Brick.import_brick_classes("Equipment")
    names = [item.name for item in props.bricks]
    service.hits.clear()
    if fragment in names:
        _call(lambda: BRICK.Brick.import_brick_classes(fragment))
    _assert_not_requested(service, "/classes")


def test_import_brick_items_does_not_fetch_service_from_class_name(service, props):
    fragment = _class_fragment(_endpoint(service, "/items"))
    _load(
        """
        @prefix brick: <https://brickschema.org/schema/Brick#> .
        <http://example.org/safe> a brick:Equipment .
        """
    )
    service.hits.clear()
    _call(lambda: BRICK.Brick.import_brick_items(fragment))
    _assert_not_requested(service, "/items")


def test_load_brick_file_does_not_fetch_service_from_root_class(service, props):
    fragment = _class_fragment(_endpoint(service, "/roots"))
    iri = "http://example.org/evil#" + fragment
    escaped = _turtle_escape(iri)
    service.hits.clear()
    _call(
        lambda: _load(
            f"""
            @prefix brick: <https://brickschema.org/schema/Brick#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            <{escaped}> rdfs:subClassOf brick:Equipment .
            <http://example.org/c1> rdfs:subClassOf <{escaped}> .
            <http://example.org/c2> rdfs:subClassOf <{escaped}> .
            <http://example.org/c3> rdfs:subClassOf <{escaped}> .
            """
        )
    )
    _assert_not_requested(service, "/roots")


def test_get_brickifc_project_does_not_fetch_service_from_global_id(service, props):
    endpoint = _endpoint(service, "/globalid")
    global_id = _global_id(endpoint)
    handle, ifc_path = tempfile.mkstemp(suffix=".ifc")
    step = "\n".join(
        [
            "ISO-10303-21;",
            "HEADER;",
            "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');",
            "FILE_NAME('project.ifc','2020-01-01T00:00:00',(''),(''),'','','');",
            "FILE_SCHEMA(('IFC4'));",
            "ENDSEC;",
            "DATA;",
            "#1=IFCPROJECT('" + global_id + "',$,'Name',$,$,$,$,$,$);",
            "ENDSEC;",
            "END-ISO-10303-21;",
            "",
        ]
    )
    os.write(handle, step.encode())
    os.close(handle)
    ifc = ifcopenshell.open(ifc_path)
    assert ifc.by_type("IfcProject")[0].GlobalId == global_id
    # brick.py looks up the open model through bonsai.tool.Ifc at call time.
    ifc_api = sys.modules["bonsai.tool"].Ifc
    ifc_api.get = classmethod(lambda cls: ifc)
    ifc_api.get_schema = classmethod(lambda cls: "IFC4")
    _load(
        """
        @prefix ref: <https://brickschema.org/schema/Brick/ref#> .
        <http://example.org/p> a ref:ifcProject ;
            ref:ifcProjectID "x" .
        """
    )
    service.hits.clear()
    _call(BRICK.Brick.get_brickifc_project)
    _assert_not_requested(service, "/globalid")
