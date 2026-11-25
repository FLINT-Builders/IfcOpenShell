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

"""Bounds for metric length formatting driven by annotation text.

These tests fail while a decimal-places count from a format query is passed
straight into a float format string. They pass once that count is rejected or
clamped to a small range (at most 10) before the format string is built, and
the same bound holds for the annotation command that feeds it.
"""

import ast
import os
import re
import tempfile
import tracemalloc
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.representation
import ifcopenshell.util.selector as selector
import ifcopenshell.util.unit as unit

# Far past any length annotation. The unfixed formatter emits one character
# per requested place, so this stays small as an input and large as an output.
HUGE_DECIMAL_PLACES = 100_000
MAX_DECIMAL_PLACES = 10
# "1." plus ten digits, with room for a sign.
MAX_NUMBER_LENGTH = 32
# Two short numbers plus the literal's own surrounding words.
MAX_LITERAL_LENGTH = 200
# format_length of a normal value peaks at a few hundred bytes. Building the
# uncapped string peaks well above this, including a format-then-slice.
MAX_FORMAT_LENGTH_PEAK = 16_384
# selector.format compiles a short query with lark (tens of KB) and then
# formats. The uncapped string pushes the peak well past this.
MAX_SELECTOR_PEAK = 100_000
# Two selector.format calls on a short literal stay under this. Two uncapped
# replacements do not, even if the final text is sliced afterwards.
MAX_LITERAL_PEAK = 160_000

DRAWING_PY = Path(__file__).resolve().parents[4] / "src" / "bonsai" / "bonsai" / "tool" / "drawing.py"


def _peak_and_result(callback):
    tracemalloc.start()
    tracemalloc.reset_peak()
    try:
        try:
            result = callback()
        except Exception:
            result = None
            raised = True
        else:
            raised = False
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return result, raised, peak


def _assert_no_long_decimal(result: str) -> None:
    for match in re.finditer(r"\d+\.(\d+)", result):
        assert len(match.group(1)) <= MAX_DECIMAL_PLACES


def _load_replace_text_literal_variables():
    """Load Drawing.replace_text_literal_variables from its source file.

    bonsai.tool.drawing imports Blender at module import, so the test executes
    the function body from that file instead of importing the module.
    """
    tree = ast.parse(DRAWING_PY.read_text(encoding="utf-8"), filename=str(DRAWING_PY))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "Drawing":
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef) or item.name != "replace_text_literal_variables":
                continue
            for arg in item.args.args:
                arg.annotation = None
            item.returns = None
            func = ast.FunctionDef(
                name="replace_text_literal_variables",
                args=item.args,
                body=item.body,
                decorator_list=[],
                returns=None,
            )
            module = ast.Module(body=[func], type_ignores=[])
            ast.fix_missing_locations(module)
            namespace = {}
            exec(compile(module, str(DRAWING_PY), "exec"), {"re": re, "ifcopenshell": ifcopenshell}, namespace)
            return namespace["replace_text_literal_variables"]
    raise AssertionError(f"replace_text_literal_variables was not found in {DRAWING_PY}")


def _annotation_with_literal(literal: str) -> ifcopenshell.entity_instance:
    ifc = ifcopenshell.file(schema="IFC4")
    annotation = ifc.create_entity("IfcAnnotation", Name="Note", ObjectType="TEXT")
    annotation.Representation = ifc.create_entity("IfcProductDefinitionShape")
    parent = ifc.create_entity(
        "IfcGeometricRepresentationContext",
        ContextType="Plan",
        CoordinateSpaceDimension=2,
        Precision=1e-5,
    )
    context = ifc.create_entity(
        "IfcGeometricRepresentationSubContext",
        ContextType="Plan",
        ContextIdentifier="Annotation",
        TargetView="PLAN_VIEW",
        ParentContext=parent,
    )
    item = ifc.create_entity(
        "IfcTextLiteralWithExtent",
        Literal=literal,
        Path="RIGHT",
        BoxAlignment="bottom-left",
    )
    representation = ifc.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=context,
        RepresentationIdentifier="Annotation",
        RepresentationType="Annotation2D",
        Items=[item],
    )
    annotation.Representation.Representations = [representation]

    handle, path = tempfile.mkstemp(suffix=".ifc")
    os.close(handle)
    try:
        ifc.write(path)
        reopened = ifcopenshell.open(path)
    finally:
        os.remove(path)
    return reopened.by_type("IfcAnnotation")[0]


def _literal_from_annotation(annotation: ifcopenshell.entity_instance) -> str:
    assert ifcopenshell.util.element.get_predefined_type(annotation) == "TEXT"
    representation = ifcopenshell.util.representation.get_representation(annotation, "Plan", "Annotation")
    assert representation is not None
    literals = [item for item in representation.Items if item.is_a("IfcTextLiteral")]
    assert len(literals) == 1
    return literals[0].Literal


class TestMetricLengthDecimalPlaces:
    def test_format_length_does_not_allocate_a_huge_decimal_string(self):
        # Warm the formatter so the measured peak is the formatting itself.
        unit.format_length(1.0, 1.0, 2, unit_system="metric")

        result, raised, peak = _peak_and_result(
            lambda: unit.format_length(1.0, 1.0, HUGE_DECIMAL_PLACES, unit_system="metric")
        )

        assert peak < MAX_FORMAT_LENGTH_PEAK
        if not raised:
            assert len(result) <= MAX_NUMBER_LENGTH
            _assert_no_long_decimal(result)

    def test_selector_format_does_not_allocate_a_huge_decimal_string(self):
        annotation = ifcopenshell.file(schema="IFC4").create_entity("IfcAnnotation", ObjectType="TEXT")
        query = f"metric_length(1, 1, {HUGE_DECIMAL_PLACES})"
        selector.format("metric_length(1, 1, 2)", annotation)

        result, raised, peak = _peak_and_result(lambda: selector.format(query, annotation))

        assert peak < MAX_SELECTOR_PEAK
        if not raised:
            assert len(result) <= MAX_NUMBER_LENGTH
            _assert_no_long_decimal(result)

    def test_ifc_text_literal_commands_cannot_exhaust_memory(self):
        command = f"``metric_length(1, 1, {HUGE_DECIMAL_PLACES})``"
        literal = f"Note {command} and {command}"
        annotation = _annotation_with_literal(literal)
        stored = _literal_from_annotation(annotation)
        assert stored == literal
        replace = _load_replace_text_literal_variables()
        # Same call get_text_data and the SVG writer make: the literal text and
        # the annotation, which is truthy even when nothing else is assigned.
        replace(None, "``metric_length(1, 1, 2)``", annotation)

        result, raised, peak = _peak_and_result(lambda: replace(None, stored, annotation))

        assert raised is False
        assert peak < MAX_LITERAL_PEAK
        assert len(result) <= MAX_LITERAL_LENGTH
        assert "metric_length" not in result
        assert str(HUGE_DECIMAL_PLACES) not in result
        _assert_no_long_decimal(result)
