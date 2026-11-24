# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

# This file was generated with the assistance of an AI coding tool.

"""Security tests for the Bonsai web UI Socket.IO server.

These tests fail while the server accepts any origin, accepts a Socket.IO
connection that does not present the session token, or returns XML from
outside the project directory. They are the specification for the fix:

- Every HTML page served by sioserver.py (``/``, ``/costing``, ``/sequencing``,
  ``/documentation``, ``/demo``) embeds one per-process secret in
  ``<meta name="bonsai-webui-token" content="...">``. The same value is
  required in the Socket.IO auth payload as ``{"token": "<that value>"}`` on
  both ``/web`` and ``/blender``. ``on_connect`` rejects a missing or wrong
  token before emitting any event.
- Engine.IO accepts only ``Origin: http://127.0.0.1:<port>`` for polling and
  for websocket. A client that presents the page token with any other origin
  is rejected, and that rejection happens before any event is emitted.
- ``get_svg`` may return only files whose canonical path is inside
  ``BONSAI_WEBUI_PROJECT_DIR``. The path that is opened is that canonical
  path. A path that merely starts with the project directory, a symlink
  inside the project that points outside it, and an ``xlink:href`` (absolute
  or relative) that resolves outside it must not contribute file bytes to
  the response. A drawing that is inside the directory is still returned.

The IfcTester Socket.IO server in ``bonsai/bim/module/tester/operator.py`` is
not covered. It is started inside Blender and is not this server.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.request
from pathlib import Path

import pytest
import socketio

WEBUI_DIR = Path(__file__).resolve().parents[2] / "bonsai" / "bim" / "data" / "webui"
SERVER_SCRIPT = WEBUI_DIR / "sioserver.py"
HTML_PAGES = ("/", "/costing", "/sequencing", "/documentation", "/demo")
FOREIGN_ORIGIN = "http://evil.example"
TOKEN_META = re.compile(
    r"""<meta\s+[^>]*name=["']bonsai-webui-token["'][^>]*content=["']([^"']*)["']""",
    re.IGNORECASE,
)
TOKEN_META_REVERSED = re.compile(
    r"""<meta\s+[^>]*content=["']([^"']*)["'][^>]*name=["']bonsai-webui-token["']""",
    re.IGNORECASE,
)
PLACEHOLDER_TOKEN = "not-the-session-secret"
OUTSIDE_XML_MARKER = "MARKER-XML-SECRET"
INSIDE_DRAWING_MARKER = "INSIDE-DRAWING"
OUTSIDE_PNG_BYTES = b"PNG-OUTSIDE-BYTES"
IGNORED_EVENTS = {"connect", "disconnect"}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _page_token(port: int, page: str = "/costing") -> str | None:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{page}", timeout=5) as response:
        html = response.read().decode("utf-8", errors="replace")
    match = TOKEN_META.search(html) or TOKEN_META_REVERSED.search(html)
    if match is None:
        return None
    token = match.group(1).strip()
    return token or None


def _local_origin(port: int) -> str:
    return f"http://127.0.0.1:{port}"


class RunningServer:
    """The product entry point: ``sioserver.py --p <port> --host 127.0.0.1``."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.port = _free_port()
        self.proc: subprocess.Popen[bytes] | None = None
        self.log_path: Path | None = None
        self._log_handle = None

    def start(self) -> RunningServer:
        log = tempfile.NamedTemporaryFile(prefix="sioserver-", suffix=".log", delete=False)
        self.log_path = Path(log.name)
        log.close()
        self._log_handle = open(self.log_path, "wb")
        env = os.environ.copy()
        env.pop("BONSAI_LIB_PATH", None)
        env["BONSAI_WEBUI_PROJECT_DIR"] = str(self.project_dir)
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT), "--p", str(self.port), "--host", "127.0.0.1"],
            cwd=str(WEBUI_DIR),
            env=env,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 10
        while time.time() < deadline:
            if self.proc.poll() is not None:
                tail = self.log_tail()
                code = self.proc.returncode
                self.stop()
                pytest.fail(f"sioserver.py exited {code}:\n{tail}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return self
            except OSError:
                time.sleep(0.05)
        tail = self.log_tail()
        self.stop()
        pytest.fail(f"sioserver.py did not accept connections:\n{tail}")

    def log_tail(self) -> str:
        if self.log_path is None or not self.log_path.exists():
            return ""
        return self.log_path.read_text(errors="replace")[-4000:]

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None
        pid_file = WEBUI_DIR / "running_pid.json"
        if pid_file.exists() and self.proc is not None:
            try:
                pids = json.loads(pid_file.read_text() or "{}")
                pids.pop(str(self.proc.pid), None)
                if pids:
                    pid_file.write_text(json.dumps(pids, indent=4))
                else:
                    pid_file.unlink()
            except (OSError, ValueError):
                pass
        if self.log_path is not None:
            self.log_path.unlink(missing_ok=True)

    def __enter__(self) -> RunningServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


def _client() -> socketio.AsyncClient:
    return socketio.AsyncClient(reconnection=False)


async def _connect(
    client: socketio.AsyncClient,
    port: int,
    namespace: str,
    origin: str,
    transports: list[str],
    auth: dict | None,
) -> bool:
    try:
        await client.connect(
            f"http://127.0.0.1:{port}",
            namespaces=[namespace],
            headers={"Origin": origin},
            transports=transports,
            auth=auth,
            wait_timeout=5,
            retry=False,
        )
    except socketio.exceptions.ConnectionError:
        return False
    return bool(client.connected)


def _record(client: socketio.AsyncClient, namespace: str) -> list[tuple]:
    received: list[tuple] = []

    async def on_any(event, *args):
        received.append((event, args))

    client.on("*", on_any, namespace=namespace)
    return received


def _interesting(received: list[tuple]) -> list[tuple]:
    return [item for item in received if item[0] not in IGNORED_EVENTS]


async def _disconnect(client: socketio.AsyncClient) -> None:
    if client.connected:
        await client.disconnect()


def _auth_for_page(port: int) -> dict | None:
    token = _page_token(port)
    if token is None:
        return None
    return {"token": token}


async def _seed_blender(port: int) -> tuple[socketio.AsyncClient, str]:
    """Connect the way Blender does, using the page token once the server issues one."""
    client = _client()
    origin = _local_origin(port)
    connected = await _connect(
        client,
        port,
        "/blender",
        origin,
        ["websocket"],
        _auth_for_page(port),
    )
    assert connected, "Blender's own client could not connect; the server never became usable"
    sid = client.get_sid(namespace="/blender")
    assert sid
    await client.emit(
        "csv_data",
        [{"GlobalId": "wall-guid", "Name": "Secret Wall"}],
        namespace="/blender",
    )
    await client.emit(
        "gantt_data",
        {"tasks": [{"id": 3, "Name": "Pour slab", "pStart": "2020-01-01"}], "work_schedule": {"id": 4}},
        namespace="/blender",
    )
    await client.emit(
        "cost_items",
        {"schedule": "secret-cost-schedule", "items": [{"id": 7, "Name": "Concrete"}]},
        namespace="/blender",
    )
    await client.emit("demo_data", {"note": "secret-demo"}, namespace="/blender")
    await asyncio.sleep(0.5)
    return client, sid


def _operator_payloads(blender_sid: str) -> list[dict]:
    """Every operator the web UI forwards and tool/web.py dispatches, plus the two shapes that broadcast."""
    cost = "cost"
    targeted = [
        ("deleteCostItem", {"type": "deleteCostItem", "costItemId": 11}),
        (
            "editCostValues",
            {
                "type": "editCostValues",
                "costItemId": 11,
                "costValues": [
                    {
                        "id": 21,
                        "costType": "FIXED",
                        "appliedValue": 12.5,
                        "unitBasisValue": None,
                    }
                ],
            },
        ),
        ("editCostItemName", {"type": "editCostItemName", "costItemId": 11, "name": "renamed-by-page"}),
        ("addCostSchedule", {"type": "addCostSchedule", "name": "extra", "predefinedType": "BUDGET"}),
        ("getCostSchedules", {"type": "getCostSchedules"}),
        ("loadCostSchedule", {"type": "loadCostSchedule", "costScheduleId": 5}),
        ("selectAssignedElements", {"type": "selectAssignedElements", "costItemId": 11}),
        ("addSummaryCostItem", {"type": "addSummaryCostItem", "costScheduleId": 5}),
        ("addCostItem", {"type": "addCostItem", "costItemId": 11}),
        ("duplicateCostItem", {"type": "duplicateCostItem", "costItemId": 11}),
        ("getPredefinedTypes", {"type": "getPredefinedTypes"}),
        ("enableEditingCostValues", {"type": "enableEditingCostValues", "costItemId": 11}),
        ("addCostValue", {"type": "addCostValue", "costItemId": 11}),
        ("addSumCostValue", {"type": "addSumCostValue", "costItemId": 11}),
        ("deleteCostValue", {"type": "deleteCostValue", "costItemId": 11, "costValueId": 22}),
        ("addProductAssignments", {"type": "addProductAssignments", "costItemId": 11, "propName": "NetVolume"}),
        ("enableEditingQuantities", {"type": "enableEditingQuantities", "costItemId": 11}),
        ("AddCostItemQuantity", {"type": "AddCostItemQuantity", "costItemId": 11, "ifcClass": "IfcQuantityVolume"}),
        (
            "editCostItemQuantity",
            {"type": "editCostItemQuantity", "costItemId": 11, "quantityId": 8, "attributes": {"Name": "Volume"}},
        ),
        ("deleteCostItemQuantity", {"type": "deleteCostItemQuantity", "costItemId": 11, "quantityId": 8}),
        ("enableEditingClassification", {"type": "enableEditingClassification", "costItemId": 11}),
        (
            "removeClassificationReference",
            {"type": "removeClassificationReference", "costItemId": 11, "classificationId": 9},
        ),
        (
            "addClassificationReference",
            {
                "type": "addClassificationReference",
                "costItemId": 11,
                "classificationId": 9,
                "classificationName": "Uniclass",
            },
        ),
        (
            "assignFromQuery",
            {"type": "assignFromQuery", "costItemId": 11, "propName": "NetVolume", "query": "IfcWall"},
        ),
        ("assignCostValues", {"type": "assignCostValues", "costRateId": 30, "costItemIds": [11]}),
    ]
    payloads = [{"sourcePage": cost, "blenderId": blender_sid, "operator": operator} for _name, operator in targeted]
    for column, value in (("pStart", "2030-01-01"), ("pEnd", "2030-02-01"), ("pName", "Moved")):
        payloads.append(
            {
                "sourcePage": "gantt",
                "blenderId": blender_sid,
                "operator": {
                    "type": "editTask",
                    "taskId": 3,
                    "column": column,
                    "value": value,
                    "workScheduleId": 4,
                },
            }
        )
    payloads.extend(
        [
            {
                "sourcePage": "gantt",
                "blenderId": blender_sid,
                "operator": {"type": "getWorkSchedules"},
            },
            {
                "sourcePage": "gantt",
                "blenderId": blender_sid,
                "operator": {"type": "loadWorkSchedule", "workScheduleId": 4},
            },
            {
                "sourcePage": "csv",
                "blenderId": blender_sid,
                "operator": {"type": "selection", "globalId": "wall-guid"},
            },
            {
                "sourcePage": "drawings",
                "blenderId": blender_sid,
                "operator": {"type": "getDrawings"},
            },
            {
                "sourcePage": "demo",
                "blenderId": blender_sid,
                "operator": {"message": "from-the-page"},
            },
            # No blender id: the server addresses every client in the blender namespace.
            {"sourcePage": "cost", "operator": {"type": "deleteCostItem", "costItemId": 99}},
            # Key spelled the way the costing page sends it. The server does not read it.
            {
                "sourcePage": "cost",
                "BlenderId": blender_sid,
                "operator": {"type": "editCostItemName", "costItemId": 11, "name": "from-cost-page"},
            },
        ]
    )
    return payloads


def _layout(root: Path) -> dict[str, Path]:
    project = root / "project"
    outside = root / "outside"
    nested = project / "nested"
    project.mkdir()
    outside.mkdir()
    nested.mkdir()
    outside_xml = outside / "secret.xml"
    outside_xml.write_text(
        f"<?xml version='1.0'?><root><secret>{OUTSIDE_XML_MARKER}</secret></root>",
        encoding="utf-8",
    )
    outside_png = outside / "secret.png"
    outside_png.write_bytes(OUTSIDE_PNG_BYTES)
    inside = project / "plan.svg"
    inside.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg"><text>{INSIDE_DRAWING_MARKER}</text></svg>',
        encoding="utf-8",
    )
    link = project / "linked.xml"
    link.symlink_to(outside_xml)
    traversal = nested / ".." / ".." / "outside" / "secret.xml"
    image = project / "with-image.svg"
    image.write_text(
        textwrap.dedent(
            f"""\
            <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
              <image xlink:href="{outside_png}"/>
              <image xlink:href="../outside/secret.png"/>
            </svg>
            """
        ),
        encoding="utf-8",
    )
    return {
        "project": project,
        "outside_xml": outside_xml,
        "outside_png": outside_png,
        "inside": inside,
        "link": link,
        "traversal": traversal,
        "image": image,
    }


async def _svg_responses(client: socketio.AsyncClient, received: list[tuple], path: Path) -> list[tuple]:
    before = len(received)
    await client.emit("get_svg", {"path": str(path)}, namespace="/web")
    deadline = time.time() + 2
    while time.time() < deadline:
        if any(event == "svg_data" for event, _args in received[before:]):
            break
        await asyncio.sleep(0.05)
    else:
        await asyncio.sleep(0.2)
    return received[before:]


def _flat_text(events: list[tuple]) -> str:
    return "\n".join(repr(item) for item in events)


@pytest.fixture
def server():
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "project"
        project.mkdir()
        running = RunningServer(project)
        try:
            running.start()
            yield running
        finally:
            running.stop()


def test_foreign_origin_polling_client_receives_no_schedule_data(server: RunningServer):
    asyncio.run(_assert_foreign_origin_receives_nothing(server, ["polling"]))


def test_foreign_origin_websocket_client_receives_no_schedule_data(server: RunningServer):
    asyncio.run(_assert_foreign_origin_receives_nothing(server, ["websocket"]))


async def _assert_foreign_origin_receives_nothing(server: RunningServer, transports: list[str]) -> None:
    blender, _sid = await _seed_blender(server.port)
    attacker = _client()
    received = _record(attacker, "/web")
    try:
        connected = await _connect(
            attacker,
            server.port,
            "/web",
            FOREIGN_ORIGIN,
            transports,
            None,
        )
        if connected:
            await blender.emit(
                "cost_schedules",
                {"cost_schedules": [{"Name": "Budget A"}], "currency": "USD"},
                namespace="/blender",
            )
            await blender.emit(
                "work_schedule_info",
                [{"Name": "Programme"}],
                namespace="/blender",
            )
            await blender.emit(
                "drawings_data",
                {"drawings": [{"name": "plan.svg", "path": "/drawings/plan.svg"}]},
                namespace="/blender",
            )
            await blender.emit("cost_values", {"cost_values": [{"id": 21}], "cost_item_id": 7}, namespace="/blender")
            await blender.emit("cost_value", {"cost_value_id": 21, "cost_item_id": 7}, namespace="/blender")
            await blender.emit("predefined_types", ["BUDGET"], namespace="/blender")
            await blender.emit("quantities", {"cost_item_id": 7}, namespace="/blender")
            await blender.emit("classification", {"cost_item_id": 7}, namespace="/blender")
            await blender.emit("message", {"error": "nope"}, namespace="/blender")
            await blender.emit("data", {"elements": [{"Name": "Wall"}]}, namespace="/blender")
            await asyncio.sleep(1.0)
        leaked = _interesting(received)
        assert leaked == [], (
            f"origin {FOREIGN_ORIGIN} on {transports} received schedule data before the connection was refused: "
            f"{_flat_text(leaked)[:2000]}"
        )
        assert not connected, (
            f"origin {FOREIGN_ORIGIN} completed the Socket.IO handshake on {transports} without a token"
        )
    finally:
        await _disconnect(attacker)
        await _disconnect(blender)


def test_foreign_origin_cannot_deliver_web_operators(server: RunningServer):
    asyncio.run(_assert_operators_not_delivered(server, ["polling", "websocket"]))


def test_foreign_origin_websocket_cannot_deliver_web_operators(server: RunningServer):
    asyncio.run(_assert_operators_not_delivered(server, ["websocket"]))


async def _assert_operators_not_delivered(server: RunningServer, transports: list[str]) -> None:
    blender, sid = await _seed_blender(server.port)
    delivered: list = []

    async def on_operator(data):
        delivered.append(data)

    blender.on("web_operator", on_operator, namespace="/blender")
    attacker = _client()
    try:
        connected = await _connect(attacker, server.port, "/web", FOREIGN_ORIGIN, transports, None)
        if connected:
            for payload in _operator_payloads(sid):
                await attacker.emit("web_operator", payload, namespace="/web")
            await asyncio.sleep(1.0)
        assert delivered == [], (
            f"web_operator commands from a foreign origin were delivered to the Blender client: {delivered!r}"[:2000]
        )
        assert not connected, "foreign origin connected to /web without a token"
    finally:
        await _disconnect(attacker)
        await _disconnect(blender)


@pytest.mark.parametrize("namespace", ["/web", "/blender"])
@pytest.mark.parametrize("transports", [["polling"], ["websocket"]])
def test_local_origin_without_token_is_rejected(server: RunningServer, namespace: str, transports: list[str]):
    asyncio.run(_assert_local_without_token_rejected(server, namespace, transports))


async def _assert_local_without_token_rejected(server: RunningServer, namespace: str, transports: list[str]) -> None:
    client = _client()
    received = _record(client, namespace)
    try:
        connected = await _connect(client, server.port, namespace, _local_origin(server.port), transports, None)
        await asyncio.sleep(0.5)
        leaked = _interesting(received)
        assert leaked == [], (
            f"{namespace} emitted events to a local client that presented no token: {_flat_text(leaked)[:1500]}"
        )
        assert not connected, f"{namespace} accepted a connection on {transports} with no auth payload"
    finally:
        await _disconnect(client)


def test_pages_embed_one_token_and_local_client_with_that_token_can_connect(server: RunningServer):
    tokens = []
    for page in HTML_PAGES:
        token = _page_token(server.port, page)
        assert token, (
            f'{page} does not embed <meta name="bonsai-webui-token" content="...">. '
            "The browser page and Blender must receive the same per-session secret."
        )
        tokens.append(token)
    assert len(set(tokens)) == 1, f"HTML pages embedded different tokens: {tokens!r}"
    asyncio.run(_assert_token_allows_only_local_origin(server, tokens[0]))


async def _assert_token_allows_only_local_origin(server: RunningServer, token: str) -> None:
    local_web = _client()
    local_blender = _client()
    try:
        web_ok = await _connect(
            local_web, server.port, "/web", _local_origin(server.port), ["polling", "websocket"], {"token": token}
        )
        blender_ok = await _connect(
            local_blender,
            server.port,
            "/blender",
            _local_origin(server.port),
            ["websocket"],
            {"token": token},
        )
        assert web_ok and blender_ok, "the token embedded in the page did not authenticate the local origin"
    finally:
        await _disconnect(local_web)
        await _disconnect(local_blender)

    foreign = _client()
    foreign_events = _record(foreign, "/web")
    try:
        foreign_ok = await _connect(
            foreign, server.port, "/web", FOREIGN_ORIGIN, ["polling", "websocket"], {"token": token}
        )
        await asyncio.sleep(0.5)
        assert _interesting(foreign_events) == [], (
            "a foreign origin that presented the page token received events: "
            f"{_flat_text(_interesting(foreign_events))[:1500]}"
        )
        assert not foreign_ok, "a foreign origin completed the handshake by presenting the page token"
    finally:
        await _disconnect(foreign)

    wrong = _client()
    wrong_events = _record(wrong, "/web")
    try:
        wrong_ok = await _connect(
            wrong,
            server.port,
            "/web",
            _local_origin(server.port),
            ["polling"],
            {"token": PLACEHOLDER_TOKEN},
        )
        await asyncio.sleep(0.5)
        assert _interesting(wrong_events) == [], "a wrong token received events before refusal"
        assert not wrong_ok, "a local client with a wrong token was accepted"
    finally:
        await _disconnect(wrong)

    foreign_blender = _client()
    try:
        injected = []
        listener = _client()
        listener_events = _record(listener, "/web")
        listener_ok = await _connect(
            listener, server.port, "/web", _local_origin(server.port), ["websocket"], {"token": token}
        )
        assert listener_ok
        blender_ok = await _connect(
            foreign_blender, server.port, "/blender", FOREIGN_ORIGIN, ["websocket"], {"token": token}
        )
        if blender_ok:
            await foreign_blender.emit(
                "cost_items",
                {"schedule": "injected-schedule"},
                namespace="/blender",
            )
            await asyncio.sleep(0.5)
        assert not blender_ok, "foreign origin joined /blender with the page token"
        assert not any("injected-schedule" in _flat_text([item]) for item in listener_events), (
            "a foreign /blender client injected schedule data into the web UI"
        )
    finally:
        await _disconnect(foreign_blender)
        if "listener" in locals():
            await _disconnect(listener)


def test_unauthenticated_blender_client_cannot_inject_schedules(server: RunningServer):
    asyncio.run(_assert_blender_namespace_cannot_inject(server))


async def _assert_blender_namespace_cannot_inject(server: RunningServer) -> None:
    listener = _client()
    listener_events = _record(listener, "/web")
    attacker = _client()
    try:
        listening = await _connect(
            listener,
            server.port,
            "/web",
            _local_origin(server.port),
            ["websocket"],
            _auth_for_page(server.port),
        )
        assert listening, "web client could not connect, so blender-namespace injection could not be checked"
        connected = await _connect(attacker, server.port, "/blender", FOREIGN_ORIGIN, ["websocket"], None)
        if connected:
            await attacker.emit("cost_items", {"schedule": "injected-schedule"}, namespace="/blender")
            await attacker.emit("gantt_data", {"tasks": [{"Name": "injected-task"}]}, namespace="/blender")
            await asyncio.sleep(1.0)
        flat = _flat_text(_interesting(listener_events))
        assert "injected-schedule" not in flat and "injected-task" not in flat, (
            f"an unauthenticated /blender client pushed schedule data to the web UI: {flat[:1500]}"
        )
        assert not connected, "foreign origin joined /blender with no token"
    finally:
        await _disconnect(attacker)
        await _disconnect(listener)


def test_get_svg_returns_project_drawings_only():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _layout(Path(tmp))
        asyncio.run(_assert_svg_confinement(paths))


async def _assert_svg_confinement(paths: dict[str, Path]) -> None:
    running = RunningServer(paths["project"])
    running.start()
    client = _client()
    received = _record(client, "/web")
    try:
        connected = await _connect(
            client,
            running.port,
            "/web",
            _local_origin(running.port),
            ["polling", "websocket"],
            _auth_for_page(running.port),
        )
        assert connected, (
            "a client using the token embedded in the page (or no token, while the server still "
            "allows that) could not connect, so get_svg could not be checked"
        )
        forbidden = [
            paths["outside_xml"],
            paths["traversal"],
            paths["link"],
            paths["image"],
        ]
        for path in forbidden:
            events = await _svg_responses(client, received, path)
            flat = _flat_text(events)
            png_b64 = base64.b64encode(OUTSIDE_PNG_BYTES).decode("ascii")
            assert OUTSIDE_XML_MARKER not in flat, (
                f"get_svg returned XML from outside the project for {path}: {flat[:500]}"
            )
            assert png_b64 not in flat, f"get_svg inlined a file from outside the project for {path}"
            assert OUTSIDE_PNG_BYTES.decode() not in flat
        inside_events = await _svg_responses(client, received, paths["inside"])
        assert INSIDE_DRAWING_MARKER in _flat_text(inside_events), (
            "get_svg did not return a drawing that is inside BONSAI_WEBUI_PROJECT_DIR. "
            f"Response: {_flat_text(inside_events)[:500]}"
        )
    finally:
        await _disconnect(client)
        running.stop()


def test_get_svg_foreign_origin_receives_no_file_bytes():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _layout(Path(tmp))
        asyncio.run(_assert_foreign_svg_refused(paths))


async def _assert_foreign_svg_refused(paths: dict[str, Path]) -> None:
    running = RunningServer(paths["project"])
    running.start()
    attacker = _client()
    received = _record(attacker, "/web")
    try:
        connected = await _connect(attacker, running.port, "/web", FOREIGN_ORIGIN, ["polling", "websocket"], None)
        if connected:
            await attacker.emit("get_svg", {"path": str(paths["outside_xml"])}, namespace="/web")
            await asyncio.sleep(1.0)
        flat = _flat_text(_interesting(received))
        assert OUTSIDE_XML_MARKER not in flat, f"foreign origin read an XML file: {flat[:500]}"
        assert not connected
    finally:
        await _disconnect(attacker)
        running.stop()
