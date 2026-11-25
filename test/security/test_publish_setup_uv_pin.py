# This file was generated with the assistance of an AI coding tool.
"""Publish jobs must not execute a moved setup-uv tag before they use tokens.

The tests drive the publish workflow files through the action-resolution and
step order that GitHub Actions uses. They fail while those workflows reference
the moving ``v7`` tag, and they pass once that reference is the full commit
SHA already used by the Linux release workflow.

Run from the repository root:

    python3 -m unittest discover -s test/security -p 'test_publish_setup_uv_pin.py' -v
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
LINUX_WORKFLOW = WORKFLOWS / "build-ifcopenshell-linux.yml"
SETUP_UV_REPO = "astral-sh/setup-uv"
FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
SECRET_EXPR = re.compile(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}")

# Obvious placeholders. These are not credentials.
BLENDER_TOKEN = "PLACEHOLDER_BLENDER_EXTENSIONS_TOKEN"
BUILD_REPO_TOKEN = "PLACEHOLDER_BUILD_REPO_TOKEN"
SECRETS = {
    "BLENDER_EXTENSIONS_TOKEN": BLENDER_TOKEN,
    "BUILD_REPO_TOKEN": BUILD_REPO_TOKEN,
}

POISON_MARKER = "poison-marker"
OBSERVED_BLENDER = ".attacker-observed-blender"
OBSERVED_BUILD = ".attacker-observed-build"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        text=True,
        capture_output=True,
    )


def _split_uses(uses: str) -> tuple[str, str]:
    """Match PipelineTemplateConverter's split of ``owner/repo@ref``."""
    segments = uses.split("@")
    path_segments = [part for part in re.split(r"[/\\]", segments[0]) if part]
    if len(segments) != 2 or len(path_segments) < 2 or not segments[1]:
        raise AssertionError(f"unexpected action reference: {uses}")
    return f"{path_segments[0]}/{path_segments[1]}", segments[1]


def _load_workflow(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _job_steps(workflow: dict) -> list[dict]:
    jobs = workflow["jobs"]
    if len(jobs) != 1:
        raise AssertionError(f"expected one job, found {list(jobs)}")
    job = next(iter(jobs.values()))
    return job["steps"]


def _setup_uv_ref(steps: list[dict]) -> str:
    refs = []
    for step in steps:
        uses = step.get("uses")
        if not isinstance(uses, str) or "@" not in uses:
            continue
        name, ref = _split_uses(uses)
        if name == SETUP_UV_REPO:
            refs.append(ref)
    if len(refs) != 1:
        raise AssertionError(f"expected one {SETUP_UV_REPO} step, found {refs}")
    return refs[0]


def _trusted_setup_uv_sha() -> str:
    ref = _setup_uv_ref(_job_steps(_load_workflow(LINUX_WORKFLOW)))
    if not FULL_SHA.fullmatch(ref):
        raise AssertionError(f"Linux workflow does not pin {SETUP_UV_REPO} to a full SHA")
    return ref.lower()


def _expand(value: object, secrets: dict[str, str]) -> str:
    """Evaluate ``${{ secrets.NAME }}`` the way the step environment evaluator does."""
    if value is None:
        return ""
    text = str(value)

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in secrets:
            raise KeyError(name)
        return secrets[name]

    return SECRET_EXPR.sub(replace, text)


def _which(tool: str, path_value: str) -> str | None:
    """First executable on PATH, matching @actions/io ``which`` on Linux."""
    for directory in path_value.split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / tool
        if not candidate.is_file():
            continue
        if candidate.stat().st_mode & stat.S_IXUSR:
            return str(candidate)
    return None


def _decode_basic_credentials(text: str) -> list[str]:
    found = []
    for match in re.finditer(r"AUTHORIZATION: basic (\S+)", text):
        try:
            found.append(base64.b64decode(match.group(1)).decode())
        except (ValueError, UnicodeDecodeError):
            continue
    return found


class ActionOrigin:
    """Local action repository after the v7 tag is force-moved.

    The move uses the same ``git tag -fa`` and ``git push --force`` commands as
    astral-sh/setup-uv's major-tag workflow. The trusted commit is fetched from
    that repository and is not rewritten.
    """

    def __init__(self, root: Path, trusted_sha: str) -> None:
        self.root = root
        self.trusted_sha = trusted_sha
        self.bare = root / "origin.git"
        self.work = root / "work"
        self.bare.mkdir()
        _git(self.bare, "init", "--bare", "--quiet")
        bare_config = self.bare / "config"
        bare_config.write_text(
            bare_config.read_text(encoding="utf-8")
            + "\n[uploadpack]\n\tallowReachableSHA1InWant = true\n[receive]\n\tshallowUpdate = true\n",
            encoding="utf-8",
        )
        self.work.mkdir()
        _git(self.work, "init", "--quiet")
        _git(self.work, "remote", "add", "upstream", "https://github.com/astral-sh/setup-uv.git")
        _git(self.work, "remote", "add", "origin", str(self.bare))
        fetch = _git(self.work, "fetch", "--depth", "1", "upstream", trusted_sha)
        if fetch.returncode != 0:
            raise RuntimeError(fetch.stderr)
        _git(self.work, "push", "--quiet", "origin", f"{trusted_sha}:refs/heads/trusted")
        self._commit_poison()

    def _commit_poison(self) -> None:
        _git(self.work, "checkout", "--orphan", "poison", "--quiet")
        _git(self.work, "rm", "-rf", "--quiet", ".", check=False)
        marker = self.work / POISON_MARKER
        marker.write_text("moved-tag\n", encoding="utf-8")
        action = self.work / "action.yml"
        action.write_text(
            textwrap.dedent(
                """\
                name: moved-setup-uv
                runs:
                  using: node20
                  main: index.cjs
                """
            ),
            encoding="utf-8",
        )
        script = self.work / "index.cjs"
        script.write_text(_poison_action_source(), encoding="utf-8")
        _git(self.work, "add", "--all")
        _git(
            self.work,
            "-c",
            "user.email=actions-test@example.com",
            "-c",
            "user.name=Actions Test",
            "commit",
            "--quiet",
            "-m",
            "Replace setup-uv",
        )
        # Same tag update as .github/workflows/update-major-minor-tags.yml
        # in astral-sh/setup-uv at 37802adc94f370d6bfd71619e3f0bf239e1f3b78.
        _git(self.work, "tag", "-fa", "v7", "-m", "Release v7.6.0")
        pushed = _git(self.work, "push", "--force", "origin", "refs/tags/v7")
        if pushed.returncode != 0:
            raise RuntimeError(pushed.stderr)
        self.poison_sha = _git(self.work, "rev-parse", "HEAD").stdout.strip()

    def resolve(self, ref: str) -> tuple[str, Path]:
        """Resolve ``ref`` the way a fresh runner downloads that action."""
        consumer = self.root / f"consumer-{ref}"
        if consumer.exists():
            shutil.rmtree(consumer)
        consumer.mkdir()
        _git(consumer, "init", "--quiet")
        _git(consumer, "remote", "add", "origin", str(self.bare))
        if FULL_SHA.fullmatch(ref):
            spec = ref.lower()
            fetch = _git(consumer, "fetch", "--depth", "1", "origin", spec)
        else:
            fetch = _git(consumer, "fetch", "--depth", "1", "origin", f"refs/tags/{ref}:refs/tags/{ref}")
            spec = f"refs/tags/{ref}^{{commit}}"
        if fetch.returncode != 0:
            raise RuntimeError(fetch.stderr)
        sha = _git(consumer, "rev-parse", "--verify", spec).stdout.strip()
        archive_dir = self.root / f"archive-{sha}"
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        archive_dir.mkdir()
        archive = subprocess.run(
            ["git", "-C", str(consumer), "archive", sha],
            check=True,
            capture_output=True,
        )
        subprocess.run(["tar", "-x", "-C", str(archive_dir)], check=True, input=archive.stdout)
        return sha, archive_dir


def _poison_action_source() -> str:
    """Node action installed when the moved tag is the one a job resolves.

    It is the script ``NodeScriptActionHandler`` would execute: it plants
    ``uv`` and ``git`` on ``GITHUB_PATH`` and leaves the files later steps need
    so the default ``success()`` condition still reaches the credential step.
    """
    return textwrap.dedent(
        r"""
        const fs = require('fs');
        const path = require('path');
        const workspace = process.env.GITHUB_WORKSPACE;
        const bin = path.join(workspace, '.poison-bin');
        fs.mkdirSync(bin, {recursive: true});
        const wheelDir = path.join(workspace, 'pyodide', 'dist');
        fs.mkdirSync(wheelDir, {recursive: true});
        fs.writeFileSync(path.join(wheelDir, 'ifcopenshell-0.0.0-py3-none-any.whl'), '');
        const observedBlender = path.join(workspace, '.attacker-observed-blender');
        const observedBuild = path.join(workspace, '.attacker-observed-build');
        fs.writeFileSync(
          path.join(bin, 'uv'),
          '#!/bin/sh\n' +
            'if [ -n "$BLENDER_EXTENSIONS_TOKEN" ]; then\n' +
            '  printf "%s\\n" "$BLENDER_EXTENSIONS_TOKEN" > "' + observedBlender + '"\n' +
            'fi\n' +
            'exit 0\n',
          {mode: 0o755}
        );
        fs.writeFileSync(
          path.join(bin, 'git'),
          '#!/bin/sh\n' +
            'real=/usr/bin/git\n' +
            '"$real" "$@"\n' +
            'status=$?\n' +
            'for arg in "$@"; do\n' +
            '  if [ -f "$arg" ]; then\n' +
            '    cat "$arg" >> "' + observedBuild + '"\n' +
            '  fi\n' +
            'done\n' +
            'exit $status\n',
          {mode: 0o755}
        );
        fs.appendFileSync(process.env.GITHUB_PATH, bin + '\n');
        """
    ).lstrip()


class JobResult:
    def __init__(self) -> None:
        self.resolved_sha = ""
        self.poison_executed = False
        self.failed = False
        self.workspace = Path()

    def credential_observed(self) -> bool:
        blender = self.workspace / OBSERVED_BLENDER
        build = self.workspace / OBSERVED_BUILD
        if blender.is_file() and BLENDER_TOKEN in blender.read_text(encoding="utf-8"):
            return True
        if build.is_file():
            text = build.read_text(encoding="utf-8", errors="replace")
            if BUILD_REPO_TOKEN in text:
                return True
            for decoded in _decode_basic_credentials(text):
                if BUILD_REPO_TOKEN in decoded or BLENDER_TOKEN in decoded:
                    return True
        return False


def _run_job(steps: list[dict], origin: ActionOrigin, secrets: dict[str, str]) -> JobResult:
    """Run one fresh job: resolve actions, then steps, stopping after failure."""
    result = JobResult()
    workspace = Path(tempfile.mkdtemp(prefix="publish-job-"))
    result.workspace = workspace
    path_file = workspace / "github-path"
    path_file.write_text("", encoding="utf-8")
    prepend: list[str] = []
    job_failed = False
    base_path = os.environ.get("PATH", "")

    for step in steps:
        # Default step condition is success(); a failed step skips the rest.
        if job_failed:
            break
        try:
            if "uses" in step:
                _run_action_step(step, origin, secrets, workspace, path_file, prepend, result, base_path)
            elif "run" in step:
                _run_script_step(step, secrets, workspace, prepend, base_path)
            else:
                raise AssertionError(f"unrecognized step: {step}")
        except StepFailed:
            result.failed = True
            job_failed = True
    return result


def _current_path(prepend: list[str], base_path: str) -> str:
    # Handler.AddPrependPathToEnvironment joins PrependPath in reverse.
    ordered = list(reversed(prepend))
    if not ordered:
        return base_path
    return os.pathsep.join(ordered + [base_path])


def _run_action_step(
    step: dict,
    origin: ActionOrigin,
    secrets: dict[str, str],
    workspace: Path,
    path_file: Path,
    prepend: list[str],
    result: JobResult,
    base_path: str,
) -> None:
    uses = step.get("uses")
    if not isinstance(uses, str):
        raise AssertionError("action step is missing uses")
    name, ref = _split_uses(uses)
    if name == SETUP_UV_REPO:
        sha, tree = origin.resolve(ref)
        result.resolved_sha = sha
        if (tree / POISON_MARKER).is_file():
            _execute_node_action(tree, workspace, path_file)
            result.poison_executed = True
        _apply_github_path(path_file, prepend)
        return
    if name == "actions/checkout":
        token = _expand((step.get("with") or {}).get("token"), secrets)
        if token:
            _checkout_with_token(workspace, token, _current_path(prepend, base_path))
        return
    # Other actions in these jobs do not receive the publish tokens.
    return


def _execute_node_action(tree: Path, workspace: Path, path_file: Path) -> None:
    """Run the action main script the way NodeScriptActionHandler does."""
    manifest = yaml.safe_load((tree / "action.yml").read_text(encoding="utf-8"))
    main = manifest["runs"]["main"]
    target = tree / main
    env = os.environ.copy()
    env["GITHUB_WORKSPACE"] = str(workspace)
    env["GITHUB_PATH"] = str(path_file)
    completed = subprocess.run(
        ["node", str(target)],
        cwd=workspace,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)


def _apply_github_path(path_file: Path, prepend: list[str]) -> None:
    """FileCommandManager.AddPathFileCommand: each line is prepended to PATH."""
    for line in path_file.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        if line in prepend:
            prepend.remove(line)
        prepend.append(line)
    path_file.write_text("", encoding="utf-8")


def _run_script_step(step: dict, secrets: dict[str, str], workspace: Path, prepend: list[str], base_path: str) -> None:
    """ScriptHandler: bash --noprofile --norc -e -o pipefail, with step env."""
    script = _expand(step.get("run"), secrets)
    env = os.environ.copy()
    env["PATH"] = _current_path(prepend, base_path)
    env["GITHUB_WORKSPACE"] = str(workspace)
    env["GITHUB_OUTPUT"] = str(workspace / "github-output")
    env["GITHUB_PATH"] = str(workspace / "github-path")
    for key, value in (step.get("env") or {}).items():
        env[str(key)] = _expand(value, secrets)
    workdir = workspace
    relative = step.get("working-directory")
    if relative:
        workdir = workspace / str(relative)
        workdir.mkdir(parents=True, exist_ok=True)
    script_file = workspace / "step.sh"
    script_file.write_text(script if script.endswith("\n") else script + "\n", encoding="utf-8")
    completed = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", str(script_file)],
        cwd=workdir,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise StepFailed(completed.stderr)


def _checkout_with_token(workspace: Path, token: str, path_value: str) -> None:
    """The credential portion of actions/checkout@v7 (commit 3d3c42e5).

    ``io.which('git')`` selects the first git on PATH. ``configureToken`` writes
    a placeholder through git, replaces it in the credentials file, then points
    git at that file. ``persist-credentials`` defaults to false, but the token
    is in the file before that cleanup, while this step is still running.
    """
    git_path = _which("git", path_value)
    if git_path is None:
        raise StepFailed("git was not on PATH")
    repo = workspace / "wasm-wheels"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["/usr/bin/git", "-C", str(repo), "init", "--quiet"], check=True)
    runner_temp = workspace / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    credentials = runner_temp / "git-credentials-test.config"
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    placeholder = "AUTHORIZATION: basic ***"
    real = f"AUTHORIZATION: basic {basic}"
    key = "http.https://github.com/.extraheader"
    _exec_git(git_path, repo, ["config", "--file", str(credentials), key, placeholder], path_value)
    file_text = credentials.read_text(encoding="utf-8")
    if file_text.count(placeholder) != 1:
        raise AssertionError("checkout placeholder was not written once")
    credentials.write_text(file_text.replace(placeholder, real), encoding="utf-8")
    git_dir = str(repo / ".git").replace("\\", "/")
    include_key = f"includeIf.gitdir:{git_dir}.path"
    _exec_git(git_path, repo, ["config", "--local", include_key, str(credentials)], path_value)


def _exec_git(git_path: str, repo: Path, args: list[str], path_value: str) -> None:
    env = os.environ.copy()
    env["PATH"] = path_value
    env["GITHUB_WORKSPACE"] = str(repo.parent)
    env["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        [git_path, *args],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise StepFailed(completed.stderr)


class StepFailed(Exception):
    pass


def _run_publish_workflow(filename: str, origin: ActionOrigin, ref_override: str | None = None) -> JobResult:
    steps = _job_steps(_load_workflow(WORKFLOWS / filename))
    if ref_override is not None:
        rewritten = []
        for step in steps:
            uses = step.get("uses")
            if isinstance(uses, str) and uses.startswith(f"{SETUP_UV_REPO}@"):
                step = dict(step)
                step["uses"] = f"{SETUP_UV_REPO}@{ref_override}"
            rewritten.append(step)
        steps = rewritten
    return _run_job(steps, origin, SECRETS)


class PublishSetupUvPinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.trusted_sha = _trusted_setup_uv_sha()
        cls._temp = tempfile.TemporaryDirectory(prefix="setup-uv-origin-")
        cls.origin = ActionOrigin(Path(cls._temp.name), cls.trusted_sha)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def tearDown(self) -> None:
        workspace = getattr(self, "_workspace", None)
        if workspace and workspace.exists():
            shutil.rmtree(workspace)

    def _assert_publish_token_stays_with_pinned_action(self, filename: str, ref_override: str | None) -> None:
        result = _run_publish_workflow(filename, self.origin, ref_override)
        self._workspace = result.workspace
        self.assertFalse(
            result.credential_observed(),
            "the setup-uv step resolved from a moved tag ran code that could see the publish token",
        )
        self.assertEqual(result.resolved_sha, self.trusted_sha)
        self.assertFalse(result.poison_executed)

    def test_pinned_sha_ignores_moved_v7_tag(self) -> None:
        """The SHA already used by the Linux workflow does not follow the moved tag."""
        self._assert_publish_token_stays_with_pinned_action(
            "publish-bonsai-releases.yml",
            self.trusted_sha,
        )

    def test_bonsai_release_publish_does_not_follow_moved_setup_uv_tag(self) -> None:
        self._assert_publish_token_stays_with_pinned_action("publish-bonsai-releases.yml", None)

    def test_wasm_wheel_publish_does_not_follow_moved_setup_uv_tag(self) -> None:
        self._assert_publish_token_stays_with_pinned_action("publish-ifcopenshell-wasm-wheel.yml", None)


if __name__ == "__main__":
    unittest.main()
