# This file was generated with the assistance of an AI coding tool.

"""Authorization and disk-use tests for POST /documents/1.0/upload_file_to_project.

The route is expected to reject callers who are not the user that owns the
selection session, to refuse a project that session is not allowed to use, to
refuse a body larger than SESSION_MAX_FILE_SIZE_BYTES, and to leave no file in
./data/documents when the request is rejected for any of those reasons or when
a later step fails. Assertions look at the stored bytes and the Document node
that was linked, so a check that is not the check applied to the write does
not satisfy them.
"""

import os
from pathlib import Path

from repository.documents import doc_db
from tests.conftest import PROJECT_A, PROJECT_B, SESSION_A, SESSION_B

UPLOAD_URL = "/documents/1.0/upload_file_to_project"
DOCUMENTS_DIR = Path("data/documents")


def _post_upload(client, filename, content, project, selection_session, token=None):
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        UPLOAD_URL,
        headers=headers,
        data={"project": project, "selection_session": selection_session},
        files={"file": (filename, content, "application/octet-stream")},
    )


def _paths_with_marker(marker):
    found = []
    for path in DOCUMENTS_DIR.iterdir():
        if path.is_file() and marker in path.read_bytes():
            found.append(path)
    return found


def _document_count(neo4j_driver, filename):
    with neo4j_driver.session() as session:
        record = session.run(
            "MATCH (d:Document {original_file_name:$name}) RETURN count(d) AS count",
            name=filename,
        ).single()
        return record["count"]


def _documents_on_project(neo4j_driver, project_id, filename):
    with neo4j_driver.session() as session:
        record = session.run(
            """
            MATCH (p:Project {project_id:$project_id})-[:CONTAINS]->(d:Document {original_file_name:$name})
            RETURN count(d) AS count
            """,
            project_id=project_id,
            name=filename,
        ).single()
        return record["count"]


def _cleanup(neo4j_driver, filename, marker):
    for path in _paths_with_marker(marker):
        path.unlink(missing_ok=True)
    with neo4j_driver.session() as session:
        session.run(
            "MATCH (d:Document {original_file_name:$name}) DETACH DELETE d",
            name=filename,
        )


def test_unauthenticated_uploads_are_rejected_and_leave_no_file(client, neo4j_driver):
    filename = "unauth-upload.ifc"
    marker = b"UNAUTH-UPLOAD-MARKER"
    content = marker + b"x" * 128
    try:
        first = _post_upload(client, filename, content, project="not-a-project", selection_session="not-a-session")
        second = _post_upload(client, filename, content, project="not-a-project", selection_session="not-a-session")

        assert first.status_code in (401, 403)
        assert second.status_code in (401, 403)
        assert _paths_with_marker(marker) == []
        assert _document_count(neo4j_driver, filename) == 0
    finally:
        _cleanup(neo4j_driver, filename, marker)


def test_invalid_bearer_token_leaves_no_file(client, neo4j_driver):
    filename = "bad-token-upload.ifc"
    marker = b"BAD-TOKEN-UPLOAD-MARKER"
    content = marker + b"y" * 64
    try:
        response = _post_upload(
            client,
            filename,
            content,
            project="not-a-project",
            selection_session="not-a-session",
            token="placeholder-not-a-token",
        )

        assert response.status_code in (401, 403)
        assert _paths_with_marker(marker) == []
        assert _document_count(neo4j_driver, filename) == 0
    finally:
        _cleanup(neo4j_driver, filename, marker)


def test_other_users_session_cannot_receive_the_upload(client, neo4j_driver, token_a):
    filename = "cross-user-upload.ifc"
    marker = b"CROSS-USER-UPLOAD-MARKER"
    content = marker + b"z" * 64
    try:
        response = _post_upload(
            client,
            filename,
            content,
            project=PROJECT_B,
            selection_session=SESSION_B,
            token=token_a,
        )

        assert 400 <= response.status_code < 500
        assert _paths_with_marker(marker) == []
        assert _document_count(neo4j_driver, filename) == 0
        assert _documents_on_project(neo4j_driver, PROJECT_B, filename) == 0
    finally:
        _cleanup(neo4j_driver, filename, marker)


def test_session_cannot_store_a_file_on_a_different_project(client, neo4j_driver, token_a):
    filename = "wrong-project-upload.ifc"
    marker = b"WRONG-PROJECT-UPLOAD-MARKER"
    content = marker + b"w" * 64
    try:
        response = _post_upload(
            client,
            filename,
            content,
            project=PROJECT_B,
            selection_session=SESSION_A,
            token=token_a,
        )

        assert 400 <= response.status_code < 500
        assert _paths_with_marker(marker) == []
        assert _document_count(neo4j_driver, filename) == 0
        assert _documents_on_project(neo4j_driver, PROJECT_A, filename) == 0
        assert _documents_on_project(neo4j_driver, PROJECT_B, filename) == 0
    finally:
        _cleanup(neo4j_driver, filename, marker)


def test_upload_over_session_max_file_size_is_not_stored(client, neo4j_driver, token_a, monkeypatch):
    filename = "oversize-upload.ifc"
    marker = b"OVERSIZE-UPLOAD-MARKER"
    limit = 128
    content = marker + b"o" * (limit + 1)
    previous_limit = os.environ.get("SESSION_MAX_FILE_SIZE_BYTES")
    os.environ["SESSION_MAX_FILE_SIZE_BYTES"] = str(limit)
    monkeypatch.setattr(doc_db, "create_ifc_graph_for_document", lambda document_id: None)
    try:
        response = _post_upload(
            client,
            filename,
            content,
            project=PROJECT_A,
            selection_session=SESSION_A,
            token=token_a,
        )

        assert 400 <= response.status_code < 500
        assert _paths_with_marker(marker) == []
        assert _document_count(neo4j_driver, filename) == 0
    finally:
        if previous_limit is None:
            os.environ.pop("SESSION_MAX_FILE_SIZE_BYTES", None)
        else:
            os.environ["SESSION_MAX_FILE_SIZE_BYTES"] = previous_limit
        _cleanup(neo4j_driver, filename, marker)


def test_upload_within_limit_is_stored_for_the_authorized_project(client, neo4j_driver, token_a, monkeypatch):
    filename = "within-limit-upload.ifc"
    marker = b"WITHIN-LIMIT-UPLOAD-MARKER"
    limit = 4096
    content = marker + b"i" * 32
    previous_limit = os.environ.get("SESSION_MAX_FILE_SIZE_BYTES")
    os.environ["SESSION_MAX_FILE_SIZE_BYTES"] = str(limit)
    monkeypatch.setattr(doc_db, "create_ifc_graph_for_document", lambda document_id: None)
    try:
        response = _post_upload(
            client,
            filename,
            content,
            project=PROJECT_A,
            selection_session=SESSION_A,
            token=token_a,
        )

        assert response.status_code == 200
        stored = _paths_with_marker(marker)
        assert len(stored) == 1
        assert stored[0].stat().st_size == len(content)
        assert stored[0].stat().st_size <= limit
        assert _documents_on_project(neo4j_driver, PROJECT_A, filename) == 1
        assert _documents_on_project(neo4j_driver, PROJECT_B, filename) == 0
    finally:
        if previous_limit is None:
            os.environ.pop("SESSION_MAX_FILE_SIZE_BYTES", None)
        else:
            os.environ["SESSION_MAX_FILE_SIZE_BYTES"] = previous_limit
        _cleanup(neo4j_driver, filename, marker)


def test_file_is_removed_when_a_later_step_fails(client, neo4j_driver, token_a):
    filename = "later-step-upload.ifc"
    marker = b"LATER-STEP-UPLOAD-MARKER"
    content = marker + b"not-an-ifc-file"
    try:
        response = _post_upload(
            client,
            filename,
            content,
            project=PROJECT_A,
            selection_session=SESSION_A,
            token=token_a,
        )

        assert response.status_code >= 400
        assert _paths_with_marker(marker) == []
    finally:
        _cleanup(neo4j_driver, filename, marker)
