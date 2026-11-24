# This file was generated with the assistance of an AI coding tool.
"""Regression tests for quadratic MVD header key-value detection.

``parse_semicolon_separated_kv`` gates on an unanchored ``re.search`` of
``\\w+\\s*:\\s*[^:]+``. A bracketed Option or other keyword with no colon makes
that search try every starting offset, so the work grows with the square of the
word. These tests drive that text through ``ifcopenshell.open`` and the
``file.mvd`` properties that call the helper.

They fail while that search is in place. A linear check (and the same results
for real ``key: value`` text) makes them pass.
"""

import os
import sqlite3
import tempfile
import time

import ifcopenshell
from ifcopenshell.util.mvd_info import parse_mvd, parse_semicolon_separated_kv

# 24_000 colon-free word characters. On CPython 3.12 this takes about four
# seconds in the quadratic search, and a linear scan of a longer colon-bearing
# option finishes in well under a millisecond.
COLON_FREE_CHARS = 24_000
MAX_SECONDS = 0.2


def _write_ifc(description_entries):
    quoted = ", ".join("'" + entry.replace("'", "''") + "'" for entry in description_entries)
    text = (
        "ISO-10303-21;\n"
        "HEADER;\n"
        f"FILE_DESCRIPTION(({quoted}),'2;1');\n"
        "FILE_NAME('x.ifc','2025-01-01T00:00:00',('a'),('b'),'c','d','e');\n"
        "FILE_SCHEMA(('IFC4'));\n"
        "ENDSEC;\n"
        "DATA;\n"
        "ENDSEC;\n"
        "END-ISO-10303-21;\n"
    )
    fd, path = tempfile.mkstemp(suffix=".ifc")
    os.write(fd, text.encode())
    os.close(fd)
    return path


def _open_ifc(description_entries):
    path = _write_ifc(description_entries)
    try:
        return path, ifcopenshell.open(path)
    except Exception:
        os.remove(path)
        raise


def _close(path):
    os.remove(path)


def _payload(n=COLON_FREE_CHARS):
    return "A" * n


def _option_entries(payload):
    return [f"ViewDefinition [CoordinationView]", f"Option [{payload}]"]


def _timed(func):
    started = time.perf_counter()
    value = func()
    return time.perf_counter() - started, value


def _assert_within_bound(elapsed, what):
    assert elapsed < MAX_SECONDS, (
        f"{what} took {elapsed:.3f}s; a linear scan of this header finishes in well under {MAX_SECONDS}s"
    )


class TestColonFreeOptionThroughOpen:
    def test_options_property_is_linear_and_keeps_the_text(self):
        payload = _payload()
        path, f = _open_ifc(_option_entries(payload))
        try:
            assert payload in " ".join(f.header.file_description.description)
            elapsed, value = _timed(lambda: f.mvd.options)
        finally:
            _close(path)
        _assert_within_bound(elapsed, "file.mvd.options")
        assert value == payload

    def test_doubling_the_word_does_not_quadruple_the_work(self):
        short_n = COLON_FREE_CHARS // 2
        path_s, small = _open_ifc(_option_entries(_payload(short_n)))
        try:
            elapsed_short, _ = _timed(lambda: small.mvd.options)
        finally:
            _close(path_s)
        path_l, large = _open_ifc(_option_entries(_payload()))
        try:
            elapsed_long, _ = _timed(lambda: large.mvd.options)
        finally:
            _close(path_l)
        # The vulnerable search is about four times slower when the word length
        # doubles. Skip the ratio only when both runs are already in the noise.
        if elapsed_short > 0.05:
            assert elapsed_long < elapsed_short * 3, (
                f"doubling the colon-free option took {elapsed_long:.3f}s after {elapsed_short:.3f}s"
            )

    def test_keywords_property_is_linear(self):
        payload = _payload()
        path, f = _open_ifc(_option_entries(payload))
        try:
            elapsed, value = _timed(lambda: f.mvd.keywords)
        finally:
            _close(path)
        _assert_within_bound(elapsed, "file.mvd.keywords")
        assert value == {"view_definitions", "options"}

    def test_view_definitions_property_is_linear(self):
        path, f = _open_ifc(_option_entries(_payload()))
        try:
            elapsed, value = _timed(lambda: f.mvd.view_definitions)
        finally:
            _close(path)
        _assert_within_bound(elapsed, "file.mvd.view_definitions")
        assert list(value) == ["CoordinationView"]

    def test_comments_property_is_linear(self):
        path, f = _open_ifc(_option_entries(_payload()) + ["Comment [Note]"])
        try:
            elapsed, value = _timed(lambda: f.mvd.comments)
        finally:
            _close(path)
        _assert_within_bound(elapsed, "file.mvd.comments")
        assert list(value) == ["Note"]

    def test_exchange_requirements_property_is_linear(self):
        entries = _option_entries(_payload()) + ["ExchangeRequirement [Any]"]
        path, f = _open_ifc(entries)
        try:
            elapsed, value = _timed(lambda: f.mvd.exchange_requirements)
        finally:
            _close(path)
        _assert_within_bound(elapsed, "file.mvd.exchange_requirements")
        assert value == "Any"


class TestColonFreeDynamicKeyword:
    def test_remark_property_is_linear(self):
        payload = _payload()
        entries = ["ViewDefinition [CoordinationView]", f"Remark [{payload}]"]
        path, f = _open_ifc(entries)
        try:
            assert payload in " ".join(f.header.file_description.description)
            started = time.perf_counter()
            try:
                f.mvd.remark
                raised = None
            except AttributeError as exc:
                raised = exc
            elapsed = time.perf_counter() - started
        finally:
            _close(path)
        _assert_within_bound(elapsed, "file.mvd.remark")
        # A colon-free dynamic keyword parses to None, and DictionaryHandler
        # then fails on that None. The failure has to happen after a linear
        # check, not after the quadratic search.
        assert raised is not None

    def test_parse_mvd_dynamic_keyword_is_linear(self):
        payload = _payload()
        elapsed, parsed = _timed(lambda: parse_mvd([f"Remark [{payload}]"]))
        _assert_within_bound(elapsed, "parse_mvd Remark")
        assert parsed.keywords == {"remark"}
        assert parsed.remark is None


class TestParseSemicolonSeparatedKv:
    def test_colon_free_word_returns_none_in_linear_time(self):
        payload = _payload()
        elapsed, value = _timed(lambda: parse_semicolon_separated_kv(payload))
        _assert_within_bound(elapsed, "parse_semicolon_separated_kv")
        assert value is None

    def test_several_colon_free_pieces_are_linear(self):
        payload = _payload()
        text = f"{payload};{payload}"
        elapsed, value = _timed(lambda: parse_semicolon_separated_kv(text))
        _assert_within_bound(elapsed, "parse_semicolon_separated_kv with a semicolon")
        assert value is None

    def test_real_pairs_still_parse(self):
        assert parse_semicolon_separated_kv("Alpha: One; Beta: Two, Three") == {
            "Alpha": "One",
            "Beta": ["Two", "Three"],
        }
        assert parse_semicolon_separated_kv("Key : Value") == {"Key": "Value"}

    def test_long_value_after_a_colon_stays_fast(self):
        payload = _payload()
        text = f"Name: {payload}"
        elapsed, value = _timed(lambda: parse_semicolon_separated_kv(text))
        _assert_within_bound(elapsed, "parse_semicolon_separated_kv with a colon")
        assert value == {"Name": payload}


class TestColonBearingOptionStaysFast:
    def test_open_and_read_long_option_value(self):
        payload = _payload()
        path, f = _open_ifc(["ViewDefinition [CoordinationView]", f"Option [Name: {payload}]"])
        try:
            elapsed, value = _timed(lambda: f.mvd.options)
        finally:
            _close(path)
        _assert_within_bound(elapsed, "file.mvd.options with a colon")
        assert value["Name"] == payload


class TestSqliteMvd:
    def test_sqlite_option_is_linear(self):
        payload = _payload()
        fd, path = tempfile.mkstemp(suffix=".ifcsqlite")
        os.close(fd)
        os.remove(path)
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE metadata (preprocessor text, schema text, mvd text)")
        conn.execute(
            "INSERT INTO metadata VALUES (?, ?, ?)",
            ("IfcOpenShell-1.0.0", "IFC4", f"ViewDefinition [CoordinationView] Option [{payload}]"),
        )
        conn.execute("CREATE TABLE id_map (ifc_id integer PRIMARY KEY NOT NULL UNIQUE, ifc_class text)")
        conn.commit()
        conn.close()
        try:
            f = ifcopenshell.open(path)
            assert payload in f.header.file_description.description[0]
            elapsed, value = _timed(lambda: f.mvd.options)
        finally:
            os.remove(path)
        _assert_within_bound(elapsed, "sqlite file.mvd.options")
        assert value == payload
