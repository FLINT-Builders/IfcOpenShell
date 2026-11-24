# This file was generated with the assistance of an AI coding tool.
"""The Bonsai release recipe must not pack or run moving third-party branches.

``make dist`` (the recipe both Publish Bonsai workflows run) currently
downloads bpypolyskel, IFC2JSON, jsgantt, Brick.ttl, and bonsai-translations
from a branch, a default HEAD, or a nightly tag, with no commit pin and no
checksum. These tests rebuild that recipe against local stand-ins of those
URLs.

They fail while those bytes are left in the package tree or execute on import.
They pass once each of those inputs is taken from an immutable commit and a
checksum recorded in the repository rejects any other bytes before those bytes
are placed in the package tree.

Not covered here, because they are not this branch-tip path:
- ``scripts/dev_environment.py`` repeats the jsgantt and Brick URLs, but only
  as an interactive developer setup step.
- ``pyproject.toml`` lists the same git URLs for the type-check extra, which
  is not part of the release zip.
- The jquery 3.7.1 CDN URL and the ifcmerge release tag are version-pinned.
- The other ``pip download`` lines float on PyPI and are not branch URLs.
- ``publish-bonsai-releases.py`` uploads an already built release asset.

Run from a checkout of this commit:

    cd src/bonsai && python3 -m pytest -o addopts= test/packaging/test_unpinned_release_inputs.py
"""

from __future__ import annotations

import os
import re
import select
import shutil
import socket
import ssl
import subprocess
import textwrap
import threading
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
BONSAI_DIR = REPO_ROOT / "src" / "bonsai"
SYSTEM_CA = Path("/etc/ssl/certs/ca-certificates.crt")

# Bytes that exist only on the moving tip of each stand-in. A pinned commit
# in the stand-in does not contain these, and a checksum mismatch must not
# leave them under the package tree.
MARKERS = (
    b"BPYPOLYSKEL_UNPINNED_BRANCH_TIP",
    b"IFCJSON_UNPINNED_BRANCH_TIP",
    b"JSGANTT_JS_UNPINNED_BRANCH_TIP",
    b"JSGANTT_CSS_UNPINNED_BRANCH_TIP",
    b"BRICK_NIGHTLY_UNPINNED_TIP",
    b"TRANSLATIONS_UNPINNED_BRANCH_TIP",
    b"UNPINNED_HTTP_BODY",
)
SHA_IN_PATH = re.compile(r"(?:^|/)([0-9a-fA-F]{40})(?:/|$)")
TUNNEL_HOSTS = {
    "pypi.org",
    "files.pythonhosted.org",
    "pypi.python.org",
    "bootstrap.pypa.io",
}
# Lines from `make -n dist` that fetch the moving inputs named above.
FETCH_TOKENS = (
    "jsgantt.js",
    "jsgantt.css",
    "Brick.ttl",
    "bpypolyskel",
    "IFC2JSON",
    "bonsai-translations",
)
SETUP_LINES = {
    "rm -rf build",
    "mkdir -p build",
    "mkdir -p dist",
    "cp -r bonsai build/",
    "mkdir -p build/wheels",
}
PACKAGING_SNIPPETS = (
    "bonsai_translations.py",
    "rm -rf build/working",
    "cp pyproject.toml build/",
    "python3 -m build",
    "cp build/dist/",
    "mv build/wheels/",
    "get_wheels.py",
    "rm -rf build/bonsai/bim/",
    "rm -rf build/bonsai/core/",
    "rm -rf build/bonsai/tool/",
    "rm -rf build/bonsai/libs/",
    "zip -r bonsai_",
    "mv build/bonsai",
)


def _run(
    cmd: list[str], cwd: Path, env: dict[str, str] | None = None, timeout: int = 180
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )


def _git(repo: Path, *args: str) -> None:
    result = _run(["git", *args], repo)
    if result.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {result.stdout}")


def _write_repo(path: Path, branch: str, commits: list[dict[str, str]]) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", branch)
    _git(path, "config", "user.email", "release-input-test@example.com")
    _git(path, "config", "user.name", "release-input-test")
    for files in commits:
        for rel, content in files.items():
            destination = path / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content)
        _git(path, "add", "-A")
        _git(path, "commit", "-qm", "snapshot")


def _pyproject(name: str) -> str:
    return textwrap.dedent(
        f"""\
        [build-system]
        requires = ["setuptools>=61"]
        build-backend = "setuptools.build_meta"

        [project]
        name = "{name}"
        version = "9.9.9"

        [tool.setuptools.packages.find]
        include = ["{name}*"]
        """
    )


def _python_package(name: str, marker: str, sentinel_line: str, malicious: bool) -> dict[str, str]:
    if malicious:
        init = textwrap.dedent(
            f"""\
            import os

            _sentinel = os.environ.get("UNPINNED_INPUT_SENTINEL")
            if _sentinel:
                with open(_sentinel, "a", encoding="utf-8") as handle:
                    handle.write({sentinel_line!r})
            MARKER = {marker!r}
            """
        )
    else:
        init = f"MARKER = {marker!r}\n"
    files = {
        "pyproject.toml": _pyproject(name),
        f"{name}/__init__.py": init,
    }
    if name == "bpypolyskel":
        files["bpypolyskel/bpypolyskel.py"] = "SKELETON = 'straight'\n"
    return files


def _make_standins(root: Path) -> dict[str, str]:
    """Local repos whose default-branch tip is attacker-controlled."""
    bpypolyskel = root / "bpypolyskel"
    ifcjson = root / "ifcjson"
    translations = root / "translations"
    _write_repo(
        bpypolyskel,
        "main",
        [
            _python_package("bpypolyskel", "BPYPOLYSKEL_PINNED_COMMIT", "bpypolyskel\n", False),
            _python_package("bpypolyskel", "BPYPOLYSKEL_UNPINNED_BRANCH_TIP", "bpypolyskel\n", True),
        ],
    )
    _write_repo(
        ifcjson,
        "main",
        [
            _python_package("ifcjson", "IFCJSON_PINNED_COMMIT", "ifcjson\n", False),
            _python_package("ifcjson", "IFCJSON_UNPINNED_BRANCH_TIP", "ifcjson\n", True),
        ],
    )
    _write_repo(
        translations,
        "main",
        [
            {"en.po": 'msgid "hello"\nmsgstr "TRANSLATIONS_PINNED_COMMIT"\n'},
            {"en.po": 'msgid "hello"\nmsgstr "TRANSLATIONS_UNPINNED_BRANCH_TIP"\n'},
        ],
    )
    return {
        "https://github.com/prochitecture/bpypolyskel": str(bpypolyskel),
        "https://github.com/IfcOpenShell/IFC2JSON_python.git": str(ifcjson),
        "https://github.com/IfcOpenShell/bonsai-translations.git": str(translations),
    }


def _openssl(args: list[str], cwd: Path) -> None:
    result = _run(["openssl", *args], cwd)
    if result.returncode != 0:
        raise RuntimeError(result.stdout)


def _certificate_authority(directory: Path) -> tuple[Path, Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    key = directory / "ca.key"
    cert = directory / "ca.crt"
    bundle = directory / "ca-bundle.crt"
    _openssl(
        [
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=Release input test CA",
        ],
        directory,
    )
    bundle.write_bytes(SYSTEM_CA.read_bytes() + b"\n" + cert.read_bytes())
    return key, cert, bundle


def _host_certificate(directory: Path, ca_key: Path, ca_cert: Path, host: str) -> tuple[Path, Path]:
    safe = re.sub(r"[^A-Za-z0-9.-]", "_", host)
    key = directory / f"{safe}.key"
    csr = directory / f"{safe}.csr"
    cert = directory / f"{safe}.crt"
    ext = directory / f"{safe}.ext"
    if not key.exists():
        _openssl(
            ["req", "-newkey", "rsa:2048", "-keyout", str(key), "-out", str(csr), "-nodes", "-subj", f"/CN={host}"],
            directory,
        )
        ext.write_text(f"subjectAltName=DNS:{host}\n")
        _openssl(
            [
                "x509",
                "-req",
                "-in",
                str(csr),
                "-CA",
                str(ca_cert),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(cert),
                "-days",
                "1",
                "-extfile",
                str(ext),
            ],
            directory,
        )
    return cert, key


class _InterceptProxy:
    """HTTPS proxy. PyPI is tunneled; every other host is answered locally.

    wget and pip both honor ``https_proxy``. The Makefile does not clear it,
    so the recipe lines keep the URLs they were expanded with.
    """

    def __init__(self, cert_dir: Path, ca_key: Path, ca_cert: Path, mode: str) -> None:
        self.cert_dir = cert_dir
        self.ca_key = ca_key
        self.ca_cert = ca_cert
        self.mode = mode
        self.requests: list[str] = []
        self._contexts: dict[str, ssl.SSLContext] = {}
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(64)
        self.port = self._socket.getsockname()[1]
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def body_for(self, path: str) -> bytes:
        pinned = self.mode == "branch" and SHA_IN_PATH.search(path) is not None
        if pinned:
            return f"PINNED_OK_NOT_A_BRANCH_TIP {path}\n".encode()
        if path.endswith("jsgantt.js"):
            return (
                b"const fs = require('fs');\n"
                b"const sentinel = process.env.UNPINNED_INPUT_SENTINEL;\n"
                b"if (sentinel) fs.appendFileSync(sentinel, 'jsgantt.js\\n');\n"
                b"var JSGANTT_JS_UNPINNED_BRANCH_TIP = true;\n"
            )
        if path.endswith("jsgantt.css"):
            return b"/* JSGANTT_CSS_UNPINNED_BRANCH_TIP */\n"
        if path.endswith("Brick.ttl"):
            return b"# BRICK_NIGHTLY_UNPINNED_TIP\n"
        return f"UNPINNED_HTTP_BODY {path}\n".encode()

    def _context_for(self, host: str) -> ssl.SSLContext:
        context = self._contexts.get(host)
        if context is None:
            cert, key = _host_certificate(self.cert_dir, self.ca_key, self.ca_cert, host)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            self._contexts[host] = context
        return context

    def _accept_loop(self) -> None:
        while True:
            try:
                connection, _address = self._socket.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _read_headers(self, connection: socket.socket | ssl.SSLSocket, buffered: bytes = b"") -> tuple[bytes, bytes]:
        data = buffered
        while b"\r\n\r\n" not in data:
            chunk = connection.recv(65536)
            if not chunk:
                break
            data += chunk
        if b"\r\n\r\n" not in data:
            return data, b""
        head, rest = data.split(b"\r\n\r\n", 1)
        return head, rest

    def _tunnel(self, client: socket.socket, host: str, port: int, rest: bytes) -> None:
        remote = socket.create_connection((host, port), timeout=30)
        client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        if rest:
            remote.sendall(rest)
        sockets = [client, remote]
        try:
            while True:
                readable, _, _ = select.select(sockets, [], [], 60)
                if not readable:
                    break
                for current in readable:
                    other = remote if current is client else client
                    data = current.recv(65536)
                    if not data:
                        return
                    other.sendall(data)
        finally:
            remote.close()

    def _handle(self, connection: socket.socket) -> None:
        try:
            head, rest = self._read_headers(connection)
            if not head:
                return
            request = head.split(b"\r\n", 1)[0].decode("ascii", "replace")
            parts = request.split()
            if len(parts) < 2 or parts[0] != "CONNECT":
                connection.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                return
            host, port_text = parts[1].rsplit(":", 1)
            port = int(port_text)
            if host in TUNNEL_HOSTS:
                self._tunnel(connection, host, port, rest)
                return
            connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            tls = self._context_for(host).wrap_socket(connection, server_side=True)
            try:
                request_head, _rest = self._read_headers(tls, rest if False else b"")
                path = "/"
                if request_head:
                    request_line = request_head.split(b"\r\n", 1)[0].decode("ascii", "replace")
                    request_parts = request_line.split()
                    if len(request_parts) >= 2:
                        path = request_parts[1]
                self.requests.append(f"https://{host}{path}")
                body = self.body_for(path)
                header = (f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode()
                tls.sendall(header + body)
            finally:
                tls.close()
                return
        except Exception:
            return
        finally:
            try:
                connection.close()
            except OSError:
                pass

    def close(self) -> None:
        self._socket.close()


def _expanded_recipe(extra_make_args: list[str] | None = None) -> list[str]:
    result = _run(
        ["make", "-n", "dist", "PLATFORM=linux", "PYVERSION=py311", *(extra_make_args or [])], BONSAI_DIR, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout)
    lines = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("make["):
            continue
        lines.append(line)
    return lines


def _commands_to_run(lines: list[str]) -> list[str]:
    selected = []
    for line in lines:
        if (
            line in SETUP_LINES
            or "python3 -m venv" in line
            or "pip3 install build" in line
            or "pip3 install wheel" in line
        ):
            selected.append(line)
            continue
        if any(token in line for token in FETCH_TOKENS):
            selected.append(line)
            continue
        if any(token in line for token in PACKAGING_SNIPPETS):
            selected.append(line)
    return selected


def _copy_sources(destination: Path) -> None:
    shutil.copytree(BONSAI_DIR / "bonsai", destination / "bonsai", symlinks=True)
    shutil.copy(BONSAI_DIR / "pyproject.toml", destination / "pyproject.toml")
    scripts = destination / "scripts"
    scripts.mkdir()
    shutil.copy(BONSAI_DIR / "scripts" / "get_wheels.py", scripts / "get_wheels.py")
    shutil.copy(BONSAI_DIR / "scripts" / "bonsai_translations.py", scripts / "bonsai_translations.py")


def _walk_archives(path: Path, prefix: str = "") -> list[tuple[str, bytes]]:
    found: list[tuple[str, bytes]] = []
    if path.is_file() and path.suffix in {".zip", ".whl"}:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                data = archive.read(info)
                name = f"{prefix}{path.name}:{info.filename}"
                found.append((name, data))
                if info.filename.endswith(".whl"):
                    nested = path.parent / f".nested-{info.filename.replace('/', '_')}"
                    nested.write_bytes(data)
                    found.extend(_walk_archives(nested, prefix=name + ":"))
                    nested.unlink()
        return found
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_file() and "env/" not in child.as_posix() and "/env/" not in child.as_posix():
                if child.suffix in {".zip", ".whl"}:
                    found.extend(_walk_archives(child, prefix=prefix))
                else:
                    found.append((str(child), child.read_bytes()))
    return found


def _marker_hits(paths: list[Path]) -> list[str]:
    hits = []
    for path in paths:
        if not path.exists():
            continue
        for name, data in _walk_archives(path):
            for marker in MARKERS:
                if marker in data:
                    hits.append(f"{marker.decode()} in {name}")
    return hits


def _execute_packed_code(work: Path, sentinel: Path) -> str:
    """Import the packed modules the add-on imports, and run the packed script."""
    wheels = list((work / "build" / "bonsai" / "wheels").glob("*.whl")) + list(
        (work / "build" / "wheels").glob("*.whl")
    )
    site = work / "site-packages"
    site.mkdir(exist_ok=True)
    roof_path = ""
    jsgantt_path = ""
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            if any(name.startswith("bpypolyskel/") or name.startswith("ifcjson/") for name in names):
                archive.extractall(site)
            if "bonsai/bim/module/model/roof.py" in names and not roof_path:
                extract = work / "bonsai-wheel"
                archive.extractall(extract)
                roof_path = str(extract / "bonsai/bim/module/model/roof.py")
                candidate = extract / "bonsai/bim/data/gantt/jsgantt.js"
                if candidate.exists():
                    jsgantt_path = str(candidate)
                webui = extract / "bonsai/bim/data/webui"
                if (webui / "sioserver.py").exists() and candidate.exists():
                    _serve_gantt(work, webui, sentinel)
    env = os.environ.copy()
    env["UNPINNED_INPUT_SENTINEL"] = str(sentinel)
    env.pop("https_proxy", None)
    env.pop("http_proxy", None)
    script = textwrap.dedent(
        f"""\
        import importlib.util
        import sys
        import types

        sys.path.insert(0, {str(site)!r})
        stubs = [
            "bpy",
            "bmesh",
            "mathutils",
            "shapely",
            "ifcopenshell",
            "ifcopenshell.api",
            "ifcopenshell.api.pset",
            "ifcopenshell.util",
            "ifcopenshell.util.representation",
            "ifcopenshell.util.unit",
            "bonsai",
            "bonsai.core",
            "bonsai.core.root",
            "bonsai.tool",
            "bonsai.bim",
            "bonsai.bim.module",
            "bonsai.bim.module.drawing",
            "bonsai.bim.module.drawing.gizmos",
            "bonsai.bim.module.model",
            "bonsai.bim.module.model.data",
            "bonsai.bim.module.model.decorator",
            "bonsai.bim.parametric_lifecycle",
        ]
        for name in stubs:
            module = types.ModuleType(name)
            module.__path__ = []
            sys.modules[name] = module
        sys.modules["bonsai.bim.module.drawing.gizmos"].DimensionGizmoConfig = object
        sys.modules["bonsai.bim.module.drawing.gizmos"].IconSlot = object
        sys.modules["mathutils"].Quaternion = object
        sys.modules["mathutils"].Vector = object
        if {roof_path!r}:
            spec = importlib.util.spec_from_file_location("packed_roof", {roof_path!r})
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception as exc:
                print("ROOF_EXC", type(exc).__name__, exc)
        try:
            import ifcjson
            print("IFCJSON", ifcjson.__file__)
        except Exception as exc:
            print("IFCJSON_EXC", type(exc).__name__, exc)
        """
    )
    result = _run([sys_executable(), "-c", script], work, env=env)
    notes = result.stdout
    if jsgantt_path:
        node = _run(["node", jsgantt_path], work, env=env)
        notes += "\n" + node.stdout
    return notes


def sys_executable() -> str:
    return os.environ.get("PYTHON", "python3")


def _serve_gantt(work: Path, webui: Path, sentinel: Path) -> None:
    """Exercise sioserver's sequencing page and the static route it registers."""
    script = textwrap.dedent(
        """\
        import asyncio
        import importlib.util
        import os

        os.chdir(os.environ["WEBUI"])
        spec = importlib.util.spec_from_file_location("sioserver", os.path.join(os.environ["WEBUI"], "sioserver.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from aiohttp.test_utils import TestClient, TestServer

        async def main():
            async with TestClient(TestServer(module.app)) as client:
                script_response = await client.get("/jsgantt/jsgantt.js")
                script_body = (await script_response.read()).decode("utf-8", "replace")
                page = await client.get("/sequencing")
                html = await page.text()
                print("JS_STATUS", script_response.status)
                print("JS_HAS_BRANCH_TIP", "JSGANTT_JS_UNPINNED_BRANCH_TIP" in script_body)
                print("HTML_STATUS", page.status)
                print("HTML_LOADS_JSGANTT", "./jsgantt/jsgantt.js" in html)

        asyncio.run(main())
        """
    )
    env = os.environ.copy()
    env["WEBUI"] = str(webui)
    env["UNPINNED_INPUT_SENTINEL"] = str(sentinel)
    log = work / "sioserver.log"
    result = _run([sys_executable(), "-c", script], webui, env=env)
    log.write_text(result.stdout)


def _build(work: Path, mode: str) -> dict[str, object]:
    standins = work / "standins"
    certs = work / "certs"
    sources = work / "src"
    _copy_sources(sources)
    mapping = _make_standins(standins)
    ca_key, ca_cert, bundle = _certificate_authority(certs)
    proxy = _InterceptProxy(certs, ca_key, ca_cert, mode)
    env = os.environ.copy()
    env["https_proxy"] = f"http://127.0.0.1:{proxy.port}"
    env["http_proxy"] = env["https_proxy"]
    env["SSL_CERT_FILE"] = str(bundle)
    env["REQUESTS_CA_BUNDLE"] = str(bundle)
    env["CURL_CA_BUNDLE"] = str(bundle)
    env["GIT_SSL_CAINFO"] = str(bundle)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    count = 0
    for prefix, target in mapping.items():
        env[f"GIT_CONFIG_KEY_{count}"] = f"url.{target}/.insteadof"
        env[f"GIT_CONFIG_VALUE_{count}"] = prefix
        count += 1
    env["GIT_CONFIG_COUNT"] = str(count)

    recipe = _expanded_recipe()
    stable = _expanded_recipe(["IS_STABLE=TRUE"])
    commands = _commands_to_run(recipe)
    log_lines = []
    try:
        for command in commands:
            if command == "rm -rf build" and any((sources / "dist").glob("*.zip")):
                continue
            result = _run(["sh", "-c", command], sources, env=env, timeout=300)
            log_lines.append(f"$ {command}\nexit {result.returncode}\n{result.stdout[-2000:]}")
            if result.returncode != 0:
                break
    finally:
        proxy.close()

    sentinel = work / "sentinel.txt"
    execution = _execute_packed_code(sources, sentinel)
    hits = _marker_hits(
        [sources / "build" / "bonsai", sources / "build" / "wheels", sources / "build" / "dist", sources / "dist"]
    )
    return {
        "hits": hits,
        "sentinel": sentinel.read_text() if sentinel.exists() else "",
        "execution": execution,
        "requests": list(proxy.requests),
        "log": "\n".join(log_lines),
        "recipe_fetch": [line for line in recipe if any(token in line for token in FETCH_TOKENS)],
        "stable_fetch": [line for line in stable if any(token in line for token in FETCH_TOKENS)],
        "served": (sources / "sioserver.log").read_text() if (sources / "sioserver.log").exists() else "",
    }


def _failure_message(result: dict[str, object]) -> str:
    return (
        "Moving third-party bytes were packed or executed.\n"
        f"packed: {result['hits']}\n"
        f"executed sentinel: {result['sentinel']!r}\n"
        f"requests: {result['requests']}\n"
        f"serve: {str(result['served'])[:1500]}\n"
        f"import: {str(result['execution'])[:1500]}\n"
        f"recipe: {result['log'][-2500:]}"
    )


def test_stable_and_daily_recipes_fetch_the_same_third_party_inputs() -> None:
    """Both publish workflows run this one recipe; the fetches must match."""
    daily = [line for line in _expanded_recipe() if any(token in line for token in FETCH_TOKENS)]
    stable = [line for line in _expanded_recipe(["IS_STABLE=TRUE"]) if any(token in line for token in FETCH_TOKENS)]
    assert daily == stable
    assert daily, "make -n dist did not print the third-party fetch lines"


def test_branch_tip_is_not_packed_or_executed(tmp_path: Path) -> None:
    """A push to the default or master branch must not become the release zip.

    Immutable commit URLs are served a different body. Mutable URLs and the
    default-branch tip are served the marker. The packed tree and the import
    of the packed modules must not observe the marker.
    """
    result = _build(tmp_path, "branch")
    assert not result["hits"], _failure_message(result)
    assert result["sentinel"] == "", _failure_message(result)


def test_checksum_mismatch_is_not_left_in_the_package_tree(tmp_path: Path) -> None:
    """Bytes that differ from a recorded checksum must not remain to be zipped.

    Every intercepted response is the marker, including responses for a commit
    SHA. A pin without a checksum still packs those bytes. A check that leaves
    the downloaded file in the package tree still fails.
    """
    result = _build(tmp_path, "tamper")
    assert not result["hits"], _failure_message(result)
    assert result["sentinel"] == "", _failure_message(result)


def test_workflows_publish_the_dist_recipe_output() -> None:
    """The workflows that upload releases are the ones that run ``make dist``."""
    unstable = (REPO_ROOT / ".github/workflows/publish-bonsai-unstable.yml").read_text()
    stable = (REPO_ROOT / ".github/workflows/publish-bonsai.yml").read_text()
    publisher = (REPO_ROOT / ".github/scripts/publish-bonsai-releases.py").read_text()
    assert "make dist PLATFORM=" in unstable
    assert "make dist PLATFORM=" in stable
    assert "IS_STABLE=TRUE" in stable
    # The publisher posts the release asset body as the extension upload.
    assert "response.content" in publisher
    assert "versions/upload/" in publisher
