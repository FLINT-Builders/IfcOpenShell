// This file was generated with the assistance of an AI coding tool.
#ifndef SPATIAL_HIERARCHY_CYCLE_INSTALL_H
#define SPATIAL_HIERARCHY_CYCLE_INSTALL_H

#include <cstdint>

class GeometryStreamer;

// The product records a parsed model on SceneLoader before ifcFile() is
// queried. Tests set this, then construct SceneLoader; the shim constructor
// stores the streamer in SceneLoader::models_ so the real ifcFile() lookup
// (copied from SceneLoader.cpp) can return it.
struct SpatialCycleInstall {
    static uint32_t session_model_id;
    static GeometryStreamer* streamer;
};

#endif
