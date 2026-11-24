# This file was generated with the assistance of an AI coding tool.
"""Release builds must not package a moved ``dtolnay/rust-toolchain`` ref.

``build-ifcopenshell-linux.yml``, ``build-ifcopenshell-linux-arm.yml``, and
``build-ifcopenshell-macos.yml`` install Rust with
``dtolnay/rust-toolchain@stable``. A later step runs ``packaging/build.py``,
which executes ``cargo`` from ``PATH`` and copies ``bonsaiviewer-autodesk``
into the BonsaiViewer zip. That zip is what the job uploads to
``s3://ifcopenshell-builds``.

``stable`` is a branch tip, not a commit. These tests move that branch to an
action whose composite ``bash`` steps install a ``cargo`` of their choosing,
apply ``GITHUB_PATH`` the way actions/runner v2.338.2 does, then run the real
``build.py`` and ``package_executable``. The packaged connector must not be
the one from the moved branch.

The tests fail while a release workflow names a branch or tag. They pass when
every one of those workflows pins ``dtolnay/rust-toolchain`` to a full
40-character commit SHA. A full SHA is resolved as that commit object only;
the branch is not read again.

Not covered, because they do not share this upload path:

- ``build-ifcopenshell-wasm.yml`` does not reference ``dtolnay/rust-toolchain``.
- ``build-ifcopenshell-windows.yml`` runs ``packaging/build.py`` but does not
  use this action.
- ``test-bonsaiviewer-autodesk.yml`` uses ``@stable`` but does not upload
  archives to the public build bucket.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOWS = (
    ".github/workflows/build-ifcopenshell-linux.yml",
    ".github/workflows/build-ifcopenshell-linux-arm.yml",
    ".github/workflows/build-ifcopenshell-macos.yml",
)
ATTACKER_MARKER = b"ATTACKER-CONTROLLED-BONSAIVIEWER-CONNECTOR"
BENIGN_MARKER = b"BENIGN-RUST-TOOLCHAIN-CONNECTOR"
FULL_SHA = re.compile(r"[0-9a-fA-F]{40}")
CONNECTOR_MEMBER = "connectors/autodesk/bonsaiviewer-autodesk"
_BUILD_LOCK = threading.Lock()


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _rev_parse(repo: Path, rev: str) -> str | None:
    result = _git(repo, "rev-parse", "--verify", rev, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _action_script(marker: bytes) -> str:
    # Composite action of the same shape as dtolnay/rust-toolchain: bash steps
    # that place cargo on PATH through GITHUB_PATH. The marker is the bytes
    # `cargo build` writes into the connector binary.
    rendered = marker.decode("ascii")
    return f"""name: rustup toolchain install
runs:
  using: composite
  steps:
    - name: Install cargo
      shell: bash
      run: |
        bindir="$HOME/.cargo/bin"
        mkdir -p "$bindir"
        {{
          echo '#!/bin/sh'
          echo 'mkdir -p target/release'
          echo "printf '%s' '{rendered}' > target/release/bonsaiviewer-autodesk"
          echo 'chmod +x target/release/bonsaiviewer-autodesk'
        }} > "$bindir/cargo"
        chmod +x "$bindir/cargo"
        echo "$bindir" >> "$GITHUB_PATH"
"""


def _commit_action(repo: Path, marker: bytes, message: str) -> str:
    (repo / "action.yml").write_text(_action_script(marker))
    _git(repo, "add", "action.yml")
    _git(repo, "commit", "-q", "-m", message)
    sha = _rev_parse(repo, "HEAD")
    assert sha is not None
    return sha


def _init_action_repo(path: Path) -> tuple[Path, str, str]:
    """Benign commit, then a ``stable`` branch moved to a different commit."""
    repo = path / "rust-toolchain"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "toolchain-test@example.com")
    _git(repo, "config", "user.name", "toolchain-test")
    benign = _commit_action(repo, BENIGN_MARKER, "benign toolchain")
    malicious = _commit_action(repo, ATTACKER_MARKER, "moved toolchain")
    _git(repo, "update-ref", "refs/heads/stable", malicious)
    assert _rev_parse(repo, "refs/heads/stable") == malicious
    assert benign != malicious
    return repo, benign, malicious


def resolve_action_ref(repo: Path, ref: str) -> str | None:
    """Resolve ``uses:`` the way a job runs it.

    A full commit SHA is that object (``rev^{commit}``). It is not looked up
    as ``refs/heads/<ref>`` or ``refs/tags/<ref>``. Any other ref is the
    current branch tip, or the tag tip if there is no branch of that name.
    ``None`` means the SHA is not this fixture's moved branch.
    """
    if FULL_SHA.fullmatch(ref):
        return _rev_parse(repo, f"{ref}^{{commit}}")
    for candidate in (f"refs/heads/{ref}", f"refs/tags/{ref}"):
        resolved = _rev_parse(repo, candidate)
        if resolved is not None:
            return resolved
    raise AssertionError(f"{ref!r} is not a full commit SHA and is not a branch or tag")


def _prepend_path(prepended: list[str], current: str) -> str:
    # actions/runner v2.338.2 PathUtil.PrependPath, after reversing PrependPath.
    if not prepended:
        return current
    path = ":".join(reversed(prepended))
    if not current:
        return path
    if current.startswith(path + ":"):
        return current
    return path + ":" + current


def _apply_github_path(path_file: Path, prepended: list[str]) -> None:
    # AddPathFileCommand.ProcessCommand: skip empty lines, move duplicates to the end.
    if not path_file.exists():
        return
    for line in path_file.read_text(encoding="utf-8").splitlines():
        if line == "":
            continue
        while line in prepended:
            prepended.remove(line)
        prepended.append(line)


def _extract_action(repo: Path, sha: str, dest: Path) -> None:
    # The runner downloads the tarball of the resolved commit and runs its action.yml.
    archive = subprocess.check_output(["git", "-C", str(repo), "archive", sha])
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)


def _run_composite_action(action_dir: Path, workspace: Path, home: Path, base_path: str) -> list[str]:
    manifest = yaml.safe_load((action_dir / "action.yml").read_text())
    runs = manifest["runs"]
    assert runs["using"] == "composite"
    prepended: list[str] = []
    for index, step in enumerate(runs["steps"]):
        script = step.get("run")
        if not script:
            continue
        shell = step.get("shell") or "bash"
        assert shell == "bash", shell
        # File commands live in the runner temp dir, not the workspace.
        path_file = home / f"add_path_{index}"
        path_file.write_text("")
        script_path = home / f"step_{index}.sh"
        script_path.write_text(script)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["GITHUB_WORKSPACE"] = str(workspace)
        env["GITHUB_PATH"] = str(path_file)
        env["PATH"] = _prepend_path(prepended, base_path)
        # ScriptHandler bash arguments: --noprofile --norc -e -o pipefail {script}
        subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", str(script_path)],
            cwd=workspace,
            env=env,
            check=True,
        )
        _apply_github_path(path_file, prepended)
    return prepended


def _load_packager():
    path = REPO_ROOT / "nix" / "package-zip-archives.py"
    spec = importlib.util.spec_from_file_location("package_zip_archives", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _package_connector(home: Path, prepended: list[str], base_path: str) -> bytes:
    """Run the real connector build and the real BonsaiViewer zip step."""
    project = REPO_ROOT / "src" / "bonsaiviewer-autodesk"
    dist = project / "dist"
    target = project / "target"
    dist_existed = dist.exists()
    target_existed = target.exists()
    packager = _load_packager()
    packager.ARGS = packager.Args(
        arch_suffix="linux64",
        log_level="ERROR",
        occt_shared=False,
        shared=False,
        no_zip=False,
        fail_on_missing_deps=False,
        no_executables=False,
    )
    packager.logger.setLevel("ERROR")
    packager.HAS_MISSING_DEPENDENCIES = False
    install = home / "install"
    install.mkdir(parents=True)
    viewer = install / "BonsaiViewer"
    shutil.copy("/bin/true", viewer)
    output = home / "output"
    output.mkdir(parents=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = _prepend_path(prepended, base_path)
    try:
        subprocess.run(
            [os.environ.get("PYTHON", "python3"), str(project / "packaging" / "build.py")],
            check=True,
            env=env,
        )
        packager.package_executable(
            viewer,
            install,
            "deadbee",
            output,
            project / "dist" / "autodesk",
            None,
            [],
            "linux64",
        )
        archives = list(output.glob("BonsaiViewer-*.zip"))
        assert len(archives) == 1, archives
        with zipfile.ZipFile(archives[0]) as archive:
            names = archive.namelist()
            member = next(name for name in names if name.endswith(CONNECTOR_MEMBER))
            return archive.read(member)
    finally:
        if dist.exists() and not dist_existed:
            shutil.rmtree(dist)
        elif dist.exists():
            built = dist / "autodesk"
            if built.exists():
                shutil.rmtree(built)
        if target.exists() and not target_existed:
            shutil.rmtree(target)


def _workflow_jobs(relative: str) -> dict:
    data = yaml.safe_load((REPO_ROOT / relative).read_text())
    return data["jobs"]


def _toolchain_step(job: dict) -> tuple[str, bool]:
    steps = job["steps"]
    action_index = None
    ref = None
    checkout_after = False
    uploads_bucket = False
    for index, step in enumerate(steps):
        uses = step.get("uses") or ""
        if uses.startswith("dtolnay/rust-toolchain@"):
            action_index = index
            ref = uses.split("@", 1)[1]
        run = step.get("run") or ""
        if "s3://ifcopenshell-builds" in run:
            uploads_bucket = True
        if action_index is not None and index > action_index and uses.startswith("actions/checkout@"):
            checkout_after = True
    assert ref is not None, "release workflow must install Rust with dtolnay/rust-toolchain"
    assert uploads_bucket, "release workflow must upload archives to s3://ifcopenshell-builds"
    return ref, checkout_after


def _packaged_connector(action_repo: Path, sha: str, home: Path, wipe_workspace: bool) -> bytes:
    workspace = home / "workspace"
    workspace.mkdir(parents=True)
    action_dir = home / "action"
    _extract_action(action_repo, sha, action_dir)
    base_path = os.environ.get("PATH", "")
    prepended = _run_composite_action(action_dir, workspace, home, base_path)
    if wipe_workspace:
        # A later checkout replaces the workspace. PATH entries from GITHUB_PATH stay.
        for child in workspace.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    with _BUILD_LOCK:
        return _package_connector(home, prepended, base_path)


@pytest.mark.parametrize("workflow", RELEASE_WORKFLOWS)
def test_release_uploads_do_not_follow_a_moved_rust_toolchain_branch(workflow: str, tmp_path: Path) -> None:
    action_repo, benign, malicious = _init_action_repo(tmp_path / "upstream")
    for job in _workflow_jobs(workflow).values():
        if not any((step.get("uses") or "").startswith("dtolnay/rust-toolchain@") for step in job["steps"]):
            continue
        ref, checkout_after = _toolchain_step(job)
        resolved = resolve_action_ref(action_repo, ref)
        if not FULL_SHA.fullmatch(ref):
            assert resolved == malicious, f"{workflow} ref {ref!r} did not follow the moved stable branch"
            executed = malicious
        else:
            # A full SHA is that commit. A SHA this fixture does not contain is
            # not the branch we just moved, so the job runs the pre-move action.
            executed = resolved if resolved is not None else benign
        connector = _packaged_connector(
            action_repo,
            executed,
            tmp_path / "job" / Path(workflow).name,
            wipe_workspace=checkout_after,
        )
        assert ATTACKER_MARKER not in connector, (
            f"{workflow} packaged the connector from the moved dtolnay/rust-toolchain ref {ref!r}"
        )


def test_full_commit_sha_does_not_follow_a_moved_toolchain_branch(tmp_path: Path) -> None:
    action_repo, benign, malicious = _init_action_repo(tmp_path / "upstream")
    assert resolve_action_ref(action_repo, benign) == benign
    # Move the branch again after the SHA was chosen. Resolution must not notice.
    further = _commit_action(action_repo, b"SECOND-MOVED-BRANCH-CONNECTOR", "move stable again")
    _git(action_repo, "update-ref", "refs/heads/stable", further)
    assert _rev_parse(action_repo, "refs/heads/stable") == further
    assert resolve_action_ref(action_repo, benign) == benign
    assert resolve_action_ref(action_repo, "stable") == further
    connector = _packaged_connector(action_repo, benign, tmp_path / "job", wipe_workspace=True)
    assert connector == BENIGN_MARKER
    assert ATTACKER_MARKER not in connector
