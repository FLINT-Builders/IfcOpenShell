# This file was generated with the assistance of an AI coding tool.
"""Signed-in document download must follow project membership.

These tests fail while a download handler serves ./data/documents/<request id>.ifc
for any authenticated user. They pass when the handler refuses callers who do not
have HAS_ACTIONS_ON the document's project, and serves the file named by that
authorized document's file_description.name.

The /user/1.0 download route is defined on the user router and is not included by
main.py. It is mounted here because it is the same missing check.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
os.chdir(APP_DIR)
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

os.environ.setdefault("NEO4J_URI", "neo4j://127.0.0.1:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_INITIAL_PASSWORD", "test-neo4j-password")
os.environ.setdefault("SECURITY_ALGORITHM", "HS256")
os.environ.setdefault("KONTROLL_BASE_URL", "http://127.0.0.1:8000/")
os.environ.setdefault("KONTROLL_CLIENT_ID", "test-client")
os.environ.setdefault("KONTROLL_CLIENT_NAME", "test-client")

SECRET_DIR = Path("/run/secrets")
SECRET_PLACEHOLDERS = {
    "security_secret_key": "test-security-secret-key",
    "kontroll_client_secret": "test-client-secret",
}


def _ensure_placeholder_secrets() -> None:
    try:
        SECRET_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        pytest.fail(f"Could not create {SECRET_DIR} for placeholder secrets: {exc}")
    for name, placeholder in SECRET_PLACEHOLDERS.items():
        path = SECRET_DIR / name
        if not path.exists():
            path.write_text(placeholder + "\n", encoding="utf-8")


_ensure_placeholder_secrets()
(APP_DIR / "logs").mkdir(parents=True, exist_ok=True)

import main
from api.user import router as user_router
from database.neo4j import driver
from fastapi import FastAPI
from fastapi.testclient import TestClient
from repository.documents import doc_db
from security.secure import create_access_token

DOCUMENTS_DIR = APP_DIR / "data" / "documents"
PROJECT_WITH_SAMPLES = "c8e9ccce-a4af-11ed-b9df-0242ac120003"
OFFICE_DOCUMENT_ID = "6dbd4d52-14db-11ee-be56-0242ac120002"
SOLIBRI_DOCUMENT_ID = "78860d3c-14db-11ee-be56-0242ac120002"
UNLINKED_DOCUMENT_ID = "78860e68-14db-11ee-be56-0242ac120002"
MISMATCH_DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
MISMATCH_STORED_NAME = "22222222-2222-4222-8222-222222222222.ifc"
OTHER_PROJECT_ID = "44444444-4444-4444-8444-444444444444"
OTHER_DOCUMENT_ID = "33333333-3333-4333-8333-333333333333"
AUTHORIZED_BYTES = b"AUTHORIZED-DOCUMENT-BYTES\n"
DECOY_BYTES = b"REQUEST-PATH-DECOY-BYTES\n"
OTHER_PROJECT_BYTES = b"OTHER-PROJECT-DOCUMENT-BYTES\n"
MEMBERS = ("kommun", "byggherre")
OUTSIDERS = ("admin", "kontrollansvarig", "kontrollant")
DOWNLOAD_CASES = (
    ("documents", "/documents/1.0/document/{document_id}/version/{version_index}/download"),
    ("user", "/user/1.0/document/{document_id}/version/{version_index}/download"),
)


def _bearer(username: str) -> dict[str, str]:
    token = create_access_token({"username": username, "scopes": ["test"]})
    return {"Authorization": f"Bearer {token}"}


def _download(client: TestClient, path_template: str, document_id: str, username: str | None, version_index: int = 1):
    path = path_template.format(document_id=document_id, version_index=version_index)
    headers = {} if username is None else _bearer(username)
    return client.get(path, headers=headers)


def _directory_snapshot(directory: Path) -> dict[str, str]:
    snapshot = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            snapshot[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _seed_documents() -> None:
    mismatch_path = DOCUMENTS_DIR / MISMATCH_STORED_NAME
    decoy_path = DOCUMENTS_DIR / f"{MISMATCH_DOCUMENT_ID}.ifc"
    other_path = DOCUMENTS_DIR / f"{OTHER_DOCUMENT_ID}.ifc"
    mismatch_path.write_bytes(AUTHORIZED_BYTES)
    decoy_path.write_bytes(DECOY_BYTES)
    other_path.write_bytes(OTHER_PROJECT_BYTES)
    with driver.session() as session:
        session.run(
            """
            MATCH (p:Project {project_id: $project_id})
            CREATE (p)-[:CONTAINS]->(d:Document {
                document_id: $document_id,
                session_file_id: '',
                version_index: 1,
                version_number: '1',
                creation_date: '2023-01-01T01:01:01.111',
                title: 'Confidential model',
                original_file_name: 'confidential.ifc',
                file_ending: '.ifc',
                mime_type: 'application/x-step',
                file_type: 'STEP Physical File (SPF)',
                name: $name,
                size_in_bytes: $size_in_bytes
            })
            """,
            project_id=PROJECT_WITH_SAMPLES,
            document_id=MISMATCH_DOCUMENT_ID,
            name=MISMATCH_STORED_NAME,
            size_in_bytes=len(AUTHORIZED_BYTES),
        )
        session.run(
            """
            MATCH (u:User {username: 'kontrollansvarig'})
            CREATE (u)-[:HAS_ACTIONS_ON {read: true}]->(p:Project {
                project_id: $project_id,
                name: 'Other organization'
            })-[:CONTAINS]->(d:Document {
                document_id: $document_id,
                session_file_id: '',
                version_index: 1,
                version_number: '1',
                creation_date: '2023-01-01T01:01:01.111',
                title: 'Other organization model',
                original_file_name: 'other.ifc',
                file_ending: '.ifc',
                mime_type: 'application/x-step',
                file_type: 'STEP Physical File (SPF)',
                name: $name,
                size_in_bytes: $size_in_bytes
            })
            """,
            project_id=OTHER_PROJECT_ID,
            document_id=OTHER_DOCUMENT_ID,
            name=f"{OTHER_DOCUMENT_ID}.ifc",
            size_in_bytes=len(OTHER_PROJECT_BYTES),
        )


def _cleanup_documents() -> None:
    for name in (MISMATCH_STORED_NAME, f"{MISMATCH_DOCUMENT_ID}.ifc", f"{OTHER_DOCUMENT_ID}.ifc"):
        path = DOCUMENTS_DIR / name
        if path.exists():
            path.unlink()
    with driver.session() as session:
        session.run(
            """
            MATCH (d:Document)
            WHERE d.document_id IN $document_ids
            DETACH DELETE d
            """,
            document_ids=[MISMATCH_DOCUMENT_ID, OTHER_DOCUMENT_ID],
        )
        session.run(
            """
            MATCH (p:Project {project_id: $project_id})
            DETACH DELETE p
            """,
            project_id=OTHER_PROJECT_ID,
        )


@pytest.fixture(scope="module")
def clients():
    user_app = FastAPI()
    user_app.include_router(user_router)
    _seed_documents()
    try:
        with TestClient(main.app) as documents_client, TestClient(user_app) as user_client:
            yield {"documents": documents_client, "user": user_client}
    finally:
        _cleanup_documents()


def test_repository_membership_matches_seeded_graph(clients):
    """The graph distinguishes members from outsiders. The download tests below require the same distinction."""
    from models.request import User

    office_member = doc_db.get_document_version(OFFICE_DOCUMENT_ID, 1, User(username="kommun", disabled=False))
    assert office_member is not False
    assert office_member.file_description.name == f"{OFFICE_DOCUMENT_ID}.ifc"

    outsider = doc_db.get_document_version(OFFICE_DOCUMENT_ID, 1, User(username="kontrollansvarig", disabled=False))
    assert outsider is False

    mismatch = doc_db.get_document_version(MISMATCH_DOCUMENT_ID, 1, User(username="kommun", disabled=False))
    assert mismatch is not False
    assert mismatch.file_description.name == MISMATCH_STORED_NAME

    other_owner = doc_db.get_document_version(OTHER_DOCUMENT_ID, 1, User(username="kontrollansvarig", disabled=False))
    assert other_owner is not False
    assert other_owner.file_description.name == f"{OTHER_DOCUMENT_ID}.ifc"

    other_outsider = doc_db.get_document_version(OTHER_DOCUMENT_ID, 1, User(username="kommun", disabled=False))
    assert other_outsider is False


@pytest.mark.parametrize(("client_name", "path_template"), DOWNLOAD_CASES)
def test_download_without_token_is_rejected(clients, client_name, path_template):
    before = _directory_snapshot(DOCUMENTS_DIR)
    response = _download(clients[client_name], path_template, OFFICE_DOCUMENT_ID, None)
    assert response.status_code == 401
    assert response.content != (DOCUMENTS_DIR / f"{OFFICE_DOCUMENT_ID}.ifc").read_bytes()
    assert _directory_snapshot(DOCUMENTS_DIR) == before


@pytest.mark.parametrize(("client_name", "path_template"), DOWNLOAD_CASES)
@pytest.mark.parametrize("username", MEMBERS)
def test_project_member_receives_sample_document_bytes(clients, client_name, path_template, username):
    before = _directory_snapshot(DOCUMENTS_DIR)
    expected = (DOCUMENTS_DIR / f"{OFFICE_DOCUMENT_ID}.ifc").read_bytes()
    response = _download(clients[client_name], path_template, OFFICE_DOCUMENT_ID, username)
    assert response.status_code == 200
    assert response.content == expected
    assert _directory_snapshot(DOCUMENTS_DIR) == before


@pytest.mark.parametrize(("client_name", "path_template"), DOWNLOAD_CASES)
@pytest.mark.parametrize("username", OUTSIDERS)
@pytest.mark.parametrize("document_id", (OFFICE_DOCUMENT_ID, SOLIBRI_DOCUMENT_ID, UNLINKED_DOCUMENT_ID))
def test_signed_in_user_without_project_membership_cannot_download(
    clients, client_name, path_template, username, document_id
):
    stored = DOCUMENTS_DIR / f"{document_id}.ifc"
    expected = stored.read_bytes()
    before = _directory_snapshot(DOCUMENTS_DIR)
    response = _download(clients[client_name], path_template, document_id, username)
    assert response.status_code == 404
    assert response.content != expected
    assert expected not in response.content
    assert stored.read_bytes() == expected
    assert _directory_snapshot(DOCUMENTS_DIR) == before


@pytest.mark.parametrize(("client_name", "path_template"), DOWNLOAD_CASES)
@pytest.mark.parametrize("username", MEMBERS)
def test_member_cannot_download_unlinked_or_other_project_document(clients, client_name, path_template, username):
    before = _directory_snapshot(DOCUMENTS_DIR)
    for document_id, payload in (
        (UNLINKED_DOCUMENT_ID, (DOCUMENTS_DIR / f"{UNLINKED_DOCUMENT_ID}.ifc").read_bytes()),
        (OTHER_DOCUMENT_ID, OTHER_PROJECT_BYTES),
    ):
        response = _download(clients[client_name], path_template, document_id, username)
        assert response.status_code == 404
        assert response.content != payload
        assert payload not in response.content
    assert _directory_snapshot(DOCUMENTS_DIR) == before


@pytest.mark.parametrize(("client_name", "path_template"), DOWNLOAD_CASES)
def test_other_project_member_receives_their_own_document(clients, client_name, path_template):
    before = _directory_snapshot(DOCUMENTS_DIR)
    response = _download(clients[client_name], path_template, OTHER_DOCUMENT_ID, "kontrollansvarig")
    assert response.status_code == 200
    assert response.content == OTHER_PROJECT_BYTES
    assert _directory_snapshot(DOCUMENTS_DIR) == before


@pytest.mark.parametrize(("client_name", "path_template"), DOWNLOAD_CASES)
def test_download_serves_authorized_name_not_request_path(clients, client_name, path_template):
    """A member receives the authorized document's stored bytes.

    A file also exists at the path built from the request document id. Returning
    that file means the handler authorized one object and read another.
    """
    before = _directory_snapshot(DOCUMENTS_DIR)
    member = _download(clients[client_name], path_template, MISMATCH_DOCUMENT_ID, "kommun")
    assert member.status_code == 200
    assert member.content == AUTHORIZED_BYTES
    assert member.content != DECOY_BYTES

    for username in OUTSIDERS:
        denied = _download(clients[client_name], path_template, MISMATCH_DOCUMENT_ID, username)
        assert denied.status_code == 404
        assert denied.content != AUTHORIZED_BYTES
        assert denied.content != DECOY_BYTES
        assert AUTHORIZED_BYTES not in denied.content
        assert DECOY_BYTES not in denied.content

    assert (DOCUMENTS_DIR / MISMATCH_STORED_NAME).read_bytes() == AUTHORIZED_BYTES
    assert (DOCUMENTS_DIR / f"{MISMATCH_DOCUMENT_ID}.ifc").read_bytes() == DECOY_BYTES
    assert _directory_snapshot(DOCUMENTS_DIR) == before
