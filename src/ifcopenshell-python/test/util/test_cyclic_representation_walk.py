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

"""Style and representation walks must finish on cyclic mapped items and boolean operands.

An IFC file can contain an IfcMappedItem whose mapped representation contains that
item, or an IfcBooleanResult that uses itself as an operand. The STEP parser accepts
both. These tests fail while the walks have no visited-set guard, and they pass once
each walk returns and reports every reached style or base item once.
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_SRC = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(_SRC / "ifcopenshell-python"),
    str(_SRC / "ifccsv"),
    str(_SRC / "ifcquery"),
]

import ifcopenshell
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.util.element
import ifcopenshell.util.representation
import ifcopenshell.util.selector
import ifcopenshell.util.shape

_TIMEOUT_SECONDS = 8
_TEMP_FILES: list[str] = []
_RETAINED: list = []


def _cleanup_temp_files() -> None:
    for path in _TEMP_FILES:
        try:
            os.unlink(path)
        except OSError:
            pass


atexit.register(_cleanup_temp_files)


def _body_context(ifc_file: ifcopenshell.file):
    ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcProject")
    model = ifcopenshell.api.context.add_context(ifc_file, context_type="Model")
    return ifcopenshell.api.context.add_context(
        ifc_file,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model,
    )


def _placement(ifc_file: ifcopenshell.file):
    origin = ifc_file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    axis = ifc_file.create_entity("IfcAxis2Placement3D", Location=origin)
    return origin, axis


def _representation(ifc_file, body, identifier, representation_type, items):
    return ifc_file.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=body,
        RepresentationIdentifier=identifier,
        RepresentationType=representation_type,
        Items=items,
    )


def _mapped_item(ifc_file, mapped_representation, axis, origin):
    target = ifc_file.create_entity("IfcCartesianTransformationOperator3D", LocalOrigin=origin)
    rep_map = ifc_file.create_entity(
        "IfcRepresentationMap", MappingOrigin=axis, MappedRepresentation=mapped_representation
    )
    return ifc_file.create_entity("IfcMappedItem", MappingSource=rep_map, MappingTarget=target)


def _extrusion(ifc_file):
    point = ifc_file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0))
    profile = ifc_file.create_entity(
        "IfcArbitraryClosedProfileDef",
        ProfileType="AREA",
        OuterCurve=ifc_file.create_entity("IfcPolyline", Points=[point, point, point]),
    )
    direction = ifc_file.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0))
    origin = ifc_file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    placement = ifc_file.create_entity("IfcAxis2Placement3D", Location=origin)
    return ifc_file.create_entity(
        "IfcExtrudedAreaSolid",
        SweptArea=profile,
        Position=placement,
        ExtrudedDirection=direction,
        Depth=1.0,
    )


def _style(ifc_file, item, name):
    style = ifc_file.create_entity("IfcSurfaceStyle", Name=name, Side="BOTH")
    ifc_file.create_entity("IfcStyledItem", Item=item, Styles=[style])
    return style


def _assign_wall(ifc_file, body, representation):
    wall = ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcWall")
    ifcopenshell.api.geometry.assign_representation(ifc_file, product=wall, representation=representation)
    return wall


def _reopen(ifc_file: ifcopenshell.file) -> ifcopenshell.file:
    """Write the model and load it back through the STEP parser.

    The reopened file is the attacker-supplied input. It stays on disk until
    process exit so the opened model remains valid for the assertions.
    """
    handle = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
    handle.close()
    ifc_file.write(handle.name)
    _TEMP_FILES.append(handle.name)
    return ifcopenshell.open(handle.name)


def _wall(ifc_file: ifcopenshell.file):
    walls = ifc_file.by_type("IfcWall")
    assert len(walls) == 1
    return walls[0]


def _body(wall):
    reps = [rep for rep in wall.Representation.Representations if rep.RepresentationIdentifier == "Body"]
    assert len(reps) == 1
    return reps[0]


def _ready(ifc_file: ifcopenshell.file) -> ifcopenshell.file:
    """Keep the reopened model and its styled items alive for inverse lookups."""
    _RETAINED.append(ifc_file)
    _RETAINED.append(ifc_file.by_type("IfcStyledItem"))
    return ifc_file


def _style_names(element) -> list[str]:
    return sorted(style.Name for style in ifcopenshell.util.element.get_styles(element))


def _self_mapped_file(styled: bool) -> ifcopenshell.file:
    ifc_file = ifcopenshell.file(schema="IFC4")
    body = _body_context(ifc_file)
    origin, axis = _placement(ifc_file)
    representation = _representation(ifc_file, body, "Body", "MappedRepresentation", [])
    mapped = _mapped_item(ifc_file, representation, axis, origin)
    representation.Items = [mapped]
    if styled:
        _style(ifc_file, mapped, "X")
    _assign_wall(ifc_file, body, representation)
    return _reopen(ifc_file)


def _two_node_mapped_file() -> ifcopenshell.file:
    """Rep A maps to rep B, rep B maps back to rep A, and only B holds a styled extrusion."""
    ifc_file = ifcopenshell.file(schema="IFC4")
    body = _body_context(ifc_file)
    origin, axis = _placement(ifc_file)
    rep_a = _representation(ifc_file, body, "Body", "MappedRepresentation", [])
    rep_b = _representation(ifc_file, body, "Body", "MappedRepresentation", [])
    item_a = _mapped_item(ifc_file, rep_b, axis, origin)
    item_b = _mapped_item(ifc_file, rep_a, axis, origin)
    extrusion = _extrusion(ifc_file)
    _style(ifc_file, extrusion, "Far")
    rep_a.Items = [item_a]
    rep_b.Items = [item_b, extrusion]
    _assign_wall(ifc_file, body, rep_a)
    return _reopen(ifc_file)


def _boolean_self_file() -> ifcopenshell.file:
    """The boolean result is its own first operand. The styled solid is the second operand."""
    ifc_file = ifcopenshell.file(schema="IFC4")
    body = _body_context(ifc_file)
    extrusion = _extrusion(ifc_file)
    _style(ifc_file, extrusion, "Solid")
    boolean = ifc_file.create_entity(
        "IfcBooleanResult", Operator="UNION", FirstOperand=extrusion, SecondOperand=extrusion
    )
    boolean.FirstOperand = boolean
    representation = _representation(ifc_file, body, "Body", "CSG", [boolean])
    _assign_wall(ifc_file, body, representation)
    return _reopen(ifc_file)


def _boolean_two_node_file() -> ifcopenshell.file:
    ifc_file = ifcopenshell.file(schema="IFC4")
    body = _body_context(ifc_file)
    solid_a = _extrusion(ifc_file)
    solid_b = _extrusion(ifc_file)
    _style(ifc_file, solid_b, "Other")
    boolean_a = ifc_file.create_entity(
        "IfcBooleanResult", Operator="UNION", FirstOperand=solid_a, SecondOperand=solid_a
    )
    boolean_b = ifc_file.create_entity(
        "IfcBooleanResult", Operator="UNION", FirstOperand=solid_b, SecondOperand=solid_b
    )
    boolean_a.FirstOperand = boolean_b
    boolean_b.FirstOperand = boolean_a
    _style(ifc_file, boolean_a, "Bool")
    representation = _representation(ifc_file, body, "Body", "CSG", [boolean_a])
    _assign_wall(ifc_file, body, representation)
    return _reopen(ifc_file)


def _boolean_second_operand_file() -> ifcopenshell.file:
    ifc_file = ifcopenshell.file(schema="IFC4")
    body = _body_context(ifc_file)
    extrusion = _extrusion(ifc_file)
    _style(ifc_file, extrusion, "Solid")
    boolean = ifc_file.create_entity(
        "IfcBooleanResult", Operator="UNION", FirstOperand=extrusion, SecondOperand=extrusion
    )
    boolean.SecondOperand = boolean
    representation = _representation(ifc_file, body, "Body", "CSG", [boolean])
    _assign_wall(ifc_file, body, representation)
    return _reopen(ifc_file)


def _clipping_self_file() -> ifcopenshell.file:
    ifc_file = ifcopenshell.file(schema="IFC4")
    body = _body_context(ifc_file)
    extrusion = _extrusion(ifc_file)
    point = ifc_file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    location = ifc_file.create_entity("IfcAxis2Placement3D", Location=point)
    plane = ifc_file.create_entity("IfcPlane", Position=location)
    half_space = ifc_file.create_entity("IfcHalfSpaceSolid", BaseSurface=plane, AgreementFlag=True)
    clipping = ifc_file.create_entity(
        "IfcBooleanClippingResult", Operator="DIFFERENCE", FirstOperand=extrusion, SecondOperand=half_space
    )
    clipping.FirstOperand = clipping
    representation = _representation(ifc_file, body, "Body", "Clipping", [clipping])
    _assign_wall(ifc_file, body, representation)
    return _reopen(ifc_file)


def _acyclic_mapped_file() -> ifcopenshell.file:
    ifc_file = ifcopenshell.file(schema="IFC4")
    body = _body_context(ifc_file)
    origin, axis = _placement(ifc_file)
    extrusion = _extrusion(ifc_file)
    _style(ifc_file, extrusion, "Once")
    mapped_rep = _representation(ifc_file, body, "Body", "SweptSolid", [extrusion])
    outer = _representation(ifc_file, body, "Body", "MappedRepresentation", [])
    outer.Items = [_mapped_item(ifc_file, mapped_rep, axis, origin)]
    _assign_wall(ifc_file, body, outer)
    return _reopen(ifc_file)


def _acyclic_boolean_file() -> ifcopenshell.file:
    ifc_file = ifcopenshell.file(schema="IFC4")
    body = _body_context(ifc_file)
    first = _extrusion(ifc_file)
    second = _extrusion(ifc_file)
    _style(ifc_file, first, "Base")
    boolean = ifc_file.create_entity(
        "IfcBooleanResult", Operator="DIFFERENCE", FirstOperand=first, SecondOperand=second
    )
    representation = _representation(ifc_file, body, "Body", "CSG", [boolean])
    _assign_wall(ifc_file, body, representation)
    return _reopen(ifc_file)


def _assert_self_mapped(wall) -> None:
    item = _body(wall).Items[0]
    assert item.is_a("IfcMappedItem")
    mapped = item.MappingSource.MappedRepresentation
    assert mapped.id() == _body(wall).id()
    assert item.id() in {candidate.id() for candidate in mapped.Items}


def _assert_two_node_mapped(wall) -> None:
    item_a = _body(wall).Items[0]
    item_b = item_a.MappingSource.MappedRepresentation.Items[0]
    assert item_a.is_a("IfcMappedItem") and item_b.is_a("IfcMappedItem")
    assert item_b.MappingSource.MappedRepresentation.Items[0].id() == item_a.id()


def _assert_boolean_self(wall) -> None:
    boolean = _body(wall).Items[0]
    assert boolean.is_a("IfcBooleanResult")
    assert boolean.FirstOperand.id() == boolean.id()
    assert boolean.SecondOperand.is_a("IfcExtrudedAreaSolid")


def _cases() -> dict:
    import ifccsv
    from ifcquery.info import _summarize_rep, _walk_clipping, info
    from ifcquery.select import select

    def acyclic_mapped():
        wall = _wall(_ready(_acyclic_mapped_file()))
        return {
            "styles": _style_names(wall),
            "indexed": ifcopenshell.util.selector.get_element_value(wall, "styles.0.Name"),
            "formatted": ifcopenshell.util.selector.format("{{styles.Name}}", wall),
        }

    def acyclic_boolean():
        wall = _wall(_ready(_acyclic_boolean_file()))
        extrusions = ifcopenshell.util.shape.get_extrusions(wall)
        base_items = [item.is_a() for item in ifcopenshell.util.representation.resolve_base_items(_body(wall))]
        return {
            "styles": _style_names(wall),
            "extrusions": [item.is_a() for item in extrusions] if extrusions else [],
            "base_items": base_items,
        }

    def styles_self_mapped_plain():
        wall = _wall(_ready(_self_mapped_file(styled=False)))
        _assert_self_mapped(wall)
        return _style_names(wall)

    def styles_self_mapped_styled():
        wall = _wall(_ready(_self_mapped_file(styled=True)))
        _assert_self_mapped(wall)
        assert _body(wall).Items[0].StyledByItem[0].Styles[0].Name == "X"
        return _style_names(wall)

    def styles_two_node():
        wall = _wall(_ready(_two_node_mapped_file()))
        _assert_two_node_mapped(wall)
        return _style_names(wall)

    def styles_boolean_self():
        wall = _wall(_ready(_boolean_self_file()))
        _assert_boolean_self(wall)
        return _style_names(wall)

    def styles_boolean_two_node():
        wall = _wall(_ready(_boolean_two_node_file()))
        boolean_a = _body(wall).Items[0]
        boolean_b = boolean_a.FirstOperand
        assert boolean_b.FirstOperand.id() == boolean_a.id()
        return _style_names(wall)

    def styles_boolean_second_operand():
        wall = _wall(_ready(_boolean_second_operand_file()))
        boolean = _body(wall).Items[0]
        assert boolean.SecondOperand.id() == boolean.id()
        assert boolean.FirstOperand.is_a("IfcExtrudedAreaSolid")
        return _style_names(wall)

    def selector_match():
        ifc_file = _ready(_self_mapped_file(styled=True))
        wall = _wall(ifc_file)
        _assert_self_mapped(wall)
        found = ifcopenshell.util.selector.filter_elements(ifc_file, 'IfcWall, query:"styles.Name" = "X"')
        return sorted(element.id() for element in found)

    def selector_miss():
        ifc_file = _ready(_self_mapped_file(styled=True))
        found = ifcopenshell.util.selector.filter_elements(ifc_file, 'query:"styles.Name" = "Nope"')
        return sorted(element.id() for element in found)

    def element_value_and_format():
        wall = _wall(_ready(_self_mapped_file(styled=True)))
        return {
            "names": ifcopenshell.util.selector.get_element_value(wall, "styles.Name"),
            "indexed": ifcopenshell.util.selector.get_element_value(wall, "styles.0.Name"),
            "format_name": ifcopenshell.util.selector.format("{{styles.Name}}", wall),
            "format_indexed": ifcopenshell.util.selector.format("{{styles.0.Name}}", wall),
        }

    def ifccsv_export():
        ifc_file = _ready(_two_node_mapped_file())
        wall = _wall(ifc_file)
        handle = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        handle.close()
        try:
            ifccsv.IfcCsv().export(
                ifc_file,
                [wall],
                ["styles.Name", "styles.0.Name"],
                format="csv",
                output=handle.name,
            )
            text = Path(handle.name).read_text(encoding="utf-8")
        finally:
            os.unlink(handle.name)
        return {"csv": text, "wall_id": wall.GlobalId}

    def ifcquery_select():
        ifc_file = _ready(_self_mapped_file(styled=True))
        rows = select(ifc_file, 'IfcWall, query:"styles.Name" = "X"')
        return [row["id"] for row in rows]

    def resolve_self_mapped():
        wall = _wall(_ready(_self_mapped_file(styled=False)))
        representation = _body(wall)
        _assert_self_mapped(wall)
        base_items = [item.is_a() for item in ifcopenshell.util.representation.resolve_base_items(representation)]
        resolved_items = [
            item["item"].is_a() for item in ifcopenshell.util.representation.resolve_items(representation)
        ]
        resolved = ifcopenshell.util.representation.resolve_representation(representation)
        return {
            "base_items": base_items,
            "resolved_items": resolved_items,
            "resolved_type": resolved.is_a(),
            "resolved_id": resolved.id(),
            "body_id": representation.id(),
        }

    def resolve_two_node():
        wall = _wall(_ready(_two_node_mapped_file()))
        representation = _body(wall)
        base_items = [item.is_a() for item in ifcopenshell.util.representation.resolve_base_items(representation)]
        resolved_items = [
            item["item"].is_a() for item in ifcopenshell.util.representation.resolve_items(representation)
        ]
        resolved = ifcopenshell.util.representation.resolve_representation(representation)
        return {
            "base_items": base_items,
            "resolved_items": resolved_items,
            "resolved_type": resolved.is_a(),
            "resolved_id": resolved.id(),
            "body_id": representation.id(),
            "other_id": representation.Items[0].MappingSource.MappedRepresentation.id(),
        }

    def resolve_boolean_self():
        wall = _wall(_ready(_boolean_self_file()))
        representation = _body(wall)
        base_items = [item.is_a() for item in ifcopenshell.util.representation.resolve_base_items(representation)]
        return base_items

    def shape_extrusions():
        wall = _wall(_ready(_boolean_self_file()))
        extrusions = ifcopenshell.util.shape.get_extrusions(wall) or []
        base = ifcopenshell.util.shape.get_base_extrusions(wall) or []
        profiles = ifcopenshell.util.selector.get_element_value(wall, "profiles")
        return {
            "extrusions": [item.is_a() for item in extrusions],
            "base_extrusions": [item.is_a() for item in base],
            "profiles": profiles,
        }

    def summarize_mapped():
        wall = _wall(_ready(_self_mapped_file(styled=False)))
        summary = _summarize_rep(_body(wall))
        return {"type": summary.get("representation_type"), "keys": sorted(summary)}

    def clipping_info():
        ifc_file = _ready(_clipping_self_file())
        wall = _wall(ifc_file)
        clipping = _body(wall).Items[0]
        assert clipping.is_a("IfcBooleanClippingResult")
        assert clipping.FirstOperand.id() == clipping.id()
        base, planes = _walk_clipping(clipping)
        described = info(ifc_file, wall)
        return {
            "base": base.is_a(),
            "planes": len(planes),
            "info_id": described["id"],
            "wall_id": wall.id(),
        }

    def set_style_name():
        ifc_file = _ready(_self_mapped_file(styled=True))
        wall = _wall(ifc_file)
        ifcopenshell.util.selector.set_element_value(ifc_file, wall, "styles.Name", "Y")
        return {"done": True}

    return {
        "acyclic_mapped": acyclic_mapped,
        "acyclic_boolean": acyclic_boolean,
        "styles_self_mapped_plain": styles_self_mapped_plain,
        "styles_self_mapped_styled": styles_self_mapped_styled,
        "styles_two_node": styles_two_node,
        "styles_boolean_self": styles_boolean_self,
        "styles_boolean_two_node": styles_boolean_two_node,
        "styles_boolean_second_operand": styles_boolean_second_operand,
        "selector_match": selector_match,
        "selector_miss": selector_miss,
        "element_value_and_format": element_value_and_format,
        "ifccsv_export": ifccsv_export,
        "ifcquery_select": ifcquery_select,
        "resolve_self_mapped": resolve_self_mapped,
        "resolve_two_node": resolve_two_node,
        "resolve_boolean_self": resolve_boolean_self,
        "shape_extrusions": shape_extrusions,
        "summarize_mapped": summarize_mapped,
        "clipping_info": clipping_info,
        "set_style_name": set_style_name,
    }


def _run_case(name: str):
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", name],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"{name} did not finish within {_TIMEOUT_SECONDS}s; the representation walk is still looping"
        ) from exc
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_acyclic_mapped_item_style_is_reported_once():
    assert _run_case("acyclic_mapped") == {
        "styles": ["Once"],
        "indexed": "Once",
        "formatted": "Once",
    }


def test_acyclic_boolean_keeps_first_operand_style_and_extrusion():
    assert _run_case("acyclic_boolean") == {
        "styles": ["Base"],
        "extrusions": ["IfcExtrudedAreaSolid"],
        "base_items": ["IfcExtrudedAreaSolid", "IfcExtrudedAreaSolid"],
    }


def test_self_mapped_item_without_style_finishes():
    assert _run_case("styles_self_mapped_plain") == []


def test_self_mapped_styled_item_returns_that_style_once():
    assert _run_case("styles_self_mapped_styled") == ["X"]


def test_two_node_mapped_cycle_returns_the_far_style_once():
    assert _run_case("styles_two_node") == ["Far"]


def test_boolean_result_used_as_its_own_first_operand_returns_the_other_style_once():
    assert _run_case("styles_boolean_self") == ["Solid"]


def test_two_node_boolean_cycle_returns_each_reached_style_once():
    assert _run_case("styles_boolean_two_node") == ["Bool", "Other"]


def test_boolean_result_used_as_its_own_second_operand_returns_the_other_style_once():
    assert _run_case("styles_boolean_second_operand") == ["Solid"]


def test_selector_query_on_styles_matches_the_cyclic_wall():
    assert len(_run_case("selector_match")) == 1


def test_selector_query_on_styles_that_does_not_match_is_empty():
    assert _run_case("selector_miss") == []


def test_get_element_value_and_format_read_the_cyclic_style_once():
    assert _run_case("element_value_and_format") == {
        "names": ["X"],
        "indexed": "X",
        "format_name": "X",
        "format_indexed": "X",
    }


def test_ifccsv_styles_column_exports_the_cyclic_style_once():
    payload = _run_case("ifccsv_export")
    rows = [row for row in payload["csv"].splitlines() if row]
    assert rows[0].startswith("GlobalId,")
    assert len(rows) == 2
    _guid, names, indexed = rows[1].split(",")
    assert names == "Far"
    assert indexed == "Far"
    assert payload["wall_id"]


def test_ifcquery_select_on_styles_returns_the_cyclic_wall():
    found = _run_case("ifcquery_select")
    assert len(found) == 1


def test_resolve_walks_finish_on_a_self_mapped_representation():
    payload = _run_case("resolve_self_mapped")
    assert payload["base_items"] == []
    assert payload["resolved_items"] == []
    assert payload["resolved_type"] == "IfcShapeRepresentation"
    assert payload["resolved_id"] == payload["body_id"]


def test_resolve_walks_finish_on_a_two_node_mapped_cycle_and_keep_the_extrusion():
    payload = _run_case("resolve_two_node")
    assert payload["base_items"] == ["IfcExtrudedAreaSolid"]
    assert payload["resolved_items"] == ["IfcExtrudedAreaSolid"]
    assert payload["resolved_type"] == "IfcShapeRepresentation"
    assert payload["resolved_id"] in {payload["body_id"], payload["other_id"]}


def test_resolve_base_items_finishes_on_a_self_boolean_and_yields_the_solid_once():
    assert _run_case("resolve_boolean_self") == ["IfcExtrudedAreaSolid"]


def test_extrusion_and_profile_lookups_finish_on_a_self_boolean():
    assert _run_case("shape_extrusions") == {
        "extrusions": [],
        "base_extrusions": [],
        "profiles": [],
    }


def test_ifcquery_mapped_summary_finishes_on_a_self_mapped_representation():
    payload = _run_case("summarize_mapped")
    assert payload["type"] == "MappedRepresentation"


def test_clipping_operand_walk_records_the_half_space_once():
    payload = _run_case("clipping_info")
    assert payload["base"] == "IfcBooleanClippingResult"
    assert payload["planes"] == 1
    assert payload["info_id"] == payload["wall_id"]


def test_set_element_value_on_styles_finishes():
    assert _run_case("set_style_name") == {"done": True}


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--worker":
        try:
            result = _cases()[sys.argv[2]]()
        except Exception:
            import traceback

            traceback.print_exc(file=sys.stderr)
            sys.exit(1)
        json.dump(result, sys.stdout)
        sys.exit(0)
