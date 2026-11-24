# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
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

"""Header preview must not materialize an unbounded line.

IfcHeaderExtractor.extract() is what Bonsai runs while a file is only
selected in the Open IFC Project browser, and again when a recent-project
tooltip is shown. These tests fail while that preview reads with next()
and no length limit. A later fix should keep every preview, including
.ifc and .ifczip, inside MAX_HEADER_BYTES of decompressed or decoded input.
"""

import importlib.util
import tracemalloc
import zipfile
from pathlib import Path

# Above 50 reads of 64 KiB (the existing line cap times a small readline limit)
# and below the newline-free fixture, so a bounded preview passes and an
# unbounded next() fails.
MAX_HEADER_BYTES = 4 * 1024 * 1024
BOMB_BYTES = 8 * 1024 * 1024

_FILE_PY = Path(__file__).resolve().parents[2] / "ifcopenshell" / "util" / "file.py"

_NORMAL_HEADER = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition[DesignTransferView]'),'2;1');
FILE_NAME('file.ifc','2024-06-25T15:48:10+05:00',(),(),'IfcOpenShell','Bonsai','Nobody');
FILE_SCHEMA(('IFC4X3_ADD2'));
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
"""


def _load_subject():
    # Header extraction does not use the native wrapper. Load this checkout's
    # module even when that wrapper is not built.
    spec = importlib.util.spec_from_file_location("ifcopenshell.util.file", _FILE_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


subject = _load_subject()


class _DecompressedByteCounter:
    """Count bytes ZipExtFile actually decompresses, once each."""

    def __init__(self) -> None:
        self.total = 0
        self._orig = zipfile.ZipExtFile._read1

    def _read1(self, wrapped_self, n):
        data = self._orig(wrapped_self, n)
        self.total += len(data)
        return data

    def __enter__(self):
        counter = self

        def _read1(wrapped_self, n):
            return counter._read1(wrapped_self, n)

        zipfile.ZipExtFile._read1 = _read1
        return self

    def __exit__(self, exc_type, exc, tb):
        zipfile.ZipExtFile._read1 = self._orig
        return False


def _write_deflated_ifczip(path: Path, first_name: str, first_payload: bytes) -> None:
    # A later small member must not hide a bomb in the first entry.
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(first_name, first_payload)
        archive.writestr("later.ifc", b"FILE_SCHEMA(('IFC4'));\n")


def _preview(path: Path):
    try:
        return subject.IfcHeaderExtractor(str(path)).extract()
    except MemoryError:
        raise
    except Exception:
        return None


def _peak_during(callback) -> int:
    tracemalloc.start()
    try:
        callback()
        _current, peak = tracemalloc.get_traced_memory()
        return peak
    finally:
        tracemalloc.stop()


class TestHeaderExtractorBounds:
    def test_small_ifczip_header_still_extracts(self, tmp_path: Path) -> None:
        path = tmp_path / "model.ifczip"
        _write_deflated_ifczip(path, "model.ifc", _NORMAL_HEADER.encode())
        with _DecompressedByteCounter() as counter:
            header = _preview(path)
            peak = _peak_during(lambda: subject.IfcHeaderExtractor(str(path)).extract())
        assert header is not None
        assert header.get("schema_name") == "IFC4X3_ADD2"
        assert header.get("description") == "ViewDefinition[DesignTransferView]"
        assert counter.total < MAX_HEADER_BYTES
        assert peak < MAX_HEADER_BYTES

    def test_ifczip_newline_free_entry_is_not_fully_decompressed(self, tmp_path: Path) -> None:
        path = tmp_path / "model.ifczip"
        _write_deflated_ifczip(path, "model.ifc", b"A" * BOMB_BYTES)
        with zipfile.ZipFile(path) as archive:
            info = archive.filelist[0]
            file_size = info.file_size
            compress_size = info.compress_size
        # The fixture is a real amplification: a few kilobytes expand to the bomb.
        assert file_size == BOMB_BYTES
        assert compress_size < 64 * 1024
        assert path.stat().st_size < 64 * 1024

        with _DecompressedByteCounter() as counter:
            peak = _peak_during(lambda: _preview(path))
        assert counter.total < MAX_HEADER_BYTES, (
            f"decompressed {counter.total} bytes from a {path.stat().st_size}-byte "
            f"zip whose first entry declares file_size {file_size}"
        )
        assert peak < MAX_HEADER_BYTES, f"preview allocated {peak} bytes"

    def test_uppercase_ifczip_newline_free_entry_is_not_fully_decompressed(self, tmp_path: Path) -> None:
        path = tmp_path / "model.IFCZIP"
        _write_deflated_ifczip(path, "model.ifc", b"A" * BOMB_BYTES)
        with _DecompressedByteCounter() as counter:
            peak = _peak_during(lambda: _preview(path))
        assert counter.total < MAX_HEADER_BYTES, f"decompressed {counter.total} bytes"
        assert peak < MAX_HEADER_BYTES, f"preview allocated {peak} bytes"

    def test_ifc_newline_free_line_is_not_fully_read(self, tmp_path: Path) -> None:
        path = tmp_path / "model.ifc"
        path.write_bytes(b"A" * BOMB_BYTES)
        peak = _peak_during(lambda: _preview(path))
        assert peak < MAX_HEADER_BYTES, f"preview allocated {peak} bytes from a newline-free .ifc line"

    def test_small_ifc_header_still_extracts(self, tmp_path: Path) -> None:
        path = tmp_path / "model.ifc"
        path.write_text(_NORMAL_HEADER, encoding="utf-8")
        header = subject.IfcHeaderExtractor(str(path)).extract()
        assert header.get("schema_name") == "IFC4X3_ADD2"
        assert header.get("name") == "file.ifc"
