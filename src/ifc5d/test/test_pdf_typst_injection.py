# Ifc5D - IFC costing utility
# Copyright (C) 2026 Dion Moult <dion@thinkmoult.com>
#
# This file is part of Ifc5D.
#
# Ifc5D is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ifc5D is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Ifc5D.  If not, see <http://www.gnu.org/licenses/>.

# This file was generated with the assistance of an AI coding tool.

"""Cost-schedule PDF export must not compile IFC text as Typst.

``Ifc5DPdfWriter.write`` interpolates the project name, the cost schedule
name, the cost schedule description, and the monetary-unit currency into
``main.typ`` and passes that file to ``typst.compile``. These tests open a
real IFC file and call that writer. They fail while those values are still
compiled as source.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid
import pytest

from ifc5d.ifc5Dspreadsheet import Ifc5DPdfWriter

# Produced only when Typst evaluates ``"INJ" + "ECTION-9f3c"``.
COMPUTED_SENTINEL = "INJECTION-9f3c"
PANIC_EXPR = '#panic("INJ" + "ECTION-9f3c")'
# Produced only when Typst evaluates ``"ONLY" + "-ATTACKER-PAGE"``.
PDF_MARKER = "ONLY-ATTACKER-PAGE"

QUOTE_BREAKOUT = 'x")\n' + PANIC_EXPR + "\n"
CARRIAGE_RETURN_BREAKOUT = 'x")\r' + PANIC_EXPR + "\r"
BACKSLASH_BREAKOUT = "x\\\n" + '")\n' + PANIC_EXPR + "\n"

TEXT_FIELDS = ("project", "name", "description", "currency")


def _assert_source_does_not_contain_results(payload: str) -> None:
    assert COMPUTED_SENTINEL not in payload
    assert PDF_MARKER not in payload


def _exception_text(exc: BaseException) -> str:
    parts = [str(exc)]
    for attr in ("message", "diagnostic", "hints", "trace"):
        value = getattr(exc, attr, None)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return "\n".join(parts)


def _pdf_text(path: Path) -> str:
    pdftotext = os.environ.get("PDFTOTEXT", "pdftotext")
    result = subprocess.run(
        [pdftotext, "-layout", str(path), "-"],
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def _open_schedule(directory: Path, project: str, name: str, description: str, currency: str | None):
    """Write an IFC4 file and open it the same way an export would."""
    model = ifcopenshell.file(schema="IFC4")
    model.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name=project)
    model.create_entity(
        "IfcCostSchedule",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
        Description=description,
        PredefinedType="PRICEDBILLOFQUANTITIES",
    )
    if currency is not None:
        model.create_entity("IfcMonetaryUnit", Currency=currency)
    ifc_path = directory / "model.ifc"
    model.write(str(ifc_path))
    opened = ifcopenshell.open(str(ifc_path))
    assert opened.by_type("IfcProject")[0].Name == project
    schedule = opened.by_type("IfcCostSchedule")[0]
    assert schedule.Name == name
    assert schedule.Description == description
    if currency is not None:
        assert opened.by_type("IfcMonetaryUnit")[0].Currency == currency
    return opened, schedule


def _export(directory: Path, opened, schedule, options: dict | None = None) -> Path:
    output = directory / "schedule.pdf"
    writer = Ifc5DPdfWriter(
        file=opened,
        output=str(output),
        cost_schedule=schedule,
        options={} if options is None else options,
    )
    writer.write()
    return output


def _fields(field: str, payload: str) -> dict:
    values = {"project": "Tower", "name": "Schedule", "description": "Plain", "currency": None}
    values[field] = payload
    return values


def _assert_typst_did_not_run(directory: Path, field: str, payload: str, options: dict | None = None) -> None:
    _assert_source_does_not_contain_results(payload)
    values = _fields(field, payload)
    opened, schedule = _open_schedule(directory, **values)
    try:
        output = _export(directory, opened, schedule, options)
    except Exception as exc:
        blob = _exception_text(exc)
        assert COMPUTED_SENTINEL not in blob
        assert PDF_MARKER not in blob
        assert "panicked with" not in blob
        return
    text = _pdf_text(output)
    assert COMPUTED_SENTINEL not in text
    assert PDF_MARKER not in text
    assert COMPUTED_SENTINEL.encode() not in output.read_bytes()


@pytest.mark.parametrize("field", TEXT_FIELDS)
def test_quote_and_newline_are_not_compiled(field):
    with tempfile.TemporaryDirectory() as tmp:
        _assert_typst_did_not_run(Path(tmp), field, QUOTE_BREAKOUT)


@pytest.mark.parametrize("field", TEXT_FIELDS)
def test_quote_and_carriage_return_are_not_compiled(field):
    with tempfile.TemporaryDirectory() as tmp:
        _assert_typst_did_not_run(Path(tmp), field, CARRIAGE_RETURN_BREAKOUT)


@pytest.mark.parametrize("field", TEXT_FIELDS)
def test_backslash_does_not_escape_the_closing_quote(field):
    with tempfile.TemporaryDirectory() as tmp:
        _assert_typst_did_not_run(Path(tmp), field, BACKSLASH_BREAKOUT)


def test_breakout_cannot_place_computed_text_in_the_pdf():
    """A project name can close the Typst call and compute header text."""
    project = (
        'ignored", schedule_name: "ONLY" + "-ATTACKER-PAGE", '
        'schedule_description: "d", schedule_type: "PRICEDBILLOFQUANTITIES", '
        'project_currency: "EUR", nested_structure_depth: 0, parent_to_new_page_up_to_depth: 0, '
        "show_only_parents: false, should_print_cover: false, should_print_cost_ids: false, "
        "should_print_description: false, should_print_each_quantity: false, "
        "should_print_each_cost_value: false, should_print_rates: false, should_print_summary: false)\n"
        "/*"
    )
    # Closes the comment opened above and discards the writer's remaining lines.
    currency = '*/\n#let swallow(..args) = none\n#swallow(dummy: "'
    _assert_source_does_not_contain_results(project)
    _assert_source_does_not_contain_results(currency)
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        opened, schedule = _open_schedule(
            directory,
            project=project,
            name="Schedule",
            description="still",
            currency=currency,
        )
        try:
            output = _export(directory, opened, schedule)
        except Exception as exc:
            blob = _exception_text(exc)
            assert PDF_MARKER not in blob
            assert COMPUTED_SENTINEL not in blob
            return
        assert PDF_MARKER not in _pdf_text(output)


def test_string_option_is_not_compiled():
    """``options`` values are interpolated without quotes. A string is source."""
    payload = "false)\n" + PANIC_EXPR + '\n#let swallow(..args) = none\n#swallow(dummy: "x"'
    _assert_source_does_not_contain_results(payload)
    with tempfile.TemporaryDirectory() as tmp:
        _assert_typst_did_not_run(
            Path(tmp),
            "description",
            "Plain",
            options={"should_print_summary": payload},
        )


@pytest.mark.parametrize(
    ("field", "literal"),
    [
        ("project", 'Tower "A"'),
        ("name", 'Rate "card"'),
        ("description", 'A "quoted" note'),
        ("currency", 'US"D'),
    ],
)
def test_ordinary_quotes_still_export(field, literal):
    options = {"should_print_cover": True} if field == "description" else None
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        values = _fields(field, literal)
        opened, schedule = _open_schedule(directory, **values)
        output = _export(directory, opened, schedule, options)
        text = _pdf_text(output)
        assert literal in text
        assert COMPUTED_SENTINEL not in text


def test_backslash_in_project_name_stays_text():
    literal = "Tower \\ Hall"
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        opened, schedule = _open_schedule(directory, literal, "Schedule", "Plain", None)
        output = _export(directory, opened, schedule)
        assert literal in _pdf_text(output)


def test_benign_schedule_exports():
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        opened, schedule = _open_schedule(directory, "Tower", "Schedule", "Plain note", "EUR")
        output = _export(directory, opened, schedule)
        text = _pdf_text(output)
        assert output.read_bytes().startswith(b"%PDF")
        assert "Tower" in text
        assert "Schedule" in text
        assert "EUR" in text


def test_outside_file_is_not_copied_into_the_export():
    """A breakout that reads outside the export directory must not return those bytes."""
    secret = "OUTSIDE-FILE-MARKER-7c21"
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        secret_path = directory / "secret.txt"
        secret_path.write_text(secret, encoding="utf-8")
        traversals = ("../" * 8) + str(secret_path).lstrip("/")
        for target in (str(secret_path), traversals):
            payload = 'x")\n#panic(read("' + target + '"))\n'
            assert secret not in payload
            opened, schedule = _open_schedule(directory, "Tower", "Schedule", payload, None)
            try:
                output = _export(directory, opened, schedule)
            except Exception as exc:
                assert secret not in _exception_text(exc)
            else:
                assert secret.encode() not in output.read_bytes()
                assert secret not in _pdf_text(output)
