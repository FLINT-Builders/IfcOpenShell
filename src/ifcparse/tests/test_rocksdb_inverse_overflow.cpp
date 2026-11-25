// This file was generated with the assistance of an AI coding tool.
//
// Spec for the RocksDB copies that turn a stored byte string into a vector of
// ids. The destination length is the stored length divided by the id width
// (uint32_t for inverse lists, size_t for per-type instance lists). Only that
// many bytes may be copied. A trailing partial id is ignored, whole ids are
// kept, and the call returns normally.
//
// The checks arm a counting allocator around the product call. A copy that
// writes past the vector trips the canary and fails the test. Query, unregister,
// and deletion paths are all covered. DefaultCodec's fixed-width decode of a
// single integer is a short-source read, not this undersized-destination bug,
// and is not exercised here.

#include <atomic>
#include <catch2/catch_test_macros.hpp>
#include <cstdint>
#include <cstring>
#include <dlfcn.h>
#include <exception>
#include <filesystem>
#include <ifcparse/file.h>
#include <memory>
#include <new>
#include <rocksdb/db.h>
#include <rocksdb/merge_operator.h>
#include <stdlib.h>
#include <string>
#include <sys/mman.h>
#include <unistd.h>
#include <utility>
#include <vector>

namespace {

constexpr std::size_t kCanaryLen = 64;
constexpr unsigned char kCanaryByte = 0xA5;
constexpr std::size_t kSlots = 1u << 16;
void* const kTombstone = reinterpret_cast<void*>(static_cast<std::uintptr_t>(1));

struct Slot {
    void* user;
    void* base;
    std::size_t mapping_size;
    unsigned char* canary;
    std::uint32_t user_size;
};

std::atomic<Slot*> g_slots{nullptr};
std::atomic_flag g_slot_lock = ATOMIC_FLAG_INIT;
std::atomic<bool> g_armed{false};
std::atomic<int> g_overflows{0};
std::atomic<bool> g_exhausted{false};
std::atomic<std::size_t> g_overflow_at{0};

struct SlotLock {
    SlotLock() {
        while (g_slot_lock.test_and_set(std::memory_order_acquire)) {
        }
    }
    ~SlotLock() { g_slot_lock.clear(std::memory_order_release); }
};

Slot* slot_table() {
    Slot* existing = g_slots.load(std::memory_order_acquire);
    if (existing != nullptr) {
        return existing;
    }
    Slot* created = static_cast<Slot*>(std::calloc(kSlots, sizeof(Slot)));
    if (created == nullptr) {
        std::abort();
    }
    Slot* expected = nullptr;
    if (!g_slots.compare_exchange_strong(expected, created, std::memory_order_release)) {
        std::free(created);
        return expected;
    }
    return created;
}

Slot* probe(void* user, bool insert) {
    Slot* table = slot_table();
    const std::size_t mask = kSlots - 1;
    std::size_t index = (reinterpret_cast<std::uintptr_t>(user) >> 4) & mask;
    Slot* tomb = nullptr;
    for (std::size_t n = 0; n < kSlots; ++n) {
        Slot& slot = table[index];
        if (slot.user == user) {
            return &slot;
        }
        if (slot.user == nullptr) {
            if (!insert) {
                return nullptr;
            }
            return tomb != nullptr ? tomb : &slot;
        }
        if (slot.user == kTombstone && tomb == nullptr) {
            tomb = &slot;
        }
        index = (index + 1) & mask;
    }
    return nullptr;
}

void* plain_alloc(std::size_t size, std::size_t align) {
    if (size == 0) {
        size = 1;
    }
    if (align <= alignof(std::max_align_t)) {
        return std::malloc(size);
    }
    void* pointer = nullptr;
    if (posix_memalign(&pointer, align, size) != 0) {
        return nullptr;
    }
    return pointer;
}

void* guarded_alloc(std::size_t size, std::size_t align) {
    const long page_value = sysconf(_SC_PAGESIZE);
    const std::size_t page = page_value > 0 ? static_cast<std::size_t>(page_value) : 4096;
    if (align < alignof(std::max_align_t)) {
        align = alignof(std::max_align_t);
    }
    const std::size_t lead = align;
    const std::size_t bytes = lead + size + kCanaryLen;
    std::size_t total = (bytes + page - 1) & ~(page - 1);
    total += page;

    void* base = mmap(nullptr, total, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (base == MAP_FAILED) {
        return nullptr;
    }
    if (mprotect(static_cast<char*>(base) + (total - page), page, PROT_NONE) != 0) {
        munmap(base, total);
        return nullptr;
    }

    const auto base_u = reinterpret_cast<std::uintptr_t>(base);
    auto user_u = (base_u + align - 1) & ~(static_cast<std::uintptr_t>(align) - 1);
    if (user_u + size + kCanaryLen > base_u + total - page) {
        munmap(base, total);
        return nullptr;
    }
    auto* user = reinterpret_cast<unsigned char*>(user_u);
    std::memset(user + size, kCanaryByte, kCanaryLen);

    {
        SlotLock lock;
        Slot* slot = probe(user, true);
        if (slot == nullptr) {
            g_exhausted.store(true, std::memory_order_release);
            munmap(base, total);
            return plain_alloc(size, align);
        }
        slot->user = user;
        slot->base = base;
        slot->mapping_size = total;
        slot->canary = user + size;
        slot->user_size = static_cast<std::uint32_t>(size);
    }
    return user;
}

bool release_guarded(void* pointer) {
    if (pointer == nullptr) {
        return true;
    }
    Slot copy{};
    {
        SlotLock lock;
        Slot* slot = probe(pointer, false);
        if (slot == nullptr) {
            return false;
        }
        copy = *slot;
        slot->user = kTombstone;
    }
    bool damaged = false;
    for (std::size_t i = 0; i < kCanaryLen; ++i) {
        if (copy.canary[i] != kCanaryByte) {
            damaged = true;
            break;
        }
    }
    if (damaged) {
        g_overflows.fetch_add(1, std::memory_order_relaxed);
        g_overflow_at.store(copy.user_size, std::memory_order_relaxed);
    }
    munmap(copy.base, copy.mapping_size);
    return true;
}

// RocksDB calls malloc_usable_size on blocks it allocated itself. Guard only
// the small id vectors created inside IfcParse; leave every other allocator alone.
bool guard_this_allocation(std::size_t size, const void* caller) {
    if (!g_armed.load(std::memory_order_acquire) || size > 1024 || caller == nullptr) {
        return false;
    }
    Dl_info info{};
    if (dladdr(caller, &info) == 0 || info.dli_fname == nullptr) {
        return false;
    }
    const char* file_name = std::strrchr(info.dli_fname, '/');
    file_name = file_name == nullptr ? info.dli_fname : file_name + 1;
    return std::strncmp(file_name, "libifcopenshell.parse", 21) == 0;
}

void* allocate(std::size_t size, std::size_t align, const void* caller) {
    if (guard_this_allocation(size, caller)) {
        if (void* pointer = guarded_alloc(size, align)) {
            return pointer;
        }
    }
    if (void* pointer = plain_alloc(size, align)) {
        return pointer;
    }
    throw std::bad_alloc();
}

void deallocate(void* pointer) noexcept {
    if (!release_guarded(pointer)) {
        std::free(pointer);
    }
}

std::string hex_key(std::uint64_t value) {
    static constexpr char digits[] = "0123456789abcdef";
    std::string text(16, '0');
    for (int i = 15; i >= 0; --i) {
        text[static_cast<std::size_t>(i)] = digits[value & 0xf];
        value >>= 4;
    }
    return text;
}

std::string inverse_prefix(int instance_id) {
    return "v|" + hex_key(static_cast<std::uint64_t>(instance_id)) + "|";
}

std::string type_list_key(int declaration_index) {
    return "t|" + hex_key(static_cast<std::uint64_t>(declaration_index));
}

template <typename Fn>
void with_db(const std::filesystem::path& directory, Fn&& fn) {
    rocksdb::Options options;
    options.create_if_missing = false;
    options.merge_operator.reset(new ConcatenateIdMergeOperator());
    rocksdb::DB* raw = nullptr;
    rocksdb::Status status = rocksdb::DB::Open(options, directory.string(), &raw);
    INFO(status.ToString());
    REQUIRE(status.ok());
    std::unique_ptr<rocksdb::DB> db(raw);
    fn(*db);
    db.reset();
}

std::vector<std::pair<std::string, std::string>> keys_under(rocksdb::DB& db, const std::string& prefix) {
    std::vector<std::pair<std::string, std::string>> found;
    std::unique_ptr<rocksdb::Iterator> it(db.NewIterator(rocksdb::ReadOptions()));
    for (it->Seek(prefix); it->Valid() && it->key().starts_with(prefix); it->Next()) {
        found.emplace_back(it->key().ToString(), it->value().ToString());
    }
    return found;
}

void put_values(rocksdb::DB& db, const std::vector<std::pair<std::string, std::string>>& values) {
    rocksdb::WriteOptions options;
    options.sync = true;
    for (const auto& value : values) {
        rocksdb::Status status = db.Put(options, value.first, value.second);
        INFO(status.ToString());
        REQUIRE(status.ok());
    }
}

// Append bytes that are not a whole id. The stored length is then no longer a multiple of the id width.
void extend_prefix(const std::filesystem::path& directory, const std::string& prefix, std::size_t width, std::size_t id_count, const std::string& extra) {
    with_db(directory, [&](rocksdb::DB& db) {
        auto found = keys_under(db, prefix);
        REQUIRE(found.size() == 1);
        REQUIRE(found[0].second.size() == id_count * width);
        found[0].second += extra;
        put_values(db, found);
    });
}

void replace_prefix(const std::filesystem::path& directory, const std::string& prefix, const std::string& value) {
    with_db(directory, [&](rocksdb::DB& db) {
        auto found = keys_under(db, prefix);
        REQUIRE(found.size() == 1);
        found[0].second = value;
        put_values(db, found);
    });
}

std::string read_exact(const std::filesystem::path& directory, const std::string& key) {
    std::string value;
    with_db(directory, [&](rocksdb::DB& db) {
        rocksdb::Status status = db.Get(rocksdb::ReadOptions(), key, &value);
        INFO(status.ToString());
        REQUIRE(status.ok());
    });
    return value;
}

struct Model {
    std::filesystem::path directory;
    int curve_a = 0;
    int curve_b = 0;
    int segment = 0;
    int curve_declaration = 0;

    explicit Model(const std::string& name) {
        directory = std::filesystem::temp_directory_path() / name;
        std::filesystem::remove_all(directory);
        ifcopenshell::file created(ifcopenshell::schema_by_name("IFC4"), ifcopenshell::FT_ROCKSDB, directory.string());
        REQUIRE(created.good());
        const auto* curve_type = created.schema()->declaration_by_name("IfcCompositeCurve");
        const auto* segment_type = created.schema()->declaration_by_name("IfcCompositeCurveSegment");
        auto curve_a_instance = created.create(curve_type);
        auto curve_b_instance = created.create(curve_type);
        auto segment_instance = created.create(segment_type);
        curve_a_instance.set_attribute_value(0, std::vector<express::base>{segment_instance});
        curve_b_instance.set_attribute_value(0, std::vector<express::base>{segment_instance});
        curve_a = curve_a_instance.id();
        curve_b = curve_b_instance.id();
        segment = segment_instance.id();
        curve_declaration = curve_type->index_in_schema();
    }

    Model(Model&& other) noexcept
        : directory(std::move(other.directory)),
          curve_a(other.curve_a),
          curve_b(other.curve_b),
          segment(other.segment),
          curve_declaration(other.curve_declaration) {
        other.directory.clear();
    }

    ~Model() {
        if (directory.empty()) {
            return;
        }
        std::error_code error;
        std::filesystem::remove_all(directory, error);
    }

    Model(const Model&) = delete;
    Model& operator=(const Model&) = delete;
};

std::atomic<int> g_model_serial{0};

Model make_model() {
    const int serial = g_model_serial.fetch_add(1, std::memory_order_relaxed);
    return Model("ifc-inverse-overflow-" + std::to_string(static_cast<long long>(::getpid())) + "-" + std::to_string(serial));
}

template <typename Fn>
void require_no_overflow(Fn&& fn) {
    g_overflows.store(0, std::memory_order_relaxed);
    g_exhausted.store(false, std::memory_order_relaxed);
    g_overflow_at.store(0, std::memory_order_relaxed);
    g_armed.store(true, std::memory_order_release);
    std::exception_ptr error;
    try {
        fn();
    } catch (...) {
        error = std::current_exception();
    }
    g_armed.store(false, std::memory_order_release);
    const int overflows = g_overflows.load(std::memory_order_acquire);
    const bool exhausted = g_exhausted.load(std::memory_order_acquire);
    INFO("canary overflows " << overflows << " at allocation " << g_overflow_at.load(std::memory_order_relaxed));
    REQUIRE_FALSE(exhausted);
    REQUIRE(overflows == 0);
    if (error) {
        std::rethrow_exception(error);
    }
}

std::vector<int> sorted_reference_ids(ifcopenshell::file& file, int instance_id) {
    std::vector<int> ids;
    for (const auto& instance : file.instances_by_reference(instance_id)) {
        ids.push_back(instance.id());
    }
    std::sort(ids.begin(), ids.end());
    return ids;
}

std::vector<int> sorted_inverse_ids(ifcopenshell::file& file, int instance_id, const ifcopenshell::declaration* type, int attribute_index) {
    std::vector<int> ids;
    for (const auto& instance : file.get_inverse(instance_id, type, attribute_index)) {
        ids.push_back(instance.id());
    }
    std::sort(ids.begin(), ids.end());
    return ids;
}

std::vector<int> sorted_type_ids(ifcopenshell::file& file) {
    std::vector<int> ids;
    for (const auto& instance : file.instances_by_type("IfcCompositeCurve")) {
        ids.push_back(instance.id());
    }
    std::sort(ids.begin(), ids.end());
    return ids;
}

std::unique_ptr<ifcopenshell::file> open_autodetected(const Model& model) {
    REQUIRE(ifcopenshell::guess_file_type(model.directory.string()) == ifcopenshell::FT_ROCKSDB);
    auto opened = std::unique_ptr<ifcopenshell::file>(new ifcopenshell::file(model.directory.string()));
    REQUIRE(opened->good());
    return opened;
}

std::vector<int> both_curves(const Model& model) {
    std::vector<int> ids{model.curve_a, model.curve_b};
    std::sort(ids.begin(), ids.end());
    return ids;
}

} // namespace

void* operator new(std::size_t size) {
    return allocate(size, alignof(std::max_align_t), __builtin_return_address(0));
}
void* operator new(std::size_t size, std::align_val_t align) {
    return allocate(size, static_cast<std::size_t>(align), __builtin_return_address(0));
}
void* operator new[](std::size_t size) {
    return allocate(size, alignof(std::max_align_t), __builtin_return_address(0));
}
void* operator new[](std::size_t size, std::align_val_t align) {
    return allocate(size, static_cast<std::size_t>(align), __builtin_return_address(0));
}
void operator delete(void* pointer) noexcept { deallocate(pointer); }
void operator delete(void* pointer, std::size_t) noexcept { deallocate(pointer); }
void operator delete(void* pointer, std::align_val_t) noexcept { deallocate(pointer); }
void operator delete(void* pointer, std::size_t, std::align_val_t) noexcept { deallocate(pointer); }
void operator delete[](void* pointer) noexcept { deallocate(pointer); }
void operator delete[](void* pointer, std::size_t) noexcept { deallocate(pointer); }
void operator delete[](void* pointer, std::align_val_t) noexcept { deallocate(pointer); }
void operator delete[](void* pointer, std::size_t, std::align_val_t) noexcept { deallocate(pointer); }

TEST_CASE("Whole inverse ids survive a RocksDB delete", "[rocksdb-inverse]") {
    Model model = make_model();
    auto opened = open_autodetected(model);
    const auto* curve_type = opened->schema()->declaration_by_name("IfcCompositeCurve");
    const std::vector<int> expected = both_curves(model);

    std::vector<int> referenced;
    require_no_overflow([&] { referenced = sorted_reference_ids(*opened, model.segment); });
    REQUIRE(referenced == expected);

    std::vector<std::uint32_t> sources;
    require_no_overflow([&] {
        opened->all_referencing_instances(model.segment, [&](std::uint32_t id) {
            sources.push_back(id);
            return true;
        });
    });
    std::sort(sources.begin(), sources.end());
    REQUIRE(sources.size() == expected.size());
    for (std::size_t i = 0; i < expected.size(); ++i) {
        REQUIRE(sources[i] == static_cast<std::uint32_t>(expected[i]));
    }

    std::vector<int> attribute_indexes;
    require_no_overflow([&] { attribute_indexes = opened->get_inverse_indices_by_id(model.segment); });
    REQUIRE(attribute_indexes == std::vector<int>{0, 0});

    std::vector<int> any_attribute;
    std::vector<int> segments_attribute;
    require_no_overflow([&] { any_attribute = sorted_inverse_ids(*opened, model.segment, curve_type, -1); });
    require_no_overflow([&] { segments_attribute = sorted_inverse_ids(*opened, model.segment, curve_type, 0); });
    REQUIRE(any_attribute == expected);
    REQUIRE(segments_attribute == expected);

    std::vector<int> of_type;
    require_no_overflow([&] { of_type = sorted_type_ids(*opened); });
    REQUIRE(of_type == expected);

    require_no_overflow([&] { opened->remove_entity(opened->instance_by_id(model.curve_a)); });
    std::vector<int> remaining;
    require_no_overflow([&] { remaining = sorted_reference_ids(*opened, model.segment); });
    REQUIRE(remaining == std::vector<int>{model.curve_b});
}

TEST_CASE("Deleting a referencer ignores a partial inverse id", "[rocksdb-inverse]") {
    Model model = make_model();
    extend_prefix(model.directory, inverse_prefix(model.segment), sizeof(std::uint32_t), 2, std::string("\xff", 1));

    auto opened = open_autodetected(model);
    require_no_overflow([&] { opened->remove_entity(opened->instance_by_id(model.curve_a)); });

    std::vector<int> remaining;
    require_no_overflow([&] { remaining = sorted_reference_ids(*opened, model.segment); });
    REQUIRE(remaining == std::vector<int>{model.curve_b});

    opened.reset();
    std::string inverse_key;
    with_db(model.directory, [&](rocksdb::DB& db) {
        auto found = keys_under(db, inverse_prefix(model.segment));
        REQUIRE(found.size() == 1);
        inverse_key = found[0].first;
    });
    const std::string stored = read_exact(model.directory, inverse_key);
    REQUIRE(stored.size() == sizeof(std::uint32_t));
    std::uint32_t stored_id = 0;
    std::memcpy(&stored_id, stored.data(), sizeof(stored_id));
    REQUIRE(stored_id == static_cast<std::uint32_t>(model.curve_b));
}

TEST_CASE("Inverse queries ignore a partial trailing id", "[rocksdb-inverse]") {
    Model model = make_model();
    extend_prefix(model.directory, inverse_prefix(model.segment), sizeof(std::uint32_t), 2, std::string("\xff\x7e", 2));
    auto opened = open_autodetected(model);
    const auto* curve_type = opened->schema()->declaration_by_name("IfcCompositeCurve");
    const std::vector<int> expected = both_curves(model);

    std::vector<int> referenced;
    require_no_overflow([&] { referenced = sorted_reference_ids(*opened, model.segment); });
    REQUIRE(referenced == expected);

    std::vector<std::uint32_t> sources;
    require_no_overflow([&] {
        const bool all = opened->all_referencing_instances(model.segment, [&](std::uint32_t id) {
            sources.push_back(id);
            return true;
        });
        REQUIRE(all);
    });
    std::sort(sources.begin(), sources.end());
    REQUIRE(sources.size() == 2);
    REQUIRE(sources[0] == static_cast<std::uint32_t>(expected[0]));
    REQUIRE(sources[1] == static_cast<std::uint32_t>(expected[1]));

    std::vector<int> indexes;
    require_no_overflow([&] { indexes = opened->get_inverse_indices_by_id(model.segment); });
    REQUIRE(indexes == std::vector<int>{0, 0});

    std::vector<int> any_attribute;
    std::vector<int> segments_attribute;
    require_no_overflow([&] { any_attribute = sorted_inverse_ids(*opened, model.segment, curve_type, -1); });
    require_no_overflow([&] { segments_attribute = sorted_inverse_ids(*opened, model.segment, curve_type, 0); });
    REQUIRE(any_attribute == expected);
    REQUIRE(segments_attribute == expected);
}

TEST_CASE("Clearing a reference ignores a partial inverse id", "[rocksdb-inverse]") {
    Model model = make_model();
    extend_prefix(model.directory, inverse_prefix(model.segment), sizeof(std::uint32_t), 2, std::string("\x01\x02\x03", 3));
    auto opened = open_autodetected(model);
    auto curve = opened->instance_by_id(model.curve_a);
    require_no_overflow([&] { curve.set_attribute_value(0, std::vector<express::base>{}); });

    std::vector<int> remaining;
    require_no_overflow([&] { remaining = sorted_reference_ids(*opened, model.segment); });
    REQUIRE(remaining == std::vector<int>{model.curve_b});
}

TEST_CASE("An inverse value shorter than one id yields no referencers", "[rocksdb-inverse]") {
    for (std::size_t length : {std::size_t{1}, std::size_t{2}, std::size_t{3}}) {
        Model model = make_model();
        replace_prefix(model.directory, inverse_prefix(model.segment), std::string(length, '\xab'));
        auto opened = open_autodetected(model);
        std::vector<int> referenced;
        require_no_overflow([&] { referenced = sorted_reference_ids(*opened, model.segment); });
        REQUIRE(referenced.empty());

        std::vector<std::uint32_t> sources;
        require_no_overflow([&] {
            opened->all_referencing_instances(model.segment, [&](std::uint32_t id) {
                sources.push_back(id);
                return true;
            });
        });
        REQUIRE(sources.empty());

        const auto* curve_type = opened->schema()->declaration_by_name("IfcCompositeCurve");
        std::vector<int> any_attribute;
        std::vector<int> segments_attribute;
        require_no_overflow([&] { any_attribute = sorted_inverse_ids(*opened, model.segment, curve_type, -1); });
        require_no_overflow([&] { segments_attribute = sorted_inverse_ids(*opened, model.segment, curve_type, 0); });
        REQUIRE(any_attribute.empty());
        REQUIRE(segments_attribute.empty());

        std::vector<int> indexes;
        require_no_overflow([&] { indexes = opened->get_inverse_indices_by_id(model.segment); });
        REQUIRE(indexes.empty());
    }
}

TEST_CASE("Clearing a reference tolerates an inverse shorter than one id", "[rocksdb-inverse]") {
    Model model = make_model();
    replace_prefix(model.directory, inverse_prefix(model.segment), std::string("\x11\x22", 2));
    auto opened = open_autodetected(model);
    auto curve = opened->instance_by_id(model.curve_a);
    require_no_overflow([&] { curve.set_attribute_value(0, std::vector<express::base>{}); });
    std::vector<int> remaining;
    require_no_overflow([&] { remaining = sorted_reference_ids(*opened, model.segment); });
    REQUIRE(remaining.empty());
}

TEST_CASE("Type queries and deletion ignore a partial type-list id", "[rocksdb-inverse]") {
    Model model = make_model();
    const std::string key = type_list_key(model.curve_declaration);
    extend_prefix(model.directory, key, sizeof(std::size_t), 2, std::string("\x5a", 1));

    auto opened = open_autodetected(model);
    std::vector<int> of_type;
    require_no_overflow([&] { of_type = sorted_type_ids(*opened); });
    REQUIRE(of_type == both_curves(model));

    require_no_overflow([&] { opened->remove_entity(opened->instance_by_id(model.curve_a)); });
    std::vector<int> remaining;
    require_no_overflow([&] { remaining = sorted_type_ids(*opened); });
    REQUIRE(remaining == std::vector<int>{model.curve_b});

    opened.reset();
    const std::string stored = read_exact(model.directory, key);
    REQUIRE(stored.size() == sizeof(std::size_t));
    std::size_t stored_id = 0;
    std::memcpy(&stored_id, stored.data(), sizeof(stored_id));
    REQUIRE(stored_id == static_cast<std::size_t>(model.curve_b));
}

TEST_CASE("A type list shorter than one id yields no instances", "[rocksdb-inverse]") {
    Model model = make_model();
    const std::string key = type_list_key(model.curve_declaration);
    replace_prefix(model.directory, key, std::string(sizeof(std::size_t) - 1, '\x3c'));
    auto opened = open_autodetected(model);
    std::vector<int> of_type;
    require_no_overflow([&] { of_type = sorted_type_ids(*opened); });
    REQUIRE(of_type.empty());

    require_no_overflow([&] { opened->remove_entity(opened->instance_by_id(model.curve_a)); });
}

TEST_CASE("Deleting the referenced instance ignores its own partial inverse", "[rocksdb-inverse]") {
    Model model = make_model();
    // Referencers are stored under the segment. Deleting the segment reads that record first.
    extend_prefix(model.directory, inverse_prefix(model.segment), sizeof(std::uint32_t), 2, std::string("\xfe", 1));
    auto opened = open_autodetected(model);
    require_no_overflow([&] { opened->remove_entity(opened->instance_by_id(model.segment)); });
    std::vector<int> referenced;
    require_no_overflow([&] { referenced = sorted_reference_ids(*opened, model.segment); });
    REQUIRE(referenced.empty());
}
