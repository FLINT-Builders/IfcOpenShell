# This file was generated with the assistance of an AI coding tool.
"""OpenCDE must not wipe Neo4j on startup, and an upload must not kill the API.

These tests fail while startup still runs db_config/init.cypher (its first
statement deletes every node) and while upload_documents_post parses the
uploaded IFC inside the API process. They pass once startup leaves existing
data in place and a deeply nested IFC upload cannot take the process down.

model.cypher begins with the same delete statement but nothing in the server
loads it, so it is not covered here.
"""

import asyncio
import io
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from neo4j import GraphDatabase
from starlette.datastructures import UploadFile

APP_DIR = Path(__file__).resolve().parents[1] / "api" / "app"
NEST_DEPTH = 50000


def _env():
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_INITIAL_PASSWORD")
    base_url = os.environ.get("KONTROLL_BASE_URL", "http://placeholder.example/")
    missing = [
        name
        for name, value in (("NEO4J_URI", uri), ("NEO4J_USER", user), ("NEO4J_INITIAL_PASSWORD", password))
        if not value
    ]
    if missing:
        pytest.fail(
            "Set " + ", ".join(missing) + " to a Neo4j the OpenCDE app can use. Do not put a real secret in the test."
        )
    env = os.environ.copy()
    env["NEO4J_URI"] = uri
    env["NEO4J_USER"] = user
    env["NEO4J_INITIAL_PASSWORD"] = password
    env["KONTROLL_BASE_URL"] = base_url
    env["PYTHONPATH"] = os.pathsep.join(part for part in (str(APP_DIR), env.get("PYTHONPATH", "")) if part)
    return env


def _driver():
    env = _env()
    return GraphDatabase.driver(env["NEO4J_URI"], auth=(env["NEO4J_USER"], env["NEO4J_INITIAL_PASSWORD"]))


def _count(session, label, marker):
    record = session.execute_read(
        lambda tx: tx.run(
            f"MATCH (n:{label} {{marker: $marker}}) RETURN count(n) AS c",
            marker=marker,
        ).single()
    )
    return record["c"]


def _import_app():
    """Load the same module main.py imports first, which initializes Neo4j."""
    (APP_DIR / "logs").mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, "-c", "import api.bcf"],
        cwd=APP_DIR,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _nested_ifc(depth):
    nested = "(" * depth + "0." + ")" * depth
    return (
        "ISO-10303-21;\n"
        "HEADER;\n"
        "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
        "FILE_NAME('nested.ifc','2020-01-01T00:00:00',(''),(''),'','','');\n"
        "FILE_SCHEMA(('IFC4'));\n"
        "ENDSEC;\n"
        "DATA;\n"
        f"#1=IFCCARTESIANPOINT({nested});\n"
        "ENDSEC;\n"
        "END-ISO-10303-21;\n"
    ).encode()


def _upload_worker():
    os.chdir(APP_DIR)
    (APP_DIR / "logs").mkdir(parents=True, exist_ok=True)
    (APP_DIR / "data" / "documents").mkdir(parents=True, exist_ok=True)
    import api.documents as documents

    marker = os.environ["TENANT_MARKER"]
    selection = os.environ["SELECTION_SESSION"]
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_INITIAL_PASSWORD"]),
    )
    with driver.session() as session:
        session.execute_write(lambda tx: tx.run("CREATE (:TenantData {marker: $marker})", marker=marker).consume())
        granted = session.execute_read(
            lambda tx: tx.run(
                """
                MATCH (u:User)-[:HAS_ACTIONS_ON]->(p:Project)
                RETURN u.username AS username, p.project_id AS project_id
                LIMIT 1
                """
            ).single()
        )
        if granted is None:
            raise SystemExit("startup did not leave a user with access to a project")
        session.execute_write(
            lambda tx: tx.run(
                """
                MATCH (u:User {username: $username})
                CREATE (u)-[:HAS]->(:Session:Select {selection_session: $selection})
                """,
                username=granted["username"],
                selection=selection,
            ).consume()
        )
        project_id = granted["project_id"]
    driver.close()

    upload = UploadFile(filename="nested.ifc", file=io.BytesIO(_nested_ifc(NEST_DEPTH)))

    async def go():
        return await documents.upload_documents_post(upload, project_id, selection)

    asyncio.run(go())
    print("upload-returned", flush=True)


def test_import_does_not_delete_data_already_in_the_database():
    marker = "before-startup-" + uuid.uuid4().hex
    driver = _driver()
    with driver.session() as session:
        session.execute_write(lambda tx: tx.run("CREATE (:Survivor {marker: $marker})", marker=marker).consume())
    started = _import_app()
    assert started.returncode == 0, started.stderr
    with driver.session() as session:
        assert _count(session, "Survivor", marker) == 1
    driver.close()


def test_second_startup_keeps_data_written_while_the_server_was_up():
    marker = "after-startup-" + uuid.uuid4().hex
    started = _import_app()
    assert started.returncode == 0, started.stderr
    driver = _driver()
    with driver.session() as session:
        session.execute_write(lambda tx: tx.run("CREATE (:TenantData {marker: $marker})", marker=marker).consume())
    restarted = _import_app()
    assert restarted.returncode == 0, restarted.stderr
    with driver.session() as session:
        assert _count(session, "TenantData", marker) == 1
    driver.close()


def test_nested_ifc_upload_does_not_kill_the_api_process_or_its_data():
    marker = "upload-tenant-" + uuid.uuid4().hex
    selection = "selection-" + uuid.uuid4().hex
    env = _env()
    env["TENANT_MARKER"] = marker
    env["SELECTION_SESSION"] = selection
    (APP_DIR / "logs").mkdir(parents=True, exist_ok=True)
    (APP_DIR / "data" / "documents").mkdir(parents=True, exist_ok=True)
    before = {path.name for path in (APP_DIR / "data" / "documents").iterdir()}
    worker = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "upload-worker"],
        cwd=APP_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        assert worker.returncode == 0, (worker.returncode, worker.stdout, worker.stderr)
        assert "upload-returned" in worker.stdout
        restarted = _import_app()
        assert restarted.returncode == 0, restarted.stderr
        driver = _driver()
        with driver.session() as session:
            assert _count(session, "TenantData", marker) == 1
        driver.close()
    finally:
        for path in (APP_DIR / "data" / "documents").iterdir():
            if path.name not in before and path.is_file():
                path.unlink()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "upload-worker":
        _upload_worker()
    else:
        raise SystemExit("Run this file with pytest.")
