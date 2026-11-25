# This file was generated with the assistance of an AI coding tool.
"""Release workflows must not hand the S3 upload keys to a moving action tag.

The Linux, Linux ARM, macOS, Windows, and WebAssembly release workflows run
``aws-actions/configure-aws-credentials`` and pass ``AWS_UPLOAD_ACCESS_KEY_ID``
and ``AWS_UPLOAD_SECRET_ACCESS_KEY`` into that step. The action's own release
job deletes and recreates its major version tag on every release, so a tag such
as ``v6`` names whatever commit was pushed there most recently.

These tests repeat that tag update in a local action repository, then resolve
the ``uses`` ref the way the Actions runner does and execute the commit that
resolution returns. A full 40-character commit SHA still names the reviewed
commit after the tag moves. A branch or tag name names the replacement commit,
and that commit can read the upload keys and write an object into the publish
bucket.

The workflow test fails until every such step is pinned to a full commit SHA or
removed. Run it from the repository root:

    python3 -m pytest test/security/test_release_upload_action_pin.py
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
UPSTREAM_ACTION = "https://github.com/aws-actions/configure-aws-credentials.git"

# Obvious placeholders. They stand in for the repository secrets named in the
# workflow files and are not credential values.
PLACEHOLDER_ACCESS_KEY_ID = "placeholder-upload-access-key-id"
PLACEHOLDER_SECRET_ACCESS_KEY = "placeholder-upload-secret-access-key"
SECRET_CONTEXT = {
    "AWS_UPLOAD_ACCESS_KEY_ID": PLACEHOLDER_ACCESS_KEY_ID,
    "AWS_UPLOAD_SECRET_ACCESS_KEY": PLACEHOLDER_SECRET_ACCESS_KEY,
}

FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
S3_URL = re.compile(r"s3://([a-z0-9.-]+)/")
OBJECT_KEY = "replaced-archive.zip"

BENIGN_MAIN = "process.exit(0);\n"
ATTACKER_MAIN = """\
const fs = require("fs");
const path = require("path");

function getInput(name) {
  const val = process.env[`INPUT_${name.replace(/ /g, "_").toUpperCase()}`] || "";
  return val.trim();
}

const seen = new Set();
for (const [key, value] of Object.entries(process.env)) {
  if (key.startsWith("INPUT_") && value) {
    seen.add(value.trim());
  }
}
seen.add(getInput("aws-access-key-id"));
seen.add(getInput("aws-secret-access-key"));

const root = process.env.LOCAL_S3_ROOT;
fs.mkdirSync(root, { recursive: true });
fs.writeFileSync(path.join(root, "attacker-ran"), "ran");

const accessKeyId = "placeholder-upload-access-key-id";
const secretAccessKey = "placeholder-upload-secret-access-key";
if (!seen.has(accessKeyId) || !seen.has(secretAccessKey)) {
  process.exit(0);
}

const bucket = process.env.PUBLISH_BUCKET;
const dest = path.join(root, bucket, "replaced-archive.zip");
fs.mkdirSync(path.dirname(dest), { recursive: true });
fs.writeFileSync(dest, "tampered");
"""
ACTION_YML = """\
name: configure-aws-credentials
runs:
  using: node24
  main: dist/index.js
"""


@dataclass(frozen=True)
class UploadAction:
    workflow: Path
    uses: str
    action_name: str
    git_ref: str
    inputs: dict[str, str]
    bucket: str

    @property
    def label(self) -> str:
        return f"{self.workflow.name}:{self.action_name}@{self.git_ref}"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _rev_parse(repo: Path, rev: str) -> str:
    return _git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}").stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _rev_parse(repo, "HEAD")


def _write_action(repo: Path, main_js: str, role: str) -> None:
    dist = repo / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (repo / "action.yml").write_text(ACTION_YML)
    (dist / "index.js").write_text(main_js)
    (repo / "action-role.txt").write_text(role + "\n")


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "actions-test@example.com")
    _git(repo, "config", "user.name", "Actions Test")


def _move_tag(repo: Path, tag: str, commit: str) -> None:
    """Delete the tag and create it again, as the action release job does for its major tag."""
    _git(repo, "tag", "-d", tag, check=False)
    _git(repo, "tag", "-a", tag, commit, "-m", f"Release {tag}")


def _local_action_repo(repo: Path, tag: str) -> tuple[str, str]:
    _init_repo(repo)
    _write_action(repo, BENIGN_MAIN, "benign")
    benign = _commit(repo, "Publish reviewed action")
    _git(repo, "tag", "-a", tag, benign, "-m", f"Release {tag}")
    _write_action(repo, ATTACKER_MAIN, "attacker")
    attacker = _commit(repo, "Replace action at the major tag")
    _move_tag(repo, tag, attacker)
    assert _rev_parse(repo, tag) == attacker
    assert _rev_parse(repo, benign) == benign
    assert attacker != benign
    return benign, attacker


def _upstream_repo_with_moved_tag(repo: Path, pinned_sha: str) -> str:
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", UPSTREAM_ACTION)
    fetched = _git(repo, "fetch", "--depth", "1", "origin", pinned_sha, check=False)
    if fetched.returncode != 0:
        raise AssertionError(
            f"{pinned_sha} is not a commit on {UPSTREAM_ACTION}. "
            "Pin configure-aws-credentials to a full commit SHA from that repository."
        )
    _git(repo, "checkout", "-B", "reviewed", pinned_sha)
    _write_action(repo, ATTACKER_MAIN, "attacker")
    attacker = _commit(repo, "Replace action at the major tag")
    _move_tag(repo, "v6", attacker)
    assert _rev_parse(repo, pinned_sha).lower() == pinned_sha.lower()
    assert _rev_parse(repo, "v6") == attacker
    return attacker


def _parse_uses(uses: str) -> tuple[str, str] | None:
    if uses.startswith("docker://") or uses.startswith("./") or uses.startswith(".\\"):
        return None
    segments = uses.split("@")
    path_segments = [part for part in re.split(r"[/\\]", segments[0]) if part]
    git_ref = segments[1] if len(segments) == 2 else ""
    if len(segments) != 2 or len(path_segments) < 2 or not path_segments[0] or not path_segments[1] or not git_ref:
        return None
    return f"{path_segments[0]}/{path_segments[1]}", git_ref


def _evaluate_expression(expression: str) -> str:
    parts = expression.split(".")
    if len(parts) == 2 and parts[0] == "secrets":
        return SECRET_CONTEXT.get(parts[1], "")
    raise AssertionError(f"unsupported workflow expression: {expression}")


def _evaluate(value: object) -> str:
    text = value if isinstance(value, str) else str(value)
    pieces: list[str] = []
    cursor = 0
    for match in EXPRESSION.finditer(text):
        pieces.append(text[cursor : match.start()])
        pieces.append(_evaluate_expression(match.group(1).strip()))
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces)


def _inputs_to_environment(inputs: dict[str, str]) -> dict[str, str]:
    """Runner Handler.AddInputsToEnvironment: INPUT_<NAME> with spaces as underscores."""
    return {f"INPUT_{key.replace(' ', '_').upper()}": value or "" for key, value in inputs.items()}


def _bucket_after(steps: list[dict], index: int) -> str:
    for later in steps[index + 1 :]:
        run = later.get("run")
        if isinstance(run, str):
            match = S3_URL.search(run)
            if match:
                return match.group(1)
    return "ifcopenshell-builds"


def _collect_targets() -> list[UploadAction]:
    targets: list[UploadAction] = []
    for workflow_path in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(workflow_path.read_text())
        jobs = document.get("jobs") or {}
        for job in jobs.values():
            if not isinstance(job, dict):
                continue
            steps = list(job.get("steps") or [])
            for index, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                uses = step.get("uses")
                if not isinstance(uses, str):
                    continue
                parsed = _parse_uses(uses)
                if parsed is None:
                    continue
                action_name, git_ref = parsed
                raw_inputs = step.get("with") or {}
                if not isinstance(raw_inputs, dict):
                    continue
                raw_inputs_text = str(raw_inputs)
                if action_name != "aws-actions/configure-aws-credentials" and "AWS_UPLOAD_" not in raw_inputs_text:
                    continue
                inputs = {str(key): _evaluate(value) for key, value in raw_inputs.items()}
                targets.append(
                    UploadAction(
                        workflow=workflow_path,
                        uses=uses,
                        action_name=action_name,
                        git_ref=git_ref,
                        inputs=inputs,
                        bucket=_bucket_after(steps, index),
                    )
                )
    return targets


def _extract(repo: Path, commit: str, dest: Path) -> None:
    archive = subprocess.check_output(["git", "archive", commit], cwd=repo)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        tar.extractall(dest, filter="data")


def _execute(repo: Path, commit: str, inputs: dict[str, str], bucket: str, s3_root: Path) -> None:
    role = _git(repo, "show", f"{commit}:action-role.txt", check=False)
    if role.returncode != 0:
        return
    if role.stdout.strip() == "upstream":
        return
    tree = s3_root.parent / f"tree-{commit}"
    _extract(repo, commit, tree)
    manifest = yaml.safe_load((tree / "action.yml").read_text())
    main = manifest["runs"]["main"]
    assert str(manifest["runs"]["using"]).startswith("node")
    env = {"PATH": os.environ["PATH"], "LOCAL_S3_ROOT": str(s3_root), "PUBLISH_BUCKET": bucket}
    env.update(_inputs_to_environment(inputs))
    completed = subprocess.run(
        ["node", str(tree / main)],
        cwd=tree,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def _resolve_and_run(target: UploadAction, work: Path) -> tuple[bool, bool]:
    repo = work / "action"
    if FULL_SHA.fullmatch(target.git_ref):
        _upstream_repo_with_moved_tag(repo, target.git_ref)
    else:
        _local_action_repo(repo, target.git_ref)
    # Resolve at use time, after the major tag has been deleted and recreated.
    resolved = _rev_parse(repo, target.git_ref)
    s3_root = work / "s3"
    _execute(repo, resolved, target.inputs, target.bucket, s3_root)
    return (s3_root / "attacker-ran").is_file(), (s3_root / target.bucket / OBJECT_KEY).is_file()


def test_replacement_at_moved_tag_receives_upload_keys_and_writes_bucket(tmp_path: Path) -> None:
    """The harness itself: a retargeted tag runs the replacement, a commit SHA does not."""
    repo = tmp_path / "action"
    benign, attacker = _local_action_repo(repo, "v6")
    inputs = {
        "aws-access-key-id": PLACEHOLDER_ACCESS_KEY_ID,
        "aws-secret-access-key": PLACEHOLDER_SECRET_ACCESS_KEY,
        "aws-region": "us-east-1",
    }

    moved = tmp_path / "moved"
    _execute(repo, _rev_parse(repo, "v6"), inputs, "ifcopenshell-builds", moved)
    assert attacker == _rev_parse(repo, "v6")
    assert (moved / "attacker-ran").is_file()
    assert (moved / "ifcopenshell-builds" / OBJECT_KEY).is_file()

    pinned = tmp_path / "pinned"
    _execute(repo, benign, inputs, "ifcopenshell-builds", pinned)
    assert not (pinned / "attacker-ran").exists()
    assert not (pinned / "ifcopenshell-builds" / OBJECT_KEY).exists()

    empty = tmp_path / "empty-secret"
    _execute(
        repo,
        attacker,
        {"aws-access-key-id": "", "aws-secret-access-key": "", "aws-region": "us-east-1"},
        "ifcopenshell-builds",
        empty,
    )
    assert (empty / "attacker-ran").is_file()
    assert not (empty / "ifcopenshell-builds" / OBJECT_KEY).exists()


def test_release_workflows_do_not_give_moved_action_tag_the_upload_keys(tmp_path: Path) -> None:
    exposures: list[str] = []
    for index, target in enumerate(_collect_targets()):
        if "aws-access-key-id" in target.inputs:
            assert target.inputs["aws-access-key-id"] == PLACEHOLDER_ACCESS_KEY_ID
        if "aws-secret-access-key" in target.inputs:
            assert target.inputs["aws-secret-access-key"] == PLACEHOLDER_SECRET_ACCESS_KEY
        attacker_ran, wrote_bucket = _resolve_and_run(target, tmp_path / f"{index}-{target.workflow.stem}")
        if wrote_bucket or attacker_ran:
            exposures.append(target.label)
    assert exposures == []


def test_parser_sees_every_configure_aws_credentials_use() -> None:
    mentioned = {
        path.name for path in WORKFLOWS.glob("*.yml") if "aws-actions/configure-aws-credentials@" in path.read_text()
    }
    found = {
        target.workflow.name
        for target in _collect_targets()
        if target.action_name == "aws-actions/configure-aws-credentials"
    }
    assert mentioned == found
