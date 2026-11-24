// This file was generated with the assistance of an AI coding tool.
// Shared attacker mesh for the measurement-tool tests.
#ifndef ATTACK_MESH_H
#define ATTACK_MESH_H

#include "meas_viewport.h"

#include <cstdint>
#include <vector>

// One in-range triangle plus two out-of-range ones.
//   (1,0,0), (1,1,0), (1,0,1) has area 0.5 and signed volume 1/6.
//   0x10000000 is past the vertex count and does not wrap 3*index.
//   0x55555555 makes the 32-bit expression `3 * index + 2` wrap to 1.
inline void plantAttackMesh(ViewportWindow& vp) {
    vp.triangles.positions = {
        1.f, 0.f, 0.f,
        1.f, 1.f, 0.f,
        1.f, 0.f, 1.f,
    };
    vp.triangles.indices = {
        0, 1, 2,
        0, 1, 0x10000000u,
        0x55555555u, 0, 1,
    };
    vp.planted_pick.object_id = 7;
    vp.planted_pick.session_model_id = 1;
    vp.planted_pick.mesh_id = 0;
    vp.planted_pick.mesh_local[0] = 1.f;
    vp.planted_pick.mesh_local[1] = 0.f;
    vp.planted_pick.mesh_local[2] = 0.f;
    vp.planted_pick.world_pos[0] = 1.f;
    vp.planted_pick.world_pos[1] = 0.f;
    vp.planted_pick.world_pos[2] = 0.f;
    vp.planted_pick.world_normal[0] = 1.f;
    vp.planted_pick.world_normal[1] = 0.f;
    vp.planted_pick.world_normal[2] = 0.f;
    vp.planted_lookup.session_model_id = 1;
    vp.planted_lookup.mesh_id = 0;
}

inline constexpr double kAttackArea = 0.5;
inline constexpr double kAttackVolume = 1.0 / 6.0;

#endif
