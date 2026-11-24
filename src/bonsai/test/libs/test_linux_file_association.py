# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 Dion Moult <dion@thinkmoult.com>
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

# This file was generated with the assistance of an AI coding tool.

"""Linux .ifc association must pass the opened path as data, not Python source.

The shipped wrapper and the copy written by ``bim.file_associate`` embed the
path in a double-quoted ``--python-expr`` string. These tests launch that
wrapper the way the desktop entry does and then execute the expression the way
Blender's ``--python-expr`` handler does. They fail while a crafted name can
change what runs or which path is opened.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
import types
from pathlib import Path

DESKTOP_DIR = Path(__file__).resolve().parents[2] / "bonsai" / "libs" / "desktop"
WRAPPER_TEMPLATE = DESKTOP_DIR / "bonsai"
PAYLOAD_ENV = "BONSAI_FILE_ASSOC_PAYLOAD"


def _injection_filename() -> str:
    # A backslash immediately before a quote. The wrapper turns the quote into
    # backslash-quote and leaves the original backslash in place.
    return "plan\\\",y=__import__('os').environ.__setitem__('" + PAYLOAD_ENV + "','1'))#.ifc"


def _write_fake_blender(blender: Path, record: Path) -> None:
    blender.write_text(
        f"#!/usr/bin/env python3\nimport json, sys\nopen({str(record)!r}, 'w').write(json.dumps(sys.argv))\n"
    )
    blender.chmod(0o755)


def _session_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    # Ubuntu's default login profile prepends ~/.local/bin when that directory exists
    # (/etc/skel/.profile). The desktop entry's Exec=bonsai looks the wrapper up on PATH.
    local_bin = home / ".local" / "bin"
    if local_bin.is_dir():
        env["PATH"] = str(local_bin) + os.pathsep + env.get("PATH", "")
    for key in ("XDG_DATA_HOME", "XDG_DATA_DIRS", "XDG_CONFIG_HOME", "XDG_CONFIG_DIRS", PAYLOAD_ENV):
        env.pop(key, None)
    return env


def _install_association(home: Path, blender: Path) -> Path:
    """Copy the launcher the way FileAssociate.install_desktop_linux does."""
    destdir = home / ".local"
    for rel in ("bin", "share/applications", "share/mime/packages"):
        (destdir / rel).mkdir(parents=True, exist_ok=True)
    (destdir / "share/applications/bonsai.desktop").write_text((DESKTOP_DIR / "bonsai.desktop").read_text())
    (destdir / "share/mime/packages/bonsai.xml").write_text((DESKTOP_DIR / "bonsai.xml").read_text())
    filedata = WRAPPER_TEMPLATE.read_text()
    filedata = filedata.replace("#BLENDER_EXE=/opt/blender-3.3/blender", 'BLENDER_EXE="' + str(blender) + '"')
    installed = destdir / "bin" / "bonsai"
    installed.write_text(filedata)
    installed.chmod(installed.stat().st_mode | stat.S_IEXEC)
    env = _session_env(home)
    subprocess.run(["update-mime-database", str(destdir / "share/mime")], env=env, check=False)
    subprocess.run(["update-desktop-database", str(destdir / "share/applications")], env=env, check=False)
    return installed


def _executable_template(directory: Path) -> Path:
    """Makefile install copies this script and marks it executable."""
    destination = directory / "bonsai"
    destination.write_text(WRAPPER_TEMPLATE.read_text())
    destination.chmod(0o755)
    return destination


def _run_wrapper(wrapper: Path, filepath: Path, blender: Path, record: Path, env: dict[str, str]) -> list[str]:
    if record.exists():
        record.unlink()
    run_env = env.copy()
    run_env["BLENDER_EXE"] = str(blender)
    run_env.pop(PAYLOAD_ENV, None)
    subprocess.run([str(wrapper), str(filepath)], env=run_env, check=True)
    return json.loads(record.read_text())


def _execute_python_expr(blender_argv: list[str]) -> tuple[str | None, str | None, BaseException | None]:
    """Run ``--python-expr`` the way Blender's BPY_run_string_exec does (file input)."""
    expr = blender_argv[blender_argv.index("--python-expr") + 1]
    loaded: list[str] = []

    def load_project(filepath: str):
        loaded.append(filepath)

    bpy = types.ModuleType("bpy")
    bpy.data = types.SimpleNamespace(objects=[], batch_remove=lambda objects: None)
    bpy.ops = types.SimpleNamespace(
        bim=types.SimpleNamespace(load_project=load_project, create_project=lambda: None),
        outliner=types.SimpleNamespace(orphans_purge=lambda **kwargs: None),
    )
    previous_bpy = sys.modules.get("bpy")
    previous_argv = sys.argv
    sys.modules["bpy"] = bpy
    sys.argv = list(blender_argv)
    os.environ.pop(PAYLOAD_ENV, None)
    error: BaseException | None = None
    try:
        exec(expr, {"__name__": "__main__", "__builtins__": __builtins__})
    except Exception as exc:
        error = exc
    finally:
        sys.argv = previous_argv
        if previous_bpy is None:
            sys.modules.pop("bpy", None)
        else:
            sys.modules["bpy"] = previous_bpy
    payload = os.environ.pop(PAYLOAD_ENV, None)
    return (loaded[0] if loaded else None, payload, error)


def _assert_opened_as_data(blender_argv: list[str], expected: str) -> None:
    loaded, payload, error = _execute_python_expr(blender_argv)
    expr = blender_argv[blender_argv.index("--python-expr") + 1]
    assert payload is None and loaded == expected, (
        "the file path was built into Python source passed to --python-expr\n"
        f"payload={payload!r}\nloaded={loaded!r}\nexpected={expected!r}\nerror={error!r}\nexpr={expr!r}"
    )


def _make_file(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"not an ifc payload\n")
    return path


def test_plain_filename_is_opened(tmp_path: Path) -> None:
    record = tmp_path / "argv.json"
    blender = tmp_path / "blender"
    _write_fake_blender(blender, record)
    path = _make_file(tmp_path / "proj", "storey.ifc")
    argv = _run_wrapper(_executable_template(tmp_path), path, blender, record, os.environ.copy())
    _assert_opened_as_data(argv, str(path))


def test_quote_and_shell_metacharacters_stay_in_the_path(tmp_path: Path) -> None:
    record = tmp_path / "argv.json"
    blender = tmp_path / "blender"
    _write_fake_blender(blender, record)
    path = _make_file(tmp_path / "proj", 'level "A" $(echo hi) `echo ho` ${HOME}.ifc')
    argv = _run_wrapper(_executable_template(tmp_path), path, blender, record, os.environ.copy())
    _assert_opened_as_data(argv, str(path))


def test_backslash_is_not_a_python_string_escape(tmp_path: Path) -> None:
    record = tmp_path / "argv.json"
    blender = tmp_path / "blender"
    _write_fake_blender(blender, record)
    path = _make_file(tmp_path / "proj", "room\\x41\\n.ifc")
    argv = _run_wrapper(_executable_template(tmp_path), path, blender, record, os.environ.copy())
    _assert_opened_as_data(argv, str(path))


def test_newline_in_filename_is_data(tmp_path: Path) -> None:
    record = tmp_path / "argv.json"
    blender = tmp_path / "blender"
    _write_fake_blender(blender, record)
    path = _make_file(tmp_path / "proj", "plan\nnext-line.ifc")
    argv = _run_wrapper(_executable_template(tmp_path), path, blender, record, os.environ.copy())
    _assert_opened_as_data(argv, str(path))


def test_backslash_quote_filename_does_not_run_as_python(tmp_path: Path) -> None:
    record = tmp_path / "argv.json"
    blender = tmp_path / "blender"
    _write_fake_blender(blender, record)
    home = tmp_path / "home"
    installed = _install_association(home, blender)
    path = _make_file(tmp_path / "Project Files", _injection_filename())
    argv = _run_wrapper(installed, path, blender, record, _session_env(home))
    _assert_opened_as_data(argv, str(path))


def test_desktop_open_of_backslash_quote_filename_does_not_run_as_python(tmp_path: Path) -> None:
    record = tmp_path / "argv.json"
    meta = tmp_path / "meta.json"
    blender = tmp_path / "blender"
    _write_fake_blender(blender, record)
    home = tmp_path / "home"
    _install_association(home, blender)
    path = _make_file(tmp_path / "Project Files", _injection_filename())
    proc = subprocess.run(
        [sys.executable, __file__, "--gio-launch", str(home), str(path), str(record), str(meta)],
        env=_session_env(home),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    launched = json.loads(meta.read_text())
    assert launched["content_type"] == "application/x-ifc", launched
    assert launched["commandline"] == "bonsai %f", launched
    assert record.is_file(), "desktop launch did not execute the bonsai wrapper"
    argv = json.loads(record.read_text())
    _assert_opened_as_data(argv, str(path))


def _gio_launch(home: str, filepath: str, record: str, meta_path: str) -> None:
    from gi.repository import Gio

    gfile = Gio.File.new_for_path(filepath)
    info = gfile.query_info("standard::content-type", 0, None)
    content_type = info.get_content_type()
    app = Gio.AppInfo.get_default_for_type(content_type, False)
    meta = {
        "content_type": content_type,
        "app_id": None if app is None else app.get_id(),
        "commandline": None if app is None else app.get_commandline(),
    }
    Path(meta_path).write_text(json.dumps(meta))
    if app is None:
        raise SystemExit(f"no default application for {content_type}")
    if not app.launch([gfile], None):
        raise SystemExit("GDesktopAppInfo.launch returned false")
    deadline = time.time() + 5
    while time.time() < deadline and not Path(record).exists():
        time.sleep(0.05)
    if not Path(record).exists():
        raise SystemExit("wrapper did not record the blender invocation")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--gio-launch":
        _gio_launch(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
