# This file was generated with the assistance of an AI coding tool.
from __future__ import annotations

from typing import Any

import ifcopenshell
import ifcopenshell.util.sequence as seq

MAX_DEPTH = 100


def _task_to_dict(task: ifcopenshell.entity_instance, max_depth: int, depth: int, expanded: set[int]) -> dict[str, Any]:
    task_time = task.TaskTime
    start = None
    finish = None
    if task_time:
        start = task_time.ScheduleStart
        finish = task_time.ScheduleFinish

    outputs = []
    for product in seq.get_task_outputs(task):
        outputs.append({"id": product.id(), "type": product.is_a(), "name": getattr(product, "Name", None)})

    nested_tasks = seq.get_nested_tasks(task)
    if task.id() in expanded:
        subtasks = []
    elif depth >= max_depth:
        subtasks = {"truncated": True, "count": len(nested_tasks)} if nested_tasks else []
    else:
        expanded.add(task.id())
        subtasks = [_task_to_dict(sub, max_depth, depth + 1, expanded) for sub in nested_tasks]

    return {
        "id": task.id(),
        "name": getattr(task, "Name", None),
        "start": start,
        "finish": finish,
        "is_milestone": bool(task.IsMilestone) if hasattr(task, "IsMilestone") else False,
        "outputs": outputs,
        "subtasks": subtasks,
    }


def schedule(model: ifcopenshell.file, max_depth: int | None = None) -> list[dict[str, Any]]:
    """List the construction programme: work schedules and their task trees.

    Covers ``IfcWorkSchedule`` only — this is the time dimension of the
    model; see ``cost()`` in this module for the money dimension. Each
    schedule lists its tasks recursively, and each task carries its scheduled
    ``start`` and ``finish``, an ``is_milestone`` flag, the products it
    ``outputs`` and its ``subtasks``. Returns an empty list when the model has
    no work schedules.

    :param model: The in-memory IFC model.
    :param max_depth: Levels of subtask nesting to expand, counting root tasks
        as level 1. Past the cutoff ``subtasks`` is replaced by a
        ``{"truncated": True, "count": N}`` marker giving the number of tasks
        not expanded. ``None`` (default) expands up to ``MAX_DEPTH`` (100)
        levels, and larger values are capped at it. A task's subtasks are
        expanded only the first time it is reached; a task reached again, as
        in cyclic nesting, is listed with empty ``subtasks``.
    """
    limit = MAX_DEPTH if max_depth is None else min(max_depth, MAX_DEPTH)
    expanded: set[int] = set()
    result = []
    for work_schedule in model.by_type("IfcWorkSchedule"):
        tasks = [_task_to_dict(t, limit, 1, expanded) for t in seq.get_root_tasks(work_schedule)]
        result.append(
            {
                "id": work_schedule.id(),
                "name": getattr(work_schedule, "Name", None),
                "predefined_type": getattr(work_schedule, "PredefinedType", None),
                "tasks": tasks,
            }
        )
    return result
