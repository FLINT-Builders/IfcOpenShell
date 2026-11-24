# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026
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
#
# This file was generated with the assistance of an AI coding tool.

"""Pip Install must verify TLS for the package index and the wheel host.

The Debug panel copies the typed package name onto ``bim.pip_install``.
``PipInstall.execute`` then runs pip. These tests drive that path and require
the resulting install to reject an intercepted HTTPS server that presents a
certificate no trusted CA signed.

They fail while ``--trusted-host`` is passed for ``pypi.org`` or
``files.pythonhosted.org``, because pip then skips certificate verification
for those hosts and installs the intercepted distribution.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
import socket
import ssl
import subprocess
import sys
import textwrap
import threading
import types
import zipfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

PACKAGE_NAME = "bonsai-tls-canary"
WHEEL_NAME = "bonsai_tls_canary-1.0.0-py3-none-any.whl"
WHEEL_URL_PATH = f"/packages/py3/{WHEEL_NAME}"
INDEX_PATH = "/simple/bonsai-tls-canary/"
OPERATOR_PATH = Path(__file__).resolve().parents[2] / "bonsai" / "bim" / "module" / "debug" / "operator.py"
UI_PATH = Path(__file__).resolve().parents[2] / "bonsai" / "bim" / "module" / "debug" / "ui.py"

_ENV_KEYS = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
    "no_proxy",
    "NO_PROXY",
    "PIP_CONFIG_FILE",
    "PIP_NO_CACHE_DIR",
    "PIP_DISABLE_PIP_VERSION_CHECK",
    "PIP_CACHE_DIR",
    "PIP_TRUSTED_HOST",
    "PIP_INDEX_URL",
    "PIP_EXTRA_INDEX_URL",
    "PIP_CERT",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "SSL_CERT_FILE",
)


class _StubModule(types.ModuleType):
    def __getattr__(self, item: str):
        if item.startswith("__") and item.endswith("__"):
            raise AttributeError(item)
        value = MagicMock(name=f"{self.__name__}.{item}")
        setattr(self, item, value)
        return value


class _OperatorBase:
    def report(self, level, message) -> None:
        reports = getattr(self, "reports", [])
        reports.append((level, message))
        self.reports = reports


class _Layout:
    def __init__(self, sink: list) -> None:
        self.sink = sink

    def row(self, align: bool = False):
        return self

    def split(self, factor: float = 0.5, align: bool = False):
        return self

    def prop(self, *args, **kwargs):
        return None

    def label(self, **kwargs):
        return None

    def operator(self, operator_id: str, **kwargs):
        holder = types.SimpleNamespace(operator_id=operator_id)
        self.sink.append(holder)
        return holder


def _register_stub(name: str, created: dict[str, types.ModuleType | None]) -> _StubModule:
    module = sys.modules.get(name)
    if name not in created:
        created[name] = module if name in sys.modules else None
    if isinstance(module, _StubModule):
        return module
    stub = _StubModule(name)
    stub.__package__ = name
    stub.__path__ = []
    stub.__file__ = f"<stub {name}>"
    sys.modules[name] = stub
    if "." in name:
        parent_name, child = name.rsplit(".", 1)
        parent = _register_stub(parent_name, created)
        setattr(parent, child, stub)
    return stub


@contextmanager
def _import_stubs() -> Generator[None, None, None]:
    created: dict[str, types.ModuleType | None] = {}
    names = [
        "ifcopenshell",
        "ifcopenshell.api",
        "ifcopenshell.api.pset",
        "ifcopenshell.geom",
        "ifcopenshell.ifcopenshell_wrapper",
        "ifcopenshell.util",
        "ifcopenshell.util.element",
        "ifcopenshell.util.placement",
        "ifcopenshell.util.unit",
        "bonsai",
        "bonsai.bim",
        "bonsai.bim.handler",
        "bonsai.bim.import_ifc",
        "bonsai.bim.ifc",
        "bonsai.core",
        "bonsai.core.debug",
        "bonsai.core.profile",
        "bonsai.core.type",
        "bonsai.tool",
        "bpy_extras",
        "bpy_extras.io_utils",
    ]
    try:
        for name in names:
            _register_stub(name, created)
        bonsai = sys.modules["bonsai"]
        bonsai.format_debug_info = lambda *args, **kwargs: ""
        bonsai.get_debug_info = lambda *args, **kwargs: {}
        sys.modules["bonsai.tool"].Ifc = types.SimpleNamespace(Operator=type("Operator", (), {}))
        helpers = sys.modules["bpy_extras.io_utils"]
        helpers.ExportHelper = type("ExportHelper", (), {})
        helpers.ImportHelper = type("ImportHelper", (), {})

        bpy = types.ModuleType("bpy")
        bpy.__file__ = "<stub bpy>"
        bpy_types = types.ModuleType("bpy.types")
        bpy_types.Operator = _OperatorBase
        bpy_types.Panel = type("Panel", (), {})
        bpy_types.Context = object
        bpy_types.Mesh = object
        bpy.types = bpy_types
        bpy.props = MagicMock(name="bpy.props")
        bpy.app = types.SimpleNamespace(binary_path="", version=(4, 2, 0), version_string="4.2.0")
        bpy.context = types.SimpleNamespace(window_manager=types.SimpleNamespace(operator_properties_last=MagicMock()))
        bpy.ops = MagicMock(name="bpy.ops")
        bpy.data = MagicMock(name="bpy.data")
        created["bpy"] = sys.modules.get("bpy")
        created["bpy.types"] = sys.modules.get("bpy.types")
        sys.modules["bpy"] = bpy
        sys.modules["bpy.types"] = bpy_types
        yield
    finally:
        for name, previous in created.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_wheel() -> bytes:
    distribution = "bonsai_tls_canary-1.0.0"
    init_source = textwrap.dedent(
        """\
        import os

        marker = os.environ.get("BONSAI_TLS_CANARY_MARKER")
        if marker:
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write("imported-untrusted-package\\n")
        """
    ).encode()
    files = {
        "bonsai_tls_canary/__init__.py": init_source,
        "bonsai_tls_canary/payload.txt": b"untrusted-package-bytes\n",
        f"{distribution}.dist-info/METADATA": (b"Metadata-Version: 2.1\nName: bonsai-tls-canary\nVersion: 1.0.0\n"),
        f"{distribution}.dist-info/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: bonsai-tls-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }

    def record_digest(data: bytes) -> str:
        encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
        return f"sha256={encoded}"

    record_lines = [f"{path},{record_digest(data)},{len(data)}" for path, data in sorted(files.items())]
    record_lines.append(f"{distribution}.dist-info/RECORD,,")
    files[f"{distribution}.dist-info/RECORD"] = ("\n".join(record_lines) + "\n").encode()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _write_certificate(directory: Path) -> tuple[Path, Path]:
    key = directory / "intercept.key"
    cert = directory / "intercept.crt"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-days",
            "1",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=pypi.org",
            "-addext",
            "subjectAltName=DNS:pypi.org,DNS:files.pythonhosted.org",
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


def _read_http_message(sock: socket.socket, pending: bytes = b"") -> tuple[str, dict[str, str], bytes]:
    data = pending
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(8192)
        if not chunk:
            break
        data += chunk
        if len(data) > 1024 * 1024:
            break
    if b"\r\n\r\n" not in data:
        return "", {}, b""
    head, _, rest = data.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1", errors="replace").split("\r\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.lower()] = value.strip()
    return lines[0], headers, rest


class _InterceptProxy(threading.Thread):
    """HTTP proxy that terminates TLS with an untrusted certificate.

    Pip reaches it through ``https_proxy``. A CONNECT tunnel is answered with
    this process's certificate, then the simple index and wheel are served.
    """

    def __init__(self, certfile: Path, keyfile: Path, routes: dict[str, tuple[str, bytes]]) -> None:
        super().__init__(daemon=True)
        self.certfile = certfile
        self.keyfile = keyfile
        self.routes = routes
        self.requests: list[str] = []
        self.tls_results: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(32)
        self._listener.settimeout(0.2)
        self.port = self._listener.getsockname()[1]

    @property
    def proxy_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self._stopped.set()
        try:
            self._listener.close()
        except OSError:
            pass
        self.join(timeout=2)

    def run(self) -> None:
        while not self._stopped.is_set():
            try:
                connection, _address = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _record(self, request_line: str) -> None:
        with self._lock:
            self.requests.append(request_line)

    def _handle(self, connection: socket.socket) -> None:
        try:
            connection.settimeout(20)
            request, _headers, _rest = _read_http_message(connection)
            if not request:
                return
            self._record(request)
            parts = request.split(" ")
            if len(parts) < 2:
                return
            method, target = parts[0], parts[1]
            if method == "CONNECT":
                host = target.rsplit(":", 1)[0]
                connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(self.certfile, self.keyfile)
                try:
                    tls = context.wrap_socket(connection, server_side=True)
                except ssl.SSLError as exc:
                    with self._lock:
                        self.tls_results.append((host, f"rejected: {exc}"))
                    return
                with self._lock:
                    self.tls_results.append((host, "accepted"))
                self._serve(tls)
                return
            path = target.split("?", 1)[0]
            if target.startswith("http://") or target.startswith("https://"):
                path = target.split("?", 1)[0].split("/", 3)[-1]
                path = "/" + path if not path.startswith("/") else path
            self._send(connection, path)
        except OSError:
            return
        finally:
            try:
                connection.close()
            except OSError:
                pass

    def _serve(self, tls: ssl.SSLSocket) -> None:
        pending = b""
        try:
            tls.settimeout(20)
            while True:
                request, _headers, pending = _read_http_message(tls, pending)
                if not request:
                    return
                self._record(request)
                parts = request.split(" ")
                if len(parts) < 2:
                    return
                path = parts[1].split("?", 1)[0]
                self._send(tls, path)
                if pending:
                    continue
                return
        except OSError:
            return
        finally:
            try:
                tls.close()
            except OSError:
                pass

    def _send(self, sock: socket.socket, path: str) -> None:
        route = self.routes.get(path)
        if route is None and path.endswith("/") and path[:-1] in self.routes:
            route = self.routes[path[:-1]]
        if route is None and not path.endswith("/") and f"{path}/" in self.routes:
            route = self.routes[f"{path}/"]
        if route is None:
            body = b"not found"
            content_type = "text/plain"
            status = "404 Not Found"
        else:
            content_type, body = route
            status = "200 OK"
        header = (
            f"HTTP/1.1 {status}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode()
        sock.sendall(header + body)


def _is_bootstrap(argv: list[str]) -> bool:
    if "ensurepip" in argv:
        return True
    return "install" in argv and "--upgrade" in argv and argv[-1] == "pip"


def _strip_trusted_hosts(argv: list[str]) -> list[str]:
    stripped: list[str] = []
    skip_value = False
    for arg in argv:
        if skip_value:
            skip_value = False
            continue
        if arg == "--trusted-host":
            skip_value = True
            continue
        stripped.append(arg)
    return stripped


def _with_target(argv: list[str], target: Path) -> list[str]:
    replaced = False
    updated: list[str] = []
    for arg in argv:
        if arg.startswith("--target="):
            updated.append(f"--target={target}")
            replaced = True
        else:
            updated.append(arg)
    if not replaced:
        updated = updated[:4] + [f"--target={target}"] + updated[4:]
    return updated


def _installed_names(target: Path) -> list[str]:
    if not target.exists():
        return []
    return sorted(path.name for path in target.iterdir())


def _tls_failure(output: str) -> bool:
    lowered = output.lower()
    return "ssl" in lowered or "certificate" in lowered or "tls" in lowered


@contextmanager
def _proxy_env(proxy_url: str, cache_dir: Path) -> Generator[None, None, None]:
    previous = {key: os.environ.get(key) for key in _ENV_KEYS}
    os.environ["http_proxy"] = proxy_url
    os.environ["https_proxy"] = proxy_url
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ["no_proxy"] = ""
    os.environ["NO_PROXY"] = ""
    os.environ.pop("all_proxy", None)
    os.environ.pop("ALL_PROXY", None)
    # pip skips configuration files when PIP_CONFIG_FILE is os.devnull
    # (pip/_internal/configuration.py).
    os.environ["PIP_CONFIG_FILE"] = os.devnull
    os.environ["PIP_NO_CACHE_DIR"] = "true"
    os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    os.environ["PIP_CACHE_DIR"] = str(cache_dir)
    for key in (
        "PIP_TRUSTED_HOST",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_CERT",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "SSL_CERT_FILE",
    ):
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _run_pip(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


def test_pip_install_rejects_intercepted_index_and_wheel(tmp_path: Path) -> None:
    """A package typed into the Debug panel must not install over bad TLS.

    The intercepted server is the network attacker: it answers for the index
    host and the wheel host with a certificate that is not in the trust store,
    and it returns a wheel whose import writes a marker file.
    """
    wheel = _build_wheel()
    wheel_sha256 = hashlib.sha256(wheel).hexdigest()
    index = {
        "meta": {"api-version": "1.1"},
        "name": PACKAGE_NAME,
        "files": [
            {
                "filename": WHEEL_NAME,
                "url": f"https://files.pythonhosted.org{WHEEL_URL_PATH}",
                "hashes": {"sha256": wheel_sha256},
                "requires-python": ">=3.8",
            }
        ],
    }
    routes = {
        INDEX_PATH: ("application/vnd.pypi.simple.v1+json", json.dumps(index).encode()),
        WHEEL_URL_PATH: ("application/octet-stream", wheel),
    }
    cert, key = _write_certificate(tmp_path)
    proxy = _InterceptProxy(cert, key, routes)
    proxy.start()

    blender_root = tmp_path / "blender"
    site_packages = blender_root / "python" / "lib" / "site-packages"
    site_packages.mkdir(parents=True)
    control_target = tmp_path / "control-site-packages"
    control_target.mkdir()
    binary = blender_root / "blender"
    binary.write_text("")
    marker = tmp_path / "imported.txt"

    calls: list[list[str]] = []
    outcome: dict[str, subprocess.CompletedProcess[str]] = {}

    try:
        with _proxy_env(proxy.proxy_url, tmp_path / "pip-cache"), _import_stubs():
            operator_module = _load_module("bonsai_pip_install_operator_under_test", OPERATOR_PATH)
            ui_module = _load_module("bonsai_pip_install_ui_under_test", UI_PATH)
            props = types.SimpleNamespace(
                package_name=PACKAGE_NAME,
                express_file="",
                step_id=1,
                active_step_id=1,
                number_of_polygons=1000,
                percentile_of_polygons=90,
                display_type="BOUNDS",
                step_id_breadcrumb=[],
                attributes=[],
                inverse_attributes=[],
                inverse_references=[],
            )
            tool = sys.modules["bonsai.tool"]
            tool.Debug = types.SimpleNamespace(get_debug_props=lambda: props)
            tool.Blender = types.SimpleNamespace(get_bim_props=lambda: types.SimpleNamespace(ifc_file=""))
            panel = ui_module.BIM_PT_debug()
            # Panel.draw reads self.layout. The stub Panel does not implement Blender's
            # constructor, so the layout is attached directly.
            assignments: list = []
            panel.layout = _Layout(assignments)
            panel.draw(None)
            pip_buttons = [item for item in assignments if item.operator_id == "bim.pip_install"]
            assert pip_buttons, assignments
            assert pip_buttons[0].name == PACKAGE_NAME

            sys.modules["bpy"].app.binary_path = str(binary)
            sys.path.insert(0, str(site_packages))
            try:
                operator = operator_module.PipInstall()
                operator.name = pip_buttons[0].name
                original_call = operator_module.subprocess.call

                def call(argv, *args, **kwargs):
                    recorded = [str(arg) for arg in argv]
                    calls.append(recorded)
                    if _is_bootstrap(recorded):
                        return 0
                    completed = _run_pip(recorded)
                    outcome["install"] = completed
                    return completed.returncode

                operator_module.subprocess.call = call
                try:
                    result = operator.execute(None)
                finally:
                    operator_module.subprocess.call = original_call
            finally:
                sys.path.remove(str(site_packages))

            assert result == {"FINISHED"}
            install_commands = [argv for argv in calls if not _is_bootstrap(argv)]
            assert len(install_commands) == 1, calls
            install_argv = install_commands[0]
            assert PACKAGE_NAME in install_argv

            control = _run_pip(_with_target(_strip_trusted_hosts(install_argv), control_target))
    finally:
        proxy.stop()

    control_output = (control.stdout or "") + (control.stderr or "")
    assert control.returncode != 0 and _tls_failure(control_output), (
        "The intercepted certificate was accepted without --trusted-host, so this "
        f"fixture does not prove verification.\n{control_output}\nproxy={proxy.requests}\n"
        f"tls={proxy.tls_results}"
    )
    assert _installed_names(control_target) == []

    install = outcome["install"]
    install_output = (install.stdout or "") + (install.stderr or "")
    installed = _installed_names(site_packages)
    imported = False
    if any(name.startswith("bonsai_tls_canary") for name in installed):
        env = os.environ.copy()
        for key in _ENV_KEYS:
            env.pop(key, None)
        env["PYTHONPATH"] = str(site_packages)
        env["BONSAI_TLS_CANARY_MARKER"] = str(marker)
        subprocess.run(
            [sys.executable, "-c", "import bonsai_tls_canary"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        imported = marker.exists()

    assert install.returncode != 0, (
        "Pip Install accepted an intercepted package.\n"
        f"command={install_argv}\n"
        f"installed={installed}\n"
        f"import_executed={imported}\n"
        f"output={install_output}\n"
        f"proxy={proxy.requests}\n"
        f"tls={proxy.tls_results}"
    )
    assert installed == [], installed
    assert not marker.exists()
    assert _tls_failure(install_output), install_output
    assert all("--trusted-host" not in argv for argv in calls), calls
