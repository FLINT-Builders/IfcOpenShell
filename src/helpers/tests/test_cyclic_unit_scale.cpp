// This file was generated with the assistance of an AI coding tool.
/********************************************************************************
 *                                                                              *
 * This file is part of IfcOpenShell.                                           *
 *                                                                              *
 * IfcOpenShell is free software: you can redistribute it and/or modify         *
 * it under the terms of the Lesser GNU General Public License as published by  *
 * the Free Software Foundation, either version 3.0 of the License, or          *
 * (at your option) any later version.                                          *
 *                                                                              *
 * IfcOpenShell is distributed in the hope that it will be useful,              *
 * but WITHOUT ANY WARRANTY; without even the implied warranty of               *
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the                 *
 * Lesser GNU General Public License for more details.                          *
 *                                                                              *
 * You should have received a copy of the Lesser GNU General Public License     *
 * along with this program. If not, see <http://www.gnu.org/licenses/>.         *
 *                                                                              *
 ********************************************************************************/

// Spec for the cyclic-conversion hang in si_scale_from_named_unit_s.
//
// SceneLoader::onStreamerFinished and SceneLoader::modelGeoref call
// computeModelGeoref, which calls calculate_unit_scale(file, "LENGTHUNIT")
// on the thread that owns the loader. That helper walks
// IfcConversionBasedUnit.ConversionFactor.UnitComponent with no cycle check.
// These cases parse a real SPF buffer and call that helper. A cycle, or a
// non-finite scale, must come back as "no scale" (nullopt, so
// calculate_unit_scale falls back to 1.0) within a few seconds.
//
// A name in SI_CONVERSIONS still returns the table value and does not follow
// the factor. A short acyclic chain must keep its real scale.

#include "unit.h"

#include "../ifcparse/file.h"
#include "../ifcparse/file_open_status.h"

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <optional>
#include <string>
#include <unistd.h>
#include <sys/wait.h>
#include <vector>

namespace {

constexpr int kBoundSeconds = 5;

struct Case {
    const char* name;
    const char* schema;
    const char* unit_type;
    // When set, si_scale_from_named_unit must be this value.
    // When unset, it must be nullopt and calculate_unit_scale must be 1.
    std::optional<double> scale;
    bool cyclic;
    std::string spf;
};

std::string quote_schema(const char* schema) {
    return std::string("FILE_SCHEMA(('") + schema + "'));\n";
}

std::string wall_instance(const char* schema) {
    // IfcWall is an IfcElement, so GeometryStreamer::run treats the file as
    // geometry-bearing and emits finished(). IFC2X3 has no PredefinedType.
    const char* tail = std::strcmp(schema, "IFC2X3") == 0
        ? "#14=IFCWALL('3kan11u0f3NusVFUxfHxT1',#5,'Wall',$,$,$,$,$);\n"
        : "#14=IFCWALL('3kan11u0f3NusVFUxfHxT1',#5,'Wall',$,$,$,$,$,$);\n";
    return tail;
}

std::string wrap(const char* schema, const std::string& units) {
    std::string spf;
    spf += "ISO-10303-21;\nHEADER;\n";
    spf += "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n";
    spf += "FILE_NAME('cycle.ifc','1970-01-01T00:00:00',(''),(''),'IfcOpenShell','IfcOpenShell','');\n";
    spf += quote_schema(schema);
    spf += "ENDSEC;\nDATA;\n";
    spf += "#1=IFCPERSON($,$,'Tester',$,$,$,$,$);\n";
    spf += "#2=IFCORGANIZATION($,'Test',$,$,$);\n";
    spf += "#3=IFCPERSONANDORGANIZATION(#1,#2,$);\n";
    spf += "#4=IFCAPPLICATION(#2,'0','Test','Test');\n";
    spf += "#5=IFCOWNERHISTORY(#3,#4,$,.ADDED.,$,$,$,0);\n";
    spf += units;
    spf += "#11=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#12,$);\n";
    spf += "#12=IFCAXIS2PLACEMENT3D(#13,$,$);\n";
    spf += "#13=IFCCARTESIANPOINT((0.,0.,0.));\n";
    spf += wall_instance(schema);
    spf += "#10=IFCPROJECT('3kan11u0f3NusVFUxfHxT0',#5,'Cyclic',$,$,$,$,(#11),#9);\n";
    spf += "ENDSEC;\nEND-ISO-10303-21;\n";
    return spf;
}

std::string exponents(int length) {
    return "#30=IFCDIMENSIONALEXPONENTS(" + std::to_string(length) + ",0,0,0,0,0,0);\n";
}

Case make_case(const char* name, const char* schema, const char* unit_type,
               std::optional<double> scale, bool cyclic, const std::string& units) {
    Case item;
    item.name = name;
    item.schema = schema;
    item.unit_type = unit_type;
    item.scale = scale;
    item.cyclic = cyclic;
    item.spf = wrap(schema, units);
    return item;
}

express::base instance_attr(const express::base& instance, const char* name) {
    return static_cast<express::base>(instance.as<express::entity>().get(name));
}

// Follow UnitComponent a bounded number of times. This is the test's own
// walk, capped so it cannot hang, used only to check that the parser kept
// the graph the helper is about to walk.
bool component_cycle(const express::base& start, int limit) {
    std::vector<uint32_t> seen;
    express::base cursor = start;
    for (int i = 0; i < limit; ++i) {
        if (!cursor || !cursor.declaration().is("IfcConversionBasedUnit")) {
            return false;
        }
        for (uint32_t id : seen) {
            if (id == cursor.id()) {
                return true;
            }
        }
        seen.push_back(cursor.id());
        const express::base factor = instance_attr(cursor, "ConversionFactor");
        cursor = instance_attr(factor, "UnitComponent");
    }
    return false;
}

int fail(const std::string& message) {
    std::cerr << message << "\n";
    return 1;
}

int run_case(const Case& item) {
    ifcopenshell::file file(const_cast<char*>(item.spf.data()), static_cast<int>(item.spf.size()));
    if (!file.good()) {
        return fail(std::string(item.name) + ": parse failed, status " +
                    std::to_string(static_cast<int>(file.good().value())));
    }

    const auto unit = get_project_unit(&file, item.unit_type);
    if (!unit) {
        return fail(std::string(item.name) + ": project unit " + item.unit_type + " was not selected");
    }
    const bool saw_cycle = component_cycle(*unit, 8);
    if (item.cyclic != saw_cycle) {
        return fail(std::string(item.name) + ": parsed UnitComponent graph cyclic=" +
                    (saw_cycle ? "yes" : "no") + " expected " + (item.cyclic ? "yes" : "no") +
                    " type " + unit->declaration().name());
    }

    std::cerr << item.name << ": calling si_scale_from_named_unit\n";
    const std::optional<double> named = si_scale_from_named_unit(*unit);
    const double project = calculate_unit_scale(&file, item.unit_type);
    std::cerr << item.name << ": returned\n";

    if (item.scale) {
        if (!named || std::fabs(*named - *item.scale) > 1e-12) {
            return fail(std::string(item.name) + ": si scale " +
                        (named ? std::to_string(*named) : std::string("nullopt")) +
                        " expected " + std::to_string(*item.scale));
        }
        if (std::fabs(project - *item.scale) > 1e-12) {
            return fail(std::string(item.name) + ": project scale " + std::to_string(project) +
                        " expected " + std::to_string(*item.scale));
        }
        return 0;
    }

    if (named) {
        return fail(std::string(item.name) + ": si scale " + std::to_string(*named) +
                    " expected nullopt");
    }
    if (!(std::isfinite(project) && project == 1.0)) {
        return fail(std::string(item.name) + ": project scale " + std::to_string(project) +
                    " expected 1");
    }
    return 0;
}

int run_bounded(const Case& item) {
    const pid_t pid = fork();
    if (pid < 0) {
        std::perror("fork");
        return 1;
    }
    if (pid == 0) {
        alarm(kBoundSeconds);
        const int status = run_case(item);
        alarm(0);
        _exit(status);
    }
    int status = 0;
    if (waitpid(pid, &status, 0) < 0) {
        std::perror("waitpid");
        return 1;
    }
    if (WIFSIGNALED(status)) {
        const int signal = WTERMSIG(status);
        std::cerr << item.name << ": did not return within " << kBoundSeconds
                  << "s (signal " << signal << ")\n";
        return 1;
    }
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        std::cerr << item.name << ": failed\n";
        return 1;
    }
    std::cerr << item.name << ": ok\n";
    return 0;
}

std::string self_cycle(const char* entity,
                        const char* unit_type,
                        const char* measure,
                        const char* name,
                        const char* factor) {
    std::string units = exponents(std::strcmp(unit_type, "AREAUNIT") == 0 ? 2 : 1);
    units += "#9=IFCUNITASSIGNMENT((#20));\n";
    units += std::string("#20=") + entity + "(#30,." + unit_type + ".,'" + name + "',#21";
    if (std::strcmp(entity, "IFCCONVERSIONBASEDUNITWITHOFFSET") == 0) {
        units += ",0.";
    }
    units += ");\n";
    units += std::string("#21=IFCMEASUREWITHUNIT(") + measure + "(" + factor + "),#20);\n";
    return units;
}

} // namespace

int main() {
    const std::vector<Case> cases = {
        make_case("ifc4_self_cycle_length", "IFC4", "LENGTHUNIT", std::nullopt, true,
                  self_cycle("IFCCONVERSIONBASEDUNIT", "LENGTHUNIT", "IFCLENGTHMEASURE", "LOOP", "1.")),
        make_case("ifc2x3_self_cycle_length", "IFC2X3", "LENGTHUNIT", std::nullopt, true,
                  self_cycle("IFCCONVERSIONBASEDUNIT", "LENGTHUNIT", "IFCLENGTHMEASURE", "LOOP", "1.")),
        make_case("ifc4x3_add2_self_cycle_length", "IFC4X3_ADD2", "LENGTHUNIT", std::nullopt, true,
                  self_cycle("IFCCONVERSIONBASEDUNIT", "LENGTHUNIT", "IFCLENGTHMEASURE", "LOOP", "1.")),
        make_case("ifc4_self_cycle_factor_two", "IFC4", "LENGTHUNIT", std::nullopt, true,
                  self_cycle("IFCCONVERSIONBASEDUNIT", "LENGTHUNIT", "IFCLENGTHMEASURE", "LOOP", "2.")),
        make_case("ifc4_two_unit_cycle", "IFC4", "LENGTHUNIT", std::nullopt, true,
                  exponents(1) +
                      "#9=IFCUNITASSIGNMENT((#20));\n"
                      "#20=IFCCONVERSIONBASEDUNIT(#30,.LENGTHUNIT.,'LOOPA',#21);\n"
                      "#21=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(1.),#22);\n"
                      "#22=IFCCONVERSIONBASEDUNIT(#30,.LENGTHUNIT.,'LOOPB',#23);\n"
                      "#23=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(1.),#20);\n"),
        make_case("ifc4_three_unit_cycle", "IFC4", "LENGTHUNIT", std::nullopt, true,
                  exponents(1) +
                      "#9=IFCUNITASSIGNMENT((#20));\n"
                      "#20=IFCCONVERSIONBASEDUNIT(#30,.LENGTHUNIT.,'LOOPA',#21);\n"
                      "#21=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(1.),#22);\n"
                      "#22=IFCCONVERSIONBASEDUNIT(#30,.LENGTHUNIT.,'LOOPB',#23);\n"
                      "#23=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(1.),#24);\n"
                      "#24=IFCCONVERSIONBASEDUNIT(#30,.LENGTHUNIT.,'LOOPC',#25);\n"
                      "#25=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(1.),#20);\n"),
        make_case("ifc4_offset_self_cycle", "IFC4", "LENGTHUNIT", std::nullopt, true,
                  self_cycle("IFCCONVERSIONBASEDUNITWITHOFFSET", "LENGTHUNIT", "IFCLENGTHMEASURE", "LOOPOFF", "1.")),
        make_case("ifc4_area_self_cycle", "IFC4", "AREAUNIT", std::nullopt, true,
                  self_cycle("IFCCONVERSIONBASEDUNIT", "AREAUNIT", "IFCAREAMEASURE", "LOOPAREA", "1.")),
        make_case("ifc4_foot_self_cycle_uses_table", "IFC4", "LENGTHUNIT", 0.3048, true,
                  self_cycle("IFCCONVERSIONBASEDUNIT", "LENGTHUNIT", "IFCLENGTHMEASURE", "foot", "1.")),
        make_case("ifc4_milli_si", "IFC4", "LENGTHUNIT", 0.001, false,
                  "#9=IFCUNITASSIGNMENT((#20));\n"
                  "#20=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);\n"),
        make_case("ifc4_custom_chain_to_milli", "IFC4", "LENGTHUNIT", 0.006, false,
                  exponents(1) +
                      "#9=IFCUNITASSIGNMENT((#20));\n"
                      "#20=IFCCONVERSIONBASEDUNIT(#30,.LENGTHUNIT.,'step-a',#21);\n"
                      "#21=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(2.),#22);\n"
                      "#22=IFCCONVERSIONBASEDUNIT(#30,.LENGTHUNIT.,'step-b',#23);\n"
                      "#23=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(3.),#24);\n"
                      "#24=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);\n"),
        make_case("ifc4_nonfinite_product", "IFC4", "LENGTHUNIT", std::nullopt, false,
                  exponents(1) +
                      "#9=IFCUNITASSIGNMENT((#20));\n"
                      "#20=IFCCONVERSIONBASEDUNIT(#30,.LENGTHUNIT.,'HUGE',#21);\n"
                      "#21=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(1.E200),#22);\n"
                      "#22=IFCCONVERSIONBASEDUNIT(#30,.LENGTHUNIT.,'HUGER',#23);\n"
                      "#23=IFCMEASUREWITHUNIT(IFCLENGTHMEASURE(1.E200),#24);\n"
                      "#24=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);\n"),
    };

    int failures = 0;
    for (const Case& item : cases) {
        failures += run_bounded(item);
    }
    if (failures != 0) {
        std::cerr << failures << " case(s) failed\n";
        return 1;
    }
    std::cerr << "all cyclic unit scale cases passed\n";
    return 0;
}
