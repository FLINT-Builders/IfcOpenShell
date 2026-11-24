# This file was generated with the assistance of an AI coding tool.
"""MCP relation queries must stop when a parent link repeats.

``IfcSession.ifc_relations``, ``IfcSession.dispatch`` and the ``ifc_relations``
tool in ``ifcmcp.server`` all pass ``traverse="up"`` through to
``ifcquery.relations.relations``. These tests fail until that walk raises
``ValueError`` on a repeated parent instead of appending forever.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid
import pytest

_TIMEOUT_SECONDS = 2

_SESSION_PROBE = """
import sys
import ifcopenshell
from ifcmcp.core import IfcSession

path, raw_id, how = sys.argv[1], int(sys.argv[2]), sys.argv[3]
session = IfcSession()
session.ifc_load(path)
try:
    if how == "dispatch":
        session.dispatch("ifc_relations", {"element_id": raw_id, "traverse": "up"})
    else:
        session.ifc_relations(raw_id, traverse="up")
except ValueError as exc:
    if "cyclic" not in str(exc).lower():
        print(f"BAD {exc}")
        raise SystemExit(2)
    print(f"RAISED {exc}")
    raise SystemExit(0)
except Exception as exc:
    print(f"{type(exc).__name__} {exc}")
    raise SystemExit(3)
print("RETURNED")
raise SystemExit(4)
"""

_SERVER_PROBE = """
import sys
from ifcmcp.server import build_server

path, raw_id = sys.argv[1], int(sys.argv[2])
server = build_server()
tools = {tool.name: tool.fn for tool in server._tool_manager.list_tools()}
tools["ifc_load"](path)
try:
    tools["ifc_relations"](element_id=raw_id, traverse="up")
except ValueError as exc:
    if "cyclic" not in str(exc).lower():
        print(f"BAD {exc}")
        raise SystemExit(2)
    print(f"RAISED {exc}")
    raise SystemExit(0)
except Exception as exc:
    print(f"{type(exc).__name__} {exc}")
    raise SystemExit(3)
print("RETURNED")
raise SystemExit(4)
"""


def _run(script: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [sys.executable, "-c", script, *args],
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
            "ifc_relations did not finish within "
            f"{_TIMEOUT_SECONDS}s (stdout={stdout[:200]!r}, stderr={stderr[:200]!r})"
        )


def _write_self_cycle(directory: Path) -> tuple[Path, int]:
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


def _assert_raised(completed: subprocess.CompletedProcess[str]) -> None:
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.startswith("RAISED ")
    assert "cyclic" in completed.stdout.lower()


class TestSessionTraverseUpCycle:
    def test_self_aggregated_storey_raises(self, tmp_path: Path) -> None:
        path, element_id = _write_self_cycle(tmp_path)
        completed = _run(_SESSION_PROBE, [str(path), str(element_id), "method"])
        _assert_raised(completed)

    def test_containment_and_aggregate_cycle_raises(self, tmp_path: Path) -> None:
        path, element_id = _write_two_cycle(tmp_path)
        completed = _run(_SESSION_PROBE, [str(path), str(element_id), "method"])
        _assert_raised(completed)

    def test_dispatch_self_aggregated_storey_raises(self, tmp_path: Path) -> None:
        path, element_id = _write_self_cycle(tmp_path)
        completed = _run(_SESSION_PROBE, [str(path), str(element_id), "dispatch"])
        _assert_raised(completed)


class TestServerToolTraverseUpCycle:
    def test_tool_self_aggregated_storey_raises(self, tmp_path: Path) -> None:
        path, element_id = _write_self_cycle(tmp_path)
        completed = _run(_SERVER_PROBE, [str(path), str(element_id)])
        _assert_raised(completed)

    def test_tool_containment_and_aggregate_cycle_raises(self, tmp_path: Path) -> None:
        path, element_id = _write_two_cycle(tmp_path)
        completed = _run(_SERVER_PROBE, [str(path), str(element_id)])
        _assert_raised(completed)
