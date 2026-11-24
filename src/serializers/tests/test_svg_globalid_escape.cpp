// This file was generated with the assistance of an AI coding tool.

// SVG attribute escaping for IFC GlobalId and Name.
//
// These tests drive the same serializer IfcConvert uses: parse an IFC file,
// iterate native geometry, and write it with svg_serializer. They fail while
// nameElement_ / idElement emit attribute values without XML escaping, and
// pass once every written attribute round-trips through a real XML parser
// with no extra elements.
//
// Run from a build configured with -DBUILD_IFCOPENSHELL_GEOMETRY_TESTS=ON
// and -DSCHEMA_VERSIONS including 4:
//
//   cmake --build <build> --target test_svg_globalid_escape
//   ctest --test-dir <build> -R svg_globalid --output-on-failure

#include "ifcgeom/iterator.h"
#include "ifcgeom/kernel_registry.h"
#include "ifcparse/hierarchy_helper.h"
#include "ifcparse/macros.h"
#include "serializers/svg_serializer.h"

#include <catch2/catch_test_macros.hpp>
#include <libxml/parser.h>
#include <libxml/tree.h>
#include <sstream>
#include <string>
#include <utility>

#include IFCGEOM_TEST_SCHEMA_HEADER

namespace {

const std::string kValidWallGuid = "0RyK8PV8D0ee9DDm77xcTZ";
const std::string kValidStoreyGuid = "1RyK8PV8D0ee9DDm77xcTY";

std::string breakout(const std::string& marker) {
    return "\"><image id=\"" + marker + "\" href=\"x\" onerror=\"xss&\"/>";
}

struct ids {
    std::string wall_guid = kValidWallGuid;
    std::string wall_name = "Wall";
    std::string storey_guid = kValidStoreyGuid;
    std::string storey_name = "Storey";
};

std::string write_spf(const ids& wanted) {
    hierarchy_helper<IfcSchema> file;
    auto wall = file.create<IfcSchema::IfcWallStandardCase>();
    wall.setGlobalId(wanted.wall_guid);
    wall.setName(wanted.wall_name);
    file.addBuildingProduct(wall);
    wall.setOwnerHistory(file.getSingle<IfcSchema::IfcOwnerHistory>());
    wall.setObjectPlacement(file.addLocalPlacement(file.getSingle<IfcSchema::IfcBuildingStorey>().ObjectPlacement()));
    wall.setRepresentation(file.addAxisBox(1000.0, 200.0, 3000.0));

    auto storey = file.getSingle<IfcSchema::IfcBuildingStorey>();
    storey.setGlobalId(wanted.storey_guid);
    storey.setName(wanted.storey_name);
    storey.setElevation(0.0);

    std::ostringstream out;
    out << static_cast<const ifcopenshell::file&>(file);
    return out.str();
}

std::string entity_string(const express::base& inst, const char* attribute) {
    return static_cast<std::string>(inst.as<express::entity>().get(attribute));
}

std::string render_svg(const std::string& spf, const ifcopenshell::geom::settings& settings) {
    std::istringstream input(spf);
    ifcopenshell::file file(input, static_cast<int>(spf.size()));

    auto walls = file.instances_by_type("IfcWall");
    REQUIRE(walls.size() == 1);
    auto storeys = file.instances_by_type("IfcBuildingStorey");
    REQUIRE(storeys.size() == 1);

    ifcopenshell::logger log;
    log.output_format(ifcopenshell::logger::FMT_INMEMORY);
    ifcopenshell::geom::settings iter_settings = settings;
    // geometry_svg_plugin::configure_serializer forces these before iteration.
    iter_settings.get<ifcopenshell::geom::settings::IteratorOutput>().value = ifcopenshell::geom::settings::NATIVE;
    iter_settings.get<ifcopenshell::geom::settings::UseElementHierarchy>().value = true;

    stream_or_filename buffer;
    svg_serializer serializer(buffer, iter_settings, &log);
    serializer.setFile(file);

    ifcopenshell::geom::iterator it(
        ifcopenshell::geom::kernels::construct(&file, "opencascade", iter_settings, log),
        iter_settings,
        &file,
        1,
        log);
    REQUIRE(it.initialize());
    serializer.writeHeader();
    do {
        auto element = it.get();
        REQUIRE(element);
        serializer.write(static_cast<const ifcopenshell::geom::native_element*>(element.get()));
    } while (it.next());
    serializer.finalize();
    const std::string svg = buffer.get_value();
    std::ostringstream log_text;
    for (const auto& message : log.log_messages()) {
        log_text << message.code << " " << message.message << "\n";
    }
    INFO(log_text.str());
    REQUIRE(svg.find("<g ") != std::string::npos);
    return svg;
}

struct xml_document {
    xmlDocPtr doc = nullptr;
    explicit xml_document(const std::string& svg) {
        doc = xmlReadMemory(svg.data(), static_cast<int>(svg.size()), "drawing.svg", nullptr, XML_PARSE_NONET);
    }
    ~xml_document() {
        if (doc) {
            xmlFreeDoc(doc);
        }
    }
    xml_document(const xml_document&) = delete;
    xml_document& operator=(const xml_document&) = delete;
};

std::string property(xmlNodePtr node, const char* name, const char* ns) {
    xmlChar* value = ns == nullptr ? xmlGetProp(node, BAD_CAST name) : xmlGetNsProp(node, BAD_CAST name, BAD_CAST ns);
    if (value == nullptr) {
        return {};
    }
    std::string text(reinterpret_cast<char*>(value));
    xmlFree(value);
    return text;
}

bool has_property(xmlNodePtr node, const char* name, const char* ns) {
    xmlChar* value = ns == nullptr ? xmlGetProp(node, BAD_CAST name) : xmlGetNsProp(node, BAD_CAST name, BAD_CAST ns);
    if (value == nullptr) {
        return false;
    }
    xmlFree(value);
    return true;
}

template <typename Fn>
void walk(xmlNodePtr node, Fn&& fn) {
    for (; node != nullptr; node = node->next) {
        if (node->type == XML_ELEMENT_NODE) {
            fn(node);
            walk(node->children, fn);
        }
    }
}

void require_no_injected_image(xmlDocPtr doc) {
    int images = 0;
    walk(xmlDocGetRootElement(doc), [&](xmlNodePtr node) {
        if (xmlStrcasecmp(node->name, BAD_CAST "image") == 0) {
            ++images;
        }
    });
    REQUIRE(images == 0);
}

void require_attribute(
    const std::string& svg,
    const std::string& class_substring,
    const char* attribute,
    const char* ns,
    const std::string& expected) {
    INFO(svg);
    xml_document parsed(svg);
    REQUIRE(parsed.doc != nullptr);
    require_no_injected_image(parsed.doc);

    int matches = 0;
    walk(xmlDocGetRootElement(parsed.doc), [&](xmlNodePtr node) {
        if (!has_property(node, "class", nullptr)) {
            return;
        }
        const std::string classes = property(node, "class", nullptr);
        if (classes.find(class_substring) == std::string::npos) {
            return;
        }
        if (!has_property(node, attribute, ns)) {
            return;
        }
        REQUIRE(property(node, attribute, ns) == expected);
        ++matches;
    });
    REQUIRE(matches > 0);
}

} // namespace

TEST_CASE("parser keeps a GlobalId that is not a compressed uuid", "[svg_globalid]") {
    const std::string payload = breakout("injected-parse");
    const std::string spf = write_spf(ids{payload, "Wall", kValidStoreyGuid, "Storey"});
    REQUIRE(spf.find(payload) != std::string::npos);

    std::istringstream input(spf);
    ifcopenshell::file file(input, static_cast<int>(spf.size()));
    auto walls = file.instances_by_type("IfcWall");
    REQUIRE(walls.size() == 1);
    REQUIRE(entity_string(walls.front(), "GlobalId") == payload);
}

TEST_CASE("floor plan data-guid escapes the product GlobalId", "[svg_globalid]") {
    const std::string payload = breakout("injected-product");
    const std::string spf = write_spf(ids{payload, "Wall", kValidStoreyGuid, "Storey"});
    ifcopenshell::geom::settings settings;
    const std::string svg = render_svg(spf, settings);
    require_attribute(svg, "IfcWall", "data-guid", nullptr, payload);
}

TEST_CASE("namespaced ifc:guid escapes the product GlobalId", "[svg_globalid]") {
    const std::string payload = breakout("injected-xmlns");
    const std::string spf = write_spf(ids{payload, "Wall", kValidStoreyGuid, "Storey"});
    ifcopenshell::geom::settings settings;
    settings.get<ifcopenshell::geom::settings::SvgUseNamespace>().value = true;
    const std::string svg = render_svg(spf, settings);
    require_attribute(svg, "IfcWall", "guid", "http://www.ifcopenshell.org/ns", payload);
}

TEST_CASE("use-element-guids escapes GlobalId in the id attribute", "[svg_globalid]") {
    const std::string payload = breakout("injected-id-guid");
    const std::string spf = write_spf(ids{payload, "Wall", kValidStoreyGuid, "Storey"});
    ifcopenshell::geom::settings settings;
    settings.get<ifcopenshell::geom::settings::UseElementGuids>().value = true;
    const std::string svg = render_svg(spf, settings);
    require_attribute(svg, "IfcWall", "id", nullptr, payload);
    require_attribute(svg, "IfcWall", "data-guid", nullptr, payload);
}

TEST_CASE("use-element-names escapes Name in the id attribute", "[svg_globalid]") {
    const std::string wall_name = breakout("injected-wall-name");
    const std::string storey_name = breakout("injected-storey-name");
    const std::string spf = write_spf(ids{kValidWallGuid, wall_name, kValidStoreyGuid, storey_name});
    ifcopenshell::geom::settings settings;
    settings.get<ifcopenshell::geom::settings::UseElementNames>().value = true;
    const std::string svg = render_svg(spf, settings);
    require_attribute(svg, "IfcWall", "id", nullptr, wall_name);
    require_attribute(svg, "IfcWall", "data-name", nullptr, wall_name);
    require_attribute(svg, "IfcBuildingStorey", "id", nullptr, "storey-" + storey_name);
    require_attribute(svg, "IfcBuildingStorey", "data-name", nullptr, storey_name);
}

TEST_CASE("storey and element guids are escaped when ids are step ids", "[svg_globalid]") {
    const std::string wall_guid = breakout("injected-wall-guid");
    const std::string storey_guid = breakout("injected-storey-guid");
    const std::string spf = write_spf(ids{wall_guid, "Wall", storey_guid, "Storey"});
    ifcopenshell::geom::settings settings;
    // Step ids keep idElement() from parsing GlobalId, so the storey group is
    // still written and its guid attribute is the raw value.
    settings.get<ifcopenshell::geom::settings::UseElementStepIds>().value = true;
    const std::string svg = render_svg(spf, settings);
    require_attribute(svg, "IfcWall", "data-guid", nullptr, wall_guid);
    require_attribute(svg, "IfcBuildingStorey", "data-guid", nullptr, storey_guid);
}
