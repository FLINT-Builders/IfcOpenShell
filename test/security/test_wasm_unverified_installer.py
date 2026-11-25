# This file was generated with the assistance of an AI coding tool.
"""The WebAssembly release job must not execute the astral.sh installer body.

These tests fail while pyodide/build_pyodide.sh pipes that URL into a shell.
They pass once that body cannot run, including when a later download differs
from the body that was checked.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import socket
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/build-ifcopenshell-wasm.yml"
BUILD_SCRIPT = REPO_ROOT / "pyodide/build_pyodide.sh"
INSTALLER_URL = "https://astral.sh/uv/install.sh"
HOST_MARKER = "wasm-unverified-installer-test"
ACCESS_KEY_PLACEHOLDER = "placeholder-aws-access-key-id"
SECRET_PLACEHOLDER = "placeholder-aws-secret-access-key"
GITHUB_SHA = "abcdef0123456789abcdef0123456789abcdef01"

# Writer transcribed from aws-actions/configure-aws-credentials v6.3.0
# (commit e1253824e5c10ff9df46874f81ed3ec929e19cfd) dist/index.js, which
# bundles @actions/core 3.0.1:
# toCommandValue 72629-72635, prepareKeyValueMessage 72712-72721,
# issueFileCommand 72700-72710, exportVariable 73906-73913.
_NODE_EXPORT = r"""
const fs = require("fs");
const os = require("os");
const crypto = require("crypto");
function toCommandValue(input) {
  if (input === null || input === undefined) {
    return "";
  } else if (typeof input === "string" || input instanceof String) {
    return input;
  }
  return JSON.stringify(input);
}
function prepareKeyValueMessage(key, value) {
  const delimiter = `ghadelimiter_${crypto.randomUUID()}`;
  const convertedValue = toCommandValue(value);
  if (key.includes(delimiter)) {
    throw new Error("name contains delimiter");
  }
  if (convertedValue.includes(delimiter)) {
    throw new Error("value contains delimiter");
  }
  return `${key}<<${delimiter}${os.EOL}${convertedValue}${os.EOL}${delimiter}`;
}
function issueFileCommand(command, message) {
  const filePath = process.env[`GITHUB_${command}`];
  if (!filePath) {
    throw new Error(`Unable to find environment variable for file command ${command}`);
  }
  if (!fs.existsSync(filePath)) {
    throw new Error(`Missing file at path: ${filePath}`);
  }
  fs.appendFileSync(filePath, `${toCommandValue(message)}${os.EOL}`, { encoding: "utf8" });
}
function exportVariable(name, val) {
  const convertedVal = toCommandValue(val);
  process.env[name] = convertedVal;
  const filePath = process.env.GITHUB_ENV || "";
  if (filePath) {
    return issueFileCommand("ENV", prepareKeyValueMessage(name, val));
  }
  throw new Error("GITHUB_ENV is required");
}
const pairs = JSON.parse(process.argv[1]);
for (const pair of pairs) {
  exportVariable(pair[0], pair[1]);
}
"""


def _read_line(text: str, index: int) -> tuple[str | None, str | None, int]:
    """FileCommandManager.EnvFileKeyValuePairs.ReadLine on Linux (no CR LF branch)."""
    if index >= len(text):
        return None, None, index
    lf_index = text.find("\n", index)
    if lf_index < 0:
        return text[index:], None, len(text)
    return text[index:lf_index], "\n", lf_index + 1


def parse_github_env(text: str) -> list[tuple[str, str]]:
    """Parse a GITHUB_ENV file the way actions/runner v2.338.2 does.

    EnvFileKeyValuePairs.GetEnumerator, FileCommandManager.cs lines 382-445,
    commit d1eb12d4b115c301201de27d667284e1a80f2ab5.
    """
    pairs: list[tuple[str, str]] = []
    index = 0
    line, _newline, index = _read_line(text, index)
    while line is not None:
        if line != "":
            equals_index = line.find("=")
            heredoc_index = line.find("<<")
            if equals_index >= 0 and (heredoc_index < 0 or equals_index < heredoc_index):
                key, output = line.split("=", 1)
                pairs.append((key, output))
            elif heredoc_index >= 0 and (equals_index < 0 or heredoc_index < equals_index):
                key, delimiter = line.split("<<", 1)
                if key == "" or delimiter == "":
                    raise ValueError(f"invalid heredoc header {line!r}")
                start_index = index
                end_index = index
                temp_line, newline, index = _read_line(text, index)
                while temp_line != delimiter:
                    if temp_line is None:
                        raise ValueError(f"missing delimiter {delimiter!r}")
                    if newline is None:
                        raise ValueError("eof marker missing new line")
                    end_index = index - len(newline)
                    temp_line, newline, index = _read_line(text, index)
                output = text[start_index:end_index] if end_index > start_index else ""
                pairs.append((key, output))
            else:
                raise ValueError(f"invalid env line {line!r}")
        line, _newline, index = _read_line(text, index)
    return pairs


def prepend_path(prepend: str, current: str) -> str:
    """PathUtil.PrependPath, Runner.Sdk/Util/PathUtil.cs lines 13-33."""
    if not prepend:
        raise ValueError("prepend path is empty")
    if not current:
        return prepend
    if current.startswith(prepend + os.pathsep):
        return current
    return prepend + os.pathsep + current


def step_path(original_path: str, prepended: list[str]) -> str:
    """Handler.AddPrependPathToEnvironment joins PrependPath in reverse.

    Handler.cs lines 215-230. AddPathFileCommand appends each GITHUB_PATH
    line in file order (FileCommandManager.cs lines 138-154).
    """
    if not prepended:
        return original_path
    joined = os.pathsep.join(reversed(prepended))
    return prepend_path(joined, original_path)


def export_variables(env_file: Path, pairs: list[tuple[str, str]]) -> None:
    env = os.environ.copy()
    env["GITHUB_ENV"] = str(env_file)
    subprocess.run(
        ["node", "-e", _NODE_EXPORT, __import__("json").dumps(pairs)],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )


def _openssl(*args: str, cwd: Path) -> None:
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip("\n"))
    path.chmod(0o755)


def _build_wheel(path: Path) -> None:
    """Minimal wheel that order_pyodide_wheel_shared_objects and split accept."""
    import base64
    import csv
    import io
    import zipfile

    payload_name = "ifcopenshell/api/__init__.py"
    payload = b"original-wheel-bytes\n"
    metadata = b"Metadata-Version: 2.1\nName: ifcopenshell\nVersion: 0.9.0\nSummary: test wheel\n\n"
    wheel_meta = b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: false\nTag: py3-none-any\n\n"
    dist_info = "ifcopenshell-0.9.0.dist-info"
    entries = {
        payload_name: payload,
        f"{dist_info}/METADATA": metadata,
        f"{dist_info}/WHEEL": wheel_meta,
    }

    def digest(data: bytes) -> str:
        raw = hashlib.sha256(data).digest()
        return "sha256=" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    record_name = f"{dist_info}/RECORD"
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    for name in sorted(entries):
        data = entries[name]
        writer.writerow([name, digest(data), str(len(data))])
    writer.writerow([record_name, "", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
        archive.writestr(record_name, buffer.getvalue().encode())


def _snapshot(workspace: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for pattern in ("dist/*.whl", "dist-modular/*.zip"):
        for path in sorted(workspace.glob(pattern)):
            files[str(path.relative_to(workspace))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def _mirror_snapshot(mirror: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(mirror.rglob("*")):
        if path.is_file():
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


class _Job:
    """Sequential steps, GITHUB_PATH, and GITHUB_ENV for one shell job.

    Condition handling follows actions/runner v2.338.2:
    empty if becomes success() (WorkflowTemplateConverter.cs lines 1813-1815);
    success() is job status == Success (SuccessFunction.cs lines 37-38);
    a failed step does not run a later success() step (StepsRunnerL0.cs lines 155-177).
    File commands are processed after the step returns (ActionRunner.cs lines 276-282).
    """

    def __init__(self, workspace: Path, base_env: dict[str, str], original_path: str):
        self.workspace = workspace
        self.env = dict(base_env)
        self.original_path = original_path
        self.prepended: list[str] = []
        self.job_ok = True
        self.ran: list[str] = []
        self.skipped: list[str] = []
        self.before_upload: dict[str, str] | None = None

    def _condition_allows(self, condition: str | None) -> bool:
        if condition is None or condition == "success()":
            return self.job_ok
        if condition == "always()":
            return True
        raise AssertionError(f"unhandled step condition {condition!r}")

    def _begin_files(self) -> tuple[Path, Path, dict[str, str]]:
        directory = self.workspace / ".runner-file-commands"
        directory.mkdir(exist_ok=True)
        path_file = directory / f"add_path_{len(self.ran) + len(self.skipped)}"
        env_file = directory / f"set_env_{len(self.ran) + len(self.skipped)}"
        path_file.write_text("")
        env_file.write_text("")
        step_env = dict(self.env)
        step_env["PATH"] = step_path(self.original_path, self.prepended)
        step_env["GITHUB_PATH"] = str(path_file)
        step_env["GITHUB_ENV"] = str(env_file)
        return path_file, env_file, step_env

    def _finish_files(self, path_file: Path, env_file: Path) -> None:
        for line in path_file.read_text().splitlines():
            if line == "":
                continue
            self.prepended = [item for item in self.prepended if item != line]
            self.prepended.append(line)
        for key, value in parse_github_env(env_file.read_text()):
            if key.upper() == "NODE_OPTIONS":
                continue
            self.env[key] = value

    def run_shell(self, name: str, script: str, condition: str | None) -> None:
        if not self._condition_allows(condition):
            self.skipped.append(name)
            return
        if name == "Upload .zip archives to S3":
            self.before_upload = _snapshot(self.workspace)
        path_file, env_file, step_env = self._begin_files()
        script_path = self.workspace / ".runner-file-commands" / f"{len(self.ran)}.sh"
        script_path.write_text(script)
        # Default Linux shell: bash located by Which, arguments for "sh"
        # (ScriptHandler.cs lines 199-203 and ScriptHandlerHelpers.cs line 19).
        completed = subprocess.run(
            ["bash", "-e", str(script_path)],
            cwd=self.workspace,
            env=step_env,
            text=True,
            capture_output=True,
            timeout=180,
        )
        self._finish_files(path_file, env_file)
        self.ran.append(name)
        log = self.workspace / ".runner-file-commands" / f"{name}.log"
        log.write_text(completed.stdout + "\n" + completed.stderr)
        if completed.returncode != 0:
            self.job_ok = False

    def run_configure_aws(self, name: str, region: str, condition: str | None) -> None:
        if not self._condition_allows(condition):
            self.skipped.append(name)
            return
        _path_file, env_file, _step_env = self._begin_files()
        # helpers.ts exportRegion (134-138) then exportCredentials (91-97)
        # when aws-access-key-id is set and output-env-credentials defaults on
        # (index.ts lines 58-60 and 197-205). Validation against STS is not
        # called here; a failed validation would fail the step and success()
        # would skip the upload (index.ts lines 318-319).
        export_variables(
            env_file,
            [
                ("AWS_DEFAULT_REGION", region),
                ("AWS_REGION", region),
                ("AWS_ACCESS_KEY_ID", ACCESS_KEY_PLACEHOLDER),
                ("AWS_SECRET_ACCESS_KEY", SECRET_PLACEHOLDER),
            ],
        )
        self._finish_files(_path_file, env_file)
        self.ran.append(name)


def _workflow_steps() -> list[dict]:
    document = yaml.safe_load(WORKFLOW.read_text())
    return document["jobs"]["build"]["steps"]


def _step_condition(step: dict) -> str | None:
    condition = step.get("if")
    if condition is None:
        return None
    if not isinstance(condition, str):
        raise AssertionError(f"unexpected if value {condition!r}")
    return condition


def _prepare_workspace(root: Path, state: Path) -> None:
    workspace = root
    pyodide = workspace / "IfcOpenShell" / "pyodide"
    nix = workspace / "IfcOpenShell" / "nix"
    pyodide.mkdir(parents=True)
    nix.mkdir(parents=True)
    (workspace / "IfcOpenShell" / "VERSION").symlink_to(REPO_ROOT / "VERSION")
    for name in (
        "build_pyodide.sh",
        "requirements.txt",
        "meta.yaml",
        "order_pyodide_wheel_shared_objects.py",
        "split_pyodide_ifcopenshell_wheel.py",
    ):
        (pyodide / name).symlink_to(REPO_ROOT / "pyodide" / name)
    shutil.copy2(REPO_ROOT / "pyodide" / "run_pytest.py", pyodide / "run_pytest.py")
    (nix / "cache_dependencies.py").symlink_to(REPO_ROOT / "nix" / "cache_dependencies.py")

    install = workspace / "ifcopenshell_build" / "Linux" / "wasm" / "install" / "dummy_dep"
    install.mkdir(parents=True)
    (install / "marker.txt").write_text("dependency\n")
    subprocess.run(["git", "init", "-b", "main"], cwd=workspace / "ifcopenshell_build", check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=workspace / "ifcopenshell_build", check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=IfcOpenBot",
            "-c",
            "user.email=ifcopenbot@ifcopenshell.org",
            "commit",
            "-m",
            "init",
        ],
        cwd=workspace / "ifcopenshell_build",
        check=True,
        capture_output=True,
    )

    bin_dir = state / "bin"
    emcc_dir = state / "emcc"
    emsdk = state / "emsdk"
    pyodide_root = state / "pyodide-root"
    bin_dir.mkdir()
    emcc_dir.mkdir()
    (pyodide_root / "dist").mkdir(parents=True)
    (pyodide_root / "dist" / "placeholder.txt").write_text("pyodide\n")
    _write_executable(
        emcc_dir / "emcc",
        """
        #!/bin/bash
        if [ "$1" = "--version" ]; then
          echo "emcc stub"
          exit 0
        fi
        exit 1
        """,
    )
    _write_executable(
        bin_dir / "pyodide",
        f"""
        #!/bin/bash
        if [ "$1" = "xbuildenv" ]; then
          exit 0
        fi
        if [ "$1" = "config" ] && [ "$2" = "get" ] && [ "$3" = "emsdk_dir" ]; then
          mkdir -p "{emsdk}"
          cat > "{emsdk}/emsdk_env.sh" << 'EOF'
        export PATH="{emcc_dir}:$PATH"
        EOF
          echo "{emsdk}"
          exit 0
        fi
        if [ "$1" = "config" ] && [ "$2" = "get" ] && [ "$3" = "pyodide_root" ]; then
          echo "{pyodide_root}"
          exit 0
        fi
        if [ "$1" = "build-recipes-no-deps" ]; then
          exit 0
        fi
        if [ "$1" = "build-recipes" ]; then
          mkdir -p "$PWD/dist"
          cp "{state / "wheel.whl"}" "$PWD/dist/ifcopenshell-0.9.0-py3-none-any.whl"
          exit 0
        fi
        echo "unexpected pyodide args: $*" >&2
        exit 1
        """,
    )
    _write_executable(
        bin_dir / "uv",
        f"""
        #!/bin/bash
        if [ "$1" = "venv" ]; then
          rm -rf .venv
          mkdir -p .venv/bin
          cat > .venv/bin/activate << EOF
        export VIRTUAL_ENV="$PWD/.venv"
        export PATH="\\$VIRTUAL_ENV/bin:\\$PATH"
        EOF
          cp "{bin_dir / "pyodide"}" .venv/bin/pyodide
          cp "{bin_dir / "pytest"}" .venv/bin/pytest
          chmod +x .venv/bin/pyodide .venv/bin/pytest
          exit 0
        fi
        if [ "$1" = "pip" ]; then
          exit 0
        fi
        if [ "$1" = "run" ]; then
          shift
          case "$1" in
            *.py) exec python3 "$@" ;;
          esac
          exec "$@"
        fi
        echo "unexpected uv args: $*" >&2
        exit 1
        """,
    )
    _write_executable(
        bin_dir / "pytest",
        """
        #!/bin/bash
        exit 0
        """,
    )
    _write_executable(
        bin_dir / "aws",
        f"""
        #!/bin/bash
        printf '%s\\n' "legit $*" >> "{state / "aws-invocations.log"}"
        mkdir -p "{state / "upload-mirror"}"
        src="$3"
        if [[ "$*" == *".whl"* ]]; then
          cp "$src"/*.whl "{state / "upload-mirror"}/"
        fi
        if [[ "$*" == *".zip"* ]]; then
          cp "$src"/*.zip "{state / "upload-mirror"}/"
        fi
        exit 0
        """,
    )
    _build_wheel(state / "wheel.whl")


def _installer_body(state: Path, label: str) -> str:
    evil = state / f"evil-{label}"
    return textwrap.dedent(
        f"""\
        #!/bin/sh
        mkdir -p "{evil}"
        cat > "{evil}/aws" << 'EOF'
        #!/bin/sh
        printf '%s\\n' "$AWS_ACCESS_KEY_ID" > "{state / "planted-access-key"}"
        printf '%s\\n' "$AWS_SECRET_ACCESS_KEY" > "{state / "planted-secret-key"}"
        printf '%s\\n' "planted $*" >> "{state / "aws-invocations.log"}"
        for pattern in dist/*.whl dist-modular/*.zip; do
          for file in $pattern; do
            [ -f "$file" ] || continue
            printf 'substituted-wheel\\n' > "$file"
          done
        done
        mkdir -p "{state / "upload-mirror"}"
        src="$3"
        case "$*" in
          *.whl*) cp "$src"/*.whl "{state / "upload-mirror"}/" ;;
        esac
        case "$*" in
          *.zip*) cp "$src"/*.zip "{state / "upload-mirror"}/" ;;
        esac
        exit 0
        EOF
        chmod +x "{evil}/aws"
        if [ -n "$GITHUB_PATH" ]; then
          printf '%s\\n' "{evil}" >> "$GITHUB_PATH"
        fi
        printf '%s\\n' "{label}" >> "{state / "installer-executed"}"
        exit 0
        """
    )


def _start_origin(state: Path) -> subprocess.Popen[str]:
    server = state / "origin.py"
    server.write_text(
        textwrap.dedent(
            f"""\
            import json
            import os
            import ssl
            from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
            from pathlib import Path
            from urllib.parse import parse_qs, urlparse

            STATE = Path({str(state)!r})
            COUNT = STATE / "payload-count"

            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    parsed = urlparse(self.path)
                    if parsed.path == "/canary.sh":
                        self._send(200, (STATE / "canary.sh").read_bytes())
                        return
                    if parsed.path != "/uv/install.sh":
                        self._send(404, b"missing\\n")
                        return
                    if "payload" not in parse_qs(parsed.query):
                        self.send_response(302)
                        self.send_header("Location", "https://astral.sh/uv/install.sh?payload=1")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    count = int(COUNT.read_text() or "0")
                    COUNT.write_text(str(count + 1))
                    name = "payload-0.sh" if count == 0 else "payload-1.sh"
                    body = (STATE / name).read_bytes()
                    self._send(200, body)

                def _send(self, status, body):
                    self.send_response(status)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, fmt, *args):
                    with (STATE / "http.log").open("a") as handle:
                        handle.write("%s\\n" % (fmt % args))

            class Server(ThreadingHTTPServer):
                address_family = __import__("socket").AF_INET6
                def server_bind(self):
                    self.socket.setsockopt(__import__("socket").IPPROTO_IPV6, __import__("socket").IPV6_V6ONLY, 0)
                    super().server_bind()

            httpd = Server(("::", 443), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(STATE / "astral.crt", STATE / "astral.key")
            httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
            (STATE / "origin.pid").write_text(str(os.getpid()))
            httpd.serve_forever()
            """
        )
    )
    (state / "payload-count").write_text("0")
    canary_out = state / "canary-out"
    (state / "canary.sh").write_text(f"#!/bin/sh\nprintf '%s\\n' canary > '{canary_out}'\n")
    (state / "payload-0.sh").write_text(_installer_body(state, "payload-0"))
    (state / "payload-1.sh").write_text(_installer_body(state, "payload-1"))
    process = subprocess.Popen(
        ["sudo", "-n", "python3", str(server)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return process


def _wait_for_port() -> None:
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", 443), timeout=0.2):
                return
        except OSError:
            import time

            time.sleep(0.1)
    raise RuntimeError("installer origin did not listen on port 443")


def _install_hosts(cert_bundle: Path) -> None:
    subprocess.run(
        ["sudo", "-n", "tee", "-a", "/etc/hosts"],
        input=f"127.0.0.1 astral.sh {HOST_MARKER}\n::1 astral.sh {HOST_MARKER}\n",
        text=True,
        check=True,
        capture_output=True,
    )


def _remove_hosts() -> None:
    subprocess.run(
        ["sudo", "-n", "sed", "-i", f"/{HOST_MARKER}/d", "/etc/hosts"],
        check=False,
        capture_output=True,
    )


@pytest.fixture
def release_job(tmp_path: Path):
    state = tmp_path / "state"
    workspace = tmp_path / "workspace"
    state.mkdir()
    workspace.mkdir()
    _openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-keyout",
        "ca.key",
        "-out",
        "ca.crt",
        "-days",
        "1",
        "-nodes",
        "-subj",
        "/CN=WasmInstallerTestCA",
        cwd=state,
    )
    _openssl(
        "req",
        "-newkey",
        "rsa:2048",
        "-keyout",
        "astral.key",
        "-out",
        "astral.csr",
        "-nodes",
        "-subj",
        "/CN=astral.sh",
        cwd=state,
    )
    ext = state / "astral.ext"
    ext.write_text("subjectAltName=DNS:astral.sh\n")
    _openssl(
        "x509",
        "-req",
        "-in",
        "astral.csr",
        "-CA",
        "ca.crt",
        "-CAkey",
        "ca.key",
        "-CAcreateserial",
        "-out",
        "astral.crt",
        "-days",
        "1",
        "-extfile",
        "astral.ext",
        cwd=state,
    )
    bundle = state / "ca-bundle.crt"
    system_bundle = Path("/etc/ssl/certs/ca-certificates.crt").read_text()
    bundle.write_text(system_bundle + "\n" + (state / "ca.crt").read_text())
    _prepare_workspace(workspace, state)
    process = _start_origin(state)
    try:
        _wait_for_port()
        _install_hosts(bundle)
        resolved = subprocess.run(["getent", "hosts", "astral.sh"], check=True, capture_output=True, text=True)
        if "127.0.0.1" not in resolved.stdout and "::1" not in resolved.stdout:
            raise RuntimeError(f"astral.sh did not resolve to the fixture: {resolved.stdout}")
        canary_env = os.environ.copy()
        canary_env["SSL_CERT_FILE"] = str(bundle)
        canary = subprocess.run(
            ["curl", "-LsSf", "https://astral.sh/canary.sh"],
            check=True,
            capture_output=True,
            env=canary_env,
        )
        subprocess.run(["sh"], input=canary.stdout, check=True, capture_output=True)
        if (state / "canary-out").read_text().strip() != "canary":
            raise RuntimeError("curl did not deliver the canary body to sh")
        rejected = subprocess.run(
            ["curl", "-LsSf", "https://astral.sh/canary.sh"],
            capture_output=True,
            env={key: value for key, value in canary_env.items() if key != "SSL_CERT_FILE"},
        )
        if rejected.returncode == 0:
            raise RuntimeError("curl accepted the fixture certificate without the test CA")
        yield workspace, state, bundle
    finally:
        _remove_hosts()
        origin_pid = state / "origin.pid"
        if origin_pid.exists():
            subprocess.run(["sudo", "-n", "kill", origin_pid.read_text().strip()], check=False)
        if process.poll() is None:
            subprocess.run(["sudo", "-n", "kill", str(process.pid)], check=False)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            subprocess.run(["sudo", "-n", "kill", "-9", str(process.pid)], check=False)


def _run_release_job(workspace: Path, state: Path, bundle: Path) -> _Job:
    original_path = f"{state / 'bin'}:{os.environ.get('PATH', '')}"
    base_env = {
        "PATH": original_path,
        "HOME": str(state / "home"),
        "SSL_CERT_FILE": str(bundle),
        "GITHUB_SHA": GITHUB_SHA,
        "GIT_TERMINAL_PROMPT": "0",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "SYSTEMD_IGNORE": "1",
    }
    (state / "home").mkdir(exist_ok=True)
    job = _Job(workspace, base_env, original_path)
    steps = _workflow_steps()
    build_index = next(index for index, step in enumerate(steps) if step.get("name") == "Build")
    for step in steps[build_index:]:
        name = step.get("name") or step.get("uses") or ""
        condition = _step_condition(step)
        uses = step.get("uses")
        if uses:
            if uses.startswith("actions/upload-artifact@"):
                if not job._condition_allows(condition):
                    job.skipped.append(name)
                else:
                    job.ran.append(name)
                continue
            if uses.startswith("aws-actions/configure-aws-credentials@"):
                region = step["with"]["aws-region"]
                job.run_configure_aws(name, region, condition)
                continue
            raise AssertionError(f"unhandled action {uses}")
        script = step.get("run")
        if not isinstance(script, str):
            raise AssertionError(f"step {name!r} has no run script")
        job.run_shell(name, script, condition)
    return job


def test_github_env_parser_matches_actions_core_writer(tmp_path: Path) -> None:
    """The env-file stand-in must parse bytes the bundled writer emits."""
    env_file = tmp_path / "github.env"
    env_file.write_text("")
    export_variables(
        env_file,
        [
            ("AWS_DEFAULT_REGION", "us-east-1"),
            ("AWS_REGION", "us-east-1"),
            ("AWS_ACCESS_KEY_ID", ACCESS_KEY_PLACEHOLDER),
            ("AWS_SECRET_ACCESS_KEY", SECRET_PLACEHOLDER),
        ],
    )
    assert parse_github_env(env_file.read_text()) == [
        ("AWS_DEFAULT_REGION", "us-east-1"),
        ("AWS_REGION", "us-east-1"),
        ("AWS_ACCESS_KEY_ID", ACCESS_KEY_PLACEHOLDER),
        ("AWS_SECRET_ACCESS_KEY", SECRET_PLACEHOLDER),
    ]


def test_release_job_does_not_run_remote_installer(release_job: tuple[Path, Path, Path]) -> None:
    workspace, state, bundle = release_job
    job = _run_release_job(workspace, state, bundle)
    executed = (state / "installer-executed").read_text().split() if (state / "installer-executed").exists() else []
    invocations = (state / "aws-invocations.log").read_text() if (state / "aws-invocations.log").exists() else ""
    mirror = _mirror_snapshot(state / "upload-mirror") if (state / "upload-mirror").exists() else {}
    expected = {}
    if job.before_upload:
        for relative, digest in job.before_upload.items():
            expected[Path(relative).name] = digest
    access_file = state / "planted-access-key"
    secret_file = state / "planted-secret-key"
    planted_saw_credentials = (
        access_file.exists()
        and secret_file.exists()
        and access_file.read_text() == ACCESS_KEY_PLACEHOLDER + "\n"
        and secret_file.read_text() == SECRET_PLACEHOLDER + "\n"
    )
    upload_ran = "Upload .zip archives to S3" in job.ran
    uploaded_bytes_match = mirror == expected and mirror != {}
    report = {
        "executed_payloads": executed,
        "planted_command_saw_upload_credentials": planted_saw_credentials,
        "planted_command_ran": "planted" in invocations,
        "upload_published_unmodified_build": (not upload_ran) or uploaded_bytes_match,
    }
    # Refusing the untrusted body before the build finishes is a pass: the
    # upload step then does not run. Publishing still has to be the bytes the
    # build produced, and the installer body must not have been executed.
    assert report == {
        "executed_payloads": [],
        "planted_command_saw_upload_credentials": False,
        "planted_command_ran": False,
        "upload_published_unmodified_build": True,
    }
