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

"""Restart Blender must not run commands embedded in the file it was opened with.

On a Microsoft Store install, ``RestartBlender.execute`` relaunches Blender through
``cmd.exe``. Both buttons that do this (the Debug panel and the reinstall prompt)
call that one operator. The opened file arrives in ``sys.argv`` because Windows
passes the quoted path from the Store file association, ``blender-launcher.exe``
forwards it, and Blender copies the resulting argv into Python. These tests run
that operator and then apply the Windows command-line joining and ``cmd.exe``
splitting that the relaunch uses.
"""

from __future__ import annotations

import ast
import os
import platform
import subprocess
import sys
import types
from pathlib import Path, PureWindowsPath

import pytest

BONSAI_ROOT = Path(__file__).resolve().parents[2]
OPERATOR_PY = BONSAI_ROOT / "bonsai" / "bim" / "module" / "debug" / "operator.py"
BLENDER_TOOL_PY = BONSAI_ROOT / "bonsai" / "tool" / "blender.py"

# ``pathlib.Path`` is ``WindowsPath`` when ``os.name == "nt"``, and ``WindowsPath``
# cannot be constructed on other systems. ``PureWindowsPath`` is the parser
# ``WindowsPath`` uses for parents and names.
STORE_BINARY = r"C:\Program Files\WindowsApps\BlenderFoundation.Blender_4.2.0.0_x64__ppwjx1n5r4v9t\Blender\blender.exe"
PLAIN_BLEND = r"C:\Users\victim\Downloads\Project\model.blend"
MARKER = "INJECTED_MARKER"


def _load_method(path: Path, class_name: str, method_name: str, namespace: dict) -> None:
    """Compile one method from ``path`` into ``namespace``.

    The method body is the source in the tree, so a fix to that method is what
    the tests execute. Imports of Blender are not required.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == method_name:
                item.decorator_list = []
                item.returns = None
                args = list(item.args.posonlyargs) + list(item.args.args) + list(item.args.kwonlyargs)
                if item.args.vararg is not None:
                    args.append(item.args.vararg)
                if item.args.kwarg is not None:
                    args.append(item.args.kwarg)
                for arg in args:
                    arg.annotation = None
                module = ast.Module(body=[item], type_ignores=[])
                exec(compile(module, str(path), "exec"), namespace)
                return
    raise AssertionError(f"{class_name}.{method_name} not found in {path}")


class _Preferences:
    def __init__(self, save: bool) -> None:
        self.use_preferences_save = save
        self.saved = False

    def save_userpref(self) -> None:
        self.saved = True


class _Bpy:
    def __init__(self, binary_path: str, preferences: _Preferences) -> None:
        self.app = types.SimpleNamespace(binary_path=binary_path)
        self.ops = types.SimpleNamespace(wm=types.SimpleNamespace(save_userpref=preferences.save_userpref))
        self.types = types.SimpleNamespace(Operator=type("Operator", (), {}))


def _namespace(binary_path: str, *, save_preferences: bool = False) -> dict:
    preferences = _Preferences(save_preferences)
    namespace = {
        "__name__": "restart_blender_under_test",
        "os": os,
        "sys": sys,
        "platform": platform,
        "subprocess": subprocess,
        "Path": PureWindowsPath,
        "bpy": _Bpy(binary_path, preferences),
        "preferences_probe": preferences,
    }
    _load_method(BLENDER_TOOL_PY, "Blender", "get_microsoft_store_app_id", namespace)
    _load_method(OPERATOR_PY, "RestartBlender", "execute", namespace)

    class _Blender:
        pass

    # The real method is a classmethod, so the operator calls it with no arguments.
    _Blender.get_microsoft_store_app_id = classmethod(namespace["get_microsoft_store_app_id"])
    namespace["tool"] = types.SimpleNamespace(Blender=_Blender)
    return namespace


def ucrt_command_line(argv: list[str]) -> str:
    """Join argv the way the Universal CRT ``construct_command_line`` does.

    ``os.execv`` on Windows calls ``_wexecv``, which copies each argument
    separated by spaces and does not add quotes. An empty argument still
    contributes a separator, matching a zero-length ``tcslen`` plus a space.
    """
    if not argv:
        return ""
    return " ".join(argv)


def subprocess_command_line(args, *, shell: bool, executable: str | None) -> tuple[str | None, str]:
    """Build the ``CreateProcess`` command line ``subprocess`` uses on Windows.

    A sequence is passed through ``list2cmdline`` (quotes spaces, not ``&``).
    ``shell=True`` then wraps that string as ``cmd.exe /c "..."``.
    """
    if isinstance(args, (str, bytes)):
        command = os.fsdecode(args)
    else:
        command = subprocess.list2cmdline(list(args))
    if not shell:
        return executable, command
    comspec = executable or os.environ.get("ComSpec")
    if not comspec:
        system_root = os.environ.get("SystemRoot", "")
        comspec = os.path.join(system_root, "System32", "cmd.exe")
    return comspec, '{} /c "{}"'.format(comspec, command)


def cmd_commands(command_line: str) -> list[str] | None:
    """Commands ``cmd.exe /c`` would run, or ``None`` when ``/c`` is absent.

    The switch scan walks the command line for ``/c`` or ``/k``. ``&`` and ``&&``
    outside quotes are separators. A caret escapes the next character, and
    ``>&`` stays part of a redirection.
    """
    index = 0
    size = len(command_line)
    while index < size and command_line[index] != "/":
        index += 1
    found = False
    while index < size:
        if command_line[index] != "/":
            index += 1
            continue
        switch = command_line[index + 1 : index + 2].lower()
        if switch in {"c", "k"}:
            found = True
            index += 2
            break
        index += 1
    if not found:
        return None
    while index < size and command_line[index] in " \t,=;":
        index += 1
    body = command_line[index:]

    commands: list[str] = []
    buffer: list[str] = []
    in_quotes = False
    cursor = 0
    while cursor < len(body):
        character = body[cursor]
        if character == "^" and not in_quotes and cursor + 1 < len(body):
            buffer.append(body[cursor + 1])
            cursor += 2
            continue
        if character == '"':
            in_quotes = not in_quotes
            buffer.append(character)
            cursor += 1
            continue
        if character == ">" and not in_quotes and cursor + 1 < len(body) and body[cursor + 1] == "&":
            buffer.append(">&")
            cursor += 2
            continue
        if character == "&" and not in_quotes:
            if cursor + 1 < len(body) and body[cursor + 1] == "&":
                cursor += 1
            commands.append("".join(buffer).strip())
            buffer = []
            cursor += 1
            continue
        buffer.append(character)
        cursor += 1
    commands.append("".join(buffer).strip())
    return [command for command in commands if command]


def _first_token(command: str) -> str:
    command = command.strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        if end > 1:
            return command[1:end]
    pieces = command.split()
    return pieces[0] if pieces else ""


def _is_cmd(executable: str | None) -> bool:
    if not executable:
        return False
    name = str(executable).replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name == "cmd.exe"


def _launch_command(launch: dict) -> tuple[str | None, str] | None:
    """Return ``(executable, command line)`` Windows would pass to ``CreateProcess``."""
    if launch["kind"] == "execv":
        return str(launch["path"]), ucrt_command_line([str(arg) for arg in launch["argv"]])
    if launch["kind"] == "system":
        executable = os.path.join(os.environ.get("SystemRoot", ""), "System32", "cmd.exe")
        return executable, "/c " + launch["command"]
    if launch["kind"] == "startfile":
        return None
    return subprocess_command_line(launch["args"], shell=launch["shell"], executable=launch["executable"])


def injected_commands(launches: list[dict], marker: str) -> list[str]:
    """Marker commands ``cmd.exe`` would run for the recorded launches."""
    found: list[str] = []
    for launch in launches:
        built = _launch_command(launch)
        if built is None:
            continue
        executable, command_line = built
        first = _first_token(command_line)
        if not (_is_cmd(executable) or _is_cmd(first) or launch.get("shell")):
            continue
        commands = cmd_commands(command_line)
        if not commands:
            continue
        for command in commands:
            if _first_token(command) == marker:
                found.append(command)
    return found


def _record_launches(namespace: dict) -> list[dict]:
    launches: list[dict] = []
    original_execv = os.execv

    def execv(path, argv):
        launches.append({"kind": "execv", "path": path, "argv": list(argv), "shell": False})

    def system(command):
        launches.append({"kind": "system", "command": command, "shell": True})
        return 0

    def startfile(path, *args, **kwargs):
        launches.append({"kind": "startfile", "path": path, "shell": False})

    def popen(args, *args_, shell=False, executable=None, **kwargs):
        launches.append({"kind": "subprocess", "args": args, "shell": shell, "executable": executable})
        return types.SimpleNamespace(returncode=0, wait=lambda *a, **k: 0, communicate=lambda *a, **k: (b"", b""))

    os.execv = execv
    os.system = system
    os.startfile = startfile
    subprocess.Popen = popen
    subprocess.run = lambda args, *a, shell=False, executable=None, **k: popen(args, shell=shell, executable=executable)
    subprocess.call = subprocess.run
    subprocess.check_call = subprocess.run
    namespace["os"] = os
    namespace["subprocess"] = subprocess
    return launches, original_execv


def _run_restart(argv: list[str], binary_path: str, *, system_name: str) -> tuple[list[dict], object]:
    namespace = _namespace(binary_path)
    previous_name = os.name
    previous_system = platform.system
    previous_system_root = os.environ.get("SystemRoot")
    previous_execv = os.execv
    previous_system_fn = os.system
    previous_startfile = getattr(os, "startfile", None)
    previous_popen = subprocess.Popen
    previous_run = subprocess.run
    previous_call = subprocess.call
    previous_check_call = subprocess.check_call
    launches, _ = _record_launches(namespace)
    os.environ["SystemRoot"] = r"C:\Windows"
    os.name = "nt"
    platform.system = lambda: system_name
    sys.argv = list(argv)
    try:
        namespace["execute"](types.SimpleNamespace(), types.SimpleNamespace(preferences=namespace["preferences_probe"]))
    finally:
        os.name = previous_name
        platform.system = previous_system
        os.execv = previous_execv
        os.system = previous_system_fn
        if previous_startfile is None:
            delattr(os, "startfile")
        else:
            os.startfile = previous_startfile
        subprocess.Popen = previous_popen
        subprocess.run = previous_run
        subprocess.call = previous_call
        subprocess.check_call = previous_check_call
        if previous_system_root is None:
            os.environ.pop("SystemRoot", None)
        else:
            os.environ["SystemRoot"] = previous_system_root
    return launches, namespace["preferences_probe"]


def test_cmd_parser_splits_unquoted_ampersand_and_keeps_quoted_one():
    """The stand-in for cmd.exe splits the metacharacter the relaunch relies on."""
    unquoted = r"/c start app C:\Project&INJECTED_MARKER&\model.blend"
    quoted = r'/c start app "C:\Project&INJECTED_MARKER&\model.blend"'
    assert _first_token(cmd_commands(unquoted)[1]) == MARKER
    assert all(_first_token(command) != MARKER for command in cmd_commands(quoted))


def test_ucrt_join_does_not_quote():
    """``os.execv``'s Windows argv join leaves an ampersand exposed."""
    joined = ucrt_command_line(["/c", "start", r"C:\Project&INJECTED_MARKER&\model.blend"])
    assert joined == r"/c start C:\Project&INJECTED_MARKER&\model.blend"
    assert _first_token(cmd_commands(joined)[1]) == MARKER


@pytest.mark.parametrize(
    "blend_path",
    [
        rf"C:\Users\victim\Downloads\Project&{MARKER}&\model.blend",
        rf"C:\Users\victim\Downloads\Project files&{MARKER}&\model.blend",
    ],
)
def test_store_restart_does_not_run_a_command_embedded_in_the_opened_file(blend_path):
    launches, preferences = _run_restart(
        [STORE_BINARY, blend_path],
        STORE_BINARY,
        system_name="Windows",
    )
    assert preferences.saved is False
    injected = injected_commands(launches, MARKER)
    assert injected == [], (
        "Restart Blender handed the opened file to cmd.exe without quoting. "
        f"Launches: {launches!r}. cmd.exe would run {injected!r}."
    )


def test_store_restart_does_not_run_a_command_embedded_in_a_later_argument():
    """Every original argument is appended, not only argv[1]."""
    blend_path = rf"C:\Users\victim\Downloads\Project&{MARKER}&\model.blend"
    launches, _preferences = _run_restart(
        [STORE_BINARY, "--factory-startup", blend_path],
        STORE_BINARY,
        system_name="Windows",
    )
    injected = injected_commands(launches, MARKER)
    assert injected == [], (
        f"A command hidden in a later Blender argument was executed. Launches: {launches!r}. Commands: {injected!r}."
    )


def test_plain_store_path_stays_one_command():
    launches, _preferences = _run_restart(
        [STORE_BINARY, PLAIN_BLEND],
        STORE_BINARY,
        system_name="Windows",
    )
    assert launches, "Restart Blender did not relaunch"
    assert injected_commands(launches, MARKER) == []
    command_lines = []
    for launch in launches:
        built = _launch_command(launch)
        if built is not None:
            command_lines.append(built[1])
    assert any(PLAIN_BLEND in line for line in command_lines)


def test_non_store_windows_restart_does_not_invoke_cmd():
    """The non-Store Windows branch execs Blender itself, not cmd.exe."""
    desktop = r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"
    launches, _preferences = _run_restart(
        [desktop, rf"C:\Users\victim\Downloads\Project&{MARKER}&\model.blend"],
        desktop,
        system_name="Windows",
    )
    assert launches
    assert all(not _is_cmd(str(launch.get("path") or launch.get("executable") or "")) for launch in launches)
    assert injected_commands(launches, MARKER) == []
