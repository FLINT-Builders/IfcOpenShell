// This file was generated with the assistance of an AI coding tool.
//
// These tests are the spec for cycle protection in the C++ IFC helpers.
// They fail while a cyclic relationship is followed with no visited set and
// no depth limit, because that recursion overflows the stack (or, if a call
// is tail-optimised, never returns). Catching std::exception does not stop
// either outcome. They pass once each call returns or throws std::exception,
// including ifcopenshell::exception, and acyclic relationships still resolve.

#include "element.h"
#include "placement.h"
#include "pset.h"

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <chrono>
#include <cstdint>
#include <functional>
#include <ifcparse/exception.h>
#include <ifcparse/express.h>
#include <ifcparse/file.h>
#include <pthread.h>
#include <signal.h>
#include <sstream>
#include <string>
#include <sys/resource.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace {

constexpr std::size_t kProbeStackBytes = 512 * 1024;
constexpr int kProbeTimeoutSeconds = 2;

const char* kHeader =
    "ISO-10303-21;\n"
    "HEADER;\n"
    "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
    "FILE_NAME('','1970-01-01T00:00:00',(''),(''),'','','');\n"
    "FILE_SCHEMA(('IFC4'));\n"
    "ENDSEC;\n"
    "DATA;\n";

const char* kFooter =
    "ENDSEC;\n"
    "END-ISO-10303-21;\n";

std::unique_ptr<ifcopenshell::file> open_ifc(const std::string& data) {
    const std::string text = std::string(kHeader) + data + kFooter;
    std::istringstream stream(text);
    auto file = std::make_unique<ifcopenshell::file>(stream, static_cast<int>(text.size()));
    return file;
}

express::base must_instance(ifcopenshell::file& file, int id) {
    express::base instance = file.instance_by_id(id);
    REQUIRE(instance);
    return instance;
}

// The worker runs on a fresh thread with a small stack. A returned value or a
// thrown std::exception ends the process; a stack overflow is delivered as
// SIGSEGV to the process and is not catchable as std::exception.
void* run_probe(void* arg) {
    auto* call = static_cast<std::function<void()>*>(arg);
    try {
        (*call)();
        _exit(0);
    } catch (const std::exception&) {
        _exit(1);
    } catch (...) {
        _exit(2);
    }
}

struct probe_result {
    bool terminated = false;
    const char* how = "setup";
    int detail = 0;
};

template <typename Fn>
probe_result invoke_isolated(Fn&& fn) {
    const pid_t pid = fork();
    if (pid < 0) {
        return {false, "fork", errno};
    }
    if (pid == 0) {
        signal(SIGSEGV, SIG_DFL);
        signal(SIGBUS, SIG_DFL);
        signal(SIGABRT, SIG_DFL);
        const struct rlimit no_core = {0, 0};
        setrlimit(RLIMIT_CORE, &no_core);

        std::function<void()> call(std::forward<Fn>(fn));
        pthread_attr_t attr;
        if (pthread_attr_init(&attr) != 0) {
            _exit(3);
        }
        if (pthread_attr_setstacksize(&attr, kProbeStackBytes) != 0) {
            _exit(4);
        }
        pthread_t thread;
        if (pthread_create(&thread, &attr, run_probe, &call) != 0) {
            _exit(5);
        }
        pthread_attr_destroy(&attr);
        for (;;) {
            pause();
        }
    }

    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(kProbeTimeoutSeconds);
    int status = 0;
    for (;;) {
        const pid_t waited = waitpid(pid, &status, WNOHANG);
        if (waited == pid) {
            if (WIFEXITED(status)) {
                const int code = WEXITSTATUS(status);
                if (code == 0) {
                    return {true, "returned", 0};
                }
                if (code == 1) {
                    return {true, "threw-std-exception", 0};
                }
                return {false, "probe-setup", code};
            }
            if (WIFSIGNALED(status)) {
                return {false, "signal", WTERMSIG(status)};
            }
            return {false, "wait-status", status};
        }
        if (waited < 0) {
            return {false, "wait", errno};
        }
        if (std::chrono::steady_clock::now() >= deadline) {
            kill(pid, SIGKILL);
            waitpid(pid, &status, 0);
            return {false, "timeout", 0};
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
}

void require_terminates(const std::function<void()>& call) {
    const probe_result result = invoke_isolated(call);
    UNSCOPED_INFO("isolated call ended by " << result.how << " detail=" << result.detail);
    CHECK(result.terminated);
}

// The spatial panel walks IfcProject's spatial children and reads each
// storey's elevation while it builds the tree. This is that walk without Qt.
void load_spatial_tree(ifcopenshell::file& file) {
    for (const auto& project : file.instances_by_type("IfcProject")) {
        for (const auto& child : get_spatial_children(project)) {
            if (child.declaration().is("IfcBuildingStorey")) {
                (void)get_storey_elevation(child);
            }
            for (const auto& grandchild : get_spatial_children(child)) {
                if (grandchild.declaration().is("IfcBuildingStorey")) {
                    (void)get_storey_elevation(grandchild);
                }
            }
        }
    }
}

const property_value* map_at(const property_map& map, const std::string& key) {
    const auto it = map.find(key);
    return it == map.end() ? nullptr : &it->second;
}

} // namespace

TEST_CASE("An acyclic placement chain composes the storey elevation", "[helpers][cycle]") {
    // Parent placement at z=3, storey placement relative to it at z=4.
    auto file = open_ifc(
        "#1=IFCPROJECT('0123456789012345678901',$,'Project',$,$,$,$,$,$);\n"
        "#2=IFCRELAGGREGATES('0123456789012345678902',$,$,$,#1,(#3));\n"
        "#3=IFCBUILDINGSTOREY('0123456789012345678903',$,'Level',$,$,#5,$,$,$,$);\n"
        "#4=IFCLOCALPLACEMENT($,#6);\n"
        "#5=IFCLOCALPLACEMENT(#4,#7);\n"
        "#6=IFCAXIS2PLACEMENT3D(#8,$,$);\n"
        "#7=IFCAXIS2PLACEMENT3D(#9,$,$);\n"
        "#8=IFCCARTESIANPOINT((0.,0.,3.));\n"
        "#9=IFCCARTESIANPOINT((0.,0.,4.));\n");
    REQUIRE(file->good());

    const express::base storey = must_instance(*file, 3);
    const express::base child = must_instance(*file, 5);
    const express::base parent = child.get_attribute_value(0);
    REQUIRE(parent);
    CHECK(parent.id() == 4);

    const Eigen::Matrix4d placed = get_local_placement(child);
    CHECK(placed(2, 3) == Catch::Approx(7.0));
    CHECK(get_storey_elevation(storey) == Catch::Approx(7.0));
    load_spatial_tree(*file);
}

TEST_CASE("Two local placements that cite each other terminate", "[helpers][cycle]") {
    auto file = open_ifc(
        "#1=IFCPROJECT('0123456789012345678911',$,'Project',$,$,$,$,$,$);\n"
        "#2=IFCRELAGGREGATES('0123456789012345678912',$,$,$,#1,(#3));\n"
        "#3=IFCBUILDINGSTOREY('0123456789012345678913',$,'Level',$,$,#4,$,$,$,$);\n"
        "#4=IFCLOCALPLACEMENT(#5,#6);\n"
        "#5=IFCLOCALPLACEMENT(#4,#7);\n"
        "#6=IFCAXIS2PLACEMENT3D(#8,$,$);\n"
        "#7=IFCAXIS2PLACEMENT3D(#9,$,$);\n"
        "#8=IFCCARTESIANPOINT((0.,0.,3.));\n"
        "#9=IFCCARTESIANPOINT((0.,0.,4.));\n");
    REQUIRE(file->good());

    const express::base storey = must_instance(*file, 3);
    const express::base first = must_instance(*file, 4);
    const express::base second = first.get_attribute_value(0);
    REQUIRE(second);
    CHECK(second.id() == 5);
    const express::base back = second.get_attribute_value(0);
    REQUIRE(back);
    CHECK(back.id() == 4);

    ifcopenshell::file* raw = file.get();
    require_terminates([raw] { load_spatial_tree(*raw); });
    require_terminates([storey] { (void)get_storey_elevation(storey); });
    require_terminates([first] { (void)get_local_placement(first); });
}

TEST_CASE("A local placement that cites itself terminates", "[helpers][cycle]") {
    auto file = open_ifc(
        "#1=IFCPROJECT('0123456789012345678921',$,'Project',$,$,$,$,$,$);\n"
        "#2=IFCRELAGGREGATES('0123456789012345678922',$,$,$,#1,(#3));\n"
        "#3=IFCBUILDINGSTOREY('0123456789012345678923',$,'Level',$,$,#4,$,$,$,$);\n"
        "#4=IFCLOCALPLACEMENT(#4,#5);\n"
        "#5=IFCAXIS2PLACEMENT3D(#6,$,$);\n"
        "#6=IFCCARTESIANPOINT((0.,0.,3.));\n");
    REQUIRE(file->good());

    const express::base storey = must_instance(*file, 3);
    const express::base placement = must_instance(*file, 4);
    const express::base relto = placement.get_attribute_value(0);
    REQUIRE(relto);
    CHECK(relto.id() == placement.id());

    ifcopenshell::file* raw = file.get();
    require_terminates([raw] { load_spatial_tree(*raw); });
    require_terminates([storey] { (void)get_storey_elevation(storey); });
    require_terminates([placement] { (void)get_local_placement(placement); });
}

TEST_CASE("An aggregated part resolves to its parent's container", "[helpers][cycle]") {
    // Wall A is aggregated by wall B. Wall B is contained in the storey.
    // Wall A has no ContainedInStructure, so get_container walks the aggregate.
    auto file = open_ifc(
        "#1=IFCBUILDINGSTOREY('0123456789012345678931',$,'Level',$,$,$,$,$,$,$);\n"
        "#2=IFCWALL('0123456789012345678932',$,'Part',$,$,$,$,$,$);\n"
        "#3=IFCWALL('0123456789012345678933',$,'Whole',$,$,$,$,$,$);\n"
        "#4=IFCRELAGGREGATES('0123456789012345678934',$,$,$,#3,(#2));\n"
        "#5=IFCRELCONTAINEDINSPATIALSTRUCTURE('0123456789012345678935',$,$,$,(#3),#1);\n");
    REQUIRE(file->good());

    const express::base part = must_instance(*file, 2);
    const express::base whole = must_instance(*file, 3);
    const express::base storey = must_instance(*file, 1);
    const auto decomposes = part.as<express::entity>().get_inverse("Decomposes");
    REQUIRE(decomposes.size() == 1);
    const express::base relating = decomposes.front().get("RelatingObject");
    REQUIRE(relating);
    CHECK(relating.id() == whole.id());

    const express::base container = get_container(part);
    REQUIRE(container);
    CHECK(container.id() == storey.id());
}

TEST_CASE("Two elements that aggregate each other terminate in get_container", "[helpers][cycle]") {
    auto file = open_ifc(
        "#1=IFCWALL('0123456789012345678941',$,'A',$,$,$,$,$,$);\n"
        "#2=IFCWALL('0123456789012345678942',$,'B',$,$,$,$,$,$);\n"
        "#3=IFCRELAGGREGATES('0123456789012345678943',$,$,$,#1,(#2));\n"
        "#4=IFCRELAGGREGATES('0123456789012345678944',$,$,$,#2,(#1));\n");
    REQUIRE(file->good());

    const express::base first = must_instance(*file, 1);
    const express::base second = must_instance(*file, 2);
    const auto first_parents = first.as<express::entity>().get_inverse("Decomposes");
    const auto second_parents = second.as<express::entity>().get_inverse("Decomposes");
    REQUIRE(first_parents.size() == 1);
    REQUIRE(second_parents.size() == 1);
    const express::base first_relating = first_parents.front().get("RelatingObject");
    const express::base second_relating = second_parents.front().get("RelatingObject");
    REQUIRE(first_relating);
    REQUIRE(second_relating);
    CHECK(first_relating.id() == second.id());
    CHECK(second_relating.id() == first.id());

    // Same calls PropertiesPanelView::refresh makes. The property reads are
    // empty here; get_container is the call that follows the cycle. The
    // isolated probe already catches std::exception, so a stack overflow
    // still fails this check.
    require_terminates([first] {
        (void)get_container(first);
        (void)get_psets(first, true, false);
        (void)get_psets(first, false, true);
    });
    require_terminates([second] { (void)get_container(second); });
}

TEST_CASE("An element aggregated by itself terminates in get_container", "[helpers][cycle]") {
    auto file = open_ifc(
        "#1=IFCWALL('0123456789012345678951',$,'Loop',$,$,$,$,$,$);\n"
        "#2=IFCRELAGGREGATES('0123456789012345678952',$,$,$,#1,(#1));\n");
    REQUIRE(file->good());

    const express::base wall = must_instance(*file, 1);
    const auto parents = wall.as<express::entity>().get_inverse("Decomposes");
    REQUIRE(parents.size() == 1);
    const express::base relating = parents.front().get("RelatingObject");
    REQUIRE(relating);
    CHECK(relating.id() == wall.id());

    require_terminates([wall] { (void)get_container(wall); });
}

TEST_CASE("A nested complex property is readable", "[helpers][cycle]") {
    auto file = open_ifc(
        "#1=IFCWALL('0123456789012345678961',$,'Wall',$,$,$,$,$,$);\n"
        "#2=IFCPROPERTYSINGLEVALUE('Inner',$,IFCLABEL('ok'),$);\n"
        "#3=IFCCOMPLEXPROPERTY('Outer',$,'Use',(#2));\n"
        "#4=IFCPROPERTYSET('0123456789012345678964',$,'Pset_Test',$,(#3));\n"
        "#5=IFCRELDEFINESBYPROPERTIES('0123456789012345678965',$,$,$,(#1),#4);\n");
    REQUIRE(file->good());

    const express::base wall = must_instance(*file, 1);
    const express::base complex = must_instance(*file, 3);
    const element_properties psets = get_psets(wall, true, false);
    REQUIRE(psets.count("Pset_Test") == 1);
    const property_value* outer = map_at(psets.at("Pset_Test"), "Outer");
    REQUIRE(outer != nullptr);
    const property_map* outer_map = outer->get_if<property_map>();
    REQUIRE(outer_map != nullptr);
    const property_value* properties = map_at(*outer_map, "properties");
    REQUIRE(properties != nullptr);
    const property_map* properties_map = properties->get_if<property_map>();
    REQUIRE(properties_map != nullptr);
    const property_value* inner = map_at(*properties_map, "Inner");
    REQUIRE(inner != nullptr);
    const std::string* text = inner->get_if<std::string>();
    REQUIRE(text != nullptr);
    CHECK(*text == "ok");

    const property_map direct = get_properties(std::vector<express::base>{complex}, false);
    const property_value* direct_outer = map_at(direct, "Outer");
    REQUIRE(direct_outer != nullptr);
    const property_map* direct_outer_map = direct_outer->get_if<property_map>();
    REQUIRE(direct_outer_map != nullptr);
    const property_value* direct_properties = map_at(*direct_outer_map, "properties");
    REQUIRE(direct_properties != nullptr);
    const property_map* direct_properties_map = direct_properties->get_if<property_map>();
    REQUIRE(direct_properties_map != nullptr);
    const property_value* direct_inner = map_at(*direct_properties_map, "Inner");
    REQUIRE(direct_inner != nullptr);
    const std::string* direct_text = direct_inner->get_if<std::string>();
    REQUIRE(direct_text != nullptr);
    CHECK(*direct_text == "ok");
}

TEST_CASE("A complex property that includes itself terminates", "[helpers][cycle]") {
    auto file = open_ifc(
        "#1=IFCWALL('0123456789012345678971',$,'Wall',$,$,$,$,$,$);\n"
        "#2=IFCCOMPLEXPROPERTY('Cycle',$,'Use',(#2));\n"
        "#3=IFCPROPERTYSET('0123456789012345678973',$,'Pset_Cycle',$,(#2));\n"
        "#4=IFCRELDEFINESBYPROPERTIES('0123456789012345678974',$,$,$,(#1),#3);\n");
    REQUIRE(file->good());

    const express::base wall = must_instance(*file, 1);
    const express::base complex = must_instance(*file, 2);
    const express::base pset = must_instance(*file, 3);
    const std::vector<express::base> has_properties = complex.get_attribute_value(3);
    REQUIRE(has_properties.size() == 1);
    CHECK(has_properties.front().id() == complex.id());

    require_terminates([wall] {
        (void)get_container(wall);
        (void)get_psets(wall, true, false);
        (void)get_psets(wall, false, true);
    });
    require_terminates([wall] { (void)get_psets(wall, true, false); });
    require_terminates([wall] { (void)get_pset(wall, "Pset_Cycle"); });
    require_terminates([complex] { (void)get_properties(std::vector<express::base>{complex}, false); });
    require_terminates([complex] { (void)get_property(std::vector<express::base>{complex}, "Cycle", false); });
    require_terminates([pset] { (void)get_property_definition(pset, std::nullopt, false); });
}

TEST_CASE("Two complex properties that include each other terminate", "[helpers][cycle]") {
    auto file = open_ifc(
        "#1=IFCWALL('0123456789012345678981',$,'Wall',$,$,$,$,$,$);\n"
        "#2=IFCCOMPLEXPROPERTY('Left',$,'Use',(#3));\n"
        "#3=IFCCOMPLEXPROPERTY('Right',$,'Use',(#2));\n"
        "#4=IFCPROPERTYSET('0123456789012345678984',$,'Pset_Cycle',$,(#2));\n"
        "#5=IFCRELDEFINESBYPROPERTIES('0123456789012345678985',$,$,$,(#1),#4);\n");
    REQUIRE(file->good());

    const express::base wall = must_instance(*file, 1);
    const express::base left = must_instance(*file, 2);
    const express::base right = must_instance(*file, 3);
    const std::vector<express::base> left_children = left.get_attribute_value(3);
    const std::vector<express::base> right_children = right.get_attribute_value(3);
    REQUIRE(left_children.size() == 1);
    REQUIRE(right_children.size() == 1);
    CHECK(left_children.front().id() == right.id());
    CHECK(right_children.front().id() == left.id());

    require_terminates([wall] { (void)get_psets(wall, true, false); });
    require_terminates([left] { (void)get_properties(std::vector<express::base>{left}, false); });
    require_terminates([right] { (void)get_property(std::vector<express::base>{right}, "Right", false); });
}

TEST_CASE("A nested complex quantity is readable", "[helpers][cycle]") {
    auto file = open_ifc(
        "#1=IFCWALL('0123456789012345678991',$,'Wall',$,$,$,$,$,$);\n"
        "#2=IFCQUANTITYAREA('Area',$,$,12.5,$);\n"
        "#3=IFCPHYSICALCOMPLEXQUANTITY('Layer',$,(#2),'layer',$,$);\n"
        "#4=IFCELEMENTQUANTITY('0123456789012345678994',$,'Qto_Test',$,$,(#3));\n"
        "#5=IFCRELDEFINESBYPROPERTIES('0123456789012345678995',$,$,$,(#1),#4);\n");
    REQUIRE(file->good());

    const express::base wall = must_instance(*file, 1);
    const express::base complex = must_instance(*file, 3);
    const element_properties qtos = get_psets(wall, false, true);
    REQUIRE(qtos.count("Qto_Test") == 1);
    const property_value* layer = map_at(qtos.at("Qto_Test"), "Layer");
    REQUIRE(layer != nullptr);
    const property_map* layer_map = layer->get_if<property_map>();
    REQUIRE(layer_map != nullptr);
    const property_value* properties = map_at(*layer_map, "properties");
    REQUIRE(properties != nullptr);
    const property_map* properties_map = properties->get_if<property_map>();
    REQUIRE(properties_map != nullptr);
    const property_value* area = map_at(*properties_map, "Area");
    REQUIRE(area != nullptr);
    const double* value = area->get_if<double>();
    REQUIRE(value != nullptr);
    CHECK(*value == Catch::Approx(12.5));

    const property_map direct = get_quantities(std::vector<express::base>{complex}, false);
    const property_value* direct_layer = map_at(direct, "Layer");
    REQUIRE(direct_layer != nullptr);
    const property_map* direct_layer_map = direct_layer->get_if<property_map>();
    REQUIRE(direct_layer_map != nullptr);
    const property_value* direct_properties = map_at(*direct_layer_map, "properties");
    REQUIRE(direct_properties != nullptr);
    const property_map* direct_properties_map = direct_properties->get_if<property_map>();
    REQUIRE(direct_properties_map != nullptr);
    const property_value* direct_area = map_at(*direct_properties_map, "Area");
    REQUIRE(direct_area != nullptr);
    const double* direct_value = direct_area->get_if<double>();
    REQUIRE(direct_value != nullptr);
    CHECK(*direct_value == Catch::Approx(12.5));
}

TEST_CASE("A complex quantity that includes itself terminates", "[helpers][cycle]") {
    auto file = open_ifc(
        "#1=IFCWALL('01234567890123456789A1',$,'Wall',$,$,$,$,$,$);\n"
        "#2=IFCPHYSICALCOMPLEXQUANTITY('Loop',$,(#2),'layer',$,$);\n"
        "#3=IFCELEMENTQUANTITY('01234567890123456789A3',$,'Qto_Cycle',$,$,(#2));\n"
        "#4=IFCRELDEFINESBYPROPERTIES('01234567890123456789A4',$,$,$,(#1),#3);\n");
    REQUIRE(file->good());

    const express::base wall = must_instance(*file, 1);
    const express::base complex = must_instance(*file, 2);
    const std::vector<express::base> has_quantities = complex.get_attribute_value(2);
    REQUIRE(has_quantities.size() == 1);
    CHECK(has_quantities.front().id() == complex.id());

    require_terminates([wall] { (void)get_psets(wall, false, true); });
    require_terminates([wall] { (void)get_pset(wall, "Qto_Cycle", std::nullopt, false, true); });
    require_terminates([complex] { (void)get_quantities(std::vector<express::base>{complex}, false); });
    require_terminates([complex] { (void)get_quantity(std::vector<express::base>{complex}, "Loop", false); });
}

TEST_CASE("Two complex quantities that include each other terminate", "[helpers][cycle]") {
    auto file = open_ifc(
        "#1=IFCWALL('01234567890123456789B1',$,'Wall',$,$,$,$,$,$);\n"
        "#2=IFCPHYSICALCOMPLEXQUANTITY('Left',$,(#3),'layer',$,$);\n"
        "#3=IFCPHYSICALCOMPLEXQUANTITY('Right',$,(#2),'layer',$,$);\n"
        "#4=IFCELEMENTQUANTITY('01234567890123456789B4',$,'Qto_Cycle',$,$,(#2));\n"
        "#5=IFCRELDEFINESBYPROPERTIES('01234567890123456789B5',$,$,$,(#1),#4);\n");
    REQUIRE(file->good());

    const express::base wall = must_instance(*file, 1);
    const express::base left = must_instance(*file, 2);
    const express::base right = must_instance(*file, 3);
    const std::vector<express::base> left_children = left.get_attribute_value(2);
    const std::vector<express::base> right_children = right.get_attribute_value(2);
    REQUIRE(left_children.size() == 1);
    REQUIRE(right_children.size() == 1);
    CHECK(left_children.front().id() == right.id());
    CHECK(right_children.front().id() == left.id());

    require_terminates([wall] { (void)get_psets(wall, false, true); });
    require_terminates([left] { (void)get_quantities(std::vector<express::base>{left}, false); });
    require_terminates([right] { (void)get_quantity(std::vector<express::base>{right}, "Right", false); });
}
