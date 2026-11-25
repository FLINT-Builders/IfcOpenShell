# This file was generated with the assistance of an AI coding tool.
"""Raster-size limits for the ifcmcp plot entry points.

IfcSession.ifc_plot and the ifc_plot MCP tool forward png_width and png_height
to ifcquery.plot. They must raise ValueError, with the message containing
"8192" or "67108864", before a bitmap is allocated when either dimension is
above 8192. The tool must not create output_path when it refuses.
"""

from __future__ import annotations

import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.owner.settings
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import pytest

from ifcmcp.core import IfcSession
from ifcmcp.server import build_server

LIMIT_MESSAGE = r"8192|67108864"


def _make_model():
    model = ifcopenshell.api.project.create_file()
    ifcopenshell.api.owner.settings.get_user = lambda ifc: (ifc.by_type("IfcPersonAndOrganization") or [None])[0]
    ifcopenshell.api.owner.settings.get_application = lambda ifc: (ifc.by_type("IfcApplication") or [None])[0]
    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="P")
    ifcopenshell.api.unit.assign_unit(model)
    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="S")
    building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name="B")
    ifcopenshell.api.aggregate.assign_object(model, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(model, products=[building], relating_object=site)
    storey = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuildingStorey", name="L0")
    storey.Elevation = 0.0
    ifcopenshell.api.aggregate.assign_object(model, products=[storey], relating_object=building)
    context = ifcopenshell.api.context.add_context(model, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        model,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=context,
    )
    wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name="W0")
    representation = ifcopenshell.api.geometry.add_wall_representation(
        model, context=body, length=5, height=3, thickness=0.2
    )
    ifcopenshell.api.geometry.assign_representation(model, product=wall, representation=representation)
    ifcopenshell.api.spatial.assign_container(model, products=[wall], relating_structure=storey)
    return model


def test_session_rejects_dimension_above_max():
    session = IfcSession()
    session.model = _make_model()
    with pytest.raises(ValueError, match=LIMIT_MESSAGE):
        session.ifc_plot(png_width=8193, png_height=128)


def test_server_tool_rejects_dimension_above_max_without_writing(tmp_path):
    server = build_server()
    tools = {tool.name: tool.fn for tool in server._tool_manager.list_tools()}
    model_path = tmp_path / "model.ifc"
    _make_model().write(str(model_path))
    tools["ifc_load"](str(model_path))
    output = tmp_path / "plot.png"
    with pytest.raises(ValueError, match=LIMIT_MESSAGE):
        tools["ifc_plot"](
            selector="",
            element_ids=None,
            view="floorplan",
            width_mm=297.0,
            height_mm=420.0,
            scale=0.01,
            png_width=8193,
            png_height=128,
            output_path=str(output),
        )
    assert not output.exists()
