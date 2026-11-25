#include "../ifcgeom/element.h"
#include "../ifcgeom/conversion_settings.h"
#include "../ifcgeom/abstract_mapping.h"
#include "../ifcgeom/function_item_evaluator.h"

#include "abstract_kernel.h"

using namespace ifcopenshell::geom;

const char* ifcopenshell::not_implemented_error::what() const noexcept {
	return "Not implemented.";
}

const char* ifcopenshell::not_supported_error::what() const noexcept {
	return "Not supported.";
}

bool ifcopenshell::geom::kernels::abstract_kernel::count_conversion_items(std::size_t n) {
	if (conversion_limit_exceeded_) {
		return false;
	}
	const int limit = settings_.get<settings::MaxConversionItems>().get();
	if (limit > 0) {
		conversion_items_ += n;
		if (conversion_items_ > static_cast<std::size_t>(limit)) {
			conversion_limit_exceeded_ = true;
			return false;
		}
	}
	return true;
}

bool ifcopenshell::geom::kernels::abstract_kernel::convert(const taxonomy::ptr item, std::vector<ifcopenshell::geom::conversion_result>& results) {
	const bool is_root = conversion_depth_ == 0;
	const auto num_results_before = results.size();
	if (is_root) {
		conversion_items_ = 0;
		conversion_limit_exceeded_ = false;
	}
	const auto items_before = conversion_items_;

	auto refuse = [&]() {
		// With cache-shapes a later conversion of the same item can be cheaper, so the bound would not hold.
		const auto consumed = conversion_items_ - items_before;
		if (!settings_.get<settings::CacheShapes>().get() && consumed > 0) {
			auto& lower_bound = conversion_cost_lower_bounds_[item];
			lower_bound = std::max(lower_bound, consumed);
		}
		if (is_root) {
			if (results.size() > num_results_before) {
				results.erase(results.begin() + num_results_before, results.end());
			}
			logger_.error("GEO", 404, "Conversion exceeds " + std::to_string(settings_.get<settings::MaxConversionItems>().get()) +
				" items (see the max-conversion-items setting), representation not converted:", item->instance);
		}
		return false;
	};

	if (!count_conversion_items(1)) {
		return refuse();
	}
	const int limit = settings_.get<settings::MaxConversionItems>().get();
	auto known_cost = conversion_cost_lower_bounds_.find(item);
	if (known_cost != conversion_cost_lower_bounds_.end() && limit > 0 && items_before + known_cost->second > static_cast<std::size_t>(limit)) {
		conversion_limit_exceeded_ = true;
		return refuse();
	}

	struct depth_guard {
		std::size_t& depth;
		explicit depth_guard(std::size_t& d) : depth(d) { ++depth; }
		~depth_guard() { --depth; }
	} guard(conversion_depth_);

	if (settings_.get<settings::CacheShapes>().get()) {
		auto it = cache_.find(item);
		if (it != cache_.end()) {
			results = it->second;
			logger_.notice("SYS", 25, "Cache hit #" + std::to_string(item->instance.id()) +
				" -> #" + std::to_string(it->first->instance.id()));
			return true;
		}
	}

	auto with_exception_handling = [&](auto fn) {
		try {
			return fn();
		} catch (std::exception& e) {
			logger_.error("GEO", 27, e, item->instance);
			return false;
		} catch (...) {
			// @todo we can't log OCCT exceptions here, can we do some reraising to solve this?
			return false;
		}
	};
	auto without_exception_handling = [](auto fn) {
		return fn();
	};
	auto process_with_upgrade = [&]() {
		try {
			return dispatch_conversion<0>::dispatch(this, item->kind(), item, results);
		} catch (const not_implemented_error&) {
			return dispatch_with_upgrade<0>::dispatch(this, item, results);
		}
	};

	bool res;
	if (propagate_exceptions) {
		res = without_exception_handling(process_with_upgrade);
	} else {
		res = with_exception_handling(process_with_upgrade);
	}

	if (conversion_limit_exceeded_) {
		return refuse();
	}

	if (settings_.get<settings::CacheShapes>().get() && res) {
		cache_.insert({ item, results });
	}

	return res;
}

const ifcopenshell::geom::settings& ifcopenshell::geom::kernels::abstract_kernel::settings() const
{
	return settings_;
}

bool ifcopenshell::geom::kernels::abstract_kernel::convert_impl(const taxonomy::collection::ptr collection, std::vector<ifcopenshell::geom::conversion_result>& r) {
	auto s = r.size();
	for (auto& c : collection->children) {
		if (!convert(c, r) && (conversion_limit_exceeded_ || !partial_success_is_success)) {
			return false;
		}
	}
	if (!count_conversion_items(r.size() > s ? r.size() - s : 0)) {
		return false;
	}
	for (auto i = s; i < r.size(); ++i) {
		if (collection->matrix) {
			r[i].prepend(collection->matrix);
		}
		if (!r[i].hasStyle() && collection->surface_style) {
			r[i].setStyle(collection->surface_style);
		}
	}
	return r.size() > s;
}

bool ifcopenshell::geom::kernels::abstract_kernel::convert_impl(const taxonomy::function_item::ptr item, std::vector<ifcopenshell::geom::conversion_result>& cs) {
   function_item_evaluator evaluator(settings(),item);
   auto expl = evaluator.evaluate();
	expl->instance = item->instance;
	return convert(expl, cs);
}

bool ifcopenshell::geom::kernels::abstract_kernel::convert_impl(const taxonomy::functor_item::ptr item, std::vector<ifcopenshell::geom::conversion_result>& cs) {
    function_item_evaluator evaluator(settings(), item);
    auto expl = evaluator.evaluate();
    expl->instance = item->instance;
    return convert(expl, cs);
}

bool ifcopenshell::geom::kernels::abstract_kernel::convert_impl(const taxonomy::piecewise_function::ptr item, std::vector<ifcopenshell::geom::conversion_result>& cs) {
    function_item_evaluator evaluator(settings(), item);
    auto expl = evaluator.evaluate();
    expl->instance = item->instance;
    return convert(expl, cs);
}

bool ifcopenshell::geom::kernels::abstract_kernel::convert_impl(const taxonomy::gradient_function::ptr item, std::vector<ifcopenshell::geom::conversion_result>& cs) {
    function_item_evaluator evaluator(settings(), item);
    auto expl = evaluator.evaluate();
    expl->instance = item->instance;
    return convert(expl, cs);
}

bool ifcopenshell::geom::kernels::abstract_kernel::convert_impl(const taxonomy::cant_function::ptr item, std::vector<ifcopenshell::geom::conversion_result>& cs) {
    function_item_evaluator evaluator(settings(), item);
    auto expl = evaluator.evaluate();
    expl->instance = item->instance;
    return convert(expl, cs);
}

bool ifcopenshell::geom::kernels::abstract_kernel::convert_impl(const taxonomy::offset_function::ptr item, std::vector<ifcopenshell::geom::conversion_result>& cs) {
    function_item_evaluator evaluator(settings(), item);
    auto expl = evaluator.evaluate();
    expl->instance = item->instance;
    return convert(expl, cs);
}
