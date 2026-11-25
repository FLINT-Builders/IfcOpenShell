# This file was generated with the assistance of an AI coding tool.
from __future__ import annotations

from typing import Any

import ifcopenshell
import ifcopenshell.util.cost as cost_util


def _cost_item_to_dict(item: ifcopenshell.entity_instance, max_depth: int | None, depth: int) -> dict[str, Any]:
    # Walk the nest depth first on an explicit stack. A nested item already on the current path is skipped, so a
    # cyclic nest is listed once around. A None in place of the output list marks leaving that item's subtree.
    result: list[dict[str, Any]] = []
    path: set[int] = set()
    stack: list[tuple[ifcopenshell.entity_instance, int, list | None]] = [(item, depth, result)]
    while stack:
        item, depth, siblings = stack.pop()
        if siblings is None:
            path.remove(item.id())
            continue

        raw_values = cost_util.get_cost_values(item)
        values = [{"formula": v.get("label", ""), "category": v.get("category")} for v in raw_values]

        path.add(item.id())
        stack.append((item, depth, None))
        nested = [sub for sub in cost_util.get_nested_cost_items(item) if sub.id() not in path]
        if max_depth is not None and depth >= max_depth:
            subitems = {"truncated": True, "count": len(nested)} if nested else []
        else:
            subitems = []
            stack.extend((sub, depth + 1, subitems) for sub in reversed(nested))

        siblings.append(
            {
                "id": item.id(),
                "name": getattr(item, "Name", None),
                "values": values,
                "subitems": subitems,
            }
        )
    return result[0]


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
        not expanded. ``None`` (default) expands to unlimited depth.
    """
    result = []
    for cost_schedule in model.by_type("IfcCostSchedule"):
        items = [_cost_item_to_dict(i, max_depth, depth=1) for i in cost_util.get_root_cost_items(cost_schedule)]
        result.append(
            {
                "id": cost_schedule.id(),
                "name": getattr(cost_schedule, "Name", None),
                "predefined_type": getattr(cost_schedule, "PredefinedType", None),
                "items": items,
            }
        )
    return result
