# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 Dion Moult <dion@thinkmoult.com>
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

"""Cross-site access to the Bonsai IfcTester Socket.IO bridge.

`StartIfcTesterWebapp` listens on 127.0.0.1 and `audit_ids` returns JSON and
HTML reports for the IFC model open in Bonsai. These tests start that
operator and send an IDS document over Socket.IO the way another website
would. They fail while that website can read the model. They pass when all
of the following hold:

- The URL opened for the IfcTester webapp carries one secret of at least 16
  characters besides the `bonsai_server` port.
- A Socket.IO client receives the model report only when its Origin is that
  page's origin (`http://127.0.0.1:<webapp port>`) and its connection auth is
  `{"token": <that secret>}`.
- Any other Origin, including the websocket port's own origin and the
  literal origin `null`, receives none of the model's name, GlobalId, class,
  property value, or quantity. A missing token, a different token, and a
  token issued to another bridge are refused the same way.
- This is true for both Engine.IO transports the server enables, `websocket`
  and `polling`.

`GET /health` and `on_ping` are not disclosure operations: health returns a
fixed `OK` and ping echoes the caller's timestamp. The separate web UI
process in `bonsai/bim/data/webui/sioserver.py` is not covered.
"""

from __future__ import annotations

import asyncio
import importlib.util
import socket
import sys
import threading
import time
import types
import urllib.parse
from pathlib import Path

import aiohttp
import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.unit
import pytest
import socketio

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src" / "ifctester"))

import ifctester.ids  # noqa: E402

EVIL_ORIGIN = "http://evil.example"
WALL_NAME = "CLIENT-WALL-NAME-88421"
REFERENCE = "CLIENT-SECRET-REF-88421"
NET_VOLUME = 42.875
VOLUME_TEXT = "42.875"


def _ensure_module(name: str) -> types.ModuleType:
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    module = types.ModuleType(name)
    module.__path__ = []
    module.__package__ = name
    sys.modules[name] = module
    return module


def load_operator():
    """Import the real tester operator without starting Blender."""
    cached = sys.modules.get("bonsai.bim.module.tester.operator")
    if cached is not None and hasattr(cached, "StartIfcTesterWebapp"):
        return cached

    bpy = _ensure_module("bpy")
    bpy.types = _ensure_module("bpy.types")
    bpy.types.Operator = type("Operator", (), {})
    bpy.props = _ensure_module("bpy.props")
    bpy.props.IntProperty = lambda **kwargs: None
    bpy.props.StringProperty = lambda **kwargs: None
    bpy.utils = types.SimpleNamespace(user_resource=lambda *args, **kwargs: "/tmp")
    _ensure_module("bpy_extras")
    io_utils = _ensure_module("bpy_extras.io_utils")
    io_utils.ExportHelper = type("ExportHelper", (), {})

    _ensure_module("bonsai")
    _ensure_module("bonsai.bim")
    _ensure_module("bonsai.bim.module")
    _ensure_module("bonsai.bim.module.tester")
    sys.modules["bonsai.bim.handler"] = types.ModuleType("bonsai.bim.handler")
    tool = types.ModuleType("bonsai.tool")
    tool.Tester = type("Tester", (), {})
    tool.Ifc = type("Ifc", (), {})
    tool.Blender = type("Blender", (), {"get_bonsai_version": staticmethod(lambda: "0.0.0-test")})
    sys.modules["bonsai.tool"] = tool

    path = ROOT / "src" / "bonsai" / "bonsai" / "bim" / "module" / "tester" / "operator.py"
    spec = importlib.util.spec_from_file_location("bonsai.bim.module.tester.operator", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_model():
    model = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="Confidential Project")
    ifcopenshell.api.unit.assign_unit(model)
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name=WALL_NAME)
    pset = ifcopenshell.api.pset.add_pset(model, product=wall, name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(model, pset=pset, properties={"Reference": REFERENCE})
    qto = ifcopenshell.api.pset.add_qto(model, product=wall, name="Qto_WallBaseQuantities")
    ifcopenshell.api.pset.edit_qto(model, qto=qto, properties={"NetVolume": NET_VOLUME})
    secrets = (WALL_NAME, wall.GlobalId, "IfcWall", REFERENCE, VOLUME_TEXT)
    return model, secrets


def make_ids() -> str:
    specs = ifctester.ids.Ids(title="cross-site probe")
    specification = ifctester.ids.Specification(name="walls", ifcVersion=["IFC4"])
    specification.applicability.append(ifctester.ids.Entity(name="IFCWALL"))
    specification.requirements.append(ifctester.ids.Attribute(name="Name", value="NOT-THE-NAME"))
    specification.requirements.append(
        ifctester.ids.Property(propertySet="Pset_WallCommon", baseName="Reference", value="NOT-THE-REF")
    )
    specification.requirements.append(
        ifctester.ids.Property(propertySet="Qto_WallBaseQuantities", baseName="NetVolume", value="0")
    )
    specs.specifications.append(specification)
    xml = specs.to_string()
    for secret in (WALL_NAME, REFERENCE, VOLUME_TEXT):
        assert secret not in xml
    return xml


IDS_XML = make_ids()


class _Proc:
    def terminate(self):
        return None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        return None


class Bridge:
    def __init__(self, operator, props, opened, secrets):
        self.operator = operator
        self.props = props
        self.opened = opened
        self.secrets = secrets
        self.websocket_port = props.websocket_server_port
        self.webapp_port = props.webapp_server_port

    @property
    def url(self) -> str:
        assert self.opened, "StartIfcTesterWebapp did not open a browser URL"
        return self.opened[0]

    @property
    def webapp_origin(self) -> str:
        parsed = urllib.parse.urlparse(self.url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def session_secret(self) -> str | None:
        """Secret the opened webapp URL gives to the legitimate page."""
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.url).query)
        found = []
        for key, values in query.items():
            if key == "bonsai_server":
                continue
            for value in values:
                if value in {str(self.websocket_port), str(self.webapp_port)}:
                    continue
                if len(value) >= 16:
                    found.append(value)
        if len(found) != 1:
            return None
        return found[0]

    def stop(self):
        stopper = self.operator.StopIfcTesterWebapp()
        stopper.report = lambda *args, **kwargs: None
        try:
            stopper.execute(None)
        finally:
            self.operator.webapp_process = None
            self.operator.websocket_server_thread = None
            self.operator.websocket_app = None


def install_webapp_package() -> None:
    """Expose src/ifctester/webapp as ifctester.webapp.

    The wheel build copies that directory into the ifctester package. The
    source tree keeps it beside the package, which is where
    StartIfcTesterWebapp imports it from after installation.
    """
    import ifctester

    name = "ifctester.webapp"
    if name in sys.modules:
        return
    webapp = types.ModuleType(name)
    webapp.__path__ = [str(ROOT / "src" / "ifctester" / "webapp")]
    webapp.__package__ = name
    sys.modules[name] = webapp
    ifctester.webapp = webapp


def start_bridge(model, secrets) -> Bridge:
    install_webapp_package()
    operator = load_operator()
    operator.webapp_process = None
    operator.websocket_server_thread = None
    operator.websocket_app = None

    tool = sys.modules["bonsai.tool"]
    props = types.SimpleNamespace(webapp_server_port=0, websocket_server_port=0, webapp_is_running=False)
    tool.Tester.get_tester_props = staticmethod(lambda: props)
    tool.Ifc.get = staticmethod(lambda: model)
    tool.Blender.get_bonsai_version = staticmethod(lambda: "0.0.0-test")

    opened = []
    reports = []
    operator.webbrowser.open = opened.append
    operator.subprocess.Popen = lambda *args, **kwargs: _Proc()

    starter = operator.StartIfcTesterWebapp()
    starter.report = lambda level, message: reports.append((level, message))
    result = starter.execute(None)
    assert result == {"FINISHED"}, (result, reports)

    bridge = Bridge(operator, props, opened, secrets)
    asyncio.run(_wait_for_start(bridge))
    return bridge


async def _wait_for_start(bridge: Bridge):
    deadline = time.monotonic() + 5
    async with aiohttp.ClientSession() as session:
        while time.monotonic() < deadline:
            if bridge.opened:
                try:
                    async with session.get(
                        f"http://127.0.0.1:{bridge.websocket_port}/health",
                        headers={"Origin": EVIL_ORIGIN},
                        timeout=aiohttp.ClientTimeout(total=0.5),
                    ) as response:
                        if response.status == 200 and await response.text() == "OK":
                            return
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    pass
            await asyncio.sleep(0.05)
    raise AssertionError(
        f"IfcTester bridge did not become reachable (url={bridge.opened!r}, port={bridge.websocket_port})"
    )


def disclosed(blob: str, secrets) -> list[str]:
    return [secret for secret in secrets if secret in blob]


async def audit(port: int, *, origin: str, auth, transport: str) -> str:
    """Perform the attack's handshake and IDS audit. Return every payload observed."""
    client = socketio.AsyncClient(reconnection=False, logger=False, engineio_logger=False)
    received: list[str] = []

    @client.on("audit_result", namespace="/ifctester")
    async def on_result(data):
        received.append(str(data))

    @client.on("error", namespace="/ifctester")
    async def on_error(data):
        received.append(str(data))

    @client.on("status", namespace="/ifctester")
    async def on_status(data):
        received.append(str(data))

    connected = False
    try:
        await client.connect(
            f"http://127.0.0.1:{port}",
            headers={"Origin": origin},
            auth=auth,
            namespaces=["/ifctester"],
            transports=[transport],
            wait_timeout=5,
        )
        connected = True
        await client.emit("audit_ids", {"id": "cross-site-1", "ids": IDS_XML}, namespace="/ifctester")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if any("cross-site-1" in item or "json_report" in item or "html_report" in item for item in received):
                break
            await asyncio.sleep(0.05)
    except socketio.exceptions.ConnectionError as exc:
        received.append(f"connection refused: {exc}")
    finally:
        if connected:
            await client.disconnect()
    return "\n".join(received)


def run_audit(port: int, *, origin: str, auth, transport: str) -> str:
    return asyncio.run(audit(port, origin=origin, auth=auth, transport=transport))


@pytest.fixture
def bridge():
    model, secrets = make_model()
    started = start_bridge(model, secrets)
    try:
        yield started
    finally:
        started.stop()


def test_health_is_reachable_and_does_not_contain_the_model(bridge):
    """Port discovery must not itself be treated as the disclosure."""

    async def fetch():
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://127.0.0.1:{bridge.websocket_port}/health",
                headers={"Origin": EVIL_ORIGIN},
            ) as response:
                return response.status, await response.text()

    status, body = asyncio.run(fetch())
    assert status == 200
    assert body == "OK"
    assert disclosed(body, bridge.secrets) == []


@pytest.mark.parametrize("transport", ["websocket", "polling"])
def test_foreign_origin_audit_does_not_disclose_the_open_model(bridge, transport):
    blob = run_audit(bridge.websocket_port, origin=EVIL_ORIGIN, auth=None, transport=transport)
    leaked = disclosed(blob, bridge.secrets)
    assert leaked == [], f"{transport} client from {EVIL_ORIGIN} received the open model: {leaked}"


def test_null_origin_audit_does_not_disclose_the_open_model(bridge):
    blob = run_audit(bridge.websocket_port, origin="null", auth=None, transport="websocket")
    leaked = disclosed(blob, bridge.secrets)
    assert leaked == [], f"client with Origin null received the open model: {leaked}"


def test_websocket_port_origin_audit_does_not_disclose_the_open_model(bridge):
    origin = f"http://127.0.0.1:{bridge.websocket_port}"
    assert origin != bridge.webapp_origin
    blob = run_audit(bridge.websocket_port, origin=origin, auth=None, transport="websocket")
    leaked = disclosed(blob, bridge.secrets)
    assert leaked == [], f"client at the bridge's own origin received the open model: {leaked}"


def test_webapp_origin_without_token_does_not_disclose_the_open_model(bridge):
    blob = run_audit(bridge.websocket_port, origin=bridge.webapp_origin, auth=None, transport="websocket")
    leaked = disclosed(blob, bridge.secrets)
    assert leaked == [], f"webapp origin without a session token received the open model: {leaked}"


def test_url_secret_from_another_origin_does_not_disclose_the_open_model(bridge):
    secret = bridge.session_secret()
    auth = {"token": secret} if secret else None
    blob = run_audit(bridge.websocket_port, origin=EVIL_ORIGIN, auth=auth, transport="websocket")
    leaked = disclosed(blob, bridge.secrets)
    assert leaked == [], f"evil origin presenting the URL secret received the open model: {leaked}"


def test_wrong_token_does_not_disclose_the_open_model(bridge):
    secret = bridge.session_secret()
    assert secret, (
        "the URL opened by StartIfcTesterWebapp must carry a session secret; "
        f"opened {bridge.url}"
    )
    wrong = "0" * len(secret)
    if wrong == secret:
        wrong = "1" * len(secret)
    blob = run_audit(
        bridge.websocket_port,
        origin=bridge.webapp_origin,
        auth={"token": wrong},
        transport="websocket",
    )
    leaked = disclosed(blob, bridge.secrets)
    assert leaked == [], f"webapp origin with a different token received the open model: {leaked}"


def test_other_bridge_secret_does_not_disclose_this_model(bridge):
    """A secret issued for one bridge must not authorize a different bridge."""
    operator = bridge.operator
    other_port_socket = socket.socket()
    other_port_socket.bind(("127.0.0.1", 0))
    other_port = other_port_socket.getsockname()[1]
    other_port_socket.close()

    other = operator.IfcTesterWebSocketServer(other_port)
    # Use this bridge's own allowed origin when it publishes one, so the
    # request is rejected for carrying the other bridge's secret.
    origin = getattr(other, "allowed_origin", None) or bridge.webapp_origin

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(other.start_server())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        ready = False
        while time.monotonic() < deadline:
            try:
                asyncio.run(_probe(other_port))
                ready = True
                break
            except (aiohttp.ClientError, AssertionError, OSError):
                time.sleep(0.05)
        assert ready, "second IfcTester bridge did not start"

        secret = bridge.session_secret()
        other_secret = getattr(other, "session_token", None)
        if isinstance(other_secret, str) and secret:
            assert other_secret != secret, "each bridge must issue its own session secret"
        auth = {"token": secret} if secret else None
        blob = run_audit(other_port, origin=origin, auth=auth, transport="websocket")
        leaked = disclosed(blob, bridge.secrets)
        assert leaked == [], f"another bridge accepted this bridge's secret and returned the model: {leaked}"
    finally:
        other.stop_server()
        thread.join(timeout=5)


async def _probe(port: int):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"http://127.0.0.1:{port}/health",
            timeout=aiohttp.ClientTimeout(total=0.5),
        ) as response:
            assert response.status == 200


def test_authorized_webapp_receives_the_open_model(bridge):
    secret = bridge.session_secret()
    assert secret, (
        "StartIfcTesterWebapp must open a URL that carries the session secret "
        f"the bridge will require; opened {bridge.url}"
    )
    blob = run_audit(
        bridge.websocket_port,
        origin=bridge.webapp_origin,
        auth={"token": secret},
        transport="websocket",
    )
    missing = [secret_value for secret_value in bridge.secrets if secret_value not in blob]
    assert missing == [], f"the webapp session did not receive the open model fields: {missing}"
