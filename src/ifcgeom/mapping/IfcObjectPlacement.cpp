/********************************************************************************
 *                                                                              *
 * This file is part of IfcOpenShell.                                           *
 *                                                                              *
 * IfcOpenShell is free software: you can redistribute it and/or modify         *
 * it under the terms of the Lesser GNU General Public License as published by  *
 * the Free Software Foundation, either version 3.0 of the License, or          *
 * (at your option) any later version.                                          *
 *                                                                              *
 * IfcOpenShell is distributed in the hope that it will be useful,              *
 * but WITHOUT ANY WARRANTY; without even the implied warranty of               *
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the                 *
 * Lesser GNU General Public License for more details.                          *
 *                                                                              *
 * You should have received a copy of the Lesser GNU General Public License     *
 * along with this program. If not, see <http://www.gnu.org/licenses/>.         *
 *                                                                              *
 ********************************************************************************/

#include "mapping.h"
#define mapping POSTFIX_SCHEMA(mapping)
using namespace ifcopenshell::geom;

#include <deque>
#include <map>
#include <set>
#include <vector>

namespace {
IfcSchema::IfcObjectPlacement placement_rel_to(const IfcSchema::IfcObjectPlacement& inst) {
#ifdef SCHEMA_IfcObjectPlacement_HAS_PlacementRelTo
    return inst.PlacementRelTo();
#else
    if (auto local = inst.as<IfcSchema::IfcLocalPlacement>()) {
        return local.PlacementRelTo();
    }
    return IfcSchema::IfcObjectPlacement();
#endif
}

// State of the PlacementRelTo walk on this thread. The outermost placement
// maps its ancestors from the root down so that every nested map() finds its
// parent in `parents` instead of recursing once per level, and a cyclic chain
// is cut at `cycle_cut`, the placement whose parent closes the cycle.
struct placement_walk_state {
    bool active = false;
    std::map<express::base, taxonomy::ptr> parents;
    express::base cycle_cut;
    std::set<express::base> in_progress;
};
thread_local placement_walk_state placement_walk;

struct placement_walk_scope {
    placement_walk_scope() {
        placement_walk.active = true;
    }
    ~placement_walk_scope() {
        placement_walk.active = false;
        placement_walk.parents.clear();
        placement_walk.cycle_cut = express::base();
    }
};

struct placement_in_progress_guard {
    express::base inst;
    explicit placement_in_progress_guard(const express::base& i) : inst(i) {
        placement_walk.in_progress.insert(inst);
    }
    ~placement_in_progress_guard() {
        placement_walk.in_progress.erase(inst);
    }
};

taxonomy::ptr map_parent_placement(mapping* m, const IfcSchema::IfcObjectPlacement& inst, const IfcSchema::IfcObjectPlacement& relative_to) {
    auto it = placement_walk.parents.find(relative_to);
    if (it != placement_walk.parents.end()) {
        return it->second;
    }
    if (placement_walk.active) {
        return m->map(relative_to);
    }

    placement_walk_scope scope;
    std::set<express::base> seen = {inst};
    std::vector<IfcSchema::IfcObjectPlacement> chain;
    for (auto placement = relative_to; placement;) {
        seen.insert(placement);
        chain.push_back(placement);
        auto next = placement_rel_to(placement);
        if (next && seen.count(next)) {
            placement_walk.cycle_cut = placement;
            break;
        }
        placement = next;
    }
    for (auto jt = chain.rbegin(); jt != chain.rend(); ++jt) {
        placement_walk.parents[*jt] = m->map(*jt);
    }
    return placement_walk.parents[relative_to];
}
} // namespace

taxonomy::ptr mapping::map_impl(const IfcSchema::IfcObjectPlacement& inst) {
	if (placement_rel_to_type_ || placement_rel_to_instance_) {
		using queue_item = std::pair<IfcSchema::IfcObjectPlacement, int>;
		std::deque<queue_item> q = {{inst, 0}};
		while (!q.empty()) {
			auto [placement, depth] = q.front();
			q.pop_front();

			if (!placement) {
				continue;
			}

			std::vector<IfcSchema::IfcProduct> self_places = placement.PlacesObject();
			for (auto& placed_product : self_places) {
				if ((placement_rel_to_type_ && placed_product.declaration().is(*placement_rel_to_type_)) ||
					(placement_rel_to_instance_ && placed_product == placement_rel_to_instance_)) {
					return taxonomy::make<taxonomy::matrix4>();
				}
			}

			// Look for two levels deep, we want to know if we're at or *above* the
			// element we're ignoring, but we don't want to traverse the entire model.
#ifdef SCHEMA_IfcObjectPlacement_HAS_ReferencedByPlacements
			if (depth < 2) {
				auto refs = placement.ReferencedByPlacements();
				for (auto& ref : refs) {
					q.emplace_back(ref.template as<IfcSchema::IfcObjectPlacement>(), depth + 1);
				}
			}
#else
			ifcopenshell::logger::root().warning("Using --site-local-placement or --building-local-placement on IFC4.2 might have issues");
#endif
		}
	}

	IfcSchema::IfcObjectPlacement relative_to;
	express::base transform;

	IfcSchema::IfcAxis2Placement3D fallback;

	if (inst.as<IfcSchema::IfcLocalPlacement>()) {
		transform = inst.as<IfcSchema::IfcLocalPlacement>().RelativePlacement();
	}
#ifdef SCHEMA_HAS_IfcLinearPlacement
   else if (inst.as<IfcSchema::IfcLinearPlacement>()) {
#ifdef SCHEMA_IfcLinearPlacement_HAS_RelativePlacement
        transform = inst.as<IfcSchema::IfcLinearPlacement>().RelativePlacement();
        fallback = inst.as<IfcSchema::IfcLinearPlacement>().CartesianPosition();
#else
        // @todo Ifc4x1 and Ifc4x2 don't have RelativePlacement
        return nullptr;
#endif
    }
#endif
    else if (inst.as<IfcSchema::IfcGridPlacement>()) {
		// @todo a bit harder to map without kernel
		return nullptr;
	}

    relative_to = placement_rel_to(inst);

	bool parent_placement_ignored = false;
    if (relative_to && (relative_to == inst || inst == placement_walk.cycle_cut ||
                        placement_walk.in_progress.count(relative_to))) {
        ifcopenshell::logger::root().warning("Ignoring cyclic PlacementRelTo:", inst);
        parent_placement_ignored = true;
    }
    if (!parent_placement_ignored && relative_to && (placement_rel_to_type_ || placement_rel_to_instance_)) {
		std::vector<IfcSchema::IfcProduct> parent_places = relative_to.PlacesObject();
        for (auto& pp : parent_places) {
            if ((placement_rel_to_type_ && pp.declaration().is(*placement_rel_to_type_)) ||
                (placement_rel_to_instance_ && pp == placement_rel_to_instance_)) {
				parent_placement_ignored = true;
			}
		}
	}

	taxonomy::matrix4::ptr result;
	if (!parent_placement_ignored && relative_to) {
        taxonomy::ptr parent;
        {
            placement_in_progress_guard guard(inst);
            parent = map_parent_placement(this, inst, relative_to);
        }
        result = taxonomy::make<taxonomy::matrix4>(
			// @nb this is a bit silly, in 0.7 we didn't have a recursive function
			// but a while loop to apply the hierarchical placements, so after the
			// loop we could apply the global offset. Since we have a recursive
			// function now we need to undo the global offset when recursing.
			offset_and_rotation_.inverse() *
			taxonomy::cast<taxonomy::matrix4>(parent)->ccomponents() *
			taxonomy::cast<taxonomy::matrix4>(map(transform))->ccomponents()
		);
	} else {
		// The parent placement of the current is a placement for a type that is
		// being ignored (Site or Building) or it is the host element of an opening.

		// Create a new copy around `result` so that it's cached copy is not altered
		// @todo immutability
		result = taxonomy::make<taxonomy::matrix4>(
			taxonomy::cast<taxonomy::matrix4>(map(transform))->ccomponents()
		);
	}

	if (fallback) {
        auto mapped_fallback = taxonomy::cast<taxonomy::matrix4>(map(fallback));
        if (!result->ccomponents().isApprox(mapped_fallback->ccomponents())) {
            ifcopenshell::logger::root().warning("Computed placement differs from fallback", inst);
        }
    }

	result->components() = offset_and_rotation_ * result->ccomponents();

	auto abs_det = std::abs(result->ccomponents().determinant());
	if (abs_det < 1.e-7) {
		ifcopenshell::logger::root().warning("Ignoring singular matrix:", inst);
		return nullptr;
	}

	return result;
}
