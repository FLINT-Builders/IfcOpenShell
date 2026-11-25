# This file was generated with the assistance of an AI coding tool.
"""Cycle tests for Bonsai aggregate walks.

Opening an IFC file does not reject an IfcRelAggregates cycle. These walks are
what duplicate, move, aggregate mode, and opening tools call:

- get_parts_recursively: duplicate (geometry/operator.py), move when the
  element has parts, add opening (tool/feature.py and the void/opening tools)
- get_aggregates_recursively: aggregate mode, and move when the element itself
  has no parts

An acyclic assembly must keep today's results. A cycle must finish: either
return each entity at most once, or raise an error that reports the cycle.
The Blender operator bodies are not executed here; they pass the loaded
entity into these two walks and do not keep their own visited set.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

AGGREGATE_PY = Path(__file__).resolve().parents[2] / "bonsai" / "tool" / "aggregate.py"
WALK_TIMEOUT_SECONDS = 3


def _run(case: str) -> dict:
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", case],
            check=False,
            capture_output=True,
            text=True,
            timeout=WALK_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{case} did not finish within {WALK_TIMEOUT_SECONDS}s; the aggregate walk did not stop")
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _assert_stopped(payload: dict, allowed: set[str]) -> None:
    assert payload["status"] in {"ok", "cycle"}
    if payload["status"] == "cycle":
        assert "cycl" in payload["message"].lower()
        return
    names = payload["names"]
    assert len(names) == len(set(names))
    assert set(names) <= allowed


def test_acyclic_parts_include_descendants_once():
    payload = _run("acyclic-parts")
    assert payload["status"] == "ok"
    assert payload["names"] == ["B", "C"]


def test_acyclic_parent_walk_orders_ancestors_toward_the_root():
    payload = _run("acyclic-aggregates")
    assert payload["status"] == "ok"
    # C is a part of B, B is a part of A. Callers use the last entry as the top aggregate.
    assert payload["names"] == ["B", "A"]


def test_self_aggregate_parts_walk_stops():
    # Duplicate, move of an IfcElementAssembly, and add-opening all call this walk.
    _assert_stopped(_run("self-parts"), {"A"})


def test_self_aggregate_parent_walk_stops():
    # Entering aggregate mode calls this walk before it looks at parts.
    _assert_stopped(_run("self-aggregates"), {"A"})


def test_mutual_aggregate_parts_walk_stops():
    _assert_stopped(_run("mutual-parts"), {"A", "B"})


def test_mutual_aggregate_parent_walk_stops():
    _assert_stopped(_run("mutual-aggregates"), {"A", "B"})


def test_part_of_mutual_aggregate_parent_walk_stops():
    # Move of an element with no parts of its own walks ancestors instead.
    _assert_stopped(_run("part-of-cycle-aggregates"), {"A", "B", "Beam"})


def test_ifc2x3_self_aggregate_parts_walk_stops():
    _assert_stopped(_run("ifc2x3-self-parts"), {"A"})


def _load_aggregate():
    bpy = types.ModuleType("bpy")
    sys.modules["bpy"] = bpy
    bonsai = types.ModuleType("bonsai")
    bonsai.__path__ = []
    core = types.ModuleType("bonsai.core")
    core.__path__ = []
    core_tool = types.ModuleType("bonsai.core.tool")

    class _AggregateBase:
        pass

    core_tool.Aggregate = _AggregateBase
    tool = types.ModuleType("bonsai.tool")
    tool.__path__ = []
    bonsai.core = core
    core.tool = core_tool
    bonsai.tool = tool
    sys.modules["bonsai"] = bonsai
    sys.modules["bonsai.core"] = core
    sys.modules["bonsai.core.tool"] = core_tool
    sys.modules["bonsai.tool"] = tool

    spec = importlib.util.spec_from_file_location("bonsai.tool.aggregate", AGGREGATE_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bonsai.tool.aggregate"] = module
    spec.loader.exec_module(module)
    return module.Aggregate


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _open_model(file):
    import ifcopenshell

    with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as handle:
        path = handle.name
    file.write(path)
    return ifcopenshell.open(path)


def _names(result) -> list[str]:
    if isinstance(result, set):
        return sorted(element.Name for element in result)
    return [element.Name for element in result]


def _finish_walk(walk, element, direct_check) -> None:
    direct_check()
    try:
        result = walk(element)
    except Exception as caught:
        message = f"{type(caught).__name__}: {caught}"
        if "cycl" in message.lower():
            _emit({"status": "cycle", "message": message})
            return
        raise
    _emit({"status": "ok", "names": _names(result)})


def _assembly(file, name):
    import ifcopenshell

    return file.create_entity("IfcElementAssembly", GlobalId=ifcopenshell.guid.new(), Name=name)


def _relate(file, whole, parts):
    import ifcopenshell

    return file.create_entity(
        "IfcRelAggregates",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=whole,
        RelatedObjects=list(parts),
    )


def run_worker(case: str) -> None:
    import ifcopenshell.util.element as element_util

    aggregate = _load_aggregate()
    parts_walk = aggregate.get_parts_recursively
    aggregates_walk = aggregate.get_aggregates_recursively

    if case == "acyclic-parts":
        file = ifcopenshell_file("IFC4")
        whole_a = _assembly(file, "A")
        whole_b = _assembly(file, "B")
        whole_c = _assembly(file, "C")
        _relate(file, whole_a, [whole_b])
        _relate(file, whole_b, [whole_c])
        model = _open_model(file)
        whole_a = _by_name(model, "A")

        def direct_check():
            _require([item.Name for item in element_util.get_parts(whole_a)] == ["B"], "acyclic parts were not loaded")

        _finish_walk(parts_walk, whole_a, direct_check)
        return

    if case == "acyclic-aggregates":
        file = ifcopenshell_file("IFC4")
        whole_a = _assembly(file, "A")
        whole_b = _assembly(file, "B")
        whole_c = _assembly(file, "C")
        _relate(file, whole_a, [whole_b])
        _relate(file, whole_b, [whole_c])
        model = _open_model(file)
        whole_c = _by_name(model, "C")

        def direct_check():
            parent = element_util.get_aggregate(whole_c)
            _require(parent is not None and parent.Name == "B", "acyclic parent was not loaded")

        _finish_walk(aggregates_walk, whole_c, direct_check)
        return

    if case in {"self-parts", "self-aggregates", "ifc2x3-self-parts"}:
        schema = "IFC2X3" if case.startswith("ifc2x3") else "IFC4"
        file = ifcopenshell_file(schema)
        whole_a = _assembly(file, "A")
        _relate(file, whole_a, [whole_a])
        model = _open_model(file)
        whole_a = _by_name(model, "A")
        walk = parts_walk if case.endswith("parts") else aggregates_walk

        def direct_check():
            part_names = [item.Name for item in element_util.get_parts(whole_a)]
            parent = element_util.get_aggregate(whole_a)
            _require(part_names == ["A"], f"self part was not loaded: {part_names}")
            _require(parent is not None and parent.Name == "A", "self parent was not loaded")

        _finish_walk(walk, whole_a, direct_check)
        return

    if case in {"mutual-parts", "mutual-aggregates"}:
        file = ifcopenshell_file("IFC4")
        whole_a = _assembly(file, "A")
        whole_b = _assembly(file, "B")
        _relate(file, whole_a, [whole_b])
        _relate(file, whole_b, [whole_a])
        model = _open_model(file)
        whole_a = _by_name(model, "A")
        walk = parts_walk if case.endswith("parts") else aggregates_walk

        def direct_check():
            part_names = [item.Name for item in element_util.get_parts(whole_a)]
            parent = element_util.get_aggregate(whole_a)
            _require(part_names == ["B"], f"mutual part was not loaded: {part_names}")
            _require(parent is not None and parent.Name == "B", "mutual parent was not loaded")

        _finish_walk(walk, whole_a, direct_check)
        return

    if case == "part-of-cycle-aggregates":
        file = ifcopenshell_file("IFC4")
        whole_a = _assembly(file, "A")
        whole_b = _assembly(file, "B")
        beam = file.create_entity("IfcBeam", GlobalId=_guid(), Name="Beam")
        _relate(file, whole_a, [whole_b, beam])
        _relate(file, whole_b, [whole_a])
        model = _open_model(file)
        beam = _by_name(model, "Beam")

        def direct_check():
            _require(list(element_util.get_parts(beam)) == [], "beam unexpectedly has parts")
            parent = element_util.get_aggregate(beam)
            _require(parent is not None and parent.Name == "A", "beam parent was not loaded")
            parent_parts = sorted(item.Name for item in element_util.get_parts(parent))
            _require(parent_parts == ["B", "Beam"], f"cycle around the beam was not loaded: {parent_parts}")

        _finish_walk(aggregates_walk, beam, direct_check)
        return

    raise SystemExit(f"unknown case {case}")


def ifcopenshell_file(schema: str):
    import ifcopenshell

    return ifcopenshell.file(schema=schema)


def _guid() -> str:
    import ifcopenshell

    return ifcopenshell.guid.new()


def _by_name(model, name: str):
    found = [element for element in model if getattr(element, "Name", None) == name]
    _require(len(found) == 1, f"expected one {name}, found {len(found)}")
    return found[0]


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        run_worker(sys.argv[2])
    else:
        raise SystemExit("usage: test_aggregate_cycle.py --worker CASE")
