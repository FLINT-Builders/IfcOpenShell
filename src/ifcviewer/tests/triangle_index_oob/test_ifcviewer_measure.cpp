// This file was generated with the assistance of an AI coding tool.
//
// IfcViewer AreaMeasurement::onPick / meshAdj and LengthMeasurement's
// laser overlay must measure the in-range triangle and must not read
// positions through an out-of-range index. The triangles are the ones a
// crafted sidecar leaves in the CPU cache; readback is the straight copy
// ViewportWindow::readbackMeshTriangles performs.

#include "meas_viewport.h"
#include "attack_mesh.h"

#include "AreaMeasurement.h"
#include "LengthMeasurement.h"

#include <cmath>
#include <iostream>
#include <string>

namespace {

int runArea(bool attack) {
    ViewportWindow vp;
    plantAttackMesh(vp);
    if (!attack) vp.triangles.indices = {0, 1, 2};
    AreaMeasurement area;
    area.onPick(vp, 0, 0, false);
    const double got = area.totalArea();
    if (!(std::abs(got - kAttackArea) < 1e-4)) {
        std::cerr << "FAIL: ifcviewer area " << got << " want " << kAttackArea << "\n";
        return 1;
    }
    std::cout << "PASS ifcviewer area\n";
    return 0;
}

int runLength(bool attack) {
    ViewportWindow vp;
    plantAttackMesh(vp);
    if (!attack) vp.triangles.indices = {0, 1, 2};
    LengthMeasurement length;
    length.onPick(vp, 0, 0, false);
    if (length.pointCount() != 1) {
        std::cerr << "FAIL: ifcviewer length did not keep the pick\n";
        return 1;
    }
    if (vp.hud.find("extent") == std::string::npos) {
        std::cerr << "FAIL: ifcviewer length HUD missing face extent: [" << vp.hud << "]\n";
        return 1;
    }
    std::cout << "PASS ifcviewer length\n";
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    if (mode == "area") return runArea(true);
    if (mode == "length") return runLength(true);
    if (mode == "area-valid") return runArea(false);
    if (mode == "length-valid") return runLength(false);
    std::cerr << "usage: test_ifcviewer_measure area|length|area-valid|length-valid\n";
    return 2;
}
