# This file was generated with the assistance of an AI coding tool.

"""Spreadsheet formula injection through IfcCsv export.

These tests describe the neutralized output. They fail while IfcCsv.export
writes attacker-controlled attribute and property strings unchanged, and they
pass once every string result that starts with ``=``, ``+``, ``-``, ``@``, a
tab, or a carriage return is prefixed with a single quote after formatting
and before the CSV, XLSX, ODS, and pandas writers.
"""

import csv
import io
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.util.selector
import openpyxl
import pytest
from odf.opendocument import OpenDocumentSpreadsheet, load
from odf.table import Table, TableCell, TableRow
from odf.text import P

_IFCCSV_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_IFCCSV_DIR))
import ifccsv

HYPERLINK = '=HYPERLINK("https://example.invalid/x","n")'
EQUALS = "=1+1"
PLUS = "+2+2"
AT = "@SUM(A1)"
MINUS = "-3+1"
TAB = "\t=4+4"
CR = "\r=5+5"
LIST_JOINED = "=1+1, ok"
EMBEDDED = "ok, =1+1"
SAFE_NAME = "Wall A"
NULL = "N/A"
EMPTY = "-"
QUOTE = "'"

DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

# Bonsai's spreadsheet export defaults. See bonsai bim csv prop.CsvProperties.
EXPORT_DEFAULTS = {
    "include_global_id": True,
    "null": NULL,
    "empty": EMPTY,
    "bool_true": "YES",
    "bool_false": "NO",
    "concat": ", ",
}


def _neutralized(original: str) -> str:
    if original[:1] in DANGEROUS_PREFIXES:
        return QUOTE + original
    return original


def _assert_neutralized_text(stored: object, original: str, *, normalize_cr: bool = False) -> None:
    expected = _neutralized(original)
    if normalize_cr and isinstance(stored, str) and isinstance(expected, str):
        # openpyxl rewrites a carriage return as a line feed when it stores the cell.
        assert stored == expected or stored == expected.replace("\r", "\n")
        return
    assert stored == expected


def _build_model(path: Path) -> ifcopenshell.file:
    """Write an IFC file whose attributes are formula text and reopen it.

    Reopening is the path a recipient of the model takes: the strings are
    whatever the IFC parser returns, not only in-memory Python attributes.
    """
    model = ifcopenshell.file(schema="IFC4")
    hostile = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall")
    hostile.Name = HYPERLINK
    hostile.Description = PLUS
    pset = ifcopenshell.api.pset.add_pset(model, product=hostile, name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(
        model,
        pset=pset,
        properties={
            "Reference": AT,
            "Status": MINUS,
            "FireRating": TAB,
            "AcousticRating": CR,
            "Combustible": False,
        },
    )
    pset.HasProperties = list(pset.HasProperties) + [
        model.create_entity(
            "IfcPropertyListValue",
            Name="Tags",
            ListValues=[model.create_entity("IfcLabel", EQUALS), model.create_entity("IfcLabel", "ok")],
        )
    ]

    plain = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall")
    plain.Name = SAFE_NAME
    plain.Description = ""
    plain_pset = ifcopenshell.api.pset.add_pset(model, product=plain, name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(model, pset=plain_pset, properties={"Reference": EMBEDDED})
    qto = ifcopenshell.api.pset.add_qto(model, product=plain, name="Custom_Qto")
    ifcopenshell.api.pset.edit_qto(model, qto=qto, properties={"Height": -1.5})

    model.write(str(path))
    return ifcopenshell.open(str(path))


def _walls(ifc_file: ifcopenshell.file) -> tuple[ifcopenshell.entity_instance, ifcopenshell.entity_instance]:
    walls = ifc_file.by_type("IfcWall")
    hostile = next(wall for wall in walls if wall.Name == HYPERLINK)
    plain = next(wall for wall in walls if wall.Name == SAFE_NAME)
    return hostile, plain


def _export(ifc_file, elements, attributes, output, file_format, **kwargs):
    options = dict(EXPORT_DEFAULTS)
    options.update(kwargs)
    exporter = ifccsv.IfcCsv()
    result = exporter.export(
        ifc_file,
        elements,
        list(attributes),
        output=None if output is None else str(output),
        format=file_format,
        **options,
    )
    return exporter, result


def _indexed_rows(header: list[str], rows: list[list[object]]) -> dict[str, dict[str, object]]:
    gid = header.index("GlobalId")
    return {row[gid]: dict(zip(header, row)) for row in rows}


def _read_csv(path: Path) -> dict[str, dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    return _indexed_rows(rows[0], rows[1:])


def _read_xlsx(path: Path) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, str]]]:
    workbook = openpyxl.load_workbook(path)
    worksheet = workbook.active
    grid = list(worksheet.iter_rows(values_only=False))
    header = [cell.value for cell in grid[0]]
    values: dict[str, dict[str, object]] = {}
    typed: dict[str, dict[str, str]] = {}
    for cells in grid[1:]:
        record = dict(zip(header, [cell.value for cell in cells]))
        values[record["GlobalId"]] = record
        typed[record["GlobalId"]] = dict(zip(header, [cell.data_type for cell in cells]))
    return values, typed


def _cell_text(cell) -> str:
    parts: list[str] = []
    for paragraph in cell.getElementsByType(P):
        for node in paragraph.childNodes:
            data = getattr(node, "data", None)
            if data:
                parts.append(data)
    return "".join(parts)


def _read_ods(path: Path) -> tuple[dict[str, dict[str, object]], list]:
    document = load(str(path))
    table = document.spreadsheet.getElementsByType(Table)[0]
    rows = []
    cells = []
    for table_row in table.getElementsByType(TableRow):
        row_cells = table_row.getElementsByType(TableCell)
        cells.append(row_cells)
        rows.append([_cell_text(cell) for cell in row_cells])
    return _indexed_rows(rows[0], rows[1:]), cells[1:]


def _sheet_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as workbook:
        return workbook.read("xl/worksheets/sheet1.xml").decode()


def _assert_hostile_row(row: dict[str, object], *, include_control_chars: bool, normalize_cr: bool = False) -> None:
    expected = {
        "Name": HYPERLINK,
        "Description": PLUS,
        "Pset_WallCommon.Reference": AT,
        "Pset_WallCommon.Status": MINUS,
        "Pset_WallCommon.Tags": LIST_JOINED,
        "Pset_WallCommon.Combustible": "NO",
    }
    if include_control_chars:
        expected["Pset_WallCommon.FireRating"] = TAB
        expected["Pset_WallCommon.AcousticRating"] = CR
    for header, original in expected.items():
        _assert_neutralized_text(row[header], original, normalize_cr=normalize_cr)


def _assert_plain_row(row: dict[str, object], *, height_is_number: bool) -> None:
    _assert_neutralized_text(row["Name"], SAFE_NAME)
    # Bonsai's empty-string placeholder is "-" and itself starts with a formula prefix.
    _assert_neutralized_text(row["Description"], EMPTY)
    _assert_neutralized_text(row["Pset_WallCommon.Reference"], EMBEDDED)
    assert row["Pset_WallCommon.Status"] == NULL
    if height_is_number:
        assert row["Custom_Qto.Height"] == -1.5
        assert isinstance(row["Custom_Qto.Height"], (int, float))
        assert not isinstance(row["Custom_Qto.Height"], bool)


@pytest.fixture(scope="module")
def ifc_file(tmp_path_factory) -> ifcopenshell.file:
    return _build_model(tmp_path_factory.mktemp("formula-ifc") / "model.ifc")


@pytest.fixture(scope="module")
def loaded_values(ifc_file):
    hostile, plain = _walls(ifc_file)
    return {
        "hostile_name": ifcopenshell.util.selector.get_element_value(hostile, "Name"),
        "hostile_description": ifcopenshell.util.selector.get_element_value(hostile, "Description"),
        "reference": ifcopenshell.util.selector.get_element_value(hostile, "Pset_WallCommon.Reference"),
        "status": ifcopenshell.util.selector.get_element_value(hostile, "Pset_WallCommon.Status"),
        "fire": ifcopenshell.util.selector.get_element_value(hostile, "Pset_WallCommon.FireRating"),
        "acoustic": ifcopenshell.util.selector.get_element_value(hostile, "Pset_WallCommon.AcousticRating"),
        "tags": ifcopenshell.util.selector.get_element_value(hostile, "Pset_WallCommon.Tags"),
        "plain_name": ifcopenshell.util.selector.get_element_value(plain, "Name"),
        "height": ifcopenshell.util.selector.get_element_value(plain, "Custom_Qto.Height"),
        "embedded": ifcopenshell.util.selector.get_element_value(plain, "Pset_WallCommon.Reference"),
    }


ATTRIBUTES = [
    "Name",
    "Description",
    "Pset_WallCommon.Reference",
    "Pset_WallCommon.Status",
    "Pset_WallCommon.FireRating",
    "Pset_WallCommon.AcousticRating",
    "Pset_WallCommon.Tags",
    "Pset_WallCommon.Combustible",
    "Custom_Qto.Height",
]

ODS_ATTRIBUTES = [
    "Name",
    "Description",
    "Pset_WallCommon.Reference",
    "Pset_WallCommon.Status",
    "Pset_WallCommon.FireRating",
    "Pset_WallCommon.Tags",
    "Pset_WallCommon.Combustible",
    "Custom_Qto.Height",
]


def test_reopened_ifc_preserves_formula_text(loaded_values):
    assert loaded_values["hostile_name"] == HYPERLINK
    assert loaded_values["hostile_description"] == PLUS
    assert loaded_values["reference"] == AT
    assert loaded_values["status"] == MINUS
    assert loaded_values["fire"] == TAB
    assert loaded_values["acoustic"] == CR
    assert loaded_values["tags"] == [EQUALS, "ok"]
    assert loaded_values["plain_name"] == SAFE_NAME
    assert loaded_values["height"] == -1.5
    assert loaded_values["embedded"] == EMBEDDED


def test_csv_export_neutralizes_formula_prefixes(ifc_file, tmp_path):
    hostile, plain = _walls(ifc_file)
    output = tmp_path / "schedule.csv"
    _export(ifc_file, [hostile, plain], ATTRIBUTES, output, "csv")
    rows = _read_csv(output)
    _assert_hostile_row(rows[hostile.GlobalId], include_control_chars=True)
    _assert_plain_row(rows[plain.GlobalId], height_is_number=False)
    assert rows[hostile.GlobalId]["GlobalId"] == hostile.GlobalId
    # A numeric quantity is not a string, so the leading minus stays part of the number.
    assert rows[plain.GlobalId]["Custom_Qto.Height"] == "-1.5"


def test_pandas_export_used_by_web_ui_neutralizes_formula_prefixes(ifc_file):
    hostile, plain = _walls(ifc_file)
    _, frame = _export(ifc_file, [hostile, plain], ATTRIBUTES, None, "pd")
    # Bonsai's web export sends this CSV. operator.ExportIfcCsv.execute.
    text = frame.to_csv(index=False)
    rows = list(csv.reader(io.StringIO(text)))
    indexed = _indexed_rows(rows[0], rows[1:])
    _assert_hostile_row(indexed[hostile.GlobalId], include_control_chars=True)
    _assert_plain_row(indexed[plain.GlobalId], height_is_number=False)
    # DataFrame.to_csv renders the number; the in-memory value stays numeric.
    assert frame.loc[frame["GlobalId"] == plain.GlobalId, "Custom_Qto.Height"].iloc[0] == -1.5


def test_xlsx_export_stores_formula_text_as_text(ifc_file, tmp_path):
    hostile, plain = _walls(ifc_file)
    output = tmp_path / "schedule.xlsx"
    _export(ifc_file, [hostile, plain], ATTRIBUTES, output, "xlsx")
    rows, types = _read_xlsx(output)
    _assert_hostile_row(rows[hostile.GlobalId], include_control_chars=True, normalize_cr=True)
    _assert_plain_row(rows[plain.GlobalId], height_is_number=True)
    for header in (
        "Name",
        "Description",
        "Pset_WallCommon.Reference",
        "Pset_WallCommon.Status",
        "Pset_WallCommon.FireRating",
        "Pset_WallCommon.AcousticRating",
        "Pset_WallCommon.Tags",
    ):
        assert types[hostile.GlobalId][header] != "f"
    assert types[plain.GlobalId]["Custom_Qto.Height"] == "n"
    assert "<f" not in _sheet_xml(output)


def _existing_xlsx(path: Path) -> None:
    workbook = openpyxl.Workbook()
    workbook.active.title = "Schedule"
    workbook.active["A1"] = "kept"
    workbook.save(path)


@pytest.mark.parametrize("preserve", [False, True])
def test_xlsx_export_onto_existing_workbook_neutralizes_formulas(ifc_file, tmp_path, preserve):
    hostile, _plain = _walls(ifc_file)
    output = tmp_path / f"existing-{preserve}.xlsx"
    _existing_xlsx(output)
    _export(
        ifc_file,
        [hostile],
        ["Name", "Description", "Pset_WallCommon.Tags"],
        output,
        "xlsx",
        should_preserve_existing=preserve,
    )
    rows, types = _read_xlsx(output)
    _assert_neutralized_text(rows[hostile.GlobalId]["Name"], HYPERLINK)
    _assert_neutralized_text(rows[hostile.GlobalId]["Description"], PLUS)
    _assert_neutralized_text(rows[hostile.GlobalId]["Pset_WallCommon.Tags"], LIST_JOINED)
    assert types[hostile.GlobalId]["Name"] != "f"
    assert "<f" not in _sheet_xml(output)


def _existing_ods(path: Path) -> None:
    document = OpenDocumentSpreadsheet()
    table = Table(name="Schedule")
    row = TableRow()
    cell = TableCell(valuetype="string")
    cell.addElement(P(text="kept"))
    row.addElement(cell)
    table.addElement(row)
    document.spreadsheet.addElement(table)
    document.save(str(path))


@pytest.mark.parametrize("preserve", [False, True])
def test_ods_export_neutralizes_formula_prefixes(ifc_file, tmp_path, preserve):
    hostile, plain = _walls(ifc_file)
    output = tmp_path / f"schedule-{preserve}.ods"
    if preserve:
        _existing_ods(output)
    _export(
        ifc_file,
        [hostile, plain],
        ODS_ATTRIBUTES,
        output,
        "ods",
        should_preserve_existing=preserve,
    )
    rows, body = _read_ods(output)
    hostile_row = rows[hostile.GlobalId]
    _assert_neutralized_text(hostile_row["Name"], HYPERLINK)
    _assert_neutralized_text(hostile_row["Description"], PLUS)
    _assert_neutralized_text(hostile_row["Pset_WallCommon.Reference"], AT)
    _assert_neutralized_text(hostile_row["Pset_WallCommon.Status"], MINUS)
    _assert_neutralized_text(hostile_row["Pset_WallCommon.FireRating"], TAB)
    _assert_neutralized_text(hostile_row["Pset_WallCommon.Tags"], LIST_JOINED)
    _assert_neutralized_text(hostile_row["Pset_WallCommon.Combustible"], "NO")
    _assert_plain_row(rows[plain.GlobalId], height_is_number=False)
    for row_cells in body:
        for cell in row_cells:
            assert not cell.getAttribute("formula")


def test_group_concat_neutralizes_a_leading_formula(ifc_file, tmp_path):
    hostile, _plain = _walls(ifc_file)
    output = tmp_path / "grouped.csv"
    _export(
        ifc_file,
        [hostile],
        ["Name", "Description"],
        output,
        "csv",
        groups=[{"name": "Name", "type": "CONCAT", "varies_value": "VARIES"}],
    )
    rows = _read_csv(output)
    _assert_neutralized_text(rows[hostile.GlobalId]["Name"], HYPERLINK)


def test_spreadsheet_application_does_not_evaluate_exported_formula(ifc_file, tmp_path):
    """Gnumeric calculates a live ``=1+1`` cell. A neutralized cell stays text."""
    if shutil.which("ssconvert") is None:
        pytest.skip("ssconvert is not installed")
    model = ifcopenshell.file(schema="IFC4")
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall")
    wall.Name = EQUALS
    wall.Description = PLUS
    ifc_path = tmp_path / "eval.ifc"
    model.write(str(ifc_path))
    opened = ifcopenshell.open(str(ifc_path))
    element = opened.by_type("IfcWall")[0]
    assert ifcopenshell.util.selector.get_element_value(element, "Name") == EQUALS

    for file_format in ("csv", "xlsx"):
        output = tmp_path / f"eval.{file_format}"
        _export(opened, [element], ["Name", "Description"], output, file_format)
        calculated = tmp_path / f"eval-{file_format}-values.csv"
        command = ["ssconvert", "--recalc"]
        if file_format == "csv":
            command.extend(["-I", "Gnumeric_stf:stf_csvtab"])
        command.extend([str(output), str(calculated)])
        subprocess.run(command, check=True, capture_output=True, text=True)
        with calculated.open(newline="", encoding="utf-8") as handle:
            body = list(csv.reader(handle))[1]
        name, description = body[1], body[2]
        assert name in {EQUALS, _neutralized(EQUALS)}
        assert description in {PLUS, _neutralized(PLUS)}
        assert name != "2"
