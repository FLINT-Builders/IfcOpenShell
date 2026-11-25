# This file was generated with the assistance of an AI coding tool.
"""Security tests for the Windows mpir dependency build.

``install_mpir`` clones ``https://github.com/Andrej730/mpir-vs2026.git`` with no
revision and runs that checkout's ``msvc/vs<ver>/msbuild.bat``. The Windows
release workflow checks out ``IfcOpenShell/build-outputs`` with
``secrets.BUILD_REPO_TOKEN`` and does not set ``persist-credentials: false``.
``actions/checkout`` v7 (commit 3d3c42e5aac5ba805825da76410c181273ba90b1) then
leaves that credential on disk for later steps, including this build.

These tests follow that path. They fail while the fork's default branch is what
gets compiled and while the build-outputs checkout persists its token. A local
git repository stands in for the fork; the installer, ``git``, and the checkout
action's credential config are the real ones.

Not executed here: the ARM64-only ``mpir-arm64-changes.patch`` apply in
``install_mpir``. x64 and ARM64 share the unpinned clone and the ``msbuild.bat``
invocation; x64 is the path the ``windows-2022`` job runs. No other
``git_clone_and_checkout_revision`` caller omits a revision.

Run:
    python3 -m pytest win/tests/test_unpinned_mpir_fork.py -vv
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

WIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WIN_DIR))

from installers import install_mpir
from vs_cfg import CMAKE_GENERATORS, VsCfgResult

PLACEHOLDER_TOKEN = "PLACEHOLDER_BUILD_REPO_TOKEN"
FULL_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
WORKFLOW = WIN_DIR.parent / ".github" / "workflows" / "build-ifcopenshell-windows.yml"
UCRT_VERSION = "10.0.22621.0"


def _vcxproj(name: str) -> str:
    line = "    <WindowsTargetPlatformVersion>10.0.17134.0</WindowsTargetPlatformVersion>\n"
    return "".join(f"<!-- line {i} -->\n" for i in range(1, 25)) + line


def _props() -> str:
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "<Project>",
        "  <PropertyGroup>",
        "    <a>1</a>",
        "  </PropertyGroup>",
        "  <PropertyGroup>",
        "    <b>2</b>",
        "  </PropertyGroup>",
        "  <ItemDefinitionGroup>",
        "    <ClCompile>",
        "      <ObjectFileName>$(IntDir)du\\m\\my\\%(RelativeDir)</ObjectFileName>",
        "      <RuntimeLibrary>MultiThreaded</RuntimeLibrary>",
        "      <ProgramDataBaseFileName>$(TargetDir)$(TargetName).pdb</ProgramDataBaseFileName>",
        "    </ClCompile>",
        "    <Link>",
        "    </Link>",
        "  </ItemDefinitionGroup>",
        "</Project>",
        "",
    ]
    return "\n".join(lines)


def _build_script() -> str:
    # Executed by install_mpir via subprocess (shebang on this runner; the same
    # path is msvc\\vs22\\msbuild.bat, which cmd runs on the Windows job).
    return """#!/bin/sh
set -eu
marker=ATTACKER_TIP
echo "$marker args:$* head:$(git rev-parse HEAD)" > "${GITHUB_WORKSPACE}/attacker-ran.txt"
git -C "${GITHUB_WORKSPACE}/_deps-vs2022-x64-installed" config --get http.https://github.com/.extraheader > "${GITHUB_WORKSPACE}/credential-leak.txt"
mkdir -p "../../lib/x64/Release"
printf 'TAMPERED %s\\n' "$marker" > "../../lib/x64/Release/mpir.lib"
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.check_call(["git", "-C", str(repo), *args])


def _init_attacker_fork(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "mpir-test@example.com")
    _git(repo, "config", "user.name", "mpir-test")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "config", "core.autocrlf", "false")
    for name in ("lib_mpir_cxx", "lib_mpir_gc"):
        path = repo / "msvc" / "vs17" / name / f"{name}.vcxproj"
        path.parent.mkdir(parents=True)
        path.write_text(_vcxproj(name))
    (repo / "msvc" / "mpir_release_lib.props").write_text(_props())
    script = repo / "msvc" / "vs22" / "msbuild.bat"
    script.parent.mkdir(parents=True)
    script.write_text(_build_script())
    script.chmod(0o755)
    _git(repo, "add", "--chmod=+x", "msvc/vs22/msbuild.bat")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "attacker default branch")


def _init_build_outputs_checkout(install_dir: Path) -> None:
    """Create the build-outputs checkout the workflow places at the install dir."""
    install_dir.mkdir(parents=True)
    _git(install_dir, "init", "-b", "windows-x64")
    _git(install_dir, "config", "user.email", "mpir-test@example.com")
    _git(install_dir, "config", "user.name", "mpir-test")
    _git(install_dir, "config", "commit.gpgsign", "false")
    (install_dir / "README").write_text("cached dependencies\n")
    _git(install_dir, "add", "README")
    _git(install_dir, "commit", "-m", "cached dependencies")


def _persist_build_repo_token(install_dir: Path, runner_temp: Path, workspace: Path) -> None:
    """Reproduce actions/checkout v7 ``configureToken`` for a host checkout.

    The token value is an obvious placeholder. The action writes it to a file
    under RUNNER_TEMP and points the checkout's ``.git/config`` at that file
    with ``includeIf.gitdir`` (git-auth-helper.ts configureToken).
    """
    runner_temp.mkdir(parents=True)
    credentials = runner_temp / "git-credentials-test.config"
    placeholder = "AUTHORIZATION: basic ***"
    basic = base64.b64encode(f"x-access-token:{PLACEHOLDER_TOKEN}".encode()).decode()
    token_value = f"AUTHORIZATION: basic {basic}"
    subprocess.check_call(
        [
            "git",
            "config",
            "--file",
            str(credentials),
            "http.https://github.com/.extraheader",
            placeholder,
        ]
    )
    content = credentials.read_text()
    if content.count(placeholder) != 1:
        raise RuntimeError("credential placeholder was not written once")
    credentials.write_text(content.replace(placeholder, token_value))

    git_dir = (
        subprocess.check_output(
            ["git", "-C", str(install_dir), "rev-parse", "--absolute-git-dir"],
            text=True,
        )
        .strip()
        .replace("\\", "/")
    )
    subprocess.check_call(
        ["git", "-C", str(install_dir), "config", f"includeIf.gitdir:{git_dir}.path", str(credentials)]
    )
    subprocess.check_call(
        [
            "git",
            "-C",
            str(install_dir),
            "config",
            f"includeIf.gitdir:{git_dir}/worktrees/*.path",
            str(credentials),
        ]
    )
    relative = install_dir.resolve().relative_to(workspace.resolve()).as_posix()
    container_git = f"/github/workspace/{relative}/.git"
    container_credentials = f"/github/runner_temp/{credentials.name}"
    subprocess.check_call(
        [
            "git",
            "-C",
            str(install_dir),
            "config",
            f"includeIf.gitdir:{container_git}.path",
            container_credentials,
        ]
    )
    subprocess.check_call(
        [
            "git",
            "-C",
            str(install_dir),
            "config",
            f"includeIf.gitdir:{container_git}/worktrees/*.path",
            container_credentials,
        ]
    )

    stored = subprocess.check_output(
        ["git", "-C", str(install_dir), "config", "--get", "http.https://github.com/.extraheader"],
        text=True,
    ).strip()
    encoded = stored.split("basic ", 1)[1]
    assert base64.b64decode(encoded).decode() == f"x-access-token:{PLACEHOLDER_TOKEN}"


def _vs_cfg(deps_dir: Path, install_dir: Path) -> VsCfgResult:
    return VsCfgResult(
        generator=CMAKE_GENERATORS["Visual Studio 17 2022"],
        vs_platform="x64",
        vs_toolset_override=None,
        arch_bits=64,
        boost_toolset="msvc-14.3",
        gen_shorthand="vs2022-x64",
        deps_dir=deps_dir,
        install_dir=install_dir,
        build_dir="_build-vs2022-x64",
        build_deps_cache_path=deps_dir / "BuildDepsCache-x64.txt",
    )


def _is_git(argv: list[str]) -> bool:
    return bool(argv) and Path(argv[0]).name in {"git", "git.exe"}


def _redirect_remote(argv: list[str], fork: Path) -> list[str]:
    if not _is_git(argv) or not any(part in {"clone", "fetch", "pull", "ls-remote"} for part in argv):
        return argv
    rewritten = []
    for arg in argv:
        if arg.startswith(("https://", "http://", "ssh://", "git@", "git+ssh://")):
            rewritten.append(str(fork))
        else:
            rewritten.append(arg)
    return rewritten


def _advance_branch(dest: Path) -> None:
    """Move the cloned default branch after ``git clone`` returns.

    ``install_mpir`` then runs ``git reset --hard`` with no revision, which
    checks out whatever that branch now names.
    """
    script = dest / "msvc" / "vs22" / "msbuild.bat"
    script.write_text(script.read_text().replace("ATTACKER_TIP", "ATTACKER_MOVED"))
    subprocess.check_call(
        [
            "git",
            "-C",
            str(dest),
            "-c",
            "user.email=mpir-test@example.com",
            "-c",
            "user.name=mpir-test",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-am",
            "default branch moved after clone",
        ]
    )


def _checks_out_full_sha(argv: list[str], cwd: Path | None, mpir_dir: Path) -> bool:
    if not _is_git(argv):
        return False
    args = argv[1:]
    command_cwd = Path(cwd).resolve() if cwd else None
    if args[:1] == ["-C"] and len(args) >= 3:
        command_cwd = Path(args[1]).resolve()
        args = args[2:]
    if command_cwd != mpir_dir.resolve() or not args:
        return False
    pinned = [arg for arg in args[1:] if FULL_SHA.fullmatch(arg)]
    if not pinned:
        return False
    if args[0] == "checkout":
        return True
    if args[0] == "switch" and "--detach" in args:
        return True
    return args[0] == "reset" and "--hard" in args


def _run_install(monkeypatch: pytest.MonkeyPatch, workspace: Path, fork: Path, *, advance_after_clone: bool) -> None:
    deps_dir = workspace / "_deps"
    install_dir = workspace / "_deps-vs2022-x64-installed"
    mpir_dir = deps_dir / "mpir"
    commands: list[tuple[list[str], Path | None]] = []
    real_check_call = subprocess.check_call
    real_run = subprocess.run

    def check_call(args, **kwargs):
        argv = _redirect_remote([str(part) for part in args], fork)
        cwd = kwargs.get("cwd")
        commands.append((argv, Path(cwd) if cwd else None))
        result = real_check_call(argv, **kwargs)
        if advance_after_clone and _is_git(argv) and "clone" in argv:
            _advance_branch(Path(argv[-1]))
        return result

    def run(args, **kwargs):
        if isinstance(args, (list, tuple)):
            argv = _redirect_remote([str(part) for part in args], fork)
            cwd = kwargs.get("cwd")
            commands.append((argv, Path(cwd) if cwd else None))
            return real_run(argv, **kwargs)
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "check_call", check_call)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    monkeypatch.setenv("UCRTVersion", UCRT_VERSION)
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")

    try:
        install_mpir(_vs_cfg(deps_dir, install_dir), deps_dir, install_dir, "Release")
    except (subprocess.CalledProcessError, FileNotFoundError, SystemExit):
        pass

    ran = workspace / "attacker-ran.txt"
    leak = workspace / "credential-leak.txt"
    library = install_dir / "mpir" / "mpir.lib"
    pinned = any(_checks_out_full_sha(argv, cwd, mpir_dir) for argv, cwd in commands)
    problems: list[str] = []
    if ran.exists():
        problems.append(f"fork msbuild.bat ran ({ran.read_text().strip()})")
    if leak.exists() and "AUTHORIZATION:" in leak.read_text():
        problems.append("fork build script read the persisted build-outputs HTTP credential")
    if library.exists() and "TAMPERED" in library.read_text():
        problems.append("installed mpir library was produced by the fork build script")
    if not pinned:
        problems.append("mpir was not checked out at a full 40-character commit hash before use")
    if problems:
        pytest.fail("; ".join(problems))


def _prepare_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    empty_global = tmp_path / "gitconfig-empty"
    empty_global.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_global))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    workspace = tmp_path / "workspace"
    fork = tmp_path / "mpir-fork"
    runner_temp = tmp_path / "runner_temp"
    workspace.mkdir()
    _init_attacker_fork(fork)
    install_dir = workspace / "_deps-vs2022-x64-installed"
    _init_build_outputs_checkout(install_dir)
    _persist_build_repo_token(install_dir, runner_temp, workspace)
    return workspace, fork, install_dir


def test_fresh_cache_miss_does_not_build_moved_fork_branch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, fork, _install_dir = _prepare_workspace(tmp_path, monkeypatch)
    _run_install(monkeypatch, workspace, fork, advance_after_clone=True)


def test_existing_source_dir_does_not_build_fork_branch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, fork, _install_dir = _prepare_workspace(tmp_path, monkeypatch)
    dest = workspace / "_deps" / "mpir"
    subprocess.check_call(["git", "clone", str(fork), str(dest)])
    _run_install(monkeypatch, workspace, fork, advance_after_clone=False)


def _step_containing(text: str, needle: str) -> str:
    lines = text.splitlines()
    indexes = [index for index, line in enumerate(lines) if needle in line]
    assert indexes, needle
    blocks = []
    for index in indexes:
        start = index
        while start > 0 and not re.match(r"^      - ", lines[start]):
            start -= 1
        end = index + 1
        while end < len(lines) and not re.match(r"^      - ", lines[end]):
            end += 1
        blocks.append("\n".join(lines[start:end]))
    assert len(blocks) == 1
    return blocks[0]


def test_build_outputs_checkout_does_not_persist_token() -> None:
    step = _step_containing(WORKFLOW.read_text(), "secrets.BUILD_REPO_TOKEN")
    assert "repository: IfcOpenShell/build-outputs" in step
    match = re.search(r"persist-credentials:\s*(\S+)", step)
    assert match is not None, "build-outputs checkout must set persist-credentials: false"
    assert match.group(1).strip("'\"") == "false"
