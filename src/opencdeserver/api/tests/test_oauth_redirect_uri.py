# This file was generated with the assistance of an AI coding tool.
"""OAuth redirect_uri must be an exact registered callback.

The client registry entry may list allowed callbacks in ``redirect_uris``.
``/foundation/oauth2/auth`` and ``/foundation/oauth2/code`` must reject every
other string with HTTP 400 before an authorization code is stored.
``/foundation/oauth2/token`` must reject an authorization-code grant unless
the form field ``redirect_uri`` is exactly the value stored with that code.

``templates/index.html`` has the same browser delivery script as the login
page, but ``GET /`` does not take ``redirect_uri`` from the request, so it is
not covered here. The refresh-token grant does not use ``redirect_uri`` and
is not covered here.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import urlopen

APP_DIR = Path(__file__).resolve().parents[1] / "app"
CLIENT_ID = "test-client"
CLIENT_SECRET = "placeholder"
USER_NAME = "victim"
USER_PASSWORD = "placeholder"
REGISTERED = "https://client.example/oauth/callback"
OTHER_REGISTERED = "https://client.example/oauth/other-callback"

# Near matches and unrelated URIs. None of these is REGISTERED.
UNREGISTERED = [
    "https://attacker.example/cb",
    "https://client.example/oauth/callback/extra",
    "https://client.example/oauth/callback.evil",
    "https://client.example/oauth/callback?x=1",
    "https://client.example/oauth/callback/",
    "http://client.example/oauth/callback",
    "https://client.example.attacker.example/oauth/callback",
    "https://evil.client.example/oauth/callback",
    "https://user@client.example/oauth/callback",
    "https://client.example/oauth/callback%2Fextra",
    "https://client.example/oauth/callback/extra/../callback",
]


class _Store:
    def __init__(self):
        self.users = {}
        self.codes = {}
        self.events = []


STORE = _Store()


class _Result:
    def __init__(self, record, nodes_created=0, nodes_deleted=0):
        self._record = record
        self.counters = types.SimpleNamespace(nodes_created=nodes_created, nodes_deleted=nodes_deleted)

    def single(self):
        return self._record

    def consume(self):
        return self


class _Tx:
    def run(self, cypher, **params):
        text = cypher if isinstance(cypher, str) else str(cypher)
        if "RETURN u AS user" in text:
            user = STORE.users.get(params.get("username"))
            if user is None:
                return _Result(None)
            return _Result({"user": dict(user)})
        # Token write deletes the code and stores access and refresh tokens.
        # Match it before code creation: that statement also mentions AuthorizationCode.
        if "access_token" in params and "DETACH DELETE" in text and "AccessToken" in text:
            code = params.get("authorization_code")
            if code not in STORE.codes:
                return _Result(None, nodes_created=0, nodes_deleted=0)
            STORE.events.append(("issue_tokens", code))
            del STORE.codes[code]
            return _Result(None, nodes_created=2, nodes_deleted=1)
        if "SET ac.code" in text and "authorization_code" in params:
            code = params["authorization_code"]
            STORE.codes[code] = {
                "username": params.get("username"),
                "scope": params.get("scope"),
                "redirect_uri": params.get("redirect_uri"),
            }
            STORE.events.append(("create_authorization_code", code))
            return _Result({"authorization_code": code}, nodes_created=1)
        if "AuthorizationCode" in text and "RETURN" in text and "authorization_code" in params:
            record = STORE.codes.get(params["authorization_code"])
            if record is None:
                return _Result(None)
            # Honor a redirect constraint once the query actually carries one.
            if "redirect_uri" in params or "ac.redirect_uri" in text:
                if params.get("redirect_uri") != record.get("redirect_uri"):
                    return _Result(None)
            return _Result({"username": record["username"], "scope": record["scope"]})
        return _Result(None)


class _Session:
    def execute_write(self, work, *args, **kwargs):
        return work(_Tx(), *args, **kwargs)

    def execute_read(self, work, *args, **kwargs):
        return work(_Tx(), *args, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Driver:
    def verify_connectivity(self):
        return None

    def session(self):
        return _Session()


def _install_import_stubs():
    neo4j = types.ModuleType("neo4j")

    class GraphDatabase:
        @staticmethod
        def driver(_uri, auth=None):
            return _Driver()

    neo4j.GraphDatabase = GraphDatabase
    sys.modules["neo4j"] = neo4j

    os.environ["NEO4J_URI"] = "bolt://127.0.0.1:7687"
    os.environ["NEO4J_USER"] = "neo4j"
    os.environ["NEO4J_INITIAL_PASSWORD"] = "placeholder"
    os.environ["KONTROLL_BASE_URL"] = "https://cde.example/"
    os.environ["KONTROLL_CLIENT_ID"] = CLIENT_ID
    os.environ["KONTROLL_CLIENT_NAME"] = "Test Client"
    os.environ["SECURITY_AUTHORIZATION_CODE_EXPIRE_SECONDS"] = "600"
    os.environ["SECURITY_ACCESS_TOKEN_EXPIRE_SECONDS"] = "3600"
    os.environ["SECURITY_REFRESH_TOKEN_EXPIRE_SECONDS"] = "86400"
    os.environ["SECURITY_ALGORITHM"] = "HS256"
    os.environ["SESSION_URL_VALIDITY_SECONDS"] = "600"
    os.environ["SESSION_MAX_FILE_SIZE_BYTES"] = "1000000"

    sys.path.insert(0, str(APP_DIR))
    import security.secrets as secrets_module

    def get_secrets():
        return {
            "kontroll_client_secret": CLIENT_SECRET,
            "security_secret_key": "placeholder",
            "neo4j_password": "placeholder",
        }

    secrets_module.get_secrets = get_secrets


_install_import_stubs()
_previous_cwd = os.getcwd()
os.chdir(APP_DIR)
try:
    import api.foundation as foundation_api
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
finally:
    os.chdir(_previous_cwd)

foundation_api.templates.env.loader.searchpath = [str(APP_DIR / "templates")]

from passlib.context import CryptContext

_passwords = CryptContext(schemes=["bcrypt"], deprecated="auto")
STORE.users[USER_NAME] = {
    "username": USER_NAME,
    "email": "victim@example.com",
    "full_name": "Victim",
    "disabled": False,
    "hashed_password": _passwords.hash(USER_PASSWORD),
}

app = FastAPI()
app.include_router(foundation_api.router)
client = TestClient(app)


def setup_function():
    STORE.events.clear()
    foundation_api.clients[CLIENT_ID]["redirect_uris"] = [REGISTERED]


def _set_redirects(uris):
    foundation_api.clients[CLIENT_ID]["redirect_uris"] = list(uris)


def _auth(redirect_uri, scope="test", state="state-1"):
    return client.get(
        "/foundation/oauth2/auth",
        params={
            "response_type": "code",
            "client_id": CLIENT_ID,
            "state": state,
            "scope": scope,
            "redirect_uri": redirect_uri,
        },
    )


def _issue_code(redirect_uri, scope="test", state="state-1"):
    before = {event for event in STORE.events if event[0] == "create_authorization_code"}
    response = client.get(
        "/foundation/oauth2/code",
        params={
            "username": USER_NAME,
            "password": USER_PASSWORD,
            "response_type": "code",
            "client_id": CLIENT_ID,
            "client_name": "Test Client",
            "state": state,
            "scope": scope,
            "redirect_uri": redirect_uri,
        },
    )
    if response.status_code != 200:
        raise AssertionError(f"code endpoint rejected a registered redirect with status {response.status_code}")
    issued = response.json()
    if not isinstance(issued, str) or not issued:
        raise AssertionError("code endpoint did not return an authorization code")
    created = [event for event in STORE.events if event[0] == "create_authorization_code" and event not in before]
    if not created:
        raise AssertionError("code endpoint returned a code without storing one")
    return issued


def _redeem(code, redirect_uri=None):
    form = {"grant_type": "authorization_code", "code": code}
    if redirect_uri is not None:
        form["redirect_uri"] = redirect_uri
    return client.post("/foundation/oauth2/token", data=form, auth=(CLIENT_ID, CLIENT_SECRET))


def _assert_no_tokens(response):
    if response.status_code != 400:
        raise AssertionError(f"expected status 400, got {response.status_code}")
    try:
        body = response.json()
    except Exception as exc:
        raise AssertionError("expected a JSON rejection") from exc
    if body.get("access_token") or body.get("refresh_token"):
        raise AssertionError("rejection included tokens")


def _assert_tokens(response):
    if response.status_code != 201:
        raise AssertionError(f"expected status 201, got {response.status_code}")
    try:
        body = response.json()
    except Exception as exc:
        raise AssertionError("expected a JSON token response") from exc
    access = body.get("access_token")
    refresh = body.get("refresh_token")
    if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
        raise AssertionError("token response did not include access and refresh tokens")


def _assert_code_untouched(code):
    if ("issue_tokens", code) in STORE.events:
        raise AssertionError("tokens were stored before the exchange was refused")
    if code not in STORE.codes:
        raise AssertionError("the authorization code was consumed before the exchange was refused")


def test_exact_registered_redirect_renders_login_page():
    response = _auth(REGISTERED)
    if response.status_code != 200:
        raise AssertionError(f"registered redirect was rejected with status {response.status_code}")
    page = response.text
    if 'id="redirect_uri"' not in page or f'value="{REGISTERED}"' not in page:
        raise AssertionError("login page did not keep the exact registered redirect")
    if "function send_code" not in page:
        raise AssertionError("login page is missing the code delivery script")


def test_unregistered_redirect_is_rejected_and_stores_nothing():
    for redirect_uri in UNREGISTERED:
        setup_function()
        before = len(STORE.events)
        response = _auth(redirect_uri)
        if response.status_code != 400:
            embedded = f'value="{redirect_uri}"' in response.text and 'id="redirect_uri"' in response.text
            raise AssertionError(
                f"unregistered redirect was not rejected (status {response.status_code}); "
                f"login form embedded it: {embedded}"
            )
        if len(STORE.events) != before:
            raise AssertionError("authorization request stored state before refusing the redirect")
        if 'id="signin_button"' in response.text:
            raise AssertionError("rejection still rendered the login form")


def test_missing_redirect_registry_rejects_every_redirect():
    del foundation_api.clients[CLIENT_ID]["redirect_uris"]
    response = _auth(REGISTERED)
    if response.status_code != 400:
        raise AssertionError(f"redirect was accepted without a registry, status {response.status_code}")


def test_code_endpoint_rejects_unregistered_redirect_before_storing_it():
    before = list(STORE.events)
    response = client.get(
        "/foundation/oauth2/code",
        params={
            "username": USER_NAME,
            "password": USER_PASSWORD,
            "response_type": "code",
            "client_id": CLIENT_ID,
            "client_name": "Test Client",
            "state": "state-1",
            "scope": "test",
            "redirect_uri": "https://attacker.example/cb",
        },
    )
    if response.status_code != 400:
        raise AssertionError(f"code endpoint accepted an unregistered redirect with status {response.status_code}")
    if STORE.events != before:
        raise AssertionError("code endpoint stored an authorization code before refusing the redirect")


def test_token_exchange_accepts_only_the_stored_redirect_uri():
    _set_redirects([REGISTERED, OTHER_REGISTERED])
    code = _issue_code(REGISTERED)
    accepted = _redeem(code, REGISTERED)
    _assert_tokens(accepted)


def test_token_exchange_rejects_a_different_registered_redirect_uri():
    _set_redirects([REGISTERED, OTHER_REGISTERED])
    code = _issue_code(REGISTERED)
    rejected = _redeem(code, OTHER_REGISTERED)
    _assert_no_tokens(rejected)
    _assert_code_untouched(code)


def test_token_exchange_rejects_an_unregistered_redirect_uri():
    code = _issue_code(REGISTERED)
    rejected = _redeem(code, "https://attacker.example/cb")
    _assert_no_tokens(rejected)
    _assert_code_untouched(code)


def test_token_exchange_rejects_a_missing_redirect_uri():
    code = _issue_code(REGISTERED)
    rejected = _redeem(code, None)
    _assert_no_tokens(rejected)
    _assert_code_untouched(code)


class _Callback:
    def __init__(self):
        paths = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                body = b"ok"
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.end_headers()

            def log_message(self, _format, *_args):
                return

        self.paths = paths
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self):
        return f"http://127.0.0.1:{self.port}/cb"

    def codes(self):
        found = []
        for path in self.paths:
            query = parse_qs(urlparse(path).query)
            for value in query.get("code", []):
                if value:
                    found.append(value)
        return found

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _jquery_source():
    """jQuery 3.6.3, the script the login page loads."""
    cache = Path(tempfile.gettempdir()) / "jquery-3.6.3.js"
    if not cache.exists() or cache.stat().st_size < 1000:
        with urlopen("https://code.jquery.com/jquery-3.6.3.js", timeout=30) as response:
            cache.write_bytes(response.read())
    return cache.read_bytes()


class _Chrome:
    def __init__(self):
        self.port = _free_port()
        self.user_dir = tempfile.mkdtemp(prefix="oauth-chrome-")
        self.proc = subprocess.Popen(
            [
                "google-chrome",
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                f"--remote-debugging-port={self.port}",
                "--remote-allow-origins=*",
                f"--user-data-dir={self.user_dir}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.ws = None
        self._next_id = 0
        self._pending = {}
        self._lock = threading.Lock()
        self._closed = False
        deadline = time.time() + 15
        ws_url = None
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError("chrome exited before the debugging port opened")
            try:
                with urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=1) as response:
                    pages = json.loads(response.read().decode())
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                time.sleep(0.1)
        if ws_url is None:
            raise AssertionError("chrome debugging endpoint did not come up")
        from websockets.sync.client import connect

        self.ws = connect(ws_url, open_timeout=5)
        self._jquery = _jquery_source()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})

    def _read_loop(self):
        while not self._closed:
            try:
                raw = self.ws.recv(timeout=0.5)
            except TimeoutError:
                continue
            except Exception:
                return
            message = json.loads(raw)
            if message.get("method") == "Fetch.requestPaused":
                self._fulfill(message["params"])
                continue
            message_id = message.get("id")
            if message_id is not None:
                with self._lock:
                    self._pending[message_id] = message

    def _fulfill(self, params):
        request_id = params["requestId"]
        url = params["request"]["url"]
        if "jquery-3.6.3" in url:
            body = self._jquery
            content_type = "application/javascript"
        elif "bootstrap" in url and ".js" in url:
            body = b"/* bootstrap not required for the login script */"
            content_type = "application/javascript"
        elif "bootstrap" in url and ".css" in url:
            body = b""
            content_type = "text/css"
        else:
            self._send("Fetch.continueRequest", {"requestId": request_id})
            return
        self._send(
            "Fetch.fulfillRequest",
            {
                "requestId": request_id,
                "responseCode": 200,
                "responseHeaders": [{"name": "Content-Type", "value": content_type}],
                "body": base64.b64encode(body).decode(),
            },
        )

    def _send(self, method, params):
        with self._lock:
            self._next_id += 1
            message_id = self._next_id
            self.ws.send(json.dumps({"id": message_id, "method": method, "params": params}))
            return message_id

    def call(self, method, params=None, timeout=20):
        message_id = self._send(method, params or {})
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                message = self._pending.pop(message_id, None)
            if message is not None:
                if "error" in message:
                    raise AssertionError(f"chrome call {method} failed")
                return message.get("result", {})
            time.sleep(0.01)
        raise AssertionError(f"chrome call {method} timed out")

    def sign_in(self, redirect_uri):
        auth = (
            "http://127.0.0.1:"
            + str(_server_port)
            + "/foundation/oauth2/auth?response_type=code&client_id="
            + quote(CLIENT_ID)
            + "&state=state-1&scope=test&redirect_uri="
            + quote(redirect_uri, safe="")
        )
        self.call("Page.navigate", {"url": auth})
        deadline = time.time() + 15
        state = "loading"
        while time.time() < deadline:
            state = self._eval(
                "(() => {"
                " if (!window.jQuery) return 'no-jquery';"
                " if (!document.querySelector('#signin_button')) return 'no-form';"
                " return 'ready';"
                "})()"
            )
            if state in ("ready", "no-form"):
                break
            time.sleep(0.1)
        if state == "no-jquery":
            raise AssertionError("login page did not load its script")
        if state == "no-form":
            return "no-form"
        if state != "ready":
            raise AssertionError("login page did not become ready")
        clicked = self._eval(
            "(() => {"
            f" jQuery('#username').val({json.dumps(USER_NAME)});"
            f" jQuery('#password').val({json.dumps(USER_PASSWORD)});"
            " jQuery('#signin_button').trigger('click');"
            " return 'clicked';"
            "})()"
        )
        return clicked

    def _eval(self, expression):
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        return result.get("result", {}).get("value")

    def close(self):
        if self.ws is not None:
            self.ws.close()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


_server = None
_server_port = None


def _start_api():
    global _server, _server_port
    import uvicorn

    _server_port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=_server_port, log_level="error")
    _server = uvicorn.Server(config)
    _server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=_server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline:
        if getattr(_server, "started", False):
            return
        time.sleep(0.05)
    raise AssertionError("API server did not start")


def _wait_codes(callback, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if callback.codes():
            return callback.codes()
        time.sleep(0.1)
    return callback.codes()


def test_browser_login_delivers_code_only_to_the_exact_registered_redirect():
    """Sign-in on the rendered login page must deliver the code only to the registered URI."""
    _start_api()
    legit = _Callback()
    attacker = _Callback()
    chrome = _Chrome()
    try:
        _set_redirects([legit.url()])
        legit_action = chrome.sign_in(legit.url())
        if legit_action != "clicked":
            raise AssertionError(f"registered redirect did not render a login form ({legit_action})")
        if not _wait_codes(legit, 8):
            raise AssertionError("registered redirect did not receive the authorization code from the login page")

        _set_redirects([legit.url()])
        attacker_action = chrome.sign_in(attacker.url())
        delivered = []
        if attacker_action == "clicked":
            delivered = _wait_codes(attacker, 5)
        elif attacker_action != "no-form":
            raise AssertionError(f"unexpected login page state for an unregistered redirect ({attacker_action})")
        tokens_issued = False
        if delivered:
            redeemed = _redeem(delivered[0], attacker.url())
            tokens_issued = redeemed.status_code == 201
        if delivered:
            if tokens_issued:
                raise AssertionError(
                    "unregistered redirect received an authorization code and the token endpoint issued tokens"
                )
            raise AssertionError("unregistered redirect received an authorization code")
    finally:
        chrome.close()
        legit.close()
        attacker.close()
