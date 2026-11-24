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

"""Saved .blend files must not contain Augin or cove.tool credentials.

A user can type those credentials into the sandbox panels and log in. These
tests assign the panel properties, save, then run the real login operators and
save again. A second Blender process, which does not register the add-on, must
not be able to read the password or session token back from either file.

The tests fail while those values are stored in scene properties that Blender
writes into the .blend. Clearing the fields only after login does not satisfy
the first save: the password is already on the property the panel edits.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path

# Obvious placeholders. They are not real credentials.
AUGIN_USERNAME = "placeholder-augin-user"
AUGIN_PASSWORD = "placeholder-augin-password"
AUGIN_TOKEN = "placeholder-augin-token"
COVETOOL_USERNAME = "placeholder-covetool-user"
COVETOOL_PASSWORD = "placeholder-covetool-password"
COVETOOL_TOKEN = "placeholder-covetool-token"
CANARY = "placeholder-canary-persists"
SCAN_PREFIX = "CREDENTIAL_SCAN "


def test_login_credentials_are_not_stored_in_blend_file():
    import bpy
    from requests import Response
    from requests.adapters import HTTPAdapter

    failures: list[str] = []
    captured: list[tuple[str, str, str]] = []
    original_send = HTTPAdapter.send

    def block_network(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        # requests.adapters.HTTPAdapter.send is the call that opens a socket.
        # Everything above it (requests.api and Session.request) still runs.
        body = request.body
        body_text = body.decode() if isinstance(body, bytes) else (body or "")
        captured.append((request.method, request.url, body_text))
        response = Response()
        response.status_code = 200
        response.reason = "OK"
        response.url = request.url
        response.encoding = "utf-8"
        url = request.url.rstrip("/")
        if url.endswith("user_login"):
            payload = {"success_feedback": {"success": True}, "token": AUGIN_TOKEN}
        elif url.endswith("get-token"):
            payload = {"token": COVETOOL_TOKEN}
        elif url.endswith("projects"):
            payload = [
                {
                    "name": "placeholder-project",
                    "run_set": ["placeholder-run"],
                    "url": "https://example.invalid/project",
                }
            ]
        else:
            raise AssertionError(f"login path tried to contact an unexpected URL: {request.url}")
        response._content = json.dumps(payload).encode()
        response._content_consumed = True
        return response

    HTTPAdapter.send = block_network
    try:
        _ensure_registered(bpy)
        _set_canary(bpy)
        for props in _groups(bpy, "AuginProperties"):
            props.username = AUGIN_USERNAME
            props.password = AUGIN_PASSWORD
        for props in _groups(bpy, "CoveToolProperties"):
            props.username = COVETOOL_USERNAME
            props.password = COVETOOL_PASSWORD

        with tempfile.TemporaryDirectory(prefix="bonsai-credential-") as directory:
            before_login = str(Path(directory) / "before-login.blend")
            after_login = str(Path(directory) / "after-login.blend")
            before_bytes, before_recovered = _save_and_reload(bpy, before_login)

            augin_result = bpy.ops.bim.augin_login()
            if augin_result != {"FINISHED"}:
                failures.append(f"Augin login operator returned {augin_result!r}")
            covetool_result = bpy.ops.bim.covetool_login()
            if covetool_result != {"FINISHED"}:
                failures.append(f"cove.tool login operator returned {covetool_result!r}")

            augin_bodies = [
                body for method, url, body in captured if method == "POST" and url.rstrip("/").endswith("user_login")
            ]
            covetool_bodies = [
                body for method, url, body in captured if method == "POST" and url.rstrip("/").endswith("get-token")
            ]
            if not any(AUGIN_PASSWORD in body for body in augin_bodies):
                failures.append("Augin login did not submit the password field")
            if not any(COVETOOL_PASSWORD in body for body in covetool_bodies):
                failures.append("cove.tool login did not submit the password field")

            after_bytes, after_recovered = _save_and_reload(bpy, after_login)

        passwords = {
            "Augin password": AUGIN_PASSWORD,
            "cove.tool password": COVETOOL_PASSWORD,
        }
        tokens = {
            "Augin session token": AUGIN_TOKEN,
            "cove.tool session token": COVETOOL_TOKEN,
        }
        for label, saved_bytes, recovered in (
            ("before login", before_bytes, before_recovered),
            ("after login", after_bytes, after_recovered),
        ):
            if CANARY not in recovered or CANARY.encode() not in saved_bytes:
                failures.append(f"canary scene property was not recovered {label}; the save/load check did not run")
            for name, secret in passwords.items():
                if secret in recovered or secret.encode() in saved_bytes:
                    failures.append(f"{name} was recovered from the .blend saved {label}")
        for name, secret in tokens.items():
            if secret in after_recovered or secret.encode() in after_bytes:
                failures.append(f"{name} was recovered from the .blend saved after login")
    finally:
        HTTPAdapter.send = original_send

    assert not failures, "\n".join(failures)


def _groups(bpy, name: str):
    found = []
    for owner in (bpy.context.scene, bpy.context.window_manager):
        if hasattr(owner, name):
            found.append(getattr(owner, name))
    if not found:
        raise AssertionError(f"{name} is not registered on Scene or WindowManager")
    return found


def _set_canary(bpy):
    if not hasattr(bpy.types.Scene, "credential_persistence_canary"):
        bpy.types.Scene.credential_persistence_canary = bpy.props.StringProperty(name="Canary")
    bpy.context.scene.credential_persistence_canary = CANARY


def _already_registered(bpy) -> bool:
    owners = (bpy.types.Scene, bpy.types.WindowManager)
    return all(any(hasattr(owner, name) for owner in owners) for name in ("AuginProperties", "CoveToolProperties"))


def _ensure_registered(bpy):
    if _already_registered(bpy):
        return
    if not hasattr(bpy.types, "BIM_PT_tab_sandbox"):

        class BIM_PT_tab_sandbox(bpy.types.Panel):
            bl_label = "Sandbox"
            bl_idname = "BIM_PT_tab_sandbox"
            bl_space_type = "PROPERTIES"
            bl_region_type = "WINDOW"
            bl_context = "scene"

            def draw(self, context):
                self.layout.label(text="")

        bpy.utils.register_class(BIM_PT_tab_sandbox)

    augin, covetool = _load_modules()
    for module in (augin, covetool):
        for cls in module.classes:
            if not getattr(cls, "is_registered", False):
                bpy.utils.register_class(cls)
        module.register()


def _load_modules():
    if importlib.util.find_spec("ifcopenshell") is not None:
        import bonsai.bim.module.augin as augin
        import bonsai.bim.module.covetool as covetool

        return augin, covetool
    return _load_modules_without_ifcopenshell()


def _namespace(name: str, path: Path | None = None):
    module = types.ModuleType(name)
    if path is not None:
        module.__path__ = [str(path)]
        module.__package__ = name
    sys.modules[name] = module
    parent_name, _, child = name.rpartition(".")
    if parent_name and parent_name in sys.modules:
        setattr(sys.modules[parent_name], child, module)
    return module


def _load_file(fullname: str, path: Path):
    is_package = path.name == "__init__.py"
    spec = importlib.util.spec_from_file_location(
        fullname,
        path,
        submodule_search_locations=[str(path.parent)] if is_package else None,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    parent_name, _, child = fullname.rpartition(".")
    if parent_name and parent_name in sys.modules:
        setattr(sys.modules[parent_name], child, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_modules_without_ifcopenshell():
    """Import the real credential modules when the IfcOpenShell binary is absent.

    ``tool/blender.py`` only needs ``ifcopenshell`` for unrelated helpers.
    ``get_covetool_props`` itself is loaded from that file. The package
    ``bonsai.tool`` is exposed the same way ``tool/__init__.py`` imports it,
    so ``covetool.operator`` calls the real lookup.
    """

    source = Path(__file__).resolve().parents[2] / "bonsai"
    _namespace("bonsai", source)
    _namespace("bonsai.bim", source / "bim")
    _namespace("bonsai.bim.module", source / "bim" / "module")
    _namespace("bonsai.core", source / "core")
    ifcopenshell = _namespace("ifcopenshell")
    util = _namespace("ifcopenshell.util")
    element = types.ModuleType("ifcopenshell.util.element")
    sys.modules["ifcopenshell.util.element"] = element
    util.element = element
    ifcopenshell.entity_instance = type("entity_instance", (), {})
    _namespace("bonsai.tool", source / "tool")
    _load_file("bonsai.core.tool", source / "core" / "tool.py")
    blender = _load_file("bonsai.tool.blender", source / "tool" / "blender.py")
    sys.modules["bonsai.tool"].Blender = blender.Blender
    augin = _load_file("bonsai.bim.module.augin", source / "bim" / "module" / "augin" / "__init__.py")
    covetool = _load_file("bonsai.bim.module.covetool", source / "bim" / "module" / "covetool" / "__init__.py")
    return augin, covetool


def _script_args(argv: list[str]) -> list[str]:
    if "--" in argv:
        return argv[argv.index("--") + 1 :]
    if argv and argv[0].endswith(".py"):
        return argv[1:]
    return argv[1:]


def _save_and_reload(bpy, blend_path: str) -> tuple[bytes, list[str]]:
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    return Path(blend_path).read_bytes(), _reload_strings(blend_path)


def _reload_strings(blend_path: str) -> list[str]:
    import bpy

    command = [
        bpy.app.binary_path,
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(Path(__file__).resolve()),
        "--",
        "reload",
        blend_path,
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    scan_lines = [line for line in completed.stdout.splitlines() if line.startswith(SCAN_PREFIX)]
    if completed.returncode != 0 or not scan_lines:
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise AssertionError(f"could not read the saved .blend in a second Blender process:\n{detail}")
    payload = json.loads(scan_lines[-1][len(SCAN_PREFIX) :])
    return payload["strings"]


def _reload_main(blend_path: str):
    import bpy

    bpy.ops.wm.open_mainfile(filepath=blend_path)
    found: list[str] = []
    for attribute in dir(bpy.data):
        collection = getattr(bpy.data, attribute)
        if not hasattr(collection, "__iter__"):
            continue
        try:
            items = list(collection)
        except Exception:
            continue
        for item in items:
            if hasattr(item, "keys"):
                _flatten_id_properties(item, found)
    print(SCAN_PREFIX + json.dumps({"strings": found}), flush=True)


def _flatten_id_properties(idblock, found: list[str]):
    def walk(value):
        if isinstance(value, str):
            found.append(value)
            return
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            for nested in to_dict().values():
                walk(nested)
            return
        if isinstance(value, dict):
            for nested in value.values():
                walk(nested)
            return
        if isinstance(value, (list, tuple)):
            for nested in value:
                walk(nested)

    for key in list(idblock.keys()):
        walk(idblock[key])


def main():
    args = _script_args(sys.argv)
    if args[:1] == ["reload"]:
        _reload_main(args[1])
        return
    try:
        test_login_credentials_are_not_stored_in_blend_file()
    except AssertionError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
