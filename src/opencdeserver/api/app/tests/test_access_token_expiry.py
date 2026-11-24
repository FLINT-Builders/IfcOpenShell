# This file was generated with the assistance of an AI coding tool.

"""Issued OpenCDE tokens must stop working after the configured lifetime.

Tokens are issued by ``FoundationDB.use_authorization_code`` and
``FoundationDB.use_refresh_token``, which both call ``create_access_token``.
They are accepted by ``get_current_user`` (foundation, BCF, and documents
routes) and decoded again inside ``use_refresh_token``.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import time

import pytest
from fastapi import HTTPException
from fastapi.security import SecurityScopes
from fastapi.testclient import TestClient
from jose import JWTError
from main import app
from repository.foundation import foundation_db
from security.secure import get_current_user

_AUTH_CODE = "placeholder-authorization-code"
_LIFETIME_SECONDS = 1
_REFRESH_LIFETIME_SECONDS = 3600
_PAST_LIFETIME_SECONDS = 5


def _issue(access_seconds, refresh_seconds):
    os.environ["SECURITY_ACCESS_TOKEN_EXPIRE_SECONDS"] = str(access_seconds)
    os.environ["SECURITY_REFRESH_TOKEN_EXPIRE_SECONDS"] = str(refresh_seconds)
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        return foundation_db.use_authorization_code(_AUTH_CODE)


def _current_user(token):
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        return asyncio.run(get_current_user(SecurityScopes(["test"]), token))


def _reject_expired_bearer(token):
    try:
        user = _current_user(token)
    except HTTPException as exc:
        assert exc.status_code == 401
        return
    pytest.fail(f"expired token was accepted for {user.username}")


def _request(path, token):
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        client = TestClient(app, raise_server_exceptions=False)
        return client.get(path, headers={"Authorization": "Bearer " + token})


def test_unexpired_access_token_is_accepted_for_its_user():
    issued = _issue(_REFRESH_LIFETIME_SECONDS, _REFRESH_LIFETIME_SECONDS)
    user = _current_user(issued.access_token)
    assert user.username == "alice"

    current_user = _request("/foundation/1.0/current-user", issued.access_token)
    assert current_user.status_code == 200
    assert current_user.json()["username"] == "alice"

    projects = _request("/bcf/3.0/projects", issued.access_token)
    assert projects.status_code == 200

    document = _request("/documents/1.0/document/missing-document/version/1", issued.access_token)
    assert document.status_code != 401


def _route_statuses(token):
    return {
        "current-user": _request("/foundation/1.0/current-user", token).status_code,
        "projects": _request("/bcf/3.0/projects", token).status_code,
        "document": _request("/documents/1.0/document/missing-document/version/1", token).status_code,
    }


def test_access_token_is_rejected_after_configured_lifetime():
    issued = _issue(_LIFETIME_SECONDS, _LIFETIME_SECONDS)
    time.sleep(_PAST_LIFETIME_SECONDS)
    assert _route_statuses(issued.access_token) == {"current-user": 401, "projects": 401, "document": 401}
    _reject_expired_bearer(issued.access_token)


def test_refresh_token_is_rejected_as_bearer_after_configured_lifetime():
    issued = _issue(_LIFETIME_SECONDS, _LIFETIME_SECONDS)
    time.sleep(_PAST_LIFETIME_SECONDS)
    assert _route_statuses(issued.refresh_token) == {"current-user": 401, "projects": 401, "document": 401}
    _reject_expired_bearer(issued.refresh_token)


def test_unexpired_refresh_token_mints_an_access_token_for_its_user():
    issued = _issue(_REFRESH_LIFETIME_SECONDS, _REFRESH_LIFETIME_SECONDS)
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        refreshed = foundation_db.use_refresh_token(issued.refresh_token)
    user = _current_user(refreshed.access_token)
    assert user.username == "alice"


def test_expired_refresh_token_cannot_mint_new_tokens():
    issued = _issue(_LIFETIME_SECONDS, _LIFETIME_SECONDS)
    time.sleep(_PAST_LIFETIME_SECONDS)
    _assert_refresh_rejected(issued.refresh_token)


def test_refresh_grant_rejects_expired_stored_access_token():
    issued = _issue(_LIFETIME_SECONDS, _REFRESH_LIFETIME_SECONDS)
    time.sleep(_PAST_LIFETIME_SECONDS)
    _assert_refresh_rejected(issued.refresh_token)


def _assert_refresh_rejected(refresh_token):
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        try:
            foundation_db.use_refresh_token(refresh_token)
        except JWTError:
            return
        except HTTPException as exc:
            assert exc.status_code == 401
            assert exc.detail != "Access token not found."
            return
    pytest.fail("expired token was accepted by the refresh grant")
