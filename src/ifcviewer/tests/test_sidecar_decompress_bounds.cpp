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

// Spec for the .ifcview size-check fix. These tests fail while a loader
// allocates a buffer from a header size before it has proved that size is
// bounded. Catching std::bad_alloc after the allocator was already asked for
// the claimed size is still a failure: the request itself is the side effect.
//
// Contract, applied to every zstd block a loader materialises (geometry
// metadata, element metadata, and per-chunk vertex/index frames):
//
//   * Reject a claimed uncompressed size greater than kMaxBlockBytes before
//     any allocation of that size. kMaxBlockBytes is 256 MiB.
//   * Reject a claimed uncompressed size greater than kMaxExpansion times the
//     accompanying compressed size before any allocation of that size.
//     kMaxExpansion is 131072. That is above the ratio zstd level 19 produces
//     on repetitive metadata (about 25k for a 2 MiB run of identical bytes)
//     and far below the ratio of a few-dozen-byte frame that claims 32 MiB.
//   * Reject a claimed compressed length, or a geometry-section length, that
//     is larger than the bytes actually present in the file, before allocating
//     a buffer of that length.
//
// A block at or under both uncompressed limits must still load. The 2 MiB
// repetitive string-table case is that allowance.
//
// Not covered here (same missing check, not reachable from this binary):
//   * ViewportCore::loadSidecarMetadataWeb allocates geometry_metadata_raw
//     before SidecarCompress::decompress.
//   * ViewportCore::loadElementMetadataWeb allocates element_metadata_raw_size.
//   * ViewportCore::beginWebChunkLoad allocates v_raw and i_raw.
//   * webReadRangesAsync / webIssueCurrentPlan allocate the compressed range.
//   Those four are compiled only for the Emscripten viewer.
//   * readSidecarVertexChunk, readSidecarIndexChunk, readSidecarVertexRanges,
//     and readSidecarIndexRanges allocate a caller-supplied length, but nothing
//     in the viewer calls them at this commit.

#include "SidecarCache.h"
#include "SidecarCompress.h"
#include "StreamingLoader.h"

#include <algorithm>
#include <atomic>
#include <catch2/catch_test_macros.hpp>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <new>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace alloc_watch {

std::atomic<bool> armed{false};
std::atomic<std::size_t> limit{0};
std::atomic<std::size_t> max_request{0};
std::atomic<bool> rejected{false};

inline bool consider(std::size_t n) {
    if (!armed.load(std::memory_order_relaxed)) {
        return false;
    }
    std::size_t prev = max_request.load(std::memory_order_relaxed);
    while (n > prev &&
           !max_request.compare_exchange_weak(prev, n, std::memory_order_relaxed)) {
    }
    if (n >= limit.load(std::memory_order_relaxed)) {
        rejected.store(true, std::memory_order_relaxed);
        return true;
    }
    return false;
}

struct Arm {
    explicit Arm(std::size_t byte_limit) {
        max_request.store(0, std::memory_order_relaxed);
        rejected.store(false, std::memory_order_relaxed);
        limit.store(byte_limit, std::memory_order_relaxed);
        armed.store(true, std::memory_order_relaxed);
    }
    ~Arm() { armed.store(false, std::memory_order_relaxed); }
    Arm(const Arm&) = delete;
    Arm& operator=(const Arm&) = delete;
};

} // namespace alloc_watch

void* operator new(std::size_t n) {
    if (alloc_watch::consider(n)) {
        throw std::bad_alloc();
    }
    if (void* p = std::malloc(n == 0 ? 1 : n)) {
        return p;
    }
    throw std::bad_alloc();
}

void* operator new(std::size_t n, std::align_val_t alignment) {
    if (alloc_watch::consider(n)) {
        throw std::bad_alloc();
    }
    const std::size_t align = std::max<std::size_t>(static_cast<std::size_t>(alignment), sizeof(void*));
    const std::size_t bytes = (n + align - 1) & ~(align - 1);
    if (void* p = std::aligned_alloc(align, bytes == 0 ? align : bytes)) {
        return p;
    }
    throw std::bad_alloc();
}

void* operator new[](std::size_t n) {
    return ::operator new(n);
}

void* operator new[](std::size_t n, std::align_val_t alignment) {
    return ::operator new(n, alignment);
}

void operator delete(void* p) noexcept {
    std::free(p);
}

void operator delete(void* p, std::size_t) noexcept {
    std::free(p);
}

void operator delete(void* p, std::align_val_t) noexcept {
    std::free(p);
}

void operator delete(void* p, std::size_t, std::align_val_t) noexcept {
    std::free(p);
}

void operator delete[](void* p) noexcept {
    std::free(p);
}

void operator delete[](void* p, std::size_t) noexcept {
    std::free(p);
}

void operator delete[](void* p, std::align_val_t) noexcept {
    std::free(p);
}

void operator delete[](void* p, std::size_t, std::align_val_t) noexcept {
    std::free(p);
}

namespace {

// Absolute cap for one decompressed block or chunk. Claims above this must
// be refused before the allocator sees them.
constexpr std::uint64_t kMaxBlockBytes = 256ull * 1024ull * 1024ull;

// Uncompressed size must also be <= compressed size * kMaxExpansion.
constexpr std::uint64_t kMaxExpansion = 131072ull;

// Bomb tests use files of a few kilobytes. A request at or above this limit
// means the loader asked for the attacker's size (or a large fraction of it)
// instead of refusing first.
constexpr std::size_t kProbeBytes = 1u << 20;

std::atomic<std::uint64_t> g_scratch_seq{0};

fs::path makeScratch(const char* tag) {
    fs::path base = fs::temp_directory_path() / "ifcviewer_test_decompress_bounds";
    fs::create_directories(base);
    fs::path dir = base / (std::to_string(g_scratch_seq.fetch_add(1)) + "_" + tag);
    fs::create_directories(dir);
    return dir;
}

void appendBytes(std::vector<std::uint8_t>& dst, const void* src, std::size_t n) {
    const auto* bytes = static_cast<const std::uint8_t*>(src);
    dst.insert(dst.end(), bytes, bytes + n);
}

template <typename T>
void appendPod(std::vector<std::uint8_t>& dst, const T& value) {
    appendBytes(dst, &value, sizeof(value));
}

std::vector<std::uint8_t> compressRaw(const std::vector<std::uint8_t>& raw) {
    auto packed = SidecarCompress::compress(raw.data(), raw.size(), 3);
    REQUIRE_FALSE(packed.empty());
    return packed;
}

std::vector<std::uint8_t> geometryMetadata(const std::vector<MeshInfo>& meshes,
                                           const std::vector<SidecarChunk>& chunks) {
    std::vector<std::uint8_t> raw;
    const std::uint32_t mesh_count = static_cast<std::uint32_t>(meshes.size());
    appendPod(raw, mesh_count);
    if (mesh_count != 0) {
        appendBytes(raw, meshes.data(), mesh_count * sizeof(MeshInfo));
    }
    const std::uint32_t instance_count = 0;
    appendPod(raw, instance_count);
    const std::uint32_t has_coordinate_operation = 0;
    appendPod(raw, has_coordinate_operation);
    const double identity[16] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
    appendBytes(raw, identity, sizeof(identity));
    const double one = 1.0;
    appendPod(raw, one);
    appendPod(raw, one);
    const std::uint32_t chunk_count = static_cast<std::uint32_t>(chunks.size());
    appendPod(raw, chunk_count);
    if (chunk_count != 0) {
        appendBytes(raw, chunks.data(), chunk_count * sizeof(SidecarChunk));
    }
    return raw;
}

std::vector<std::uint8_t> elementMetadata(const std::string& string_table) {
    std::vector<std::uint8_t> raw;
    const std::uint32_t element_count = 0;
    appendPod(raw, element_count);
    const std::uint32_t table_bytes = static_cast<std::uint32_t>(string_table.size());
    appendPod(raw, table_bytes);
    appendBytes(raw, string_table.data(), string_table.size());
    return raw;
}

struct Block {
    std::vector<std::uint8_t> payload;
    std::uint64_t comp_field = 0;
    std::uint64_t raw_field = 0;
};

Block honestBlock(const std::vector<std::uint8_t>& raw) {
    Block block;
    block.payload = compressRaw(raw);
    block.comp_field = block.payload.size();
    block.raw_field = raw.size();
    return block;
}

// On-disk .ifcview: 20-byte head, geometry section, then two
// [comp u64][raw u64][payload] metadata blocks. `geom_bytes_field` is what
// the header claims; the bytes actually written are `geom_section`.
void writeView(const fs::path& ifc_path,
               std::uint64_t geom_bytes_field,
               const std::vector<std::uint8_t>& geom_section,
               const Block& geometry_meta,
               const Block& element_meta) {
    const fs::path view = fs::path(ifc_path).replace_extension(".ifcview");
    FILE* file = std::fopen(view.string().c_str(), "wb");
    REQUIRE(file != nullptr);
    const std::uint32_t magic = SIDECAR_MAGIC;
    const std::uint32_t version = SIDECAR_VERSION;
    const std::uint32_t endian = SIDECAR_ENDIAN;
    REQUIRE(std::fwrite(&magic, 4, 1, file) == 1);
    REQUIRE(std::fwrite(&version, 4, 1, file) == 1);
    REQUIRE(std::fwrite(&endian, 4, 1, file) == 1);
    REQUIRE(std::fwrite(&geom_bytes_field, 8, 1, file) == 1);
    if (!geom_section.empty()) {
        REQUIRE(std::fwrite(geom_section.data(), 1, geom_section.size(), file) == geom_section.size());
    }
    auto writeBlock = [&](const Block& block) {
        REQUIRE(std::fwrite(&block.comp_field, 8, 1, file) == 1);
        REQUIRE(std::fwrite(&block.raw_field, 8, 1, file) == 1);
        if (!block.payload.empty()) {
            REQUIRE(std::fwrite(block.payload.data(), 1, block.payload.size(), file) == block.payload.size());
        }
    };
    writeBlock(geometry_meta);
    writeBlock(element_meta);
    std::fclose(file);
}

// `fn` returns true when the loader accepted the file. The call itself must
// not sit inside a Catch2 assertion: REQUIRE catches std::bad_alloc and
// hides the fact that the allocator was asked for the claimed size.
template <typename Fn>
void expectRefusedBeforeAlloc(Fn&& fn) {
    bool threw = false;
    bool accepted = false;
    {
        alloc_watch::Arm arm(kProbeBytes);
        try {
            accepted = static_cast<bool>(fn());
        } catch (const std::bad_alloc&) {
            threw = true;
        }
    }
    const std::size_t requested = alloc_watch::max_request.load();
    const bool rejected = alloc_watch::rejected.load();
    INFO("largest allocation request was " << requested << " bytes");
    // CHECK, not REQUIRE: one bomb must not hide the next loader in this case.
    CHECK_FALSE(threw);
    CHECK_FALSE(rejected);
    CHECK(requested < kProbeBytes);
    if (threw || rejected || requested >= kProbeBytes) {
        return;
    }
    CHECK_FALSE(accepted);
}

} // namespace

TEST_CASE("sidecar struct layout used by the hand-built bombs", "[decompress-bounds]") {
    static_assert(sizeof(MeshInfo) == 56, "MeshInfo padding changed; update the hand-built metadata");
    static_assert(sizeof(SidecarChunk) == 56, "SidecarChunk padding changed; update the hand-built metadata");
    REQUIRE(sizeof(MeshInfo) == 56);
    REQUIRE(sizeof(SidecarChunk) == 56);
}

TEST_CASE("honest sidecar and a repetitive element table still load", "[decompress-bounds]") {
    fs::path dir = makeScratch("honest");
    fs::path ifc = dir / "model.ifc";
    SidecarData data;
    data.string_table.assign(2u * 1024u * 1024u, 'A');
    data.chunks.clear();
    REQUIRE(writeSidecar(ifc.string(), data));

    std::optional<StreamingSidecar> loaded;
    std::optional<SidecarData> full;
    std::size_t requested = 0;
    {
        alloc_watch::Arm arm(16u << 20);
        loaded = readSidecarMetadata(ifc.string());
        full = readSidecar(ifc.string());
        requested = alloc_watch::max_request.load();
        REQUIRE_FALSE(alloc_watch::rejected.load());
    }
    REQUIRE(loaded.has_value());
    REQUIRE(loaded->meta.string_table.size() == data.string_table.size());
    REQUIRE(loaded->meta.string_table == data.string_table);
    REQUIRE(full.has_value());
    REQUIRE(full->string_table.size() == data.string_table.size());
    REQUIRE(full->string_table == data.string_table);
    INFO("largest allocation request was " << requested << " bytes");
    // The 2 MiB table is under both limits and must actually be allocated,
    // so a probe that ignores allocations cannot hide a broken loader.
    REQUIRE(requested >= data.string_table.size());
    REQUIRE(requested < (16u << 20));
}

TEST_CASE("metadata raw size over the absolute cap is refused before allocation",
          "[decompress-bounds]") {
    // 8192 compressed bytes claiming just over 256 MiB. Expansion is 32768,
    // under kMaxExpansion, so only the absolute cap rejects this file.
    constexpr std::uint64_t kClaim = kMaxBlockBytes + 1;
    constexpr std::uint64_t kComp = 8192;
    static_assert(kClaim / kComp <= kMaxExpansion, "cap case must be allowed by the ratio alone");

    fs::path dir = makeScratch("raw-cap");
    fs::path ifc = dir / "model.ifc";
    const Block honest_geometry = honestBlock(geometryMetadata({}, {}));
    const Block honest_element = honestBlock(elementMetadata(""));

    Block geometry = honest_geometry;
    geometry.payload.assign(static_cast<std::size_t>(kComp), 0xA5);
    geometry.comp_field = kComp;
    geometry.raw_field = kClaim;
    writeView(ifc, 0, {}, geometry, honest_element);
    expectRefusedBeforeAlloc([&] { return readSidecarMetadata(ifc.string()).has_value(); });
    expectRefusedBeforeAlloc([&] { return readSidecar(ifc.string()).has_value(); });

    Block element = honest_element;
    element.payload.assign(static_cast<std::size_t>(kComp), 0x5A);
    element.comp_field = kComp;
    element.raw_field = kClaim;
    fs::path element_ifc = dir / "element.ifc";
    writeView(element_ifc, 0, {}, honest_geometry, element);
    expectRefusedBeforeAlloc([&] { return readSidecarMetadata(element_ifc.string()).has_value(); });
    expectRefusedBeforeAlloc([&] { return readSidecar(element_ifc.string()).has_value(); });
}

TEST_CASE("metadata raw size over the expansion cap is refused before allocation",
          "[decompress-bounds]") {
    // 32 MiB claimed from a real tiny frame. Under the 256 MiB cap, so only
    // the expansion check rejects it.
    constexpr std::uint64_t kClaim = 32ull * 1024ull * 1024ull;
    static_assert(kClaim < kMaxBlockBytes, "ratio case must be under the absolute cap");

    fs::path dir = makeScratch("raw-ratio");
    fs::path ifc = dir / "model.ifc";
    const std::vector<std::uint8_t> tiny_raw(4, 0x11);
    const std::vector<std::uint8_t> tiny_frame = compressRaw(tiny_raw);
    REQUIRE(tiny_frame.size() < kClaim / kMaxExpansion);

    const Block honest_geometry = honestBlock(geometryMetadata({}, {}));
    const Block honest_element = honestBlock(elementMetadata(""));

    Block geometry = honest_geometry;
    geometry.payload = tiny_frame;
    geometry.comp_field = tiny_frame.size();
    geometry.raw_field = kClaim;
    writeView(ifc, 0, {}, geometry, honest_element);
    expectRefusedBeforeAlloc([&] { return readSidecarMetadata(ifc.string()).has_value(); });
    expectRefusedBeforeAlloc([&] { return readSidecar(ifc.string()).has_value(); });

    Block element = honest_element;
    element.payload = tiny_frame;
    element.comp_field = tiny_frame.size();
    element.raw_field = kClaim;
    fs::path element_ifc = dir / "element.ifc";
    writeView(element_ifc, 0, {}, honest_geometry, element);
    expectRefusedBeforeAlloc([&] { return readSidecarMetadata(element_ifc.string()).has_value(); });
    expectRefusedBeforeAlloc([&] { return readSidecar(element_ifc.string()).has_value(); });
}

TEST_CASE("compressed metadata length past EOF is refused before allocation",
          "[decompress-bounds]") {
    constexpr std::uint64_t kCompClaim = 32ull * 1024ull * 1024ull;
    fs::path dir = makeScratch("comp-eof");
    fs::path ifc = dir / "model.ifc";
    const Block honest_geometry = honestBlock(geometryMetadata({}, {}));
    const Block honest_element = honestBlock(elementMetadata(""));

    Block geometry = honest_geometry;
    geometry.comp_field = kCompClaim;
    geometry.payload.clear();
    geometry.raw_field = 64;
    writeView(ifc, 0, {}, geometry, honest_element);
    REQUIRE(fs::file_size(fs::path(ifc).replace_extension(".ifcview")) < kProbeBytes);
    expectRefusedBeforeAlloc([&] { return readSidecarMetadata(ifc.string()).has_value(); });
    expectRefusedBeforeAlloc([&] { return readSidecar(ifc.string()).has_value(); });

    Block element = honest_element;
    element.comp_field = kCompClaim;
    element.payload.clear();
    element.raw_field = 64;
    fs::path element_ifc = dir / "element.ifc";
    writeView(element_ifc, 0, {}, honest_geometry, element);
    REQUIRE(fs::file_size(fs::path(element_ifc).replace_extension(".ifcview")) < kProbeBytes);
    expectRefusedBeforeAlloc([&] { return readSidecarMetadata(element_ifc.string()).has_value(); });
    expectRefusedBeforeAlloc([&] { return readSidecar(element_ifc.string()).has_value(); });
}

TEST_CASE("geometry-section length past EOF is refused before allocation", "[decompress-bounds]") {
    constexpr std::uint64_t kGeomClaim = 32ull * 1024ull * 1024ull;
    fs::path dir = makeScratch("geom-len");
    fs::path ifc = dir / "model.ifc";
    const Block geometry = honestBlock(geometryMetadata({}, {}));
    const Block element = honestBlock(elementMetadata(""));
    // Header claims a 32 MiB geometry section; the file ends at the header.
    writeView(ifc, kGeomClaim, {}, geometry, element);
    REQUIRE(fs::file_size(fs::path(ifc).replace_extension(".ifcview")) < kProbeBytes);

    // The streaming reader seeks past the claimed section and does not
    // allocate it. The full reader allocates a buffer of the claimed length
    // before it reads. Only the full reader is the bug under test.
    {
        alloc_watch::Arm arm(kProbeBytes);
        REQUIRE_FALSE(readSidecarMetadata(ifc.string()).has_value());
        REQUIRE_FALSE(alloc_watch::rejected.load());
        REQUIRE(alloc_watch::max_request.load() < kProbeBytes);
    }
    expectRefusedBeforeAlloc([&] { return readSidecar(ifc.string()).has_value(); });
}

TEST_CASE("chunk and mesh sizes inside an honest metadata block are capped", "[decompress-bounds]") {
    fs::path dir = makeScratch("inner");
    fs::path ifc = dir / "model.ifc";

    // Chunk TOC raw size is a lie; the metadata block itself is honest and small.
    // readSidecar allocates v_raw_size before decompressing the chunk frame.
    {
        SidecarChunk chunk{};
        chunk.mesh_count = 0;
        chunk.v_raw_size = 32ull * 1024ull * 1024ull;
        const Block geometry = honestBlock(geometryMetadata({}, {chunk}));
        const Block element = honestBlock(elementMetadata(""));
        writeView(ifc, 0, {}, geometry, element);
        {
            alloc_watch::Arm arm(kProbeBytes);
            REQUIRE(readSidecarMetadata(ifc.string()).has_value());
            REQUIRE_FALSE(alloc_watch::rejected.load());
        }
        expectRefusedBeforeAlloc([&] { return readSidecar(ifc.string()).has_value(); });
    }

    // Mesh vertex_count is what the desktop streamer turns into v_raw_size
    // (count * INSTANCED_VERTEX_STRIDE_BYTES). The metadata block stays small.
    auto writeMesh = [&](std::uint32_t vertex_count, std::uint32_t index_count, std::uint64_t comp_size, const std::vector<std::uint8_t>& geom_section) {
        MeshInfo mesh{};
        mesh.vertex_count = vertex_count;
        mesh.index_count = index_count;
        SidecarChunk chunk{};
        chunk.first_mesh = 0;
        chunk.mesh_count = 1;
        chunk.v_comp_off = 0;
        chunk.v_comp_size = comp_size;
        chunk.v_raw_size = std::uint64_t(vertex_count) * INSTANCED_VERTEX_STRIDE_BYTES;
        chunk.i_comp_off = comp_size;
        chunk.i_comp_size = 0;
        chunk.i_raw_size = std::uint64_t(index_count) * sizeof(std::uint32_t);
        const Block geometry = honestBlock(geometryMetadata({mesh}, {chunk}));
        const Block element = honestBlock(elementMetadata(""));
        writeView(ifc, geom_section.size(), geom_section, geometry, element);
    };

    const std::vector<std::uint8_t> tiny_frame = compressRaw(std::vector<std::uint8_t>(8, 0x22));
    REQUIRE(tiny_frame.size() < (32ull * 1024ull * 1024ull) / kMaxExpansion);

    const std::uint32_t ratio_vertex_count = 2796203; // * 12 = 33554436, just over 32 MiB
    REQUIRE(std::uint64_t(ratio_vertex_count) * INSTANCED_VERTEX_STRIDE_BYTES > 32ull * 1024ull * 1024ull);
    REQUIRE(std::uint64_t(ratio_vertex_count) * INSTANCED_VERTEX_STRIDE_BYTES < kMaxBlockBytes);
    writeMesh(ratio_vertex_count, 0, tiny_frame.size(), tiny_frame);
    {
        alloc_watch::Arm arm(kProbeBytes);
        auto meta = readSidecarMetadata(ifc.string());
        REQUIRE(meta.has_value());
        REQUIRE(meta->meta.meshes.at(0).vertex_count == ratio_vertex_count);
        REQUIRE_FALSE(alloc_watch::rejected.load());
    }
    expectRefusedBeforeAlloc([&] { return readSidecar(ifc.string()).has_value(); });
    {
        auto meta = readSidecarMetadata(ifc.string());
        REQUIRE(meta.has_value());
        const auto mesh = meta->meta.meshes.at(0);
        const auto chunk = meta->meta.chunks.at(0);
        expectRefusedBeforeAlloc([&] {
            std::vector<std::uint8_t> vertices;
            std::vector<std::uint32_t> indices;
            const std::uint64_t vertex_bytes =
                std::uint64_t(mesh.vertex_count) * INSTANCED_VERTEX_STRIDE_BYTES;
            const std::uint64_t index_bytes = std::uint64_t(mesh.index_count) * sizeof(std::uint32_t);
            return readChunkGeometryCompressed(
                ifc.string(), meta->geometry_section_offset, chunk.v_comp_off, chunk.v_comp_size, vertex_bytes, chunk.i_comp_off, chunk.i_comp_size, index_bytes, vertices, indices);
        });
    }

    // Over the absolute cap, with a compressed frame large enough that the
    // expansion ratio alone would allow the claim.
    const std::uint32_t cap_vertex_count = 22369622; // * 12 = 268435464 > 256 MiB
    const std::uint64_t cap_vertex_bytes =
        std::uint64_t(cap_vertex_count) * INSTANCED_VERTEX_STRIDE_BYTES;
    REQUIRE(cap_vertex_bytes > kMaxBlockBytes);
    std::vector<std::uint8_t> wide_frame(4096, 0x33);
    REQUIRE(cap_vertex_bytes / wide_frame.size() <= kMaxExpansion);
    fs::path cap_ifc = dir / "cap.ifc";
    {
        MeshInfo mesh{};
        mesh.vertex_count = cap_vertex_count;
        SidecarChunk chunk{};
        chunk.first_mesh = 0;
        chunk.mesh_count = 1;
        chunk.v_comp_size = wide_frame.size();
        chunk.v_raw_size = cap_vertex_bytes;
        const Block geometry = honestBlock(geometryMetadata({mesh}, {chunk}));
        const Block element = honestBlock(elementMetadata(""));
        writeView(cap_ifc, wide_frame.size(), wide_frame, geometry, element);
    }
    {
        auto meta = readSidecarMetadata(cap_ifc.string());
        REQUIRE(meta.has_value());
        const auto mesh = meta->meta.meshes.at(0);
        const auto chunk = meta->meta.chunks.at(0);
        expectRefusedBeforeAlloc([&] {
            std::vector<std::uint8_t> vertices;
            std::vector<std::uint32_t> indices;
            return readChunkGeometryCompressed(
                cap_ifc.string(), meta->geometry_section_offset, chunk.v_comp_off, chunk.v_comp_size, std::uint64_t(mesh.vertex_count) * INSTANCED_VERTEX_STRIDE_BYTES, chunk.i_comp_off, chunk.i_comp_size, std::uint64_t(mesh.index_count) * sizeof(std::uint32_t), vertices, indices);
        });
    }

    // Index bytes: index_count * 4, vertex buffer empty, tiny index frame.
    const std::uint32_t index_count = 8u * 1024u * 1024u; // 32 MiB of indices
    std::vector<std::uint8_t> index_section = tiny_frame;
    MeshInfo mesh{};
    mesh.vertex_count = 0;
    mesh.index_count = index_count;
    SidecarChunk chunk{};
    chunk.first_mesh = 0;
    chunk.mesh_count = 1;
    chunk.v_comp_size = 0;
    chunk.v_raw_size = 0;
    chunk.i_comp_off = 0;
    chunk.i_comp_size = tiny_frame.size();
    chunk.i_raw_size = std::uint64_t(index_count) * sizeof(std::uint32_t);
    {
        const Block geometry = honestBlock(geometryMetadata({mesh}, {chunk}));
        const Block element = honestBlock(elementMetadata(""));
        writeView(ifc, index_section.size(), index_section, geometry, element);
    }
    {
        auto meta = readSidecarMetadata(ifc.string());
        REQUIRE(meta.has_value());
        const auto loaded_mesh = meta->meta.meshes.at(0);
        const auto loaded_chunk = meta->meta.chunks.at(0);
        expectRefusedBeforeAlloc([&] {
            std::vector<std::uint8_t> vertices;
            std::vector<std::uint32_t> indices;
            return readChunkGeometryCompressed(
                ifc.string(), meta->geometry_section_offset, loaded_chunk.v_comp_off, loaded_chunk.v_comp_size, std::uint64_t(loaded_mesh.vertex_count) * INSTANCED_VERTEX_STRIDE_BYTES, loaded_chunk.i_comp_off, loaded_chunk.i_comp_size, std::uint64_t(loaded_mesh.index_count) * sizeof(std::uint32_t), vertices, indices);
        });
    }

    // Compressed frame length from the TOC, larger than the file. The raw
    // vertex buffer is only one mesh of 6 vertices, so the allocation under
    // test is the compressed-size buffer inside the chunk reader.
    MeshInfo small{};
    small.vertex_count = 6;
    SidecarChunk wide{};
    wide.first_mesh = 0;
    wide.mesh_count = 1;
    wide.v_comp_size = 32ull * 1024ull * 1024ull;
    wide.v_raw_size = 6ull * INSTANCED_VERTEX_STRIDE_BYTES;
    {
        const Block geometry = honestBlock(geometryMetadata({small}, {wide}));
        const Block element = honestBlock(elementMetadata(""));
        const std::vector<std::uint8_t> stub(16, 0x44);
        writeView(ifc, stub.size(), stub, geometry, element);
        REQUIRE(fs::file_size(fs::path(ifc).replace_extension(".ifcview")) < kProbeBytes);
    }
    {
        auto meta = readSidecarMetadata(ifc.string());
        REQUIRE(meta.has_value());
        const auto loaded_mesh = meta->meta.meshes.at(0);
        const auto loaded_chunk = meta->meta.chunks.at(0);
        REQUIRE(loaded_chunk.v_comp_size == 32ull * 1024ull * 1024ull);
        expectRefusedBeforeAlloc([&] {
            std::vector<std::uint8_t> vertices;
            std::vector<std::uint32_t> indices;
            return readChunkGeometryCompressed(
                ifc.string(), meta->geometry_section_offset, loaded_chunk.v_comp_off, loaded_chunk.v_comp_size, std::uint64_t(loaded_mesh.vertex_count) * INSTANCED_VERTEX_STRIDE_BYTES, loaded_chunk.i_comp_off, loaded_chunk.i_comp_size, std::uint64_t(loaded_mesh.index_count) * sizeof(std::uint32_t), vertices, indices);
        });
    }
}
