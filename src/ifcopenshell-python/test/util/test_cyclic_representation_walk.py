# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 Dion Moult <dion@thinkmoult.com>
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

"""Cyclic boolean operands and mapped items must not make representation walks run forever.

An uploaded IFC file can contain an IfcBooleanResult that uses itself as an
operand, or IfcMappedItem representations that point at each other. These tests
open that file and run the library walks a caller such as Bonsai's profile-axis
check actually runs. Each walk has to finish and report every distinct base
solid once.
"""

import signal
from itertools import islice
from pathlib import Path
from types import SimpleNamespace

import pytest

import ifcopenshell
import ifcopenshell.util.element as element
import ifcopenshell.util.representation as representation
import ifcopenshell.util.shape as shape
from ifcopenshell.api.geometry.add_boolean import add_boolean
from ifcopenshell.api.geometry.regenerate_wall_representation import Regenerator
from ifcopenshell.api.geometry.remove_boolean import remove_boolean

_HEADER = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('cycle.ifc','2024-01-01T00:00:00',(''),(''),'test','test','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
"""

# Shared placement and a Body/MODEL_VIEW subcontext. Later entities start at #20.
_CONTEXT = """\
#1=IFCCARTESIANPOINT((0.,0.,0.));
#2=IFCAXIS2PLACEMENT3D(#1,$,$);
#10=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#2,$);
#11=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#10,$,.MODEL_VIEW.,$);
"""

_WALK_LIMIT = 32


class WalkDidNotFinish(BaseException):
    """Raised when a representation walk is still running at the deadline."""


def _on_alarm(signum, frame):
    raise WalkDidNotFinish()


def assert_finishes(fn, seconds=1.0):
    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn()
    except WalkDidNotFinish:
        pytest.fail(f"representation walk did not finish within {seconds}s")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def open_data(tmp_path: Path, data: str) -> ifcopenshell.file:
    path = tmp_path / "model.ifc"
    path.write_text(_HEADER + data + "ENDSEC;\nEND-ISO-10303-21;\n")
    return ifcopenshell.open(path)


def base_ids(rep) -> list[int]:
    items = assert_finishes(lambda: list(islice(representation.resolve_base_items(rep), _WALK_LIMIT)))
    assert all(not item.is_a("IfcBooleanResult") for item in items)
    assert all(not item.is_a("IfcMappedItem") for item in items)
    return [item.id() for item in items]


def assert_ids(ids: list[int], expected: set[int]) -> None:
    assert set(ids) == expected
    assert len(ids) == len(expected)


class TestResolveBaseItems:
    def test_self_first_operand_yields_the_other_solid_once(self, tmp_path):
        # #30 uses itself as FirstOperand. #31 is not a revolved solid.
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#30=IFCBOOLEANRESULT(.DIFFERENCE.,#30,#31);
#31=IFCSPHERE(#2,1.);
#32=IFCSHAPEREPRESENTATION(#11,'Body','CSG',(#30));
#33=IFCPRODUCTDEFINITIONSHAPE($,$,(#32));
#34=IFCCOLUMN('1U7MoqHmr8YP6jwz0pc7e0',$,'Column',$,$,$,#33,$,$);
#35=IFCMATERIALPROFILESET('Profiles',$,());
#36=IFCMATERIALPROFILESETUSAGE(#35,$,$);
#37=IFCRELASSOCIATESMATERIAL('1U7MoqHmr8YP6jwz0pc7e1',$,$,$,(#34),#36);
""",
        )
        column = model.by_id(34)
        body = representation.get_representation(column, "Model", "Body", "MODEL_VIEW")
        # Bonsai Model.get_usage_type feeds this generator to any() for an
        # IfcMaterialProfileSetUsage element. The predicate never matches #31.
        assert element.get_material(column, should_inherit=False).is_a("IfcMaterialProfileSetUsage")
        assert body.id() == 32
        revolved = assert_finishes(
            lambda: any(item.is_a("IfcRevolvedAreaSolid") for item in representation.resolve_base_items(body))
        )
        assert revolved is False
        assert_ids(base_ids(body), {31})

    def test_self_second_operand_yields_the_first_solid_once(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#30=IFCBOOLEANRESULT(.DIFFERENCE.,#31,#30);
#31=IFCSPHERE(#2,1.);
#32=IFCSHAPEREPRESENTATION(#11,'Body','CSG',(#30));
""",
        )
        assert_ids(base_ids(model.by_id(32)), {31})

    def test_mutual_boolean_cycle_yields_each_solid_once(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#30=IFCBOOLEANRESULT(.UNION.,#31,#32);
#31=IFCBOOLEANRESULT(.UNION.,#30,#33);
#32=IFCSPHERE(#2,1.);
#33=IFCSPHERE(#2,2.);
#34=IFCSHAPEREPRESENTATION(#11,'Body','CSG',(#30));
""",
        )
        assert_ids(base_ids(model.by_id(34)), {32, 33})

    def test_three_boolean_cycle_yields_each_solid_once(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#30=IFCBOOLEANRESULT(.UNION.,#31,#40);
#31=IFCBOOLEANRESULT(.UNION.,#32,#41);
#32=IFCBOOLEANRESULT(.UNION.,#30,#42);
#40=IFCSPHERE(#2,1.);
#41=IFCSPHERE(#2,2.);
#42=IFCSPHERE(#2,3.);
#34=IFCSHAPEREPRESENTATION(#11,'Body','CSG',(#30));
""",
        )
        assert_ids(base_ids(model.by_id(34)), {40, 41, 42})

    def test_self_clipping_result_yields_the_half_space_once(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#30=IFCPLANE(#2);
#31=IFCHALFSPACESOLID(#30,.T.);
#32=IFCBOOLEANCLIPPINGRESULT(.DIFFERENCE.,#32,#31);
#33=IFCSHAPEREPRESENTATION(#11,'Body','Clipping',(#32));
""",
        )
        assert model.by_id(32).is_a("IfcBooleanResult")
        assert_ids(base_ids(model.by_id(33)), {31})

    def test_mapped_item_cycle_yields_the_sibling_solid_once(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#30=IFCSPHERE(#2,1.);
#31=IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,#1,$,$);
#32=IFCSHAPEREPRESENTATION(#11,'Body','MappedRepresentation',(#30,#33));
#33=IFCMAPPEDITEM(#34,#31);
#34=IFCREPRESENTATIONMAP(#2,#32);
""",
        )
        assert model.by_id(33).MappingSource.MappedRepresentation.id() == 32
        assert_ids(base_ids(model.by_id(32)), {30})

    def test_mapped_representations_that_point_at_each_other_yield_the_solid_once(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#30=IFCSPHERE(#2,1.);
#31=IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,#1,$,$);
#32=IFCSHAPEREPRESENTATION(#11,'Body','MappedRepresentation',(#30,#33));
#33=IFCMAPPEDITEM(#36,#31);
#35=IFCSHAPEREPRESENTATION(#11,'Body','MappedRepresentation',(#37));
#36=IFCREPRESENTATIONMAP(#2,#35);
#37=IFCMAPPEDITEM(#38,#31);
#38=IFCREPRESENTATIONMAP(#2,#32);
""",
        )
        assert_ids(base_ids(model.by_id(32)), {30})

    def test_acyclic_boolean_still_yields_both_operands(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#30=IFCSPHERE(#2,1.);
#31=IFCSPHERE(#2,2.);
#32=IFCBOOLEANRESULT(.DIFFERENCE.,#30,#31);
#33=IFCSHAPEREPRESENTATION(#11,'Body','CSG',(#32));
""",
        )
        assert_ids(base_ids(model.by_id(33)), {30, 31})

    def test_shared_operand_is_reported_once(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#30=IFCSPHERE(#2,1.);
#31=IFCSPHERE(#2,2.);
#32=IFCSPHERE(#2,3.);
#33=IFCBOOLEANRESULT(.UNION.,#30,#31);
#34=IFCBOOLEANRESULT(.UNION.,#30,#32);
#35=IFCSHAPEREPRESENTATION(#11,'Body','CSG',(#33,#34));
""",
        )
        assert_ids(base_ids(model.by_id(35)), {30, 31, 32})

    def test_revolved_solid_is_still_reported(self):
        model = ifcopenshell.file(schema="IFC4")
        origin = model.create_entity("IfcCartesianPoint", (0.0, 0.0, 0.0))
        placement = model.create_entity("IfcAxis2Placement3D", origin)
        direction = model.create_entity("IfcDirection", (0.0, 0.0, 1.0))
        axis = model.create_entity("IfcAxis1Placement", origin, direction)
        profile_origin = model.create_entity("IfcCartesianPoint", (0.0, 0.0))
        profile_placement = model.create_entity("IfcAxis2Placement2D", profile_origin)
        profile = model.create_entity("IfcRectangleProfileDef", "AREA", None, profile_placement, 1.0, 1.0)
        revolved = model.create_entity("IfcRevolvedAreaSolid", profile, placement, axis, 1.0)
        context = model.create_entity("IfcGeometricRepresentationContext", None, "Model", 3, 1e-5, placement)
        subcontext = model.create_entity(
            "IfcGeometricRepresentationSubContext",
            "Body",
            "Model",
            None,
            None,
            None,
            None,
            context,
            None,
            "MODEL_VIEW",
        )
        body = model.create_entity("IfcShapeRepresentation", subcontext, "Body", "SweptSolid", [revolved])
        revolved_found = assert_finishes(
            lambda: any(item.is_a("IfcRevolvedAreaSolid") for item in representation.resolve_base_items(body))
        )
        assert revolved_found is True
        assert_ids(base_ids(body), {revolved.id()})


class TestResolveItems:
    def test_mapped_item_cycle_returns_the_sibling_solid_once(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#30=IFCSPHERE(#2,1.);
#31=IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,#1,$,$);
#32=IFCSHAPEREPRESENTATION(#11,'Body','MappedRepresentation',(#30,#33));
#33=IFCMAPPEDITEM(#34,#31);
#34=IFCREPRESENTATIONMAP(#2,#32);
""",
        )
        resolved = assert_finishes(lambda: representation.resolve_items(model.by_id(32)))
        assert [item["item"].id() for item in resolved] == [30]

    def test_mapped_representations_that_point_at_each_other_return_the_solid_once(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#30=IFCSPHERE(#2,1.);
#31=IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,#1,$,$);
#32=IFCSHAPEREPRESENTATION(#11,'Body','MappedRepresentation',(#30,#33));
#33=IFCMAPPEDITEM(#36,#31);
#35=IFCSHAPEREPRESENTATION(#11,'Body','MappedRepresentation',(#37));
#36=IFCREPRESENTATIONMAP(#2,#35);
#37=IFCMAPPEDITEM(#38,#31);
#38=IFCREPRESENTATIONMAP(#2,#32);
""",
        )
        resolved = assert_finishes(lambda: representation.resolve_items(model.by_id(32)))
        assert [item["item"].id() for item in resolved] == [30]


class TestResolveRepresentation:
    def test_single_mapped_item_cycle_returns_the_representation(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#31=IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,#1,$,$);
#32=IFCSHAPEREPRESENTATION(#11,'Body','MappedRepresentation',(#33));
#33=IFCMAPPEDITEM(#34,#31);
#34=IFCREPRESENTATIONMAP(#2,#32);
""",
        )
        resolved = assert_finishes(lambda: representation.resolve_representation(model.by_id(32)))
        assert resolved.is_a("IfcShapeRepresentation")
        assert resolved.id() == 32

    def test_two_mapped_representations_return_a_representation(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#31=IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,#1,$,$);
#32=IFCSHAPEREPRESENTATION(#11,'Body','MappedRepresentation',(#33));
#33=IFCMAPPEDITEM(#36,#31);
#35=IFCSHAPEREPRESENTATION(#11,'Body','MappedRepresentation',(#37));
#36=IFCREPRESENTATIONMAP(#2,#35);
#37=IFCMAPPEDITEM(#38,#31);
#38=IFCREPRESENTATIONMAP(#2,#32);
""",
        )
        resolved = assert_finishes(lambda: representation.resolve_representation(model.by_id(32)))
        assert resolved.is_a("IfcShapeRepresentation")
        assert resolved.id() in {32, 35}


class TestElementAndShapeWalks:
    def _styled_column(self, tmp_path, items: str) -> ifcopenshell.file:
        return open_data(
            tmp_path,
            _CONTEXT
            + items
            + """\
#50=IFCSURFACESTYLE('Red',.BOTH.,());
#51=IFCSTYLEDITEM(#40,(#50),$);
#52=IFCPRODUCTDEFINITIONSHAPE($,$,(#42));
#53=IFCWALL('1U7MoqHmr8YP6jwz0pc7e0',$,'Wall',$,$,$,#52,$);
""",
        )

    def test_get_styles_on_a_boolean_cycle_returns_the_style_once(self, tmp_path):
        model = self._styled_column(
            tmp_path,
            """\
#40=IFCSPHERE(#2,1.);
#41=IFCBOOLEANRESULT(.DIFFERENCE.,#41,#40);
#42=IFCSHAPEREPRESENTATION(#11,'Body','CSG',(#41));
""",
        )
        styles = assert_finishes(lambda: element.get_styles(model.by_id(53)))
        assert [style.id() for style in styles] == [50]

    def test_get_styles_on_a_mapped_cycle_returns_the_style_once(self, tmp_path):
        model = self._styled_column(
            tmp_path,
            """\
#40=IFCSPHERE(#2,1.);
#41=IFCCARTESIANTRANSFORMATIONOPERATOR3D($,$,#1,$,$);
#42=IFCSHAPEREPRESENTATION(#11,'Body','MappedRepresentation',(#40,#43));
#43=IFCMAPPEDITEM(#44,#41);
#44=IFCREPRESENTATIONMAP(#2,#42);
""",
        )
        styles = assert_finishes(lambda: element.get_styles(model.by_id(53)))
        assert [style.id() for style in styles] == [50]

    def test_get_extrusions_on_a_boolean_cycle_returns_no_extrusion(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#40=IFCSPHERE(#2,1.);
#41=IFCBOOLEANRESULT(.DIFFERENCE.,#41,#40);
#42=IFCSHAPEREPRESENTATION(#11,'Body','CSG',(#41));
#52=IFCPRODUCTDEFINITIONSHAPE($,$,(#42));
#53=IFCWALL('1U7MoqHmr8YP6jwz0pc7e0',$,'Wall',$,$,$,#52,$);
""",
        )
        wall = model.by_id(53)
        assert assert_finishes(lambda: shape.get_extrusions(wall)) == []
        assert assert_finishes(lambda: shape.get_base_extrusions(wall)) == []

    def test_get_extrusions_still_follows_an_acyclic_boolean_to_the_extrusion(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#20=IFCCARTESIANPOINT((0.,0.));
#21=IFCAXIS2PLACEMENT2D(#20,$);
#22=IFCRECTANGLEPROFILEDEF(.AREA.,$,#21,1.,1.);
#23=IFCDIRECTION((0.,0.,1.));
#40=IFCEXTRUDEDAREASOLID(#22,#2,#23,2.);
#41=IFCSPHERE(#2,1.);
#42=IFCBOOLEANRESULT(.DIFFERENCE.,#40,#41);
#43=IFCSHAPEREPRESENTATION(#11,'Body','CSG',(#42));
#52=IFCPRODUCTDEFINITIONSHAPE($,$,(#43));
#53=IFCWALL('1U7MoqHmr8YP6jwz0pc7e0',$,'Wall',$,$,$,#52,$);
""",
        )
        wall = model.by_id(53)
        assert [item.id() for item in shape.get_extrusions(wall)] == [40]
        assert [item.id() for item in shape.get_base_extrusions(wall)] == [40]


class TestBooleanApi:
    def test_remove_boolean_finishes_and_leaves_the_solid(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#30=IFCBOOLEANRESULT(.DIFFERENCE.,#30,#31);
#31=IFCSPHERE(#2,1.);
#32=IFCSHAPEREPRESENTATION(#11,'Body','CSG',(#30));
""",
        )
        assert_finishes(lambda: remove_boolean(model, model.by_id(30)))
        assert_ids(base_ids(model.by_id(32)), {31})

    def test_add_boolean_finishes_on_a_self_operand(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#30=IFCBOOLEANRESULT(.DIFFERENCE.,#30,#31);
#31=IFCSPHERE(#2,1.);
#32=IFCSHAPEREPRESENTATION(#11,'Body','CSG',(#30));
""",
        )
        other = model.create_entity("IfcSphere", model.by_id(2), 2.0)
        created = assert_finishes(lambda: add_boolean(model, model.by_id(30), [other]))
        assert isinstance(created, list)
        assert_ids(base_ids(model.by_id(32)), {31, other.id()})


class TestWallRegenerator:
    def test_get_wall_vectors_finishes_on_a_boolean_cycle(self, tmp_path):
        model = open_data(
            tmp_path,
            _CONTEXT
            + """\
#40=IFCSPHERE(#2,1.);
#41=IFCBOOLEANRESULT(.DIFFERENCE.,#41,#40);
#42=IFCSHAPEREPRESENTATION(#11,'Body','CSG',(#41));
#52=IFCPRODUCTDEFINITIONSHAPE($,$,(#42));
#53=IFCWALL('1U7MoqHmr8YP6jwz0pc7e0',$,'Wall',$,$,$,#52,$);
""",
        )
        tool = SimpleNamespace(fallback_angle=None, fallback_height=3.0, is_angled=False)
        vectors = assert_finishes(lambda: Regenerator.get_wall_vectors(tool, model.by_id(53)))
        assert vectors["h"] == 3.0
        assert vectors["d"] == 3.0
