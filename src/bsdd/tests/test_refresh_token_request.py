# This file was generated with the assistance of an AI coding tool.
"""OAuth credentials must be sent in the POST body, not the request URL.

Client.get_access_token refreshes through get_new_access_token. Client.login
exchanges the authorization code. Both currently pass those values as query
parameters. The login request is forwarded to a local listener after the
client selects its token URL, so this file does not contact the identity
provider.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

import bsdd
from bsdd import Client

ISSUED_REFRESH = "placeholder-bsdd-refresh"
REFRESHED_ACCESS = "placeholder-bsdd-access"
AUTH_CODE = "placeholder-auth-code"
TOKEN_URL = (
    "https://buildingsmartservices.b2clogin.com/tfp/"
    "buildingsmartservices.onmicrosoft.com/b2c_1_signupsignin/oauth2/v2.0/token"
)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        item = {
            "requestline": bytes(self.raw_requestline),
            "path": self.path,
            "body": body,
        }
        self.server.received.append(item)  # type: ignore[attr-defined]
        grant, _where = _field(item, "grant_type")
        if grant == "refresh_token":
            payload = {
                "access_token": REFRESHED_ACCESS,
                "refresh_token": "placeholder-rotated-refresh",
                "expires_in": 1200,
                "refresh_token_expires_in": 2400,
            }
        else:
            payload = {
                "access_token": "placeholder-issued-access",
                "refresh_token": ISSUED_REFRESH,
                "expires_in": 3600,
                "refresh_token_expires_in": 7200,
            }
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: object) -> None:
        return


def _field(item: dict[str, object], name: str) -> tuple[str | None, str | None]:
    query = parse_qs(urlsplit(str(item["path"])).query)
    body = parse_qs(bytes(item["body"]).decode() or "")  # type: ignore[arg-type]
    if name in body:
        return body[name][0], "body"
    if name in query:
        return query[name][0], "query"
    return None, None


def _serve() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.received = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _stop(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()


def test_get_access_token_puts_refresh_token_in_the_body() -> None:
    server = _serve()
    try:
        host, port = server.server_address
        client = Client()
        client.token_endpoint = f"http://{host}:{port}/token"
        client.access_token = "placeholder-old-access"
        client.access_token_expires_on = time.time() - 30
        client.refresh_token = ISSUED_REFRESH
        client.refresh_token_expires_on = time.time() + 3600

        returned = client.get_access_token()

        assert len(server.received) == 1
        item = server.received[0]
        requestline = bytes(item["requestline"]).decode()
        assert ISSUED_REFRESH not in requestline
        assert "refresh_token" not in urlsplit(str(item["path"])).query
        assert _field(item, "grant_type") == ("refresh_token", "body")
        assert _field(item, "refresh_token") == (ISSUED_REFRESH, "body")
        assert returned == REFRESHED_ACCESS
        assert client.access_token == REFRESHED_ACCESS
    finally:
        _stop(server)


def test_login_puts_authorization_code_in_the_body(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _serve()
    observed: list[str] = []
    try:
        host, port = server.server_address
        local_token = f"http://{host}:{port}/token"
        original_post = bsdd.requests.post

        def post(url, data=None, json=None, **kwargs):  # type: ignore[no-untyped-def]
            observed.append(url)
            parsed = urlsplit(url)
            if parsed.hostname not in {"127.0.0.1", "localhost"}:
                if url != TOKEN_URL:
                    raise AssertionError("login selected an unexpected token URL")
                url = local_token
            return original_post(url, data=data, json=json, **kwargs)

        def open_browser(url: str) -> None:
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
                        bsdd.requests.get(callback, timeout=1)
                        return
                    except Exception:
                        time.sleep(0.05)

            threading.Thread(target=deliver, daemon=True).start()

        monkeypatch.setattr(bsdd.requests, "post", post)
        monkeypatch.setattr(bsdd.webbrowser, "open", open_browser)

        client = Client()
        client.login()

        assert observed == [TOKEN_URL]
        assert len(server.received) == 1
        item = server.received[0]
        requestline = bytes(item["requestline"]).decode()
        assert AUTH_CODE not in requestline
        assert "code" not in urlsplit(str(item["path"])).query
        assert _field(item, "grant_type") == ("authorization_code", "body")
        assert _field(item, "code") == (AUTH_CODE, "body")
        assert client.access_token == "placeholder-issued-access"
    finally:
        _stop(server)
