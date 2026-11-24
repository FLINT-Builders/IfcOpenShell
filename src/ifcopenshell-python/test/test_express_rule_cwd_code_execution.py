# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2021 Thomas Krijnen <thomas@aecgeeks.com>
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

"""Working-directory EXPRESS schemas must not execute planted Python modules.

The IFC header names the schema. For a schema with no bundled rules, validation
and derived-attribute lookup currently find ``<schema>.exp`` in the process
working directory and then run a ``.py`` file chosen from that same directory.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCHEMA_NAME = "EVILSCHEMA"

# Present so validate() can walk the file far enough to reach rule execution.
# IfcRoot is required to open a file; IfcApplication is looked up by name.
_SUPPORT_ENTITIES = """
ENTITY IfcRoot;
  GlobalId : STRING;
END_ENTITY;
ENTITY IfcApplication;
  ApplicationFullName : STRING;
  Version : STRING;
  ApplicationIdentifier : STRING;
END_ENTITY;
"""


def _header(schema: str, data: str) -> str:
    return textwrap.dedent(
        f"""\
        ISO-10303-21;
        HEADER;
        FILE_DESCRIPTION(('ViewDefinition[DesignTransferView]'),'2;1');
        FILE_NAME('test.ifc','2024-08-30T12:34:53+05:00',('author'),('organization'),'IfcOpenShell','test','');
        FILE_SCHEMA(('{schema}'));
        ENDSEC;
        DATA;
        {data}
        ENDSEC;
        END-ISO-10303-21;
        """
    )


def _plant(directory: Path, filename: str, marker: Path) -> bytes:
    """Write a module whose import or exec creates ``marker`` and return its bytes."""
    source = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
    path = directory / filename
    path.write_text(source)
    return path.read_bytes()


def _run(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_not_executed(marker: Path, module_path: Path, original: bytes) -> None:
    assert not marker.exists(), "Python from the working directory was executed"
    assert module_path.read_bytes() == original, "working-directory schema module was replaced or removed"


def test_validate_rules_does_not_execute_cwd_schema_module(tmp_path: Path) -> None:
    """``python -m ifcopenshell.validate --rules`` must not exec a planted schema module.

    The schema name is taken from the IFC header. The planted module uses the
    on-disk stem of ``<schema>.exp``, which is how ``rule_executor.run`` opens it.
    """
    pytest.importorskip("_pytest.assertion")
    exp_name = "evilschema.exp"
    module_name = "evilschema.py"
    (tmp_path / exp_name).write_text(
        textwrap.dedent(
            f"""\
            SCHEMA {SCHEMA_NAME};
            {_SUPPORT_ENTITIES}
            END_SCHEMA;
            """
        )
    )
    marker = tmp_path / "marker.txt"
    original = _plant(tmp_path, module_name, marker)
    (tmp_path / "model.ifc").write_text(_header(SCHEMA_NAME, "#1=IFCROOT('1iBd2lkrX61vZxF9AnXLa0');"))

    _run(tmp_path, ["-m", "ifcopenshell.validate", "--rules", "model.ifc"])

    _assert_not_executed(marker, tmp_path / module_name, original)


def test_rule_executor_run_does_not_execute_cwd_schema_module(tmp_path: Path) -> None:
    """``rule_executor.run`` must not exec a pre-existing module beside the schema."""
    pytest.importorskip("_pytest.assertion")
    exp_name = "evilschema.exp"
    module_name = "evilschema.py"
    (tmp_path / exp_name).write_text(
        textwrap.dedent(
            f"""\
            SCHEMA {SCHEMA_NAME};
            {_SUPPORT_ENTITIES}
            END_SCHEMA;
            """
        )
    )
    marker = tmp_path / "marker.txt"
    original = _plant(tmp_path, module_name, marker)
    (tmp_path / "model.ifc").write_text(_header(SCHEMA_NAME, "#1=IFCROOT('1iBd2lkrX61vZxF9AnXLa0');"))
    driver = tmp_path / "driver.py"
    driver.write_text(
        textwrap.dedent(
            """\
            import logging

            import ifcopenshell
            import ifcopenshell.express
            import ifcopenshell.express.rule_executor

            ifcopenshell.register_schema(ifcopenshell.express.parse("evilschema.exp"))
            model = ifcopenshell.open("model.ifc")
            logger = logging.getLogger("cwd-rule-executor")
            logger.addHandler(logging.NullHandler())
            ifcopenshell.express.rule_executor.run(model, logger)
            """
        )
    )

    _run(tmp_path, ["-m", "driver"])

    _assert_not_executed(marker, tmp_path / module_name, original)


def test_validate_does_not_import_cwd_module_for_attribute_lookup(tmp_path: Path) -> None:
    """Plain validation must not import a cwd module while reading attributes.

    ``validate`` calls ``getattr(inst, "GlobalId", ...)``. On an entity with no
    such forward attribute, ``entity_instance.__getattr__`` imports a module
    named after the schema.
    """
    module_name = f"{SCHEMA_NAME}.py"
    (tmp_path / f"{SCHEMA_NAME}.exp").write_text(
        textwrap.dedent(
            f"""\
            SCHEMA {SCHEMA_NAME};
            ENTITY IfcRoot;
              Name : STRING;
            END_ENTITY;
            ENTITY IfcApplication;
              ApplicationFullName : STRING;
              Version : STRING;
              ApplicationIdentifier : STRING;
            END_ENTITY;
            END_SCHEMA;
            """
        )
    )
    marker = tmp_path / "marker.txt"
    original = _plant(tmp_path, module_name, marker)
    (tmp_path / "model.ifc").write_text(_header(SCHEMA_NAME, "#1=IFCROOT('hello');"))

    _run(tmp_path, ["-m", "ifcopenshell.validate", "model.ifc"])

    _assert_not_executed(marker, tmp_path / module_name, original)


def test_derived_attribute_does_not_import_cwd_schema_module(tmp_path: Path) -> None:
    """Reading a derived attribute must not import ``<schema>`` from the working directory."""
    module_name = f"{SCHEMA_NAME}.py"
    (tmp_path / f"{SCHEMA_NAME}.exp").write_text(
        textwrap.dedent(
            f"""\
            SCHEMA {SCHEMA_NAME};
            ENTITY Parent;
              Name : STRING;
            END_ENTITY;
            ENTITY Child SUBTYPE OF (Parent);
              GlobalId : STRING;
             DERIVE
              SELF\\Parent.Name : STRING := 'x';
            END_ENTITY;
            {_SUPPORT_ENTITIES}
            END_SCHEMA;
            """
        )
    )
    marker = tmp_path / "marker.txt"
    original = _plant(tmp_path, module_name, marker)
    (tmp_path / "model.ifc").write_text(_header(SCHEMA_NAME, "#1=CHILD('1iBd2lkrX61vZxF9AnXLa0');"))
    driver = tmp_path / "driver.py"
    driver.write_text(
        textwrap.dedent(
            """\
            import os
            import sys

            import ifcopenshell
            import ifcopenshell.express

            cwd_on_path = "" in sys.path or "." in sys.path or os.getcwd() in sys.path
            if not cwd_on_path:
                sys.exit("cwd is not on sys.path")
            ifcopenshell.register_schema(ifcopenshell.express.parse("EVILSCHEMA.exp"))
            model = ifcopenshell.open("model.ifc")
            inst = next(iter(model))
            if inst.get_attribute_category("Name") != 3:
                sys.exit("Name was not a derived attribute")
            try:
                inst.Name
            except Exception:
                pass
            """
        )
    )

    completed = _run(tmp_path, ["-m", "driver"])
    assert completed.returncode == 0, completed.stderr

    _assert_not_executed(marker, tmp_path / module_name, original)
