// This file was generated with the assistance of an AI coding tool.
//
// Stand-in for ViewportWindow so the real AreaMeasurement / LengthMeasurement
// translation units can be compiled without Qt. The methods that move triangle
// data do the same thing as the product:
//   readbackMeshTriangles copies the cached positions and indices with no
//   index check (ViewportWindow.cpp:1025-1036).
// pickMeshLocalAt / findInstance only hand back the record the test planted,
// which is what a successful pick of that element returns. They do not
// interpret index values.
#ifndef MEAS_VIEWPORT_H
#define MEAS_VIEWPORT_H

#include "meas_overlay.h"

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

class ViewportWindow {
public:
    struct MeshTriangles {
        std::vector<float>    positions;
        std::vector<uint32_t> indices;
    };
    struct MeshLocalPick {
        uint32_t object_id = 0;
        uint32_t session_model_id = 0;
        uint32_t mesh_id = 0;
        float mesh_local[3] = {};
        float world_pos[3] = {};
        float world_normal[3] = {};
        float composed_transform[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
    };
    struct RaycastHit {
        uint32_t object_id = 0;
        float distance = 0;
        float world_pos[3] = {};
        float world_normal[3] = {};
    };
    struct InstanceLookup {
        uint32_t session_model_id = 0;
        uint32_t mesh_id = 0;
        double placement_transformation[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
    };

    MeshTriangles triangles;
    MeshLocalPick planted_pick;
    bool have_pick = true;
    InstanceLookup planted_lookup;
    bool have_lookup = true;
    std::string hud;
    std::vector<float> highlight;

    // Same contract as ViewportWindow::readbackMeshTriangles: copy the shadow
    // through, including any out-of-range index values.
    bool readbackMeshTriangles(uint32_t, uint32_t, MeshTriangles& out) const {
        if (triangles.indices.empty() || triangles.positions.empty()) return false;
        out = triangles;
        return true;
    }
    bool pickMeshLocalAt(int, int, MeshLocalPick& out) {
        if (!have_pick) return false;
        out = planted_pick;
        return true;
    }
    bool findInstance(uint32_t, InstanceLookup& out) const {
        if (!have_lookup) return false;
        out = planted_lookup;
        return true;
    }
    bool meshLocalToGlobal(uint32_t, const float mesh_local[3], double global_out[3]) const {
        global_out[0] = mesh_local[0];
        global_out[1] = mesh_local[1];
        global_out[2] = mesh_local[2];
        return true;
    }
    bool raycast(const float*, const float*, RaycastHit&) const { return false; }

    void setOverlayLines(const std::vector<OverlayRenderer::LineGroup>&) {}
    void setOverlayPoints(const std::vector<float>&,
                          float, float, float, float, float,
                          float, float, float, float, float) {}
    void setOverlayLabels(const std::vector<OverlayRenderer::Label>&) {}
    void setHudText(const std::string& text) { hud = text; }
    void setHighlightTriangles(const std::vector<float>& world_xyz,
                               float, float, float, float) {
        highlight = world_xyz;
    }
};

#endif
