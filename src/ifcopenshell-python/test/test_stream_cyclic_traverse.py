# This file was generated with the assistance of an AI coding tool.
#
# Streaming traversal follows every #id in an entity line and never records
# ids already queued. These tests are the spec for that bug: they fail while
# the loop is present and pass once each reachable entity is returned once.
#
# Callers that share this path all end in ``stream.traverse`` and are covered
# by the cases below (unlimited depth, and ``breadth_first=True``):
#   bonsai.tool.geometry.Geometry.get_ifc_representation_class
#   bonsai.tool.geometry.Geometry.import_representation_parameters
#   bonsai.tool.geometry.Geometry.get_shape_aspect_styles
#   bonsai.tool.loader.Loader.create_camera
#   bonsai.tool.system.System.has_parametric_body
#   bonsai.bim.module.project.operator (representation and style walks)
#   ifcopenshell.util.element.get_layers
#   ifcopenshell.util.element.remove_deep
#   ifcopenshell.util.element.remove_deep2
#   ifcpatch recipes and ifcopenshell.api helpers that call ``file.traverse``
# No other stream operation walks references recursively.

import multiprocessing as mp
import sys
import traceback
from pathlib import Path

import pytest

# A fixed traverse returns as soon as the file is open. The limit only catches
# a walk that keeps queueing entities it has already visited.
_TRAVERSE_TIMEOUT_SECONDS = 10


def _write_ifc(path: Path, entities: dict[int, str]) -> None:
    lines = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');",
        "FILE_NAME('cycle.ifc','2020-01-01T00:00:00',(''),(''),'','','');",
        "FILE_SCHEMA(('IFC4'));",
        "ENDSEC;",
        "DATA;",
    ]
    for step_id in sorted(entities):
        lines.append(f"#{step_id}={entities[step_id]}")
    lines.extend(["ENDSEC;", "END-ISO-10303-21;", ""])
    path.write_text("\n".join(lines))


def _traverse_worker(path, should_stream, start_id, max_levels, breadth_first, conn) -> None:
    try:
        import ifcopenshell

        opened = ifcopenshell.open(path, should_stream=should_stream)
        kwargs = {"breadth_first": breadth_first}
        if max_levels is not None:
            kwargs["max_levels"] = max_levels
        walked = opened.traverse(opened.by_id(start_id), **kwargs)
        conn.send({"ids": [None if entity is None else entity.id() for entity in walked]})
    except Exception:
        conn.send({"error": traceback.format_exc()})


def _traverse(
    path: Path,
    start_id: int,
    max_levels: int | None = None,
    breadth_first: bool = False,
    should_stream: bool = True,
):
    ctx = mp.get_context("fork" if sys.platform != "win32" else "spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_traverse_worker,
        args=(str(path), should_stream, start_id, max_levels, breadth_first, child),
    )
    proc.start()
    child.close()
    proc.join(_TRAVERSE_TIMEOUT_SECONDS)
    if proc.is_alive():
        proc.kill()
        proc.join(5)
        pytest.fail(f"traverse did not return within {_TRAVERSE_TIMEOUT_SECONDS}s")
    if not parent.poll():
        pytest.fail(f"traverse process exited {proc.exitcode} without a result")
    payload = parent.recv()
    if "error" in payload:
        pytest.fail(payload["error"])
    return payload["ids"]


def _assert_ids(ids: list[int | None], start_id: int, expected: set[int]) -> None:
    assert ids, "traverse returned no entities"
    assert ids[0] == start_id
    assert all(entity_id is not None for entity_id in ids)
    assert len(ids) == len(set(ids))
    assert set(ids) == expected


# A shape representation whose item points back at the representation, plus the
# geometric context. This is the graph geometry helpers walk with no depth limit.
_MUTUAL_CYCLE = {
    10: "IFCSHAPEREPRESENTATION(#12,'Body','SweptSolid',(#11));",
    11: "IFCEXTRUDEDAREASOLID(#10,$,#10,1.);",
    12: "IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,$,$);",
}

# The cycle is not the entity traverse starts on. Root references are acyclic;
# the profile and its placement reference each other.
_CYCLE_BELOW_ROOT = {
    10: "IFCSHAPEREPRESENTATION(#12,'Body','SweptSolid',(#11));",
    11: "IFCEXTRUDEDAREASOLID(#13,$,#14,1.);",
    12: "IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,$,$);",
    13: "IFCRECTANGLEPROFILEDEF(.AREA.,$,#15,1.,1.);",
    14: "IFCDIRECTION((0.,0.,1.));",
    15: "IFCAXIS2PLACEMENT2D(#13,$);",
}

# One entity lists the same child twice, and that child points back.
_REPEATED_BACK_EDGE = {
    10: "IFCSHAPEREPRESENTATION(#12,'Body','SweptSolid',(#11,#11));",
    11: "IFCEXTRUDEDAREASOLID(#10,$,#10,1.);",
    12: "IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,$,$);",
}

_SELF_CYCLE = {
    10: "IFCLOCALPLACEMENT(#10,#11);",
    11: "IFCAXIS2PLACEMENT3D(#12,$,$);",
    12: "IFCCARTESIANPOINT((0.,0.,0.));",
}

# Two parents share one direction. No cycle; each id is still reachable once.
_SHARED_DESCENDANT = {
    10: "IFCSHAPEREPRESENTATION(#12,'Body','SweptSolid',(#11));",
    11: "IFCEXTRUDEDAREASOLID(#13,$,#14,1.);",
    12: "IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#14,$);",
    13: "IFCRECTANGLEPROFILEDEF(.AREA.,$,#15,1.,1.);",
    14: "IFCDIRECTION((0.,0.,1.));",
    15: "IFCCARTESIANPOINT((0.,0.));",
}

_DEEP_CHAIN = {
    10: "IFCSHAPEREPRESENTATION($,'Body','SweptSolid',(#11));",
    11: "IFCEXTRUDEDAREASOLID(#12,$,#15,1.);",
    12: "IFCRECTANGLEPROFILEDEF(.AREA.,$,#13,1.,1.);",
    13: "IFCAXIS2PLACEMENT2D(#14,$);",
    14: "IFCCARTESIANPOINT((0.,0.));",
    15: "IFCDIRECTION((0.,0.,1.));",
}


class TestStreamCyclicTraverse:
    def test_mutual_cycle_returns_each_entity_once(self, tmp_path: Path):
        path = tmp_path / "mutual.ifc"
        _write_ifc(path, _MUTUAL_CYCLE)
        ids = _traverse(path, start_id=10)
        _assert_ids(ids, 10, {10, 11, 12})

    def test_mutual_cycle_breadth_first_returns_each_entity_once(self, tmp_path: Path):
        path = tmp_path / "mutual-bfs.ifc"
        _write_ifc(path, _MUTUAL_CYCLE)
        ids = _traverse(path, start_id=10, breadth_first=True)
        _assert_ids(ids, 10, {10, 11, 12})

    def test_cycle_below_the_start_entity_returns_each_entity_once(self, tmp_path: Path):
        path = tmp_path / "below.ifc"
        _write_ifc(path, _CYCLE_BELOW_ROOT)
        ids = _traverse(path, start_id=10)
        _assert_ids(ids, 10, {10, 11, 12, 13, 14, 15})

    def test_self_cycle_returns_each_entity_once(self, tmp_path: Path):
        path = tmp_path / "self.ifc"
        _write_ifc(path, _SELF_CYCLE)
        ids = _traverse(path, start_id=10)
        _assert_ids(ids, 10, {10, 11, 12})

    def test_repeated_reference_on_a_back_edge_returns_each_entity_once(self, tmp_path: Path):
        path = tmp_path / "repeated.ifc"
        _write_ifc(path, _REPEATED_BACK_EDGE)
        ids = _traverse(path, start_id=10)
        _assert_ids(ids, 10, {10, 11, 12})

    def test_shared_descendant_is_returned_once(self, tmp_path: Path):
        path = tmp_path / "shared.ifc"
        _write_ifc(path, _SHARED_DESCENDANT)
        ids = _traverse(path, start_id=10)
        _assert_ids(ids, 10, {10, 11, 12, 13, 14, 15})

    def test_unlimited_walk_reaches_the_end_of_an_acyclic_chain(self, tmp_path: Path):
        path = tmp_path / "chain.ifc"
        _write_ifc(path, _DEEP_CHAIN)
        ids = _traverse(path, start_id=10)
        _assert_ids(ids, 10, {10, 11, 12, 13, 14, 15})

    def test_depth_limit_does_not_walk_into_a_cycle(self, tmp_path: Path):
        path = tmp_path / "limited.ifc"
        _write_ifc(path, _CYCLE_BELOW_ROOT)
        ids = _traverse(path, start_id=10, max_levels=1)
        _assert_ids(ids, 10, {10, 11, 12})

    def test_nonstream_traverse_of_the_same_cycle_returns(self, tmp_path: Path):
        path = tmp_path / "native.ifc"
        _write_ifc(path, _MUTUAL_CYCLE)
        ids = _traverse(path, start_id=10, should_stream=False)
        _assert_ids(ids, 10, {10, 11, 12})
