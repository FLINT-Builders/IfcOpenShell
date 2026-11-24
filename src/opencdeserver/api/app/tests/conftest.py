# This file was generated with the assistance of an AI coding tool.

"""Load the OpenCDE app without a running graph database.

Token expiry is decided in ``create_access_token`` and ``jwt.decode`` before a
query result is used. The session double only does what neo4j 5.9.0's
``Session._run_transaction`` does with the unit of work: call it and let
exceptions other than driver errors propagate
(``neo4j/_sync/work/session.py``). The transaction functions from this
repository run unchanged.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
os.chdir(APP_DIR)
sys.path.insert(0, str(APP_DIR))
(APP_DIR / "logs").mkdir(exist_ok=True)

os.environ["NEO4J_URI"] = "bolt://127.0.0.1:7687"
os.environ["NEO4J_USER"] = "neo4j"
os.environ["NEO4J_INITIAL_PASSWORD"] = "placeholder-password"
os.environ["SECURITY_ALGORITHM"] = "HS256"
os.environ["SECURITY_ACCESS_TOKEN_EXPIRE_SECONDS"] = "1"
os.environ["SECURITY_REFRESH_TOKEN_EXPIRE_SECONDS"] = "1"
os.environ["SECURITY_AUTHORIZATION_CODE_EXPIRE_SECONDS"] = "60"
os.environ["KONTROLL_BASE_URL"] = "https://cde.example.test/"
os.environ["KONTROLL_CLIENT_ID"] = "test-client"
os.environ["KONTROLL_CLIENT_NAME"] = "test-client-name"
os.environ["SESSION_URL_VALIDITY_SECONDS"] = "60"
os.environ["SESSION_MAX_FILE_SIZE_BYTES"] = "1000"

import security.secrets as secrets_mod

_PLACEHOLDER_SECRETS = {
    "security_secret_key": "test-signing-key-placeholder",
    "kontroll_client_secret": "test-client-secret-placeholder",
    "neo4j_password": "test-neo4j-password-placeholder",
}


def _placeholder_secrets():
    return dict(_PLACEHOLDER_SECRETS)


secrets_mod.get_secrets = _placeholder_secrets

import neo4j


class GraphState:
    stored_access_token = None
    stored_refresh_token = None


graph_state = GraphState()


class _Counters:
    def __init__(self):
        self.nodes_created = 2
        self.nodes_deleted = 2


class _Summary:
    def __init__(self):
        self.counters = _Counters()


class _Result:
    def __init__(self, record):
        self._record = record

    def single(self):
        return self._record

    def consume(self):
        return _Summary()

    def __iter__(self):
        if self._record is None:
            return iter(())
        return iter((self._record,))


class _Tx:
    def run(self, cypher, **kwargs):
        if "RETURN u AS user" in cypher:
            username = kwargs.get("username")
            return _Result(
                {
                    "user": {
                        "username": username,
                        "hashed_password": "placeholder-hash",
                        "email": None,
                        "full_name": None,
                        "disabled": False,
                    }
                }
            )
        if "ac.scope AS scope" in cypher:
            return _Result({"username": "alice", "scope": "test"})
        if "at.value AS access_token" in cypher:
            return _Result({"access_token": graph_state.stored_access_token})
        if "access_token" in kwargs:
            graph_state.stored_access_token = kwargs["access_token"]
            graph_state.stored_refresh_token = kwargs.get("refresh_token")
        return _Result(None)


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute_read(self, work, *args, **kwargs):
        return work(_Tx(), *args, **kwargs)

    def execute_write(self, work, *args, **kwargs):
        return work(_Tx(), *args, **kwargs)


class _Driver:
    def verify_connectivity(self):
        return None

    def session(self, *args, **kwargs):
        return _Session()


def _driver(*args, **kwargs):
    return _Driver()


neo4j.GraphDatabase.driver = _driver

# ifcopenshell is imported by the documents repository and is not on the token path.
_ifcopenshell = types.ModuleType("ifcopenshell")
_util = types.ModuleType("ifcopenshell.util")
_schema = types.ModuleType("ifcopenshell.util.schema")
_ifcopenshell.util = _util
_util.schema = _schema
sys.modules["ifcopenshell"] = _ifcopenshell
sys.modules["ifcopenshell.util"] = _util
sys.modules["ifcopenshell.util.schema"] = _schema

import main  # ruff: ignore[unused-import]
