// This file was generated with the assistance of an AI coding tool.

#include <optional>
#include <sstream>
#include <string>

#include <catch2/catch_test_macros.hpp>

#include "ifcgeom/converter.h"
#include "ifcgeom/iterator.h"
#include "ifcgeom/kernel_registry.h"
#include "ifcparse/file.h"
#include IFCGEOM_TEST_SCHEMA_HEADER

namespace {

constexpr const char* kHeader = R"IFC(ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('','',(''),(''),'','','');
FILE_SCHEMA(('IFC4X3_ADD2'));
ENDSEC;
DATA;
#1=IFCPROJECT('0RYK8PV8D0ee9DDm77xcTZ',$,'T',$,$,$,$,(#6),$);
#2=IFCCARTESIANPOINT((0.,0.,0.));
#3=IFCDIRECTION((0.,0.,1.));
#4=IFCDIRECTION((1.,0.,0.));
#5=IFCAXIS2PLACEMENT3D(#2,#3,#4);
#6=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#5,$);
#7=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#6,$,.MODEL_VIEW.,$);
#8=IFCCARTESIANPOINT((0.,0.,0.));
#9=IFCCARTESIANPOINT((10.,0.,0.));
#10=IFCPOLYLINE((#8,#9));
#16=IFCAXIS2PLACEMENT3D(#8,#3,#4);
#17=IFCCURVESEGMENT(.DISCONTINUOUS.,#16,IFCLENGTHMEASURE(0.),IFCLENGTHMEASURE(10.),#10);
)IFC";

// #11 is the curve under test and is the directrix of #12. #18 is a different
// curve of the same kind whose Segments list is not empty, so a check against
// some other curve in the file must not be treated as a check of #11.
std::string alignment_body(const std::string& empty_curve, const std::string& solid, const std::string& decoy) {
    std::ostringstream spf;
    spf << kHeader << empty_curve << "\n" << decoy << "\n" << solid << R"IFC(
#13=IFCSHAPEREPRESENTATION(#7,'Body','SweptSolid',(#12));
#14=IFCPRODUCTDEFINITIONSHAPE($,$,(#13));
#15=IFCBUILDINGELEMENTPROXY('3cWcr4$892GAeKwryhDILR',$,'pipe',$,$,$,#14,$,$);
ENDSEC;
END-ISO-10303-21;
)IFC";
    return spf.str();
}

std::string gradient_body(const std::string& solid) {
    return alignment_body(
        "#11=IFCGRADIENTCURVE((),.F.,#10,$);",
        solid,
        "#18=IFCGRADIENTCURVE((#17),.F.,#10,$);");
}

std::string segmented_reference_body(const std::string& solid) {
    return alignment_body(
        "#11=IFCSEGMENTEDREFERENCECURVE((),.F.,#10,$);",
        solid,
        "#18=IFCSEGMENTEDREFERENCECURVE((#17),.F.,#10,$);");
}

struct opened_file {
    ifcopenshell::logger log;
    std::optional<ifcopenshell::file> file;

    explicit opened_file(const std::string& spf) {
        log.output_format(ifcopenshell::logger::FMT_INMEMORY);
        log.verbosity(ifcopenshell::logger::LOG_NOTICE);
        std::istringstream stream(spf);
        file.emplace(stream, static_cast<int>(spf.size()), log);
    }
};

std::size_t errors_for_instance(const ifcopenshell::logger& log, int id) {
    const auto token = "#" + std::to_string(id) + "=";
    std::size_t count = 0;
    for (const auto& message : log.log_messages()) {
        if (message.severity < ifcopenshell::logger::LOG_ERROR) {
            continue;
        }
        if (message.instance.find(token) != std::string::npos || message.message.find(token) != std::string::npos) {
            ++count;
        }
    }
    return count;
}

template <typename T>
T require_empty_segments(ifcopenshell::file& file) {
    std::optional<T> empty;
    std::size_t nonempty = 0;
    for (auto curve : file.instances_by_type_excl_subtypes<T>()) {
        auto segments = curve.Segments();
        if (segments.empty()) {
            REQUIRE_FALSE(empty.has_value());
            empty = curve;
        } else {
            ++nonempty;
            // Reading the populated list must be well defined. The vulnerable
            // call is front() on the empty list, so this only checks that the
            // decoy survived parsing as a different instance.
            (void) segments.front();
        }
    }
    REQUIRE(empty.has_value());
    REQUIRE(nonempty >= 1);
    REQUIRE(empty->Segments().empty());
    return *empty;
}

template <typename T>
void reject_empty_segments(const std::string& spf) {
    if (std::string(STRINGIFY(IfcSchema)) != "Ifc4x3_add2") {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }

    opened_file opened(spf);
    REQUIRE(opened.file->good());
    auto& file = *opened.file;

    const auto curve = require_empty_segments<T>(file);
    const auto curve_id = curve.id();
    const auto errors_before = errors_for_instance(opened.log, curve_id);

    ifcopenshell::geom::settings settings;
    auto kernel = ifcopenshell::geom::kernels::construct(&file, "passthrough", settings, opened.log);
    ifcopenshell::geom::converter converter(std::move(kernel), &file, settings, opened.log);

    std::vector<ifcopenshell::geom::geometry_conversion_task> tasks;
    std::vector<ifcopenshell::geom::filter_function> filters;
    converter.mapping()->get_representations(tasks, filters);
    REQUIRE(tasks.size() == 1);
    REQUIRE(tasks.front().products.size() == 1);

    // The list is still empty at the point mapping reads it. A check of a
    // different curve, or a check that does not still apply to this list when
    // front() runs, still has to fail this mapping.
    REQUIRE(curve.Segments().empty());
    const auto solid = file.instance_by_id(12);
    REQUIRE(solid);
    ifcopenshell::geom::taxonomy::ptr mapped_solid;
    try {
        // Body geometry maps the solid, which maps this directrix.
        mapped_solid = converter.mapping()->map(solid);
    } catch (const std::exception&) {
        mapped_solid = nullptr;
    }
    REQUIRE(mapped_solid == nullptr);
    REQUIRE(curve.Segments().empty());

    ifcopenshell::geom::taxonomy::ptr mapped_curve;
    REQUIRE_NOTHROW(mapped_curve = converter.mapping()->map(curve));
    REQUIRE(mapped_curve == nullptr);
    REQUIRE(errors_for_instance(opened.log, curve_id) > errors_before);

    ifcopenshell::geom::settings iterator_settings;
    ifcopenshell::geom::iterator iterator(
        ifcopenshell::geom::kernels::construct(&file, "passthrough", iterator_settings, opened.log),
        iterator_settings,
        &file,
        1,
        opened.log);
    const bool produced_geometry = iterator.initialize();
    CHECK_FALSE(produced_geometry);
    CHECK((iterator.had_error_processing_elements() || errors_for_instance(opened.log, curve_id) > errors_before));
    REQUIRE(curve.Segments().empty());
}

} // namespace

TEST_CASE("empty IfcGradientCurve segments do not crash swept disk geometry", "[ifcgeom][empty-segments]") {
    reject_empty_segments<IfcSchema::IfcGradientCurve>(gradient_body("#12=IFCSWEPTDISKSOLID(#11,0.5,$,$,$);"));
}

TEST_CASE("empty IfcSegmentedReferenceCurve segments do not crash swept disk geometry", "[ifcgeom][empty-segments]") {
    reject_empty_segments<IfcSchema::IfcSegmentedReferenceCurve>(
        segmented_reference_body("#12=IFCSWEPTDISKSOLID(#11,0.5,$,$,$);"));
}

TEST_CASE("empty IfcGradientCurve segments do not crash sectioned solid geometry", "[ifcgeom][empty-segments]") {
    reject_empty_segments<IfcSchema::IfcGradientCurve>(
        gradient_body("#12=IFCSECTIONEDSOLIDHORIZONTAL(#11,(),());"));
}
