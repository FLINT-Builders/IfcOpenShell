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

#include <optional>

#define mapping POSTFIX_SCHEMA(mapping)
using namespace ifcopenshell::geom;

namespace {
	// Mapped items are converted recursively, so cyclic or very deep nesting would exhaust the stack.
	const size_t max_mapped_item_nesting_depth = 64;

	class expansion_guard {
	public:
		expansion_guard(std::unordered_set<uint32_t>& in_progress, uint32_t identity)
			: in_progress_(in_progress)
			, identity_(identity) {
			in_progress_.insert(identity_);
		}
		~expansion_guard() {
			in_progress_.erase(identity_);
		}
		expansion_guard(const expansion_guard&) = delete;
		expansion_guard& operator=(const expansion_guard&) = delete;

	private:
		std::unordered_set<uint32_t>& in_progress_;
		uint32_t identity_;
	};
}

taxonomy::ptr mapping::map_impl(const IfcSchema::IfcMappedItem& inst) {
	auto transform = inst.MappingTarget();
	taxonomy::matrix4::ptr gtrsf = taxonomy::cast<taxonomy::matrix4>(map(transform));
	auto rmap = inst.MappingSource();
	auto placement = rmap.MappingOrigin();
	taxonomy::matrix4::ptr trsf2 = taxonomy::cast<taxonomy::matrix4>(map(placement));
	Eigen::Matrix4d res = gtrsf->ccomponents() * trsf2->ccomponents();

	auto mapped_representation = rmap.MappedRepresentation();
	std::optional<expansion_guard> guard;
	if (mapped_representation) {
		const uint32_t identity = mapped_representation.identity();
		if (mapped_representations_in_progress_.count(identity)) {
			logger_.error("GEO", 328, "Cyclic mapped representation:", inst);
			failed_on_purpose_.insert(inst);
			return nullptr;
		}
		if (mapped_representations_in_progress_.size() >= max_mapped_item_nesting_depth) {
			logger_.error("GEO", 329, "Mapped item nesting exceeds " + std::to_string(max_mapped_item_nesting_depth) + " levels:", inst);
			failed_on_purpose_.insert(inst);
			return nullptr;
		}
		guard.emplace(mapped_representations_in_progress_, identity);
	}

	// @todo immutable for caching?
	// @todo allow for multiple levels of matrix?
	auto shapes = taxonomy::dcast<taxonomy::collection>(map(mapped_representation));
	if (shapes == nullptr) {
		if (failed_on_purpose_.find(mapped_representation) != failed_on_purpose_.end()) {
			// propagate
			failed_on_purpose_.insert(inst);
		}
		return shapes;
	}

	auto collection = taxonomy::make<taxonomy::collection>();
	collection->children.push_back(shapes);
	collection->matrix = taxonomy::make<taxonomy::matrix4>(res);

	return collection;
}
