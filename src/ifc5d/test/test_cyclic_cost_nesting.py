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

# This file was generated with the assistance of an AI coding tool.

"""Cost-item nest cycles must export as a finite tree.

These tests fail while a walk follows IfcRelNests with no record of the items
already on the path. A fix should skip an item that is already on the current
path and still emit every other nested item. An item reached by two parents
stays under both, because it is not on the path a second time.
"""

import csv

import ifcopenshell
import ifcopenshell.api.cost
import ifcopenshell.api.root
import ifcopenshell.guid
import ifcopenshell.util.cost
from ifcquery.cost import cost

import ifc5d.ifc2json
import ifc5d.ifc5Dspreadsheet


def fresh_file():
    file = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(file, ifc_class="IfcProject", name="P")
    return file


def add_schedule(file, name):
    return ifcopenshell.api.cost.add_cost_schedule(file, name=name)


def add_root(file, schedule, name):
    item = ifcopenshell.api.cost.add_cost_item(file, cost_schedule=schedule)
    item.Name = name
    return item


def add_child(file, parent, name):
    item = ifcopenshell.api.cost.add_cost_item(file, cost_item=parent)
    item.Name = name
    return item


def link(file, parent, children):
    file.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=parent,
        RelatedObjects=list(children),
    )


def save(file, directory):
    path = directory / "schedule.ifc"
    file.write(str(path))
    return path


def entity_named(file, ifc_class, name):
    found = [entity for entity in file.by_type(ifc_class) if entity.Name == name]
    assert len(found) == 1
    return found[0]


def nested_names(nodes, depth=0):
    assert depth <= 8, "cost item nesting expanded a cycle"
    return [(node["Name"], nested_names(node["IsNestedBy"], depth + 1)) for node in nodes]


def convert_file(file, schedule=None):
    converter = ifc5d.ifc2json.ifc5D2json()
    converter.file_path = file
    converter.cost_schedule = schedule
    return converter.convert_ifc_to_json()


def convert_path(path):
    converter = ifc5d.ifc2json.ifc5D2json()
    converter.file_path = str(path)
    return converter.convert_ifc_to_json()


def mutual_cycle():
    file = fresh_file()
    schedule = add_schedule(file, "BoQ")
    first = add_root(file, schedule, "A")
    second = add_child(file, first, "B")
    link(file, second, [first])
    return file


def test_supplied_file_exports_a_two_item_cycle(tmp_path):
    path = save(mutual_cycle(), tmp_path)
    file = ifcopenshell.open(str(path))
    schedule = entity_named(file, "IfcCostSchedule", "BoQ")
    second = entity_named(file, "IfcCostItem", "B")
    assert [item.Name for rel in second.IsNestedBy for item in rel.RelatedObjects] == ["A"]

    data = convert_file(file, schedule)

    assert nested_names(data[0]["cost_items"]) == [("A", [("B", [])])]


def test_path_conversion_exports_every_schedule(tmp_path):
    file = fresh_file()
    cyclic = add_schedule(file, "Cyclic")
    first = add_root(file, cyclic, "A")
    second = add_child(file, first, "B")
    link(file, second, [first])
    plain = add_schedule(file, "Plain")
    add_root(file, plain, "Leaf")
    path = save(file, tmp_path)

    data = {row["Name"]: row for row in convert_path(path)}

    assert nested_names(data["Cyclic"]["cost_items"]) == [("A", [("B", [])])]
    assert nested_names(data["Plain"]["cost_items"]) == [("Leaf", [])]


def test_self_nested_cost_item_is_emitted_once(tmp_path):
    file = fresh_file()
    schedule = add_schedule(file, "BoQ")
    item = add_root(file, schedule, "A")
    link(file, item, [item])
    path = save(file, tmp_path)
    file = ifcopenshell.open(str(path))
    schedule = entity_named(file, "IfcCostSchedule", "BoQ")

    data = convert_file(file, schedule)

    assert nested_names(data[0]["cost_items"]) == [("A", [])]


def test_three_item_cycle_stops_at_the_repeated_item(tmp_path):
    file = fresh_file()
    schedule = add_schedule(file, "BoQ")
    first = add_root(file, schedule, "A")
    second = add_child(file, first, "B")
    third = add_child(file, second, "C")
    link(file, third, [first])
    path = save(file, tmp_path)
    file = ifcopenshell.open(str(path))
    schedule = entity_named(file, "IfcCostSchedule", "BoQ")

    data = convert_file(file, schedule)

    assert nested_names(data[0]["cost_items"]) == [("A", [("B", [("C", [])])])]


def test_cycle_keeps_a_sibling_that_is_not_on_the_path(tmp_path):
    file = fresh_file()
    schedule = add_schedule(file, "BoQ")
    first = add_root(file, schedule, "A")
    second = add_child(file, first, "B")
    sibling = ifcopenshell.api.root.create_entity(file, ifc_class="IfcCostItem", name="C")
    link(file, second, [first, sibling])
    path = save(file, tmp_path)
    file = ifcopenshell.open(str(path))
    schedule = entity_named(file, "IfcCostSchedule", "BoQ")

    data = convert_file(file, schedule)

    assert nested_names(data[0]["cost_items"]) == [("A", [("B", [("C", [])])])]


def test_shared_descendant_is_exported_under_each_parent(tmp_path):
    file = fresh_file()
    schedule = add_schedule(file, "BoQ")
    root = add_root(file, schedule, "A")
    left = add_child(file, root, "B")
    right = add_child(file, root, "C")
    shared = ifcopenshell.api.root.create_entity(file, ifc_class="IfcCostItem", name="D")
    link(file, left, [shared])
    link(file, right, [shared])
    path = save(file, tmp_path)
    file = ifcopenshell.open(str(path))
    schedule = entity_named(file, "IfcCostSchedule", "BoQ")

    data = convert_file(file, schedule)

    assert nested_names(data[0]["cost_items"]) == [("A", [("B", [("D", [])]), ("C", [("D", [])])])]


def test_acyclic_nest_is_fully_exported(tmp_path):
    file = fresh_file()
    schedule = add_schedule(file, "BoQ")
    first = add_root(file, schedule, "A")
    second = add_child(file, first, "B")
    add_child(file, second, "C")
    path = save(file, tmp_path)
    file = ifcopenshell.open(str(path))
    schedule = entity_named(file, "IfcCostSchedule", "BoQ")

    data = convert_file(file, schedule)

    assert nested_names(data[0]["cost_items"]) == [("A", [("B", [("C", [])])])]


def test_summed_cycle_exports_a_finite_total(tmp_path):
    file = mutual_cycle()
    for item in file.by_type("IfcCostItem"):
        value = ifcopenshell.api.cost.add_cost_value(file, parent=item)
        value.Category = "*"
    path = save(file, tmp_path)
    file = ifcopenshell.open(str(path))
    schedule = entity_named(file, "IfcCostSchedule", "BoQ")

    data = convert_file(file, schedule)
    root = data[0]["cost_items"][0]
    child = root["IsNestedBy"][0]

    assert nested_names(data[0]["cost_items"]) == [("A", [("B", [])])]
    assert root["IsSum"] is True
    assert child["IsSum"] is True
    assert root["TotalAppliedValue"] is None
    assert child["TotalAppliedValue"] is None
    assert root["TotalCost"] == 0.0
    assert child["TotalCost"] == 0.0


def test_csv_writer_writes_each_cyclic_item_once(tmp_path):
    path = save(mutual_cycle(), tmp_path)
    file = ifcopenshell.open(str(path))
    schedule = entity_named(file, "IfcCostSchedule", "BoQ")
    output = tmp_path / "csv"
    ifc5d.ifc5Dspreadsheet.Ifc5DCsvWriter(file, str(output), cost_schedule=schedule).write()

    written = list(output.glob("*.csv"))
    assert len(written) == 1
    with written[0].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["Name"], row["Hierarchy"]) for row in rows] == [("A", "1"), ("B", "1.1")]


def test_schedule_cost_item_walk_is_finite(tmp_path):
    path = save(mutual_cycle(), tmp_path)
    file = ifcopenshell.open(str(path))
    schedule = entity_named(file, "IfcCostSchedule", "BoQ")
    root = entity_named(file, "IfcCostItem", "A")

    names = []
    for count, item in enumerate(ifcopenshell.util.cost.get_schedule_cost_items(schedule), start=1):
        names.append(item.Name)
        assert count <= 4
    deep = []
    for count, item in enumerate(ifcopenshell.util.cost.get_nested_cost_items(root, is_deep=True), start=1):
        deep.append(item.Name)
        assert count <= 4

    assert names == ["A", "B"]
    assert deep == ["B"]


def test_ifcquery_cost_exports_a_two_item_cycle(tmp_path):
    path = save(mutual_cycle(), tmp_path)
    file = ifcopenshell.open(str(path))

    result = cost(file)

    assert len(result) == 1
    root = result[0]["items"][0]
    assert root["name"] == "A"
    assert [item["name"] for item in root["subitems"]] == ["B"]
    assert root["subitems"][0]["subitems"] == []
