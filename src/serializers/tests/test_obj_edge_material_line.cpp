// This file was generated with the assistance of an AI coding tool.

// Drives the Wavefront edge loop in wavefront_obj_serializer::write().
// Curve tessellation in the OpenCASCADE kernel is what normally calls
// triangulation::addEdge(); this harness builds that same edge mesh and
// gives it the IfcSurfaceStyle name parsed from the IFC file, then calls
// the real serializer. A face-only export does not enter this loop.

#include "wavefront_obj_serializer.h"

#include "../ifcgeom/element.h"
#include "../ifcgeom/representation.h"
#include "../ifcgeom/taxonomy.h"
#include "../ifcparse/file.h"

#include <iostream>
#include <memory>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "usage: test_obj_edge_material_line <input.ifc> <output.obj> <output.mtl>\n";
        return 2;
    }

    ifcopenshell::file file(argv[1]);
    if (!file.good()) {
        std::cerr << "unable to parse " << argv[1] << "\n";
        return 2;
    }

    auto styles = file.instances_by_type("IfcSurfaceStyle");
    auto products = file.instances_by_type("IfcBuildingElementProxy");
    if (styles.empty() || products.empty()) {
        std::cerr << "fixture is missing IfcSurfaceStyle or IfcBuildingElementProxy\n";
        return 2;
    }

    auto style_entity = styles.front().as<express::entity>();
    auto product = products.front().as<express::entity>();
    const std::string style_name = style_entity.get_value<std::string>("Name", "");

    ifcopenshell::geom::settings settings;
    auto style = ifcopenshell::geom::taxonomy::make<ifcopenshell::geom::taxonomy::style>(style_name);
    style->diffuse = ifcopenshell::geom::taxonomy::colour(0.2, 0.3, 0.4);

    auto mesh = std::make_shared<ifcopenshell::geom::triangulation>(
        settings,
        std::string("IfcBuildingElementProxy"),
        std::string("edge"),
        std::vector<double>{0.0, 0.0, 0.0, 1.0, 0.0, 0.0},
        std::vector<int>{},
        std::vector<int>{0, 1},
        std::vector<double>{},
        std::vector<double>{},
        std::vector<int>{0},
        std::vector<ifcopenshell::geom::taxonomy::style::ptr>{style},
        std::vector<int>{},
        std::vector<int>{0});

    auto place = ifcopenshell::geom::taxonomy::make<ifcopenshell::geom::taxonomy::matrix4>();
    ifcopenshell::geom::element source(
        settings,
        product.id(),
        -1,
        product.get_value<std::string>("Name", ""),
        product.declaration().name(),
        product.get_value<std::string>("GlobalId", ""),
        std::string("Body"),
        place,
        product);
    ifcopenshell::geom::triangulation_element element(source, mesh);

    wavefront_obj_serializer serializer(std::string(argv[2]), std::string(argv[3]), settings);
    if (!serializer.ready()) {
        std::cerr << "serializer could not open output\n";
        return 2;
    }
    serializer.writeHeader();
    serializer.write(&element);
    return 0;
}
