# This file was generated with the assistance of an AI coding tool.
"""Path traversal when extracting BCF header files and v3 documents.

These tests load a BCF archive through ``bcf.bcfxml.load`` (the loader Bonsai
uses) and call ``bcf.agnostic.topic.extract_file`` with the same arguments as
``LoadBcfHeaderIfcFile`` and ``ExtractBcfFile``. They fail while the filename
from the BCF XML is joined onto the temporary directory and opened.

The safe result is a file whose name is ``Path(filename).name``, stored as a
direct child of the directory created for that extraction, and nowhere else.
``''``, ``'.'`` and ``'..'`` are not usable names: the bytes must still be
written under a generated name inside that directory. A check that accepts a
sanitized path and then opens the original path still fails, because the
assertions look at the file that was created.
"""

from __future__ import annotations

import tempfile
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

import bcf.agnostic.topic
import bcf.bcfxml
import bcf.v2.model

PAYLOAD_PREFIX = b"bcf-extract-traversal-payload:"
TOPIC_GUID = "7ddc3ef0-0ab7-43f1-918a-45e38b42369c"
DOCUMENT_GUID = "b1d1b7f0-60b9-457d-ad12-16e0fb997bc5"
REFERENCE_GUID = "048e898f-555f-47c3-a273-6c664fb2ef69"
INTERNAL_REFERENCE = "payload.bin"


@pytest.fixture
def recorded_temp_dirs(tmp_path, monkeypatch):
    system_temp = tmp_path / "system-temp"
    system_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(system_temp))
    created: list[Path] = []
    real_mkdtemp = tempfile.mkdtemp

    def recording_mkdtemp(*args, **kwargs):
        directory = real_mkdtemp(*args, **kwargs)
        created.append(Path(directory))
        return directory

    monkeypatch.setattr(tempfile, "mkdtemp", recording_mkdtemp)
    return created


def _header_files(topic):
    # Same selection as bonsai.tool.bcf.Bcf.get_topic_header_files.
    header = topic.header
    assert header is not None
    if isinstance(header, bcf.v2.model.Header):
        return header.file
    files = header.files
    assert files is not None
    return files.file


def _v3_document_references(topic):
    # Same selection as bonsai.tool.bcf.Bcf.get_topic_document_references.
    document_references = topic.topic.document_references
    assert document_references is not None
    return document_references.document_reference


def _write_bcf(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def _v2_header_bcf(directory: Path, filename: str, payload: bytes) -> Path:
    markup = f"""<?xml version="1.0" encoding="utf-8"?>
<Markup>
  <Header>
    <File isExternal="false">
      <Filename>{escape(filename)}</Filename>
      <Reference>{INTERNAL_REFERENCE}</Reference>
    </File>
  </Header>
  <Topic Guid="{TOPIC_GUID}">
    <Title>Traversal</Title>
    <CreationDate>2015-06-21T12:00:00Z</CreationDate>
    <CreationAuthor>author@example.com</CreationAuthor>
  </Topic>
</Markup>
"""
    bcf_path = directory / "header-v2.bcf"
    _write_bcf(
        bcf_path,
        {
            "bcf.version": b'<Version VersionId="2.1"/>',
            f"{TOPIC_GUID}/markup.bcf": markup.encode(),
            f"{TOPIC_GUID}/{INTERNAL_REFERENCE}": payload,
        },
    )
    return bcf_path


def _v3_header_bcf(directory: Path, filename: str, payload: bytes) -> Path:
    markup = f"""<?xml version="1.0" encoding="utf-8"?>
<Markup>
  <Header>
    <Files>
      <File IsExternal="false">
        <Filename>{escape(filename)}</Filename>
        <Reference>{INTERNAL_REFERENCE}</Reference>
      </File>
    </Files>
  </Header>
  <Topic Guid="{TOPIC_GUID}" TopicType="ERROR" TopicStatus="OPEN">
    <Title>Traversal</Title>
    <CreationDate>2021-02-17T09:16:04.160Z</CreationDate>
    <CreationAuthor>author@example.com</CreationAuthor>
  </Topic>
</Markup>
"""
    bcf_path = directory / "header-v3.bcf"
    _write_bcf(
        bcf_path,
        {
            "bcf.version": b'<Version VersionId="3.0"/>',
            f"{TOPIC_GUID}/markup.bcf": markup.encode(),
            f"{TOPIC_GUID}/{INTERNAL_REFERENCE}": payload,
        },
    )
    return bcf_path


def _v3_document_bcf(directory: Path, filename: str, payload: bytes) -> Path:
    markup = f"""<?xml version="1.0" encoding="utf-8"?>
<Markup>
  <Topic Guid="{TOPIC_GUID}" TopicType="ERROR" TopicStatus="OPEN">
    <Title>Traversal</Title>
    <CreationDate>2021-02-17T09:16:04.160Z</CreationDate>
    <CreationAuthor>author@example.com</CreationAuthor>
    <DocumentReferences>
      <DocumentReference Guid="{REFERENCE_GUID}">
        <DocumentGuid>{DOCUMENT_GUID}</DocumentGuid>
        <Description>attachment</Description>
      </DocumentReference>
    </DocumentReferences>
  </Topic>
</Markup>
"""
    documents = f"""<?xml version="1.0" encoding="utf-8"?>
<DocumentInfo>
  <Documents>
    <Document Guid="{DOCUMENT_GUID}">
      <Filename>{escape(filename)}</Filename>
    </Document>
  </Documents>
</DocumentInfo>
"""
    bcf_path = directory / "document-v3.bcf"
    _write_bcf(
        bcf_path,
        {
            "bcf.version": b'<Version VersionId="3.0"/>',
            f"{TOPIC_GUID}/markup.bcf": markup.encode(),
            "documents.xml": documents.encode(),
            f"documents/{DOCUMENT_GUID}": payload,
        },
    )
    return bcf_path


def _payload_files(root: Path, payload: bytes) -> list[Path]:
    found = []
    for path in root.rglob("*"):
        if path.is_file() and path.read_bytes() == payload:
            found.append(path.resolve())
    return found


def _assert_contained(tmp_path: Path, directory: Path, payload: bytes, requested_filename: str, result) -> None:
    """Fail if the payload was written outside ``directory``, including when a sanitized path was checked first."""
    requested_name = Path(requested_filename).name
    outside = [path for path in _payload_files(tmp_path, payload) if not path.is_relative_to(directory.resolve())]
    assert outside == [], f"payload written outside {directory}: {outside}"

    assert isinstance(result, Path), result
    written = result.resolve()
    assert written.is_file()
    assert written.read_bytes() == payload
    assert written.is_relative_to(directory.resolve())
    assert written.parent.resolve() == directory.resolve()
    assert written.name not in {"", ".", ".."}
    if requested_name not in {"", ".", ".."}:
        assert written.name == requested_name
    else:
        assert written.name != requested_name


def _extract(topic, entity, bcfxml, pass_bcfxml: bool):
    if pass_bcfxml:
        # ExtractBcfFile.execute passes the loaded BCF as the third argument.
        return bcf.agnostic.topic.extract_file(topic, entity, bcfxml)
    # LoadBcfHeaderIfcFile.execute calls extract_file with the topic and header file only.
    return bcf.agnostic.topic.extract_file(topic, entity)


@pytest.mark.parametrize("version", ["2.1", "3.0"])
@pytest.mark.parametrize("pass_bcfxml", [False, True])
@pytest.mark.parametrize(
    "filename_case",
    ["absolute", "parent_segment", "dot_parent_segment", "two_parent_segments", "dot", "dotdot", "nested_dotdot"],
)
def test_header_filename_is_contained_in_the_temp_directory(
    tmp_path, recorded_temp_dirs, version, pass_bcfxml, filename_case
):
    payload = PAYLOAD_PREFIX + f"header-{version}-{filename_case}-{pass_bcfxml}".encode()
    if filename_case == "absolute":
        # The destination directory already exists, as a Startup folder would.
        filename = str(tmp_path / "escaped" / f"header-{version}.bin")
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
    elif filename_case == "parent_segment":
        filename = f"../header-{version}-parent.bin"
    elif filename_case == "dot_parent_segment":
        filename = f"./../header-{version}-dot-parent.bin"
    elif filename_case == "two_parent_segments":
        filename = f"../../header-{version}-up-two.bin"
    elif filename_case == "dot":
        filename = "."
    elif filename_case == "dotdot":
        filename = ".."
    else:
        filename = "reports/.."

    work = tmp_path / "bcf"
    work.mkdir()
    if version == "2.1":
        bcf_path = _v2_header_bcf(work, filename, payload)
    else:
        bcf_path = _v3_header_bcf(work, filename, payload)

    before = len(recorded_temp_dirs)
    with bcf.bcfxml.load(bcf_path) as bcfxml:
        assert bcfxml is not None
        topic = bcfxml.topics[TOPIC_GUID]
        entity = _header_files(topic)[0]
        assert entity.filename == filename
        assert entity.is_external is False
        assert topic.reference_files[INTERNAL_REFERENCE] == payload
        try:
            result = _extract(topic, entity, bcfxml, pass_bcfxml)
        except OSError as caught:
            result = caught
    assert len(recorded_temp_dirs) == before + 1
    directory = recorded_temp_dirs[-1]
    _assert_contained(tmp_path, directory, payload, filename, result)


@pytest.mark.parametrize(
    "filename_case",
    ["absolute", "parent_segment", "dot_parent_segment", "two_parent_segments", "dot", "dotdot", "nested_dotdot"],
)
def test_v3_document_filename_is_contained_in_the_temp_directory(tmp_path, recorded_temp_dirs, filename_case):
    payload = PAYLOAD_PREFIX + f"document-{filename_case}".encode()
    if filename_case == "absolute":
        filename = str(tmp_path / "escaped" / f"document-{uuid.uuid4().hex}.bin")
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
    elif filename_case == "parent_segment":
        filename = "../document-parent.bin"
    elif filename_case == "dot_parent_segment":
        filename = "./../document-dot-parent.bin"
    elif filename_case == "two_parent_segments":
        filename = "../../document-up-two.bin"
    elif filename_case == "dot":
        filename = "."
    elif filename_case == "dotdot":
        filename = ".."
    else:
        filename = "reports/.."

    work = tmp_path / "bcf"
    work.mkdir()
    bcf_path = _v3_document_bcf(work, filename, payload)

    before = len(recorded_temp_dirs)
    with bcf.bcfxml.load(bcf_path) as bcfxml:
        assert bcfxml is not None
        topic = bcfxml.topics[TOPIC_GUID]
        entity = _v3_document_references(topic)[0]
        assert bcfxml.documents is not None
        definition = bcfxml.documents.definition.documents
        assert definition is not None
        document = next(doc for doc in definition.document if doc.guid == entity.document_guid)
        assert document.filename == filename
        assert bcfxml.documents.documents[document.filename] == payload
        try:
            # ExtractBcfFile.execute for DOCUMENT_REFERENCE.
            result = bcf.agnostic.topic.extract_file(topic, entity, bcfxml)
        except OSError as caught:
            result = caught
    assert len(recorded_temp_dirs) == before + 1
    directory = recorded_temp_dirs[-1]
    _assert_contained(tmp_path, directory, payload, filename, result)


def test_ordinary_header_filename_is_extracted_inside_the_temp_directory(tmp_path, recorded_temp_dirs):
    payload = PAYLOAD_PREFIX + b"ordinary-header"
    filename = "IfcPile_01.ifc"
    work = tmp_path / "bcf"
    work.mkdir()
    bcf_path = _v2_header_bcf(work, filename, payload)
    before = len(recorded_temp_dirs)
    with bcf.bcfxml.load(bcf_path) as bcfxml:
        assert bcfxml is not None
        topic = bcfxml.topics[TOPIC_GUID]
        entity = _header_files(topic)[0]
        result = bcf.agnostic.topic.extract_file(topic, entity)
    assert len(recorded_temp_dirs) == before + 1
    directory = recorded_temp_dirs[-1]
    _assert_contained(tmp_path, directory, payload, filename, result)
