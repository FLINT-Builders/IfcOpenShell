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

# This file was generated with the assistance of an AI coding tool.

"""IDS classification checks must finish on cyclic ReferencedSource chains.

A parsed classification reference is kept once. Its identification still
takes part in the value check. When the chain never reaches an
IfcClassification, the system check fails with an empty system list instead
of recursing. An acyclic chain still satisfies a matching system and value.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pytest

_HEADER = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('','2026-11-24T00:00:00',(''),(''),'IfcOpenShell','IfcOpenShell','');
FILE_SCHEMA(('{schema}'));
ENDSEC;
DATA;
{body}
ENDSEC;
END-ISO-10303-21;
"""

_SELF_IFC4 = """
#1=IFCWALL('2iYWrudX5068$o5zjmb9j3',$,'Wall',$,$,$,$,$,$);
#2=IFCCLASSIFICATIONREFERENCE($,'X','X',#2,$,$);
#3=IFCRELASSOCIATESCLASSIFICATION('1AkGsof5DBfRc4OrW7p$Ng',$,$,$,(#1),#2);
"""

_PAIR_IFC4 = """
#1=IFCWALL('2iYWrudX5068$o5zjmb9j3',$,'Wall',$,$,$,$,$,$);
#2=IFCCLASSIFICATIONREFERENCE($,'A','A',#3,$,$);
#3=IFCCLASSIFICATIONREFERENCE($,'B','B',#2,$,$);
#4=IFCRELASSOCIATESCLASSIFICATION('1AkGsof5DBfRc4OrW7p$Ng',$,$,$,(#1),#2);
"""

_ACYCLIC_IFC4 = """
#1=IFCWALL('2iYWrudX5068$o5zjmb9j3',$,'Wall',$,$,$,$,$,$);
#2=IFCCLASSIFICATION($,$,$,'Uniclass',$,$,$);
#3=IFCCLASSIFICATIONREFERENCE($,'P','P',#2,$,$);
#4=IFCCLASSIFICATIONREFERENCE($,'C','C',#3,$,$);
#5=IFCRELASSOCIATESCLASSIFICATION('1AkGsof5DBfRc4OrW7p$Ng',$,$,$,(#1),#4);
"""

_TYPE_CYCLE = """
#1=IFCWALL('3x7UUs9_nA2vxynSeZ38To',$,'Wall',$,$,$,$,$,$);
#2=IFCWALLTYPE('17ImyB3_9EIvWnmGGTPgzi',$,'WallType',$,$,$,$,$,$,.NOTDEFINED.);
#3=IFCRELDEFINESBYTYPE('0nWAFIqg9CXR1xxpzyMbyW',$,$,$,(#1),#2);
#4=IFCCLASSIFICATIONREFERENCE($,'X','X',#4,$,$);
#5=IFCRELASSOCIATESCLASSIFICATION('1N$G2CKKbFXwK2a7u4ZiUl',$,$,$,(#2),#4);
"""

_TYPE_AND_OCCURRENCE = """
#1=IFCWALL('3x7UUs9_nA2vxynSeZ38To',$,'Wall',$,$,$,$,$,$);
#2=IFCWALLTYPE('17ImyB3_9EIvWnmGGTPgzi',$,'WallType',$,$,$,$,$,$,.NOTDEFINED.);
#3=IFCRELDEFINESBYTYPE('0nWAFIqg9CXR1xxpzyMbyW',$,$,$,(#1),#2);
#4=IFCCLASSIFICATION($,$,$,'Other',$,$,$);
#5=IFCCLASSIFICATIONREFERENCE($,'T','T',#4,$,$);
#6=IFCCLASSIFICATIONREFERENCE($,'X','X',#6,$,$);
#7=IFCRELASSOCIATESCLASSIFICATION('1N$G2CKKbFXwK2a7u4ZiUl',$,$,$,(#2),#5);
#8=IFCRELASSOCIATESCLASSIFICATION('0t$04VUYT0I8vr7grAkkFW',$,$,$,(#1),#6);
"""

_SELF_IFC2X3 = """
#1=IFCWALL('2iYWrudX5068$o5zjmb9j3',$,'Wall',$,$,$,$,$,$);
#2=IFCCLASSIFICATIONREFERENCE($,'X','X',#2);
#3=IFCRELASSOCIATESCLASSIFICATION('1AkGsof5DBfRc4OrW7p$Ng',$,$,$,(#1),#2);
"""


def _open_spf(schema: str, body: str):
    import ifcopenshell

    text = _HEADER.format(schema=schema, body=body.strip())
    fd, path = tempfile.mkstemp(suffix=".ifc")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    try:
        return ifcopenshell.open(path)
    finally:
        os.remove(path)


def _facet_and_validate(model, *, applicability: list[dict], requirements: list[dict]) -> dict:
    import ifctester.ids
    from ifctester.facet import Classification, Entity

    def build(clause: dict):
        if clause["facet"] == "entity":
            return Entity(name=clause["name"])
        return Classification(system=clause.get("system"), value=clause.get("value"))

    wall = model.by_type("IfcWall")[0]
    facet_results = []
    for clause in applicability + requirements:
        if clause["facet"] != "classification":
            continue
        result = build(clause)(wall)
        facet_results.append({"pass": bool(result), "reason": result.reason})

    specs = ifctester.ids.Ids(title="delivery")
    spec = ifctester.ids.Specification(name="classified")
    for clause in applicability:
        spec.applicability.append(build(clause))
    for clause in requirements:
        spec.requirements.append(build(clause))
    specs.specifications.append(spec)
    specs.validate(model)
    failures = [failure["reason"] for failure in spec.requirements[0].failures] if spec.requirements else []
    return {
        "facets": facet_results,
        "status": spec.status,
        "applicable": len(spec.applicable_entities),
        "failures": failures,
    }


def _case_requirement_self() -> dict:
    model = _open_spf("IFC4", _SELF_IFC4)
    reference = model.by_type("IfcClassificationReference")[0]
    assert reference.ReferencedSource.id() == reference.id()
    return _facet_and_validate(
        model,
        applicability=[{"facet": "entity", "name": "IFCWALL"}],
        requirements=[{"facet": "classification", "system": "Uniclass", "value": "X"}],
    )


def _case_requirement_pair() -> dict:
    model = _open_spf("IFC4", _PAIR_IFC4)
    first = next(item for item in model.by_type("IfcClassificationReference") if item.Identification == "A")
    assert first.ReferencedSource.Identification == "B"
    assert first.ReferencedSource.ReferencedSource.id() == first.id()
    return _facet_and_validate(
        model,
        applicability=[{"facet": "entity", "name": "IFCWALL"}],
        requirements=[{"facet": "classification", "system": "Uniclass", "value": "B"}],
    )


def _case_requirement_ifc4x3() -> dict:
    model = _open_spf("IFC4X3_ADD2", _SELF_IFC4)
    reference = model.by_type("IfcClassificationReference")[0]
    assert reference.ReferencedSource.id() == reference.id()
    return _facet_and_validate(
        model,
        applicability=[{"facet": "entity", "name": "IFCWALL"}],
        requirements=[{"facet": "classification", "system": "Uniclass", "value": "X"}],
    )


def _case_requirement_ifc2x3() -> dict:
    model = _open_spf("IFC2X3", _SELF_IFC2X3)
    reference = model.by_type("IfcClassificationReference")[0]
    assert reference.ReferencedSource.id() == reference.id()
    return _facet_and_validate(
        model,
        applicability=[{"facet": "entity", "name": "IFCWALL"}],
        requirements=[{"facet": "classification", "system": "Uniclass", "value": "X"}],
    )


def _case_applicability_self() -> dict:
    model = _open_spf("IFC4", _SELF_IFC4)
    return _facet_and_validate(
        model,
        applicability=[
            {"facet": "entity", "name": "IFCWALL"},
            {"facet": "classification", "system": "Uniclass", "value": "X"},
        ],
        requirements=[{"facet": "entity", "name": "IFCWALL"}],
    )


def _case_type_cycle() -> dict:
    model = _open_spf("IFC4", _TYPE_CYCLE)
    reference = model.by_type("IfcClassificationReference")[0]
    assert reference.ReferencedSource.id() == reference.id()
    return _facet_and_validate(
        model,
        applicability=[{"facet": "entity", "name": "IFCWALL"}],
        requirements=[{"facet": "classification", "system": "Uniclass", "value": "X"}],
    )


def _case_type_and_occurrence() -> dict:
    model = _open_spf("IFC4", _TYPE_AND_OCCURRENCE)
    return _facet_and_validate(
        model,
        applicability=[{"facet": "entity", "name": "IFCWALL"}],
        requirements=[{"facet": "classification", "system": "Uniclass", "value": "X"}],
    )


def _case_acyclic() -> dict:
    model = _open_spf("IFC4", _ACYCLIC_IFC4)
    return _facet_and_validate(
        model,
        applicability=[{"facet": "entity", "name": "IFCWALL"}],
        requirements=[{"facet": "classification", "system": "Uniclass", "value": "P"}],
    )


_CASES = {
    "requirement_self": _case_requirement_self,
    "requirement_pair": _case_requirement_pair,
    "requirement_ifc4x3": _case_requirement_ifc4x3,
    "requirement_ifc2x3": _case_requirement_ifc2x3,
    "applicability_self": _case_applicability_self,
    "type_cycle": _case_type_cycle,
    "type_and_occurrence": _case_type_and_occurrence,
    "acyclic": _case_acyclic,
}


def _run(case: str) -> dict:
    env = os.environ.copy()
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = package_root + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.run(
            [sys.executable, __file__, case],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{case} did not finish")
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["error"] is None, payload
    return payload["result"]


def test_ids_requirement_finishes_on_a_self_referential_classification():
    result = _run("requirement_self")
    assert result["facets"] == [{"pass": False, "reason": {"type": "SYSTEM", "actual": []}}]
    assert result["status"] is False
    assert result["applicable"] == 1
    assert result["failures"] == ['The systems "[]" do not match the requirements']


def test_ids_requirement_sees_every_reference_in_a_two_node_cycle():
    result = _run("requirement_pair")
    assert result["facets"] == [{"pass": False, "reason": {"type": "SYSTEM", "actual": []}}]
    assert result["status"] is False
    assert result["applicable"] == 1


def test_ids_requirement_finishes_on_an_ifc4x3_self_reference():
    result = _run("requirement_ifc4x3")
    assert result["facets"] == [{"pass": False, "reason": {"type": "SYSTEM", "actual": []}}]
    assert result["status"] is False


def test_ids_requirement_finishes_on_an_ifc2x3_self_reference():
    result = _run("requirement_ifc2x3")
    assert result["facets"] == [{"pass": False, "reason": {"type": "SYSTEM", "actual": []}}]
    assert result["status"] is False


def test_ids_applicability_finishes_on_a_self_referential_classification():
    result = _run("applicability_self")
    assert result["facets"] == [{"pass": False, "reason": {"type": "SYSTEM", "actual": []}}]
    assert result["applicable"] == 0
    assert result["status"] is True


def test_ids_requirement_finishes_when_the_type_reference_is_cyclic():
    result = _run("type_cycle")
    assert result["facets"] == [{"pass": False, "reason": {"type": "SYSTEM", "actual": []}}]
    assert result["status"] is False
    assert result["applicable"] == 1


def test_ids_requirement_keeps_an_acyclic_type_system_beside_a_cyclic_occurrence():
    result = _run("type_and_occurrence")
    assert result["facets"] == [{"pass": False, "reason": {"type": "SYSTEM", "actual": ["Other"]}}]
    assert result["status"] is False
    assert result["applicable"] == 1


def test_ids_requirement_still_passes_an_acyclic_classification_chain():
    result = _run("acyclic")
    assert result["facets"] == [{"pass": True, "reason": None}]
    assert result["status"] is True
    assert result["applicable"] == 1
    assert result["failures"] == []


if __name__ == "__main__":
    name = sys.argv[1]
    try:
        result = _CASES[name]()
        print(json.dumps({"error": None, "result": result}))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}))
