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

#include <algorithm>
#include <deque>
#include <string>
#include <vector>

namespace {
	// Mapping recurses once per PlacementRelTo level, so longer chains are
	// rejected before they can exhaust the stack.
	constexpr std::size_t max_placement_depth = 256;

	IfcSchema::IfcObjectPlacement get_placement_rel_to(const IfcSchema::IfcObjectPlacement& placement) {
#ifdef SCHEMA_IfcObjectPlacement_HAS_PlacementRelTo
		return placement.PlacementRelTo();
#else
		if (auto local = placement.as<IfcSchema::IfcLocalPlacement>()) {
			return local.PlacementRelTo();
		}
		return {};
#endif
	}

	// The parser accepts cyclic PlacementRelTo chains, which would otherwise
	// recurse until the stack overflows.
	void check_placement_chain(const IfcSchema::IfcObjectPlacement& inst) {
		std::vector<IfcSchema::IfcObjectPlacement> chain = {inst};
		for (auto placement = get_placement_rel_to(inst); placement; placement = get_placement_rel_to(placement)) {
			if (std::find(chain.begin(), chain.end(), placement) != chain.end()) {
				throw ifcopenshell::exception("Cyclic PlacementRelTo chain at #" + std::to_string(inst.id()));
			}
			if (chain.size() >= max_placement_depth) {
				throw ifcopenshell::exception("PlacementRelTo chain too deep at #" + std::to_string(inst.id()));
			}
			chain.push_back(placement);
		}
	}
}

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

	relative_to = get_placement_rel_to(inst);

	bool parent_placement_ignored = false;
	if (relative_to && (placement_rel_to_type_ || placement_rel_to_instance_)) {
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
		check_placement_chain(inst);
        result = taxonomy::make<taxonomy::matrix4>(
			// @nb this is a bit silly, in 0.7 we didn't have a recursive function
			// but a while loop to apply the hierarchical placements, so after the
			// loop we could apply the global offset. Since we have a recursive
			// function now we need to undo the global offset when recursing.
			offset_and_rotation_.inverse() *
			taxonomy::cast<taxonomy::matrix4>(map(relative_to))->ccomponents() *
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
