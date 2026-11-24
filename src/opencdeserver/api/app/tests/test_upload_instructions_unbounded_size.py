# This file was generated with the assistance of an AI coding tool.
"""Bounds for OpenCDE upload-instructions file sizes.

The server advertises ``SESSION_MAX_FILE_SIZE_BYTES`` as ``max_size_in_bytes``
and describes it as the maximum file size, above which an upload must fail.
``size_in_bytes`` on an upload-instructions request has to be an integer in
``1 .. that maximum`` inclusive. A request that breaks the bound, including one
file in a multi-file body, must be rejected before any Neo4j write: no size
update and no Part node.

These tests fail while an oversized or non-positive size is stored or split
into parts.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

os.environ.setdefault("NEO4J_URI", "neo4j://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_INITIAL_PASSWORD", "placeholder")
os.environ.setdefault("KONTROLL_BASE_URL", "http://localhost/")
os.environ.setdefault("KONTROLL_CLIENT_ID", "placeholder-client")
os.environ.setdefault("KONTROLL_CLIENT_NAME", "placeholder-client")
os.environ.setdefault("SECURITY_ALGORITHM", "HS256")
os.environ.setdefault("SECURITY_ACCESS_TOKEN_EXPIRE_SECONDS", "3600")
os.environ.setdefault("SECURITY_REFRESH_TOKEN_EXPIRE_SECONDS", "7200")
os.environ.setdefault("SECURITY_AUTHORIZATION_CODE_EXPIRE_SECONDS", "60")
os.environ.setdefault("SESSION_URL_VALIDITY_SECONDS", "60")
os.environ.setdefault("SESSION_MAX_FILE_SIZE_BYTES", "1073741824")

# Stop the part loop if the product still creates one Part per unbounded chunk.
# A legal file at the advertised maximum is a single part with the chunk size
# this server uses, so a handful of creates is already past any accepted request.
PART_CREATE_SAFETY_LIMIT = 4
OWNER = "ordinary-user"
OTHER = "other-user"
SESSION_ID = "session-1"
FILE_ID = "file-a"
PLACEHOLDER_SECRET = "placeholder-secret"


class _Counters:
    def __init__(self, nodes_created: int, properties_set: int):
        self.nodes_created = nodes_created
        self.properties_set = properties_set


class _Summary:
    def __init__(self, counters: _Counters):
        self.counters = counters


class _Result:
    def __init__(self, summary: _Summary):
        self._summary = summary

    def consume(self):
        # neo4j 5.9.0 Result.consume returns the summary the unit of work reads.
        return self._summary


class RecordingDriver:
    """Stand-in for neo4j.GraphDatabase.driver used by ``database.neo4j``.

    ``Session.execute_write`` in neo4j 5.9.0 runs the unit of work and returns
    its value, then commits. This driver does the same call and return. A
    CREATE of a Part counts as one node, and a SET counts as a property write,
    only when the parameters match the caller's own seeded upload document.
    That is the MATCH in ``get_upload_instructions``: username, upload session,
    and session file id together. A query that does not name those parameters
    does not match, so it cannot create a Part for a session the caller does
    not own.
    """

    def __init__(self):
        self.parts: list[dict] = []
        self.size_updates: list[dict] = []
        self.queries: list[dict] = []
        self.sessions_opened = 0
        self.owned = {
            (OWNER, SESSION_ID, FILE_ID),
            (OWNER, SESSION_ID, "file-b"),
        }

    def reset(self):
        self.parts.clear()
        self.size_updates.clear()
        self.queries.clear()
        self.sessions_opened = 0

    def verify_connectivity(self):
        return None

    def session(self):
        self.sessions_opened += 1
        return _RecordingSession(self)


class _RecordingSession:
    def __init__(self, driver: RecordingDriver):
        self._driver = driver

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute_write(self, work, *args, **kwargs):
        return work(_RecordingTx(self._driver), *args, **kwargs)


class _RecordingTx:
    def __init__(self, driver: RecordingDriver):
        self._driver = driver

    def run(self, cypher, **params):
        self._driver.queries.append({"cypher": cypher, "params": dict(params)})
        matched = self._matches(params, cypher)
        creates_part = "CREATE" in cypher and ":Part" in cypher
        sets_size = "d.size_in_bytes" in cypher and "SET" in cypher
        if matched and creates_part:
            if len(self._driver.parts) >= PART_CREATE_SAFETY_LIMIT:
                raise RuntimeError("part creation was not bounded")
            self._driver.parts.append(dict(params))
            return _Result(_Summary(_Counters(nodes_created=1, properties_set=1)))
        if matched and sets_size:
            self._driver.size_updates.append(dict(params))
            return _Result(_Summary(_Counters(nodes_created=0, properties_set=1)))
        return _Result(_Summary(_Counters(nodes_created=0, properties_set=0)))

    def _matches(self, params, cypher) -> bool:
        needed = ("$username", "$upload_session", "$session_file_id")
        if any(token not in cypher for token in needed):
            return False
        key = (params.get("username"), params.get("upload_session"), params.get("session_file_id"))
        return key in self._driver.owned


DRIVER = RecordingDriver()


def _install_import_stubs():
    neo4j_mod = types.ModuleType("neo4j")

    class GraphDatabase:
        @staticmethod
        def driver(uri, auth=None):
            return DRIVER

    neo4j_mod.GraphDatabase = GraphDatabase
    sys.modules["neo4j"] = neo4j_mod

    ifcopenshell = types.ModuleType("ifcopenshell")
    util = types.ModuleType("ifcopenshell.util")
    schema = types.ModuleType("ifcopenshell.util.schema")
    ifcopenshell.util = util
    sys.modules["ifcopenshell"] = ifcopenshell
    sys.modules["ifcopenshell.util"] = util
    sys.modules["ifcopenshell.util.schema"] = schema

    py2neo = types.ModuleType("py2neo")
    py2neo_data = types.ModuleType("py2neo.data")
    py2neo.Graph = object
    py2neo.data = py2neo_data
    py2neo_data.Node = object
    py2neo_data.Relationship = object
    sys.modules["py2neo"] = py2neo
    sys.modules["py2neo.data"] = py2neo_data


_install_import_stubs()

import security.secrets as secrets_mod

secrets_mod.get_secrets = lambda: {
    "security_secret_key": PLACEHOLDER_SECRET,
    "kontroll_client_secret": PLACEHOLDER_SECRET,
    "neo4j_password": "placeholder",
}

from api.documents import router as documents_router
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from models.documents_request import UploadFileDetail
from models.request import UserInDB
from pydantic import ValidationError
from repository.documents import doc_db
from security.secure import create_access_token
from security.secure import db as security_db

ADVERTISED_MAX = int(os.environ["SESSION_MAX_FILE_SIZE_BYTES"])
ATTACK_SIZE = 10**21

app = FastAPI()
app.include_router(documents_router)


def _user(username: str) -> UserInDB:
    return UserInDB(
        username=username,
        email=f"{username}@example.com",
        full_name=username,
        disabled=False,
        hashed_password="placeholder",
    )


def _token(username: str, scopes: list[str]) -> str:
    return create_access_token({"username": username, "scopes": scopes})


def _auth(username: str, scopes: list[str] | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(username, scopes if scopes is not None else ['test'])}"}


def _post(client: TestClient, username: str, files: list[dict], scopes: list[str] | None = None):
    return client.post(
        "/documents/1.0/upload-instructions",
        params={"session_id": SESSION_ID, "server_context": "x"},
        json={"files": files},
        headers=_auth(username, scopes),
    )


def _file(size: int, session_file_id: str = FILE_ID) -> dict:
    return {"session_file_id": session_file_id, "size_in_bytes": size}


def _owner() -> UserInDB:
    return _user(OWNER)


def _assert_http_rejected(response, driver: RecordingDriver):
    assert response.status_code in (400, 422), response.text
    assert driver.parts == []
    assert driver.size_updates == []


def _assert_repository_rejects(size: int):
    DRIVER.reset()
    try:
        detail = UploadFileDetail(size_in_bytes=size, session_file_id=FILE_ID)
        doc_db.get_upload_instructions(SESSION_ID, "x", detail, _owner())
    except ValidationError:
        rejected = True
    except HTTPException as exc:
        assert exc.status_code in (400, 422)
        rejected = True
    except (RuntimeError, ZeroDivisionError) as exc:
        raise AssertionError(
            f"size_in_bytes={size} was not rejected before a write "
            f"({type(exc).__name__}: {exc}; parts={len(DRIVER.parts)}, "
            f"size_updates={len(DRIVER.size_updates)})"
        ) from exc
    else:
        rejected = False
    assert rejected, f"size_in_bytes={size} was accepted"
    assert DRIVER.parts == []
    assert DRIVER.size_updates == []


def setup_function():
    DRIVER.reset()
    security_db.get_user = lambda username: _user(username)


def test_ordinary_user_upload_at_advertised_maximum_creates_one_part():
    with TestClient(app) as client:
        response = _post(client, OWNER, [_file(ADVERTISED_MAX)])
    assert response.status_code == 200, response.text
    body = response.json()
    parts = body["documents_to_upload"][0]["upload_file_parts"]
    assert 1 <= len(parts) <= PART_CREATE_SAFETY_LIMIT
    assert len(DRIVER.parts) == len(parts)
    assert DRIVER.size_updates == [] or DRIVER.size_updates[0]["size_in_bytes"] == ADVERTISED_MAX


def test_token_without_normal_scope_cannot_upload():
    with TestClient(app) as client:
        response = _post(client, OWNER, [_file(ADVERTISED_MAX)], scopes=["user"])
    assert response.status_code == 401
    assert DRIVER.parts == []
    assert DRIVER.size_updates == []


def test_other_user_cannot_create_parts_for_someone_elses_session():
    with TestClient(app) as client:
        response = _post(client, OTHER, [_file(ADVERTISED_MAX)])
    assert response.status_code in (400, 401, 403, 404)
    assert DRIVER.parts == []


def test_size_above_advertised_maximum_is_rejected_before_any_write():
    with TestClient(app) as client:
        response = _post(client, OWNER, [_file(ADVERTISED_MAX + 1)])
    _assert_http_rejected(response, DRIVER)


def test_non_positive_size_is_rejected_before_any_write():
    for size in (0, -1):
        DRIVER.reset()
        with TestClient(app) as client:
            try:
                response = _post(client, OWNER, [_file(size)])
            except (RuntimeError, ZeroDivisionError) as exc:
                raise AssertionError(
                    f"size_in_bytes={size} was not rejected before a write "
                    f"({type(exc).__name__}: {exc}; parts={len(DRIVER.parts)}, "
                    f"size_updates={len(DRIVER.size_updates)})"
                ) from exc
        _assert_http_rejected(response, DRIVER)


def test_attack_size_does_not_start_part_creation():
    with TestClient(app) as client:
        try:
            response = _post(client, OWNER, [_file(ATTACK_SIZE)])
        except RuntimeError as exc:
            raise AssertionError(
                f"upload-instructions started unbounded part creation: {exc}; parts={len(DRIVER.parts)}"
            ) from exc
    _assert_http_rejected(response, DRIVER)


def test_second_file_over_maximum_rejects_entire_request_before_writes():
    files = [_file(ADVERTISED_MAX, FILE_ID), _file(ADVERTISED_MAX + 1, "file-b")]
    with TestClient(app) as client:
        response = _post(client, OWNER, files)
    _assert_http_rejected(response, DRIVER)


def test_repository_rejects_size_above_maximum_before_any_write():
    _assert_repository_rejects(ADVERTISED_MAX + 1)


def test_repository_rejects_non_positive_size_before_any_write():
    _assert_repository_rejects(0)
    _assert_repository_rejects(-1)


def test_repository_rejects_attack_size_before_any_write():
    _assert_repository_rejects(ATTACK_SIZE)
