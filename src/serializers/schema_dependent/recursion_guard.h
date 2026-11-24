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

// This file was generated with the assistance of an AI coding tool.

#ifndef SERIALIZERS_RECURSION_GUARD_H
#define SERIALIZERS_RECURSION_GUARD_H

#include "../../ifcparse/express.h"

#include <algorithm>
#include <cstddef>
#include <vector>

// The parser accepts cyclic relationships, so the recursive formatters skip an
// instance that is already on the current path and stop at a nesting depth that
// no real model reaches.
class recursion_guard {
  public:
    static constexpr std::size_t max_depth = 256;

    class scope {
      public:
        scope(recursion_guard& guard, const express::base& instance) {
            auto& path = guard.path_;
            if (path.size() < max_depth && std::find(path.begin(), path.end(), instance) == path.end()) {
                path.push_back(instance);
                guard_ = &guard;
            }
        }

        ~scope() {
            if (guard_ != nullptr) {
                guard_->path_.pop_back();
            }
        }

        scope(const scope&) = delete;
        scope& operator=(const scope&) = delete;

        explicit operator bool() const {
            return guard_ != nullptr;
        }

      private:
        recursion_guard* guard_ = nullptr;
    };

  private:
    std::vector<express::base> path_;
};

#endif
