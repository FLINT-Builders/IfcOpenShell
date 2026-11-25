# This file was generated with the assistance of an AI coding tool.
from __future__ import annotations

from typing import Any

import ifcopenshell
import ifcopenshell.util.cost as cost_util

DEFAULT_MAX_DEPTH = 64


def _cost_items_to_dicts(items: list[ifcopenshell.entity_instance], max_depth: int | None) -> list[dict[str, Any]]:
    # Walked with an explicit stack, listing each item once: nesting may form
    # a cycle or be deeper than the recursion limit.
    result: list[dict[str, Any]] = []
    visited: set[int] = set()
    stack = [(item, 1, result) for item in reversed(items)]
    while stack:
        item, depth, siblings = stack.pop()
        if item.id() in visited:
            continue
        visited.add(item.id())

        raw_values = cost_util.get_cost_values(item)
        values = [{"formula": v.get("label", ""), "category": v.get("category")} for v in raw_values]
        nested = cost_util.get_nested_cost_items(item)

        node: dict[str, Any] = {
            "id": item.id(),
            "name": getattr(item, "Name", None),
            "values": values,
            "subitems": [],
        }
        siblings.append(node)

        if max_depth is not None and depth >= max_depth:
            child_count = len([sub for sub in nested if sub.id() not in visited])
            if child_count:
                node["subitems"] = {"truncated": True, "count": child_count}
        else:
            stack.extend((sub, depth + 1, node["subitems"]) for sub in reversed(nested))
    return result


def cost(model: ifcopenshell.file, max_depth: int | None = DEFAULT_MAX_DEPTH) -> list[dict[str, Any]]:
    """List the cost schedules: bills of quantities and their cost items.

    Covers ``IfcCostSchedule`` only — this is the money dimension of the
    model; see ``schedule()`` in this module for the construction programme.
    Each cost item reports its cost ``values`` as ``formula`` label and
    ``category`` pairs, together with its nested ``subitems``. A cost item
    nested more than once in a schedule, including through a cycle, is listed
    only where it is first reached. Returns an empty list when the model has
    no cost schedules.

    :param model: The in-memory IFC model.
    :param max_depth: Levels of cost item nesting to expand, counting root
        items as level 1. Past the cutoff ``subitems`` is replaced by a
        ``{"truncated": True, "count": N}`` marker giving the number of items
        not expanded. Defaults to 64 levels; ``None`` expands to unlimited
        depth.
    """
    result = []
    for cost_schedule in model.by_type("IfcCostSchedule"):
        items = _cost_items_to_dicts(cost_util.get_root_cost_items(cost_schedule), max_depth)
        result.append(
            {
                "id": cost_schedule.id(),
                "name": getattr(cost_schedule, "Name", None),
                "predefined_type": getattr(cost_schedule, "PredefinedType", None),
                "items": items,
            }
        )
    return result
