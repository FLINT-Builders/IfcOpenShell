// This file was generated with the assistance of an AI coding tool.
//
// Spec for the RocksDB attribute decoders. A crafted model directory is a
// file a user opens. Each case below is rejected with an exception, and the
// directory is left unchanged, once short records and out-of-range declaration
// indexes are refused before any copy. The cases fail while those copies and
// indexes still happen.

#include <ifcparse/exception.h>
#include <ifcparse/file.h>
#include <ifcparse/instance_data.h>

#include <catch2/catch_test_macros.hpp>

#include <sys/wait.h>
#include <unistd.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <functional>
#include <map>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {

namespace fs = std::filesystem;

struct Model {
    fs::path path;
    uint32_t project_id = 0;
    uint32_t assignment_id = 0;
    uint32_t unit_id = 0;
    uint32_t exponents_id = 0;
    uint32_t context_id = 0;
    uint32_t layer_id = 0;
    uint32_t texture_id = 0;
    uint32_t surface_id = 0;
    uint32_t voids_id = 0;
    int project_units_index = -1;
    int assignment_units_index = -1;
    int unit_type_index = -1;
    int length_exponent_index = -1;
    int precision_index = -1;
    int global_id_index = -1;
    int layer_on_index = -1;
    int raster_code_index = -1;
    int control_points_index = -1;
    int inner_coords_index = -1;
    size_t project_type_index = 0;
    std::string guid;
};

int attribute_index(const ifcopenshell::declaration* declaration, const char* name) {
    const auto index = declaration->as_entity()->attribute_index(name);
    if (index < 0) {
        throw std::runtime_error(std::string("missing attribute ") + name + " on " + declaration->name());
    }
    return static_cast<int>(index);
}

ifcopenshell::enumeration_reference enumeration_item(const ifcopenshell::schema_definition* schema, const char* type_name, const char* item) {
    const auto* enumeration = schema->declaration_by_name(type_name)->as_enumeration_type();
    if (enumeration == nullptr) {
        throw std::runtime_error(std::string("missing enumeration ") + type_name);
    }
    return {enumeration, enumeration->lookup_enum_offset(item)};
}

void put_bytes(ifcopenshell::file& file, const std::string& key, const std::string& value) {
    auto& storage = std::get<ifcopenshell::impl::rocks_db_file_storage>(file.storage_);
    const auto status = storage.db->Put(storage.wopts, key, value);
    if (!status.ok()) {
        throw std::runtime_error(status.ToString());
    }
}

std::string bytes_of(size_t value) {
    std::string encoded(sizeof(value), '\0');
    std::memcpy(encoded.data(), &value, sizeof(value));
    return encoded;
}

template <typename T>
std::string tagged(std::string_view rest) {
    std::string encoded;
    encoded.push_back(ifcopenshell::type_encoder::encode_type<T>());
    encoded.append(rest.data(), rest.size());
    return encoded;
}

std::map<std::string, uintmax_t> fingerprint(const fs::path& root) {
    std::map<std::string, uintmax_t> files;
    for (const auto& entry : fs::recursive_directory_iterator(root)) {
        if (entry.is_regular_file()) {
            files[fs::relative(entry.path(), root).generic_string()] = entry.file_size();
        }
    }
    return files;
}

int run_in_child(const std::function<int()>& body) {
    const pid_t pid = fork();
    if (pid < 0) {
        throw std::runtime_error("fork failed");
    }
    if (pid == 0) {
        // A short entity-list walks off the buffer. Bound the walk so a
        // missed fault cannot stall the suite.
        alarm(10);
        int code = 0;
        try {
            code = body();
        } catch (const std::exception& ex) {
            std::fprintf(stderr, "rejected: %s\n", ex.what());
            code = 2;
        }
        _exit(code);
    }
    int status = 0;
    if (waitpid(pid, &status, 0) < 0) {
        throw std::runtime_error("waitpid failed");
    }
    return status;
}

std::string status_text(int status) {
    if (WIFEXITED(status)) {
        return "exit " + std::to_string(WEXITSTATUS(status));
    }
    if (WIFSIGNALED(status)) {
        return std::string("signal ") + strsignal(WTERMSIG(status));
    }
    return "status " + std::to_string(status);
}

void require_rejection(const fs::path& directory, const std::function<int()>& body) {
    const auto before = fingerprint(directory);
    const int status = run_in_child(body);
    const auto after = fingerprint(directory);
    INFO(status_text(status));
    REQUIRE(after == before);
    REQUIRE(WIFEXITED(status));
    REQUIRE(WEXITSTATUS(status) == 2);
}

template <typename Fn>
int with_open_directory(const fs::path& directory, Fn&& fn) {
    ifcopenshell::file file(directory.string(), ifcopenshell::FT_AUTODETECT, true, ifcopenshell::logger::root());
    if (!file.good()) {
        return 3;
    }
    fn(file);
    return 0;
}

Model build_model() {
    Model model;
    model.path = fs::temp_directory_path() / ("ifcos-rocks-base-" + std::to_string(getpid()));
    fs::remove_all(model.path);
    fs::create_directory(model.path);
    model.guid = "0123456789012345678901";

    ifcopenshell::file file(ifcopenshell::schema_by_name("IFC4"), ifcopenshell::FT_ROCKSDB, model.path.string(), ifcopenshell::logger::root());
    const auto* schema = file.schema();
    auto project = file.create(schema->declaration_by_name("IfcProject"));
    auto assignment = file.create(schema->declaration_by_name("IfcUnitAssignment"));
    auto unit = file.create(schema->declaration_by_name("IfcSIUnit"));
    auto exponents = file.create(schema->declaration_by_name("IfcDimensionalExponents"));
    auto context = file.create(schema->declaration_by_name("IfcGeometricRepresentationContext"));
    auto layer = file.create(schema->declaration_by_name("IfcPresentationLayerWithStyle"));
    auto texture = file.create(schema->declaration_by_name("IfcBlobTexture"));
    auto surface = file.create(schema->declaration_by_name("IfcBSplineSurfaceWithKnots"));
    auto voids = file.create(schema->declaration_by_name("IfcIndexedPolygonalFaceWithVoids"));
    auto point = file.create(schema->declaration_by_name("IfcCartesianPoint"));

    model.project_id = project.id();
    model.assignment_id = assignment.id();
    model.unit_id = unit.id();
    model.exponents_id = exponents.id();
    model.context_id = context.id();
    model.layer_id = layer.id();
    model.texture_id = texture.id();
    model.surface_id = surface.id();
    model.voids_id = voids.id();
    model.project_type_index = project.declaration().index_in_schema();
    model.project_units_index = attribute_index(&project.declaration(), "UnitsInContext");
    model.assignment_units_index = attribute_index(&assignment.declaration(), "Units");
    model.unit_type_index = attribute_index(&unit.declaration(), "UnitType");
    model.length_exponent_index = attribute_index(&exponents.declaration(), "LengthExponent");
    model.precision_index = attribute_index(&context.declaration(), "Precision");
    model.global_id_index = attribute_index(&project.declaration(), "GlobalId");
    model.layer_on_index = attribute_index(&layer.declaration(), "LayerOn");
    model.raster_code_index = attribute_index(&texture.declaration(), "RasterCode");
    model.control_points_index = attribute_index(&surface.declaration(), "ControlPointsList");
    model.inner_coords_index = attribute_index(&voids.declaration(), "InnerCoordIndices");

    project.set_attribute_value(model.global_id_index, model.guid);
    project.set_attribute_value(model.project_units_index, assignment);
    assignment.set_attribute_value(model.assignment_units_index, std::vector<express::base>{unit});
    unit.set_attribute_value(model.unit_type_index, enumeration_item(schema, "IfcUnitEnum", "LENGTHUNIT"));
    unit.set_attribute_value(attribute_index(&unit.declaration(), "Name"), enumeration_item(schema, "IfcSIUnitName", "METRE"));
    exponents.set_attribute_value(model.length_exponent_index, static_cast<int64_t>(1));
    context.set_attribute_value(model.precision_index, 0.5);
    layer.set_attribute_value(model.layer_on_index, boost::logic::tribool(true));
    {
        boost::dynamic_bitset<> code;
        code.push_back(true);
        texture.set_attribute_value(model.raster_code_index, code);
    }
    surface.set_attribute_value(model.control_points_index, std::vector<std::vector<express::base>>{{point, point}, {point, point}});
    voids.set_attribute_value(model.inner_coords_index, std::vector<std::vector<int64_t>>{{1, 2, 3}, {4, 5, 6}});

    put_bytes(file, "g|" + model.guid, bytes_of(model.project_id));
    return model;
}

const Model& base_model() {
    static const Model model = build_model();
    return model;
}

fs::path stage_copy() {
    static int counter = 0;
    const auto dest = fs::temp_directory_path() / ("ifcos-rocks-case-" + std::to_string(getpid()) + "-" + std::to_string(counter++));
    fs::remove_all(dest);
    fs::copy(base_model().path, dest, fs::copy_options::recursive);
    return dest;
}

fs::path tamper(const std::function<void(ifcopenshell::file&)>& edit) {
    const auto directory = stage_copy();
    {
        ifcopenshell::file file(directory.string(), ifcopenshell::FT_ROCKSDB, false, ifcopenshell::logger::root());
        if (!file.good()) {
            throw std::runtime_error("could not reopen model to plant a record");
        }
        edit(file);
    }
    return directory;
}

std::string attribute_key(uint32_t instance, int index) {
    return rocksdb_key::attribute(true, instance, static_cast<uint64_t>(index));
}

void require_read_rejected(const fs::path& directory, const std::function<void(ifcopenshell::file&)>& read) {
    require_rejection(directory, [&] { return with_open_directory(directory, read); });
}

} // namespace

TEST_CASE("A RocksDB model with intact records opens and reports its length unit", "[rocksdb][bounds]") {
    const auto directory = stage_copy();
    const int status = run_in_child([&] {
        return with_open_directory(directory, [&](ifcopenshell::file& file) {
            const auto [unit, scale] = file.get_unit("LENGTHUNIT");
            if (!unit || unit.declaration().name() != "IfcSIUnit" || scale != 1.) {
                throw std::runtime_error("length unit was not read back");
            }
            const std::string kind = unit.as<express::entity>().get("UnitType");
            if (kind != "LENGTHUNIT") {
                throw std::runtime_error("length unit kind was not read back");
            }
        });
    });
    INFO(status_text(status));
    REQUIRE(WIFEXITED(status));
    REQUIRE(WEXITSTATUS(status) == 0);
}

TEST_CASE("An empty entity list is rejected when units are read", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        put_bytes(file, attribute_key(model.assignment_id, model.assignment_units_index), "");
    });
    require_read_rejected(directory, [](ifcopenshell::file& file) { (void)file.get_unit("LENGTHUNIT"); });
}

TEST_CASE("An enumeration declaration index past the schema is rejected", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        const size_t past_the_table = 1000000000;
        put_bytes(file, attribute_key(model.unit_id, model.unit_type_index), tagged<ifcopenshell::enumeration_reference>(bytes_of(past_the_table) + bytes_of(0)));
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) {
        const std::string kind = file.instance_by_id(model.unit_id).as<express::entity>().get("UnitType");
        (void)kind;
    });
}

TEST_CASE("An enumeration reference with a declaration index past the schema is rejected", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        const size_t past_the_table = 1000000000;
        put_bytes(file, attribute_key(model.unit_id, model.unit_type_index), tagged<ifcopenshell::enumeration_reference>(bytes_of(past_the_table) + bytes_of(0)));
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) {
        const ifcopenshell::enumeration_reference reference = file.instance_by_id(model.unit_id).get_attribute_value(model.unit_type_index);
        if (reference.enumeration() != nullptr) {
            (void)reference.value();
        }
    });
}

TEST_CASE("A one-byte enumeration record is rejected", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        put_bytes(file, attribute_key(model.unit_id, model.unit_type_index), tagged<ifcopenshell::enumeration_reference>(""));
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) {
        const std::string kind = file.instance_by_id(model.unit_id).as<express::entity>().get("UnitType");
        (void)kind;
    });
}

TEST_CASE("A one-byte enumeration reference is rejected", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        put_bytes(file, attribute_key(model.unit_id, model.unit_type_index), tagged<ifcopenshell::enumeration_reference>(""));
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) {
        const ifcopenshell::enumeration_reference reference = file.instance_by_id(model.unit_id).get_attribute_value(model.unit_type_index);
        (void)reference;
    });
}

TEST_CASE("A short instance type record is rejected when the instance is resolved", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        put_bytes(file, rocksdb_key::type_record(true, model.project_id), "x");
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) { (void)file.instances_by_type("IfcProject"); });
}

TEST_CASE("A short type-list value is rejected when projects are listed", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        put_bytes(file, rocksdb_key::type_list(model.project_type_index), "abc");
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) { (void)file.instances_by_type("IfcProject"); });
}

TEST_CASE("A one-byte integer attribute is rejected", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        put_bytes(file, attribute_key(model.exponents_id, model.length_exponent_index), tagged<int64_t>(""));
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) {
        const int64_t exponent = file.instance_by_id(model.exponents_id).get_attribute_value(model.length_exponent_index);
        (void)exponent;
    });
}

TEST_CASE("A one-byte real attribute is rejected", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        put_bytes(file, attribute_key(model.context_id, model.precision_index), tagged<double>(""));
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) {
        const double precision = file.instance_by_id(model.context_id).get_attribute_value(model.precision_index);
        (void)precision;
    });
}

TEST_CASE("A one-byte logical attribute is rejected", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        put_bytes(file, attribute_key(model.layer_id, model.layer_on_index), tagged<boost::logic::tribool>(""));
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) {
        const boost::logic::tribool layer_on = file.instance_by_id(model.layer_id).get_attribute_value(model.layer_on_index);
        (void)layer_on;
    });
}

TEST_CASE("An empty string attribute is rejected", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        put_bytes(file, attribute_key(model.project_id, model.global_id_index), "");
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) {
        const auto attribute = file.instance_by_id(model.project_id).get_attribute_value(model.global_id_index);
        (void)attribute.type();
        const std::string guid = attribute;
        (void)guid;
    });
}

TEST_CASE("An empty binary attribute is rejected", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        put_bytes(file, attribute_key(model.texture_id, model.raster_code_index), "");
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) {
        const boost::dynamic_bitset<> code = file.instance_by_id(model.texture_id).get_attribute_value(model.raster_code_index);
        (void)code;
    });
}

TEST_CASE("A short list of lists of integers is rejected", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        put_bytes(file, attribute_key(model.voids_id, model.inner_coords_index), tagged<std::vector<std::vector<int64_t>>>("xxxx"));
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) {
        const std::vector<std::vector<int64_t>> indices = file.instance_by_id(model.voids_id).get_attribute_value(model.inner_coords_index);
        (void)indices;
    });
}

TEST_CASE("A short list of lists of entities is rejected", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        put_bytes(file, attribute_key(model.surface_id, model.control_points_index), tagged<std::vector<std::vector<express::base>>>("xxxx"));
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) {
        const std::vector<std::vector<express::base>> points = file.instance_by_id(model.surface_id).get_attribute_value(model.control_points_index);
        (void)points;
    });
}

TEST_CASE("A short inverse record is rejected", "[rocksdb][bounds]") {
    const Model& model = base_model();
    const auto directory = tamper([&](ifcopenshell::file& file) {
        put_bytes(file, rocksdb_key::inverse(model.project_id, model.project_type_index, 0), "abc");
    });
    require_read_rejected(directory, [&](ifcopenshell::file& file) {
        (void)file.get_inverse(model.project_id, file.schema()->declaration_by_name("IfcProject"), 0);
    });
}

TEST_CASE("A type key whose declaration index is past the schema is rejected", "[rocksdb][bounds]") {
    const auto directory = tamper([](ifcopenshell::file& file) {
        auto& storage = std::get<ifcopenshell::impl::rocks_db_file_storage>(file.storage_);
        rocksdb::WriteBatch batch;
        auto iterator = std::unique_ptr<rocksdb::Iterator>(storage.db->NewIterator(rocksdb::ReadOptions{}));
        for (iterator->Seek("t|"); iterator->Valid() && iterator->key().starts_with("t|"); iterator->Next()) {
            batch.Delete(iterator->key());
        }
        batch.Put("t|1000000000|x", "z");
        const auto status = storage.db->Write(storage.wopts, &batch);
        if (!status.ok()) {
            throw std::runtime_error(status.ToString());
        }
    });
    require_read_rejected(directory, [](ifcopenshell::file& file) {
        auto cursor = file.types_begin();
        if (cursor == file.types_end()) {
            return;
        }
        const ifcopenshell::declaration* declaration = *cursor;
        (void)declaration->name();
    });
}

TEST_CASE("An empty schema record is rejected when the directory is opened", "[rocksdb][bounds]") {
    const auto directory = tamper([](ifcopenshell::file& file) { put_bytes(file, rocksdb_key::header_attribute("file_schema", 0), ""); });
    require_rejection(directory, [&] {
        ifcopenshell::file file(directory.string(), ifcopenshell::FT_AUTODETECT, true, ifcopenshell::logger::root());
        if (file.good()) {
            return 0;
        }
        return 2;
    });
}

TEST_CASE("A short schema record is rejected when the directory is opened", "[rocksdb][bounds]") {
    const auto directory = tamper([](ifcopenshell::file& file) {
        put_bytes(file, rocksdb_key::header_attribute("file_schema", 0), tagged<std::vector<std::string>>("xxxx"));
    });
    require_rejection(directory, [&] {
        ifcopenshell::file file(directory.string(), ifcopenshell::FT_AUTODETECT, true, ifcopenshell::logger::root());
        if (file.good()) {
            return 0;
        }
        return 2;
    });
}
