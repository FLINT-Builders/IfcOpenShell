// This file was generated with the assistance of an AI coding tool.

#include <memory>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include <catch2/catch_test_macros.hpp>

#include "ifcgeom/converter.h"
#include "ifcgeom/iterator.h"
#include "ifcgeom/kernel_registry.h"
#include "ifcgeom/taxonomy.h"
#include "ifcparse/hierarchy_helper.h"
#include "ifcparse/parse.h"
#include IFCGEOM_TEST_SCHEMA_HEADER

namespace {

enum class station_measure { length, parameter, cartesian };

struct station {
    double distance;
    station_measure measure;
};

enum class sectioned_kind { solid, surface };

const char* sectioned_entity_name(sectioned_kind kind) {
    return kind == sectioned_kind::solid ? "IfcSectionedSolidHorizontal" : "IfcSectionedSurface";
}

IfcSchema::IfcCurve make_gradient_curve(hierarchy_helper<IfcSchema>& file) {
    auto point = file.addTriplet<IfcSchema::IfcCartesianPoint>(0.0, 0.0, 0.0);
    auto direction = file.addTriplet<IfcSchema::IfcDirection>(1.0, 0.0, 0.0);
    auto vector = file.create<IfcSchema::IfcVector>();
    vector.setOrientation(direction);
    vector.setMagnitude(1.0);
    auto line = file.create<IfcSchema::IfcLine>();
    line.setPnt(point);
    line.setDir(vector);

    auto horizontal_segment = file.create<IfcSchema::IfcCurveSegment>();
    horizontal_segment.setTransition(IfcSchema::IfcTransitionCode::IfcTransitionCode_CONTINUOUS);
    horizontal_segment.setPlacement(file.addPlacement3d());
    horizontal_segment.setSegmentStart(file.addValue<IfcSchema::IfcLengthMeasure>(0.0));
    horizontal_segment.setSegmentLength(file.addValue<IfcSchema::IfcLengthMeasure>(100.0));
    horizontal_segment.setParentCurve(line);

    auto base_curve = file.create<IfcSchema::IfcCompositeCurve>();
    base_curve.setSegments({horizontal_segment});
    base_curve.setSelfIntersect(false);

    auto vertical_segment = file.create<IfcSchema::IfcCurveSegment>();
    vertical_segment.setTransition(IfcSchema::IfcTransitionCode::IfcTransitionCode_CONTINUOUS);
    vertical_segment.setPlacement(file.addPlacement3d());
    vertical_segment.setSegmentStart(file.addValue<IfcSchema::IfcLengthMeasure>(0.0));
    vertical_segment.setSegmentLength(file.addValue<IfcSchema::IfcLengthMeasure>(100.0));
    vertical_segment.setParentCurve(line);

    auto gradient = file.create<IfcSchema::IfcGradientCurve>();
    gradient.setSegments({vertical_segment});
    gradient.setSelfIntersect(false);
    gradient.setBaseCurve(base_curve);
    return gradient;
}

IfcSchema::IfcPoint station_location(hierarchy_helper<IfcSchema>& file, const IfcSchema::IfcCurve& basis, const station& at) {
    if (at.measure == station_measure::cartesian) {
        return file.addTriplet<IfcSchema::IfcCartesianPoint>(at.distance, 0.0, 0.0);
    }
    auto expression = file.create<IfcSchema::IfcPointByDistanceExpression>();
    if (at.measure == station_measure::parameter) {
        expression.setDistanceAlong(file.addValue<IfcSchema::IfcParameterValue>(at.distance));
    } else {
        expression.setDistanceAlong(file.addValue<IfcSchema::IfcLengthMeasure>(at.distance));
    }
    expression.setBasisCurve(basis);
    return expression;
}

IfcSchema::IfcAxis2PlacementLinear linear_placement(
    hierarchy_helper<IfcSchema>& file, const IfcSchema::IfcCurve& basis, const station& at) {
    auto placement = file.create<IfcSchema::IfcAxis2PlacementLinear>();
    placement.setLocation(station_location(file, basis, at));
    return placement;
}

IfcSchema::IfcRectangleProfileDef rectangle_profile(hierarchy_helper<IfcSchema>& file) {
    auto profile = file.create<IfcSchema::IfcRectangleProfileDef>();
    profile.setProfileType(IfcSchema::IfcProfileTypeEnum::IfcProfileType_AREA);
    profile.setPosition(file.addPlacement2d());
    profile.setXDim(1.0);
    profile.setYDim(1.0);
    return profile;
}

std::string sectioned_product_spf(sectioned_kind kind, const station& first, const station& second) {
    hierarchy_helper<IfcSchema> file;
    auto owner_history = file.addOwnerHistory();
    file.addProject(owner_history);
    auto context = file.getRepresentationContext("Model");
    context.setContextType("Model");

    auto gradient = make_gradient_curve(file);
    std::vector<IfcSchema::IfcProfileDef> profiles = {rectangle_profile(file), rectangle_profile(file)};
    std::vector<IfcSchema::IfcAxis2PlacementLinear> positions = {
        linear_placement(file, gradient, first),
        linear_placement(file, gradient, second),
    };

    IfcSchema::IfcRepresentationItem item;
    if (kind == sectioned_kind::solid) {
        auto solid = file.create<IfcSchema::IfcSectionedSolidHorizontal>();
        solid.setDirectrix(gradient);
        solid.setCrossSections(profiles);
        solid.setCrossSectionPositions(positions);
        item = solid;
    } else {
        auto surface = file.create<IfcSchema::IfcSectionedSurface>();
        surface.setDirectrix(gradient);
        surface.setCrossSectionPositions(positions);
        surface.setCrossSections(profiles);
        item = surface;
    }

    auto representation = file.create<IfcSchema::IfcShapeRepresentation>();
    representation.setContextOfItems(context);
    representation.setRepresentationIdentifier("Body");
    representation.setRepresentationType("AdvancedSweptSolid");
    representation.setItems({item});

    auto shape = file.create<IfcSchema::IfcProductDefinitionShape>();
    shape.setRepresentations({representation});

    auto product = file.create<IfcSchema::IfcBuildingElementProxy>();
    product.setGlobalId(ifcopenshell::global_id());
    product.setOwnerHistory(owner_history);
    product.setName(std::string(sectioned_entity_name(kind)));
    product.setObjectPlacement(file.addLocalPlacement());
    product.setRepresentation(shape);
    file.addBuildingProduct(product);

    std::ostringstream spf;
    spf << file;
    return spf.str();
}

std::unique_ptr<ifcopenshell::file> open_spf(const std::string& spf, ifcopenshell::logger& logger) {
    auto parsed = std::make_unique<ifcopenshell::file>(const_cast<char*>(spf.data()), static_cast<int>(spf.size()), logger);
    REQUIRE(parsed->good());
    REQUIRE(parsed->schema() != nullptr);
    REQUIRE(parsed->schema()->name().find("IFC4X3") != std::string::npos);
    return parsed;
}

express::base sectioned_item(ifcopenshell::file& file) {
    auto solids = file.instances_by_type<IfcSchema::IfcSectionedSolidHorizontal>();
    if (!solids.empty()) {
        REQUIRE(solids.size() == 1);
        return solids.front();
    }
    auto surfaces = file.instances_by_type<IfcSchema::IfcSectionedSurface>();
    REQUIRE(surfaces.size() == 1);
    return surfaces.front();
}

IfcSchema::IfcCurve directrix_of(const express::base& item) {
    if (auto solid = item.as<IfcSchema::IfcSectionedSolidHorizontal>()) {
        return solid.Directrix();
    }
    return item.as<IfcSchema::IfcSectionedSurface>().Directrix();
}

std::vector<IfcSchema::IfcAxis2PlacementLinear> positions_of(const express::base& item) {
    if (auto solid = item.as<IfcSchema::IfcSectionedSolidHorizontal>()) {
        return solid.CrossSectionPositions();
    }
    return item.as<IfcSchema::IfcSectionedSurface>().CrossSectionPositions();
}

void require_station(const IfcSchema::IfcAxis2PlacementLinear& placement, station_measure measure) {
    auto location = placement.Location();
    REQUIRE(location);
    if (measure == station_measure::cartesian) {
        REQUIRE(location.as<IfcSchema::IfcCartesianPoint>());
        REQUIRE_FALSE(location.as<IfcSchema::IfcPointByDistanceExpression>());
        return;
    }
    auto expression = location.as<IfcSchema::IfcPointByDistanceExpression>();
    REQUIRE(expression);
    auto distance = expression.DistanceAlong();
    REQUIRE(distance);
    if (measure == station_measure::parameter) {
        REQUIRE(distance.as<IfcSchema::IfcParameterValue>());
        REQUIRE_FALSE(distance.as<IfcSchema::IfcLengthMeasure>());
    } else {
        REQUIRE(distance.as<IfcSchema::IfcLengthMeasure>());
    }
}

bool logged_refusal_for(const ifcopenshell::logger& logger, const std::string& entity_name) {
    for (const auto& message : logger.log_messages()) {
        if (message.severity < ifcopenshell::logger::LOG_WARNING) {
            continue;
        }
        if (message.instance.find(entity_name) != std::string::npos || message.message.find(entity_name) != std::string::npos) {
            return true;
        }
    }
    return false;
}

ifcopenshell::geom::taxonomy::ptr map_item(ifcopenshell::file& file, const express::base& item, ifcopenshell::logger& logger) {
    ifcopenshell::geom::settings settings;
    auto kernel = ifcopenshell::geom::kernels::construct(&file, "passthrough", settings, logger);
    REQUIRE(kernel);
    ifcopenshell::geom::converter converter(std::move(kernel), &file, settings, logger);
    REQUIRE(converter.mapping() != nullptr);
    return converter.mapping()->map(item);
}

void require_directrix_maps(ifcopenshell::file& file, const express::base& item) {
    ifcopenshell::logger logger;
    logger.output_format(ifcopenshell::logger::FMT_INMEMORY);
    auto mapped = map_item(file, directrix_of(item), logger);
    INFO(logger.get_log());
    REQUIRE(ifcopenshell::geom::taxonomy::dcast<ifcopenshell::geom::taxonomy::function_item>(mapped));
}

void expect_refused(sectioned_kind kind, const station& first, const station& second) {
    const std::string spf = sectioned_product_spf(kind, first, second);
    ifcopenshell::logger parse_logger;
    std::unique_ptr<ifcopenshell::file> file = open_spf(spf, parse_logger);
    const express::base item = sectioned_item(*file);
    const auto positions = positions_of(item);
    REQUIRE(positions.size() == 2);
    require_station(positions[0], first.measure);
    require_station(positions[1], second.measure);
    require_directrix_maps(*file, item);

    ifcopenshell::logger logger;
    logger.output_format(ifcopenshell::logger::FMT_INMEMORY);
    logger.verbosity(ifcopenshell::logger::LOG_NOTICE);
    const auto mapped = map_item(*file, item, logger);
    INFO(logger.get_log());
    REQUIRE(mapped == nullptr);
    REQUIRE(logged_refusal_for(logger, sectioned_entity_name(kind)));
}

} // namespace

TEST_CASE("Sectioned solid with cartesian cross-section locations is refused", "[sectioned-location]") {
    expect_refused(sectioned_kind::solid, {0.0, station_measure::cartesian}, {100.0, station_measure::cartesian});
}

TEST_CASE("Sectioned surface with cartesian cross-section locations is refused", "[sectioned-location]") {
    expect_refused(sectioned_kind::surface, {0.0, station_measure::cartesian}, {100.0, station_measure::cartesian});
}

TEST_CASE("Sectioned solid refuses a later cartesian cross-section location", "[sectioned-location]") {
    expect_refused(sectioned_kind::solid, {10.0, station_measure::length}, {90.0, station_measure::cartesian});
}

TEST_CASE("Sectioned surface refuses a parameter distance after a length distance", "[sectioned-location]") {
    expect_refused(sectioned_kind::surface, {10.0, station_measure::length}, {90.0, station_measure::parameter});
}

TEST_CASE("Sectioned solid refuses parameter distances along the directrix", "[sectioned-location]") {
    expect_refused(sectioned_kind::solid, {0.0, station_measure::parameter}, {1.0, station_measure::parameter});
}

TEST_CASE("Valid sectioned solid cross-section locations still map", "[sectioned-location]") {
    const std::string spf = sectioned_product_spf(
        sectioned_kind::solid, {10.0, station_measure::length}, {90.0, station_measure::length});
    ifcopenshell::logger parse_logger;
    std::unique_ptr<ifcopenshell::file> file = open_spf(spf, parse_logger);
    const express::base item = sectioned_item(*file);
    const auto positions = positions_of(item);
    REQUIRE(positions.size() == 2);
    require_station(positions[0], station_measure::length);
    require_station(positions[1], station_measure::length);
    require_directrix_maps(*file, item);

    ifcopenshell::logger logger;
    logger.output_format(ifcopenshell::logger::FMT_INMEMORY);
    logger.verbosity(ifcopenshell::logger::LOG_NOTICE);
    const auto mapped = map_item(*file, item, logger);
    INFO(logger.get_log());
    REQUIRE(mapped);
    REQUIRE(mapped->kind() == ifcopenshell::geom::taxonomy::LOFT);
}

TEST_CASE("Geometry iterator refuses a product whose sectioned solid uses cartesian locations", "[sectioned-location]") {
    const std::string spf = sectioned_product_spf(
        sectioned_kind::solid, {0.0, station_measure::cartesian}, {100.0, station_measure::cartesian});
    ifcopenshell::logger parse_logger;
    std::unique_ptr<ifcopenshell::file> file = open_spf(spf, parse_logger);
    const express::base item = sectioned_item(*file);
    require_station(positions_of(item).front(), station_measure::cartesian);
    require_directrix_maps(*file, item);

    ifcopenshell::geom::settings settings;
    ifcopenshell::logger logger;
    logger.output_format(ifcopenshell::logger::FMT_INMEMORY);
    logger.verbosity(ifcopenshell::logger::LOG_NOTICE);
    ifcopenshell::geom::iterator iterator(
        ifcopenshell::geom::kernels::construct(file.get(), "passthrough", settings, logger), settings, file.get(), 1, logger);
    INFO(logger.get_log());
    REQUIRE_FALSE(iterator.initialize());
    REQUIRE(logged_refusal_for(logger, "IfcSectionedSolidHorizontal"));
}
