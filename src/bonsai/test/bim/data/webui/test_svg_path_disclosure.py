# This file was generated with the assistance of an AI coding tool.
"""Spec for the Bonsai web UI SVG loader file disclosure.

An unauthenticated Socket.IO client on ``/web`` must not be able to read a
local file by passing its path to ``get_svg``, and ``process_svg`` must not
inline image bytes that resolve outside the drawing file's own directory.

These tests fail while that disclosure is present. They pass once a client
can no longer obtain those bytes. Run:

    python3 -m pytest --noconftest --override-ini='addopts=' \\
        src/bonsai/test/bim/data/webui/test_svg_path_disclosure.py -q
"""

from __future__ import annotations

import asyncio
import base64
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import aiohttp
import pytest
import socketio

BONSAI_ROOT = Path(__file__).resolve().parents[4]
SIOSERVER = BONSAI_ROOT / "bonsai" / "bim" / "data" / "webui" / "sioserver.py"

# Distinctive placeholders. These are not credentials.
XML_MARKER = "MARKER_XML_BODY_7f3a"
SIBLING_SVG_MARKER = "MARKER_SIBLING_SVG_2b91"
TRAVERSAL_MARKER = "MARKER_TRAVERSAL_XML_44de"
PNG_MARKER = b"MARKER_PNG_OUTSIDE_91c2"
ABS_PNG_MARKER = b"MARKER_PNG_ABSOLUTE_c31e"
JPEG_MARKER = b"MARKER_JPEG_OUTSIDE_bb02"
LINKED_SVG_MARKER = "MARKER_LINKED_SVG_aa01"
DIRLINK_MARKER = b"MARKER_DIRLINK_PNG_e77d"
SYMLINK_PNG_MARKER = b"MARKER_SYMLINK_PNG_55f0"
RACE_SECRET_MARKER = b"MARKER_RACE_SECRET_19ab"
RACE_SAFE_MARKER = b"MARKER_RACE_SAFE_FILE_6d0e"
EVIL_ORIGIN = "https://evil.example"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _svg(body: str) -> str:
    return (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">\n'
        f"{body}\n"
        "</svg>\n"
    )


def _build_tree(root: Path) -> dict[str, Path]:
    drawing_dir = root / "project" / "drawings"
    outside = root / "outside"
    drawing_dir.mkdir(parents=True)
    outside.mkdir()

    secret_xml = root / "secret.xml"
    secret_xml.write_text(f"<settings><token>{XML_MARKER}</token></settings>\n", encoding="utf-8")

    traversal_xml = root / "project" / "traversal.xml"
    traversal_xml.write_text(f"<settings><token>{TRAVERSAL_MARKER}</token></settings>\n", encoding="utf-8")

    sibling_svg = drawing_dir / "extra.svg"
    sibling_svg.write_text(_svg(f"<text>{SIBLING_SVG_MARKER}</text>"), encoding="utf-8")

    outside_png = outside / "outside.png"
    outside_png.write_bytes(PNG_MARKER)
    absolute_png = outside / "absolute.png"
    absolute_png.write_bytes(ABS_PNG_MARKER)
    outside_jpeg = outside / "outside.jpeg"
    outside_jpeg.write_bytes(JPEG_MARKER)
    linked_svg = outside / "linked.svg"
    # Not parsed, only read and base64-encoded, so the body can be the marker itself.
    linked_svg.write_bytes(LINKED_SVG_MARKER.encode("utf-8"))
    dir_target = outside / "nested.png"
    dir_target.write_bytes(DIRLINK_MARKER)
    (drawing_dir / "linked_dir").symlink_to(outside, target_is_directory=True)
    (drawing_dir / "alias.png").symlink_to(outside / "alias-target.png")
    (outside / "alias-target.png").write_bytes(SYMLINK_PNG_MARKER)

    symlink_svg = drawing_dir / "alias.svg"
    symlink_svg.symlink_to(secret_xml)

    plan = drawing_dir / "plan.svg"
    # Relative href is resolved from the drawing directory: project/drawings -> outside/.
    plan.write_text(
        _svg(
            "\n".join(
                [
                    "<text>published-drawing</text>",
                    '<image xlink:href="../../outside/outside.png"/>',
                    f'<image xlink:href="{absolute_png}"/>',
                    '<image xlink:href="alias.png"/>',
                    '<image xlink:href="linked_dir/nested.png"/>',
                    f'<image xlink:href="{outside_jpeg}"/>',
                    f'<image xlink:href="{linked_svg}"/>',
                ]
            )
        ),
        encoding="utf-8",
    )

    sheet = drawing_dir / "sheet.svg"
    sheet.write_text(_svg("<text>published-sheet</text>"), encoding="utf-8")

    race_dir = root / "race" / "drawings"
    race_dir.mkdir(parents=True)
    safe_png = race_dir / "safe.png"
    safe_png.write_bytes(RACE_SAFE_MARKER)
    race_secret = root / "race-secret.png"
    race_secret.write_bytes(RACE_SECRET_MARKER)
    race_svg = race_dir / "race.svg"
    race_svg.write_text(_svg('<image xlink:href="safe.png"/>'), encoding="utf-8")

    return {
        "secret_xml": secret_xml,
        "traversal_xml": traversal_xml,
        "sibling_svg": sibling_svg,
        "symlink_svg": symlink_svg,
        "plan": plan,
        "sheet": sheet,
        "race_svg": race_svg,
        "race_safe": safe_png,
        "race_secret": race_secret,
        "race_hold": race_dir / "safe.png.held",
    }


class _Server:
    def __init__(self, proc: subprocess.Popen[bytes], port: int, paths: dict[str, Path], log_path: Path):
        self.proc = proc
        self.port = port
        self.paths = paths
        self.log_path = log_path


def _start_server(tmp: Path, paths: dict[str, Path]) -> _Server:
    port = _free_port()
    log_path = tmp / "sioserver.log"
    log_file = log_path.open("w", encoding="utf-8")
    # Same arguments and working directory Bonsai uses (web.py start_websocket_server).
    # Static routes are resolved from that directory at import.
    proc = subprocess.Popen(
        [sys.executable, str(SIOSERVER), "--p", str(port), "--host", "127.0.0.1"],
        cwd=SIOSERVER.parent,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    log_file.close()
    return _Server(proc, port, paths, log_path)


async def _wait_until_listening(server: _Server) -> None:
    url = f"http://127.0.0.1:{server.port}/socket.io/?EIO=4&transport=polling"
    deadline = time.monotonic() + 15
    async with aiohttp.ClientSession() as session:
        while time.monotonic() < deadline:
            if server.proc.poll() is not None:
                break
            try:
                async with session.get(url) as response:
                    body = await response.text()
                if response.status == 200 and body.startswith("0"):
                    return
            except (aiohttp.ClientError, ConnectionError, OSError):
                pass
            await asyncio.sleep(0.05)
    log = server.log_path.read_text(encoding="utf-8", errors="replace")
    raise RuntimeError(f"sioserver did not accept an Engine.IO handshake.\n{log}")


async def _publish_drawings(server: _Server) -> None:
    """Send the same drawings_data payload Bonsai emits for one drawing and one sheet."""
    client = socketio.AsyncClient(reconnection=False)
    await client.connect(
        f"http://127.0.0.1:{server.port}",
        namespaces=["/blender"],
        wait_timeout=5,
    )
    await client.emit(
        "drawings_data",
        {
            "ifc_file": "model.ifc",
            "is_dirty": False,
            "drawings_data": {
                "drawings": [{"name": "plan.svg", "path": str(server.paths["plan"])}],
                "sheets": [{"name": "sheet.svg", "path": str(server.paths["sheet"])}],
            },
        },
        namespace="/blender",
    )
    await client.disconnect()


def _payload_text(payloads: list[object]) -> str:
    chunks: list[str] = []
    for payload in payloads:
        if isinstance(payload, bytes):
            chunks.append(payload.decode("utf-8", errors="replace"))
        else:
            chunks.append(str(payload))
    return "\n".join(chunks)


async def _request_svg(port: int, path: str, origin: str | None) -> tuple[bool, str]:
    """Emit get_svg the way drawings.js does. No auth token is sent."""
    client = socketio.AsyncClient(reconnection=False)
    payloads: list[object] = []
    received = asyncio.Event()
    # theme_data is pushed on connect, before get_svg. Ignore it so we do not
    # treat that greeting as the response and disconnect too early.
    armed = False

    @client.on("*", namespace="/web")
    async def _catch_all(event: str, data: object = None) -> None:
        nonlocal armed
        if not armed or event in {"connect", "disconnect"}:
            return
        payloads.append({"event": event, "data": data})
        if event == "svg_data":
            received.set()

    headers = {} if origin is None else {"Origin": origin}
    try:
        await client.connect(
            f"http://127.0.0.1:{port}",
            namespaces=["/web"],
            headers=headers,
            auth=None,
            wait_timeout=5,
        )
    except (TimeoutError, socketio.exceptions.ConnectionError, OSError):
        return False, ""
    try:
        armed = True
        await client.emit("get_svg", {"path": path}, namespace="/web")
        try:
            await asyncio.wait_for(received.wait(), timeout=3)
        except TimeoutError:
            pass
        return True, _payload_text(payloads)
    finally:
        await client.disconnect()


def _needles(*markers: str | bytes) -> list[str]:
    found: list[str] = []
    for marker in markers:
        raw = marker.decode("utf-8") if isinstance(marker, bytes) else marker
        found.append(raw)
        blob = marker if isinstance(marker, bytes) else marker.encode("utf-8")
        found.append(base64.b64encode(blob).decode("ascii"))
    return found


async def _assert_hidden(server: _Server, path: str | Path, markers: list[str | bytes], label: str) -> None:
    leaked: list[str] = []
    refused_connection = False
    for origin in (None, EVIL_ORIGIN):
        connected, text = await _request_svg(server.port, str(path), origin)
        if not connected:
            refused_connection = True
            continue
        for needle in _needles(*markers):
            if needle and needle in text:
                leaked.append(f"origin={origin!r} needle={needle!r} body={text[:800]!r}")
    if leaked:
        pytest.fail(f"{label} was disclosed to an unauthenticated /web client:\n" + "\n".join(leaked))
    # A refused Socket.IO connection discloses nothing. A live server that returns
    # no file body is the other passing outcome. ``_wait_until_listening`` already
    # proved the process is the SVG server.
    assert refused_connection or not leaked


@pytest.fixture(scope="module")
def disclosure_server():
    if not SIOSERVER.is_file():
        raise RuntimeError(f"missing {SIOSERVER}")
    tmp = Path(tempfile.mkdtemp(prefix="bonsai-svg-disclosure-"))
    paths = _build_tree(tmp)
    pid_file = SIOSERVER.parent / "running_pid.json"
    previous_pid = pid_file.read_text(encoding="utf-8") if pid_file.exists() else None
    server = _start_server(tmp, paths)

    async def _boot() -> None:
        await _wait_until_listening(server)
        await _publish_drawings(server)

    try:
        asyncio.run(_boot())
        yield server
    finally:
        if server.proc.poll() is None:
            server.proc.terminate()
            try:
                server.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.proc.kill()
                server.proc.wait(timeout=5)
        if previous_pid is None:
            pid_file.unlink(missing_ok=True)
        else:
            pid_file.write_text(previous_pid, encoding="utf-8")


def test_get_svg_does_not_return_xml_outside_published_drawings(disclosure_server: _Server) -> None:
    asyncio.run(_assert_hidden(disclosure_server, disclosure_server.paths["secret_xml"], [XML_MARKER], "secret xml"))


def test_get_svg_does_not_return_unpublished_svg_in_drawing_directory(disclosure_server: _Server) -> None:
    asyncio.run(
        _assert_hidden(
            disclosure_server,
            disclosure_server.paths["sibling_svg"],
            [SIBLING_SVG_MARKER],
            "unpublished svg",
        )
    )


def test_get_svg_does_not_return_path_that_normalizes_outside_drawing_directory(disclosure_server: _Server) -> None:
    plan = disclosure_server.paths["plan"]
    # ".." is kept in the client string and the first segment is the drawing directory,
    # so a prefix check on that directory still matches. Opening the path escapes it.
    escape = str(plan.parent) + "/../traversal.xml"
    asyncio.run(_assert_hidden(disclosure_server, escape, [TRAVERSAL_MARKER], "normalised traversal path"))


def test_get_svg_does_not_follow_symlink_to_xml_outside_drawing_directory(disclosure_server: _Server) -> None:
    asyncio.run(
        _assert_hidden(
            disclosure_server,
            disclosure_server.paths["symlink_svg"],
            [XML_MARKER],
            "symlink svg",
        )
    )


def test_get_svg_does_not_inline_images_that_resolve_outside_drawing_directory(disclosure_server: _Server) -> None:
    asyncio.run(
        _assert_hidden(
            disclosure_server,
            disclosure_server.paths["plan"],
            [PNG_MARKER, ABS_PNG_MARKER, JPEG_MARKER, LINKED_SVG_MARKER, DIRLINK_MARKER, SYMLINK_PNG_MARKER],
            "linked image",
        )
    )


def _load_sioserver():
    import importlib.util

    spec = importlib.util.spec_from_file_location("bonsai_sioserver_under_test", SIOSERVER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SIOSERVER}")
    module = importlib.util.module_from_spec(spec)
    # add_static resolves ../gantt from the process cwd. Bonsai launches the
    # script with cwd set to the webui directory.
    previous = os.getcwd()
    os.chdir(SIOSERVER.parent)
    try:
        spec.loader.exec_module(module)
    finally:
        os.chdir(previous)
    return module


def test_image_open_uses_the_file_that_was_checked(tmp_path: Path) -> None:
    """Fail if the image path is looked up, then opened again as a path.

    After the check observes the in-directory file, that directory entry is
    replaced with a symlink to a file outside the drawing directory. Reading
    the secret means the open did not use the checked file.
    """
    paths = _build_tree(tmp_path)
    module = _load_sioserver()
    safe = paths["race_safe"]
    secret = paths["race_secret"]
    hold = paths["race_hold"]
    safe_abs = str(safe.resolve())
    state = {"done": False}
    original_stat = os.stat
    original_lstat = os.lstat

    def maybe_swap(path: object) -> None:
        if state["done"] or not isinstance(path, (str, bytes, os.PathLike)):
            return
        try:
            absolute = os.path.abspath(os.fsdecode(path))
        except (TypeError, ValueError):
            return
        if absolute != safe_abs:
            return
        state["done"] = True
        os.rename(safe, hold)
        os.symlink(secret, safe)

    def wrapped_stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        maybe_swap(path)
        return result

    def wrapped_lstat(path, *args, **kwargs):
        result = original_lstat(path, *args, **kwargs)
        maybe_swap(path)
        return result

    async def scenario() -> str:
        from aiohttp import web

        previous = os.getcwd()
        os.chdir(tmp_path)
        runner = web.AppRunner(module.app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        os.stat = wrapped_stat
        os.lstat = wrapped_lstat
        try:
            _connected, text = await _request_svg(port, str(paths["race_svg"]), None)
            return text
        finally:
            os.stat = original_stat
            os.lstat = original_lstat
            await runner.cleanup()
            os.chdir(previous)

    text = asyncio.run(scenario())
    secret_b64 = base64.b64encode(RACE_SECRET_MARKER).decode("ascii")
    assert RACE_SECRET_MARKER.decode("ascii") not in text
    assert secret_b64 not in text
