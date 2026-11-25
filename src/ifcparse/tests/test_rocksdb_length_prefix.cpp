// This file was generated with the assistance of an AI coding tool.
//
// These tests plant a RocksDB model directory and open it through
// ifcopenshell::file. They are expected to fail until every length-prefixed
// RocksDB read rejects a size that does not fit in the stored value.

#include <catch2/catch_test_macros.hpp>

#include <ifcparse/file.h>
#include <ifcparse/instance_data.h>

#include <rocksdb/db.h>

#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

namespace fs = std::filesystem;

constexpr size_t kPastMapping = 32u * 1024u * 1024u;

struct DirectoryGuard {
    fs::path path;
    ~DirectoryGuard() {
        std::error_code error;
        fs::remove_all(path, error);
    }
};

std::map<std::string, std::string> snapshot_directory(const fs::path& directory) {
    std::map<std::string, std::string> files;
    for (const auto& entry : fs::recursive_directory_iterator(directory)) {
        if (!entry.is_regular_file()) {
            continue;
        }
        std::ifstream input(entry.path(), std::ios::binary);
        files[fs::relative(entry.path(), directory).generic_string()] =
            std::string(std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>());
    }
    return files;
}

void append_size(std::string& out, size_t value) {
    out.append(reinterpret_cast<const char*>(&value), sizeof(value));
}

template <typename T>
char type_tag() {
    return ifcopenshell::type_encoder::encode_type<T>();
}

std::string nested_aggregate(char tag, std::vector<std::pair<size_t, std::string>> elements) {
    std::string value(1, tag);
    for (const auto& element : elements) {
        append_size(value, element.first);
        value += element.second;
    }
    return value;
}

std::string valid_file_schema() {
    return nested_aggregate(type_tag<std::vector<std::string>>(), {{4, "IFC4"}});
}

std::string type_record_bytes(size_t declaration_index) {
    std::string value(sizeof(size_t), '\0');
    std::memcpy(value.data(), &declaration_index, sizeof(declaration_index));
    return value;
}

fs::path plant_database(const std::string& name, const std::vector<std::pair<std::string, std::string>>& records) {
    const fs::path directory = fs::temp_directory_path() / ("ifcopenshell-rocksdb-length-" + name);
    fs::remove_all(directory);
    fs::create_directories(directory);

    rocksdb::Options options;
    options.create_if_missing = true;
    rocksdb::DB* raw = nullptr;
    const rocksdb::Status opened = rocksdb::DB::Open(options, directory.string(), &raw);
    REQUIRE(opened.ok());
    std::unique_ptr<rocksdb::DB> database(raw);
    for (const auto& record : records) {
        REQUIRE(database->Put(rocksdb::WriteOptions{}, record.first, record.second).ok());
    }
    database.reset();
    return directory;
}

const std::string& file_schema_key() {
    static const std::string key = rocksdb_key::header_attribute("file_schema", 0);
    return key;
}

bool rejected_without_reading_past_value(const std::exception& error) {
    const std::string message = error.what();
    return message.find("bad_alloc") == std::string::npos;
}

bool open_rejects_schema(const fs::path& directory, bool readonly) {
    try {
        ifcopenshell::file model(directory.string(), ifcopenshell::FT_AUTODETECT, readonly);
        return !model.good() && model.good().value() == ifcopenshell::file_open_status::UNSUPPORTED_SCHEMA;
    } catch (const std::bad_alloc&) {
        throw;
    } catch (const std::exception& error) {
        return rejected_without_reading_past_value(error);
    }
}

template <typename T>
bool attribute_read_rejects(ifcopenshell::file& model, int instance_id, uint8_t index) {
    try {
        T value = model.instance_by_id(instance_id).get_attribute_value(index);
        (void)value;
        return false;
    } catch (const std::bad_alloc&) {
        throw;
    } catch (const std::exception& error) {
        return rejected_without_reading_past_value(error);
    }
}

const ifcopenshell::declaration* small_entity() {
    for (const auto* declaration : ifcopenshell::schema_by_name("IFC4")->declarations()) {
        if (declaration->as_entity() != nullptr && declaration->index_in_schema() > 0 && declaration->index_in_schema() < 256) {
            return declaration;
        }
    }
    return nullptr;
}

} // namespace

TEST_CASE("A well-formed RocksDB directory opens as that schema", "[ifcparse][rocksdb]") {
    const auto directory = plant_database("valid-schema", {{file_schema_key(), valid_file_schema()}});
    const DirectoryGuard guard{directory};
    const auto before = snapshot_directory(directory);

    REQUIRE(ifcopenshell::guess_file_type(directory.string()) == ifcopenshell::FT_ROCKSDB);

    ifcopenshell::file model(directory.string(), ifcopenshell::FT_AUTODETECT, true);
    REQUIRE(model.good());
    REQUIRE(model.schema()->name() == "IFC4");
    REQUIRE(snapshot_directory(directory) == before);
}

TEST_CASE("Opening a RocksDB model rejects a file_schema length past the stored bytes", "[ifcparse][rocksdb]") {
    const auto value = nested_aggregate(type_tag<std::vector<std::string>>(), {{kPastMapping, "IFC4"}});
    const auto directory = plant_database("schema-length", {{file_schema_key(), value}});
    const DirectoryGuard guard{directory};
    const auto before = snapshot_directory(directory);

    REQUIRE(open_rejects_schema(directory, true));
    REQUIRE(snapshot_directory(directory) == before);
}

TEST_CASE("The default RocksDB open rejects a file_schema length with no payload", "[ifcparse][rocksdb]") {
    const auto value = nested_aggregate(type_tag<std::vector<std::string>>(), {{kPastMapping, ""}});
    const auto directory = plant_database("schema-length-default", {{file_schema_key(), value}});
    const DirectoryGuard guard{directory};

    REQUIRE(open_rejects_schema(directory, false));
}

TEST_CASE("A later file_schema length is rejected and not only the first", "[ifcparse][rocksdb]") {
    const auto value = nested_aggregate(
        type_tag<std::vector<std::string>>(),
        {{4, "IFC4"}, {kPastMapping, ""}});
    const auto directory = plant_database("schema-second-length", {{file_schema_key(), value}});
    const DirectoryGuard guard{directory};
    const auto before = snapshot_directory(directory);

    REQUIRE(open_rejects_schema(directory, true));
    REQUIRE(snapshot_directory(directory) == before);
}

TEST_CASE("A length that fits the whole value but not the following bytes is rejected", "[ifcparse][rocksdb]") {
    constexpr size_t prefix = 48u * 1024u * 1024u;
    constexpr size_t claimed = 32u * 1024u * 1024u;
    const auto value = nested_aggregate(
        type_tag<std::vector<std::string>>(),
        {{prefix, std::string(prefix, 'A')}, {claimed, std::string(32, 'B')}});
    REQUIRE(claimed < value.size());
    REQUIRE(claimed > 32u);
    const auto directory = plant_database("schema-length-within-buffer", {{file_schema_key(), value}});
    const DirectoryGuard guard{directory};
    const auto before = snapshot_directory(directory);

    REQUIRE(open_rejects_schema(directory, true));
    REQUIRE(snapshot_directory(directory) == before);
}

TEST_CASE("Nested aggregate attributes reject a length past the stored bytes", "[ifcparse][rocksdb]") {
    const auto declaration = ifcopenshell::schema_by_name("IFC4")->declaration_by_name("IfcWall");
    REQUIRE(declaration != nullptr);
    const auto declaration_index = static_cast<size_t>(declaration->index_in_schema());
    const std::vector<std::pair<std::string, std::string>> common = {
        {file_schema_key(), valid_file_schema()},
        {rocksdb_key::type_record(true, 1), type_record_bytes(declaration_index)},
    };

    {
        auto records = common;
        records.emplace_back(
            rocksdb_key::attribute(true, 1, 0),
            nested_aggregate(type_tag<std::vector<std::string>>(), {{kPastMapping, "wall"}}));
        const auto directory = plant_database("attr-strings", records);
        const DirectoryGuard guard{directory};
        const auto before = snapshot_directory(directory);
        ifcopenshell::file model(directory.string(), ifcopenshell::FT_AUTODETECT, true);
        REQUIRE(model.good());
        REQUIRE(attribute_read_rejects<std::vector<std::string>>(model, 1, 0));
        REQUIRE(snapshot_directory(directory) == before);
    }
    {
        auto records = common;
        records.emplace_back(
            rocksdb_key::attribute(true, 1, 0),
            nested_aggregate(type_tag<std::vector<std::vector<int64_t>>>(), {{kPastMapping, ""}}));
        const auto directory = plant_database("attr-ints", records);
        const DirectoryGuard guard{directory};
        ifcopenshell::file model(directory.string(), ifcopenshell::FT_AUTODETECT, true);
        REQUIRE(model.good());
        REQUIRE(attribute_read_rejects<std::vector<std::vector<int64_t>>>(model, 1, 0));
    }
    {
        auto records = common;
        records.emplace_back(
            rocksdb_key::attribute(true, 1, 0),
            nested_aggregate(type_tag<std::vector<std::vector<double>>>(), {{kPastMapping, ""}}));
        const auto directory = plant_database("attr-doubles", records);
        const DirectoryGuard guard{directory};
        ifcopenshell::file model(directory.string(), ifcopenshell::FT_AUTODETECT, true);
        REQUIRE(model.good());
        REQUIRE(attribute_read_rejects<std::vector<std::vector<double>>>(model, 1, 0));
    }
}

TEST_CASE("Scalar RocksDB attributes reject a value shorter than the encoded type", "[ifcparse][rocksdb]") {
    const auto declaration = ifcopenshell::schema_by_name("IFC4")->declaration_by_name("IfcWall");
    const auto type_record = type_record_bytes(static_cast<size_t>(declaration->index_in_schema()));
    const std::string schema = valid_file_schema();

    {
        const auto directory = plant_database(
            "attr-int",
            {{file_schema_key(), schema},
             {rocksdb_key::type_record(true, 1), type_record},
             {rocksdb_key::attribute(true, 1, 0), std::string(1, type_tag<int64_t>())}});
        const DirectoryGuard guard{directory};
        ifcopenshell::file model(directory.string(), ifcopenshell::FT_AUTODETECT, true);
        REQUIRE(model.good());
        REQUIRE(attribute_read_rejects<int64_t>(model, 1, 0));
    }
    {
        const auto directory = plant_database(
            "attr-double",
            {{file_schema_key(), schema},
             {rocksdb_key::type_record(true, 1), type_record},
             {rocksdb_key::attribute(true, 1, 0), std::string(1, type_tag<double>())}});
        const DirectoryGuard guard{directory};
        ifcopenshell::file model(directory.string(), ifcopenshell::FT_AUTODETECT, true);
        REQUIRE(model.good());
        REQUIRE(attribute_read_rejects<double>(model, 1, 0));
    }
}

TEST_CASE("A short enumeration value is rejected", "[ifcparse][rocksdb]") {
    const auto declaration = ifcopenshell::schema_by_name("IFC4")->declaration_by_name("IfcWall");
    const auto directory = plant_database(
        "attr-enum",
        {{file_schema_key(), valid_file_schema()},
         {rocksdb_key::type_record(true, 1), type_record_bytes(static_cast<size_t>(declaration->index_in_schema()))},
         {rocksdb_key::attribute(true, 1, 0), std::string(1, type_tag<ifcopenshell::enumeration_reference>())}});
    const DirectoryGuard guard{directory};
    ifcopenshell::file model(directory.string(), ifcopenshell::FT_AUTODETECT, true);
    REQUIRE(model.good());
    REQUIRE(attribute_read_rejects<ifcopenshell::enumeration_reference>(model, 1, 0));
    REQUIRE(attribute_read_rejects<std::string>(model, 1, 0));
}

TEST_CASE("A short entity reference is rejected", "[ifcparse][rocksdb]") {
    const auto* declaration = small_entity();
    REQUIRE(declaration != nullptr);
    const auto type_record = type_record_bytes(static_cast<size_t>(declaration->index_in_schema()));
    std::string reference(2, '\0');
    reference[1] = 'i';
    const auto directory = plant_database(
        "attr-entity-ref",
        {{file_schema_key(), valid_file_schema()},
         {rocksdb_key::type_record(true, 0), type_record},
         {rocksdb_key::type_record(true, 1), type_record},
         {rocksdb_key::attribute(true, 1, 0), reference}});
    const DirectoryGuard guard{directory};
    ifcopenshell::file model(directory.string(), ifcopenshell::FT_AUTODETECT, true);
    REQUIRE(model.good());
    REQUIRE(attribute_read_rejects<express::base>(model, 1, 0));
}

TEST_CASE("A type record shorter than a declaration index is rejected", "[ifcparse][rocksdb]") {
    const auto* declaration = small_entity();
    REQUIRE(declaration != nullptr);
    const auto directory = plant_database(
        "short-type-record",
        {{file_schema_key(), valid_file_schema()},
         {rocksdb_key::type_record(true, 1), std::string(1, static_cast<char>(declaration->index_in_schema()))}});
    const DirectoryGuard guard{directory};
    const auto before = snapshot_directory(directory);
    ifcopenshell::file model(directory.string(), ifcopenshell::FT_AUTODETECT, true);
    REQUIRE(model.good());
    bool rejected = false;
    try {
        const auto instance = model.instance_by_id(1);
        (void)instance;
    } catch (const std::bad_alloc&) {
        throw;
    } catch (const std::exception& error) {
        rejected = rejected_without_reading_past_value(error);
    }
    REQUIRE(rejected);
    REQUIRE(snapshot_directory(directory) == before);
}

TEST_CASE("A guid record shorter than an instance id is rejected", "[ifcparse][rocksdb]") {
    const auto declaration = ifcopenshell::schema_by_name("IFC4")->declaration_by_name("IfcWall");
    const auto directory = plant_database(
        "short-guid",
        {{file_schema_key(), valid_file_schema()},
         {rocksdb_key::type_record(true, 1), type_record_bytes(static_cast<size_t>(declaration->index_in_schema()))},
         {"g|short-guid", std::string(1, '\x01')}});
    const DirectoryGuard guard{directory};
    ifcopenshell::file model(directory.string(), ifcopenshell::FT_AUTODETECT, true);
    REQUIRE(model.good());
    bool rejected = false;
    try {
        const auto instance = model.instance_by_guid("short-guid");
        (void)instance;
    } catch (const std::bad_alloc&) {
        throw;
    } catch (const std::exception& error) {
        rejected = rejected_without_reading_past_value(error);
    }
    REQUIRE(rejected);
}

TEST_CASE("Instance lists reject a value whose length is not a whole id", "[ifcparse][rocksdb]") {
    const auto declaration = ifcopenshell::schema_by_name("IFC4")->declaration_by_name("IfcWall");
    const auto directory = plant_database(
        "short-bytype",
        {{file_schema_key(), valid_file_schema()},
         {rocksdb_key::type_list(static_cast<size_t>(declaration->index_in_schema())), std::string(1, 'x')}});
    const DirectoryGuard guard{directory};
    ifcopenshell::file model(directory.string(), ifcopenshell::FT_AUTODETECT, true);
    REQUIRE(model.good());
    bool rejected = false;
    try {
        const auto instances = model.instances_by_type("IfcWall");
        (void)instances;
    } catch (const std::bad_alloc&) {
        throw;
    } catch (const std::exception& error) {
        rejected = rejected_without_reading_past_value(error);
    }
    REQUIRE(rejected);
}

TEST_CASE("Inverse lists reject a value whose length is not a whole id", "[ifcparse][rocksdb]") {
    const auto directory = plant_database(
        "short-inverse",
        {{file_schema_key(), valid_file_schema()},
         {rocksdb_key::inverse(7, 1, 0), std::string(1, 'x')}});
    const DirectoryGuard guard{directory};
    ifcopenshell::file model(directory.string(), ifcopenshell::FT_AUTODETECT, true);
    REQUIRE(model.good());
    bool rejected = false;
    try {
        const auto instances = model.instances_by_reference(7);
        (void)instances;
    } catch (const std::bad_alloc&) {
        throw;
    } catch (const std::exception& error) {
        rejected = rejected_without_reading_past_value(error);
    }
    REQUIRE(rejected);
}
