# This file was generated with the assistance of an AI coding tool.
"""Authorization for OpenCDE document versioning.

A signed-in user who supplies another document's id must not replace the
bytes stored for that document. These tests drive the real upload routes
(upload-documents, save-metadata-for-documents, upload-instructions,
upload-part, upload-completion, and the version download). They fail while
the server keeps the client-supplied document id as the stored file name
and renames the merged upload onto that path.

Not covered, because those operations do not take a client document id and
then write it onto an existing stored file:

- ``upload_file_to_project`` generates its own id with ``uuid4``.
- BCF ``post_document`` returns without writing a file.

Run from ``src/opencdeserver/api/app`` with Neo4j 5.7 and APOC 5.7 already
listening on bolt://127.0.0.1:7687 as user ``neo4j`` with the placeholder
password this module sets. See the module setup below for the other
placeholders. The tests fail until the vulnerability is fixed.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "api" / "app"
DOCUMENTS_DIR = APP_DIR / "data" / "documents"
PARTS_DIR = APP_DIR / "data" / "document_parts"

# Seeded by src/opencdeserver/api/app/db_config/init.cypher.
VICTIM_DOCUMENT_ID = "78860d3c-14db-11ee-be56-0242ac120002"
OTHER_DOCUMENT_ID = "6dbd4d52-14db-11ee-be56-0242ac120002"
PROJECT_WITH_DOCUMENT = "c8e9ccce-a4af-11ed-b9df-0242ac120003"
OTHER_PROJECT = "d1842bfe-a4af-11ed-b9df-0242ac120003"

PLACEHOLDER_PASSWORD = "placeholder-password"
PLACEHOLDER_CLIENT_ID = "placeholder-client"
PLACEHOLDER_CLIENT_SECRET = "placeholder-client-secret"
PAYLOAD = b"REPLACEMENT-PAYLOAD-NOT-THE-STORED-DOCUMENT\n"


@dataclass
class FileSnap:
    inode: int
    data: bytes


@dataclass
class UploadResult:
    upload_status: int
    completion_status: int | None
    stored_name: str | None
    download_status: int | None
    download_body: bytes | None
    changed: list[str] = field(default_factory=list)
    new_payload_files: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def summary(self) -> str:
        return (
            f"upload_status={self.upload_status} completion_status={self.completion_status} "
            f"stored_name={self.stored_name!r} download_status={self.download_status} "
            f"changed={self.changed} new_payload_files={self.new_payload_files} error={self.error}"
        )


def _prepare_process() -> None:
    os.chdir(APP_DIR)
    sys.path.insert(0, str(APP_DIR))
    # The repository directory src/opencdeserver/api is also named api, and it
    # shadows the application's api package if pytest has already imported it.
    for name in list(sys.modules):
        if name == "api" or name.startswith("api."):
            del sys.modules[name]
    (APP_DIR / "logs").mkdir(exist_ok=True)
    os.environ["NEO4J_URI"] = "bolt://127.0.0.1:7687"
    os.environ["NEO4J_USER"] = "neo4j"
    os.environ["NEO4J_INITIAL_PASSWORD"] = "placeholder-neo4j-password"
    os.environ["KONTROLL_BASE_URL"] = "http://testserver/"
    os.environ["KONTROLL_CLIENT_ID"] = PLACEHOLDER_CLIENT_ID
    os.environ["KONTROLL_CLIENT_NAME"] = "placeholder-client-name"
    os.environ["SECURITY_AUTHORIZATION_CODE_EXPIRE_SECONDS"] = "3600"
    os.environ["SECURITY_ACCESS_TOKEN_EXPIRE_SECONDS"] = "3600"
    os.environ["SECURITY_REFRESH_TOKEN_EXPIRE_SECONDS"] = "7200"
    os.environ["SECURITY_ALGORITHM"] = "HS256"
    os.environ["SESSION_URL_VALIDITY_SECONDS"] = "600"
    os.environ["SESSION_MAX_FILE_SIZE_BYTES"] = "10485760"
    secrets_dir = Path("/run/secrets")
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "security_secret_key").write_text("placeholder-security-secret-key")
    (secrets_dir / "kontroll_client_secret").write_text(PLACEHOLDER_CLIENT_SECRET)


def _snapshot() -> dict[str, FileSnap]:
    snaps = {}
    for path in DOCUMENTS_DIR.iterdir():
        if path.is_file():
            snaps[path.name] = FileSnap(path.stat().st_ino, path.read_bytes())
    return snaps


def _restore(before: dict[str, FileSnap], extra: list[Path]) -> None:
    for path in extra:
        if path.exists() and path.name not in before:
            path.unlink()
    for name, snap in before.items():
        path = DOCUMENTS_DIR / name
        path.write_bytes(snap.data)
    if PARTS_DIR.exists():
        for child in PARTS_DIR.iterdir():
            if child.name == ".empty":
                continue
            if child.is_dir():
                for nested in child.iterdir():
                    nested.unlink()
                child.rmdir()
            else:
                child.unlink()


@pytest.fixture(scope="module")
def api():
    _prepare_process()
    import main
    from database.neo4j import driver
    from fastapi.testclient import TestClient
    from security.secure import get_password_hash

    password_hash = get_password_hash(PLACEHOLDER_PASSWORD)
    with driver.session() as session:
        for username in ("admin", "kommun", "byggherre", "kontrollant", "kontrollansvarig"):
            session.run(
                "MATCH (u:User {username:$username}) SET u.hashed_password=$password_hash",
                username=username,
                password_hash=password_hash,
            ).consume()

    with TestClient(main.app, raise_server_exceptions=False) as client:
        yield {"client": client, "driver": driver, "tokens": {}}


@pytest.fixture
def stored_files():
    before = _snapshot()
    extra: list[Path] = []
    try:
        yield before, extra
    finally:
        _restore(before, extra)


def _login(api, username: str) -> str:
    cached = api["tokens"].get(username)
    if cached:
        return cached
    client = api["client"]
    code = client.get(
        "/foundation/oauth2/code",
        params={
            "username": username,
            "password": PLACEHOLDER_PASSWORD,
            "response_type": "code",
            "client_id": PLACEHOLDER_CLIENT_ID,
            "client_name": "placeholder-client-name",
            "state": "state",
            "redirect_uri": "http://localhost/callback",
            "scope": "test",
        },
    )
    assert code.status_code == 200, code.text[:200]
    token = client.post(
        "/foundation/oauth2/token",
        data={"grant_type": "authorization_code", "code": code.json()},
        auth=(PLACEHOLDER_CLIENT_ID, PLACEHOLDER_CLIENT_SECRET),
    )
    assert token.status_code == 201, token.text[:200]
    access_token = token.json()["access_token"]
    api["tokens"][username] = access_token
    return access_token


def _set_project_actions(driver, username: str, grants: list[tuple[str, bool, bool]]) -> None:
    with driver.session() as session:
        session.run(
            "MATCH (u:User {username:$username})-[rel:HAS_ACTIONS_ON]->() DELETE rel",
            username=username,
        ).consume()
        for project_id, can_read, can_update in grants:
            session.run(
                """
                MATCH (u:User {username:$username})
                MATCH (p:Project {project_id:$project_id})
                CREATE (u)-[:HAS_ACTIONS_ON {read:$can_read, update:$can_update}]->(p)
                """,
                username=username,
                project_id=project_id,
                can_read=can_read,
                can_update=can_update,
            ).consume()


def _stored_name(driver, upload_session: str) -> str | None:
    with driver.session() as session:
        record = session.run(
            """
            MATCH (:Session:Upload {upload_session:$upload_session})-[:CONTAINS]->(d:Document)
            RETURN d.name AS name
            """,
            upload_session=upload_session,
        ).single()
    if record is None:
        return None
    return record["name"]


def _attempt(
    api,
    username: str,
    document_id: str,
    project_id: str,
    file_name: str,
    before: dict[str, FileSnap],
) -> UploadResult:
    client = api["client"]
    token = _login(api, username)
    headers = {"Authorization": f"Bearer {token}"}
    result = UploadResult(
        upload_status=0,
        completion_status=None,
        stored_name=None,
        download_status=None,
        download_body=None,
    )
    try:
        upload = client.post(
            "/documents/1.0/upload-documents",
            headers=headers,
            json={
                "server_context": "ctx",
                "callback": {"url": "http://client.example/callback", "expires_in": 3600},
                "files": [{"file_name": file_name, "session_file_id": "s1", "document_id": document_id}],
            },
        )
        result.upload_status = upload.status_code
        if upload.status_code >= 400:
            return result
        upload_ui_url = upload.json().get("upload_ui_url", "")
        upload_session = upload_ui_url.split("upload_session=")[-1]
        result.stored_name = _stored_name(api["driver"], upload_session)
        metadata = client.post(
            "/documents/1.0/save-metadata-for-documents",
            data={
                "session_file_id@s1": "s1",
                "document@s1": document_id,
                "title@s1": "tampered",
                "version_number@s1": "2",
                "filename@s1": file_name,
                "username": username,
                "upload_session": upload_session,
                "server_context": "ctx",
                "callback_url": "http://client.example/callback",
                "callback_expires_in": "3600",
                "project": project_id,
            },
        )
        if metadata.status_code >= 400:
            result.error = f"metadata {metadata.status_code}"
            return result
        instructions = client.post(
            "/documents/1.0/upload-instructions",
            headers=headers,
            params={"session_id": upload_session, "server_context": "ctx"},
            json={"files": [{"session_file_id": "s1", "size_in_bytes": len(PAYLOAD)}]},
        )
        if instructions.status_code >= 400:
            result.error = f"instructions {instructions.status_code}"
            return result
        part_url = instructions.json()["documents_to_upload"][0]["upload_file_parts"][0]["url"]
        part_id = part_url.rstrip("/").split("/")[-1]
        part = client.post(f"/documents/1.0/upload-part/{part_id}", headers=headers, content=PAYLOAD)
        if part.status_code >= 400:
            result.error = f"part {part.status_code}"
            return result
        completion = client.post(
            "/documents/1.0/upload-completion",
            headers=headers,
            params={"upload_session": upload_session},
        )
        result.completion_status = completion.status_code
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        _observe_files(result, before)
        if file_name.lower().endswith(".ifc"):
            owner = _login(api, "kommun")
            download = client.get(
                f"/documents/1.0/document/{document_id}/version/1/download",
                headers={"Authorization": f"Bearer {owner}"},
            )
            result.download_status = download.status_code
            result.download_body = download.content
    return result


def _observe_files(result: UploadResult, before: dict[str, FileSnap]) -> None:
    result.changed = []
    result.new_payload_files = []
    for path in DOCUMENTS_DIR.iterdir():
        if not path.is_file():
            continue
        if path.name not in before:
            if path.read_bytes() == PAYLOAD:
                result.new_payload_files.append(path.name)
            continue
        snap = before[path.name]
        if path.stat().st_ino != snap.inode or path.read_bytes() != snap.data:
            result.changed.append(path.name)


def _assert_rejected(result: UploadResult, original: bytes | None) -> None:
    preserved = not result.changed and not result.new_payload_files
    download_ok = True
    if original is not None:
        download_ok = result.download_status == 200 and result.download_body == original
    assert 400 <= result.upload_status < 500 and preserved and download_ok, result.summary


def test_signed_in_user_without_project_access_cannot_replace_document(api, stored_files):
    before, _extra = stored_files
    _set_project_actions(api["driver"], "kontrollant", [])
    original = before[f"{VICTIM_DOCUMENT_ID}.ifc"].data
    result = _attempt(
        api,
        "kontrollant",
        VICTIM_DOCUMENT_ID,
        PROJECT_WITH_DOCUMENT,
        "x.ifc",
        before,
    )
    _assert_rejected(result, original)


def test_read_without_update_cannot_replace_document(api, stored_files):
    before, _extra = stored_files
    _set_project_actions(api["driver"], "kontrollant", [(PROJECT_WITH_DOCUMENT, True, False)])
    original = before[f"{VICTIM_DOCUMENT_ID}.ifc"].data
    result = _attempt(
        api,
        "kontrollant",
        VICTIM_DOCUMENT_ID,
        PROJECT_WITH_DOCUMENT,
        "x.ifc",
        before,
    )
    _assert_rejected(result, original)


def test_update_on_another_project_cannot_replace_document(api, stored_files):
    """The project sent in metadata is not the document that is written."""
    before, _extra = stored_files
    _set_project_actions(api["driver"], "kontrollansvarig", [(OTHER_PROJECT, True, True)])
    original = before[f"{VICTIM_DOCUMENT_ID}.ifc"].data
    result = _attempt(
        api,
        "kontrollansvarig",
        VICTIM_DOCUMENT_ID,
        OTHER_PROJECT,
        "x.ifc",
        before,
    )
    _assert_rejected(result, original)
    assert (DOCUMENTS_DIR / f"{OTHER_DOCUMENT_ID}.ifc").read_bytes() == before[f"{OTHER_DOCUMENT_ID}.ifc"].data


def test_pdf_extension_cannot_replace_stored_file(api, stored_files):
    _before, extra = stored_files
    _set_project_actions(api["driver"], "kontrollant", [])
    pdf_path = DOCUMENTS_DIR / f"{VICTIM_DOCUMENT_ID}.pdf"
    pdf_path.write_bytes(b"ORIGINAL-PDF")
    extra.append(pdf_path)
    current = _snapshot()
    result = _attempt(api, "kontrollant", VICTIM_DOCUMENT_ID, PROJECT_WITH_DOCUMENT, "x.pdf", current)
    _assert_rejected(result, None)
    assert pdf_path.read_bytes() == b"ORIGINAL-PDF"
    assert pdf_path.stat().st_ino == current[pdf_path.name].inode


def test_extensionless_name_cannot_replace_stored_file(api, stored_files):
    _before, extra = stored_files
    _set_project_actions(api["driver"], "kontrollant", [])
    bare_path = DOCUMENTS_DIR / VICTIM_DOCUMENT_ID
    bare_path.write_bytes(b"ORIGINAL-BARE")
    extra.append(bare_path)
    current = _snapshot()
    result = _attempt(api, "kontrollant", VICTIM_DOCUMENT_ID, PROJECT_WITH_DOCUMENT, "notes", current)
    _assert_rejected(result, None)
    assert bare_path.read_bytes() == b"ORIGINAL-BARE"
    assert bare_path.stat().st_ino == current[bare_path.name].inode


def test_update_right_keeps_previous_file_and_stores_a_new_name(api, stored_files):
    before, _extra = stored_files
    _set_project_actions(api["driver"], "byggherre", [(PROJECT_WITH_DOCUMENT, True, True)])
    original = before[f"{VICTIM_DOCUMENT_ID}.ifc"].data
    result = _attempt(
        api,
        "byggherre",
        VICTIM_DOCUMENT_ID,
        PROJECT_WITH_DOCUMENT,
        "x.ifc",
        before,
    )
    previous_kept = not result.changed
    download_ok = result.download_status == 200 and result.download_body == original
    new_copy = any(name != f"{VICTIM_DOCUMENT_ID}.ifc" for name in result.new_payload_files)
    accepted = result.upload_status < 400 and result.completion_status is not None and result.completion_status < 400
    assert accepted and previous_kept and download_ok and new_copy, result.summary
