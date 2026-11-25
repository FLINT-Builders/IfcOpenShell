# This file was generated with the assistance of an AI coding tool.
# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2026 IfcOpenShell contributors
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

"""Metric reference walks must finish when InnerReference forms a cycle.

An IFC file can store an IfcReference whose InnerReference points at itself
or at an earlier reference in the same chain. Opening that file and drawing
the Resources panel walks every resource metric. These tests open such a
file and run each caller of that walk. They fail while the walk recurses
without a visited set and a depth bound.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.sequence

REPO_IFC = Path(__file__).resolve().parents[2]
REPO_SRC = REPO_IFC.parent
BONSAI_ROOT = REPO_SRC / "bonsai"
REPO_CONSTRAINT = REPO_IFC / "ifcopenshell" / "util" / "constraint.py"


def _load_repo_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Test the helpers in this checkout, not a previously imported copy.
constraint = _load_repo_module("ifcopenshell.util.constraint", REPO_CONSTRAINT)
import ifcopenshell.util as _ifcopenshell_util

_ifcopenshell_util.constraint = constraint
calculate_resource_usage_module = _load_repo_module(
    "calculate_resource_usage_under_test",
    REPO_IFC / "ifcopenshell" / "api" / "resource" / "calculate_resource_usage.py",
)
calculate_resource_work_module = _load_repo_module(
    "calculate_resource_work_under_test",
    REPO_IFC / "ifcopenshell" / "api" / "resource" / "calculate_resource_work.py",
)
edit_resource_time_module = _load_repo_module(
    "edit_resource_time_under_test",
    REPO_IFC / "ifcopenshell" / "api" / "resource" / "edit_resource_time.py",
)
edit_task_time_module = _load_repo_module(
    "edit_task_time_under_test",
    REPO_IFC / "ifcopenshell" / "api" / "sequence" / "edit_task_time.py",
)

calculate_resource_usage = calculate_resource_usage_module.calculate_resource_usage
calculate_resource_work = calculate_resource_work_module.calculate_resource_work
edit_resource_time = edit_resource_time_module.edit_resource_time


def _bonsai_parts():
    """Load the resource panel data path and the resource tool wrappers.

    Blender is not importable here. Modules that only dispatch into
    ifcopenshell stay real. Modules whose import exists to reach bpy are
    replaced with the attributes this path actually reads.
    """
    if str(BONSAI_ROOT) not in sys.path:
        sys.path.insert(0, str(BONSAI_ROOT))
    import bonsai.core.tool

    _ = bonsai.core.tool

    bpy = types.ModuleType("bpy")
    bpy.context = types.SimpleNamespace(active_object=None)
    sys.modules["bpy"] = bpy

    class _Ifc:
        model = None

        @classmethod
        def get(cls):
            return cls.model

        @staticmethod
        def get_entity(obj):
            return None

    class _ResourceApi:
        @staticmethod
        def get_resource_props():
            return types.SimpleNamespace(active_resource_id=0)

    tool_module = types.ModuleType("bonsai.tool")
    tool_module.Ifc = _Ifc
    tool_module.Resource = _ResourceApi
    sys.modules["bonsai.tool"] = tool_module

    bim = types.ModuleType("bonsai.bim")
    bim.__path__ = []
    sys.modules["bonsai.bim"] = bim
    sys.modules["bonsai.bim.helper"] = types.ModuleType("bonsai.bim.helper")

    data_path = BONSAI_ROOT / "bonsai" / "bim" / "module" / "resource" / "data.py"
    data = _load_repo_module("bonsai_resource_data_under_test", data_path)
    tool_path = BONSAI_ROOT / "bonsai" / "tool" / "resource.py"
    tool_resource = _load_repo_module("bonsai_tool_resource_under_test", tool_path)
    core_path = BONSAI_ROOT / "bonsai" / "core" / "resource.py"
    core_resource = _load_repo_module("bonsai_core_resource_under_test", core_path)
    return data.ResourceData, tool_resource.Resource, core_resource.remove_usage_constraint, _Ifc


ResourceData, ResourceTool, remove_usage_constraint, IfcHolder = _bonsai_parts()


def _reopen(model: ifcopenshell.file) -> ifcopenshell.file:
    handle, path = tempfile.mkstemp(suffix=".ifc")
    os.close(handle)
    try:
        model.write(path)
        return ifcopenshell.open(path)
    finally:
        os.unlink(path)


def _chain(model: ifcopenshell.file, identifiers: list[str | None], cycle_to: int | None = None):
    references = []
    for identifier in identifiers:
        reference = model.create_entity("IfcReference", AttributeIdentifier=identifier)
        if references:
            references[-1].InnerReference = reference
        references.append(reference)
    if cycle_to is not None:
        references[-1].InnerReference = references[cycle_to]
    return references


def _resource_metric(
    model: ifcopenshell.file,
    identifiers: list[str | None],
    cycle_to: int | None = None,
    *,
    grade: str = "HARD",
    benchmark: str = "EQUALTO",
    name: str = "Material",
):
    references = _chain(model, identifiers, cycle_to)
    metric = model.create_entity(
        "IfcMetric",
        Name="Metric",
        ConstraintGrade=grade,
        Benchmark=benchmark,
        ReferencePath=references[0],
    )
    objective = model.create_entity(
        "IfcObjective",
        Name="Objective",
        ConstraintGrade=grade,
        ObjectiveQualifier="PARAMETER",
        BenchmarkValues=[metric],
    )
    resource = model.create_entity(
        "IfcConstructionMaterialResource",
        GlobalId=ifcopenshell.guid.new(),
        Name=name,
    )
    model.create_entity(
        "IfcRelAssociatesConstraint",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[resource],
        RelatingConstraint=objective,
    )
    return resource, objective, metric, references


def _opened_resource(identifiers, cycle_to, **kwargs):
    model = ifcopenshell.file(schema="IFC4")
    _resource_metric(model, identifiers, cycle_to, **kwargs)
    opened = _reopen(model)
    resource = opened.by_type("IfcConstructionMaterialResource")[-1]
    metric = opened.by_type("IfcMetric")[-1]
    return opened, resource, metric


def test_repo_constraint_module_is_the_one_under_test():
    assert Path(constraint.__file__).resolve() == REPO_CONSTRAINT.resolve()


def test_self_inner_reference_returns_its_attribute_once():
    _model, _resource, metric = _opened_resource(["Usage"], 0)
    reference = metric.ReferencePath
    assert reference.InnerReference.id() == reference.id()
    assert constraint.get_metric_reference(metric, is_deep=False) == "Usage"
    assert constraint.get_metric_reference(metric) == "Usage"


def test_two_reference_cycle_returns_each_attribute_once():
    _model, _resource, metric = _opened_resource(["Usage", "ScheduleUsage"], 0)
    reference = metric.ReferencePath
    assert reference.InnerReference.InnerReference.id() == reference.id()
    assert constraint.get_metric_reference(metric) == "Usage.ScheduleUsage"


def test_cycle_back_to_a_middle_reference_stops_at_the_repeat():
    _model, _resource, metric = _opened_resource(["Usage", "ScheduleUsage", "Extra"], 1)
    assert constraint.get_metric_reference(metric) == "Usage.ScheduleUsage.Extra"


def test_cycle_with_no_attribute_identifier_returns_no_path():
    model = ifcopenshell.file(schema="IFC4")
    reference = _chain(model, [None], 0)[0]
    metric = model.create_entity(
        "IfcMetric",
        Name="Metric",
        ConstraintGrade="HARD",
        Benchmark="EQUALTO",
        ReferencePath=reference,
    )
    opened = _reopen(model)
    opened_metric = opened.by_id(metric.id())
    assert opened_metric.ReferencePath.InnerReference.id() == opened_metric.ReferencePath.id()
    assert constraint.get_metric_reference(opened_metric) is None


def test_inner_reference_without_an_identifier_keeps_the_outer_attribute():
    _model, _resource, metric = _opened_resource(["Usage", None], 0)
    assert constraint.get_metric_reference(metric) == "Usage"


def test_acyclic_reference_path_is_unchanged():
    _model, _resource, metric = _opened_resource(["Usage", "ScheduleUsage", "ScheduleWork", "Status"], None)
    assert constraint.get_metric_reference(metric) == "Usage.ScheduleUsage.ScheduleWork.Status"


def test_reference_chain_longer_than_the_stack_returns_a_prefix():
    depth = sys.getrecursionlimit() + 100
    identifiers = [f"L{index}" for index in range(depth)]
    model = ifcopenshell.file(schema="IFC4")
    reference = _chain(model, identifiers, None)[0]
    metric = model.create_entity(
        "IfcMetric",
        Name="Metric",
        ConstraintGrade="SOFT",
        Benchmark="EQUALTO",
        ReferencePath=reference,
    )
    opened = _reopen(model)
    result = constraint.get_metric_reference(opened.by_id(metric.id()))
    parts = result.split(".")
    assert parts == identifiers[: len(parts)]
    assert 4 <= len(parts) <= depth


def test_metric_constraint_queries_stop_on_a_cycle():
    _model, resource, metric = _opened_resource(["Usage", "ScheduleUsage"], 0)
    assert constraint.get_metric_constraints(resource, "Usage.ScheduleUsage") == [metric]
    assert constraint.get_metric_constraints(resource, "Usage.ScheduleWork") is None
    assert constraint.is_attribute_locked(resource, "Usage.ScheduleUsage") is True
    assert constraint.is_attribute_locked(resource, "Usage.ScheduleWork") is False

    _model, soft_resource, _metric = _opened_resource(
        ["Usage", "ScheduleUsage"], 0, grade="SOFT", benchmark="EQUALTO", name="Soft"
    )
    assert constraint.is_attribute_locked(soft_resource, "Usage.ScheduleUsage") is False


def test_edit_resource_time_skips_a_locked_cyclic_attribute():
    model, resource, _metric = _opened_resource(["Usage", "ScheduleUsage"], 0)
    usage = model.create_entity("IfcResourceTime", ScheduleWork="PT8H")
    resource.Usage = usage
    edit_resource_time(model, resource_time=usage, attributes={"ScheduleUsage": 2.5, "ScheduleContour": "Flat"})
    assert usage.ScheduleUsage is None
    assert usage.ScheduleContour == "Flat"


def test_calculate_resource_usage_stops_before_writing_a_locked_value():
    model, resource, _metric = _opened_resource(["Usage", "ScheduleUsage"], 0)
    usage = model.create_entity("IfcResourceTime", ScheduleWork="PT8H")
    resource.Usage = usage
    task = model.create_entity(
        "IfcTask",
        GlobalId=ifcopenshell.guid.new(),
        Name="Task",
        IsMilestone=False,
        TaskTime=model.create_entity("IfcTaskTime", DurationType="WORKTIME", ScheduleDuration="P1D"),
    )
    model.create_entity(
        "IfcRelAssignsToProcess",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[resource],
        RelatingProcess=task,
    )
    opened = _reopen(model)
    opened_resource = opened.by_type("IfcConstructionMaterialResource")[0]
    calculate_resource_usage(opened, resource=opened_resource)
    assert opened_resource.Usage.ScheduleUsage is None


def test_calculate_resource_work_stops_on_a_cyclic_lock():
    model, resource, _metric = _opened_resource(["Usage", "ScheduleWork"], 0)
    usage = model.create_entity("IfcResourceTime", ScheduleWork="PT8H")
    resource.Usage = usage
    opened = _reopen(model)
    opened_resource = opened.by_type("IfcConstructionMaterialResource")[0]
    assert constraint.is_attribute_locked(opened_resource, "Usage.ScheduleWork") is True
    calculate_resource_work(opened, resource=opened_resource)
    assert opened_resource.Usage.ScheduleWork == "PT8H"


def test_task_resource_calculation_reaches_the_cyclic_metric():
    model, resource, _metric = _opened_resource(["Usage", "ScheduleWork"], 0)
    task = model.create_entity("IfcTask", GlobalId=ifcopenshell.guid.new(), Name="Task", IsMilestone=False)
    model.create_entity(
        "IfcRelAssignsToProcess",
        GlobalId=ifcopenshell.guid.new(),
        RelatedObjects=[resource],
        RelatingProcess=task,
    )
    opened = _reopen(model)
    opened_task = opened.by_type("IfcTask")[0]
    opened_resource = opened.by_type("IfcConstructionMaterialResource")[0]
    assert opened_resource in ifcopenshell.util.sequence.get_task_resources(opened_task, is_recursive=False)
    import ifcopenshell.api.resource as resource_api

    original_calculate_usage = resource_api.calculate_resource_usage
    resource_api.calculate_resource_usage = calculate_resource_usage
    try:
        usecase = edit_task_time_module.Usecase()
        usecase.file = opened
        usecase.task = opened_task
        usecase.handle_resource_calculation()
    finally:
        resource_api.calculate_resource_usage = original_calculate_usage


def test_remove_usage_constraint_walks_the_cyclic_metric():
    model, resource, metric = _opened_resource(["Usage", "ScheduleUsage"], 0)
    objective = model.by_type("IfcObjective")[0]
    calls = []

    class _IfcApi:
        def run(self, command, **kwargs):
            calls.append((command, kwargs))

    remove_usage_constraint(_IfcApi(), ResourceTool, resource, "Usage.ScheduleUsage")
    assert calls == [
        ("constraint.remove_metric", {"metric": metric}),
        ("constraint.unassign_constraint", {"products": [resource], "constraint": objective}),
        ("constraint.remove_constraint", {"constraint": objective}),
    ]
    assert model.by_id(metric.id()).is_a("IfcMetric")


def test_resource_tool_wrappers_walk_the_cyclic_metric():
    _model, resource, metric = _opened_resource(["Usage", "ScheduleUsage"], 0)
    assert ResourceTool.get_metric_reference(metric, is_deep=True) == "Usage.ScheduleUsage"
    assert ResourceTool.has_metric_constraint(resource, "Usage.ScheduleUsage") is True
    assert ResourceTool.is_attribute_locked(resource, "Usage.ScheduleUsage") is True
    assert ResourceTool.is_attribute_locked(resource, "Usage.ScheduleWork") is False


def test_resources_panel_load_walks_every_resource_metric():
    model = ifcopenshell.file(schema="IFC4")
    _resource_metric(model, ["Usage"], 0, name="Cyclic")
    _resource_metric(model, ["Usage", "ScheduleUsage"], None, name="Acyclic")
    opened = _reopen(model)
    cyclic = next(
        resource for resource in opened.by_type("IfcConstructionMaterialResource") if resource.Name == "Cyclic"
    )
    acyclic = next(
        resource for resource in opened.by_type("IfcConstructionMaterialResource") if resource.Name == "Acyclic"
    )
    assert cyclic.HasAssociations[0].RelatingConstraint.BenchmarkValues[0].ReferencePath.InnerReference.id() == (
        cyclic.HasAssociations[0].RelatingConstraint.BenchmarkValues[0].ReferencePath.id()
    )

    IfcHolder.model = opened
    ResourceData.is_loaded = False
    ResourceData.data = {}
    ResourceData.load()

    assert ResourceData.is_loaded is True
    assert ResourceData.data["total_resources"] == 2
    cyclic_metrics = ResourceData.data["resources"][cyclic.id()]["Benchmarks"][0]["metrics"]
    acyclic_metrics = ResourceData.data["resources"][acyclic.id()]["Benchmarks"][0]["metrics"]
    assert cyclic_metrics[0]["reference"] == "Usage"
    assert cyclic_metrics[0]["ConstraintGrade"] == "HARD"
    assert acyclic_metrics[0]["reference"] == "Usage.ScheduleUsage"
