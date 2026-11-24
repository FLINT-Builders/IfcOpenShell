# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026
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
#
# This file was generated with the assistance of an AI coding tool.

"""Linked-model paths must not be pasted into the background Blender script.

Load Link writes a temporary Python file and runs it with ``blender --python``.
The linked file path is the ``IfcDocumentReference.Location`` of an
``IfcDocumentInformation`` whose Scope is ``LINKED_MODEL``. These tests feed
that location a name containing a double quote and a Python expression, then
run the real operator. They fail while that expression still runs.
"""

from __future__ import annotations

import ast
import subprocess
import uuid
from pathlib import Path

import addon_utils
import bpy
import ifcopenshell
import ifcopenshell.api.document
import ifcopenshell.api.root
import pytest

import bonsai.bim.module.project.operator as project_operator
import bonsai.tool as tool
from bonsai.bim.ifc import IfcStore
from test.bim.bootstrap import NewFile

pytestmark = pytest.mark.project


def _python_path_expr(path: Path) -> str:
    """Python expression for ``path`` that contains no ``/`` characters.

    The expression has to fit inside a single filename. ``chr`` keeps the
    directory separators out of that name.
    """
    return "+".join(f"chr({ord(char)})" for char in path.as_posix())


def _quote_breaking_name(marker: Path) -> str:
    """Filename that closes the raw ``r\"...\"`` literal and writes ``marker``.

    ``write`` returns an integer. ``and ""`` keeps the surrounding concatenation
    valid Python, so the side effect is the failure signal rather than a
    ``TypeError`` raised while the argument is evaluated.
    """
    write = f'(open({_python_path_expr(marker)},"w").write("pwned") and "")'
    return f'S"+{write}+".ifc'


def _try_create(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    except OSError:
        return False
    path.unlink()
    return True


def _filepath_expressions(source: str) -> list[ast.AST]:
    expressions = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "filepath":
                expressions.append(keyword.value)
    return expressions


def _keyword_expressions(source: str, name: str) -> list[ast.AST]:
    expressions = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == name:
                expressions.append(keyword.value)
    return expressions


def _eval_expression(expression: ast.AST):
    module = ast.Expression(expression)
    ast.fix_missing_locations(module)
    return eval(compile(module, "<load-link-script>", "eval"), {"__builtins__": __builtins__})


def _ensure_addon_preferences() -> None:
    """Load Link's background process needs the addon; preferences must exist too.

    ``tool.Ifc.set`` reloads pset templates through the addon preferences.
    A ``--addons`` launch enables the module without always creating that entry.
    """
    package = tool.Blender.get_blender_addon_package_name()
    if package not in bpy.context.preferences.addons:
        addon_utils.enable(package, default_set=True, persistent=True)


def _host_with_linked_location(directory: Path, location: str) -> Path:
    ifc = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
    document = ifcopenshell.api.document.add_information(ifc)
    document.Scope = "LINKED_MODEL"
    document.Name = "Linked model"
    reference = ifcopenshell.api.document.add_reference(ifc, information=document)
    reference.Location = location
    reference.Identification = ""
    host = directory / "main.ifc"
    ifc.write(str(host))
    return host


def _open_host(host: Path) -> None:
    _ensure_addon_preferences()
    IfcStore.purge()
    tool.Ifc.set(ifcopenshell.open(str(host)))
    tool.Ifc.set_path(str(host))
    tool.Project.load_linked_models_from_ifc()


def _run_and_capture_scripts(callback) -> list[str]:
    """Run ``callback`` while Load Link's real Blender subprocess still runs."""
    scripts: list[str] = []
    real_run = subprocess.run

    def capture(cmd, *args, **kwargs):
        command = list(cmd)
        if "--python" in command:
            script_path = Path(command[command.index("--python") + 1])
            scripts.append(script_path.read_text())
        return real_run(command, *args, **kwargs)

    # link_ifc calls subprocess.run through the operator module global.
    project_operator.subprocess.run = capture
    try:
        callback()
    finally:
        project_operator.subprocess.run = real_run
    return scripts


def _expressions_ran(marker: Path, scripts: list[str]) -> bool:
    ran = marker.exists()
    marker.unlink(missing_ok=True)
    for source in scripts:
        for expression in _filepath_expressions(source):
            _eval_expression(expression)
            if marker.exists():
                ran = True
                marker.unlink()
    return ran


class TestLinkedModelPathInjection(NewFile):
    def test_load_link_does_not_execute_code_in_the_linked_filename(self, tmp_path):
        marker = Path("/tmp") / f"m{uuid.uuid4().hex[:8]}"
        location = _quote_breaking_name(marker)
        linked = tmp_path / location
        if not _try_create(linked):
            pytest.skip("This platform rejects the quote character in a file name")
        linked.write_text("not an ifc")
        host = _host_with_linked_location(tmp_path, location)
        marker.unlink(missing_ok=True)
        try:
            _open_host(host)
            props = tool.Project.get_project_props()
            assert len(props.links) == 1
            assert props.links[0].filepath == location
            resolved = Path(tool.Ifc.resolve_uri(props.links[0].filepath))
            assert resolved.is_file()
            assert resolved.suffix.lower() == ".ifc"

            scripts = _run_and_capture_scripts(lambda: bpy.ops.bim.load_link(link_index=0))
            assert scripts, "Load Link did not write a background Python script"
            assert not _expressions_ran(marker, scripts)
        finally:
            marker.unlink(missing_ok=True)

    def test_reload_link_does_not_execute_code_in_the_linked_filename(self, tmp_path):
        marker = Path("/tmp") / f"m{uuid.uuid4().hex[:8]}"
        location = _quote_breaking_name(marker)
        linked = tmp_path / location
        if not _try_create(linked):
            pytest.skip("This platform rejects the quote character in a file name")
        linked.write_text("not an ifc")
        host = _host_with_linked_location(tmp_path, location)
        marker.unlink(missing_ok=True)
        try:
            _open_host(host)
            scripts = _run_and_capture_scripts(lambda: bpy.ops.bim.reload_link(link_index=0))
            assert scripts, "Reload Link did not write a background Python script"
            assert not _expressions_ran(marker, scripts)
        finally:
            marker.unlink(missing_ok=True)

    def test_selector_query_is_not_executed_as_python(self, tmp_path):
        """The query argument is already passed through repr(). Keep it that way."""
        marker = Path("/tmp") / f"m{uuid.uuid4().hex[:8]}"
        linked = tmp_path / "plain.ifc"
        linked.write_text("not an ifc")
        host = _host_with_linked_location(tmp_path, "plain.ifc")
        marker.unlink(missing_ok=True)
        query = f'IfcWall"+open({_python_path_expr(marker)},"w").write("pwned")+"x'
        try:
            _open_host(host)
            props = tool.Project.get_project_props()
            props.links[0].query = query
            scripts = _run_and_capture_scripts(lambda: bpy.ops.bim.load_link(link_index=0, query=query))
            assert scripts
            for source in scripts:
                for expression in _keyword_expressions(source, "query"):
                    _eval_expression(expression)
            assert not marker.exists()
        finally:
            marker.unlink(missing_ok=True)
