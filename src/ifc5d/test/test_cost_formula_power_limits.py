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

"""Bounds for cost quantity formulas.

``FormulaEvaluator.visit_BinOp`` applies ``operator.pow`` to whatever the
formula evaluates to. These tests require that path to refuse oversized
powers before the result is stored.

Limits, checked on the numbers that would be passed to the power
operation (not only on literal text in the formula):

- absolute value of an exponent greater than 10
- absolute value of a base greater than 1_000_000
- a base or exponent that is not an ``int`` or ``float``
- a formula string longer than 1024 characters
- a syntax tree deeper than 32 nodes

Tree depth counts every node, including the ``Expression`` root. A leaf
is 1. Every other node is ``1 + max(child depths)``.

Negation of a quantity must still evaluate, and ``*`` must still evaluate.
``ast.Pow`` is the only operator this evaluator leaves unbounded. The cost
value formula parser in ``ifcopenshell.util.cost`` does not evaluate
Python power expressions and is not covered here. Bonsai's import and
refresh operators only forward the CSV path into ``Csv2Ifc.execute`` and
``Csv2Ifc.refresh``, which are covered below.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import tempfile
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.cost
import ifcopenshell.api.pset
import ifcopenshell.api.root
import pytest

import ifc5d.csv2ifc

MAX_ABS_EXPONENT = 10
MAX_ABS_BASE = 1_000_000
MAX_FORMULA_LENGTH = 1024
MAX_AST_DEPTH = 32

CSV_HEADER = "Index,Identification,Name,Unit,Value,Quantity,Query,Property,Formula\n"


def ast_depth(node: ast.AST) -> int:
    children = list(ast.iter_child_nodes(node))
    if not children:
        return 1
    return 1 + max(ast_depth(child) for child in children)


def _repository_formula_source() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "src/ifcopenshell-python/ifcopenshell/api/cost/assign_cost_item_quantity.py"
        if candidate.is_file():
            return candidate
    raise RuntimeError("assign_cost_item_quantity.py was not found in this checkout")


def _load_repository_formula_module():
    """Evaluate the checkout's formula module, not a previously imported copy."""
    source = _repository_formula_source()
    spec = importlib.util.spec_from_file_location("ifcopenshell.api.cost.assign_cost_item_quantity", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ifcopenshell.api.cost.assign_cost_item_quantity"] = module
    spec.loader.exec_module(module)
    wrapped = ifcopenshell.api.wrap_usecase("cost.assign_cost_item_quantity", module.assign_cost_item_quantity)
    ifcopenshell.api.cost.assign_cost_item_quantity = wrapped
    ifcopenshell.api.CACHED_USECASES.pop("cost.assign_cost_item_quantity", None)
    return module


FORMULA_MODULE = _load_repository_formula_module()


def build_model(net_volume: float | None = None):
    ifc = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
    wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
    if net_volume is not None:
        qto = ifcopenshell.api.pset.add_qto(ifc, product=wall, name="Qto_WallBaseQuantities")
        ifcopenshell.api.pset.edit_qto(ifc, qto=qto, properties={"NetVolume": net_volume})
    schedule = ifcopenshell.api.cost.add_cost_schedule(ifc, name="Schedule")
    item = ifcopenshell.api.cost.add_cost_item(ifc, cost_schedule=schedule)
    return ifc, wall, item, schedule


def assign_formula(ifc, item, wall, formula: str):
    return ifcopenshell.api.cost.assign_cost_item_quantity(
        ifc,
        cost_item=item,
        products=[wall],
        formula=formula,
        ifc_class="IfcQuantityVolume",
    )


def stored_quantities(ifc) -> list:
    return [quantity[3] for quantity in ifc.by_type("IfcPhysicalSimpleQuantity")]


def assert_value_absent(ifc, forbidden: float) -> None:
    for value in stored_quantities(ifc):
        assert value != forbidden


def reject_formula(formula: str, forbidden: float, net_volume: float | None = None):
    ifc, wall, item, _schedule = build_model(net_volume)
    with pytest.raises(ValueError):
        assign_formula(ifc, item, wall, formula)
    assert_value_absent(ifc, forbidden)
    return ifc


def write_csv(directory: Path, formula: str, query: str = "IfcWall") -> Path:
    path = directory / "schedule.csv"
    path.write_text(CSV_HEADER + f"1,X,Boom,m3,,,{query},,{formula}\n", encoding="utf-8")
    return path


class TestCostFormulaPowerLimits:
    def test_limits_match_the_contract(self):
        assert MAX_ABS_EXPONENT == 10
        assert MAX_ABS_BASE == 1_000_000
        assert MAX_FORMULA_LENGTH == 1024
        assert MAX_AST_DEPTH == 32

    def test_literal_exponent_above_cap_is_rejected(self):
        reject_formula("2**11", 2048)

    def test_float_exponent_above_cap_is_rejected(self):
        reject_formula("2**20.0", 1048576)

    def test_right_associative_tower_is_rejected(self):
        # 2**(2**(2**2)) evaluates the outer exponent to 16, above the cap.
        # Every literal exponent in the text is 2.
        tree = ast.parse("2**2**2**2", mode="eval")
        with pytest.raises(ValueError):
            FORMULA_MODULE.FormulaEvaluator({}).visit(tree.body)
        reject_formula("2**2**2**2", 65536)

    def test_exponent_from_multiplication_is_rejected(self):
        reject_formula("2**(10*2)", 1048576)

    def test_exponent_from_quantity_is_rejected(self):
        reject_formula("2**NetVolume", 1048576, net_volume=20.0)

    def test_base_above_cap_is_rejected(self):
        reject_formula("1000001**2", 1000002000001)

    def test_base_from_quantity_above_cap_is_rejected(self):
        reject_formula("NetVolume**2", 1000002000001, net_volume=1000001.0)

    def test_non_numeric_base_is_rejected(self):
        ifc, wall, item, _schedule = build_model()
        with pytest.raises(ValueError):
            assign_formula(ifc, item, wall, "Missing**2")

    def test_non_numeric_exponent_is_rejected(self):
        ifc, wall, item, _schedule = build_model()
        with pytest.raises(ValueError):
            assign_formula(ifc, item, wall, "2**Missing")

    def test_formula_longer_than_1024_characters_is_rejected(self):
        formula = "NetVolume" + (" " * 1100) + "* 2"
        assert len(formula) > MAX_FORMULA_LENGTH
        reject_formula(formula, 6, net_volume=3.0)

    def test_formula_deeper_than_32_nodes_is_rejected(self):
        formula = "1+" * 31 + "1"
        assert ast_depth(ast.parse(formula, mode="eval")) > MAX_AST_DEPTH
        reject_formula(formula, 32)

    def test_quantity_negation_is_applied(self):
        ifc, wall, item, _schedule = build_model(3.0)
        assign_formula(ifc, item, wall, "-NetVolume")
        assert -3.0 in stored_quantities(ifc)

    def test_multiplication_formula_is_applied(self):
        ifc, wall, item, _schedule = build_model(3.0)
        assign_formula(ifc, item, wall, "NetVolume * 2")
        assert 6.0 in stored_quantities(ifc)

    def test_csv_import_rejects_power_tower(self):
        ifc, _wall, _item, _schedule = build_model()
        with tempfile.TemporaryDirectory() as directory:
            csv_path = write_csv(Path(directory), "2**2**2**2")
            with pytest.raises(ValueError):
                ifc5d.csv2ifc.Csv2Ifc(str(csv_path), ifc).execute()
        assert_value_absent(ifc, 65536)

    def test_csv_import_rejects_quantity_exponent(self):
        ifc, _wall, _item, _schedule = build_model(20.0)
        with tempfile.TemporaryDirectory() as directory:
            csv_path = write_csv(Path(directory), "2**NetVolume")
            with pytest.raises(ValueError):
                ifc5d.csv2ifc.Csv2Ifc(str(csv_path), ifc).execute()
        assert_value_absent(ifc, 1048576)

    def test_csv_import_rejects_literal_exponent(self):
        ifc, _wall, _item, _schedule = build_model()
        with tempfile.TemporaryDirectory() as directory:
            csv_path = write_csv(Path(directory), "2**11")
            with pytest.raises(ValueError):
                ifc5d.csv2ifc.Csv2Ifc(str(csv_path), ifc).execute()
        assert_value_absent(ifc, 2048)

    def test_csv_refresh_rejects_power_tower(self):
        ifc, _wall, _item, schedule = build_model()
        with tempfile.TemporaryDirectory() as directory:
            csv_path = write_csv(Path(directory), "2**2**2**2")
            csv2ifc = ifc5d.csv2ifc.Csv2Ifc(str(csv_path), ifc, cost_schedule=schedule)
            with pytest.raises(ValueError):
                csv2ifc.refresh()
        assert_value_absent(ifc, 65536)
