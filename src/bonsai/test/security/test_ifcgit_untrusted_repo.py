# This file was generated with the assistance of an AI coding tool.

"""Untrusted IfcGit repositories must not execute commands from their config.

Opening an IFC project stores the chosen absolute path (``tool.Ifc.set_path``,
then ``tool.Ifc.get_path``). Expanding the Git panel calls
``IFCGIT_PT_panel.draw``, which calls ``IfcGitData.load``. That discovers a
``.git`` directory in the file's folder or any parent and runs git there.

A repository the user did not create can set ``core.fsmonitor`` and
``core.hooksPath``. On git 2.43, reading the index runs the fsmonitor command
(``ls-files``, ``diff``, ``checkout``, ``merge``, ``commit``). GitPython also
runs ``pre-commit`` and ``commit-msg`` hooks itself from ``index.commit``.

These tests fail while any of those commands still run. They pass when the
same calls no longer execute the repository command. Skipping the call before
it runs is a pass. Running the command and then raising is not.

Not covered, because those git commands do not read the index or run hooks on
git 2.43: revision listing (``git rev-list``), ``entity_log`` (``git log -L``),
``rename_branch`` (``git branch -m``), tags (``git tag``), remotes, fetch,
push, ``git mergetool``, ``git merge --abort``, and ``run_git_diff``
(``git diff --no-index``).
"""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest

BONSAI_ROOT = Path(__file__).resolve().parents[2]
if str(BONSAI_ROOT) not in sys.path:
    sys.path.insert(0, str(BONSAI_ROOT))


class _Layout:
    """Stand-in for a Blender UILayout. The panel only needs the layout object to exist."""

    def __getattr__(self, name):
        def _call(*args, **kwargs):
            return _Layout()

        return _call


class _Props:
    def __init__(self) -> None:
        self.ifcgit_commits = []
        self.commit_index = 0
        self.merge_conflicts = ""
        self.remote_url = ""
        self.local_folder = ""
        self.commit_message = ""
        self.new_branch_name = ""
        self.display_branch = "main"
        self.ifcgit_filter = "all"
        self.select_remote = ""
        self.new_tag_name = ""
        self.new_tag_message = ""
        self.remote_name = ""


class _IfcSession:
    """Stand-in for the open-project path stored by ``tool.Ifc``.

    ``finish_loading_project`` calls ``tool.Ifc.set_path`` with the file the
    user opened. ``get_path`` returns that absolute path and ``get`` returns
    the open file. Neither value is rewritten before IfcGit uses it.
    """

    path = ""
    file = None

    @classmethod
    def get(cls):
        return cls.file

    @classmethod
    def get_path(cls) -> str:
        return cls.path

    @classmethod
    def open(cls, path: Path) -> None:
        cls.path = str(path)
        cls.file = object()


def _module(name: str, path: list[str] | None = None) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    module.__package__ = name
    if path is not None:
        module.__path__ = path
    return module


def _load_source(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def ifcgit():
    """Load the real IfcGit sources. Blender is not part of the git invocation."""

    os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")
    # Import bonsai before a bpy module exists so its non-Blender startup path is used.
    import bonsai.core.tool as core_tool

    assert core_tool.IfcGit

    bpy = _module("bpy")
    bpy.types = _module("bpy.types")
    bpy.props = _module("bpy.props")
    bpy.path = types.SimpleNamespace(abspath=os.path.abspath)
    bpy.ops = types.SimpleNamespace()
    bpy.data = types.SimpleNamespace()
    props = _Props()
    bpy.context = types.SimpleNamespace(scene=types.SimpleNamespace(IfcGitProperties=props))

    class _Panel:
        pass

    bpy.types.Panel = _Panel
    bpy.types.UIList = _Panel

    bim = _module("bonsai.bim", [str(BONSAI_ROOT / "bonsai" / "bim")])
    _module("bonsai.bim.module", [str(BONSAI_ROOT / "bonsai" / "bim" / "module")])
    _module("bonsai.bim.module.ifcgit", [str(BONSAI_ROOT / "bonsai" / "bim" / "module" / "ifcgit")])
    bim_ifc = _module("bonsai.bim.ifc")

    class _IfcStore:
        path = ""
        file = None

    bim_ifc.IfcStore = _IfcStore
    bim.import_ifc = _module("bonsai.bim.import_ifc")

    tool = _module("bonsai.tool", [str(BONSAI_ROOT / "bonsai" / "tool")])
    ifcgit_py = _load_source("bonsai.tool.ifcgit", BONSAI_ROOT / "bonsai" / "tool" / "ifcgit.py")
    tool.IfcGit = ifcgit_py.IfcGit
    tool.IfcGitRepo = ifcgit_py.IfcGitRepo
    tool.Ifc = _IfcSession

    data = _load_source(
        "bonsai.bim.module.ifcgit.data",
        BONSAI_ROOT / "bonsai" / "bim" / "module" / "ifcgit" / "data.py",
    )
    ui = _load_source(
        "bonsai.bim.module.ifcgit.ui",
        BONSAI_ROOT / "bonsai" / "bim" / "module" / "ifcgit" / "ui.py",
    )
    return types.SimpleNamespace(tool=ifcgit_py, data=data, ui=ui, props=props)


@pytest.fixture
def opened(ifcgit):
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_CONFIG_PARAMETERS"):
        os.environ.pop(key, None)
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    os.environ["GIT_EDITOR"] = "true"
    os.environ["GIT_PAGER"] = "cat"

    ifcgit.tool.IfcGitRepo.repo = None
    ifcgit.data.IfcGitData.is_loaded = False
    ifcgit.data.IfcGitData.data = {}
    props = ifcgit.props
    props.ifcgit_commits = []
    props.commit_index = 0
    props.merge_conflicts = ""
    props.display_branch = "main"
    props.new_branch_name = ""
    _IfcSession.file = None
    _IfcSession.path = ""
    return ifcgit


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _attack_repo(tmp_path: Path, *, nested: bool, prepare=None) -> dict:
    """Committed repository owned by the current user, with attacker config applied last.

    ``prepare`` runs extra git setup before ``core.fsmonitor`` and
    ``core.hooksPath`` are set, so fixture commands do not execute the payload.
    """

    repo = tmp_path / "project"
    ifc = (repo / "nested" / "model.ifc") if nested else (repo / "model.ifc")
    ifc.parent.mkdir(parents=True)
    ifc.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n")

    marker = tmp_path / "attacker-ran"
    script = tmp_path / "fsmonitor.sh"
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    _write_executable(
        script,
        "#!/bin/sh\n" + f'echo "fsmonitor $*" >> "{marker}"\n' + "printf '/'\n" + "exit 0\n",
    )
    for name in ("pre-commit", "commit-msg", "post-commit", "post-checkout", "pre-merge-commit", "post-merge"):
        _write_executable(
            hooks / name,
            "#!/bin/sh\n" + f'echo "hook:{name}" >> "{marker}"\n' + "exit 0\n",
        )

    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", "--", str(ifc.relative_to(repo)))
    _git(repo, "commit", "-q", "-m", "Initial IFC")
    if prepare is not None:
        prepare(repo)
    _git(repo, "config", "core.fsmonitor", str(script))
    _git(repo, "config", "core.hooksPath", str(hooks))
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return {"repo": repo, "ifc": ifc, "marker": marker, "sha": sha}


def _executed(marker: Path) -> str:
    if not marker.exists():
        return ""
    return marker.read_text()


def _invoke(marker: Path, func) -> None:
    try:
        func()
    except Exception as exc:
        ran = _executed(marker)
        if ran:
            raise AssertionError(f"untrusted repository executed a command before refusing:\n{ran}") from exc
        raise
    ran = _executed(marker)
    assert ran == "", f"untrusted repository executed a command:\n{ran}"


def _open(attack: dict) -> None:
    _IfcSession.open(attack["ifc"])


def _draw(opened, attack: dict) -> None:
    _open(attack)
    panel = opened.ui.IFCGIT_PT_panel()
    panel.layout = _Layout()
    _invoke(attack["marker"], lambda: panel.draw(None))


def test_git_panel_draw_does_not_run_fsmonitor_in_project_repo(opened, tmp_path):
    attack = _attack_repo(tmp_path, nested=False)
    _draw(opened, attack)
    repo = opened.data.IfcGitData.data.get("repo")
    if repo is not None:
        assert Path(repo.working_dir).resolve() == attack["repo"].resolve()


def test_git_panel_draw_does_not_run_fsmonitor_in_parent_repo(opened, tmp_path):
    attack = _attack_repo(tmp_path, nested=True)
    _draw(opened, attack)
    repo = opened.data.IfcGitData.data.get("repo")
    if repo is not None:
        assert Path(repo.working_dir).resolve() == attack["repo"].resolve()


def test_ifc_is_untracked_does_not_run_fsmonitor(opened, tmp_path):
    attack = _attack_repo(tmp_path, nested=False)
    _open(attack)
    repo = opened.tool.IfcGit.repo_from_path(str(attack["ifc"]))
    _invoke(attack["marker"], lambda: opened.data.IfcGitData.ifc_is_untracked(repo))


def test_is_dirty_does_not_run_fsmonitor(opened, tmp_path):
    attack = _attack_repo(tmp_path, nested=False)
    _open(attack)
    repo = opened.tool.IfcGit.repo_from_path(str(attack["ifc"]))
    _invoke(attack["marker"], lambda: opened.data.IfcGitData.is_dirty(repo))


def test_ifc_diff_ids_does_not_run_fsmonitor(opened, tmp_path):
    attack = _attack_repo(tmp_path, nested=False)
    _open(attack)
    repo = opened.tool.IfcGit.repo_from_path(str(attack["ifc"]))
    _invoke(
        attack["marker"],
        lambda: opened.tool.IfcGit.ifc_diff_ids(repo, None, "HEAD", str(attack["ifc"])),
    )


def test_git_checkout_does_not_run_fsmonitor_or_hooks(opened, tmp_path):
    attack = _attack_repo(tmp_path, nested=False)
    _open(attack)
    opened.tool.IfcGit.repo_from_path(str(attack["ifc"]))
    _invoke(attack["marker"], lambda: opened.tool.IfcGit.git_checkout(str(attack["ifc"])))


def test_checkout_new_branch_does_not_run_fsmonitor_or_hooks(opened, tmp_path):
    attack = _attack_repo(tmp_path, nested=False)
    _open(attack)
    opened.tool.IfcGit.repo_from_path(str(attack["ifc"]))
    _invoke(attack["marker"], lambda: opened.tool.IfcGit.checkout_new_branch(str(attack["ifc"]), "feature"))


def test_create_new_branch_does_not_run_fsmonitor_or_hooks(opened, tmp_path):
    attack = _attack_repo(tmp_path, nested=False)
    _open(attack)
    opened.tool.IfcGit.repo_from_path(str(attack["ifc"]))
    _invoke(attack["marker"], lambda: opened.tool.IfcGit.create_new_branch("from-head"))


def test_switch_to_revision_does_not_run_fsmonitor_or_hooks(opened, tmp_path):
    attack = _attack_repo(tmp_path, nested=False)
    _open(attack)
    opened.tool.IfcGit.repo_from_path(str(attack["ifc"]))
    opened.props.ifcgit_commits = [types.SimpleNamespace(hexsha=attack["sha"])]
    opened.props.commit_index = 0
    opened.props.display_branch = "not-a-branch"
    _invoke(attack["marker"], opened.tool.IfcGit.switch_to_revision_item)


def test_git_merge_does_not_run_fsmonitor_or_hooks(opened, tmp_path):
    def prepare(repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "feature")
        _git(repo, "checkout", "-q", "main")

    attack = _attack_repo(tmp_path, nested=False, prepare=prepare)
    _open(attack)
    opened.tool.IfcGit.repo_from_path(str(attack["ifc"]))
    _invoke(attack["marker"], lambda: opened.tool.IfcGit.git_merge("feature"))


def test_git_merge_no_commit_does_not_run_fsmonitor_or_hooks(opened, tmp_path):
    def prepare(repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "feature")
        _git(repo, "checkout", "-q", "main")

    attack = _attack_repo(tmp_path, nested=False, prepare=prepare)
    _open(attack)
    opened.tool.IfcGit.repo_from_path(str(attack["ifc"]))
    _invoke(attack["marker"], lambda: opened.tool.IfcGit.git_merge_no_commit("feature"))


def test_add_file_does_not_run_commit_hooks_or_fsmonitor(opened, tmp_path):
    attack = _attack_repo(tmp_path, nested=False)
    attack["ifc"].write_text("ISO-10303-21;\nDATA;\nEND-ISO-10303-21;\n")
    _open(attack)
    repo = opened.tool.IfcGit.repo_from_path(str(attack["ifc"]))
    _invoke(attack["marker"], lambda: opened.tool.IfcGit.add_file_to_repo(repo, str(attack["ifc"])))


def test_git_commit_does_not_run_commit_hooks_or_fsmonitor(opened, tmp_path):
    attack = _attack_repo(tmp_path, nested=False)
    attack["ifc"].write_text("ISO-10303-21;\nDATA;\nEND-ISO-10303-21;\n")
    _open(attack)
    opened.tool.IfcGit.repo_from_path(str(attack["ifc"]))
    _invoke(attack["marker"], lambda: opened.tool.IfcGit.git_commit(str(attack["ifc"]), "Update model"))


def test_commit_merge_does_not_run_fsmonitor_or_hooks(opened, tmp_path):
    def prepare(repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "feature")
        (repo / "README").write_text("feature\n")
        _git(repo, "add", "--", "README")
        _git(repo, "commit", "-q", "-m", "Feature note")
        _git(repo, "checkout", "-q", "main")
        (repo / "README").write_text("main\n")
        _git(repo, "add", "--", "README")
        _git(repo, "commit", "-q", "-m", "Main note")
        _git(repo, "merge", "feature", check=False)
        (repo / "README").write_text("resolved\n")
        _git(repo, "add", "--", "README")

    attack = _attack_repo(tmp_path, nested=False, prepare=prepare)
    _open(attack)
    opened.tool.IfcGit.repo_from_path(str(attack["ifc"]))
    _invoke(attack["marker"], lambda: opened.tool.IfcGit.commit_merge(str(attack["ifc"])))
