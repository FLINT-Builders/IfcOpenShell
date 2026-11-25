# This file was generated with the assistance of an AI coding tool.
"""Refresh-token requests must not put the token in the URL.

These tests exercise FoundationClient.login, get_access_token, and BcfClient.
They fail while the refresh token is sent in the query string, while the
refresh request omits the Basic client authentication used by the
authorization-code exchange, or while a token URL from the auth document is
contacted on a different host from the one the caller configured.
"""

import base64
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from bcf.v3 import bcfapi
from bcf.v3.bcfapi import BcfClient, FoundationClient

CLIENT_ID = "placeholder-client-id"
CLIENT_SECRET = "placeholder-client-secret"
AUTH_CODE = "placeholder-auth-code"
ISSUED_REFRESH = "placeholder-issued-refresh"
REFRESHED_ACCESS = "placeholder-refreshed-access"
FOREIGN_HOST = "bcf-foreign.test"


class _RecordingHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._finish(self._record(b""))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        self._finish(self._record(body))

    def _record(self, body: bytes) -> dict[str, object]:
        item = {
            "requestline": bytes(self.raw_requestline),
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "body": body,
        }
        self.server.received.append(item)  # type: ignore[attr-defined]
        return item

    def _finish(self, item: dict[str, object]) -> None:
        path = _normalized_path(str(item["path"]))
        if path == "/foundation/1.0/auth":
            host, port = self.server.server_address
            payload = {
                "oauth2_auth_url": f"http://{host}:{port}/oauth/authorize",
                "oauth2_token_url": self.server.oauth2_token_url,  # type: ignore[attr-defined]
                "supported_oauth2_flows": ["authorization_code_grant"],
            }
        elif path.endswith("/projects"):
            payload = [{"project_id": "placeholder-project"}]
        else:
            payload = _token_payload(item)
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: object) -> None:
        return


def _token_payload(item: dict[str, object]) -> dict[str, object]:
    grant, _where = _field(item, "grant_type")
    if grant == "refresh_token":
        return {
            "access_token": REFRESHED_ACCESS,
            "refresh_token": "placeholder-rotated-refresh",
            "expires_in": 1200,
            "refresh_token_expires_in": 2400,
        }
    return {
        "access_token": "placeholder-issued-access",
        "refresh_token": ISSUED_REFRESH,
        "expires_in": 3600,
        "refresh_token_expires_in": 7200,
    }


def _normalized_path(raw_path: str) -> str:
    path = urlsplit(raw_path).path
    while "//" in path:
        path = path.replace("//", "/")
    return path


def _field(item: dict[str, object], name: str) -> tuple[str | None, str | None]:
    query = parse_qs(urlsplit(str(item["path"])).query)
    body = parse_qs(bytes(item["body"]).decode() or "")  # type: ignore[arg-type]
    if name in body:
        return body[name][0], "body"
    if name in query:
        return query[name][0], "query"
    return None, None


def _serve(token_url: str) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
    server.received = []  # type: ignore[attr-defined]
    server.oauth2_token_url = token_url  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()


def _basic_header() -> str:
    raw = f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _deliver_browser_redirect(url: str) -> threading.Thread:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    state = query["state"][0]
    redirect = query["redirect_uri"][0]
    joiner = "&" if "?" in redirect else "?"
    callback = redirect + joiner + urlencode({"code": AUTH_CODE, "state": state})

    def deliver() -> None:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                import requests

                requests.get(callback, timeout=1)
                return
            except Exception:
                time.sleep(0.05)

    thread = threading.Thread(target=deliver, daemon=True)
    thread.start()
    return thread


def _token_posts(received: list[dict[str, object]]) -> list[dict[str, object]]:
    posts = []
    for item in received:
        if _normalized_path(str(item["path"])).rstrip("/").endswith("/foundation/oauth2/token"):
            posts.append(item)
    return posts


def _assert_refresh_post(item: dict[str, object], refresh_value: str) -> None:
    requestline = bytes(item["requestline"]).decode()
    assert refresh_value not in requestline
    assert CLIENT_SECRET not in requestline
    assert "refresh_token" not in urlsplit(str(item["path"])).query
    value, where = _field(item, "refresh_token")
    grant, grant_where = _field(item, "grant_type")
    assert (value, where) == (refresh_value, "body")
    assert (grant, grant_where) == ("refresh_token", "body")
    assert item["authorization"] == _basic_header()


@pytest.fixture
def map_foreign_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the test hostname at the loopback listener without changing the URL."""
    original = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host == FOREIGN_HOST:
            host = "127.0.0.1"
        return original(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


def test_expired_api_call_refreshes_without_putting_token_in_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    server, _thread = _serve("pending")
    try:
        host, port = server.server_address
        base = f"http://{host}:{port}/"
        token_url = f"{base}foundation/oauth2/token"
        server.oauth2_token_url = token_url  # type: ignore[attr-defined]
        monkeypatch.setattr(bcfapi.webbrowser, "open", _deliver_browser_redirect)

        client = FoundationClient(CLIENT_ID, CLIENT_SECRET, base, redirect_subdir="callback")
        client.login()
        assert client.token_endpoint == token_url
        assert client.refresh_token == ISSUED_REFRESH

        code_posts = [
            item for item in _token_posts(server.received) if _field(item, "grant_type")[0] == "authorization_code"
        ]
        assert len(code_posts) == 1
        assert AUTH_CODE not in bytes(code_posts[0]["requestline"]).decode()
        assert _field(code_posts[0], "code") == (AUTH_CODE, "body")
        assert code_posts[0]["authorization"] == _basic_header()

        client.access_token_expires_on = time.time() - 30
        bcf = BcfClient(client)
        bcf.baseurl = base
        try:
            bcf.get_projects()
        except Exception:
            pass

        refresh_posts = [
            item for item in _token_posts(server.received) if _field(item, "grant_type")[0] == "refresh_token"
        ]
        assert len(refresh_posts) == 1
        _assert_refresh_post(refresh_posts[0], ISSUED_REFRESH)
        assert refresh_posts[0]["authorization"] == code_posts[0]["authorization"]
        assert client.access_token == REFRESHED_ACCESS
        assert bcf.get_projects() == [{"project_id": "placeholder-project"}]
    finally:
        _stop(server)


def test_get_access_token_refreshes_from_the_stored_token_endpoint() -> None:
    server, _thread = _serve("pending")
    try:
        host, port = server.server_address
        base = f"http://{host}:{port}/"
        token_url = f"{base}foundation/oauth2/token"
        server.oauth2_token_url = token_url  # type: ignore[attr-defined]
        client = FoundationClient(CLIENT_ID, CLIENT_SECRET, base)
        client.token_endpoint = token_url
        client.access_token = "placeholder-old-access"
        client.access_token_expires_on = time.time() - 30
        client.refresh_token = ISSUED_REFRESH
        client.refresh_token_expires_on = time.time() + 3600

        try:
            returned = client.get_access_token()
        except Exception:
            returned = None

        refresh_posts = [
            item for item in _token_posts(server.received) if _field(item, "grant_type")[0] == "refresh_token"
        ]
        assert len(refresh_posts) == 1
        _assert_refresh_post(refresh_posts[0], ISSUED_REFRESH)
        assert returned == REFRESHED_ACCESS
        assert client.access_token == REFRESHED_ACCESS
        assert client.refresh_token == "placeholder-rotated-refresh"
    finally:
        _stop(server)


def test_auth_document_token_url_on_another_host_is_not_called(
    monkeypatch: pytest.MonkeyPatch, map_foreign_host: None
) -> None:
    foreign, _foreign_thread = _serve("pending")
    legit, _legit_thread = _serve("pending")
    try:
        foreign_port = foreign.server_address[1]
        legit_host, legit_port = legit.server_address
        foreign_token = f"http://{FOREIGN_HOST}:{foreign_port}/foundation/oauth2/token"
        legit.oauth2_token_url = foreign_token  # type: ignore[attr-defined]
        base = f"http://{legit_host}:{legit_port}/"
        monkeypatch.setattr(bcfapi.webbrowser, "open", _deliver_browser_redirect)

        client = FoundationClient(CLIENT_ID, CLIENT_SECRET, base, redirect_subdir="callback")
        try:
            client.login()
        except Exception:
            pass
        if client.refresh_token:
            client.access_token_expires_on = time.time() - 30
            try:
                client.get_access_token()
            except Exception:
                pass

        assert any("foundation/1.0/auth" in str(item["path"]) for item in legit.received)
        leaked = []
        for item in foreign.received:
            raw = bytes(item["requestline"]) + b"\n" + bytes(item["body"])  # type: ignore[arg-type]
            if AUTH_CODE.encode() in raw or ISSUED_REFRESH.encode() in raw or b"refresh_token=" in raw:
                leaked.append(raw)
        assert leaked == []
    finally:
        _stop(foreign)
        _stop(legit)
