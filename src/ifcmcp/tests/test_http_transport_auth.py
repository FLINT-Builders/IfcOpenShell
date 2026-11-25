# This file was generated with the assistance of an AI coding tool.
"""Unauthenticated ifcmcp HTTP transports must not touch the operator's files.

``ifcmcp --transport streamable-http`` and ``ifcmcp --transport sse`` start a
loopback MCP server. These tests connect to that server the way another local
user would, with no Authorization header and no auth handler, and require that
the call cannot:

- read an IFC model that lives outside the server's working directory
- write an IFC model to a caller-chosen path, including overwriting the file
  that was loaded
- write the PNG or SVG from ``ifc_plot`` or the PNG from ``ifc_render``

They fail while those calls succeed. A fix that rejects the transport, requires
credentials before any tool runs, or refuses paths outside a working directory
without creating or modifying the target file makes them pass.

Run from an environment that has this repo's ifcmcp, ifcquery, ifcedit, ifc5d,
ifcopenshell, mcp>=1.0,<2, pytest, httpx, cairosvg, and pyvista installed:

    python -m pytest src/ifcmcp/tests/test_http_transport_auth.py -vv
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
import ifcopenshell.api.aggregate
import ifcopenshell.api.owner.settings
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import pytest
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

HOST = "127.0.0.1"
PORT = 8000
PROJECT_MARKER = "OperatorProjectMarker"
WALL_MARKER = "OperatorWallMarker"
SENTINEL = b"SENTINEL-NOT-IFC\n"
BASIC_IFC = Path(__file__).resolve().parents[2] / "bonsai" / "test" / "files" / "basic.ifc"
MISSING_DEPENDENCY = (
    "CairoSVG is not installed",
    "ifcopenshell.draw is not available",
    "pyvista is not installed",
)

TRANSPORTS = ("streamable-http", "sse")


def _make_private_model(path: Path) -> int:
    model = ifcopenshell.api.project.create_file()
    ifcopenshell.api.owner.settings.get_user = lambda ifc: (ifc.by_type("IfcPersonAndOrganization") or [None])[0]
    ifcopenshell.api.owner.settings.get_application = lambda ifc: (ifc.by_type("IfcApplication") or [None])[0]
    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name=PROJECT_MARKER)
    ifcopenshell.api.unit.assign_unit(model)
    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name="Building")
    storey = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuildingStorey", name="Storey")
    ifcopenshell.api.aggregate.assign_object(model, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(model, products=[building], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(model, products=[storey], relating_object=building)
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name=WALL_MARKER)
    ifcopenshell.api.spatial.assign_container(model, products=[wall], relating_structure=storey)
    model.write(str(path))
    path.chmod(0o600)
    return wall.id()


def _endpoint(transport: str) -> str:
    if transport == "streamable-http":
        return f"http://{HOST}:{PORT}/mcp"
    if transport == "sse":
        return f"http://{HOST}:{PORT}/sse"
    raise AssertionError(transport)


def _client(transport: str, **kwargs):
    url = _endpoint(transport)
    if transport == "streamable-http":
        return streamable_http_client(url, **kwargs)
    return sse_client(url, **kwargs)


class _Server:
    def __init__(self, transport: str, cwd: Path):
        self.log_path = cwd / "server.log"
        self._log = self.log_path.open("w")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "ifcmcp", "--transport", transport],
            cwd=cwd,
            stdout=self._log,
            stderr=subprocess.STDOUT,
        )
        self.listening = self._wait_until_listening()

    def _wait_until_listening(self) -> bool:
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False
            try:
                with socket.create_connection((HOST, PORT), 0.2):
                    return True
            except OSError:
                time.sleep(0.05)
        return False

    def output(self) -> str:
        self._log.flush()
        return self.log_path.read_text(errors="replace")

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)
        self._log.close()
        deadline = time.time() + 5
        while time.time() < deadline:
            probe = socket.socket()
            try:
                probe.bind((HOST, PORT))
            except OSError:
                time.sleep(0.05)
                continue
            else:
                return
            finally:
                probe.close()


def _refuse_startup_failure(server: _Server) -> None:
    text = server.output()
    if "Traceback" in text or "Address already in use" in text:
        pytest.fail(text[-4000:])


async def _tool_text(transport: str, calls: list[tuple[str, dict]]) -> str:
    """Call tools with the MCP client defaults: no auth handler and no token."""
    chunks: list[str] = []
    async with _client(transport) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            try:
                await session.initialize()
            except Exception as exc:
                return f"{type(exc).__name__}: {exc}"
            for name, arguments in calls:
                try:
                    result = await session.call_tool(name, arguments)
                    chunks.append(result.model_dump_json())
                except Exception as exc:
                    chunks.append(f"{type(exc).__name__}: {exc}")
    return "\n".join(chunks)


def _exercise(transport: str, cwd: Path, attack: Callable[[], Awaitable[str]]) -> str | None:
    server = _Server(transport, cwd)
    try:
        if not server.listening:
            _refuse_startup_failure(server)
            return None
        text = asyncio.run(attack())
    finally:
        server.close()
    if "Connection refused" in text or "All connection attempts failed" in text:
        pytest.fail(text)
    for needle in MISSING_DEPENDENCY:
        if needle in text:
            pytest.fail(f"write path was not exercised: {needle}\n{text[-2000:]}")
    return text


def _snapshot(path: Path) -> tuple[int, bytes]:
    stat = path.stat()
    return stat.st_mtime_ns, path.read_bytes()


@pytest.fixture
def server_cwd(tmp_path: Path) -> Path:
    cwd = tmp_path / "server-cwd"
    cwd.mkdir()
    return cwd


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_unauthenticated_client_cannot_read_model(transport: str, tmp_path: Path, server_cwd: Path):
    model_path = tmp_path / "operator-model.ifc"
    wall_id = _make_private_model(model_path)

    async def attack() -> str:
        return await _tool_text(
            transport,
            [
                ("ifc_load", {"path": str(model_path)}),
                ("ifc_summary", {}),
                ("ifc_select", {"query": "IfcWall"}),
                ("ifc_info", {"element_id": wall_id}),
                ("ifc_tree", {}),
                ("ifc_relations", {"element_id": wall_id}),
            ],
        )

    text = _exercise(transport, server_cwd, attack)
    if text is None:
        return
    if PROJECT_MARKER in text or WALL_MARKER in text:
        pytest.fail("unauthenticated client received the loaded model")


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_unauthenticated_client_cannot_write_model(transport: str, tmp_path: Path, server_cwd: Path):
    model_path = tmp_path / "operator-model.ifc"
    _make_private_model(model_path)
    original = _snapshot(model_path)
    overwrite = tmp_path / "overwrite-me.ifc"
    overwrite.write_bytes(SENTINEL)
    overwrite_before = overwrite.read_bytes()
    created = tmp_path / "must-not-be-created.ifc"

    async def attack() -> str:
        return await _tool_text(
            transport,
            [
                ("ifc_new", {"schema": "IFC4"}),
                ("ifc_save", {"path": str(overwrite)}),
                ("ifc_save", {"path": str(created)}),
                ("ifc_load", {"path": str(model_path)}),
                ("ifc_save", {"path": ""}),
            ],
        )

    _exercise(transport, server_cwd, attack)
    problems: list[str] = []
    if overwrite.read_bytes() != overwrite_before:
        problems.append("overwrote the caller-chosen file")
    if created.exists():
        problems.append("created a file")
    if _snapshot(model_path) != original:
        problems.append("overwrote the loaded model")
    if problems:
        pytest.fail("ifc_save " + " and ".join(problems))


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_unauthenticated_client_cannot_write_plot(transport: str, tmp_path: Path, server_cwd: Path):
    model_path = tmp_path / "operator-model.ifc"
    shutil.copy(BASIC_IFC, model_path)
    png = tmp_path / "plot.png"
    svg = tmp_path / "plot.svg"
    png.write_bytes(SENTINEL)
    svg.write_bytes(SENTINEL)
    plot_args = {
        "selector": "",
        "element_ids": None,
        "view": "elevation",
        "width_mm": 297.0,
        "height_mm": 420.0,
        "scale": 0.01,
        "png_width": 32,
        "png_height": 32,
    }

    async def attack() -> str:
        return await _tool_text(
            transport,
            [
                ("ifc_load", {"path": str(model_path)}),
                ("ifc_plot", {**plot_args, "output_path": str(png)}),
                ("ifc_plot", {**plot_args, "output_path": str(svg)}),
            ],
        )

    _exercise(transport, server_cwd, attack)
    if png.read_bytes() != SENTINEL or svg.read_bytes() != SENTINEL:
        pytest.fail(f"ifc_plot wrote png={png.read_bytes()[:8]!r} svg={svg.read_bytes()[:8]!r}")


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_unauthenticated_client_cannot_write_render(transport: str, tmp_path: Path, server_cwd: Path):
    model_path = tmp_path / "operator-model.ifc"
    shutil.copy(BASIC_IFC, model_path)
    png = tmp_path / "render.png"
    png.write_bytes(SENTINEL)

    async def attack() -> str:
        return await _tool_text(
            transport,
            [
                ("ifc_load", {"path": str(model_path)}),
                (
                    "ifc_render",
                    {"selector": "", "element_ids": None, "view": "iso", "output_path": str(png)},
                ),
            ],
        )

    _exercise(transport, server_cwd, attack)
    if png.read_bytes() != SENTINEL:
        pytest.fail(f"ifc_render wrote {png.read_bytes()[:8]!r}")


def _rebinding_request(transport: str, session_id: str, path: Path) -> httpx.Request:
    body = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "tools/call",
        "params": {"name": "ifc_save", "arguments": {"path": str(path)}},
    }
    headers = {
        "Host": "rebinding.example",
        "Origin": "http://rebinding.example",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "mcp-protocol-version": "2025-11-25",
    }
    if transport == "streamable-http":
        headers["mcp-session-id"] = session_id
        url = _endpoint(transport)
    else:
        url = f"http://{HOST}:{PORT}/messages/?session_id={session_id}"
    return httpx.Request("POST", url, headers=headers, json=body)


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_rebinding_host_cannot_save(transport: str, tmp_path: Path, server_cwd: Path):
    """A session opened on loopback must not accept a rebound Host header.

    mcp 1.30.0 enables this check for the default loopback bind. The test
    still has to fail if a session created without credentials can be reused
    from a foreign host to write a file.
    """
    target = tmp_path / "rebind-target.ifc"
    target.write_bytes(SENTINEL)
    session_ids: list[str] = []

    async def attack() -> str:
        kwargs = {"on_session_created": session_ids.append} if transport == "sse" else {"terminate_on_close": False}
        async with _client(transport, **kwargs) as streams:
            get_session_id = streams[2] if transport == "streamable-http" else None
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                await session.call_tool("ifc_new", {"schema": "IFC4"})
                session_id = get_session_id() if get_session_id else session_ids[0]
                request = _rebinding_request(transport, session_id, target)
                async with httpx.AsyncClient() as http:
                    response = await http.send(request)
                return f"{response.status_code}\n{response.text}"

    text = _exercise(transport, server_cwd, attack)
    assert target.read_bytes() == SENTINEL
    if text is not None:
        status = int(text.split("\n", 1)[0])
        assert status in (403, 421)
