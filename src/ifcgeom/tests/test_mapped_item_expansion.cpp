// This file was generated with the assistance of an AI coding tool.

#include "ifcgeom/converter.h"
#include "ifcgeom/element.h"
#include "ifcgeom/iterator.h"
#include "ifcgeom/kernel_registry.h"
#include "ifcparse/hierarchy_helper.h"

#include <catch2/catch_test_macros.hpp>
#include <fstream>
#include <string>
#include IFCGEOM_TEST_SCHEMA_HEADER

namespace {

// Default geometry conversion must not materialize one result per path of a
// shared IfcMappedItem DAG. A representation whose path count exceeds this
// limit has to be refused under default settings (cache-shapes stays off).
// Ordinary mapped-item graphs below the limit must still convert in full.
constexpr int kMaxConversionResultsPerRepresentation = 100000;

int mapped_item_paths(int branch, int depth) {
    int paths = 1;
    for (int level = 0; level < depth; ++level) {
        paths *= branch;
    }
    return paths;
}

IfcSchema::IfcProduct add_nested_mapped_proxy(hierarchy_helper<IfcSchema>& file, int branch, int depth) {
    auto context = file.getRepresentationSubContext("Body", "Model");

    auto leaf = file.create<IfcSchema::IfcShapeRepresentation>();
    leaf.setContextOfItems(context);
    leaf.setRepresentationIdentifier("Body");
    leaf.setRepresentationType("SweptSolid");
    leaf.setItems(std::vector<IfcSchema::IfcRepresentationItem>{});
    file.addBox(leaf, 1000.0, 200.0, 300.0);

    auto map = file.create<IfcSchema::IfcRepresentationMap>();
    map.setMappingOrigin(file.addPlacement3d());
    map.setMappedRepresentation(leaf);

    for (int level = 0; level < depth; ++level) {
        std::vector<IfcSchema::IfcRepresentationItem> items;
        items.reserve(static_cast<std::size_t>(branch));
        for (int i = 0; i < branch; ++i) {
            auto transform = file.create<IfcSchema::IfcCartesianTransformationOperator3D>();
            transform.setLocalOrigin(
                file.addTriplet<IfcSchema::IfcCartesianPoint>(static_cast<double>(i) * 10.0, static_cast<double>(level) * 10.0, 0.0));
            auto item = file.create<IfcSchema::IfcMappedItem>();
            item.setMappingSource(map);
            item.setMappingTarget(transform);
            items.push_back(item);
        }

        auto representation = file.create<IfcSchema::IfcShapeRepresentation>();
        representation.setContextOfItems(context);
        representation.setRepresentationIdentifier("Body");
        representation.setRepresentationType("MappedRepresentation");
        representation.setItems(items);

        map = file.create<IfcSchema::IfcRepresentationMap>();
        map.setMappingOrigin(file.addPlacement3d());
        map.setMappedRepresentation(representation);
    }

    auto proxy = file.create<IfcSchema::IfcBuildingElementProxy>();
    proxy.setGlobalId(ifcopenshell::global_id());
    proxy.setName("nested mapped proxy");
    file.addBuildingProduct(proxy);

    auto shape = file.create<IfcSchema::IfcProductDefinitionShape>();
    shape.setRepresentations(std::vector<IfcSchema::IfcRepresentation>{map.MappedRepresentation()});
    proxy.setRepresentation(shape);
    return proxy;
}

ifcopenshell::geom::settings default_geometry_settings() {
    ifcopenshell::geom::settings settings;
    REQUIRE(settings.get<ifcopenshell::geom::settings::CacheShapes>().get() == false);
    settings.get<ifcopenshell::geom::settings::IteratorOutput>().value = ifcopenshell::geom::settings::NATIVE;
    return settings;
}

std::string peak_memory() {
    std::ifstream status("/proc/self/status");
    std::string line;
    std::string report;
    while (std::getline(status, line)) {
        if (line.rfind("VmPeak:", 0) == 0 || line.rfind("VmRSS:", 0) == 0) {
            if (!report.empty()) {
                report += "; ";
            }
            report += line;
        }
    }
    return report.empty() ? "memory counters unavailable" : report;
}

struct conversion_outcome {
    bool converted = false;
    int shape_count = 0;
};

conversion_outcome convert_with_create_brep(hierarchy_helper<IfcSchema>& file, const IfcSchema::IfcProduct& product) {
    auto settings = default_geometry_settings();
    ifcopenshell::logger log;
    log.output_format(ifcopenshell::logger::FMT_INMEMORY);
    ifcopenshell::geom::converter converter(
        ifcopenshell::geom::kernels::construct(&file, "passthrough", settings, log), &file, settings, log);

    const auto representation = product.Representation().Representations().back();
    std::unique_ptr<ifcopenshell::geom::native_element> element(
        converter.create_brep_for_representation_and_product(representation, product));
    conversion_outcome outcome;
    if (element) {
        outcome.converted = true;
        outcome.shape_count = element->geometry().size();
    }
    return outcome;
}

conversion_outcome convert_with_iterator(hierarchy_helper<IfcSchema>& file, int num_threads) {
    auto settings = default_geometry_settings();
    ifcopenshell::logger log;
    log.output_format(ifcopenshell::logger::FMT_INMEMORY);
    ifcopenshell::geom::iterator geometry(
        ifcopenshell::geom::kernels::construct(&file, "passthrough", settings, log), settings, &file, num_threads, log);

    conversion_outcome outcome;
    if (!geometry.initialize()) {
        return outcome;
    }
    auto element = geometry.get();
    auto* native = dynamic_cast<ifcopenshell::geom::native_element*>(element.get());
    if (native == nullptr) {
        return outcome;
    }
    outcome.converted = true;
    outcome.shape_count = native->geometry().size();
    return outcome;
}

} // namespace

TEST_CASE("Nested mapped items within the conversion budget expand once per path", "[ifcgeom][mapped-item]") {
    constexpr int branch = 4;
    constexpr int depth = 3;
    const int paths = mapped_item_paths(branch, depth);
    REQUIRE(paths == 64);
    REQUIRE(paths <= kMaxConversionResultsPerRepresentation);

    hierarchy_helper<IfcSchema> file;
    const auto proxy = add_nested_mapped_proxy(file, branch, depth);

    const auto brep = convert_with_create_brep(file, proxy);
    REQUIRE(brep.converted);
    REQUIRE(brep.shape_count == paths);

    const auto iterated = convert_with_iterator(file, 1);
    REQUIRE(iterated.converted);
    REQUIRE(iterated.shape_count == paths);
}

TEST_CASE("Nested mapped items are expanded when the iterator uses multiple threads", "[ifcgeom][mapped-item]") {
    constexpr int branch = 4;
    constexpr int depth = 3;
    const int paths = mapped_item_paths(branch, depth);

    hierarchy_helper<IfcSchema> file;
    add_nested_mapped_proxy(file, branch, depth);

    const auto iterated = convert_with_iterator(file, 2);
    REQUIRE(iterated.converted);
    REQUIRE(iterated.shape_count == paths);
}

TEST_CASE("Nested mapped items beyond the conversion budget are refused", "[ifcgeom][mapped-item]") {
    // 7^6 = 117649 paths from one extruded solid and 42 mapped items.
    // Default conversion currently returns every path. It must instead refuse
    // the representation before that result vector is built.
    constexpr int branch = 7;
    constexpr int depth = 6;
    const int paths = mapped_item_paths(branch, depth);
    REQUIRE(paths == 117649);
    REQUIRE(paths > kMaxConversionResultsPerRepresentation);

    hierarchy_helper<IfcSchema> file;
    const auto proxy = add_nested_mapped_proxy(file, branch, depth);

    const auto brep = convert_with_create_brep(file, proxy);
    INFO("create_brep converted=" << brep.converted << " shape_count=" << brep.shape_count << " paths=" << paths << " " << peak_memory());
    CHECK_FALSE(brep.converted);
    CHECK(brep.shape_count <= kMaxConversionResultsPerRepresentation);

    hierarchy_helper<IfcSchema> iterator_file;
    add_nested_mapped_proxy(iterator_file, branch, depth);
    const auto iterated = convert_with_iterator(iterator_file, 1);
    INFO("iterator converted=" << iterated.converted << " shape_count=" << iterated.shape_count << " paths=" << paths << " " << peak_memory());
    CHECK_FALSE(iterated.converted);
    CHECK(iterated.shape_count <= kMaxConversionResultsPerRepresentation);
}
