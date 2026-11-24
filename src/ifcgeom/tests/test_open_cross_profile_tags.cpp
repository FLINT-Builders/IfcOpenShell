// This file was generated with the assistance of an AI coding tool.

#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include <catch2/catch_test_macros.hpp>

#include "ifcgeom/converter.h"
#include "ifcgeom/kernel_registry.h"
#include "ifcgeom/taxonomy.h"
#include "ifcparse/macros.h"
#include IFCGEOM_TEST_SCHEMA_HEADER

namespace {

std::string repeated_measure(int count) {
    std::string values;
    for (int i = 0; i < count; ++i) {
        if (i) {
            values += ",";
        }
        values += "1.";
    }
    return values;
}

std::string repeated_tags(int count) {
    std::string values;
    for (int i = 0; i < count; ++i) {
        if (i) {
            values += ",";
        }
        values += "'T" + std::to_string(i) + "'";
    }
    return values;
}

// tag_count < 0 omits Tags. tag_count == 0 writes an empty list.
std::string open_cross_file(int width_count, int tag_count, bool tapered_end) {
    const std::string measures = repeated_measure(width_count);
    std::string tags = "$";
    if (tag_count >= 0) {
        tags = "(" + repeated_tags(tag_count) + ")";
    }
    const std::string profile =
        "IFCOPENCROSSPROFILEDEF(.CURVE.,$,.T.,(" + measures + "),(" + measures + ")," + tags + ",$)";

    std::ostringstream out;
    out << "ISO-10303-21;\n"
           "HEADER;\n"
           "FILE_DESCRIPTION((''),'2;1');\n"
           "FILE_NAME('','',(''),(''),'','','');\n"
           "FILE_SCHEMA(('IFC4X3_ADD2'));\n"
           "ENDSEC;\n"
           "DATA;\n"
           "#1=IFCPROJECT('0RYK8PV8D0ee9DDm77xcTZ',$,'T',$,$,$,$,(#6),$);\n"
           "#2=IFCCARTESIANPOINT((0.,0.,0.));\n"
           "#3=IFCDIRECTION((0.,0.,1.));\n"
           "#4=IFCDIRECTION((1.,0.,0.));\n"
           "#5=IFCAXIS2PLACEMENT3D(#2,#3,#4);\n"
           "#6=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#5,$);\n"
           "#7=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#6,$,.MODEL_VIEW.,$);\n"
           "#8=IFCDIRECTION((0.,0.,1.));\n"
           "#9=IFCAXIS2PLACEMENT3D(#2,#3,#4);\n";
    if (!tapered_end) {
        out << "#10=" << profile << ";\n"
            << "#11=IFCEXTRUDEDAREASOLID(#10,#9,#8,2.);\n";
    } else {
        const std::string matched_tags = "(" + repeated_tags(width_count + 1) + ")";
        out << "#10=IFCOPENCROSSPROFILEDEF(.CURVE.,$,.T.,(" << measures << "),(" << measures << "),"
            << matched_tags << ",$);\n"
            << "#15=" << profile << ";\n"
            << "#11=IFCEXTRUDEDAREASOLIDTAPERED(#10,#9,#8,2.,#15);\n";
    }
    out << "#12=IFCSHAPEREPRESENTATION(#7,'Body','SweptSolid',(#11));\n"
           "#13=IFCPRODUCTDEFINITIONSHAPE($,$,(#12));\n"
           "#14=IFCBUILDINGELEMENTPROXY('3cWcr4$892GAeKwryhDILR',$,'cross',$,$,$,#13,$,$);\n"
           "ENDSEC;\n"
           "END-ISO-10303-21;\n";
    return out.str();
}

struct opened_model {
    ifcopenshell::logger log;
    ifcopenshell::geom::settings settings;
    std::unique_ptr<ifcopenshell::file> file;
    std::unique_ptr<ifcopenshell::geom::converter> converter;

    explicit opened_model(const std::string& spf) {
        log.output_format(ifcopenshell::logger::FMT_INMEMORY);
        std::istringstream stream(spf);
        file.reset(new ifcopenshell::file(stream, static_cast<int>(spf.size()), log));
        converter.reset(new ifcopenshell::geom::converter(
            ifcopenshell::geom::kernels::construct(file.get(), "passthrough", settings, log),
            file.get(),
            settings,
            log));
    }

    opened_model(const opened_model&) = delete;
    opened_model& operator=(const opened_model&) = delete;
};

void require_schema() {
    if (std::string(STRINGIFY(IfcSchema)) != "Ifc4x3_add2") {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }
}

std::unique_ptr<opened_model> open_or_fail(const std::string& spf) {
    auto model = std::unique_ptr<opened_model>(new opened_model(spf));
    REQUIRE(model->file->good());
    REQUIRE(model->converter->mapping() != nullptr);
    return model;
}

IfcSchema::IfcOpenCrossProfileDef only_profile(opened_model& model, int which) {
    auto profiles = model.file->instances_by_type<IfcSchema::IfcOpenCrossProfileDef>();
    REQUIRE(static_cast<int>(profiles.size()) > which);
    return profiles[which];
}

void require_loop_edges(const ifcopenshell::geom::taxonomy::ptr& mapped, int width_count, int expected_tags) {
    REQUIRE(mapped);
    auto loop = ifcopenshell::geom::taxonomy::dcast<ifcopenshell::geom::taxonomy::loop>(mapped);
    REQUIRE(loop);
    CHECK(loop->children.size() == static_cast<std::size_t>(width_count));
    CHECK(loop->closed.has_value());
    CHECK(*loop->closed == false);
    if (expected_tags < 0) {
        CHECK_FALSE(loop->tags.has_value());
    } else {
        REQUIRE(loop->tags.has_value());
        CHECK(loop->tags->size() == static_cast<std::size_t>(expected_tags));
    }
}

} // namespace

TEST_CASE("IfcOpenCrossProfileDef maps when Tags matches Widths + 1", "[ifcgeom][open-cross-profile]") {
    require_schema();
    constexpr int widths = 2;
    auto model = open_or_fail(open_cross_file(widths, widths + 1, false));
    auto profile = only_profile(*model, 0);
    REQUIRE(profile.Widths().size() == static_cast<std::size_t>(widths));
    REQUIRE(profile.Tags().has_value());
    REQUIRE(profile.Tags()->size() == static_cast<std::size_t>(widths + 1));

    require_loop_edges(model->converter->mapping()->map(profile), widths, widths + 1);

    auto solids = model->file->instances_by_type<IfcSchema::IfcExtrudedAreaSolid>();
    REQUIRE(solids.size() == 1);
    auto solid = model->converter->mapping()->map(solids.front());
    REQUIRE(solid);
    CHECK(solid->kind() == ifcopenshell::geom::taxonomy::EXTRUSION);

    std::vector<ifcopenshell::geom::geometry_conversion_task> tasks;
    std::vector<ifcopenshell::geom::filter_function> filters;
    model->converter->mapping()->get_representations(tasks, filters);
    REQUIRE(tasks.size() == 1);
    auto representation = model->converter->mapping()->map(tasks.front().representation);
    REQUIRE(representation);
}

TEST_CASE("IfcOpenCrossProfileDef maps when Tags is omitted or empty", "[ifcgeom][open-cross-profile]") {
    require_schema();
    constexpr int widths = 3;

    auto omitted = open_or_fail(open_cross_file(widths, -1, false));
    auto omitted_profile = only_profile(*omitted, 0);
    CHECK_FALSE(omitted_profile.Tags().has_value());
    require_loop_edges(omitted->converter->mapping()->map(omitted_profile), widths, -1);

    auto empty = open_or_fail(open_cross_file(widths, 0, false));
    auto empty_profile = only_profile(*empty, 0);
    REQUIRE(empty_profile.Tags().has_value());
    REQUIRE(empty_profile.Tags()->empty());
    require_loop_edges(empty->converter->mapping()->map(empty_profile), widths, 0);
}

TEST_CASE("IfcOpenCrossProfileDef rejects a Tags list shorter than Widths + 1", "[ifcgeom][open-cross-profile]") {
    require_schema();

    // The reported file: one tag and many equal-length widths and slopes.
    // Also the off-by-one case, Tags.size() == Widths.size(), which still
    // indexes Tags[i + 1] past the end on the last width.
    const std::vector<std::pair<int, int>> short_lists = {{200, 1}, {2, 1}, {4, 4}};
    for (const auto& [widths, tags] : short_lists) {
        auto model = open_or_fail(open_cross_file(widths, tags, false));
        auto profile = only_profile(*model, 0);
        REQUIRE(profile.Widths().size() == profile.Slopes().size());
        REQUIRE(profile.Widths().size() == static_cast<std::size_t>(widths));
        REQUIRE(profile.Tags().has_value());
        REQUIRE(profile.Tags()->size() == static_cast<std::size_t>(tags));
        REQUIRE(profile.Tags()->size() != profile.Widths().size() + 1);

        // The geometry iterator maps the body representation before kernel
        // conversion. That walks IfcExtrudedAreaSolid::SweptArea into this
        // profile. A short Tags list must be rejected there, and on a direct
        // map of the profile and the solid.
        std::vector<ifcopenshell::geom::geometry_conversion_task> tasks;
        std::vector<ifcopenshell::geom::filter_function> filters;
        model->converter->mapping()->get_representations(tasks, filters);
        REQUIRE(tasks.size() == 1);
        REQUIRE(tasks.front().products.size() == 1);
        CHECK(model->converter->mapping()->map(tasks.front().representation) == nullptr);

        auto solids = model->file->instances_by_type<IfcSchema::IfcExtrudedAreaSolid>();
        REQUIRE(solids.size() == 1);
        CHECK(model->converter->mapping()->map(solids.front()) == nullptr);
        CHECK(model->converter->mapping()->map(profile) == nullptr);
    }
}

TEST_CASE("IfcExtrudedAreaSolidTapered rejects a short Tags list on EndSweptArea", "[ifcgeom][open-cross-profile]") {
    require_schema();
    constexpr int widths = 2;
    auto model = open_or_fail(open_cross_file(widths, 1, true));
    auto profiles = model->file->instances_by_type<IfcSchema::IfcOpenCrossProfileDef>();
    REQUIRE(profiles.size() == 2);

    IfcSchema::IfcOpenCrossProfileDef matched;
    IfcSchema::IfcOpenCrossProfileDef short_tags;
    for (auto& profile : profiles) {
        REQUIRE(profile.Tags().has_value());
        if (profile.Tags()->size() == static_cast<std::size_t>(widths + 1)) {
            matched = profile;
        } else {
            short_tags = profile;
        }
    }
    REQUIRE(matched);
    REQUIRE(short_tags);
    REQUIRE(short_tags.Tags()->size() == 1);
    REQUIRE(short_tags.Widths().size() == static_cast<std::size_t>(widths));

    auto tapered = model->file->instances_by_type<IfcSchema::IfcExtrudedAreaSolidTapered>();
    REQUIRE(tapered.size() == 1);
    CHECK(model->converter->mapping()->map(tapered.front()) == nullptr);
    require_loop_edges(model->converter->mapping()->map(matched), widths, widths + 1);
    CHECK(model->converter->mapping()->map(short_tags) == nullptr);
}
