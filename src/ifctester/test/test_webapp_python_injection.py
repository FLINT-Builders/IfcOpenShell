# This file was generated with the assistance of an AI coding tool.
"""IDS predefined-type values must reach the Pyodide worker as data.

Opening an IDS document and editing a property facet feeds each applicability
entity's predefinedType into ``getApplicablePsets``. The worker currently
places that string, the entity name, and the schema inside a Python source
string. These tests open a document with the real worker decoder and then run
the autocomplete calls RestrictionEditor makes.

They fail while those values are interpolated into Python. A fix passes the
same strings as arguments of ``get_applicable_psets``,
``get_predefined_types_for_entity``, and ``get_entity_attributes``.

Not covered, because the opened document cannot choose the interpolated value:

* ``getAllEntityClasses`` and ``getAllDataTypes`` are called with the fixed
  schema names in ``preloadAutocompletions``.
* ``loadIfc`` interpolates a hyperid that the worker generates, then
  percent-encodes it.
* ``validateIDS`` interpolates a ``Date.now()`` file name.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import xml.sax.saxutils
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
IFCTESTER_SRC = REPO / "src" / "ifctester"
WORKER_API = IFCTESTER_SRC / "webapp" / "public" / "worker" / "api.py"
RUNNER = Path(__file__).resolve().parent / "webapp_python_injection_runner.mjs"

sys.path.insert(0, str(IFCTESTER_SRC))
_spec = importlib.util.spec_from_file_location("ifctester_web_worker_api", WORKER_API)
assert _spec and _spec.loader
_worker_api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_worker_api)


def _xml(
    *,
    entity_name: str,
    predefined_simple: str | None = None,
    predefined_enum: list[str] | None = None,
    include_attribute: bool = False,
) -> str:
    entity_name = xml.sax.saxutils.escape(entity_name)
    if predefined_simple is not None:
        predefined = (
            "<ids:predefinedType><ids:simpleValue>"
            f"{xml.sax.saxutils.escape(predefined_simple)}"
            "</ids:simpleValue></ids:predefinedType>"
        )
    elif predefined_enum is not None:
        values = "".join(
            f'<xs:enumeration value="{xml.sax.saxutils.escape(item, {'"': "&quot;"})}"/>' for item in predefined_enum
        )
        predefined = (
            f'<ids:predefinedType><xs:restriction base="xs:string">{values}</xs:restriction></ids:predefinedType>'
        )
    else:
        predefined = ""
    attribute = ""
    if include_attribute:
        attribute = "<ids:attribute><ids:name><ids:simpleValue>Name</ids:simpleValue></ids:name></ids:attribute>"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ids:ids xmlns:ids="http://standards.buildingsmart.org/IDS"
         xmlns:xs="http://www.w3.org/2001/XMLSchema"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <ids:info><ids:title>injection</ids:title></ids:info>
  <ids:specifications>
    <ids:specification name="Walls" ifcVersion="IFC4">
      <ids:applicability minOccurs="0" maxOccurs="unbounded">
        <ids:entity>
          <ids:name><ids:simpleValue>{entity_name}</ids:simpleValue></ids:name>
          {predefined}
        </ids:entity>
        {attribute}
      </ids:applicability>
      <ids:requirements>
        <ids:property cardinality="required">
          <ids:propertySet><ids:simpleValue>Pset_WallCommon</ids:simpleValue></ids:propertySet>
          <ids:baseName><ids:simpleValue>FireRating</ids:simpleValue></ids:baseName>
        </ids:property>
      </ids:requirements>
    </ids:specification>
  </ids:specifications>
</ids:ids>
"""


def _open(xml: str) -> dict:
    # Same decoder the worker's openIDS calls. validation stays strict because
    # ids_from_xml_string uses XMLSchema.decode's default.
    document = _worker_api.ids_from_xml_string(xml, True)
    return document.asdict()


def _semi(marker: Path) -> str:
    # Closes the interpolated string and the get_applicable_psets call.
    return f'"); open("{marker}", "w").write("executed"); x=("'


def _expression(marker: Path) -> str:
    return f'" or open("{marker}", "w").write("executed") or "'


def _backslash(marker: Path) -> str:
    return f'\\"); open("{marker}", "w").write("executed"); x=("'


def _run(document: dict, marker: Path) -> dict:
    payload = marker.with_suffix(".json")
    payload.write_text(json.dumps(document), encoding="utf-8")
    proc = subprocess.run(
        ["node", str(RUNNER), str(payload), str(marker)],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def _args(result: dict, fn: str) -> list[list]:
    return [call["args"] for call in result["calls"] if call["fn"] == fn]


def test_benign_predefined_type_is_passed_to_the_lookup(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    document = _open(_xml(entity_name="IfcWall", predefined_simple="SOLIDWALL"))
    result = _run(document, marker)
    assert ["IFC4", "IFCWALL", "SOLIDWALL"] in _args(result, "get_applicable_psets")
    assert any(
        item["label"] == "getApplicablePsets" and item["value"] == ["Pset_WallCommon"] for item in result["returned"]
    )
    assert not marker.exists()


@pytest.mark.parametrize(
    "payload_for",
    [_semi, _expression, _backslash],
    ids=["statements", "expression", "backslash"],
)
def test_predefined_type_simple_value_is_not_executed(tmp_path: Path, payload_for) -> None:
    marker = tmp_path / "marker"
    payload = payload_for(marker)
    document = _open(_xml(entity_name="IfcWall", predefined_simple=payload))
    result = _run(document, marker)
    assert not marker.exists()
    assert ["IFC4", "IFCWALL", payload] in _args(result, "get_applicable_psets")


def test_predefined_type_enumeration_is_not_executed(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    payload = _semi(marker)
    document = _open(_xml(entity_name="IfcWall", predefined_enum=[payload, "SOLIDWALL"]))
    result = _run(document, marker)
    assert not marker.exists()
    assert ["IFC4", "IFCWALL", payload] in _args(result, "get_applicable_psets")


def test_entity_name_reaches_worker_as_data(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    payload = _semi(marker)
    document = _open(_xml(entity_name=payload, predefined_simple="SOLIDWALL", include_attribute=True))
    result = _run(document, marker)
    expected = payload.upper()
    assert not marker.exists()
    assert ["IFC4", expected] in _args(result, "get_predefined_types_for_entity")
    assert ["IFC4", expected] in _args(result, "get_entity_attributes")
    assert ["IFC4", expected, "SOLIDWALL"] in _args(result, "get_applicable_psets")
