# This file was generated with the assistance of an AI coding tool.
from __future__ import annotations

from typing import Any

import ifcopenshell
import ifcopenshell.util.cost as cost_util

MAX_DEPTH = 100


def _cost_item_to_dict(
    item: ifcopenshell.entity_instance, max_depth: int, depth: int, expanded: set[int]
) -> dict[str, Any]:
    raw_values = cost_util.get_cost_values(item)
    values = [{"formula": v.get("label", ""), "category": v.get("category")} for v in raw_values]

    nested_items = cost_util.get_nested_cost_items(item)
    if item.id() in expanded:
        subitems = []
    elif depth >= max_depth:
        subitems = {"truncated": True, "count": len(nested_items)} if nested_items else []
    else:
        expanded.add(item.id())
        subitems = [_cost_item_to_dict(sub, max_depth, depth + 1, expanded) for sub in nested_items]

    return {
        "id": item.id(),
        "name": getattr(item, "Name", None),
        "values": values,
        "subitems": subitems,
    }


def cost(model: ifcopenshell.file, max_depth: int | None = None) -> list[dict[str, Any]]:
    """List the cost schedules: bills of quantities and their cost items.

    Covers ``IfcCostSchedule`` only — this is the money dimension of the
    model; see ``schedule()`` in this module for the construction programme.
    Each cost item reports its cost ``values`` as ``formula`` label and
    ``category`` pairs, together with its nested ``subitems``. Returns an
    empty list when the model has no cost schedules.

    :param model: The in-memory IFC model.
    :param max_depth: Levels of cost item nesting to expand, counting root
        items as level 1. Past the cutoff ``subitems`` is replaced by a
        ``{"truncated": True, "count": N}`` marker giving the number of items
        not expanded. ``None`` (default) expands up to ``MAX_DEPTH`` (100)
        levels, and larger values are capped at it. An item's subitems are
        expanded only the first time it is reached; an item reached again, as
        in cyclic nesting, is listed with empty ``subitems``.
    """
    limit = MAX_DEPTH if max_depth is None else min(max_depth, MAX_DEPTH)
    expanded: set[int] = set()
    result = []
    for cost_schedule in model.by_type("IfcCostSchedule"):
        items = [_cost_item_to_dict(i, limit, 1, expanded) for i in cost_util.get_root_cost_items(cost_schedule)]
        result.append(
            {
                "id": cost_schedule.id(),
                "name": getattr(cost_schedule, "Name", None),
                "predefined_type": getattr(cost_schedule, "PredefinedType", None),
                "items": items,
            }
        )
    return result
