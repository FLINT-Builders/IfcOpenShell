# This file was generated with the assistance of an AI coding tool.
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

"""Cost-schedule export must keep files inside the directory the user chose.

IfcCostSchedule.Name is taken from the IFC file. These tests fail while that
text is joined onto the output directory and opened. They pass when a write
outside that directory is refused and no file outside it is created or replaced.
"""

import builtins
import io
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.cost
import ifcopenshell.api.root
import pytest

import ifc5d.ifc5Dspreadsheet as spreadsheet

CANARY = b"CANARY-DO-NOT-OVERWRITE\n"
ITEM_NAME = "ForgedLineItem"
SCRIPT = Path(__file__).resolve().parents[1] / "ifc5d" / "ifc5Dspreadsheet.py"
WRITERS = {
    "CSV": spreadsheet.Ifc5DCsvWriter,
    "ODS": spreadsheet.Ifc5DOdsWriter,
    "XLSX": spreadsheet.Ifc5DXlsxWriter,
}
SUFFIXES = {"CSV": ".csv", "ODS": ".ods", "XLSX": ".xlsx"}


def build_model(directory: Path, schedule_names: list[str]) -> ifcopenshell.file:
    """Write an IFC file and reopen it, so the schedule name comes from the parser."""
    model = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="Tower")
    for schedule_name in schedule_names:
        schedule = ifcopenshell.api.cost.add_cost_schedule(model, name=schedule_name, predefined_type="BUDGET")
        item = ifcopenshell.api.cost.add_cost_item(model, cost_schedule=schedule)
        ifcopenshell.api.cost.edit_cost_item(
            model,
            cost_item=item,
            attributes={"Name": ITEM_NAME, "Identification": "LINE-100"},
        )
    path = directory / "model.ifc"
    model.write(str(path))
    reopened = ifcopenshell.open(str(path))
    reopened_names = [schedule.Name for schedule in reopened.by_type("IfcCostSchedule")]
    assert reopened_names == schedule_names
    return reopened


def tree_snapshot(root: Path) -> dict[str, object]:
    snapshot: dict[str, object] = {}
    if not root.exists():
        return snapshot
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            snapshot[relative] = ("link", os.readlink(path))
        elif path.is_dir():
            snapshot[relative] = ("dir",)
        elif path.is_file():
            snapshot[relative] = ("file", path.read_bytes())
    return snapshot


def plant(root: Path, relative_names: list[str]) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    for relative_name in relative_names:
        target = root / relative_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(CANARY)
    return tree_snapshot(root)


class _OutsideWrites:
    def __init__(
        self,
        export_dir: Path | None,
        retarget: dict[str, object] | None,
        forbid: Path | None,
    ) -> None:
        self.export_real = os.path.realpath(export_dir) if export_dir is not None else None
        self.forbid_real = os.path.realpath(forbid) if forbid is not None else None
        self.retarget = retarget
        self.paths: list[str] = []
        self._swapped = False
        self._original_open = builtins.open
        self._original_os_open = os.open

    def __enter__(self) -> list[str]:
        builtins.open = self._open
        io.open = self._open
        os.open = self._os_open
        return self.paths

    def __exit__(self, exc_type, exc, traceback) -> None:
        builtins.open = self._original_open
        io.open = self._original_open
        os.open = self._original_os_open

    def _consider(self, file: object) -> None:
        if not isinstance(file, (str, bytes, os.PathLike)):
            return
        text = os.fsdecode(os.fspath(file))
        self._swap_link(text)
        resolved = os.path.realpath(text)
        if self._is_forbidden(resolved):
            self.paths.append(resolved)

    def _is_forbidden(self, resolved: str) -> bool:
        if self.forbid_real is not None:
            try:
                return os.path.commonpath([self.forbid_real, resolved]) == self.forbid_real
            except ValueError:
                return False
        try:
            return os.path.commonpath([self.export_real, resolved]) != self.export_real
        except ValueError:
            return True

    def _swap_link(self, text: str) -> None:
        """Point a symlink outside after a containment check would have resolved it."""
        if self.retarget is None or self._swapped:
            return
        if self.retarget["name"] not in Path(text).parts:
            return
        link = Path(self.retarget["link"])
        link.unlink()
        link.symlink_to(self.retarget["dest"], target_is_directory=True)
        self._swapped = True

    def _open(self, file, mode="r", *args, **kwargs):
        mode_text = mode if isinstance(mode, str) else "r"
        if any(flag in mode_text for flag in ("w", "a", "x", "+")):
            self._consider(file)
        return self._original_open(file, mode, *args, **kwargs)

    def _os_open(self, path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd is None and flags & (os.O_WRONLY | os.O_RDWR):
            self._consider(path)
        return self._original_os_open(path, flags, mode, dir_fd=dir_fd)


def assert_export_stays_inside(
    export_dir: Path | None,
    protected: Path,
    before: dict[str, object],
    write: Callable[[], None],
    retarget: dict[str, object] | None = None,
    forbid: Path | None = None,
) -> None:
    with _OutsideWrites(export_dir, retarget, forbid) as outside_writes:
        try:
            write()
        except Exception:
            # Refusing the write is acceptable. A file created first is not.
            pass
    assert outside_writes == []
    assert tree_snapshot(protected) == before


def test_plain_schedule_name_writes_inside_the_export_directory(tmp_path: Path) -> None:
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    model = build_model(tmp_path, ["Tower Budget"])
    spreadsheet.Ifc5DCsvWriter(model, str(export_dir)).write()
    written = list(export_dir.iterdir())
    assert len(written) == 1
    assert written[0].is_file()
    assert os.path.realpath(written[0]).startswith(os.path.realpath(export_dir) + os.sep)
    assert ITEM_NAME.encode() in written[0].read_bytes()


@pytest.mark.parametrize("export_format", ["CSV", "ODS", "XLSX"])
def test_relative_schedule_name_cannot_replace_a_file_outside_the_export_directory(
    tmp_path: Path, export_format: str
) -> None:
    export_dir = tmp_path / "export"
    protected = tmp_path / "vault"
    export_dir.mkdir()
    suffix = SUFFIXES[export_format]
    before = plant(protected, [f"Budget{suffix}"])
    schedule_name = os.path.relpath(protected / "Budget", export_dir)
    model = build_model(tmp_path, [schedule_name])
    writer = WRITERS[export_format](model, str(export_dir))
    assert_export_stays_inside(export_dir, protected, before, writer.write)


@pytest.mark.parametrize("export_format", ["CSV", "ODS", "XLSX"])
def test_relative_schedule_name_cannot_create_a_file_outside_the_export_directory(
    tmp_path: Path, export_format: str
) -> None:
    export_dir = tmp_path / "export"
    protected = tmp_path / "vault"
    export_dir.mkdir()
    protected.mkdir()
    before = tree_snapshot(protected)
    schedule_name = os.path.relpath(protected / "Created", export_dir)
    model = build_model(tmp_path, [schedule_name])
    writer = WRITERS[export_format](model, str(export_dir))
    assert_export_stays_inside(export_dir, protected, before, writer.write)


@pytest.mark.parametrize("export_format", ["CSV", "ODS", "XLSX"])
def test_absolute_schedule_name_cannot_write_outside_the_export_directory(tmp_path: Path, export_format: str) -> None:
    export_dir = tmp_path / "export"
    protected = tmp_path / "vault"
    export_dir.mkdir()
    suffix = SUFFIXES[export_format]
    before = plant(protected, [f"Budget{suffix}"])
    model = build_model(tmp_path, [str(protected / "Budget")])
    writer = WRITERS[export_format](model, str(export_dir))
    assert_export_stays_inside(export_dir, protected, before, writer.write)


def test_duplicate_relative_names_keep_the_csv_suffix_inside_the_export_directory(tmp_path: Path) -> None:
    export_dir = tmp_path / "export"
    protected = tmp_path / "vault"
    export_dir.mkdir()
    before = plant(protected, ["Budget.csv", "Budget_1.csv"])
    schedule_name = os.path.relpath(protected / "Budget", export_dir)
    model = build_model(tmp_path, [schedule_name, schedule_name])
    writer = spreadsheet.Ifc5DCsvWriter(model, str(export_dir))
    assert_export_stays_inside(export_dir, protected, before, writer.write)


@pytest.mark.parametrize("export_format", ["ODS", "XLSX"])
def test_concatenated_schedule_names_cannot_leave_the_export_directory(tmp_path: Path, export_format: str) -> None:
    export_dir = tmp_path / "export"
    protected = tmp_path / "vault"
    export_dir.mkdir()
    suffix = SUFFIXES[export_format]
    before = plant(protected, [f"Budget_Rates{suffix}"])
    traversed = os.path.relpath(protected / "Budget", export_dir)
    model = build_model(tmp_path, [traversed, "Rates"])
    writer = WRITERS[export_format](model, str(export_dir))
    assert_export_stays_inside(export_dir, protected, before, writer.write)


@pytest.mark.parametrize("export_format", ["CSV", "ODS", "XLSX"])
def test_symlink_component_is_not_opened_again_after_a_containment_check(tmp_path: Path, export_format: str) -> None:
    """A check that resolves the path, then opens the original path, still escapes.

    The symlink points inside the export directory while it is resolved. The
    write hook retargets it before the kernel opens the path. Opening the
    already resolved path, or refusing the name, leaves the protected file alone.
    """
    export_dir = tmp_path / "export"
    protected = tmp_path / "vault"
    inbox = export_dir / "inbox"
    export_dir.mkdir()
    inbox.mkdir()
    link = export_dir / "schedule_link"
    link.symlink_to(inbox, target_is_directory=True)
    suffix = SUFFIXES[export_format]
    before = plant(protected, [f"note{suffix}"])
    model = build_model(tmp_path, ["schedule_link/note"])
    writer = WRITERS[export_format](model, str(export_dir))
    assert_export_stays_inside(
        export_dir,
        protected,
        before,
        writer.write,
        retarget={"name": "schedule_link", "link": link, "dest": protected},
    )


@pytest.mark.parametrize("export_format", ["CSV", "ODS", "XLSX"])
def test_cli_schedule_name_cannot_write_outside_the_output_directory(tmp_path: Path, export_format: str) -> None:
    export_dir = tmp_path / "export"
    protected = tmp_path / "vault"
    export_dir.mkdir()
    suffix = SUFFIXES[export_format]
    before = plant(protected, [f"Budget{suffix}"])
    schedule_name = os.path.relpath(protected / "Budget", export_dir)
    build_model(tmp_path, [schedule_name])
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(tmp_path / "model.ifc"),
            str(export_dir),
            "-l",
            str(export_dir / "export.log"),
            "-f",
            export_format,
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert tree_snapshot(protected) == before, completed.stderr


def test_pdf_export_relative_schedule_name_cannot_leave_its_temp_directory(tmp_path: Path) -> None:
    pytest.importorskip("typst")
    controlled_tmp = tmp_path / "tmp"
    protected = controlled_tmp / "escaped"
    controlled_tmp.mkdir()
    before = plant(protected, ["Budget.csv"])
    pdf_path = tmp_path / "schedule.pdf"
    model = build_model(tmp_path, ["../escaped/Budget"])
    schedule = model.by_type("IfcCostSchedule")[0]
    previous_tempdir = tempfile.tempdir
    tempfile.tempdir = str(controlled_tmp)
    try:
        # The PDF writer picks its own temp directory. Only the sibling it can
        # reach with ".." is protected; temp files and the PDF itself may be written.
        assert_export_stays_inside(
            None,
            protected,
            before,
            lambda: spreadsheet.Ifc5DPdfWriter(model, str(pdf_path), {}, schedule).write(),
            forbid=protected,
        )
    finally:
        tempfile.tempdir = previous_tempdir


def test_pdf_export_absolute_schedule_name_cannot_write_a_csv_outside_its_temp_directory(tmp_path: Path) -> None:
    pytest.importorskip("typst")
    export_dir = tmp_path / "export"
    protected = tmp_path / "vault"
    export_dir.mkdir()
    before = plant(protected, ["Budget.csv"])
    model = build_model(tmp_path, [str(protected / "Budget")])
    schedule = model.by_type("IfcCostSchedule")[0]
    writer = spreadsheet.Ifc5DPdfWriter(model, str(export_dir / "schedule.pdf"), {}, schedule)
    # The intermediate CSV is the write that must stay out of the vault. The
    # temporary typst files are created in a temp directory and are allowed.
    assert_export_stays_inside(None, protected, before, writer.write, forbid=protected)
