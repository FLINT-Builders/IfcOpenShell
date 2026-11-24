# This file was generated with the assistance of an AI coding tool.
"""Cyclic IfcBooleanClippingResult chains must not hang element inspection.

These tests fail while the vulnerability is present. ``_walk_clipping`` follows
``FirstOperand`` with no record of results it has already visited, so a cycle
never leaves the loop. A plane half-space as ``SecondOperand`` also appends a
new plane dict on every pass. ``info()`` (the ``ifcquery info`` command and
``IfcSession.ifc_info``) must finish and still describe the element. The
geometry summary may be omitted; if it is present, clipping planes must not
repeat the cycle.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.unit
import ifcopenshell.util.representation
import pytest

_SRC = Path(__file__).resolve().parents[2]
_TIMEOUT_S = 2.0

_INFO_SCRIPT = """
import json
import sys

import ifcopenshell
from ifcquery.info import info

model = ifcopenshell.open(sys.argv[1])
element = model.by_id(int(sys.argv[2]))
result = info(model, element)
planes = None
geom = result.get("geometry_summary")
if isinstance(geom, dict):
    solids = geom.get("solids") or []
    if solids:
        planes = len(solids[0].get("clipping_planes") or [])
print(json.dumps({"id": result["id"], "type": result["type"], "planes": planes}))
"""

_WALK_SCRIPT = """
import json
import sys

import ifcopenshell
from ifcquery.info import _walk_clipping

model = ifcopenshell.open(sys.argv[1])
wall = model.by_type("IfcWall")[0]
item = next(r for r in wall.Representation.Representations if r.RepresentationIdentifier == "Body").Items[0]
try:
    _base, planes = _walk_clipping(item)
except Exception as exc:
    print(json.dumps({"outcome": "raised", "exc": type(exc).__name__}))
else:
    print(json.dumps({"outcome": "returned", "planes": len(planes)}))
"""

_SESSION_SCRIPT = """
import json
import sys

from ifcmcp.core import IfcSession

session = IfcSession()
session.ifc_load(sys.argv[1])
result = session.ifc_info(int(sys.argv[2]))
planes = None
geom = result.get("geometry_summary")
if isinstance(geom, dict):
    solids = geom.get("solids") or []
    if solids:
        planes = len(solids[0].get("clipping_planes") or [])
print(json.dumps({"id": result["id"], "type": result["type"], "planes": planes}))
"""


def _env() -> dict[str, str]:
    paths = [str(_SRC / "ifcquery"), str(_SRC / "ifcmcp"), str(_SRC / "ifcedit")]
    if os.environ.get("PYTHONPATH"):
        paths.append(os.environ["PYTHONPATH"])
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _rss_kb(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        return None
    return None


def _run(args: list[str], *, timeout: float = _TIMEOUT_S) -> subprocess.CompletedProcess[str]:
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_env())
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        rss_before = _rss_kb(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=0.5)
        except subprocess.TimeoutExpired:
            rss_after = _rss_kb(proc.pid)
            proc.kill()
            proc.communicate()
            growth = None if rss_before is None or rss_after is None else rss_after - rss_before
            pytest.fail(
                f"inspection still running after {timeout}s (VmRSS {rss_before} kB -> {rss_after} kB, delta {growth} kB)"
            )
        proc.kill()
        pytest.fail(f"inspection still running after {timeout}s")
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)


def _assert_summary(stdout: str, element_id: int, max_planes: int) -> None:
    payload = json.loads(stdout)
    assert payload["id"] == element_id
    assert payload["type"] == "IfcWall"
    assert payload["planes"] is None or payload["planes"] <= max_planes


def _body_item(wall):
    return next(r for r in wall.Representation.Representations if r.RepresentationIdentifier == "Body").Items[0]


def _new_wall():
    model = ifcopenshell.api.project.create_file()
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject")
    ifcopenshell.api.unit.assign_unit(model)
    model_context = ifcopenshell.api.context.add_context(model, context_type="Model")
    ifcopenshell.api.context.add_context(
        model,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_context,
    )
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Cyclic")
    body = ifcopenshell.util.representation.get_context(model, "Model", "Body", "MODEL_VIEW")
    return model, wall, body


def _axis(model):
    origin = model.createIfcCartesianPoint((0.0, 0.0, 0.0))
    axis = model.createIfcDirection((0.0, 0.0, 1.0))
    ref = model.createIfcDirection((1.0, 0.0, 0.0))
    return model.createIfcAxis2Placement3D(origin, axis, ref)


def _write_self_plane(path: Path) -> int:
    """Body item is an IfcBooleanClippingResult whose FirstOperand is itself."""
    model, wall, body = _new_wall()
    rep = ifcopenshell.api.geometry.add_wall_representation(
        model,
        context=body,
        length=5.0,
        height=4.0,
        thickness=0.2,
        clippings=[{"location": (0.0, 0.0, 3.0), "normal": (0.0, 0.0, 1.0)}],
    )
    ifcopenshell.api.geometry.assign_representation(model, product=wall, representation=rep)
    clipping = rep.Items[0]
    assert clipping.is_a("IfcBooleanClippingResult")
    assert clipping.SecondOperand.BaseSurface.is_a("IfcPlane")
    clipping.FirstOperand = clipping
    model.write(str(path))
    return wall.id()


def _write_two_cycle(path: Path) -> int:
    """Two clipping results whose FirstOperand attributes point at each other."""
    model, wall, body = _new_wall()
    rep = ifcopenshell.api.geometry.add_wall_representation(
        model,
        context=body,
        length=5.0,
        height=4.0,
        thickness=0.2,
        clippings=[
            {"location": (0.0, 0.0, 3.0), "normal": (0.0, 0.0, 1.0)},
            {"location": (1.0, 0.0, 0.0), "normal": (1.0, 0.0, 0.0)},
        ],
    )
    ifcopenshell.api.geometry.assign_representation(model, product=wall, representation=rep)
    outer = rep.Items[0]
    inner = outer.FirstOperand
    assert outer.is_a("IfcBooleanClippingResult") and inner.is_a("IfcBooleanClippingResult")
    inner.FirstOperand = outer
    model.write(str(path))
    return wall.id()


def _write_self_nonplane(path: Path) -> int:
    """Self-cycle whose second operand is a half-space on a non-plane surface."""
    model, wall, body = _new_wall()
    rep = ifcopenshell.api.geometry.add_wall_representation(model, context=body, length=1.0, height=1.0, thickness=0.2)
    ifcopenshell.api.geometry.assign_representation(model, product=wall, representation=rep)
    surface = model.createIfcCylindricalSurface(_axis(model), 1.0)
    half_space = model.createIfcHalfSpaceSolid(surface, False)
    clipping = model.createIfcBooleanClippingResult("DIFFERENCE", rep.Items[0], half_space)
    clipping.FirstOperand = clipping
    rep.RepresentationType = "Clipping"
    rep.Items = [clipping]
    model.write(str(path))
    return wall.id()


def _reopened_cycle(path: Path, element_id: int, *, kind: str):
    model = ifcopenshell.open(path)
    wall = model.by_id(element_id)
    item = _body_item(wall)
    assert item.is_a("IfcBooleanClippingResult")
    if kind == "self":
        assert item.FirstOperand.id() == item.id()
    elif kind == "two":
        assert item.FirstOperand.FirstOperand.id() == item.id()
        assert item.FirstOperand.id() != item.id()
    else:
        raise AssertionError(kind)
    return wall.id()


def test_info_self_cycle_on_plane_terminates(tmp_path: Path):
    path = tmp_path / "self-plane.ifc"
    element_id = _reopened_cycle(path, _write_self_plane(path), kind="self")
    text = path.read_text()
    assert "IFCBOOLEANCLIPPINGRESULT(.DIFFERENCE.,#" in text
    completed = _run([sys.executable, "-c", _INFO_SCRIPT, str(path), str(element_id)])
    assert completed.returncode == 0, completed.stderr
    _assert_summary(completed.stdout, element_id, max_planes=1)


def test_info_mutual_cycle_on_planes_terminates(tmp_path: Path):
    path = tmp_path / "two-cycle.ifc"
    element_id = _reopened_cycle(path, _write_two_cycle(path), kind="two")
    completed = _run([sys.executable, "-c", _INFO_SCRIPT, str(path), str(element_id)])
    assert completed.returncode == 0, completed.stderr
    _assert_summary(completed.stdout, element_id, max_planes=2)


def test_info_self_cycle_on_nonplane_terminates(tmp_path: Path):
    path = tmp_path / "self-nonplane.ifc"
    element_id = _reopened_cycle(path, _write_self_nonplane(path), kind="self")
    reopened = ifcopenshell.open(path)
    item = _body_item(reopened.by_id(element_id))
    assert item.SecondOperand.is_a("IfcHalfSpaceSolid")
    assert not item.SecondOperand.BaseSurface.is_a("IfcPlane")
    completed = _run([sys.executable, "-c", _INFO_SCRIPT, str(path), str(element_id)])
    assert completed.returncode == 0, completed.stderr
    _assert_summary(completed.stdout, element_id, max_planes=0)


@pytest.mark.parametrize(
    ("name", "writer", "kind", "max_planes"),
    [
        ("self-plane.ifc", _write_self_plane, "self", 1),
        ("two-cycle.ifc", _write_two_cycle, "two", 2),
        ("self-nonplane.ifc", _write_self_nonplane, "self", 0),
    ],
)
def test_walk_clipping_rejects_or_bounds_cycles(tmp_path: Path, name, writer, kind, max_planes):
    path = tmp_path / name
    _reopened_cycle(path, writer(path), kind=kind)
    completed = _run([sys.executable, "-c", _WALK_SCRIPT, str(path)])
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    if payload["outcome"] == "returned":
        assert payload["planes"] <= max_planes
    else:
        assert payload["outcome"] == "raised"


def test_cli_info_self_cycle_terminates(tmp_path: Path):
    path = tmp_path / "self-plane.ifc"
    element_id = _reopened_cycle(path, _write_self_plane(path), kind="self")
    completed = _run([sys.executable, "-m", "ifcquery", str(path), "info", str(element_id)])
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["id"] == element_id
    assert payload["type"] == "IfcWall"
    geom = payload.get("geometry_summary")
    if isinstance(geom, dict) and geom.get("solids"):
        assert len(geom["solids"][0].get("clipping_planes") or []) <= 1


def test_session_ifc_info_self_cycle_terminates(tmp_path: Path):
    path = tmp_path / "self-plane.ifc"
    element_id = _reopened_cycle(path, _write_self_plane(path), kind="self")
    completed = _run([sys.executable, "-c", _SESSION_SCRIPT, str(path), str(element_id)])
    assert completed.returncode == 0, completed.stderr
    _assert_summary(completed.stdout, element_id, max_planes=1)
