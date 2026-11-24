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
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

"""Bounded evaluation of regular expressions taken from IFC models.

Drawing Include and Exclude strings, IfcTextLiteral templates, and the same
selector operations those call sites share must not run a nested quantifier
against a non-matching string for an unbounded time. A non-match has to come
back as "no match": an empty filter result, None from value lookup, or text
that does not contain the property value behind the pattern.

These tests fail while `re.compile` / `Pattern.match` run without a limit.
They pass once that evaluation is bounded and a timeout or rejection is
treated as no match.

Not executed here, because they import Blender: `Drawing.activate_drawing`,
`DecoratorData.load`, the camera decorator, `SvgWriter` text drawing, and the
drawing UI / operator callers. Each of those forwards the IFC string into
`filter_elements` or `replace_text_literal_variables`, which are executed.
`ifccsv` reaches the same `set_element_value` regex match tested below.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest


# The checkout's Python package has no compiled wrapper. Pytest puts that
# checkout on sys.path, which would shadow an installed IfcOpenShell.
def _has_compiled_wrapper(package_dir: Path) -> bool:
    for path in package_dir.glob("ifcopenshell_wrapper.*"):
        if path.suffix != ".pyi":
            return True
    return any(package_dir.glob("_ifcopenshell_wrapper.*"))


_PKG_ROOT = Path(__file__).resolve().parents[2]
if not _has_compiled_wrapper(_PKG_ROOT / "ifcopenshell"):
    sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != _PKG_ROOT]

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.classification
import ifcopenshell.api.group
import ifcopenshell.api.material
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.type
import ifcopenshell.util.element

REPO_ROOT = Path(__file__).resolve().parents[4]
SELECTOR_PATH = REPO_ROOT / "src/ifcopenshell-python/ifcopenshell/util/selector.py"
DRAWING_PATH = REPO_ROOT / "src/bonsai/bonsai/tool/drawing.py"
SEARCH_PATH = REPO_ROOT / "src/bonsai/bonsai/tool/search.py"
DATA_PATH = REPO_ROOT / "src/bonsai/bonsai/bim/module/drawing/data.py"
SVGWRITER_PATH = REPO_ROOT / "src/bonsai/bonsai/bim/module/drawing/svgwriter.py"

# 32 non-matching "a"s is exponential in CPython's `re` engine (about 2^32
# attempts). A bounded matcher returns in well under this limit.
EVIL_LENGTH = 32
SMALL_LENGTH = 16
TIMEOUT_SECONDS = 2.0
NESTED = "/(a+)+$/"
SENTINEL = "MATCHED_SENTINEL"


def _load_repo_selector():
    """Import selector.py from this checkout, not another copy on sys.path."""
    spec = importlib.util.spec_from_file_location("ifcopenshell.util.selector", SELECTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ifcopenshell.util.selector"] = module
    spec.loader.exec_module(module)
    import ifcopenshell.util as util

    util.selector = module
    return module


subject = _load_repo_selector()


def _evil(length: int) -> str:
    return "a" * length + "!"


def _new_file() -> ifcopenshell.file:
    return ifcopenshell.api.project.create_file()


def _reopen(ifc_file: ifcopenshell.file) -> ifcopenshell.file:
    handle, path = tempfile.mkstemp(suffix=".ifc")
    os.close(handle)
    try:
        ifc_file.write(path)
        return ifcopenshell.open(path)
    finally:
        os.remove(path)


def _wall_named(name: str) -> tuple[ifcopenshell.file, ifcopenshell.entity_instance]:
    ifc_file = _new_file()
    wall = ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcWall")
    wall.Name = name
    return ifc_file, wall


def _annotation_with_pset(pset_name: str, prop_name: str, prop_value: str):
    ifc_file = _new_file()
    element = ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcAnnotation")
    element.ObjectType = "TEXT"
    pset = ifcopenshell.api.pset.add_pset(ifc_file, product=element, name=pset_name)
    ifcopenshell.api.pset.edit_pset(ifc_file, pset=pset, properties={prop_name: prop_value})
    return ifc_file, element


def _load_methods(path: Path, class_name: str, names: set[str]):
    """Compile methods from source so the test runs the product function."""
    source = path.read_text()
    tree = ast.parse(source)
    blocks: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        lines = source.splitlines()
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name in names:
                start = item.lineno - 1
                if item.decorator_list:
                    start = min(decorator.lineno for decorator in item.decorator_list) - 1
                block = "\n".join(lines[start : item.end_lineno])
                blocks.append(textwrap.dedent(block))
        break
    else:
        raise AssertionError(f"{class_name} not found in {path}")
    missing = names.difference(
        item.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
        for item in node.body
        if isinstance(item, ast.FunctionDef)
    )
    if missing:
        raise AssertionError(f"{path} is missing {missing}")
    namespace: dict = {
        "re": __import__("re"),
        "json": json,
        "ifcopenshell": ifcopenshell,
        "Optional": __import__("typing").Optional,
        "Union": __import__("typing").Union,
        "Any": __import__("typing").Any,
    }
    exec(
        "from __future__ import annotations\nclass _Loaded:\n" + textwrap.indent("\n\n".join(blocks), "    "),
        namespace,
    )
    return namespace["_Loaded"]


def _drawing_include_elements(ifc_file: ifcopenshell.file, include: str | None):
    """Same Include dispatch as Drawing.get_drawing_elements."""
    elements: set = set()
    if include:
        try:
            data = json.loads(include)
            if isinstance(data, dict) and "filter_structure" in data:
                search = _load_methods(SEARCH_PATH, "Search", {"execute_filter_groups_from_json", "_wrap_json_value"})
                elements = search.execute_filter_groups_from_json(data, ifc_file)
            elif isinstance(data, dict) and "query" in data:
                elements = subject.filter_elements(ifc_file, data["query"])
            else:
                elements = subject.filter_elements(ifc_file, include)
        except (json.JSONDecodeError, ValueError):
            elements = subject.filter_elements(ifc_file, include)
    return elements


def _store_drawing_filters(include: str, exclude: str) -> ifcopenshell.file:
    ifc_file, _wall = _wall_named(_evil(EVIL_LENGTH))
    drawing = ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcAnnotation")
    drawing.ObjectType = "DRAWING"
    pset = ifcopenshell.api.pset.add_pset(ifc_file, product=drawing, name="EPset_Drawing")
    ifcopenshell.api.pset.edit_pset(ifc_file, pset=pset, properties={"Include": include, "Exclude": exclude})
    return _reopen(ifc_file)


def _drawing_by_type(ifc_file: ifcopenshell.file, object_type: str):
    return next(element for element in ifc_file.by_type("IfcAnnotation") if element.ObjectType == object_type)


def _filter_token(elements: set, victim: ifcopenshell.entity_instance) -> str:
    return "MATCH" if victim in elements else "NO_MATCH"


def _value_token(value) -> str:
    if value is None:
        return "NO_MATCH"
    if SENTINEL in str(value):
        return "MATCH"
    return "NO_MATCH"


# --- cases executed in a child process so a hang fails the test ------------


def _case_include_attribute() -> str:
    include = f"IfcWall, Name={NESTED}"
    ifc_file = _store_drawing_filters(include, include)
    drawing = _drawing_by_type(ifc_file, "DRAWING")
    stored = ifcopenshell.util.element.get_psets(drawing)["EPset_Drawing"]["Include"]
    assert stored == include
    wall = ifc_file.by_type("IfcWall")[0]
    return _filter_token(_drawing_include_elements(ifc_file, stored), wall)


def _case_include_json_query() -> str:
    query = f"IfcWall, Name={NESTED}"
    include = json.dumps({"query": query})
    ifc_file = _store_drawing_filters(include, "")
    drawing = _drawing_by_type(ifc_file, "DRAWING")
    stored = ifcopenshell.util.element.get_psets(drawing)["EPset_Drawing"]["Include"]
    wall = ifc_file.by_type("IfcWall")[0]
    return _filter_token(_drawing_include_elements(ifc_file, stored), wall)


def _case_exclude_attribute() -> str:
    exclude = f"IfcWall, Name={NESTED}"
    ifc_file = _store_drawing_filters("IfcWall", exclude)
    drawing = _drawing_by_type(ifc_file, "DRAWING")
    stored = ifcopenshell.util.element.get_psets(drawing)["EPset_Drawing"]["Exclude"]
    assert stored == exclude
    wall = ifc_file.by_type("IfcWall")[0]
    # get_drawing_elements and get_drawing_spaces subtract this same call.
    return _filter_token(subject.filter_elements(ifc_file, stored), wall)


def _case_filter_structure() -> str:
    ifc_file, wall = _wall_named(_evil(EVIL_LENGTH))
    search = _load_methods(SEARCH_PATH, "Search", {"execute_filter_groups_from_json", "_wrap_json_value"})
    data = {
        "filter_structure": [
            [
                {"type": "entity", "value": "IfcWall", "filter_mode": "ADD"},
                {
                    "type": "attribute",
                    "name": "Name",
                    "comparison": "=",
                    "value": NESTED,
                    "filter_mode": "FILTER",
                },
            ]
        ]
    }
    return _filter_token(search.execute_filter_groups_from_json(data, ifc_file), wall)


def _case_type_value() -> str:
    ifc_file, wall = _wall_named("Wall")
    element_type = ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcWallType")
    element_type.Name = _evil(EVIL_LENGTH)
    ifcopenshell.api.type.assign_type(ifc_file, related_objects=[wall], relating_type=element_type)
    return _filter_token(subject.filter_elements(ifc_file, f"IfcWall, type={NESTED}"), wall)


def _case_material_value() -> str:
    ifc_file, wall = _wall_named("Wall")
    material = ifcopenshell.api.material.add_material(ifc_file, name=_evil(EVIL_LENGTH))
    ifcopenshell.api.material.assign_material(ifc_file, products=[wall], material=material)
    return _filter_token(subject.filter_elements(ifc_file, f"IfcWall, material={NESTED}"), wall)


def _case_classification_value() -> str:
    ifc_file, wall = _wall_named("Wall")
    ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcProject")
    classification = ifcopenshell.api.classification.add_classification(ifc_file, classification="Uniclass")
    ifcopenshell.api.classification.add_reference(
        ifc_file,
        products=[wall],
        identification="X",
        name=_evil(EVIL_LENGTH),
        classification=classification,
    )
    return _filter_token(subject.filter_elements(ifc_file, f"IfcWall, classification={NESTED}"), wall)


def _case_location_value() -> str:
    ifc_file, wall = _wall_named("Wall")
    storey = ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcBuildingStorey", name=_evil(EVIL_LENGTH))
    ifcopenshell.api.spatial.assign_container(ifc_file, products=[wall], relating_structure=storey)
    return _filter_token(subject.filter_elements(ifc_file, f"IfcWall, location={NESTED}"), wall)


def _case_group_value() -> str:
    ifc_file, wall = _wall_named("Wall")
    group = ifcopenshell.api.group.add_group(ifc_file, name=_evil(EVIL_LENGTH))
    ifcopenshell.api.group.assign_group(ifc_file, products=[wall], group=group)
    return _filter_token(subject.filter_elements(ifc_file, f"IfcWall, group={NESTED}"), wall)


def _case_parent_value() -> str:
    ifc_file, wall = _wall_named("Wall")
    parent = ifcopenshell.api.root.create_entity(ifc_file, ifc_class="IfcElementAssembly", name=_evil(EVIL_LENGTH))
    ifcopenshell.api.aggregate.assign_object(ifc_file, products=[wall], relating_object=parent)
    return _filter_token(subject.filter_elements(ifc_file, f"IfcWall, parent={NESTED}"), wall)


def _case_property_value() -> str:
    ifc_file, wall = _wall_named("Wall")
    pset = ifcopenshell.api.pset.add_pset(ifc_file, product=wall, name="Custom")
    ifcopenshell.api.pset.edit_pset(ifc_file, pset=pset, properties={"Reference": _evil(EVIL_LENGTH)})
    return _filter_token(subject.filter_elements(ifc_file, f"IfcWall, Custom.Reference={NESTED}"), wall)


def _case_property_list_value() -> str:
    ifc_file, wall = _wall_named("Wall")
    pset = ifcopenshell.api.pset.add_pset(ifc_file, product=wall, name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(ifc_file, pset=pset, properties={"Status": [_evil(EVIL_LENGTH)]})
    return _filter_token(subject.filter_elements(ifc_file, f"IfcWall, Pset_WallCommon.Status={NESTED}"), wall)


def _case_property_name() -> str:
    ifc_file, element = _annotation_with_pset("Safe", _evil(EVIL_LENGTH), SENTINEL)
    return _filter_token(subject.filter_elements(ifc_file, f"IfcAnnotation, Safe.{NESTED}={SENTINEL}"), element)


def _case_pset_name() -> str:
    ifc_file, element = _annotation_with_pset(_evil(EVIL_LENGTH), "X", SENTINEL)
    return _filter_token(subject.filter_elements(ifc_file, f"IfcAnnotation, {NESTED}.X={SENTINEL}"), element)


def _case_query_value() -> str:
    ifc_file, wall = _wall_named(_evil(EVIL_LENGTH))
    return _filter_token(subject.filter_elements(ifc_file, f"IfcWall, query:Name={NESTED}"), wall)


def _case_query_key() -> str:
    ifc_file, element = _annotation_with_pset(_evil(EVIL_LENGTH), "X", SENTINEL)
    query = f'IfcAnnotation, query:"{NESTED}.X"={SENTINEL}'
    return _filter_token(subject.filter_elements(ifc_file, query), element)


def _case_get_element_pset() -> str:
    _ifc_file, element = _annotation_with_pset(_evil(EVIL_LENGTH), "X", SENTINEL)
    return _value_token(subject.get_element_value(element, f"{NESTED}.X"))


def _case_get_element_prop() -> str:
    _ifc_file, element = _annotation_with_pset("Safe", _evil(EVIL_LENGTH), SENTINEL)
    return _value_token(subject.get_element_value(element, f"Safe.{NESTED}"))


def _case_format_variable() -> str:
    _ifc_file, element = _annotation_with_pset(_evil(EVIL_LENGTH), "X", SENTINEL)
    return _value_token(subject.format("{{" + f"{NESTED}.X" + "}}", element))


def _case_text_literal_braces() -> str:
    ifc_file, element = _annotation_with_pset(_evil(EVIL_LENGTH), "X", SENTINEL)
    origin = ifc_file.createIfcAxis2Placement3D(ifc_file.createIfcCartesianPoint((0.0, 0.0, 0.0)))
    literal = "{{" + f"{NESTED}.X" + "}}"
    ifc_file.createIfcTextLiteral(Literal=literal, Placement=origin, Path="RIGHT")
    reopened = _reopen(ifc_file)
    stored = reopened.by_type("IfcTextLiteral")[0].Literal
    product = _drawing_by_type(reopened, "TEXT")
    drawing = _load_methods(DRAWING_PATH, "Drawing", {"replace_text_literal_variables"})
    return _value_token(drawing.replace_text_literal_variables(stored, product))


def _case_text_literal_backticks() -> str:
    _ifc_file, element = _annotation_with_pset(_evil(EVIL_LENGTH), "X", SENTINEL)
    literal = "``{{" + f"{NESTED}.X" + "}}``"
    drawing = _load_methods(DRAWING_PATH, "Drawing", {"replace_text_literal_variables"})
    return _value_token(drawing.replace_text_literal_variables(literal, element))


def _case_set_element_pset() -> str:
    ifc_file, element = _annotation_with_pset(_evil(EVIL_LENGTH), "X", SENTINEL)
    subject.set_element_value(ifc_file, element, f"{NESTED}.X", "changed")
    stored = ifcopenshell.util.element.get_pset(element, _evil(EVIL_LENGTH), "X")
    return "NO_MATCH" if stored == SENTINEL else "MATCH"


def _case_set_element_prop() -> str:
    ifc_file, element = _annotation_with_pset("Safe", _evil(EVIL_LENGTH), SENTINEL)
    subject.set_element_value(ifc_file, element, f"Safe.{NESTED}", "changed")
    stored = ifcopenshell.util.element.get_pset(element, "Safe", _evil(EVIL_LENGTH))
    return "NO_MATCH" if stored == SENTINEL else "MATCH"


CASES = {
    "include_attribute": _case_include_attribute,
    "include_json_query": _case_include_json_query,
    "exclude_attribute": _case_exclude_attribute,
    "filter_structure": _case_filter_structure,
    "type_value": _case_type_value,
    "material_value": _case_material_value,
    "classification_value": _case_classification_value,
    "location_value": _case_location_value,
    "group_value": _case_group_value,
    "parent_value": _case_parent_value,
    "property_value": _case_property_value,
    "property_list_value": _case_property_list_value,
    "property_name": _case_property_name,
    "pset_name": _case_pset_name,
    "query_value": _case_query_value,
    "query_key": _case_query_key,
    "get_element_pset": _case_get_element_pset,
    "get_element_prop": _case_get_element_prop,
    "format_variable": _case_format_variable,
    "text_literal_braces": _case_text_literal_braces,
    "text_literal_backticks": _case_text_literal_backticks,
    "set_element_pset": _case_set_element_pset,
    "set_element_prop": _case_set_element_prop,
}


def _run_case(case: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), case],
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


@pytest.mark.parametrize("case", sorted(CASES))
def test_ifc_supplied_regex_is_bounded(case: str):
    try:
        proc = _run_case(case)
    except subprocess.TimeoutExpired:
        pytest.fail(f"{case} was still running after {TIMEOUT_SECONDS}s")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "NO_MATCH"


def test_short_nested_pattern_reaches_the_matcher_and_does_not_match():
    """A short input finishes, so a hang on the long input is backtracking."""
    ifc_file, wall = _wall_named(_evil(SMALL_LENGTH))
    assert subject.filter_elements(ifc_file, f"IfcWall, Name={NESTED}") == set()
    _ifc_file, element = _annotation_with_pset(_evil(SMALL_LENGTH), "X", SENTINEL)
    assert subject.get_element_value(element, f"{NESTED}.X") is None


def test_long_string_with_a_linear_pattern_stays_fast():
    ifc_file, wall = _wall_named(_evil(EVIL_LENGTH))
    assert subject.filter_elements(ifc_file, "IfcWall, Name=/^nope$/") == set()
    wall.Name = "SafeWall"
    assert subject.filter_elements(ifc_file, "IfcWall, Name=/^SafeWall$/") == {wall}


def test_benign_template_substitution_still_works():
    ifc_file, element = _annotation_with_pset("Safe", "X", SENTINEL)
    assert subject.get_element_value(element, "Safe.X") == SENTINEL
    assert subject.format("{{Safe.X}}", element) == SENTINEL
    assert subject.get_element_value(element, "/Safe.*/.X") == SENTINEL
    drawing = _load_methods(DRAWING_PATH, "Drawing", {"replace_text_literal_variables"})
    assert drawing.replace_text_literal_variables("Value {{Safe.X}}", element) == f"Value {SENTINEL}"


def test_call_sites_forward_ifc_text_into_the_selector():
    drawing = DRAWING_PATH.read_text()
    assert 'ifcopenshell.util.selector.filter_elements(ifc_file, data["query"])' in drawing
    assert "ifcopenshell.util.selector.filter_elements(ifc_file, include)" in drawing
    assert "ifcopenshell.util.selector.filter_elements(ifc_file, exclude)" in drawing
    assert "ifcopenshell.util.selector.get_element_value(product, variable[2:-2])" in drawing
    assert "ifcopenshell.util.selector.format(command_content, product)" in drawing
    search = SEARCH_PATH.read_text()
    assert 'if value.startswith("/") and value.endswith("/")' in search
    assert "return value" in search
    data = DATA_PATH.read_text()
    assert "tool.Drawing.replace_text_literal_variables(literal_value, product)" in data
    svg = SVGWRITER_PATH.read_text()
    assert "tool.Drawing.replace_text_literal_variables(text_literal.Literal, product or element)" in svg


if __name__ == "__main__":
    token = CASES[sys.argv[1]]()
    print(token)
