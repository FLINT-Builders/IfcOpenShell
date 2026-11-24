// This file was generated with the assistance of an AI coding tool.
// Overlay structs the measurement tools fill. No index arithmetic.
#ifndef MEAS_OVERLAY_H
#define MEAS_OVERLAY_H

#include "meas_qt.h"

#include <vector>

class OverlayRenderer {
public:
    struct LineGroup {
        std::vector<float> world_xyz;
        float color[4]        = {1, 1, 1, 1};
        float stroke_color[4] = {0, 0, 0, 1};
        float line_width      = 1.5f;
        float stroke_extra    = 0.5f;
        float dash_period_px  = 0.0f;
        float dash_on_ratio   = 0.6f;
    };
    struct Label {
        float   world_pos[3] = {};
        QString text;
    };
};

#endif
