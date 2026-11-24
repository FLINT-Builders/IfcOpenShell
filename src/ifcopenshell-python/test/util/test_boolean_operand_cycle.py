# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 IfcOpenShell contributors
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
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

"""Boolean-operand walks must finish on cyclic IFC input.

These tests are the expected behaviour for ``get_extrusions``,
``get_base_extrusions``, and every other unbounded ``FirstOperand`` /
``SecondOperand`` walk that shares that bug. A cycle must not spin: the walk
stops when an operand repeats, sibling representation items are still
returned, and an acyclic chain still yields its extrusion.

The same loops in Bonsai are not imported here (they require Blender):
``Loader.get_extrusion_vector``, ``Model.get_extrusion``, ``Model.get_booleans``,
``Drawing.get_extrusion_vector``, ``Geometry.get_representation_styles``,
``import_ifc.resolve_all_stylable_representation_items``, and
``wall.get_extrusion_data``.
"""

from __future__ import annotations

import signal
import sys
from pathlib import Path

import pytest

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.element
import ifcopenshell.util.representation
import ifcopenshell.util.selector
import ifcopenshell.util.shape
from ifcopenshell.api.geometry.regenerate_wall_representation import Regenerator

_SRC = Path(__file__).resolve().parents[3]
for _extra in (_SRC / "ifcquery", _SRC / "ifccsv"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import ifccsv
import ifcquery.info
import ifcquery.select

_WALK_SECONDS = 0.5
_PROFILE_QUERY = 'query:"profiles.ProfileName"="P"'


class OperandWalkHung(BaseException):
    """A boolean-operand walk did not return before the deadline.

    ``BaseException`` so product code that uses ``except Exception`` cannot
    report a hang as an empty result.
    """


def assert_terminates(label, fn, seconds=_WALK_SECONDS):
    def handler(signum, frame):
        raise OperandWalkHung(label)

    previous = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn()
    except OperandWalkHung:
        pytest.fail(f"{label} did not finish; the boolean-operand walk is unbounded")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous)


def _point(file, coords):
    return file.create_entity("IfcCartesianPoint", Coordinates=tuple(coords))


def _axis3(file, origin=(0.0, 0.0, 0.0)):
    return file.create_entity("IfcAxis2Placement3D", Location=_point(file, origin))


class BodyModel:
    """Minimal product whose Model/Body/MODEL_VIEW item is whatever we attach."""

    def __init__(self, schema="IFC4"):
        self.file = ifcopenshell.file(schema=schema)
        origin = _axis3(self.file)
        parent = self.file.create_entity(
            "IfcGeometricRepresentationContext",
            ContextType="Model",
            CoordinateSpaceDimension=3,
            Precision=1.0e-5,
            WorldCoordinateSystem=origin,
        )
        self.body = self.file.create_entity(
            "IfcGeometricRepresentationSubContext",
            ContextIdentifier="Body",
            ContextType="Model",
            ParentContext=parent,
            TargetView="MODEL_VIEW",
        )
        self.wall = self.file.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="W")

    def extrusion(self, depth=3.0, profile_name="P"):
        profile = self.file.create_entity(
            "IfcRectangleProfileDef",
            ProfileType="AREA",
            ProfileName=profile_name,
            Position=self.file.create_entity("IfcAxis2Placement2D", Location=_point(self.file, (0.0, 0.0))),
            XDim=1.0,
            YDim=0.2,
        )
        return self.file.create_entity(
            "IfcExtrudedAreaSolid",
            SweptArea=profile,
            Position=_axis3(self.file),
            ExtrudedDirection=self.file.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)),
            Depth=float(depth),
        )

    def arbitrary_extrusion(self, x_max=4.0, depth=3.0):
        coords = [(0.0, 0.0), (x_max, 0.0), (x_max, 0.2), (0.0, 0.2), (0.0, 0.0)]
        curve = self.file.create_entity("IfcPolyline", Points=[_point(self.file, xy) for xy in coords])
        profile = self.file.create_entity(
            "IfcArbitraryClosedProfileDef", ProfileType="AREA", ProfileName="A", OuterCurve=curve
        )
        return self.file.create_entity(
            "IfcExtrudedAreaSolid",
            SweptArea=profile,
            Position=_axis3(self.file),
            ExtrudedDirection=self.file.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)),
            Depth=float(depth),
        )

    def halfspace(self):
        plane = self.file.create_entity("IfcPlane", Position=_axis3(self.file))
        return self.file.create_entity("IfcHalfSpaceSolid", BaseSurface=plane, AgreementFlag=False)

    def boolean(self, first, second, clipping=False):
        return self.file.create_entity(
            "IfcBooleanClippingResult" if clipping else "IfcBooleanResult",
            Operator="DIFFERENCE",
            FirstOperand=first,
            SecondOperand=second,
        )

    def style(self, item, name):
        surface = self.file.create_entity("IfcSurfaceStyle", Name=name, Side="BOTH", Styles=[])
        self.file.create_entity("IfcStyledItem", Item=item, Styles=[surface])
        return surface

    def represent(self, items, representation_type="CSG"):
        if not isinstance(items, (list, tuple)):
            items = [items]
        rep = self.file.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=self.body,
            RepresentationIdentifier="Body",
            RepresentationType=representation_type,
            Items=list(items),
        )
        self.wall.Representation = self.file.create_entity("IfcProductDefinitionShape", Representations=[rep])
        return rep

    def map_item(self, item):
        """Put ``item`` behind one mapped representation on the wall."""
        inner = self.file.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=self.body,
            RepresentationIdentifier="Body",
            RepresentationType="CSG",
            Items=[item],
        )
        mapping = self.file.create_entity(
            "IfcRepresentationMap",
            MappingOrigin=_axis3(self.file),
            MappedRepresentation=inner,
        )
        mapped = self.file.create_entity(
            "IfcMappedItem",
            MappingSource=mapping,
            MappingTarget=self.file.create_entity(
                "IfcCartesianTransformationOperator3D", LocalOrigin=_point(self.file, (0.0, 0.0, 0.0))
            ),
        )
        return self.represent(mapped, "MappedRepresentation")

    def reopen(self, tmp_path, name):
        path = tmp_path / f"{name}.ifc"
        self.file.write(str(path))
        model = ifcopenshell.open(str(path))
        return model, model.by_type("IfcWall")[0]


def _body_items(wall):
    rep = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
    return ifcopenshell.util.representation.resolve_representation(rep).Items


def _open_self(tmp_path, schema="IFC4", styled=False):
    model = BodyModel(schema)
    other = model.extrusion(1.0, profile_name="Other")
    if styled:
        model.style(other, "CycleStyle")
    cycle = model.boolean(other, other)
    cycle.FirstOperand = cycle
    model.represent(cycle)
    return model.reopen(tmp_path, f"self-{schema}-{styled}")


def _open_mutual(tmp_path, schema="IFC4"):
    model = BodyModel(schema)
    other = model.extrusion(1.0, profile_name="Other")
    first = model.boolean(other, other)
    second = model.boolean(first, other)
    first.FirstOperand = second
    model.represent(second)
    return model.reopen(tmp_path, f"mutual-{schema}")


def _open_sibling(tmp_path):
    """A cyclic boolean followed by a real extrusion in the same body."""
    model = BodyModel()
    kept = model.extrusion(2.5, profile_name="P")
    other = model.extrusion(1.0, profile_name="Other")
    cycle = model.boolean(other, other)
    cycle.FirstOperand = cycle
    model.represent([cycle, kept])
    return model.reopen(tmp_path, "sibling")


def _open_mapped(tmp_path):
    model = BodyModel()
    other = model.extrusion(1.0, profile_name="Other")
    cycle = model.boolean(other, other)
    cycle.FirstOperand = cycle
    model.map_item(cycle)
    return model.reopen(tmp_path, "mapped")


def _open_second_operand_cycle(tmp_path):
    """FirstOperand is the extrusion. SecondOperand points back at the boolean."""
    model = BodyModel()
    solid = model.extrusion(2.5, profile_name="P")
    model.style(solid, "CycleStyle")
    cycle = model.boolean(solid, solid)
    cycle.SecondOperand = cycle
    model.represent(cycle)
    return model.reopen(tmp_path, "second")


def _open_chain(tmp_path, depth=8):
    model = BodyModel()
    solid = model.extrusion(2.5, profile_name="P")
    other = model.halfspace()
    item = solid
    for _ in range(depth):
        item = model.boolean(item, other)
    model.represent(item)
    return model.reopen(tmp_path, f"chain-{depth}")


def _open_reference_profile(tmp_path):
    model = BodyModel()
    solid = model.arbitrary_extrusion(x_max=4.0)
    wrapped = model.boolean(solid, model.halfspace())
    model.represent(wrapped)
    return model.reopen(tmp_path, "reference")


def _open_clip_self(tmp_path):
    model = BodyModel()
    clip = model.boolean(model.halfspace(), model.halfspace(), clipping=True)
    clip.FirstOperand = clip
    model.represent(clip, "Clipping")
    return model.reopen(tmp_path, "clip-self")


def _open_clip_chain(tmp_path, depth=3):
    model = BodyModel()
    solid = model.extrusion(2.0, profile_name="P")
    item = solid
    for _ in range(depth):
        item = model.boolean(item, model.halfspace(), clipping=True)
    model.represent(item, "Clipping")
    return model.reopen(tmp_path, f"clip-chain-{depth}")


def _ids(items):
    return [item.id() for item in items]


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_parser_keeps_self_referencing_first_operand(tmp_path, schema):
    model, wall = _open_self(tmp_path, schema)
    item = _body_items(wall)[0]
    assert item.is_a("IfcBooleanResult")
    assert item.FirstOperand == item
    assert model.by_id(item.id()) == item


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_parser_keeps_mutually_referencing_first_operands(tmp_path, schema):
    _, wall = _open_mutual(tmp_path, schema)
    item = _body_items(wall)[0]
    assert item.FirstOperand.FirstOperand == item
    assert item.FirstOperand != item


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_get_extrusions_stops_on_self_and_mutual_cycles(tmp_path, schema):
    _, self_wall = _open_self(tmp_path, schema)
    _, mutual_wall = _open_mutual(tmp_path, schema)
    assert assert_terminates("get_extrusions self", lambda: ifcopenshell.util.shape.get_extrusions(self_wall)) == []
    assert assert_terminates("get_extrusions mutual", lambda: ifcopenshell.util.shape.get_extrusions(mutual_wall)) == []


def test_get_extrusions_keeps_sibling_and_mapped_cycles(tmp_path):
    _, sibling = _open_sibling(tmp_path)
    kept = next(item for item in _body_items(sibling) if item.is_a("IfcExtrudedAreaSolid"))
    found = assert_terminates("get_extrusions sibling", lambda: ifcopenshell.util.shape.get_extrusions(sibling))
    assert _ids(found) == [kept.id()]

    _, mapped = _open_mapped(tmp_path)
    assert _body_items(mapped)[0].is_a("IfcBooleanResult")
    assert _body_items(mapped)[0].FirstOperand == _body_items(mapped)[0]
    assert assert_terminates("get_extrusions mapped", lambda: ifcopenshell.util.shape.get_extrusions(mapped)) == []


def test_get_base_extrusions_stops_on_cycles_and_keeps_siblings(tmp_path):
    _, self_wall = _open_self(tmp_path)
    _, mutual_wall = _open_mutual(tmp_path)
    _, sibling = _open_sibling(tmp_path)
    kept = next(item for item in _body_items(sibling) if item.is_a("IfcExtrudedAreaSolid"))
    assert (
        assert_terminates("get_base_extrusions self", lambda: ifcopenshell.util.shape.get_base_extrusions(self_wall))
        == []
    )
    assert (
        assert_terminates(
            "get_base_extrusions mutual", lambda: ifcopenshell.util.shape.get_base_extrusions(mutual_wall)
        )
        == []
    )
    found = assert_terminates(
        "get_base_extrusions sibling", lambda: ifcopenshell.util.shape.get_base_extrusions(sibling)
    )
    assert _ids(found) == [kept.id()]


def test_get_profiles_stops_on_cycles_and_keeps_sibling_profile(tmp_path):
    _, self_wall = _open_self(tmp_path)
    _, mutual_wall = _open_mutual(tmp_path)
    _, sibling = _open_sibling(tmp_path)
    assert assert_terminates("get_profiles self", lambda: ifcopenshell.util.shape.get_profiles(self_wall)) == []
    assert assert_terminates("get_profiles mutual", lambda: ifcopenshell.util.shape.get_profiles(mutual_wall)) == []
    profiles = assert_terminates("get_profiles sibling", lambda: ifcopenshell.util.shape.get_profiles(sibling))
    assert [profile.ProfileName for profile in profiles] == ["P"]


def test_selector_profiles_query_stops_on_cycle(tmp_path):
    model, wall = _open_self(tmp_path)
    assert (
        assert_terminates(
            "get_element_value profiles", lambda: ifcopenshell.util.selector.get_element_value(wall, "profiles")
        )
        == []
    )
    assert (
        assert_terminates(
            "get_element_value profiles.ProfileName",
            lambda: ifcopenshell.util.selector.get_element_value(wall, "profiles.ProfileName"),
        )
        == []
    )
    matched = assert_terminates(
        "filter_elements profiles", lambda: ifcopenshell.util.selector.filter_elements(model, _PROFILE_QUERY)
    )
    assert matched == set()
    selected = assert_terminates("ifc_select profiles", lambda: ifcquery.select.select(model, _PROFILE_QUERY))
    assert selected == []
    formatted = assert_terminates(
        "format profiles", lambda: ifcopenshell.util.selector.format("{{profiles.ProfileName}}", wall)
    )
    assert formatted == ""


def test_ifccsv_profiles_column_stops_on_cycle(tmp_path):
    model, wall = _open_self(tmp_path)
    csv = ifccsv.IfcCsv()

    def export():
        csv.export(model, [wall], ["Name", "profiles"], include_global_id=False)
        return csv.results

    results = assert_terminates("ifccsv profiles", export)
    assert results == [["W", ""]]


def test_reference_line_stops_on_cycle(tmp_path):
    _, wall = _open_self(tmp_path)
    line = assert_terminates(
        "get_reference_line", lambda: ifcopenshell.util.representation.get_reference_line(wall, fallback_length=2.5)
    )
    assert [point.tolist() for point in line] == [[0.0, 0.0], [2.5, 0.0]]


def test_get_styles_stops_on_first_operand_cycle(tmp_path):
    _, wall = _open_self(tmp_path, styled=True)
    styles = assert_terminates("get_styles first-operand cycle", lambda: ifcopenshell.util.element.get_styles(wall))
    assert [style.Name for style in styles] == ["CycleStyle"]


def test_get_styles_stops_on_second_operand_cycle(tmp_path):
    _, wall = _open_second_operand_cycle(tmp_path)
    styles = assert_terminates("get_styles second-operand cycle", lambda: ifcopenshell.util.element.get_styles(wall))
    assert [style.Name for style in styles] == ["CycleStyle"]


def _base_item_types(wall):
    rep = wall.Representation.Representations[0]
    items = list(ifcopenshell.util.representation.resolve_base_items(rep))
    assert all(not item.is_a("IfcBooleanResult") for item in items)
    return [item.is_a() for item in items]


def test_resolve_base_items_stops_on_first_operand_cycle(tmp_path):
    _, wall = _open_self(tmp_path, styled=True)
    assert assert_terminates("resolve_base_items first", lambda: _base_item_types(wall)) == ["IfcExtrudedAreaSolid"]


def test_resolve_base_items_stops_on_second_operand_cycle(tmp_path):
    _, wall = _open_second_operand_cycle(tmp_path)
    assert assert_terminates("resolve_base_items second", lambda: _base_item_types(wall)) == ["IfcExtrudedAreaSolid"]


def test_wall_vectors_stop_on_cycle(tmp_path):
    _, wall = _open_self(tmp_path)
    regenerator = Regenerator.__new__(Regenerator)
    regenerator.fallback_angle = None
    regenerator.fallback_height = 9.0
    regenerator.is_angled = False
    vectors = assert_terminates("get_wall_vectors", lambda: regenerator.get_wall_vectors(wall))
    assert vectors["d"] == 9.0
    assert vectors["h"] == 9.0
    assert regenerator.is_angled is False


def test_clipping_walk_and_info_stop_on_cycle(tmp_path):
    _, wall = _open_clip_self(tmp_path)
    item = _body_items(wall)[0]
    assert item.is_a("IfcBooleanClippingResult")
    assert item.FirstOperand == item
    base, planes = assert_terminates("walk clipping", lambda: ifcquery.info._walk_clipping(item))
    assert base == item
    assert isinstance(planes, list)
    summary = assert_terminates("info", lambda: ifcquery.info.info(wall.file, wall))
    assert summary["id"] == wall.id()
    assert summary["type"] == "IfcWall"


def test_acyclic_boolean_chain_still_yields_extrusion_and_profile(tmp_path):
    _, wall = _open_chain(tmp_path, depth=8)
    extrusions = ifcopenshell.util.shape.get_extrusions(wall)
    assert len(extrusions) == 1
    assert extrusions[0].is_a("IfcExtrudedAreaSolid")
    assert extrusions[0].Depth == 2.5
    assert ifcopenshell.util.shape.get_base_extrusions(wall)[0] == extrusions[0]
    assert ifcopenshell.util.shape.get_profiles(wall)[0].ProfileName == "P"
    assert ifcopenshell.util.selector.get_element_value(wall, "profiles.ProfileName") == ["P"]
    assert wall in ifcopenshell.util.selector.filter_elements(wall.file, _PROFILE_QUERY)
    selected = ifcquery.select.select(wall.file, _PROFILE_QUERY)
    assert [row["id"] for row in selected] == [wall.id()]
    assert ifcopenshell.util.selector.format("{{profiles.ProfileName}}", wall) == "P"

    csv = ifccsv.IfcCsv()
    csv.export(wall.file, [wall], ["Name", "profiles"], include_global_id=False)
    assert csv.results[0][0] == "W"
    assert "IfcRectangleProfileDef" in csv.results[0][1]

    regenerator = Regenerator.__new__(Regenerator)
    regenerator.fallback_angle = None
    regenerator.fallback_height = 9.0
    regenerator.is_angled = False
    assert regenerator.get_wall_vectors(wall)["d"] == 2.5


def test_second_operand_cycle_does_not_hide_the_first_operand_extrusion(tmp_path):
    _, wall = _open_second_operand_cycle(tmp_path)
    extrusions = ifcopenshell.util.shape.get_extrusions(wall)
    assert len(extrusions) == 1
    assert extrusions[0].SweptArea.ProfileName == "P"
    assert ifcopenshell.util.shape.get_base_extrusions(wall) == extrusions


def test_reference_line_uses_acyclic_extrusion_profile(tmp_path):
    _, wall = _open_reference_profile(tmp_path)
    line = ifcopenshell.util.representation.get_reference_line(wall, fallback_length=2.5)
    assert [point.tolist() for point in line] == [[0.0, 0.0], [4.0, 0.0]]


def test_styles_and_base_items_keep_acyclic_operands(tmp_path):
    model = BodyModel()
    solid = model.extrusion(2.5, profile_name="P")
    model.style(solid, "CycleStyle")
    model.represent(model.boolean(solid, model.halfspace()))
    _, wall = model.reopen(tmp_path, "styled-chain")
    styles = ifcopenshell.util.element.get_styles(wall)
    assert [style.Name for style in styles] == ["CycleStyle"]
    items = list(ifcopenshell.util.representation.resolve_base_items(wall.Representation.Representations[0]))
    assert sorted(item.is_a() for item in items) == ["IfcExtrudedAreaSolid", "IfcHalfSpaceSolid"]


def test_clipping_chain_still_reaches_the_extrusion(tmp_path):
    _, wall = _open_clip_chain(tmp_path, depth=3)
    item = _body_items(wall)[0]
    base, planes = ifcquery.info._walk_clipping(item)
    assert base.is_a("IfcExtrudedAreaSolid")
    assert len(planes) == 3
    summary = ifcquery.info.info(wall.file, wall)
    assert summary["geometry_summary"]["representation_type"] == "Clipping"
    assert summary["geometry_summary"]["solids"][0]["solid_type"] == "IfcExtrudedAreaSolid"
