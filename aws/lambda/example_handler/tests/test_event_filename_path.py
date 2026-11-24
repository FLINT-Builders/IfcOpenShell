# This file was generated with the assistance of an AI coding tool.
"""Security spec for the sample Lambda handler's event filename.

``extract_wall_psets_handler`` must not create, truncate, or replace a file
outside ``/tmp`` when ``event["body"]["filename"]`` contains parent-directory
segments or names a directory symlink. A refusal that still writes, including
a write through a path that was only checked lexically, does not pass.

These tests fail while that handler uses the filename as the download path.
Run them with::

    python3 -m pip install pytest boto3 awslambdaric
    PYTHONPATH=aws/lambda python3 -m pytest aws/lambda/example_handler/tests/test_event_filename_path.py -q
"""

from __future__ import annotations

import ctypes
import ctypes.util
import io
import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

LAMBDA_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(LAMBDA_ROOT))

# The image installs IfcOpenShell. This checkout has no compiled wrapper, so
# the tests supply the Python prefix of ifcopenshell.open (exists-check, then
# hand the absolute path to the native parser) and stop before that parser.
OPENED: list[str] = []


def _outside_tmp(path: str) -> bool:
    real = os.path.realpath(path)
    root = os.path.realpath("/tmp")
    try:
        return os.path.commonpath([real, root]) != root
    except ValueError:
        return True


def _install_ifcopenshell_prefix() -> None:
    try:
        import ifcopenshell
    except ImportError:
        ifcopenshell = types.ModuleType("ifcopenshell")
        util = types.ModuleType("ifcopenshell.util")
        element = types.ModuleType("ifcopenshell.util.element")
        element.get_psets = lambda wall: {}
        util.element = element
        ifcopenshell.util = util

        def _native_open_unavailable(path, *_args, **_kwargs):
            checked = Path(path)
            if not checked.exists():
                raise FileNotFoundError(f"Path does not exist: '{checked}'.")
            # ifcopenshell.open continues into ifcopenshell_wrapper.open on the
            # absolute path. No wrapper is built here; the bytes are already on disk.
            raise OSError(f"native IFC parser is not built for {checked.absolute()}")

        ifcopenshell.open = _native_open_unavailable
        sys.modules["ifcopenshell"] = ifcopenshell
        sys.modules["ifcopenshell.util"] = util
        sys.modules["ifcopenshell.util.element"] = element

    original_open = ifcopenshell.open

    def _open_spy(path, *args, **kwargs):
        OPENED.append(os.fspath(path))
        return original_open(path, *args, **kwargs)

    ifcopenshell.open = _open_spy


_install_ifcopenshell_prefix()

import example_handler
from awslambdaric.lambda_runtime_marshaller import LambdaMarshaller
from botocore.awsrequest import AWSResponse
from botocore.response import StreamingBody

PAYLOAD = b"ifc-lambda-download-bytes"
_IN_NONBLOCK = 0x00000800
_IN_MODIFY = 0x00000002
_IN_ATTRIB = 0x00000004
_IN_CLOSE_WRITE = 0x00000008
_IN_OPEN = 0x00000020
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_WATCH_MASK = (
    _IN_MODIFY | _IN_ATTRIB | _IN_CLOSE_WRITE | _IN_OPEN | _IN_MOVED_FROM | _IN_MOVED_TO | _IN_CREATE | _IN_DELETE
)


class _DirectoryWatch:
    """Records inotify events for a directory. The kernel queues them until read."""

    def __init__(self, directory: Path):
        libc_name = ctypes.util.find_library("c")
        if not libc_name:
            raise OSError("libc was not found; cannot watch the download directory")
        self._libc = ctypes.CDLL(libc_name, use_errno=True)
        self._libc.inotify_init1.argtypes = [ctypes.c_int]
        self._libc.inotify_init1.restype = ctypes.c_int
        self._libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self._libc.inotify_add_watch.restype = ctypes.c_int
        self._fd = self._libc.inotify_init1(_IN_NONBLOCK)
        if self._fd < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        watch = self._libc.inotify_add_watch(self._fd, os.fsencode(directory), _WATCH_MASK)
        if watch < 0:
            error = ctypes.get_errno()
            os.close(self._fd)
            raise OSError(error, os.strerror(error))

    def drain(self) -> bytes:
        chunks: list[bytes] = []
        while True:
            try:
                chunk = os.read(self._fd, 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def close(self) -> None:
        os.close(self._fd)


class _ObjectDownload:
    """Feed HeadObject and GetObject through the client the handler already holds.

    The response shape matches botocore's stubber: a parsed service response
    whose Body is a StreamingBody over the object bytes. s3transfer then writes
    those bytes with its normal temp-file and rename path.
    """

    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []
        self._client = example_handler.s3

    def _respond(self, model, params, **_kwargs):
        self.calls.append((model.name, dict(params)))
        http_response = AWSResponse(None, 200, {}, None)
        if model.name == "HeadObject":
            parsed = {
                "ContentLength": len(self.payload),
                "ETag": '"fixture"',
                "ResponseMetadata": {"HTTPStatusCode": 200},
            }
            return http_response, parsed
        if model.name == "GetObject":
            parsed = {
                "Body": StreamingBody(io.BytesIO(self.payload), len(self.payload)),
                "ContentLength": len(self.payload),
                "ETag": '"fixture"',
                "ResponseMetadata": {"HTTPStatusCode": 200},
            }
            return http_response, parsed
        return None

    def __enter__(self):
        self._client.meta.events.register("before-call.s3.*", self._respond, unique_id="filename-path-test")
        return self

    def __exit__(self, *_args):
        self._client.meta.events.unregister("before-call.s3.*", self._respond, unique_id="filename-path-test")


def _snapshot(directory: Path) -> dict[str, object]:
    snapshot: dict[str, object] = {}
    for entry in directory.iterdir():
        if entry.is_symlink():
            snapshot[entry.name] = ("symlink", os.readlink(entry))
        elif entry.is_file():
            snapshot[entry.name] = entry.read_bytes()
        elif entry.is_dir():
            snapshot[entry.name] = "directory"
        else:
            snapshot[entry.name] = "other"
    return snapshot


def _invoke(filename: str, payload: bytes = PAYLOAD):
    raw = json.dumps({"body": {"filename": filename}})
    event = LambdaMarshaller().unmarshal_request(raw, "application/json")
    assert event["body"]["filename"] == filename
    with _ObjectDownload(payload):
        try:
            return example_handler.extract_wall_psets_handler(event, None)
        except Exception as exc:
            return exc


def _succeeded(result: object) -> bool:
    return isinstance(result, dict) and result.get("statusCode") == 200


def _traversal_name(target: Path, extra_parents: int) -> str:
    filename = ("../" * extra_parents) + os.path.relpath(target, "/tmp")
    joined = f"/tmp/{filename}"
    assert os.path.normpath(joined) == str(target)
    assert _outside_tmp(joined)
    return filename


@pytest.fixture
def outside_directory():
    directory = Path(tempfile.mkdtemp(prefix="ifc-lambda-outside-", dir=str(Path.home())))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _assert_outside_untouched(directory: Path, before: dict[str, object], events: bytes, result: object) -> None:
    after = _snapshot(directory)
    assert after == before, f"download wrote outside /tmp: before={before!r} after={after!r} result={result!r}"
    assert events == b"", f"download touched a path outside /tmp before returning: {events!r} result={result!r}"
    assert not _succeeded(result)


def test_dotdot_filename_does_not_replace_file_outside_tmp(outside_directory: Path):
    target = outside_directory / "victim.ifc"
    original = b"ORIGINAL-CONTENTS"
    target.write_bytes(original)
    filename = _traversal_name(target, extra_parents=0)
    before = _snapshot(outside_directory)
    watch = _DirectoryWatch(outside_directory)
    try:
        result = _invoke(filename)
    finally:
        events = watch.drain()
        watch.close()
    _assert_outside_untouched(outside_directory, before, events, result)
    assert target.read_bytes() == original


def test_several_dotdot_segments_do_not_create_file_outside_tmp(outside_directory: Path):
    target = outside_directory / "created.ifc"
    filename = _traversal_name(target, extra_parents=5)
    assert filename.count("..") >= 6
    before = _snapshot(outside_directory)
    watch = _DirectoryWatch(outside_directory)
    try:
        result = _invoke(filename)
    finally:
        events = watch.drain()
        watch.close()
    _assert_outside_untouched(outside_directory, before, events, result)
    assert not target.exists()


def test_directory_symlink_under_tmp_is_not_followed(outside_directory: Path):
    """A lexical '/tmp/...' check still follows a directory symlink on open."""
    link = Path("/tmp") / f"ifc-lambda-link-{outside_directory.name}"
    target = outside_directory / "via-symlink.ifc"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(outside_directory, target_is_directory=True)
    filename = f"{link.name}/via-symlink.ifc"
    lexical = os.path.normpath(f"/tmp/{filename}")
    assert os.path.commonpath([lexical, os.path.realpath("/tmp")]) == os.path.realpath("/tmp")
    assert _outside_tmp(f"/tmp/{filename}")
    before = _snapshot(outside_directory)
    watch = _DirectoryWatch(outside_directory)
    try:
        result = _invoke(filename)
    finally:
        events = watch.drain()
        watch.close()
        link.unlink(missing_ok=True)
    _assert_outside_untouched(outside_directory, before, events, result)
    assert not target.exists()


def test_single_segment_filename_stays_inside_tmp():
    filename = "wall.ifc"
    destination = Path("/tmp") / filename
    leftovers = list(Path("/tmp").glob(filename + "*"))
    for leftover in leftovers:
        if leftover.is_file() or leftover.is_symlink():
            leftover.unlink()
    OPENED.clear()
    try:
        _invoke(filename)
        assert OPENED, "a single path segment must still be opened inside /tmp"
        for opened in OPENED:
            assert not _outside_tmp(opened), opened
            written = Path(os.path.realpath(opened))
            assert written.is_file()
            assert written.read_bytes() == PAYLOAD
    finally:
        for leftover in Path("/tmp").glob(filename + "*"):
            if leftover.is_file() or leftover.is_symlink():
                leftover.unlink()
        destination.unlink(missing_ok=True)
