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

"""Resource CSV export must not emit spreadsheet formulas.

Ifc2Csv writes construction-resource text from an IFC file into CSV cells.
Text that starts with ``=``, ``+``, ``-``, or ``@`` has to be prefixed with
one apostrophe so a spreadsheet stores the cell as text. CSV quoting is not
enough: a reader returns the formula string with the quotes removed.

These tests open a written IFC file and export it with ``Ifc2Csv``, the
writer Bonsai's resource export calls. They fail while the exporter copies
the source text unchanged.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.resource
import ifcopenshell.api.root
import ifcopenshell.api.unit
import pytest

_IFC4D_ROOT = Path(__file__).resolve().parents[1]
if str(_IFC4D_ROOT) not in sys.path:
    sys.path.insert(0, str(_IFC4D_ROOT))

from ifc4d.csv2ifc import Ifc2Csv

FORMULA_PREFIXES = ("=", "+", "-", "@")
TEXT_COLUMNS = (
    "ACTIVITY/RESOURCE NAME",
    "DESCRIPTION",
    "QUANTITY NAME",
    "BASE QUANTITY NAME",
    "GUID",
)


def attacker_text(prefix: str, number: int) -> str:
    if prefix == "@":
        return f"@SUM(Z{number})"
    if prefix == "-":
        return f"-{number}+{number + 1}"
    return f"{prefix}{number}+{number}"


def attacker_guid(prefix: str, number: int) -> str:
    body = attacker_text(prefix, number)
    if len(body) < 22:
        body = (body + ("+0" * 22))[:22]
    else:
        body = body[:22]
    assert len(body) == 22 and body.startswith(prefix)
    return body


def expected_cell(source: str | None) -> str:
    if source is None:
        return ""
    if source[:1] in FORMULA_PREFIXES:
        return "'" + source
    return source


def _add_productivity(ifc: ifcopenshell.file, resource: ifcopenshell.entity_instance, quantity_name: str) -> None:
    pset = ifcopenshell.api.pset.add_pset(ifc, product=resource, name="EPset_Productivity")
    ifcopenshell.api.pset.edit_pset(
        ifc,
        pset=pset,
        properties={
            "BaseQuantityProducedName": quantity_name,
            "BaseQuantityConsumed": "PT1H",
            "BaseQuantityProducedValue": 1.0,
        },
    )


def _add_base_quantity(
    ifc: ifcopenshell.file,
    resource: ifcopenshell.entity_instance,
    quantity_class: str,
    quantity_name: str,
) -> None:
    quantity = ifcopenshell.api.resource.add_resource_quantity(ifc, resource=resource, ifc_class=quantity_class)
    ifcopenshell.api.resource.edit_resource_quantity(
        ifc, physical_quantity=quantity, attributes={"Name": quantity_name}
    )


def _resource(
    ifc: ifcopenshell.file,
    *,
    ifc_class: str,
    name: str,
    description: str | None,
    guid: str | None = None,
    parent: ifcopenshell.entity_instance | None = None,
    quantity_name: str | None = None,
    base_quantity_name: str | None = None,
    quantity_class: str | None = None,
) -> ifcopenshell.entity_instance:
    resource = ifcopenshell.api.resource.add_resource(ifc, parent_resource=parent, ifc_class=ifc_class, name=name)
    if description is not None:
        resource.Description = description
    if guid is not None:
        resource.GlobalId = guid
    if quantity_name is not None:
        _add_productivity(ifc, resource, quantity_name)
    if base_quantity_name is not None:
        assert quantity_class is not None
        _add_base_quantity(ifc, resource, quantity_class, base_quantity_name)
    return resource


def _cases() -> list[dict[str, str | None]]:
    cases: list[dict[str, str | None]] = []
    for index, prefix in enumerate(FORMULA_PREFIXES):
        cases.append(
            {
                "ifc_class": "IfcLaborResource",
                "name": attacker_text(prefix, 10 + index),
                "description": attacker_text(prefix, 20 + index),
                "quantity_name": attacker_text(prefix, 30 + index),
                "base_quantity_name": attacker_text(prefix, 40 + index),
                "guid": attacker_guid(prefix, 50 + index),
                "quantity_class": "IfcQuantityTime",
                "parent_name": None,
            }
        )
    cases.append(
        {
            "ifc_class": "IfcConstructionEquipmentResource",
            "name": "=8+8",
            "description": "+8+8",
            "quantity_name": "-8+9",
            "base_quantity_name": "@SUM(Z8)",
            "guid": attacker_guid("=", 80),
            "quantity_class": "IfcQuantityTime",
            "parent_name": None,
        }
    )
    cases.append(
        {
            "ifc_class": "IfcCrewResource",
            "name": "Crew",
            "description": "Total=Net",
            "quantity_name": None,
            "base_quantity_name": None,
            "guid": None,
            "quantity_class": None,
            "parent_name": None,
        }
    )
    cases.append(
        {
            "ifc_class": "IfcLaborResource",
            "name": "=1+2,3",
            "description": '="ab"',
            "quantity_name": None,
            "base_quantity_name": "@SUM(Z9)",
            "guid": attacker_guid("+", 90),
            "quantity_class": "IfcQuantityTime",
            "parent_name": "Crew",
        }
    )
    cases.append(
        {
            "ifc_class": "IfcConstructionMaterialResource",
            "name": "Concrete",
            "description": None,
            "quantity_name": None,
            "base_quantity_name": "Volume",
            "guid": None,
            "quantity_class": "IfcQuantityVolume",
            "parent_name": None,
        }
    )
    return cases


def _export_cases(tmp_path: Path) -> tuple[list[dict[str, str | None]], list[dict[str, str]]]:
    ifc = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcProject")
    ifcopenshell.api.unit.assign_unit(ifc)
    cases = _cases()
    created: dict[str, ifcopenshell.entity_instance] = {}
    for case in cases:
        parent = created[case["parent_name"]] if case["parent_name"] else None
        created[case["name"]] = _resource(
            ifc,
            ifc_class=case["ifc_class"],
            name=case["name"],
            description=case["description"],
            guid=case["guid"],
            parent=parent,
            quantity_name=case["quantity_name"],
            base_quantity_name=case["base_quantity_name"],
            quantity_class=case["quantity_class"],
        )

    ifc_path = tmp_path / "resources.ifc"
    ifc.write(str(ifc_path))
    reopened = ifcopenshell.open(str(ifc_path))
    by_name = {resource.Name: resource for resource in reopened.by_type("IfcConstructionResource")}
    for case in cases:
        resource = by_name[case["name"]]
        assert resource.Name == case["name"]
        assert resource.Description == case["description"]
        if case["guid"] is None:
            case["guid"] = resource.GlobalId
            assert resource.GlobalId[:1] not in FORMULA_PREFIXES
        else:
            assert resource.GlobalId == case["guid"]
        if case["base_quantity_name"] is not None:
            assert resource.BaseQuantity.Name == case["base_quantity_name"]

    csv_path = tmp_path / "resources.csv"
    Ifc2Csv(str(csv_path), reopened).execute()
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    header = rows[0]
    exported = [{name: row[index] for index, name in enumerate(header)} for row in rows[1:] if any(row)]
    return cases, exported


def _row_for(exported: list[dict[str, str]], name: str) -> dict[str, str]:
    matches = [row for row in exported if row["ACTIVITY/RESOURCE NAME"] in (name, expected_cell(name))]
    assert len(matches) == 1, name
    return matches[0]


@pytest.fixture(scope="module")
def exported_resources(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[list[dict[str, str | None]], list[dict[str, str]]]:
    return _export_cases(tmp_path_factory.mktemp("resource-csv"))


def test_formula_prefixes_in_resource_text_are_prefixed_with_an_apostrophe(
    exported_resources: tuple[list[dict[str, str | None]], list[dict[str, str]]],
) -> None:
    cases, exported = exported_resources
    for case in cases:
        row = _row_for(exported, case["name"])
        sources = {
            "ACTIVITY/RESOURCE NAME": case["name"],
            "DESCRIPTION": case["description"],
            "QUANTITY NAME": case["quantity_name"],
            "BASE QUANTITY NAME": case["base_quantity_name"],
            "GUID": case["guid"],
        }
        for column in TEXT_COLUMNS:
            cell = row[column]
            source = sources[column]
            assert cell == expected_cell(source), (case["name"], column, cell, source)
            if isinstance(source, str) and source[:1] in FORMULA_PREFIXES:
                assert not cell.startswith(FORMULA_PREFIXES)
                assert cell[1:] == source


def test_nested_and_quoted_formula_text_uses_the_same_neutralization(
    exported_resources: tuple[list[dict[str, str | None]], list[dict[str, str]]],
) -> None:
    _, exported = exported_resources
    nested = _row_for(exported, "=1+2,3")
    assert nested["HIERARCHY"] == "2"
    assert nested["ACTIVITY/RESOURCE NAME"] == "'=1+2,3"
    assert nested["DESCRIPTION"] == '\'="ab"'
    assert nested["BASE QUANTITY NAME"] == "'@SUM(Z9)"
    assert nested["TYPE"] == "LABOR"


def test_text_without_a_formula_prefix_is_unchanged(
    exported_resources: tuple[list[dict[str, str | None]], list[dict[str, str]]],
) -> None:
    _, exported = exported_resources
    crew = _row_for(exported, "Crew")
    assert crew["ACTIVITY/RESOURCE NAME"] == "Crew"
    assert crew["DESCRIPTION"] == "Total=Net"
    assert crew["QUANTITY NAME"] == ""
    concrete = _row_for(exported, "Concrete")
    assert concrete["ACTIVITY/RESOURCE NAME"] == "Concrete"
    assert concrete["DESCRIPTION"] == ""
    assert concrete["BASE QUANTITY NAME"] == "Volume"
    assert concrete["TYPE"] == "MATERIAL"
