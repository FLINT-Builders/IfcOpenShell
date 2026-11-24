# This file was generated with the assistance of an AI coding tool.

import os
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
os.chdir(APP_DIR)
sys.path.insert(0, str(APP_DIR))
(APP_DIR / "logs").mkdir(exist_ok=True)
(APP_DIR / "data" / "documents").mkdir(parents=True, exist_ok=True)

os.environ.setdefault("NEO4J_URI", "bolt://127.0.0.1:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
if "NEO4J_INITIAL_PASSWORD" not in os.environ:
    raise RuntimeError(
        "Set NEO4J_INITIAL_PASSWORD to the password of the local Neo4j 5.7 server before running these tests."
    )
os.environ.setdefault("SECURITY_ALGORITHM", "HS256")
os.environ.setdefault("SESSION_MAX_FILE_SIZE_BYTES", "1048576")
os.environ.setdefault("SESSION_URL_VALIDITY_SECONDS", "60")
os.environ.setdefault("SECURITY_ACCESS_TOKEN_EXPIRE_SECONDS", "3600")
os.environ.setdefault("SECURITY_REFRESH_TOKEN_EXPIRE_SECONDS", "7200")
os.environ.setdefault("KONTROLL_BASE_URL", "http://127.0.0.1:8000/")
os.environ.setdefault("KONTROLL_CLIENT_ID", "placeholder-client")
os.environ.setdefault("KONTROLL_CLIENT_NAME", "placeholder-client")

import security.secrets as secrets_mod

# Obvious placeholders. The running server reads these the same way it reads /run/secrets.
_PLACEHOLDER_SECRETS = {
    "security_secret_key": "placeholder-secret-key",
    "kontroll_client_secret": "placeholder-client-secret",
}


def _placeholder_secrets():
    return dict(_PLACEHOLDER_SECRETS)


secrets_mod.get_secrets = _placeholder_secrets

from database.neo4j import driver
from fastapi.testclient import TestClient
from main import app
from security.secure import create_access_token, get_password_hash

USER_A = "placeholder-user-a"
USER_B = "placeholder-user-b"
PROJECT_A = "placeholder-project-a"
PROJECT_B = "placeholder-project-b"
SESSION_A = "placeholder-session-a"
SESSION_B = "placeholder-session-b"
PLACEHOLDER_USER_PASSWORD = "placeholder-password"


def _token_for(username):
    return create_access_token({"username": username, "scopes": ["test"]})


@pytest.fixture(scope="session")
def neo4j_driver():
    return driver


@pytest.fixture(scope="session", autouse=True)
def seeded_users(neo4j_driver):
    password_hash = get_password_hash(PLACEHOLDER_USER_PASSWORD)
    with neo4j_driver.session() as session:
        session.run(
            """
            CREATE (a:User {username:$user_a, email:'a@example.test', full_name:'Placeholder A',
                            hashed_password:$password_hash, disabled:false})
            CREATE (b:User {username:$user_b, email:'b@example.test', full_name:'Placeholder B',
                            hashed_password:$password_hash, disabled:false})
            CREATE (pa:Project {project_id:$project_a, name:'Placeholder A'})
            CREATE (pb:Project {project_id:$project_b, name:'Placeholder B'})
            CREATE (a)-[:HAS_ACTIONS_ON {createDocument:true}]->(pa)
            CREATE (b)-[:HAS_ACTIONS_ON {createDocument:true}]->(pb)
            CREATE (a)-[:HAS]->(:Session:Select {selection_session:$session_a})
            CREATE (b)-[:HAS]->(:Session:Select {selection_session:$session_b})
            """,
            user_a=USER_A,
            user_b=USER_B,
            project_a=PROJECT_A,
            project_b=PROJECT_B,
            session_a=SESSION_A,
            session_b=SESSION_B,
            password_hash=password_hash,
        )
    yield
    with neo4j_driver.session() as session:
        session.run(
            """
            MATCH (u:User) WHERE u.username IN [$user_a, $user_b]
            OPTIONAL MATCH (u)-[:HAS]->(s:Session)
            DETACH DELETE u, s
            """,
            user_a=USER_A,
            user_b=USER_B,
        )
        session.run(
            "MATCH (p:Project) WHERE p.project_id IN [$project_a, $project_b] DETACH DELETE p",
            project_a=PROJECT_A,
            project_b=PROJECT_B,
        )


@pytest.fixture(scope="session")
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="session")
def token_a():
    return _token_for(USER_A)


@pytest.fixture(scope="session")
def token_b():
    return _token_for(USER_B)
