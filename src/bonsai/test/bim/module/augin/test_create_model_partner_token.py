# This file was generated with the assistance of an AI coding tool.
# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

"""Augin model creation must not send a partner credential shipped in the add-on.

``AuginLogin`` posts the caller's email and password to ``user_login`` and stores
the returned user token. ``AuginCreateNewModel`` posts that user token to
``new_model``. These tests drive both operators and fail while ``new_model``
also sends a ``partner_token`` whose value is a string literal in the shipped
``augin`` package. ``AuginReset`` performs no request. ``files_uploaded`` is
covered because it is the other request ``AuginCreateNewModel`` makes.
"""

import ast
import importlib.util
import json
import socket
import sys
import types
import urllib.parse
from pathlib import Path

import pytest
import requests
from requests.adapters import HTTPAdapter

AUGN_DIR = Path(__file__).resolve().parents[4] / "bonsai" / "bim" / "module" / "augin"
OPERATOR_PATH = AUGN_DIR / "operator.py"
NEW_MODEL_URL = "https://server.auge.pro.br/API/v3/augin_rest.php/new_model"
USER_LOGIN_URL = "https://server.auge.pro.br/API/v3/augin_rest.php/user_login"
FILES_UPLOADED_URL = "https://server.auge.pro.br/API/v3/augin_rest.php/files_uploaded"
AUGN_HOST = "server.auge.pro.br"


class _Render:
    def __init__(self):
        self.image_settings = types.SimpleNamespace(file_format="PNG")
        self.filepath = ""


class _Scene:
    def __init__(self):
        self.AuginProperties = types.SimpleNamespace(
            username="",
            password="",
            token="",
            project_name="Example project",
            project_filename="",
            is_success=False,
        )
        self.render = _Render()
        self.collection = types.SimpleNamespace(objects=types.SimpleNamespace(link=lambda obj: None))
        self.camera = None


class _Context:
    def __init__(self):
        self.scene = _Scene()


def _string_constants(node):
    found = set()

    def walk(code):
        for const in code.co_consts:
            if isinstance(const, str):
                found.add(const)
            elif isinstance(const, types.CodeType):
                walk(const)

    walk(node)
    return found


def _shipped_string_literals(module):
    """String literals an attacker can read from the installed augin package."""
    literals = set()
    for path in AUGN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
    for value in vars(module).values():
        code = getattr(value, "__code__", None)
        if isinstance(code, types.CodeType):
            literals.update(_string_constants(code))
        for member in vars(value).values() if isinstance(value, type) else ():
            member_code = getattr(member, "__code__", None)
            if isinstance(member_code, types.CodeType):
                literals.update(_string_constants(member_code))
    return literals


def _load_operator():
    bpy = types.ModuleType("bpy")
    bpy.app = types.SimpleNamespace(version_string="4.2.0")
    bpy.types = types.SimpleNamespace(Operator=type("Operator", (), {}), Panel=type("Panel", (), {}))
    bpy.data = types.SimpleNamespace(
        cameras=types.SimpleNamespace(new=lambda name: object()),
        objects=types.SimpleNamespace(new=lambda name, data: object()),
    )
    render_ops = types.SimpleNamespace()

    def opengl(write_still=False):
        filepath = opengl.scene.render.filepath
        Path(filepath).write_bytes(b"png")

    opengl.scene = None
    render_ops.opengl = opengl
    bpy.ops = types.SimpleNamespace(render=render_ops)
    sys.modules["bpy"] = bpy

    bonsai_pkg = types.ModuleType("bonsai")
    bonsai_pkg.__path__ = []
    tool = types.ModuleType("bonsai.tool")

    class _Blender:
        @staticmethod
        def get_bonsai_version():
            return "0.0.0-test"

        @staticmethod
        def get_addon_preferences():
            return types.SimpleNamespace(tmp_dir=None)

        @staticmethod
        def get_bim_props():
            return types.SimpleNamespace(ifc_file=opengl.ifc_file)

    tool.Blender = _Blender
    sys.modules["bonsai"] = bonsai_pkg
    sys.modules["bonsai.tool"] = tool

    boto3 = types.ModuleType("boto3")

    class _S3Client:
        def upload_file(self, filename, bucket, key):
            return None

    boto3.client = lambda *args, **kwargs: _S3Client()
    botocore = types.ModuleType("botocore")
    botocore_config = types.ModuleType("botocore.config")

    class _Config:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    botocore_config.Config = _Config
    sys.modules["boto3"] = boto3
    sys.modules["botocore"] = botocore
    sys.modules["botocore.config"] = botocore_config

    spec = importlib.util.spec_from_file_location("augin_operator_under_test", OPERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._opengl = opengl
    return module


def _partner_token_values(prepared):
    body = prepared.body
    if body is None:
        return []
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    content_type = prepared.headers.get("Content-Type", "")
    if "application/json" in content_type:
        data = json.loads(text)
        if not isinstance(data, dict) or "partner_token" not in data:
            if "partner_token" in text:
                raise AssertionError("partner_token is present in the body but was not parsed")
            return []
        value = data["partner_token"]
        return [value] if isinstance(value, str) else [json.dumps(value)]
    parsed = urllib.parse.parse_qs(text, keep_blank_values=True)
    if "partner_token" in parsed:
        return parsed["partner_token"]
    if "partner_token" in text:
        raise AssertionError("partner_token is present in the body but was not parsed")
    return []


def _form_values(prepared, key):
    body = prepared.body
    if body is None:
        return []
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    content_type = prepared.headers.get("Content-Type", "")
    if "application/json" in content_type:
        data = json.loads(text)
        if not isinstance(data, dict) or key not in data:
            return []
        value = data[key]
        return [value] if isinstance(value, str) else [json.dumps(value)]
    return urllib.parse.parse_qs(text, keep_blank_values=True).get(key, [])


def _local_response(prepared, issued_user_token):
    response = requests.Response()
    response.status_code = 200
    response.url = prepared.url
    response.request = prepared
    response.headers["Content-Type"] = "application/json"
    if prepared.url == USER_LOGIN_URL:
        payload = {"success_feedback": {"success": True}, "token": issued_user_token}
    elif prepared.url == NEW_MODEL_URL:
        payload = {
            "s3_region": "placeholder-region",
            "s3_key": "placeholder-key",
            "s3_secret": "placeholder-secret",
            "s3_token": "placeholder-session",
            "s3_bucket": "placeholder-bucket",
            "model_path": "placeholder/model.ifc",
            "thumb_path": "placeholder/thumb.png",
            "model_id": "placeholder-id",
        }
    elif prepared.url == FILES_UPLOADED_URL:
        payload = {"success_feedback": {"success": True}}
    else:
        raise AssertionError("Augin operator called an unexpected URL")
    response._content = json.dumps(payload).encode("utf-8")
    return response


def _run_login_and_create(module, email, password, issued_user_token, ifc_file):
    captured = []
    module._opengl.scene = None
    module._opengl.ifc_file = ifc_file

    def capturing_send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        host = urllib.parse.urlparse(request.url).hostname
        if host != AUGN_HOST:
            raise AssertionError("operator tried to call a host other than the Augin API")
        captured.append(request.copy())
        return _local_response(request, issued_user_token)

    def refuse_connection(*args, **kwargs):
        raise AssertionError("test attempted a real network connection")

    context = _Context()
    context.scene.AuginProperties.username = email
    context.scene.AuginProperties.password = password
    module._opengl.scene = context.scene

    original_send = HTTPAdapter.send
    original_create_connection = socket.create_connection
    HTTPAdapter.send = capturing_send
    socket.create_connection = refuse_connection
    try:
        login = module.AuginLogin()
        login_result = login.execute(context)
        create = module.AuginCreateNewModel()
        create_result = create.execute(context)
    finally:
        HTTPAdapter.send = original_send
        socket.create_connection = original_create_connection
    return context, login_result, create_result, captured


def _by_url(captured, url):
    matches = [prepared for prepared in captured if prepared.url == url]
    if len(matches) != 1:
        raise AssertionError(f"expected one request to {url}")
    return matches[0]


@pytest.fixture()
def operator_module():
    keys = ("bpy", "bonsai", "bonsai.tool", "boto3", "botocore", "botocore.config")
    saved = {key: sys.modules.get(key) for key in keys}
    module = _load_operator()
    try:
        yield module
    finally:
        for key, previous in saved.items():
            if previous is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = previous


@pytest.fixture()
def shipped_literals(operator_module):
    return _shipped_string_literals(operator_module)


def _urls_sending_shipped_partner_credential(captured, shipped_literals):
    offending = []
    for prepared in captured:
        values = _partner_token_values(prepared)
        if any(value in shipped_literals for value in values):
            offending.append(prepared.url)
    return offending


def test_login_then_create_does_not_send_a_shipped_partner_credential(operator_module, shipped_literals, tmp_path):
    ifc_file = tmp_path / "model.ifc"
    ifc_file.write_text("ISO-10303-21;", encoding="utf-8")
    issued_user_token = "user-token-issued-for-caller"
    context, login_result, create_result, captured = _run_login_and_create(
        operator_module,
        email="caller@example.com",
        password="caller-password",
        issued_user_token=issued_user_token,
        ifc_file=str(ifc_file),
    )

    if login_result != {"FINISHED"} or create_result != {"FINISHED"}:
        raise AssertionError("Augin operators did not finish")
    if context.scene.AuginProperties.token != issued_user_token:
        raise AssertionError("login did not store the user token returned by user_login")

    login = _by_url(captured, USER_LOGIN_URL)
    if login.method != "POST":
        raise AssertionError("user_login was not a POST")
    if _form_values(login, "email") != ["caller@example.com"]:
        raise AssertionError("user_login did not send the caller email")
    if _form_values(login, "password") != ["caller-password"]:
        raise AssertionError("user_login did not send the caller password")

    new_model = _by_url(captured, NEW_MODEL_URL)
    if new_model.method != "POST":
        raise AssertionError("new_model was not a POST")
    if _form_values(new_model, "user_token") != [issued_user_token]:
        raise AssertionError("new_model did not send the user token stored by login")

    uploaded = _by_url(captured, FILES_UPLOADED_URL)
    if _form_values(uploaded, "user_token") != [issued_user_token]:
        raise AssertionError("files_uploaded did not send the user token stored by login")

    offending = _urls_sending_shipped_partner_credential(captured, shipped_literals)
    if offending:
        raise AssertionError(
            "partner_token in an Augin request is a string literal shipped in the augin package: "
            + ", ".join(offending)
        )


def test_shipped_partner_credential_is_not_shared_across_callers(operator_module, shipped_literals, tmp_path):
    partner_values = []
    for index, issued_user_token in enumerate(("user-token-for-caller-a", "user-token-for-caller-b")):
        ifc_file = tmp_path / f"model-{index}.ifc"
        ifc_file.write_text("ISO-10303-21;", encoding="utf-8")
        _, _, _, captured = _run_login_and_create(
            operator_module,
            email=f"caller-{index}@example.com",
            password=f"caller-password-{index}",
            issued_user_token=issued_user_token,
            ifc_file=str(ifc_file),
        )
        new_model = _by_url(captured, NEW_MODEL_URL)
        if _form_values(new_model, "user_token") != [issued_user_token]:
            raise AssertionError("new_model did not send the caller-specific user token")
        offending = _urls_sending_shipped_partner_credential(captured, shipped_literals)
        if offending:
            raise AssertionError(
                "partner_token in an Augin request is a string literal shipped in the augin package: "
                + ", ".join(offending)
            )
        partner_values.append(_partner_token_values(new_model))

    if partner_values[0] and partner_values[0] == partner_values[1]:
        raise AssertionError("two callers were given the same client-selected partner_token")
