# This file was generated with the assistance of an AI coding tool.
"""Sign-in must stop accepting unlimited password guesses.

These tests fail while GET /foundation/oauth2/code checks every guess and
returns either 401 or an authorization code. They pass when that operation
locks the account and the calling address after a short run of failures.

The only password check in this server is ``authenticate_user``, called from
``code`` in ``api/app/api/foundation.py``. The login pages submit to that same
route. Project and document routes do not check the password again; they
accept the bearer token this sign-in issues. ``repository/bcf.py``
``get_documents`` returns a constant and is not a document read, so project
listing is the read these tests perform.

A fresh account with the matching password must still receive a code. That
case passes before and after the lockout is added.
"""

import asyncio
import uuid

import httpx
from security.secure import crypt_context
from signin_graph import GraphNode, GraphRelationship

# More failures than this, from one account or one address, must be rejected.
MAX_FAILURES = 5
SEEDED_USERNAMES = ("admin", "kommun", "byggherre", "kontrollansvarig", "kontrollant")
CLIENT_ID = "placeholder-client-id"


def _hash(password):
    return crypt_context.hash(password, rounds=4)


def _add_user(graph, username, password, project_name=None):
    user = GraphNode(
        ["User"],
        {
            "username": username,
            "hashed_password": _hash(password),
            "disabled": False,
            "email": None,
            "full_name": username,
        },
    )
    graph.nodes.append(user)
    if project_name is not None:
        project = GraphNode(
            ["Project"],
            {"project_id": str(uuid.uuid4()), "name": project_name},
        )
        graph.nodes.append(project)
        graph.rels.append(
            GraphRelationship(
                user,
                "HAS_ACTIONS_ON",
                {"read": True, "update": False, "createTopic": False, "createDocument": False},
                project,
            )
        )
    return user


def _params(username, password):
    return {
        "username": username,
        "password": password,
        "response_type": "code",
        "client_id": CLIENT_ID,
        "client_name": "Placeholder Client",
        "state": "placeholder-state",
        "redirect_uri": "https://client.example/callback",
        "scope": "test",
    }


def _request(app, ip, method, path, **kwargs):
    transport = httpx.ASGITransport(app=app, client=(ip, 50000))

    async def send():
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def _sign_in(app, ip, username, password):
    return _request(app, ip, "GET", "/foundation/oauth2/code", params=_params(username, password))


def _is_authorization_code(response):
    if response.status_code != 200:
        return False
    try:
        value = response.json()
    except ValueError:
        return False
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def test_startup_loads_the_seeded_usernames(graph):
    loaded = [name for name in SEEDED_USERNAMES if graph.user(name) is not None]
    assert loaded == list(SEEDED_USERNAMES)


def test_matching_password_still_opens_the_user_projects(app, graph, placeholder_password, placeholder_client_secret):
    """A first successful sign-in still returns a code that can read projects."""
    username = "fresh-user"
    project_name = "Fresh project"
    _add_user(graph, username, placeholder_password, project_name=project_name)
    signed_in = _sign_in(app, "203.0.113.10", username, placeholder_password)
    assert _is_authorization_code(signed_in), signed_in.status_code
    token_response = _request(
        app,
        "203.0.113.10",
        "POST",
        "/foundation/oauth2/token",
        data={"grant_type": "authorization_code", "code": signed_in.json()},
        auth=(CLIENT_ID, placeholder_client_secret),
    )
    assert token_response.status_code == 201, token_response.status_code
    access_token = token_response.json()["access_token"]
    projects = _request(
        app,
        "203.0.113.10",
        "GET",
        "/bcf/3.0/projects",
        headers={"Authorization": "Bearer " + access_token},
    )
    assert projects.status_code == 200, projects.status_code
    assert project_name in {item["name"] for item in projects.json()}


def test_repeated_guesses_for_one_account_are_locked_out(app, graph, placeholder_password):
    username = "lock-account"
    _add_user(graph, username, placeholder_password, project_name="Locked project")
    ip = "203.0.113.20"
    for attempt in range(MAX_FAILURES):
        failed = _sign_in(app, ip, username, "guess-%s" % attempt)
        assert not _is_authorization_code(failed)
    blocked = _sign_in(app, ip, username, placeholder_password)
    assert blocked.status_code == 429
    assert not _is_authorization_code(blocked)


def test_repeated_guesses_from_one_address_are_locked_out_across_accounts(app, graph, placeholder_password):
    ip = "203.0.113.30"
    for attempt in range(MAX_FAILURES):
        username = "address-target-%s" % attempt
        _add_user(graph, username, placeholder_password)
        failed = _sign_in(app, ip, username, "guess-%s" % attempt)
        assert not _is_authorization_code(failed)
    victim = "address-victim"
    _add_user(graph, victim, placeholder_password, project_name="Victim project")
    blocked = _sign_in(app, ip, victim, placeholder_password)
    assert blocked.status_code == 429
    assert not _is_authorization_code(blocked)


def test_seeded_admin_guesses_are_locked_out(app, graph):
    assert graph.user("admin") is not None
    ip = "203.0.113.50"
    for attempt in range(MAX_FAILURES):
        failed = _sign_in(app, ip, "admin", "guess-%s" % attempt)
        assert not _is_authorization_code(failed)
    blocked = _sign_in(app, ip, "admin", "guess-after-limit")
    assert blocked.status_code == 429
    assert not _is_authorization_code(blocked)


def test_parallel_guesses_against_one_account_are_locked_out(app, graph, placeholder_password):
    username = "parallel-account"
    _add_user(graph, username, placeholder_password)
    ip = "203.0.113.40"

    async def burst():
        transport = httpx.ASGITransport(app=app, client=(ip, 50000))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            calls = [
                client.get("/foundation/oauth2/code", params=_params(username, "guess-%s" % attempt))
                for attempt in range(MAX_FAILURES + 7)
            ]
            return await asyncio.gather(*calls)

    responses = asyncio.run(burst())
    statuses = [response.status_code for response in responses]
    assert 429 in statuses, statuses
    assert all(not _is_authorization_code(response) for response in responses)


def test_other_seeded_usernames_share_the_same_lockout(app, graph):
    octet = 60
    for username in ("kommun", "byggherre", "kontrollansvarig", "kontrollant"):
        assert graph.user(username) is not None
        ip = "203.0.113.%s" % octet
        octet += 1
        for attempt in range(MAX_FAILURES):
            failed = _sign_in(app, ip, username, "guess-%s" % attempt)
            assert not _is_authorization_code(failed)
        blocked = _sign_in(app, ip, username, "guess-after-limit")
        assert blocked.status_code == 429, username
        assert not _is_authorization_code(blocked)
