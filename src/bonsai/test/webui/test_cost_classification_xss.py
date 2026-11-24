# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2022 Dion Moult <dion@thinkmoult.com>
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

"""Costing-page classification references must render as text.

A classification library is an IFC file a user loads. Its reference
Identification and Name are sent to the costing page and drawn in the
layered classification panel. Those strings must show up as text. Markup
in them must not become elements and must not run script.
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import ifcopenshell
import socketio
import websockets

REPO = Path(__file__).resolve().parents[4]
WEBUI = REPO / "src" / "bonsai" / "bonsai" / "bim" / "data" / "webui"
CLASSIFICATION_PY = REPO / "src" / "ifcopenshell-python" / "ifcopenshell" / "util" / "classification.py"
JQUERY = WEBUI / "static" / "js" / "jquery.min.js"
# Same file the Bonsai dev environment downloads for the costing page.
JQUERY_URL = "https://cdn.jsdelivr.net/npm/jquery@3.7.1/dist/jquery.min.js"

IDENTIFICATION_MARKUP = '<img src="x" id="xss-identification" onerror="window.__xssIdentification=1">'
NAME_MARKUP = '<img src="x" id="xss-name" onerror="window.__xssName=1">'
NESTED_MARKUP = '<img src="x" id="xss-nested" onerror="window.__xssNested=1">'
PLAIN_PARENT = "PARENT-REF"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _repo_classification():
    spec = spec_from_file_location("repo_classification_for_xss_test", CLASSIFICATION_PY)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _classification_library(path: Path) -> str:
    library = ifcopenshell.file(schema="IFC4")
    classification = library.create_entity("IfcClassification", Name="Shared library")
    library.create_entity(
        "IfcClassificationReference",
        Identification=IDENTIFICATION_MARKUP,
        Name="Plain name",
        ReferencedSource=classification,
    )
    library.create_entity(
        "IfcClassificationReference",
        Identification="PLAIN",
        Name=NAME_MARKUP,
        ReferencedSource=classification,
    )
    parent = library.create_entity(
        "IfcClassificationReference",
        Identification=PLAIN_PARENT,
        Name="Parent",
        ReferencedSource=classification,
    )
    library.create_entity(
        "IfcClassificationReference",
        Identification=NESTED_MARKUP,
        Name="Nested name",
        ReferencedSource=parent,
    )
    library.write(str(path))
    return str(path)


def _wire_payload(opened) -> dict:
    """Build the object the costing page reads from the classification event.

    tool/web.py copies get_classification_data() into this dictionary and
    sioserver.py forwards that dictionary as the event's data field.
    """
    classification_data, classification_name = _repo_classification().get_classification_data(opened)
    assert classification_data, "classification library produced no references"
    stored = []

    def collect(items):
        for item in items:
            stored.append(item["Identification"])
            stored.append(item["Name"])
            collect(item["references"])

    collect(classification_data)
    for markup in (IDENTIFICATION_MARKUP, NAME_MARKUP, NESTED_MARKUP):
        assert markup in stored, "reference text did not survive opening the library"
    return {
        "classification": {
            "classification_data": classification_data,
            "classification_name": classification_name,
            "cost_item_id": 1,
            "cost_classifications": [],
        }
    }


def _ensure_jquery() -> None:
    if JQUERY.is_file() and JQUERY.stat().st_size > 0:
        return
    JQUERY.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(JQUERY_URL, JQUERY)


def _wait_until(predicate, timeout: float, message: str):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.1)
    raise AssertionError(f"{message}. Last observation: {last!r}")


def _start_process(args, cwd) -> subprocess.Popen:
    return subprocess.Popen(
        args,
        cwd=cwd,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _stop_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait(timeout=5)


class _Page:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self._next_id = 1

    def evaluate(self, expression: str):
        result = asyncio.run(self._evaluate(expression))
        if "error" in result:
            raise AssertionError(result["error"])
        remote = result.get("result", {}).get("result", {})
        if remote.get("subtype") == "error":
            raise AssertionError(remote.get("description") or remote)
        return remote.get("value")

    async def _evaluate(self, expression: str):
        message_id = self._next_id
        self._next_id += 1
        async with websockets.connect(self.ws_url, max_size=8_000_000) as ws:
            await ws.send(
                json.dumps(
                    {
                        "id": message_id,
                        "method": "Runtime.evaluate",
                        "params": {"expression": expression, "returnByValue": True},
                    }
                )
            )
            while True:
                incoming = json.loads(await ws.recv())
                if incoming.get("id") == message_id:
                    return incoming


def _panel_state(page: _Page) -> dict:
    return page.evaluate(
        """
        (() => {
          const view = document.getElementById("classificationView");
          return {
            text: view ? view.textContent : "",
            imgs: view ? [...view.querySelectorAll("img")].map((element) => element.id) : [],
            xssIdentification: window.__xssIdentification || null,
            xssName: window.__xssName || null,
            xssNested: window.__xssNested || null,
          };
        })()
        """
    )


def _open_nested_level(page: _Page) -> None:
    clicked = page.evaluate(
        """
        (() => {
          const button = [...document.querySelectorAll("#classificationView button")]
            .find((candidate) => candidate.dataset.tooltip === "View");
          if (!button) return false;
          button.click();
          return true;
        })()
        """
    )
    assert clicked, "classification panel did not offer the nested reference level"


def test_classification_reference_text_is_not_html():
    _ensure_jquery()
    with tempfile.TemporaryDirectory() as tmp:
        library_path = _classification_library(Path(tmp) / "library.ifc")
        # Same call LoadClassificationLibrary uses to store the library.
        opened = ifcopenshell.open(library_path)
        payload = _wire_payload(opened)

    port = _free_port()
    server = _start_process(
        [sys.executable, "sioserver.py", "--host", "127.0.0.1", "--port", str(port)],
        WEBUI,
    )
    chrome = None
    client = None
    try:
        _wait_until(
            lambda: _http_ok(f"http://127.0.0.1:{port}/costing"),
            15,
            "costing page did not start",
        )

        chrome_port = _free_port()
        user_dir = tempfile.mkdtemp(prefix="cost-xss-chrome-")
        chrome = _start_process(
            [
                "google-chrome",
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--remote-debugging-port={chrome_port}",
                f"--user-data-dir={user_dir}",
                "about:blank",
            ],
            None,
        )
        _wait_until(
            lambda: _http_ok(f"http://127.0.0.1:{chrome_port}/json/version"),
            15,
            "Chrome DevTools did not start",
        )
        page_info = json.load(
            urllib.request.urlopen(
                urllib.request.Request(
                    f"http://127.0.0.1:{chrome_port}/json/new?http://127.0.0.1:{port}/costing",
                    method="PUT",
                )
            )
        )
        page = _Page(page_info["webSocketDebuggerUrl"])

        client = socketio.Client()
        client.connect(
            f"http://127.0.0.1:{port}",
            namespaces=["/blender"],
            transports=["websocket"],
        )

        def panel_ready():
            try:
                state = _panel_state(page)
            except Exception:
                return None
            if PLAIN_PARENT in state["text"]:
                return state
            return None

        # The page connects on load. Retry the event until that connection is up.
        def published():
            client.emit("classification", payload, namespace="/blender")
            return panel_ready()

        _wait_until(published, 20, "costing page did not draw the classification library")
        # Image error handlers run after the row is inserted. Read the panel
        # once those handlers have had a chance to run.
        time.sleep(0.5)
        top = _panel_state(page)
        _open_nested_level(page)

        def nested_ready():
            state = _panel_state(page)
            if "Nested name" in state["text"] or state["xssNested"]:
                return state
            return None

        _wait_until(nested_ready, 5, "nested classification reference was not drawn")
        time.sleep(0.5)
        nested = _panel_state(page)

        problems = []
        if top["xssIdentification"] or "xss-identification" in top["imgs"] or IDENTIFICATION_MARKUP not in top["text"]:
            problems.append(
                f"Identification was interpreted as HTML: flags={top['xssIdentification']!r} "
                f"imgs={top['imgs']!r} text={top['text']!r}"
            )
        if top["xssName"] or "xss-name" in top["imgs"] or NAME_MARKUP not in top["text"]:
            problems.append(
                f"Name was interpreted as HTML: flags={top['xssName']!r} imgs={top['imgs']!r} text={top['text']!r}"
            )
        if nested["xssNested"] or "xss-nested" in nested["imgs"] or NESTED_MARKUP not in nested["text"]:
            problems.append(
                f"nested Identification was interpreted as HTML: flags={nested['xssNested']!r} "
                f"imgs={nested['imgs']!r} text={nested['text']!r}"
            )
        assert not problems, "\n".join(problems)
    finally:
        if client is not None and client.connected:
            client.disconnect()
        _stop_process(chrome)
        _stop_process(server)


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            return 200 <= response.status < 500
    except Exception:
        return False
