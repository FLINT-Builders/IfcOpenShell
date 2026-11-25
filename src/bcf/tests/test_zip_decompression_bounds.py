# This file was generated with the assistance of an AI coding tool.
"""BCF zip reads must refuse a decompression bomb before allocating it.

Opening a BCF follows ``bcf.bcfxml.load`` (Bonsai's BCF panel calls that with
the path the user selected) and then reads more zip members while topics,
documents, snippets, and viewpoints are loaded or saved. Those reads go through
``zipfile.ZipFile.read`` and ``zipfile.Path.read_bytes``, which materialise the
whole uncompressed member.

The limits below are the contract:

- Refuse a member whose declared uncompressed size is greater than
  ``MAX_UNCOMPRESSED_BYTES`` (8 MiB).
- Refuse a member whose declared ratio of uncompressed size to compressed size
  is greater than ``MAX_COMPRESSION_RATIO`` (100). A 64 KiB deflate of NUL
  bytes is about 840:1 and must be refused, while 64 KiB of incompressible
  data must still load. The size cap therefore has to be above 64 KiB and at
  most 8 MiB, and the ratio check has to be separate from it.
- Refuse a member whose deflate stream expands past 8 MiB even when both the
  local header and the central directory claim an uncompressed size of 64
  bytes. Checking ``ZipInfo.file_size`` and then calling ``ZipFile.read``
  still allocates the expanded stream, so the read itself has to be bounded.
- Raising counts only if the allocation stayed under ``PEAK_LIMIT`` and, on
  save, the output file was not created.

These tests fail while that unbounded read is still in place.
"""

from __future__ import annotations

import io
import os
import struct
import tracemalloc
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from xsdata.models.datatype import XmlDateTime

import bcf.bcfxml as bcfxml
import bcf.v2.model as v2
import bcf.v3.model as v3
from bcf.v2.bcfxml import BcfXml as BcfXml2
from bcf.v3.bcfxml import BcfXml as BcfXml3
from bcf.xml_parser import XmlParserSerializer

MAX_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
ACCEPT_BYTES = 64 * 1024
SPOOF_DECLARED_SIZE = 64
# Vulnerable reads of an 8 MiB member peak around 30 MiB. A bounded refusal
# stays well under this, including the XML objects parsed to reach the member.
PEAK_LIMIT = 2 * 1024 * 1024
# A 64 KiB ratio bomb peaks higher than a normal topic parse. Refusal must stay
# under the bomb and above the cost of parsing the small markup that points at it.
RATIO_PEAK_LIMIT = 190 * 1024

TOPIC = "11111111-1111-1111-1111-111111111111"
VIEWPOINT = "22222222-2222-2222-2222-222222222222"
DOCUMENT = "33333333-3333-3333-3333-333333333333"
CREATED = XmlDateTime(2020, 1, 1, 0, 0, 0)

_XML = XmlParserSerializer()


def _xml(obj: object) -> bytes:
    return _XML.serialize(obj).encode()


V3_VERSION = _xml(v3.Version(version_id="3.0"))
V2_VERSION = _xml(v2.Version(version_id="2.1", detailed_version="2.1"))


def _v3_topic(**extra: object) -> v3.Topic:
    fields: dict[str, object] = {
        "title": "T",
        "creation_author": "A",
        "creation_date": CREATED,
        "guid": TOPIC,
        "topic_type": "Issue",
        "topic_status": "Open",
    }
    fields.update(extra)
    return v3.Topic(**fields)  # type: ignore[arg-type]


def _v2_topic(**extra: object) -> v2.Topic:
    fields: dict[str, object] = {
        "title": "T",
        "creation_author": "A",
        "creation_date": CREATED,
        "guid": TOPIC,
    }
    fields.update(extra)
    return v2.Topic(**fields)  # type: ignore[arg-type]


def _members_v3_topic(markup: bytes, extra: list[tuple[str, bytes]] | None = None) -> list[tuple[str, bytes]]:
    members = [("bcf.version", V3_VERSION), (f"{TOPIC}/", b""), (f"{TOPIC}/markup.bcf", markup)]
    if extra:
        members.extend(extra)
    return members


def _members_v2_topic(markup: bytes, extra: list[tuple[str, bytes]] | None = None) -> list[tuple[str, bytes]]:
    members = [("bcf.version", V2_VERSION), (f"{TOPIC}/", b""), (f"{TOPIC}/markup.bcf", markup)]
    if extra:
        members.extend(extra)
    return members


def _point(cls_point: type, cls_direction: type) -> tuple[object, object, object]:
    return cls_point(x=0.0, y=0.0, z=0.0), cls_direction(x=0.0, y=0.0, z=1.0), cls_direction(x=0.0, y=1.0, z=0.0)


def build_v3_version(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    return [("bcf.version", payload)], "bcf.version"


def build_v2_version(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    return [("bcf.version", payload)], "bcf.version"


def build_v3_project(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    return [("bcf.version", V3_VERSION), ("project.bcfp", payload)], "project.bcfp"


def build_v2_project(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    return [("bcf.version", V2_VERSION), ("project.bcfp", payload)], "project.bcfp"


def build_v3_extensions(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    return [("bcf.version", V3_VERSION), ("extensions.xml", payload)], "extensions.xml"


def build_v2_extension_schema(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    project = _xml(v2.ProjectExtension(project=v2.Project(name="P", project_id="p"), extension_schema="extensions.xsd"))
    return [("bcf.version", V2_VERSION), ("project.bcfp", project), ("extensions.xsd", payload)], "extensions.xsd"


def build_v3_markup(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    return _members_v3_topic(payload), f"{TOPIC}/markup.bcf"


def build_v2_markup(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    return _members_v2_topic(payload), f"{TOPIC}/markup.bcf"


def build_v3_snippet(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    markup = _xml(
        v3.Markup(
            topic=_v3_topic(
                bim_snippet=v3.BimSnippet(
                    reference="snip.txt",
                    reference_schema="schema",
                    snippet_type="snip",
                    is_external=False,
                )
            )
        )
    )
    return _members_v3_topic(markup, [(f"{TOPIC}/snip.txt", payload)]), f"{TOPIC}/snip.txt"


def build_v2_snippet(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    markup = _xml(
        v2.Markup(
            topic=_v2_topic(
                bim_snippet=v2.BimSnippet(
                    reference="snip.txt",
                    reference_schema="schema",
                    snippet_type="snip",
                    is_external=False,
                )
            )
        )
    )
    return _members_v2_topic(markup, [(f"{TOPIC}/snip.txt", payload)]), f"{TOPIC}/snip.txt"


def build_v3_reference(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    header = v3.Header(files=v3.HeaderFiles(file=[v3.File(reference="ref.bin", is_external=False)]))
    markup = _xml(v3.Markup(topic=_v3_topic(), header=header))
    return _members_v3_topic(markup, [(f"{TOPIC}/ref.bin", payload)]), f"{TOPIC}/ref.bin"


def build_v2_reference(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    header = v2.Header(file=[v2.HeaderFile(reference="ref.bin", is_external=False)])
    markup = _xml(v2.Markup(topic=_v2_topic(), header=header))
    return _members_v2_topic(markup, [(f"{TOPIC}/ref.bin", payload)]), f"{TOPIC}/ref.bin"


def build_v2_document_reference(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    markup = _xml(
        v2.Markup(
            topic=_v2_topic(
                document_reference=[
                    v2.TopicDocumentReference(referenced_document="doc.bin", is_external=False, guid=DOCUMENT)
                ]
            )
        )
    )
    return _members_v2_topic(markup, [(f"{TOPIC}/doc.bin", payload)]), f"{TOPIC}/doc.bin"


def build_v3_documents_xml(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    return [("bcf.version", V3_VERSION), ("documents.xml", payload)], "documents.xml"


def build_v3_document(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    documents = _xml(
        v3.DocumentInfo(documents=v3.DocumentInfoDocuments(document=[v3.Document(filename="a.bin", guid=DOCUMENT)]))
    )
    name = f"documents/{DOCUMENT}"
    return [("bcf.version", V3_VERSION), ("documents.xml", documents), (name, payload)], name


def _v3_viewpoint_markup(snapshot: str | None) -> bytes:
    viewpoint = v3.ViewPoint(viewpoint="view.bcfv", snapshot=snapshot, guid=VIEWPOINT)
    topic = _v3_topic(viewpoints=v3.TopicViewpoints(view_point=[viewpoint]))
    return _xml(v3.Markup(topic=topic))


def _v2_viewpoint_markup(snapshot: str | None) -> bytes:
    viewpoint = v2.ViewPoint(viewpoint="view.bcfv", snapshot=snapshot, guid=VIEWPOINT)
    return _xml(v2.Markup(topic=_v2_topic(), viewpoints=[viewpoint]))


def build_v3_visinfo(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    name = f"{TOPIC}/view.bcfv"
    return _members_v3_topic(_v3_viewpoint_markup(None), [(name, payload)]), name


def build_v2_visinfo(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    name = f"{TOPIC}/view.bcfv"
    return _members_v2_topic(_v2_viewpoint_markup(None), [(name, payload)]), name


def build_v3_snapshot(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    visinfo = _xml(v3.VisualizationInfo(guid=VIEWPOINT))
    name = f"{TOPIC}/shot.png"
    extra = [(f"{TOPIC}/view.bcfv", visinfo), (name, payload)]
    return _members_v3_topic(_v3_viewpoint_markup("shot.png"), extra), name


def build_v2_snapshot(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    visinfo = _xml(v2.VisualizationInfo(guid=VIEWPOINT))
    name = f"{TOPIC}/shot.png"
    extra = [(f"{TOPIC}/view.bcfv", visinfo), (name, payload)]
    return _members_v2_topic(_v2_viewpoint_markup("shot.png"), extra), name


def build_v3_bitmap(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    location, normal, up = _point(v3.Point, v3.Direction)
    visinfo = _xml(
        v3.VisualizationInfo(
            guid=VIEWPOINT,
            bitmaps=v3.VisualizationInfoBitmaps(
                bitmap=[
                    v3.Bitmap(
                        format=v3.BitmapFormat.PNG,
                        reference="bitmap.png",
                        location=location,  # type: ignore[arg-type]
                        normal=normal,  # type: ignore[arg-type]
                        up=up,  # type: ignore[arg-type]
                        height=1.0,
                    )
                ]
            ),
        )
    )
    name = f"{TOPIC}/bitmap.png"
    extra = [(f"{TOPIC}/view.bcfv", visinfo), (name, payload)]
    return _members_v3_topic(_v3_viewpoint_markup(None), extra), name


def build_v2_bitmap(payload: bytes) -> tuple[list[tuple[str, bytes]], str]:
    location, normal, up = _point(v2.Point, v2.Direction)
    visinfo = _xml(
        v2.VisualizationInfo(
            guid=VIEWPOINT,
            bitmap=[
                v2.VisualizationInfoBitmap(
                    bitmap=v2.BitmapFormat.PNG,
                    reference="bitmap.png",
                    location=location,  # type: ignore[arg-type]
                    normal=normal,  # type: ignore[arg-type]
                    up=up,  # type: ignore[arg-type]
                    height=1.0,
                )
            ],
        )
    )
    name = f"{TOPIC}/bitmap.png"
    extra = [(f"{TOPIC}/view.bcfv", visinfo), (name, payload)]
    return _members_v2_topic(_v2_viewpoint_markup(None), extra), name


def exercise_load(path: Path, _output: Path | None) -> None:
    loaded = bcfxml.load(path)
    if loaded is not None:
        loaded.close()


def exercise_v3_version(path: Path, _output: Path | None) -> None:
    with BcfXml3.load(path) as loaded:
        loaded.version


def exercise_v2_version(path: Path, _output: Path | None) -> None:
    with BcfXml2.load(path) as loaded:
        loaded.version


def exercise_v3_project(path: Path, _output: Path | None) -> None:
    with BcfXml3.load(path) as loaded:
        loaded.project_info


def exercise_v2_project(path: Path, _output: Path | None) -> None:
    with BcfXml2.load(path) as loaded:
        loaded.project_info


def exercise_v3_extensions(path: Path, _output: Path | None) -> None:
    with BcfXml3.load(path) as loaded:
        loaded.extensions


def exercise_v2_extension_schema(path: Path, _output: Path | None) -> None:
    with BcfXml2.load(path) as loaded:
        loaded.extension_schema


def exercise_v3_markup(path: Path, _output: Path | None) -> None:
    with BcfXml3.load(path) as loaded:
        loaded.topics[TOPIC].markup


def exercise_v2_markup(path: Path, _output: Path | None) -> None:
    with BcfXml2.load(path) as loaded:
        loaded.topics[TOPIC].markup


def exercise_v3_snippet(path: Path, _output: Path | None) -> None:
    with BcfXml3.load(path) as loaded:
        loaded.topics[TOPIC].bim_snippet


def exercise_v2_snippet(path: Path, _output: Path | None) -> None:
    with BcfXml2.load(path) as loaded:
        loaded.topics[TOPIC].bim_snippet


def exercise_v3_reference(path: Path, _output: Path | None) -> None:
    with BcfXml3.load(path) as loaded:
        loaded.topics[TOPIC].reference_files


def exercise_v2_reference(path: Path, _output: Path | None) -> None:
    with BcfXml2.load(path) as loaded:
        loaded.topics[TOPIC].reference_files


def exercise_v2_document_reference(path: Path, _output: Path | None) -> None:
    with BcfXml2.load(path) as loaded:
        loaded.topics[TOPIC].document_references


def exercise_v3_documents(path: Path, _output: Path | None) -> None:
    with BcfXml3.load(path) as loaded:
        loaded.documents


def exercise_v3_viewpoints(path: Path, _output: Path | None) -> None:
    with BcfXml3.load(path) as loaded:
        loaded.topics[TOPIC].viewpoints


def exercise_v2_viewpoints(path: Path, _output: Path | None) -> None:
    with BcfXml2.load(path) as loaded:
        loaded.topics[TOPIC].viewpoints


def _save(cls: type, path: Path, output: Path | None) -> None:
    assert output is not None
    with cls.load(path) as loaded:
        loaded.save(output)


def exercise_save_v3(path: Path, output: Path | None) -> None:
    _save(BcfXml3, path, output)


def exercise_save_v2(path: Path, output: Path | None) -> None:
    _save(BcfXml2, path, output)


Build = Callable[[bytes], tuple[list[tuple[str, bytes]], str]]
Exercise = Callable[[Path, Path | None], None]


@dataclass(frozen=True)
class Spec:
    name: str
    build: Build
    exercise: Exercise
    save: bool = False
    kinds: tuple[str, ...] = ("oversized", "spoofed", "ratio")


SPECS: tuple[Spec, ...] = (
    Spec("bcfxml-load-version", build_v3_version, exercise_load, kinds=("oversized", "spoofed", "ratio", "stored")),
    Spec("v3-version", build_v3_version, exercise_v3_version),
    Spec("v2-version", build_v2_version, exercise_v2_version),
    Spec("v3-project", build_v3_project, exercise_v3_project),
    Spec("v2-project", build_v2_project, exercise_v2_project),
    Spec("v3-extensions", build_v3_extensions, exercise_v3_extensions),
    Spec("v2-extension-schema", build_v2_extension_schema, exercise_v2_extension_schema),
    Spec("v3-markup", build_v3_markup, exercise_v3_markup),
    Spec("v2-markup", build_v2_markup, exercise_v2_markup),
    Spec("v3-snippet", build_v3_snippet, exercise_v3_snippet, kinds=("oversized", "spoofed", "ratio", "stored")),
    Spec("v2-snippet", build_v2_snippet, exercise_v2_snippet),
    Spec("v3-reference-file", build_v3_reference, exercise_v3_reference),
    Spec("v2-reference-file", build_v2_reference, exercise_v2_reference),
    Spec("v2-document-reference", build_v2_document_reference, exercise_v2_document_reference),
    Spec("v3-documents-xml", build_v3_documents_xml, exercise_v3_documents),
    Spec("v3-document", build_v3_document, exercise_v3_documents),
    Spec("v3-viewpoint", build_v3_visinfo, exercise_v3_viewpoints),
    Spec("v2-viewpoint", build_v2_visinfo, exercise_v2_viewpoints),
    Spec("v3-snapshot", build_v3_snapshot, exercise_v3_viewpoints),
    Spec("v2-snapshot", build_v2_snapshot, exercise_v2_viewpoints),
    Spec("v3-bitmap", build_v3_bitmap, exercise_v3_viewpoints),
    Spec("v2-bitmap", build_v2_bitmap, exercise_v2_viewpoints),
    Spec("v3-save-project", build_v3_project, exercise_save_v3, save=True),
    Spec("v2-save-project", build_v2_project, exercise_save_v2, save=True),
    Spec("v3-save-version", build_v3_version, exercise_save_v3, save=True),
    Spec("v2-save-version", build_v2_version, exercise_save_v2, save=True),
    Spec("v3-save-extensions", build_v3_extensions, exercise_save_v3, save=True),
    Spec("v2-save-extension-schema", build_v2_extension_schema, exercise_save_v2, save=True),
    Spec("v3-save-markup", build_v3_markup, exercise_save_v3, save=True),
    Spec("v2-save-markup", build_v2_markup, exercise_save_v2, save=True),
    Spec("v3-save-snippet", build_v3_snippet, exercise_save_v3, save=True),
    Spec("v2-save-snippet", build_v2_snippet, exercise_save_v2, save=True),
    Spec("v3-save-document", build_v3_document, exercise_save_v3, save=True),
    Spec("v3-save-reference-file", build_v3_reference, exercise_save_v3, save=True),
    Spec("v2-save-reference-file", build_v2_reference, exercise_save_v2, save=True),
    Spec("v2-save-document-reference", build_v2_document_reference, exercise_save_v2, save=True),
    Spec("v3-save-snapshot", build_v3_snapshot, exercise_save_v3, save=True),
    Spec("v2-save-snapshot", build_v2_snapshot, exercise_save_v2, save=True),
)


def _cases() -> list[tuple[Spec, str]]:
    return [(spec, kind) for spec in SPECS for kind in spec.kinds]


def _payload(kind: str) -> bytes:
    if kind == "ratio":
        return b"\0" * ACCEPT_BYTES
    return b"\0" * (MAX_UNCOMPRESSED_BYTES + 1)


def _write_bcf(path: Path, members: list[tuple[str, bytes]], bomb_name: str, kind: str) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            if kind == "stored" and name == bomb_name:
                info = zipfile.ZipInfo(filename=name)
                info.compress_type = zipfile.ZIP_STORED
                archive.writestr(info, data)
            else:
                archive.writestr(name, data)
    if kind == "spoofed":
        path.write_bytes(_spoof_uncompressed_size(path.read_bytes(), bomb_name, SPOOF_DECLARED_SIZE))


def _spoof_uncompressed_size(blob: bytes, filename: str, declared: int) -> bytes:
    """Claim ``declared`` uncompressed bytes in both headers, leaving the deflate stream unchanged."""
    patched = bytearray(blob)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        info = archive.getinfo(filename)
    local = info.header_offset
    assert patched[local : local + 4] == b"PK\x03\x04"
    struct.pack_into("<I", patched, local + 22, declared)
    name = filename.encode()
    start = 0
    found = False
    while True:
        central = patched.find(b"PK\x01\x02", start)
        assert central >= 0
        name_len = struct.unpack_from("<H", patched, central + 28)[0]
        if patched[central + 46 : central + 46 + name_len] == name:
            struct.pack_into("<I", patched, central + 24, declared)
            found = True
            break
        start = central + 4
    assert found
    return bytes(patched)


def _compressed_payload(path: Path, filename: str) -> tuple[int, bytes]:
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(filename)
        compress_size = info.compress_size
        compress_type = info.compress_type
        header = info.header_offset
    blob = path.read_bytes()
    name_len, extra_len = struct.unpack_from("<HH", blob, header + 26)
    start = header + 30 + name_len + extra_len
    return compress_type, blob[start : start + compress_size]


def _deflate_expands_past(compressed: bytes, limit: int) -> bool:
    decoder = zlib.decompressobj(-15)
    produced = 0
    pending = compressed
    while produced <= limit:
        chunk = decoder.decompress(pending, 256 * 1024)
        pending = decoder.unconsumed_tail
        produced += len(chunk)
        if decoder.eof or not chunk:
            break
    return produced > limit


def _assert_fixture(path: Path, bomb_name: str, kind: str) -> None:
    """The archive is the bomb the assertion describes, before any product code reads it."""
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(bomb_name)
    if kind == "oversized":
        assert info.file_size > MAX_UNCOMPRESSED_BYTES
        assert info.compress_type == zipfile.ZIP_DEFLATED
    elif kind == "stored":
        assert info.file_size > MAX_UNCOMPRESSED_BYTES
        assert info.compress_type == zipfile.ZIP_STORED
        assert info.file_size / max(info.compress_size, 1) <= MAX_COMPRESSION_RATIO
    elif kind == "ratio":
        assert info.file_size <= ACCEPT_BYTES
        assert info.compress_size > 0
        assert info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
    elif kind == "spoofed":
        assert info.file_size == SPOOF_DECLARED_SIZE
        assert info.file_size / max(info.compress_size, 1) <= MAX_COMPRESSION_RATIO
        compress_type, compressed = _compressed_payload(path, bomb_name)
        assert compress_type == zipfile.ZIP_DEFLATED
        assert _deflate_expands_past(compressed, MAX_UNCOMPRESSED_BYTES)
    else:
        raise AssertionError(kind)


def _assert_refuses(fn: Callable[[], None], peak_limit: int, output: Path | None) -> None:
    tracemalloc.start()
    tracemalloc.clear_traces()
    raised = False
    try:
        fn()
    except Exception:
        raised = True
    finally:
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert raised, f"zip member was read without raising (peak={peak} bytes)"
    assert peak < peak_limit, f"allocated {peak} bytes from the zip member; limit is {peak_limit}"
    if output is not None:
        assert not output.exists(), f"{output.name} was created before the member was refused"


@pytest.mark.parametrize(("spec", "kind"), _cases(), ids=lambda item: item if isinstance(item, str) else item.name)
def test_zip_member_is_refused(spec: Spec, kind: str, tmp_path: Path) -> None:
    members, bomb_name = spec.build(_payload(kind))
    source = tmp_path / "input.bcf"
    _write_bcf(source, members, bomb_name, kind)
    _assert_fixture(source, bomb_name, kind)
    output = tmp_path / "out.bcf" if spec.save else None
    limit = RATIO_PEAK_LIMIT if kind == "ratio" else PEAK_LIMIT
    _assert_refuses(lambda: spec.exercise(source, output), limit, output)


def _write_snippet(path: Path, version: bytes, markup: bytes, payload: bytes) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bcf.version", version)
        archive.writestr(f"{TOPIC}/", b"")
        archive.writestr(f"{TOPIC}/markup.bcf", markup)
        archive.writestr(f"{TOPIC}/snip.txt", payload)


def test_incompressible_snippet_still_loads(tmp_path: Path) -> None:
    """A member under both caps still loads, so the fix cannot reject every zip entry."""
    payload = os.urandom(ACCEPT_BYTES)
    markup = _xml(
        v3.Markup(
            topic=_v3_topic(
                bim_snippet=v3.BimSnippet(
                    reference="snip.txt",
                    reference_schema="schema",
                    snippet_type="snip",
                    is_external=False,
                )
            )
        )
    )
    path = tmp_path / "ok.bcf"
    _write_snippet(path, V3_VERSION, markup, payload)
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(f"{TOPIC}/snip.txt")
    assert info.file_size == ACCEPT_BYTES
    assert info.file_size / info.compress_size <= MAX_COMPRESSION_RATIO
    with BcfXml3.load(path) as loaded:
        assert loaded.topics[TOPIC].bim_snippet == payload


def test_small_bcf_still_opens(tmp_path: Path) -> None:
    path = tmp_path / "small.bcf"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("bcf.version", V3_VERSION)
    loaded = bcfxml.load(path)
    assert loaded is not None
    try:
        assert loaded.version.version_id == "3.0"
    finally:
        loaded.close()


def test_v2_incompressible_snippet_still_loads(tmp_path: Path) -> None:
    payload = os.urandom(ACCEPT_BYTES)
    markup = _xml(
        v2.Markup(
            topic=_v2_topic(
                bim_snippet=v2.BimSnippet(
                    reference="snip.txt",
                    reference_schema="schema",
                    snippet_type="snip",
                    is_external=False,
                )
            )
        )
    )
    path = tmp_path / "ok.bcf"
    _write_snippet(path, V2_VERSION, markup, payload)
    with BcfXml2.load(path) as loaded:
        assert loaded.topics[TOPIC].bim_snippet == payload
