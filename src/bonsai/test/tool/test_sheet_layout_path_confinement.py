# This file was generated with the assistance of an AI coding tool.
# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
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

"""Sheet and drawing document locations must stay inside the project.

Load Sheets rebuilds a sheet when its first referenced file is missing and
writes the LAYOUT location stored in the IFC. These tests open an IFC the
same way that button does. They fail while a location outside the project,
a symlink to such a location, or an existing non-layout file can be created,
replaced, moved, or deleted.
"""

import tempfile
from pathlib import Path

import bpy
import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.guid
import pytest

import bonsai.core.drawing as core_drawing
import bonsai.tool as tool
from bonsai.bim.module.drawing.sheeter import SheetBuilder
from test.bim.bootstrap import NewFile

ORIGINAL = b"ORIGINAL-SECRET\n"
USER_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" id="user"></svg>\n'
SHEET_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    b'width="10mm" height="10mm" viewBox="0 0 10 10">'
    b'<g data-type="titleblock"><image xlink:href="titleblocks/A1.svg" width="10" height="10"/></g>'
    b"</svg>"
)
DRAWING_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80"></svg>\n'


class TestSheetLayoutPathConfinement(NewFile):
    def _fresh_tree(self) -> tempfile.TemporaryDirectory:
        return tempfile.TemporaryDirectory(prefix="bonsai-sheet-path-")

    def _write_project(self, root: Path, schema: str, populate) -> tuple[Path, ifcopenshell.file]:
        project_dir = root / "project"
        project_dir.mkdir()
        ifc_path = project_dir / "model.ifc"
        ifc = ifcopenshell.file(schema=schema)
        project = ifc.createIfcProject(GlobalId=ifcopenshell.guid.new(), Name="Path confinement")
        populate(ifc, project, project_dir)
        ifc.write(str(ifc_path))
        opened = ifcopenshell.open(str(ifc_path))
        tool.Ifc.set(opened)
        tool.Ifc.set_path(str(ifc_path))
        return project_dir, opened

    def _add_sheet(self, ifc: ifcopenshell.file, references: list[tuple[str, str]]):
        if ifc.schema == "IFC2X3":
            sheet = ifc.createIfcDocumentInformation(DocumentId="A01", Name="Evil", Scope="SHEET")
            sheet.DocumentReferences = [
                ifc.createIfcDocumentReference(ItemReference=str(index), Name=description, Location=location)
                for index, (description, location) in enumerate(references, start=1)
            ]
            return sheet
        sheet = ifc.createIfcDocumentInformation(Identification="A01", Name="Evil", Scope="SHEET")
        for index, (description, location) in enumerate(references, start=1):
            ifc.createIfcDocumentReference(
                Identification=str(index),
                Description=description,
                Location=location,
                ReferencedDocument=sheet,
            )
        return sheet

    def _missing_marker(self, project_dir: Path) -> str:
        return (project_dir / "missing-first.svg").as_posix()

    def _load_sheets(self) -> None:
        result = bpy.ops.bim.load_sheets()
        assert result == {"FINISHED"}

    def _assert_unchanged(self, path: Path) -> None:
        assert path.is_file(), f"{path} is missing"
        assert path.read_bytes() == ORIGINAL, f"{path} was replaced: {path.read_bytes()[:80]!r}"
        assert not path.is_symlink()

    def test_load_sheets_does_not_overwrite_absolute_layout_location(self):
        with self._fresh_tree() as name:
            root = Path(name)
            victim = root / "victim.txt"
            victim.write_bytes(ORIGINAL)

            def populate(ifc, project, project_dir: Path):
                self._add_sheet(
                    ifc,
                    [
                        ("SHEET", self._missing_marker(project_dir)),
                        ("TITLEBLOCK", "layouts/titleblocks/A1.svg"),
                        ("LAYOUT", victim.as_posix()),
                    ],
                )

            self._write_project(root, "IFC4", populate)
            self._load_sheets()
            self._assert_unchanged(victim)

    def test_load_sheets_does_not_overwrite_dotdot_layout_location(self):
        with self._fresh_tree() as name:
            root = Path(name)
            victim = root / "victim.txt"
            victim.write_bytes(ORIGINAL)

            def populate(ifc, project, project_dir: Path):
                self._add_sheet(
                    ifc,
                    [
                        ("SHEET", self._missing_marker(project_dir)),
                        ("TITLEBLOCK", "layouts/titleblocks/A1.svg"),
                        ("LAYOUT", "../victim.txt"),
                    ],
                )

            self._write_project(root, "IFC4", populate)
            self._load_sheets()
            self._assert_unchanged(victim)

    def test_load_sheets_does_not_create_parent_directories_outside_project(self):
        with self._fresh_tree() as name:
            root = Path(name)
            outside = root / "created-outside"
            target = outside / "nested" / "page.svg"

            def populate(ifc, project, project_dir: Path):
                self._add_sheet(
                    ifc,
                    [
                        ("SHEET", self._missing_marker(project_dir)),
                        ("TITLEBLOCK", "layouts/titleblocks/A1.svg"),
                        ("LAYOUT", target.as_posix()),
                    ],
                )

            self._write_project(root, "IFC4", populate)
            self._load_sheets()
            assert not outside.exists(), f"created {outside}"
            assert not target.exists()

    def test_load_sheets_does_not_follow_layout_symlink_outside_project(self):
        with self._fresh_tree() as name:
            root = Path(name)
            victim = root / "victim.txt"
            victim.write_bytes(ORIGINAL)

            def populate(ifc, project, project_dir: Path):
                layouts = project_dir / "layouts"
                layouts.mkdir()
                (layouts / "sheet.svg").symlink_to(victim)
                self._add_sheet(
                    ifc,
                    [
                        ("SHEET", self._missing_marker(project_dir)),
                        ("TITLEBLOCK", "layouts/titleblocks/A1.svg"),
                        ("LAYOUT", "layouts/sheet.svg"),
                    ],
                )

            self._write_project(root, "IFC4", populate)
            self._load_sheets()
            self._assert_unchanged(victim)

    def test_load_sheets_does_not_follow_layouts_directory_symlink(self):
        with self._fresh_tree() as name:
            root = Path(name)
            outside = root / "outside"
            outside.mkdir()
            victim = outside / "victim.txt"
            victim.write_bytes(ORIGINAL)

            def populate(ifc, project, project_dir: Path):
                (project_dir / "layouts").symlink_to(outside, target_is_directory=True)
                self._add_sheet(
                    ifc,
                    [
                        ("SHEET", self._missing_marker(project_dir)),
                        ("TITLEBLOCK", "layouts/titleblocks/A1.svg"),
                        ("LAYOUT", "layouts/victim.txt"),
                    ],
                )

            self._write_project(root, "IFC4", populate)
            self._load_sheets()
            self._assert_unchanged(victim)
            assert not (outside / "titleblocks").exists()

    def test_load_sheets_does_not_overwrite_non_svg_inside_project(self):
        with self._fresh_tree() as name:
            root = Path(name)
            victim_holder: dict[str, Path] = {}

            def populate(ifc, project, project_dir: Path):
                layouts = project_dir / "layouts"
                layouts.mkdir()
                victim = layouts / "report.docx"
                victim.write_bytes(ORIGINAL)
                victim_holder["path"] = victim
                self._add_sheet(
                    ifc,
                    [
                        ("SHEET", self._missing_marker(project_dir)),
                        ("TITLEBLOCK", "layouts/titleblocks/A1.svg"),
                        ("LAYOUT", "layouts/report.docx"),
                    ],
                )

            self._write_project(root, "IFC4", populate)
            self._load_sheets()
            self._assert_unchanged(victim_holder["path"])

    def test_load_sheets_does_not_overwrite_existing_svg_inside_layouts(self):
        with self._fresh_tree() as name:
            root = Path(name)
            victim_holder: dict[str, Path] = {}

            def populate(ifc, project, project_dir: Path):
                layouts = project_dir / "layouts"
                layouts.mkdir()
                victim = layouts / "user-notes.svg"
                victim.write_bytes(USER_SVG)
                victim_holder["path"] = victim
                self._add_sheet(
                    ifc,
                    [
                        ("SHEET", self._missing_marker(project_dir)),
                        ("TITLEBLOCK", "layouts/titleblocks/A1.svg"),
                        ("LAYOUT", "layouts/user-notes.svg"),
                    ],
                )

            self._write_project(root, "IFC4", populate)
            self._load_sheets()
            victim = victim_holder["path"]
            assert victim.is_file()
            assert victim.read_bytes() == USER_SVG

    def test_load_sheets_does_not_delete_layout_when_drawing_file_is_missing(self):
        with self._fresh_tree() as name:
            root = Path(name)
            victim = root / "victim.txt"
            victim.write_bytes(ORIGINAL)

            def populate(ifc, project, project_dir: Path):
                self._add_sheet(
                    ifc,
                    [
                        ("SHEET", self._missing_marker(project_dir)),
                        ("TITLEBLOCK", "layouts/titleblocks/A1.svg"),
                        ("LAYOUT", victim.as_posix()),
                        ("DRAWING", "drawings/PLAN.svg"),
                    ],
                )
                annotation = ifc.createIfcAnnotation(
                    GlobalId=ifcopenshell.guid.new(), Name="PLAN", ObjectType="DRAWING"
                )
                drawing_ref = ifc.createIfcDocumentReference(
                    Identification="D",
                    Description="DRAWING",
                    Location=(project_dir / "drawings" / "PLAN.svg").as_posix(),
                )
                ifc.createIfcRelAssociatesDocument(
                    GlobalId=ifcopenshell.guid.new(),
                    RelatingDocument=drawing_ref,
                    RelatedObjects=[annotation],
                )

            self._write_project(root, "IFC4", populate)
            self._load_sheets()
            self._assert_unchanged(victim)

    def test_load_sheets_does_not_copy_titleblock_outside_project(self):
        with self._fresh_tree() as name:
            root = Path(name)
            outside = root / "titleblock-escape"

            def populate(ifc, project, project_dir: Path):
                pset = ifcopenshell.api.pset.add_pset(ifc, product=project, name="BBIM_Documentation")
                ifcopenshell.api.pset.edit_pset(ifc, pset=pset, properties={"TitleblocksDir": outside.as_posix() + "/"})
                self._add_sheet(
                    ifc,
                    [
                        ("LAYOUT", "layouts/A01 - UNTITLED.svg"),
                        ("TITLEBLOCK", "layouts/titleblocks/A1.svg"),
                    ],
                )

            self._write_project(root, "IFC4", populate)
            self._load_sheets()
            assert not outside.exists(), f"titleblock written to {outside}"

    def test_load_sheets_ifc2x3_does_not_overwrite_absolute_layout_location(self):
        with self._fresh_tree() as name:
            root = Path(name)
            victim = root / "victim.txt"
            victim.write_bytes(ORIGINAL)

            def populate(ifc, project, project_dir: Path):
                self._add_sheet(
                    ifc,
                    [
                        ("SHEET", self._missing_marker(project_dir)),
                        ("TITLEBLOCK", "layouts/titleblocks/A1.svg"),
                        ("LAYOUT", victim.as_posix()),
                    ],
                )

            self._write_project(root, "IFC2X3", populate)
            self._load_sheets()
            self._assert_unchanged(victim)

    def test_load_sheets_creates_missing_svg_inside_layouts_directory(self):
        with self._fresh_tree() as name:
            root = Path(name)
            sentinel = root / "sentinel.txt"
            sentinel.write_bytes(ORIGINAL)
            layout_holder: dict[str, Path] = {}

            def populate(ifc, project, project_dir: Path):
                layout = project_dir / "layouts" / "A01 - UNTITLED.svg"
                layout_holder["path"] = layout
                self._add_sheet(
                    ifc,
                    [
                        ("LAYOUT", "layouts/A01 - UNTITLED.svg"),
                        ("TITLEBLOCK", "layouts/titleblocks/A1.svg"),
                    ],
                )

            self._write_project(root, "IFC4", populate)
            self._load_sheets()
            layout = layout_holder["path"]
            assert layout.is_file()
            assert b"<svg" in layout.read_bytes()
            self._assert_unchanged(sentinel)

    @pytest.mark.parametrize("description", ["LAYOUT", "SHEET", "REVISION", "RASTER"])
    def test_remove_sheet_does_not_delete_unconfined_reference(self, description):
        with self._fresh_tree() as name:
            root = Path(name)
            victim = root / "victim.txt"
            victim.write_bytes(ORIGINAL)

            def populate(ifc, project, project_dir: Path):
                self._add_sheet(ifc, [(description, victim.as_posix())])

            _, opened = self._write_project(root, "IFC4", populate)
            sheet = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SHEET")
            result = bpy.ops.bim.remove_sheet(sheet=sheet.id())
            assert result == {"FINISHED"}
            self._assert_unchanged(victim)

    @pytest.mark.parametrize("description", ["LAYOUT", "SHEET"])
    def test_rename_sheet_does_not_move_unconfined_reference(self, description):
        with self._fresh_tree() as name:
            root = Path(name)
            victim = root / "victim.txt"
            victim.write_bytes(ORIGINAL)

            def populate(ifc, project, project_dir: Path):
                (project_dir / "layouts").mkdir()
                (project_dir / "sheets").mkdir()
                self._add_sheet(ifc, [(description, victim.as_posix())])

            _, opened = self._write_project(root, "IFC4", populate)
            self._load_sheets()
            sheet = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SHEET")
            # Edit Sheet sets the new id and name, then rename_sheet moves LAYOUT and SHEET files.
            core_drawing.rename_sheet(tool.Ifc, tool.Drawing, sheet=sheet, identification="B02", name="Renamed")
            self._assert_unchanged(victim)

    def test_add_drawing_does_not_rewrite_layout_outside_project(self):
        with self._fresh_tree() as name:
            root = Path(name)
            victim = root / "victim.svg"
            victim.write_bytes(USER_SVG)

            def populate(ifc, project, project_dir: Path):
                drawing_path = project_dir / "drawings" / "PLAN.svg"
                drawing_path.parent.mkdir()
                drawing_path.write_bytes(DRAWING_SVG)
                sheet = self._add_sheet(ifc, [("LAYOUT", victim.as_posix())])
                annotation = ifc.createIfcAnnotation(
                    GlobalId=ifcopenshell.guid.new(), Name="PLAN", ObjectType="DRAWING"
                )
                reference = ifc.createIfcDocumentReference(
                    Identification="D",
                    Description="DRAWING",
                    Location=drawing_path.as_posix(),
                    ReferencedDocument=sheet,
                )
                ifc.createIfcRelAssociatesDocument(
                    GlobalId=ifcopenshell.guid.new(),
                    RelatingDocument=reference,
                    RelatedObjects=[annotation],
                )

            _, opened = self._write_project(root, "IFC4", populate)
            sheet = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SHEET")
            annotation = next(item for item in opened.by_type("IfcAnnotation") if item.ObjectType == "DRAWING")
            reference = tool.Drawing.get_drawing_reference(annotation)
            # bim.add_drawing_to_sheet reaches this write after the drawing is selected.
            SheetBuilder().add_drawing(reference, annotation, sheet)
            victim_bytes = victim.read_bytes()
            assert victim_bytes == USER_SVG, victim_bytes[:80]

    def test_remove_drawing_does_not_delete_document_outside_project(self):
        with self._fresh_tree() as name:
            root = Path(name)
            victim = root / "victim.txt"
            victim.write_bytes(ORIGINAL)

            def populate(ifc, project, project_dir: Path):
                annotation = ifc.createIfcAnnotation(
                    GlobalId=ifcopenshell.guid.new(), Name="PLAN", ObjectType="DRAWING"
                )
                information = ifc.createIfcDocumentInformation(Identification="D", Name="PLAN", Scope="DRAWING")
                reference = ifc.createIfcDocumentReference(
                    Identification="D",
                    Description="DRAWING",
                    Location=victim.as_posix(),
                    ReferencedDocument=information,
                )
                ifc.createIfcRelAssociatesDocument(
                    GlobalId=ifcopenshell.guid.new(),
                    RelatingDocument=reference,
                    RelatedObjects=[annotation],
                )

            _, opened = self._write_project(root, "IFC4", populate)
            annotation = next(item for item in opened.by_type("IfcAnnotation") if item.ObjectType == "DRAWING")
            # bim.remove_drawing calls this with the selected drawing and no path check.
            core_drawing.remove_drawing(tool.Ifc, tool.Drawing, drawing=annotation)
            self._assert_unchanged(victim)

    def test_update_drawing_name_does_not_move_document_outside_project(self):
        with self._fresh_tree() as name:
            root = Path(name)
            victim = root / "victim.txt"
            victim.write_bytes(ORIGINAL)

            def populate(ifc, project, project_dir: Path):
                (project_dir / "drawings").mkdir()
                annotation = ifc.createIfcAnnotation(GlobalId=ifcopenshell.guid.new(), Name="OLD", ObjectType="DRAWING")
                group = ifc.createIfcGroup(GlobalId=ifcopenshell.guid.new(), Name="OLD", ObjectType="DRAWING")
                ifc.createIfcRelAssignsToGroup(
                    GlobalId=ifcopenshell.guid.new(), RelatingGroup=group, RelatedObjects=[annotation]
                )
                information = ifc.createIfcDocumentInformation(Identification="D", Name="OLD", Scope="DRAWING")
                reference = ifc.createIfcDocumentReference(
                    Identification="D",
                    Description="DRAWING",
                    Location=victim.as_posix(),
                    ReferencedDocument=information,
                )
                ifc.createIfcRelAssociatesDocument(
                    GlobalId=ifcopenshell.guid.new(),
                    RelatingDocument=reference,
                    RelatedObjects=[annotation],
                )

            _, opened = self._write_project(root, "IFC4", populate)
            annotation = next(item for item in opened.by_type("IfcAnnotation") if item.ObjectType == "DRAWING")
            # Renaming a drawing in the list calls this with the stored location.
            core_drawing.update_drawing_name(tool.Ifc, tool.Drawing, drawing=annotation, name="NEW")
            self._assert_unchanged(victim)

    def _sheet_with_layout(self, ifc, project_dir: Path, layout: Path):
        return self._add_sheet(ifc, [("LAYOUT", layout.as_posix()), ("TITLEBLOCK", "layouts/titleblocks/A1.svg")])

    def test_sheet_builder_remove_drawing_does_not_rewrite_layout_outside_project(self):
        with self._fresh_tree() as name:
            root = Path(name)
            victim = root / "victim.svg"
            victim.write_bytes(USER_SVG)

            def populate(ifc, project, project_dir: Path):
                sheet = self._sheet_with_layout(ifc, project_dir, victim)
                ifc.createIfcDocumentReference(
                    Identification="D", Description="DRAWING", Location="drawings/PLAN.svg", ReferencedDocument=sheet
                )

            _, opened = self._write_project(root, "IFC4", populate)
            sheet = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SHEET")
            reference = next(ref for ref in tool.Drawing.get_document_references(sheet) if ref.Description == "DRAWING")
            SheetBuilder().remove_drawing(reference, sheet)
            assert victim.read_bytes() == USER_SVG

    def test_update_sheet_drawing_sizes_does_not_rewrite_layout_outside_project(self):
        with self._fresh_tree() as name:
            root = Path(name)
            victim = root / "victim.svg"
            victim.write_bytes(USER_SVG)

            def populate(ifc, project, project_dir: Path):
                self._sheet_with_layout(ifc, project_dir, victim)

            _, opened = self._write_project(root, "IFC4", populate)
            sheet = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SHEET")
            SheetBuilder().update_sheet_drawing_sizes(sheet)
            assert victim.read_bytes() == USER_SVG

    def test_change_titleblock_does_not_rewrite_layout_outside_project(self):
        with self._fresh_tree() as name:
            root = Path(name)
            victim = root / "victim.svg"
            victim.write_bytes(SHEET_SVG)

            def populate(ifc, project, project_dir: Path):
                self._sheet_with_layout(ifc, project_dir, victim)

            _, opened = self._write_project(root, "IFC4", populate)
            sheet = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SHEET")
            SheetBuilder().change_titleblock(sheet, "A1")
            assert victim.read_bytes() == SHEET_SVG

    def test_add_document_does_not_rewrite_layout_outside_project(self):
        with self._fresh_tree() as name:
            root = Path(name)
            outside = root / "outside"
            outside.mkdir()
            victim = outside / "victim.svg"
            victim.write_bytes(USER_SVG)

            def populate(ifc, project, project_dir: Path):
                schedule_path = project_dir / "schedules" / "door.svg"
                schedule_path.parent.mkdir()
                schedule_path.write_bytes(DRAWING_SVG)
                sheet = self._sheet_with_layout(ifc, project_dir, victim)
                ifc.createIfcDocumentInformation(
                    Identification="S", Name="Door", Scope="SCHEDULE", Location=schedule_path.as_posix()
                )
                ifc.createIfcDocumentReference(
                    Identification="S",
                    Description="SCHEDULE",
                    Location=schedule_path.as_posix(),
                    ReferencedDocument=sheet,
                )

            _, opened = self._write_project(root, "IFC4", populate)
            sheet = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SHEET")
            schedule = next(doc for doc in opened.by_type("IfcDocumentInformation") if doc.Scope == "SCHEDULE")
            reference = next(
                ref for ref in tool.Drawing.get_document_references(sheet) if ref.Description == "SCHEDULE"
            )
            SheetBuilder().add_document(reference, schedule, sheet)
            assert victim.read_bytes() == USER_SVG
            assert not (outside / "assets").exists()
