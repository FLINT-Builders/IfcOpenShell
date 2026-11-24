# This file was generated with the assistance of an AI coding tool.
"""Failing spec for Bonsai .ifczip decompression limits.

Opening a project loads the archive through ``IfcStore.get_file`` →
``IfcStore.load_file``. While the vulnerability is present, ``load_file``
calls ``ZipFile.extractall`` on every member before it looks for an ``.ifc``.
These tests drive that function (and ``get_file``, which is what
``tool.Ifc.get`` / Open IFC Project call) with crafted archives.

An archive must be refused, with no member file created, when ``infolist()``
shows any of:

* more than ``MAX_ENTRIES`` members (512)
* sum of ``file_size`` greater than ``MAX_TOTAL_UNCOMPRESSED_BYTES`` (256 MiB)
* ``sum(file_size) / sum(compress_size)`` greater than ``MAX_COMPRESSION_RATIO``
  (100), for archives whose compressed size is non-zero

Refusal has to use the archive object that was checked. Opening the same path
again and extracting that later view is still a failure. A small legitimate
``.ifczip`` (the bundled ``basic.ifc`` plus a tiny sidecar) must still load.

The tests fail on purpose until the loader enforces those limits.
"""

from __future__ import annotations

import builtins
import importlib.util
import io
import os
import struct
import sys
import tempfile
import types
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
IFC_MODULE_PATH = REPO_ROOT / "src" / "bonsai" / "bonsai" / "bim" / "ifc.py"
BASIC_IFC = (REPO_ROOT / "src" / "bonsai" / "test" / "files" / "basic.ifc").read_bytes()

MAX_ENTRIES = 512
MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
# Above any legitimate fixture in this module, below every bomb payload.
REFUSAL_WRITE_CEILING = 256 * 1024
BOMB_UNCOMPRESSED = 4 * 1024 * 1024

_OPENED: list[tuple[str, bytes]] = []
_SENTINEL = object()


_CREATED_MODULES: list[str] = []
_ATTACHED_ATTRS: list[tuple[types.ModuleType, str]] = []


def _ensure_module(name: str) -> types.ModuleType:
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    module = types.ModuleType(name)
    module.__path__ = []
    module.__package__ = name
    sys.modules[name] = module
    _CREATED_MODULES.append(name)
    if "." in name:
        parent_name, child_name = name.rsplit(".", 1)
        parent = _ensure_module(parent_name)
        if not hasattr(parent, child_name):
            setattr(parent, child_name, module)
            _ATTACHED_ATTRS.append((parent, child_name))
    return module


def _release_import_stubs() -> None:
    """Drop stub modules so later imports in this process are unaffected."""
    created = set(_CREATED_MODULES)
    for parent, child_name in reversed(_ATTACHED_ATTRS):
        if parent.__name__ in created:
            continue
        if hasattr(parent, child_name):
            delattr(parent, child_name)
    for name in reversed(_CREATED_MODULES):
        sys.modules.pop(name, None)
    _CREATED_MODULES.clear()
    _ATTACHED_ATTRS.clear()


def _install_import_stubs() -> types.SimpleNamespace:
    """Satisfy bonsai.bim.ifc imports. None of these read the archive."""
    for name in (
        "bpy",
        "bpy.types",
        "ifcopenshell",
        "ifcopenshell.geom",
        "ifcopenshell.ifcopenshell_wrapper",
        "ifcopenshell.file",
        "bonsai",
        "bonsai.bim",
        "bonsai.bim.handler",
        "bonsai.tool",
        "bonsai.tool.brick",
    ):
        _ensure_module(name)

    props = types.SimpleNamespace(ifc_file="")
    bpy_module = sys.modules["bpy"]
    if "bpy.types" in _CREATED_MODULES:
        bpy_module.types = sys.modules["bpy.types"]
        sys.modules["bpy.types"].Material = type("Material", (), {})
        sys.modules["bpy.types"].Object = type("Object", (), {})

    class _UndoSystemError(Exception):
        pass

    sys.modules["ifcopenshell.file"].UndoSystemError = _UndoSystemError

    def _open_ifc(path, *args, **kwargs):
        data = Path(path).read_bytes()
        _OPENED.append((os.fspath(path), data))
        return _SENTINEL

    sys.modules["ifcopenshell"].open = _open_ifc

    class _BrickStore:
        pass

    sys.modules["bonsai.tool.brick"].BrickStore = _BrickStore

    class _Blender:
        @staticmethod
        def get_addon_preferences():
            return types.SimpleNamespace(should_stream=False)

        @staticmethod
        def get_bim_props():
            return props

    class _IfcTool:
        @staticmethod
        def after_file_loaded():
            return None

    sys.modules["bonsai.tool"].Blender = _Blender
    sys.modules["bonsai.tool"].Ifc = _IfcTool
    return props


def _load_ifc_module():
    props = _install_import_stubs()
    spec = importlib.util.spec_from_file_location("_ifczip_bomb_loader", IFC_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_ifczip_bomb_loader"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("_ifczip_bomb_loader", None)
        _release_import_stubs()
    module._test_props = props
    return module


IFC = _load_ifc_module()


class _WriteStats:
    def __init__(self) -> None:
        self.bytes_written = 0
        self.files_created: set[str] = set()
        self.temp_dirs: list[str] = []


class _RecordingTemporaryDirectory(tempfile.TemporaryDirectory):
    stats: _WriteStats

    def __enter__(self):
        path = super().__enter__()
        self.stats.temp_dirs.append(path)
        return path


def _under_temp(path: str, stats: _WriteStats) -> bool:
    absolute = os.path.abspath(path)
    return any(absolute.startswith(os.path.abspath(temp_dir) + os.sep) for temp_dir in stats.temp_dirs)


def _invoke(entry: str, archive: Path, *, zip_factory=None) -> _WriteStats:
    """Run the real loader and count member bytes it writes."""
    stats = _WriteStats()
    _OPENED.clear()
    IFC.IfcStore.file = None
    IFC.IfcStore.path = ""
    IFC._test_props.ifc_file = str(archive)

    real_open = builtins.open
    real_temp = IFC.tempfile.TemporaryDirectory
    real_zip = IFC.zipfile.ZipFile

    class _BoundTemp(_RecordingTemporaryDirectory):
        pass

    _BoundTemp.stats = stats

    def tracking_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        if not isinstance(file, (str, os.PathLike)):
            return handle
        if not any(flag in mode for flag in ("w", "a", "x", "+")):
            return handle
        if not _under_temp(os.fspath(file), stats):
            return handle
        stats.files_created.add(os.path.abspath(os.fspath(file)))
        real_write = handle.write

        def write(data, _real=real_write):
            stats.bytes_written += len(data)
            return _real(data)

        handle.write = write
        return handle

    IFC.tempfile.TemporaryDirectory = _BoundTemp
    builtins.open = tracking_open
    if zip_factory is not None:
        IFC.zipfile.ZipFile = zip_factory
    try:
        if entry == "get_file":
            IFC.IfcStore.get_file()
        elif entry == "load_file":
            IFC.IfcStore.load_file(str(archive))
        else:
            raise AssertionError(entry)
    finally:
        builtins.open = real_open
        IFC.tempfile.TemporaryDirectory = real_temp
        IFC.zipfile.ZipFile = real_zip
    return stats


def _assert_refused(entry: str, archive: Path) -> None:
    stats = _invoke(entry, archive)
    assert stats.bytes_written == 0
    assert stats.files_created == set()
    assert IFC.IfcStore.file is None
    assert _OPENED == []


def _write_zip(path: Path, members: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members:
            archive.writestr(name, payload)


def _legitimate_ifczip(path: Path) -> None:
    _write_zip(path, [("model.ifc", BASIC_IFC), ("note.txt", b"sidecar")])


def _non_ifc_bomb(path: Path) -> None:
    zeros = b"\0" * BOMB_UNCOMPRESSED
    _write_zip(
        path,
        [
            ("payload/zeros-a.bin", zeros),
            ("payload/zeros-b.bin", zeros),
            ("model.ifc", BASIC_IFC),
        ],
    )


def _ifc_member_bomb(path: Path) -> None:
    _write_zip(path, [("model.ifc", b"\0" * BOMB_UNCOMPRESSED)])


def _too_many_entries(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for index in range(MAX_ENTRIES + 1):
            archive.writestr(f"entries/{index}.dat", b"")
        archive.writestr("model.ifc", BASIC_IFC)


def _declare_uncompressed_size(source: Path, destination: Path, declared: int) -> None:
    """Rewrite the central-directory and local uncompressed sizes.

    Python's reader trusts ``ZipInfo.file_size`` from the central directory.
    The compressed payload stays the small legitimate member, so a loader that
    extracts before consulting ``file_size`` still produces a readable ``.ifc``.
    """
    raw = bytearray(source.read_bytes())
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.getinfo("model.ifc")
    struct.pack_into("<I", raw, info.header_offset + 22, declared)
    central = raw.find(b"PK\x01\x02")
    struct.pack_into("<I", raw, central + 24, declared)
    destination.write_bytes(raw)
    with zipfile.ZipFile(destination) as archive:
        assert archive.getinfo("model.ifc").file_size == declared


def _oversized_declaration(path: Path) -> None:
    legitimate = path.with_suffix(".legitimate.ifczip")
    _legitimate_ifczip(legitimate)
    _declare_uncompressed_size(legitimate, path, MAX_TOTAL_UNCOMPRESSED_BYTES + 1)
    legitimate.unlink()


@pytest.fixture(params=["get_file", "load_file"])
def entry(request) -> str:
    return request.param


def test_non_ifc_bomb_members_are_refused_before_any_write(entry: str, tmp_path: Path) -> None:
    archive = tmp_path / "project.ifczip"
    _non_ifc_bomb(archive)
    _assert_refused(entry, archive)


def test_uppercase_ifczip_bomb_is_refused_before_any_write(entry: str, tmp_path: Path) -> None:
    archive = tmp_path / "project.IFCZIP"
    _non_ifc_bomb(archive)
    _assert_refused(entry, archive)


def test_high_ratio_ifc_member_is_refused_before_any_write(entry: str, tmp_path: Path) -> None:
    archive = tmp_path / "project.ifczip"
    _ifc_member_bomb(archive)
    _assert_refused(entry, archive)


def test_too_many_entries_are_refused_before_any_file_is_created(entry: str, tmp_path: Path) -> None:
    archive = tmp_path / "project.ifczip"
    _too_many_entries(archive)
    _assert_refused(entry, archive)


def test_declared_uncompressed_size_over_limit_is_refused_before_any_write(entry: str, tmp_path: Path) -> None:
    archive = tmp_path / "project.ifczip"
    _oversized_declaration(archive)
    _assert_refused(entry, archive)


def test_second_zip_open_cannot_extract_a_different_archive(entry: str, tmp_path: Path) -> None:
    """A check against one open of the path must not extract a later open."""
    safe = tmp_path / "safe.ifczip"
    bomb = tmp_path / "bomb.ifczip"
    _legitimate_ifczip(safe)
    _non_ifc_bomb(bomb)
    calls = {"n": 0}

    class _SwitchingZipFile(zipfile.ZipFile):
        def __init__(self, file, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] > 1:
                file = str(bomb)
            super().__init__(file, *args, **kwargs)

    stats = _invoke(entry, safe, zip_factory=_SwitchingZipFile)
    assert stats.bytes_written < REFUSAL_WRITE_CEILING
    assert stats.bytes_written < BOMB_UNCOMPRESSED
    if _OPENED:
        assert _OPENED[0][1].startswith(b"ISO-10303-21;")


def test_legitimate_ifczip_still_loads(entry: str, tmp_path: Path) -> None:
    archive = tmp_path / "project.ifczip"
    _legitimate_ifczip(archive)
    stats = _invoke(entry, archive)
    assert IFC.IfcStore.file is _SENTINEL
    assert len(_OPENED) == 1
    assert _OPENED[0][1].startswith(b"ISO-10303-21;")
    assert stats.bytes_written < REFUSAL_WRITE_CEILING
    assert stats.bytes_written >= len(BASIC_IFC)
