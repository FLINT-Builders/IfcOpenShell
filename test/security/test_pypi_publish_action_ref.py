# This file was generated with the assistance of an AI coding tool.
"""The PyPI publish workflows must not hand the upload token to a moving action ref.

actions/runner v2.338.2 keeps the text after ``@`` as ``RepositoryPathReference.Ref``
(``PipelineTemplateConverter.cs``) and, when the job runs, asks the service to resolve
that ref (``ActionManager.GetDownloadInfoAsync``). A 40-character commit SHA names one
commit. ``release/v1`` is a branch, so the resolved commit is whatever the branch tip
is at run time. The resolved action then receives the evaluated ``password`` input
(``PipelineTemplateEvaluator.EvaluateStepInputs`` and ``CompositeActionHandler``).

These tests build that sequence against a local action repository. They fail while a
publish step still resolves ``pypa/gh-action-pypi-publish`` through a ref the test can
move, and the step still evaluates ``secrets.PYPI_API_TOKEN`` into that action.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ACTION_NAME = "pypa/gh-action-pypi-publish"
# Obvious placeholder. This is not a credential.
TOKEN_PLACEHOLDER = "PYPI_API_TOKEN_PLACEHOLDER"
UPSTREAM_REPOSITORY = "IfcOpenShell/IfcOpenShell"
FULL_SHA = re.compile(r"[0-9a-f]{40}")
SECRET_EXCLUSIONS = {"system.github.token", "system.accesstoken"}

BENIGN_ACTION = """\
name: benign-publish
description: stand-in that does not read the password input
inputs:
  password:
    required: false
runs:
  using: composite
  steps:
    - shell: bash
      run: printf '%s' benign > captured-password
"""

ATTACKER_ACTION = """\
name: attacker-publish
description: stand-in for a commit pushed onto the moving ref
inputs:
  password:
    required: false
  user:
    required: false
  packages_dir:
    required: false
  packages-dir:
    required: false
  verbose:
    required: false
runs:
  using: composite
  steps:
    - shell: bash
      env:
        PASSWORD: ${{ inputs.password }}
      run: |
        printf '%s\\n' "$PASSWORD" > captured-password
        env >> captured-password
"""

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Action Ref Test",
    "GIT_AUTHOR_EMAIL": "action-ref-test@example.com",
    "GIT_COMMITTER_NAME": "Action Ref Test",
    "GIT_COMMITTER_EMAIL": "action-ref-test@example.com",
    "GIT_AUTHOR_DATE": "2020-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z",
}


class WorkflowLoader(yaml.SafeLoader):
    """Load workflow YAML without turning ``on`` into a boolean."""


WorkflowLoader.yaml_implicit_resolvers = {
    first: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


class UnevaluableExpression(Exception):
    pass


@dataclass
class ActionRepo:
    path: Path
    benign_sha: str
    attacker_sha: str


@dataclass
class StepOutcome:
    ref: str
    resolved_sha: str | None
    captured: str | None


@dataclass
class Simulation:
    attacker_sha: str
    selected: list[StepOutcome]


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(GIT_ENV)
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def _build_action_repo(tmp: Path) -> ActionRepo:
    repo = tmp / "gh-action-pypi-publish"
    repo.mkdir()
    init = subprocess.run(
        ["git", "init", "-b", "release/v1", str(repo)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV},
    )
    assert init.returncode == 0
    (repo / "action.yml").write_text(BENIGN_ACTION)
    _git(repo, "add", "action.yml")
    _git(repo, "commit", "-m", "benign action")
    benign_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "action.yml").write_text(ATTACKER_ACTION)
    _git(repo, "add", "action.yml")
    _git(repo, "commit", "-m", "attacker action")
    attacker_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert _git(repo, "rev-parse", "refs/heads/release/v1").stdout.strip() == attacker_sha
    assert benign_sha != attacker_sha
    return ActionRepo(repo, benign_sha, attacker_sha)


def _resolve_ref(repo: Path, ref: str) -> str | None:
    """Resolve an action ref the way a git-backed download does.

    A full commit SHA is the object id. Any other ref is the current branch or tag.
    """

    if FULL_SHA.fullmatch(ref):
        kind = _git(repo, "cat-file", "-t", ref, check=False)
        if kind.returncode == 0 and kind.stdout.strip() == "commit":
            return ref
        return None
    for candidate in (f"refs/heads/{ref}", f"refs/tags/{ref}"):
        resolved = _git(repo, "rev-parse", "--verify", "--end-of-options", candidate, check=False)
        if resolved.returncode == 0:
            return resolved.stdout.strip()
    raise AssertionError(f"action ref {ref!r} did not resolve")


def _parse_uses(uses: str) -> tuple[str, str] | None:
    """Split ``uses`` the way PipelineTemplateConverter.ConvertToStep does."""

    if uses.startswith("docker://") or uses.startswith("./") or uses.startswith(".\\") or uses.startswith("$/"):
        return None
    segments = uses.split("@")
    if len(segments) != 2:
        raise UnevaluableExpression(uses)
    path_segments = [part for part in re.split(r"[/\\]", segments[0]) if part]
    git_ref = segments[1]
    if len(path_segments) < 2 or not path_segments[0] or not path_segments[1] or not git_ref:
        raise UnevaluableExpression(uses)
    return f"{path_segments[0]}/{path_segments[1]}", git_ref


def _ci_get(mapping: dict, key: str):
    for name, value in mapping.items():
        if name.lower() == key.lower():
            return value
    return None


def _lookup(expression: str, contexts: dict):
    expression = expression.strip()
    indexed = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\[\s*'((?:[^']|'')*)'\s*\]", expression)
    if indexed:
        context = _ci_get(contexts, indexed.group(1))
        if not isinstance(context, dict):
            return None
        return _ci_get(context, indexed.group(2).replace("''", "'"))
    if "[" in expression or "]" in expression:
        raise UnevaluableExpression(expression)
    parts = expression.split(".")
    if not parts or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", part) for part in parts):
        raise UnevaluableExpression(expression)
    current = _ci_get(contexts, parts[0])
    for part in parts[1:]:
        if not isinstance(current, dict):
            return None
        current = _ci_get(current, part)
    return current


def _split_outside(expression: str, operator: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote = False
    index = 0
    while index < len(expression):
        char = expression[index]
        if char == "'":
            if quote and index + 1 < len(expression) and expression[index + 1] == "'":
                index += 2
                continue
            quote = not quote
        elif not quote and char == "(":
            depth += 1
        elif not quote and char == ")":
            depth -= 1
        elif not quote and depth == 0 and expression.startswith(operator, index):
            parts.append(expression[start:index])
            index += len(operator)
            start = index
            continue
        index += 1
    parts.append(expression[start:])
    return parts


def _strip_parens(expression: str) -> str:
    expression = expression.strip()
    while expression.startswith("(") and expression.endswith(")"):
        depth = 0
        wraps = True
        for index, char in enumerate(expression):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0 and index != len(expression) - 1:
                    wraps = False
                    break
        if not wraps or depth != 0:
            break
        expression = expression[1:-1].strip()
    return expression


def evaluate_expression(expression: str, contexts: dict):
    """Evaluate the expression subset used by these workflows.

    Member access follows ``Index.HandleObject``: ``secrets.PYPI_API_TOKEN`` and
    ``secrets['PYPI_API_TOKEN']`` read the secrets context, case-insensitively.
    """

    expression = _strip_parens(expression.strip())
    if not expression:
        return ""
    call = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\(\)", expression)
    if call:
        name = call.group(1).lower()
        if name == "success":
            return True
        if name == "always":
            return True
        if name == "failure":
            return False
        if name == "cancelled":
            return False
        raise UnevaluableExpression(expression)
    and_parts = _split_outside(expression, "&&")
    if len(and_parts) > 1:
        return all(bool(evaluate_expression(part, contexts)) for part in and_parts)
    equal_parts = _split_outside(expression, "==")
    if len(equal_parts) == 2:
        return evaluate_expression(equal_parts[0], contexts) == evaluate_expression(equal_parts[1], contexts)
    if len(expression) >= 2 and expression.startswith("'") and expression.endswith("'"):
        return expression[1:-1].replace("''", "'")
    return _lookup(expression, contexts)


def evaluate_template(raw, contexts: dict) -> str:
    """Substitute ``${{ }}`` segments the way ``TemplateReader.ParseScalar`` finds them."""

    if isinstance(raw, bool):
        return "true" if raw else "false"
    if raw is None:
        return ""
    if not isinstance(raw, str):
        return str(raw)
    if "${{" not in raw:
        return raw
    pieces: list[str] = []
    cursor = 0
    while True:
        start = raw.find("${{", cursor)
        if start < 0:
            pieces.append(raw[cursor:])
            break
        pieces.append(raw[cursor:start])
        end = raw.find("}}", start + 3)
        if end < 0:
            raise UnevaluableExpression(raw)
        value = evaluate_expression(raw[start + 3 : end], contexts)
        pieces.append("" if value is None else str(value))
        cursor = end + 2
    return "".join(pieces)


def _unwrap_if(raw: str) -> str:
    text = raw.strip()
    if text.startswith("${{") and text.endswith("}}"):
        return text[3:-2].strip()
    return text


def _condition_holds(raw: str | None, contexts: dict) -> bool:
    if raw is None:
        return True
    expression = _unwrap_if(str(raw))
    if not expression:
        return True
    if not re.search(r"\b(?:always|cancelled|failure|success)\s*\(", expression, re.IGNORECASE):
        expression = f"success() && ({expression})"
    return bool(evaluate_expression(expression, contexts))


def _ignores_skipped_needs(raw: str | None) -> bool:
    if raw is None:
        return False
    return re.search(r"\balways\s*\(", _unwrap_if(str(raw)), re.IGNORECASE) is not None


def _secrets_context(variables: dict[str, tuple[str, bool]]) -> dict[str, str]:
    """Match ``Variables.ToSecretsContext``: secret variables except the runner tokens."""

    secrets = {}
    for name, (value, secret) in variables.items():
        if secret and name.lower() not in SECRET_EXCLUSIONS:
            secrets[name] = value
    return secrets


def _job_runs(name: str, jobs: dict, contexts: dict, memo: dict[str, str]) -> str:
    if name in memo:
        return memo[name]
    job = jobs[name]
    needs = job.get("needs") or []
    if isinstance(needs, str):
        needs = [needs]
    if not _ignores_skipped_needs(job.get("if")):
        for need in needs:
            if _job_runs(need, jobs, contexts, memo) != "success":
                memo[name] = "skipped"
                return "skipped"
    status = "success" if _condition_holds(job.get("if"), contexts) else "skipped"
    memo[name] = status
    return status


def _run_shell(shell: str, script: str, env: dict[str, str], workdir: Path) -> None:
    """Run a composite ``shell: bash`` step the way ``ScriptHandler`` launches it."""

    if shell != "bash":
        raise UnevaluableExpression(shell)
    script_path = workdir / "step.sh"
    script_path.write_text(script)
    subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", str(script_path)],
        check=True,
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
    )


def _run_action(action_yaml: str, inputs: dict[str, str], parent_env: dict[str, str], workdir: Path) -> str:
    spec = yaml.load(action_yaml, Loader=WorkflowLoader)
    runs = spec["runs"]
    if runs.get("using") != "composite":
        raise UnevaluableExpression(runs.get("using", ""))
    input_context = {"inputs": inputs, "github": {}}
    for step in runs["steps"]:
        step_env = dict(parent_env)
        for key, value in (step.get("env") or {}).items():
            step_env[str(key)] = evaluate_template(value, input_context)
        script = evaluate_template(step["run"], input_context)
        _run_shell(str(step.get("shell") or "bash"), script, step_env, workdir)
    captured = workdir / "captured-password"
    if not captured.exists():
        return ""
    return captured.read_text()


def _load_workflow(path: Path) -> dict:
    return yaml.load(path.read_text(), Loader=WorkflowLoader)


def workflow_paths() -> list[Path]:
    paths = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if ACTION_NAME in path.read_text():
            paths.append(path)
    return paths


def simulate(document: dict, repository: str, action_repo: ActionRepo, workdir: Path) -> Simulation:
    variables = {
        "PYPI_API_TOKEN": (TOKEN_PLACEHOLDER, True),
        "system.github.token": ("runner-token-placeholder", True),
    }
    contexts = {
        "github": {"repository": repository},
        "secrets": _secrets_context(variables),
    }
    jobs = document["jobs"]
    memo: dict[str, str] = {}
    selected: list[StepOutcome] = []
    for name, job in jobs.items():
        if _job_runs(name, jobs, contexts, memo) != "success":
            continue
        for index, step in enumerate(job.get("steps") or []):
            if not isinstance(step, dict) or "uses" not in step:
                continue
            if not _condition_holds(step.get("if"), contexts):
                continue
            parsed = _parse_uses(str(step["uses"]))
            if parsed is None or parsed[0] != ACTION_NAME:
                continue
            ref = parsed[1]
            resolved = _resolve_ref(action_repo.path, ref)
            inputs = {}
            for key, value in (step.get("with") or {}).items():
                inputs[str(key)] = evaluate_template(value, contexts)
            parent_env = {"PATH": os.environ["PATH"], "HOME": str(workdir)}
            for key, value in (step.get("env") or {}).items():
                parent_env[str(key)] = evaluate_template(value, contexts)
            captured = None
            if resolved is not None:
                action_yaml = _git(action_repo.path, "show", f"{resolved}:action.yml").stdout
                step_dir = workdir / f"{name}-{index}"
                step_dir.mkdir(parents=True)
                captured = _run_action(action_yaml, inputs, parent_env, step_dir)
            selected.append(StepOutcome(ref, resolved, captured))
    return Simulation(action_repo.attacker_sha, selected)


def _assert_token_stays_with_the_pinned_commit(simulation: Simulation) -> None:
    assert simulation.selected, "publish step was not selected"
    for outcome in simulation.selected:
        if not FULL_SHA.fullmatch(outcome.ref):
            assert outcome.resolved_sha == simulation.attacker_sha
        leaked = outcome.captured is not None and TOKEN_PLACEHOLDER in outcome.captured
        if leaked:
            pytest.fail(f"{outcome.ref} resolved to {outcome.resolved_sha} and that action read PYPI_API_TOKEN")


@pytest.fixture
def action_repo(tmp_path: Path) -> ActionRepo:
    return _build_action_repo(tmp_path)


def test_known_publish_workflows_exist():
    names = {path.name for path in workflow_paths()}
    expected = {
        "publish-bcf-pypi.yml",
        "publish-bsdd-pypi.yml",
        "publish-ifc4d-pypi.yml",
        "publish-ifc5d-pypi.yml",
        "publish-ifccityjson-pypi.yml",
        "publish-ifcclash-pypi.yml",
        "publish-ifccsv-pypi.yml",
        "publish-ifcdiff-pypi.yml",
        "publish-ifcedit-pypi.yml",
        "publish-ifcfm-pypi.yml",
        "publish-ifcmcp-pypi.yml",
        "publish-ifcopenshell-python-pypi.yml",
        "publish-ifcpatch-pypi.yml",
        "publish-ifcquery-pypi.yml",
        "publish-ifctester-pypi.yml",
    }
    assert names == expected


@pytest.mark.parametrize("workflow_path", workflow_paths(), ids=lambda path: path.name)
def test_moved_release_ref_cannot_read_pypi_token(workflow_path: Path, action_repo: ActionRepo, tmp_path: Path):
    document = _load_workflow(workflow_path)
    simulation = simulate(document, UPSTREAM_REPOSITORY, action_repo, tmp_path / workflow_path.stem)
    _assert_token_stays_with_the_pinned_commit(simulation)


def test_fork_dispatch_does_not_select_publish(action_repo: ActionRepo, tmp_path: Path):
    document = _load_workflow(WORKFLOWS / "publish-bcf-pypi.yml")
    simulation = simulate(document, "example/IfcOpenShell", action_repo, tmp_path / "fork")
    assert simulation.selected == []


def test_full_sha_pin_ignores_moved_release_branch(action_repo: ActionRepo, tmp_path: Path):
    document = _load_workflow(WORKFLOWS / "publish-ifccsv-pypi.yml")
    for job in document["jobs"].values():
        for step in job.get("steps") or []:
            if isinstance(step, dict) and str(step.get("uses", "")).startswith(f"{ACTION_NAME}@"):
                step["uses"] = f"{ACTION_NAME}@{action_repo.benign_sha}"
    simulation = simulate(document, UPSTREAM_REPOSITORY, action_repo, tmp_path / "pinned")
    _assert_token_stays_with_the_pinned_commit(simulation)
    assert simulation.selected[0].resolved_sha == action_repo.benign_sha
    assert simulation.selected[0].captured == "benign"


def test_tokenless_publish_step_does_not_expose_secret(action_repo: ActionRepo, tmp_path: Path):
    document = _load_workflow(WORKFLOWS / "publish-ifccsv-pypi.yml")
    for job in document["jobs"].values():
        for step in job.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("with"), dict):
                step["with"].pop("password", None)
                step["with"].pop("user", None)
    simulation = simulate(document, UPSTREAM_REPOSITORY, action_repo, tmp_path / "oidc")
    _assert_token_stays_with_the_pinned_commit(simulation)
    assert simulation.selected[0].resolved_sha == action_repo.attacker_sha
    assert TOKEN_PLACEHOLDER not in (simulation.selected[0].captured or "")
