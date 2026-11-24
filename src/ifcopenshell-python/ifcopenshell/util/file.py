# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
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

import io
import os
import zipfile
from typing import IO, TypedDict, Union

from typing_extensions import NotRequired

import ifcopenshell

DEFAULT_MAX_UNCOMPRESSED_BYTES = 1024**3
DEFAULT_MAX_COMPRESSION_RATIO = 100


class _LimitedReader(io.RawIOBase):
    def __init__(self, member: IO[bytes], limit: int, name: str):
        self.member = member
        self.remaining = limit
        self.member_name = name

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        data = self.member.read(min(len(buffer), self.remaining + 1))
        if len(data) > self.remaining:
            raise ifcopenshell.DecompressionLimitError(
                f"Zip member '{self.member_name}' inflates past its declared size."
            )
        self.remaining -= len(data)
        buffer[: len(data)] = data
        return len(data)

    def close(self) -> None:
        self.member.close()
        super().close()


def open_zip_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    archive_size: int,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_compression_ratio: int = DEFAULT_MAX_COMPRESSION_RATIO,
) -> IO[bytes]:
    """Open a zip member for reading after checking it against decompression limits

    The member is refused before any of it is read if its declared uncompressed
    size exceeds ``max_uncompressed_bytes``, or if its declared size divided by
    its compressed size exceeds ``max_compression_ratio``. The returned stream
    also stops with an error if the member inflates past its declared size.

    :param archive_size: Size in bytes of the archive file ``archive`` reads from.
        A member claiming more compressed bytes than the archive holds is refused.
    :raises ifcopenshell.DecompressionLimitError: If a limit is exceeded.
    """
    if info.file_size > max_uncompressed_bytes:
        raise ifcopenshell.DecompressionLimitError(
            f"Zip member '{info.filename}' declares {info.file_size} uncompressed bytes, "
            f"more than the limit of {max_uncompressed_bytes}."
        )
    if info.compress_size > archive_size or info.file_size > max_compression_ratio * info.compress_size:
        raise ifcopenshell.DecompressionLimitError(
            f"Zip member '{info.filename}' exceeds the compression ratio limit of {max_compression_ratio}."
        )
    return io.BufferedReader(_LimitedReader(archive.open(info), info.file_size, info.filename))


class HeaderMetadata(TypedDict):
    name: NotRequired[str]
    # FILE_DESCRIPTION, not the description from FILE_NAME.
    description: NotRequired[str]
    implementation_level: NotRequired[str]
    time_stamp: NotRequired[str]
    schema_name: NotRequired[str]


class IfcHeaderExtractor:
    """An utility class for extracting header information from IFC files.

    This class provides functionality to extract key metadata from the header section of
    IFC files without recreating the entire file as `ifcopenshell.file`.
    For optimization, extractor will search only for the first 50 lines
    of the IFC file for metadata.

    Supported formats: .ifc, .ifczip.

    Metadata available by the extraction is presented in the example below.


    Example:

    .. code:: python

        from ifcopenshell.util.file import IfcHeaderExtractor

        extractor = IfcHeaderExtractor("path/to/your/file.ifc")
        # Get dictionary of the extracted metadata.
        header_info = extractor.extract()

        # Print the extracted information

        # ViewDefinition[DesignTransferView]
        print("File Description:", header_info.get("description"))

        # 2;1
        print("Implementation Level:", header_info.get("implementation_level"))

        # file.ifc
        print("File Name:", header_info.get("name"))

        # 2024-06-25T15:48:10+05:00
        print("Time Stamp:", header_info.get("time_stamp"))

        # IFC4X3_ADD2
        print("Schema Name:", header_info.get("schema_name"))
    """

    def __init__(
        self,
        filepath: str,
        max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
        max_compression_ratio: int = DEFAULT_MAX_COMPRESSION_RATIO,
    ):
        """
        :param max_uncompressed_bytes: Largest uncompressed size accepted for the
            member read from an .ifczip archive.
        :param max_compression_ratio: Largest uncompressed to compressed size ratio
            accepted for the member read from an .ifczip archive.
        """
        self.filepath = filepath
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_compression_ratio = max_compression_ratio

    def extract(self) -> HeaderMetadata:
        extension = self.filepath.split(".")[-1]
        if extension.lower() == "ifc":
            with open(self.filepath) as ifc_file:
                return self.extract_ifc_spf(ifc_file)
        elif extension.lower() == "ifczip":
            return self.extract_ifc_zip()
        elif extension.lower() == "ifcsqlite":
            return {}  # TODO
        raise ValueError(f"Unsupported file extension: '{extension}'.")

    def extract_ifc_spf(self, ifc_file: Union[IO[bytes], IO[str]]) -> HeaderMetadata:
        # https://www.steptools.com/stds/step/IS_final_p21e3.html#clause-8
        data = HeaderMetadata()
        max_lines_to_parse = 50
        for _ in range(max_lines_to_parse):
            line = next(ifc_file)
            if isinstance(line, bytes):
                line = line.decode("utf-8")
            if line.startswith("FILE_DESCRIPTION"):
                for i, part in enumerate(line.split("'")):
                    if i == 1:
                        data["description"] = part
                    elif i == 3:
                        data["implementation_level"] = part
            elif line.startswith("FILE_NAME"):
                for i, part in enumerate(line.split("'")):
                    if i == 1:
                        data["name"] = part
                    elif i == 3:
                        data["time_stamp"] = part
            elif line.startswith("FILE_SCHEMA"):
                data["schema_name"] = line.split("'")[1]
                break
        return data

    def extract_ifc_zip(self) -> HeaderMetadata:
        with open(self.filepath, "rb") as archive_file, zipfile.ZipFile(archive_file) as archive:
            archive_size = os.fstat(archive_file.fileno()).st_size
            with open_zip_member(
                archive,
                archive.filelist[0],
                archive_size,
                self.max_uncompressed_bytes,
                self.max_compression_ratio,
            ) as member:
                return self.extract_ifc_spf(member)
