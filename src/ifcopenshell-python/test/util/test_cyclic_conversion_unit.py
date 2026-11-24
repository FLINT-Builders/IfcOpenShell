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

"""Cyclic IfcConversionBasedUnit chains must not hang unit-scale calculation.

A project length unit whose ConversionFactor.UnitComponent points back at a
conversion-based unit already on the chain is schema-accepted STEP. The scale
walk has to finish for that file. Finishing means either a finite float or an
exception. An acyclic chain must still produce the SI scale, including a chain
of several conversion-based units and IfcConversionBasedUnitWithOffset.
"""

import logging
import math
import multiprocessing
import os
import sys
from pathlib import Path

# pytest puts this package's source tree on sys.path. That tree has no
# compiled ifcopenshell_wrapper, so the installed build has to win.
_PACKAGE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path[:] = [entry for entry in sys.path if os.path.abspath(entry or "") != _PACKAGE_ROOT]

import pytest

import ifcopenshell
import ifcopenshell.api.project
import ifcopenshell.api.unit
import ifcopenshell.guid
import ifcopenshell.util.unit as unit

REPO_ROOT = Path(__file__).resolve().parents[4]
SOURCE_PATHS = [str(REPO_ROOT / "src" / name) for name in ("bcf", "ifc5d", "ifcpatch", "ifcfm")]
# A tight cycle burns a core immediately, so a short bound is enough. Legitimate
# calls return in well under a tenth of a second.
LOOP_BOUND_SECONDS = 1.5

# The STEP the attack writes: the length unit's measure names that same unit.
IFC4_SELF_CYCLE = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition[DesignTransferView]'),'2;1');
FILE_NAME('cycle.ifc','2026-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCPROJECT('3Wxmb$LMz3kAfiyF_AU9Mo',$,'P',$,$,$,$,$,#6);
#2=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#3=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(1.),#5);
#4=IFCDIMENSIONALEXPONENTS(1,0,0,0,0,0,0);
#5=IFCCONVERSIONBASEDUNIT(#4,.LENGTHUNIT.,'X',#3);
#6=IFCUNITASSIGNMENT((#5));
#7=IFCWALL('2xa1UNwNX6g9DmhoYIPyWU',$,'W',$,$,#12,$,$,$);
#8=IFCCARTESIANPOINT((0.,0.,0.));
#9=IFCDIRECTION((0.,0.,1.));
#10=IFCDIRECTION((1.,0.,0.));
#11=IFCAXIS2PLACEMENT3D(#8,#9,#10);
#12=IFCLOCALPLACEMENT($,#11);
ENDSEC;
END-ISO-10303-21;
"""

IFC2X3_SELF_CYCLE = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition[DesignTransferView]'),'2;1');
FILE_NAME('cycle.ifc','2026-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('IFC2X3'));
ENDSEC;
DATA;
#1=IFCPROJECT('2VU8ozUq9DKgVr7ONjLnmy',$,'P',$,$,$,$,$,#6);
#2=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#3=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(1.),#5);
#4=IFCDIMENSIONALEXPONENTS(1,0,0,0,0,0,0);
#5=IFCCONVERSIONBASEDUNIT(#4,.LENGTHUNIT.,'X',#3);
#6=IFCUNITASSIGNMENT((#5));
#7=IFCWALL('3OTcExBdb1hOjf6w4Nu81T',$,'W',$,$,#12,$,$);
#8=IFCCARTESIANPOINT((0.,0.,0.));
#9=IFCDIRECTION((0.,0.,1.));
#10=IFCDIRECTION((1.,0.,0.));
#11=IFCAXIS2PLACEMENT3D(#8,#9,#10);
#12=IFCLOCALPLACEMENT($,#11);
ENDSEC;
END-ISO-10303-21;
"""


class _NotReached(Exception):
    """The product function returned without walking a conversion-based unit."""


def _project(schema):
    ifc_file = ifcopenshell.api.project.create_file(version=schema)
    project = ifc_file.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="P")
    return ifc_file, project


def _assign(project, units):
    project.UnitsInContext = project.file.createIfcUnitAssignment(list(units))


def _conversion(ifc_file, name, factor, component, with_offset=False):
    measure = ifc_file.createIfcMeasureWithUnit(
        ifc_file.create_entity("IfcLengthMeasure", wrappedValue=factor), component
    )
    dims = ifc_file.createIfcDimensionalExponents(1, 0, 0, 0, 0, 0, 0)
    if with_offset:
        unit = ifc_file.createIfcConversionBasedUnitWithOffset(dims, "LENGTHUNIT", name, measure, 0.0)
    else:
        unit = ifc_file.createIfcConversionBasedUnit(dims, "LENGTHUNIT", name, measure)
    return unit, measure


def _metre(ifc_file):
    return ifc_file.createIfcSIUnit(UnitType="LENGTHUNIT", Name="METRE")


def _self_cycle_spf(schema="IFC4", with_offset=False):
    ifc_file, project = _project(schema)
    unit, measure = _conversion(ifc_file, "X", 1.0, _metre(ifc_file), with_offset=with_offset)
    measure.UnitComponent = unit
    _assign(project, [unit])
    return ifc_file.to_string()


def _pair_cycle_spf(schema):
    """A and B name each other. Neither unit is its own UnitComponent."""
    ifc_file, project = _project(schema)
    metre = _metre(ifc_file)
    first, first_measure = _conversion(ifc_file, "A", 2.0, metre)
    second, second_measure = _conversion(ifc_file, "B", 3.0, metre)
    first_measure.UnitComponent = second
    second_measure.UnitComponent = first
    _assign(project, [first])
    return ifc_file.to_string()


def _tail_cycle_spf(schema):
    """A names B, and B names itself. The repeated unit is not the start."""
    ifc_file, project = _project(schema)
    metre = _metre(ifc_file)
    first, first_measure = _conversion(ifc_file, "A", 2.0, metre)
    second, second_measure = _conversion(ifc_file, "B", 3.0, metre)
    first_measure.UnitComponent = second
    second_measure.UnitComponent = second
    _assign(project, [first])
    return ifc_file.to_string()


def _derived_cycle_spf(schema):
    ifc_file, project = _project(schema)
    unit, measure = _conversion(ifc_file, "X", 1.0, _metre(ifc_file))
    measure.UnitComponent = unit
    element = ifc_file.createIfcDerivedUnitElement(unit, 1)
    derived = ifc_file.createIfcDerivedUnit((element,), "USERDEFINED", "cycle")
    _assign(project, [derived])
    return ifc_file.to_string()


def _chain_spf(schema, factors):
    """Project length unit is the head of an acyclic conversion chain ending at metres."""
    ifc_file, project = _project(schema)
    component = _metre(ifc_file)
    # factors are listed from the project unit back toward the SI unit.
    for index, factor in enumerate(reversed(factors)):
        component, _measure = _conversion(ifc_file, f"u{index}", factor, component)
    _assign(project, [component])
    return ifc_file


def _foot_spf(schema):
    ifc_file, project = _project(schema)
    foot = ifcopenshell.api.unit.add_conversion_based_unit(ifc_file, name="foot")
    _assign(project, [foot])
    return ifc_file


def _milli_spf(schema):
    ifc_file, project = _project(schema)
    milli = ifcopenshell.api.unit.add_si_unit(ifc_file, unit_type="LENGTHUNIT", prefix="MILLI")
    _assign(project, [milli])
    return ifc_file


def _square_metre_derived(schema):
    ifc_file, _project_entity = _project(schema)
    metre = _metre(ifc_file)
    element = ifc_file.createIfcDerivedUnitElement(metre, 2)
    return ifc_file.createIfcDerivedUnit((element,), "USERDEFINED", "area")


def _add_wall(ifc_file):
    wall = ifc_file.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(), Name="W")
    origin = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
    axis_z = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
    axis_x = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
    placement = ifc_file.createIfcAxis2Placement3D(origin, axis_z, axis_x)
    wall.ObjectPlacement = ifc_file.createIfcLocalPlacement(None, placement)
    return wall


def _add_space_box(ifc_file):
    space = ifc_file.create_entity("IfcSpace", GlobalId=ifcopenshell.guid.new(), Name="S")
    origin = ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0))
    axis_z = ifc_file.createIfcDirection((0.0, 0.0, 1.0))
    axis_x = ifc_file.createIfcDirection((1.0, 0.0, 0.0))
    placement = ifc_file.createIfcAxis2Placement3D(origin, axis_z, axis_x)
    context = ifc_file.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0e-5, placement, None)
    profile_origin = ifc_file.createIfcCartesianPoint((0.0, 0.0))
    profile_axis = ifc_file.createIfcAxis2Placement2D(profile_origin, None)
    profile = ifc_file.createIfcRectangleProfileDef("AREA", None, profile_axis, 1.0, 1.0)
    solid = ifc_file.createIfcExtrudedAreaSolid(profile, placement, axis_z, 1.0)
    body = ifc_file.createIfcShapeRepresentation(context, "Body", "SweptSolid", [solid])
    space.Representation = ifc_file.createIfcProductDefinitionShape(None, None, [body])
    space.ObjectPlacement = ifc_file.createIfcLocalPlacement(None, placement)
    return space


def _length_unit(ifc_file):
    for candidate in ifc_file.by_type("IfcProject")[0].UnitsInContext.Units:
        if getattr(candidate, "UnitType", None) == "LENGTHUNIT":
            return candidate
    return None


def _chain_cycles(start, steps=8):
    seen = set()
    current = start
    for _ in range(steps):
        if current is None or not current.is_a("IfcConversionBasedUnit"):
            return False
        if current.id() in seen:
            return True
        seen.add(current.id())
        factor = current.ConversionFactor
        current = factor.UnitComponent if factor is not None else None
    return False


def _require_cycle(ifc_file):
    length = _length_unit(ifc_file)
    derived = next(iter(ifc_file.by_type("IfcDerivedUnit")), None)
    if length is not None and _chain_cycles(length):
        return
    if derived is not None and any(_chain_cycles(element.Unit) for element in derived.Elements):
        return
    raise _NotReached("parsed file does not contain a cyclic conversion-based unit")


def _call_product(ifc_file, operation):
    logger = logging.getLogger("cyclic-unit-test")
    if operation == "bcf2":
        import bcf.v2.visinfo as visinfo

        visinfo.build_viewpoint(ifc_file.by_type("IfcWall")[0])
    elif operation == "bcf3":
        import bcf.v3.visinfo as visinfo

        visinfo.build_viewpoint(ifc_file.by_type("IfcWall")[0])
    elif operation == "qto":
        from ifc5d.qto import IfcOpenShell

        IfcOpenShell.calculate(ifc_file, [], {}, {})
    elif operation == "spaces":
        from ifcpatch.recipes.FixArchiCADToRevitSpaces import Patcher

        Patcher(ifc_file, logger)
    elif operation == "fractions":
        from ifcpatch.recipes.AssignConstituentFractions import Patcher

        Patcher(ifc_file, logger).patch()
    elif operation == "doors":
        from ifcpatch.recipes.FixArchiCADToRevitDoorSwings import Patcher

        Patcher(ifc_file, logger).patch()
    elif operation == "ifc2sql":
        from ifcpatch.recipes.Ifc2Sql import Patcher

        Patcher(ifc_file, logger, database="unused", full_schema=False).create_geometry()
    elif operation == "cobie":
        import ifcfm.cobie24 as cobie

        list(cobie.get_coordinate_data_(ifc_file.by_type("IfcSpace")[0]))
    elif operation == "alignment":
        import ifcopenshell.util.alignment as alignment

        alignment.station_as_string(ifc_file, 100.0)
    else:
        raise AssertionError(operation)


def _dispatch(ifc_file, operation):
    _require_cycle(ifc_file)
    if operation == "named":
        return unit.get_named_unit_scale(_length_unit(ifc_file))
    if operation == "unit":
        length = _length_unit(ifc_file)
        if length is not None and length.is_a("IfcConversionBasedUnit"):
            target = length
        else:
            target = ifc_file.by_type("IfcDerivedUnit")[0]
        return unit.get_unit_scale(target)
    if operation == "calculate":
        return unit.calculate_unit_scale(ifc_file)
    if operation == "derived":
        return unit.get_derived_unit_scale(ifc_file.by_type("IfcDerivedUnit")[0])
    reached = {"ok": False}
    real = unit.get_named_unit_scale

    def _mark_entry(*args, **kwargs):
        reached["ok"] = True
        return real(*args, **kwargs)

    unit.get_named_unit_scale = _mark_entry
    try:
        _call_product(ifc_file, operation)
    finally:
        unit.get_named_unit_scale = real
    if not reached["ok"]:
        raise _NotReached(operation)
    return None


def _child(queue, source_paths, payload, operation):
    import sys

    for path in source_paths:
        if path not in sys.path:
            sys.path.insert(0, path)
    try:
        if operation == "open":
            ifc_file = ifcopenshell.open(payload)
            operation = "calculate"
        else:
            ifc_file = ifcopenshell.file.from_string(payload)
        result = _dispatch(ifc_file, operation)
    except _NotReached as exc:
        queue.put(("not_reached", str(exc)))
        return
    except Exception as exc:
        queue.put(("raised", type(exc).__name__))
        return
    if result is None or (isinstance(result, float) and math.isfinite(result)):
        queue.put(("done", None if result is None else float(result)))
        return
    queue.put(("bad", repr(result)))


def _assert_finishes(payload, operation):
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    process = context.Process(target=_child, args=(queue, SOURCE_PATHS, payload, operation))
    process.start()
    process.join(LOOP_BOUND_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
        pytest.fail(f"{operation} was still running after {LOOP_BOUND_SECONDS}s")
    if queue.empty():
        pytest.fail(f"{operation} exited {process.exitcode} without a result")
    kind, detail = queue.get()
    if kind == "not_reached":
        pytest.fail(f"{operation} did not walk the cyclic unit: {detail}")
    if kind == "bad":
        pytest.fail(f"{operation} returned a non-finite result: {detail}")
    assert kind in {"done", "raised"}


CYCLE_CASES = [
    ("IFC4", "self", lambda: _self_cycle_spf("IFC4")),
    ("IFC2X3", "self", lambda: _self_cycle_spf("IFC2X3")),
    ("IFC4", "pair", lambda: _pair_cycle_spf("IFC4")),
    ("IFC2X3", "pair", lambda: _pair_cycle_spf("IFC2X3")),
    ("IFC4", "tail", lambda: _tail_cycle_spf("IFC4")),
    ("IFC2X3", "tail", lambda: _tail_cycle_spf("IFC2X3")),
    ("IFC4", "offset", lambda: _self_cycle_spf("IFC4", with_offset=True)),
]


@pytest.mark.parametrize("schema,kind,build", CYCLE_CASES, ids=[f"{s}-{k}" for s, k, _ in CYCLE_CASES])
@pytest.mark.parametrize("operation", ["named", "unit", "calculate"])
def test_cyclic_length_unit_scale_finishes(schema, kind, build, operation):
    _assert_finishes(build(), operation)


DERIVED_CASES = ["IFC4", "IFC2X3"]


@pytest.mark.parametrize("schema", DERIVED_CASES)
@pytest.mark.parametrize("operation", ["derived", "unit"])
def test_derived_unit_over_cyclic_named_unit_finishes(schema, operation):
    _assert_finishes(_derived_cycle_spf(schema), operation)


@pytest.mark.parametrize(
    "spf,label",
    [(IFC4_SELF_CYCLE, "IFC4"), (IFC2X3_SELF_CYCLE, "IFC2X3")],
    ids=["IFC4", "IFC2X3"],
)
def test_literal_step_file_scale_finishes(spf, label):
    _assert_finishes(spf, "calculate")


@pytest.mark.parametrize(
    "spf,label",
    [(IFC4_SELF_CYCLE, "IFC4"), (IFC2X3_SELF_CYCLE, "IFC2X3")],
    ids=["IFC4", "IFC2X3"],
)
def test_opened_step_file_scale_finishes(tmp_path, spf, label):
    path = tmp_path / f"{label}.ifc"
    path.write_text(spf)
    _assert_finishes(str(path), "open")


def _plain_spf():
    return _self_cycle_spf("IFC4")


def _wall_spf():
    ifc_file, project = _project("IFC4")
    unit, measure = _conversion(ifc_file, "X", 1.0, _metre(ifc_file))
    measure.UnitComponent = unit
    _assign(project, [unit])
    _add_wall(ifc_file)
    return ifc_file.to_string()


def _space_spf():
    ifc_file, project = _project("IFC4")
    unit, measure = _conversion(ifc_file, "X", 1.0, _metre(ifc_file))
    measure.UnitComponent = unit
    _assign(project, [unit])
    _add_space_box(ifc_file)
    return ifc_file.to_string()


@pytest.mark.parametrize(
    "operation,builder",
    [
        ("bcf2", _wall_spf),
        ("bcf3", _wall_spf),
        ("qto", _plain_spf),
        ("spaces", _plain_spf),
        ("fractions", _plain_spf),
        ("doors", _plain_spf),
        ("ifc2sql", _plain_spf),
        ("alignment", _plain_spf),
        ("cobie", _space_spf),
    ],
)
def test_product_entry_finishes(operation, builder):
    _assert_finishes(builder(), operation)


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_foot_scale_is_unchanged(schema):
    assert unit.calculate_unit_scale(_foot_spf(schema)) == pytest.approx(0.3048)


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_millimetre_scale_is_unchanged(schema):
    assert unit.calculate_unit_scale(_milli_spf(schema)) == pytest.approx(0.001)


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_acyclic_conversion_chain_multiplies_every_factor(schema):
    # 2 * 2 * 2 * 2 * 0.5 metres. A guard that stops at the first unit returns 2.
    ifc_file = _chain_spf(schema, [2.0, 2.0, 2.0, 2.0, 0.5])
    assert unit.calculate_unit_scale(ifc_file) == pytest.approx(8.0)
    assert unit.get_named_unit_scale(_length_unit(ifc_file)) == pytest.approx(8.0)


@pytest.mark.parametrize("schema", ["IFC4", "IFC2X3"])
def test_derived_square_metre_scale_is_unchanged(schema):
    derived = _square_metre_derived(schema)
    assert unit.get_derived_unit_scale(derived) == pytest.approx(1.0)
    assert unit.get_unit_scale(derived) == pytest.approx(1.0)
