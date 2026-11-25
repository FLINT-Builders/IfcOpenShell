# This file was generated with the assistance of an AI coding tool.
# IfcTester - IDS based model auditing
#
# This file is part of IfcTester.
#
# IfcTester is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Parsers that feed attacker-supplied XML to libexpat must stay fast.

libexpat before 2.8.1 scans every already-stored default attribute when it
defines the next one (``defineAttribute``). A document of a few megabytes whose
internal DTD gives one element tens of thousands of defaulted attributes makes
that scan quadratic and stalls the caller. 2.8.1 looks the name up in a hash
table instead.

These tests fail on the libexpat 2.6.4 and 2.7.1 builds pinned in ``pixi.lock``
and pass on libexpat 2.8.1 or newer. They are expected to fail until that
upgrade is what the interpreter is actually linked against.

Not covered here, because importing them needs Blender: ``sheeter`` and
``svgwriter`` in ``bonsai.bim.module.drawing``, and
``bonsai.tool.drawing.Drawing.convert_svg_to_dxf``. They call
``xml.etree.ElementTree`` on SVG the same way the tests below do. Paths that
parse with lxml (libxml2) are a different library and are not this bug.
``#IMPLIED`` / ``#REQUIRED`` attributes that are not IDs never enter the
quadratic scan; attributes with a default value do, which is what the fixture
uses.
"""

from __future__ import annotations

import pyexpat
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
for _relative in ("src/ifctester", "src/ifc4d", "src/bcf", "src/ifcopenshell-python"):
    _path = str(REPO_ROOT / _relative)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from bcf.v2.bcfxml import BcfXml
from bcf.v2.model.version import Version
from bcf.xml_parser import XmlParserSerializer
from ifc4d.msp2ifc import MSP2Ifc
from ifc4d.p62ifc import P62Ifc
from xsdata.formats.dataclass.parsers.handlers.native import XmlEventHandler

from ifctester.ids import IdsXmlValidationError, from_string
from ifctester.ids import open as ids_open

# 80_000 defaulted attributes is about 1.3 MiB. On libexpat 2.6.4 and 2.7.1 one
# parse takes about a second, and four times fewer attributes takes about a
# sixteenth of that. On 2.8.1 the same document parses in a few hundredths of a
# second, including the IDS schema load inside ``from_string``.
ATTRIBUTE_COUNT = 80_000
MAX_SECONDS = 0.5


def _expat_version() -> tuple[int, int, int]:
    numbers = pyexpat.EXPAT_VERSION.split("_", 1)[-1]
    major, minor, micro = numbers.split(".")
    return int(major), int(minor), int(micro)


def _crafted_xml(count: int = ATTRIBUTE_COUNT) -> str:
    declarations = " ".join(f'a{index} CDATA "x"' for index in range(count))
    return f"<!DOCTYPE r [<!ELEMENT r EMPTY><!ATTLIST r {declarations}>]><r/>"


@pytest.fixture(scope="module")
def crafted_xml() -> str:
    return _crafted_xml()


def _run_bounded(action):
    started = time.perf_counter()
    caught = None
    result = None
    try:
        result = action()
    except Exception as exc:  # the assertion below still applies when parsing raises afterwards
        caught = exc
    elapsed = time.perf_counter() - started
    assert elapsed < MAX_SECONDS, (
        f"parsing {ATTRIBUTE_COUNT} defaulted attributes took {elapsed:.3f}s "
        f"with {pyexpat.EXPAT_VERSION}; libexpat 2.8.1 finishes in under {MAX_SECONDS:.1f}s"
    )
    return result, caught


def test_linked_libexpat_has_attribute_collision_fix():
    """The 2.8.1 hash-table lookup is the fix. 2.8.0 still scans the list."""
    assert _expat_version() >= (2, 8, 1), pyexpat.EXPAT_VERSION


def test_ids_from_string_parses_default_attributes_quickly(crafted_xml):
    _result, caught = _run_bounded(lambda: from_string(crafted_xml))
    assert isinstance(caught, IdsXmlValidationError)


def test_ids_open_parses_default_attributes_quickly(crafted_xml, tmp_path):
    ids_path = tmp_path / "crafted.ids"
    ids_path.write_text(crafted_xml, encoding="utf-8")
    _result, caught = _run_bounded(lambda: ids_open(str(ids_path)))
    assert isinstance(caught, IdsXmlValidationError)


def test_msp2ifc_parses_default_attributes_quickly(crafted_xml, tmp_path):
    xml_path = tmp_path / "programme.xml"
    xml_path.write_text(crafted_xml, encoding="utf-8")
    converter = MSP2Ifc()
    converter.xml = str(xml_path)
    _result, caught = _run_bounded(converter.parse_xml)
    assert caught is None


def test_p62ifc_parses_default_attributes_quickly(crafted_xml, tmp_path):
    xml_path = tmp_path / "programme.xml"
    xml_path.write_text(crafted_xml, encoding="utf-8")
    converter = P62Ifc()
    converter.xml = str(xml_path)
    _result, caught = _run_bounded(converter.parse_xml)
    assert isinstance(caught, AttributeError)
    assert "findtext" in str(caught)


def test_bcf_v2_extension_schema_parses_default_attributes_quickly(crafted_xml):
    bcf = BcfXml()
    # ``extensions`` feeds ``extension_schema`` to ElementTree. A BCF zip stores
    # those bytes under the name ``project.bcfp`` points at.
    bcf._extension_schema = crafted_xml.encode()
    result, caught = _run_bounded(lambda: bcf.extensions)
    assert caught is None
    assert result is not None


def test_bcf_stdlib_xml_parser_parses_default_attributes_quickly(crafted_xml):
    """``XmlParserSerializer`` uses this handler when lxml is not installed.

    ``build_xml_parser`` takes xsdata's default handler. That default is
    ``XmlEventHandler`` (ElementTree / expat) unless importing lxml succeeds.
    The published ``bcf-client`` package does not depend on lxml.
    """
    serializer = XmlParserSerializer()
    serializer.parser.handler = XmlEventHandler
    result, caught = _run_bounded(lambda: serializer.parse(crafted_xml.encode(), Version))
    assert caught is None
    assert result is not None


def test_elementtree_itself_is_the_parser_under_test(crafted_xml):
    """The product calls above all end in ElementTree, which calls ``XML_Parse``."""
    result, caught = _run_bounded(lambda: ET.fromstring(crafted_xml))
    assert caught is None
    assert result.tag == "r"
