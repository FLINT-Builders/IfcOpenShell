# This file was generated with the assistance of an AI coding tool.
"""The MCP session, server tool, dispatcher, and embedded caller share the spatial tree walk.

Each one loads an IFC path supplied by the caller and then asks for the tree.
A project and a site that aggregate each other must still produce one node
per element, including the site's other aggregate and its contained wall.
"""

import ifcopenshell
import ifcopenshell.guid

from ifcmcp.core import IfcSession
from ifcmcp.embedded import call_tool
from ifcmcp.server import build_server


def _guid() -> str:
    return ifcopenshell.guid.new()


def _attack_path(tmp_path) -> str:
    model = ifcopenshell.file(schema="IFC4")
    project = model.create_entity("IfcProject", GlobalId=_guid(), Name="P")
    site = model.create_entity("IfcSite", GlobalId=_guid(), Name="S")
    building = model.create_entity("IfcBuilding", GlobalId=_guid(), Name="B")
    wall = model.create_entity("IfcWall", GlobalId=_guid(), Name="W")
    model.create_entity(
        "IfcRelAggregates",
        GlobalId=_guid(),
        RelatingObject=project,
        RelatedObjects=[site],
    )
    model.create_entity(
        "IfcRelAggregates",
        GlobalId=_guid(),
        RelatingObject=site,
        RelatedObjects=[project, building],
    )
    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_guid(),
        RelatingStructure=site,
        RelatedElements=[wall],
    )
    path = tmp_path / "mutual.ifc"
    model.write(str(path))
    return str(path)


def _assert_attack_tree(result: dict) -> None:
    assert result["type"] == "IfcProject"
    assert result["name"] == "P"
    assert [child["name"] for child in result.get("children", [])] == ["S"]
    site = result["children"][0]
    assert site["type"] == "IfcSite"
    assert [child["name"] for child in site.get("children", [])] == ["B"]
    assert site["children"][0].get("children", []) == []
    assert [element["name"] for element in site.get("elements", [])] == ["W"]
    seen: set[int] = set()

    def walk(node: dict) -> None:
        assert node["id"] not in seen
        seen.add(node["id"])
        for child in node.get("children", []):
            walk(child)

    walk(result)


class TestCyclicSpatialTreeSession:
    def test_ifc_tree_after_ifc_load(self, tmp_path):
        session = IfcSession()
        loaded = session.ifc_load(_attack_path(tmp_path))
        assert loaded.startswith("Loaded ")
        _assert_attack_tree(session.ifc_tree())

    def test_dispatch_ifc_tree_after_ifc_load(self, tmp_path):
        session = IfcSession()
        session.dispatch("ifc_load", {"path": _attack_path(tmp_path)})
        _assert_attack_tree(session.dispatch("ifc_tree"))


class TestCyclicSpatialTreeServer:
    def test_ifc_tree_tool_after_ifc_load(self, tmp_path):
        server = build_server()
        tools = {tool.name: tool.fn for tool in server._tool_manager.list_tools()}
        loaded = tools["ifc_load"](_attack_path(tmp_path))
        assert loaded.startswith("Loaded ")
        _assert_attack_tree(tools["ifc_tree"]())


class TestCyclicSpatialTreeEmbedded:
    def test_call_tool_ifc_tree_after_ifc_load(self, tmp_path):
        loaded = call_tool("ifc_load", {"path": _attack_path(tmp_path)})
        assert loaded["ok"] is True
        result = call_tool("ifc_tree")
        assert result["ok"] is True, result
        _assert_attack_tree(result["data"])
