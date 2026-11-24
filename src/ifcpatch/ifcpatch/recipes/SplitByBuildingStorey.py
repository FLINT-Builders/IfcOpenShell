# IfcPatch - IFC patching utiliy
# Copyright (C) 2020, 2021 Dion Moult <dion@thinkmoult.com>
#
# This file is part of IfcPatch.
#
# IfcPatch is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcPatch is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcPatch.  If not, see <http://www.gnu.org/licenses/>.

import logging
import os
import re
from pathlib import Path
from typing import Union

import ifcopenshell


class Patcher:
    def __init__(self, file: ifcopenshell.file, logger: logging.Logger, output_dir: Union[str, None] = None):
        """Split an IFC model into multiple models based on building storey

        The new IFC model names will be named after the storey name in the
        format of {i}-{name}.ifc, where {i} is an ascending number starting from
        0 and {name} is the name of the storey.

        :param output_dir: Specifies an output directory where the new IFC models will be saved.
        :filter_glob output_dir: *.ifc;*.ifczip;*.ifcxml

        Example:

        .. code:: python

            ifcpatch.execute({"input": "input.ifc", "file": model, "recipe": "SplitByBuildingStorey", "arguments": ["C:/.../output_files"]})
        """
        self.file = file
        self.logger = logger
        self.output_dir = output_dir

    def patch(self) -> None:
        import tempfile

        if self.output_dir is None:
            output_dir = Path()
        else:
            output_dir = Path(self.output_dir)
            if output_dir.is_file():
                raise ValueError(f"Provided path is a file, not a directory: {output_dir}")
            output_dir.mkdir(parents=True, exist_ok=True)

        temp_file = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
        self.file.write(temp_file.name)

        # Storey names are untrusted, so outputs are created by name relative to
        # this one directory handle rather than through a re-resolved path.
        dir_fd = None
        if os.open in os.supports_dir_fd:
            dir_fd = os.open(output_dir, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            self.split(temp_file.name, output_dir, dir_fd)
        finally:
            if dir_fd is not None:
                os.close(dir_fd)

        temp_file.close()
        os.unlink(temp_file.name)

    def split(self, source: str, output_dir: Path, dir_fd: Union[int, None]) -> None:
        storeys = self.file.by_type("IfcBuildingStorey")
        for i, storey in enumerate(storeys):
            filename = f"{i}-{self.get_safe_filename_component(storey.Name)}.ifc"
            old_ifc: ifcopenshell.file = ifcopenshell.open(source)
            new_ifc = ifcopenshell.file(schema=self.file.schema)

            if self.file.schema == "IFC2X3":
                elements = old_ifc.by_type("IfcProject") + old_ifc.by_type("IfcProduct")
            else:
                elements = old_ifc.by_type("IfcContext") + old_ifc.by_type("IfcProduct")

            inverse_elements: list[ifcopenshell.entity_instance] = []
            for element in elements:
                if element.is_a("IfcElement") and not self.is_in_storey(element, storey):
                    element.Representation = None
                    continue
                if element.is_a("IfcElement"):
                    styled_rep_items = [
                        i for i in old_ifc.traverse(element) if i.is_a("IfcRepresentationItem") and i.StyledByItem
                    ]
                    [new_ifc.add(i.StyledByItem[0]) for i in styled_rep_items]
                new_ifc.add(element)
                inverse_elements.extend(old_ifc.get_inverse(element))
            for inverse_element in inverse_elements:
                new_ifc.add(inverse_element)
            for element in new_ifc.by_type("IfcElement"):
                if not self.is_in_storey(element, storey):
                    new_ifc.remove(element)
            self.write_new_file(new_ifc, output_dir, filename, dir_fd)

    def get_safe_filename_component(self, name: Union[str, None]) -> str:
        return re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", str(name))

    def write_new_file(self, new_ifc: ifcopenshell.file, output_dir: Path, filename: str, dir_fd: Union[int, None]):
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        if dir_fd is None:
            fd = os.open(output_dir / filename, flags, 0o666)
        else:
            fd = os.open(filename, flags, 0o666, dir_fd=dir_fd)
        with os.fdopen(fd, "wb") as f:
            f.write(new_ifc.to_string().encode("utf-8"))

    def is_in_storey(self, element: ifcopenshell.entity_instance, storey: ifcopenshell.entity_instance) -> bool:
        return (
            (contained_in_structure := element.ContainedInStructure)
            and (relating_structure := contained_in_structure[0].RelatingStructure).is_a("IfcBuildingStorey")
            and relating_structure.GlobalId == storey.GlobalId
        )
