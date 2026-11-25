// This file was generated with the assistance of an AI coding tool.

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

#ifndef WALK_GUARD_H
#define WALK_GUARD_H

#include "../ifcparse/express.h"
#include "../ifcparse/logger.h"

#include <cstddef>
#include <cstdint>
#include <set>

namespace ifcopenshell {
namespace serializers {

// Instance identities on the current path of a recursive relationship walk.
typedef std::set<uint32_t> walk_path;

// Marks an instance as being on the path of a recursive relationship walk for
// the lifetime of the guard. The guard is false, and nothing is marked, when
// the instance is already on the path or the path is max_depth long, so that a
// cyclic or pathologically deep model cannot exhaust the stack. Pass the path
// of the enclosing guard to nested calls, or nullptr to start a new walk.
class walk_guard {
  public:
    // Far beyond the nesting found in real models, and shallow enough that the
    // recursion, and the nested output trees it builds, stay within the stack.
    static constexpr std::size_t max_depth = 256;

    walk_guard(ifcopenshell::logger& log, walk_path* path, const express::base& instance)
        : path_(path ? path : &own_path_), identity_(instance.identity()), entered_(path_->size() < max_depth && path_->insert(identity_).second) {
        if (!entered_) {
            log.warning("SER", 38, "Relationship cycle or maximum nesting depth reached, not descending into:", instance);
        }
    }

    ~walk_guard() {
        if (entered_) {
            path_->erase(identity_);
        }
    }

    walk_guard(const walk_guard&) = delete;
    walk_guard& operator=(const walk_guard&) = delete;

    explicit operator bool() const { return entered_; }

    walk_path* path() const { return path_; }

  private:
    walk_path own_path_;
    walk_path* path_;
    uint32_t identity_;
    bool entered_;
};

} // namespace serializers
} // namespace ifcopenshell

#endif
