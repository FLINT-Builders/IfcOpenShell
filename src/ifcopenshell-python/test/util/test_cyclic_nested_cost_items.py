# This file was generated with the assistance of an AI coding tool.
# ruff: file-ignore[unsorted-imports]  # test.bootstrap must run before ifcopenshell is imported.
"""Cyclic IfcRelNests cost items must not exhaust the call stack.

A supplied IFC file can nest two cost items under a schedule so that each
appears in the other's IfcRelNests RelatedObjects. Listing that schedule, a
deep assignment query, a summed cost value, a CSV rate import, a spreadsheet
export, and an ifcquery cost listing all follow those nests with no visited
set. These tests fail while that recursion is present and pass once an item
already on the current path is skipped.

The expected tree is the depth-first nest walk that yields a child and then
its descendants, and that does not enter an id already on the path. A shared
child reached by two parents is still listed under each parent.

Not executed here, because importing them requires Blender: bonsai.tool.cost.Cost
.create_new_cost_item_li, load_cost_schedule_tree, load_schedule_of_rates_tree,
highlight_cost_item (expand_ancestors), create_cost_item_json, and the one-line
wrappers get_schedule_cost_items, get_cost_schedule_products, and get_cost_schedule.
Those wrappers call the library functions this file does execute. The tree and
ancestor helpers walk IfcRelNests themselves.

IFC2X3 IfcCostItem has no CostValues and no Nests inverse. Value summation and
get_cost_schedule are exercised on IFC4, where those attributes exist. Listing
is exercised on IFC2X3 as well, because get_components reads IsDecomposedBy there.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import test.bootstrap  # ruff: ignore[unused-import]  # drop the source tree from sys.path when it would hide the binary

import ifcopenshell
import ifcopenshell.api.control
import ifcopenshell.api.cost
import ifcopenshell.api.nest
import ifcopenshell.api.owner.settings
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.guid
import ifcopenshell.util.cost as subject

_REPO = Path(__file__).resolve().parents[4]
for _extra in (_REPO / "src" / "ifc5d", _REPO / "src" / "ifcquery"):
    _extra_s = str(_extra)
    if _extra_s not in sys.path:
        sys.path.insert(0, _extra_s)


def _install_owner_hooks() -> None:
    def get_user(ifc: ifcopenshell.file):
        user = next(iter(ifc.by_type("IfcPersonAndOrganization")), None)
        if user:
            return user
        person = ifc.create_entity("IfcPerson")
        organization = ifc.create_entity("IfcOrganization")
        return ifc.create_entity("IfcPersonAndOrganization", ThePerson=person, TheOrganization=organization)

    def get_application(ifc: ifcopenshell.file):
        application = next(iter(ifc.by_type("IfcApplication")), None)
        if application:
            return application
        return ifc.create_entity("IfcApplication")

    ifcopenshell.api.owner.settings.get_user = get_user
    ifcopenshell.api.owner.settings.get_application = get_application


def _descendant_ids(item: ifcopenshell.entity_instance) -> list[int]:
    """Ids a path-aware nest walk yields under ``item``, not including ``item``."""
    found: list[int] = []

    def walk(current: ifcopenshell.entity_instance, path: set[int]) -> None:
        for child in subject.get_nested_cost_items(current):
            ident = child.id()
            if ident in path:
                continue
            found.append(ident)
            walk(child, path | {ident})

    walk(item, {item.id()})
    return found


def _schedule_ids(schedule: ifcopenshell.entity_instance) -> list[int]:
    found: list[int] = []
    for root in subject.get_root_cost_items(schedule):
        found.append(root.id())
        found.extend(_descendant_ids(root))
    return found


def _ids(items) -> list[int]:
    return [item.id() for item in items]


def _shallow_ids(item: ifcopenshell.entity_instance) -> list[int]:
    return _ids(subject.get_nested_cost_items(item))


def _open_written(model: ifcopenshell.file, path: Path) -> ifcopenshell.file:
    model.write(str(path))
    return ifcopenshell.open(str(path))


def _named(model: ifcopenshell.file) -> dict[str, ifcopenshell.entity_instance]:
    return {item.Name: item for item in model.by_type("IfcCostItem")}


def _schedule(model: ifcopenshell.file) -> ifcopenshell.entity_instance:
    return model.by_type("IfcCostSchedule")[0]


def _mutual_cycle(schema: str, tmp_path: Path, *, both_roots: bool = False, with_product: bool = False):
    """Two cost items, each in the other's IfcRelNests.RelatedObjects.

    ``A`` is a schedule root. ``B`` is nested under ``A``. The cycle is closed
    by nesting ``A`` under ``B``. When ``both_roots`` is set, ``B`` is also
    assigned to the schedule, which is the shape in the reported attack.
    """
    _install_owner_hooks()
    model = ifcopenshell.api.project.create_file(version=schema)
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="Rates", predefined_type="SCHEDULEOFRATES")
    item_a = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=schedule)
    item_a.Name = "A"
    item_b = ifcopenshell.api.cost.add_cost_item(model, cost_item=item_a)
    item_b.Name = "B"
    # IFC2X3 IfcCostItem has no Identification attribute.
    if schema != "IFC2X3":
        item_a.Identification = "R1"
        item_b.Identification = "R2"
    if both_roots:
        ifcopenshell.api.control.assign_control(model, relating_control=schedule, related_objects=[item_b])
    if with_product:
        wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Wall")
        ifcopenshell.api.control.assign_control(model, relating_control=item_b, related_objects=[wall])
    ifcopenshell.api.nest.assign_object(model, related_objects=[item_a], relating_object=item_b)
    opened = _open_written(model, tmp_path / "mutual.ifc")
    items = _named(opened)
    # The cycle has to survive the parser. A walk that never sees it proves nothing.
    assert items["B"].id() in _shallow_ids(items["A"])
    assert items["A"].id() in _shallow_ids(items["B"])
    return opened, _schedule(opened), items


def _self_cycle(schema: str, tmp_path: Path):
    _install_owner_hooks()
    model = ifcopenshell.api.project.create_file(version=schema)
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="Rates")
    item_a = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=schedule)
    item_a.Name = "A"
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Wall")
    ifcopenshell.api.control.assign_control(model, relating_control=item_a, related_objects=[wall])
    ifcopenshell.api.nest.assign_object(model, related_objects=[item_a], relating_object=item_a)
    opened = _open_written(model, tmp_path / "self.ifc")
    items = _named(opened)
    assert items["A"].id() in _shallow_ids(items["A"])
    return opened, _schedule(opened), items


def _three_cycle(schema: str, tmp_path: Path):
    _install_owner_hooks()
    model = ifcopenshell.api.project.create_file(version=schema)
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="Rates")
    item_a = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=schedule)
    item_a.Name = "A"
    item_b = ifcopenshell.api.cost.add_cost_item(model, cost_item=item_a)
    item_b.Name = "B"
    item_c = ifcopenshell.api.cost.add_cost_item(model, cost_item=item_b)
    item_c.Name = "C"
    ifcopenshell.api.nest.assign_object(model, related_objects=[item_a], relating_object=item_c)
    opened = _open_written(model, tmp_path / "three.ifc")
    items = _named(opened)
    assert _shallow_ids(items["A"]) == [items["B"].id()]
    assert _shallow_ids(items["B"]) == [items["C"].id()]
    assert _shallow_ids(items["C"]) == [items["A"].id()]
    return opened, _schedule(opened), items


def _diamond(schema: str, tmp_path: Path):
    """A nests B and C; B and C both nest D. D has two parents, and there is no cycle."""
    _install_owner_hooks()
    model = ifcopenshell.api.project.create_file(version=schema)
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="Rates")
    item_a = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=schedule)
    item_a.Name = "A"
    item_b = ifcopenshell.api.cost.add_cost_item(model, cost_item=item_a)
    item_b.Name = "B"
    item_c = ifcopenshell.api.cost.add_cost_item(model, cost_item=item_a)
    item_c.Name = "C"
    item_d = ifcopenshell.api.cost.add_cost_item(model, cost_item=item_b)
    item_d.Name = "D"
    model.create_entity(
        "IfcRelNests",
        GlobalId=ifcopenshell.guid.new(),
        RelatingObject=item_c,
        RelatedObjects=[item_d],
    )
    opened = _open_written(model, tmp_path / "diamond.ifc")
    items = _named(opened)
    assert items["D"].id() in _shallow_ids(items["B"])
    assert items["D"].id() in _shallow_ids(items["C"])
    return opened, _schedule(opened), items


def _chain(schema: str, tmp_path: Path):
    _install_owner_hooks()
    model = ifcopenshell.api.project.create_file(version=schema)
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="Rates")
    item_a = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=schedule)
    item_a.Name = "A"
    item_b = ifcopenshell.api.cost.add_cost_item(model, cost_item=item_a)
    item_b.Name = "B"
    item_c = ifcopenshell.api.cost.add_cost_item(model, cost_item=item_b)
    item_c.Name = "C"
    opened = _open_written(model, tmp_path / "chain.ifc")
    return opened, _schedule(opened), _named(opened)


def _sum_cycle(schema: str, tmp_path: Path):
    """A and B sum their children. B also nests C, whose value is 5, and nests A."""
    _install_owner_hooks()
    model = ifcopenshell.api.project.create_file(version=schema)
    schedule = ifcopenshell.api.cost.add_cost_schedule(model, name="Rates")
    item_a = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=schedule)
    item_a.Name = "A"
    item_b = ifcopenshell.api.cost.add_cost_item(model, cost_item=item_a)
    item_b.Name = "B"
    item_c = ifcopenshell.api.cost.add_cost_item(model, cost_item=item_b)
    item_c.Name = "C"
    ifcopenshell.api.nest.assign_object(model, related_objects=[item_a], relating_object=item_b)
    value_a = ifcopenshell.api.cost.add_cost_value(model, parent=item_a)
    value_b = ifcopenshell.api.cost.add_cost_value(model, parent=item_b)
    value_c = ifcopenshell.api.cost.add_cost_value(model, parent=item_c)
    ifcopenshell.api.cost.edit_cost_value(model, cost_value=value_a, attributes={"Category": "*"})
    ifcopenshell.api.cost.edit_cost_value(model, cost_value=value_b, attributes={"Category": "*"})
    ifcopenshell.api.cost.edit_cost_value(model, cost_value=value_c, attributes={"AppliedValue": 5.0})
    opened = _open_written(model, tmp_path / "sum.ifc")
    items = _named(opened)
    assert items["A"].id() in _shallow_ids(items["B"])
    return opened, _schedule(opened), items


def _unassigned_cycle(schema: str, tmp_path: Path):
    _install_owner_hooks()
    model = ifcopenshell.api.project.create_file(version=schema)
    item_a = ifcopenshell.api.root.create_entity(model, ifc_class="IfcCostItem", name="A")
    item_b = ifcopenshell.api.root.create_entity(model, ifc_class="IfcCostItem", name="B")
    ifcopenshell.api.nest.assign_object(model, related_objects=[item_b], relating_object=item_a)
    ifcopenshell.api.nest.assign_object(model, related_objects=[item_a], relating_object=item_b)
    opened = _open_written(model, tmp_path / "unassigned.ifc")
    items = _named(opened)
    assert items["B"].id() in _shallow_ids(items["A"])
    assert items["A"].id() in _shallow_ids(items["B"])
    return opened, items


def _assert_listing(schedule, items, root_name: str) -> None:
    root = items[root_name]
    assert _ids(subject.get_all_nested_cost_items(root)) == _descendant_ids(root)
    assert _ids(subject.get_nested_cost_items(root, is_deep=True)) == _descendant_ids(root)
    assert _ids(subject.get_schedule_cost_items(schedule)) == _schedule_ids(schedule)


SCHEMAS = ["IFC4", "IFC2X3"]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_mutual_cycle_listing_stays_on_the_path(schema, tmp_path):
    _model, schedule, items = _mutual_cycle(schema, tmp_path)
    _assert_listing(schedule, items, "A")
    assert _descendant_ids(items["A"]) == [items["B"].id()]
    assert _schedule_ids(schedule) == [items["A"].id(), items["B"].id()]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_both_schedule_roots_in_each_others_nests(schema, tmp_path):
    _model, schedule, items = _mutual_cycle(schema, tmp_path, both_roots=True)
    _assert_listing(schedule, items, "A")
    assert _schedule_ids(schedule) == [
        items["A"].id(),
        items["B"].id(),
        items["B"].id(),
        items["A"].id(),
    ]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_self_nested_cost_item_is_listed_once(schema, tmp_path):
    model, schedule, items = _self_cycle(schema, tmp_path)
    _assert_listing(schedule, items, "A")
    wall = model.by_type("IfcWall")[0]
    assert _descendant_ids(items["A"]) == []
    assert _ids(subject.get_cost_item_assignments(items["A"], is_deep=True)) == [wall.id()]
    assert _ids(subject.get_cost_item_assignments(items["A"], filter_by_type="PRODUCT", is_deep=True)) == [wall.id()]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_three_item_cycle_listing_stops_at_the_start(schema, tmp_path):
    _model, schedule, items = _three_cycle(schema, tmp_path)
    _assert_listing(schedule, items, "A")
    assert _descendant_ids(items["A"]) == [items["B"].id(), items["C"].id()]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_deep_assignments_include_the_nested_product_once(schema, tmp_path):
    model, _schedule, items = _mutual_cycle(schema, tmp_path, with_product=True)
    wall = model.by_type("IfcWall")[0]
    assert _ids(subject.get_cost_item_assignments(items["A"], is_deep=False)) == []
    assert _ids(subject.get_cost_item_assignments(items["A"], is_deep=True)) == [wall.id()]
    assert _ids(subject.get_cost_item_assignments(items["A"], filter_by_type="PRODUCT", is_deep=True)) == [wall.id()]
    assert _ids(subject.get_cost_item_assignments(items["B"], filter_by_type="PRODUCT", is_deep=True)) == [wall.id()]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_shared_child_is_listed_under_each_parent(schema, tmp_path):
    _model, schedule, items = _diamond(schema, tmp_path)
    _assert_listing(schedule, items, "A")
    assert _descendant_ids(items["A"]) == [
        items["B"].id(),
        items["D"].id(),
        items["C"].id(),
        items["D"].id(),
    ]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_acyclic_chain_is_listed_in_full(schema, tmp_path):
    _model, schedule, items = _chain(schema, tmp_path)
    _assert_listing(schedule, items, "A")
    assert _schedule_ids(schedule) == [items["A"].id(), items["B"].id(), items["C"].id()]


def test_summed_values_stop_when_the_path_repeats(tmp_path):
    # IFC2X3 IfcCostItem has no CostValues, and IfcCostValue has no Category.
    # calculate_applied_value reads those IFC4 attributes directly.
    _model, _schedule, items = _sum_cycle("IFC4", tmp_path)
    # C contributes 5. Walking back into A or B, which are already on the path, adds nothing.
    assert subject.calculate_applied_value(items["A"], items["A"].CostValues[0]) == 5.0
    assert subject.calculate_applied_value(items["B"], items["B"].CostValues[0]) == 5.0
    assert subject.get_cost_values(items["A"])[0]["label"].startswith("5.00")


def test_schedule_lookup_stops_on_a_nest_cycle_with_no_schedule(tmp_path):
    # IFC2X3 exposes the parent link as Decomposes, and get_cost_schedule reads Nests,
    # so this upward walk is not reached on IFC2X3.
    _model, items = _unassigned_cycle("IFC4", tmp_path)
    assert subject.get_cost_schedule(items["A"]) is None
    assert subject.get_cost_schedule(items["B"]) is None


def test_schedule_lookup_finds_the_assigned_schedule_through_a_cycle(tmp_path):
    _model, schedule, items = _mutual_cycle("IFC4", tmp_path)
    assert subject.get_cost_schedule(items["A"]) == schedule
    assert subject.get_cost_schedule(items["B"]) == schedule


def test_csv_rate_import_lists_the_cyclic_rate_schedule(tmp_path):
    model, _schedule, items = _mutual_cycle("IFC4", tmp_path)
    csv_path = tmp_path / "boq.csv"
    csv_path.write_text(
        "Index,Name,Unit,Identification,Value,RateSchedule,RateID\n1,Imported,m,W1,10,Rates,R1\n",
        encoding="utf-8",
    )
    from ifc5d.csv2ifc import Csv2Ifc

    Csv2Ifc(str(csv_path), model, is_schedule_of_rates=False).execute()
    imported = next(item for item in model.by_type("IfcCostItem") if item.Name == "Imported")
    assigned = [
        rel.RelatingControl
        for rel in imported.HasAssignments or []
        if rel.is_a("IfcRelAssignsToControl") and rel.RelatingControl.is_a("IfcCostItem")
    ]
    assert any(control.Identification == "R1" and control.id() == items["A"].id() for control in assigned)


def test_spreadsheet_schedule_rows_stop_on_the_cycle(tmp_path):
    model, schedule, items = _mutual_cycle("IFC4", tmp_path)
    from ifc5d.ifc5Dspreadsheet import IfcDataGetter

    rows = IfcDataGetter.get_schedule_cost_items_data(model, schedule)
    assert [row["Id"] for row in rows] == [items["A"].id(), items["B"].id()]
    assert [row["Hierarchy"] for row in rows] == ["1", "1.1"]


def test_json_export_stops_on_the_cycle(tmp_path):
    _model, _schedule, items = _mutual_cycle("IFC4", tmp_path)
    from ifc5d.ifc2json import ifc5D2json

    converter = ifc5D2json()
    converter.file_path = str(tmp_path / "mutual.ifc")
    data = converter.convert_ifc_to_json()
    tree = data[0]["cost_items"]
    assert [item["id"] for item in tree] == [items["A"].id()]
    assert [child["id"] for child in tree[0]["IsNestedBy"]] == [items["B"].id()]
    assert tree[0]["IsNestedBy"][0]["IsNestedBy"] == []


def test_ifcquery_cost_listing_stops_on_the_cycle(tmp_path):
    model, schedule, items = _mutual_cycle("IFC4", tmp_path)
    from ifcquery.cost import cost

    listed = cost(model)
    assert listed[0]["id"] == schedule.id()
    roots = listed[0]["items"]
    assert [item["id"] for item in roots] == [items["A"].id()]
    assert [child["id"] for child in roots[0]["subitems"]] == [items["B"].id()]
    assert roots[0]["subitems"][0]["subitems"] == []
