# This file was generated with the assistance of an AI coding tool.

"""ifcquery must finish when an IFC file contains a cyclic aggregate."""

import os
import signal
import tempfile

import ifcopenshell
import ifcopenshell.guid

from ifcquery.relations import relations
from ifcquery.select import select

_DEADLINE_SECONDS = 2.0


class WalkDidNotFinish(AssertionError):
    pass


def _on_deadline(signum, frame):
    raise WalkDidNotFinish(f"walk did not finish within {_DEADLINE_SECONDS}s")


def finish(fn):
    previous = signal.signal(signal.SIGALRM, _on_deadline)
    signal.setitimer(signal.ITIMER_REAL, _DEADLINE_SECONDS)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _guid():
    return ifcopenshell.guid.new()


def _make(file, ifc_class, name):
    return file.create_entity(ifc_class, GlobalId=_guid(), Name=name)


def cyclic_model():
    file = ifcopenshell.file(schema="IFC4")
    wall = _make(file, "IfcWall", "Wall")
    storey = _make(file, "IfcBuildingStorey", "Level 1")
    building = _make(file, "IfcBuilding", "Building")
    file.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=_guid(),
        RelatingStructure=storey,
        RelatedElements=[wall],
    )
    file.create_entity(
        "IfcRelAggregates",
        GlobalId=_guid(),
        RelatingObject=building,
        RelatedObjects=[storey],
    )
    file.create_entity(
        "IfcRelAggregates",
        GlobalId=_guid(),
        RelatingObject=storey,
        RelatedObjects=[building],
    )
    return file, wall, storey, building


def mutual_aggregate():
    file = ifcopenshell.file(schema="IFC4")
    wall = _make(file, "IfcWall", "Wall")
    assembly = _make(file, "IfcElementAssembly", "Assembly")
    file.create_entity(
        "IfcRelAggregates",
        GlobalId=_guid(),
        RelatingObject=assembly,
        RelatedObjects=[wall],
    )
    file.create_entity(
        "IfcRelAggregates",
        GlobalId=_guid(),
        RelatingObject=wall,
        RelatedObjects=[assembly],
    )
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "cycle.ifc")
        file.write(path)
        loaded = ifcopenshell.open(path)
    return loaded


class TestCyclicAggregation:
    def test_select_location_on_cyclic_containers(self):
        file, wall, storey, building = cyclic_model()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "cycle.ifc")
            file.write(path)
            loaded = ifcopenshell.open(path)
        loaded_wall = loaded.by_type("IfcWall")[0]
        selected = finish(lambda: select(loaded, 'IfcWall, location="Level 1"'))
        assert [item["id"] for item in selected] == [loaded_wall.id()]
        assert selected[0]["name"] == "Wall"
        assert finish(lambda: select(loaded, "IfcWall, location=Missing")) == []

    def test_relations_and_traverse_up_on_aggregate_cycle(self):
        loaded = mutual_aggregate()
        wall = loaded.by_type("IfcWall")[0]
        assembly = loaded.by_type("IfcElementAssembly")[0]
        result = finish(lambda: relations(loaded, wall))
        assert result["hierarchy"]["aggregate"]["id"] == assembly.id()
        chain = finish(lambda: relations(loaded, wall, traverse="up"))
        assert [item["id"] for item in chain] == [wall.id(), assembly.id()]
        assert len(chain) == len({item["id"] for item in chain})
