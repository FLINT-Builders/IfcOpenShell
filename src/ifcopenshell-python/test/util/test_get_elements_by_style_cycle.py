# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

# This file was generated with the assistance of an AI coding tool.

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# pytest puts src/ifcopenshell-python on sys.path, which shadows an installed
# build that contains the native wrapper. Same guard as test.bootstrap.
_python_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if sys.path and os.path.abspath(sys.path[0]) == _python_root:
    del sys.path[0]

import pytest

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.element as subject

# A visited-set fix returns immediately. Two seconds is enough for the lookup
# itself; the child also has to import ifcopenshell.
LOOKUP_TIMEOUT_SECONDS = 5


def _lookup_entrypoint(path: str) -> None:
    ifc_file = ifcopenshell.open(path)
    for style in ifc_file.by_type("IfcPresentationStyle"):
        result = subject.get_elements_by_style(ifc_file, style)
        identifiers = " ".join(sorted(element.GlobalId for element in result))
        print(f"{style.Name}\t{identifiers}", flush=True)


def _assert_lookup(path: str, expected: dict[str, set[str]]) -> None:
    command = [sys.executable, str(Path(__file__).resolve()), "--lookup", path]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=LOOKUP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("get_elements_by_style did not return for a cyclic style graph")
    assert completed.returncode == 0, completed.stderr
    found: dict[str, set[str]] = {}
    for line in completed.stdout.splitlines():
        name, _, identifiers = line.partition("\t")
        found[name] = set(identifiers.split()) if identifiers else set()
    assert found == expected


def _wall(ifc_file: ifcopenshell.file, item: ifcopenshell.entity_instance) -> ifcopenshell.entity_instance:
    wall = ifc_file.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new())
    wall.Representation = ifc_file.create_entity(
        "IfcProductDefinitionShape",
        Representations=[ifc_file.create_entity("IfcShapeRepresentation", Items=[item])],
    )
    return wall


def _write(ifc_file: ifcopenshell.file) -> str:
    handle = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
    handle.close()
    ifc_file.write(handle.name)
    return handle.name


@pytest.mark.parametrize("schema", ["IFC4", "IFC4X3"])
def test_cyclic_fill_area_style_tiles_from_parsed_file(schema: str) -> None:
    ifc_file = ifcopenshell.file(schema=schema)
    surface = ifc_file.create_entity("IfcSurfaceStyle", Name="Surface")
    fill = ifc_file.create_entity("IfcFillAreaStyle", Name="Fill")
    curve = ifc_file.create_entity("IfcCurveStyle", Name="Curve")
    ifc_file.create_entity("IfcSurfaceStyle", Name="Unused")
    item = ifc_file.create_entity("IfcExtrudedAreaSolid")
    styled = ifc_file.create_entity("IfcStyledItem", Item=item, Styles=[surface, fill, curve])
    tiles = ifc_file.create_entity("IfcFillAreaStyleTiles", Tiles=[styled])
    fill.FillStyles = [tiles]
    wall = _wall(ifc_file, item)
    path = _write(ifc_file)
    try:
        _assert_lookup(
            path,
            {
                "Surface": {wall.GlobalId},
                "Fill": {wall.GlobalId},
                "Curve": {wall.GlobalId},
                "Unused": set(),
            },
        )
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_cyclic_fill_area_style_tiles_through_style_assignment(schema: str) -> None:
    ifc_file = ifcopenshell.file(schema=schema)
    surface = ifc_file.create_entity("IfcSurfaceStyle", Name="Surface")
    fill = ifc_file.create_entity("IfcFillAreaStyle", Name="Fill")
    curve = ifc_file.create_entity("IfcCurveStyle", Name="Curve")
    assignment = ifc_file.create_entity("IfcPresentationStyleAssignment", Styles=[surface, fill, curve])
    item = ifc_file.create_entity("IfcExtrudedAreaSolid")
    styled = ifc_file.create_entity("IfcStyledItem", Item=item, Styles=[assignment])
    tiles = ifc_file.create_entity("IfcFillAreaStyleTiles", Tiles=[styled])
    fill.FillStyles = [tiles]
    wall = _wall(ifc_file, item)
    path = _write(ifc_file)
    try:
        _assert_lookup(
            path,
            {
                "Surface": {wall.GlobalId},
                "Fill": {wall.GlobalId},
                "Curve": {wall.GlobalId},
            },
        )
    finally:
        Path(path).unlink(missing_ok=True)


def test_cyclic_fill_area_style_tiles_entered_through_hatching() -> None:
    ifc_file = ifcopenshell.file(schema="IFC4")
    curve = ifc_file.create_entity("IfcCurveStyle", Name="Curve")
    fill = ifc_file.create_entity("IfcFillAreaStyle", Name="Fill")
    hatching = ifc_file.create_entity("IfcFillAreaStyleHatching", HatchLineAppearance=curve)
    item = ifc_file.create_entity("IfcExtrudedAreaSolid")
    styled = ifc_file.create_entity("IfcStyledItem", Item=item, Styles=[fill])
    tiles = ifc_file.create_entity("IfcFillAreaStyleTiles", Tiles=[styled])
    fill.FillStyles = [hatching, tiles]
    wall = _wall(ifc_file, item)
    path = _write(ifc_file)
    try:
        _assert_lookup(path, {"Curve": {wall.GlobalId}, "Fill": {wall.GlobalId}})
    finally:
        Path(path).unlink(missing_ok=True)


def test_cyclic_styled_item_references_terminate() -> None:
    ifc_file = ifcopenshell.file(schema="IFC4")
    mutual = ifc_file.create_entity("IfcSurfaceStyle", Name="Mutual")
    first = ifc_file.create_entity("IfcStyledItem", Styles=[mutual])
    second = ifc_file.create_entity("IfcStyledItem", Styles=[mutual])
    first.Item = second
    second.Item = first
    own = ifc_file.create_entity("IfcSurfaceStyle", Name="Self")
    styled = ifc_file.create_entity("IfcStyledItem", Styles=[own])
    styled.Item = styled
    path = _write(ifc_file)
    try:
        _assert_lookup(path, {"Mutual": set(), "Self": set()})
    finally:
        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--lookup":
        _lookup_entrypoint(sys.argv[2])
