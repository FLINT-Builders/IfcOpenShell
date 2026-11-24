// This file was generated with the assistance of an AI coding tool.

// IfcCurveSegment only builds a parent-curve function for a fixed list of
// curve types. For every other ParentCurve, and for the identity fallback
// used when a supported type is applied to cant, mapping logs and continues
// with a null function and/or an empty start point. Evaluating that segment
// calls through the null function. These tests run that evaluation through
// the geometry converter. They pass only when the file is rejected without
// terminating the process and without producing evaluated geometry.

#include "ifcgeom/converter.h"
#include "ifcgeom/function_item_evaluator.h"
#include "ifcgeom/iterator.h"
#include "ifcgeom/kernel_registry.h"

#include <catch2/catch_test_macros.hpp>
#include <csignal>
#include <sstream>
#include <string>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>
#include IFCGEOM_TEST_SCHEMA_HEADER

namespace {

constexpr const char* MODEL_PREFIX = R"IFC(ISO-10303-21;
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
#9=IFCDIRECTION((0.,0.,1.));
#10=IFCDIRECTION((1.,0.,0.));
#11=IFCAXIS2PLACEMENT3D(#8,#9,#10);
#12=IFCCARTESIANPOINT((0.,0.));
#13=IFCDIRECTION((1.,0.));
#14=IFCAXIS2PLACEMENT2D(#12,#13);
)IFC";

constexpr const char* PROFILE = R"IFC(
#30=IFCCARTESIANPOINTLIST2D(((-0.5,0.),(0.5,0.),(0.5,1.),(-0.5,1.),(-0.5,0.)),$);
#31=IFCINDEXEDPOLYCURVE(#30,$,.F.);
#32=IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#31);
)IFC";

std::string finish(const std::string& body) {
    return std::string(MODEL_PREFIX) + PROFILE + body + "ENDSEC;\nEND-ISO-10303-21;\n";
}

std::string segment(int id, int parent, const char* length = "40.") {
    return "#" + std::to_string(id) +
           "=IFCCURVESEGMENT(.CONTINUOUS.,#11,IFCLENGTHMEASURE(0.),IFCLENGTHMEASURE(" + length + "),#" +
           std::to_string(parent) + ");\n";
}

std::string sectioned_on(int directrix) {
    const std::string d = std::to_string(directrix);
    return "#60=IFCDIRECTION((0.,0.,1.));\n"
           "#61=IFCDIRECTION((1.,0.,0.));\n"
           "#62=IFCPOINTBYDISTANCEEXPRESSION(IFCLENGTHMEASURE(0.),$,$,$,#" +
           d +
           ");\n"
           "#63=IFCPOINTBYDISTANCEEXPRESSION(IFCLENGTHMEASURE(40.),$,$,$,#" +
           d +
           ");\n"
           "#64=IFCAXIS2PLACEMENTLINEAR(#62,#60,#61);\n"
           "#65=IFCAXIS2PLACEMENTLINEAR(#63,#60,#61);\n"
           "#66=IFCSECTIONEDSOLIDHORIZONTAL(#" +
           d +
           ",(#32,#32),(#64,#65));\n"
           "#67=IFCSHAPEREPRESENTATION(#7,'Body','AdvancedSweptSolid',(#66));\n"
           "#68=IFCPRODUCTDEFINITIONSHAPE($,$,(#67));\n"
           "#69=IFCBUILDINGELEMENTPROXY('3cWcr4$892GAeKwryhDILR',$,'span',$,$,#11,#68,$,$);\n";
}

std::string line_parent() {
    return "#20=IFCCARTESIANPOINT((0.,0.));\n"
           "#21=IFCDIRECTION((1.,0.));\n"
           "#22=IFCVECTOR(#21,1.);\n"
           "#23=IFCLINE(#20,#22);\n" +
           segment(24, 23) + "#40=IFCCOMPOSITECURVE((#24),.F.);\n";
}

std::string polyline_parent() {
    return "#20=IFCCARTESIANPOINT((0.,0.));\n"
           "#21=IFCCARTESIANPOINT((40.,0.));\n"
           "#23=IFCPOLYLINE((#20,#21));\n" +
           segment(24, 23) + "#40=IFCCOMPOSITECURVE((#24),.F.);\n";
}

std::string ellipse_parent() {
    return "#23=IFCELLIPSE(#14,5.,3.);\n" + segment(24, 23, "4.") + "#40=IFCCOMPOSITECURVE((#24),.F.);\n";
}

std::string bspline_parent() {
    return "#20=IFCCARTESIANPOINT((0.,0.));\n"
           "#21=IFCCARTESIANPOINT((20.,5.));\n"
           "#22=IFCCARTESIANPOINT((40.,0.));\n"
           "#23=IFCBSPLINECURVEWITHKNOTS(2,(#20,#21,#22),.UNSPECIFIED.,.F.,.F.,(3,3),(0.,1.),.UNSPECIFIED.);\n" +
           segment(24, 23) + "#40=IFCCOMPOSITECURVE((#24),.F.);\n";
}

std::string gradient_with_vertical(const std::string& vertical_parent) {
    return line_parent() + vertical_parent + segment(44, 43) +
           "#45=IFCGRADIENTCURVE((#44),.F.,#40,$);\n";
}

std::string polyline_gradient() {
    return gradient_with_vertical("#41=IFCCARTESIANPOINT((0.,0.));\n"
                                  "#42=IFCCARTESIANPOINT((40.,1.));\n"
                                  "#43=IFCPOLYLINE((#41,#42));\n");
}

std::string cant_over_gradient(const std::string& cant_parent, int parent_id) {
    return line_parent() +
           "#41=IFCCARTESIANPOINT((0.,0.));\n"
           "#42=IFCDIRECTION((1.,0.));\n"
           "#46=IFCVECTOR(#42,1.);\n"
           "#47=IFCLINE(#41,#46);\n" +
           segment(44, 47) + "#45=IFCGRADIENTCURVE((#44),.F.,#40,$);\n" + cant_parent + segment(54, parent_id) +
           "#55=IFCSEGMENTEDREFERENCECURVE((#54),.F.,#45,$);\n";
}

void force_evaluate(const ifcopenshell::geom::settings& settings, const ifcopenshell::geom::taxonomy::ptr& item) {
    if (!item) {
        return;
    }
    if (auto fn = std::dynamic_pointer_cast<ifcopenshell::geom::taxonomy::function_item>(item)) {
        ifcopenshell::geom::function_item_evaluator evaluator(settings, fn);
        for (double u : evaluator.evaluation_points()) {
            (void)evaluator.evaluate(u);
        }
        return;
    }
    if (auto col = std::dynamic_pointer_cast<ifcopenshell::geom::taxonomy::collection>(item)) {
        for (auto& child : col->children) {
            force_evaluate(settings, child);
        }
    }
}

// 0: geometry was refused (exception or no mapped item).
// 1: a representation was mapped and every function item on it was evaluated.
// 3: the file was not selected for conversion, or it did not parse.
int convert_file(const std::string& spf, bool include_curves) {
    try {
        std::istringstream stream(spf);
        ifcopenshell::logger log;
        log.output_format(ifcopenshell::logger::FMT_INMEMORY);
        ifcopenshell::file file(stream, static_cast<int>(spf.size()), log);
        if (!file.good()) {
            return 3;
        }

        ifcopenshell::geom::settings settings;
        if (include_curves) {
            // Set the enumerator directly. settings::set(string) only accepts
            // the stored type, so a dimensionality name never reaches the kernel.
            settings.get<ifcopenshell::geom::settings::OutputDimensionality>().value =
                ifcopenshell::geom::settings::CURVES_SURFACES_AND_SOLIDS;
        }

        ifcopenshell::geom::iterator it(
            ifcopenshell::geom::kernels::construct(&file, "passthrough", settings, log),
            settings,
            &file,
            1,
            log);
        const bool initialized = it.initialize();
        if (initialized && !it.had_error_processing_elements()) {
            return 1;
        }

        // The iterator reports a failed element without publishing geometry.
        // Map the same representation once more and evaluate any function item
        // that was still returned. A parent curve that was only logged as
        // unsupported is invoked here.
        ifcopenshell::geom::converter converter(
            ifcopenshell::geom::kernels::construct(&file, "passthrough", settings, log), &file, settings, log);
        std::vector<ifcopenshell::geom::geometry_conversion_task> tasks;
        std::vector<ifcopenshell::geom::filter_function> filters;
        converter.mapping()->get_representations(tasks, filters);
        if (tasks.empty()) {
            return 3;
        }

        bool evaluated = false;
        for (const auto& task : tasks) {
            auto item = converter.mapping()->map(task.representation);
            if (!item) {
                continue;
            }
            force_evaluate(settings, item);
            if (!task.products.empty()) {
                delete converter.create_brep_for_representation_and_product(task.representation, task.products.front());
            }
            evaluated = true;
        }
        return evaluated ? 1 : 0;
    } catch (const std::exception&) {
        return 0;
    } catch (...) {
        return 0;
    }
}

int run_child(const std::string& spf, bool include_curves) {
    const pid_t pid = fork();
    if (pid < 0) {
        return -1;
    }
    if (pid == 0) {
        std::signal(SIGSEGV, SIG_DFL);
        std::signal(SIGBUS, SIG_DFL);
        std::signal(SIGABRT, SIG_DFL);
        const int code = convert_file(spf, include_curves);
        _exit(code);
    }
    int status = 0;
    if (waitpid(pid, &status, 0) < 0) {
        return -1;
    }
    return status;
}

void require_rejected(const std::string& spf, bool include_curves = false) {
    const int status = run_child(spf, include_curves);
    REQUIRE(status >= 0);
    INFO("child status " << status);
    REQUIRE(WIFEXITED(status));
    REQUIRE(WEXITSTATUS(status) == 0);
}

void require_evaluated(const std::string& spf, bool include_curves = false) {
    const int status = run_child(spf, include_curves);
    REQUIRE(status >= 0);
    INFO("child status " << status);
    REQUIRE(WIFEXITED(status));
    REQUIRE(WEXITSTATUS(status) == 1);
}

} // namespace

TEST_CASE("supported IfcLine parent curve segment evaluates", "[ifcgeom][curve-segment]") {
    if (std::string(STRINGIFY(IfcSchema)) != "Ifc4x3_add2") {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }
    require_evaluated(finish(line_parent() + sectioned_on(40)));
}

TEST_CASE("IfcPolyline parent curve segment is rejected without a crash", "[ifcgeom][curve-segment]") {
    if (std::string(STRINGIFY(IfcSchema)) != "Ifc4x3_add2") {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }
    require_rejected(finish(polyline_parent() + sectioned_on(40)));
}

TEST_CASE("IfcEllipse parent curve segment is rejected without a crash", "[ifcgeom][curve-segment]") {
    if (std::string(STRINGIFY(IfcSchema)) != "Ifc4x3_add2") {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }
    require_rejected(finish(ellipse_parent() + sectioned_on(40)));
}

TEST_CASE("IfcBSplineCurve parent curve segment is rejected without a crash", "[ifcgeom][curve-segment]") {
    if (std::string(STRINGIFY(IfcSchema)) != "Ifc4x3_add2") {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }
    require_rejected(finish(bspline_parent() + sectioned_on(40)));
}

TEST_CASE("curve representation with an IfcPolyline parent is rejected without a crash", "[ifcgeom][curve-segment]") {
    if (std::string(STRINGIFY(IfcSchema)) != "Ifc4x3_add2") {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }
    const std::string body = polyline_parent() +
                             "#67=IFCSHAPEREPRESENTATION(#7,'Axis','Curve3D',(#40));\n"
                             "#68=IFCPRODUCTDEFINITIONSHAPE($,$,(#67));\n"
                             "#69=IFCBUILDINGELEMENTPROXY('3cWcr4$892GAeKwryhDILR',$,'axis',$,$,#11,#68,$,$);\n";
    require_rejected(finish(body), true);
}

TEST_CASE("IfcFixedReferenceSweptAreaSolid with an IfcPolyline directrix segment is rejected without a crash", "[ifcgeom][curve-segment]") {
    if (std::string(STRINGIFY(IfcSchema)) != "Ifc4x3_add2") {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }
    const std::string body = polyline_parent() +
                             "#60=IFCDIRECTION((0.,0.,1.));\n"
                             "#66=IFCFIXEDREFERENCESWEPTAREASOLID(#32,#11,#40,IFCLENGTHMEASURE(0.),IFCLENGTHMEASURE(40.),#60);\n"
                             "#67=IFCSHAPEREPRESENTATION(#7,'Body','AdvancedSweptSolid',(#66));\n"
                             "#68=IFCPRODUCTDEFINITIONSHAPE($,$,(#67));\n"
                             "#69=IFCBUILDINGELEMENTPROXY('3cWcr4$892GAeKwryhDILR',$,'sweep',$,$,#11,#68,$,$);\n";
    require_rejected(finish(body));
}

TEST_CASE("IfcGradientCurve vertical IfcPolyline segment is rejected without a crash", "[ifcgeom][curve-segment]") {
    if (std::string(STRINGIFY(IfcSchema)) != "Ifc4x3_add2") {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }
    require_rejected(finish(polyline_gradient() + sectioned_on(45)));
}

TEST_CASE("cant IfcPolyline parent is rejected without a crash", "[ifcgeom][curve-segment]") {
    if (std::string(STRINGIFY(IfcSchema)) != "Ifc4x3_add2") {
        SKIP("fixture is authored for IFC4X3_ADD2");
    }
    const std::string parent = "#50=IFCCARTESIANPOINT((0.,0.));\n"
                               "#51=IFCCARTESIANPOINT((40.,0.));\n"
                               "#53=IFCPOLYLINE((#50,#51));\n";
    require_rejected(finish(cant_over_gradient(parent, 53) + sectioned_on(55)));
}
