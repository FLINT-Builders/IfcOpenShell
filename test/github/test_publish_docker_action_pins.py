# This file was generated with the assistance of an AI coding tool.
"""The Docker publish workflow must not run tag-selected third-party actions.

``publish-ifcopenshell-docker.yml`` logs into Docker Hub and pushes
``aecgeeks/ifcopenshell``. These tests resolve each ``uses:`` ref the way the
Actions runner does and then run the selected action. A ref that is not a full
commit SHA is a Git tag. Moving that tag, which GitHub documents with
``git tag -f`` for major action tags, selects different code. The selected
code receives the step inputs, including the Hub credential, and shares the
job PATH and Docker config with later steps.

The tests fail while any ``uses:`` in the ``build`` or ``publish`` jobs is a
movable ref. Pinning each of those actions to a full 40-character commit SHA
makes the moved tag irrelevant, and the tests pass. Removing the Hub
credential and the image push also makes them pass, because that job no longer
publishes.

Run:

    python -m pytest test/github/test_publish_docker_action_pins.py
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "publish-ifcopenshell-docker.yml"
FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
HUB_TOKEN = "placeholder-docker-hub-token"
UPSTREAM = "IfcOpenShell/IfcOpenShell"
IMAGE = "aecgeeks/ifcopenshell"

# actions/runner v2.330.0 Handler.cs AddEnvironmentVariable stores the input
# or an empty string. @actions/core 3.0.1 getInput trims that value.
# docker/cli v28.3.3 login.go verifyLoginOptions trims one trailing LF then one CR.
DOCKER_STUB = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import base64, json, os, sys
    from pathlib import Path

    args = sys.argv[1:]
    if not args or args[0] != "login":
        sys.exit(0)
    username = ""
    registry = ""
    password_stdin = False
    i = 1
    while i < len(args):
        arg = args[i]
        if arg == "--password-stdin":
            password_stdin = True
        elif arg == "--username" and i + 1 < len(args):
            i += 1
            username = args[i]
        elif not arg.startswith("-"):
            registry = arg
        i += 1
    if not password_stdin:
        sys.exit("docker login was not given --password-stdin")
    raw = sys.stdin.read()
    if raw.endswith("\\n"):
        raw = raw[:-1]
    if raw.endswith("\\r"):
        raw = raw[:-1]
    server = "https://index.docker.io/v1/" if registry in ("", "docker.io") else registry
    encoded = base64.b64encode(f"{username}:{raw}".encode()).decode()
    config_dir = Path(os.environ.get("DOCKER_CONFIG") or (Path.home() / ".docker"))
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "config.json"
    data = {"auths": {}}
    if path.is_file():
        data = json.loads(path.read_text())
    data.setdefault("auths", {})[server] = {"auth": encoded}
    path.write_text(json.dumps(data))
    """
)

BENIGN_LOGIN = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import os, subprocess

    def get_input(name):
        return os.environ.get(f"INPUT_{name.replace(' ', '_').upper()}", "").strip()

    password = get_input("password")
    username = get_input("username")
    registry = get_input("registry") or "docker.io"
    if not username or not password:
        raise SystemExit("Username and password required")
    subprocess.run(
        ["docker", "login", "--password-stdin", "--username", username, registry],
        input=password + "\\n",
        text=True,
        check=True,
    )
    """
)

BENIGN_PUSH = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import base64, json, os
    from pathlib import Path

    def get_input(name):
        return os.environ.get(f"INPUT_{name.replace(' ', '_').upper()}", "").strip()

    if get_input("push") not in ("true", "True", "TRUE"):
        raise SystemExit(0)
    config = json.loads((Path(os.environ["DOCKER_CONFIG"]) / "config.json").read_text())
    auths = [item.get("auth", "") for item in config.get("auths", {}).values()]
    if not any(auths):
        raise SystemExit("push requested without registry credentials")
    for encoded in auths:
        if not encoded:
            continue
        user, sep, secret = base64.b64decode(encoded).decode().partition(":")
        if sep and user and secret:
            break
    else:
        raise SystemExit("push requested without registry credentials")
    Path(os.environ["LEGITIMATE_PUSH_LOG"]).write_text(get_input("tags"))
    """
)

BENIGN_NOOP = "#!/usr/bin/env python3\n"

MALICIOUS = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import base64, json, os, stat
    from pathlib import Path

    sink = Path(os.environ["ATTACKER_SINK"])
    notes = []
    password = os.environ.get("INPUT_PASSWORD", "").strip()
    if password:
        notes.append("password-input")
    config_dir = os.environ.get("DOCKER_CONFIG", "")
    config_path = Path(config_dir) / "config.json" if config_dir else None
    if config_path and config_path.is_file():
        data = json.loads(config_path.read_text())
        for auth in (data.get("auths") or {}).values():
            encoded = auth.get("auth") or ""
            if not encoded:
                continue
            user, sep, secret = base64.b64decode(encoded).decode().partition(":")
            if sep and secret:
                notes.append("docker-config")
    tags = os.environ.get("INPUT_TAGS", "")
    push = os.environ.get("INPUT_PUSH", "").strip()
    if push in ("true", "True", "TRUE") and "aecgeeks/ifcopenshell" in tags:
        notes.append("pushed-replacement")
    artifact = Path(os.environ["ARTIFACT_DIR"])
    artifact.mkdir(parents=True, exist_ok=True)
    (artifact / "attacker-package.deb").write_text("attacker-package")
    planted = Path(os.environ["RUNNER_TEMP"]) / "planted-docker"
    planted.mkdir(parents=True, exist_ok=True)
    docker = planted / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\\n"
        "import os, sys\\n"
        "from pathlib import Path\\n"
        "data = sys.stdin.read()\\n"
        "if data.strip():\\n"
        "    Path(os.environ['ATTACKER_SINK']).open('a').write('docker-stdin\\\\n')\\n"
    )
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    path_file = os.environ.get("GITHUB_PATH", "")
    if path_file:
        with open(path_file, "a", encoding="utf-8") as handle:
            handle.write(str(planted) + "\\n")
    if notes:
        with sink.open("a", encoding="utf-8") as handle:
            handle.write("\\n".join(notes) + "\\n")
    """
)


class _WorkflowLoader(yaml.SafeLoader):
    """Load workflow YAML without turning the ``on`` key into a boolean."""


_WorkflowLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"]
    for key, resolvers in _WorkflowLoader.yaml_implicit_resolvers.items()
}


def _load_workflow():
    return yaml.load(WORKFLOW.read_text(), Loader=_WorkflowLoader)


def _starts_with(left, right):
    # actions/runner StartsWith.cs: non-primitives return false; strings use
    # OrdinalIgnoreCase. EvaluationResult.ConvertToString maps null to "".
    if isinstance(left, (dict, list)):
        return False
    return str("" if left is None else left).lower().startswith(str("" if right is None else right).lower())


def _contains(left, right):
    # actions/runner Contains.cs uses OrdinalIgnoreCase IndexOf for primitives.
    if isinstance(left, (dict, list)) or isinstance(right, (dict, list)):
        return False
    return str("" if right is None else right).lower() in str("" if left is None else left).lower()


def _is_falsy(value):
    # actions/runner EvaluationResult.IsFalsy
    if value is None or value is False:
        return True
    if value is True:
        return False
    if isinstance(value, str):
        return value == ""
    if isinstance(value, (int, float)):
        return value == 0
    return False


def _equal(left, right):
    # actions/runner Equal.cs delegates to AbstractEqual, OrdinalIgnoreCase for strings.
    if isinstance(left, str) and isinstance(right, str):
        return left.lower() == right.lower()
    return left == right


def _lookup(context, path):
    # actions/runner Index.cs returns null when the container or key is missing.
    current = context
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


class _Parser:
    def __init__(self, text, context):
        self.text = text.strip()
        self.context = context
        self.i = 0

    def parse(self):
        value = self._and()
        self._skip()
        if self.i != len(self.text):
            raise AssertionError(f"unparsed workflow expression: {self.text[self.i :]!r}")
        return value

    def _skip(self):
        while self.i < len(self.text) and self.text[self.i].isspace():
            self.i += 1

    def _and(self):
        # actions/runner And.cs returns the first falsy operand, otherwise the last value.
        value = self._unary()
        while True:
            self._skip()
            if not self.text.startswith("&&", self.i):
                return value
            self.i += 2
            if _is_falsy(value):
                self._unary()
                continue
            value = self._unary()

    def _unary(self):
        self._skip()
        if self.text.startswith("!", self.i) and not self.text.startswith("!=", self.i):
            self.i += 1
            # actions/runner Not.cs returns IsFalsy of the operand.
            return _is_falsy(self._unary())
        return self._comparison()

    def _comparison(self):
        left = self._primary()
        self._skip()
        if self.text.startswith("==", self.i):
            self.i += 2
            return _equal(left, self._primary())
        return left

    def _primary(self):
        self._skip()
        if self.text.startswith("(", self.i):
            self.i += 1
            value = self._and()
            self._skip()
            if not self.text.startswith(")", self.i):
                raise AssertionError("missing ) in workflow expression")
            self.i += 1
            return value
        if self.text.startswith("'", self.i):
            self.i += 1
            end = self.text.find("'", self.i)
            value = self.text[self.i : end]
            self.i = end + 1
            return value
        start = self.i
        while self.i < len(self.text) and (self.text[self.i].isalnum() or self.text[self.i] in "._"):
            self.i += 1
        word = self.text[start : self.i]
        self._skip()
        if self.text.startswith("(", self.i):
            self.i += 1
            args = []
            while True:
                args.append(self._and())
                self._skip()
                if self.text.startswith(",", self.i):
                    self.i += 1
                    continue
                if self.text.startswith(")", self.i):
                    self.i += 1
                    break
                raise AssertionError("missing ) after function arguments")
            if word == "startsWith" and len(args) == 2:
                return _starts_with(args[0], args[1])
            if word == "contains" and len(args) == 2:
                return _contains(args[0], args[1])
            raise AssertionError(f"unsupported expression function {word}")
        if word in ("true", "false"):
            return word == "true"
        if word == "":
            raise AssertionError(f"empty expression at {self.text[self.i :]!r}")
        return _lookup(self.context, word)


def _truthy(expression, context):
    if expression is None:
        return True
    return not _is_falsy(_Parser(str(expression), context).parse())


def _running_jobs(workflow, context):
    # Workflow syntax jobs.<job_id>.needs: a skipped needed job skips dependents
    # unless the dependent job sets its own if. None of these jobs use always().
    jobs = workflow["jobs"]
    running = set()
    pending = set(jobs)
    while pending:
        progressed = False
        for name in list(pending):
            job = jobs[name]
            needs = job.get("needs") or []
            if isinstance(needs, str):
                needs = [needs]
            if any(item in pending for item in needs):
                continue
            progressed = True
            pending.remove(name)
            if all(item in running for item in needs) and _truthy(job.get("if"), context):
                running.add(name)
        if not progressed:
            raise AssertionError(f"job dependency cycle: {pending}")
    return running


def _tag_push_context(repository, message, ref_name="v0.8.0"):
    return {
        "github": {
            "repository": repository,
            "ref_name": ref_name,
            "event": {"head_commit": {"message": message}, "repository": {"default_branch": "v0.9.0"}},
            "event_name": "push",
        }
    }


def _dispatch_context(repository):
    return {
        "github": {
            "repository": repository,
            "ref_name": "v0.9.0",
            "event": {"repository": {"default_branch": "v0.9.0"}},
            "event_name": "workflow_dispatch",
        }
    }


def _steps(job):
    steps = []
    for step in job.get("steps") or []:
        uses = step.get("uses")
        if not uses or uses.startswith("docker://"):
            continue
        owner_repo, _, ref = uses.rpartition("@")
        if not ref or "/" not in owner_repo:
            raise AssertionError(f"unparsed action reference {uses}")
        inputs = step.get("with") or {}
        steps.append({"uses": uses, "owner_repo": owner_repo, "ref": ref, "inputs": inputs, "name": step.get("name")})
    return steps


def _substitute(value, context):
    text = str(value)
    text = text.replace("${{ secrets.DOCKER_HUB_TOKEN }}", HUB_TOKEN)

    def replace(match):
        result = _Parser(match.group(1), context).parse()
        if result is None or result is False:
            return ""
        if result is True:
            return "true"
        return str(result)

    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", replace, text)


def _git(repo, *args, check=True):
    command = [
        "git",
        "-C",
        str(repo),
        "-c",
        "user.email=actions-test@example.com",
        "-c",
        "user.name=actions-test",
        *args,
    ]
    return subprocess.run(command, check=check, capture_output=True, text=True)


def _write_executable(path: Path, content: str):
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _commit_actions(repo: Path, files: dict[str, str]) -> str:
    for name, content in files.items():
        destination = repo / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_executable(destination, content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "action revision")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _action_repos(root: Path, steps):
    repos = {}
    benign_by_role = {
        "login": {"main.py": BENIGN_LOGIN},
        "push": {"main.py": BENIGN_PUSH},
        "other": {"main.py": BENIGN_NOOP},
    }
    for step in steps:
        key = step["owner_repo"]
        if key in repos:
            continue
        repo = root / "actions" / key.replace("/", "__")
        repo.mkdir(parents=True)
        _git(repo, "init", "-q")
        role = "other"
        if step["owner_repo"] == "docker/login-action":
            role = "login"
        elif step["owner_repo"] == "docker/build-push-action":
            role = "push"
        benign = _commit_actions(repo, benign_by_role[role])
        malicious = _commit_actions(repo, {"main.py": MALICIOUS})
        repos[key] = {"path": repo, "benign": benign, "malicious": malicious}
    for step in steps:
        repo = repos[step["owner_repo"]]["path"]
        if not FULL_SHA.fullmatch(step["ref"]):
            # Same update GitHub documents for a major action tag: git tag -f, then push --force.
            _git(repo, "tag", "-f", step["ref"], repos[step["owner_repo"]]["malicious"])
    return repos


def _resolve(repo_info, ref):
    repo = repo_info["path"]
    if FULL_SHA.fullmatch(ref):
        # A full commit id does not follow refs/tags. rev-parse of the benign
        # commit stays on that commit after the tag was moved to the malicious one.
        resolved = _git(repo, "rev-parse", f"{repo_info['benign']}^{{commit}}").stdout.strip()
        assert resolved == repo_info["benign"]
        moved = _git(repo, "rev-parse", "refs/tags/v4", check=False)
        if moved.returncode == 0:
            assert moved.stdout.strip() == repo_info["malicious"]
        if ref.lower() == repo_info["malicious"].lower():
            return repo_info["malicious"]
        parsed = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
        if parsed.returncode == 0:
            return parsed.stdout.strip()
        # The workflow names a commit that is not the moved tag. The fixture
        # stands in for that reviewed commit.
        return repo_info["benign"]
    resolved = _git(repo, "rev-parse", f"refs/tags/{ref}^{{commit}}").stdout.strip()
    return resolved


def _run_publish_path(workflow, context, work: Path, repos=None):
    work.mkdir(parents=True, exist_ok=True)
    jobs = workflow["jobs"]
    running = _running_jobs(workflow, context)
    steps = []
    for name in ("build", "publish"):
        if name in running:
            for step in _steps(jobs[name]):
                step["job"] = name
                steps.append(step)
    if repos is None:
        repos = _action_repos(work, steps)
    sink = work / "attacker-sink.txt"
    sink.write_text("")
    artifact = work / "artifacts"
    artifact.mkdir()
    config_dir = work / "docker-config"
    config_dir.mkdir()
    docker_bin = work / "docker-bin"
    docker_bin.mkdir()
    _write_executable(docker_bin / "docker", DOCKER_STUB)
    legitimate = work / "legitimate-push.txt"
    prepend: list[str] = []
    base_path = f"{docker_bin}{os.pathsep}{os.environ.get('PATH', '')}"
    for step in steps:
        info = repos[step["owner_repo"]]
        commit = _resolve(info, step["ref"])
        script = _git(info["path"], "show", f"{commit}:main.py").stdout
        step_dir = work / "step"
        if step_dir.exists():
            shutil.rmtree(step_dir)
        step_dir.mkdir()
        _write_executable(step_dir / "main.py", script)
        github_path = work / "github_path.txt"
        github_path.write_text("")
        env = os.environ.copy()
        env["PATH"] = os.pathsep.join([*reversed(prepend), base_path]) if prepend else base_path
        env["GITHUB_PATH"] = str(github_path)
        env["DOCKER_CONFIG"] = str(config_dir)
        env["ATTACKER_SINK"] = str(sink)
        env["ARTIFACT_DIR"] = str(artifact)
        env["LEGITIMATE_PUSH_LOG"] = str(legitimate)
        env["RUNNER_TEMP"] = str(work / "runner-temp")
        Path(env["RUNNER_TEMP"]).mkdir(exist_ok=True)
        for key, value in step["inputs"].items():
            rendered = _substitute(value, context)
            env[f"INPUT_{str(key).replace(' ', '_').upper()}"] = rendered
        if "INPUT_PASSWORD" not in env and step["owner_repo"] == "docker/login-action":
            env["INPUT_PASSWORD"] = ""
        completed = subprocess.run(["python3", "main.py"], cwd=step_dir, env=env, capture_output=True, text=True)
        if completed.returncode != 0 and commit != info["malicious"]:
            raise AssertionError(f"{step['uses']} failed\n{completed.stderr}")
        # actions/runner FileCommandManager.cs AddPathFileCommand, then Handler prepends in reverse.
        for line in github_path.read_text().splitlines():
            if line and line not in prepend:
                prepend.append(line)
            elif line in prepend:
                prepend.remove(line)
                prepend.append(line)
    return {
        "running": running,
        "sink": sink.read_text(),
        "artifact": artifact,
        "legitimate": legitimate.read_text() if legitimate.exists() else "",
    }


def _publishes_with_hub_token(workflow, context):
    running = _running_jobs(workflow, context)
    if "publish" not in running:
        return False
    steps = _steps(workflow["jobs"]["publish"])
    has_token = any("secrets.DOCKER_HUB_TOKEN" in str(value) for step in steps for value in step["inputs"].values())
    pushes = any(str(step["inputs"].get("push", "")).lower() == "true" for step in steps)
    image = any(IMAGE in str(value) for step in steps for value in step["inputs"].values())
    return has_token and pushes and image


def test_upstream_tag_push_runs_publish_job():
    workflow = _load_workflow()
    context = _tag_push_context(UPSTREAM, "build: add run_against_package script metadata")
    assert workflow["on"]["push"]["tags"] == ["v0.**"]
    assert "workflow_dispatch" in workflow["on"]
    running = _running_jobs(workflow, context)
    assert {"upstream-only", "build", "publish"} <= running


def test_fork_tag_push_skips_publish_job():
    workflow = _load_workflow()
    running = _running_jobs(workflow, _tag_push_context("FLINT-Builders/IfcOpenShell", "build: add metadata"))
    assert "publish" not in running
    assert "build" not in running


def test_release_commit_message_skips_publish_job():
    workflow = _load_workflow()
    running = _running_jobs(workflow, _tag_push_context(UPSTREAM, "Release v0.8.0"))
    assert "publish" not in running


def test_ci_skip_message_skips_publish_job():
    workflow = _load_workflow()
    running = _running_jobs(workflow, _tag_push_context(UPSTREAM, "build: ci skip this publish"))
    assert "publish" not in running


def test_workflow_dispatch_on_upstream_runs_publish_job():
    workflow = _load_workflow()
    running = _running_jobs(workflow, _dispatch_context(UPSTREAM))
    assert "publish" in running


def test_commit_sha_pin_ignores_moved_tag(tmp_path):
    workflow = _load_workflow()
    context = _tag_push_context(UPSTREAM, "build: add metadata")
    jobs = workflow["jobs"]
    steps = _steps(jobs["build"]) + _steps(jobs["publish"])
    repos = _action_repos(tmp_path, steps)
    login = repos["docker/login-action"]
    assert _resolve(login, "v4") == login["malicious"]
    assert _resolve(login, login["benign"]) == login["benign"]
    pinned = yaml.load(WORKFLOW.read_text(), Loader=_WorkflowLoader)
    for job_name in ("build", "publish"):
        for step in pinned["jobs"][job_name]["steps"]:
            uses = step.get("uses")
            if not uses or "@" not in uses:
                continue
            owner_repo = uses.rpartition("@")[0]
            step["uses"] = f"{owner_repo}@{repos[owner_repo]['benign']}"
    result = _run_publish_path(pinned, context, tmp_path / "run", repos)
    assert result["sink"] == ""
    assert not (result["artifact"] / "attacker-package.deb").exists()
    assert IMAGE in result["legitimate"]
    assert HUB_TOKEN not in result["legitimate"]


def test_publish_workflow_does_not_run_code_from_a_moved_action_tag(tmp_path):
    workflow = _load_workflow()
    context = _tag_push_context(UPSTREAM, "build: add run_against_package script metadata")
    assert _publishes_with_hub_token(workflow, context)
    result = _run_publish_path(workflow, context, tmp_path)
    tampered = (result["artifact"] / "attacker-package.deb").exists()
    assert result["sink"] == "" and not tampered, (
        "A moved action tag in the Docker publish path supplied the code that ran. "
        f"Attacker observations: {result['sink'].strip() or 'tampered package'}. "
        "Pin every uses: in the build and publish jobs to a full commit SHA."
    )
