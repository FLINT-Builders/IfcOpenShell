# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 IfcOpenShell contributors
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

"""Cyclic IfcMappedItem expansion must stay bounded.

These tests fail while a mapped representation can point at itself, or two
mapped representations can point at each other, and the product still walks
that cycle with no visited set. A fix passes them by skipping the repeated
representation or by raising an error other than an unbounded recursion.
"""

from __future__ import annotations

import ast
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

# The source tree has no compiled wrapper. Same guard as test/bootstrap.py.
if os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")) == os.path.abspath(sys.path[0]):
    sys.path[0:1] = []

import pytest

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.representation

REPO_ROOT = Path(__file__).resolve().parents[4]
IMPORT_IFC = REPO_ROOT / "src/bonsai/bonsai/bim/import_ifc.py"
LOADER = REPO_ROOT / "src/bonsai/bonsai/tool/loader.py"
PARAMETRIC = REPO_ROOT / "src/bonsai/bonsai/tool/parametric.py"
PSET = REPO_ROOT / "src/bonsai/bonsai/tool/pset.py"


class ExpansionTimeout(Exception):
    pass


def caused_by_recursion(exc: BaseException) -> bool:
    stack = [exc]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, RecursionError):
            return True
        stack.append(current.__context__)
        stack.append(current.__cause__)
    return False


def assert_expansion_is_bounded(fn):
    """Fail only when mapped-item expansion does not finish."""

    def handler(signum, frame):
        raise ExpansionTimeout()

    previous = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, 3)
    try:
        try:
            fn()
        except RecursionError:
            pytest.fail("cyclic mapped representation recursed without a bound")
        except ExpansionTimeout:
            pytest.fail("cyclic mapped representation did not finish")
        except SystemError as exc:
            if caused_by_recursion(exc):
                pytest.fail("cyclic mapped representation recursed without a bound")
            raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def load_method(path: Path, class_name: str, method_name: str, namespace: dict):
    source = path.read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    segment = ast.get_source_segment(source, item)
                    decorators = "\n".join(
                        "@" + (ast.get_source_segment(source, deco) or "") for deco in item.decorator_list
                    )
                    code = "from __future__ import annotations\n" + decorators + "\n" + textwrap.dedent(segment or "")
                    exec(compile(code, str(path), "exec"), namespace)
                    return namespace[method_name]
    raise AssertionError(f"{class_name}.{method_name} not found in {path}")


def base_file():
    ifc = ifcopenshell.file(schema="IFC4")
    origin = ifc.createIfcCartesianPoint((0.0, 0.0, 0.0))
    axis = ifc.createIfcAxis2Placement3D(Location=origin)
    target = ifc.createIfcCartesianTransformationOperator3D(LocalOrigin=origin)
    parent = ifc.createIfcGeometricRepresentationContext(
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1e-5,
        WorldCoordinateSystem=axis,
    )
    context = ifc.createIfcGeometricRepresentationSubContext(
        ContextIdentifier="Body",
        ContextType="Model",
        ParentContext=parent,
        TargetView="MODEL_VIEW",
    )
    return ifc, axis, target, context


def shape(ifc, context, items):
    return ifc.createIfcShapeRepresentation(
        ContextOfItems=context,
        RepresentationIdentifier="Body",
        RepresentationType="SweptSolid",
        Items=items,
    )


def mutual_cycle(ifc, axis, target, context, extra_a=(), extra_b=()):
    rep_a = shape(ifc, context, [])
    rep_b = shape(ifc, context, [])
    map_a = ifc.createIfcRepresentationMap(MappingOrigin=axis, MappedRepresentation=rep_a)
    map_b = ifc.createIfcRepresentationMap(MappingOrigin=axis, MappedRepresentation=rep_b)
    rep_a.Items = [ifc.createIfcMappedItem(MappingSource=map_b, MappingTarget=target), *extra_a]
    rep_b.Items = [ifc.createIfcMappedItem(MappingSource=map_a, MappingTarget=target), *extra_b]
    return rep_a, rep_b


def self_cycle(ifc, axis, target, context, extra=()):
    body = shape(ifc, context, [])
    mapping = ifc.createIfcRepresentationMap(MappingOrigin=axis, MappedRepresentation=body)
    body.Items = [ifc.createIfcMappedItem(MappingSource=mapping, MappingTarget=target), *extra]
    return body


def add_wall(ifc, body):
    wall = ifc.createIfcWall(GlobalId=ifcopenshell.guid.new(), Name="Cyclic")
    wall.Representation = ifc.createIfcProductDefinitionShape(Representations=[body])
    return wall


def extrusion(ifc, axis):
    profile = ifc.createIfcRectangleProfileDef("AREA", None, axis, 1.0, 1.0)
    direction = ifc.createIfcDirection((0.0, 0.0, 1.0))
    return ifc.createIfcExtrudedAreaSolid(profile, axis, direction, 1.0)


def reopen(ifc, tmp_path: Path, name: str):
    path = tmp_path / name
    ifc.write(str(path))
    return ifcopenshell.open(str(path)), path


def wall_body(ifc):
    wall = ifc.by_type("IfcWall")[0]
    return wall, wall.Representation.Representations[0]


def acyclic_mapped_body(ifc, axis, target, context, item):
    inner = shape(ifc, context, [item])
    mapping = ifc.createIfcRepresentationMap(MappingOrigin=axis, MappedRepresentation=inner)
    outer = shape(ifc, context, [ifc.createIfcMappedItem(MappingSource=mapping, MappingTarget=target)])
    return outer


def test_resolve_items_bounds_mutual_cycle(tmp_path):
    ifc, axis, target, context = base_file()
    body, _ = mutual_cycle(ifc, axis, target, context, extra_a=(ifc.createIfcSweptDiskSolid(Radius=0.01),))
    add_wall(ifc, body)
    opened, _ = reopen(ifc, tmp_path, "mutual-items.ifc")
    _, body = wall_body(opened)
    assert_expansion_is_bounded(lambda: ifcopenshell.util.representation.resolve_items(body))


def test_resolve_items_bounds_self_cycle(tmp_path):
    ifc, axis, target, context = base_file()
    body = self_cycle(ifc, axis, target, context, extra=(ifc.createIfcSweptDiskSolid(Radius=0.01),))
    add_wall(ifc, body)
    opened, _ = reopen(ifc, tmp_path, "self-items.ifc")
    _, body = wall_body(opened)
    assert_expansion_is_bounded(lambda: ifcopenshell.util.representation.resolve_items(body))


def test_resolve_representation_bounds_single_item_cycle(tmp_path):
    ifc, axis, target, context = base_file()
    body, _ = mutual_cycle(ifc, axis, target, context)
    add_wall(ifc, body)
    opened, _ = reopen(ifc, tmp_path, "mutual-representation.ifc")
    _, body = wall_body(opened)
    assert len(body.Items) == 1
    assert_expansion_is_bounded(lambda: ifcopenshell.util.representation.resolve_representation(body))


def test_resolve_base_items_bounds_cycle(tmp_path):
    ifc, axis, target, context = base_file()
    body = self_cycle(ifc, axis, target, context)
    add_wall(ifc, body)
    opened, _ = reopen(ifc, tmp_path, "self-base-items.ifc")
    _, body = wall_body(opened)
    assert_expansion_is_bounded(lambda: list(ifcopenshell.util.representation.resolve_base_items(body)))


def test_get_styles_bounds_cycle(tmp_path):
    ifc, axis, target, context = base_file()
    body, _ = mutual_cycle(ifc, axis, target, context)
    wall = add_wall(ifc, body)
    opened, _ = reopen(ifc, tmp_path, "styles.ifc")
    wall = opened.by_type("IfcWall")[0]
    assert ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW") is not None
    assert_expansion_is_bounded(lambda: ifcopenshell.util.element.get_styles(wall))


def test_get_elements_by_representation_bounds_cycle(tmp_path):
    ifc, axis, target, context = base_file()
    body, _ = mutual_cycle(ifc, axis, target, context)
    add_wall(ifc, body)
    opened, _ = reopen(ifc, tmp_path, "elements-by-representation.ifc")
    _, body = wall_body(opened)
    assert_expansion_is_bounded(lambda: ifcopenshell.util.element.get_elements_by_representation(opened, body))


def bonsai_namespace():
    namespace = {
        "ifcopenshell": ifcopenshell,
        "np": __import__("numpy"),
        "tool": SimpleNamespace(),
    }

    class Pset:
        get_element_pset = load_method(PSET, "Pset", "get_element_pset", namespace)

    class Parametric:
        is_railing = load_method(PARAMETRIC, "Parametric", "is_railing", namespace)

    class Loader:
        settings = SimpleNamespace(contexts=[])
        is_native_swept_disk_solid = load_method(LOADER, "Loader", "is_native_swept_disk_solid", namespace)

    namespace["tool"].Pset = Pset
    namespace["tool"].Parametric = Parametric
    namespace["tool"].Loader = Loader
    namespace["tool"].Ifc = SimpleNamespace(get=lambda: None)
    return namespace


def importer_from_file(ifc, namespace):
    contexts = ifcopenshell.util.representation.get_prioritised_contexts(ifc)
    namespace["tool"].Loader.settings.contexts = contexts

    class Importer:
        is_native = load_method(IMPORT_IFC, "IfcImporter", "is_native", namespace)
        parse_native_elements = load_method(IMPORT_IFC, "IfcImporter", "parse_native_elements", namespace)

    importer = Importer()
    importer.file = ifc
    importer.elements = set(ifc.by_type("IfcElement"))
    importer.native_elements = set()
    importer.native_data = {}
    importer.unit_scale = 1.0
    importer.ifc_import_settings = SimpleNamespace(should_load_geometry=True)
    wall, body = wall_body(ifc)
    assert body.ContextOfItems in contexts
    assert wall in importer.elements
    return importer, wall, body


def test_loader_native_sweep_check_bounds_cycle(tmp_path):
    ifc, axis, target, context = base_file()
    body, _ = mutual_cycle(ifc, axis, target, context, extra_a=(ifc.createIfcSweptDiskSolid(Radius=0.01),))
    add_wall(ifc, body)
    opened, _ = reopen(ifc, tmp_path, "loader-sweep.ifc")
    namespace = bonsai_namespace()
    _, wall, body = importer_from_file(opened, namespace)
    # Loader.is_native_swept_disk_solid calls resolve_items before any other check.
    assert_expansion_is_bounded(lambda: namespace["tool"].Loader.is_native_swept_disk_solid(wall, body))


def test_importer_parse_native_elements_bounds_multi_item_cycle(tmp_path):
    ifc, axis, target, context = base_file()
    body, _ = mutual_cycle(ifc, axis, target, context, extra_a=(ifc.createIfcSweptDiskSolid(Radius=0.01),))
    add_wall(ifc, body)
    opened, _ = reopen(ifc, tmp_path, "parse-native-multi.ifc")
    namespace = bonsai_namespace()
    importer, _, _ = importer_from_file(opened, namespace)
    assert opened.by_type("IfcSweptDiskSolid")
    assert_expansion_is_bounded(importer.parse_native_elements)


def test_importer_native_walk_bounds_single_item_cycle(tmp_path):
    ifc, axis, target, context = base_file()
    body, _ = mutual_cycle(ifc, axis, target, context)
    add_wall(ifc, body)
    # Present anywhere in the file, this is what makes parse_native_elements walk products.
    ifc.createIfcSweptDiskSolid(Radius=0.01)
    opened, _ = reopen(ifc, tmp_path, "parse-native-single.ifc")
    namespace = bonsai_namespace()
    importer, _, body = importer_from_file(opened, namespace)
    assert len(body.Items) == 1 and body.Items[0].is_a("IfcMappedItem")
    assert_expansion_is_bounded(importer.parse_native_elements)


def run_iterator(path: Path) -> subprocess.CompletedProcess:
    script = r"""
import multiprocessing
import sys
import ifcopenshell
import ifcopenshell.geom

ifc = ifcopenshell.open(sys.argv[1])
wall = ifc.by_type("IfcWall")[0]
context_id = wall.Representation.Representations[0].ContextOfItems.id()
settings = ifcopenshell.geom.settings()
settings.set("mesher-linear-deflection", 0.05)
settings.set("mesher-angular-deflection", 0.5)
settings.set("dimensionality", ifcopenshell.ifcopenshell_wrapper.CURVES_SURFACES_AND_SOLIDS)
settings.set("context-ids", [context_id])
settings.set("apply-default-materials", False)
settings.set("keep-bounding-boxes", True)
settings.set("layerset-first", True)
settings.set("no-wire-intersection-check", True)
iterator = ifcopenshell.geom.iterator(
    settings,
    ifc,
    multiprocessing.cpu_count(),
    include=[wall],
    geometry_library="hybrid-cgal-simple-opencascade",
)
print("initialize", iterator.initialize(), flush=True)
print("survived", flush=True)
"""
    try:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        return subprocess.run(
            [sys.executable, "-c", script, str(path)],
            check=False,
            capture_output=True,
            timeout=30,
            cwd="/tmp",
            env=env,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("geometry iterator did not finish")


def assert_iterator_survives(proc: subprocess.CompletedProcess):
    if proc.returncode != 0 or b"survived" not in proc.stdout:
        pytest.fail(
            "geometry iterator did not survive cyclic mapped items\n"
            f"returncode={proc.returncode}\n"
            f"stdout={proc.stdout!r}\n"
            f"stderr={proc.stderr!r}"
        )


def test_geometry_iterator_survives_cyclic_mapped_body(tmp_path):
    ifc, axis, target, context = base_file()
    body, _ = mutual_cycle(ifc, axis, target, context, extra_a=(extrusion(ifc, axis),))
    add_wall(ifc, body)
    _, path = reopen(ifc, tmp_path, "iterator-cycle.ifc")
    assert_iterator_survives(run_iterator(path))


def test_acyclic_mapped_item_still_resolves(tmp_path):
    ifc, axis, target, context = base_file()
    body = acyclic_mapped_body(ifc, axis, target, context, extrusion(ifc, axis))
    add_wall(ifc, body)
    opened, path = reopen(ifc, tmp_path, "acyclic.ifc")
    _, body = wall_body(opened)
    items = ifcopenshell.util.representation.resolve_items(body)
    assert [item["item"].is_a() for item in items] == ["IfcExtrudedAreaSolid"]
    resolved = ifcopenshell.util.representation.resolve_representation(body)
    assert resolved.Items[0].is_a("IfcExtrudedAreaSolid")
    assert [item.is_a() for item in ifcopenshell.util.representation.resolve_base_items(body)] == [
        "IfcExtrudedAreaSolid"
    ]
    proc = run_iterator(path)
    assert proc.returncode == 0, proc.stderr
    assert b"survived" in proc.stdout
    assert b"initialize True" in proc.stdout
