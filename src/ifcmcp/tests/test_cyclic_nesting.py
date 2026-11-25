# This file was generated with the assistance of an AI coding tool.
"""MCP schedule and cost tools must not recurse forever on a cyclic nest.

The session, its dispatcher, the embedded tool caller, and the FastMCP
tools all forward to the same expansion. These tests fail while that
expansion follows a cycle or uses an unlimited default depth.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from ifcmcp.core import IfcSession
from ifcmcp.embedded import call_tool
from ifcmcp.embedded import session as embedded_session
from ifcmcp.server import build_server

_HELPERS = Path(__file__).resolve().parents[2] / "ifcquery" / "tests" / "test_cyclic_nesting.py"
_spec = importlib.util.spec_from_file_location("ifcquery_cyclic_nesting_helpers", _HELPERS)
assert _spec is not None and _spec.loader is not None
_models = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_models)
assert_cycle_leaf = _models.assert_cycle_leaf
assert_no_reexpansion = _models.assert_no_reexpansion
assert_truncated = _models.assert_truncated
chain_cost = _models.chain_cost
chain_schedule = _models.chain_schedule
cyclic_cost = _models.cyclic_cost
cyclic_schedule = _models.cyclic_schedule


@pytest.fixture
def fresh_embedded_session():
    embedded_session.ifc_reset()
    yield embedded_session
    embedded_session.ifc_reset()


def _open_schedule(tmp_path, model):
    path = tmp_path / "model.ifc"
    model.write(str(path))
    return str(path)


class TestSessionSchedule:
    def test_unlimited_depth_treats_repeat_as_leaf(self, tmp_path):
        path = _open_schedule(tmp_path, cyclic_schedule("IFC4", ["A", "B", "A"]))
        session = IfcSession()
        session.ifc_load(path)
        result = session.ifc_schedule(max_depth=None)
        assert_cycle_leaf(result[0]["tasks"], "subtasks", ["A", "B", "A"])

    def test_large_depth_treats_repeat_as_leaf(self, tmp_path):
        path = _open_schedule(tmp_path, cyclic_schedule("IFC4", ["A", "B", "C", "A"]))
        session = IfcSession()
        session.ifc_load(path)
        result = session.ifc_schedule(max_depth=10000)
        assert_cycle_leaf(result[0]["tasks"], "subtasks", ["A", "B", "C", "A"])

    def test_default_depth_truncates_long_chain(self, tmp_path):
        length = sys.getrecursionlimit() + 30
        path = _open_schedule(tmp_path, chain_schedule("IFC4", length))
        session = IfcSession()
        session.ifc_load(path)
        result = session.ifc_schedule()
        assert_truncated(result[0]["tasks"], "subtasks", length)
        assert_no_reexpansion(result[0]["tasks"], "subtasks")


class TestSessionCost:
    def test_unlimited_depth_treats_repeat_as_leaf(self, tmp_path):
        path = _open_schedule(tmp_path, cyclic_cost("IFC4", ["A", "B", "A"]))
        session = IfcSession()
        session.ifc_load(path)
        result = session.ifc_cost(max_depth=None)
        assert_cycle_leaf(result[0]["items"], "subitems", ["A", "B", "A"])

    def test_default_depth_truncates_long_chain(self, tmp_path):
        length = sys.getrecursionlimit() + 30
        path = _open_schedule(tmp_path, chain_cost("IFC4", length))
        session = IfcSession()
        session.ifc_load(path)
        result = session.ifc_cost()
        assert_truncated(result[0]["items"], "subitems", length)


class TestDispatchAndEmbedded:
    def test_dispatch_schedule_unlimited_is_a_leaf(self, tmp_path):
        path = _open_schedule(tmp_path, cyclic_schedule("IFC4", ["A", "A"]))
        session = IfcSession()
        session.ifc_load(path)
        result = session.dispatch("ifc_schedule", {"max_depth": None})
        assert_cycle_leaf(result[0]["tasks"], "subtasks", ["A", "A"])

    def test_dispatch_schedule_default_truncates_long_chain(self, tmp_path):
        length = sys.getrecursionlimit() + 30
        path = _open_schedule(tmp_path, chain_schedule("IFC4", length))
        session = IfcSession()
        session.ifc_load(path)
        result = session.dispatch("ifc_schedule", {})
        assert_truncated(result[0]["tasks"], "subtasks", length)

    def test_embedded_call_tool_schedule_is_a_leaf(self, tmp_path, fresh_embedded_session):
        path = _open_schedule(tmp_path, cyclic_schedule("IFC4", ["A", "B", "A"]))
        fresh_embedded_session.ifc_load(path)
        result = call_tool("ifc_schedule", {"max_depth": None})
        assert result["ok"] is True, result
        assert_cycle_leaf(result["data"][0]["tasks"], "subtasks", ["A", "B", "A"])

    def test_embedded_call_tool_default_truncates_long_chain(self, tmp_path, fresh_embedded_session):
        length = sys.getrecursionlimit() + 30
        path = _open_schedule(tmp_path, chain_schedule("IFC4", length))
        fresh_embedded_session.ifc_load(path)
        result = call_tool("ifc_schedule", None)
        assert result["ok"] is True, result
        assert_truncated(result["data"][0]["tasks"], "subtasks", length)


class TestFastMcpTools:
    def test_ifc_schedule_large_depth_treats_repeat_as_leaf(self, tmp_path):
        path = _open_schedule(tmp_path, cyclic_schedule("IFC4", ["A", "B", "A"]))

        async def run():
            server = build_server()
            await server.call_tool("ifc_load", {"path": path})
            _blocks, structured = await server.call_tool("ifc_schedule", {"max_depth": 10000})
            return structured["result"]

        result = asyncio.run(run())
        assert_cycle_leaf(result[0]["tasks"], "subtasks", ["A", "B", "A"])

    def test_ifc_schedule_default_truncates_long_chain(self, tmp_path):
        length = sys.getrecursionlimit() + 30
        path = _open_schedule(tmp_path, chain_schedule("IFC4", length))

        async def run():
            server = build_server()
            await server.call_tool("ifc_load", {"path": path})
            _blocks, structured = await server.call_tool("ifc_schedule", {})
            return structured["result"]

        result = asyncio.run(run())
        assert_truncated(result[0]["tasks"], "subtasks", length)

    def test_ifc_cost_default_truncates_long_chain(self, tmp_path):
        length = sys.getrecursionlimit() + 30
        path = _open_schedule(tmp_path, chain_cost("IFC4", length))

        async def run():
            server = build_server()
            await server.call_tool("ifc_load", {"path": path})
            _blocks, structured = await server.call_tool("ifc_cost", {})
            return structured["result"]

        result = asyncio.run(run())
        assert_truncated(result[0]["items"], "subitems", length)
