// This file was generated with the assistance of an AI coding tool.
//
// SceneLoader::queueModels is invoked only after extractRdbview has already
// inflated the bundle. The real queueModels (SceneLoader.cpp) assigns ids and
// schedules a geometry load; it does not read the zip. These definitions keep
// that boundary: they record the paths loadModels actually queued and do not
// open them.

#include "../../ifcviewer/SceneLoader.h"

#include <QStringList>
#include <QThread>

namespace {

QStringList g_queued;
void* g_queue_thread = nullptr;

} // namespace

QStringList rdbview_test_queued_paths() { return g_queued; }

void rdbview_test_reset_queued_paths() {
    g_queued.clear();
    g_queue_thread = nullptr;
}

void* rdbview_test_queue_thread() { return g_queue_thread; }

SceneLoader::SceneLoader(ViewportWindow* viewport, QObject* parent)
    : QObject(parent), viewport_(viewport) {}

SceneLoader::~SceneLoader() {
    if (sidecar_read_thread_.joinable()) sidecar_read_thread_.join();
    for (auto& thread : data_source_threads_) {
        if (thread.joinable()) thread.join();
    }
    if (sidecar_write_thread_.joinable()) sidecar_write_thread_.join();
}

void SceneLoader::setShouldReadSidecar(bool enabled) { should_read_sidecar_ = enabled; }
void SceneLoader::setShouldWriteSidecar(bool enabled) { should_write_sidecar_ = enabled; }

std::vector<uint32_t> SceneLoader::queueModels(const QStringList& paths) {
    g_queue_thread = QThread::currentThreadId();
    std::vector<uint32_t> assigned;
    assigned.reserve(static_cast<size_t>(paths.size()));
    for (const QString& path : paths) {
        g_queued.push_back(path);
        assigned.push_back(next_session_model_id_++);
    }
    return assigned;
}

void SceneLoader::cancelCurrentLoad() {}
void SceneLoader::removeModel(uint32_t) {}
QString SceneLoader::filePath(uint32_t) const { return {}; }
QString SceneLoader::displayName(uint32_t) const { return {}; }
ifcopenshell::file* SceneLoader::ifcFile(uint32_t) const { return nullptr; }
const ModelGeoref* SceneLoader::modelGeoref(uint32_t) { return nullptr; }

void SceneLoader::onStreamerProgressChanged(int) {}
void SceneLoader::onStreamerMeshReady(StreamedMesh) {}
void SceneLoader::onStreamerInstanceReady(StreamedInstance) {}
void SceneLoader::onStreamerFinished() {}
void SceneLoader::onStreamerCancelled() {}
void SceneLoader::onStreamerError(const QString&) {}
void SceneLoader::onElementPollTick() {}
