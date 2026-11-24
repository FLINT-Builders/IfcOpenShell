// This file was generated with the assistance of an AI coding tool.

// Spec for the missing cap on function-curve evaluation.
//
// function_item_evaluator::evaluation_points() sets
//   num_steps = ceil(curve_length / function-step-param)
// with the default step of 0.5 m and then allocates one sample per step.
// abstract_kernel::convert_impl() evaluates every function item (piecewise,
// gradient, cant, offset, functor) through that method. IfcFixedReferenceSweptAreaSolid
// clones the profile at every sample. make_loft() repeats the same uncapped
// division for IfcSectionedSolidHorizontal. These tests fail until each of
// those paths refuses or widens the step before allocating more than
// kMaxFunctionSamples positions.

#include "ifcgeom/abstract_kernel.h"
#include "ifcgeom/converter.h"
#include "ifcgeom/function_item_evaluator.h"
#include "ifcgeom/kernel_registry.h"
#include "ifcgeom/taxonomy.h"
#include "ifcparse/macros.h"

#include <catch2/catch_test_macros.hpp>
#include <cstddef>
#include <fstream>
#include <limits>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>
#include <vector>
#include IFCGEOM_TEST_SCHEMA_HEADER

namespace {

// Inclusive of the endpoint stored by evaluation_points(). A later fix must
// keep the default sampling at or below this count (widen the step, or fail
// the element) for every path listed above.
constexpr std::size_t kMaxFunctionSamples = 200000;

// ceil(100010 / 0.5) + 1 = 200021, just past the cap. The reported 5e8 m
// segment is the same division; this length is large enough to prove the
// count is not clamped and small enough that the uncapped allocation can
// finish and fail the assertion.
constexpr const char* kOverlongMetres = "100010.";
constexpr const char* kShortMetres = "10.";
// ceil(3e9 / 0.5) = 6e9, which does not fit in a 32-bit unsigned step count.
constexpr const char* kOversizedMetres = "3.E9";
constexpr const char* kNonFiniteMetres = "1.E999";

std::string replace_all(std::string text, const std::string& from, const std::string& to) {
    std::size_t at = 0;
    while ((at = text.find(from, at)) != std::string::npos) {
        text.replace(at, from.size(), to);
        at += to.size();
    }
    return text;
}

std::string alignment_spf(const std::string& length_literal) {
    const char* source = R"IFC(ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('','',(''),(''),'','','');
FILE_SCHEMA(('IFC4X3_ADD2'));
ENDSEC;
DATA;
#1=IFCPROJECT('0RYK8PV8D0ee9DDm77xcTZ',$,'curve-step-cap',$,$,$,$,(#6),#100);
#100=IFCUNITASSIGNMENT((#101,#102));
#101=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#102=IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.);
#2=IFCCARTESIANPOINT((0.,0.,0.));
#3=IFCDIRECTION((0.,0.,1.));
#4=IFCDIRECTION((1.,0.,0.));
#5=IFCAXIS2PLACEMENT3D(#2,#3,#4);
#6=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#5,$);
#7=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#6,$,.MODEL_VIEW.,$);
#8=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Axis','Model',*,*,*,*,#6,$,.MODEL_VIEW.,$);
#10=IFCCARTESIANPOINT((0.,0.));
#11=IFCDIRECTION((1.,0.));
#12=IFCAXIS2PLACEMENT2D(#10,#11);
#13=IFCCARTESIANPOINT((0.,0.));
#14=IFCDIRECTION((1.,0.));
#15=IFCVECTOR(#14,1.);
#16=IFCLINE(#13,#15);
#17=IFCCURVESEGMENT(.CONTSAMEGRADIENT.,#12,IFCLENGTHMEASURE(0.),IFCLENGTHMEASURE(@LEN@),#16);
#18=IFCCOMPOSITECURVE((#17),.F.);
#20=IFCCARTESIANPOINT((0.,0.));
#21=IFCDIRECTION((1.,0.));
#22=IFCAXIS2PLACEMENT2D(#20,#21);
#23=IFCCARTESIANPOINT((0.,0.));
#24=IFCDIRECTION((1.,0.));
#25=IFCVECTOR(#24,1.);
#26=IFCLINE(#23,#25);
#27=IFCCURVESEGMENT(.CONTSAMEGRADIENT.,#22,IFCLENGTHMEASURE(0.),IFCLENGTHMEASURE(@LEN@),#26);
#28=IFCGRADIENTCURVE((#27),.F.,#18,$);
#30=IFCCARTESIANPOINT((0.,0.));
#31=IFCDIRECTION((1.,0.));
#32=IFCAXIS2PLACEMENT2D(#30,#31);
#33=IFCCARTESIANPOINT((0.,0.));
#34=IFCDIRECTION((1.,0.));
#35=IFCVECTOR(#34,1.);
#36=IFCLINE(#33,#35);
#37=IFCCURVESEGMENT(.CONTSAMEGRADIENT.,#32,IFCLENGTHMEASURE(0.),IFCLENGTHMEASURE(@LEN@),#36);
#38=IFCSEGMENTEDREFERENCECURVE((#37),.F.,#28,$);
#40=IFCPOINTBYDISTANCEEXPRESSION(IFCLENGTHMEASURE(0.),0.,0.,$,#18);
#41=IFCPOINTBYDISTANCEEXPRESSION(IFCLENGTHMEASURE(@LEN@),1.,0.,$,#18);
#42=IFCOFFSETCURVEBYDISTANCES(#18,(#40,#41),$);
#50=IFCCARTESIANPOINT((0.,0.));
#51=IFCDIRECTION((1.,0.));
#52=IFCAXIS2PLACEMENT2D(#50,#51);
#53=IFCRECTANGLEPROFILEDEF(.AREA.,$,#52,1.,1.);
#54=IFCDIRECTION((0.,0.,1.));
#55=IFCFIXEDREFERENCESWEPTAREASOLID(#53,$,#18,$,$,#54);
#60=IFCPOINTBYDISTANCEEXPRESSION(IFCLENGTHMEASURE(0.),$,$,$,#18);
#61=IFCAXIS2PLACEMENTLINEAR(#60,$,$);
#62=IFCPOINTBYDISTANCEEXPRESSION(IFCLENGTHMEASURE(@LEN@),$,$,$,#18);
#63=IFCAXIS2PLACEMENTLINEAR(#62,$,$);
#64=IFCSECTIONEDSOLIDHORIZONTAL(#18,(#53,#53),(#61,#63));
#70=IFCSHAPEREPRESENTATION(#8,'Curve','Curve3D',(#18));
#71=IFCSHAPEREPRESENTATION(#8,'Gradient','Curve3D',(#28));
#72=IFCSHAPEREPRESENTATION(#8,'Cant','Curve3D',(#38));
#73=IFCSHAPEREPRESENTATION(#8,'Offset','Curve3D',(#42));
#74=IFCSHAPEREPRESENTATION(#7,'Sweep','AdvancedSweptSolid',(#55));
#75=IFCSHAPEREPRESENTATION(#7,'Sectioned','AdvancedSweptSolid',(#64));
#80=IFCPRODUCTDEFINITIONSHAPE($,$,(#70));
#81=IFCPRODUCTDEFINITIONSHAPE($,$,(#71));
#82=IFCPRODUCTDEFINITIONSHAPE($,$,(#72));
#83=IFCPRODUCTDEFINITIONSHAPE($,$,(#73));
#84=IFCPRODUCTDEFINITIONSHAPE($,$,(#74));
#85=IFCPRODUCTDEFINITIONSHAPE($,$,(#75));
#90=IFCBUILDINGELEMENTPROXY('3cWcr4$892GAeKwryhDIL1',$,'curve',$,$,$,$,#80,$);
#91=IFCBUILDINGELEMENTPROXY('3cWcr4$892GAeKwryhDIL2',$,'gradient',$,$,$,$,#81,$);
#92=IFCBUILDINGELEMENTPROXY('3cWcr4$892GAeKwryhDIL3',$,'cant',$,$,$,$,#82,$);
#93=IFCBUILDINGELEMENTPROXY('3cWcr4$892GAeKwryhDIL4',$,'offset',$,$,$,$,#83,$);
#94=IFCBUILDINGELEMENTPROXY('3cWcr4$892GAeKwryhDIL5',$,'sweep',$,$,$,$,#84,$);
#95=IFCBUILDINGELEMENTPROXY('3cWcr4$892GAeKwryhDIL6',$,'sectioned',$,$,$,$,#85,$);
ENDSEC;
END-ISO-10303-21;
)IFC";
    return replace_all(source, "@LEN@", length_literal);
}

struct opened_model {
    ifcopenshell::logger log;
    std::unique_ptr<ifcopenshell::file> file;

    explicit opened_model(const std::string& spf) {
        log.output_format(ifcopenshell::logger::FMT_INMEMORY);
        std::istringstream stream(spf);
        file = std::make_unique<ifcopenshell::file>(stream, static_cast<int>(spf.size()), log);
    }
};

struct sample_result {
    bool refused = false;
    bool allocation_exhausted = false;
    std::size_t samples = 0;
};

class address_space_limit {
  public:
    explicit address_space_limit(rlim_t extra_bytes) {
        getrlimit(RLIMIT_AS, &previous_);
        rlimit narrowed = previous_;
        narrowed.rlim_cur = resident_bytes() + extra_bytes;
        if (narrowed.rlim_max != RLIM_INFINITY && narrowed.rlim_cur > narrowed.rlim_max) {
            narrowed.rlim_cur = narrowed.rlim_max;
        }
        setrlimit(RLIMIT_AS, &narrowed);
    }

    ~address_space_limit() { setrlimit(RLIMIT_AS, &previous_); }

  private:
    static rlim_t resident_bytes() {
        std::ifstream status("/proc/self/status");
        std::string key;
        while (status >> key) {
            if (key == "VmSize:") {
                rlim_t kibibytes = 0;
                status >> kibibytes;
                return kibibytes * 1024;
            }
            status.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
        }
        return 256ull * 1024ull * 1024ull;
    }

    rlimit previous_{};
};

sample_result count_samples(
    const ifcopenshell::geom::settings& settings,
    const ifcopenshell::geom::taxonomy::function_item::ptr& function) {
    sample_result result;
    try {
        ifcopenshell::geom::function_item_evaluator evaluator(settings, function);
        result.samples = evaluator.evaluation_points().size();
    } catch (const std::bad_alloc&) {
        result.allocation_exhausted = true;
    } catch (const std::exception&) {
        result.refused = true;
    }
    return result;
}

void require_bounded(const sample_result& result) {
    CHECK_FALSE(result.allocation_exhausted);
    if (!result.allocation_exhausted && !result.refused) {
        CHECK(result.samples <= kMaxFunctionSamples);
    }
}

ifcopenshell::geom::settings curve_settings() {
    ifcopenshell::geom::settings settings;
    auto dimensionality = settings.get<ifcopenshell::geom::settings::OutputDimensionality>();
    dimensionality.value = ifcopenshell::geom::settings::CURVES_SURFACES_AND_SOLIDS;
    settings.set(dimensionality);
    return settings;
}

ifcopenshell::geom::settings solid_settings() {
    return {};
}

struct converted {
    ifcopenshell::logger log;
    ifcopenshell::geom::settings settings;
    std::unique_ptr<ifcopenshell::geom::converter> converter;

    converted(ifcopenshell::file* file, ifcopenshell::geom::settings initial)
        : settings(std::move(initial)) {
        log.output_format(ifcopenshell::logger::FMT_INMEMORY);
        converter = std::make_unique<ifcopenshell::geom::converter>(
            ifcopenshell::geom::kernels::construct(file, "passthrough", settings, log),
            file,
            settings,
            log);
    }
};

IfcSchema::IfcShapeRepresentation representation_named(ifcopenshell::file& file, const std::string& identifier) {
    for (auto& representation : file.instances_by_type<IfcSchema::IfcShapeRepresentation>()) {
        const auto name = representation.RepresentationIdentifier();
        if (name && *name == identifier) {
            return representation;
        }
    }
    throw std::runtime_error("missing representation " + identifier);
}

void collect(
    const ifcopenshell::geom::taxonomy::ptr& item,
    std::vector<ifcopenshell::geom::taxonomy::function_item::ptr>& functions,
    std::vector<ifcopenshell::geom::taxonomy::loft::ptr>& lofts) {
    if (!item) {
        return;
    }
    if (auto function = std::dynamic_pointer_cast<ifcopenshell::geom::taxonomy::function_item>(item)) {
        functions.push_back(function);
    }
    if (auto loft = std::dynamic_pointer_cast<ifcopenshell::geom::taxonomy::loft>(item)) {
        lofts.push_back(loft);
    }
    if (auto group = std::dynamic_pointer_cast<ifcopenshell::geom::taxonomy::collection>(item)) {
        for (const auto& child : group->children) {
            collect(child, functions, lofts);
        }
    }
}

struct mapped_geometry {
    std::vector<ifcopenshell::geom::taxonomy::function_item::ptr> functions;
    std::vector<ifcopenshell::geom::taxonomy::loft::ptr> lofts;
    bool refused = false;
    bool allocation_exhausted = false;
};

mapped_geometry map_representation(converted& model, ifcopenshell::file& file, const std::string& identifier) {
    mapped_geometry mapped;
    try {
        auto item = model.converter->mapping()->map(representation_named(file, identifier));
        collect(item, mapped.functions, mapped.lofts);
        if (!item) {
            mapped.refused = true;
        }
    } catch (const std::bad_alloc&) {
        mapped.allocation_exhausted = true;
    } catch (const std::exception&) {
        mapped.refused = true;
    }
    return mapped;
}

void require_bounded_geometry(const mapped_geometry& mapped) {
    CHECK_FALSE(mapped.allocation_exhausted);
    if (mapped.allocation_exhausted || mapped.refused) {
        return;
    }
    for (const auto& loft : mapped.lofts) {
        CHECK(loft->children.size() <= kMaxFunctionSamples);
    }
}

bool schema_is_ifc4x3_add2() {
    return std::string(STRINGIFY(IfcSchema)) == "Ifc4x3_add2";
}

} // namespace

TEST_CASE("Short function curves keep the default half-metre sampling", "[ifcgeom][function-step-cap]") {
    if (!schema_is_ifc4x3_add2()) {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }

    const auto spf = alignment_spf(kShortMetres);
    opened_model model(spf);
    REQUIRE(model.file->good());

    converted curves(model.file.get(), curve_settings());
    for (const char* identifier : {"Curve", "Gradient", "Cant", "Offset"}) {
        INFO(identifier);
        const auto mapped = map_representation(curves, *model.file, identifier);
        REQUIRE_FALSE(mapped.refused);
        REQUIRE(mapped.functions.size() == 1);
        const auto samples = count_samples(curves.settings, mapped.functions.front());
        REQUIRE_FALSE(samples.allocation_exhausted);
        REQUIRE_FALSE(samples.refused);
        // 10 m / 0.5 m, plus the endpoint.
        CHECK(samples.samples == 21);
    }

    converted solids(model.file.get(), solid_settings());
    for (const char* identifier : {"Sweep", "Sectioned"}) {
        INFO(identifier);
        const auto mapped = map_representation(solids, *model.file, identifier);
        REQUIRE_FALSE(mapped.refused);
        REQUIRE(mapped.lofts.size() == 1);
        CHECK(mapped.lofts.front()->children.size() == 21);
    }
}

TEST_CASE("Overlong SegmentLength does not allocate an uncapped sample vector", "[ifcgeom][function-step-cap]") {
    if (!schema_is_ifc4x3_add2()) {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }

    const auto spf = alignment_spf(kOverlongMetres);
    opened_model model(spf);
    REQUIRE(model.file->good());

    converted curves(model.file.get(), curve_settings());
    for (const char* identifier : {"Curve", "Gradient", "Cant", "Offset"}) {
        INFO(identifier);
        const auto mapped = map_representation(curves, *model.file, identifier);
        REQUIRE_FALSE(mapped.allocation_exhausted);
        if (mapped.refused || mapped.functions.empty()) {
            continue;
        }
        const auto samples = count_samples(curves.settings, mapped.functions.front());
        require_bounded(samples);

        // abstract_kernel::convert_impl evaluates this same function item.
        std::vector<ifcopenshell::geom::conversion_result> converted_shape;
        try {
            curves.converter->kernel()->convert(mapped.functions.front(), converted_shape);
        } catch (const std::bad_alloc&) {
            FAIL("kernel conversion allocated the uncapped sample buffer");
        } catch (const std::exception&) {
            converted_shape.clear();
        }
        REQUIRE(converted_shape.size() <= kMaxFunctionSamples);
    }
}

TEST_CASE("Negative SegmentLength is capped after it is made absolute", "[ifcgeom][function-step-cap]") {
    if (!schema_is_ifc4x3_add2()) {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }

    const auto spf = alignment_spf(std::string("-") + kOverlongMetres);
    opened_model model(spf);
    REQUIRE(model.file->good());

    converted curves(model.file.get(), curve_settings());
    const auto mapped = map_representation(curves, *model.file, "Curve");
    REQUIRE_FALSE(mapped.allocation_exhausted);
    if (!mapped.refused && !mapped.functions.empty()) {
        require_bounded(count_samples(curves.settings, mapped.functions.front()));
    }
}

TEST_CASE("Swept solids and infrastructure lofts cap samples from SegmentLength", "[ifcgeom][function-step-cap]") {
    if (!schema_is_ifc4x3_add2()) {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }

    const auto spf = alignment_spf(kOverlongMetres);
    opened_model model(spf);
    REQUIRE(model.file->good());

    converted solids(model.file.get(), solid_settings());
    for (const char* identifier : {"Sweep", "Sectioned"}) {
        INFO(identifier);
        const auto mapped = map_representation(solids, *model.file, identifier);
        require_bounded_geometry(mapped);
        if (!mapped.refused) {
            REQUIRE_FALSE(mapped.lofts.empty());
        }
    }
}

TEST_CASE("Non-finite SegmentLength is rejected before step-count conversion", "[ifcgeom][function-step-cap]") {
    if (!schema_is_ifc4x3_add2()) {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }

    const auto spf = alignment_spf(kNonFiniteMetres);
    opened_model model(spf);
    if (!model.file->good()) {
        // The STEP reader rejects this token before the geometry kernel sees it.
        SUCCEED("parser rejected a non-finite length before geometry evaluation");
        return;
    }

    converted curves(model.file.get(), curve_settings());
    const auto mapped = map_representation(curves, *model.file, "Curve");
    REQUIRE_FALSE(mapped.allocation_exhausted);
    if (mapped.refused || mapped.functions.empty()) {
        SUCCEED("mapping rejected a non-finite length");
        return;
    }
    const auto samples = count_samples(curves.settings, mapped.functions.front());
    REQUIRE_FALSE(samples.allocation_exhausted);
    CHECK((samples.refused || samples.samples == 0));
}

TEST_CASE("Oversized SegmentLength does not cast into an uncapped allocation", "[ifcgeom][function-step-cap]") {
    if (!schema_is_ifc4x3_add2()) {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }

    const auto spf = alignment_spf(kOversizedMetres);
    opened_model model(spf);
    REQUIRE(model.file->good());

    converted curves(model.file.get(), curve_settings());
    const auto mapped = map_representation(curves, *model.file, "Curve");
    REQUIRE_FALSE(mapped.allocation_exhausted);
    if (mapped.refused || mapped.functions.empty()) {
        SUCCEED("mapping rejected an oversized length");
        return;
    }

    // The uncapped cast requests about 1.7e9 doubles on this platform. Keep
    // that allocation from succeeding so the test observes the refusal path
    // instead of spending the host's memory.
    address_space_limit limit(32ull * 1024ull * 1024ull);
    require_bounded(count_samples(curves.settings, mapped.functions.front()));
}
