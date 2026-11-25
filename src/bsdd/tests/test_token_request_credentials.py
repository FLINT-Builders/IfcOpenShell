# This file was generated with the assistance of an AI coding tool.
"""Authorization-code and refresh-token grants must travel in the POST body.

``Client.login`` and ``Client.get_new_access_token`` currently pass those
fields as ``requests`` params. These tests speak HTTP with the real client
and fail until the token request target contains none of them.
"""

from __future__ import annotations

import http.server
import json
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

import pytest
import requests.adapters

from bsdd import Client

AUTHORIZATION_CODE = "placeholder-authorization-code"
REFRESH_TOKEN = "placeholder-refresh-token"
ACCESS_TOKEN = "placeholder-access-token"
ROTATED_REFRESH_TOKEN = "placeholder-rotated-refresh-token"
TOKEN_HOST = "buildingsmartservices.b2clogin.com"
TOKEN_PATH = "/tfp/buildingsmartservices.onmicrosoft.com/b2c_1_signupsignin/oauth2/v2.0/token"


class _TokenHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        self.server.captured.append(
            {
                "requestline": self.requestline,
                "path": self.path,
                "body": body,
                "content_type": self.headers.get("Content-Type", ""),
            }
        )
        payload = json.dumps(
            {
                "access_token": ACCESS_TOKEN,
                "refresh_token": ROTATED_REFRESH_TOKEN,
                "expires_in": 3600,
                "refresh_token_expires_in": 7200,
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        return


@pytest.fixture
def token_exchange(monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _TokenHandler)
    server.captured = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    opened = []
    real_send = requests.adapters.HTTPAdapter.send

    def send(adapter, request, **kwargs):
        parts = urllib.parse.urlsplit(request.url)
        if parts.hostname == TOKEN_HOST:
            request.url = urllib.parse.urlunsplit(("http", f"127.0.0.1:{port}", parts.path or "/", parts.query, ""))
        elif parts.hostname not in {"127.0.0.1", "localhost"}:
            raise AssertionError(f"refusing unexpected host {parts.hostname}")
        return real_send(adapter, request, **kwargs)

    def open_browser(url):
        opened.append(url)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        redirect_uri = query["redirect_uri"][0]
        state = query["state"][0]
        callback = redirect_uri + "?" + urllib.parse.urlencode({"code": AUTHORIZATION_CODE, "state": state})

        def deliver():
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(callback, timeout=1) as response:
                        response.read()
                    return
                except Exception:
                    time.sleep(0.02)

        threading.Thread(target=deliver, daemon=True).start()

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    monkeypatch.setattr(webbrowser, "open", open_browser)
    try:
        yield {"captured": server.captured, "opened": opened}
    finally:
        server.shutdown()
        server.server_close()


def _assert_form_body_only(captured, expected):
    assert captured, "token endpoint received no request"
    request = captured[-1]
    target = urllib.parse.urlsplit(request["path"])
    assert target.path == TOKEN_PATH
    assert target.query == ""
    for value in expected.values():
        assert value not in request["requestline"]
    assert request["content_type"].startswith("application/x-www-form-urlencoded")
    body = urllib.parse.parse_qs(request["body"].decode())
    for key, value in expected.items():
        assert body.get(key) == [value]


def _code_grant(client, opened):
    auth = urllib.parse.parse_qs(urllib.parse.urlsplit(opened[-1]).query)
    return {
        "grant_type": "authorization_code",
        "code": AUTHORIZATION_CODE,
        "redirect_uri": auth["redirect_uri"][0],
        "client_id": client.client_id,
    }


def test_login_sends_authorization_code_in_body_not_url(token_exchange):
    client = Client()
    client.login()
    _assert_form_body_only(token_exchange["captured"], _code_grant(client, token_exchange["opened"]))


def test_get_access_token_sends_authorization_code_in_body_not_url(token_exchange):
    client = Client()
    assert client.get_access_token() == ACCESS_TOKEN
    _assert_form_body_only(token_exchange["captured"], _code_grant(client, token_exchange["opened"]))


def test_search_list_sends_authorization_code_in_body_not_url(token_exchange):
    client = Client()

    def dictionary_get(*args, **kwargs):
        class Response:
            def json(self):
                return {}

        assert kwargs["headers"]["Authorization"] == "Bearer " + ACCESS_TOKEN
        return Response()

    client.session.get = dictionary_get
    client.SearchList("placeholder-dictionary")
    _assert_form_body_only(token_exchange["captured"], _code_grant(client, token_exchange["opened"]))


def _refresh_grant(client):
    return {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": client.client_id,
    }


def _arm_refresh(client):
    client.access_token = ACCESS_TOKEN
    client.access_token_expires_on = time.time() - 30
    client.refresh_token = REFRESH_TOKEN
    client.refresh_token_expires_on = time.time() + 3600


def test_get_new_access_token_sends_refresh_token_in_body_not_url(token_exchange):
    client = Client()
    _arm_refresh(client)
    client.get_new_access_token()
    _assert_form_body_only(token_exchange["captured"], _refresh_grant(client))


def test_expired_access_token_sends_refresh_token_in_body_not_url(token_exchange):
    client = Client()
    _arm_refresh(client)
    assert client.get_access_token() == ACCESS_TOKEN
    _assert_form_body_only(token_exchange["captured"], _refresh_grant(client))
