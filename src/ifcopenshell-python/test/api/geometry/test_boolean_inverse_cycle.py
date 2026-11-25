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

import json
import os
import subprocess
import sys
import tempfile

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.geom
import ifcopenshell.guid
import ifcopenshell.util.representation
import test.bootstrap

# A finished call returns in well under a second. An unvisited cycle does not return.
CALL_TIMEOUT_SECONDS = 3

# The child re-opens the attacker-supplied IFC and runs one product operation.
# stdout is unused: ifcopenshell may log there. The JSON result is a sibling file.
_CHILD_SCRIPT = r"""
import json
import sys

path, action, payload_json = sys.argv[1:]
payload = json.loads(payload_json)

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.representation
import ifcopenshell.util.shape

model = ifcopenshell.open(path)
result = None
if action == "remove":
    ifcopenshell.api.geometry.remove_boolean(model, model.by_id(payload["target"]))
    model.write(path)
elif action == "add":
    created = ifcopenshell.api.geometry.add_boolean(
        model, model.by_id(payload["target"]), [model.by_id(payload["second"])]
    )
    result = [
        [item.id(), item.Operator, item.SecondOperand.id(), item.FirstOperand.is_a()] for item in created
    ]
elif action == "base_items":
    result = sorted(
        item.id()
        for item in ifcopenshell.util.representation.resolve_base_items(model.by_id(payload["representation"]))
    )
elif action == "extrusions":
    found = ifcopenshell.util.shape.get_extrusions(model.by_id(payload["wall"]))
    result = None if found is None else [item.id() for item in found]
elif action == "base_extrusions":
    found = ifcopenshell.util.shape.get_base_extrusions(model.by_id(payload["wall"]))
    result = None if found is None else [item.id() for item in found]
elif action == "styles":
    result = [item.id() for item in ifcopenshell.util.element.get_styles(model.by_id(payload["wall"]))]
elif action == "shape":
    try:
        ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), model.by_id(payload["target"]))
        result = "returned"
    except Exception as exc:
        result = "raised:" + type(exc).__name__
else:
    raise SystemExit("unknown action " + action)

with open(path + ".json", "w", encoding="utf-8") as handle:
    json.dump(result, handle)
"""


class CallDidNotReturn(AssertionError):
    pass


class TestBooleanInverseCycle(test.bootstrap.IFC4):
    def _reopen(self):
        with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as handle:
            path = handle.name
        try:
            self.file.write(path)
            self.file = ifcopenshell.open(path)
        finally:
            os.remove(path)

    def _alive(self, entity_id):
        return any(element.id() == entity_id for element in self.file)

    def _body(self, items):
        context = self.file.create_entity(
            "IfcGeometricRepresentationContext",
            ContextType="Model",
            CoordinateSpaceDimension=3,
            Precision=1e-5,
        )
        subcontext = self.file.create_entity(
            "IfcGeometricRepresentationSubContext",
            ContextIdentifier="Body",
            ContextType="Model",
            TargetView="MODEL_VIEW",
            ParentContext=context,
        )
        return self.file.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=subcontext,
            RepresentationIdentifier="Body",
            RepresentationType="CSG",
            Items=items,
        )

    def _wall(self, representation):
        wall = self.file.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new())
        wall.Representation = self.file.create_entity("IfcProductDefinitionShape", Representations=[representation])
        return wall

    def _finish(self, action, payload):
        """Run one operation in a child process and reload the file when it writes one back."""
        with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as handle:
            path = handle.name
        result_path = path + ".json"
        self.file.write(path)
        try:
            try:
                completed = subprocess.run(
                    [sys.executable, "-c", _CHILD_SCRIPT, path, action, json.dumps(payload)],
                    timeout=CALL_TIMEOUT_SECONDS,
                    capture_output=True,
                    text=True,
                )
            except subprocess.TimeoutExpired as exc:
                raise CallDidNotReturn(
                    f"{action} did not return; the boolean graph was walked again without a visited set"
                ) from exc
            if completed.returncode != 0:
                raise CallDidNotReturn(
                    f"{action} process exited {completed.returncode} without returning\n{completed.stderr}"
                )
            with open(result_path, encoding="utf-8") as handle:
                result = json.load(handle)
            if action == "remove":
                self.file = ifcopenshell.open(path)
            return result
        finally:
            for candidate in (path, result_path):
                if os.path.exists(candidate):
                    os.remove(candidate)

    def test_remove_acyclic_boolean_still_replaces_the_result_with_its_operands(self):
        first = self.file.create_entity("IfcBlock")
        second = self.file.create_entity("IfcBlock")
        boolean = self.file.create_entity(
            "IfcBooleanResult", Operator="DIFFERENCE", FirstOperand=first, SecondOperand=second
        )
        representation = self._body([boolean])
        boolean_id = boolean.id()
        first_id = first.id()
        second_id = second.id()
        representation_id = representation.id()
        self._reopen()

        ifcopenshell.api.geometry.remove_boolean(self.file, self.file.by_id(boolean_id))

        assert not self._alive(boolean_id)
        assert set(self.file.by_id(representation_id).Items) == {self.file.by_id(first_id), self.file.by_id(second_id)}

    def test_remove_boolean_on_mutual_inverse_results_finishes_and_updates_representation(self):
        second = self.file.create_entity("IfcBlock")
        removed = self.file.create_entity("IfcBooleanResult", Operator="DIFFERENCE", SecondOperand=second)
        other = self.file.create_entity(
            "IfcBooleanResult", Operator="UNION", SecondOperand=self.file.create_entity("IfcBlock")
        )
        # Each result lists the other as an operand, so each is an inverse of the other.
        removed.FirstOperand = other
        other.FirstOperand = removed
        # The representation references only the other result, so it is reached by walking inverses.
        representation = self._body([other])
        removed_id = removed.id()
        other_id = other.id()
        second_id = second.id()
        representation_id = representation.id()
        self._reopen()
        removed = self.file.by_id(removed_id)
        other = self.file.by_id(other_id)
        assert other in self.file.get_inverse(removed)
        assert removed in self.file.get_inverse(other)
        assert representation_id not in {inverse.id() for inverse in self.file.get_inverse(removed)}

        self._finish("remove", {"target": removed_id})

        assert not self._alive(removed_id)
        other = self.file.by_id(other_id)
        assert other.FirstOperand == other
        assert set(self.file.by_id(representation_id).Items) == {other, self.file.by_id(second_id)}

    def test_remove_boolean_on_self_inverse_finishes_and_keeps_the_second_operand(self):
        second = self.file.create_entity("IfcBlock")
        removed = self.file.create_entity("IfcBooleanResult", Operator="UNION", SecondOperand=second)
        removed.FirstOperand = removed
        representation = self._body([removed])
        removed_id = removed.id()
        second_id = second.id()
        representation_id = representation.id()
        self._reopen()
        removed = self.file.by_id(removed_id)
        assert removed in self.file.get_inverse(removed)

        self._finish("remove", {"target": removed_id})

        assert not self._alive(removed_id)
        assert list(self.file.by_id(representation_id).Items) == [self.file.by_id(second_id)]
        assert self.file.by_type("IfcBooleanResult") == []

    def test_remove_boolean_on_inverse_cycle_through_csg_solid_finds_the_representation(self):
        second = self.file.create_entity("IfcBlock")
        removed = self.file.create_entity("IfcBooleanResult", Operator="UNION", SecondOperand=second)
        other = self.file.create_entity("IfcBooleanResult", Operator="INTERSECTION", SecondOperand=second)
        csg = self.file.create_entity("IfcCsgSolid", TreeRootExpression=other)
        removed.FirstOperand = csg
        other.FirstOperand = removed
        representation = self._body([csg])
        removed_id = removed.id()
        other_id = other.id()
        csg_id = csg.id()
        second_id = second.id()
        representation_id = representation.id()
        self._reopen()
        removed = self.file.by_id(removed_id)
        other = self.file.by_id(other_id)
        csg = self.file.by_id(csg_id)
        assert other in self.file.get_inverse(removed)
        assert csg in self.file.get_inverse(other)
        assert removed in self.file.get_inverse(csg)
        assert self.file.by_id(representation_id) in self.file.get_inverse(csg)

        self._finish("remove", {"target": removed_id})

        assert not self._alive(removed_id)
        csg = self.file.by_id(csg_id)
        assert self.file.by_id(other_id).FirstOperand == csg
        assert set(self.file.by_id(representation_id).Items) == {csg, self.file.by_id(second_id)}

    def test_remove_boolean_from_operand_of_cyclic_results_removes_the_direct_boolean(self):
        block = self.file.create_entity("IfcBlock")
        direct = self.file.create_entity("IfcBooleanResult", Operator="DIFFERENCE", FirstOperand=block)
        outer = self.file.create_entity(
            "IfcBooleanResult",
            Operator="UNION",
            FirstOperand=direct,
            SecondOperand=self.file.create_entity("IfcBlock"),
        )
        direct.SecondOperand = outer
        block_id = block.id()
        direct_id = direct.id()
        outer_id = outer.id()
        self._reopen()
        block = self.file.by_id(block_id)
        direct = self.file.by_id(direct_id)
        outer = self.file.by_id(outer_id)
        assert direct in self.file.get_inverse(block)
        assert outer in self.file.get_inverse(direct)
        assert direct in self.file.get_inverse(outer)
        assert not block.is_a("IfcBooleanResult")

        self._finish("remove", {"target": block_id})

        assert self._alive(block_id)
        assert not self._alive(direct_id)
        assert self.file.by_id(outer_id).FirstOperand == self.file.by_id(block_id)

    def test_remove_boolean_on_cyclic_clipping_results_finishes(self):
        second = self.file.create_entity("IfcHalfSpaceSolid")
        removed = self.file.create_entity("IfcBooleanClippingResult", Operator="DIFFERENCE", SecondOperand=second)
        other = self.file.create_entity(
            "IfcBooleanClippingResult",
            Operator="DIFFERENCE",
            SecondOperand=self.file.create_entity("IfcHalfSpaceSolid"),
        )
        removed.FirstOperand = other
        other.FirstOperand = removed
        representation = self._body([other])
        removed_id = removed.id()
        other_id = other.id()
        second_id = second.id()
        representation_id = representation.id()
        self._reopen()
        removed = self.file.by_id(removed_id)
        other = self.file.by_id(other_id)
        assert removed.is_a("IfcBooleanClippingResult")
        assert other.is_a("IfcBooleanResult")
        assert other in self.file.get_inverse(removed)
        assert removed in self.file.get_inverse(other)

        self._finish("remove", {"target": removed_id})

        assert not self._alive(removed_id)
        other = self.file.by_id(other_id)
        assert other.is_a("IfcBooleanClippingResult")
        assert other.FirstOperand == other
        assert set(self.file.by_id(representation_id).Items) == {other, self.file.by_id(second_id)}

    def test_add_boolean_on_operand_of_cyclic_results_creates_the_new_boolean(self):
        block = self.file.create_entity("IfcBlock")
        added = self.file.create_entity("IfcSphere")
        inner = self.file.create_entity("IfcBooleanResult", Operator="UNION", FirstOperand=block)
        outer = self.file.create_entity("IfcBooleanResult", Operator="UNION", FirstOperand=inner, SecondOperand=added)
        inner.SecondOperand = outer
        block_id = block.id()
        added_id = added.id()
        inner_id = inner.id()
        outer_id = outer.id()
        self._reopen()
        block = self.file.by_id(block_id)
        inner = self.file.by_id(inner_id)
        outer = self.file.by_id(outer_id)
        assert inner in self.file.get_inverse(block)
        assert outer in self.file.get_inverse(inner)
        assert inner in self.file.get_inverse(outer)

        created = self._finish("add", {"target": block_id, "second": added_id})

        assert len(created) == 1
        new_id, operator, second_id, first_type = created[0]
        assert operator == "DIFFERENCE"
        assert second_id == added_id
        assert first_type == "IfcBooleanResult"
        assert new_id not in {inner_id, outer_id}

    def _cyclic_results_and_extrusion(self):
        extrusion = self.file.create_entity("IfcExtrudedAreaSolid")
        style = self.file.create_entity("IfcSurfaceStyle", Name="CycleStyle", Side="BOTH")
        self.file.create_entity("IfcStyledItem", Item=extrusion, Styles=[style])
        block = self.file.create_entity("IfcBlock")
        acyclic = self.file.create_entity(
            "IfcBooleanResult", Operator="UNION", FirstOperand=extrusion, SecondOperand=block
        )
        left = self.file.create_entity("IfcBooleanResult", Operator="UNION", SecondOperand=block)
        right = self.file.create_entity("IfcBooleanResult", Operator="UNION", SecondOperand=extrusion)
        left.FirstOperand = right
        right.FirstOperand = left
        representation = self._body([acyclic, left])
        wall = self._wall(representation)
        return {
            "extrusion_id": extrusion.id(),
            "style_id": style.id(),
            "block_id": block.id(),
            "left_id": left.id(),
            "right_id": right.id(),
            "representation_id": representation.id(),
            "wall_id": wall.id(),
        }

    def test_resolve_base_items_on_cyclic_boolean_yields_operands(self):
        ids = self._cyclic_results_and_extrusion()
        self._reopen()
        left = self.file.by_id(ids["left_id"])
        right = self.file.by_id(ids["right_id"])
        assert right in self.file.get_inverse(left)
        assert left in self.file.get_inverse(right)

        found = self._finish("base_items", {"representation": ids["representation_id"]})

        assert set(found) == {ids["extrusion_id"], ids["block_id"]}

    def test_get_extrusions_on_cyclic_boolean_returns_the_extrusion(self):
        ids = self._cyclic_results_and_extrusion()
        self._reopen()
        wall = self.file.by_id(ids["wall_id"])
        assert ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")

        found = self._finish("extrusions", {"wall": ids["wall_id"]})

        assert found == [ids["extrusion_id"]]

    def test_get_base_extrusions_on_cyclic_boolean_returns_the_extrusion(self):
        ids = self._cyclic_results_and_extrusion()
        self._reopen()

        found = self._finish("base_extrusions", {"wall": ids["wall_id"]})

        assert found == [ids["extrusion_id"]]

    def test_get_styles_on_cyclic_boolean_returns_the_operand_style(self):
        ids = self._cyclic_results_and_extrusion()
        self._reopen()
        wall = self.file.by_id(ids["wall_id"])
        assert ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")

        found = self._finish("styles", {"wall": ids["wall_id"]})

        assert ids["style_id"] in found

    def test_create_shape_on_cyclic_difference_finishes(self):
        block = self.file.create_entity("IfcBlock")
        other = self.file.create_entity("IfcBlock")
        acyclic = self.file.create_entity(
            "IfcBooleanResult", Operator="DIFFERENCE", FirstOperand=block, SecondOperand=other
        )
        left = self.file.create_entity("IfcBooleanResult", Operator="DIFFERENCE", SecondOperand=block)
        right = self.file.create_entity("IfcBooleanResult", Operator="DIFFERENCE", SecondOperand=other)
        left.FirstOperand = right
        right.FirstOperand = left
        acyclic_id = acyclic.id()
        left_id = left.id()
        right_id = right.id()
        self._reopen()
        left = self.file.by_id(left_id)
        right = self.file.by_id(right_id)
        assert right in self.file.get_inverse(left)
        assert left in self.file.get_inverse(right)
        settings = ifcopenshell.geom.settings()
        assert ifcopenshell.geom.create_shape(settings, self.file.by_id(acyclic_id)) is not None

        outcome = self._finish("shape", {"target": left_id})

        assert outcome.split(":", 1)[0] in {"returned", "raised"}


class TestBooleanInverseCycleIFC2X3(test.bootstrap.IFC2X3, TestBooleanInverseCycle):
    pass
