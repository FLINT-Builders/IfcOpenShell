# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2021 Thomas Krijnen <thomas@aecgeeks.com>
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

"""Adjacent EXPRESS ``*.exp.cache.dat`` files must not be unpickled.

``ifcopenshell.express.express_parser.parse`` loads ``<schema>.exp.cache.dat``
with ``pickle.load`` when that file is at least as new as the schema. These
tests place a pickle whose reduce payload writes a marker file next to a
schema and assert the marker is absent after each product entry point runs.
They fail while that load still executes.
"""

from __future__ import annotations

import logging
import os
import pickle
import subprocess
import sys
from pathlib import Path

import ifcopenshell.express
import ifcopenshell.validate

_IFC_TEMPLATE = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('model.ifc','2022-10-02T14:16:07',(''),(''),'test','test','');
FILE_SCHEMA(('{schema}'));
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
"""

_NS = 1_000_000_000


def _marker_pickle(marker: Path) -> bytes:
    """Pickle that runs ``eval`` and writes ``marker`` as its first action."""

    class _Payload:
        def __reduce__(self):
            statement = f"open({os.fspath(marker)!r}, 'w').write('executed')"
            return (eval, (statement,))

    return pickle.dumps(_Payload(), protocol=0)


def _write_schema_bundle(directory: Path, marker: Path, *, cache_newer_by_ns: int) -> Path:
    """Write an IFC file, a matching ``.exp``, and an adjacent pickle cache.

    ``cache_newer_by_ns`` is added to the schema mtime to form the cache
    mtime. Zero covers the ``>=`` comparison; a positive value covers a
    strictly newer cache.
    """

    schema_name = "EVILSCHEMA"
    ifc_path = directory / "model.ifc"
    exp_path = directory / "evilschema.exp"
    cache_path = directory / "evilschema.exp.cache.dat"
    ifc_path.write_text(_IFC_TEMPLATE.format(schema=schema_name), encoding="ascii")
    exp_path.write_text("not a schema\n", encoding="ascii")
    cache_path.write_bytes(_marker_pickle(marker))
    exp_mtime = 1_700_000_000 * _NS
    os.utime(exp_path, ns=(exp_mtime, exp_mtime))
    cache_mtime = exp_mtime + cache_newer_by_ns
    os.utime(cache_path, ns=(cache_mtime, cache_mtime))
    return ifc_path


def _assert_marker_absent(marker: Path) -> None:
    if marker.exists():
        raise AssertionError("adjacent .exp.cache.dat pickle payload executed")


def _assert_no_adjacent_pickle(source: str, label: str) -> None:
    for needle in ("pickle.load", ".cache.dat"):
        if needle in source:
            raise AssertionError(f"{label} still contains {needle!r}")


def _validate_in_directory(ifc_path: Path) -> None:
    logger = logging.getLogger("test_express_cache_deserialization")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    previous = Path.cwd()
    os.chdir(ifc_path.parent)
    try:
        try:
            ifcopenshell.validate.validate(ifc_path.name, logger)
        except Exception:
            # Parsing a deliberately invalid schema may raise after the cache
            # is considered. The marker is the signal that matters.
            pass
    finally:
        os.chdir(previous)


def test_validate_does_not_execute_newer_adjacent_pickle_cache(tmp_path: Path) -> None:
    marker = tmp_path / "marker-newer.txt"
    ifc_path = _write_schema_bundle(tmp_path, marker, cache_newer_by_ns=_NS)
    _validate_in_directory(ifc_path)
    _assert_marker_absent(marker)


def test_validate_does_not_execute_same_mtime_adjacent_pickle_cache(tmp_path: Path) -> None:
    marker = tmp_path / "marker-equal.txt"
    ifc_path = _write_schema_bundle(tmp_path, marker, cache_newer_by_ns=0)
    _validate_in_directory(ifc_path)
    _assert_marker_absent(marker)


def test_cli_validate_does_not_execute_adjacent_pickle_cache(tmp_path: Path) -> None:
    marker = tmp_path / "marker-cli.txt"
    _write_schema_bundle(tmp_path, marker, cache_newer_by_ns=_NS)
    subprocess.run(
        [sys.executable, "-m", "ifcopenshell.validate", "model.ifc"],
        cwd=tmp_path,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )
    _assert_marker_absent(marker)


def _parse_schema(exp_path: Path) -> None:
    try:
        ifcopenshell.express.parse(os.fspath(exp_path))
    except Exception:
        pass


def test_express_parse_does_not_execute_newer_adjacent_pickle_cache(tmp_path: Path) -> None:
    """``express.parse`` is the call ``bonsai.tool.debug.Debug.load_express`` makes."""

    marker = tmp_path / "marker-parse-newer.txt"
    ifc_path = _write_schema_bundle(tmp_path, marker, cache_newer_by_ns=_NS)
    _parse_schema(ifc_path.with_name("evilschema.exp"))
    _assert_marker_absent(marker)


def test_express_parse_does_not_execute_same_mtime_adjacent_pickle_cache(tmp_path: Path) -> None:
    marker = tmp_path / "marker-parse-equal.txt"
    ifc_path = _write_schema_bundle(tmp_path, marker, cache_newer_by_ns=0)
    _parse_schema(ifc_path.with_name("evilschema.exp"))
    _assert_marker_absent(marker)


def test_bootstrap_does_not_emit_adjacent_pickle_load() -> None:
    express_dir = Path(ifcopenshell.express.__file__).resolve().parent
    completed = subprocess.run(
        [sys.executable, str(express_dir / "bootstrap.py")],
        cwd=express_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    _assert_no_adjacent_pickle(completed.stdout, "bootstrap.py output")


def test_express_parser_module_does_not_define_adjacent_pickle_load() -> None:
    """The checked-in parser, not only the generator, must drop the cache load."""

    parser_path = Path(ifcopenshell.express.__file__).resolve().parent / "express_parser.py"
    source = parser_path.read_text(encoding="utf-8")
    _assert_no_adjacent_pickle(source, str(parser_path))
