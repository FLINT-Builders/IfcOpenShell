// This file was generated with the assistance of an AI coding tool.

#include "ifcgeom/converter.h"
#include "ifcgeom/iterator.h"
#include "ifcgeom/kernel_registry.h"
#include "ifcgeom/profile_helper.h"
#include "ifcparse/file.h"

#include <catch2/catch_test_macros.hpp>
#include <memory>
#include <set>
#include <sstream>
#include <string>
#include <utility>
#include <vector>
#include IFCGEOM_TEST_SCHEMA_HEADER

using ifcopenshell::geom::taxonomy::point3;

namespace {

struct session {
    ifcopenshell::logger log;
    ifcopenshell::geom::settings settings;
    std::unique_ptr<ifcopenshell::file> file;
    std::unique_ptr<ifcopenshell::geom::converter> converter;
};

std::unique_ptr<session> open_spf(const std::string& spf) {
    auto opened = std::make_unique<session>();
    opened->log.output_format(ifcopenshell::logger::FMT_INMEMORY);
    opened->log.verbosity(ifcopenshell::logger::LOG_NOTICE);
    std::istringstream stream(spf);
    opened->file = std::make_unique<ifcopenshell::file>(stream, static_cast<int>(spf.size()), opened->log);
    REQUIRE(opened->file->good());
    opened->converter = std::make_unique<ifcopenshell::geom::converter>(
        ifcopenshell::geom::kernels::construct(opened->file.get(), "passthrough", opened->settings, opened->log),
        opened->file.get(),
        opened->settings,
        opened->log);
    return opened;
}

template <typename T>
T only_instance(session& opened) {
    auto instances = opened.file->instances_by_type<T>();
    REQUIRE(instances.size() == 1);
    return instances.front();
}

template <typename T>
ifcopenshell::geom::taxonomy::ptr map_only(session& opened) {
    return opened.converter->mapping()->map(only_instance<T>(opened));
}

void expect_no_edges(const ifcopenshell::geom::taxonomy::ptr& item) {
    if (!item) {
        return;
    }
    if (auto loop = std::dynamic_pointer_cast<ifcopenshell::geom::taxonomy::loop>(item)) {
        CHECK(loop->children.empty());
    }
    if (auto collection = std::dynamic_pointer_cast<ifcopenshell::geom::taxonomy::collection>(item)) {
        for (const auto& child : collection->children) {
            expect_no_edges(child);
        }
    }
}

point3::ptr point_at(double x, double y, double z) {
    return ifcopenshell::geom::taxonomy::make<point3>(x, y, z);
}

// Every polyline below is written as IFCPOLYLINE(()) so the STEP parser stores
// a typed empty Points list. Each shape is one the geometry iterator will map.
constexpr const char* EMPTY_POLYLINES_SPF = R"IFC(ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('empty-polylines.ifc','',(''),(''),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCPROJECT('0YvhJ9o$zFVx8mYqAA111',$,'P',$,$,$,$,(#2),#3);
#2=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#4,$);
#3=IFCUNITASSIGNMENT((#5));
#4=IFCAXIS2PLACEMENT3D(#6,$,$);
#5=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#6=IFCCARTESIANPOINT((0.,0.,0.));
#7=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#2,$,.MODEL_VIEW.,$);
#8=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Axis','Model',*,*,*,*,#2,$,.GRAPH_VIEW.,$);
#9=IFCDIRECTION((0.,0.,1.));
#10=IFCDIRECTION((1.,0.,0.));
#11=IFCAXIS2PLACEMENT3D(#6,#9,#10);
#12=IFCPOLYLINE(());
#13=IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#12);
#14=IFCEXTRUDEDAREASOLID(#13,#11,#9,3.);
#15=IFCSHAPEREPRESENTATION(#7,'Body','SweptSolid',(#14));
#16=IFCPOLYLINE(());
#17=IFCSHAPEREPRESENTATION(#8,'Axis','Curve2D',(#16));
#18=IFCPRODUCTDEFINITIONSHAPE($,$,(#15,#17));
#19=IFCLOCALPLACEMENT($,#11);
#20=IFCWALL('0YvhJ9o$zFVx8mYqAA112',$,'Wall',$,$,#19,#18,$,$);
#21=IFCPOLYLINE(());
#22=IFCSWEPTDISKSOLID(#21,0.5,$,$,$);
#23=IFCSHAPEREPRESENTATION(#7,'Body','SweptSolid',(#22));
#24=IFCPRODUCTDEFINITIONSHAPE($,$,(#23));
#25=IFCBUILDINGELEMENTPROXY('0YvhJ9o$zFVx8mYqAA113',$,'Pipe',$,$,#19,#24,$,$);
#26=IFCPOLYLINE(());
#27=IFCARBITRARYOPENPROFILEDEF(.CURVE.,$,#26);
#28=IFCSURFACEOFLINEAREXTRUSION(#27,#11,#9,1.);
#29=IFCSHAPEREPRESENTATION(#7,'Body','SurfaceModel',(#28));
#30=IFCPRODUCTDEFINITIONSHAPE($,$,(#29));
#31=IFCBUILDINGELEMENTPROXY('0YvhJ9o$zFVx8mYqAA114',$,'Surface',$,$,#19,#30,$,$);
#32=IFCPOLYLINE(());
#33=IFCGEOMETRICCURVESET((#32));
#34=IFCSHAPEREPRESENTATION(#7,'Body','GeometricCurveSet',(#33));
#35=IFCPRODUCTDEFINITIONSHAPE($,$,(#34));
#36=IFCBUILDINGELEMENTPROXY('0YvhJ9o$zFVx8mYqAA115',$,'Curves',$,$,#19,#35,$,$);
#37=IFCPOLYLINE(());
#38=IFCCOMPOSITECURVESEGMENT(.CONTINUOUS.,.T.,#37);
#39=IFCCOMPOSITECURVE((#38),.F.);
#40=IFCSHAPEREPRESENTATION(#8,'Axis','Curve2D',(#39));
#41=IFCPRODUCTDEFINITIONSHAPE($,$,(#40));
#42=IFCBUILDINGELEMENTPROXY('0YvhJ9o$zFVx8mYqAA116',$,'Composite',$,$,#19,#41,$,$);
#43=IFCPOLYLINE(());
#44=IFCTRIMMEDCURVE(#43,(IFCPARAMETERVALUE(0.)),(IFCPARAMETERVALUE(1.)),.T.,.PARAMETER.);
#45=IFCSHAPEREPRESENTATION(#8,'Axis','Curve2D',(#44));
#46=IFCPRODUCTDEFINITIONSHAPE($,$,(#45));
#47=IFCBUILDINGELEMENTPROXY('0YvhJ9o$zFVx8mYqAA117',$,'Trimmed',$,$,#19,#46,$,$);
#48=IFCPOLYLOOP(());
#49=IFCFACE((#50));
#50=IFCFACEOUTERBOUND(#48,.T.);
#51=IFCFACETEDBREP(#52);
#52=IFCCLOSEDSHELL((#49));
#53=IFCSHAPEREPRESENTATION(#7,'Body','Brep',(#51));
#54=IFCPRODUCTDEFINITIONSHAPE($,$,(#53));
#55=IFCBUILDINGELEMENTPROXY('0YvhJ9o$zFVx8mYqAA118',$,'Brep',$,$,#19,#54,$,$);
ENDSEC;
END-ISO-10303-21;
)IFC";

constexpr const char* TWO_POINT_POLYLINE_SPF = R"IFC(ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('two-point-polyline.ifc','',(''),(''),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCCARTESIANPOINT((0.,0.,0.));
#2=IFCCARTESIANPOINT((1.,0.,0.));
#3=IFCPOLYLINE((#1,#2));
ENDSEC;
END-ISO-10303-21;
)IFC";

constexpr const char* ONE_POINT_POLYLINE_SPF = R"IFC(ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('one-point-polyline.ifc','',(''),(''),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCCARTESIANPOINT((0.,0.,0.));
#2=IFCPOLYLINE((#1));
ENDSEC;
END-ISO-10303-21;
)IFC";

} // namespace

TEST_CASE("two-point IfcPolyline still maps to one edge", "[empty-polyline]") {
    auto opened = open_spf(TWO_POINT_POLYLINE_SPF);
    auto polyline = only_instance<IfcSchema::IfcPolyline>(*opened);
    REQUIRE(polyline.Points().size() == 2);

    auto mapped = opened->converter->mapping()->map(polyline);
    REQUIRE(mapped);
    auto loop = std::dynamic_pointer_cast<ifcopenshell::geom::taxonomy::loop>(mapped);
    REQUIRE(loop);
    CHECK(loop->children.size() == 1);
    CHECK(opened->log.count("GEO277") == 0);
}

TEST_CASE("one-point IfcPolyline is rejected", "[empty-polyline]") {
    auto opened = open_spf(ONE_POINT_POLYLINE_SPF);
    auto polyline = only_instance<IfcSchema::IfcPolyline>(*opened);
    REQUIRE(polyline.Points().size() == 1);

    CHECK(opened->converter->mapping()->map(polyline) == nullptr);
    CHECK(opened->log.count("GEO277") == 1);
}

TEST_CASE("open duplicate removal keeps a loop of two or more points", "[empty-polyline]") {
    std::vector<point3::ptr> polygon{point_at(0., 0., 0.), point_at(0., 0., 0.), point_at(1., 0., 0.)};
    ifcopenshell::geom::remove_duplicate_points_from_loop(polygon, false, 1e-5);
    CHECK(polygon.size() == 2);
}

TEST_CASE("empty open loop does not divide by its point count", "[empty-polyline]") {
    std::vector<point3::ptr> polygon;
    ifcopenshell::geom::remove_duplicate_points_from_loop(polygon, false, 1e-5);
    CHECK(polygon.empty());
}

// Defined at global scope in profile_helper.cpp. The header declares the same
// signature inside ifcopenshell::geom, but that namespaced symbol is not emitted.
std::pair<
    std::vector<ifcopenshell::geom::taxonomy::point3::ptr>,
    std::vector<std::set<std::string>>>
remove_duplicate_points_from_loop(
    const std::vector<ifcopenshell::geom::taxonomy::point3::ptr>& polygon,
    const std::vector<std::string>& tags);

TEST_CASE("tag-aware duplicate removal does not divide by an empty point count", "[empty-polyline]") {
    std::vector<ifcopenshell::geom::taxonomy::point3::ptr> polygon;
    auto with_tags = remove_duplicate_points_from_loop(polygon, std::vector<std::string>{"edge"});
    CHECK(with_tags.first.empty());
    auto without_tags = remove_duplicate_points_from_loop(polygon, {});
    CHECK(without_tags.first.empty());
}

TEST_CASE("empty closed loop is left unchanged", "[empty-polyline]") {
    std::vector<point3::ptr> polygon;
    ifcopenshell::geom::remove_duplicate_points_from_loop(polygon, true, 1e-5);
    CHECK(polygon.empty());
}

TEST_CASE("parsed empty IfcPolyline points list is empty", "[empty-polyline]") {
    auto opened = open_spf(EMPTY_POLYLINES_SPF);
    auto polylines = opened->file->instances_by_type<IfcSchema::IfcPolyline>();
    REQUIRE(!polylines.empty());
    for (auto& polyline : polylines) {
        CHECK(polyline.Points().empty());
    }
}

TEST_CASE("mapping an empty IfcPolyline rejects it", "[empty-polyline]") {
    auto opened = open_spf(EMPTY_POLYLINES_SPF);
    auto polylines = opened->file->instances_by_type<IfcSchema::IfcPolyline>();
    REQUIRE(!polylines.empty());
    for (auto& polyline : polylines) {
        CHECK(opened->converter->mapping()->map(polyline) == nullptr);
    }
    CHECK(opened->log.count("GEO277") == polylines.size());
}

TEST_CASE("extruded wall profile with an empty outer polyline is rejected", "[empty-polyline]") {
    auto opened = open_spf(EMPTY_POLYLINES_SPF);
    CHECK(map_only<IfcSchema::IfcArbitraryClosedProfileDef>(*opened) == nullptr);
    CHECK(map_only<IfcSchema::IfcExtrudedAreaSolid>(*opened) == nullptr);
}

TEST_CASE("swept disk whose directrix is an empty polyline is rejected", "[empty-polyline]") {
    auto opened = open_spf(EMPTY_POLYLINES_SPF);
    CHECK(map_only<IfcSchema::IfcSweptDiskSolid>(*opened) == nullptr);
}

TEST_CASE("open profile and linear extrusion of an empty polyline are rejected", "[empty-polyline]") {
    auto opened = open_spf(EMPTY_POLYLINES_SPF);
    CHECK(map_only<IfcSchema::IfcArbitraryOpenProfileDef>(*opened) == nullptr);
    expect_no_edges(map_only<IfcSchema::IfcSurfaceOfLinearExtrusion>(*opened));
}

TEST_CASE("geometric curve set of an empty polyline has no edges", "[empty-polyline]") {
    auto opened = open_spf(EMPTY_POLYLINES_SPF);
    auto mapped = map_only<IfcSchema::IfcGeometricCurveSet>(*opened);
    auto collection = std::dynamic_pointer_cast<ifcopenshell::geom::taxonomy::collection>(mapped);
    REQUIRE(collection);
    CHECK(collection->children.empty());
}

TEST_CASE("composite curve segment on an empty polyline has no edges", "[empty-polyline]") {
    auto opened = open_spf(EMPTY_POLYLINES_SPF);
    auto mapped = map_only<IfcSchema::IfcCompositeCurve>(*opened);
    expect_no_edges(mapped);
    if (mapped) {
        CHECK(mapped->kind() == ifcopenshell::geom::taxonomy::LOOP);
    }
}

TEST_CASE("trimmed curve on an empty polyline has no edges", "[empty-polyline]") {
    auto opened = open_spf(EMPTY_POLYLINES_SPF);
    expect_no_edges(map_only<IfcSchema::IfcTrimmedCurve>(*opened));
}

TEST_CASE("empty IfcPolyLoop is rejected before duplicate cleanup", "[empty-polyline]") {
    auto opened = open_spf(EMPTY_POLYLINES_SPF);
    auto loop = only_instance<IfcSchema::IfcPolyLoop>(*opened);
    REQUIRE(loop.Polygon().empty());
    CHECK(opened->converter->mapping()->map(loop) == nullptr);
}

TEST_CASE("geometry iterator survives products that use empty polylines", "[empty-polyline]") {
    auto opened = open_spf(EMPTY_POLYLINES_SPF);
    ifcopenshell::geom::iterator it(
        ifcopenshell::geom::kernels::construct(opened->file.get(), "passthrough", opened->settings, opened->log),
        opened->settings,
        opened->file.get(),
        1,
        opened->log);

    if (!it.initialize()) {
        return;
    }
    for (;;) {
        auto element = it.get();
        REQUIRE(element);
        if (auto* mesh = dynamic_cast<ifcopenshell::geom::triangulation_element*>(element.get())) {
            CHECK(mesh->geometry().verts().empty());
        }
        if (!it.next()) {
            break;
        }
    }
}
