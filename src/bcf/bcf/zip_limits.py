# This file was generated with the assistance of an AI coding tool.
"""Bounded reads of BCF zip archive members."""

from __future__ import annotations

import os
import weakref
import zipfile

MAX_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100

# Bytes still allowed to be decompressed from each open archive. Members can be
# referenced (and so read) any number of times, so the per-member caps alone do
# not bound the total.
_remaining: weakref.WeakKeyDictionary[zipfile.ZipFile, int] = weakref.WeakKeyDictionary()


class ZipMemberTooLargeError(zipfile.BadZipFile):
    """A zip member expands beyond what a BCF file is allowed to contain."""


def _archive_size(zip_file: zipfile.ZipFile) -> int:
    try:
        return os.fstat(zip_file.fp.fileno()).st_size
    except (AttributeError, OSError, ValueError):
        return sum(info.compress_size for info in zip_file.infolist())


def read_member(zip_file: zipfile.ZipFile, name: str) -> bytes:
    """Read a member, refusing it before decompression if it exceeds the limits."""
    info = zip_file.getinfo(name)
    size = info.file_size
    if size > MAX_UNCOMPRESSED_BYTES:
        raise ZipMemberTooLargeError(f"{name}: {size} bytes exceeds the {MAX_UNCOMPRESSED_BYTES} byte limit")
    if size > MAX_COMPRESSION_RATIO * info.compress_size:
        raise ZipMemberTooLargeError(f"{name}: compression ratio exceeds {MAX_COMPRESSION_RATIO}")
    remaining = _remaining.get(zip_file)
    if remaining is None:
        remaining = MAX_COMPRESSION_RATIO * _archive_size(zip_file)
    if size > remaining:
        raise ZipMemberTooLargeError(f"{name}: archive expands more than {MAX_COMPRESSION_RATIO} times its size")
    _remaining[zip_file] = remaining - size
    with zip_file.open(info) as member:
        data = member.read(size + 1)
    if len(data) > size:
        raise ZipMemberTooLargeError(f"{name}: member is larger than its declared size")
    return data


def read_path(path: zipfile.Path) -> bytes:
    """Bounded equivalent of ``zipfile.Path.read_bytes``."""
    if path.is_dir():
        raise IsADirectoryError(path)
    if not path.exists():
        raise FileNotFoundError(path)
    return read_member(path.root, path.at)
