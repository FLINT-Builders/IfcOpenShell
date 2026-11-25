# This file was generated with the assistance of an AI coding tool.
"""IfcConvert document export must finish on cyclic IFC relationship graphs.

The JSON serializer (and the XML serializer, which walks the same
relationships) recurses through aggregation, nesting, containment, openings,
and fills without recording entities already emitted. A model that closes one
of those edges overflows the process stack and aborts conversion. These tests
fail while that recursion is unbounded and pass once each id is emitted once.
"""

import json
import os
import resource
import shutil
import signal
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

GUID_PROJECT = "00000000000000000000P1"
GUID_A = "00000000000000000000A1"
GUID_B = "00000000000000000000B1"
EXPECTED_IDS = (GUID_PROJECT, GUID_A, GUID_B)

# Deep enough for a normal spatial tree, small enough that an unbounded
# cycle aborts instead of growing the output without bound.
STACK_BYTES = 8 * 1024 * 1024
CONVERT_TIMEOUT_SECONDS = 20


def _limit_stack():
    resource.setrlimit(resource.RLIMIT_STACK, (STACK_BYTES, STACK_BYTES))


def _ifcconvert():
    path = os.environ.get("IFCCONVERT") or shutil.which("IfcConvert")
    if not path:
        pytest.fail("Set IFCCONVERT to the IfcConvert binary built with JSON support")
    return path


def _library_path(binary):
    """Locate the build or install tree that holds IfcConvert's shared libraries."""
    origin = Path(binary).resolve().parent
    candidates = [
        origin,
        origin / ".." / "lib",
        origin / ".." / "ifcparse",
        origin / ".." / "ifcgeom",
        origin / ".." / "plugin",
    ]
    found = []
    for candidate in candidates:
        directory = candidate.resolve()
        if directory.is_dir() and any(directory.glob("libifcopenshell*.so*")):
            found.append(str(directory))
    extra = os.environ.get("LD_LIBRARY_PATH")
    if extra:
        found.append(extra)
    return os.pathsep.join(found)


def _header(schema):
    return f"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('cycle.ifc','2024-01-01T00:00:00',(''),(''),'test','test','');
FILE_SCHEMA(('{schema}'));
ENDSEC;
DATA;
#1=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#2=IFCUNITASSIGNMENT((#1));
#3=IFCPROJECT('{GUID_PROJECT}',$,'Project',$,$,$,$,$,#2);
"""


def _footer():
    return "ENDSEC;\nEND-ISO-10303-21;\n"


def _space(schema, instance_id, guid, name):
    # Both schemas store IfcSpace with eleven attributes; unset ones are $.
    return f"#{instance_id}=IFCSPACE('{guid}',$,'{name}',$,$,$,$,$,$,$,$);"


def _proxy(schema, instance_id, guid, name):
    if schema == "IFC2X3":
        return f"#{instance_id}=IFCBUILDINGELEMENTPROXY('{guid}',$,'{name}',$,$,$,$,$,$);"
    return f"#{instance_id}=IFCBUILDINGELEMENTPROXY('{guid}',$,'{name}',$,$,$,$,$,$);"


def _wall(schema, instance_id, guid, name):
    if schema == "IFC2X3":
        return f"#{instance_id}=IFCWALL('{guid}',$,'{name}',$,$,$,$,$);"
    return f"#{instance_id}=IFCWALL('{guid}',$,'{name}',$,$,$,$,$,$);"


def _opening(schema, instance_id, guid, name):
    if schema == "IFC2X3":
        return f"#{instance_id}=IFCOPENINGELEMENT('{guid}',$,'{name}',$,$,$,$,$);"
    return f"#{instance_id}=IFCOPENINGELEMENT('{guid}',$,'{name}',$,$,$,$,$,$);"


def _aggregate(instance_id, guid, relating, related):
    return f"#{instance_id}=IFCRELAGGREGATES('{guid}',$,$,$,#{relating},(#{related}));"


def _nest(instance_id, guid, relating, related):
    return f"#{instance_id}=IFCRELNESTS('{guid}',$,$,$,#{relating},(#{related}));"


def _contain(instance_id, guid, structure, element):
    return f"#{instance_id}=IFCRELCONTAINEDINSPATIALSTRUCTURE('{guid}',$,$,$,(#{element}),#{structure});"


def _voids(instance_id, guid, element, opening):
    return f"#{instance_id}=IFCRELVOIDSELEMENT('{guid}',$,$,$,#{element},#{opening});"


def _fills(instance_id, guid, opening, element):
    return f"#{instance_id}=IFCRELFILLSELEMENT('{guid}',$,$,$,#{opening},#{element});"


def _model(schema, body_lines):
    return _header(schema) + "\n".join(body_lines) + "\n" + _footer()


def _acyclic(schema):
    return _model(
        schema,
        [
            _space(schema, 10, GUID_A, "SpaceA"),
            _space(schema, 11, GUID_B, "SpaceB"),
            _aggregate(12, "0000000000000000000R01", 3, 10),
            _aggregate(13, "0000000000000000000R02", 10, 11),
        ],
    )


def _aggregation_cycle(schema):
    """Project aggregates A, A aggregates B, and B aggregates A."""
    return _model(
        schema,
        [
            _space(schema, 10, GUID_A, "SpaceA"),
            _space(schema, 11, GUID_B, "SpaceB"),
            _aggregate(12, "0000000000000000000R01", 3, 10),
            _aggregate(13, "0000000000000000000R02", 10, 11),
            _aggregate(14, "0000000000000000000R03", 11, 10),
        ],
    )


def _nesting_cycle(schema):
    """Project aggregates A; A and B nest each other."""
    return _model(
        schema,
        [
            _proxy(schema, 10, GUID_A, "ProxyA"),
            _proxy(schema, 11, GUID_B, "ProxyB"),
            _aggregate(12, "0000000000000000000R01", 3, 10),
            _nest(13, "0000000000000000000R02", 10, 11),
            _nest(14, "0000000000000000000R03", 11, 10),
        ],
    )


def _containment_cycle(schema):
    """Project aggregates A; A contains B and B contains A."""
    return _model(
        schema,
        [
            _space(schema, 10, GUID_A, "SpaceA"),
            _space(schema, 11, GUID_B, "SpaceB"),
            _aggregate(12, "0000000000000000000R01", 3, 10),
            _contain(13, "0000000000000000000R02", 10, 11),
            _contain(14, "0000000000000000000R03", 11, 10),
        ],
    )


def _opening_fill_cycle(schema):
    """An opening aggregated under the project is filled by a wall that voids that opening."""
    return _model(
        schema,
        [
            _opening(schema, 10, GUID_A, "OpeningA"),
            _wall(schema, 11, GUID_B, "WallB"),
            _aggregate(12, "0000000000000000000R01", 3, 10),
            _fills(13, "0000000000000000000R02", 10, 11),
            _voids(14, "0000000000000000000R03", 11, 10),
        ],
    )


def _group_cycle(schema):
    """Two IfcGroups assign each other. XML walks IfcRelAssignsToGroup without a visited set."""
    return _model(
        schema,
        [
            f"#10=IFCGROUP('{GUID_A}',$,'GroupA',$,$);",
            f"#11=IFCGROUP('{GUID_B}',$,'GroupB',$,$);",
            f"#12=IFCRELASSIGNSTOGROUP('0000000000000000000R02',$,$,$,(#11),$,#10);",
            f"#13=IFCRELASSIGNSTOGROUP('0000000000000000000R03',$,$,$,(#10),$,#11);",
        ],
    )


def _task_nesting_cycle():
    """IFC4 work schedule controls a task that nests a second task which nests the first.

    Ifc2x3's XML task writer does not follow IfcRelNests, so this case is IFC4 only.
    """
    return _model(
        "IFC4",
        [
            f"#10=IFCTASK('{GUID_A}',$,'TaskA',$,$,$,$,$,$,.F.,$,$,$);",
            f"#11=IFCTASK('{GUID_B}',$,'TaskB',$,$,$,$,$,$,.F.,$,$,$);",
            (
                "#12=IFCWORKSCHEDULE('0000000000000000000WS1',$,'Schedule',$,$,$,"
                "'2024-01-01T00:00:00',$,$,$,$,'2024-01-01T00:00:00',$,$);"
            ),
            "#13=IFCRELASSIGNSTOCONTROL('0000000000000000000R02',$,$,$,(#10),$,#12);",
            _nest(14, "0000000000000000000R03", 10, 11),
            _nest(15, "0000000000000000000R04", 11, 10),
        ],
    )


def _type_aggregation_cycle(schema):
    """Two type objects aggregate each other. XML descends every IfcTypeObject."""
    return _model(
        schema,
        [
            f"#10=IFCWALLTYPE('{GUID_A}',$,'WallTypeA',$,$,$,$,$,$,.STANDARD.);",
            f"#11=IFCWALLTYPE('{GUID_B}',$,'WallTypeB',$,$,$,$,$,$,.STANDARD.);",
            _aggregate(12, "0000000000000000000R02", 10, 11),
            _aggregate(13, "0000000000000000000R03", 11, 10),
        ],
    )


def _convert(tmp_path, schema, body, extension):
    ifc_path = tmp_path / f"model-{schema}.ifc"
    out_path = tmp_path / f"model-{schema}.{extension}"
    ifc_path.write_text(body, encoding="ascii")
    env = os.environ.copy()
    binary = _ifcconvert()
    library_path = _library_path(binary)
    if library_path:
        env["LD_LIBRARY_PATH"] = library_path
    try:
        completed = subprocess.run(
            [binary, "-y", "-q", "--no-progress", str(ifc_path), str(out_path)],
            env=env,
            capture_output=True,
            timeout=CONVERT_TIMEOUT_SECONDS,
            preexec_fn=_limit_stack,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"IfcConvert did not finish within {CONVERT_TIMEOUT_SECONDS}s: {exc}")
    return completed, out_path


def _signal_name(returncode):
    if returncode >= 0:
        return None
    try:
        return signal.Signals(-returncode).name
    except ValueError:
        return str(-returncode)


def _assert_finished(completed, out_path):
    rendered = (completed.stderr or b"").decode("utf-8", errors="replace")
    rendered += (completed.stdout or b"").decode("utf-8", errors="replace")
    signame = _signal_name(completed.returncode)
    assert completed.returncode == 0, (
        f"IfcConvert exited {completed.returncode} ({signame}); output exists={out_path.exists()}; log:\n{rendered}"
    )
    assert out_path.is_file(), f"IfcConvert wrote no output file {out_path}"
    assert out_path.stat().st_size < 1_000_000, f"output {out_path} is unexpectedly large"


def _ids_from_json(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    objects = document["metaObjects"]
    return [obj["id"] for obj in objects], objects


def _ids_from_xml(path):
    root = ET.parse(path).getroot()
    return [element.attrib["id"] for element in root.iter() if "id" in element.attrib]


def _assert_ids_once(ids):
    for guid in EXPECTED_IDS:
        assert ids.count(guid) == 1, f"{guid} appears {ids.count(guid)} times in {ids}"


SCHEMAS = ("IFC4", "IFC2X3")
EXTENSIONS = ("json", "xml")
CYCLES = {
    "aggregation": _aggregation_cycle,
    "nesting": _nesting_cycle,
    "containment": _containment_cycle,
    "opening_fill": _opening_fill_cycle,
}


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("extension", EXTENSIONS)
def test_acyclic_spatial_tree_exports(tmp_path, schema, extension):
    completed, out_path = _convert(tmp_path, schema, _acyclic(schema), extension)
    _assert_finished(completed, out_path)
    if extension == "json":
        ids, objects = _ids_from_json(out_path)
        _assert_ids_once(ids)
        child = next(obj for obj in objects if obj["id"] == GUID_B)
        assert child["parent"] == GUID_A
    else:
        _assert_ids_once(_ids_from_xml(out_path))


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("extension", EXTENSIONS)
@pytest.mark.parametrize("cycle_name", sorted(CYCLES))
def test_cyclic_relationship_exports_once(tmp_path, schema, extension, cycle_name):
    body = CYCLES[cycle_name](schema)
    completed, out_path = _convert(tmp_path, schema, body, extension)
    _assert_finished(completed, out_path)
    ids = _ids_from_json(out_path)[0] if extension == "json" else _ids_from_xml(out_path)
    _assert_ids_once(ids)


@pytest.mark.parametrize("schema", SCHEMAS)
def test_xml_group_cycle_exports_once(tmp_path, schema):
    completed, out_path = _convert(tmp_path, schema, _group_cycle(schema), "xml")
    _assert_finished(completed, out_path)
    ids = _ids_from_xml(out_path)
    assert ids.count(GUID_PROJECT) == 1
    # The group walk is invoked once per IfcGroup. A visited set stops the cycle;
    # each group may still be written once from that outer loop.
    assert 1 <= ids.count(GUID_A) <= 2
    assert 1 <= ids.count(GUID_B) <= 2


def test_xml_task_nesting_cycle_exports_once(tmp_path):
    completed, out_path = _convert(tmp_path, "IFC4", _task_nesting_cycle(), "xml")
    _assert_finished(completed, out_path)
    _assert_ids_once(_ids_from_xml(out_path))


@pytest.mark.parametrize("schema", SCHEMAS)
def test_xml_type_aggregation_cycle_exports_once(tmp_path, schema):
    completed, out_path = _convert(tmp_path, schema, _type_aggregation_cycle(schema), "xml")
    _assert_finished(completed, out_path)
    ids = _ids_from_xml(out_path)
    assert ids.count(GUID_PROJECT) == 1
    # finalize() calls descend once per type object, so a per-descent visited set
    # still allows each type to be emitted from its own call.
    assert 1 <= ids.count(GUID_A) <= 2
    assert 1 <= ids.count(GUID_B) <= 2
