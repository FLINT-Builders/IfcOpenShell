# This file was generated with the assistance of an AI coding tool.
"""PlacementRelTo cycles must not recurse without a bound.

A crafted IFC file can point an IfcLocalPlacement (or any other
IfcObjectPlacement) at itself, or at another placement that points back.
Opening that file and asking for the element's location is an ordinary
library, IfcPatch, IfcDiff, and geometry-iterator operation.

These tests fail while that walk is unbounded. A fix should remember
placements already seen and, on a repeat, return a finite 4x4 matrix (the
identity is acceptable) or raise an exception that is not RecursionError.
Catching RecursionError after the stack has already been exhausted does not
satisfy the bound: the walk must stop after a handful of calls.
"""

import os
import signal
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

# Same rule as test.bootstrap: the source tree has no compiled extension.
# Pytest may insert that tree anywhere on sys.path, not only at the front.
_PACKAGE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path[:] = [entry for entry in sys.path if os.path.abspath(entry or os.getcwd()) != _PACKAGE_ROOT]

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.placement as placement
import ifcopenshell.util.selector as selector

_SRC = Path(__file__).resolve().parents[3]
for _extra in (_SRC / "ifcpatch", _SRC / "ifcdiff"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import ifcpatch

_PLACEMENT_WALKERS = {"get_local_placement", "get_absolute_placement"}


def _caused_by_recursion(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, RecursionError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__ or getattr(current, "orig_exc", None)
    return False


def assert_bounded(fn, *, max_calls: int, expect_matrix: bool = False):
    """Run fn and fail if the placement walk blows the stack or keeps calling itself."""
    calls = {"n": 0}

    def profile(frame, event, arg):
        if event == "call" and frame.f_code.co_name in _PLACEMENT_WALKERS:
            calls["n"] += 1

    def _timeout(signum, frame):
        raise TimeoutError("placement walk did not finish")

    previous = signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(2)
    sys.setprofile(profile)

    def disarm():
        sys.setprofile(None)
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)

    try:
        try:
            value = fn()
        except RecursionError:
            disarm()
            raise AssertionError("unbounded PlacementRelTo recursion") from None
        except TimeoutError as exc:
            disarm()
            raise AssertionError(str(exc)) from None
        except Exception as exc:
            disarm()
            if _caused_by_recursion(exc):
                raise AssertionError(f"unbounded PlacementRelTo recursion wrapped in {type(exc).__name__}") from None
            value = None
    finally:
        disarm()
    assert calls["n"] <= max_calls, f"placement walk made {calls['n']} recursive calls; limit is {max_calls}"
    if expect_matrix and value is not None:
        matrix = np.asarray(value, dtype=float)
        assert matrix.shape == (4, 4)
        assert np.isfinite(matrix).all()
    return value


def _header(schema: str) -> str:
    return (
        "ISO-10303-21;\n"
        "HEADER;\n"
        "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
        "FILE_NAME('cycle.ifc','2020-01-01T00:00:00',(''),(''),'','','');\n"
        f"FILE_SCHEMA(('{schema}'));\n"
        "ENDSEC;\n"
        "DATA;\n"
    )


def _write(tmp_path: Path, name: str, schema: str, body: str) -> ifcopenshell.file:
    path = tmp_path / name
    path.write_text(_header(schema) + body + "ENDSEC;\nEND-ISO-10303-21;\n", encoding="utf-8")
    return ifcopenshell.open(path)


def _wall_line(schema: str, guid: str) -> str:
    # IFC2X3 IfcWall has no PredefinedType; IFC4 and IFC4X3 do.
    if schema == "IFC2X3":
        return f"#10=IFCWALL('{guid}',$,'Cyclic',$,$,#20,$,$);\n"
    return f"#10=IFCWALL('{guid}',$,'Cyclic',$,$,#20,$,$,$);\n"


def _axis(entity_id: int, point_id: int, xyz: tuple[float, float, float]) -> str:
    x, y, z = xyz
    return f"#{point_id}=IFCCARTESIANPOINT(({x},{y},{z}));\n#{entity_id}=IFCAXIS2PLACEMENT3D(#{point_id},$,$);\n"


def _local(entity_id: int, parent: str, axis_id: int) -> str:
    return f"#{entity_id}=IFCLOCALPLACEMENT({parent},#{axis_id});\n"


def _open_wall(tmp_path: Path, schema: str, placements: str):
    model = _write(tmp_path, f"{schema}.ifc", schema, _wall_line(schema, ifcopenshell.guid.new()) + placements)
    wall = model.by_type("IfcWall")[0]
    assert wall.ObjectPlacement is not None
    return model, wall


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    extras = [str(_SRC / "ifcpatch"), str(_SRC / "ifcdiff")]
    previous = [
        entry
        for entry in env.get("PYTHONPATH", "").split(os.pathsep)
        if entry and os.path.abspath(entry) != _PACKAGE_ROOT
    ]
    env["PYTHONPATH"] = os.pathsep.join(extras + previous)
    return env


def _run_child(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [sys.executable, "-c", script, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env=_child_env(),
            cwd="/tmp",
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"placement walk did not finish: {exc}")


def _assert_child_finished(proc: subprocess.CompletedProcess[str]) -> None:
    assert proc.returncode == 0, f"child exited {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"


def _geometry_body(schema: str, guid: str, parent: str) -> str:
    wall = (
        f"#14=IFCWALL('{guid}',$,'Cyclic',$,$,#20,#13,$);\n"
        if schema == "IFC2X3"
        else f"#14=IFCWALL('{guid}',$,'Cyclic',$,$,#20,#13,$,$);\n"
    )
    return (
        "#1=IFCCARTESIANPOINT((0.,0.,0.));\n"
        "#2=IFCAXIS2PLACEMENT3D(#1,$,$);\n"
        "#3=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#2,$);\n"
        "#4=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#3,$,.MODEL_VIEW.,$);\n"
        "#5=IFCCARTESIANPOINT((0.,0.));\n"
        "#6=IFCAXIS2PLACEMENT2D(#5,$);\n"
        "#7=IFCRECTANGLEPROFILEDEF(.AREA.,$,#6,1.,1.);\n"
        "#8=IFCCARTESIANPOINT((0.,0.,0.));\n"
        "#9=IFCAXIS2PLACEMENT3D(#8,$,$);\n"
        "#10=IFCDIRECTION((0.,0.,1.));\n"
        "#11=IFCEXTRUDEDAREASOLID(#7,#9,#10,1.);\n"
        "#12=IFCSHAPEREPRESENTATION(#4,'Body','SweptSolid',(#11));\n"
        "#13=IFCPRODUCTDEFINITIONSHAPE($,$,(#12));\n"
        + wall
        + f"#20=IFCLOCALPLACEMENT({parent},#21);\n"
        + _axis(21, 22, (1.0, 2.0, 3.0))
    )


_ITERATOR_SCRIPT = """
import sys
import ifcopenshell
import ifcopenshell.geom
model = ifcopenshell.open(sys.argv[1])
wall = model.by_type("IfcWall")[0]
settings = ifcopenshell.geom.settings()
iterator = ifcopenshell.geom.iterator(settings, model, include=[wall])
try:
    iterator.initialize()
except RecursionError:
    sys.exit(2)
print("ok")
"""

_DIFF_SCRIPT = """
import sys
import ifcopenshell
from ifcdiff import IfcDiff
old = ifcopenshell.open(sys.argv[1])
new = ifcopenshell.open(sys.argv[1])
diff = IfcDiff(old, new, relationships=["geometry"], is_shallow=True)
try:
    diff.diff()
except RecursionError:
    sys.exit(2)
print("ok")
"""


def test_self_placement_from_opened_file_is_bounded(tmp_path: Path):
    # Same call Bonsai's importer makes: get_local_placement(element.ObjectPlacement)
    # (bonsai/bim/import_ifc.py get_element_matrix, create_product, create_structural_point_connections).
    _, wall = _open_wall(
        tmp_path,
        "IFC4",
        _local(20, "#20", 21) + _axis(21, 22, (1.0, 2.0, 3.0)),
    )
    assert wall.ObjectPlacement.PlacementRelTo == wall.ObjectPlacement
    assert_bounded(lambda: placement.get_local_placement(wall.ObjectPlacement), max_calls=3, expect_matrix=True)


def test_mutual_placement_cycle_from_opened_file_is_bounded(tmp_path: Path):
    _, wall = _open_wall(
        tmp_path,
        "IFC4",
        _local(20, "#30", 21) + _local(30, "#20", 31) + _axis(21, 22, (1.0, 0.0, 0.0)) + _axis(31, 32, (0.0, 2.0, 0.0)),
    )
    assert wall.ObjectPlacement.PlacementRelTo.PlacementRelTo == wall.ObjectPlacement
    assert_bounded(lambda: placement.get_local_placement(wall.ObjectPlacement), max_calls=4, expect_matrix=True)


def test_three_placement_cycle_is_bounded(tmp_path: Path):
    _, wall = _open_wall(
        tmp_path,
        "IFC4",
        _local(20, "#30", 21)
        + _local(30, "#40", 31)
        + _local(40, "#20", 41)
        + _axis(21, 22, (1.0, 0.0, 0.0))
        + _axis(31, 32, (0.0, 1.0, 0.0))
        + _axis(41, 42, (0.0, 0.0, 1.0)),
    )
    assert_bounded(lambda: placement.get_local_placement(wall.ObjectPlacement), max_calls=5, expect_matrix=True)


def test_cycle_below_a_real_parent_is_bounded(tmp_path: Path):
    # The element placement itself is not repeated; its parent points at itself.
    _, wall = _open_wall(
        tmp_path,
        "IFC4",
        _local(20, "#30", 21) + _local(30, "#30", 31) + _axis(21, 22, (4.0, 0.0, 0.0)) + _axis(31, 32, (0.0, 5.0, 0.0)),
    )
    assert wall.ObjectPlacement != wall.ObjectPlacement.PlacementRelTo
    assert wall.ObjectPlacement.PlacementRelTo.PlacementRelTo == wall.ObjectPlacement.PlacementRelTo
    assert_bounded(lambda: placement.get_local_placement(wall.ObjectPlacement), max_calls=4, expect_matrix=True)


@pytest.mark.parametrize("schema", ["IFC2X3", "IFC4X3_ADD2"])
def test_self_placement_is_bounded_on_other_schemas(tmp_path: Path, schema: str):
    _, wall = _open_wall(tmp_path, schema, _local(20, "#20", 21) + _axis(21, 22, (1.0, 2.0, 3.0)))
    assert_bounded(lambda: placement.get_local_placement(wall.ObjectPlacement), max_calls=3, expect_matrix=True)


def test_linear_and_grid_placement_cycles_are_bounded(tmp_path: Path):
    # IFC4X3 moves PlacementRelTo onto IfcObjectPlacement, so every subtype shares the walk.
    guid = ifcopenshell.guid.new()
    linear = _write(
        tmp_path,
        "linear.ifc",
        "IFC4X3_ADD2",
        f"#10=IFCWALL('{guid}',$,'Cyclic',$,$,#20,$,$,$);\n#20=IFCLINEARPLACEMENT(#20,$,$);\n",
    )
    grid = _write(
        tmp_path,
        "grid.ifc",
        "IFC4X3_ADD2",
        f"#10=IFCWALL('{ifcopenshell.guid.new()}',$,'Cyclic',$,$,#20,$,$,$);\n#20=IFCGRIDPLACEMENT(#20,$,$);\n",
    )
    assert linear.by_type("IfcWall")[0].ObjectPlacement.is_a("IfcLinearPlacement")
    assert grid.by_type("IfcWall")[0].ObjectPlacement.is_a("IfcGridPlacement")
    assert_bounded(
        lambda: placement.get_local_placement(linear.by_type("IfcWall")[0].ObjectPlacement),
        max_calls=3,
        expect_matrix=True,
    )
    assert_bounded(
        lambda: placement.get_local_placement(grid.by_type("IfcWall")[0].ObjectPlacement),
        max_calls=3,
        expect_matrix=True,
    )


def test_storey_elevation_on_cyclic_placement_is_bounded(tmp_path: Path):
    model = _write(
        tmp_path,
        "storey.ifc",
        "IFC4",
        "#10=IFCBUILDINGSTOREY('3$1bQd1ZX7hgLJK8storey01',$,'S',$,$,#20,$,$,$,0.);\n"
        + _local(20, "#20", 21)
        + _axis(21, 22, (0.0, 0.0, 3.0)),
    )
    storey = model.by_type("IfcBuildingStorey")[0]
    assert_bounded(lambda: placement.get_storey_elevation(storey), max_calls=3)


def test_selector_location_query_on_cyclic_placement_is_bounded(tmp_path: Path):
    model, wall = _open_wall(tmp_path, "IFC4", _local(20, "#20", 21) + _axis(21, 22, (1.0, 2.0, 3.0)))
    assert_bounded(lambda: selector.filter_elements(model, "IfcWall, query:x > 0"), max_calls=4)
    assert_bounded(lambda: selector.set_element_value(model, wall, "x", "9"), max_calls=16)


def test_offset_object_placements_cycle_is_bounded(tmp_path: Path):
    model, wall = _open_wall(tmp_path, "IFC4", _local(20, "#20", 21) + _axis(21, 22, (1.0, 2.0, 3.0)))
    # The recipe's own parent walk, then get_local_placement on the root it returns.
    assert_bounded(
        lambda: ifcpatch.execute({"file": model, "recipe": "OffsetObjectPlacements", "arguments": ["1", "0", "0"]}),
        max_calls=8,
    )
    assert wall.ObjectPlacement.PlacementRelTo == wall.ObjectPlacement


def test_parent_chain_still_composes(tmp_path: Path):
    _, wall = _open_wall(
        tmp_path,
        "IFC4",
        _local(20, "#30", 21) + _local(30, "$", 31) + _axis(21, 22, (1.0, 0.0, 0.0)) + _axis(31, 32, (0.0, 2.0, 0.0)),
    )
    matrix = placement.get_local_placement(wall.ObjectPlacement)
    assert np.allclose(matrix[:, 3], (1.0, 2.0, 0.0, 1.0))


def test_deep_acyclic_chain_still_composes(tmp_path: Path):
    depth = 12
    body = []
    for index in range(depth):
        entity_id = 20 + index * 2
        parent = "$" if index == depth - 1 else f"#{entity_id + 2}"
        body.append(_local(entity_id, parent, entity_id + 1))
        body.append(_axis(entity_id + 1, 200 + index, (1.0, 0.0, 0.0)))
    _, wall = _open_wall(tmp_path, "IFC4", "".join(body))
    matrix = assert_bounded(
        lambda: placement.get_local_placement(wall.ObjectPlacement), max_calls=depth + 1, expect_matrix=True
    )
    assert matrix is not None
    assert np.allclose(matrix[0, 3], float(depth))


def test_missing_placement_is_identity():
    assert np.allclose(placement.get_local_placement(None), np.eye(4))


@pytest.mark.parametrize("schema", ["IFC2X3", "IFC4", "IFC4X3_ADD2"])
def test_geometry_iterator_on_cyclic_placement_does_not_abort(tmp_path: Path, schema: str):
    path = tmp_path / f"geom-{schema}.ifc"
    path.write_text(
        _header(schema) + _geometry_body(schema, ifcopenshell.guid.new(), "#20") + "ENDSEC;\nEND-ISO-10303-21;\n",
        encoding="utf-8",
    )
    # The iterator maps PlacementRelTo in C++. A cycle must not abort the process.
    _assert_child_finished(_run_child(_ITERATOR_SCRIPT, str(path)))


@pytest.mark.parametrize("schema", ["IFC2X3", "IFC4", "IFC4X3_ADD2"])
def test_ifcdiff_geometry_on_cyclic_placement_does_not_abort(tmp_path: Path, schema: str):
    path = tmp_path / f"diff-{schema}.ifc"
    path.write_text(
        _header(schema) + _geometry_body(schema, ifcopenshell.guid.new(), "#20") + "ENDSEC;\nEND-ISO-10303-21;\n",
        encoding="utf-8",
    )
    _assert_child_finished(_run_child(_DIFF_SCRIPT, str(path)))


def test_geometry_iterator_on_acyclic_placement_still_runs(tmp_path: Path):
    path = tmp_path / "geom-ok.ifc"
    path.write_text(
        _header("IFC4") + _geometry_body("IFC4", ifcopenshell.guid.new(), "$") + "ENDSEC;\nEND-ISO-10303-21;\n",
        encoding="utf-8",
    )
    script = """
import sys
import ifcopenshell
import ifcopenshell.geom
model = ifcopenshell.open(sys.argv[1])
wall = model.by_type("IfcWall")[0]
settings = ifcopenshell.geom.settings()
iterator = ifcopenshell.geom.iterator(settings, model, include=[wall])
assert iterator.initialize()
shape = iterator.get()
assert shape is not None and shape.id == wall.id()
print("ok")
"""
    _assert_child_finished(_run_child(script, str(path)))
