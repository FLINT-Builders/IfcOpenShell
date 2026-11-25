# This file was generated with the assistance of an AI coding tool.
"""Downloads from a BCF API server must not write outside the client temp directory.

The server chooses project, topic, and document ids. ``get_snippet`` and
``get_document`` turn those ids into a local filename. A project id that is
absolute, or that begins with dot-dot segments, must not create, truncate,
replace, or delete a file outside ``BcfClient.filepath``. A write that is
undone before the call returns still fails these tests.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from bcf.v3.bcfapi import BcfClient, FoundationClient

SNIPPET_BODY = "snippet-body-from-server"
ORIGINAL_BYTES = b"original-file-contents"

# inotify event masks from the Linux ABI. The watch only observes the
# directory outside the temp dir; it is not part of the client.
_IN_NONBLOCK = 0x800
_IN_MODIFY = 0x00000002
_IN_ATTRIB = 0x00000004
_IN_CLOSE_WRITE = 0x00000008
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_IN_DELETE_SELF = 0x00000400
_IN_MOVE_SELF = 0x00000800
_IN_WATCH_MASK = (
    _IN_MODIFY
    | _IN_ATTRIB
    | _IN_CLOSE_WRITE
    | _IN_MOVED_FROM
    | _IN_MOVED_TO
    | _IN_CREATE
    | _IN_DELETE
    | _IN_DELETE_SELF
    | _IN_MOVE_SELF
)

_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
_libc.inotify_init1.argtypes = [ctypes.c_int]
_libc.inotify_init1.restype = ctypes.c_int
_libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
_libc.inotify_add_watch.restype = ctypes.c_int


class _ApiState:
    def __init__(self) -> None:
        self.projects: list[dict[str, str]] = []


class _DirectoryWatch:
    def __init__(self, directory: str) -> None:
        self._fd = _libc.inotify_init1(_IN_NONBLOCK)
        if self._fd < 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err), "inotify_init1")
        watch = _libc.inotify_add_watch(self._fd, os.fsencode(directory), _IN_WATCH_MASK)
        if watch < 0:
            err = ctypes.get_errno()
            os.close(self._fd)
            raise OSError(err, os.strerror(err), directory)

    def read(self) -> bytes:
        chunks: list[bytes] = []
        while True:
            try:
                chunk = os.read(self._fd, 4096)
            except BlockingIOError:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def close(self) -> None:
        os.close(self._fd)


def _snapshot(directory: str) -> dict[str, tuple[Any, ...]]:
    found: dict[str, tuple[Any, ...]] = {}
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        stat_result = os.lstat(path)
        if stat_result.st_mode & 0o170000 == 0o100000:
            with open(path, "rb") as handle:
                found[name] = (stat_result.st_ino, handle.read())
        else:
            found[name] = ("not-a-regular-file", stat_result.st_mode, stat_result.st_ino)
    return found


def _start_server(state: _ApiState) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/projects":
                payload = json.dumps(state.projects).encode("utf-8")
                content_type = "application/json"
            else:
                # Snippet and document bodies are whatever the server sends.
                # urllib3 removes dot segments from the request path first, so
                # this handler answers the normalized path with the same body.
                payload = SNIPPET_BODY.encode("utf-8")
                content_type = "text/plain"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _make_client(baseurl: str) -> BcfClient:
    foundation = FoundationClient("", "")
    foundation.access_token = "placeholder-token"
    foundation.access_token_expires_on = time.time() + 3600
    client = BcfClient(foundation)
    client.baseurl = baseurl
    return client


@pytest.fixture()
def api_client():
    state = _ApiState()
    server = _start_server(state)
    port = server.server_address[1]
    client = _make_client(f"http://127.0.0.1:{port}")
    cleanup: list[str] = []
    try:
        yield client, state, cleanup
    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(client.filepath, ignore_errors=True)
        for path in cleanup:
            shutil.rmtree(path, ignore_errors=True)


def _outside_directory(client: BcfClient, cleanup: list[str]) -> str:
    parent = os.path.dirname(client.filepath)
    directory = os.path.join(parent, "bcf-escape-" + uuid.uuid4().hex)
    os.mkdir(directory)
    cleanup.append(directory)
    # The product temp dir from mkdtemp() must not already contain this directory.
    assert os.path.commonpath([os.path.realpath(client.filepath), os.path.realpath(directory)]) != os.path.realpath(
        client.filepath
    )
    return directory


def _publish(state: _ApiState, project_id: str, topic_id: str = "topic", document_id: str = "document") -> None:
    state.projects = [{"project_id": project_id, "topic_id": topic_id, "document_id": document_id}]


def _ids_from_server(client: BcfClient) -> tuple[str, str, str]:
    projects = client.get_projects()
    project = projects[0]
    return project["project_id"], project["topic_id"], project["document_id"]


def _assert_directory_unchanged(directory: str, before: dict[str, tuple[Any, ...]], events: bytes) -> None:
    assert events == b"", "a file outside the temp directory was created, modified, or removed during the download"
    assert _snapshot(directory) == before


def _run_download(download: Callable[[str, str, str], object], client: BcfClient) -> None:
    project_id, topic_id, document_id = _ids_from_server(client)
    try:
        download(project_id, topic_id, document_id)
    except Exception:
        # A fixed client may reject the ids. Rejection is only acceptable
        # when the outside directory was not touched first.
        return


def test_snippet_absolute_project_id_does_not_replace_outside_file(api_client) -> None:
    client, state, cleanup = api_client
    outside = _outside_directory(client, cleanup)
    project_id = os.path.join(outside, "abs")
    topic_id = "topic"
    target = os.path.join(outside, f"abs_{topic_id}_snippet.txt")
    with open(target, "wb") as handle:
        handle.write(ORIGINAL_BYTES)
    before = _snapshot(outside)
    watch = _DirectoryWatch(outside)
    try:
        _publish(state, project_id, topic_id)
        _run_download(lambda project, topic, _document: client.get_snippet(project, topic), client)
        _assert_directory_unchanged(outside, before, watch.read())
    finally:
        watch.close()


def test_snippet_dotdot_project_id_does_not_create_outside_file(api_client) -> None:
    client, state, cleanup = api_client
    outside = _outside_directory(client, cleanup)
    project_id = f"../{os.path.basename(outside)}/marker"
    before = _snapshot(outside)
    watch = _DirectoryWatch(outside)
    try:
        _publish(state, project_id, "topic")
        _run_download(lambda project, topic, _document: client.get_snippet(project, topic), client)
        _assert_directory_unchanged(outside, before, watch.read())
    finally:
        watch.close()


def test_document_absolute_project_id_does_not_replace_outside_file(api_client) -> None:
    client, state, cleanup = api_client
    outside = _outside_directory(client, cleanup)
    project_id = os.path.join(outside, "abs")
    topic_id = "topic"
    document_id = "document"
    target = os.path.join(outside, f"abs_{topic_id}_{document_id}_document.txt")
    with open(target, "wb") as handle:
        handle.write(ORIGINAL_BYTES)
    before = _snapshot(outside)
    watch = _DirectoryWatch(outside)
    try:
        _publish(state, project_id, topic_id, document_id)
        _run_download(lambda project, topic, document: client.get_document(project, topic, document), client)
        _assert_directory_unchanged(outside, before, watch.read())
    finally:
        watch.close()


def test_document_dotdot_project_id_does_not_create_outside_file(api_client) -> None:
    client, state, cleanup = api_client
    outside = _outside_directory(client, cleanup)
    project_id = f"../{os.path.basename(outside)}/marker"
    before = _snapshot(outside)
    watch = _DirectoryWatch(outside)
    try:
        _publish(state, project_id, "topic", "document")
        _run_download(lambda project, topic, document: client.get_document(project, topic, document), client)
        _assert_directory_unchanged(outside, before, watch.read())
    finally:
        watch.close()


def test_snippet_safe_ids_write_only_inside_temp_dir(api_client) -> None:
    client, state, _cleanup = api_client
    _publish(state, "project-1", "topic-1")
    project_id, topic_id, _document_id = _ids_from_server(client)
    status, content = client.get_snippet(project_id, topic_id)
    written = os.path.join(client.filepath, f"{project_id}_{topic_id}_snippet.txt")
    assert status == 200
    assert content == SNIPPET_BODY
    assert os.path.isfile(written)
    with open(written, encoding="utf-8") as handle:
        assert handle.read() == SNIPPET_BODY
    assert os.path.realpath(written).startswith(os.path.realpath(client.filepath) + os.sep)


def test_document_safe_ids_write_only_inside_temp_dir(api_client) -> None:
    client, state, _cleanup = api_client
    _publish(state, "project-1", "topic-1", "document-1")
    project_id, topic_id, document_id = _ids_from_server(client)
    status, content = client.get_document(project_id, topic_id, document_id)
    written = os.path.join(client.filepath, f"{project_id}_{topic_id}_{document_id}_document.txt")
    assert status == 200
    assert content == SNIPPET_BODY
    assert os.path.isfile(written)
    with open(written, encoding="utf-8") as handle:
        assert handle.read() == SNIPPET_BODY
    assert os.path.realpath(written).startswith(os.path.realpath(client.filepath) + os.sep)
