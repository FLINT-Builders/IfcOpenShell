# This file was generated with the assistance of an AI coding tool.

"""Cyclic IFC references must not exhaust the process stack during geometry mapping.

mapping::map() stores a result only after a conversion finishes and does not
record entities that are still being converted. A file an attacker supplies can
therefore recurse until the stack overflows. These tests call the same entry
points IfcConvert, ifcopenshell.geom, and Bonsai use. They fail while that
recursion kills the process, and they pass when conversion reports failure
instead.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if not any(_PACKAGE_ROOT.joinpath("ifcopenshell").glob("_ifcopenshell_wrapper*.so")):
    _root = str(_PACKAGE_ROOT)
    sys.path[:] = [entry for entry in sys.path if os.path.abspath(entry or os.curdir) != _root]

import ifcopenshell
import ifcopenshell.geom

GEOMETRY_LIBRARY = os.environ.get("IFC_GEOMETRY_LIBRARY", "passthrough")
WORKER_TIMEOUT_SECONDS = 20


def _guid():
    return ifcopenshell.guid.new()


def _context(file):
    origin = file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    axis = file.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0))
    ref = file.create_entity("IfcDirection", DirectionRatios=(1.0, 0.0, 0.0))
    placement = file.create_entity("IfcAxis2Placement3D", Location=origin, Axis=axis, RefDirection=ref)
    context = file.create_entity(
        "IfcGeometricRepresentationContext",
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1e-5,
        WorldCoordinateSystem=placement,
    )
    body = file.create_entity(
        "IfcGeometricRepresentationSubContext",
        ContextIdentifier="Body",
        ContextType="Model",
        ParentContext=context,
        TargetView="MODEL_VIEW",
    )
    return body, placement


def _box(file, position):
    points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    polyline = file.create_entity(
        "IfcPolyline",
        Points=[file.create_entity("IfcCartesianPoint", Coordinates=point) for point in points],
    )
    profile = file.create_entity("IfcArbitraryClosedProfileDef", ProfileType="AREA", OuterCurve=polyline)
    direction = file.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0))
    return file.create_entity(
        "IfcExtrudedAreaSolid",
        SweptArea=profile,
        Position=position,
        ExtrudedDirection=direction,
        Depth=1.0,
    )


def _wall(file, body, placement, items, representation_type):
    representation = file.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=body,
        RepresentationIdentifier="Body",
        RepresentationType=representation_type,
        Items=items,
    )
    shape = file.create_entity("IfcProductDefinitionShape", Representations=[representation])
    wall = file.create_entity(
        "IfcWall",
        GlobalId=_guid(),
        Name="Wall",
        ObjectPlacement=placement,
        Representation=shape,
    )
    return wall, representation


def _shifted_target(file):
    # A non-identity target keeps representation_mapped_to() from eliding the
    # representation, so the iterator creates a normal conversion task for it.
    origin = file.create_entity("IfcCartesianPoint", Coordinates=(1.0, 0.0, 0.0))
    return file.create_entity("IfcCartesianTransformationOperator3D", LocalOrigin=origin)


def _identity_target(file):
    origin = file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    return file.create_entity("IfcCartesianTransformationOperator3D", LocalOrigin=origin)


def _new_file():
    file = ifcopenshell.file(schema="IFC4")
    file.create_entity("IfcProject", GlobalId=_guid(), Name="Cyclic mapping")
    body, position = _context(file)
    placement = file.create_entity("IfcLocalPlacement", RelativePlacement=position)
    return file, body, position, placement


def build_model(kind):
    """Return (file, entity id that the caller converts)."""
    file, body, position, placement = _new_file()

    if kind == "extrusion":
        wall, _representation = _wall(file, body, placement, [_box(file, position)], "SweptSolid")
        return file, wall.id()

    if kind == "mapped":
        source = file.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=body,
            RepresentationIdentifier="Body",
            RepresentationType="SweptSolid",
            Items=[_box(file, position)],
        )
        mapped = file.create_entity(
            "IfcMappedItem",
            MappingSource=file.create_entity(
                "IfcRepresentationMap",
                MappingOrigin=position,
                MappedRepresentation=source,
            ),
            MappingTarget=_shifted_target(file),
        )
        wall, _representation = _wall(file, body, placement, [mapped], "MappedRepresentation")
        return file, wall.id()

    if kind in {"mapped-self", "mapped-identity"}:
        representation = file.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=body,
            RepresentationIdentifier="Body",
            RepresentationType="MappedRepresentation",
            Items=[],
        )
        target = _identity_target(file) if kind == "mapped-identity" else _shifted_target(file)
        mapped = file.create_entity(
            "IfcMappedItem",
            MappingSource=file.create_entity(
                "IfcRepresentationMap",
                MappingOrigin=position,
                MappedRepresentation=representation,
            ),
            MappingTarget=target,
        )
        representation.Items = [mapped]
        shape = file.create_entity("IfcProductDefinitionShape", Representations=[representation])
        wall = file.create_entity(
            "IfcWall", GlobalId=_guid(), Name="Wall", ObjectPlacement=placement, Representation=shape
        )
        return file, wall.id()

    if kind == "mapped-mutual":
        first = file.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=body,
            RepresentationIdentifier="Body",
            RepresentationType="MappedRepresentation",
            Items=[],
        )
        second = file.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=body,
            RepresentationIdentifier="Box",
            RepresentationType="MappedRepresentation",
            Items=[],
        )
        target = _shifted_target(file)
        first.Items = [
            file.create_entity(
                "IfcMappedItem",
                MappingSource=file.create_entity(
                    "IfcRepresentationMap", MappingOrigin=position, MappedRepresentation=second
                ),
                MappingTarget=target,
            )
        ]
        second.Items = [
            file.create_entity(
                "IfcMappedItem",
                MappingSource=file.create_entity(
                    "IfcRepresentationMap", MappingOrigin=position, MappedRepresentation=first
                ),
                MappingTarget=target,
            )
        ]
        shape = file.create_entity("IfcProductDefinitionShape", Representations=[first])
        wall = file.create_entity(
            "IfcWall", GlobalId=_guid(), Name="Wall", ObjectPlacement=placement, Representation=shape
        )
        return file, wall.id()

    if kind == "placement-self":
        placement.PlacementRelTo = placement
        wall, _representation = _wall(file, body, placement, [_box(file, position)], "SweptSolid")
        return file, wall.id()

    if kind == "placement-direct":
        placement.PlacementRelTo = placement
        return file, placement.id()

    if kind == "placement-mutual":
        other = file.create_entity("IfcLocalPlacement", RelativePlacement=position, PlacementRelTo=placement)
        placement.PlacementRelTo = other
        wall, _representation = _wall(file, body, placement, [_box(file, position)], "SweptSolid")
        return file, wall.id()

    if kind == "boolean-self":
        solid = _box(file, position)
        boolean = file.create_entity("IfcBooleanResult", Operator="UNION", FirstOperand=solid, SecondOperand=solid)
        boolean.FirstOperand = boolean
        wall, _representation = _wall(file, body, placement, [boolean], "CSG")
        return file, wall.id()

    if kind == "boolean-item":
        solid = _box(file, position)
        boolean = file.create_entity("IfcBooleanResult", Operator="UNION", FirstOperand=solid, SecondOperand=solid)
        boolean.FirstOperand = boolean
        return file, boolean.id()

    if kind == "boolean-mutual":
        solid = _box(file, position)
        first = file.create_entity("IfcBooleanResult", Operator="UNION", FirstOperand=solid, SecondOperand=solid)
        second = file.create_entity("IfcBooleanResult", Operator="UNION", FirstOperand=solid, SecondOperand=solid)
        first.FirstOperand = second
        second.FirstOperand = first
        wall, _representation = _wall(file, body, placement, [first], "CSG")
        return file, wall.id()

    if kind == "boolean-intersection-self":
        solid = _box(file, position)
        boolean = file.create_entity(
            "IfcBooleanResult", Operator="INTERSECTION", FirstOperand=solid, SecondOperand=solid
        )
        boolean.FirstOperand = boolean
        return file, boolean.id()

    if kind == "csg-self":
        solid = _box(file, position)
        boolean = file.create_entity("IfcBooleanResult", Operator="UNION", FirstOperand=solid, SecondOperand=solid)
        boolean.FirstOperand = boolean
        csg = file.create_entity("IfcCsgSolid", TreeRootExpression=boolean)
        return file, csg.id()

    if kind == "trimmed-curve-self":
        curve = file.create_entity(
            "IfcTrimmedCurve",
            BasisCurve=file.create_entity(
                "IfcPolyline",
                Points=[file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0))],
            ),
            Trim1=[file.create_entity("IfcParameterValue", 0.0)],
            Trim2=[file.create_entity("IfcParameterValue", 1.0)],
            SenseAgreement=True,
            MasterRepresentation="PARAMETER",
        )
        curve.BasisCurve = curve
        return file, curve.id()

    raise AssertionError(kind)


def _write(tmp_path, kind):
    file, entity_id = build_model(kind)
    path = tmp_path / f"{kind}.ifc"
    file.write(str(path))
    reopened = ifcopenshell.open(str(path))
    assert reopened.by_id(entity_id) is not None
    return path, entity_id


def _run_worker(path, entity_id, mode):
    try:
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "worker", str(path), str(entity_id), mode],
            check=False,
            capture_output=True,
            text=True,
            timeout=WORKER_TIMEOUT_SECONDS,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as raised:
        pytest.fail(f"{mode} did not return within {WORKER_TIMEOUT_SECONDS}s: {raised}")


def _assert_converted(completed):
    assert completed.returncode == 0, completed.stderr
    assert "MESH " in completed.stdout, completed.stdout + completed.stderr
    count = int(completed.stdout.split("MESH ", 1)[1].split()[0])
    assert count > 0


def _assert_refused(completed):
    assert completed.returncode == 0, (
        f"geometry conversion was killed (return code {completed.returncode})\n"
        f"{completed.stdout}\n{completed.stderr}"
    )
    assert "REFUSED" in completed.stdout, completed.stdout + completed.stderr
    assert "MESH " not in completed.stdout


def _worker(path, entity_id, mode):
    file = ifcopenshell.open(path)
    instance = file.by_id(int(entity_id))
    settings = ifcopenshell.geom.settings()
    try:
        if mode == "create":
            result = ifcopenshell.geom.create_shape(settings, instance, geometry_library=GEOMETRY_LIBRARY)
            geometry = getattr(result, "geometry", result)
            verts = getattr(geometry, "verts", None) or []
            if len(verts) > 0:
                print(f"MESH {len(verts)}")
            else:
                print("REFUSED empty geometry")
            return
        if mode == "iterate-noparallel":
            settings.set("no-parallel-mapping", True)
            threads = 1
        elif mode == "iterate-threads":
            threads = 2
        elif mode == "iterate":
            threads = 1
        else:
            raise AssertionError(mode)
        iterator = ifcopenshell.geom.iterator(settings, file, threads, geometry_library=GEOMETRY_LIBRARY)
        if not iterator.initialize():
            print("REFUSED iterator produced no element")
            return
        element = iterator.get()
        verts = element.geometry.verts
        if len(verts) > 0:
            print(f"MESH {len(verts)}")
        else:
            print("REFUSED empty geometry")
    except Exception as raised:
        print(f"REFUSED {type(raised).__name__}: {raised}")


BENIGN_CREATE = ["extrusion", "mapped"]
CYCLIC_CREATE = [
    "mapped-self",
    "mapped-identity",
    "mapped-mutual",
    "placement-self",
    "placement-direct",
    "placement-mutual",
    "boolean-self",
    "boolean-item",
    "boolean-mutual",
    "boolean-intersection-self",
    "csg-self",
    "trimmed-curve-self",
]
CYCLIC_ITERATE = [
    "mapped-self",
    "mapped-mutual",
    "placement-self",
    "placement-mutual",
    "boolean-self",
    "boolean-mutual",
]


@pytest.mark.parametrize("kind", BENIGN_CREATE)
def test_benign_create_shape_produces_geometry(tmp_path, kind):
    path, entity_id = _write(tmp_path, kind)
    _assert_converted(_run_worker(path, entity_id, "create"))


@pytest.mark.parametrize("kind", ["extrusion", "mapped"])
def test_benign_iterator_produces_geometry(tmp_path, kind):
    path, entity_id = _write(tmp_path, kind)
    _assert_converted(_run_worker(path, entity_id, "iterate"))


@pytest.mark.parametrize("kind", CYCLIC_CREATE)
def test_cyclic_create_shape_refuses(tmp_path, kind):
    path, entity_id = _write(tmp_path, kind)
    _assert_refused(_run_worker(path, entity_id, "create"))


@pytest.mark.parametrize("kind", CYCLIC_ITERATE)
def test_cyclic_iterator_refuses(tmp_path, kind):
    path, entity_id = _write(tmp_path, kind)
    _assert_refused(_run_worker(path, entity_id, "iterate"))


def test_cyclic_mapped_item_iterator_without_parallel_mapping(tmp_path):
    path, entity_id = _write(tmp_path, "mapped-self")
    _assert_refused(_run_worker(path, entity_id, "iterate-noparallel"))


def test_cyclic_placement_iterator_with_two_threads(tmp_path):
    path, entity_id = _write(tmp_path, "placement-self")
    _assert_refused(_run_worker(path, entity_id, "iterate-threads"))


def _ifcconvert():
    binary = os.environ.get("IFC_CONVERT")
    if binary:
        return binary
    return None


@pytest.mark.parametrize(
    "kind",
    ["mapped-self", "placement-self", "boolean-self"],
)
def test_ifcconvert_cyclic_file_does_not_crash(tmp_path, kind):
    binary = _ifcconvert()
    if not binary:
        pytest.skip("Set IFC_CONVERT to the IfcConvert binary to run this case")
    path, _entity_id = _write(tmp_path, kind)
    # TTL does not force use-world-coords, so a mapped representation is not
    # skipped before mapping. OBJ does force that setting; placement and
    # boolean cycles still reach mapping::map() for OBJ.
    suffix = ".ttl" if kind == "mapped-self" else ".obj"
    output = tmp_path / f"out{suffix}"
    try:
        completed = subprocess.run(
            [binary, "--kernel", GEOMETRY_LIBRARY, "-y", str(path), str(output)],
            check=False,
            capture_output=True,
            text=True,
            timeout=WORKER_TIMEOUT_SECONDS,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as raised:
        pytest.fail(f"IfcConvert did not return within {WORKER_TIMEOUT_SECONDS}s: {raised}")
    assert completed.returncode == 1, (
        f"IfcConvert return code {completed.returncode}\n{completed.stdout}\n{completed.stderr}"
    )
    assert not output.exists() or output.stat().st_size == 0


def test_ifcconvert_benign_mapped_wall_writes_mesh(tmp_path):
    binary = _ifcconvert()
    if not binary:
        pytest.skip("Set IFC_CONVERT to the IfcConvert binary to run this case")
    path, _entity_id = _write(tmp_path, "mapped")
    output = tmp_path / "out.obj"
    completed = subprocess.run(
        [binary, "--kernel", GEOMETRY_LIBRARY, "-y", str(path), str(output)],
        check=False,
        capture_output=True,
        text=True,
        timeout=WORKER_TIMEOUT_SECONDS,
        env=os.environ.copy(),
    )
    assert completed.returncode == 0, completed.stderr
    text = output.read_text(encoding="utf-8", errors="replace")
    assert "\nv " in f"\n{text}"


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "worker":
        _worker(sys.argv[2], sys.argv[3], sys.argv[4])
