# This file was generated with the assistance of an AI coding tool.

"""The Salome script Ifc2CA writes must treat the IFC path as data.

create_mesh renders templates/salome/scriptSalome.py with the MED and JSON
paths. Those paths include the IFC file's own name. A name containing a
double quote (or a newline that closes that quote) has to survive as the
string value of med_path and json_path when the generated script is run.
"""

from __future__ import annotations

import ast
import os
import sys
import types
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid

from ifc2ca import Ifc2CA


def _statement(sentinel: Path) -> str:
    """Python that writes sentinel, with no slash characters in the source.

    A slash would be a directory separator in the IFC file name, so the
    absolute path is built at runtime from chr(47).
    """
    parts = [part for part in sentinel.parts if part != os.sep]
    joined = ",".join(repr(part) for part in parts)
    return "__import__('pathlib').Path(chr(47)+chr(47).join([" + joined + "])).write_text('executed')"


def _write_structural_ifc(path: Path) -> None:
    ifc = ifcopenshell.file(schema="IFC4")
    ifc.create_entity(
        "IfcStructuralAnalysisModel",
        GlobalId=ifcopenshell.guid.new(),
        Name="Analysis",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    ifc.write(str(path))


def _quoted_name(sentinel: Path) -> str:
    return 'model";' + _statement(sentinel) + ';".ifc'


def _newline_name(sentinel: Path) -> str:
    return 'model"\n' + _statement(sentinel) + '\n".ifc'


def _run_script(script_path: Path) -> dict:
    """Run the script Ifc2CA wrote.

    Salome is imported above the path assignments and is not installed here.
    The stand-ins only satisfy those imports. They do not read the IFC path.
    """
    saved = {name: sys.modules.get(name) for name in ("salome", "salome_notebook", "salome_version")}
    for name in saved:
        sys.modules[name] = types.ModuleType(name)
    sys.modules["salome_version"].getVersion = lambda: ["9", "0", "0"]
    source = script_path.read_text()
    ast.parse(source)
    namespace: dict = {"__name__": "ifc2ca_generated_salome_script"}
    try:
        exec(compile(source, str(script_path), "exec"), namespace)
    except Exception:
        # After the path lines, the script calls into Salome.
        pass
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return namespace


def _assert_paths_are_data(engine: Ifc2CA, result: dict, sentinel: Path) -> None:
    scripts = sorted(engine.folder_path.glob("ScriptSalome_*.py"))
    assert scripts, "create_mesh did not write the Salome script"
    expected_med = str((engine.folder_path / f"{result['name']}.med").resolve())
    expected_json = str((engine.folder_path / f"Model_{result['model_id']}.json").resolve())
    for script in scripts:
        namespace = _run_script(script)
        assert not sentinel.is_file(), "generated Salome script executed the IFC file name"
        assert namespace["med_path"] == expected_med
        assert namespace["json_path"] == expected_json


def test_quoted_ifc_filename_stays_inside_salome_string(tmp_path):
    sentinel = tmp_path / "quote_sentinel"
    ifc_path = tmp_path / _quoted_name(sentinel)
    _write_structural_ifc(ifc_path)

    engine = Ifc2CA(ifc_path)
    result = engine.create_mesh(engine.get_models()[0], {"mesh_size": 0.1})

    _assert_paths_are_data(engine, result, sentinel)


def test_quoted_ifc_filename_stays_data_when_salome_is_launched(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # The product invokes the literal command name "python".
    (bindir / "python").symlink_to(sys.executable)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    salome = tmp_path / "salome_noop.py"
    salome.write_text("raise SystemExit(0)\n")

    sentinel = tmp_path / "launch_sentinel"
    ifc_path = tmp_path / _quoted_name(sentinel)
    _write_structural_ifc(ifc_path)
    engine = Ifc2CA(ifc_path)
    engine.salome_path = salome
    result = engine.create_mesh(engine.get_models()[0], {"mesh_size": 0.1})

    _assert_paths_are_data(engine, result, sentinel)


def test_newline_in_ifc_filename_stays_inside_salome_string(tmp_path):
    sentinel = tmp_path / "newline_sentinel"
    ifc_path = tmp_path / _newline_name(sentinel)
    _write_structural_ifc(ifc_path)

    engine = Ifc2CA(ifc_path)
    result = engine.create_mesh(engine.get_models()[0], {"mesh_size": 0.1})

    _assert_paths_are_data(engine, result, sentinel)


def test_ordinary_ifc_filename_is_preserved(tmp_path):
    ifc_path = tmp_path / "frame.ifc"
    _write_structural_ifc(ifc_path)
    engine = Ifc2CA(ifc_path)
    result = engine.create_mesh(engine.get_models()[0], {"mesh_size": 0.5})
    script = result["script_path"]
    namespace = _run_script(script)
    assert namespace["med_path"] == str((engine.folder_path / f"{result['name']}.med").resolve())
    assert namespace["json_path"] == str((engine.folder_path / f"Model_{result['model_id']}.json").resolve())
    assert namespace["mesh_size"] == 0.5
