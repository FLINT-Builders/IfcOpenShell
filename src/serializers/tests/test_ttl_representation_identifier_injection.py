# This file was generated with the assistance of an AI coding tool.
"""Turtle subject terms must not copy representation text into the document.

IfcConvert writes each element's Turtle subject from an identifier that
appends the shape representation's RepresentationIdentifier, or the
geometric context's ContextType when that identifier is absent. Those
strings are only lowercased and have spaces turned into dashes, so a
model-context representation can close the generated subject and add
another triple.

These tests fail while that identifier is copied through. They pass when
the Turtle file loads as valid Turtle, still describes the element, and
does not contain the triple supplied in the IFC text.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pyoxigraph = pytest.importorskip("pyoxigraph")

PRODUCT_GUID = "0CYx5dHHH3Fg8k0sF0oO0B"
PROJECT_GUID = "0YvhM3o4H3Fg8k0sF0oO0A"
# Tabs separate tokens. Spaces would be rewritten to dashes and would stay
# inside the prefixed name. The leading newline ends that name.
IDENTIFIER_PAYLOAD = '\n\ta\tgeo:feature\t.\nbase:evil\ta\tgeo:feature\t;\n\trdfs:label\t"pwned"\t.\nbase:tail'
NAME_PAYLOAD = "Proxy\nbase:fromname\ta\tgeo:feature\t.\nbase:x"
EVIL_SUBJECT = "http://example.org/evil"
FROMNAME_SUBJECT = "http://example.org/fromname"


def _step_string(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("'", "''")
        .replace("\t", "\\X\\09")
        .replace("\n", "\\X\\0A")
        .replace("\r", "\\X\\0D")
    )


def _ifc(identifier: str | None, context_type: str, name: str) -> str:
    identifier_token = "$" if identifier is None else "'" + _step_string(identifier) + "'"
    context_token = "'" + _step_string(context_type) + "'"
    name_token = "'" + _step_string(name) + "'"
    return f"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('ttl-injection.ifc','2020-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCDIRECTION((1.,0.,0.));
#2=IFCDIRECTION((0.,0.,1.));
#3=IFCCARTESIANPOINT((0.,0.,0.));
#4=IFCAXIS2PLACEMENT3D(#3,#2,#1);
#5=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#6=IFCUNITASSIGNMENT((#5));
#10=IFCGEOMETRICREPRESENTATIONCONTEXT($,{context_token},3,1.E-05,#4,$);
#12=IFCPROJECT('{PROJECT_GUID}',$,'Project',$,$,$,$,(#10),#6);
#13=IFCLOCALPLACEMENT($,#4);
#14=IFCCARTESIANPOINT((0.,0.,0.));
#15=IFCCARTESIANPOINT((1.,0.,0.));
#16=IFCCARTESIANPOINT((0.,0.,1.));
#17=IFCPOLYLOOP((#14,#15,#16,#14));
#18=IFCFACEOUTERBOUND(#17,.T.);
#19=IFCFACE((#18));
#20=IFCCLOSEDSHELL((#19));
#21=IFCFACETEDBREP(#20);
#22=IFCSHAPEREPRESENTATION(#10,{identifier_token},'Brep',(#21));
#23=IFCPRODUCTDEFINITIONSHAPE($,$,(#22));
#24=IFCBUILDINGELEMENTPROXY('{PRODUCT_GUID}',$,{name_token},$,$,#13,#23,$,$);
ENDSEC;
END-ISO-10303-21;
"""


def _library_dirs(executable: Path) -> list[str]:
    root = executable.resolve().parent
    candidates = [
        root,
        root / "ifcgeom",
        root / "ifcparse",
        root / "plugin",
        root / "ifcgeom" / "serialization" / "Release",
        root.parent / "ifcgeom",
        root.parent / "ifcparse",
        root.parent / "plugin",
        root.parent / "ifcgeom" / "serialization" / "Release",
    ]
    return [str(path) for path in candidates if path.is_dir()]


def _convert(ifc_text: str, destination: Path, *arguments: str) -> str:
    executable = os.environ.get("IFCCONVERT")
    if not executable:
        pytest.fail("Set IFCCONVERT to the IfcConvert executable built from this commit")
    source = destination.with_suffix(".ifc")
    source.write_text(ifc_text)
    env = os.environ.copy()
    lib_dirs = _library_dirs(Path(executable))
    if lib_dirs:
        env["LD_LIBRARY_PATH"] = ":".join(lib_dirs + [env.get("LD_LIBRARY_PATH", "")])
    completed = subprocess.run(
        [executable, str(source), str(destination), *arguments],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if completed.returncode != 0 or not destination.exists():
        pytest.fail(
            "IfcConvert did not write Turtle output\n"
            f"exit {completed.returncode}\n{completed.stdout}\n{completed.stderr}"
        )
    return destination.read_text()


def _triples(turtle: str):
    try:
        return list(pyoxigraph.parse(turtle.encode(), format=pyoxigraph.RdfFormat.TURTLE))
    except Exception as exc:
        pytest.fail(f"Turtle output is not valid Turtle:\n{exc}\n\n{turtle}")


def _assert_safe_graph(turtle: str) -> None:
    triples = _triples(turtle)
    subjects = [str(triple.subject) for triple in triples]
    objects = [str(triple.object) for triple in triples]
    assert not any(EVIL_SUBJECT in subject for subject in subjects)
    assert not any("pwned" in obj for obj in objects)
    assert not any(FROMNAME_SUBJECT in subject for subject in subjects)
    assert any(PRODUCT_GUID in obj for obj in objects)


@pytest.mark.parametrize("extra_args", [[], ["--wkt-use-section"]])
def test_representation_identifier_is_not_turtle(tmp_path: Path, extra_args: list[str]) -> None:
    turtle = _convert(
        _ifc(IDENTIFIER_PAYLOAD, "Model", NAME_PAYLOAD),
        tmp_path / "identifier.ttl",
        *extra_args,
    )
    _assert_safe_graph(turtle)


@pytest.mark.parametrize("extra_args", [[], ["--wkt-use-section"]])
def test_context_type_is_not_turtle_when_identifier_absent(tmp_path: Path, extra_args: list[str]) -> None:
    turtle = _convert(
        _ifc(None, IDENTIFIER_PAYLOAD, NAME_PAYLOAD),
        tmp_path / "context.ttl",
        *extra_args,
    )
    _assert_safe_graph(turtle)


@pytest.mark.parametrize("extra_args", [[], ["--wkt-use-section"]])
def test_body_identifier_exports_element_without_injected_name(tmp_path: Path, extra_args: list[str]) -> None:
    turtle = _convert(
        _ifc("Body", "Model", NAME_PAYLOAD),
        tmp_path / "body.ttl",
        *extra_args,
    )
    _assert_safe_graph(turtle)
