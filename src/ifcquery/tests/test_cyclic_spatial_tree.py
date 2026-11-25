# This file was generated with the assistance of an AI coding tool.
"""Spatial tree queries must finish on a cyclic decomposition.

``_build_spatial_node`` walks ``IsDecomposedBy`` from every ``IfcProject``.
A file can name an element as an aggregate of itself, or of an ancestor,
through ``IfcRelAggregates`` (and, in IFC2X3, ``IfcRelNests``, which shares
that inverse). The walk has to record element ids it has already emitted and
skip those children, while still emitting later siblings and contained
elements. These tests open a written IFC file, which is the input the CLI
accepts.
"""

import json
import subprocess
import sys

import ifcopenshell
import ifcopenshell.guid

from ifcquery.tree import tree


def _guid() -> str:
    return ifcopenshell.guid.new()


def _file(schema: str = "IFC4") -> ifcopenshell.file:
    return ifcopenshell.file(schema=schema)


def _element(model: ifcopenshell.file, ifc_class: str, name: str) -> ifcopenshell.entity_instance:
    return model.create_entity(ifc_class, GlobalId=_guid(), Name=name)


def _decompose(model: ifcopenshell.file, parent, children, rel_class: str = "IfcRelAggregates") -> None:
    model.create_entity(
        rel_class,
        GlobalId=_guid(),
        RelatingObject=parent,
        RelatedObjects=list(children),
    )


def _contain(model: ifcopenshell.file, structure, elements) -> None:
    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_guid(),
        RelatingStructure=structure,
        RelatedElements=list(elements),
    )


def _open_written(model: ifcopenshell.file, tmp_path, name: str) -> ifcopenshell.file:
    path = tmp_path / name
    model.write(str(path))
    return ifcopenshell.open(str(path))


def _spatial_ids(node: dict, seen: set[int] | None = None) -> set[int]:
    seen = set() if seen is None else seen
    assert node["id"] not in seen
    seen.add(node["id"])
    for child in node.get("children", []):
        _spatial_ids(child, seen)
    return seen


def _attack_model() -> ifcopenshell.file:
    """Project and site each aggregate the other; the site also has a building and a wall."""
    model = _file()
    project = _element(model, "IfcProject", "P")
    site = _element(model, "IfcSite", "S")
    building = _element(model, "IfcBuilding", "B")
    wall = _element(model, "IfcWall", "W")
    _decompose(model, project, [site])
    _decompose(model, site, [project, building])
    _contain(model, site, [wall])
    return model


def _assert_attack_tree(result: dict) -> None:
    assert result["type"] == "IfcProject"
    assert result["name"] == "P"
    assert [child["name"] for child in result.get("children", [])] == ["S"]
    site = result["children"][0]
    assert site["type"] == "IfcSite"
    assert [child["name"] for child in site.get("children", [])] == ["B"]
    building = site["children"][0]
    assert building["type"] == "IfcBuilding"
    assert building.get("children", []) == []
    assert [element["name"] for element in site.get("elements", [])] == ["W"]
    assert [element["type"] for element in site["elements"]] == ["IfcWall"]
    _spatial_ids(result)


class TestCyclicSpatialTree:
    def test_mutual_aggregates_emit_each_element_once(self, tmp_path):
        result = tree(_open_written(_attack_model(), tmp_path, "mutual.ifc"))
        _assert_attack_tree(result)

    def test_three_element_cycle(self, tmp_path):
        model = _file()
        project = _element(model, "IfcProject", "P")
        site = _element(model, "IfcSite", "S")
        building = _element(model, "IfcBuilding", "B")
        _decompose(model, project, [site])
        _decompose(model, site, [building])
        _decompose(model, building, [project])

        result = tree(_open_written(model, tmp_path, "three.ifc"))

        assert result["name"] == "P"
        assert [child["name"] for child in result.get("children", [])] == ["S"]
        assert [child["name"] for child in result["children"][0].get("children", [])] == ["B"]
        assert result["children"][0]["children"][0].get("children", []) == []
        _spatial_ids(result)

    def test_self_aggregate(self, tmp_path):
        model = _file()
        project = _element(model, "IfcProject", "P")
        _decompose(model, project, [project])

        result = tree(_open_written(model, tmp_path, "self.ifc"))

        assert result["type"] == "IfcProject"
        assert result["name"] == "P"
        assert result.get("children", []) == []
        _spatial_ids(result)

    def test_cycle_below_the_project_keeps_the_following_sibling(self, tmp_path):
        model = _file()
        project = _element(model, "IfcProject", "P")
        site = _element(model, "IfcSite", "S")
        building = _element(model, "IfcBuilding", "B")
        storey = _element(model, "IfcBuildingStorey", "G")
        _decompose(model, project, [site])
        _decompose(model, site, [building])
        _decompose(model, building, [site, storey])

        result = tree(_open_written(model, tmp_path, "below.ifc"))

        assert [child["name"] for child in result.get("children", [])] == ["S"]
        building_node = result["children"][0]["children"][0]
        assert building_node["name"] == "B"
        assert [child["name"] for child in building_node.get("children", [])] == ["G"]
        assert building_node["children"][0].get("children", []) == []
        _spatial_ids(result)

    def test_each_project_in_a_cyclic_file(self, tmp_path):
        model = _file()
        first = _element(model, "IfcProject", "P1")
        first_site = _element(model, "IfcSite", "S1")
        second = _element(model, "IfcProject", "P2")
        second_site = _element(model, "IfcSite", "S2")
        _decompose(model, first, [first_site])
        _decompose(model, first_site, [first])
        _decompose(model, second, [second_site])
        _decompose(model, second_site, [second])

        result = tree(_open_written(model, tmp_path, "two.ifc"))

        assert isinstance(result, list)
        by_name = {node["name"]: node for node in result}
        assert set(by_name) == {"P1", "P2"}
        assert [child["name"] for child in by_name["P1"].get("children", [])] == ["S1"]
        assert by_name["P1"]["children"][0].get("children", []) == []
        assert [child["name"] for child in by_name["P2"].get("children", [])] == ["S2"]
        assert by_name["P2"]["children"][0].get("children", []) == []
        for node in result:
            _spatial_ids(node)

    def test_duplicate_aggregate_is_emitted_once(self, tmp_path):
        model = _file()
        project = _element(model, "IfcProject", "P")
        site = _element(model, "IfcSite", "S")
        _decompose(model, project, [site, site])

        result = tree(_open_written(model, tmp_path, "duplicate.ifc"))

        assert [child["name"] for child in result.get("children", [])] == ["S"]
        _spatial_ids(result)

    def test_shared_descendant_is_emitted_once(self, tmp_path):
        model = _file()
        project = _element(model, "IfcProject", "P")
        site = _element(model, "IfcSite", "S")
        building = _element(model, "IfcBuilding", "B")
        storey = _element(model, "IfcBuildingStorey", "G")
        _decompose(model, project, [site, building])
        _decompose(model, site, [storey])
        _decompose(model, building, [storey])

        result = tree(_open_written(model, tmp_path, "diamond.ifc"))

        assert [child["name"] for child in result.get("children", [])] == ["S", "B"]
        assert [child["name"] for child in result["children"][0].get("children", [])] == ["G"]
        assert result["children"][1].get("children", []) == []
        _spatial_ids(result)

    def test_ifc2x3_nest_cycle_uses_the_same_walk(self, tmp_path):
        model = _file("IFC2X3")
        project = _element(model, "IfcProject", "P")
        site = _element(model, "IfcSite", "S")
        _decompose(model, project, [site], rel_class="IfcRelNests")
        _decompose(model, site, [project], rel_class="IfcRelNests")

        result = tree(_open_written(model, tmp_path, "nest.ifc"))

        assert result["type"] == "IfcProject"
        assert result["name"] == "P"
        assert [child["name"] for child in result.get("children", [])] == ["S"]
        assert result["children"][0].get("children", []) == []
        _spatial_ids(result)


class TestCyclicSpatialTreeCli:
    def test_tree_command_on_a_cyclic_file(self, tmp_path):
        path = tmp_path / "mutual.ifc"
        _attack_model().write(str(path))

        completed = subprocess.run(
            [sys.executable, "-m", "ifcquery", str(path), "tree"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        _assert_attack_tree(json.loads(completed.stdout))
