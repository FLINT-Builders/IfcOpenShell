# This file was generated with the assistance of an AI coding tool.
"""Authorization tests for OpenCDE document upload completion.

These tests fail while a signed-in user can store an arbitrary project id on an
upload and document_upload_finish then links that document to the project
without a user-to-project write check. They pass once both of these hold:

* save-metadata refuses a project the user cannot create documents in
* upload completion links the document only from the same project node the
  uploading user's createDocument relationship authorizes, in the same
  statement, and does not write or delete files when that check fails
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_DIR = Path(__file__).resolve().parents[1]
os.chdir(APP_DIR)
sys.path.insert(0, str(APP_DIR))

os.environ.setdefault("NEO4J_URI", "bolt://127.0.0.1:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_INITIAL_PASSWORD", "placeholder")
os.environ.setdefault("KONTROLL_BASE_URL", "http://127.0.0.1:8000/")
os.environ.setdefault("KONTROLL_CLIENT_ID", "placeholder-client")
os.environ.setdefault("KONTROLL_CLIENT_NAME", "placeholder")
os.environ.setdefault("SESSION_URL_VALIDITY_SECONDS", "600")
os.environ.setdefault("SESSION_MAX_FILE_SIZE_BYTES", "1048576")
os.environ.setdefault("SECURITY_ALGORITHM", "HS256")
os.environ.setdefault("SECURITY_AUTHORIZATION_CODE_EXPIRE_SECONDS", "60")
os.environ.setdefault("SECURITY_ACCESS_TOKEN_EXPIRE_SECONDS", "60")
os.environ.setdefault("SECURITY_REFRESH_TOKEN_EXPIRE_SECONDS", "60")

# The server reads these files at import. The contents are placeholders, not live credentials.
_secrets_dir = Path("/run/secrets")
_secrets_dir.mkdir(parents=True, exist_ok=True)
for _secret_name in ("kontroll_client_secret", "security_secret_key", "neo4j_password"):
    _secret_path = _secrets_dir / _secret_name
    if not _secret_path.exists():
        _secret_path.write_text("placeholder\n")

from api.user import router as user_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from main import app
from models.request import User
from repository.documents import doc_db
from security.secure import get_current_active_user

RAW_DRIVER = doc_db.driver
BINDING = {"swap_pair": None, "swapped": False, "queries": []}
ACTOR = {"user": None}


def _compact(cypher: str) -> str:
    return " ".join(cypher.lower().split())


def _is_unbound_project_attach(cypher: str) -> bool:
    text = _compact(cypher)
    if "create" not in text or "contains" not in text:
        return False
    if "has_actions_on" in text:
        return False
    return "project_id" in text and "project" in text


def _swap_project_nodes(element_a: str, element_b: str) -> None:
    with RAW_DRIVER.session() as session:
        session.run(
            """
            MATCH (a:Project), (b:Project)
            WHERE elementId(a) = $a AND elementId(b) = $b
            WITH a, b, a.project_id AS aid, b.project_id AS bid
            SET a.project_id = bid, b.project_id = aid
            """,
            a=element_a,
            b=element_b,
        ).consume()


class _RecordingTx:
    def __init__(self, tx):
        self._tx = tx
        self._saw_project_statement = False

    def run(self, query, parameters=None, **kwargs):
        # A project matched only by id, in its own statement, is not the node a
        # previous membership check authorized. Swap the ids before that
        # statement so the attachment lands on the other node. Skip the swap
        # when this transaction already read a project: that node may be
        # locked, and the query text assertion still rejects the split lookup.
        if BINDING["swap_pair"] is not None and _is_unbound_project_attach(query) and not self._saw_project_statement:
            _swap_project_nodes(*BINDING["swap_pair"])
            BINDING["swapped"] = True
        if "project" in query.lower():
            self._saw_project_statement = True
        BINDING["queries"].append(query)
        return self._tx.run(query, parameters, **kwargs)


class _RecordingSession:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        self._session.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._session.__exit__(exc_type, exc, tb)

    def execute_write(self, work, *args, **kwargs):
        def wrapped(tx, *inner_args, **inner_kwargs):
            return work(_RecordingTx(tx), *inner_args, **inner_kwargs)

        return self._session.execute_write(wrapped, *args, **kwargs)

    def execute_read(self, work, *args, **kwargs):
        def wrapped(tx, *inner_args, **inner_kwargs):
            return work(_RecordingTx(tx), *inner_args, **inner_kwargs)

        return self._session.execute_read(wrapped, *args, **kwargs)


class _RecordingDriver:
    def __init__(self, driver):
        self._driver = driver

    def session(self, *args, **kwargs):
        return _RecordingSession(self._driver.session(*args, **kwargs))

    def verify_connectivity(self):
        return self._driver.verify_connectivity()

    def close(self):
        return self._driver.close()


doc_db.driver = _RecordingDriver(RAW_DRIVER)


def _actor(username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@example.test",
        full_name=username,
        disabled=False,
    )
    ACTOR["user"] = user
    return user


def _override_user():
    return ACTOR["user"]


app.dependency_overrides[get_current_active_user] = _override_user
user_app = FastAPI()
user_app.include_router(user_router)
user_app.dependency_overrides[get_current_active_user] = _override_user

client = TestClient(app, raise_server_exceptions=False)
user_client = TestClient(user_app, raise_server_exceptions=False)


def _rows(cypher: str, **params):
    with RAW_DRIVER.session() as session:
        return [record.data() for record in session.run(cypher, **params)]


def _run(cypher: str, **params) -> None:
    with RAW_DRIVER.session() as session:
        session.run(cypher, **params).consume()


def _new_id() -> str:
    return str(uuid.uuid4())


def _add_user(username: str) -> None:
    _run(
        """
        CREATE (:User {
            username: $username,
            email: $email,
            full_name: $username,
            disabled: false,
            hashed_password: 'placeholder'
        })
        """,
        username=username,
        email=f"{username}@example.test",
    )


def _add_project(project_id: str, name: str) -> str:
    rows = _rows(
        """
        CREATE (p:Project {project_id: $project_id, name: $name})
        RETURN elementId(p) AS element_id
        """,
        project_id=project_id,
        name=name,
    )
    return rows[0]["element_id"]


def _grant(username: str, project_id: str, *, read: bool, create_document: bool) -> None:
    _run(
        """
        MATCH (u:User {username: $username}), (p:Project {project_id: $project_id})
        CREATE (u)-[:HAS_ACTIONS_ON {
            read: $read,
            update: false,
            createTopic: false,
            createDocument: $create_document,
            createViewpoint: false,
            createComment: false
        }]->(p)
        """,
        username=username,
        project_id=project_id,
        read=read,
        create_document=create_document,
    )


def _metadata_form(upload_session: str, session_file_id: str, document_id: str, project_id: str, username: str):
    return {
        "username": username,
        "upload_session": upload_session,
        "server_context": "server-context",
        "callback_url": "http://127.0.0.1/callback",
        "callback_expires_in": "3600",
        "project": project_id,
        f"session_file_id@{session_file_id}": session_file_id,
        f"document@{session_file_id}": document_id,
        f"title@{session_file_id}": "planted-title",
        f"version_number@{session_file_id}": "1",
        f"filename@{session_file_id}": "planted.ifc",
    }


def _start_upload(username: str) -> dict:
    _actor(username)
    session_file_id = _new_id()
    response = client.post(
        "/documents/1.0/upload-documents",
        json={
            "server_context": "server-context",
            "callback": {"url": "http://127.0.0.1/callback", "expires_in": 3600},
            "files": [{"file_name": "planted.ifc", "session_file_id": session_file_id}],
        },
    )
    assert response.status_code == 200, response.text
    upload_session = parse_qs(urlparse(response.json()["upload_ui_url"]).query)["upload_session"][0]
    document = _rows(
        """
        MATCH (u:User {username: $username})-[:HAS]->(us:Session:Upload {upload_session: $upload_session})
              -[:CONTAINS]->(d:Document)
        RETURN d.document_id AS document_id, d.name AS name, d.session_file_id AS session_file_id
        """,
        username=username,
        upload_session=upload_session,
    )[0]
    return {
        "username": username,
        "upload_session": upload_session,
        "session_file_id": session_file_id,
        "document_id": document["document_id"],
        "name": document["name"],
    }


def _save_metadata(http: TestClient, path: str, upload: dict, project_id: str):
    return http.post(
        path,
        data=_metadata_form(
            upload["upload_session"],
            upload["session_file_id"],
            upload["document_id"],
            project_id,
            upload["username"],
        ),
    )


def _stored_project(document_id: str):
    rows = _rows(
        "MATCH (d:Document {document_id: $document_id}) RETURN d.project AS project",
        document_id=document_id,
    )
    return rows[0]["project"] if rows else None


def _set_project(document_id: str, project_id: str) -> None:
    _run(
        """
        MATCH (d:Document {document_id: $document_id})
        SET d.project = $project_id, d.title = 'planted-title', d.version_number = '1', d.version_index = 1
        """,
        document_id=document_id,
        project_id=project_id,
    )


def _upload_bytes(upload: dict, payload: bytes) -> Path:
    _actor(upload["username"])
    instructions = client.post(
        "/documents/1.0/upload-instructions",
        params={"session_id": upload["upload_session"], "server_context": "server-context"},
        json={"files": [{"session_file_id": upload["session_file_id"], "size_in_bytes": len(payload)}]},
    )
    assert instructions.status_code == 200, instructions.text
    part_url = instructions.json()["documents_to_upload"][0]["upload_file_parts"][0]["url"]
    part_id = part_url.rstrip("/").split("/")[-1]
    part_path = APP_DIR / "data" / "document_parts" / upload["document_id"] / part_id
    uploaded = client.post(f"/documents/1.0/upload-part/{part_id}", content=payload)
    assert uploaded.status_code == 200, uploaded.text
    assert part_path.is_file()
    return part_path


def _containing_projects(document_id: str) -> list[dict]:
    return _rows(
        """
        MATCH (p:Project)-[:CONTAINS]->(d:Document {document_id: $document_id})
        RETURN elementId(p) AS element_id, p.project_id AS project_id, p.name AS name
        """,
        document_id=document_id,
    )


def _selection_html(username: str) -> str:
    _actor(username)
    started = client.post(
        "/documents/1.0/select-documents",
        json={"callback": {"url": "http://127.0.0.1/callback", "expires_in": 3600}},
    )
    assert started.status_code == 200, started.text
    selection_session = parse_qs(urlparse(started.json()["select_documents_url"]).query)["selection_session"][0]
    page = client.get("/documents/1.0/document-selection", params={"selection_session": selection_session})
    assert page.status_code == 200, page.text
    return page.text


def _published_path(upload: dict) -> Path:
    return APP_DIR / "data" / "documents" / upload["name"]


def _cleanup_files(upload: dict, part_path: Path | None) -> None:
    published = _published_path(upload)
    if published.exists():
        published.unlink()
    if part_path is not None and part_path.exists():
        part_path.unlink()
    part_dir = APP_DIR / "data" / "document_parts" / upload["document_id"]
    if part_dir.exists():
        for child in part_dir.iterdir():
            child.unlink()
        part_dir.rmdir()


def test_metadata_form_rejects_project_the_caller_cannot_write():
    attacker = f"attacker-{_new_id()}"
    victim = f"victim-{_new_id()}"
    _add_user(attacker)
    _add_user(victim)
    own_project = _new_id()
    foreign_project = _new_id()
    _add_project(own_project, "attacker project")
    _add_project(foreign_project, "victim project")
    _grant(attacker, own_project, read=True, create_document=True)
    _grant(victim, foreign_project, read=True, create_document=True)

    upload = _start_upload(attacker)
    page = client.get("/documents/1.0/document-upload", params={"upload_session": upload["upload_session"]})
    assert page.status_code == 200, page.text
    assert own_project in page.text
    assert foreign_project not in page.text

    saved = _save_metadata(client, "/documents/1.0/save-metadata-for-documents", upload, foreign_project)
    assert saved.status_code >= 400, saved.text
    assert _stored_project(upload["document_id"]) != foreign_project


def test_unmounted_user_metadata_route_rejects_project_the_caller_cannot_write():
    attacker = f"attacker-{_new_id()}"
    _add_user(attacker)
    own_project = _new_id()
    foreign_project = _new_id()
    _add_project(own_project, "attacker project")
    _add_project(foreign_project, "foreign project")
    _grant(attacker, own_project, read=True, create_document=True)

    upload = _start_upload(attacker)
    saved = _save_metadata(user_client, "/user/1.0/save-metadata-for-documents", upload, foreign_project)
    assert saved.status_code >= 400, saved.text
    assert _stored_project(upload["document_id"]) != foreign_project


def test_nonmember_cannot_publish_upload_into_another_project():
    attacker = f"attacker-{_new_id()}"
    victim = f"victim-{_new_id()}"
    _add_user(attacker)
    _add_user(victim)
    own_project = _new_id()
    foreign_project = _new_id()
    _add_project(own_project, "attacker project")
    _add_project(foreign_project, "victim project")
    _grant(attacker, own_project, read=True, create_document=True)
    _grant(victim, foreign_project, read=True, create_document=True)

    upload = _start_upload(attacker)
    payload = b"planted-ifc"
    part_path = None
    try:
        saved = _save_metadata(client, "/documents/1.0/save-metadata-for-documents", upload, foreign_project)
        if saved.status_code < 400:
            assert _stored_project(upload["document_id"]) == foreign_project
        else:
            _set_project(upload["document_id"], foreign_project)
        part_path = _upload_bytes(upload, payload)
        completed = client.post(
            "/documents/1.0/upload-completion",
            params={"upload_session": upload["upload_session"]},
        )
        selection_html = _selection_html(victim)
        assert upload["document_id"] not in selection_html
        assert "planted-title" not in selection_html
        assert completed.status_code >= 400, completed.text
        assert _containing_projects(upload["document_id"]) == []
        assert not _published_path(upload).exists()
        assert part_path.is_file()
        _actor(victim)
        listing = client.get(f"/bcf/3.0/projects/{foreign_project}/files_information")
        assert listing.status_code == 200, listing.text
        assert upload["document_id"] not in listing.text
        assert b"planted-title" not in listing.content
    finally:
        _cleanup_files(upload, part_path)


def test_reader_without_create_document_cannot_publish_upload():
    reader = f"reader-{_new_id()}"
    _add_user(reader)
    project_id = _new_id()
    _add_project(project_id, "read only project")
    _grant(reader, project_id, read=True, create_document=False)

    upload = _start_upload(reader)
    payload = b"reader-ifc"
    part_path = None
    try:
        _set_project(upload["document_id"], project_id)
        part_path = _upload_bytes(upload, payload)
        completed = client.post(
            "/documents/1.0/upload-completion",
            params={"upload_session": upload["upload_session"]},
        )
        assert completed.status_code >= 400, completed.text
        assert _containing_projects(upload["document_id"]) == []
        assert not _published_path(upload).exists()
        assert part_path.is_file()
    finally:
        _cleanup_files(upload, part_path)


def test_completion_refuses_a_project_already_stored_on_the_document():
    attacker = f"attacker-{_new_id()}"
    _add_user(attacker)
    own_project = _new_id()
    foreign_project = _new_id()
    _add_project(own_project, "attacker project")
    _add_project(foreign_project, "foreign project")
    _grant(attacker, own_project, read=True, create_document=True)

    upload = _start_upload(attacker)
    payload = b"preset-ifc"
    part_path = None
    try:
        _set_project(upload["document_id"], foreign_project)
        part_path = _upload_bytes(upload, payload)
        completed = client.post(
            "/documents/1.0/upload-completion",
            params={"upload_session": upload["upload_session"]},
        )
        assert completed.status_code >= 400, completed.text
        parents = _containing_projects(upload["document_id"])
        assert parents == []
        assert not _published_path(upload).exists()
        assert part_path.is_file()
    finally:
        _cleanup_files(upload, part_path)


def test_finish_attaches_the_authorized_project_node_in_the_same_statement():
    attacker = f"attacker-{_new_id()}"
    other = f"other-{_new_id()}"
    _add_user(attacker)
    _add_user(other)
    own_project = _new_id()
    decoy_project = _new_id()
    own_element = _add_project(own_project, "authorized project")
    decoy_element = _add_project(decoy_project, "decoy project")
    _grant(attacker, own_project, read=True, create_document=True)
    _grant(other, decoy_project, read=True, create_document=True)

    upload = _start_upload(attacker)
    payload = b"bound-ifc"
    part_path = None
    BINDING["queries"] = []
    BINDING["swapped"] = False
    BINDING["swap_pair"] = (own_element, decoy_element)
    try:
        saved = _save_metadata(client, "/documents/1.0/save-metadata-for-documents", upload, own_project)
        assert saved.status_code < 400, saved.text
        assert _stored_project(upload["document_id"]) == own_project
        part_path = _upload_bytes(upload, payload)
        completed = client.post(
            "/documents/1.0/upload-completion",
            params={"upload_session": upload["upload_session"]},
        )
        assert completed.status_code < 400, completed.text
        parents = _containing_projects(upload["document_id"])
        assert parents == [{"element_id": own_element, "project_id": own_project, "name": "authorized project"}]
        attach_queries = [
            query
            for query in BINDING["queries"]
            if _compact(query).count("create") and "contains" in _compact(query) and "project" in _compact(query)
        ]
        assert attach_queries
        for query in attach_queries:
            text = _compact(query)
            assert "has_actions_on" in text
            assert "createdocument" in text
        assert upload["document_id"] in _selection_html(attacker)
        assert _published_path(upload).is_file()
    finally:
        BINDING["swap_pair"] = None
        _cleanup_files(upload, part_path)


def test_writer_can_publish_into_own_project():
    writer = f"writer-{_new_id()}"
    _add_user(writer)
    project_id = _new_id()
    element_id = _add_project(project_id, "own project")
    _grant(writer, project_id, read=True, create_document=True)

    upload = _start_upload(writer)
    payload = b"owned-ifc"
    part_path = None
    try:
        saved = _save_metadata(client, "/documents/1.0/save-metadata-for-documents", upload, project_id)
        assert saved.status_code < 400, saved.text
        part_path = _upload_bytes(upload, payload)
        completed = client.post(
            "/documents/1.0/upload-completion",
            params={"upload_session": upload["upload_session"]},
        )
        assert completed.status_code < 400, completed.text
        assert _containing_projects(upload["document_id"]) == [
            {"element_id": element_id, "project_id": project_id, "name": "own project"}
        ]
        assert _published_path(upload).read_bytes() == payload
        assert upload["document_id"] in _selection_html(writer)
    finally:
        _cleanup_files(upload, part_path)
