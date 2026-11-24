# This file was generated with the assistance of an AI coding tool.
"""Stand-in for Pyodide 0.29.4 ``runPythonAsync``.

The web worker calls ``pyodide.runPythonAsync(source)``. In Pyodide 0.29.4 that
is ``API.pyodide_code.eval_code_async`` (``src/js/api.ts``), which is
``CodeRunner`` in ``src/py/_pyodide/_base.py``:

* ``textwrap.dedent`` the source
* compile with ``ast.PyCF_ALLOW_TOP_LEVEL_AWAIT``
* if the last statement is an expression, that value is the result
* ``eval`` the code object in the persistent globals

``api`` is a recording stub so ``from api import ...`` resolves without running
the real IfcOpenShell lookup. Injected statements still run in this process.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import textwrap
import types
from typing import Any

CALLS: list[dict[str, Any]] = []


def _record(name: str, args: tuple[Any, ...]) -> list[str] | dict[str, str]:
    CALLS.append({"fn": name, "args": list(args)})
    if name == "get_all_data_types":
        return {}
    if name == "get_applicable_psets":
        return ["Pset_WallCommon"]
    return []


def _install_api() -> None:
    module = types.ModuleType("api")

    def get_predefined_types_for_entity(schema_name, entity_name):
        return _record("get_predefined_types_for_entity", (schema_name, entity_name))

    def get_all_entity_classes(schema_name):
        return _record("get_all_entity_classes", (schema_name,))

    def get_all_data_types(schema_name):
        return _record("get_all_data_types", (schema_name,))

    def get_entity_attributes(schema_name, entity_name):
        return _record("get_entity_attributes", (schema_name, entity_name))

    def get_applicable_psets(schema_name, entity_name, predefined_type=""):
        return _record("get_applicable_psets", (schema_name, entity_name, predefined_type))

    module.get_predefined_types_for_entity = get_predefined_types_for_entity
    module.get_all_entity_classes = get_all_entity_classes
    module.get_all_data_types = get_all_data_types
    module.get_entity_attributes = get_entity_attributes
    module.get_applicable_psets = get_applicable_psets
    sys.modules["api"] = module


class _Result(Exception):
    def __init__(self, value: Any) -> None:
        self.value = value


def eval_code(source: str, globals_dict: dict[str, Any] | None = None) -> Any:
    """Run ``source`` the way Pyodide 0.29.4 ``eval_code_async`` does."""

    source = textwrap.dedent(source)
    flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
    module = compile(source, "<pyodide>", "exec", flags | ast.PyCF_ONLY_AST)
    if module.body and isinstance(module.body[-1], ast.Expr):
        module.body[-1] = ast.Raise(
            exc=ast.Call(
                func=ast.Name(id="_Result", ctx=ast.Load()),
                args=[module.body[-1].value],
                keywords=[],
            ),
            cause=None,
        )
        ast.fix_missing_locations(module)
    code = compile(module, "<pyodide>", "exec", flags)
    glob = dict(globals_dict or {})
    glob["_Result"] = _Result
    try:
        # Same eval() CodeRunner.run_async uses on the compiled code object.
        eval(code, glob, glob)
    except _Result as result:
        return result.value
    return None


def _self_check() -> None:
    assert eval_code("1 + 1") == 2
    assert eval_code("\n        x = 1\n        x + 1\n") == 2


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        _self_check()
        return
    request = json.load(sys.stdin)
    _install_api()
    marker = request.get("marker") or ""
    error = None
    value: Any = None
    try:
        value = eval_code(request["source"], request.get("globals") or {})
    except Exception as exc:  # the injected source is allowed to fail after its side effect
        error = f"{type(exc).__name__}: {exc}"
    if not isinstance(value, (str, int, float, bool, list, dict, type(None))):
        value = str(value)
    json.dump(
        {
            "value": value,
            "calls": CALLS,
            "error": error,
            "markerWritten": bool(marker) and os.path.exists(marker),
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
