// This file was generated with the assistance of an AI coding tool.
//
// Spec for the sidecar triangle-index bug. These checks fail while
// computeMeshLocalVolumeQuantised copies every index into the CPU triangle
// cache, and pass once only in-range indices are stored.
//
// The bytes travel through the real bake and the real streaming reader
// (writeSidecar -> readSidecarMetadata -> readChunkGeometryCompressed) and
// then through ViewportCore::applyStreamedChunk, which is what a streamed
// chunk calls. wgpuQueueWriteBuffer is wrapped because the pool slices are
// fake handles; the index values are not rewritten there.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

#include <Eigen/Dense>

#define private public
#define protected public
#include "ViewportCore.h"
#undef private
#undef protected

#include "SidecarCache.h"
#include "StreamingLoader.h"
#include "ViewportHost.h"

namespace fs = std::filesystem;

namespace {

int g_fails = 0;

void expect(bool cond, const char* msg) {
    if (cond) return;
    std::cerr << "FAIL: " << msg << "\n";
    ++g_fails;
}

struct MockHost : ViewportHost {
    WGPUSurface createSurface(WGPUInstance) override { return nullptr; }
    void framebufferSize(int& w, int& h) const override { w = 64; h = 64; }
    float dpr() const override { return 1.f; }
    void requestFrame() override {}
    void quit() override {}
};

SidecarData makeSidecar(const std::vector<uint32_t>& indices) {
    SidecarData sd;
    sd.vertices.assign(3 * INSTANCED_VERTEX_STRIDE_BYTES, 0);
    sd.indices = indices;
    MeshInfo mesh{};
    mesh.vertex_count = 3;
    mesh.index_count = uint32_t(indices.size());
    mesh.local_aabb_min[0] = mesh.local_aabb_min[1] = mesh.local_aabb_min[2] = -1.f;
    mesh.local_aabb_max[0] = mesh.local_aabb_max[1] = mesh.local_aabb_max[2] = 1.f;
    sd.meshes = {mesh};
    InstanceInfo inst{};
    inst.mesh_id = 0;
    inst.object_id = 1;
    inst.session_model_id = 1;
    sd.instances = {inst};
    sd.chunks = {{0, 1}};
    return sd;
}

struct LoadedChunk {
    std::vector<uint8_t> vbytes;
    std::vector<uint32_t> idx;
    StreamingSidecar meta;
};

bool loadChunk(const SidecarData& sd, const fs::path& dir, LoadedChunk& out) {
    const fs::path ifc = dir / "project.ifc";
    if (!writeSidecar(ifc.string(), sd)) return false;
    auto meta = readSidecarMetadata(ifc.string());
    if (!meta || meta->meta.chunks.size() != 1) return false;
    const auto& c = meta->meta.chunks[0];
    if (!readChunkGeometryCompressed(
            ifc.string(), meta->geometry_section_offset,
            c.v_comp_off, c.v_comp_size, c.v_raw_size,
            c.i_comp_off, c.i_comp_size, c.i_raw_size,
            out.vbytes, out.idx)) {
        return false;
    }
    out.meta = std::move(*meta);
    return true;
}

// The GPU uploads in applyStreamedChunk are not what this test is about.
// Fake pool slices satisfy alloc(); the wrapped queue write does not touch
// the index vector.
extern "C" void __wrap_wgpuQueueWriteBuffer(WGPUQueue, WGPUBuffer, uint64_t,
                                            void const*, size_t) {}

bool applyChunk(ViewportCore& core, const LoadedChunk& loaded, ModelGpuData& model) {
    model = ModelGpuData{};
    model.meshes = loaded.meta.meta.meshes;
    model.mesh_local_volumes.assign(model.meshes.size(), 0.0);
    model.mesh_triangles_cache.assign(model.meshes.size(), {});
    model.mesh_resident_chunk_refs.assign(model.meshes.size(), 0);
    model.mesh_chunk_local_base_vertex.assign(model.meshes.size(), 0);
    model.mesh_chunk_local_ebo_first_u32.assign(model.meshes.size(), 0);
    ModelGpuData::Chunk chunk;
    chunk.mesh_ids = {0};
    model.chunks = {chunk};

    core.pool_.addSubBufferForTesting(reinterpret_cast<WGPUBuffer>(0x1), 64ull << 20);
    const bool ok = core.applyStreamedChunk(model, 0, loaded.vbytes, loaded.idx);
    core.pool_.clearSubPoolsForTesting();
    return ok;
}

}  // namespace

int main() {
    MockHost host;
    expect(host.wantsCpuMeshTriangles(),
           "desktop host must request the CPU triangle shadow");

    const fs::path root = fs::temp_directory_path() / "ifcviewer_index_oob_tests";
    fs::remove_all(root);
    fs::create_directories(root / "valid");
    fs::create_directories(root / "crafted");

    {
        LoadedChunk loaded;
        expect(loadChunk(makeSidecar({0, 1, 2}), root / "valid", loaded),
               "valid sidecar round-trip");
        expect(loaded.idx == std::vector<uint32_t>({0, 1, 2}),
               "valid indices survive zstd");
        ViewportCore core(&host);
        ModelGpuData model;
        expect(applyChunk(core, loaded, model), "apply valid chunk");
        const auto& tris = model.mesh_triangles_cache.at(0);
        expect(tris.positions.size() == 9, "valid mesh dequantises 3 vertices");
        expect(tris.indices == std::vector<uint32_t>({0, 1, 2}),
               "in-range triangle is kept in the CPU cache");
    }

    {
        const std::vector<uint32_t> crafted = {0, 1, 2, 0, 1, 0x55555555u, 0, 1, 0x10000000u};
        LoadedChunk loaded;
        expect(loadChunk(makeSidecar(crafted), root / "crafted", loaded),
               "crafted sidecar round-trip");
        expect(loaded.idx == crafted,
               "out-of-range indices survive the sidecar reader unchanged");
        ViewportCore core(&host);
        ModelGpuData model;
        expect(applyChunk(core, loaded, model), "apply crafted chunk");
        const auto& tris = model.mesh_triangles_cache.at(0);
        // Positions are sized to the mesh vertex count. An index >= that
        // count is an out-of-bounds read when a measurement tool uses it.
        const uint32_t vertex_count = model.meshes.at(0).vertex_count;
        expect(tris.positions.size() == size_t(vertex_count) * 3,
               "cache positions are exactly the mesh vertices");
        bool oob = false;
        for (uint32_t ix : tris.indices) {
            if (ix >= vertex_count) oob = true;
        }
        if (oob) {
            std::cerr << "FAIL: CPU triangle cache stored an index >= vertex_count ("
                      << vertex_count << "):";
            for (uint32_t ix : tris.indices) std::cerr << " " << ix;
            std::cerr << "\n";
            ++g_fails;
        }
    }

    fs::remove_all(root);
    if (g_fails) {
        std::cerr << g_fails << " check(s) failed\n";
        return 1;
    }
    std::cout << "PASS sidecar index cache\n";
    return 0;
}
