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

"""Cost-schedule export must not turn IFC text into spreadsheet formulas.

Ifc5DXlsxWriter and Ifc5DCsvWriter copy IfcCostItem Identification, Name and
Description, and an IfcCostValue category header, straight into the workbook.
A string that starts with "=" has to stay text. The TotalPrice cell is the
one generated formula and has to stay a formula.

These tests fail until that neutralization is in place.
"""

import csv
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.cost
import ifcopenshell.api.root
import openpyxl

import ifc5d.ifc5Dspreadsheet

IDENTIFICATION = "=1+1"
NAME = "=2+2"
DESCRIPTION = "=3+3"
CATEGORY = "=4+4"
# Category is written as a CSV column header, not as a data cell.
CATEGORY_HEADER = f"{CATEGORY} Cost"


def assert_text_preserved_and_not_formula(value, original: str) -> None:
    assert value == original or value == "'" + original


def write_cost_schedule(path: Path) -> None:
    model = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="Formula export")
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="BoQ", predefined_type="PRICEDBILLOFQUANTITIES")
    item = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=schedule)
    ifcopenshell.api.cost.edit_cost_item(
        model,
        cost_item=item,
        attributes={"Identification": IDENTIFICATION, "Name": NAME, "Description": DESCRIPTION},
    )
    value = ifcopenshell.api.cost.add_cost_value(model, parent=item)
    ifcopenshell.api.cost.edit_cost_value(
        model, cost_value=value, attributes={"AppliedValue": 5.0, "Category": CATEGORY}
    )
    item.CostQuantities = [model.create_entity("IfcQuantityArea", Name="Area", AreaValue=2.0)]
    model.write(path)


def exported_model(ifc_path: Path):
    # Reload from disk so the strings are whatever the IFC parser hands the writer.
    return ifcopenshell.open(ifc_path)


def test_xlsx_cost_item_text_is_not_a_formula(tmp_path: Path) -> None:
    ifc_path = tmp_path / "model.ifc"
    write_cost_schedule(ifc_path)
    output = tmp_path / "xlsx"
    ifc5d.ifc5Dspreadsheet.Ifc5DXlsxWriter(exported_model(ifc_path), str(output)).write()

    workbook = openpyxl.load_workbook(next(output.glob("*.xlsx")))
    worksheet = workbook.active
    headers = [cell.value for cell in worksheet[1]]
    assert headers == ["ID", "Name", "Quantity", "Value", "Total Cost"]
    row = worksheet[2]

    identification = row[headers.index("ID")]
    name = row[headers.index("Name")]
    # openpyxl reloads a formula cell with data_type "f". Text must not take that path.
    assert identification.data_type != "f"
    assert name.data_type != "f"
    assert_text_preserved_and_not_formula(identification.value, IDENTIFICATION)
    assert_text_preserved_and_not_formula(name.value, NAME)

    quantity_col = openpyxl.utils.get_column_letter(headers.index("Quantity") + 1)
    value_col = openpyxl.utils.get_column_letter(headers.index("Value") + 1)
    total = row[headers.index("Total Cost")]
    assert total.data_type == "f"
    assert total.value == f"={quantity_col}2*{value_col}2"


def test_csv_cost_item_text_is_not_formula_text(tmp_path: Path) -> None:
    ifc_path = tmp_path / "model.ifc"
    write_cost_schedule(ifc_path)
    output = tmp_path / "csv"
    ifc5d.ifc5Dspreadsheet.Ifc5DCsvWriter(exported_model(ifc_path), str(output)).write()

    with next(output.glob("*.csv")).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    headers, data = rows[0], rows[1]

    for column, original in (
        ("Identification", IDENTIFICATION),
        ("Name", NAME),
        ("Description", DESCRIPTION),
    ):
        value = data[headers.index(column)]
        assert not value.startswith("=")
        assert_text_preserved_and_not_formula(value, original)

    category_headers = [header for header in headers if "4+4" in header]
    assert len(category_headers) == 1
    assert not category_headers[0].startswith("=")
    assert_text_preserved_and_not_formula(category_headers[0], CATEGORY_HEADER)
