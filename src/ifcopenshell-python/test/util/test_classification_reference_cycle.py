# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2022 Dion Moult <dion@thinkmoult.com>
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

"""ReferencedSource cycles must not make classification walks unbounded.

get_inherited_references returns each IfcClassificationReference once, in
walk order, and stops when a reference id repeats or an IfcClassification
is reached. The IfcClassification itself is not part of that list.
get_classification returns that IfcClassification, or None when the chain
repeats without reaching one. Acyclic chains are unchanged.
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


def _ident(reference) -> str | None:
    # IFC2X3 stores the code in ItemReference. Later schemas use Identification.
    identification = getattr(reference, "Identification", None)
    if identification:
        return identification
    return getattr(reference, "ItemReference", None)


def _classification_name(reference):
    import ifcopenshell.util.classification as classification

    found = classification.get_classification(reference)
    if found is None:
        return None
    return found.Name


def _inherited_idents(reference) -> list[str | None]:
    import ifcopenshell.util.classification as classification

    return [_ident(item) for item in classification.get_inherited_references(reference)]


def _loaded_self(schema: str):
    if schema == "IFC2X3":
        body = """
#1=IFCWALL('2iYWrudX5068$o5zjmb9j3',$,'Wall',$,$,$,$,$,$);
#2=IFCCLASSIFICATIONREFERENCE($,'X','X',#2);
#3=IFCRELASSOCIATESCLASSIFICATION('1AkGsof5DBfRc4OrW7p$Ng',$,$,$,(#1),#2);
"""
    else:
        body = """
#1=IFCWALL('2iYWrudX5068$o5zjmb9j3',$,'Wall',$,$,$,$,$,$);
#2=IFCCLASSIFICATIONREFERENCE($,'X','X',#2,$,$);
#3=IFCRELASSOCIATESCLASSIFICATION('1AkGsof5DBfRc4OrW7p$Ng',$,$,$,(#1),#2);
"""
    model = _open_spf(schema, body)
    reference = model.by_type("IfcClassificationReference")[0]
    assert reference.ReferencedSource.id() == reference.id()
    return reference


def _loaded_pair():
    body = """
#1=IFCCLASSIFICATIONREFERENCE($,'A','A',#2,$,$);
#2=IFCCLASSIFICATIONREFERENCE($,'B','B',#1,$,$);
"""
    model = _open_spf("IFC4", body)
    first = next(item for item in model.by_type("IfcClassificationReference") if _ident(item) == "A")
    assert first.ReferencedSource.ReferencedSource.id() == first.id()
    return first


def _loaded_triple():
    body = """
#1=IFCCLASSIFICATIONREFERENCE($,'A','A',#2,$,$);
#2=IFCCLASSIFICATIONREFERENCE($,'B','B',#3,$,$);
#3=IFCCLASSIFICATIONREFERENCE($,'C','C',#1,$,$);
"""
    model = _open_spf("IFC4", body)
    return next(item for item in model.by_type("IfcClassificationReference") if _ident(item) == "A")


def _case_acyclic() -> dict:
    body = """
#1=IFCCLASSIFICATION($,$,$,'Uniclass',$,$,$);
#2=IFCCLASSIFICATIONREFERENCE($,'P','P',#1,$,$);
#3=IFCCLASSIFICATIONREFERENCE($,'C','C',#2,$,$);
#4=IFCCLASSIFICATIONREFERENCE($,'Lone','Lone',$,$,$);
"""
    model = _open_spf("IFC4", body)
    child = next(item for item in model.by_type("IfcClassificationReference") if _ident(item) == "C")
    lone = next(item for item in model.by_type("IfcClassificationReference") if _ident(item) == "Lone")
    import ifcopenshell.util.classification as classification

    return {
        "child_classification": _classification_name(child),
        "child_inherited": _inherited_idents(child),
        "parent_inherited": _inherited_idents(child.ReferencedSource),
        "lone_classification": _classification_name(lone),
        "lone_inherited": _inherited_idents(lone),
        "empty": [_ident(item) for item in classification.get_inherited_references(None)],
    }


def _case_type_and_occurrence() -> dict:
    body = """
#1=IFCWALL('3x7UUs9_nA2vxynSeZ38To',$,'Wall',$,$,$,$,$,$);
#2=IFCWALLTYPE('17ImyB3_9EIvWnmGGTPgzi',$,'WallType',$,$,$,$,$,$,.NOTDEFINED.);
#3=IFCRELDEFINESBYTYPE('0nWAFIqg9CXR1xxpzyMbyW',$,$,$,(#1),#2);
#4=IFCCLASSIFICATION($,$,$,'Other',$,$,$);
#5=IFCCLASSIFICATIONREFERENCE($,'T','T',#4,$,$);
#6=IFCCLASSIFICATIONREFERENCE($,'X','X',#6,$,$);
#7=IFCRELASSOCIATESCLASSIFICATION('1N$G2CKKbFXwK2a7u4ZiUl',$,$,$,(#2),#5);
#8=IFCRELASSOCIATESCLASSIFICATION('0t$04VUYT0I8vr7grAkkFW',$,$,$,(#1),#6);
"""
    import ifcopenshell.util.classification as classification

    model = _open_spf("IFC4", body)
    wall = model.by_type("IfcWall")[0]
    references = list(classification.get_references(wall))
    by_ident = {_ident(item): item for item in references}
    return {
        "references": sorted(by_ident),
        "occurrence_classification": _classification_name(by_ident["X"]),
        "type_classification": _classification_name(by_ident["T"]),
        "occurrence_inherited": _inherited_idents(by_ident["X"]),
        "type_inherited": _inherited_idents(by_ident["T"]),
    }


def _walk(reference, mode: str) -> dict:
    if mode == "classification":
        return {"classification": _classification_name(reference)}
    if mode == "inherited":
        return {"inherited": _inherited_idents(reference)}
    raise AssertionError(mode)


_CASES = {
    "self_ifc4_classification": lambda: _walk(_loaded_self("IFC4"), "classification"),
    "self_ifc4_inherited": lambda: _walk(_loaded_self("IFC4"), "inherited"),
    "self_ifc4x3_classification": lambda: _walk(_loaded_self("IFC4X3_ADD2"), "classification"),
    "self_ifc4x3_inherited": lambda: _walk(_loaded_self("IFC4X3_ADD2"), "inherited"),
    "self_ifc2x3_classification": lambda: _walk(_loaded_self("IFC2X3"), "classification"),
    "self_ifc2x3_inherited": lambda: _walk(_loaded_self("IFC2X3"), "inherited"),
    "pair_classification": lambda: _walk(_loaded_pair(), "classification"),
    "pair_inherited": lambda: _walk(_loaded_pair(), "inherited"),
    "triple_classification": lambda: _walk(_loaded_triple(), "classification"),
    "triple_inherited": lambda: _walk(_loaded_triple(), "inherited"),
    "acyclic": _case_acyclic,
    "type_and_occurrence": _case_type_and_occurrence,
}


def _run(case: str) -> dict:
    try:
        proc = subprocess.run(
            [sys.executable, __file__, case],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{case} did not finish")
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["error"] is None, payload
    return payload["result"]


def test_self_reference_does_not_grow_inherited_references():
    assert _run("self_ifc4_inherited")["inherited"] == ["X"]


def test_self_reference_classification_lookup_stops():
    assert _run("self_ifc4_classification")["classification"] is None


def test_two_reference_cycle_returns_each_reference_once():
    assert _run("pair_inherited")["inherited"] == ["A", "B"]


def test_two_reference_cycle_classification_lookup_stops():
    assert _run("pair_classification")["classification"] is None


def test_three_reference_cycle_returns_each_reference_once():
    assert _run("triple_inherited")["inherited"] == ["A", "B", "C"]


def test_three_reference_cycle_classification_lookup_stops():
    assert _run("triple_classification")["classification"] is None


def test_ifc4x3_self_reference_stops_at_the_repeated_reference():
    assert _run("self_ifc4x3_inherited")["inherited"] == ["X"]
    assert _run("self_ifc4x3_classification")["classification"] is None


def test_ifc2x3_self_reference_stops_at_the_repeated_reference():
    assert _run("self_ifc2x3_inherited")["inherited"] == ["X"]
    assert _run("self_ifc2x3_classification")["classification"] is None


def test_acyclic_chains_still_reach_their_classification():
    result = _run("acyclic")
    assert result["child_inherited"] == ["C", "P"]
    assert result["parent_inherited"] == ["P"]
    assert result["child_classification"] == "Uniclass"
    assert result["lone_inherited"] == ["Lone"]
    assert result["lone_classification"] is None
    assert result["empty"] == []


def test_type_and_occurrence_mix_stops_on_the_cyclic_reference():
    # get_references calls get_classification while merging a typed occurrence.
    result = _run("type_and_occurrence")
    assert result["references"] == ["T", "X"]
    assert result["type_classification"] == "Other"
    assert result["type_inherited"] == ["T"]
    assert result["occurrence_classification"] is None
    assert result["occurrence_inherited"] == ["X"]


if __name__ == "__main__":
    name = sys.argv[1]
    try:
        result = _CASES[name]()
        print(json.dumps({"error": None, "result": result}))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}))
