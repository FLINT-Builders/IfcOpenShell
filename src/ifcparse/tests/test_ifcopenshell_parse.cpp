// This file was generated with the assistance of an AI coding tool.

#include <catch2/catch_test_macros.hpp>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <ifcparse/exception.h>
#include <ifcparse/file.h>
#include <ifcparse/parse.h>
#include <sstream>
#include <string>
#include <unistd.h>
#include <vector>

TEST_CASE("SPF strings can be encoded and decoded", "[ifcparse]") {
    const std::string decoded = "Caf\xC3\xA9"
                                "'s \\";
    const std::string encoded = R"('Caf\X2\00E9\X0\''s \\')";

    CHECK(ifcopenshell::encode_spf_string(decoded) == encoded);
    CHECK(ifcopenshell::decode_spf_string(encoded) == decoded);
    CHECK(ifcopenshell::decode_spf_string(encoded.substr(1, encoded.size() - 2)) == decoded);
}

TEST_CASE("IfcPropertySetDefinitionSet references are resolved without replacing their owner", "[ifcparse]") {
    const std::string fixture = std::string(IFCOPENSHELL_TEST_FIXTURES) + "/ColumnPSetsOfSets.ifc";
    ifcopenshell::file file(fixture);

    REQUIRE(file.good());

    const auto relationship = file.instance_by_id(139);
    REQUIRE(relationship);
    CHECK(relationship.id() == 139);
    CHECK(relationship.declaration().name() == "IfcRelDefinesByProperties");

    const express::base definition_set = relationship.get_attribute_value(5);
    REQUIRE(definition_set);
    CHECK(definition_set.declaration().name() == "IfcPropertySetDefinitionSet");

    const std::vector<express::base> definitions = definition_set.get_attribute_value(0);
    REQUIRE(definitions.size() == 2);
    CHECK(definitions[0].id() == 136);
    CHECK(definitions[1].id() == 138);
}

TEST_CASE("Bypassed entity types include their subtypes", "[ifcparse]") {
    const std::string fixture = std::string(IFCOPENSHELL_TEST_FIXTURES) + "/ColumnPSetsOfSets.ifc";
    ifcopenshell::file file(ifcopenshell::uninitialized_tag{});
    file.bypass_type("IfcRepresentationItem");

    REQUIRE(file.initialize(fixture));
    CHECK(file.instances_by_type("IfcRepresentationItem").empty());
    CHECK(file.instances_by_type("IfcCartesianPoint").empty());
}

TEST_CASE("Aggregate inverse updates preserve reference multiplicity", "[ifcparse]") {
    ifcopenshell::file file(ifcopenshell::schema_by_name("IFC4"));
    const auto* segment_declaration = file.schema()->declaration_by_name("IfcCompositeCurveSegment");
    auto curve = file.create(file.schema()->declaration_by_name("IfcCompositeCurve"));
    auto segment_a = file.create(segment_declaration);
    auto segment_b = file.create(segment_declaration);
    auto segment_c = file.create(segment_declaration);
    auto segment_d = file.create(segment_declaration);
    const auto inverse_count = [&file](const express::base& instance) {
        return file.instances_by_reference(instance.id()).size();
    };

    curve.set_attribute_value(0, std::vector<express::base>{segment_a, segment_a, segment_b, segment_c});
    CHECK(inverse_count(segment_a) == 2);
    CHECK(inverse_count(segment_b) == 1);
    CHECK(inverse_count(segment_c) == 1);
    CHECK(inverse_count(segment_d) == 0);

    curve.set_attribute_value(0, std::vector<express::base>{segment_a, segment_a, segment_b, segment_c, segment_d});
    CHECK(inverse_count(segment_a) == 2);
    CHECK(inverse_count(segment_b) == 1);
    CHECK(inverse_count(segment_c) == 1);
    CHECK(inverse_count(segment_d) == 1);

    curve.set_attribute_value(0, std::vector<express::base>{segment_a, segment_a, segment_b, segment_c});
    CHECK(inverse_count(segment_a) == 2);
    CHECK(inverse_count(segment_b) == 1);
    CHECK(inverse_count(segment_c) == 1);
    CHECK(inverse_count(segment_d) == 0);

    const std::vector<express::base> reordered{segment_c, segment_a, segment_b, segment_a};
    curve.set_attribute_value(0, reordered);
    CHECK((std::vector<express::base>)curve.get_attribute_value(0) == reordered);
    CHECK(inverse_count(segment_a) == 2);
    CHECK(inverse_count(segment_b) == 1);
    CHECK(inverse_count(segment_c) == 1);
    CHECK(inverse_count(segment_d) == 0);

    curve.set_attribute_value(0, std::vector<express::base>{segment_a, segment_b, segment_b, segment_d});
    CHECK(inverse_count(segment_a) == 1);
    CHECK(inverse_count(segment_b) == 2);
    CHECK(inverse_count(segment_c) == 0);
    CHECK(inverse_count(segment_d) == 1);

    curve.set_attribute_value(0, std::vector<express::base>{segment_c, segment_c, segment_d});
    CHECK(inverse_count(segment_a) == 0);
    CHECK(inverse_count(segment_b) == 0);
    CHECK(inverse_count(segment_c) == 2);
    CHECK(inverse_count(segment_d) == 1);
}

TEST_CASE("Tokens without a string representation do not recurse in to_string()", "[ifcparse]") {
    // to_string() used to delegate to as_string() for every token type it did
    // not handle explicitly, while as_string() builds its exception message
    // with to_string(). An EOF marker or an instance name therefore recursed
    // between the two until the stack was exhausted.
    ifcopenshell::token eof;
    REQUIRE(eof.type == ifcopenshell::token::Token_NONE);
    CHECK_THROWS_AS(eof.to_string(), ifcopenshell::invalid_token_exception);
    CHECK_THROWS_AS(eof.as_string(), ifcopenshell::invalid_token_exception);

    ifcopenshell::token identifier(0, ifcopenshell::token::Token_IDENTIFIER, (int64_t)123);
    CHECK(identifier.to_string() == "#123");
    CHECK_THROWS_AS(identifier.as_string(), ifcopenshell::invalid_token_exception);
}

TEST_CASE("Files that contain no tokens are rejected rather than crashing", "[ifcparse]") {
    // The header parser asks the lexer for a keyword before checking for EOF,
    // so input that lexes to zero tokens reaches token::as_string() on the EOF
    // marker. Parsing must fail cleanly instead of overflowing the stack.
    const std::vector<std::string> inputs{" ", "\r\n\t  ", "/* only a comment */"};

    for (const auto& contents : inputs) {
        INFO("input: " << contents);
        ifcopenshell::logger log;
        std::istringstream input(contents);
        ifcopenshell::file file(input, (int)contents.size(), log);

        CHECK(file.good().value() != ifcopenshell::file_open_status::SUCCESS);
    }
}

TEST_CASE("Inverse lookups stay consistent across interleaved adds, removals and reads", "[ifcparse]") {
    ifcopenshell::file file(ifcopenshell::schema_by_name("IFC4"));
    const auto* point_declaration = file.schema()->declaration_by_name("IfcCartesianPoint");
    const auto* polyline_declaration = file.schema()->declaration_by_name("IfcPolyline");
    auto target = file.create(point_declaration);
    auto other = file.create(point_declaration);

    const auto referencing_ids = [&file](const express::base& instance) {
        std::vector<int> ids;
        for (const auto& referencing : file.instances_by_reference(instance.id())) {
            ids.push_back(referencing.id());
        }
        std::sort(ids.begin(), ids.end());
        return ids;
    };

    // Reading an inverse after every write is the pattern that used to
    // re-sort the whole index per iteration. Enough iterations to fold the
    // delta into the base several times over.
    std::vector<express::base> polylines;
    std::vector<int> expected;
    for (int i = 0; i < 600; ++i) {
        auto polyline = file.create(polyline_declaration);
        polyline.set_attribute_value(0, std::vector<express::base>{target});
        polylines.push_back(polyline);
        expected.push_back(polyline.id());
        REQUIRE(file.instances_by_reference(target.id()).size() == (size_t)i + 1);
    }
    CHECK(referencing_ids(target) == expected);
    CHECK(file.get_inverse_indices_by_id(target.id()) == std::vector<int>(600, 0));
    CHECK(file.get_total_inverses(target.id()) == 600);

    // Repointing an attribute removes the old record and adds a new one,
    // whether the record lives in the base or in the delta.
    for (int i = 0; i < 600; i += 7) {
        polylines[i].set_attribute_value(0, std::vector<express::base>{other});
        expected.erase(std::find(expected.begin(), expected.end(), polylines[i].id()));
    }
    CHECK(referencing_ids(target) == expected);
    CHECK(file.instances_by_reference(other.id()).size() == 86);

    // The same source referencing the target through two attributes yields two records.
    const auto* trimmed_curve_declaration = file.schema()->declaration_by_name("IfcTrimmedCurve");
    auto trimmed = file.create(trimmed_curve_declaration);
    trimmed.set_attribute_value(1, std::vector<express::base>{target});
    trimmed.set_attribute_value(2, std::vector<express::base>{target});
    CHECK(file.instances_by_reference(target.id()).size() == expected.size() + 2);
    CHECK(file.get_total_inverses(target.id()) == expected.size() + 1);
    trimmed.set_attribute_value(2, std::vector<express::base>{other});
    expected.push_back((int)trimmed.id());
    CHECK(referencing_ids(target) == expected);

    // Deleting a referencing instance drops its records; deleting the
    // target drops the records into it.
    file.remove_entity(polylines[1]);
    expected.erase(std::find(expected.begin(), expected.end(), polylines[1].id()));
    CHECK(referencing_ids(target) == expected);
    file.remove_entity(other);
    CHECK(file.instances_by_reference(other.id()).empty());

    // Removing most of the base tombstones it past the compaction threshold.
    for (int i = 2; i < 600; ++i) {
        if (i % 7 != 0) {
            file.remove_entity(polylines[i]);
        }
    }
    CHECK(referencing_ids(target) == std::vector<int>{(int)trimmed.id()});
}

TEST_CASE("Deleting an instance unregisters the records its own attributes contributed", "[ifcparse]") {
    ifcopenshell::file file(ifcopenshell::schema_by_name("IFC4"));
    const auto* point_declaration = file.schema()->declaration_by_name("IfcCartesianPoint");
    const auto* polyline_declaration = file.schema()->declaration_by_name("IfcPolyline");
    const auto* trimmed_curve_declaration = file.schema()->declaration_by_name("IfcTrimmedCurve");

    auto target = file.create(point_declaration);
    auto second = file.create(point_declaration);

    // A reference registered before the first lookup lands in the base tier,
    // one registered after it in the delta.
    auto base_referencer = file.create(polyline_declaration);
    base_referencer.set_attribute_value(0, std::vector<express::base>{target, target});
    REQUIRE(file.instances_by_reference(target.id()).size() == 2);
    auto delta_referencer = file.create(polyline_declaration);
    delta_referencer.set_attribute_value(0, std::vector<express::base>{target, second});
    REQUIRE(file.instances_by_reference(target.id()).size() == 3);

    // Duplicate references in one aggregate contribute two records; deleting
    // the source must drop both.
    file.remove_entity(base_referencer);
    CHECK(file.instances_by_reference(target.id()).size() == 1);

    // Referencing the same instance through two attributes contributes a
    // record per attribute; deleting the source must drop them all.
    auto trimmed = file.create(trimmed_curve_declaration);
    trimmed.set_attribute_value(1, std::vector<express::base>{second});
    trimmed.set_attribute_value(2, std::vector<express::base>{second});
    CHECK(file.instances_by_reference(second.id()).size() == 3);
    file.remove_entity(trimmed);
    CHECK(file.instances_by_reference(second.id()).size() == 1);

    // Deleting the target first prunes it out of the source's attribute, so
    // deleting the source afterwards finds nothing left to unregister.
    file.remove_entity(target);
    file.remove_entity(delta_referencer);
    CHECK(file.instances_by_reference(second.id()).empty());
    CHECK(file.get_total_inverses(second.id()) == 0);
}

TEST_CASE("Batch deletion prunes surviving referencers and leaves no stale records", "[ifcparse]") {
    ifcopenshell::file file(ifcopenshell::schema_by_name("IFC4"));
    const auto* point_declaration = file.schema()->declaration_by_name("IfcCartesianPoint");
    const auto* polyline_declaration = file.schema()->declaration_by_name("IfcPolyline");

    auto kept_point = file.create(point_declaration);
    std::vector<express::base> doomed_points;
    for (int i = 0; i < 50; ++i) {
        doomed_points.push_back(file.create(point_declaration));
    }

    // The survivor references every doomed point plus the kept one; a doomed
    // referencer references the kept point.
    auto survivor = file.create(polyline_declaration);
    auto survivor_points = doomed_points;
    survivor_points.push_back(kept_point);
    survivor.set_attribute_value(0, survivor_points);
    auto doomed_referencer = file.create(polyline_declaration);
    doomed_referencer.set_attribute_value(0, std::vector<express::base>{kept_point});
    REQUIRE(file.instances_by_reference(kept_point.id()).size() == 2);

    file.batch();
    for (auto& point : doomed_points) {
        file.remove_entity(point);
    }
    file.remove_entity(doomed_referencer);
    file.unbatch();

    CHECK((std::vector<express::base>)survivor.get_attribute_value(0) == std::vector<express::base>{kept_point});
    CHECK(file.instances_by_reference(kept_point.id()).size() == 1);
    CHECK(file.get_total_inverses(kept_point.id()) == 1);
    for (auto& point : doomed_points) {
        CHECK(file.instances_by_reference(point.id()).empty());
    }
    CHECK(file.instances_by_reference(doomed_referencer.id()).empty());
}

namespace {

// Real IFC aggregates nest two or three levels. Anything past this is still
// inside the bound suggested for a fix (64) and must keep parsing.
constexpr int kNestingStillAccepted = 32;
// Past any bound that still admits real models. The parser must refuse this
// instead of building the instance.
constexpr int kNestingRejected = 256;
// Enough frames to exhaust the native stack while the recursion is unbounded.
constexpr int kNestingAttack = 100000;

std::string repeated(const std::string& piece, int count) {
    std::string value;
    value.reserve(piece.size() * static_cast<size_t>(count));
    for (int i = 0; i < count; ++i) {
        value += piece;
    }
    return value;
}

std::string ifc_document(const std::string& description_argument, const std::string& data_body) {
    std::string contents;
    contents += "ISO-10303-21;\nHEADER;\n";
    contents += "FILE_DESCRIPTION(" + description_argument + ",'2;1');\n";
    contents += "FILE_NAME('nesting.ifc','2024-01-01T00:00:00',('author'),('org'),'preprocessor','origin','auth');\n";
    contents += "FILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n";
    contents += data_body;
    contents += "ENDSEC;\nEND-ISO-10303-21;\n";
    return contents;
}

// depth 1 is the single list a header description already uses: ('x')
std::string nested_description(int depth) {
    return repeated("(", depth) + "'x'" + repeated(")", depth);
}

// depth 1 is a normal coordinate list: (0.)
std::string nested_point(int depth) {
    return "#1=IFCCARTESIANPOINT(" + repeated("(", depth) + "0." + repeated(")", depth) + ");\n";
}

std::string survivor_point() {
    return "#2=IFCCARTESIANPOINT((1.,2.));\n";
}

// depth 1 is one typed wrapper: IFCLABEL('Name')
std::string nested_label_project(int depth) {
    return "#1=IFCPROJECT('1iBd2lkrX61vZxF9AnXLa0',$," + repeated("IFCLABEL(", depth) + "'Name'" + repeated(")", depth) + ",$,$,$,$,$,$);\n";
}

// depth 1 is one typed value inside the coordinate list.
std::string nested_measure_point(int depth) {
    return "#1=IFCCARTESIANPOINT((" + repeated("IFCLENGTHMEASURE(", depth) + "0." + repeated(")", depth) + "));\n";
}

std::string point_with_discarded_nesting(int depth) {
    return "#1=IFCCARTESIANPOINT((1.,2.)," + repeated("(", depth) + repeated(")", depth) + ");\n";
}

class temporary_ifc {
  public:
    explicit temporary_ifc(const std::string& contents) {
        path_ = std::filesystem::temp_directory_path() / ("ifcopenshell-nesting-" + std::to_string(::getpid()) + "-" + std::to_string(next_id_++) + ".ifc");
        std::ofstream output(path_, std::ios::binary);
        output << contents;
    }

    ~temporary_ifc() {
        std::error_code error;
        std::filesystem::remove(path_, error);
    }

    temporary_ifc(const temporary_ifc&) = delete;
    temporary_ifc& operator=(const temporary_ifc&) = delete;

    const std::filesystem::path& path() const { return path_; }

  private:
    std::filesystem::path path_;
    static int next_id_;
};

int temporary_ifc::next_id_ = 0;

ifcopenshell::logger& silence(ifcopenshell::logger& log) {
    log.verbosity(ifcopenshell::logger::LOG_ERROR);
    return log;
}

std::vector<double> coordinates_of(const express::base& instance) {
    return instance.get_attribute_value(0);
}

void expect_survivor_coordinates(ifcopenshell::file& file) {
    const express::base survivor = file.instance_by_id(2);
    REQUIRE(survivor);
    CHECK(coordinates_of(survivor) == std::vector<double>{1.0, 2.0});
}

// path: the constructor ifcopenshell.open() calls.
// memory: the constructor ifcopenshell.read() calls.
// stream: the istream constructor.
// streamer: the instance streamer ifcopenshell.stream2() calls.
enum class parse_entry {
    path,
    memory,
    stream,
    streamer
};

struct refusal {
    bool threw = false;
    bool constructed = false;
    bool good = false;
    bool malformed_present = false;
    bool survivor_ok = false;
};

refusal open_for_refusal(parse_entry entry, const std::string& contents) {
    refusal result;
    try {
        ifcopenshell::logger log;
        silence(log);
        if (entry == parse_entry::path) {
            temporary_ifc saved(contents);
            ifcopenshell::file file(saved.path().string(), ifcopenshell::FT_AUTODETECT, false, log);
            result.constructed = true;
            result.good = static_cast<bool>(file.good());
            if (result.good) {
                result.malformed_present = static_cast<bool>(file.instance_by_id(1));
                const express::base survivor = file.instance_by_id(2);
                result.survivor_ok = survivor && coordinates_of(survivor) == std::vector<double>{1.0, 2.0};
            }
        } else if (entry == parse_entry::memory) {
            ifcopenshell::file file(const_cast<char*>(contents.data()), static_cast<int>(contents.size()), log);
            result.constructed = true;
            result.good = static_cast<bool>(file.good());
            if (result.good) {
                result.malformed_present = static_cast<bool>(file.instance_by_id(1));
                const express::base survivor = file.instance_by_id(2);
                result.survivor_ok = survivor && coordinates_of(survivor) == std::vector<double>{1.0, 2.0};
            }
        } else if (entry == parse_entry::stream) {
            std::istringstream input(contents);
            ifcopenshell::file file(input, static_cast<int>(contents.size()), log);
            result.constructed = true;
            result.good = static_cast<bool>(file.good());
            if (result.good) {
                result.malformed_present = static_cast<bool>(file.instance_by_id(1));
                const express::base survivor = file.instance_by_id(2);
                result.survivor_ok = survivor && coordinates_of(survivor) == std::vector<double>{1.0, 2.0};
            }
        } else {
            ifcopenshell::instance_streamer<> streamer(const_cast<char*>(contents.data()), static_cast<int>(contents.size()), nullptr, log);
            result.constructed = true;
            while (streamer) {
                auto instance = streamer.read_instance();
                if (!instance) {
                    break;
                }
                const auto id = std::get<0>(*instance);
                if (id == 1) {
                    result.malformed_present = true;
                }
                if (id == 2) {
                    result.survivor_ok = true;
                }
            }
            result.good = streamer.status() == ifcopenshell::file_open_status::SUCCESS;
        }
    } catch (const ifcopenshell::exception&) {
        result.threw = true;
    }
    return result;
}

void expect_refused(const refusal& result) {
    if (result.threw || (result.constructed && !result.good)) {
        return;
    }
    REQUIRE(result.constructed);
    CHECK_FALSE(result.malformed_present);
    CHECK(result.survivor_ok);
}

void expect_malformed_instance_refused(const std::string& contents) {
    expect_refused(open_for_refusal(parse_entry::path, contents));
    expect_refused(open_for_refusal(parse_entry::memory, contents));
    expect_refused(open_for_refusal(parse_entry::stream, contents));
    expect_refused(open_for_refusal(parse_entry::streamer, contents));
}

void expect_header_nesting_refused(const std::string& contents) {
    {
        INFO("file path constructor");
        temporary_ifc saved(contents);
        ifcopenshell::logger log;
        silence(log);
        bool threw = false;
        bool good = true;
        try {
            ifcopenshell::file file(saved.path().string(), ifcopenshell::FT_AUTODETECT, false, log);
            good = static_cast<bool>(file.good());
        } catch (const ifcopenshell::exception&) {
            threw = true;
        }
        if (!threw) {
            CHECK_FALSE(good);
        }
    }
    {
        INFO("instance streamer");
        ifcopenshell::logger log;
        silence(log);
        bool threw = false;
        bool good = true;
        try {
            ifcopenshell::instance_streamer<> streamer(const_cast<char*>(contents.data()), static_cast<int>(contents.size()), nullptr, log);
            good = streamer.status() == ifcopenshell::file_open_status::SUCCESS;
        } catch (const ifcopenshell::exception&) {
            threw = true;
        }
        if (!threw) {
            CHECK_FALSE(good);
        }
    }
}

} // namespace

TEST_CASE("A well formed cartesian point survives every STEP entry point", "[ifcparse][nesting]") {
    const std::string contents = ifc_document(nested_description(1), nested_point(1) + survivor_point());
    temporary_ifc saved(contents);
    ifcopenshell::logger log;
    silence(log);

    ifcopenshell::file from_path(saved.path().string(), ifcopenshell::FT_AUTODETECT, false, log);
    REQUIRE(from_path.good());
    REQUIRE(from_path.instance_by_id(1));
    expect_survivor_coordinates(from_path);

    ifcopenshell::file from_memory(const_cast<char*>(contents.data()), static_cast<int>(contents.size()), log);
    REQUIRE(from_memory.good());
    CHECK(coordinates_of(from_memory.instance_by_id(1)) == std::vector<double>{0.0});
    expect_survivor_coordinates(from_memory);

    std::istringstream input(contents);
    ifcopenshell::file from_stream(input, static_cast<int>(contents.size()), log);
    REQUIRE(from_stream.good());
    expect_survivor_coordinates(from_stream);
}

TEST_CASE("Aggregate nesting within the accepted bound still parses", "[ifcparse][nesting]") {
    const std::string contents = ifc_document(nested_description(1), nested_point(kNestingStillAccepted) + survivor_point());
    temporary_ifc saved(contents);
    ifcopenshell::logger log;
    silence(log);
    ifcopenshell::file file(saved.path().string(), ifcopenshell::FT_AUTODETECT, false, log);

    REQUIRE(file.good());
    const express::base nested = file.instance_by_id(1);
    REQUIRE(nested);
    CHECK(nested.declaration().name() == "IfcCartesianPoint");
    expect_survivor_coordinates(file);
}

TEST_CASE("A single typed value and a typed list element still parse", "[ifcparse][nesting]") {
    const std::string labeled = ifc_document(nested_description(1), nested_label_project(1) + survivor_point());
    const std::string measured = ifc_document(nested_description(1), nested_measure_point(1) + survivor_point());
    ifcopenshell::logger log;
    silence(log);

    {
        temporary_ifc saved(labeled);
        ifcopenshell::file file(saved.path().string(), ifcopenshell::FT_AUTODETECT, false, log);
        REQUIRE(file.good());
        const express::base project = file.instance_by_id(1);
        REQUIRE(project);
        CHECK(project.declaration().name() == "IfcProject");
        expect_survivor_coordinates(file);
    }
    {
        temporary_ifc saved(measured);
        ifcopenshell::file file(saved.path().string(), ifcopenshell::FT_AUTODETECT, false, log);
        REQUIRE(file.good());
        const express::base point = file.instance_by_id(1);
        REQUIRE(point);
        CHECK(point.declaration().name() == "IfcCartesianPoint");
        expect_survivor_coordinates(file);
    }
}

TEST_CASE("Nested parentheses past the accepted bound are refused", "[ifcparse][nesting]") {
    // read_direct_aggregate calls itself for every '(' of a retained attribute.
    // Depth 256 is far past real IFC models and past a bound of 64, and today
    // the instance is kept anyway.
    const std::string contents = ifc_document(nested_description(1), nested_point(kNestingRejected) + survivor_point());
    expect_malformed_instance_refused(contents);
}

TEST_CASE("Attack-depth nested parentheses are refused instead of exhausting the stack", "[ifcparse][nesting]") {
    // The same recursion overflows the native stack once the nesting reaches
    // the depth used by the reported file. The process must not be signalled.
    const std::string contents = ifc_document(nested_description(1), nested_point(kNestingAttack) + survivor_point());
    expect_malformed_instance_refused(contents);
}

TEST_CASE("Nested typed values past the accepted bound are refused", "[ifcparse][nesting]") {
    // in_memory_file_storage::load calls itself for every typed wrapper such
    // as IFCLABEL(IFCLABEL(...)).
    const std::string contents = ifc_document(nested_description(1), nested_label_project(kNestingRejected) + survivor_point());
    expect_malformed_instance_refused(contents);
}

TEST_CASE("Attack-depth nested typed values are refused instead of exhausting the stack", "[ifcparse][nesting]") {
    const std::string contents = ifc_document(nested_description(1), nested_label_project(kNestingAttack) + survivor_point());
    expect_malformed_instance_refused(contents);
}

TEST_CASE("Typed values nested inside an aggregate past the accepted bound are refused", "[ifcparse][nesting]") {
    // read_direct_aggregate dispatches a keyword to load, which then recurses.
    const std::string contents = ifc_document(nested_description(1), nested_measure_point(kNestingRejected) + survivor_point());
    expect_malformed_instance_refused(contents);
}

TEST_CASE("Attack-depth typed values inside an aggregate are refused instead of exhausting the stack", "[ifcparse][nesting]") {
    const std::string contents = ifc_document(nested_description(1), nested_measure_point(kNestingAttack) + survivor_point());
    expect_malformed_instance_refused(contents);
}

TEST_CASE("Header aggregate nesting past the accepted bound is refused", "[ifcparse][nesting]") {
    // Header entities are read through the same load function, before DATA.
    const std::string contents = ifc_document(nested_description(kNestingRejected), survivor_point());
    expect_header_nesting_refused(contents);
}

TEST_CASE("Attack-depth header aggregate nesting is refused instead of exhausting the stack", "[ifcparse][nesting]") {
    const std::string contents = ifc_document(nested_description(kNestingAttack), survivor_point());
    expect_header_nesting_refused(contents);
}

TEST_CASE("A discarded attribute with attack-depth parentheses is skipped iteratively", "[ifcparse][nesting]") {
    // The extra attribute is past IfcCartesianPoint's attribute count, so the
    // parser takes skip_aggregate, which already counts depth in a loop.
    const std::string contents = ifc_document(nested_description(1), point_with_discarded_nesting(kNestingAttack));
    temporary_ifc saved(contents);
    ifcopenshell::logger log;
    silence(log);
    ifcopenshell::file file(saved.path().string(), ifcopenshell::FT_AUTODETECT, false, log);

    REQUIRE(file.good());
    const express::base point = file.instance_by_id(1);
    REQUIRE(point);
    CHECK(coordinates_of(point) == std::vector<double>{1.0, 2.0});

    ifcopenshell::instance_streamer<> streamer(const_cast<char*>(contents.data()), static_cast<int>(contents.size()), nullptr, log);
    bool saw_point = false;
    while (streamer) {
        auto instance = streamer.read_instance();
        if (!instance) {
            break;
        }
        if (std::get<0>(*instance) == 1) {
            saw_point = true;
            const express::base streamed(std::get<2>(*instance));
            CHECK(coordinates_of(streamed) == std::vector<double>{1.0, 2.0});
        }
    }
    CHECK(streamer.status() == ifcopenshell::file_open_status::SUCCESS);
    CHECK(saw_point);
}
