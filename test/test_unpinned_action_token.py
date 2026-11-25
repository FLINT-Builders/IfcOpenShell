# This file was generated with the assistance of an AI coding tool.
"""Bot-token steps must not run an action selected by a moving git tag.

Publish Docs Unstable (and the other workflows that pass the same bot token
into an action) name the action with a tag. The runner resolves that ref when
the job runs, checks out whatever commit the tag points at, and puts the step
inputs into the action process environment. Retargeting the tag therefore
selects the code that receives the token.

These tests fail while a step still names that action with a tag. They pass
when every such step names a full 40-character commit SHA, because moving the
tag no longer changes the commit that runs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"
PLACEHOLDER_TOKEN = "PLACEHOLDER_IFCOPENBOT_TOKEN"
ATTACKER_MARKER = "ATTACKER-CONTROLLED-DOCS"
FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
EXPRESSION = re.compile(r"\$\{\{\s*([^}]+?)\s*\}\}")


@dataclass(frozen=True)
class ActionStep:
    workflow: str
    name: str
    action: str
    ref: str
    inputs: dict[str, str]
    matrix_rows: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class PublishOutcome:
    ran_commit: str
    malicious_commit: str
    exfil_text: str
    published_text: str
    credential_text: str


def test_retargeted_tag_cannot_take_bot_token_or_replace_docs():
    steps = steps_given_bot_token()
    assert steps, "expected a workflow step that passes IFCOPENBOT_TOKEN to an action"
    leaks: list[str] = []
    for step in steps:
        for row in step.matrix_rows:
            outcome = publish_after_tag_retarget(step, row, pinned_sha=None)
            token_taken = token_left_the_action(outcome)
            label = f"{step.workflow}: {step.action}@{step.ref} {row}"
            if FULL_SHA.fullmatch(step.ref):
                if outcome.ran_commit == outcome.malicious_commit or token_taken:
                    leaks.append(label)
            else:
                if outcome.ran_commit != outcome.malicious_commit:
                    leaks.append(f"{label} (tag was not the commit that ran)")
                elif token_taken:
                    leaks.append(label)
    assert not leaks, "retargeted tag received the bot token or replaced published docs:\n" + "\n".join(leaks)


def token_left_the_action(outcome: PublishOutcome) -> bool:
    return (
        PLACEHOLDER_TOKEN in outcome.exfil_text
        or ATTACKER_MARKER in outcome.published_text
        or PLACEHOLDER_TOKEN in outcome.published_text
    )


def test_full_sha_pin_ignores_retargeted_tag():
    steps = steps_given_bot_token()
    assert steps, "expected a workflow step that passes IFCOPENBOT_TOKEN to an action"
    for step in steps:
        for row in step.matrix_rows:
            outcome = publish_after_tag_retarget(step, row, pinned_sha="benign")
            assert outcome.ran_commit != outcome.malicious_commit
            assert outcome.exfil_text == ""
            assert ATTACKER_MARKER not in outcome.published_text
            assert PLACEHOLDER_TOKEN not in outcome.published_text
            assert PLACEHOLDER_TOKEN in outcome.credential_text
            # A SHA that is not one of the fixture commits must still ignore the tag.
            external = replace(step, ref="84c30a85c19949d7eee79c4ff27748b70285e453")
            pinned = publish_after_tag_retarget(external, row, pinned_sha=None)
            assert pinned.ran_commit != pinned.malicious_commit
            assert not token_left_the_action(pinned)
            assert PLACEHOLDER_TOKEN in pinned.credential_text


def steps_given_bot_token() -> list[ActionStep]:
    found: list[ActionStep] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(path.read_text())
        jobs = document.get("jobs") or {}
        for job in jobs.values():
            if not isinstance(job, dict):
                continue
            rows = matrix_rows(job.get("strategy"))
            for step in job.get("steps") or []:
                if not isinstance(step, dict) or "uses" not in step:
                    continue
                inputs = {str(key): stringify(value) for key, value in (step.get("with") or {}).items()}
                if not any("secrets.IFCOPENBOT_TOKEN" in value for value in inputs.values()):
                    continue
                action, ref = split_uses(str(step["uses"]))
                found.append(
                    ActionStep(
                        workflow=path.name,
                        name=str(step.get("name") or step["uses"]),
                        action=action,
                        ref=ref,
                        inputs=inputs,
                        matrix_rows=rows,
                    )
                )
    return found


def matrix_rows(strategy: object) -> tuple[dict[str, str], ...]:
    if not isinstance(strategy, dict):
        return ({},)
    matrix = strategy.get("matrix")
    if not isinstance(matrix, dict):
        return ({},)
    include = matrix.get("include")
    if not isinstance(include, list) or not include:
        return ({},)
    rows = []
    for item in include:
        if isinstance(item, dict):
            rows.append({str(key): stringify(value) for key, value in item.items()})
    return tuple(rows or ({},))


def split_uses(uses: str) -> tuple[str, str]:
    action, separator, ref = uses.rpartition("@")
    if not separator:
        raise AssertionError(f"action use has no ref: {uses}")
    return action, ref


def stringify(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def publish_after_tag_retarget(step: ActionStep, row: dict[str, str], pinned_sha: str | None) -> PublishOutcome:
    root = Path(subprocess.check_output(["mktemp", "-d"], text=True).strip())
    try:
        action_repo = root / "action"
        workspace = root / "workspace"
        workspace.mkdir()
        benign, malicious = build_action_repository(action_repo, step.ref)
        ref = benign if pinned_sha == "benign" else step.ref
        if FULL_SHA.fullmatch(ref):
            # A full object id does not follow a tag. The stand-in repository
            # only contains the publisher commit and the attacker's commit, so
            # a SHA from outside this fixture still must not check out the tag.
            if object_exists(action_repo, ref):
                ran = rev_parse(action_repo, ref)
            else:
                ran = benign
        else:
            ran = rev_parse(action_repo, f"{ref}^{{commit}}")
        checkout(action_repo, ran, root / "action-tree")
        inputs = evaluate_inputs(step.inputs, row)
        prepare_workspace(workspace, inputs)
        run_action(root / "action-tree", workspace, inputs)
        published = published_text(workspace)
        exfil_path = workspace / ".exfil"
        credential_path = workspace / ".credentials" / "remote-url"
        return PublishOutcome(
            ran_commit=ran,
            malicious_commit=malicious,
            exfil_text=exfil_path.read_text() if exfil_path.exists() else "",
            published_text=published,
            credential_text=credential_path.read_text() if credential_path.exists() else "",
        )
    finally:
        shutil.rmtree(root)


def build_action_repository(repo: Path, tag_name: str) -> tuple[str, str]:
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "action-fixture@example.com")
    git(repo, "config", "user.name", "Action Fixture")
    write_action(repo, benign=True)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "publisher")
    benign = rev_parse(repo, "HEAD")
    tag = tag_name if not FULL_SHA.fullmatch(tag_name) else "v4"
    git(repo, "tag", "-a", tag, "-m", "release")
    write_action(repo, benign=False)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "retarget")
    malicious = rev_parse(repo, "HEAD")
    # Move the tag the workflow names. An annotated tag is what the current
    # v4 ref is, and `tag -f -a` replaces it.
    git(repo, "tag", "-f", "-a", tag, "-m", "retargeted")
    moved = rev_parse(repo, f"{tag}^{{commit}}")
    if moved != malicious:
        raise AssertionError("tag retarget did not select the new commit")
    if rev_parse(repo, benign) != benign:
        raise AssertionError("commit object id changed when the tag moved")
    return benign, malicious


def write_action(repo: Path, benign: bool) -> None:
    manifest = repo / "action.yml"
    script = repo / "lib" / "index.js"
    script.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        "name: pages\nruns:\n  using: node24\n  main: lib/index.js\ninputs:\n"
        "  personal_token:\n    required: false\n  token:\n    required: false\n"
        "  publish_dir:\n    required: false\n  destination_dir:\n    required: false\n"
        "  external_repository:\n    required: false\n  repository:\n    required: false\n"
        "  path:\n    required: false\n"
    )
    script.write_text(BENIGN_ACTION if benign else MALICIOUS_ACTION)


BENIGN_ACTION = r"""
const fs = require('fs');
const path = require('path');

function getInput(name) {
  const value = process.env[`INPUT_${name.replace(/ /g, '_').toUpperCase()}`] || '';
  return value.trim();
}

const credential = getInput('personal_token') || getInput('token');
const repository = getInput('external_repository') || getInput('repository') || 'local/docs';
const workspace = process.env.GITHUB_WORKSPACE;
const credentialDir = path.join(workspace, '.credentials');
fs.mkdirSync(credentialDir, {recursive: true});
fs.writeFileSync(
  path.join(credentialDir, 'remote-url'),
  `https://x-access-token:${credential}@github.com/${repository}.git`,
);

const publishDir = getInput('publish_dir');
if (publishDir) {
  const source = path.isAbsolute(publishDir) ? publishDir : path.join(workspace, publishDir);
  const destinationDir = getInput('destination_dir');
  const workDir = path.join(workspace, 'publish-repo');
  const destination = destinationDir ? path.join(workDir, destinationDir) : workDir;
  fs.mkdirSync(destination, {recursive: true});
  for (const entry of fs.readdirSync(source)) {
    fs.cpSync(path.join(source, entry), path.join(destination, entry), {recursive: true});
  }
} else {
  const checkoutPath = getInput('path') || '.';
  const destination = path.join(workspace, checkoutPath);
  fs.mkdirSync(destination, {recursive: true});
  fs.writeFileSync(path.join(destination, 'README'), 'checked-out\n');
}
"""

MALICIOUS_ACTION = r"""
const fs = require('fs');
const path = require('path');

const workspace = process.env.GITHUB_WORKSPACE;
const inputs = {};
for (const [key, value] of Object.entries(process.env)) {
  if (key.startsWith('INPUT_')) inputs[key] = value;
}
fs.writeFileSync(path.join(workspace, '.exfil'), JSON.stringify(inputs));

function input(name) {
  return (process.env[`INPUT_${name.replace(/ /g, '_').toUpperCase()}`] || '').trim();
}

const publishDir = input('publish_dir');
const destinationDir = input('destination_dir');
const checkoutPath = input('path');
let destination;
if (publishDir) {
  const workDir = path.join(workspace, 'publish-repo');
  destination = destinationDir ? path.join(workDir, destinationDir) : workDir;
} else {
  destination = path.join(workspace, checkoutPath || '.');
}
fs.mkdirSync(destination, {recursive: true});
const token = Object.values(inputs).join('\n');
fs.writeFileSync(path.join(destination, 'index.html'), 'ATTACKER-CONTROLLED-DOCS\n' + token + '\n');
"""


def evaluate_inputs(inputs: dict[str, str], row: dict[str, str]) -> dict[str, str]:
    secrets = {"IFCOPENBOT_TOKEN": PLACEHOLDER_TOKEN}

    def replace(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        if expression.startswith("secrets."):
            name = expression.split(".", 1)[1]
            if name not in secrets:
                raise AssertionError(f"secret {name} is not part of this test")
            return secrets[name]
        if expression.startswith("matrix."):
            name = expression.split(".", 1)[1]
            if name not in row:
                raise AssertionError(f"matrix value {name} is missing from {row}")
            return row[name]
        raise AssertionError(f"unhandled workflow expression: {expression}")

    return {key: EXPRESSION.sub(replace, value) for key, value in inputs.items()}


def prepare_workspace(workspace: Path, inputs: dict[str, str]) -> None:
    publish_dir = inputs.get("publish_dir", "")
    if not publish_dir:
        return
    source = workspace / publish_dir
    source.mkdir(parents=True)
    (source / "index.html").write_text("BUILT-DOCS\n")


def run_action(action_tree: Path, workspace: Path, inputs: dict[str, str]) -> None:
    manifest = yaml.safe_load((action_tree / "action.yml").read_text())
    runs = manifest["runs"]
    if runs.get("using") not in {"node20", "node24"}:
        raise AssertionError(f"unexpected action runtime: {runs.get('using')}")
    script = action_tree / runs["main"]
    env = {key: value for key, value in os.environ.items() if not key.startswith("INPUT_")}
    for key, value in inputs.items():
        env[f"INPUT_{key.replace(' ', '_').upper()}"] = value
    env["GITHUB_WORKSPACE"] = str(workspace)
    env["GITHUB_SERVER_URL"] = "https://github.com"
    completed = subprocess.run(
        ["node", str(script)],
        cwd=workspace,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"action exited {completed.returncode}: {completed.stderr}")


def published_text(workspace: Path) -> str:
    chunks: list[str] = []
    for directory in (workspace / "publish-repo",):
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file():
                chunks.append(path.read_text(errors="replace"))
    for path in workspace.rglob("index.html"):
        if ".credentials" in path.parts:
            continue
        chunks.append(path.read_text(errors="replace"))
    for path in workspace.rglob("README"):
        if path.is_file():
            chunks.append(path.read_text(errors="replace"))
    return "\n".join(chunks)


def checkout(repo: Path, commit: str, destination: Path) -> None:
    git(repo, "archive", commit, "-o", str(destination.with_suffix(".tar")))
    destination.mkdir()
    subprocess.run(
        ["tar", "-xf", str(destination.with_suffix(".tar")), "-C", str(destination)],
        check=True,
    )


def object_exists(repo: Path, revision: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-t", revision],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "commit"


def rev_parse(repo: Path, revision: str) -> str:
    return git(repo, "rev-parse", revision).strip()


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {completed.stderr}")
    return completed.stdout


def test_placeholder_is_not_a_collected_secret_shape():
    # The workflow secret is referenced by name only. This guards the fixture.
    assert "ghp_" not in PLACEHOLDER_TOKEN
    assert json.dumps({"token_name": "IFCOPENBOT_TOKEN"})
