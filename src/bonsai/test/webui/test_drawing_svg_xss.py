# This file was generated with the assistance of an AI coding tool.
# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 Bonsai contributors
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

"""Documentation-page drawing SVG must not run script in the web UI origin.

The page asks the web UI server for a drawing or sheet SVG and inserts the
returned markup with SVG.js. These tests drive that path: a Socket.IO client
plays the role of the browser only for the assertions below, while Chrome
loads the real documentation page, clicks the drawing or sheet, and records
whether the markup's event handler ran.

They fail while a handler in the returned SVG can run in the page and emit
``web_operator`` / ``get_svg`` on the page's socket. A fix passes them when
showing the drawing no longer runs that handler.

Run from the repository root:

    python -m pytest src/bonsai/test/webui/test_drawing_svg_xss.py -q -o addopts=

Requires the web UI's Python dependencies (aiohttp, python-socketio, pystache),
Google Chrome, and network access to the same script CDNs the documentation
template loads. jQuery 3.7.1 is downloaded into the gitignored static path
when that file is absent, matching ``src/bonsai/scripts/dev_environment.py``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import aiohttp
import pytest
import socketio

WEBUI = Path(__file__).resolve().parents[2] / "bonsai" / "bim" / "data" / "webui"
JQUERY = WEBUI / "static" / "js" / "jquery.min.js"
JQUERY_URL = "https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js"
# 1x1 PNG. process_svg rewrites a sibling image href and must still be covered.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
MARKER = "SECRET_MARKER"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_port(port: int, timeout: float = 10) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"nothing accepted connections on 127.0.0.1:{port}")


def _attacker_handler(secret_path: str) -> str:
    """XML-escaped handler. Ampersands are escaped so ElementTree accepts the file.

    ``socket`` is a top-level ``let`` in drawings.js, so the handler has to use
    that binding. ``io`` and ``SOCKET_PORT`` are also global and are the fallback
    when the handler runs in a same-origin frame that cannot see the binding.
    """
    return (
        "(function(){"
        "var w=window;"
        "try{if(parent&amp;&amp;parent!==window)w=parent;}catch(e){}"
        "w.__xssFired=true;"
        "try{"
        "var sock=null;"
        "if(typeof socket!=='undefined'&amp;&amp;socket&amp;&amp;socket.emit)sock=socket;"
        "if(!sock&amp;&amp;w.io&amp;&amp;w.SOCKET_PORT)sock=w.io('ws://localhost:'+w.SOCKET_PORT+'/web');"
        "if(sock&amp;&amp;sock.emit){"
        "var notice=function(data){ if(String(data).indexOf('%s')!==-1) w.__exfil=true; };"
        "if(sock._callbacks&amp;&amp;sock._callbacks.$svg_data)sock._callbacks.$svg_data.unshift(notice);"
        "else sock.on('svg_data', notice);"
        "sock.emit('get_svg', {path: '%s'});"
        "sock.emit('web_operator', {sourcePage:'cost', operator:{type:'deleteCostItem', costItemId:1}});"
        "}"
        "}catch(e){ w.__xssError=String(e); }"
        "})()"
    ) % (MARKER, secret_path)


def _write_project(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "dot.png").write_bytes(PNG)
    secret = root / "secret.svg"
    secret.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>%s</text></svg>' % MARKER)
    handler = _attacker_handler(secret.as_posix())
    files = {
        "set": (
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
            '<image xlink:href="dot.png"/>'
            f'<set attributeName="x" to="1" begin="0s" onbegin="{handler}"/>'
            "</svg>"
        ),
        "animate": (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            f'<animate attributeName="x" begin="0s" dur="0.1s" onbegin="{handler}" values="0;1"/>'
            "</svg>"
        ),
        "foreign": (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<foreignObject width="8" height="8">'
            f'<img src="x" onerror="{handler}"/>'
            "</foreignObject></svg>"
        ),
        "benign": ('<svg xmlns="http://www.w3.org/2000/svg"><rect id="benign-rect" width="10" height="10"/></svg>'),
    }
    paths = {}
    for name, text in files.items():
        path = root / f"{name}.svg"
        path.write_text(text)
        paths[name] = path
    return paths


def _ensure_jquery() -> None:
    if JQUERY.is_file() and JQUERY.stat().st_size > 0:
        return
    JQUERY.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(JQUERY_URL, JQUERY)


class DocumentationPage:
    """Real sioserver plus the documentation page in headless Chrome."""

    def __init__(self, project: Path):
        self.project = project
        self.paths = _write_project(project)
        self.events: list[dict] = []
        self._events_lock = threading.Lock()
        self.port = _free_port()
        self.debug_port = _free_port()
        self.server: subprocess.Popen | None = None
        self.chrome: subprocess.Popen | None = None
        self.loop = asyncio.new_event_loop()
        self.session_id = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._setup_error: BaseException | None = None

    def start(self) -> None:
        _ensure_jquery()
        if shutil.which("google-chrome") is None:
            raise RuntimeError("google-chrome is required")
        log_path = self.project / "sioserver.log"
        self._log = log_path.open("w")
        self.server = subprocess.Popen(
            [sys.executable, "sioserver.py", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=WEBUI,
            stdout=self._log,
            stderr=subprocess.STDOUT,
        )
        _wait_port(self.port)
        profile = self.project / "chrome-profile"
        self.chrome = subprocess.Popen(
            [
                "google-chrome",
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                f"--remote-debugging-port={self.debug_port}",
                f"--user-data-dir={profile}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_port(self.debug_port)
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=40):
            raise RuntimeError(f"documentation page did not become ready\n{self._server_log()}")
        if self._setup_error:
            raise self._setup_error

    def stop(self) -> None:
        if self.loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop)
            try:
                future.result(timeout=5)
            except Exception:
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        for proc in (self.chrome, self.server):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        if getattr(self, "_log", None):
            self._log.close()

    def show(self, kind: str, svg_path: Path) -> tuple[dict, list[dict]]:
        """Open one drawing or sheet through the page's click handler."""
        with self._events_lock:
            before = len(self.events)
        future = asyncio.run_coroutine_threadsafe(self._show(kind, svg_path), self.loop)
        result = future.result(timeout=30)
        time.sleep(0.3)
        with self._events_lock:
            fresh = list(self.events[before:])
        return result, fresh

    def _server_log(self) -> str:
        try:
            return (self.project / "sioserver.log").read_text()[-2000:]
        except OSError:
            return ""

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._setup())
        except BaseException as exc:
            self._setup_error = exc
            self._ready.set()
            return
        self._ready.set()
        self.loop.run_forever()

    async def _setup(self) -> None:
        self._http = aiohttp.ClientSession()
        self._blender = socketio.AsyncClient()

        @self._blender.on("web_operator", namespace="/blender")
        async def _on_operator(data):
            with self._events_lock:
                self.events.append(data)

        await self._blender.connect(
            f"http://127.0.0.1:{self.port}",
            namespaces=["/blender"],
            transports=["websocket"],
        )
        version = await (await self._http.get(f"http://127.0.0.1:{self.debug_port}/json/version")).json()
        self._ws = await self._http.ws_connect(version["webSocketDebuggerUrl"], max_msg_size=0)
        self._seq = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader = asyncio.create_task(self._read_cdp())
        created = await self._cdp("Target.createTarget", {"url": "about:blank"})
        attached = await self._cdp(
            "Target.attachToTarget",
            {"targetId": created["targetId"], "flatten": True},
        )
        self.session_id = attached["sessionId"]
        await self._cdp("Page.enable")
        await self._cdp("Runtime.enable")
        await self._cdp("Page.navigate", {"url": f"http://127.0.0.1:{self.port}/documentation"})
        deadline = time.time() + 20
        while time.time() < deadline:
            value = await self._eval("(typeof socket!=='undefined'&&socket&&socket.connected)===true")
            if value is True:
                return
            await asyncio.sleep(0.25)
        raise RuntimeError("documentation page socket did not connect")

    async def _shutdown(self) -> None:
        if getattr(self, "_reader", None):
            self._reader.cancel()
        if getattr(self, "_ws", None) and not self._ws.closed:
            await self._ws.close()
        if getattr(self, "_blender", None) and self._blender.connected:
            await self._blender.disconnect()
        if getattr(self, "_http", None) and not self._http.closed:
            await self._http.close()

    async def _read_cdp(self) -> None:
        async for msg in self._ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            future = self._pending.get(data.get("id"))
            if future is None or future.done():
                continue
            if "error" in data:
                future.set_exception(RuntimeError(str(data["error"])))
            else:
                future.set_result(data.get("result"))

    async def _cdp(self, method: str, params: dict | None = None) -> dict:
        self._seq += 1
        message = {"id": self._seq, "method": method, "params": params or {}}
        if self.session_id and not method.startswith("Target."):
            message["sessionId"] = self.session_id
        future: asyncio.Future = self.loop.create_future()
        self._pending[self._seq] = future
        await self._ws.send_json(message)
        return await future

    async def _eval(self, expression: str, await_promise: bool = False):
        result = await self._cdp(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": await_promise, "returnByValue": True},
        )
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            text = details.get("text") or details.get("exception", {}).get("description")
            raise RuntimeError(text or str(details))
        return result["result"].get("value")

    async def _show(self, kind: str, svg_path: Path) -> dict:
        list_key = "drawings" if kind == "drawing" else "sheets"
        element_id = f"{kind}-0"
        expression = """
        (async () => {
          window.__xssFired = false;
          window.__exfil = false;
          window.__xssError = null;
          const data = {blenderId: "b1", data: {ifc_file: "proj.ifc", drawings_data: {drawings: [], sheets: []}}};
          data.data.drawings_data[%s] = [{name: %s, path: %s}];
          handleDrawingsData(data);
          document.getElementById("dropdown-menu").value = "proj.ifc";
          displayDrawingsNames("b1", "proj.ifc");
          const li = document.getElementById(%s);
          if (!li) return {error: "missing drawing entry"};
          li.click();
          for (let i = 0; i < 20; i++) {
            await new Promise((resolve) => setTimeout(resolve, 100));
          }
          const box = document.getElementById("svg-container");
          return {
            fired: !!window.__xssFired,
            exfil: !!window.__exfil,
            error: window.__xssError,
            child: (box && box.innerHTML || "").slice(0, 180)
          };
        })()
        """ % (
            json.dumps(list_key),
            json.dumps(svg_path.name),
            json.dumps(svg_path.as_posix()),
            json.dumps(element_id),
        )
        return await self._eval(expression, await_promise=True)


def _cost_deletes(events: list[dict]) -> list[dict]:
    return [event for event in events if (event.get("operator") or {}).get("type") == "deleteCostItem"]


def _assert_inert(result: dict, events: list[dict]) -> None:
    problems = []
    if result.get("error"):
        problems.append(result["error"])
    if result.get("fired"):
        problems.append("handler ran in the documentation page")
    if result.get("exfil"):
        problems.append("handler read another local SVG back through get_svg")
    deletes = _cost_deletes(events)
    if deletes:
        problems.append(f"handler forwarded deleteCostItem: {deletes}")
    assert problems == [], problems


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    project = tmp_path_factory.mktemp("drawing-svg")
    ui = DocumentationPage(project)
    ui.start()
    try:
        yield ui
    finally:
        ui.stop()


def test_drawing_set_handler_does_not_run(page):
    """A set/onbegin handler must not run, including when an image href is rewritten."""
    result, events = page.show("drawing", page.paths["set"])
    _assert_inert(result, events)


def test_drawing_animate_handler_does_not_run(page):
    result, events = page.show("drawing", page.paths["animate"])
    _assert_inert(result, events)


def test_sheet_foreignobject_handler_does_not_run(page):
    result, events = page.show("sheet", page.paths["foreign"])
    _assert_inert(result, events)


def test_benign_drawing_still_renders(page):
    result, events = page.show("drawing", page.paths["benign"])
    assert not result.get("error"), result
    assert result["fired"] is False
    assert "<svg" in result["child"]
    assert _cost_deletes(events) == []
