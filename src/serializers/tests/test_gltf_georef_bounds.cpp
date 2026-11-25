// This file was generated with the assistance of an AI coding tool.
//
// Spec for gltf_serializer::setFile when ecef is enabled. Short
// RefLatitude / RefLongitude / DirectionRatios lists must not be indexed.
// The test is built with AddressSanitizer and _GLIBCXX_ASSERTIONS, so the
// unchecked reads in the current serializer abort the case.

#include "../gltf_serializer.h"

#include "../../ifcgeom/element.h"
#include "../../ifcgeom/taxonomy.h"
#include "../../ifcparse/file.h"

#include <proj.h>

#include <nlohmann/json.hpp>

#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>

namespace {

struct Case {
    const char* name;
    bool ecef;
    int site_count;
    std::optional<std::vector<int64_t>> latitude;
    std::optional<std::vector<int64_t>> longitude;
    std::optional<std::vector<double>> ratios;
    bool expect_cesium;
};

std::string ints_token(const std::optional<std::vector<int64_t>>& values) {
    if (!values) {
        return "$";
    }
    std::string token = "(";
    for (size_t i = 0; i < values->size(); ++i) {
        if (i != 0) {
            token += ",";
        }
        token += std::to_string((*values)[i]);
    }
    token += ")";
    return token;
}

std::string reals_token(const std::optional<std::vector<double>>& values) {
    if (!values) {
        return "$";
    }
    std::string token = "(";
    for (size_t i = 0; i < values->size(); ++i) {
        if (i != 0) {
            token += ",";
        }
        // std::to_string always emits a decimal point, so the parser stores
        // a real aggregate rather than an integer aggregate.
        token += std::to_string((*values)[i]);
    }
    token += ")";
    return token;
}

std::string ifc_text(const Case& spec) {
    const std::string lat = ints_token(spec.latitude);
    const std::string lon = ints_token(spec.longitude);
    std::ostringstream data;
    int next_id = 1;
    auto emit = [&](const std::string& body) {
        const int id = next_id++;
        data << "#" << id << "=" << body << ";\n";
        return id;
    };

    std::vector<int> site_ids;
    for (int i = 0; i < spec.site_count; ++i) {
        const std::string guid = (i == 0) ? "1Us2WBBOP0tAtKGpdhMN8l" : "2Us2WBBOP0tAtKGpdhMN8m";
        site_ids.push_back(emit(
            "IFCSITE('" + guid + "',$,'Site',$,$,$,$,$,$," + lat + "," + lon + ",$,$,$)"));
    }

    const int point = emit("IFCCARTESIANPOINT((0.,0.,0.))");
    const int placement = emit("IFCAXIS2PLACEMENT3D(#" + std::to_string(point) + ",$,$)");
    std::string north = "$";
    if (spec.ratios) {
        const int direction = emit("IFCDIRECTION(" + reals_token(spec.ratios) + ")");
        north = "#" + std::to_string(direction);
    }
    const int context = emit(
        "IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#" + std::to_string(placement) + "," + north + ")");
    emit("IFCPROJECT('3Us2WBBOP0tAtKGpdhMN8n',$,'P',$,$,$,$,(#" + std::to_string(context) + "),$)");
    (void)site_ids;

    std::ostringstream file;
    file << "ISO-10303-21;\n"
         << "HEADER;\n"
         << "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
         << "FILE_NAME('','1970-01-01T00:00:00',(''),(''),'IfcOpenShell','IfcOpenShell','');\n"
         << "FILE_SCHEMA(('IFC4'));\n"
         << "ENDSEC;\n"
         << "DATA;\n"
         << data.str()
         << "ENDSEC;\n"
         << "END-ISO-10303-21;\n";
    return file.str();
}

double compound_angle(const std::vector<int64_t>& dms) {
    // Same reduction as gltf_serializer.cpp to_decimal, for lists the
    // serializer is allowed to read (3 or 4 components).
    double value = static_cast<double>(dms.at(0)) + static_cast<double>(dms.at(1)) / 60. +
                   static_cast<double>(dms.at(2)) / 3600.;
    if (dms.size() == 4) {
        value += static_cast<double>(dms.at(3)) / 3600.e6;
    }
    return value;
}

std::array<double, 3> expected_ecef(double latitude, double longitude) {
    // Mirrors gltf_serializer::setup_georeferencing for EPSG:4326 at the
    // revision under test, using PROJ 9.4 (proj.h proj_coord / PJ_COORD).
    PJ_CONTEXT* context = proj_context_create();
    if (context == nullptr) {
        throw std::runtime_error("proj_context_create failed");
    }
    proj_context_set_database_path(context, "proj.db", nullptr, nullptr);

    PJ_COORD wgs84 = proj_coord(latitude, longitude, 0.0, 0.0);
    std::swap(wgs84.lp.phi, wgs84.lp.lam);

    const char* input_crs = "+proj=latlong +datum=WGS84";
    const char* output_crs = "+proj=geocent +datum=WGS84 +units=m";
    PJ* transform = proj_create_crs_to_crs(context, input_crs, output_crs, nullptr);
    if (transform == nullptr) {
        proj_context_destroy(context);
        throw std::runtime_error("proj_create_crs_to_crs failed");
    }
    PJ_COORD output = proj_trans(transform, PJ_FWD, wgs84);

    PJ* ellipsoid_crs = proj_create(context, "WGS84");
    if (ellipsoid_crs == nullptr) {
        proj_destroy(transform);
        proj_context_destroy(context);
        throw std::runtime_error("proj_create WGS84 failed");
    }
    PJ* ellipse = proj_get_ellipsoid(context, ellipsoid_crs);
    int semi_minor_computed = 0;
    double semi_major = 0.0;
    double semi_minor = 0.0;
    double inverse_flattening = 0.0;
    if (ellipse == nullptr ||
        proj_ellipsoid_get_parameters(context, ellipse, &semi_major, &semi_minor, &semi_minor_computed, &inverse_flattening) == 0) {
        proj_destroy(ellipsoid_crs);
        proj_destroy(transform);
        proj_context_destroy(context);
        throw std::runtime_error("proj ellipsoid parameters failed");
    }
    (void)semi_major;
    (void)semi_minor;
    proj_destroy(ellipsoid_crs);
    proj_destroy(transform);
    proj_context_destroy(context);
    return {output.xyz.x, output.xyz.y, output.xyz.z};
}

nlohmann::json glb_json(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("missing glb " + path.string());
    }
    char header[12];
    input.read(header, sizeof(header));
    if (!input) {
        throw std::runtime_error("short glb header");
    }
    uint32_t chunk_length = 0;
    uint32_t chunk_type = 0;
    input.read(reinterpret_cast<char*>(&chunk_length), sizeof(chunk_length));
    input.read(reinterpret_cast<char*>(&chunk_type), sizeof(chunk_type));
    if (!input || chunk_type != 0x4E4F534AU) {
        throw std::runtime_error("glb JSON chunk missing");
    }
    std::string payload(chunk_length, '\0');
    input.read(payload.data(), static_cast<std::streamsize>(chunk_length));
    if (!input) {
        throw std::runtime_error("short glb JSON chunk");
    }
    return nlohmann::json::parse(payload);
}

void require_stored_lengths(ifcopenshell::file& file, const Case& spec) {
    const auto sites = file.instances_by_type("IfcSite");
    if (static_cast<int>(sites.size()) != spec.site_count) {
        throw std::runtime_error(
            "parser kept " + std::to_string(sites.size()) + " IfcSite instances, expected " + std::to_string(spec.site_count));
    }
    if (spec.site_count > 0 && spec.latitude && spec.longitude) {
        for (const auto& site_base : sites) {
            auto site = site_base.as<express::entity>();
            auto lat_attr = site.get("RefLatitude");
            auto lon_attr = site.get("RefLongitude");
            if (lat_attr.isNull() || lon_attr.isNull()) {
                throw std::runtime_error("parser dropped a supplied latitude or longitude list");
            }
            const std::vector<int64_t> lat = lat_attr;
            const std::vector<int64_t> lon = lon_attr;
            if (lat.size() != spec.latitude->size() || lon.size() != spec.longitude->size()) {
                throw std::runtime_error(
                    "parser resized a compound plane angle from " + std::to_string(spec.latitude->size()) + "/" +
                    std::to_string(spec.longitude->size()) + " to " + std::to_string(lat.size()) + "/" + std::to_string(lon.size()));
            }
        }
    }
    const auto contexts = file.instances_by_type_excl_subtypes("IfcGeometricRepresentationContext");
    if (contexts.size() != 1) {
        throw std::runtime_error("expected one geometric context");
    }
    auto north_attr = contexts.front().as<express::entity>().get("TrueNorth");
    if (!spec.ratios) {
        if (!north_attr.isNull()) {
            throw std::runtime_error("parser invented a TrueNorth");
        }
        return;
    }
    if (north_attr.isNull()) {
        throw std::runtime_error("parser dropped TrueNorth");
    }
    const express::base north = north_attr;
    const std::vector<double> ratios = north.as<express::entity>().get("DirectionRatios");
    if (ratios.size() != spec.ratios->size()) {
        throw std::runtime_error(
            "parser resized DirectionRatios from " + std::to_string(spec.ratios->size()) + " to " + std::to_string(ratios.size()));
    }
}

void write_triangle(gltf_serializer& serializer, ifcopenshell::file& file, const ifcopenshell::geom::settings& settings) {
    const auto projects = file.instances_by_type("IfcProject");
    if (projects.size() != 1) {
        throw std::runtime_error("expected one IfcProject");
    }
    const express::entity product = projects.front().as<express::entity>();
    auto geometry = std::make_shared<ifcopenshell::geom::triangulation>(
        settings,
        "IfcFacetedBrep",
        "body",
        std::vector<double>{0, 0, 0, 1, 0, 0, 0, 1, 0},
        std::vector<int>{0, 1, 2},
        std::vector<int>{},
        std::vector<double>{},
        std::vector<double>{},
        std::vector<int>{-1},
        std::vector<ifcopenshell::geom::taxonomy::style::ptr>{},
        std::vector<int>{1},
        std::vector<int>{});
    auto transform = std::make_shared<ifcopenshell::geom::taxonomy::matrix4>();
    ifcopenshell::geom::element source(settings, 1, 0, "proxy", "IfcBuildingElementProxy", "3Us2WBBOP0tAtKGpdhMN8n", "Body", transform, product);
    ifcopenshell::geom::triangulation_element element(source, geometry);
    serializer.write(&element);
}

std::string run_case(const Case& spec, const std::filesystem::path& output) {
    const auto text = ifc_text(spec);
    const auto source = output.string() + ".ifc";
    {
        std::ofstream ifc(source);
        ifc << text;
    }

    ifcopenshell::file file(source);
    if (!file.good()) {
        return "IFC file did not parse";
    }
    require_stored_lengths(file, spec);

    ifcopenshell::geom::settings settings;
    settings.get<ifcopenshell::geom::settings::WriteGltfEcef>().value = spec.ecef;

    {
        gltf_serializer serializer(output.string(), settings);
        if (!serializer.ready()) {
            return "serializer could not open its output";
        }
        // IfcConvert calls setFile, then writeHeader, then write, then finalize.
        serializer.setFile(file);
        serializer.writeHeader();
        write_triangle(serializer, file, settings);
        serializer.finalize();
    }

    const auto document = glb_json(output);
    const bool has_cesium = document.contains("extensions") && document["extensions"].contains("CESIUM_RTC") &&
                            document["extensions"]["CESIUM_RTC"].contains("center");
    if (has_cesium != spec.expect_cesium) {
        return has_cesium ? "wrote CESIUM_RTC from a list that must not be georeferenced"
                          : "did not write CESIUM_RTC for an accepted latitude and longitude";
    }
    if (!spec.expect_cesium) {
        return "";
    }
    const auto expected = expected_ecef(compound_angle(*spec.latitude), compound_angle(*spec.longitude));
    const auto& center = document["extensions"]["CESIUM_RTC"]["center"];
    if (!center.is_array() || center.size() != 3) {
        return "CESIUM_RTC center is not a 3-vector";
    }
    for (size_t i = 0; i < 3; ++i) {
        const double actual = center[i].get<double>();
        if (!std::isfinite(actual) || std::fabs(actual - expected[i]) > 1e-3) {
            std::ostringstream message;
            message << "ECEF component " << i << " is " << actual << ", expected " << expected[i]
                    << " from the in-range angle components";
            return message.str();
        }
    }
    return "";
}

const std::vector<int64_t> kLat3{52, 30, 0};
const std::vector<int64_t> kLon3{4, 20, 0};
const std::vector<int64_t> kLat4{52, 30, 0, 500000};
const std::vector<int64_t> kLon4{4, 20, 0, 250000};
const std::vector<double> kNorth2{0.0, 1.0};
const std::vector<double> kNorth3{0.0, 1.0, 0.0};
const std::vector<double> kNorth1{1.0};

const Case kCases[] = {
    {"ecef_disabled_ignores_short_lists", false, 1, std::vector<int64_t>{52}, std::vector<int64_t>{4}, kNorth1, false},
    {"null_angles_are_not_read", true, 1, std::nullopt, std::nullopt, std::nullopt, false},
    {"two_sites_are_not_read", true, 2, std::vector<int64_t>{52}, std::vector<int64_t>{4}, std::nullopt, false},

    {"latitude_length_0", true, 1, std::vector<int64_t>{}, kLon3, std::nullopt, false},
    {"latitude_length_1", true, 1, std::vector<int64_t>{52}, kLon3, std::nullopt, false},
    {"latitude_length_2", true, 1, std::vector<int64_t>{52, 30}, kLon3, std::nullopt, false},
    {"longitude_length_0", true, 1, kLat3, std::vector<int64_t>{}, std::nullopt, false},
    {"longitude_length_1", true, 1, kLat3, std::vector<int64_t>{4}, std::nullopt, false},
    {"longitude_length_2", true, 1, kLat3, std::vector<int64_t>{4, 20}, std::nullopt, false},
    {"both_angles_length_1", true, 1, std::vector<int64_t>{52}, std::vector<int64_t>{4}, std::nullopt, false},
    {"latitude_length_5_is_rejected", true, 1, std::vector<int64_t>{52, 30, 0, 0, 9}, kLon3, std::nullopt, false},
    {"longitude_length_5_is_rejected", true, 1, kLat3, std::vector<int64_t>{4, 20, 0, 0, 9}, std::nullopt, false},

    {"true_north_length_0", true, 1, kLat3, kLon3, std::vector<double>{}, true},
    {"true_north_length_1", true, 1, kLat3, kLon3, kNorth1, true},

    {"angles_length_3_are_georeferenced", true, 1, kLat3, kLon3, std::nullopt, true},
    {"angles_length_4_include_millionths", true, 1, kLat4, kLon4, std::nullopt, true},
    {"true_north_length_2_keeps_georeferencing", true, 1, kLat3, kLon3, kNorth2, true},
    {"true_north_length_3_keeps_georeferencing", true, 1, kLat3, kLon3, kNorth3, true},
};

int run_child(const Case& spec, const std::filesystem::path& output) {
    try {
        const std::string error = run_case(spec, output);
        if (!error.empty()) {
            std::cerr << spec.name << " FAIL " << error << std::endl;
            return 1;
        }
        std::cerr << spec.name << " PASS" << std::endl;
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << spec.name << " EXCEPTION " << ex.what() << std::endl;
        return 1;
    } catch (...) {
        std::cerr << spec.name << " EXCEPTION unknown" << std::endl;
        return 1;
    }
}

}  // namespace

int main(int argc, char** argv) {
    const auto work = std::filesystem::temp_directory_path() / "gltf-georef-bounds";
    std::filesystem::remove_all(work);
    std::filesystem::create_directories(work);
    std::filesystem::current_path(work);

    const std::filesystem::path database = "/usr/share/proj/proj.db";
    if (!std::filesystem::is_regular_file(database)) {
        std::cerr << "PROJ database " << database << " is not available\n";
        return 2;
    }
    std::filesystem::create_symlink(database, work / "proj.db");

    const char* only = argc > 1 ? argv[1] : nullptr;
    int failures = 0;
    int ran = 0;
    for (const Case& spec : kCases) {
        if (only != nullptr && std::string(only) != spec.name) {
            continue;
        }
        ++ran;
        const auto output = work / (std::string(spec.name) + ".glb");
        const pid_t pid = fork();
        if (pid < 0) {
            std::cerr << spec.name << " FAIL fork\n";
            return 2;
        }
        if (pid == 0) {
            const int code = run_child(spec, output);
            std::_Exit(code);
        }
        int status = 0;
        if (waitpid(pid, &status, 0) < 0) {
            std::cerr << spec.name << " FAIL waitpid\n";
            ++failures;
            continue;
        }
        if (WIFEXITED(status) && WEXITSTATUS(status) == 0) {
            continue;
        }
        ++failures;
        if (WIFSIGNALED(status)) {
            std::cerr << spec.name << " FAIL killed by signal " << WTERMSIG(status) << std::endl;
        } else if (WIFEXITED(status)) {
            std::cerr << spec.name << " FAIL exit " << WEXITSTATUS(status) << std::endl;
        } else {
            std::cerr << spec.name << " FAIL status " << status << std::endl;
        }
    }

    if (ran == 0) {
        std::cerr << "no case named " << only << std::endl;
        return 2;
    }
    std::cerr << failures << " case(s) failed" << std::endl;
    return failures == 0 ? 0 : 1;
}
