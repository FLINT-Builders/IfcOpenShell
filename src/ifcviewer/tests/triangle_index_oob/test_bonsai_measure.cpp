// This file was generated with the assistance of an AI coding tool.
//
// BonsaiViewer AreaMeasurement (meshCache and onPick), LengthMeasurement's
// laser overlay, and volumeOfObjects / volumesPerObject must measure the
// in-range triangle and must not read positions through an out-of-range
// index. Same triangle list the sidecar cache stores.

#include "meas_viewport.h"
#include "attack_mesh.h"

#include "Measurement.h"

#include <cmath>
#include <iostream>
#include <string>
#include <vector>

namespace {

void maybeStrip(ViewportWindow& vp, bool attack) {
    if (!attack) vp.triangles.indices = {0, 1, 2};
}

int runArea(bool attack) {
    ViewportWindow vp;
    plantAttackMesh(vp);
    maybeStrip(vp, attack);
    AreaMeasurement area;
    area.onPick(vp, 0, 0, false);
    const double got = area.totalArea();
    if (!(std::abs(got - kAttackArea) < 1e-4)) {
        std::cerr << "FAIL: bonsai area " << got << " want " << kAttackArea << "\n";
        return 1;
    }
    std::cout << "PASS bonsai area\n";
    return 0;
}

int runLength(bool attack) {
    ViewportWindow vp;
    plantAttackMesh(vp);
    maybeStrip(vp, attack);
    LengthMeasurement length;
    length.onPick(vp, 0, 0, false);
    if (length.pointCount() != 1) {
        std::cerr << "FAIL: bonsai length did not keep the pick\n";
        return 1;
    }
    if (vp.hud.find("extent") == std::string::npos) {
        std::cerr << "FAIL: bonsai length HUD missing face extent: [" << vp.hud << "]\n";
        return 1;
    }
    std::cout << "PASS bonsai length\n";
    return 0;
}

int runVolume(bool attack) {
    ViewportWindow vp;
    plantAttackMesh(vp);
    maybeStrip(vp, attack);
    const double got = volumeOfObjects(vp, {7});
    if (!(std::abs(got - kAttackVolume) < 1e-5)) {
        std::cerr << "FAIL: bonsai volume " << got << " want " << kAttackVolume << "\n";
        return 1;
    }
    const auto per = volumesPerObject(vp, {7});
    if (per.size() != 1 || !(std::abs(per[0].second - kAttackVolume) < 1e-5)) {
        std::cerr << "FAIL: bonsai per-object volume\n";
        return 1;
    }
    std::cout << "PASS bonsai volume\n";
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    if (mode == "area") return runArea(true);
    if (mode == "length") return runLength(true);
    if (mode == "volume") return runVolume(true);
    if (mode == "area-valid") return runArea(false);
    if (mode == "length-valid") return runLength(false);
    if (mode == "volume-valid") return runVolume(false);
    std::cerr << "usage: test_bonsai_measure area|length|volume|area-valid|length-valid|volume-valid\n";
    return 2;
}
