# This file was generated with the assistance of an AI coding tool.
"""The BCF refresh grant must travel in the POST body.

``FoundationClient.get_access_token`` calls ``get_refresh_token``, which
passes the refresh token as a ``requests`` param. ``login`` and
``get_new_access_token`` already use the body and are not covered here.
"""

from __future__ import annotations

import http.server
import json
import threading
import time
import urllib.parse

import pytest

from bcf.v3.bcfapi import FoundationClient

REFRESH_TOKEN = "placeholder-refresh-token"
ACCESS_TOKEN = "placeholder-access-token"
ROTATED_REFRESH_TOKEN = "placeholder-rotated-refresh-token"


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
def token_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _TokenHandler)
    server.captured = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _client(server):
    client = FoundationClient("placeholder-client-id", "placeholder-client-secret")
    port = server.server_address[1]
    client.token_endpoint = f"http://127.0.0.1:{port}/oauth2/token"
    client.access_token = "placeholder-expired-access-token"
    client.access_token_expires_on = time.time() - 30
    client.refresh_token = REFRESH_TOKEN
    client.refresh_token_expires_on = time.time() + 3600
    return client


def _assert_refresh_in_body_only(server):
    assert server.captured, "token endpoint received no request"
    request = server.captured[-1]
    target = urllib.parse.urlsplit(request["path"])
    assert target.path == "/oauth2/token"
    assert target.query == ""
    assert REFRESH_TOKEN not in request["requestline"]
    assert request["content_type"].startswith("application/x-www-form-urlencoded")
    body = urllib.parse.parse_qs(request["body"].decode())
    assert body.get("grant_type") == ["refresh_token"]
    assert body.get("refresh_token") == [REFRESH_TOKEN]


def test_get_refresh_token_sends_refresh_token_in_body_not_url(token_server):
    client = _client(token_server)
    try:
        client.get_refresh_token()
    except Exception:
        pass
    _assert_refresh_in_body_only(token_server)


def test_get_access_token_sends_refresh_token_in_body_not_url(token_server):
    client = _client(token_server)
    try:
        client.get_access_token()
    except Exception:
        pass
    _assert_refresh_in_body_only(token_server)
