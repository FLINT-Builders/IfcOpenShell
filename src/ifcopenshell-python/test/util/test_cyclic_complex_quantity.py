# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
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

"""Quantity-set walks must tolerate cyclic IfcPhysicalComplexQuantity graphs.

`get_quantities` and `get_quantity` recurse through `HasQuantities`. A cycle
(a quantity that lists itself, or two or more quantities that list each other)
must not raise RecursionError. A repeated quantity is skipped only when its id
is already on the active path. Siblings are still returned, and a quantity
reached by two parents that are not nested inside each other is expanded under
both parents.

These tests open a written IFC file. Parsing does not run EXPRESS rules, and
`NoSelfReference` only rejects a quantity that contains itself, so a two-node
cycle arrives at the walk intact.
"""

import pytest

import ifcopenshell
import ifcopenshell.api.owner.settings
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.guid
import ifcopenshell.util.cost as cost
import ifcopenshell.util.element as element
import ifcopenshell.util.selector as selector
from ifcopenshell.express.rules.IFC2X3 import IfcPhysicalComplexQuantity_WR21
from ifcopenshell.express.rules.IFC4 import IfcPhysicalComplexQuantity_NoSelfReference

SCHEMAS = ["IFC4", "IFC2X3"]


@pytest.fixture(autouse=True)
def _owner_settings():
    ifcopenshell.api.owner.settings.get_user = lambda ifc: (ifc.by_type("IfcPersonAndOrganization") or [None])[0]
    ifcopenshell.api.owner.settings.get_application = lambda ifc: (ifc.by_type("IfcApplication") or [None])[0]
    ifcopenshell.api.pre_listeners = {}
    ifcopenshell.api.post_listeners = {}


def new_file(schema):
    if schema == "IFC4":
        return ifcopenshell.api.project.create_file()
    return ifcopenshell.api.project.create_file(version=schema)


def write_and_open(ifc_file, tmp_path, name):
    path = tmp_path / name
    ifc_file.write(path)
    return ifcopenshell.open(path)


def length_quantity(ifc_file, name, value):
    return ifc_file.create_entity("IfcQuantityLength", Name=name, LengthValue=value)


def complex_quantity(ifc_file, name, quantities, discrimination="cycle"):
    return ifc_file.create_entity(
        "IfcPhysicalComplexQuantity",
        Name=name,
        Discrimination=discrimination,
        HasQuantities=quantities,
    )


def assign_qto(ifc_file, product, name, quantities):
    qto = ifc_file.create_entity(
        "IfcElementQuantity",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        Quantities=quantities,
    )
    if product.is_a("IfcTypeObject"):
        product.HasPropertySets = list(product.HasPropertySets or []) + [qto]
    else:
        ifc_file.create_entity(
            "IfcRelDefinesByProperties",
            GlobalId=ifcopenshell.guid.new(),
            RelatedObjects=[product],
            RelatingPropertyDefinition=qto,
        )
    return qto


def by_name(ifc_file, ifc_class, name):
    found = [inst for inst in ifc_file.by_type(ifc_class) if inst.Name == name]
    assert len(found) == 1
    return found[0]


def complex_dict(quantity, properties):
    return {
        "id": quantity.id(),
        "type": quantity.is_a(),
        "Discrimination": quantity.Discrimination,
        "properties": properties,
    }


def verbose_simple(quantity, value):
    return {"id": quantity.id(), "class": quantity.is_a(), "value": value}


def verbose_complex(quantity, properties):
    data = complex_dict(quantity, properties)
    return {"id": quantity.id(), "class": quantity.is_a(), "value": data}


def test_two_node_cycle_is_not_rejected_by_no_self_reference_rule(tmp_path):
    """The EXPRESS rule cited for this entity compares a quantity with itself only."""
    ifc_file = new_file("IFC4")
    width = length_quantity(ifc_file, "Width", 1.5)
    height = length_quantity(ifc_file, "Height", 2.5)
    other = complex_quantity(ifc_file, "B", [width])
    current = complex_quantity(ifc_file, "A", [other, height])
    other.HasQuantities = [current, width]
    self_ref = complex_quantity(ifc_file, "Self", [width])
    self_ref.HasQuantities = [self_ref, width]
    opened = write_and_open(ifc_file, tmp_path, "rule.ifc")
    left = by_name(opened, "IfcPhysicalComplexQuantity", "A")
    right = by_name(opened, "IfcPhysicalComplexQuantity", "B")
    assert right in left.HasQuantities
    assert left in right.HasQuantities
    IfcPhysicalComplexQuantity_NoSelfReference.__call__(left)
    IfcPhysicalComplexQuantity_NoSelfReference.__call__(right)
    with pytest.raises(AssertionError):
        IfcPhysicalComplexQuantity_NoSelfReference.__call__(by_name(opened, "IfcPhysicalComplexQuantity", "Self"))


@pytest.mark.parametrize("schema", SCHEMAS)
def test_mutual_cycle_quantities_expand_without_recursion(schema, tmp_path):
    ifc_file = new_file(schema)
    wall = ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcWall", name="Cyclic wall")
    width = length_quantity(ifc_file, "Width", 1.5)
    height = length_quantity(ifc_file, "Height", 2.5)
    area = ifc_file.create_entity("IfcQuantityArea", Name="NetArea", AreaValue=5.0)
    other = complex_quantity(ifc_file, "B", [width])
    current = complex_quantity(ifc_file, "A", [other, width])
    other.HasQuantities = [current, height]
    assign_qto(ifc_file, wall, "Qto_Cyclic", [current, other, area])

    opened = write_and_open(ifc_file, tmp_path, f"{schema}-mutual.ifc")
    wall = by_name(opened, "IfcWall", "Cyclic wall")
    qto = wall.IsDefinedBy[0].RelatingPropertyDefinition
    current = by_name(opened, "IfcPhysicalComplexQuantity", "A")
    other = by_name(opened, "IfcPhysicalComplexQuantity", "B")
    width = by_name(opened, "IfcQuantityLength", "Width")
    height = by_name(opened, "IfcQuantityLength", "Height")
    area = by_name(opened, "IfcQuantityArea", "NetArea")
    assert other in current.HasQuantities and current in other.HasQuantities

    expected = {
        "A": complex_dict(current, {"B": complex_dict(other, {"Height": 2.5}), "Width": 1.5}),
        "B": complex_dict(other, {"A": complex_dict(current, {"Width": 1.5}), "Height": 2.5}),
        "NetArea": 5.0,
    }
    assert element.get_quantities(qto.Quantities) == expected
    assert element.get_quantity(qto.Quantities, "A") == expected["A"]
    assert element.get_quantity(qto.Quantities, "NetArea") == 5.0
    assert element.get_property_definition(qto) == {**expected, "id": qto.id()}
    assert element.get_property_definition(qto, "A") == expected["A"]
    assert element.get_property_definition(qto, "NetArea") == 5.0

    qto_result = {**expected, "id": qto.id()}
    assert element.get_psets(wall) == {"Qto_Cyclic": qto_result}
    assert element.get_psets(wall, qtos_only=True) == {"Qto_Cyclic": qto_result}
    assert element.get_psets(wall, psets_only=True) == {}
    assert element.get_pset(wall, "Qto_Cyclic") == qto_result
    assert element.get_pset(wall, "Qto_Cyclic", "A") == expected["A"]
    assert element.get_pset(wall, "Qto_Cyclic", qtos_only=True) == qto_result
    assert element.get_pset(wall, "Qto_Cyclic", "Width", qtos_only=True) is None
    assert element.has_property(wall, "A") is True
    assert element.has_property(wall, "NetArea") is True
    assert set(cost.get_product_quantity_names([wall])) == {"A", "B", "NetArea"}
    assert selector.get_element_value(wall, "Qto_Cyclic.A.Width") == 1.5
    assert selector.get_element_value(wall, "Qto_Cyclic.A.B.Height") == 2.5
    assert selector.get_element_value(wall, "Qto_Cyclic.B.A.Width") == 1.5
    assert selector.get_element_value(wall, "Qto_Cyclic.A.B.A") is None
    assert selector.filter_elements(opened, "IfcWall, Qto_Cyclic.A.Width=1.5") == {wall}

    verbose_expected = {
        "A": verbose_complex(
            current,
            {
                "B": verbose_complex(other, {"Height": verbose_simple(height, 2.5)}),
                "Width": verbose_simple(width, 1.5),
            },
        ),
        "B": verbose_complex(
            other,
            {
                "A": verbose_complex(current, {"Width": verbose_simple(width, 1.5)}),
                "Height": verbose_simple(height, 2.5),
            },
        ),
        "NetArea": verbose_simple(area, 5.0),
    }
    assert element.get_quantities(qto.Quantities, verbose=True) == verbose_expected
    assert element.get_quantity(qto.Quantities, "A", verbose=True) == verbose_expected["A"]
    # Bonsai's quantity panel and cost-quantity list call get_psets this way.
    assert element.get_psets(wall, qtos_only=True, should_inherit=False, verbose=True) == {
        "Qto_Cyclic": {**verbose_expected, "id": qto.id()}
    }


@pytest.mark.parametrize("schema", SCHEMAS)
def test_self_and_three_node_cycles_skip_only_the_repeated_quantity(schema, tmp_path):
    ifc_file = new_file(schema)
    wall = ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcWall", name="Self wall")
    task = ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcTask", name="Cyclic task")
    width = length_quantity(ifc_file, "Width", 1.5)
    self_ref = complex_quantity(ifc_file, "Self", [width], discrimination="self")
    self_ref.HasQuantities = [self_ref, width]
    assign_qto(ifc_file, wall, "Qto_Self", [self_ref])

    height = length_quantity(ifc_file, "Height", 2.5)
    depth = length_quantity(ifc_file, "Depth", 3.5)
    third = complex_quantity(ifc_file, "C", [depth])
    second = complex_quantity(ifc_file, "B", [third, height])
    first = complex_quantity(ifc_file, "A", [second, width])
    third.HasQuantities = [first, depth]
    assign_qto(ifc_file, task, "Qto_Three", [first, second, third])

    opened = write_and_open(ifc_file, tmp_path, f"{schema}-cycles.ifc")
    wall = by_name(opened, "IfcWall", "Self wall")
    self_ref = by_name(opened, "IfcPhysicalComplexQuantity", "Self")
    assert self_ref in self_ref.HasQuantities
    self_expected = {"Self": complex_dict(self_ref, {"Width": 1.5})}
    qto = wall.IsDefinedBy[0].RelatingPropertyDefinition
    assert element.get_quantities(qto.Quantities) == self_expected
    assert element.get_psets(wall, qtos_only=True)["Qto_Self"]["Self"] == self_expected["Self"]
    rule = IfcPhysicalComplexQuantity_WR21 if schema == "IFC2X3" else IfcPhysicalComplexQuantity_NoSelfReference
    with pytest.raises(AssertionError):
        rule.__call__(self_ref)

    task = by_name(opened, "IfcTask", "Cyclic task")
    first = by_name(opened, "IfcPhysicalComplexQuantity", "A")
    second = by_name(opened, "IfcPhysicalComplexQuantity", "B")
    third = by_name(opened, "IfcPhysicalComplexQuantity", "C")
    assert first in third.HasQuantities and second in first.HasQuantities and third in second.HasQuantities
    three_expected = {
        "A": complex_dict(
            first,
            {
                "B": complex_dict(second, {"C": complex_dict(third, {"Depth": 3.5}), "Height": 2.5}),
                "Width": 1.5,
            },
        ),
        "B": complex_dict(
            second,
            {
                "C": complex_dict(third, {"A": complex_dict(first, {"Width": 1.5}), "Depth": 3.5}),
                "Height": 2.5,
            },
        ),
        "C": complex_dict(
            third,
            {
                "A": complex_dict(first, {"B": complex_dict(second, {"Height": 2.5}), "Width": 1.5}),
                "Depth": 3.5,
            },
        ),
    }
    qto = task.IsDefinedBy[0].RelatingPropertyDefinition
    assert element.get_quantities(qto.Quantities) == three_expected
    assert element.get_psets(task, qtos_only=True)["Qto_Three"]["C"]["properties"]["Depth"] == 3.5
    assert set(cost.get_product_quantity_names([task])) == {"A", "B", "C"}
    assert selector.get_element_value(task, "Qto_Three.A.B.C.Depth") == 3.5
    assert selector.get_element_value(task, "Qto_Three.A.B.C.A") is None
    assert "A" not in three_expected["A"]["properties"]["B"]["properties"]["C"]["properties"]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_type_quantity_set_cycle_uses_the_same_walk(schema, tmp_path):
    ifc_file = new_file(schema)
    wall_type = ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcWallType", name="Cyclic type")
    width = length_quantity(ifc_file, "Width", 4.0)
    other = complex_quantity(ifc_file, "B", [])
    current = complex_quantity(ifc_file, "A", [other, width])
    other.HasQuantities = [current]
    assign_qto(ifc_file, wall_type, "Qto_Type", [current])
    opened = write_and_open(ifc_file, tmp_path, f"{schema}-type.ifc")
    wall_type = by_name(opened, "IfcWallType", "Cyclic type")
    current = by_name(opened, "IfcPhysicalComplexQuantity", "A")
    other = by_name(opened, "IfcPhysicalComplexQuantity", "B")
    expected = {
        "A": complex_dict(current, {"B": complex_dict(other, {}), "Width": 4.0}),
    }
    assert element.get_psets(wall_type, qtos_only=True)["Qto_Type"]["A"] == expected["A"]
    assert element.get_pset(wall_type, "Qto_Type", "A", qtos_only=True) == expected["A"]


@pytest.mark.parametrize("schema", SCHEMAS)
def test_acyclic_nesting_and_shared_complex_children_still_expand(schema, tmp_path):
    ifc_file = new_file(schema)
    wall = ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcWall", name="Acyclic wall")
    width = length_quantity(ifc_file, "Width", 1.5)
    height = length_quantity(ifc_file, "Height", 2.5)
    depth = length_quantity(ifc_file, "Depth", 3.5)
    inner = complex_quantity(ifc_file, "Inner", [height], discrimination="layer")
    mid = complex_quantity(ifc_file, "Mid", [inner, depth], discrimination="layer")
    outer = complex_quantity(ifc_file, "Outer", [mid, width], discrimination="layer")
    shared = complex_quantity(ifc_file, "Shared", [depth], discrimination="layer")
    left = complex_quantity(ifc_file, "Left", [shared], discrimination="layer")
    right = complex_quantity(ifc_file, "Right", [shared], discrimination="layer")
    parent = complex_quantity(ifc_file, "Parent", [left, right], discrimination="layer")
    assign_qto(ifc_file, wall, "Qto_Layers", [outer, parent])

    opened = write_and_open(ifc_file, tmp_path, f"{schema}-acyclic.ifc")
    wall = by_name(opened, "IfcWall", "Acyclic wall")
    outer = by_name(opened, "IfcPhysicalComplexQuantity", "Outer")
    mid = by_name(opened, "IfcPhysicalComplexQuantity", "Mid")
    inner = by_name(opened, "IfcPhysicalComplexQuantity", "Inner")
    parent = by_name(opened, "IfcPhysicalComplexQuantity", "Parent")
    left = by_name(opened, "IfcPhysicalComplexQuantity", "Left")
    right = by_name(opened, "IfcPhysicalComplexQuantity", "Right")
    shared = by_name(opened, "IfcPhysicalComplexQuantity", "Shared")
    qto = wall.IsDefinedBy[0].RelatingPropertyDefinition
    result = element.get_quantities(qto.Quantities)
    assert result["Outer"] == complex_dict(
        outer,
        {
            "Mid": complex_dict(mid, {"Inner": complex_dict(inner, {"Height": 2.5}), "Depth": 3.5}),
            "Width": 1.5,
        },
    )
    shared_dict = complex_dict(shared, {"Depth": 3.5})
    assert result["Parent"] == complex_dict(
        parent,
        {
            "Left": complex_dict(left, {"Shared": shared_dict}),
            "Right": complex_dict(right, {"Shared": shared_dict}),
        },
    )
    assert result["Parent"]["properties"]["Left"]["properties"]["Shared"]["id"] == shared.id()
    assert result["Parent"]["properties"]["Right"]["properties"]["Shared"]["id"] == shared.id()
    assert selector.get_element_value(wall, "Qto_Layers.Outer.Mid.Inner.Height") == 2.5
    assert selector.get_element_value(wall, "Qto_Layers.Parent.Right.Shared.Depth") == 3.5
