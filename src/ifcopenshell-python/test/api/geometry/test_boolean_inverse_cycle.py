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

import signal
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.util.shape
import ifcopenshell.util.shape_builder
import test.bootstrap

# The walk must return. Two seconds is far longer than a finished call on this
# model and far shorter than an unbounded inverse loop.
_RETURN_WITHIN_SECONDS = 2.0


def _call_within(fn):
    def handler(signum, frame):
        raise AssertionError(f"call did not return within {_RETURN_WITHIN_SECONDS} seconds")

    previous = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, _RETURN_WITHIN_SECONDS)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous)


def _assert_inverse_cycle(file: ifcopenshell.file, solid: ifcopenshell.entity_instance) -> None:
    """The opened file must contain a cycle of IfcBooleanResult inverses from the solid."""
    seen: set[int] = set()
    current = solid
    for _ in range(6):
        booleans = [inverse for inverse in file.get_inverse(current) if inverse.is_a("IfcBooleanResult")]
        assert booleans, "solid has no inverse IfcBooleanResult after the file was opened"
        nxt = booleans[0]
        if nxt.id() in seen:
            return
        seen.add(nxt.id())
        current = nxt
    raise AssertionError("opened file has no cycle of IfcBooleanResult inverses")


class TestBooleanInverseCycle(test.bootstrap.IFC4):
    def _opened_model(self, tmp_path: Path, kind: str):
        file = self.file
        ifcopenshell.api.root.create_entity(file, ifc_class="IfcProject")
        model = ifcopenshell.api.context.add_context(file, context_type="Model")
        body = ifcopenshell.api.context.add_context(
            file, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model
        )
        builder = ifcopenshell.util.shape_builder.ShapeBuilder(file)
        solid = builder.extrude(builder.rectangle(), magnitude=3.0)
        held = builder.block()
        added = builder.sphere()
        representation = builder.get_representation(body, [solid])
        wall = ifcopenshell.api.root.create_entity(file, ifc_class="IfcWall")
        wall.Representation = file.create_entity("IfcProductDefinitionShape", Representations=[representation])

        if kind == "pair":
            # A uses the solid, B uses A, and A uses B.
            first = file.create_entity("IfcBooleanResult", "DIFFERENCE", solid, held)
            second = file.create_entity("IfcBooleanResult", "DIFFERENCE", first, held)
            first.SecondOperand = second
        elif kind == "self":
            first = file.create_entity("IfcBooleanResult", "DIFFERENCE", solid, held)
            first.SecondOperand = first
        elif kind == "triple":
            first = file.create_entity("IfcBooleanResult", "DIFFERENCE", solid, held)
            second = file.create_entity("IfcBooleanResult", "DIFFERENCE", first, held)
            third = file.create_entity("IfcBooleanResult", "DIFFERENCE", second, held)
            first.SecondOperand = third
        else:
            raise AssertionError(kind)

        path = tmp_path / "cycle.ifc"
        file.write(path)
        opened = ifcopenshell.open(path)
        solid = opened.by_id(solid.id())
        added = opened.by_id(added.id())
        wall = opened.by_id(wall.id())
        _assert_inverse_cycle(opened, solid)
        return opened, solid, added, wall

    def _assert_boolean_added(self, opened, solid, added):
        before = {boolean.id() for boolean in opened.by_type("IfcBooleanResult")}
        result = _call_within(lambda: ifcopenshell.api.geometry.add_boolean(opened, solid, [added]))
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].is_a("IfcBooleanResult")
        assert result[0].id() not in before
        assert result[0].SecondOperand == added
        assert result[0].Operator == "DIFFERENCE"

    def test_add_boolean_returns_when_two_results_reference_each_other(self, tmp_path):
        opened, solid, added, _wall = self._opened_model(tmp_path, "pair")
        self._assert_boolean_added(opened, solid, added)

    def test_add_boolean_returns_when_a_result_references_itself(self, tmp_path):
        opened, solid, added, _wall = self._opened_model(tmp_path, "self")
        self._assert_boolean_added(opened, solid, added)

    def test_add_boolean_returns_when_three_results_form_a_cycle(self, tmp_path):
        opened, solid, added, _wall = self._opened_model(tmp_path, "triple")
        self._assert_boolean_added(opened, solid, added)

    def test_clip_wall_extrusion_returns_when_inverses_cycle(self, tmp_path):
        # Same sequence as bonsai.tool.model.Model.clip_wall_to_slab: resolve the
        # wall extrusion, then add a boolean on that extrusion.
        opened, solid, added, wall = self._opened_model(tmp_path, "pair")
        extrusions = _call_within(lambda: ifcopenshell.util.shape.get_base_extrusions(wall))
        assert extrusions
        assert extrusions[0] == solid
        self._assert_boolean_added(opened, extrusions[0], added)

    def test_remove_boolean_returns_when_two_results_reference_each_other(self, tmp_path):
        opened, solid, _added, _wall = self._opened_model(tmp_path, "pair")
        boolean = next(inverse for inverse in opened.get_inverse(solid) if inverse.is_a("IfcBooleanResult"))
        result = _call_within(lambda: ifcopenshell.api.geometry.remove_boolean(opened, boolean))
        assert result is None
        # The call must leave the model readable. A walk that is still queued
        # never reaches this line.
        assert opened.by_id(solid.id()) == solid

    def test_add_boolean_still_nests_on_the_outermost_result(self):
        ifcopenshell.api.root.create_entity(self.file, ifc_class="IfcProject")
        model = ifcopenshell.api.context.add_context(self.file, context_type="Model")
        body = ifcopenshell.api.context.add_context(
            self.file, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model
        )
        builder = ifcopenshell.util.shape_builder.ShapeBuilder(self.file)
        first = builder.sphere()
        second = builder.block()
        third = builder.block()
        builder.get_representation(body, [first, second])
        _call_within(lambda: ifcopenshell.api.geometry.add_boolean(self.file, first, [second]))
        booleans = _call_within(lambda: ifcopenshell.api.geometry.add_boolean(self.file, first, [third]))
        assert len(booleans) == 1
        assert booleans[0].FirstOperand.is_a("IfcBooleanResult")
        assert booleans[0].FirstOperand.FirstOperand == first
        assert booleans[0].FirstOperand.SecondOperand == second
        assert booleans[0].SecondOperand == third


class TestBooleanInverseCycleIFC2X3(test.bootstrap.IFC2X3, TestBooleanInverseCycle):
    pass
