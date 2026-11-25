# This file was generated with the assistance of an AI coding tool.
# IfcQuery - IFC model interrogation CLI
# Copyright (C) 2026 Bruno Postle <bruno@postle.net>
#
# This file is part of IfcQuery.
#
# IfcQuery is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcQuery is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcQuery.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import annotations

from typing import Any

import ifcopenshell


def _element_summary(element: ifcopenshell.entity_instance) -> dict[str, Any]:
    """Return a minimal summary dict for an element."""
    return {
        "id": element.id(),
        "type": element.is_a(),
        "name": element.Name if hasattr(element, "Name") else None,
    }


# Real spatial hierarchies are a handful of levels deep. Nesting is capped so
# the result stays within the depth that JSON and MCP serializers can encode.
MAX_DEPTH = 64


def _build_spatial_node(element: ifcopenshell.entity_instance, visited: set[int], depth: int = 0) -> dict[str, Any]:
    """Recursively build a spatial tree node, emitting each element only once."""
    visited.add(element.id())
    node = _element_summary(element)

    # Get aggregated children (Site in Project, Building in Site, Storey in Building, etc.)
    aggregates = []
    truncated = False
    for rel in getattr(element, "IsDecomposedBy", []):
        for child in rel.RelatedObjects:
            if child.id() in visited:
                continue
            if depth >= MAX_DEPTH:
                truncated = True
                continue
            aggregates.append(_build_spatial_node(child, visited, depth + 1))

    # Get contained elements (walls, slabs, etc. in a storey/space)
    contained = []
    for rel in getattr(element, "ContainsElements", []):
        for child in rel.RelatedElements:
            contained.append(_element_summary(child))

    if aggregates:
        node["children"] = aggregates
    if contained:
        node["elements"] = contained
    if truncated:
        node["truncated"] = True

    return node


def tree(model: ifcopenshell.file) -> dict[str, Any] | list[dict[str, Any]]:
    """Return the spatial hierarchy of the model as a nested tree.

    Starts at ``IfcProject`` and descends through decomposition (site,
    building, storeys) and containment (the elements placed in each storey).
    Every node carries ``id``, ``type`` and ``name``; ``children`` holds
    decomposed sub-spaces and ``elements`` holds contained elements, and
    either key is omitted when empty. Each element appears at most once, so
    cyclic or repeated decompositions are cut at the repeat. Nodes deeper
    than ``MAX_DEPTH`` are not descended into and carry ``truncated: True``.
    Returns a list when the file contains several projects, or an ``error``
    key when it contains none.

    :param model: The in-memory IFC model.
    """
    projects = model.by_type("IfcProject")
    if not projects:
        return {"error": "No IfcProject found in model"}
    visited: set[int] = set()
    if len(projects) == 1:
        return _build_spatial_node(projects[0], visited)
    return [_build_spatial_node(p, visited) for p in projects if p.id() not in visited]
