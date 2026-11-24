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

// Spec for the web object-list string-table bounds check.
//
// Build with -m32 (see run_element_string_bounds.sh). The web viewer is
// wasm32, so size_t is 32 bits there; a 64-bit build hides the wrap and
// must not be used to decide this test.
//
// These tests fail while visitModelElements / makeElementRef accept a
// length whose size_t sum with the offset wraps. They pass once every
// such length is rejected and is not handed to the JSON writer.

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <unordered_map>

#include <signal.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>

#include "ViewportCore.h"
#include "SidecarCompress.h"

// models_gpu_ is private and only the GPU load path fills it. The string
// checks do not need a device; this reaches the same member
// loadElementMetadataWeb writes.
template <class Tag>
struct MemberAccessor {
    static typename Tag::type pointer;
};
template <class Tag>
typename Tag::type MemberAccessor<Tag>::pointer;

template <class Tag, typename Tag::type Pointer>
struct MemberRobber {
    MemberRobber() { MemberAccessor<Tag>::pointer = Pointer; }
    static MemberRobber instance;
};
template <class Tag, typename Tag::type Pointer>
MemberRobber<Tag, Pointer> MemberRobber<Tag, Pointer>::instance;

struct ModelsTag {
    using type = std::unordered_map<std::uint32_t, ModelGpuData> ViewportCore::*;
};
template struct MemberRobber<ModelsTag, &ViewportCore::models_gpu_>;

// The function the web object list calls with each slice. The test build
// compiles it from src/ifcviewer-web/main_web.cpp.
void appendJsonString(std::string& out, const char* data, std::uint32_t length);

// Default-constructed GPU and worker members are never started here. Their
// production destructors call into wgpu; these definitions only tear down
// the C++ members of an object the string-table path does not touch.
BufferPool::~BufferPool() {}
StreamingThread::~StreamingThread() {}
AxisIndicatorRenderer::~AxisIndicatorRenderer() {}
SectionGizmoRenderer::~SectionGizmoRenderer() {}

namespace {

int g_failed = 0;

void fail(const char* test, const std::string& detail) {
    std::printf("FAIL %s: %s\n", test, detail.c_str());
    std::fflush(stdout);
    ++g_failed;
}

void pass(const char* test) {
    std::printf("PASS %s\n", test);
    std::fflush(stdout);
}

void appendU32(std::vector<std::uint8_t>& out, std::uint32_t value) {
    const auto* bytes = reinterpret_cast<const std::uint8_t*>(&value);
    out.insert(out.end(), bytes, bytes + 4);
}

// Element-metadata block layout consumed by parseSidecarElementMetadata:
// uint32 count, ElementTableRecord[count], uint32 string bytes, bytes.
std::vector<std::uint8_t> serializeElementBlock(
        const std::vector<ElementTableRecord>& elements,
        const std::string& table) {
    std::vector<std::uint8_t> raw;
    appendU32(raw, static_cast<std::uint32_t>(elements.size()));
    if (!elements.empty()) {
        const auto* bytes = reinterpret_cast<const std::uint8_t*>(elements.data());
        raw.insert(raw.end(), bytes,
                   bytes + elements.size() * sizeof(ElementTableRecord));
    }
    appendU32(raw, static_cast<std::uint32_t>(table.size()));
    raw.insert(raw.end(), table.begin(), table.end());
    return raw;
}

// Same transforms as loadElementMetadataWeb: zstd frame, then
// SidecarCompress::decompress, then parseSidecarElementMetadata.
bool loadElementBlock(const std::vector<ElementTableRecord>& elements,
                      const std::string& table,
                      SidecarData& out,
                      std::string& error) {
    const std::vector<std::uint8_t> raw = serializeElementBlock(elements, table);
    const std::vector<std::uint8_t> compressed =
        SidecarCompress::compress(raw.data(), raw.size(), 1);
    if (compressed.empty()) {
        error = "compress failed";
        return false;
    }
    std::vector<std::uint8_t> decoded(raw.size());
    if (!SidecarCompress::decompress(compressed.data(), compressed.size(),
                                     decoded.data(), decoded.size())) {
        error = "decompress failed";
        return false;
    }
    if (decoded != raw) {
        error = "decompress did not restore the element block";
        return false;
    }
    if (!parseSidecarElementMetadata(decoded.data(), decoded.size(), out)) {
        error = "parseSidecarElementMetadata rejected the block";
        return false;
    }
    return true;
}

// Mirrors the assignment in loadElementMetadataWeb: move the parsed table
// onto the model and rebase object ids. String offsets and lengths are
// not rewritten.
void installModel(ViewportCore& core, SidecarData parsed, std::uint32_t base) {
    ModelGpuData model;
    model.object_id_base = base;
    model.web_source_id = 7;
    model.elements = std::move(parsed.elements);
    model.string_table = std::move(parsed.string_table);
    for (auto& element : model.elements) element.object_id += base;
    model.element_metadata_loaded = true;
    if (!model.elements.empty()) {
        InstanceInfo instance{};
        instance.object_id = model.elements.front().object_id;
        model.instances.push_back(instance);
        model.object_id_to_instance.emplace(instance.object_id, 0u);
    }
    (core.*MemberAccessor<ModelsTag>::pointer).emplace(1u, std::move(model));
}

bool spanInsideTable(const std::string& table, const char* data, std::uint32_t length) {
    if (length == 0) return true;
    if (data == nullptr) return false;
    const std::uint64_t begin = static_cast<std::uint64_t>(
        reinterpret_cast<std::uintptr_t>(table.data()));
    const std::uint64_t end = begin + static_cast<std::uint64_t>(table.size());
    const std::uint64_t start = static_cast<std::uint64_t>(
        reinterpret_cast<std::uintptr_t>(data));
    const std::uint64_t last = start + static_cast<std::uint64_t>(length);
    return start >= begin && last <= end;
}

// The web writer (ifcv_request_objects_c) calls appendJsonString with the
// pointer and length visitModelElements produced. A length that does not
// fit in the table is the failure; the writer is not invoked with it,
// because that read is the multi-gigabyte walk off the heap.
bool handToJsonWriter(const std::string& table,
                      const char* data,
                      std::uint32_t length,
                      std::string& json,
                      std::string& error) {
    if (!spanInsideTable(table, data, length)) {
        error = "length " + std::to_string(length) +
                " is outside the string table of " + std::to_string(table.size()) +
                " bytes";
        return false;
    }
    appendJsonString(json, data, length);
    return true;
}

ElementTableRecord recordWith(std::uint32_t object_id,
                              std::uint32_t guid_off, std::uint32_t guid_len,
                              std::uint32_t name_off, std::uint32_t name_len,
                              std::uint32_t type_off, std::uint32_t type_len) {
    ElementTableRecord element{};
    element.object_id = object_id;
    element.session_model_id = 1;
    element.ifc_id = 42;
    element.guid_offset = guid_off;
    element.guid_length = guid_len;
    element.name_offset = name_off;
    element.name_length = name_len;
    element.type_offset = type_off;
    element.type_length = type_len;
    return element;
}

struct Loaded {
    ViewportCore core;
    explicit Loaded() : core(nullptr) {}
    ModelGpuData& model() {
        return (core.*MemberAccessor<ModelsTag>::pointer).at(1u);
    }
    const std::string& table() { return model().string_table; }
};

bool prepare(const char* test,
             const std::vector<ElementTableRecord>& elements,
             const std::string& table,
             Loaded& loaded) {
    SidecarData parsed;
    std::string error;
    if (!loadElementBlock(elements, table, parsed, error)) {
        fail(test, error);
        return false;
    }
    if (parsed.elements.size() != elements.size() || parsed.string_table != table) {
        fail(test, "parsed element block does not match the serialized block");
        return false;
    }
    for (std::size_t i = 0; i < elements.size(); ++i) {
        const ElementTableRecord& want = elements[i];
        const ElementTableRecord& got = parsed.elements[i];
        if (got.guid_offset != want.guid_offset || got.guid_length != want.guid_length ||
            got.name_offset != want.name_offset || got.name_length != want.name_length ||
            got.type_offset != want.type_offset || got.type_length != want.type_length) {
            fail(test, "parser changed a string offset or length");
            return false;
        }
    }
    installModel(loaded.core, std::move(parsed), /*base=*/10u);
    if (loaded.table() != table) {
        fail(test, "installed string table does not match the parsed block");
        return false;
    }
    return true;
}

void checkVisit(const char* test, Loaded& loaded) {
    int visits = 0;
    std::string error;
    loaded.core.visitModelElements(0, [&](const ViewportCore::ElementSlices& slice) {
        ++visits;
        std::string json;
        if (!handToJsonWriter(loaded.table(), slice.guid, slice.guid_len, json, error)) {
            fail(test, "guid " + error);
        }
        if (!handToJsonWriter(loaded.table(), slice.name, slice.name_len, json, error)) {
            fail(test, "name " + error);
        }
        if (!handToJsonWriter(loaded.table(), slice.type, slice.type_len, json, error)) {
            fail(test, "type " + error);
        }
    });
    if (visits == 0) fail(test, "visitModelElements visited no elements");
}

void checkMaterializedEmpty(const char* test, const ViewportCore::ElementRef& ref,
                            bool want_guid_empty, bool want_name_empty, bool want_type_empty) {
    if (want_guid_empty && !ref.guid.empty()) {
        fail(test, "guid was materialized from an out-of-range length (" + ref.guid + ")");
    }
    if (want_name_empty && !ref.name.empty()) {
        fail(test, "name was materialized from an out-of-range length (" + ref.name + ")");
    }
    if (want_type_empty && !ref.type.empty()) {
        fail(test, "type was materialized from an out-of-range length (" + ref.type + ")");
    }
}

void checkElementsAndLookup(const char* test, Loaded& loaded,
                            bool want_guid_empty, bool want_name_empty, bool want_type_empty) {
    try {
        const std::vector<ViewportCore::ElementRef> refs = loaded.core.elements();
        if (refs.size() != 1) {
            fail(test, "elements() returned " + std::to_string(refs.size()) + " rows");
            return;
        }
        checkMaterializedEmpty(test, refs[0], want_guid_empty, want_name_empty, want_type_empty);
        ViewportCore::ElementRef looked;
        if (!loaded.core.elementForObject(refs[0].object_id, looked)) {
            fail(test, "elementForObject missed the installed object");
            return;
        }
        checkMaterializedEmpty(test, looked, want_guid_empty, want_name_empty, want_type_empty);
    } catch (const std::exception& ex) {
        fail(test, std::string("threw while materializing strings: ") + ex.what());
    }
}

// ---- cases -----------------------------------------------------------------

void test_in_bounds_round_trip() {
    const char* test = "in_bounds_round_trip";
    const std::string table = "WallSlabBeam";
    // guid empty (length 0); name "Wall"; type "Slab".
    const auto element = recordWith(1, 0, 0, 0, 4, 4, 4);
    Loaded loaded;
    if (!prepare(test, {element}, table, loaded)) return;

    std::string json;
    int visits = 0;
    std::string error;
    loaded.core.visitModelElements(0, [&](const ViewportCore::ElementSlices& slice) {
        ++visits;
        if (!handToJsonWriter(loaded.table(), slice.guid, slice.guid_len, json, error) ||
            !handToJsonWriter(loaded.table(), slice.name, slice.name_len, json, error) ||
            !handToJsonWriter(loaded.table(), slice.type, slice.type_len, json, error)) {
            fail(test, error);
        }
        if (slice.guid_len != 0 || slice.name_len != 4 || slice.type_len != 4) {
            fail(test, "in-range lengths were not preserved");
        }
    });
    if (visits != 1) fail(test, "expected one element");
    if (json.find("\"Wall\"") == std::string::npos ||
        json.find("\"Slab\"") == std::string::npos) {
        fail(test, "JSON writer did not emit the in-range strings: " + json);
    }

    try {
        const auto refs = loaded.core.elements();
        if (refs.size() != 1 || refs[0].name != "Wall" || refs[0].type != "Slab" ||
            !refs[0].guid.empty()) {
            fail(test, "elements() dropped an in-range string");
        }
    } catch (const std::exception& ex) {
        fail(test, std::string("elements() threw: ") + ex.what());
    }
    if (g_failed == 0) pass(test);
}

void test_nonwrapping_oversize_rejected() {
    const char* test = "nonwrapping_oversize_rejected";
    const std::string table = "0123456789abcdef";  // 16 bytes
    // offset 0 + length 100 does not wrap and is past the table.
    // offset 100 + length 4 is past the table and does not wrap either.
    const auto past_end = recordWith(1, 0, 100, 100, 4, 0, 0);
    Loaded loaded;
    if (!prepare(test, {past_end}, table, loaded)) return;
    const int before = g_failed;
    checkVisit(test, loaded);
    checkElementsAndLookup(test, loaded, true, true, true);
    if (g_failed == before) pass(test);
}

void test_wrapped_field_rejected(const char* test,
                                 std::uint32_t guid_off, std::uint32_t guid_len,
                                 std::uint32_t name_off, std::uint32_t name_len,
                                 std::uint32_t type_off, std::uint32_t type_len,
                                 bool guid_bad, bool name_bad, bool type_bad) {
    const std::string table = "0123456789abcdef";
    const auto element = recordWith(1, guid_off, guid_len, name_off, name_len,
                                    type_off, type_len);
    Loaded loaded;
    if (!prepare(test, {element}, table, loaded)) return;
    const int before = g_failed;
    checkVisit(test, loaded);
    checkElementsAndLookup(test, loaded, guid_bad, name_bad, type_bad);
    if (g_failed == before) pass(test);
}

// appendJsonString has no table size of its own: given a pointer at the end
// of a mapped page and a length that continues into the next page, the read
// faults. That is the use visitModelElements feeds.
bool jsonWriterFaultsPastMapping() {
    const long page = sysconf(_SC_PAGESIZE);
    if (page <= 0) return false;
    void* mapping = mmap(nullptr, static_cast<std::size_t>(page) * 2,
                         PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (mapping == MAP_FAILED) return false;
    auto* bytes = static_cast<char*>(mapping);
    if (mprotect(bytes + page, static_cast<std::size_t>(page), PROT_NONE) != 0) {
        munmap(mapping, static_cast<std::size_t>(page) * 2);
        return false;
    }
    char* tail = bytes + page - 4;
    std::memcpy(tail, "ABCD", 4);
    const pid_t child = fork();
    if (child == 0) {
        std::string json;
        appendJsonString(json, tail, 64);
        _exit(0);
    }
    int status = 0;
    const pid_t waited = waitpid(child, &status, 0);
    munmap(mapping, static_cast<std::size_t>(page) * 2);
    return waited == child && WIFSIGNALED(status) && WTERMSIG(status) == SIGSEGV;
}

void test_json_writer_reads_supplied_length() {
    const char* test = "json_writer_reads_supplied_length";
    if (!jsonWriterFaultsPastMapping()) {
        fail(test, "appendJsonString did not fault when length ran off the mapping");
        return;
    }
    pass(test);
}

}  // namespace

int main() {
    static_assert(sizeof(std::size_t) == 4,
                  "build this test with -m32 so size_t matches the wasm32 viewer");
    static_assert(sizeof(ElementTableRecord) == 36, "element record layout changed");

    const int baseline = g_failed;
    test_in_bounds_round_trip();
    test_nonwrapping_oversize_rejected();
    test_json_writer_reads_supplied_length();
    if (g_failed != baseline) {
        std::printf("control tests failed; bounds results would be meaningless\n");
        return 1;
    }

    // offset + length wraps mod 2^32 to a value <= the 16-byte table.
    // guid: 1 + 0xFFFFFFFF -> 0
    // name: 5 + 0xFFFFFFFD -> 2
    // type: 8 + 0xFFFFFFF9 -> 1
    test_wrapped_field_rejected(
        "wrapped_guid_length_rejected",
        1, 0xFFFFFFFFu, 0, 4, 4, 4,
        true, false, false);
    test_wrapped_field_rejected(
        "wrapped_name_length_rejected",
        0, 0, 5, 0xFFFFFFFDu, 0, 4,
        false, true, false);
    test_wrapped_field_rejected(
        "wrapped_type_length_rejected",
        0, 4, 4, 4, 8, 0xFFFFFFF9u,
        false, false, true);
    // Offset itself is outside the table. The wrapping length makes
    // size_t(offset) + length look small.
    test_wrapped_field_rejected(
        "wrapped_length_with_offset_past_table_rejected",
        100, static_cast<std::uint32_t>(0u - 100u),
        0, 0,
        0, 0,
        true, false, false);

    if (g_failed != 0) {
        std::printf("%d check(s) failed\n", g_failed);
        return 1;
    }
    std::printf("all element string bounds checks passed\n");
    return 0;
}
