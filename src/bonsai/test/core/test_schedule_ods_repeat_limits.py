# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026 IfcOpenShell contributors
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

# This file was generated with the assistance of an AI coding tool.

"""Schedule SVG conversion must budget ODS repeats before expanding them.

`Scheduler.schedule` is the function both entry points call with the
attacker-supplied spreadsheet path:

- `bim.build_schedule` -> `core.build_schedule` -> `Drawing.create_svg_schedule`
- IfcCSV export when "Generate SVG" is enabled and the format is not csv

Those operators need Blender, and neither one inspects repeat attributes
before calling `schedule`. These tests drive `schedule` with real ODS files
parsed by odfpy. They fail while `schedule_ods` materialises
`number-columns-repeated`, `number-rows-repeated`, or the cell span/repeat
product into lists before applying the 10000-cell budget.
"""

from __future__ import annotations

import importlib
import sys
import tracemalloc
import types
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

CELL_BUDGET = 10_000
# Large enough that the expanded width/height list is visible to tracemalloc,
# and far above CELL_BUDGET. The loop that consumes the attribute has no cap,
# so a larger repeat is the same path.
OVERSIZED_REPEAT = 200_000
# Each part is below a per-attribute cap of CELL_BUDGET. The total is not.
REPEAT_PARTS = 200
REPEAT_PER_PART = 1_000
# A 9900-cell conversion peaked under 0.5 MiB. Expanding OVERSIZED_REPEAT
# widths peaked above 3 MiB, or 8 MiB when each width is its own float.
MAX_EXPANSION_BYTES = 2_000_000

ODS_MIMETYPE = "application/vnd.oasis.opendocument.spreadsheet"
MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
 <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>
 <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
"""
CONTENT_NS = " ".join(
    [
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"',
        'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"',
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"',
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"',
        'office:version="1.2"',
    ]
)
EMPTY_CELL = "<table:table-cell/>"
# Keep these on one line. A whitespace text node becomes the style's first
# child, and schedule_ods then crashes before it expands the repeats.
COLUMN_STYLE = (
    '<style:style style:name="co1" style:family="table-column">'
    '<style:table-column-properties style:column-width="20mm"/>'
    "</style:style>"
)
ROW_STYLE = (
    '<style:style style:name="ro1" style:family="table-row">'
    '<style:table-row-properties style:row-height="5mm"/>'
    "</style:style>"
)


@dataclass
class Conversion:
    exc: BaseException | None
    peak_bytes: int
    svg_bytes: bytes | None

    @property
    def rects(self) -> int:
        if self.svg_bytes is None:
            return 0
        return self.svg_bytes.count(b"<rect")


@pytest.fixture(scope="module")
def scheduler():
    root = Path(__file__).resolve().parents[2]
    inserted = str(root)
    if inserted not in sys.path:
        sys.path.insert(0, inserted)

    bonsai_pkg = importlib.import_module("bonsai")
    assert bonsai_pkg.__path__

    saved = {name: sys.modules.get(name) for name in _stub_names()}
    _install_import_stubs(root)
    module = importlib.import_module("bonsai.bim.module.drawing.scheduler")
    try:
        yield module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def _stub_names() -> tuple[str, ...]:
    return (
        "bonsai.bim",
        "bonsai.bim.module",
        "bonsai.bim.module.drawing",
        "bonsai.bim.module.drawing.svgwriter",
        "bonsai.bim.module.drawing.scheduler",
        "bonsai.tool",
    )


def _install_import_stubs(root: Path) -> None:
    """Load the real scheduler module without Blender.

    `parse_css` always asks for addon preferences, then reads a sibling CSS
    file when one is present. SVG text layout is not used by these fixtures.
    """

    def package(name: str, path: Path) -> None:
        module = types.ModuleType(name)
        module.__path__ = [str(path)]  # type: ignore[attr-defined]
        module.__package__ = name
        sys.modules[name] = module

    package("bonsai.bim", root / "bonsai" / "bim")
    package("bonsai.bim.module", root / "bonsai" / "bim" / "module")
    package("bonsai.bim.module.drawing", root / "bonsai" / "bim" / "module" / "drawing")

    svgwriter = types.ModuleType("bonsai.bim.module.drawing.svgwriter")

    class SvgWriter:
        @staticmethod
        def get_box_alignment_parameters(box_alignment: str) -> dict[str, str]:
            return {}

    svgwriter.SvgWriter = SvgWriter
    sys.modules["bonsai.bim.module.drawing.svgwriter"] = svgwriter

    tool = types.ModuleType("bonsai.tool")

    class _Doc:
        schedules_stylesheet_path = "schedule.css"

    class _Prefs:
        doc = _Doc()

    class Blender:
        @staticmethod
        def get_addon_preferences() -> _Prefs:
            return _Prefs()

        @staticmethod
        def get_data_dir_path(path: Path) -> str:
            raise AssertionError("sibling CSS should satisfy parse_css")

    class Ifc:
        @staticmethod
        def get_path() -> str:
            raise AssertionError("sibling CSS should satisfy parse_css")

    tool.Blender = Blender
    tool.Ifc = Ifc
    sys.modules["bonsai.tool"] = tool


def _columns(repeats: list[int], style_name: str | None = None) -> str:
    style = f' table:style-name="{style_name}"' if style_name else ""
    return "".join(f'<table:table-column{style} table:number-columns-repeated="{repeat}"/>' for repeat in repeats)


def _rows(repeats: list[int], cell_xml: str, style_name: str | None = None) -> str:
    style = f' table:style-name="{style_name}"' if style_name else ""
    return "".join(
        f'<table:table-row{style} table:number-rows-repeated="{repeat}">{cell_xml}</table:table-row>'
        for repeat in repeats
    )


def _content(
    columns_xml: str,
    rows_xml: str,
    *,
    styles: str = "",
    print_range: str | None = None,
) -> str:
    printed = f' table:print-ranges="{print_range}"' if print_range else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {CONTENT_NS}>
  <office:automatic-styles>{styles}</office:automatic-styles>
  <office:body>
    <office:spreadsheet>
      <table:table table:name="Sheet1"{printed}>
        {columns_xml}
        {rows_xml}
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>
"""


def _write_ods(path: Path, content_xml: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", ODS_MIMETYPE)
        archive.writestr("META-INF/manifest.xml", MANIFEST)
        archive.writestr("content.xml", content_xml)
    path.with_suffix(".css").write_text(":root { --font-size-pt: 12; }\n", encoding="utf-8")


def _convert(scheduler, directory: Path, name: str, content_xml: str) -> Conversion:
    ods_path = directory / f"{name}.ods"
    svg_path = directory / f"{name}.svg"
    _write_ods(ods_path, content_xml)
    tracemalloc.start()
    exc: BaseException | None = None
    try:
        scheduler.Scheduler().schedule(str(ods_path), str(svg_path))
    except Exception as caught:
        exc = caught
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    svg_bytes = svg_path.read_bytes() if svg_path.exists() else None
    return Conversion(exc=exc, peak_bytes=peak, svg_bytes=svg_bytes)


def _assert_budget_holds(result: Conversion) -> None:
    assert not isinstance(result.exc, MemoryError), "repeat expansion exhausted memory"
    assert not isinstance(result.exc, IndexError), "repeat walk ran past the resolved table"
    assert not isinstance(result.exc, (AttributeError, KeyError, TypeError)), (
        f"schedule failed while reading the ODS, before the budget could apply: {result.exc}"
    )
    assert result.peak_bytes < MAX_EXPANSION_BYTES, (
        f"allocated {result.peak_bytes} bytes expanding ODS repeats; "
        f"apply the {CELL_BUDGET}-cell budget before building column or row lists"
    )
    if result.exc is not None:
        assert result.svg_bytes is None, "SVG was written before the oversized schedule was refused"
        return
    assert result.rects <= CELL_BUDGET


def test_small_schedule_converts(scheduler, tmp_path: Path) -> None:
    content = _content(_columns([2]), _rows([2], EMPTY_CELL))
    result = _convert(scheduler, tmp_path, "small", content)

    assert result.exc is None
    assert result.svg_bytes is not None
    assert result.rects == 2
    assert result.peak_bytes < MAX_EXPANSION_BYTES


def test_styled_schedule_converts(scheduler, tmp_path: Path) -> None:
    content = _content(
        _columns([1], style_name="co1"),
        _rows([1], EMPTY_CELL, style_name="ro1"),
        styles=COLUMN_STYLE + ROW_STYLE,
    )
    result = _convert(scheduler, tmp_path, "styled-small", content)

    assert result.exc is None
    assert result.rects == 1
    assert result.peak_bytes < MAX_EXPANSION_BYTES


def test_column_repeat_is_not_expanded_past_budget(scheduler, tmp_path: Path) -> None:
    content = _content(_columns([OVERSIZED_REPEAT]), _rows([1], EMPTY_CELL))
    _assert_budget_holds(_convert(scheduler, tmp_path, "columns", content))


def test_styled_column_repeat_with_print_range_is_not_expanded(scheduler, tmp_path: Path) -> None:
    content = _content(
        _columns([OVERSIZED_REPEAT], style_name="co1"),
        _rows([1], EMPTY_CELL),
        styles=COLUMN_STYLE,
        print_range="Sheet1.A1:Sheet1.A1",
    )
    _assert_budget_holds(_convert(scheduler, tmp_path, "styled-columns", content))


def test_row_repeat_is_not_expanded_past_budget(scheduler, tmp_path: Path) -> None:
    content = _content(_columns([1]), _rows([OVERSIZED_REPEAT], EMPTY_CELL))
    _assert_budget_holds(_convert(scheduler, tmp_path, "rows", content))


def test_styled_row_repeat_with_print_range_is_not_expanded(scheduler, tmp_path: Path) -> None:
    content = _content(
        _columns([1]),
        _rows([OVERSIZED_REPEAT], EMPTY_CELL, style_name="ro1"),
        styles=ROW_STYLE,
        print_range="Sheet1.A1:Sheet1.A1",
    )
    _assert_budget_holds(_convert(scheduler, tmp_path, "styled-rows", content))


def test_split_column_repeats_are_budgeted_as_a_total(scheduler, tmp_path: Path) -> None:
    repeats = [REPEAT_PER_PART] * REPEAT_PARTS
    content = _content(_columns(repeats), _rows([1], EMPTY_CELL))
    _assert_budget_holds(_convert(scheduler, tmp_path, "split-columns", content))


def test_split_row_repeats_are_budgeted_as_a_total(scheduler, tmp_path: Path) -> None:
    repeats = [REPEAT_PER_PART] * REPEAT_PARTS
    content = _content(_columns([1]), _rows(repeats, EMPTY_CELL))
    _assert_budget_holds(_convert(scheduler, tmp_path, "split-rows", content))


def test_cell_column_repeat_without_columns_is_not_materialised(scheduler, tmp_path: Path) -> None:
    cell = f'<table:table-cell table:number-columns-repeated="{OVERSIZED_REPEAT}"/>'
    content = _content("", _rows([1], cell))
    _assert_budget_holds(_convert(scheduler, tmp_path, "cell-repeat", content))


def test_cell_span_times_repeat_is_not_materialised(scheduler, tmp_path: Path) -> None:
    cell = '<table:table-cell table:number-columns-spanned="500" table:number-columns-repeated="400"/>'
    content = _content("", _rows([1], cell))
    _assert_budget_holds(_convert(scheduler, tmp_path, "cell-product", content))


def test_cell_column_repeat_does_not_walk_past_resolved_columns(scheduler, tmp_path: Path) -> None:
    cell = f'<table:table-cell table:number-columns-repeated="{OVERSIZED_REPEAT}"/>'
    content = _content(_columns([1]), _rows([1], cell))
    _assert_budget_holds(_convert(scheduler, tmp_path, "cell-walk", content))


def test_row_and_column_product_over_budget_is_refused(scheduler, tmp_path: Path) -> None:
    content = _content(_columns([200]), _rows([200], EMPTY_CELL))
    result = _convert(scheduler, tmp_path, "product", content)
    _assert_budget_holds(result)
    assert result.exc is not None
    assert result.rects == 0
