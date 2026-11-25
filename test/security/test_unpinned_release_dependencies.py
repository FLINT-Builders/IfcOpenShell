# This file was generated with the assistance of an AI coding tool.
"""Release jobs must not run code from an unpinned PyPI release.

These tests execute the install commands in the release workflows and the
makefiles those workflows call. Each command is pointed at a local index that
stands in for the registry the command already consults (PyPI, unless the
command opts out with --no-index). The index publishes a release that satisfies
the command's requirement. Its build backend and its installed modules record
that they ran, and which release-secret names were present in the environment.

The tests fail while that code runs. They pass when the command rejects the
index artifact instead, which is what an exact pin plus a hash check does
(pip --require-hashes, or a uv script lock that checks hashes). A failure that
does not mention a hash is not treated as a fix.

Left untested, and why:
- nix/build-all.py's ``pip install numpy typing_extensions`` runs only after
  that script has compiled a private CPython, which this suite does not build.
- publish-bonsai-unstable.yml installs ``-r requirements.txt`` from the
  separate bonsai_unstable_repo checkout, which is not in this tree.
- docs/cpp-api/requirements.txt pins direct packages to exact versions, so a
  newly published Sphinx is not selected. Transitive dependencies of those
  pins are still unhashed; this file does not rebuild Sphinx's dependency tree.
- publish-ifctester-pypi.yml's ``make dist`` downloads Pyodide and an
  IfcOpenShell wasm wheel before the makefile reaches ``pip install build``.
  The workflow ``pip install build`` and the makefile recipe line are run;
  the Pyodide download is not.
- publish-ifcopenshell-python-pypi.yml's ``make dist`` downloads a binary zip
  before ``pip install build``. The workflow install and the makefile's
  install / ``python -m build`` lines are run; the binary zip download is not.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import textwrap
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SIGNATURE = "ATTACKER_CONTROLLED"
SECRET_NAMES = (
    "CHOCO_TOKEN",
    "BLENDER_EXTENSIONS_TOKEN",
    "PYPI_API_TOKEN",
    "ANACONDA_TOKEN",
    "IFCOPENBOT_TOKEN",
    "BUILD_REPO_TOKEN",
    "GITHUB_TOKEN",
)
PYPI_SIMPLE = "https://pypi.org/simple"
RUNNER_CHOCO = Path("/home/runner/work/IfcOpenShell/IfcOpenShell/choco/bonsai")

# pip 24 prints these when --require-hashes refuses an index artifact.
# See pip/_internal/exceptions.py HashMissing, HashUnpinned, HashMismatch.
_HASH_REJECTION = re.compile(r"hash", re.IGNORECASE)


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _split_requirement(requirement: str) -> tuple[str, str]:
    requirement = requirement.strip().strip("\"'")
    name = re.split(r"[<>=~!;\[]", requirement, maxsplit=1)[0].strip()
    exact = re.search(r"==\s*([0-9][0-9A-Za-z.*+]*)", requirement)
    if exact:
        return name, exact.group(1)
    upper = re.search(r"<\s*=?\s*([0-9]+(?:\.[0-9]+)*)", requirement)
    if upper:
        parts = [int(part) for part in upper.group(1).split(".")]
        for index in range(len(parts) - 1, -1, -1):
            if parts[index] > 0:
                parts[index] -= 1
                break
        return name, ".".join(str(part) for part in parts)
    return name, "99.0.0"


def _pip_clause(line: str) -> str:
    match = re.search(r"(?:python3? -m )?pip3?\s+(?:install|download)\b.*", line)
    return match.group(0) if match else ""


def _requirements_in_command(command: str, cwd: Path) -> list[tuple[str, str]]:
    clause = _pip_clause(command)
    if not clause:
        return []
    tokens = shlex.split(clause)
    requirements: list[str] = []
    skip = False
    take_file = False
    value_flags = {
        "-r",
        "--requirement",
        "--dest",
        "--platform",
        "--python-version",
        "--implementation",
        "--index-url",
        "-i",
        "--extra-index-url",
        "--find-links",
        "-f",
        "--constraint",
        "-c",
        "--target",
        "-t",
        "--prefix",
    }
    for token in tokens:
        if skip:
            if take_file:
                req_file = Path(token)
                if not req_file.is_absolute():
                    req_file = cwd / req_file
                requirements.extend(_requirements_in_file(req_file))
            skip = False
            take_file = False
            continue
        if token in value_flags:
            skip = True
            take_file = token in {"-r", "--requirement"}
            continue
        if token.startswith("-"):
            continue
        if token in {"pip", "pip3", "python", "python3", "-m", "install", "download"}:
            continue
        requirements.append(token)
    return [_split_requirement(requirement) for requirement in requirements if requirement]


def _requirements_in_file(path: Path) -> list[str]:
    found: list[str] = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        found.append(line)
    return found


def _marker_preamble(package: str) -> str:
    names = ", ".join(repr(name) for name in SECRET_NAMES)
    return textwrap.dedent(
        f"""\
        import json, os
        from pathlib import Path
        _seen = [n for n in ({names}) if n in os.environ]
        with Path(os.environ["ATTACK_MARKER"]).open("a") as _marker:
            _marker.write(json.dumps({{
                "phase": "import",
                "package": "{package}",
                "secret_names": _seen,
                "signature": "{SIGNATURE}",
            }}) + "\\n")
        """
    )


def _module_sources(project: str) -> dict[str, str]:
    """Files the built wheel must contain so the product's imports run the payload."""
    sources: dict[str, str] = {}
    project_key = _normalize(project)
    if project_key == "pygithub":
        sources["github/__init__.py"] = _marker_preamble(project) + textwrap.dedent(
            """\
            class Github:
                def get_repo(self, name):
                    return self

                def get_release(self, tag):
                    return self

                def get_assets(self):
                    return [
                        type("Asset", (), {"name": "bonsai-py313-linux-x64.zip", "browser_download_url": "https://example.invalid/a"})(),
                        type("Asset", (), {"name": "bonsai-py313-macos-arm64.zip", "browser_download_url": "https://example.invalid/b"})(),
                        type("Asset", (), {"name": "bonsai-py313-windows-x64.zip", "browser_download_url": "https://example.invalid/c"})(),
                    ]
            """
        )
        sources["github/GitReleaseAsset.py"] = "class GitReleaseAsset:\n    pass\n"
    elif project_key == "requests":
        sources["requests/__init__.py"] = _marker_preamble(project) + textwrap.dedent(
            """\
            class _Response:
                content = b"index-bytes"
                status_code = 200

                def raise_for_status(self):
                    return None

            def get(url, *args, **kwargs):
                return _Response()

            def post(url, headers=None, files=None, *args, **kwargs):
                import json, os
                from pathlib import Path
                saw = bool(headers and "Authorization" in headers)
                with Path(os.environ["ATTACK_MARKER"]).open("a") as _marker:
                    _marker.write(json.dumps({
                        "phase": "post",
                        "package": "requests",
                        "saw_authorization": saw,
                        "signature": "ATTACKER_CONTROLLED",
                    }) + "\\n")
                return _Response()
            """
        )
    elif project_key == "build":
        sources["build/__init__.py"] = _marker_preamble(project)
        sources["build/__main__.py"] = _marker_preamble(project) + textwrap.dedent(
            f"""\
            import zipfile
            from pathlib import Path
            destination = Path("dist")
            destination.mkdir(parents=True, exist_ok=True)
            wheel_path = destination / "published-attacker-py3-none-any.whl"
            with zipfile.ZipFile(wheel_path, "w") as wheel:
                wheel.writestr("ATTACKER_CONTROLLED", "{SIGNATURE}")
            """
        )
    elif project_key == "anaconda-client":
        sources["binstar_client/__init__.py"] = (
            "import requests\n" + _marker_preamble(project) + "class Binstar:\n    pass\n"
        )
        sources["binstar_client/errors.py"] = "class BinstarError(Exception):\n    pass\n"
        sources["binstar_client/utils.py"] = "def get_server_api(token=None):\n    raise RuntimeError('index stub')\n"
    else:
        module = _normalize(project).replace("-", "_")
        sources[f"{module}/__init__.py"] = _marker_preamble(project)
    return sources


def _wheel_bytes(project: str, version: str, modules: dict[str, str], requires: list[str]) -> bytes:
    import io

    dist = f"{_normalize(project).replace('-', '_')}-{version}.dist-info"
    metadata = ["Metadata-Version: 2.1", f"Name: {project}", f"Version: {version}"]
    metadata.extend(f"Requires-Dist: {requirement}" for requirement in requires)
    files = dict(modules)
    files[f"{dist}/METADATA"] = "\n".join(metadata) + "\n"
    files[f"{dist}/WHEEL"] = (
        "Wheel-Version: 1.0\nGenerator: release-index-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    )

    def row(path: str, data: bytes) -> str:
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        return f"{path},sha256={digest},{len(data)}\n"

    encoded = {path: data.encode() for path, data in files.items()}
    record = "".join(row(path, data) for path, data in encoded.items())
    record_path = f"{dist}/RECORD"
    record += f"{record_path},,\n"
    encoded[record_path] = record.encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as wheel:
        for path, data in encoded.items():
            wheel.writestr(path, data)
    return buffer.getvalue()


class ReleaseIndex:
    """PEP 503 index whose releases are the ones a hijacked project could publish."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.simple = root / "simple"
        self.simple.mkdir(parents=True)
        self._seen: set[tuple[str, str, str]] = set()

    def url(self) -> str:
        return self.simple.as_uri()

    def add(self, project: str, version: str, *, requires: list[str] | None = None, wheel: bool = False) -> None:
        kind = "wheel" if wheel else "sdist"
        key = (_normalize(project), version, kind)
        if key in self._seen:
            return
        self._seen.add(key)
        requires = requires or []
        if not wheel:
            _write_sdist_with_sources(self, project, version, requires)
            return
        filename = f"{_normalize(project).replace('-', '_')}-{version}-py3-none-any.whl"
        payload = _wheel_bytes(project, version, _module_sources(project), requires)
        (self.root / filename).write_bytes(payload)
        self._link(project, filename)

    @staticmethod
    def _add_bytes(archive: tarfile.TarFile, name: str, data: bytes) -> None:
        import io
        import time

        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mtime = int(time.time())
        archive.addfile(info, io.BytesIO(data))

    def _link(self, project: str, filename: str) -> None:
        digest = hashlib.sha256((self.root / filename).read_bytes()).hexdigest()
        folder = self.simple / _normalize(project)
        folder.mkdir(parents=True, exist_ok=True)
        page = folder / "index.html"
        existing = page.read_text() if page.exists() else "<!DOCTYPE html><html><body>\n"
        if not existing.endswith("\n"):
            existing += "\n"
        link = f'<a href="../../{filename}#sha256={digest}">{filename}</a>\n'
        if link not in existing:
            if "</body>" in existing:
                existing = existing.replace("</body>", link + "</body>")
            else:
                existing += link
            page.write_text(existing)


def _write_sdist_with_sources(index: ReleaseIndex, project: str, version: str, requires: list[str]) -> None:
    top = f"{_normalize(project).replace('-', '_')}-{version}"
    filename = f"{top}.tar.gz"
    destination = index.root / filename
    config = {"name": project, "version": version, "requires": requires}
    pyproject = textwrap.dedent(
        f"""\
        [build-system]
        requires = []
        build-backend = "attacker_backend"
        backend-path = ["."]

        [project]
        name = "{project}"
        version = "{version}"
        """
    )
    if requires:
        pyproject += "dependencies = [\n" + "".join(f'    "{requirement}",\n' for requirement in requires) + "]\n"
    pyproject += f"# {SIGNATURE}\n"
    with tarfile.open(destination, "w:gz") as archive:
        index._add_bytes(archive, f"{top}/pyproject.toml", pyproject.encode())
        index._add_bytes(archive, f"{top}/attacker_config.json", json.dumps(config).encode())
        index._add_bytes(archive, f"{top}/attacker_backend.py", _backend_source().encode())
        for relative, source in _module_sources(project).items():
            index._add_bytes(archive, f"{top}/wheel_sources/{relative}", source.encode())
    index._link(project, filename)
    index._seen.add((_normalize(project), version, "sdist"))


def _backend_source() -> str:
    names = list(SECRET_NAMES)
    return textwrap.dedent(
        f'''\
        import base64
        import hashlib
        import json
        import os
        import zipfile
        from pathlib import Path

        CONFIG = json.loads((Path(__file__).resolve().parent / "attacker_config.json").read_text())
        SIGNATURE = "{SIGNATURE}"
        SECRET_NAMES = {names!r}

        def _note(phase):
            seen = [name for name in SECRET_NAMES if name in os.environ]
            path = Path(os.environ["ATTACK_MARKER"])
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a") as marker:
                marker.write(json.dumps({{
                    "phase": phase,
                    "package": CONFIG["name"],
                    "secret_names": seen,
                    "signature": SIGNATURE,
                }}) + "\\n")

        def get_requires_for_build_wheel(config_settings=None):
            _note("get_requires_for_build_wheel")
            return []

        def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
            _note("build_wheel")
            project = CONFIG["name"]
            version = CONFIG["version"]
            normalized = project.lower().replace("_", "-")
            dist = normalized.replace("-", "_") + "-" + version + ".dist-info"
            root = Path(__file__).resolve().parent / "wheel_sources"
            files = {{}}
            if root.exists():
                for path in root.rglob("*"):
                    if path.is_file():
                        files[str(path.relative_to(root))] = path.read_text()
            metadata = "Metadata-Version: 2.1\\nName: " + project + "\\nVersion: " + version + "\\n"
            for requirement in CONFIG.get("requires", []):
                metadata += "Requires-Dist: " + requirement + "\\n"
            files[dist + "/METADATA"] = metadata
            files[dist + "/WHEEL"] = (
                "Wheel-Version: 1.0\\nGenerator: release-index-test\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n"
            )
            encoded = {{path: data.encode() for path, data in files.items()}}
            record = ""
            for path, data in encoded.items():
                digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                record += path + ",sha256=" + digest + "," + str(len(data)) + "\\n"
            record_path = dist + "/RECORD"
            record += record_path + ",,\\n"
            encoded[record_path] = record.encode()
            wheel_name = dist[: -len(".dist-info")] + "-py3-none-any.whl"
            target = os.path.join(wheel_directory, wheel_name)
            with zipfile.ZipFile(target, "w") as wheel:
                for path, data in encoded.items():
                    wheel.writestr(path, data)
            return wheel_name
        '''
    )


def _seed(
    index: ReleaseIndex,
    requirements: list[tuple[str, str]],
    *,
    wheel: bool,
    requires_of: dict[str, list[str]] | None = None,
) -> None:
    requires_of = requires_of or {}
    for name, version in requirements:
        extra = requires_of.get(_normalize(name), [])
        if wheel:
            index.add(name, version, requires=extra, wheel=True)
        else:
            _write_sdist_with_sources(index, name, version, extra)


def _events(marker: Path) -> list[dict]:
    if not marker.exists():
        return []
    return [json.loads(line) for line in marker.read_text().splitlines() if line.strip()]


def _tree_bytes(root: Path) -> bytes:
    chunks = []
    if not root.exists():
        return b""
    for path in root.rglob("*"):
        if path.is_file():
            chunks.append(path.read_bytes())
    return b"".join(chunks)


def _command_env(tmp: Path, index_url: str, marker: Path, secrets: dict[str, str], command: str) -> dict[str, str]:
    path = os.pathsep.join([os.path.expanduser("~/.local/bin"), os.environ.get("PATH", "")])
    env = {
        "PATH": path,
        "HOME": str(tmp / "home"),
        "TMPDIR": str(tmp),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_CACHE_DIR": "1",
        "PIP_NO_INPUT": "1",
        "UV_CACHE_DIR": str(tmp / "uv-cache"),
        "ATTACK_MARKER": str(marker),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    (tmp / "home").mkdir(parents=True, exist_ok=True)
    substituted = command.replace(PYPI_SIMPLE, index_url)
    if "--no-index" not in substituted:
        env["PIP_INDEX_URL"] = index_url
        env["UV_DEFAULT_INDEX"] = index_url
    env.update(secrets)
    return env


def _run(command: str, cwd: Path, env: dict[str, str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    rewritten = command.replace(PYPI_SIMPLE, env.get("PIP_INDEX_URL", env.get("UV_DEFAULT_INDEX", "")))
    return subprocess.run(
        ["bash", "-lc", rewritten],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _assert_closed(proc: subprocess.CompletedProcess[str], marker: Path, output: Path | None = None) -> None:
    events = _events(marker)
    leaked = sorted({name for event in events for name in event.get("secret_names", [])})
    shipped = SIGNATURE.encode() in _tree_bytes(output) if output else False
    if events or shipped:
        phases = [f"{event.get('package')}:{event.get('phase')}" for event in events]
        pytest.fail(
            "index release code ran in the release command"
            + (f" and saw secret names {leaked}" if leaked else "")
            + (f" during {phases}" if phases else "")
            + (" and wrote the published artifact" if shipped else "")
            + f"\nexit={proc.returncode}\nstdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
        )
    if proc.returncode != 0 and not _HASH_REJECTION.search(proc.stdout + proc.stderr):
        pytest.fail(
            "release command failed without a hash rejection, so this does not show the index artifact was refused\n"
            f"exit={proc.returncode}\nstdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
        )


def _workflow_env_block(text: str) -> str:
    return text.split("\njobs:", 1)[0]


def _pip_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if "pip install" in stripped or "pip download" in stripped or "pip3 install" in stripped:
            lines.append(stripped.rstrip("\\").strip())
    return lines


def _expand_make_vars(line: str) -> str:
    replacements = {
        "$(PYTHON)": "python3",
        "$(PIP)": "pip3",
        "$(VENV_ACTIVATE)": "bin/activate",
        "$(PYPI_PLATFORM)": "--platform manylinux_2_17_x86_64",
        "$(PYPI_VERSION)": "3.11",
        "$(PYPI_IMP)": "cp",
        "$(WEBAPP_IFCTESTER_BUILD_DIR)": ".",
    }
    for key, value in replacements.items():
        line = line.replace(key, value)
    return line


def test_choco_release_does_not_run_index_pygithub(tmp_path: Path) -> None:
    workflow = (REPO / ".github/workflows/publish-bonsai-choco.yml").read_text()
    assert "pip install pygithub" in workflow
    index = ReleaseIndex(tmp_path / "index")
    _seed(index, [("pygithub", "99.0.0")], wheel=False)
    marker = tmp_path / "marker.jsonl"
    secrets = {}
    if "CHOCO_TOKEN" in _workflow_env_block(workflow):
        secrets["CHOCO_TOKEN"] = "placeholder-not-a-real-secret"
    if RUNNER_CHOCO.exists():
        shutil.rmtree(RUNNER_CHOCO)
    RUNNER_CHOCO.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO / "choco" / "bonsai", RUNNER_CHOCO)
    command = textwrap.dedent(
        """\
        pip install pygithub
        cd /home/runner/work/IfcOpenShell/IfcOpenShell/choco/bonsai/ &&
        python3 choco_release.py
        """
    )
    env = _command_env(tmp_path, index.url(), marker, secrets, command)
    try:
        proc = _run(command, tmp_path, env, timeout=60)
    finally:
        shutil.rmtree(RUNNER_CHOCO, ignore_errors=True)
    _assert_closed(proc, marker)


def test_bonsai_extensions_publish_does_not_run_index_dependencies(tmp_path: Path) -> None:
    workflow = (REPO / ".github/workflows/publish-bonsai-releases.yml").read_text()
    script = REPO / ".github/scripts/publish-bonsai-releases.py"
    assert "uv run .github/scripts/publish-bonsai-releases.py" in workflow
    assert "BLENDER_EXTENSIONS_TOKEN" in workflow
    index = ReleaseIndex(tmp_path / "index")
    _seed(index, [("PyGithub", "99.0.0"), ("requests", "99.0.0")], wheel=False)
    root = tmp_path / "repo"
    shutil.copytree(REPO / ".github", root / ".github")
    shutil.copy(REPO / "pyproject.toml", root / "pyproject.toml")
    shutil.copy(REPO / "VERSION", root / "VERSION")
    # The workflow runs the checkout's script. Keep the copy byte-identical.
    assert (root / ".github/scripts/publish-bonsai-releases.py").read_bytes() == script.read_bytes()
    marker = tmp_path / "marker.jsonl"
    command = "uv run .github/scripts/publish-bonsai-releases.py"
    env = _command_env(
        tmp_path,
        index.url(),
        marker,
        {"BLENDER_EXTENSIONS_TOKEN": "placeholder-not-a-real-secret"},
        command,
    )
    proc = _run(command, root, env, timeout=60)
    _assert_closed(proc, marker, root)


def test_conda_cleaner_does_not_run_unpinned_dependency(tmp_path: Path) -> None:
    workflow = (REPO / ".github/workflows/publish-ifcopenshell-conda-cleaner.yml").read_text()
    script = (REPO / "conda/clean-old-versions.py").read_text()
    assert "anaconda-client==1.15.0" in script
    assert "ANACONDA_TOKEN" in _workflow_env_block(workflow)
    index = ReleaseIndex(tmp_path / "index")
    # anaconda-client stays at the pinned version and depends on requests, which is not pinned.
    # binstar_client/__init__.py in anaconda-client 1.15.0 imports requests at import time.
    _write_sdist_with_sources(index, "anaconda-client", "1.15.0", ["requests>=2.20.0"])
    _seed(index, [("requests", "99.0.0")], wheel=False)
    root = tmp_path / "repo"
    (root / "conda").mkdir(parents=True)
    shutil.copy(REPO / "conda/clean-old-versions.py", root / "conda/clean-old-versions.py")
    marker = tmp_path / "marker.jsonl"
    command = "uv run --script conda/clean-old-versions.py"
    env = _command_env(
        tmp_path,
        index.url(),
        marker,
        {"ANACONDA_TOKEN": "placeholder-not-a-real-secret", "NUM_SUPPORTED_VERSIONS": "5"},
        command,
    )
    proc = _run(command, root, env, timeout=60)
    _assert_closed(proc, marker)


@pytest.mark.parametrize(
    "script",
    [
        "pyodide/pack_wheel.py",
        "nix/build-all.py",
        "test/package/run_against_package.py",
    ],
)
def test_build_job_uv_script_does_not_run_index_dependencies(tmp_path: Path, script: str) -> None:
    source = (REPO / script).read_text()
    dependencies = re.findall(r'^\s*#\s*"([^"]+)"', source, re.MULTILINE)
    assert dependencies, script
    index = ReleaseIndex(tmp_path / "index")
    _seed(index, [_split_requirement(dependency) for dependency in dependencies], wheel=False)
    root = tmp_path / "repo"
    destination = root / script
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / script, destination)
    # build-all.py imports a sibling module before the third-party import returns.
    if script == "nix/build-all.py":
        for extra in (REPO / "nix").glob("*.py"):
            shutil.copy(extra, root / "nix" / extra.name)
    marker = tmp_path / "marker.jsonl"
    command = f"uv run --no-project {script} --help"
    env = _command_env(tmp_path, index.url(), marker, {}, command)
    proc = _run(command, root, env, timeout=60)
    _assert_closed(proc, marker)


def _pypi_workflows() -> list[Path]:
    return sorted((REPO / ".github/workflows").glob("publish-*-pypi.yml"))


@pytest.mark.parametrize("workflow_path", _pypi_workflows(), ids=lambda path: path.name)
def test_pypi_workflow_install_does_not_run_index_build(tmp_path: Path, workflow_path: Path) -> None:
    text = workflow_path.read_text()
    installs = [line for line in _pip_lines(text) if "install" in line]
    assert installs, workflow_path.name
    index = ReleaseIndex(tmp_path / "index")
    requirements = []
    for line in installs:
        requirements.extend(_requirements_in_command(line, REPO))
    _seed(index, requirements, wheel=False)
    marker = tmp_path / "marker.jsonl"
    command = "\n".join(installs)
    env = _command_env(tmp_path, index.url(), marker, {}, command)
    proc = _run(command, tmp_path, env, timeout=120)
    _assert_closed(proc, marker)


def test_bcf_dist_does_not_publish_index_build_output(tmp_path: Path) -> None:
    workflow = (REPO / ".github/workflows/publish-bcf-pypi.yml").read_text()
    assert "pip install build" in workflow
    assert "make dist IS_STABLE=TRUE" in workflow
    index = ReleaseIndex(tmp_path / "index")
    _seed(index, [("build", "99.0.0")], wheel=False)
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    shutil.copy(REPO / "VERSION", root / "VERSION")
    shutil.copy(REPO / "src/common.mk", root / "src/common.mk")
    shutil.copytree(REPO / "src/bcf", root / "src/bcf")
    marker = tmp_path / "marker.jsonl"
    command = "pip install build\ncd src/bcf && make dist IS_STABLE=TRUE"
    env = _command_env(tmp_path, index.url(), marker, {}, command)
    proc = _run(command, root, env, timeout=180)
    _assert_closed(proc, marker, root / "src/bcf/dist")


def test_ifcopenshell_python_makefile_does_not_run_index_build(tmp_path: Path) -> None:
    makefile = (REPO / "src/ifcopenshell-python/Makefile").read_text()
    lines = [
        _expand_make_vars(line.strip())
        for line in makefile.splitlines()
        if "install build" in line or "-m build" in line
    ]
    assert len(lines) >= 2
    index = ReleaseIndex(tmp_path / "index")
    _seed(index, [("build", "99.0.0")], wheel=False)
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "pyproject.toml").write_text("[project]\nname='ifcopenshell'\nversion='0.0.0'\n")
    marker = tmp_path / "marker.jsonl"
    # make runs each recipe line in a new shell from the makefile directory.
    command = "\n".join(f"( {line} )" for line in lines)
    env = _command_env(tmp_path, index.url(), marker, {}, command)
    proc = _run(command, tmp_path, env, timeout=180)
    _assert_closed(proc, marker, build_dir / "dist")


def test_ifctester_makefile_does_not_run_index_build(tmp_path: Path) -> None:
    makefile = (REPO / "src/ifctester/Makefile").read_text()
    lines = [_expand_make_vars(line.strip()) for line in makefile.splitlines() if "pip install build" in line]
    assert lines
    index = ReleaseIndex(tmp_path / "index")
    _seed(index, [("build", "99.0.0")], wheel=False)
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy(REPO / "src/ifctester/pyproject.toml", project / "pyproject.toml")
    marker = tmp_path / "marker.jsonl"
    command = "\n".join(f"( {line} )" for line in lines)
    env = _command_env(tmp_path, index.url(), marker, {}, command)
    proc = _run(command, project, env, timeout=180)
    _assert_closed(proc, marker, project / "dist")


def test_bonsai_makefile_installs_do_not_run_index_code(tmp_path: Path) -> None:
    makefile = (REPO / "src/bonsai/Makefile").read_text()
    lines = [
        _expand_make_vars(line.strip())
        for line in makefile.splitlines()
        if "$(PIP) install" in line or "pip install" in line
    ]
    assert lines
    index = ReleaseIndex(tmp_path / "index")
    requirements = []
    for line in lines:
        requirements.extend(_requirements_in_command(line, REPO))
    _seed(index, requirements, wheel=False)
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    marker = tmp_path / "marker.jsonl"
    command = "\n".join(f"( {line} )" for line in lines)
    env = _command_env(tmp_path, index.url(), marker, {}, command)
    proc = _run(command, tmp_path, env, timeout=180)
    _assert_closed(proc, marker)


def test_bonsai_makefile_downloads_do_not_fetch_index_artifacts(tmp_path: Path) -> None:
    makefile = (REPO / "src/bonsai/Makefile").read_text()
    lines = [_expand_make_vars(line.strip()) for line in makefile.splitlines() if "$(PIP) download" in line]
    assert len(lines) > 10
    index = ReleaseIndex(tmp_path / "index")
    requirements = []
    for line in lines:
        requirements.extend(_requirements_in_command(line, REPO))
    _seed(index, requirements, wheel=True)
    # only-binary downloads need a wheel; an sdist-only release would not be selected.
    build_dir = tmp_path / "build"
    wheels = build_dir / "wheels"
    wheels.mkdir(parents=True)
    marker = tmp_path / "marker.jsonl"
    # Download lines activate build/env, which the dist recipe creates earlier.
    # Each recipe line starts from the makefile directory, as make does.
    command = "( python3 -m venv build/env )\n" + "\n".join(f"( {line} )" for line in lines)
    env = _command_env(tmp_path, index.url(), marker, {}, command)
    proc = _run(command, tmp_path, env, timeout=180)
    _assert_closed(proc, marker, wheels)


@pytest.mark.parametrize(
    "requirements",
    [
        "src/bonsai/docs/requirements.txt",
        "src/bonsaiviewer/docs/requirements.txt",
    ],
)
def test_docs_publish_requirements_do_not_run_index_code(tmp_path: Path, requirements: str) -> None:
    workflow = (REPO / ".github/workflows/publish-docs-unstable.yml").read_text()
    assert "pip install -r" in workflow
    assert "IFCOPENBOT_TOKEN" in workflow
    path = REPO / requirements
    index = ReleaseIndex(tmp_path / "index")
    _seed(index, [_split_requirement(line) for line in _requirements_in_file(path)], wheel=False)
    root = tmp_path / "repo"
    destination = root / requirements
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(path, destination)
    marker = tmp_path / "marker.jsonl"
    command = f"pip install -r {requirements}"
    env = _command_env(tmp_path, index.url(), marker, {}, command)
    proc = _run(command, root, env, timeout=180)
    _assert_closed(proc, marker)
