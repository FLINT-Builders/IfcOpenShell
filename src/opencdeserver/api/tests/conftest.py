# This file was generated with the assistance of an AI coding tool.
"""Load the OpenCDE app against the sign-in graph stand-in.

Importing the app connects to Neo4j and reads Docker secrets at import time.
Those calls are pointed at local placeholders before the app modules load.
The placeholders are not deployment credentials.
"""

import glob
import os
import sys
import types
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
APP_DIR = TESTS_DIR.parent / "app"
SECRET_DIR = Path("/tmp/opencde-signin-test-secrets")

# Obvious placeholders. They are not the values shipped in the repository.
PLACEHOLDER_PASSWORD = "placeholder-password"
PLACEHOLDER_CLIENT_SECRET = "placeholder-client-secret"
PLACEHOLDER_SIGNING_KEY = "placeholder-signing-key"

os.environ["NEO4J_URI"] = "neo4j://placeholder:7687"
os.environ["NEO4J_USER"] = "neo4j"
os.environ["NEO4J_INITIAL_PASSWORD"] = "placeholder-neo4j-password"
os.environ["KONTROLL_BASE_URL"] = "https://opencde.example/"
os.environ["KONTROLL_CLIENT_ID"] = "placeholder-client-id"
os.environ["KONTROLL_CLIENT_NAME"] = "Placeholder Client"
os.environ["SECURITY_AUTHORIZATION_CODE_EXPIRE_SECONDS"] = "600"
os.environ["SECURITY_ACCESS_TOKEN_EXPIRE_SECONDS"] = "3600"
os.environ["SECURITY_REFRESH_TOKEN_EXPIRE_SECONDS"] = "7200"
os.environ["SECURITY_ALGORITHM"] = "HS256"

SECRET_DIR.mkdir(parents=True, exist_ok=True)
(SECRET_DIR / "kontroll_client_secret").write_text(PLACEHOLDER_CLIENT_SECRET + "\n")
(SECRET_DIR / "security_secret_key").write_text(PLACEHOLDER_SIGNING_KEY + "\n")
(SECRET_DIR / "neo4j_password").write_text("placeholder-neo4j-password\n")

_real_glob = glob.glob


def _secret_glob(pathname, *args, **kwargs):
    if pathname == "/run/secrets/*":
        return [str(path) for path in sorted(SECRET_DIR.iterdir())]
    return _real_glob(pathname, *args, **kwargs)


glob.glob = _secret_glob

sys.path.insert(0, str(TESTS_DIR))
from signin_graph import DRIVER, GRAPH

neo4j_module = types.ModuleType("neo4j")


class GraphDatabase:
    @staticmethod
    def driver(uri, auth=None, **kwargs):
        return DRIVER


neo4j_module.GraphDatabase = GraphDatabase
sys.modules["neo4j"] = neo4j_module

ifcopenshell_module = types.ModuleType("ifcopenshell")
ifcopenshell_util = types.ModuleType("ifcopenshell.util")
ifcopenshell_schema = types.ModuleType("ifcopenshell.util.schema")
sys.modules["ifcopenshell"] = ifcopenshell_module
sys.modules["ifcopenshell.util"] = ifcopenshell_util
sys.modules["ifcopenshell.util.schema"] = ifcopenshell_schema

py2neo_module = types.ModuleType("py2neo")
py2neo_data = types.ModuleType("py2neo.data")
py2neo_data.Node = type("Node", (), {})
py2neo_data.Relationship = type("Relationship", (), {})
py2neo_module.Graph = type("Graph", (), {})
py2neo_module.data = py2neo_data
sys.modules["py2neo"] = py2neo_module
sys.modules["py2neo.data"] = py2neo_data

os.chdir(APP_DIR)
sys.path.insert(0, str(APP_DIR))
(APP_DIR / "logs").mkdir(exist_ok=True)

import pytest
from main import app as fastapi_app


@pytest.fixture(scope="session")
def graph():
    return GRAPH


@pytest.fixture(scope="session")
def app():
    return fastapi_app


@pytest.fixture(scope="session")
def placeholder_password():
    return PLACEHOLDER_PASSWORD


@pytest.fixture(scope="session")
def placeholder_client_secret():
    return PLACEHOLDER_CLIENT_SECRET
