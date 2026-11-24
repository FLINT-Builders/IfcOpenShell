# This file was generated with the assistance of an AI coding tool.
"""Filesystem bounds for the OpenCDE document upload flow.

A signed-in user can send ``document_id`` on ``POST /documents/1.0/upload-documents``.
The part, completion, and cancellation handlers build paths from that value.
These tests fail while that value can create or delete files outside
``./data/document_parts`` and ``./data/documents``.

Importing the API runs ``db.initialize_db()``, which executes ``db_config/init.cypher``
and deletes every node in the configured Neo4j database. Point ``NEO4J_URI`` at a
disposable database.

The tests use the obvious placeholder ``placeholder-not-a-secret`` for the
throwaway account and for Docker-style secret files that are absent.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

APP_DIR = Path(__file__).resolve().parents[1] / "app"
PLACEHOLDER = "placeholder-not-a-secret"
PART_PAYLOAD = b"part-bytes-outside-store"
COMPLETE_PAYLOAD = b"complete-bytes-outside-store"
INSIDE_PAYLOAD = b"part-bytes-inside-store"

SANDBOX = Path(tempfile.mkdtemp(prefix="opencde-upload-traversal-"))
PARTS_ROOT = SANDBOX / "data" / "document_parts"
DOCUMENTS_ROOT = SANDBOX / "data" / "documents"
LOGS_ROOT = SANDBOX / "logs"


def _prepare_runtime():
    os.environ.setdefault("NEO4J_URI", "bolt://127.0.0.1:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_INITIAL_PASSWORD", PLACEHOLDER)
    os.environ.setdefault("KONTROLL_BASE_URL", "http://127.0.0.1:8000/")
    os.environ.setdefault("KONTROLL_CLIENT_ID", "test-client")
    os.environ.setdefault("KONTROLL_CLIENT_NAME", "test-client")
    os.environ.setdefault("SECURITY_ALGORITHM", "HS256")
    os.environ.setdefault("SECURITY_AUTHORIZATION_CODE_EXPIRE_SECONDS", "600")
    os.environ.setdefault("SECURITY_ACCESS_TOKEN_EXPIRE_SECONDS", "3600")
    os.environ.setdefault("SECURITY_REFRESH_TOKEN_EXPIRE_SECONDS", "7200")
    os.environ.setdefault("SESSION_URL_VALIDITY_SECONDS", "600")
    os.environ.setdefault("SESSION_MAX_FILE_SIZE_BYTES", "1048576")

    secrets_dir = Path("/run/secrets")
    secrets_dir.mkdir(parents=True, exist_ok=True)
    for name in ("security_secret_key", "kontroll_client_secret", "neo4j_password"):
        path = secrets_dir / name
        if not path.exists():
            path.write_text(PLACEHOLDER + "\n", encoding="utf-8")

    LOGS_ROOT.mkdir(parents=True)
    PARTS_ROOT.mkdir(parents=True)
    DOCUMENTS_ROOT.mkdir(parents=True)
    os.symlink(APP_DIR / "db_config", SANDBOX / "db_config")
    os.chdir(SANDBOX)
    sys.path.insert(0, str(APP_DIR))


_prepare_runtime()

from api.documents import router as documents_router
from api.foundation import router as foundation_router
from database.neo4j import driver
from security.secure import get_password_hash

app = FastAPI()
app.include_router(foundation_router)
app.include_router(documents_router)


def _client_secret():
    return Path("/run/secrets/kontroll_client_secret").read_text(encoding="utf-8").rstrip("\n")


def _realpath(path):
    return os.path.realpath(path)


def _is_under(path, root):
    real = _realpath(path)
    base = _realpath(root)
    return real == base or real.startswith(base + os.sep)


def _ignored(path):
    return _is_under(path, LOGS_ROOT)


def _allowed(path):
    return _is_under(path, PARTS_ROOT) or _is_under(path, DOCUMENTS_ROOT)


def _outside_snapshot():
    """Directories and files whose resolved path is outside the two store roots."""
    directories = set()
    files = {}
    for dirpath, dirnames, filenames in os.walk(SANDBOX, followlinks=False):
        if _ignored(dirpath):
            dirnames[:] = []
            continue
        if _allowed(dirpath):
            continue
        directories.add(_realpath(dirpath))
        for name in filenames:
            path = os.path.join(dirpath, name)
            if _ignored(path) or _allowed(path):
                continue
            files[_realpath(path)] = Path(path).read_bytes()
    return directories, files


def _assert_outside_store_unchanged(before):
    before_dirs, before_files = before
    after_dirs, after_files = _outside_snapshot()
    created_dirs = sorted(after_dirs - before_dirs)
    removed_dirs = sorted(before_dirs - after_dirs)
    created_files = sorted(set(after_files) - set(before_files))
    removed_files = sorted(set(before_files) - set(after_files))
    changed_files = sorted(
        path for path in set(before_files) & set(after_files) if before_files[path] != after_files[path]
    )
    problems = []
    if created_dirs:
        problems.append("created directories: " + ", ".join(created_dirs))
    if removed_dirs:
        problems.append("removed directories: " + ", ".join(removed_dirs))
    if created_files:
        problems.append("created files: " + ", ".join(created_files))
    if removed_files:
        problems.append("removed files: " + ", ".join(removed_files))
    if changed_files:
        problems.append("changed files: " + ", ".join(changed_files))
    assert not problems, "upload flow modified paths outside the document store; " + "; ".join(problems)


def _payloads_outside_store():
    found = []
    for dirpath, dirnames, filenames in os.walk(SANDBOX, followlinks=False):
        if _ignored(dirpath):
            dirnames[:] = []
            continue
        for name in filenames:
            path = os.path.join(dirpath, name)
            if _ignored(path) or _allowed(path):
                continue
            data = Path(path).read_bytes()
            if PART_PAYLOAD in data or COMPLETE_PAYLOAD in data or INSIDE_PAYLOAD in data:
                found.append(_realpath(path))
    return found


@pytest.fixture(scope="module")
def signed_in_client():
    username = "ordinary-user"
    with driver.session() as session:
        session.run("MATCH (u:User {username: $username}) DETACH DELETE u", username=username).consume()
        session.run(
            """
            CREATE (u:User {
                username: $username,
                email: $email,
                full_name: $full_name,
                hashed_password: $hashed_password,
                disabled: false
            })
            """,
            username=username,
            email="ordinary@example.com",
            full_name="Ordinary User",
            hashed_password=get_password_hash(PLACEHOLDER),
        ).consume()

    with TestClient(app) as client:
        code = client.get(
            "/foundation/oauth2/code",
            params={
                "username": username,
                "password": PLACEHOLDER,
                "response_type": "code",
                "client_id": os.environ["KONTROLL_CLIENT_ID"],
                "client_name": os.environ["KONTROLL_CLIENT_NAME"],
                "state": "state",
                "redirect_uri": "http://127.0.0.1/callback",
                "scope": "test",
            },
        )
        assert code.status_code == 200, code.text
        token = client.post(
            "/foundation/oauth2/token",
            data={"grant_type": "authorization_code", "code": code.json()},
            auth=(os.environ["KONTROLL_CLIENT_ID"], _client_secret()),
        )
        assert token.status_code == 201, token.text
        headers = {"Authorization": "Bearer " + token.json()["access_token"]}
        yield client, headers, username


def _start_upload(client, headers, username, document_id, payload):
    file_entry = {"file_name": "a.ifc", "session_file_id": "s1"}
    if document_id is not None:
        file_entry["document_id"] = document_id
    started = _post(
        client,
        "/documents/1.0/upload-documents",
        json={
            "server_context": "ctx",
            "callback": {"url": "http://127.0.0.1/callback", "expires_in": 3600},
            "files": [file_entry],
        },
        headers=headers,
    )
    if getattr(started, "status_code", None) != 200:
        return None
    upload_session = started.json()["upload_ui_url"].split("upload_session=", 1)[1]
    # The upload UI posts this form with no bearer token.
    saved = _post(
        client,
        "/documents/1.0/save-metadata-for-documents",
        data={
            "username": username,
            "upload_session": upload_session,
            "server_context": "ctx",
            "callback_url": "http://127.0.0.1/callback",
            "callback_expires_in": "3600",
            "project": "any",
            "session_file_id@k": "s1",
            "version_number@k": "1",
            "title@k": "x",
        },
    )
    if getattr(saved, "status_code", None) != 200:
        return None
    instructions = _post(
        client,
        "/documents/1.0/upload-instructions",
        params={"session_id": upload_session, "server_context": "ctx"},
        json={"files": [{"session_file_id": "s1", "size_in_bytes": len(payload)}]},
        headers=headers,
    )
    if getattr(instructions, "status_code", None) != 200:
        return None
    part_url = instructions.json()["documents_to_upload"][0]["upload_file_parts"][0]["url"]
    part_id = part_url.rstrip("/").rsplit("/", 1)[1]
    return upload_session, part_id


def _post(client, path, **kwargs):
    try:
        return client.post(path, **kwargs)
    except Exception as exc:
        return exc


def test_upload_part_does_not_write_outside_parts_directory(signed_in_client):
    client, headers, username = signed_in_client
    victim = SANDBOX / "data" / "part-victim"
    victim.mkdir()
    (victim / "sentinel").write_text("keep", encoding="utf-8")
    before = _outside_snapshot()

    started = _start_upload(client, headers, username, "../part-victim", PART_PAYLOAD)
    if started is None:
        _assert_outside_store_unchanged(before)
        return
    _part_session, part_id = started
    _post(
        client,
        "/documents/1.0/upload-part/" + part_id,
        content=PART_PAYLOAD,
        headers=headers,
    )

    _assert_outside_store_unchanged(before)
    assert _payloads_outside_store() == []
    assert (victim / "sentinel").read_text(encoding="utf-8") == "keep"


def test_upload_cancellation_does_not_delete_outside_parts_directory(signed_in_client):
    client, headers, username = signed_in_client
    victim = SANDBOX / "cancel-victim"
    victim.mkdir()
    (victim / "sentinel").write_text("keep", encoding="utf-8")
    before = _outside_snapshot()

    started = _start_upload(client, headers, username, "../../cancel-victim", PART_PAYLOAD)
    if started is None:
        _assert_outside_store_unchanged(before)
        return
    upload_session, _part_id = started
    _post(
        client,
        "/documents/1.0/upload-cancellation",
        params={"upload_session": upload_session},
        headers=headers,
    )

    _assert_outside_store_unchanged(before)
    assert (victim / "sentinel").read_text(encoding="utf-8") == "keep"


def test_upload_completion_does_not_write_or_delete_outside_store(signed_in_client):
    client, headers, username = signed_in_client
    victim = SANDBOX / "complete-victim"
    victim.mkdir()
    (victim / "sentinel").write_text("keep", encoding="utf-8")
    before = _outside_snapshot()

    started = _start_upload(client, headers, username, "../../complete-victim", COMPLETE_PAYLOAD)
    if started is None:
        _assert_outside_store_unchanged(before)
        return
    upload_session, part_id = started
    _post(
        client,
        "/documents/1.0/upload-part/" + part_id,
        content=COMPLETE_PAYLOAD,
        headers=headers,
    )
    _post(
        client,
        "/documents/1.0/upload-completion",
        params={"upload_session": upload_session},
        headers=headers,
    )

    _assert_outside_store_unchanged(before)
    assert _payloads_outside_store() == []
    assert (victim / "sentinel").read_text(encoding="utf-8") == "keep"


def test_server_chosen_document_id_stays_inside_parts_directory(signed_in_client):
    client, headers, username = signed_in_client
    neighbor = PARTS_ROOT / "neighbor-sentinel"
    neighbor.write_text("keep", encoding="utf-8")
    outside = SANDBOX / "outside-sentinel"
    outside.mkdir()
    (outside / "sentinel").write_text("keep", encoding="utf-8")
    before = _outside_snapshot()

    started = _start_upload(client, headers, username, None, INSIDE_PAYLOAD)
    assert started is not None, "a server-chosen document id did not produce upload instructions"
    upload_session, part_id = started
    uploaded = client.post(
        "/documents/1.0/upload-part/" + part_id,
        content=INSIDE_PAYLOAD,
        headers=headers,
    )
    assert uploaded.status_code == 200, uploaded.text

    stored = []
    for dirpath, _dirnames, filenames in os.walk(PARTS_ROOT):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if Path(path).read_bytes() == INSIDE_PAYLOAD:
                stored.append(path)
    assert stored, "server-chosen document id did not store the part under data/document_parts"
    assert all(_is_under(path, PARTS_ROOT) for path in stored)

    cancelled = client.post(
        "/documents/1.0/upload-cancellation",
        params={"upload_session": upload_session},
        headers=headers,
    )
    assert cancelled.status_code == 204, cancelled.text
    assert neighbor.read_text(encoding="utf-8") == "keep"
    _assert_outside_store_unchanged(before)
    assert (outside / "sentinel").read_text(encoding="utf-8") == "keep"
