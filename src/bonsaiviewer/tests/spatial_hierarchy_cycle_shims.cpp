// This file was generated with the assistance of an AI coding tool.
//
// Symbols the spatial-hierarchy view calls, supplied here so the test can
// link View.cpp without the GPU viewport. Bodies that decide the result are
// the product's own: SceneLoader::ifcFile is the lookup in SceneLoader.cpp,
// and the SessionState accessors are the ones in SessionState.cpp.
// SceneLoader's element-poll slots are not on the path from an opened IFC
// file to the spatial tree; they are empty so Qt's meta-object can take
// their addresses.

#include "../../ifcviewer/GeometryStreamer.h"
#include "../../ifcviewer/SceneLoader.h"
#include "../SessionState.h"
#include "spatial_hierarchy_cycle_install.h"

#include <utility>

uint32_t SpatialCycleInstall::session_model_id = 0;
GeometryStreamer* SpatialCycleInstall::streamer = nullptr;

GeometryStreamer::GeometryStreamer(QObject* parent) : QObject(parent) {}

GeometryStreamer::~GeometryStreamer() {}

void GeometryStreamer::setIfcFile(std::unique_ptr<ifcopenshell::file> file) {
    // GeometryStreamer.cpp: setIfcFile stores the opened file for ifcFile().
    ifc_file_ = std::move(file);
}

SceneLoader::SceneLoader(ViewportWindow* viewport, QObject* parent)
    : QObject(parent), viewport_(viewport) {
    if (SpatialCycleInstall::streamer != nullptr && SpatialCycleInstall::session_model_id != 0) {
        Model model;
        model.id = SpatialCycleInstall::session_model_id;
        model.streamer = SpatialCycleInstall::streamer;
        models_.emplace(model.id, std::move(model));
    }
}

SceneLoader::~SceneLoader() {}

ifcopenshell::file* SceneLoader::ifcFile(uint32_t session_model_id) const {
    // SceneLoader.cpp: a missing model yields null; otherwise the streamer's file.
    auto it = models_.find(session_model_id);
    return it == models_.end() ? nullptr : it->second.streamer->ifcFile();
}

void SceneLoader::onStreamerProgressChanged(int) {}
void SceneLoader::onStreamerMeshReady(StreamedMesh) {}
void SceneLoader::onStreamerInstanceReady(StreamedInstance) {}
void SceneLoader::onStreamerFinished() {}
void SceneLoader::onStreamerCancelled() {}
void SceneLoader::onStreamerError(const QString&) {}
void SceneLoader::onElementPollTick() {}

namespace bonsaiviewer {

SessionState::SessionState(QObject* parent) : QObject(parent) {}

void SessionState::setModelMapping(const QString& model_id, uint32_t session_model_id) {
    model_id_to_session_model_id_[model_id] = session_model_id;
    session_model_id_to_model_id_[session_model_id] = model_id;
}

void SessionState::setActiveModelId(const QString& model_id) {
    if (model_id == active_model_id_) {
        return;
    }
    active_model_id_ = model_id;
    emit activeModelChanged(active_model_id_);
}

uint32_t SessionState::sessionModelIdForModelId(const QString& model_id) const {
    return model_id_to_session_model_id_.value(model_id, 0);
}

QString SessionState::modelIdForSessionModelId(uint32_t session_model_id) const {
    return session_model_id_to_model_id_.value(session_model_id);
}

void SessionState::notifyModelGeometryReady(uint32_t session_model_id) {
    emit modelGeometryReady(session_model_id);
}

void SessionState::notifyProjectOpened(const QString& path) {
    emit projectOpened(path);
}

void SessionState::setStatusMessage(const QString& mode, const QString& detail) {
    status_mode_ = mode;
    status_detail_ = detail;
    emit statusMessageChanged(status_mode_, status_detail_);
}

} // namespace bonsaiviewer
