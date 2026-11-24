// This file was generated with the assistance of an AI coding tool.
//
// ViewportCore::raycast must ignore triangle indices that are not less than
// the position count, including values whose 32-bit expression
// `3 * index + 2` wraps (0x55555555 wraps to 1). A hit on an in-range
// triangle in the same mesh must still be reported.
//
// pickMeshLocalAt uses the same wrapped comparison (ViewportCore.cpp around
// the mesh-shadow loop) but only after the GPU pick pass. That entry point
// is not driven here. The comparison it shares with raycast is.

#include <cmath>
#include <cstdint>
#include <iostream>
#include <vector>

#include <Eigen/Dense>

#define private public
#define protected public
#include "ViewportCore.h"
#undef private
#undef protected

#include "ViewportHost.h"

namespace {

struct MockHost : ViewportHost {
    WGPUSurface createSurface(WGPUInstance) override { return nullptr; }
    void framebufferSize(int& w, int& h) const override { w = 64; h = 64; }
    float dpr() const override { return 1.f; }
    void requestFrame() override {}
    void quit() override {}
};

void identity(float m[16]) {
    for (int i = 0; i < 16; ++i) m[i] = 0.f;
    m[0] = m[5] = m[10] = m[15] = 1.f;
}

}  // namespace

int main() {
    MockHost host;
    ViewportCore core(&host);

    ModelGpuData model;
    MeshInfo mesh{};
    mesh.vertex_count = 3;
    mesh.index_count = 6;
    model.meshes = {mesh};

    // Triangle 0 is a real face the ray hits. Triangle 1 carries the
    // wrapping index. Both live in the cache the way applyStreamedChunk
    // leaves them today: raw indices, positions sized to vertex_count.
    ModelGpuData::MeshTriangles tris;
    tris.positions = {
        -1.f, -1.f, 0.f,
         1.f, -1.f, 0.f,
         0.f,  1.f, 0.f,
    };
    tris.indices = {0, 1, 2, 0x55555555u, 0u, 1u};
    model.mesh_triangles_cache = {std::move(tris)};

    InstanceInfo inst{};
    inst.mesh_id = 0;
    inst.object_id = 42;
    identity(inst.transform);
    inst.world_aabb_min[0] = inst.world_aabb_min[1] = inst.world_aabb_min[2] = -2.f;
    inst.world_aabb_max[0] = inst.world_aabb_max[1] = inst.world_aabb_max[2] = 2.f;
    model.instances = {inst};
    model.hidden = false;
    model.unloaded = false;

    core.models_gpu_.emplace(1, std::move(model));

    const float origin[3] = {0.f, 0.f, 5.f};
    const float dir[3] = {0.f, 0.f, -1.f};
    ViewportCore::RaycastHit hit;
    const bool found = core.raycast(origin, dir, hit);
    if (!found) {
        std::cerr << "FAIL: raycast dropped the in-range triangle or did not return\n";
        return 1;
    }
    if (hit.object_id != 42) {
        std::cerr << "FAIL: raycast hit object " << hit.object_id << "\n";
        return 1;
    }
    if (!(hit.distance > 4.5f && hit.distance < 5.5f)) {
        std::cerr << "FAIL: raycast distance " << hit.distance << "\n";
        return 1;
    }
    std::cout << "PASS raycast index bounds\n";
    return 0;
}
