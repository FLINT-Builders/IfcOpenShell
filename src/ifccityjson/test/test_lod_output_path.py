# This file was generated with the assistance of an AI coding tool.

"""Output paths built from CityJSON level-of-detail values must stay inside the output directory.

Split conversion appends each geometry lod between the output stem and the extension.
These tests load a CityJSON file through cjio and run Cityjson2ifc the way the CLI
(and the Bonsai operator's converter call) does. A level-of-detail value comes from
the CityJSON file. It has to be one path segment: a separator or a ".." segment must
not create or overwrite anything outside the directory of the requested output, and
must not create a subdirectory of that directory. Refusing the value, or rewriting it
to a single safe segment, both satisfy the tests. A plain lod such as "2.2" must still
produce "<stem>2.2<ext>" in the output directory.

The Bonsai operator in src/bonsai/bonsai/bim/module/gis/operator.py is not executed
here; it needs Blender. It calls this same converter. Selecting a lod uses write_file
and does not put that lod in the output path. Split output with no lod filter is the
CLI default, and that is the path the traversal tests run.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from cjio import cityjson
from ifccityjson.cityjson2ifc.cityjson2ifc import Cityjson2ifc

SENTINEL = b"sentinel-do-not-overwrite\n"
TRAVERSAL_LODS = ("/../../outside/other-model", "/../../outside/planted")
NESTED_LOD = "/nested/name"


def _document(lods):
    return {
        "type": "CityJSON",
        "version": "1.1",
        "CityObjects": {
            "building-1": {
                "type": "Building",
                "geometry": [{"type": "MultiPoint", "lod": lod, "boundaries": [0]} for lod in lods],
            }
        },
        "vertices": [[0.0, 0.0, 0.0]],
    }


def _workspace(tmp_path):
    workspace = tmp_path / "workspace"
    output_dir = workspace / "output"
    outside = workspace / "outside"
    output_dir.mkdir(parents=True)
    outside.mkdir()
    (outside / "other-model.ifc").write_bytes(SENTINEL)
    source = workspace / "input.json"
    return workspace, output_dir, source


def _write_cityjson(source, lods):
    source.write_text(json.dumps(_document(lods)), encoding="utf-8")


def _snapshot(root):
    state = {}
    for path in root.rglob("*"):
        key = path.relative_to(root).as_posix()
        if path.is_symlink():
            state[key] = ("symlink", os.readlink(path))
        elif path.is_file():
            state[key] = ("file", path.read_bytes())
        elif path.is_dir():
            state[key] = ("dir", None)
    return state


def _assert_outside_unchanged(before, after):
    changed = []
    for key in sorted(set(before) | set(after)):
        if key == "output" or key.startswith("output/"):
            continue
        if before.get(key) != after.get(key):
            changed.append(key)
    assert changed == [], f"paths outside the output directory changed: {changed}"


def _assert_output_is_flat_files(output_dir):
    for path in output_dir.rglob("*"):
        assert path.is_file(), f"created a directory from a level-of-detail value: {path}"
        assert path.parent == output_dir, f"level-of-detail value created a nested path: {path}"


def _convert(source, output, *, split, lod_argument):
    """Run the converter. lod_argument False means the caller omitted lod, as the CLI does."""
    city_model = cityjson.load(str(source), transform=False)
    data = {"file_destination": str(output), "split": split}
    if lod_argument is not False:
        data["lod"] = lod_argument
    converter = Cityjson2ifc()
    converter.configuration(**data)
    try:
        converter.convert(city_model)
    except Exception:
        # Refusal is acceptable only when the assertions below still hold,
        # including when a write already happened before the exception.
        return


def test_split_conversion_keeps_traversal_lod_inside_output_directory(tmp_path):
    workspace, output_dir, source = _workspace(tmp_path)
    _write_cityjson(source, TRAVERSAL_LODS)
    before = _snapshot(workspace)

    _convert(source, output_dir / "model.ifc", split=True, lod_argument=False)

    _assert_outside_unchanged(before, _snapshot(workspace))
    _assert_output_is_flat_files(output_dir)


def test_lod_separator_does_not_create_nested_output(tmp_path):
    workspace, output_dir, source = _workspace(tmp_path)
    _write_cityjson(source, (NESTED_LOD,))
    before = _snapshot(workspace)

    _convert(source, output_dir / "model.ifc", split=True, lod_argument=False)

    _assert_outside_unchanged(before, _snapshot(workspace))
    _assert_output_is_flat_files(output_dir)


def test_cli_default_split_keeps_traversal_lod_inside_output_directory(tmp_path):
    workspace, output_dir, source = _workspace(tmp_path)
    _write_cityjson(source, TRAVERSAL_LODS)
    before = _snapshot(workspace)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        [sys.executable, "-m", "ifccityjson", "-i", "input.json", "-o", "output/model.ifc"],
        cwd=workspace,
        env=env,
        capture_output=True,
        check=False,
    )

    combined = proc.stdout + proc.stderr
    assert b"No module named" not in combined, combined.decode("utf-8", "replace")
    _assert_outside_unchanged(before, _snapshot(workspace))
    _assert_output_is_flat_files(output_dir)


def test_plain_lod_still_writes_ifc_in_output_directory(tmp_path):
    workspace, output_dir, source = _workspace(tmp_path)
    _write_cityjson(source, ("2.2",))
    before = _snapshot(workspace)
    output = output_dir / "model.ifc"

    _convert(source, output, split=True, lod_argument=False)

    _assert_outside_unchanged(before, _snapshot(workspace))
    written = output_dir / "model2.2.ifc"
    assert written.is_file(), "a plain lod string must still be written next to the output stem"
    assert written.read_bytes().startswith(b"ISO-10303-21;"), "split output for a plain lod must be an IFC file"
    _assert_output_is_flat_files(output_dir)


def test_lod_filter_writes_only_the_requested_output_file(tmp_path):
    workspace, output_dir, source = _workspace(tmp_path)
    _write_cityjson(source, TRAVERSAL_LODS)
    before = _snapshot(workspace)
    output = output_dir / "model.ifc"

    _convert(source, output, split=True, lod_argument=TRAVERSAL_LODS[0])

    _assert_outside_unchanged(before, _snapshot(workspace))
    assert output.is_file()
    assert output.read_bytes().startswith(b"ISO-10303-21;")
    _assert_output_is_flat_files(output_dir)


def test_no_split_writes_only_the_requested_output_file(tmp_path):
    workspace, output_dir, source = _workspace(tmp_path)
    _write_cityjson(source, TRAVERSAL_LODS)
    before = _snapshot(workspace)
    output = output_dir / "model.ifc"

    _convert(source, output, split=False, lod_argument=False)

    _assert_outside_unchanged(before, _snapshot(workspace))
    assert output.is_file()
    assert output.read_bytes().startswith(b"ISO-10303-21;")
    _assert_output_is_flat_files(output_dir)
