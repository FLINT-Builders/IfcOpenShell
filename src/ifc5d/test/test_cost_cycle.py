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

"""Cost export and CSV rate import must survive cyclic nested cost items."""

from __future__ import annotations

import csv

import ifcopenshell
import ifcopenshell.api.cost
import ifcopenshell.api.nest
import ifcopenshell.api.owner.settings
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.unit
import pytest
from ifc5d.csv2ifc import Csv2Ifc
from ifc5d.ifc5Dspreadsheet import Ifc5DCsvWriter


def _prepare() -> ifcopenshell.file:
    model = ifcopenshell.api.project.create_file()
    ifcopenshell.api.owner.settings.get_user = lambda ifc: (ifc.by_type("IfcPersonAndOrganization") or [None])[0]
    ifcopenshell.api.owner.settings.get_application = lambda ifc: (ifc.by_type("IfcApplication") or [None])[0]
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="P")
    ifcopenshell.api.unit.assign_unit(model)
    return model


def _item(model, *, schedule=None, parent=None, name: str, identification: str | None = None):
    if parent is None:
        item = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=schedule)
    else:
        item = ifcopenshell.api.cost.add_cost_item(model, cost_item=parent)
    attributes = {"Name": name}
    if identification is not None:
        attributes["Identification"] = identification
    ifcopenshell.api.cost.edit_cost_item(model, cost_item=item, attributes=attributes)
    return item


def write_mutual_cycle(path) -> str:
    model = _prepare()
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="BoQ")
    item_a = _item(model, schedule=schedule, name="A", identification="A")
    item_b = _item(model, parent=item_a, name="B", identification="B")
    _item(model, parent=item_a, name="Sibling", identification="S")
    ifcopenshell.api.nest.assign_object(model, related_objects=[item_a], relating_object=item_b)
    model.write(str(path))
    return str(path)


def write_self_cycle(path) -> str:
    model = _prepare()
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="BoQ")
    item = _item(model, schedule=schedule, name="Loop", identification="L")
    ifcopenshell.api.nest.assign_object(model, related_objects=[item], relating_object=item)
    model.write(str(path))
    return str(path)


def invoke(func):
    try:
        return func()
    except RecursionError as exc:
        pytest.fail(f"cyclic nested cost items exhausted the stack: {exc}")


def _rows(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


class TestCyclicCostExport:
    def test_csv_writer_lists_mutual_cycle_once(self, tmp_path):
        ifc_path = write_mutual_cycle(tmp_path / "mutual.ifc")
        output = tmp_path / "sheets"
        writer = Ifc5DCsvWriter(str(ifc_path), str(output))
        invoke(writer.write)
        written = list(output.glob("*.csv"))
        assert len(written) == 1
        rows = _rows(written[0])
        header = rows[0]
        name_at = header.index("Name")
        id_at = header.index("Id")
        names = [row[name_at] for row in rows[1:]]
        ids = [row[id_at] for row in rows[1:]]
        assert set(names) == {"A", "B", "Sibling"}
        assert len(ids) == len(set(ids)) == 3

    def test_csv_writer_lists_self_cycle_once(self, tmp_path):
        ifc_path = write_self_cycle(tmp_path / "self.ifc")
        output = tmp_path / "sheets"
        writer = Ifc5DCsvWriter(str(ifc_path), str(output))
        invoke(writer.write)
        rows = _rows(next(output.glob("*.csv")))
        header = rows[0]
        names = [row[header.index("Name")] for row in rows[1:]]
        ids = [row[header.index("Id")] for row in rows[1:]]
        assert names == ["Loop"]
        assert len(ids) == len(set(ids)) == 1


class TestCyclicRateImport:
    def test_csv_import_reads_cyclic_rate_schedule(self, tmp_path):
        ifc_path = write_mutual_cycle(tmp_path / "mutual.ifc")
        csv_path = tmp_path / "import.csv"
        csv_path.write_text(
            "Index,Name,Unit,Value,RateSchedule,RateID\n1,ImportedWall,m2,10,BoQ,B\n",
            encoding="utf-8",
        )
        before = {p.name for p in tmp_path.iterdir()}
        model = ifcopenshell.open(ifc_path)
        importer = Csv2Ifc(str(csv_path), ifc_file=model)
        invoke(importer.execute)
        assert {p.name for p in tmp_path.iterdir()} == before
        assert any(item.Name == "ImportedWall" for item in model.by_type("IfcCostItem"))
