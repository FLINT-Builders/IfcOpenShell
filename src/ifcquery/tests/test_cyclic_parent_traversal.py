# This file was generated with the assistance of an AI coding tool.
"""Upward relation traversal must stop when a parent link repeats.

``relations(..., traverse="up")`` and ``ifcquery relations --traverse up``
follow ``ifcopenshell.util.element.get_parent`` with no record of elements
already visited. A storey aggregated into itself, or a wall contained in a
storey that is aggregated by that wall, makes ``get_parent`` return an
element already on the chain. These tests fail until that walk raises
``ValueError`` instead of appending forever.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid
import pytest

_LIBRARY_PROBE = """
import sys
import ifcopenshell
from ifcquery.relations import relations

path, raw_id = sys.argv[1], int(sys.argv[2])
model = ifcopenshell.open(path)
element = model.by_id(raw_id)
try:
    result = relations(model, element, traverse="up")
except ValueError as exc:
    if "cyclic" not in str(exc).lower():
        print(f"BAD {exc}")
        raise SystemExit(2)
    print(f"RAISED {exc}")
    raise SystemExit(0)
except Exception as exc:
    print(f"{type(exc).__name__} {exc}")
    raise SystemExit(3)
length = len(result) if isinstance(result, list) else -1
print(f"RETURNED {length}")
raise SystemExit(4)
"""

_TIMEOUT_SECONDS = 2


def _run(args: list[str], *, script: str | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable]
    if script is None:
        command.extend(args)
    else:
        command.extend(["-c", script, *args])
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode()
        if isinstance(stderr, bytes):
            stderr = stderr.decode()
        pytest.fail(
            f"traversal did not finish within {_TIMEOUT_SECONDS}s (stdout={stdout[:200]!r}, stderr={stderr[:200]!r})"
        )


def _write_self_cycle(directory: Path) -> tuple[Path, int]:
    """Storey whose IfcRelAggregates lists that storey as its own parent."""
    model = ifcopenshell.file(schema="IFC4")
    storey = model.create_entity(
        "IfcBuildingStorey",
        GlobalId=ifcopenshell.guid.new(),
        Name="LoopStorey",
    )
    model.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=storey,
        RelatedObjects=[storey],
    )
    path = directory / "self_cycle.ifc"
    model.write(str(path))
    reopened = ifcopenshell.open(str(path))
    return path, reopened.by_type("IfcBuildingStorey")[0].id()


def _write_two_cycle(directory: Path) -> tuple[Path, int]:
    """Wall contained in a storey that is aggregated by that wall."""
    model = ifcopenshell.file(schema="IFC4")
    wall = model.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="LoopWall")
    storey = model.create_entity(
        "IfcBuildingStorey",
        GlobalId=ifcopenshell.guid.new(),
        Name="LoopStorey",
    )
    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=ifcopenshell.guid.new(),
        RelatingStructure=storey,
        RelatedElements=[wall],
    )
    model.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=wall,
        RelatedObjects=[storey],
    )
    path = directory / "two_cycle.ifc"
    model.write(str(path))
    reopened = ifcopenshell.open(str(path))
    return path, reopened.by_type("IfcWall")[0].id()


def _write_chain(directory: Path) -> tuple[Path, int]:
    model = ifcopenshell.file(schema="IFC4")
    project = model.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Project")
    storey = model.create_entity(
        "IfcBuildingStorey",
        GlobalId=ifcopenshell.guid.new(),
        Name="Storey",
    )
    model.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=project,
        RelatedObjects=[storey],
    )
    path = directory / "chain.ifc"
    model.write(str(path))
    reopened = ifcopenshell.open(str(path))
    return path, reopened.by_type("IfcBuildingStorey")[0].id()


def _assert_library_rejects(path: Path, element_id: int) -> None:
    completed = _run([str(path), str(element_id)], script=_LIBRARY_PROBE)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.startswith("RAISED ")
    assert "cyclic" in completed.stdout.lower()


class TestTraverseUpCycle:
    def test_self_aggregated_storey_raises(self, tmp_path: Path) -> None:
        path, element_id = _write_self_cycle(tmp_path)
        _assert_library_rejects(path, element_id)

    def test_containment_and_aggregate_cycle_raises(self, tmp_path: Path) -> None:
        path, element_id = _write_two_cycle(tmp_path)
        _assert_library_rejects(path, element_id)

    def test_acyclic_chain_still_reaches_project(self, tmp_path: Path) -> None:
        path, element_id = _write_chain(tmp_path)
        completed = _run([str(path), str(element_id)], script=_LIBRARY_PROBE)
        assert completed.returncode == 4, completed.stdout + completed.stderr
        assert completed.stdout.startswith("RETURNED ")
        assert completed.stdout.strip() != "RETURNED -1"


class TestCliTraverseUpCycle:
    def test_self_aggregated_storey_exits(self, tmp_path: Path) -> None:
        path, element_id = _write_self_cycle(tmp_path)
        completed = _run(["-m", "ifcquery", str(path), "relations", str(element_id), "--traverse", "up"])
        assert completed.returncode != 0
        assert "cyclic" in completed.stderr.lower()
        assert completed.stdout.count(f'"id": {element_id}') <= 2

    def test_containment_and_aggregate_cycle_exits(self, tmp_path: Path) -> None:
        path, element_id = _write_two_cycle(tmp_path)
        completed = _run(["-m", "ifcquery", str(path), "relations", f"#{element_id}", "--traverse", "up"])
        assert completed.returncode != 0
        assert "cyclic" in completed.stderr.lower()
        assert completed.stdout.count(f'"id": {element_id}') <= 2
