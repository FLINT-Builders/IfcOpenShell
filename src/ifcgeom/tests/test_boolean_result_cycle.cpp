// This file was generated with the assistance of an AI coding tool.
//
// These tests are expected to fail while cyclic IfcBooleanResult operands are
// still flattened without a bound. They pass once mapping of such a file
// returns, whether the item is converted or rejected.

#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <catch2/catch_test_macros.hpp>

#include "ifcgeom/converter.h"
#include "ifcgeom/iterator.h"
#include "ifcgeom/kernel_registry.h"

#if defined(_WIN32)

TEST_CASE("cyclic IfcBooleanResult operands are bounded", "[ifcgeom][boolean-cycle]") {
    SKIP("POSIX fork is required to stop a mapping call that does not return");
}

#else

#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>

namespace {

std::string ifc_with_body(const std::string& geometry, const std::string& item_list) {
    return "ISO-10303-21;\n"
           "HEADER;\n"
           "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
           "FILE_NAME('cycle.ifc','',(''),(''),'','','');\n"
           "FILE_SCHEMA(('IFC4X3_ADD2'));\n"
           "ENDSEC;\n"
           "DATA;\n"
           "#1=IFCPROJECT('0RYK8PV8D0ee9DDm77xcTZ',$,'T',$,$,$,$,(#6),#103);\n"
           "#2=IFCCARTESIANPOINT((0.,0.,0.));\n"
           "#3=IFCDIRECTION((0.,0.,1.));\n"
           "#4=IFCDIRECTION((1.,0.,0.));\n"
           "#5=IFCAXIS2PLACEMENT3D(#2,#3,#4);\n"
           "#6=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#5,$);\n"
           "#7=IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#6,$,.MODEL_VIEW.,$);\n"
           "#9=IFCBLOCK(#5,1.,1.,1.);\n" +
           geometry +
           "#100=IFCSHAPEREPRESENTATION(#7,'Body','CSG',(" + item_list + "));\n"
           "#101=IFCPRODUCTDEFINITIONSHAPE($,$,(#100));\n"
           "#102=IFCBUILDINGELEMENTPROXY('3cWcr4$892GAeKwryhDILR',$,'proxy',$,$,$,#101,$,$);\n"
           "#103=IFCUNITASSIGNMENT((#104));\n"
           "#104=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);\n"
           "ENDSEC;\n"
           "END-ISO-10303-21;\n";
}

// Drives the same single-threaded iterator path IfcConvert uses. Returns 0 when
// initialize() comes back. Non-zero means the file never reached mapping.
int convert_file(const std::string& spf) {
    std::istringstream stream(spf);
    ifcopenshell::logger log;
    log.output_format(ifcopenshell::logger::FMT_INMEMORY);
    ifcopenshell::file file(stream, static_cast<int>(spf.size()), log);
    if (!file.good()) {
        std::fprintf(stderr, "boolean-cycle: file did not parse\n");
        return 3;
    }

    ifcopenshell::geom::settings settings;
    try {
        ifcopenshell::geom::converter probe(
            ifcopenshell::geom::kernels::construct(&file, "passthrough", settings, log),
            &file,
            settings,
            log);
        std::vector<ifcopenshell::geom::geometry_conversion_task> tasks;
        std::vector<ifcopenshell::geom::filter_function> filters;
        probe.mapping()->get_representations(tasks, filters);
        if (tasks.empty()) {
            std::fprintf(stderr, "boolean-cycle: iterator would not select a representation\n");
            return 4;
        }
    } catch (const std::exception& e) {
        std::fprintf(stderr, "boolean-cycle: setup failed: %s\n", e.what());
        return 5;
    } catch (...) {
        std::fprintf(stderr, "boolean-cycle: setup failed\n");
        return 5;
    }

    try {
        std::vector<ifcopenshell::geom::filter_function> filters;
        ifcopenshell::geom::iterator context_iterator(
            ifcopenshell::geom::kernels::construct(&file, "passthrough", settings, log),
            settings,
            &file,
            filters,
            1,
            log);
        context_iterator.initialize();
        return 0;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "boolean-cycle: mapping ended with: %s\n", e.what());
        return 0;
    } catch (...) {
        return 0;
    }
}

long rss_kb_of(pid_t pid) {
    std::ifstream status("/proc/" + std::to_string(pid) + "/status");
    std::string line;
    while (std::getline(status, line)) {
        if (line.compare(0, 6, "VmRSS:") == 0) {
            return std::strtol(line.c_str() + 6, nullptr, 10);
        }
    }
    return -1;
}

// Empty string means the child finished without unbounded growth.
std::string mapping_is_bounded(const std::string& spf) {
    const pid_t pid = fork();
    if (pid < 0) {
        return "fork failed";
    }
    if (pid == 0) {
        std::signal(SIGSEGV, SIG_DFL);
        std::signal(SIGABRT, SIG_DFL);
        std::signal(SIGBUS, SIG_DFL);
        rlimit core_limit {};
        core_limit.rlim_cur = 0;
        core_limit.rlim_max = 0;
        setrlimit(RLIMIT_CORE, &core_limit);
        alarm(20);
        _exit(convert_file(spf));
    }

    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    long baseline_rss_kb = -1;
    int status = 0;
    while (std::chrono::steady_clock::now() < deadline) {
        const pid_t waited = waitpid(pid, &status, WNOHANG);
        if (waited == pid) {
            if (WIFEXITED(status) && WEXITSTATUS(status) == 0) {
                return {};
            }
            if (WIFEXITED(status)) {
                return "child exited " + std::to_string(WEXITSTATUS(status));
            }
            if (WIFSIGNALED(status)) {
                return "child killed by signal " + std::to_string(WTERMSIG(status));
            }
            return "child did not exit normally";
        }

        const long rss_kb = rss_kb_of(pid);
        if (rss_kb > 0) {
            if (baseline_rss_kb < 0) {
                baseline_rss_kb = rss_kb;
            } else if (rss_kb > baseline_rss_kb + 64 * 1024) {
                kill(pid, SIGKILL);
                waitpid(pid, &status, 0);
                return "operand mapping grew by more than 64MB (" + std::to_string(baseline_rss_kb) + " -> " +
                       std::to_string(rss_kb) + " kB)";
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    const long final_rss_kb = rss_kb_of(pid);
    kill(pid, SIGKILL);
    waitpid(pid, &status, 0);
    return "iterator did not finish within 3s (rss " + std::to_string(baseline_rss_kb) + " -> " +
           std::to_string(final_rss_kb) + " kB)";
}

} // namespace

TEST_CASE("acyclic difference boolean maps", "[ifcgeom][boolean-cycle]") {
    const auto spf = ifc_with_body(
        "#8=IFCBLOCK(#5,2.,2.,2.);\n"
        "#10=IFCBOOLEANRESULT(.DIFFERENCE.,#8,#9);\n",
        "#10");
    const auto failure = mapping_is_bounded(spf);
    REQUIRE(failure == "");
}

TEST_CASE("self-referential difference boolean is bounded", "[ifcgeom][boolean-cycle]") {
    const auto spf = ifc_with_body("#10=IFCBOOLEANRESULT(.DIFFERENCE.,#10,#9);\n", "#10");
    const auto failure = mapping_is_bounded(spf);
    REQUIRE(failure == "");
}

TEST_CASE("mutually referential difference booleans are bounded", "[ifcgeom][boolean-cycle]") {
    const auto spf = ifc_with_body(
        "#10=IFCBOOLEANRESULT(.DIFFERENCE.,#20,#9);\n"
        "#20=IFCBOOLEANRESULT(.DIFFERENCE.,#10,#9);\n",
        "#10");
    const auto failure = mapping_is_bounded(spf);
    REQUIRE(failure == "");
}

TEST_CASE("difference chain that enters a cycle is bounded", "[ifcgeom][boolean-cycle]") {
    const auto spf = ifc_with_body(
        "#10=IFCBOOLEANRESULT(.DIFFERENCE.,#20,#9);\n"
        "#20=IFCBOOLEANRESULT(.DIFFERENCE.,#21,#9);\n"
        "#21=IFCBOOLEANRESULT(.DIFFERENCE.,#20,#9);\n",
        "#10");
    const auto failure = mapping_is_bounded(spf);
    REQUIRE(failure == "");
}

TEST_CASE("self-referential union boolean is bounded", "[ifcgeom][boolean-cycle]") {
    const auto spf = ifc_with_body("#10=IFCBOOLEANRESULT(.UNION.,#10,#9);\n", "#10");
    const auto failure = mapping_is_bounded(spf);
    REQUIRE(failure == "");
}

TEST_CASE("self-referential intersection boolean is bounded", "[ifcgeom][boolean-cycle]") {
    const auto spf = ifc_with_body("#10=IFCBOOLEANRESULT(.INTERSECTION.,#10,#9);\n", "#10");
    const auto failure = mapping_is_bounded(spf);
    REQUIRE(failure == "");
}

TEST_CASE("mutually referential union booleans are bounded", "[ifcgeom][boolean-cycle]") {
    const auto spf = ifc_with_body(
        "#10=IFCBOOLEANRESULT(.UNION.,#20,#9);\n"
        "#20=IFCBOOLEANRESULT(.UNION.,#10,#9);\n",
        "#10");
    const auto failure = mapping_is_bounded(spf);
    REQUIRE(failure == "");
}

TEST_CASE("mutually referential intersection booleans are bounded", "[ifcgeom][boolean-cycle]") {
    const auto spf = ifc_with_body(
        "#10=IFCBOOLEANRESULT(.INTERSECTION.,#20,#9);\n"
        "#20=IFCBOOLEANRESULT(.INTERSECTION.,#10,#9);\n",
        "#10");
    const auto failure = mapping_is_bounded(spf);
    REQUIRE(failure == "");
}

TEST_CASE("self-referential clipping result is bounded", "[ifcgeom][boolean-cycle]") {
    const auto spf = ifc_with_body(
        "#11=IFCPLANE(#5);\n"
        "#12=IFCHALFSPACESOLID(#11,.T.);\n"
        "#10=IFCBOOLEANCLIPPINGRESULT(.DIFFERENCE.,#10,#12);\n",
        "#10");
    const auto failure = mapping_is_bounded(spf);
    REQUIRE(failure == "");
}

TEST_CASE("clipping result with a cyclic block operand is bounded", "[ifcgeom][boolean-cycle]") {
    const auto spf = ifc_with_body(
        "#10=IFCBOOLEANCLIPPINGRESULT(.DIFFERENCE.,#20,#9);\n"
        "#20=IFCBOOLEANRESULT(.DIFFERENCE.,#20,#9);\n",
        "#10");
    const auto failure = mapping_is_bounded(spf);
    REQUIRE(failure == "");
}

#endif
