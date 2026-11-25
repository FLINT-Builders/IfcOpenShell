# This file was generated with the assistance of an AI coding tool.
"""Security tests for the BCF OAuth token URL.

FoundationClient.login reads oauth2_token_url from the server discovery
document and posts the authorization code and client credentials there.
These tests describe the required behavior: that request may go only to an
https URL on the host of the configured BCF base URL, and it must not follow
a redirect. They fail while the client still performs the unsafe request.
"""

import base64
import json
import socket
import ssl
import subprocess
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bcf.v3 import bcfapi

CLIENT_ID = "client-id-placeholder"
CLIENT_SECRET = "client-secret-placeholder"
AUTH_CODE = "authorization-code-placeholder"
ISSUED_ACCESS_TOKEN = "issued-access-token"
ISSUED_REFRESH_TOKEN = "issued-refresh-token"
COLLECTOR_ACCESS_TOKEN = "collector-access-token"
CALLBACK_PORT = 8080

LOGIN_LOCK = threading.Lock()


def _decoded_basic(header: str | None) -> str | None:
    if header is None or not header.startswith("Basic "):
        return None
    try:
        return base64.b64decode(header.removeprefix("Basic ")).decode("utf-8")
    except Exception:
        return None


def _leak_summary(posts: list[dict[str, str | None]]) -> list[dict[str, object]]:
    """Describe captured token posts without repeating credential material."""

    summary = []
    for item in posts:
        raw_path = item["path"] or ""
        path, _, query = raw_path.partition("?")
        body = item["body"] or ""
        summary.append(
            {
                "path": path,
                "sent_client_credentials": _decoded_basic(item["authorization"]) == f"{CLIENT_ID}:{CLIENT_SECRET}",
                "sent_authorization_code": AUTH_CODE in body,
                "sent_refresh_token": ISSUED_REFRESH_TOKEN in body or ISSUED_REFRESH_TOKEN in query,
            }
        )
    return summary


def _deliver_authorization_code(url: str, new: int = 0, autoraise: bool = True) -> bool:
    """Stand in for the browser after the user finishes login.

    login() has already bound its loopback receiver. Delivering the code there
    is the same request a browser would make to the redirect_uri.
    """

    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    state = query["state"][0]
    callback = "http://127.0.0.1:%d/callback?%s" % (
        CALLBACK_PORT,
        urllib.parse.urlencode({"code": AUTH_CODE, "state": state}),
    )

    def deliver() -> None:
        try:
            with urllib.request.urlopen(callback, timeout=10) as response:
                response.read()
        except Exception:
            return

    threading.Thread(target=deliver, daemon=True).start()
    return True


@pytest.fixture(autouse=True)
def _local_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bcfapi.webbrowser, "open", _deliver_authorization_code)
    monkeypatch.setattr(bcfapi.http.server.HTTPServer, "allow_reuse_address", True, raising=False)


@pytest.fixture(scope="session")
def localhost_certificate(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, str]:
    directory = tmp_path_factory.mktemp("bcf-token-ca")
    cert = directory / "cert.pem"
    key = directory / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1,DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )
    return str(cert), str(key)


def _token_document(access_token: str) -> dict[str, object]:
    return {
        "access_token": access_token,
        "refresh_token": ISSUED_REFRESH_TOKEN,
        "expires_in": 3600,
    }


class _QuietHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_body(self) -> str:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length).decode("utf-8")

    def _send(self, status: int, body: bytes, headers: dict[str, str]) -> None:
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path.rstrip("/") == "/foundation/1.0/auth":
            payload = {
                "oauth2_auth_url": self.server.auth_url,  # type: ignore[attr-defined]
                "oauth2_token_url": self.server.token_url,  # type: ignore[attr-defined]
                "supported_oauth2_flows": ["authorization_code_grant"],
            }
            if self.server.omit_token_url:  # type: ignore[attr-defined]
                del payload["oauth2_token_url"]
            body = json.dumps(payload).encode("utf-8")
            self._send(200, body, {"Content-Type": "application/json"})
            return
        self._send(404, b"not found", {"Content-Type": "text/plain"})

    def do_POST(self) -> None:
        body = self._read_body()
        self.server.posts.append(  # type: ignore[attr-defined]
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        redirect_to = self.server.redirect_to  # type: ignore[attr-defined]
        if redirect_to:
            self._send(307, b"", {"Location": redirect_to, "Content-Type": "text/plain"})
            return
        document = json.dumps(self.server.token_document).encode("utf-8")  # type: ignore[attr-defined]
        self._send(200, document, {"Content-Type": "application/json"})


class RecordingServer:
    """HTTP server whose discovery document and token endpoint this process controls."""

    def __init__(self, tls: tuple[str, str] | None = None) -> None:
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
        self._httpd.posts = []  # type: ignore[attr-defined]
        self._httpd.auth_url = ""  # type: ignore[attr-defined]
        self._httpd.token_url = ""  # type: ignore[attr-defined]
        self._httpd.redirect_to = None  # type: ignore[attr-defined]
        self._httpd.omit_token_url = False  # type: ignore[attr-defined]
        self._httpd.token_document = _token_document(ISSUED_ACCESS_TOKEN)  # type: ignore[attr-defined]
        if tls is not None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=tls[0], keyfile=tls[1])
            self._httpd.ssl_context = context  # type: ignore[attr-defined]
            plain_get_request = self._httpd.get_request

            def get_request() -> tuple[socket.socket, tuple[str, int]]:
                connection, address = plain_get_request()
                try:
                    wrapped = context.wrap_socket(connection, server_side=True)
                except ssl.SSLError:
                    connection.close()
                    raise
                return wrapped, address

            self._httpd.get_request = get_request  # type: ignore[method-assign]
        self.scheme = "https" if tls else "http"
        host, port = self._httpd.server_address[:2]
        self.base_url = f"{self.scheme}://{host}:{port}/"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def posts(self) -> list[dict[str, str | None]]:
        return self._httpd.posts  # type: ignore[attr-defined]

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def set_discovery(self, token_url: str, *, omit_token_url: bool = False) -> None:
        self._httpd.auth_url = self.base_url + "foundation/oauth2/auth"  # type: ignore[attr-defined]
        self._httpd.token_url = token_url  # type: ignore[attr-defined]
        self._httpd.omit_token_url = omit_token_url  # type: ignore[attr-defined]

    def set_redirect(self, location: str | None) -> None:
        self._httpd.redirect_to = location  # type: ignore[attr-defined]

    def set_token_document(self, document: dict[str, object]) -> None:
        self._httpd.token_document = document  # type: ignore[attr-defined]


class _DemuxState:
    def __init__(self) -> None:
        self.stop = False
        self.cleartext_posts: list[dict[str, str | None]] = []
        self.token_url = ""
        self.auth_url = ""


def _read_http_request(connection: socket.socket) -> tuple[str, str, dict[str, str], str]:
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = connection.recv(4096)
        if not chunk:
            break
        buffer += chunk
    head, _, rest = buffer.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1").split("\r\n")
    method, target, _protocol = lines[0].split(" ", 2)
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    while len(rest) < length:
        chunk = connection.recv(4096)
        if not chunk:
            break
        rest += chunk
    return method, target, headers, rest[:length].decode("utf-8")


def _write_http_response(
    connection: socket.socket, status: int, reason: str, body: bytes, headers: dict[str, str]
) -> None:
    header_lines = [f"HTTP/1.1 {status} {reason}", f"Content-Length: {len(body)}", "Connection: close"]
    header_lines.extend(f"{name}: {value}" for name, value in headers.items())
    connection.sendall(("\r\n".join(header_lines) + "\r\n\r\n").encode("ascii") + body)


def _handle_demux_connection(connection: socket.socket, context: ssl.SSLContext, state: _DemuxState) -> None:
    try:
        connection.settimeout(5)
        peeked = connection.recv(1, socket.MSG_PEEK)
        tls = peeked[:1] == b"\x16"
        stream: socket.socket = context.wrap_socket(connection, server_side=True) if tls else connection
        method, target, headers, body = _read_http_request(stream)
        path = target.split("?", 1)[0]
        if method == "GET" and path.rstrip("/") == "/foundation/1.0/auth":
            payload = json.dumps(
                {
                    "oauth2_auth_url": state.auth_url,
                    "oauth2_token_url": state.token_url,
                    "supported_oauth2_flows": ["authorization_code_grant"],
                }
            ).encode("utf-8")
            _write_http_response(stream, 200, "OK", payload, {"Content-Type": "application/json"})
            return
        if method == "POST" and not tls:
            state.cleartext_posts.append(
                {
                    "path": target,
                    "authorization": headers.get("authorization"),
                    "body": body,
                }
            )
        _write_http_response(stream, 404, "Not Found", b"not found", {"Content-Type": "text/plain"})
    except Exception:
        return
    finally:
        try:
            connection.close()
        except Exception:
            return


class DemuxServer:
    """One port that speaks HTTPS for discovery and records a cleartext token POST."""

    def __init__(self, certificate: tuple[str, str]) -> None:
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.load_cert_chain(certfile=certificate[0], keyfile=certificate[1])
        self._state = _DemuxState()
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen()
        self._listener.settimeout(0.2)
        host, port = self._listener.getsockname()
        self.base_url = f"https://{host}:{port}/"
        self._state.auth_url = self.base_url + "foundation/oauth2/auth"
        self._state.token_url = f"http://{host}:{port}/token"
        self._thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def cleartext_posts(self) -> list[dict[str, str | None]]:
        return self._state.cleartext_posts

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._state.stop = True
        self._thread.join(timeout=5)
        self._listener.close()

    def _serve(self) -> None:
        while not self._state.stop:
            try:
                connection, _address = self._listener.accept()
            except TimeoutError:
                continue
            threading.Thread(
                target=_handle_demux_connection,
                args=(connection, self._context, self._state),
                daemon=True,
            ).start()


def _login(base_url: str) -> bcfapi.FoundationClient:
    client = bcfapi.FoundationClient(CLIENT_ID, CLIENT_SECRET, base_url, "callback")
    with LOGIN_LOCK:
        client.login()
    return client


def _call_token_operations(client: bcfapi.FoundationClient) -> None:
    """Exercise every method that posts to the stored token endpoint."""

    for operation in (
        lambda: client.get_new_access_token(),
        lambda: client.get_refresh_token(),
        lambda: _refresh_via_get_access_token(client),
    ):
        try:
            operation()
        except Exception:
            continue


def _refresh_via_get_access_token(client: bcfapi.FoundationClient) -> None:
    client.access_token_expires_on = 0
    client.refresh_token_expires_on = float("inf")
    if not client.refresh_token:
        client.refresh_token = ISSUED_REFRESH_TOKEN
    client.get_access_token()


def test_login_does_not_post_credentials_to_another_host() -> None:
    """A discovery document must not make login post the code or client secret elsewhere."""

    bcf = RecordingServer()
    collector = RecordingServer()
    bcf.start()
    collector.start()
    try:
        bcf.set_discovery(collector.base_url + "token")
        collector.set_token_document(_token_document(COLLECTOR_ACCESS_TOKEN))
        client = bcfapi.FoundationClient(CLIENT_ID, CLIENT_SECRET, bcf.base_url, "callback")
        with LOGIN_LOCK:
            try:
                client.login()
            except Exception:
                pass
            _call_token_operations(client)
        assert _leak_summary(collector.posts) == []
        assert client.access_token != COLLECTOR_ACCESS_TOKEN
    finally:
        collector.close()
        bcf.close()


def test_login_does_not_post_to_token_url_with_base_host_in_userinfo() -> None:
    """The host check has to use the parsed host, not a substring of the URL."""

    bcf = RecordingServer()
    collector = RecordingServer()
    bcf.start()
    collector.start()
    try:
        parsed = urllib.parse.urlparse(bcf.base_url)
        collector_parsed = urllib.parse.urlparse(collector.base_url)
        token_url = "http://%s:%s@%s:%s/token" % (
            parsed.hostname,
            parsed.port,
            collector_parsed.hostname,
            collector_parsed.port,
        )
        bcf.set_discovery(token_url)
        client = bcfapi.FoundationClient(CLIENT_ID, CLIENT_SECRET, bcf.base_url, "callback")
        with LOGIN_LOCK:
            try:
                client.login()
            except Exception:
                pass
            _call_token_operations(client)
        assert _leak_summary(collector.posts) == []
    finally:
        collector.close()
        bcf.close()


def test_login_does_not_post_http_token_url_on_the_configured_host(
    localhost_certificate: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An http token URL is refused even when the host and port match the base URL."""

    monkeypatch.setenv("REQUESTS_CA_BUNDLE", localhost_certificate[0])
    server = DemuxServer(localhost_certificate)
    server.start()
    try:
        client = bcfapi.FoundationClient(CLIENT_ID, CLIENT_SECRET, server.base_url, "callback")
        with LOGIN_LOCK:
            try:
                client.login()
            except Exception:
                pass
        assert _leak_summary(server.cleartext_posts) == []
    finally:
        server.close()


def test_login_does_not_follow_token_redirect(
    localhost_certificate: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A token URL that passes the host check must not redirect the credentials away."""

    monkeypatch.setenv("REQUESTS_CA_BUNDLE", localhost_certificate[0])
    bcf = RecordingServer(tls=localhost_certificate)
    collector = RecordingServer()
    bcf.start()
    collector.start()
    try:
        bcf.set_discovery(bcf.base_url + "token")
        bcf.set_redirect(collector.base_url + "collect")
        collector.set_token_document(_token_document(COLLECTOR_ACCESS_TOKEN))
        client = bcfapi.FoundationClient(CLIENT_ID, CLIENT_SECRET, bcf.base_url, "callback")
        with LOGIN_LOCK:
            try:
                client.login()
            except Exception:
                pass
        assert _leak_summary(collector.posts) == []
        assert client.access_token != COLLECTOR_ACCESS_TOKEN
    finally:
        collector.close()
        bcf.close()


def test_refresh_does_not_follow_token_redirect(
    localhost_certificate: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refresh requests use the token URL from discovery and must not follow redirects."""

    monkeypatch.setenv("REQUESTS_CA_BUNDLE", localhost_certificate[0])
    bcf = RecordingServer(tls=localhost_certificate)
    collector = RecordingServer()
    bcf.start()
    collector.start()
    try:
        bcf.set_discovery(bcf.base_url + "token")
        client = _login(bcf.base_url)
        assert client.access_token == ISSUED_ACCESS_TOKEN
        bcf.set_redirect(collector.base_url + "collect")
        collector.set_token_document(_token_document(COLLECTOR_ACCESS_TOKEN))
        bcf.posts.clear()
        with LOGIN_LOCK:
            _call_token_operations(client)
        assert _leak_summary(collector.posts) == []
        assert client.access_token != COLLECTOR_ACCESS_TOKEN
    finally:
        collector.close()
        bcf.close()


def test_login_accepts_https_token_url_on_the_configured_host(
    localhost_certificate: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The token request is still sent when the discovery URL is https on the configured host."""

    monkeypatch.setenv("REQUESTS_CA_BUNDLE", localhost_certificate[0])
    bcf = RecordingServer(tls=localhost_certificate)
    bcf.start()
    try:
        bcf.set_discovery(bcf.base_url + "token")
        client = _login(bcf.base_url)
        assert client.access_token == ISSUED_ACCESS_TOKEN
        assert _leak_summary(bcf.posts) == [
            {
                "path": "/token",
                "sent_client_credentials": True,
                "sent_authorization_code": True,
                "sent_refresh_token": False,
            }
        ]
    finally:
        bcf.close()


def test_missing_token_url_does_not_post() -> None:
    bcf = RecordingServer()
    bcf.start()
    try:
        bcf.set_discovery("", omit_token_url=True)
        client = bcfapi.FoundationClient(CLIENT_ID, CLIENT_SECRET, bcf.base_url, "callback")
        with LOGIN_LOCK:
            with pytest.raises(Exception):
                client.login()
        assert _leak_summary(bcf.posts) == []
    finally:
        bcf.close()


def test_relative_token_url_does_not_post() -> None:
    bcf = RecordingServer()
    bcf.start()
    try:
        bcf.set_discovery("/token")
        client = bcfapi.FoundationClient(CLIENT_ID, CLIENT_SECRET, bcf.base_url, "callback")
        with LOGIN_LOCK:
            with pytest.raises(Exception):
                client.login()
            _call_token_operations(client)
        assert _leak_summary(bcf.posts) == []
    finally:
        bcf.close()
