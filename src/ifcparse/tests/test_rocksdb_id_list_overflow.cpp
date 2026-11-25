// This file was generated with the assistance of an AI coding tool.
//
// These tests fail while a RocksDB id list whose length is not a multiple of
// the id width is copied into a shorter heap buffer. They pass once that copy
// is rejected or truncated to the rounded byte count. Build IfcParse and this
// executable with -fsanitize=address; the overflow is one byte and AddressSanitizer
// is what makes the failure reliable.

#include <catch2/catch_test_macros.hpp>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <ifcparse/file.h>
#include <memory>
#include <rocksdb/db.h>
#include <rocksdb/merge_operator.h>
#include <string>
#include <sys/wait.h>
#include <unistd.h>
#include <utility>
#include <vector>

#if !defined(__SANITIZE_ADDRESS__)
#if !defined(__has_feature)
#define __has_feature(x) 0
#endif
#if !__has_feature(address_sanitizer)
#error "test_rocksdb_id_list_overflow.cpp must be compiled with -fsanitize=address"
#endif
#endif

namespace {

namespace fs = std::filesystem;

enum class Query {
    ByType,
    ByTypeExcl,
    ByReference,
    AllReferencing,
    GetInverseUntyped,
    GetInverseTyped,
    InverseIndices,
    DeleteReferencer,
    ClearReference,
    RemoveTypeRef,
};

struct Fixture {
    fs::path dir;
    int point_id = 0;
    int placement_id = 0;
    std::string point_type_list_key;
    std::string point_inverse_key;

    ~Fixture() {
        std::error_code ec;
        fs::remove_all(dir, ec);
    }
};

// Same concatenation the file storage installs, so a Get sees the merged id list
// the product wrote. The name matches ConcatenateIdMergeOperator in file.h.
class ReadMergeOperator : public rocksdb::AssociativeMergeOperator {
  public:
    bool FullMergeV2(const MergeOperationInput& merge_in, MergeOperationOutput* merge_out) const override {
        merge_out->new_value.clear();
        if (merge_in.existing_value) {
            merge_out->new_value.append(merge_in.existing_value->data(), merge_in.existing_value->size());
        }
        for (const auto& operand : merge_in.operand_list) {
            merge_out->new_value.append(operand.data(), operand.size());
        }
        return true;
    }

    bool Merge(const rocksdb::Slice&, const rocksdb::Slice*, const rocksdb::Slice&, std::string*, rocksdb::Logger*) const override {
        return false;
    }

    const char* Name() const override { return "ConcatenateIdMergeOperator"; }
};

std::unique_ptr<rocksdb::DB> open_db(const fs::path& dir) {
    rocksdb::Options options;
    options.create_if_missing = false;
    options.merge_operator.reset(new ReadMergeOperator());
    rocksdb::DB* raw = nullptr;
    auto status = rocksdb::DB::Open(options, dir.string(), &raw);
    REQUIRE(status.ok());
    return std::unique_ptr<rocksdb::DB>(raw);
}

std::string read_value(rocksdb::DB& db, const std::string& key) {
    std::string value;
    auto status = db.Get(rocksdb::ReadOptions{}, key, &value);
    if (!status.ok()) {
        std::string keys;
        auto it = std::unique_ptr<rocksdb::Iterator>(db.NewIterator(rocksdb::ReadOptions{}));
        for (it->SeekToFirst(); it->Valid(); it->Next()) {
            keys += it->key().ToString();
            keys += "\n";
        }
        FAIL("missing key " << key << " status " << status.ToString() << " keys:\n"
                            << keys);
    }
    return value;
}

// Leaves a value whose length is one byte past a multiple of elem, which is the
// input the undersized vector allocation accepts.
void append_unaligned_byte(const fs::path& dir, const std::string& key, size_t elem) {
    auto db = open_db(dir);
    auto value = read_value(*db, key);
    REQUIRE(value.size() >= elem);
    REQUIRE(value.size() % elem == 0);
    value.push_back('\x5a');
    auto status = db->Put(rocksdb::WriteOptions{}, key, value);
    REQUIRE(status.ok());
    rocksdb::FlushOptions flush;
    flush.wait = true;
    status = db->Flush(flush);
    REQUIRE(status.ok());
    auto stored = read_value(*db, key);
    REQUIRE(stored.size() == value.size());
    REQUIRE(stored.size() % elem == 1);
}

Fixture make_fixture() {
    Fixture fixture;
    fixture.dir = fs::temp_directory_path() / ("ifc-rocksdb-id-list-" + std::to_string(getpid()) + "-" + std::to_string(rand()));
    fs::create_directories(fixture.dir);

    const auto* schema = ifcopenshell::schema_by_name("IFC4");
    REQUIRE(schema != nullptr);
    const auto* point_decl = schema->declaration_by_name("IfcCartesianPoint");
    const auto* placement_decl = schema->declaration_by_name("IfcAxis2Placement3D");
    REQUIRE(point_decl != nullptr);
    REQUIRE(placement_decl != nullptr);

    {
        ifcopenshell::file file(schema, ifcopenshell::FT_ROCKSDB, fixture.dir.string());
        REQUIRE(file.good());
        auto point = file.create(point_decl);
        auto placement = file.create(placement_decl);
        // IfcPlacement.Location is attribute 0.
        placement.set_attribute_value(0, point);
        REQUIRE(file.instances_by_reference(point.id()).size() == 1);

        fixture.point_id = point.id();
        fixture.placement_id = placement.id();
        fixture.point_type_list_key = rocksdb_key::type_list(point_decl->index_in_schema());
        fixture.point_inverse_key = rocksdb_key::inverse(static_cast<uint64_t>(point.id()), placement_decl->index_in_schema(), 0);
    }
    return fixture;
}

int run_query(Query query, const fs::path& dir, int point_id, int placement_id) {
    try {
        ifcopenshell::file file(dir.string(), ifcopenshell::FT_ROCKSDB, false);
        if (!file.good()) {
            return 2;
        }
        try {
            switch (query) {
            case Query::ByType:
                file.instances_by_type("IfcCartesianPoint");
                break;
            case Query::ByTypeExcl:
                file.instances_by_type_excl_subtypes("IfcCartesianPoint");
                break;
            case Query::ByReference:
                file.instances_by_reference(point_id);
                break;
            case Query::AllReferencing:
                file.all_referencing_instances(point_id, [](uint32_t) { return true; });
                break;
            case Query::GetInverseUntyped:
                file.get_inverse(point_id, nullptr, -1);
                break;
            case Query::GetInverseTyped: {
                const auto* placement_decl = file.schema()->declaration_by_name("IfcAxis2Placement3D");
                file.get_inverse(point_id, placement_decl, 0);
                break;
            }
            case Query::InverseIndices:
                file.get_inverse_indices_by_id(point_id);
                break;
            case Query::DeleteReferencer:
                file.remove_entity(file.instance_by_id(placement_id));
                break;
            case Query::ClearReference:
                file.instance_by_id(placement_id).set_attribute_value(0, ifcopenshell::blank{});
                break;
            case Query::RemoveTypeRef:
                file.remove_type_ref(file.instance_by_id(point_id));
                break;
            }
        } catch (const std::exception&) {
            // Rejecting the odd-length list is a fix. Truncating it and then
            // failing a later lookup is also a fix. Overflow is not.
            return 0;
        }
        return 0;
    } catch (const std::exception&) {
        return 3;
    }
}

void expect_no_heap_overflow(Query query, const Fixture& fixture) {
    const pid_t pid = fork();
    REQUIRE(pid >= 0);
    if (pid == 0) {
        const int code = run_query(query, fixture.dir, fixture.point_id, fixture.placement_id);
        _exit(code);
    }
    int status = 0;
    REQUIRE(waitpid(pid, &status, 0) == pid);
    if (WIFSIGNALED(status) || (WIFEXITED(status) && WEXITSTATUS(status) == 1)) {
        FAIL("id-list copy wrote past the heap buffer (query " << static_cast<int>(query) << ")");
    }
    REQUIRE(WIFEXITED(status));
    if (WEXITSTATUS(status) == 2) {
        FAIL("RocksDB model did not open");
    }
    if (WEXITSTATUS(status) == 3) {
        FAIL("opening the RocksDB model threw");
    }
    REQUIRE(WEXITSTATUS(status) == 0);
}

} // namespace

TEST_CASE("aligned rocksdb id lists are readable", "[rocksdb][overflow]") {
    const auto fixture = make_fixture();
    expect_no_heap_overflow(Query::ByType, fixture);
    expect_no_heap_overflow(Query::ByReference, fixture);
}

TEST_CASE("by-type id list with a trailing byte does not overflow", "[rocksdb][overflow]") {
    const auto fixture = make_fixture();
    append_unaligned_byte(fixture.dir, fixture.point_type_list_key, sizeof(size_t));
    expect_no_heap_overflow(Query::ByType, fixture);
}

TEST_CASE("by-type excl id list with a trailing byte does not overflow", "[rocksdb][overflow]") {
    const auto fixture = make_fixture();
    append_unaligned_byte(fixture.dir, fixture.point_type_list_key, sizeof(size_t));
    expect_no_heap_overflow(Query::ByTypeExcl, fixture);
}

TEST_CASE("inverse id list with a trailing byte does not overflow", "[rocksdb][overflow]") {
    const auto fixture = make_fixture();
    append_unaligned_byte(fixture.dir, fixture.point_inverse_key, sizeof(uint32_t));
    expect_no_heap_overflow(Query::ByReference, fixture);
}

TEST_CASE("all referencing instances with a trailing byte does not overflow", "[rocksdb][overflow]") {
    const auto fixture = make_fixture();
    append_unaligned_byte(fixture.dir, fixture.point_inverse_key, sizeof(uint32_t));
    expect_no_heap_overflow(Query::AllReferencing, fixture);
}

TEST_CASE("untyped get_inverse with a trailing byte does not overflow", "[rocksdb][overflow]") {
    const auto fixture = make_fixture();
    append_unaligned_byte(fixture.dir, fixture.point_inverse_key, sizeof(uint32_t));
    expect_no_heap_overflow(Query::GetInverseUntyped, fixture);
}

TEST_CASE("typed get_inverse decodes a trailing byte without overflow", "[rocksdb][overflow]") {
    const auto fixture = make_fixture();
    append_unaligned_byte(fixture.dir, fixture.point_inverse_key, sizeof(uint32_t));
    expect_no_heap_overflow(Query::GetInverseTyped, fixture);
}

TEST_CASE("inverse attribute indices with a trailing byte do not overflow", "[rocksdb][overflow]") {
    const auto fixture = make_fixture();
    append_unaligned_byte(fixture.dir, fixture.point_inverse_key, sizeof(uint32_t));
    expect_no_heap_overflow(Query::InverseIndices, fixture);
}

TEST_CASE("deletion walks an inverse id list with a trailing byte", "[rocksdb][overflow]") {
    const auto fixture = make_fixture();
    append_unaligned_byte(fixture.dir, fixture.point_inverse_key, sizeof(uint32_t));
    expect_no_heap_overflow(Query::DeleteReferencer, fixture);
}

TEST_CASE("clearing a reference rewrites an inverse id list with a trailing byte", "[rocksdb][overflow]") {
    const auto fixture = make_fixture();
    append_unaligned_byte(fixture.dir, fixture.point_inverse_key, sizeof(uint32_t));
    expect_no_heap_overflow(Query::ClearReference, fixture);
}

TEST_CASE("removing a type ref reads an id list with a trailing byte", "[rocksdb][overflow]") {
    const auto fixture = make_fixture();
    append_unaligned_byte(fixture.dir, fixture.point_type_list_key, sizeof(size_t));
    expect_no_heap_overflow(Query::RemoveTypeRef, fixture);
}
