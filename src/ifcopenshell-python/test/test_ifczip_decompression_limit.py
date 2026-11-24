# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Spec for decompression limits on zipped IFC input.

``ifcopenshell.open`` and ``IfcHeaderExtractor`` must enforce both limits
below before they read or write an archive member. These tests fail while a
zip entry can still be inflated with no cap.

Defaults (used when the caller does not pass them):

- ``max_uncompressed_bytes`` = 1 GiB. ``ZipInfo.file_size`` above this is refused.
- ``max_compression_ratio`` = 100. ``file_size / compress_size`` above this is
  refused. A ``compress_size`` of 0 is over the limit.

``ifcopenshell.open(path, format=None, ..., max_uncompressed_bytes=...,
max_compression_ratio=...)`` and
``IfcHeaderExtractor(path, max_uncompressed_bytes=..., max_compression_ratio=...)``
accept the limits as keyword arguments. On refusal they raise
``ifcopenshell.DecompressionLimitError``, a subclass of ``ifcopenshell.Error``.

Refusal is about the member that will be extracted or read, not a different
member of the same archive. No byte of that member may be written to disk, and
no byte of that member may be read from the archive, before the exception.
Creating the destination file counts as a write. A later deletion does not
undo it.
"""

from __future__ import annotations

import builtins
import inspect
import os
import tempfile
import zipfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest

import ifcopenshell
from ifcopenshell.util.file import IfcHeaderExtractor

DEFAULT_MAX_UNCOMPRESSED_BYTES = 1024**3
DEFAULT_MAX_COMPRESSION_RATIO = 100

_HEADER = (
    "ISO-10303-21;\n"
    "HEADER;\n"
    "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
    "FILE_NAME('model.ifc','2020-01-01T00:00:00',(''),(''),'','','');\n"
    "FILE_SCHEMA(('IFC4'));\n"
    "ENDSEC;\n"
    "DATA;\n"
)
_FOOTER = "ENDSEC;\nEND-ISO-10303-21;\n"


def assert_limit_defaults(callable_obj: object, what: str) -> None:
    params = inspect.signature(callable_obj).parameters
    expected = {
        "max_uncompressed_bytes": DEFAULT_MAX_UNCOMPRESSED_BYTES,
        "max_compression_ratio": DEFAULT_MAX_COMPRESSION_RATIO,
    }
    for name, value in expected.items():
        if name not in params:
            pytest.fail(f"{what} must accept {name}")
        default = params[name].default
        if default is inspect.Parameter.empty or default != value:
            pytest.fail(f"{what} {name} default is {default!r}, expected {value!r}")


def valid_ifc(min_size: int = 0) -> bytes:
    """IFC SPF text the native parser accepts. ``min_size`` is a minimum length."""
    body = (_HEADER + _FOOTER).encode()
    if len(body) >= min_size:
        return body
    fill = min_size - len(body)
    # Keep the extra bytes inside one comment so the header stays parseable.
    padded = (_HEADER + "/*" + ("A" * fill) + "*/\n" + _FOOTER).encode()
    assert len(padded) >= min_size
    return padded


def write_zip(path: Path, members: list[tuple[str, bytes, int]]) -> list[zipfile.ZipInfo]:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload, compression in members:
            archive.writestr(name, payload, compress_type=compression)
    with zipfile.ZipFile(path) as archive:
        return [archive.getinfo(name) for name, _, _ in members]


def forge_uncompressed_size(path: Path, member: str, declared_size: int) -> zipfile.ZipInfo:
    """Rewrite only the uncompressed-size fields, leaving the deflate stream intact.

    CPython's reader stops inflating at the declared size, but it still reports
    ``ZipInfo.file_size`` from these fields. Patching them is how a header can
    claim a member larger than the bytes the test is willing to materialize.
    """
    data = bytearray(path.read_bytes())
    local = data.find(b"PK\x03\x04")
    central = data.find(b"PK\x01\x02")
    if local < 0 or central < 0:
        raise AssertionError("zip headers not found")
    encoded = declared_size.to_bytes(4, "little")
    data[local + 22 : local + 26] = encoded
    data[central + 24 : central + 28] = encoded
    path.write_bytes(data)
    with zipfile.ZipFile(path) as archive:
        return archive.getinfo(member)


@contextmanager
def track_extracted_writes() -> Generator[dict[str, object], None, None]:
    """Count bytes written under temp dirs created while the context is active.

    ``zipfile.ZipFile.extract`` writes the member through the builtin ``open``
    the stdlib looks up at call time. Wrapping that records the real write.
    """
    state: dict[str, object] = {"bytes": 0, "paths": []}
    roots: list[str] = []
    real_mkdtemp = tempfile.mkdtemp
    real_open = builtins.open

    def wrapped_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        roots.append(path)
        return path

    def wrapped_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        try:
            path = os.fspath(file)
        except TypeError:
            return handle
        under_root = any(path == root or path.startswith(root + os.sep) for root in roots)
        writing = any(flag in str(mode) for flag in ("w", "a", "x", "+"))
        if not under_root or not writing:
            return handle
        state["paths"].append(path)
        real_write = handle.write

        def write(data, /):
            written = real_write(data)
            state["bytes"] += written if isinstance(written, int) else len(data)
            return written

        handle.write = write
        return handle

    tempfile.mkdtemp = wrapped_mkdtemp
    builtins.open = wrapped_open
    try:
        yield state
    finally:
        tempfile.mkdtemp = real_mkdtemp
        builtins.open = real_open


@contextmanager
def track_member_reads() -> Generator[dict[str, int], None, None]:
    """Count decompressed bytes ``ZipFile.open`` yields for a member."""
    state = {"bytes": 0, "opened": 0}
    real_open = zipfile.ZipFile.open

    def wrapped_open(self, name, mode="r", pwd=None, *, force_zip64=False):
        handle = real_open(self, name, mode=mode, pwd=pwd, force_zip64=force_zip64)
        if mode != "r":
            return handle
        state["opened"] += 1
        real_read = handle.read

        def read(n=-1):
            data = real_read(n)
            state["bytes"] += len(data)
            return data

        handle.read = read
        return handle

    zipfile.ZipFile.open = wrapped_open
    try:
        yield state
    finally:
        zipfile.ZipFile.open = real_open


def _missing_limit_error(detail: str) -> type[BaseException]:
    error = getattr(ifcopenshell, "DecompressionLimitError", None)
    if not isinstance(error, type) or not issubclass(error, ifcopenshell.Error):
        pytest.fail(f"ifcopenshell.DecompressionLimitError is missing; {detail}")
    return error


def assert_open_refuses(path: Path, **kwargs) -> None:
    with track_extracted_writes() as writes:
        try:
            ifcopenshell.open(path, **kwargs)
        except Exception as exc:
            outcome = f"raised {type(exc).__name__}: {exc}"
            caught: BaseException | None = exc
        else:
            outcome = "returned a model"
            caught = None
    detail = f"open() {outcome}; wrote {writes['bytes']} bytes to {writes['paths']}"
    error = _missing_limit_error(detail)
    if not isinstance(caught, error):
        pytest.fail(detail)
    assert writes["paths"] == []
    assert writes["bytes"] == 0


def assert_header_refuses(path: Path, **kwargs) -> None:
    with track_member_reads() as reads:
        try:
            IfcHeaderExtractor(str(path), **kwargs).extract()
        except Exception as exc:
            outcome = f"raised {type(exc).__name__}: {exc}"
            caught: BaseException | None = exc
        else:
            outcome = "returned a header"
            caught = None
    detail = f"IfcHeaderExtractor {outcome}; read {reads['bytes']} member bytes in {reads['opened']} opens"
    error = _missing_limit_error(detail)
    if not isinstance(caught, error):
        pytest.fail(detail)
    assert reads["opened"] == 0
    assert reads["bytes"] == 0


def test_open_declares_decompression_limits():
    assert_limit_defaults(ifcopenshell.open, "ifcopenshell.open()")


def test_header_extractor_declares_decompression_limits():
    assert_limit_defaults(IfcHeaderExtractor, "IfcHeaderExtractor()")


def test_guess_format_maps_zip_suffixes():
    assert ifcopenshell.guess_format(Path("model.ifczip")) == ".ifcZIP"
    assert ifcopenshell.guess_format(Path("model.zip")) == ".ifcZIP"
    assert ifcopenshell.guess_format(Path("model.ZIP")) == ".ifcZIP"


@pytest.mark.parametrize(
    ("suffix", "format_arg", "arcname"),
    [
        (".ifczip", None, "model.ifc"),
        (".zip", None, "model.ifc"),
        (".bin", ".ifcZIP", "model.ifc"),
        (".ifczip", None, "Model.IFC"),
        (".ifczip", None, "nested/model.ifc"),
        (".ifczip", None, "model.ifcxml"),
    ],
)
def test_open_refuses_high_ratio_member_before_extract(tmp_path: Path, suffix: str, format_arg, arcname: str):
    payload = valid_ifc(min_size=512 * 1024)
    archive_path = tmp_path / f"bomb{suffix}"
    info = write_zip(archive_path, [(arcname, payload, zipfile.ZIP_DEFLATED)])[0]
    ratio = info.file_size / info.compress_size
    assert info.file_size < DEFAULT_MAX_UNCOMPRESSED_BYTES
    assert ratio > DEFAULT_MAX_COMPRESSION_RATIO
    assert archive_path.stat().st_size < info.file_size / DEFAULT_MAX_COMPRESSION_RATIO
    kwargs = {} if format_arg is None else {"format": format_arg}
    assert_open_refuses(archive_path, **kwargs)


def test_open_limits_the_ifc_member_not_an_earlier_small_file(tmp_path: Path):
    payload = valid_ifc(min_size=512 * 1024)
    archive_path = tmp_path / "decoy.ifczip"
    infos = write_zip(
        archive_path,
        [
            ("readme.txt", b"small", zipfile.ZIP_STORED),
            ("model.ifc", payload, zipfile.ZIP_DEFLATED),
        ],
    )
    ifc_info = infos[1]
    assert ifc_info.file_size / ifc_info.compress_size > DEFAULT_MAX_COMPRESSION_RATIO
    assert_open_refuses(archive_path)


def test_open_refuses_declared_size_over_the_default_before_extract(tmp_path: Path):
    archive_path = tmp_path / "declared.ifczip"
    write_zip(archive_path, [("model.ifc", valid_ifc(), zipfile.ZIP_DEFLATED)])
    info = forge_uncompressed_size(archive_path, "model.ifc", DEFAULT_MAX_UNCOMPRESSED_BYTES + 1)
    assert info.file_size > DEFAULT_MAX_UNCOMPRESSED_BYTES
    assert info.file_size / info.compress_size > DEFAULT_MAX_COMPRESSION_RATIO
    assert_open_refuses(archive_path)


def test_open_honors_a_lower_uncompressed_limit(tmp_path: Path):
    payload = valid_ifc(min_size=2 * 1024 * 1024)
    archive_path = tmp_path / "stored.ifczip"
    info = write_zip(archive_path, [("model.ifc", payload, zipfile.ZIP_STORED)])[0]
    assert info.file_size > 1024 * 1024
    assert info.file_size / info.compress_size <= DEFAULT_MAX_COMPRESSION_RATIO
    assert_open_refuses(archive_path, max_uncompressed_bytes=1024 * 1024)


def test_open_accepts_a_stored_model_under_the_default_limit(tmp_path: Path):
    payload = valid_ifc(min_size=2 * 1024 * 1024)
    archive_path = tmp_path / "ok.ifczip"
    info = write_zip(archive_path, [("model.ifc", payload, zipfile.ZIP_STORED)])[0]
    assert info.file_size <= DEFAULT_MAX_UNCOMPRESSED_BYTES
    assert info.file_size / info.compress_size <= DEFAULT_MAX_COMPRESSION_RATIO
    with track_extracted_writes() as writes:
        model = ifcopenshell.open(archive_path)
    assert model.schema == "IFC4"
    assert writes["bytes"] == info.file_size


def test_open_honors_a_raised_compression_ratio(tmp_path: Path):
    payload = valid_ifc(min_size=512 * 1024)
    archive_path = tmp_path / "raised.ifczip"
    info = write_zip(archive_path, [("model.ifc", payload, zipfile.ZIP_DEFLATED)])[0]
    assert info.file_size / info.compress_size > DEFAULT_MAX_COMPRESSION_RATIO
    with track_extracted_writes() as writes:
        model = ifcopenshell.open(archive_path, max_compression_ratio=10**7)
    assert model.schema == "IFC4"
    assert writes["bytes"] == info.file_size


def test_header_extractor_refuses_high_ratio_member_before_read(tmp_path: Path):
    # One line and no FILE_SCHEMA: the extractor otherwise reads the member to EOF.
    payload = b"A" * (2 * 1024 * 1024)
    archive_path = tmp_path / "line.ifczip"
    info = write_zip(archive_path, [("model.ifc", payload, zipfile.ZIP_DEFLATED)])[0]
    assert info.file_size < DEFAULT_MAX_UNCOMPRESSED_BYTES
    assert info.file_size / info.compress_size > DEFAULT_MAX_COMPRESSION_RATIO
    assert_header_refuses(archive_path)


def test_header_extractor_honors_a_lower_uncompressed_limit(tmp_path: Path):
    payload = b"B" * (2 * 1024 * 1024)
    archive_path = tmp_path / "stored-line.ifczip"
    info = write_zip(archive_path, [("model.ifc", payload, zipfile.ZIP_STORED)])[0]
    assert info.file_size > 1024 * 1024
    assert info.file_size / info.compress_size <= DEFAULT_MAX_COMPRESSION_RATIO
    assert_header_refuses(archive_path, max_uncompressed_bytes=1024 * 1024, max_compression_ratio=100)


def test_header_extractor_reads_a_normal_ifczip(tmp_path: Path):
    archive_path = tmp_path / "ok.ifczip"
    info = write_zip(archive_path, [("model.ifc", valid_ifc(), zipfile.ZIP_DEFLATED)])[0]
    assert info.file_size / max(info.compress_size, 1) <= DEFAULT_MAX_COMPRESSION_RATIO
    with track_member_reads() as reads:
        header = IfcHeaderExtractor(str(archive_path)).extract()
    assert header.get("schema_name") == "IFC4"
    assert reads["bytes"] < 4096


def test_header_extractor_honors_a_raised_compression_ratio(tmp_path: Path):
    payload = valid_ifc(min_size=512 * 1024)
    archive_path = tmp_path / "raised.ifczip"
    info = write_zip(archive_path, [("model.ifc", payload, zipfile.ZIP_DEFLATED)])[0]
    assert info.file_size / info.compress_size > DEFAULT_MAX_COMPRESSION_RATIO
    header = IfcHeaderExtractor(str(archive_path), max_compression_ratio=10**7).extract()
    assert header.get("schema_name") == "IFC4"
