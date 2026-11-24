// This file was generated with the assistance of an AI coding tool.

// Spec for IfcCurveSegment parent IfcLine lists. curve_segment_evaluator::operator()(IfcLine)
// reads Coordinates()[0], Coordinates()[1], DirectionRatios()[0] and DirectionRatios()[1]
// with no length check. The same reads run for horizontal, vertical and cant segments.
// These tests fail while that stands: an empty list faults a null buffer, and a short
// list fails the bounds check enabled for the mapping plugin. A fixed build must keep
// converting a well-formed line, and for a short list either refuse the segment or
// return only finite geometry that matches the in-range values (missing components
// behave as 0, as the guarded IfcCartesianPoint and IfcDirection mappings do). A
// zero-length direction has to be refused rather than divided into.

#include "ifcgeom/converter.h"
#include "ifcgeom/iterator.h"
#include "ifcgeom/kernel_registry.h"
#include "ifcparse/file.h"

#include <catch2/catch_test_macros.hpp>
#include <cmath>
#include <csignal>
#include <Eigen/Dense>
#include <sstream>
#include <string>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>
#include IFCGEOM_TEST_SCHEMA_HEADER

namespace {

enum class Expectation {
    // A functor is required and places the segment on the line below.
    MatchValidLine,
    // No geometry. A zero-length direction, including an empty list, cannot be returned.
    Refuse,
    // Refusal, or the same placement as the well-formed line. Used when padding the
    // missing component with 0 reproduces that line.
    ValidLineOrRefuse,
    // Refusal, or any finite functor. Used for vertical and cant, where the segment
    // placement replaces the line direction after the unguarded read.
    FiniteOrRefuse,
};

enum class Host {
    Composite,
    Gradient,
    Cant,
};

struct Case {
    const char* name;
    const char* point;
    const char* direction;
    Host host;
    Expectation expectation;
};

constexpr double kLength = 10.0;

// Placement origin (100, 50), parent direction (1, 0), length 10. The parent point is
// normalized away, so a missing Y padded as 0 still lands on this line.
bool is_valid_line(const Eigen::Matrix4d& at_start, const Eigen::Matrix4d& at_end) {
    auto near = [](double a, double b) { return std::abs(a - b) < 1e-6; };
    return at_start.allFinite() && at_end.allFinite() && near(at_start(0, 3), 100.0) && near(at_start(1, 3), 50.0) &&
           near(at_start(2, 3), 0.0) && near(at_start(0, 0), 1.0) && near(at_start(1, 0), 0.0) && near(at_start(2, 0), 0.0) &&
           near(at_end(0, 3), 110.0) && near(at_end(1, 3), 50.0) && near(at_end(2, 3), 0.0) && near(at_end(0, 0), 1.0) &&
           near(at_end(1, 0), 0.0) && near(at_end(2, 0), 0.0);
}

std::string ifc_text(const Case& cs) {
    const char* curve_tail = "";
    const char* base_segments = "";
    if (cs.host == Host::Gradient) {
        curve_tail = ",#40,$";
        base_segments =
            "#32=IFCCARTESIANPOINT((100.,50.));"
            "#33=IFCDIRECTION((1.,0.));"
            "#34=IFCAXIS2PLACEMENT2D(#32,#33);"
            "#35=IFCCARTESIANPOINT((0.,0.));"
            "#36=IFCDIRECTION((1.,0.));"
            "#37=IFCVECTOR(#36,1.);"
            "#38=IFCLINE(#35,#37);"
            "#39=IFCCURVESEGMENT(.CONTINUOUS.,#34,IFCLENGTHMEASURE(0.),IFCLENGTHMEASURE(10.),#38);"
            "#40=IFCCOMPOSITECURVE((#39),.F.);";
    } else if (cs.host == Host::Cant) {
        curve_tail = ",#40,$";
        base_segments =
            "#32=IFCCARTESIANPOINT((100.,50.));"
            "#33=IFCDIRECTION((1.,0.));"
            "#34=IFCAXIS2PLACEMENT2D(#32,#33);"
            "#35=IFCCARTESIANPOINT((0.,0.));"
            "#36=IFCDIRECTION((1.,0.));"
            "#37=IFCVECTOR(#36,1.);"
            "#38=IFCLINE(#35,#37);"
            "#39=IFCCURVESEGMENT(.CONTINUOUS.,#34,IFCLENGTHMEASURE(0.),IFCLENGTHMEASURE(10.),#38);"
            "#40=IFCCOMPOSITECURVE((#39),.F.);";
    }

    const char* curve_type = "IFCCOMPOSITECURVE";
    if (cs.host == Host::Gradient) {
        curve_type = "IFCGRADIENTCURVE";
    } else if (cs.host == Host::Cant) {
        curve_type = "IFCSEGMENTEDREFERENCECURVE";
    }

    std::ostringstream ifc;
    ifc << "ISO-10303-21;\nHEADER;\n"
           "FILE_DESCRIPTION(('ViewDefinition[DesignTransferView]'),'2;1');\n"
           "FILE_NAME('curve-segment-line.ifc','2026-01-01T00:00:00',(),(),'test','test','');\n"
           "FILE_SCHEMA(('IFC4X3_ADD2'));\nENDSEC;\nDATA;\n"
           "#1=IFCORGANIZATION($,'Org',$,$,$);\n"
           "#2=IFCAPPLICATION(#1,'0','Test','Test');\n"
           "#3=IFCPERSON($,'Doe',$,$,$,$,$,$);\n"
           "#4=IFCPERSONANDORGANIZATION(#3,#1,$);\n"
           "#5=IFCOWNERHISTORY(#4,#2,$,.ADDED.,$,$,$,0);\n"
           "#6=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);\n"
           "#7=IFCUNITASSIGNMENT((#6));\n"
           "#8=IFCCARTESIANPOINT((0.,0.,0.));\n"
           "#9=IFCDIRECTION((0.,0.,1.));\n"
           "#10=IFCDIRECTION((1.,0.,0.));\n"
           "#11=IFCAXIS2PLACEMENT3D(#8,#9,#10);\n"
           "#12=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#11,#10);\n"
           "#13=IFCPROJECT('2xwg5dkcT4T8MlEIX1jLjD',#5,'P',$,$,$,$,(#12),#7);\n"
           "#14=IFCCARTESIANPOINT((0.,0.,0.));\n"
           "#15=IFCDIRECTION((0.,0.,1.));\n"
           "#16=IFCDIRECTION((1.,0.,0.));\n"
           "#17=IFCAXIS2PLACEMENT3D(#14,#15,#16);\n"
           "#18=IFCLOCALPLACEMENT($,#17);\n"
        << base_segments << "#20=IFCCARTESIANPOINT((100.,50.));\n"
                            "#21=IFCDIRECTION((1.,0.));\n"
                            "#22=IFCAXIS2PLACEMENT2D(#20,#21);\n"
                            "#23=IFCCARTESIANPOINT("
        << cs.point << ");\n#24=IFCDIRECTION(" << cs.direction
        << ");\n"
           "#25=IFCVECTOR(#24,1.);\n"
           "#26=IFCLINE(#23,#25);\n"
           "#27=IFCCURVESEGMENT(.CONTINUOUS.,#22,IFCLENGTHMEASURE(0.),IFCLENGTHMEASURE(10.),#26);\n"
           "#28="
        << curve_type << "((#27),.F." << curve_tail
        << ");\n"
           "#29=IFCSHAPEREPRESENTATION(#12,'Axis','Curve2D',(#28));\n"
           "#30=IFCPRODUCTDEFINITIONSHAPE($,$,(#29));\n"
           "#31=IFCANNOTATION('3cz3qtLYbCURHSIUoySdUS',#5,'Ann',$,$,#18,#30,$);\n"
           "ENDSEC;\nEND-ISO-10303-21;\n";
    return ifc.str();
}

int fail(const char* message) {
    std::fprintf(stderr, "%s\n", message);
    return 2;
}

bool finite_functor(const ifcopenshell::geom::taxonomy::ptr& mapped) {
    auto fn = std::dynamic_pointer_cast<ifcopenshell::geom::taxonomy::functor_item>(mapped);
    if (!fn) {
        return false;
    }
    return (*fn)(0.0).allFinite() && (*fn)(fn->length()).allFinite();
}

bool valid_line_functor(const ifcopenshell::geom::taxonomy::ptr& mapped) {
    auto fn = std::dynamic_pointer_cast<ifcopenshell::geom::taxonomy::functor_item>(mapped);
    if (!fn || std::abs(fn->length() - kLength) > 1e-6) {
        return false;
    }
    return is_valid_line((*fn)(0.0), (*fn)(fn->length()));
}

int expect_mapped(const ifcopenshell::geom::taxonomy::ptr& mapped, Expectation expectation) {
    if (expectation == Expectation::MatchValidLine) {
        return valid_line_functor(mapped) ? 0 : fail("well-formed IfcLine segment was not mapped onto its line");
    }
    if (expectation == Expectation::Refuse) {
        return mapped ? fail("short or zero direction produced geometry") : 0;
    }
    if (!mapped) {
        return 0;
    }
    if (expectation == Expectation::ValidLineOrRefuse) {
        return valid_line_functor(mapped) ? 0 : fail("short list geometry does not match the in-range components");
    }
    return finite_functor(mapped) ? 0 : fail("segment geometry is not finite");
}

int exercise(const Case& cs) {
    const std::string text = ifc_text(cs);
    ifcopenshell::logger log;
    log.verbosity(ifcopenshell::logger::LOG_ERROR);
    log.output_format(ifcopenshell::logger::FMT_INMEMORY);

    ifcopenshell::file file(static_cast<void*>(const_cast<char*>(text.data())), static_cast<int>(text.size()), log);
    if (!file.good()) {
        return fail("IFC file did not parse");
    }

    auto segments = file.instances_by_type<IfcSchema::IfcCurveSegment>();
    if (segments.empty()) {
        return fail("parser dropped IfcCurveSegment");
    }

    const auto subject = segments.back();
    auto line = subject.ParentCurve().as<IfcSchema::IfcLine>();
    if (!line) {
        return fail("parent curve is not IfcLine");
    }
    const auto coordinates = line.Pnt().Coordinates();
    const auto ratios = line.Dir().Orientation().DirectionRatios();
    const auto point_text = std::string(cs.point);
    const auto direction_text = std::string(cs.direction);
    const std::size_t expected_coordinates = point_text == "()" ? 0 : (point_text == "(7.)" ? 1 : 2);
    const std::size_t expected_ratios = direction_text == "()" ? 0 : (direction_text == "(1.)" || direction_text == "(0.)" ? 1 : 2);
    if (coordinates.size() != expected_coordinates || ratios.size() != expected_ratios) {
        std::fprintf(stderr, "parser stored %zu coordinates and %zu direction ratios\n", coordinates.size(), ratios.size());
        return 3;
    }

    ifcopenshell::geom::settings settings;
    ifcopenshell::geom::converter converter(
        ifcopenshell::geom::kernels::construct(&file, "passthrough", settings, log), &file, settings, log);

    std::vector<ifcopenshell::geom::filter_function> filters;
    std::vector<ifcopenshell::geom::geometry_conversion_task> tasks;
    converter.mapping()->get_representations(tasks, filters);
    if (tasks.empty()) {
        return fail("geometry iterator did not select the annotation representation");
    }

    try {
        for (auto& task : tasks) {
            converter.mapping()->map(task.representation);
        }
        for (auto& segment : segments) {
            const bool base = segments.size() > 1 && segment.id() != subject.id();
            const int status = expect_mapped(converter.mapping()->map(segment), base ? Expectation::MatchValidLine : cs.expectation);
            if (status != 0) {
                return status;
            }
        }
    } catch (const std::exception& ex) {
        if (cs.expectation == Expectation::MatchValidLine) {
            std::fprintf(stderr, "well-formed segment raised %s\n", ex.what());
            return 2;
        }
    }

    try {
        ifcopenshell::geom::iterator iterator(
            ifcopenshell::geom::kernels::construct(&file, "passthrough", settings, log), settings, &file, 1, log);
        // Default dimensionality keeps surfaces and solids, so a curve representation is mapped
        // and then dropped. initialize() still enters that mapping. next() is only valid once an
        // element was produced.
        if (iterator.initialize()) {
            while (iterator.next()) {
            }
        }
    } catch (const std::exception& ex) {
        if (cs.expectation == Expectation::MatchValidLine) {
            std::fprintf(stderr, "iterator raised %s\n", ex.what());
            return 2;
        }
    }
    return 0;
}

int run_child(const Case& cs) {
    const pid_t pid = fork();
    if (pid < 0) {
        return -1;
    }
    if (pid == 0) {
        // The child must die with the raw signal. Catch installed handlers in the parent.
        std::signal(SIGABRT, SIG_DFL);
        std::signal(SIGSEGV, SIG_DFL);
        std::signal(SIGBUS, SIG_DFL);
        const int status = exercise(cs);
        _exit(status);
    }
    int status = 0;
    if (waitpid(pid, &status, 0) < 0) {
        return -1;
    }
    return status;
}

} // namespace

TEST_CASE("IfcCurveSegment IfcLine lists stay in range during geometry conversion", "[geom][curve-segment-line]") {
    const Case cases[] = {
        {"horizontal well-formed line", "(0.,0.)", "(1.,0.)", Host::Composite, Expectation::MatchValidLine},
        {"horizontal empty point", "()", "(1.,0.)", Host::Composite, Expectation::ValidLineOrRefuse},
        {"horizontal one-element point", "(7.)", "(1.,0.)", Host::Composite, Expectation::ValidLineOrRefuse},
        {"horizontal empty direction", "(0.,0.)", "()", Host::Composite, Expectation::Refuse},
        {"horizontal one-element direction", "(0.,0.)", "(1.)", Host::Composite, Expectation::ValidLineOrRefuse},
        {"horizontal one-element zero direction", "(0.,0.)", "(0.)", Host::Composite, Expectation::Refuse},
        {"horizontal zero direction", "(0.,0.)", "(0.,0.)", Host::Composite, Expectation::Refuse},
        {"horizontal empty point and direction", "()", "()", Host::Composite, Expectation::Refuse},
        {"vertical empty point", "()", "(1.,0.)", Host::Gradient, Expectation::FiniteOrRefuse},
        {"vertical one-element direction", "(0.,0.)", "(1.)", Host::Gradient, Expectation::FiniteOrRefuse},
        {"cant one-element point", "(7.)", "(1.,0.)", Host::Cant, Expectation::FiniteOrRefuse},
        {"cant empty direction", "(0.,0.)", "()", Host::Cant, Expectation::Refuse},
    };

    for (const auto& cs : cases) {
        const int status = run_child(cs);
        INFO(cs.name);
        if (status < 0) {
            FAIL("failed to run case");
        }
        const bool clean = WIFEXITED(status) && WEXITSTATUS(status) == 0;
        if (!clean) {
            if (WIFSIGNALED(status)) {
                std::fprintf(stderr, "%s: signal %d\n", cs.name, WTERMSIG(status));
            } else if (WIFEXITED(status)) {
                std::fprintf(stderr, "%s: exit %d\n", cs.name, WEXITSTATUS(status));
            }
        }
        CHECK(clean);
    }
}
