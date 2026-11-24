# This file was generated with the assistance of an AI coding tool.
"""Sign-in and token issuance must not write secrets to logs or process output.

The OpenCDE app mounts the foundation and BCF routers, both using LoggingRoute,
and prints credentials from the handlers. These tests drive those routes and
the login page the server renders. They fail while a password, authorization
code, client secret, access token, or refresh token is written to logs/info.log,
process stdout/stderr, or the uvicorn access log.

Not requested here, and therefore not asserted one by one:
- src/opencdeserver/api/app/api/documents.py routes. main.py mounts that router
  with the same LoggingRoute, and its handlers use get_current_active_user, but
  importing the package pulls ifcopenshell and py2neo, which are not installed
  in this environment.
- Other BCF routes besides GET /bcf/3.0/projects. They use the same LoggingRoute
  and the same get_current_active_user dependency exercised below.
- src/opencdeserver/api/app/api/user.py. That router is not included by main.py.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import threading
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
REPORT: dict | None = None

STORE: dict = {"users": {}, "codes": {}, "access_by_refresh_hash": {}}


class _Summary:
    def __init__(self, created: int, deleted: int) -> None:
        self.counters = type("Counters", (), {"nodes_created": created, "nodes_deleted": deleted})()


class _Result:
    def __init__(self, records: list, created: int = 0, deleted: int = 0) -> None:
        self._records = records
        self._summary = _Summary(created, deleted)

    def single(self):
        if not self._records:
            return None
        return self._records[0]

    def consume(self):
        return self._summary

    def __iter__(self):
        return iter(self._records)


class _Tx:
    def run(self, cypher, **kwargs):
        text = cypher if isinstance(cypher, str) else ""
        if "RETURN u AS user" in text:
            user = STORE["users"].get(kwargs.get("username"))
            if user is None:
                return _Result([])
            return _Result([{"user": user}])
        if "SET ac.code = $authorization_code" in text:
            STORE["codes"][kwargs["authorization_code"]] = {
                "username": kwargs["username"],
                "scope": kwargs["scope"],
            }
            return _Result([{"authorization_code": kwargs["authorization_code"]}], created=1)
        if "WHERE ac.code = $authorization_code" in text:
            found = STORE["codes"].get(kwargs.get("authorization_code"))
            if found is None:
                return _Result([])
            return _Result([{"username": found["username"], "scope": found["scope"]}])
        if "SET t2.value = $access_token" in text:
            STORE["access_by_refresh_hash"][kwargs["refresh_token_hash"]] = kwargs["access_token"]
            return _Result([], created=1, deleted=1)
        if "at.value AS access_token" in text:
            access = STORE["access_by_refresh_hash"].get(kwargs.get("refresh_token_hash"))
            if access is None:
                return _Result([])
            return _Result([{"access_token": access}])
        if "rt.value = $refresh_token" in text:
            STORE["access_by_refresh_hash"][kwargs["refresh_token_hash"]] = kwargs["access_token"]
            return _Result([], created=2, deleted=2)
        if "RETURN p AS project" in text:
            return _Result([])
        return _Result([])


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute_read(self, work, *args, **kwargs):
        return work(_Tx(), *args, **kwargs)

    def execute_write(self, work, *args, **kwargs):
        return work(_Tx(), *args, **kwargs)


class _Driver:
    def verify_connectivity(self):
        return None

    def session(self):
        return _Session()


def install_fakes(secret_dir: str) -> None:
    """Point secret loading and the Neo4j driver at test doubles before the app imports."""
    import glob

    import neo4j

    real_glob = glob.glob

    def patched_glob(pattern, *args, **kwargs):
        if pattern == "/run/secrets/*":
            return real_glob(str(Path(secret_dir) / "*"), *args, **kwargs)
        return real_glob(pattern, *args, **kwargs)

    glob.glob = patched_glob
    neo4j.GraphDatabase.driver = lambda *args, **kwargs: _Driver()


def register_placeholder_user() -> None:
    from models.request import UserInDB
    from security.secure import get_password_hash

    username = os.environ["PLACEHOLDER_USERNAME"]
    # Touch the model so a field mismatch fails here, then store the node map the driver returns.
    UserInDB(
        username=username,
        email="placeholder@example.com",
        full_name="Placeholder User",
        disabled=False,
        hashed_password=get_password_hash(os.environ["PLACEHOLDER_PASSWORD"]),
    )
    STORE["users"][username] = {
        "username": username,
        "email": "placeholder@example.com",
        "full_name": "Placeholder User",
        "disabled": False,
        "hashed_password": get_password_hash(os.environ["PLACEHOLDER_PASSWORD"]),
    }


def _contains(haystack: str, needle: str) -> bool:
    return bool(needle) and needle in haystack


def _form_fields(html: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in re.finditer(r"<input\b([^>]*)>", html, re.I):
        attrs = match.group(1)
        name = re.search(r'name="([^"]+)"', attrs)
        if name is None:
            continue
        value = re.search(r'value="([^"]*)"', attrs)
        fields[name.group(1)] = value.group(1) if value else ""
    return fields


def _sign_in_method(html: str) -> str:
    if re.search(r"type:\s*['\"]GET['\"]", html):
        return "GET"
    form = re.search(r"<form\b([^>]*)>", html, re.I)
    if form and re.search(r"method\s*=\s*['\"]post['\"]", form.group(1), re.I):
        return "POST"
    return "GET"


def _prepare_tree() -> Path:
    work = Path(tempfile.mkdtemp(prefix="opencde-auth-log-"))
    (work / "logs").mkdir()
    os.symlink(APP_DIR / "templates", work / "templates")
    os.symlink(APP_DIR / "db_config", work / "db_config")
    os.chdir(work)
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    return work


def _write_secrets(secret_dir: Path, client_secret: str, security_key: str) -> None:
    secret_dir.mkdir(exist_ok=True)
    (secret_dir / "kontroll_client_secret").write_text(client_secret + "\n", encoding="utf-8")
    (secret_dir / "security_secret_key").write_text(security_key + "\n", encoding="utf-8")
    (secret_dir / "neo4j_password").write_text("placeholder-neo4j\n", encoding="utf-8")


def _base_env(secret_dir: Path, client_secret: str, security_key: str) -> None:
    os.environ["KONTROLL_CLIENT_ID"] = "placeholder-client"
    os.environ["KONTROLL_CLIENT_NAME"] = "Placeholder Client"
    os.environ["KONTROLL_BASE_URL"] = "http://testserver/"
    os.environ["NEO4J_URI"] = "bolt://127.0.0.1:7687"
    os.environ["NEO4J_USER"] = "placeholder-neo4j-user"
    os.environ["NEO4J_INITIAL_PASSWORD"] = "placeholder-neo4j"
    os.environ["SECURITY_AUTHORIZATION_CODE_EXPIRE_SECONDS"] = "60"
    os.environ["SECURITY_ACCESS_TOKEN_EXPIRE_SECONDS"] = "60"
    os.environ["SECURITY_REFRESH_TOKEN_EXPIRE_SECONDS"] = "120"
    os.environ["SECURITY_ALGORITHM"] = "HS256"
    os.environ["SECRET_DIR"] = str(secret_dir)
    os.environ["PLACEHOLDER_CLIENT_SECRET"] = client_secret
    os.environ["SECURITY_KEY_FOR_TEST"] = security_key
    _write_secrets(secret_dir, client_secret, security_key)


def _new_placeholders() -> tuple[str, str, str, str, str]:
    import secrets

    username = "placeholder-user"
    password = "placeholder-" + secrets.token_hex(16)
    rejected_password = "placeholder-rejected-" + secrets.token_hex(16)
    client_secret = "placeholder-client-secret-" + secrets.token_hex(16)
    wrong_client_secret = "placeholder-wrong-client-secret-" + secrets.token_hex(16)
    return username, password, rejected_password, client_secret, wrong_client_secret


def _scan(text: str, names: dict[str, str], flags: dict[str, bool], suffix: str) -> None:
    for label, value in names.items():
        flags[f"{label}_{suffix}"] = _contains(text, value)


def _read_log() -> str:
    path = Path("logs") / "info.log"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _flush_logs() -> None:
    for name in ("", "uvicorn.access", "uvicorn", "uvicorn.error"):
        for handler in logging.getLogger(name).handlers:
            handler.flush()


class _Capture:
    def __enter__(self):
        self.out = io.StringIO()
        self.err = io.StringIO()
        self._out = sys.stdout
        self._err = sys.stderr
        sys.stdout = self.out
        sys.stderr = self.err
        return self

    def __exit__(self, exc_type, exc, tb):
        sys.stdout = self._out
        sys.stderr = self._err
        return False


def _submit_sign_in(client, html: str, username: str, password: str):
    fields = _form_fields(html)
    fields["username"] = username
    fields["password"] = password
    method = _sign_in_method(html)
    if method == "POST":
        return method, client.post("/foundation/oauth2/code", data=fields)
    return method, client.get("/foundation/oauth2/code", params=fields)


def _load_routers():
    from api.bcf import router as bcf_router
    from api.foundation import router as foundation_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(foundation_router)
    app.include_router(bcf_router)
    return app


def _auth_params() -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": os.environ["KONTROLL_CLIENT_ID"],
        "state": "placeholder-state",
        "scope": "test",
        "redirect_uri": "http://127.0.0.1/callback",
    }


def run_flow() -> dict:
    import secrets

    from fastapi.testclient import TestClient

    username, password, rejected_password, client_secret, wrong_client_secret = _new_placeholders()
    security_key = "placeholder-security-key-" + secrets.token_hex(16)
    secret_dir = Path(tempfile.mkdtemp(prefix="opencde-secrets-"))
    _prepare_tree()
    _base_env(secret_dir, client_secret, security_key)
    os.environ["PLACEHOLDER_USERNAME"] = username
    os.environ["PLACEHOLDER_PASSWORD"] = password
    install_fakes(str(secret_dir))
    app = _load_routers()
    register_placeholder_user()
    # The TestClient uses httpx. The app's basicConfig attaches a debug file handler
    # to the root logger, so the client's own request log would land in logs/info.log.
    # The server does not log incoming calls through httpx. Silence that client logger
    # so the file contains the server's records.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    names = {
        "password": password,
        "rejected_password": rejected_password,
        "client_secret": client_secret,
        "wrong_client_secret": wrong_client_secret,
    }
    flags = {"flow_ok": False, "error": "", "sign_in_method": ""}
    capture = _Capture()
    try:
        with capture:
            client = TestClient(app)
            page = client.get("/foundation/oauth2/auth", params=_auth_params())
            flags["auth_page_status"] = page.status_code
            method, rejected = _submit_sign_in(client, page.text, username, rejected_password)
            flags["sign_in_method"] = method
            flags["rejected_status"] = rejected.status_code
            method, accepted = _submit_sign_in(client, page.text, username, password)
            flags["code_status"] = accepted.status_code
            auth_code = ""
            if accepted.status_code == 200:
                auth_code = accepted.json()
                names["auth_code"] = auth_code
            bad = client.post(
                "/foundation/oauth2/token",
                data={"grant_type": "authorization_code", "code": auth_code},
                auth=("placeholder-client", wrong_client_secret),
            )
            flags["bad_token_status"] = bad.status_code
            token_response = client.post(
                "/foundation/oauth2/token",
                data={"grant_type": "authorization_code", "code": auth_code},
                auth=("placeholder-client", client_secret),
            )
            flags["token_status"] = token_response.status_code
            access_token = ""
            refresh_token = ""
            if token_response.status_code == 201:
                body = token_response.json()
                access_token = body.get("access_token") or ""
                refresh_token = body.get("refresh_token") or ""
                names["access_token"] = access_token
                names["refresh_token"] = refresh_token
            current = client.get(
                "/foundation/1.0/current-user",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            flags["current_user_status"] = current.status_code
            projects = client.get(
                "/bcf/3.0/projects",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            flags["projects_status"] = projects.status_code
            refresh = client.post(
                "/foundation/oauth2/token",
                data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                auth=("placeholder-client", client_secret),
            )
            flags["refresh_status"] = refresh.status_code
            if refresh.status_code == 201:
                refreshed = refresh.json()
                names["refreshed_access_token"] = refreshed.get("access_token") or ""
                names["refreshed_refresh_token"] = refreshed.get("refresh_token") or ""
        _flush_logs()
        log_text = _read_log()
        _scan(log_text, names, flags, "in_info_log")
        _scan(capture.out.getvalue(), names, flags, "in_stdout")
        _scan(capture.err.getvalue(), names, flags, "in_stderr")
        expected = {
            "auth_page_status": 200,
            "rejected_status": 401,
            "code_status": 200,
            "bad_token_status": 401,
            "token_status": 201,
            "current_user_status": 200,
            "projects_status": 200,
            "refresh_status": 201,
        }
        mismatches = [f"{key}={flags.get(key)}" for key, value in expected.items() if flags.get(key) != value]
        if mismatches:
            flags["error"] = "unexpected status: " + ", ".join(mismatches)
        elif not names.get("auth_code") or not names.get("access_token") or not names.get("refresh_token"):
            flags["error"] = "sign-in did not return an authorization code and tokens"
        else:
            flags["flow_ok"] = True
    except Exception as exc:
        flags["error"] = type(exc).__name__
        flags["flow_ok"] = False
        _flush_logs()
        names_now = {key: value for key, value in names.items() if value}
        _scan(_read_log(), names_now, flags, "in_info_log")
        _scan(capture.out.getvalue(), names_now, flags, "in_stdout")
        _scan(capture.err.getvalue(), names_now, flags, "in_stderr")
    return flags


def _server_entry_source() -> str:
    return textwrap.dedent(
        """
        import importlib.util
        import os
        import sys

        sys.path.insert(0, os.environ["APP_DIR"])
        spec = importlib.util.spec_from_file_location("auth_log_tests", os.environ["AUTH_TEST_FILE"])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.install_fakes(os.environ["SECRET_DIR"])
        from fastapi import FastAPI
        from api.foundation import router as foundation_router

        app = FastAPI()
        app.include_router(foundation_router)
        module.register_placeholder_user()
        """
    )


def run_uvicorn() -> dict:
    import copy
    import secrets

    import httpx
    import uvicorn

    username, password, _rejected, client_secret, _wrong = _new_placeholders()
    security_key = "placeholder-security-key-" + secrets.token_hex(16)
    secret_dir = Path(tempfile.mkdtemp(prefix="opencde-secrets-"))
    work = _prepare_tree()
    sys.path.insert(0, str(work))
    _base_env(secret_dir, client_secret, security_key)
    os.environ["APP_DIR"] = str(APP_DIR)
    os.environ["AUTH_TEST_FILE"] = str(Path(__file__).resolve())
    os.environ["PLACEHOLDER_USERNAME"] = username
    os.environ["PLACEHOLDER_PASSWORD"] = password
    entry = work / "server_entry.py"
    entry.write_text(_server_entry_source(), encoding="utf-8")
    access_path = work / "logs" / "access.log"
    log_config = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    log_config["handlers"]["access"] = {
        "formatter": "access",
        "class": "logging.FileHandler",
        "filename": str(access_path),
    }
    flags = {"uvicorn_ok": False, "uvicorn_error": ""}
    capture = _Capture()
    try:
        with capture:
            config = uvicorn.Config(
                "server_entry:app",
                host="127.0.0.1",
                port=0,
                http="h11",
                access_log=True,
                log_config=log_config,
                log_level="info",
            )
            sockets = config.bind_socket()
            port = sockets.getsockname()[1]
            server = uvicorn.Server(config)
            thread_error: list[str] = []

            def serve() -> None:
                try:
                    server.run(sockets=[sockets])
                except BaseException as exc:
                    thread_error.append(type(exc).__name__)

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            for _ in range(100):
                if server.started:
                    break
                thread.join(0.05)
            if not server.started:
                detail = ",".join(thread_error)
                redacted = re.sub(
                    r"placeholder-[A-Za-z0-9-]+",
                    "<placeholder>",
                    capture.out.getvalue() + "\n" + capture.err.getvalue(),
                )
                redacted = re.sub(r"eyJ[A-Za-z0-9_\-\.]+", "<jwt>", redacted)
                tail = " | ".join(redacted.splitlines()[-8:])
                flags["uvicorn_error"] = f"server did not start: {detail} {tail}"[:500]
                return flags
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("httpcore").setLevel(logging.WARNING)
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
                page = client.get("/foundation/oauth2/auth", params=_auth_params())
                flags["uvicorn_auth_status"] = page.status_code
                _method, signed_in = _submit_sign_in(client, page.text, username, password)
                flags["uvicorn_code_status"] = signed_in.status_code
            server.should_exit = True
            thread.join(5)
        _flush_logs()
        access_text = access_path.read_text(encoding="utf-8", errors="replace") if access_path.exists() else ""
        info_text = _read_log()
        stdout_text = capture.out.getvalue()
        stderr_text = capture.err.getvalue()
        flags["uvicorn_password_in_access_log"] = _contains(access_text, password)
        flags["uvicorn_password_in_info_log"] = _contains(info_text, password)
        flags["uvicorn_password_in_stdout"] = _contains(stdout_text, password)
        flags["uvicorn_password_in_stderr"] = _contains(stderr_text, password)
        if flags["uvicorn_auth_status"] != 200 or flags["uvicorn_code_status"] != 200:
            flags["uvicorn_error"] = "unexpected uvicorn status"
        else:
            flags["uvicorn_ok"] = True
    except Exception as exc:
        flags["uvicorn_error"] = type(exc).__name__
        flags["uvicorn_ok"] = False
    return flags


def _worker(mode: str, report_path: str) -> None:
    if mode == "flow":
        report = run_flow()
    elif mode == "uvicorn":
        report = run_uvicorn()
    else:
        report = {"error": "unknown mode"}
    Path(report_path).write_text(json.dumps(report), encoding="utf-8")


def _spawn(mode: str) -> dict:
    fd, report_path = tempfile.mkstemp(prefix=f"opencde-{mode}-", suffix=".json")
    os.close(fd)
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), mode, report_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    path = Path(report_path)
    if not path.exists() or path.stat().st_size == 0:
        return {"flow_ok": False, "uvicorn_ok": False, "error": f"{mode} worker produced no report"}
    return json.loads(path.read_text(encoding="utf-8"))


def get_report() -> dict:
    global REPORT
    if REPORT is None:
        flow = _spawn("flow")
        uvicorn_report = _spawn("uvicorn")
        REPORT = {**flow, **uvicorn_report}
    return REPORT


@pytest.fixture(scope="session")
def report() -> dict:
    return get_report()


def _require_flow(report: dict) -> None:
    assert report.get("flow_ok") is True, report.get("error") or "sign-in flow did not complete"


def test_successful_sign_in_does_not_record_password(report):
    _require_flow(report)
    assert report.get("password_in_info_log") is False
    assert report.get("password_in_stdout") is False
    assert report.get("password_in_stderr") is False


def test_rejected_sign_in_does_not_record_password(report):
    _require_flow(report)
    assert report.get("rejected_password_in_info_log") is False
    assert report.get("rejected_password_in_stdout") is False
    assert report.get("rejected_password_in_stderr") is False


def test_authorization_code_is_not_recorded(report):
    _require_flow(report)
    assert report.get("auth_code_in_info_log") is False
    assert report.get("auth_code_in_stdout") is False
    assert report.get("auth_code_in_stderr") is False


def test_token_response_and_client_secret_are_not_recorded(report):
    _require_flow(report)
    for label in ("access_token", "refresh_token", "client_secret", "wrong_client_secret"):
        assert report.get(f"{label}_in_info_log") is False
        assert report.get(f"{label}_in_stdout") is False
        assert report.get(f"{label}_in_stderr") is False


def test_refresh_grant_tokens_are_not_recorded(report):
    _require_flow(report)
    for label in ("refresh_token", "refreshed_access_token", "refreshed_refresh_token"):
        assert report.get(f"{label}_in_info_log") is False
        assert report.get(f"{label}_in_stdout") is False
        assert report.get(f"{label}_in_stderr") is False


def test_bearer_token_is_not_recorded_on_authenticated_routes(report):
    _require_flow(report)
    assert report.get("current_user_status") == 200
    assert report.get("projects_status") == 200
    assert report.get("access_token_in_stdout") is False
    assert report.get("access_token_in_stderr") is False
    assert report.get("access_token_in_info_log") is False


def test_uvicorn_access_log_omits_password(report):
    assert report.get("uvicorn_ok") is True, report.get("uvicorn_error") or "uvicorn sign-in did not complete"
    assert report.get("uvicorn_password_in_access_log") is False
    assert report.get("uvicorn_password_in_info_log") is False
    assert report.get("uvicorn_password_in_stdout") is False
    assert report.get("uvicorn_password_in_stderr") is False


if __name__ == "__main__":
    _worker(sys.argv[1], sys.argv[2])
