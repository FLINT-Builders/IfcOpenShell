# This file was generated with the assistance of an AI coding tool.
# IfcTester - IDS based model auditing
# Copyright (C) 2021-2022 Thomas Krijnen <thomas@aecgeeks.com>, Dion Moult <dion@thinkmoult.com>
#
# This file is part of IfcTester.
#
# IfcTester is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcTester is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcTester.  If not, see <http://www.gnu.org/licenses/>.

"""Nested IDS restriction patterns must not stall an audit.

A pattern such as one-or-more "a", repeated, and then a final "b" is legal in
an IDS restriction. These tests load that pattern through the same parsers the
command-line checker and the web worker use, then audit a model whose compared
string is a few dozen "a" characters. The audit has to finish quickly. Finishing
with a non-match is required, and rejecting the pattern or the match is also
accepted. While the matcher backtracks without a bound, the audit does not
return and the test fails.

Not covered here, because this input cannot reach a long match there:

- Entity, attribute, and part-of names are schema identifiers. The strings
  compared with those restrictions are class and attribute names, not the
  model value.
- Numeric property values never reach the matcher. A pattern restriction
  returns before compilation when the other value is not a string.
- Enumerated properties and string columns of table properties use the same
  list comparison as the list-value test.
"""

from __future__ import annotations

import importlib.util
import multiprocessing
import os
import tempfile
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.classification
import ifcopenshell.api.feature
import ifcopenshell.api.group
import ifcopenshell.api.material
import ifcopenshell.api.nest
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import pytest

from ifctester import ids
from ifctester.facet import Attribute, Entity, Material, PartOf, Property, Restriction

# Doubling time measured on this pattern is about one extra character per
# doubling. Thirty characters is past two seconds. A linear match is not.
ATTACK_LENGTH = 30
LIMIT_SECONDS = 2.0
BENIGN_PATTERN = "a+b"
BENIGN_VALUE = "ab"
ATTACK_PATTERN = "(a+)+b"
ATTACK_VALUE = "a" * ATTACK_LENGTH

# requirement: the element stays applicable and the requirement records a failure.
# applicability: the facet rejects the element, so nothing is applicable.
REQUIREMENT = "requirement"
APPLICABILITY = "applicability"

SCENARIOS = {
    "cli_open_attribute_value": REQUIREMENT,
    "web_attribute_value": REQUIREMENT,
    "attribute_applicability": APPLICABILITY,
    "property_value": REQUIREMENT,
    "property_list_value": REQUIREMENT,
    "property_set_name": REQUIREMENT,
    "property_base_name": REQUIREMENT,
    "classification_value": REQUIREMENT,
    "classification_system": REQUIREMENT,
    "material_name": REQUIREMENT,
    "entity_predefined_type": REQUIREMENT,
    "partof_parent": REQUIREMENT,
    "partof_aggregate": REQUIREMENT,
    "partof_group": REQUIREMENT,
    "partof_container": REQUIREMENT,
    "partof_nest": REQUIREMENT,
    "partof_opening": REQUIREMENT,
    "partof_filling": REQUIREMENT,
}


def _restriction(pattern: str) -> Restriction:
    return Restriction(options={"pattern": pattern})


def _specs(scenario: str, pattern: str) -> ids.Ids:
    restriction = _restriction(pattern)
    specs = ids.Ids(title="Pattern")
    spec = ids.Specification(name="Pattern")
    if scenario in ("cli_open_attribute_value", "web_attribute_value"):
        spec.applicability.append(Entity(name="IFCWALL"))
        spec.requirements.append(Attribute(name="Name", value=restriction))
    elif scenario == "attribute_applicability":
        spec.applicability.append(Entity(name="IFCWALL"))
        spec.applicability.append(Attribute(name="Name", value=restriction))
        spec.requirements.append(Attribute(name="Name"))
    elif scenario in ("property_value", "property_list_value"):
        spec.applicability.append(Entity(name="IFCWALL"))
        spec.requirements.append(Property(propertySet="Pset", baseName="Foo", value=restriction))
    elif scenario == "property_set_name":
        spec.applicability.append(Entity(name="IFCWALL"))
        spec.requirements.append(Property(propertySet=restriction, baseName="Foo"))
    elif scenario == "property_base_name":
        spec.applicability.append(Entity(name="IFCWALL"))
        spec.requirements.append(Property(propertySet="Pset", baseName=restriction))
    elif scenario == "classification_value":
        spec.applicability.append(Entity(name="IFCWALL"))
        spec.requirements.append(ids.Classification(system="System", value=restriction))
    elif scenario == "classification_system":
        spec.applicability.append(Entity(name="IFCWALL"))
        spec.requirements.append(ids.Classification(system=restriction))
    elif scenario == "material_name":
        spec.applicability.append(Entity(name="IFCWALL"))
        spec.requirements.append(Material(value=restriction))
    elif scenario == "entity_predefined_type":
        spec.applicability.append(Entity(name="IFCWALL"))
        spec.requirements.append(Entity(name="IFCWALL", predefinedType=restriction))
    elif scenario == "partof_parent":
        spec.applicability.append(Entity(name="IFCWALL"))
        spec.requirements.append(PartOf(name="IFCSPACE", predefinedType=restriction))
    elif scenario == "partof_aggregate":
        spec.applicability.append(Entity(name="IFCBEAM"))
        spec.requirements.append(
            PartOf(name="IFCELEMENTASSEMBLY", predefinedType=restriction, relation="IFCRELAGGREGATES")
        )
    elif scenario == "partof_group":
        spec.applicability.append(Entity(name="IFCELEMENTASSEMBLY"))
        spec.requirements.append(
            PartOf(name="IFCINVENTORY", predefinedType=restriction, relation="IFCRELASSIGNSTOGROUP")
        )
    elif scenario == "partof_container":
        spec.applicability.append(Entity(name="IFCELEMENTASSEMBLY"))
        spec.requirements.append(
            PartOf(
                name="IFCSPACE",
                predefinedType=restriction,
                relation="IFCRELCONTAINEDINSPATIALSTRUCTURE",
            )
        )
    elif scenario == "partof_nest":
        spec.applicability.append(Entity(name="IFCDISCRETEACCESSORY"))
        spec.requirements.append(PartOf(name="IFCFURNITURE", predefinedType=restriction, relation="IFCRELNESTS"))
    elif scenario == "partof_opening":
        spec.applicability.append(Entity(name="IFCOPENINGELEMENT"))
        spec.requirements.append(
            PartOf(
                name="IFCWALL",
                predefinedType=restriction,
                relation="IFCRELVOIDSELEMENT IFCRELFILLSELEMENT",
            )
        )
    elif scenario == "partof_filling":
        spec.applicability.append(Entity(name="IFCWINDOW"))
        spec.requirements.append(
            PartOf(
                name="IFCWALL",
                predefinedType=restriction,
                relation="IFCRELVOIDSELEMENT IFCRELFILLSELEMENT",
            )
        )
    else:
        raise AssertionError(scenario)
    specs.specifications.append(spec)
    return specs


def _web_api():
    path = Path(__file__).resolve().parents[1] / "webapp" / "public" / "worker" / "api.py"
    spec = importlib.util.spec_from_file_location("ifctester_web_worker_api", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load(scenario: str, pattern: str) -> ids.Ids:
    xml = _specs(scenario, pattern).to_string()
    if scenario == "cli_open_attribute_value":
        fd, name = tempfile.mkstemp(suffix=".ids")
        os.close(fd)
        try:
            Path(name).write_text(xml)
            return ids.open(name)
        finally:
            os.unlink(name)
    if scenario == "web_attribute_value":
        # The worker calls this with validate=True. The flag is unused; decode still loads the pattern.
        return _web_api().ids_from_xml_string(xml, True)
    return ids.from_string(xml)


def _new_file() -> ifcopenshell.file:
    ifc = ifcopenshell.file()
    ifc.createIfcProject()
    unit = ifcopenshell.api.unit.add_si_unit(ifc, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(ifc, units=[unit])
    return ifc


def _assign_free_type(element, value: str) -> None:
    try:
        element.PredefinedType = "USERDEFINED"
    except RuntimeError:
        pass
    element.ObjectType = value


def _model(scenario: str, value: str) -> ifcopenshell.file:
    ifc = _new_file()
    if scenario in ("cli_open_attribute_value", "web_attribute_value", "attribute_applicability"):
        wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        wall.Name = value
        return ifc
    if scenario == "property_value":
        wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        pset = ifcopenshell.api.pset.add_pset(ifc, product=wall, name="Pset")
        ifcopenshell.api.pset.edit_pset(ifc, pset=pset, properties={"Foo": value})
        return ifc
    if scenario == "property_list_value":
        wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        pset = ifcopenshell.api.pset.add_pset(ifc, product=wall, name="Pset")
        pset.HasProperties = [ifc.createIfcPropertyListValue(Name="Foo", ListValues=[ifc.createIfcLabel(value)])]
        return ifc
    if scenario == "property_set_name":
        wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        pset = ifcopenshell.api.pset.add_pset(ifc, product=wall, name=value)
        ifcopenshell.api.pset.edit_pset(ifc, pset=pset, properties={"Foo": "Bar"})
        return ifc
    if scenario == "property_base_name":
        wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        pset = ifcopenshell.api.pset.add_pset(ifc, product=wall, name="Pset")
        ifcopenshell.api.pset.edit_pset(ifc, pset=pset, properties={value: "Bar"})
        return ifc
    if scenario == "classification_value":
        library = ifcopenshell.file()
        system = library.createIfcClassification(Name="System")
        reference = library.createIfcClassificationReference(Identification=value, ReferencedSource=system)
        copied = ifcopenshell.api.classification.add_classification(ifc, classification=system)
        wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        ifcopenshell.api.classification.add_reference(ifc, products=[wall], reference=reference, classification=copied)
        return ifc
    if scenario == "classification_system":
        library = ifcopenshell.file()
        system = library.createIfcClassification(Name=value)
        reference = library.createIfcClassificationReference(Identification="X", ReferencedSource=system)
        copied = ifcopenshell.api.classification.add_classification(ifc, classification=system)
        wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        ifcopenshell.api.classification.add_reference(ifc, products=[wall], reference=reference, classification=copied)
        return ifc
    if scenario == "material_name":
        wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        material = ifcopenshell.api.material.add_material(ifc, name=value)
        ifcopenshell.api.material.assign_material(ifc, products=[wall], material=material)
        return ifc
    if scenario == "entity_predefined_type":
        wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        _assign_free_type(wall, value)
        return ifc
    if scenario == "partof_parent":
        space = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcSpace")
        _assign_free_type(space, value)
        wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        ifcopenshell.api.spatial.assign_container(ifc, products=[wall], relating_structure=space)
        return ifc
    if scenario == "partof_aggregate":
        whole = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcElementAssembly")
        _assign_free_type(whole, value)
        part = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcBeam")
        ifcopenshell.api.aggregate.assign_object(ifc, products=[part], relating_object=whole)
        return ifc
    if scenario == "partof_group":
        group = ifc.createIfcInventory()
        _assign_free_type(group, value)
        element = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcElementAssembly")
        ifcopenshell.api.group.assign_group(ifc, products=[element], group=group)
        return ifc
    if scenario == "partof_container":
        space = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcSpace")
        _assign_free_type(space, value)
        element = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcElementAssembly")
        ifcopenshell.api.spatial.assign_container(ifc, products=[element], relating_structure=space)
        return ifc
    if scenario == "partof_nest":
        host = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcFurniture")
        _assign_free_type(host, value)
        part = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcDiscreteAccessory")
        ifcopenshell.api.nest.assign_object(ifc, related_objects=[part], relating_object=host)
        return ifc
    if scenario in ("partof_opening", "partof_filling"):
        wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        _assign_free_type(wall, value)
        opening = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcOpeningElement")
        ifcopenshell.api.feature.add_feature(ifc, feature=opening, element=wall)
        if scenario == "partof_filling":
            window = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWindow")
            ifcopenshell.api.feature.add_filling(ifc, opening=opening, element=window)
        return ifc
    raise AssertionError(scenario)


def _outcome(specs: ids.Ids) -> dict:
    spec = specs.specifications[0]
    return {
        "status": spec.status,
        "applicable": len(spec.applicable_entities),
        "failures": sum(len(facet.failures) for facet in spec.requirements),
    }


def _run(scenario: str, pattern: str, value: str) -> dict:
    loaded = _load(scenario, pattern)
    loaded.validate(_model(scenario, value))
    return _outcome(loaded)


def _attack(scenario: str, send) -> None:
    try:
        try:
            loaded = _load(scenario, ATTACK_PATTERN)
        except Exception as exc:
            send.send(("rejected", "load", type(exc).__name__, str(exc)))
            return
        try:
            model = _model(scenario, ATTACK_VALUE)
        except Exception as exc:
            send.send(("setup", type(exc).__name__, str(exc)))
            return
        try:
            loaded.validate(model)
        except Exception as exc:
            send.send(("rejected", "validate", type(exc).__name__, str(exc)))
            return
        send.send(("done", _outcome(loaded)))
    finally:
        send.close()


def _assert_control(scenario: str, outcome: dict) -> None:
    assert outcome["applicable"] >= 1, outcome
    assert outcome["failures"] == 0, outcome
    assert outcome["status"] is True, outcome


def _assert_attack_finished(scenario: str, message) -> None:
    kind = message[0]
    if kind == "setup":
        pytest.fail(f"{scenario} could not build the model: {message[1]}: {message[2]}")
    if kind == "rejected":
        return
    assert kind == "done", message
    outcome = message[1]
    if SCENARIOS[scenario] == APPLICABILITY:
        assert outcome["applicable"] == 0, outcome
        return
    assert outcome["applicable"] >= 1, outcome
    assert outcome["failures"] >= 1, outcome
    assert outcome["status"] is False, outcome


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_nested_ids_pattern_does_not_stall_audit(scenario: str):
    _assert_control(scenario, _run(scenario, BENIGN_PATTERN, BENIGN_VALUE))

    ctx = multiprocessing.get_context("fork")
    recv, send = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_attack, args=(scenario, send))
    proc.start()
    send.close()
    proc.join(LIMIT_SECONDS)
    if proc.is_alive():
        proc.kill()
        proc.join()
        pytest.fail(f"{scenario} was still auditing after {LIMIT_SECONDS}s")
    if not recv.poll(1):
        pytest.fail(f"{scenario} audit process ended without a result (exit {proc.exitcode})")
    _assert_attack_finished(scenario, recv.recv())
