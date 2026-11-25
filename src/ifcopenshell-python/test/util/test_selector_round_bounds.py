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

"""Bounds for ``FormatTransformer.round``.

``round`` turns its arguments into ``Decimal`` values and then into Python
integers. An exponent such as ``1e300000`` is inside the default decimal
context, and that integer conversion takes time proportional to the square of
the digit count. These tests are the spec for rejecting that work up front.

A value or a step is rejected when its ``Decimal`` is not finite, when
constructing it overflows the decimal context, or when ``abs(adjusted())`` is
greater than 30. ``round`` then returns the original value unchanged and does
not divide, call ``round``, or convert the magnitude to ``int``. Ordinary
values at or below that limit still round as they do today.
"""

import ast
import re
import tempfile
import time
from decimal import Decimal
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.util.selector as subject
import test.bootstrap

# Absolute Decimal.adjusted() limit. 30 matches a coordinate or a length well
# beyond anything a drawing annotation needs, and 10**30 is still cheap to round.
MAX_ABS_ADJUSTED = 30
# Large enough that the quadratic conversion takes seconds on this interpreter,
# while a rejection that happens before the conversion stays well under MAX_SECONDS.
HUGE_EXPONENT = 300_000
MAX_SECONDS = 0.4


def _evaluate(query, element=None):
    started = time.perf_counter()
    try:
        result = subject.format(query, element)
        error = None
    except Exception as caught:
        result = None
        error = caught
    return result, error, time.perf_counter() - started


def _assert_round(query, expected, element=None):
    result, error, elapsed = _evaluate(query, element)
    assert elapsed < MAX_SECONDS, f"{query!r} took {elapsed:.3f}s (result={result!r}, error={error!r})"
    assert error is None, error
    assert result == expected
    assert len(result) < 64


def _drawing_source():
    here = Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (
            parent / "src/bonsai/bonsai/tool/drawing.py",
            parent / "bonsai/bonsai/tool/drawing.py",
        ):
            if candidate.is_file():
                return candidate
    raise FileNotFoundError("bonsai/tool/drawing.py")


def _replace_text_literal_variables():
    """Load Drawing.replace_text_literal_variables from its source file.

    The drawing module imports Blender, which is not available here. The
    function itself only uses ``re`` and ``ifcopenshell.util.selector``, so
    executing that function from the file runs the same statements the
    annotation and drawing paths call.
    """
    tree = ast.parse(_drawing_source().read_text())
    function = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Drawing":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "replace_text_literal_variables":
                    function = item
                    break
    if function is None:
        raise AssertionError("replace_text_literal_variables was not found")
    function.decorator_list = []
    function.returns = None
    for arg in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs):
        arg.annotation = None
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"re": re, "ifcopenshell": ifcopenshell}
    exec(compile(module, str(_drawing_source()), "exec"), namespace)
    return namespace["replace_text_literal_variables"]


class TestRoundExponentBounds(test.bootstrap.IFC4):
    def test_in_range_values_still_round(self):
        assert subject.format("round(123, 5)") == "125"
        assert subject.format("round(-123, 5)") == "-125"
        assert subject.format("round(1.239, 0.01)") == "1.24"
        assert subject.format('round("Level 1", 0.01)') == "Level 1"

        wall = ifcopenshell.api.root.create_entity(self.file, ifc_class="IfcWall")
        pset = ifcopenshell.api.pset.add_pset(self.file, name="Pset_X", product=wall)
        ifcopenshell.api.pset.edit_pset(self.file, pset=pset, properties={"N": "123.456"})
        assert subject.format("round({{Pset_X.N}}, 0.01)", wall) == "123.46"

        # adjusted() == 30 stays inside the limit and must still round. The
        # rendering may be the full integer or a decimal string; it must not be
        # the original token left untouched.
        at_limit = subject.format("round(1e30, 1)")
        assert at_limit != "1e30"
        assert Decimal(at_limit) == Decimal("1e30")
        assert len(at_limit) <= MAX_ABS_ADJUSTED + 1

    def test_exponent_above_limit_returns_the_value(self):
        _assert_round("round(1e31, 1)", "1e31")
        _assert_round("round(1E+31, 1)", "1E+31")
        _assert_round("round(-1e31, 1)", "-1e31")
        _assert_round("round(1e31, 0.5)", "1e31")
        _assert_round("round(1e31, 1e31)", "1e31")
        _assert_round("round((1e31), 1)", "1e31")

    def test_step_exponent_above_limit_returns_the_value(self):
        # The step is a NUMBER token, not an expression. A tiny step makes
        # value/step huge even when the value itself is 1.
        _assert_round("round(1, 1e-31)", "1")
        _assert_round("round(1.5, 1e-31)", "1.5")
        _assert_round("round(1e20, 1E-31)", "1e20")
        _assert_round("round(-2, 1e31)", "-2")

    def test_nonfinite_values_return_the_value(self):
        _assert_round('round("Infinity", 1)', "Infinity")
        _assert_round('round("-Infinity", 1)', "-Infinity")
        _assert_round('round("NaN", 1)', "NaN")
        _assert_round('round("sNaN", 1)', "sNaN")
        # Past the context Emax, Decimal() raises Overflow instead of building a finite value.
        _assert_round("round(1e10000000, 1)", "1e10000000")
        _assert_round("round(1, 1e-10000000)", "1")

    def test_property_exponent_returns_the_value(self):
        wall = ifcopenshell.api.root.create_entity(self.file, ifc_class="IfcWall")
        pset = ifcopenshell.api.pset.add_pset(self.file, name="Pset_X", product=wall)
        ifcopenshell.api.pset.edit_pset(
            self.file,
            pset=pset,
            properties={"Big": "1e31", "Neg": "-1e31", "Inf": "Infinity", "NaN": "NaN"},
        )
        _assert_round("round({{Pset_X.Big}}, 1)", "1e31", wall)
        _assert_round("round({{Pset_X.Neg}}, 0.5)", "-1e31", wall)
        _assert_round("round({{Pset_X.Inf}}, 1)", "Infinity", wall)
        _assert_round("round({{Pset_X.NaN}}, 1)", "NaN", wall)

    def test_huge_exponent_is_rejected_before_conversion(self):
        literal = f"1e{HUGE_EXPONENT}"
        wall = ifcopenshell.api.root.create_entity(self.file, ifc_class="IfcWall")
        pset = ifcopenshell.api.pset.add_pset(self.file, name="Pset_X", product=wall)
        ifcopenshell.api.pset.edit_pset(self.file, pset=pset, properties={"Big": literal})

        failures = []
        cases = (
            (f"round({literal}, 1)", None, literal),
            (f"round(-{literal}, 1)", None, f"-{literal}"),
            (f"round({literal}, 0.5)", None, literal),
            ("round({{Pset_X.Big}}, 1)", wall, literal),
            ("round({{Pset_X.Big}}, 0.5)", wall, literal),
        )
        for query, element, expected in cases:
            result, error, elapsed = _evaluate(query, element)
            if elapsed >= MAX_SECONDS or error is not None or result != expected:
                failures.append(f"{query!r} took {elapsed:.3f}s result={result!r} error={error!r}")
        assert not failures

    def test_huge_step_is_rejected_before_conversion(self):
        step = f"1e-{HUGE_EXPONENT}"
        failures = []
        cases = (
            (f"round(1, {step})", "1"),
            (f"round(-1.25, {step})", "-1.25"),
            (f"round(1e20, {step})", "1e20"),
        )
        for query, expected in cases:
            result, error, elapsed = _evaluate(query)
            if elapsed >= MAX_SECONDS or error is not None or result != expected:
                failures.append(f"{query!r} took {elapsed:.3f}s result={result!r} error={error!r}")
        assert not failures

    def test_annotation_literal_commands_stay_bounded(self):
        literal_text = f"A ``round(1e{HUGE_EXPONENT}, 1)`` B ``round(1, 1e-{HUGE_EXPONENT})`` C ``round(123, 5)``"
        annotation = self.file.create_entity("IfcAnnotation", Name="note", ObjectType="TEXT")
        context = self.file.create_entity("IfcGeometricRepresentationContext", ContextType="Plan")
        item = self.file.create_entity("IfcTextLiteral", Literal=literal_text, Path="RIGHT")
        representation = self.file.create_entity("IfcShapeRepresentation", ContextOfItems=context, Items=[item])
        annotation.Representation = self.file.create_entity(
            "IfcProductDefinitionShape", Representations=[representation]
        )
        with tempfile.TemporaryDirectory() as directory:
            written = Path(directory) / "annotation.ifc"
            self.file.write(str(written))
            reloaded = ifcopenshell.open(str(written))

        reloaded_annotation = reloaded.by_type("IfcAnnotation")[0]
        literals = [
            entity
            for shape in reloaded_annotation.Representation.Representations
            for entity in shape.Items
            if entity.is_a("IfcTextLiteral")
        ]
        assert literals[0].Literal == literal_text

        product = reloaded.by_type("IfcAnnotation")[0]
        replace = _replace_text_literal_variables()
        started = time.perf_counter()
        resolved = replace(None, literals[0].Literal, product)
        elapsed = time.perf_counter() - started
        assert elapsed < MAX_SECONDS, f"text literal resolution took {elapsed:.3f}s and returned {resolved!r}"
        assert resolved == f"A 1e{HUGE_EXPONENT} B 1 C 125"
