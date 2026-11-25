# This file was generated with the assistance of an AI coding tool.
"""GlobalId values must not become CSS rules in a drawing stylesheet.

These tests follow the plot highlight path: an IFC file supplies the GlobalId,
a caller highlights that element's step id, and the SVG stylesheet is parsed
back out of the drawing. They fail while a quote in the GlobalId can close the
selector string and introduce another rule.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as ET

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.owner.settings
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import pytest

from ifcquery.plot import plot

MARKER = "https://example.invalid/highlight-css"
# Closes the quoted attribute selector, then adds a stylesheet import.
QUOTE_IMPORT = f'"]{{}}@import url({MARKER});/*'
# Closes the selector and adds a rule whose declaration loads a remote image.
QUOTE_IMAGE = f'"]{{}}*{{background-image:url({MARKER})}}/*'
SAFE_GUID = "0123456789ABCDEFGHIJ_a"

SVG_NS = "http://www.w3.org/2000/svg"


def _stylesheet_urls(css: str) -> list[str]:
    """Return every CSS url token value, including url("...") function arguments.

    String and url scanning follows the CSS tokenizer in tinycss2 1.5.1
    (tokenizer.py): an unescaped newline ends a string, a backslash escapes the
    next character or a hex codepoint, and url( is a url token unless it is
    written as a function with a quoted argument. Characters inside strings and
    comments are not url tokens.
    """
    css = css.replace("\0", "\ufffd").replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    length = len(css)
    urls: list[str] = []
    pos = 0
    # Stack of block terminators. "url" means the current () belongs to url(.
    stack: list[str | None] = []

    def consume_escape(start: int) -> int:
        if start >= length:
            return start
        hex_end = start
        while hex_end < length and hex_end - start < 6 and css[hex_end] in "0123456789abcdefABCDEF":
            hex_end += 1
        if hex_end > start:
            if hex_end < length and css[hex_end] in " \n\t":
                hex_end += 1
            return hex_end
        return start + 1

    def consume_ident(start: int) -> tuple[str, int]:
        chunks: list[str] = []
        cursor = start
        while cursor < length:
            char = css[cursor]
            if char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" or ord(char) > 0x7F:
                cursor += 1
                continue
            if char == "\\" and not css.startswith("\\\n", cursor):
                chunks.append(css[start:cursor])
                cursor = consume_escape(cursor + 1)
                start = cursor
                continue
            break
        chunks.append(css[start:cursor])
        return "".join(chunks), cursor

    def is_ident_start(start: int) -> bool:
        if start >= length:
            return False
        char = css[start]
        if char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_" or ord(char) > 0x7F:
            return True
        if char == "-":
            return is_ident_start(start + 1) or (start + 1 < length and css[start + 1] == "-")
        if char == "\\":
            return not css.startswith("\\\n", start)
        return False

    while pos < length:
        char = css[pos]
        if char in " \n\t":
            pos += 1
            continue
        if css.startswith("/*", pos):
            end = css.find("*/", pos + 2)
            pos = length if end == -1 else end + 2
            continue
        if is_ident_start(pos):
            value, pos = consume_ident(pos)
            if pos < length and css[pos] == "(" and value.lower() == "url":
                pos += 1
                probe = pos
                while probe < length and css[probe] in " \n\t":
                    probe += 1
                if probe >= length or css[probe] not in "\"'":
                    urls.append(_consume_url(css, pos))
                    pos = _url_end(css, pos)
                    continue
                stack.append("url")
                continue
            continue
        if char in "\"'":
            value, pos, closed = _consume_string(css, pos)
            if stack and stack[-1] == "url" and value is not None:
                urls.append(value)
            continue
        if char == "{":
            stack.append("}")
            pos += 1
            continue
        if char == "[":
            stack.append("]")
            pos += 1
            continue
        if char == "(":
            stack.append(")")
            pos += 1
            continue
        if stack and char == stack[-1]:
            stack.pop()
            pos += 1
            continue
        pos += 1
    return urls


def _consume_string(css: str, pos: int) -> tuple[str | None, int, bool]:
    quote = css[pos]
    pos += 1
    chunks: list[str] = []
    start = pos
    length = len(css)
    while pos < length:
        char = css[pos]
        if char == quote:
            chunks.append(css[start:pos])
            return "".join(chunks), pos + 1, True
        if char == "\\":
            chunks.append(css[start:pos])
            pos += 1
            if pos >= length:
                break
            if css[pos] == "\n":
                pos += 1
            elif css[pos] in "0123456789abcdefABCDEF":
                hex_end = pos
                while hex_end < length and hex_end - pos < 6 and css[hex_end] in "0123456789abcdefABCDEF":
                    hex_end += 1
                if hex_end < length and css[hex_end] in " \n\t":
                    hex_end += 1
                chunks.append(chr(int(css[pos:hex_end].rstrip(" \n\t"), 16)))
                pos = hex_end
            else:
                chunks.append(css[pos])
                pos += 1
            start = pos
            continue
        if char == "\n":
            return None, pos, False
        pos += 1
    chunks.append(css[start:pos])
    return "".join(chunks), pos, False


def _consume_url(css: str, pos: int) -> str:
    length = len(css)
    while pos < length and css[pos] in " \n\t":
        pos += 1
    if pos >= length or css[pos] == ")":
        return ""
    chunks: list[str] = []
    start = pos
    while pos < length:
        char = css[pos]
        if char == ")":
            chunks.append(css[start:pos])
            return "".join(chunks)
        if char in " \n\t":
            chunks.append(css[start:pos])
            return "".join(chunks)
        if char == "\\" and not css.startswith("\\\n", pos):
            chunks.append(css[start:pos])
            pos += 1
            if pos < length and css[pos] in "0123456789abcdefABCDEF":
                hex_end = pos
                while hex_end < length and hex_end - pos < 6 and css[hex_end] in "0123456789abcdefABCDEF":
                    hex_end += 1
                if hex_end < length and css[hex_end] in " \n\t":
                    hex_end += 1
                chunks.append(chr(int(css[pos:hex_end].rstrip(" \n\t"), 16)))
                pos = hex_end
            elif pos < length:
                chunks.append(css[pos])
                pos += 1
            start = pos
            continue
        pos += 1
    chunks.append(css[start:pos])
    return "".join(chunks)


def _url_end(css: str, pos: int) -> int:
    length = len(css)
    while pos < length and css[pos] in " \n\t":
        pos += 1
    while pos < length:
        char = css[pos]
        if char == ")":
            return pos + 1
        if char == "\\" and not css.startswith("\\\n", pos):
            pos += 2
            continue
        pos += 1
    return pos


def _style_text(svg: bytes) -> str:
    root = ET.fromstring(svg)
    parts: list[str] = []
    for element in root.iter(f"{{{SVG_NS}}}style"):
        if element.text:
            parts.append(element.text)
        for child in list(element):
            if child.tail:
                parts.append(child.tail)
    return "".join(parts)


def _assert_no_remote_stylesheet(svg: bytes) -> None:
    urls = _stylesheet_urls(_style_text(svg))
    assert MARKER not in urls, urls


def _model_with_unplotted_element(global_id: str) -> tuple[ifcopenshell.file, int]:
    """Return a reopened IFC file and the step id of a wall that has no geometry.

    The highlighted element is not serialized as an SVG attribute. The other
    wall gives the drawing real geometry so plot() still writes an SVG.
    """
    model = ifcopenshell.api.project.create_file()
    ifcopenshell.api.owner.settings.get_user = lambda ifc: (ifc.by_type("IfcPersonAndOrganization") or [None])[0]
    ifcopenshell.api.owner.settings.get_application = lambda ifc: (ifc.by_type("IfcApplication") or [None])[0]
    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="TestProject")
    ifcopenshell.api.unit.assign_unit(model)
    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="TestSite")
    building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name="TestBuilding")
    storey = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuildingStorey", name="Ground Floor")
    storey.Elevation = 0.0
    ifcopenshell.api.aggregate.assign_object(model, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(model, products=[building], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(model, products=[storey], relating_object=building)
    context = ifcopenshell.api.context.add_context(model, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        model, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=context
    )
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Wall001")
    representation = ifcopenshell.api.geometry.add_wall_representation(
        model, context=body, length=5, height=3, thickness=0.2
    )
    ifcopenshell.api.geometry.assign_representation(model, product=wall, representation=representation)
    ifcopenshell.api.spatial.assign_container(model, products=[wall], relating_structure=storey)
    highlighted = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="Ghost")
    ifcopenshell.api.spatial.assign_container(model, products=[highlighted], relating_structure=storey)
    highlighted.GlobalId = global_id

    handle = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
    handle.close()
    try:
        model.write(handle.name)
        reopened = ifcopenshell.open(handle.name)
    finally:
        os.unlink(handle.name)
    ghost = next(element for element in reopened.by_type("IfcWall") if element.Name == "Ghost")
    assert ghost.GlobalId == global_id
    return reopened, ghost.id()


def _plot_stylesheet(global_id: str) -> bytes | None:
    model, element_id = _model_with_unplotted_element(global_id)
    try:
        svg = plot(model, output_format="svg", element_ids=[element_id])
    except ValueError:
        return None
    assert isinstance(svg, bytes)
    return svg


def test_safe_global_id_still_plots() -> None:
    svg = _plot_stylesheet(SAFE_GUID)
    assert svg is not None
    assert b"<svg" in svg
    _assert_no_remote_stylesheet(svg)


def test_quoted_global_id_does_not_import_stylesheet() -> None:
    svg = _plot_stylesheet(QUOTE_IMPORT)
    if svg is None:
        return
    _assert_no_remote_stylesheet(svg)


def test_quoted_global_id_does_not_add_image_rule() -> None:
    svg = _plot_stylesheet(QUOTE_IMAGE)
    if svg is None:
        return
    _assert_no_remote_stylesheet(svg)


def test_cli_plot_does_not_write_injected_stylesheet() -> None:
    model, element_id = _model_with_unplotted_element(QUOTE_IMPORT)
    ifc_handle = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
    ifc_handle.close()
    out_path = ifc_handle.name[:-4] + ".svg"
    model.write(ifc_handle.name)
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ifcquery",
                ifc_handle.name,
                "plot",
                "--out-format",
                "svg",
                "--element",
                str(element_id),
                "-o",
                out_path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            assert not os.path.exists(out_path), result.stderr
            return
        assert os.path.exists(out_path), result.stderr
        with open(out_path, "rb") as drawing:
            _assert_no_remote_stylesheet(drawing.read())
    finally:
        for path in (ifc_handle.name, out_path):
            try:
                os.unlink(path)
            except OSError:
                pass


def test_session_plot_does_not_import_stylesheet() -> None:
    pytest.importorskip("ifcmcp")
    from ifcmcp.core import IfcSession

    model, element_id = _model_with_unplotted_element(QUOTE_IMPORT)
    ifc_handle = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
    ifc_handle.close()
    model.write(ifc_handle.name)
    try:
        session = IfcSession()
        session.ifc_load(ifc_handle.name)
        try:
            svg = session.ifc_plot(element_ids=[element_id], output_format="svg")
        except ValueError:
            return
        assert isinstance(svg, bytes)
        _assert_no_remote_stylesheet(svg)
    finally:
        os.unlink(ifc_handle.name)
