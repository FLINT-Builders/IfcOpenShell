# This file was generated with the assistance of an AI coding tool.
"""Pytest setup for the OpenCDE API.

Importing the application connects to Neo4j and runs db_config/init.cypher,
which deletes every node in that database. Point NEO4J_URI at a disposable
Neo4j 5.7 server before collecting tests.
"""

import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

APP_DIR = Path(__file__).resolve().parents[1]
PLACEHOLDER_SECURITY_SECRET = "placeholder-security-secret"

os.chdir(APP_DIR)
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

os.environ.setdefault("NEO4J_URI", "bolt://127.0.0.1:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_INITIAL_PASSWORD", "placeholder-neo4j-password")
os.environ.setdefault("SECURITY_ALGORITHM", "HS256")
os.environ.setdefault("KONTROLL_BASE_URL", "http://127.0.0.1/")
os.environ.setdefault("KONTROLL_CLIENT_ID", "placeholder-client")
os.environ.setdefault("KONTROLL_CLIENT_NAME", "placeholder")
os.environ.setdefault("SECURITY_AUTHORIZATION_CODE_EXPIRE_SECONDS", "60")
os.environ.setdefault("SECURITY_ACCESS_TOKEN_EXPIRE_SECONDS", "3600")
os.environ.setdefault("SECURITY_REFRESH_TOKEN_EXPIRE_SECONDS", "3600")

(APP_DIR / "logs").mkdir(exist_ok=True)
(APP_DIR / "data" / "snapshots").mkdir(parents=True, exist_ok=True)
(APP_DIR / "data" / "bitmaps").mkdir(parents=True, exist_ok=True)

_secret_path = Path("/run/secrets/security_secret_key")
if not _secret_path.exists():
    try:
        _secret_path.parent.mkdir(parents=True, exist_ok=True)
        _secret_path.write_text(PLACEHOLDER_SECURITY_SECRET + "\n")
    except OSError as exc:
        pytest.exit(
            "The API reads its signing key from /run/secrets/security_secret_key "
            f"({exc}). Create that file with a local placeholder before running these tests.",
            returncode=1,
        )

from api.bcf import router
from database.neo4j import driver


@pytest.fixture(scope="session")
def api():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="session")
def graph():
    return driver
