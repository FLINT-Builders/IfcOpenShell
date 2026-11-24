# This file was generated with the assistance of an AI coding tool.
"""Sign-in must hand each caller the authorization code created for that caller.

GET /foundation/oauth2/code stores the new code on a module-global and returns
that global. FastAPI runs this synchronous route on a shared worker thread
pool, so two sign-ins in the same process can cross codes. The code that is
returned is what POST /foundation/oauth2/token exchanges, and the exchange
loads the user from the code value alone.

These tests fail while that global is what the route returns. They pass once
each request returns the code it just created for the authenticated user.

The Neo4j driver is a stand-in for the neo4j:5.7.0-community service in
docker-compose.yml. It runs the Cypher text this repository sends: every
``alias.property = $param`` predicate and every ``SET alias.property = $param``
assignment in that text, and no predicate the text does not contain.
"""

import asyncio
import linecache
import os
import re
import sys
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
SECRET_DIR = Path("/tmp/ocde-placeholder-secrets")

# Obvious placeholders. They are not credentials for any deployment.
CLIENT_SECRET_PLACEHOLDER = "placeholder-client-secret"
SIGNING_KEY_PLACEHOLDER = "placeholder-signing-key"
DB_PASSWORD_PLACEHOLDER = "placeholder-db-password"
USER_PASSWORD_PLACEHOLDER = "placeholder-password"

_EQUALITY = re.compile(r"(\w+)\.(\w+)\s*=\s*\$(\w+)")
_ASSIGNMENT = re.compile(r"SET\s+(\w+)\.(\w+)\s*=\s*\$(\w+)")

# Worker threads pause on the return line of code() while this is set, so both
# sign-ins have finished writing the shared global before either returns it.
_RETURN_BARRIER = {"barrier": None}


def _install_return_barrier_tracer():
    def tracer(frame, event, arg):
        if event != "line" or frame.f_code.co_name != "code":
            return tracer
        if not frame.f_code.co_filename.endswith(os.path.join("api", "foundation.py")):
            return tracer
        barrier = _RETURN_BARRIER["barrier"]
        if barrier is None:
            return tracer
        line = linecache.getline(frame.f_code.co_filename, frame.f_lineno).strip()
        if line.startswith("return "):
            barrier.wait(timeout=10)
        return tracer

    threading.settrace(tracer)


def _equality_filters(cypher, params):
    filters = []
    for alias, prop, param in _EQUALITY.findall(cypher):
        filters.append((alias, prop, params[param]))
    return filters


def _matches(props, filters):
    return all(props.get(prop) == value for _alias, prop, value in filters)


class _Counters:
    def __init__(self, nodes_created=0, nodes_deleted=0):
        self.nodes_created = nodes_created
        self.nodes_deleted = nodes_deleted


class _Summary:
    def __init__(self, nodes_created=0, nodes_deleted=0):
        self.counters = _Counters(nodes_created, nodes_deleted)


class _Result:
    def __init__(self, records=None, nodes_created=0, nodes_deleted=0):
        self._records = records or []
        self._summary = _Summary(nodes_created, nodes_deleted)

    def single(self):
        if not self._records:
            return None
        return self._records[0]

    def consume(self):
        return self._summary

    def __iter__(self):
        return iter(self._records)


class _Graph:
    def __init__(self):
        self.lock = threading.Lock()
        self.users = {}
        self.codes = {}
        self.code_of_user = {}


class _Tx:
    def __init__(self, graph: _Graph):
        self.graph = graph

    def run(self, cypher, **params):
        with self.graph.lock:
            if "RETURN u AS user" in cypher:
                return self._get_user(cypher, params)
            if "SET ac.code" in cypher:
                return self._create_code(cypher, params)
            if "DETACH DELETE ac1" in cypher:
                return self._consume_code(cypher, params)
            if "AuthorizationCode" in cypher and "RETURN" in cypher:
                return self._lookup_code(cypher, params)
            return _Result()

    def _get_user(self, cypher, params):
        user_filters = [item for item in _equality_filters(cypher, params) if item[0] == "u"]
        matched = [user for user in self.graph.users.values() if _matches(user, user_filters)]
        if not matched:
            return _Result([])
        return _Result([{"user": matched[0]}])

    def _create_code(self, cypher, params):
        user_filters = [item for item in _equality_filters(cypher, params) if item[0] == "u"]
        matched = [user for user in self.graph.users.values() if _matches(user, user_filters)]
        if len(matched) != 1:
            return _Result(nodes_created=0)
        username = matched[0]["username"]
        props = {}
        for _alias, prop, param in _ASSIGNMENT.findall(cypher):
            props[prop] = params[param]
        if username in self.graph.code_of_user:
            previous = self.graph.code_of_user[username]
            record = self.graph.codes.pop(previous)
            record.update(props)
            self.graph.codes[record["code"]] = record
            self.graph.code_of_user[username] = record["code"]
            return _Result(nodes_created=0)
        self.graph.codes[props["code"]] = {
            "code": props["code"],
            "scope": props.get("scope"),
            "username": username,
        }
        self.graph.code_of_user[username] = props["code"]
        return _Result(nodes_created=1)

    def _lookup_code(self, cypher, params):
        filters = _equality_filters(cypher, params)
        code_filters = [item for item in filters if item[0].startswith("ac")]
        user_filters = [item for item in filters if item[0] == "u"]
        for record in self.graph.codes.values():
            user = self.graph.users[record["username"]]
            code_props = {"code": record["code"], "scope": record["scope"]}
            if _matches(code_props, code_filters) and _matches(user, user_filters):
                return _Result([{"username": record["username"], "scope": record["scope"]}])
        return _Result([])

    def _consume_code(self, cypher, params):
        filters = _equality_filters(cypher, params)
        code_filters = [item for item in filters if item[0].startswith("ac")]
        user_filters = [item for item in filters if item[0] == "u"]
        for code, record in list(self.graph.codes.items()):
            user = self.graph.users[record["username"]]
            code_props = {"code": record["code"], "scope": record["scope"]}
            if _matches(code_props, code_filters) and _matches(user, user_filters):
                del self.graph.codes[code]
                self.graph.code_of_user.pop(record["username"], None)
                return _Result(nodes_created=2, nodes_deleted=1)
        return _Result(nodes_created=0, nodes_deleted=0)


class _Session:
    def __init__(self, graph: _Graph):
        self.graph = graph

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute_read(self, work, **kwargs):
        return work(_Tx(self.graph), **kwargs)

    def execute_write(self, work, **kwargs):
        return work(_Tx(self.graph), **kwargs)


class _Driver:
    def __init__(self):
        self.graph = _Graph()

    def verify_connectivity(self):
        return None

    def session(self, *args, **kwargs):
        return _Session(self.graph)


_DRIVER = _Driver()


def _install_import_stubs():
    import glob
    import types

    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    (SECRET_DIR / "kontroll_client_secret").write_text(CLIENT_SECRET_PLACEHOLDER + "\n")
    (SECRET_DIR / "security_secret_key").write_text(SIGNING_KEY_PLACEHOLDER + "\n")
    (SECRET_DIR / "neo4j_password").write_text(DB_PASSWORD_PLACEHOLDER + "\n")

    original_glob = glob.glob

    def glob_with_placeholders(pathname, *args, **kwargs):
        if pathname == "/run/secrets/*":
            return [str(path) for path in SECRET_DIR.iterdir() if path.is_file()]
        return original_glob(pathname, *args, **kwargs)

    glob.glob = glob_with_placeholders

    neo4j_mod = types.ModuleType("neo4j")

    class GraphDatabase:
        @staticmethod
        def driver(uri, auth=None):
            return _DRIVER

    neo4j_mod.GraphDatabase = GraphDatabase
    sys.modules["neo4j"] = neo4j_mod

    os.environ["NEO4J_URI"] = "bolt://localhost:7687"
    os.environ["NEO4J_USER"] = "neo4j"
    os.environ["NEO4J_INITIAL_PASSWORD"] = DB_PASSWORD_PLACEHOLDER
    os.environ["KONTROLL_BASE_URL"] = "http://test/"
    os.environ["KONTROLL_CLIENT_ID"] = "test-client"
    os.environ["KONTROLL_CLIENT_NAME"] = "Test Client"
    os.environ["SECURITY_AUTHORIZATION_CODE_EXPIRE_SECONDS"] = "600"
    os.environ["SECURITY_ACCESS_TOKEN_EXPIRE_SECONDS"] = "3600"
    os.environ["SECURITY_REFRESH_TOKEN_EXPIRE_SECONDS"] = "7200"
    os.environ["SECURITY_ALGORITHM"] = "HS256"

    (APP_DIR / "logs").mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(APP_DIR))


_install_import_stubs()
_previous_cwd = os.getcwd()
os.chdir(APP_DIR)
try:
    from api import foundation as foundation_api
    from fastapi import FastAPI
    from jose import jwt
    from repository.foundation import foundation_db
    from security.secure import crypt_context
finally:
    os.chdir(_previous_cwd)

# Same registration as main.py: the foundation router is mounted at the root.
app = FastAPI()
app.include_router(foundation_api.router, prefix="")

_install_return_barrier_tracer()


def _discard_handler_print(*args, **kwargs):
    # The handler prints passwords, client secrets, authorization codes, and tokens.
    return None


foundation_api.print = _discard_handler_print


def _seed_user(username):
    _DRIVER.graph.users[username] = {
        "username": username,
        "email": None,
        "full_name": username,
        "disabled": False,
        "hashed_password": crypt_context.hash(USER_PASSWORD_PLACEHOLDER),
    }


def _sign_in_query(username):
    return {
        "username": username,
        "password": USER_PASSWORD_PLACEHOLDER,
        "response_type": "code",
        "client_id": os.environ["KONTROLL_CLIENT_ID"],
        "client_name": os.environ["KONTROLL_CLIENT_NAME"],
        "state": "state-" + username,
        "redirect_uri": "http://localhost/callback",
        "scope": "user",
    }


async def _sign_in(client, username):
    response = await client.get("/foundation/oauth2/code", params=_sign_in_query(username))
    assert response.status_code == 200, response.text
    return response.json()


async def _exchange(client, code):
    secret = foundation_api.clients[os.environ["KONTROLL_CLIENT_ID"]]["secret"]
    response = await client.post(
        "/foundation/oauth2/token",
        data={"grant_type": "authorization_code", "code": code},
        auth=(os.environ["KONTROLL_CLIENT_ID"], secret),
    )
    assert response.status_code == 201, response.text
    payload = jwt.decode(
        response.json()["access_token"],
        SIGNING_KEY_PLACEHOLDER,
        algorithms=[os.environ["SECURITY_ALGORITHM"]],
    )
    return payload["username"]


def test_one_sign_in_returns_that_users_code_and_token():
    """A single sign-in is the control: the returned code belongs to that user."""
    username = "solo-user"
    _seed_user(username)
    issued = {}
    original = foundation_db.create_authorization_code

    def record_create(user, authorization_code, scope):
        issued[user] = authorization_code
        return original(user, authorization_code, scope)

    foundation_db.create_authorization_code = record_create
    try:
        import httpx

        async def run():
            async with httpx.AsyncClient(app=app, base_url="http://testserver") as client:
                code = await _sign_in(client, username)
                owner = await _exchange(client, code)
                return code, owner

        code, owner = asyncio.run(run())
    finally:
        foundation_db.create_authorization_code = original

    assert code == issued[username]
    assert owner == username


def test_concurrent_sign_ins_do_not_swap_authorization_codes():
    """Two overlapping sign-ins must not receive each other's authorization code.

    The return line of the live handler is held until both requests have passed
    the assignment of the shared global. On the unfixed handler both responses
    therefore carry whichever code was stored last, and exchanging either code
    yields that other account's access token.
    """
    users = ("user-a", "user-b")
    for username in users:
        _seed_user(username)

    issued = {}
    issued_lock = threading.Lock()
    original = foundation_db.create_authorization_code

    def record_create(user, authorization_code, scope):
        with issued_lock:
            issued[user] = authorization_code
        return original(user, authorization_code, scope)

    foundation_db.create_authorization_code = record_create
    barrier = threading.Barrier(len(users))
    _RETURN_BARRIER["barrier"] = barrier
    try:
        import httpx

        async def run():
            async with httpx.AsyncClient(app=app, base_url="http://testserver") as client:
                codes = await asyncio.gather(*[_sign_in(client, username) for username in users])
                returned_codes = dict(zip(users, codes))
                # A code is single-use. Exchange each distinct value once.
                owner_of_code = {}
                for code in returned_codes.values():
                    if code not in owner_of_code:
                        owner_of_code[code] = await _exchange(client, code)
                return returned_codes, owner_of_code

        returned, owner_of_code = asyncio.run(run())
    finally:
        _RETURN_BARRIER["barrier"] = None
        foundation_db.create_authorization_code = original

    for username in users:
        code = returned[username]
        assert code == issued[username] and owner_of_code[code] == username, (
            f"{username} was given {code!r} (created for the sign-in: {issued[username]!r}); "
            f"exchanging it yielded a token for {owner_of_code[code]!r}"
        )
