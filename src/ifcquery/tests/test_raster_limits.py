# This file was generated with the assistance of an AI coding tool.
"""Raster-size limits for ifcquery.plot.

These tests are the specification for the missing cap. They fail while
plot() will rasterise whatever size the caller asks for.

plot() must raise ValueError before CairoSVG or Pillow allocates a bitmap
when either of these is true:

- png_width or png_height is greater than MAX_RASTER_DIMENSION (8192)
- png_width * png_height * (number of top-level SVG drawing groups) is
  greater than MAX_RASTER_PIXELS (8192 * 8192)

The ValueError message must contain the limit that was exceeded, either
"8192" or "67108864". Requests at or under both limits must still return a
PNG, including a multi-storey model whose image height is png_height times
the number of storey groups. A rejected plot must not create an output file.

The subprocess cases set RLIMIT_AS tight enough for drawing and for one
in-limit raster, and too tight for the bitmap the uncapped code allocates.
A check that still allocates, then raises, fails those cases.
"""

from __future__ import annotations

import os
import re
import resource
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr
from io import BytesIO, StringIO
from pathlib import Path

import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.owner.settings
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import pytest
from PIL import Image

from ifcquery.plot import plot

MAX_RASTER_DIMENSION = 8192
MAX_RASTER_PIXELS = 8192 * 8192
LIMIT_MESSAGE = r"8192|67108864"
# Headroom above VmSize. Large enough for SVG generation (and, where noted,
# one in-limit raster) and smaller than the bitmap the uncapped path allocates.
_HEADROOM_HUGE_SINGLE = 96 * 1024 * 1024
_HEADROOM_MANY_STOREYS = 220 * 1024 * 1024
_HEADROOM_TWO_MAX_RASTERS = 380 * 1024 * 1024


def _make_model(storeys: int):
    """IFC4 model with one wall on each of `storeys` building storeys."""
    model = ifcopenshell.api.project.create_file()
    ifcopenshell.api.owner.settings.get_user = lambda ifc: (ifc.by_type("IfcPersonAndOrganization") or [None])[0]
    ifcopenshell.api.owner.settings.get_application = lambda ifc: (ifc.by_type("IfcApplication") or [None])[0]

    project = ifcopenshell.api.root.create_entity(model, ifc_class="IfcProject", name="P")
    ifcopenshell.api.unit.assign_unit(model)
    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="S")
    building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name="B")
    ifcopenshell.api.aggregate.assign_object(model, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(model, products=[building], relating_object=site)

    context = ifcopenshell.api.context.add_context(model, context_type="Model")
    body = ifcopenshell.api.context.add_context(
        model,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=context,
    )
    for index in range(storeys):
        storey = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuildingStorey", name=f"L{index}")
        storey.Elevation = float(index * 4)
        ifcopenshell.api.aggregate.assign_object(model, products=[storey], relating_object=building)
        wall = ifcopenshell.api.root.create_entity(model, ifc_class="IfcWall", name=f"W{index}")
        representation = ifcopenshell.api.geometry.add_wall_representation(
            model, context=body, length=5, height=3, thickness=0.2
        )
        ifcopenshell.api.geometry.assign_representation(model, product=wall, representation=representation)
        ifcopenshell.api.spatial.assign_container(model, products=[wall], relating_structure=storey)
    return model


def _vmsize_bytes() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmSize:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("VmSize is not available")


def _cap_address_space(headroom: int) -> None:
    limit = _vmsize_bytes() + headroom
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def _assert_rejected(exc: BaseException) -> None:
    if not isinstance(exc, ValueError) or not re.search(LIMIT_MESSAGE, str(exc)):
        raise SystemExit(f"expected ValueError mentioning the raster limit, got {type(exc).__name__}: {exc}")


def _child(mode: str) -> int:
    if mode == "huge-single":
        model = _make_model(1)
        _cap_address_space(_HEADROOM_HUGE_SINGLE)
        try:
            plot(model, output_format="png", png_width=20_000, png_height=20_000)
        except BaseException as exc:
            _assert_rejected(exc)
            return 0
        raise SystemExit("plot returned a bitmap for a 20000x20000 request")

    if mode == "many-storeys":
        model = _make_model(65)
        _cap_address_space(_HEADROOM_MANY_STOREYS)
        try:
            plot(model, output_format="png")
        except BaseException as exc:
            _assert_rejected(exc)
            return 0
        raise SystemExit("plot returned a bitmap for 65 storeys at 1024x1024")

    if mode == "two-max":
        model = _make_model(2)
        _cap_address_space(_HEADROOM_TWO_MAX_RASTERS)
        try:
            plot(model, output_format="png", png_width=MAX_RASTER_DIMENSION, png_height=MAX_RASTER_DIMENSION)
        except BaseException as exc:
            _assert_rejected(exc)
            return 0
        raise SystemExit("plot returned a bitmap for 2 storeys at 8192x8192")

    if mode == "cli-many-storeys":
        model = _make_model(65)
        handle = tempfile.NamedTemporaryFile(suffix=".ifc", delete=False)
        ifc_path = handle.name
        handle.close()
        out_path = ifc_path + ".png"
        model.write(ifc_path)
        _cap_address_space(_HEADROOM_MANY_STOREYS)
        from ifcquery.__main__ import main

        argv = sys.argv
        sys.argv = ["ifcquery", ifc_path, "plot", "-o", out_path]
        stderr = StringIO()
        try:
            with redirect_stderr(stderr):
                try:
                    main()
                except SystemExit as exc:
                    code = exc.code
                else:
                    code = None
        finally:
            sys.argv = argv
        if os.path.exists(out_path):
            raise SystemExit(f"cli created {out_path} before refusing the raster")
        text = stderr.getvalue()
        if code != 1 or "Traceback" in text or not re.search(LIMIT_MESSAGE, text):
            raise SystemExit(f"cli did not refuse with the raster limit (exit {code!r}): {text}")
        return 0

    raise SystemExit(f"unknown mode {mode}")


def _run_child(mode: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src = Path(__file__).resolve().parents[2]
    roots = [src / "ifcquery", src / "ifcmcp", src / "ifcedit"]
    env["PYTHONPATH"] = (
        os.pathsep.join(str(path) for path in roots if path.is_dir()) + os.pathsep + env.get("PYTHONPATH", "")
    )
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), mode],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _require_child_rejected(mode: str) -> None:
    result = _run_child(mode)
    assert result.returncode == 0, (
        f"{mode} did not reject the raster before allocating\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


class TestRasterLimits:
    def test_dimension_at_max_is_allowed(self):
        image = Image.open(BytesIO(plot(_make_model(1), output_format="png", png_width=8192, png_height=128)))
        assert image.size == (8192, 128)

    def test_pixel_budget_at_max_is_allowed(self):
        image = Image.open(BytesIO(plot(_make_model(1), output_format="png", png_width=8192, png_height=8192)))
        assert image.size == (8192, 8192)

    def test_dimension_above_max_is_rejected(self):
        with pytest.raises(ValueError, match=LIMIT_MESSAGE):
            plot(_make_model(1), output_format="png", png_width=8193, png_height=128)

    def test_base64_dimension_above_max_is_rejected(self):
        with pytest.raises(ValueError, match=LIMIT_MESSAGE):
            plot(_make_model(1), output_format="base64", png_width=8193, png_height=128)

    def test_multigigabyte_request_is_rejected_without_allocating(self):
        _require_child_rejected("huge-single")

    def test_storey_groups_within_budget_stack_vertically(self):
        image = Image.open(BytesIO(plot(_make_model(3), output_format="png", png_width=128, png_height=96)))
        assert image.size == (128, 96 * 3)

    def test_two_max_rasters_are_rejected_without_allocating(self):
        _require_child_rejected("two-max")

    def test_default_size_many_storeys_rejected_without_allocating(self):
        _require_child_rejected("many-storeys")

    def test_cli_many_storeys_rejected_without_writing(self):
        result = _run_child("cli-many-storeys")
        assert result.returncode == 0, (
            f"cli plot did not refuse before writing a raster\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_raster_limits.py <mode>")
    raise SystemExit(_child(sys.argv[1]))
