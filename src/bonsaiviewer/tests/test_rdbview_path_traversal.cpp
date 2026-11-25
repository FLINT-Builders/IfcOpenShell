// This file was generated with the assistance of an AI coding tool.
//
// Spec for .rdbview extraction: a bundle opened through loadModels (the path
// used by project open, Add Model, and a cloud pull) must not create, modify,
// or delete anything outside the session cache directory. These checks fail
// while entry names are joined onto that directory and written as-is.

#include <QCoreApplication>
#include <QByteArray>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonObject>
#include <QStandardPaths>
#include <QVariantMap>

#include <QtCore/private/qzipwriter_p.h>

#include <cstdint>
#include <exception>
#include <iostream>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include <QHash>
#include <QPair>

#include <errno.h>
#include <sys/inotify.h>
#include <sys/stat.h>
#include <unistd.h>

// Heavy translation-unit dependencies of Commands.cpp are not part of the
// unzip. Their include guards are claimed here and the declarations below are
// only complete enough for the rest of that file to compile. loadModels,
// resolveLoadPath, and extractRdbview are the originals from Commands.cpp.

#define IFCINTERFACE_ELEMENTREGISTRY_H
#define IFCINTERFACE_SESSIONSTATE_H
#define FEDERATION_H
#define SCENELOADER_H
#define SIDECARBUILDER_H
#define WGPUVIEWPORTWINDOW_H
#define SERIALIZER_H
#define IFCOPENSHELL_DOCUMENT_SERIALIZER_PLUGIN_H

class Federation {
public:
    struct Group {
        bool visible = true;
        QString display_name;
    };
    struct Model {
        bool visible = true;
        QString display_name;
        QString source_connector;
        QJsonObject source_data;
    };

    Group* findGroupById(const QString&) { return nullptr; }
    Model* findById(const QString&) { return nullptr; }
    void setGroupVisible(const QString&, bool) {}
    void setModelVisible(const QString&, bool) {}
    QString addGroup(const QString&, const QString&) { return {}; }
    void setGroupName(const QString&, const QString&) {}
    void setModelDisplayName(const QString&, const QString&) {}
    void setGroupParent(const QString&, const QString&) {}
    void setModelGroup(const QString&, const QString&) {}
    void removeGroup(const QString&) {}
    void removeModel(const QString&) {}
    QString addModel(const QString&, const QString&) { return {}; }
    QString addCloudModel(const QString&, const QString&, const QJsonObject&) { return {}; }
    void setModelSource(const QString&, const QString&, const QJsonObject&) {}
};

class ViewportWindow {
public:
    void setSelectedObjectId(uint32_t) {}
    void removeModel(uint32_t) {}
    void unloadModel(uint32_t) {}
    bool loadModel(uint32_t) { return false; }
    std::uint64_t modelVramBytes(uint32_t) const { return 0; }
    bool viewModels(const std::vector<uint32_t>&) { return false; }
};

static QStringList g_queued_paths;

class SceneLoader {
public:
    std::vector<uint32_t> queueModels(const QStringList& paths) {
        g_queued_paths = paths;
        std::vector<uint32_t> ids;
        ids.reserve(static_cast<size_t>(paths.size()));
        for (int i = 0; i < paths.size(); ++i) ids.push_back(static_cast<uint32_t>(i + 1));
        return ids;
    }
    bool isLoadingModel(uint32_t) { return false; }
    void removeModel(uint32_t) {}
    QString filePath(uint32_t) const { return {}; }
};

class SidecarBuilder {
public:
    bool build(const QString&, const QString&) { return false; }
    QString lastError() const { return {}; }
};

namespace ifcopenshell {
class exception : public std::exception {
public:
    explicit exception(std::string message) : message_(std::move(message)) {}
    const char* what() const noexcept override { return message_.c_str(); }

private:
    std::string message_;
};

namespace geom {
class serializer {
public:
    virtual ~serializer() = default;
    virtual void finalize() {}
};
}  // namespace geom

namespace serializers {
struct document_serializer_info {
    bool supports_input_filename = false;
};
struct document_serializer_context {
    void* file = nullptr;
    std::string input_filename;
    std::string output_filename;
    bool stream = false;
    std::vector<std::string> skip_supertypes;
};
class document_serializer_registry {
public:
    const document_serializer_info* find(const std::string&) { return nullptr; }
    std::shared_ptr<ifcopenshell::geom::serializer> create(const std::string&, const document_serializer_context&) {
        return {};
    }
};
inline document_serializer_registry& document_serializer_registry_instance() {
    static document_serializer_registry registry;
    return registry;
}
}  // namespace serializers
}  // namespace ifcopenshell

namespace bonsaiviewer::modules::connectors {
class ConnectorRegistry;
}

namespace bonsaiviewer {
class ElementRegistry {
public:
    void removeModel(uint32_t) {}
};

class SessionState : public QObject {
public:
    explicit SessionState(QObject* parent = nullptr) : QObject(parent) {}

    Federation* federation() { return &federation_; }
    SceneLoader* loader() { return &loader_; }
    ElementRegistry* elementRegistry() { return &elements_; }
    modules::connectors::ConnectorRegistry* connectorRegistry();
    void setStatusMessage(const QString&, const QString&) {}
    void beginProgress(const QString&) {}
    void endProgress() {}
    void setModelMapping(const QString&, uint32_t) {}
    void removeModelMappingByModelId(const QString&) {}
    void setCloudMetadata(const QString&, const QVariantMap&) {}
    uint32_t sessionModelIdForModelId(const QString&) const { return 0; }
    QList<uint32_t> sessionModelIds() const { return {}; }
    void setSelectedObjectId(uint32_t) {}
    void notifySelectionChanged() {}
    void notifyModelsChanged() {}
    void notifyFederationChanged() {}
    void notifyVisibilityChanged() {}
    void notifyModelLoadStateChanged(const QString&) {}

private:
    Federation federation_;
    SceneLoader loader_;
    ElementRegistry elements_;
};
}  // namespace bonsaiviewer

#include "../modules/models/Commands.cpp"

namespace bonsaiviewer {
modules::connectors::ConnectorRegistry* SessionState::connectorRegistry() { return nullptr; }
}

namespace {

int g_failures = 0;
QString g_sandbox;
QString g_cache_root;

void fail(const std::string& name, const std::string& detail) {
    std::cerr << "FAIL " << name << ": " << detail << "\n";
    ++g_failures;
}

void pass(const std::string& name) { std::cerr << "PASS " << name << "\n"; }

QString sandboxChild(const QString& rel) { return QDir(g_sandbox).filePath(rel); }

bool writeBytes(const QString& path, const QByteArray& bytes) {
    QDir().mkpath(QFileInfo(path).absolutePath());
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) return false;
    return file.write(bytes) == bytes.size();
}

QByteArray readBytes(const QString& path) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) return {};
    return file.readAll();
}

void writeZip(const QString& path, const QList<QPair<QString, QByteArray>>& entries) {
    QFile::remove(path);
    QZipWriter writer(path);
    writer.setCompressionPolicy(QZipWriter::NeverCompress);
    for (const auto& entry : entries) writer.addFile(entry.first, entry.second);
    writer.close();
}

class DirWatch {
public:
    DirWatch() : fd_(inotify_init1(IN_NONBLOCK | IN_CLOEXEC)) {}
    ~DirWatch() {
        if (fd_ >= 0) close(fd_);
    }

    bool add(const QString& dir) {
        if (fd_ < 0) return false;
        const int wd = inotify_add_watch(fd_, dir.toLocal8Bit().constData(),
                                          IN_CREATE | IN_DELETE | IN_MODIFY | IN_MOVED_FROM | IN_MOVED_TO |
                                              IN_CLOSE_WRITE | IN_ATTRIB | IN_DELETE_SELF);
        if (wd < 0) return false;
        dirs_.insert(wd, dir);
        return true;
    }

    // Names created, removed, or written directly inside a watched directory.
    QStringList events() {
        QStringList out;
        if (fd_ < 0) return out;
        alignas(inotify_event) char buf[4096];
        while (true) {
            const ssize_t n = read(fd_, buf, sizeof(buf));
            if (n < 0) break;
            ssize_t off = 0;
            while (off < n) {
                auto* ev = reinterpret_cast<inotify_event*>(buf + off);
                const QString dir = dirs_.value(ev->wd);
                const QString name = ev->len ? QString::fromLocal8Bit(ev->name) : QString();
                out << (dir + "/" + name + " mask=" + QString::number(ev->mask));
                off += sizeof(inotify_event) + ev->len;
            }
        }
        return out;
    }

private:
    int fd_ = -1;
    QHash<int, QString> dirs_;
};

struct OutsideProbe {
    QString path;
    QByteArray sentinel;
    bool existed = false;
};

void resetCache() { bonsaiviewer::modules::models::commands::cleanupRdbviewCache(); }

void loadBundle(const QString& path) {
    g_queued_paths.clear();
    bonsaiviewer::SessionState session;
    bonsaiviewer::modules::models::commands::detail::loadModels(
        session, QStringList{path}, QStringList{QStringLiteral("model-1")});
}

bool outsideUntouched(const std::string& name, const OutsideProbe& probe, const QStringList& events,
                      const QString& allowed_dir_event) {
    bool ok = true;
    if (probe.existed) {
        if (readBytes(probe.path) != probe.sentinel) {
            fail(name, "existing file outside the cache was modified: " + probe.path.toStdString() +
                           " now contains '" + readBytes(probe.path).toStdString() + "'");
            ok = false;
        }
    } else if (QFileInfo::exists(probe.path)) {
        fail(name, "created " + probe.path.toStdString() + " containing '" +
                       readBytes(probe.path).left(200).toStdString() + "'");
        ok = false;
    }
    for (const QString& event : events) {
        const QString leaf = QFileInfo(event.section(' ', 0, 0)).fileName();
        if (leaf == QFileInfo(allowed_dir_event).fileName()) continue;
        if (event.contains(g_cache_root)) continue;
        fail(name, "filesystem event outside the cache: " + event.toStdString());
        ok = false;
    }
    return ok;
}

void expectBenignLoaded(const std::string& name, const QByteArray& payload) {
    if (g_queued_paths.size() != 1) {
        fail(name, "expected the extracted model.rdb to be queued, got " +
                       std::to_string(g_queued_paths.size()) + " path(s)");
        return;
    }
    const QString queued = QFileInfo(g_queued_paths.front()).absoluteFilePath();
    const QString cache = QFileInfo(g_cache_root).absoluteFilePath();
    if (!queued.startsWith(cache + "/") || !queued.endsWith("/model.rdb")) {
        fail(name, "queued path is not model.rdb inside the cache: " + queued.toStdString());
        return;
    }
    if (readBytes(queued) != payload) {
        fail(name, "model.rdb bytes were not extracted into the cache");
        return;
    }
    pass(name);
}

const QByteArray kModel = QByteArray("MODEL-RDB-BYTES");
const QByteArray kSidecar = QByteArray("SIDECAR-BYTES");
const QByteArray kPayload = QByteArray("PWNED-RDBVIEW-BYTES");
const QByteArray kSentinel = QByteArray("SAFE-SENTINEL");

void testBenignBundleStaysInside() {
    const std::string name = "benign_bundle_extracts_inside_cache";
    resetCache();
    const QString zip = sandboxChild("bundles/benign.rdbview");
    writeZip(zip, {{"model.ifcview", kSidecar}, {"model.rdb", kModel}});
    const QString outside = sandboxChild("outside/from-benign.bin");
    DirWatch watch;
    watch.add(g_sandbox);
    watch.add(sandboxChild("outside"));
    loadBundle(zip);
    const bool quiet = outsideUntouched(name, OutsideProbe{outside, {}, false}, watch.events(), g_cache_root);
    if (quiet) expectBenignLoaded(name, kModel);
    QFile::remove(zip);
    resetCache();
}

// `seed` is a normal file entry written first so its parent directory exists.
// QFile opens the joined name without collapsing "..", so a later entry can
// only leave the cache when that intermediate directory is already there.
void testDotDotDoesNotEscape(const QString& seed_name, const QByteArray& seed_bytes, const QString& entry_name,
                             const std::string& name) {
    resetCache();
    QDir(sandboxChild("outside")).removeRecursively();
    const QString zip = sandboxChild("bundles/" + QString::fromStdString(name) + ".rdbview");
    const QString outside = sandboxChild("outside/pwned.bin");
    writeZip(zip, {{seed_name, seed_bytes}, {entry_name, kPayload}, {"model.ifcview", kSidecar}});
    DirWatch watch;
    watch.add(g_sandbox);
    loadBundle(zip);
    const QStringList events = watch.events();
    if (QFileInfo::exists(outside)) {
        fail(name, "created " + outside.toStdString() + " containing '" +
                       readBytes(outside).left(200).toStdString() + "'");
    } else if (QFileInfo::exists(sandboxChild("outside"))) {
        fail(name, "created directory outside the cache: " + sandboxChild("outside").toStdString());
    } else if (!outsideUntouched(name, OutsideProbe{outside, {}, false}, events, g_cache_root)) {
        // outsideUntouched already recorded the event.
    } else {
        pass(name);
    }
    QFile::remove(zip);
    QDir(sandboxChild("outside")).removeRecursively();
    resetCache();
}

void testAbsolutePathDoesNotReplaceSentinel() {
    const std::string name = "absolute_entry_does_not_write_outside";
    resetCache();
    const QString target = sandboxChild("absolute/sentinel.bin");
    writeBytes(target, kSentinel);
    const QString zip = sandboxChild("bundles/absolute.rdbview");
    const QString absolute = QFileInfo(target).absoluteFilePath();
    writeZip(zip, {{absolute, kPayload}, {"model.rdb", kModel}});
    DirWatch watch;
    watch.add(sandboxChild("absolute"));
    watch.add(g_sandbox);
    loadBundle(zip);
    if (outsideUntouched(name, OutsideProbe{target, kSentinel, true}, watch.events(), g_cache_root)) pass(name);
    writeBytes(target, kSentinel);
    QFile::remove(zip);
    resetCache();
}

void testDriveLetterDoesNotEscape() {
    const std::string name = "drive_letter_entry_does_not_escape_cache";
    resetCache();
    const QString zip = sandboxChild("bundles/drive.rdbview");
    writeZip(zip, {{"C:/outside/pwned.bin", kPayload}, {"model.rdb", kModel}});
    const QString outside = sandboxChild("outside/pwned.bin");
    QFile::remove(outside);
    DirWatch watch;
    watch.add(g_sandbox);
    watch.add(sandboxChild("outside"));
    loadBundle(zip);
    bool ok = outsideUntouched(name, OutsideProbe{outside, {}, false}, watch.events(), g_cache_root);
    // A drive-letter name is not absolute on Linux, so the bytes may be stored
    // under the cache. They must not be stored anywhere else.
    if (QFileInfo::exists(QStringLiteral("/outside/pwned.bin")) &&
        readBytes(QStringLiteral("/outside/pwned.bin")) == kPayload) {
        fail(name, "wrote C:/outside/pwned.bin at the filesystem root");
        ok = false;
    }
    if (ok) pass(name);
    QFile::remove(zip);
    QFile::remove(outside);
    resetCache();
}

void testUppercaseExtensionReachesExtract() {
    const std::string name = "uppercase_rdbview_extension_does_not_escape";
    resetCache();
    const QString zip = sandboxChild("bundles/model.RDBVIEW");
    QDir(sandboxChild("outside")).removeRecursively();
    const QString outside = sandboxChild("outside/pwned.bin");
    writeZip(zip, {{"x/keep.txt", QByteArray("keep")},
                   {"x/../../../outside/pwned.bin", kPayload},
                   {"model.rdb", kModel}});
    DirWatch watch;
    watch.add(g_sandbox);
    loadBundle(zip);
    const QStringList events = watch.events();
    if (QFileInfo::exists(outside)) {
        fail(name, "created " + outside.toStdString() + " containing '" +
                       readBytes(outside).left(200).toStdString() + "'");
    } else if (QFileInfo::exists(sandboxChild("outside"))) {
        fail(name, "created directory outside the cache: " + sandboxChild("outside").toStdString());
    } else if (!outsideUntouched(name, OutsideProbe{outside, {}, false}, events, g_cache_root)) {
        // outsideUntouched already recorded the event.
    } else {
        pass(name);
    }
    QFile::remove(zip);
    QFile::remove(outside);
    resetCache();
}

void testRejectDoesNotLeavePartialOutsideWrite() {
    // A file under x/ is extracted first, which creates that directory. The
    // next entry walks back out of it. Creating the outside directory and
    // then refusing the write is still a failure.
    testDotDotDoesNotEscape("x/keep.txt", QByteArray("keep"), "x/../../../outside/pwned.bin",
                            "dotdot_prefix_does_not_escape");
    testDotDotDoesNotEscape("model.rdb/CURRENT", QByteArray("ok"), "model.rdb/../../../outside/pwned.bin",
                            "model_rdb_prefix_dotdot_does_not_escape");
    testDotDotDoesNotEscape("model.ifcview/pad", kSidecar, "model.ifcview/../../../outside/pwned.bin",
                            "ifcview_prefix_dotdot_does_not_escape");
}

void testUnseededDotDotCreatesNoOutsideDirectory() {
    const std::string name = "unseeded_dotdot_creates_no_outside_directory";
    resetCache();
    QDir(sandboxChild("outside")).removeRecursively();
    const QString zip = sandboxChild("bundles/unseeded.rdbview");
    writeZip(zip, {{"x/../../../outside/pwned.bin", kPayload}, {"model.rdb", kModel}});
    DirWatch watch;
    watch.add(g_sandbox);
    loadBundle(zip);
    const bool outside_exists = QFileInfo::exists(sandboxChild("outside"));
    const bool file_exists = QFileInfo::exists(sandboxChild("outside/pwned.bin"));
    if (!outside_exists && !file_exists &&
        outsideUntouched(name, OutsideProbe{sandboxChild("outside/pwned.bin"), {}, false}, watch.events(),
                         g_cache_root)) {
        pass(name);
    } else if (outside_exists || file_exists) {
        fail(name, "extraction created " + sandboxChild("outside").toStdString() +
                       (file_exists ? " and wrote pwned.bin" : " (directory only)"));
    }
    QFile::remove(zip);
    QDir(sandboxChild("outside")).removeRecursively();
    resetCache();
}

void testBareDotDotIsNotAnEscape() {
    // Qt's reader strips a leading "." or "/" one character at a time, so a
    // name that is only dot-dot segments collapses to a file inside the cache.
    // That result must stay inside; it is not a substitute for the prefixed case.
    const std::string name = "leading_dotdot_stays_inside_cache";
    resetCache();
    const QString zip = sandboxChild("bundles/leading-dotdot.rdbview");
    const QString outside = sandboxChild("outside/pwned.bin");
    QFile::remove(outside);
    writeZip(zip, {{"../../../outside/pwned.bin", kPayload}, {"model.rdb", kModel}});
    DirWatch watch;
    watch.add(g_sandbox);
    watch.add(sandboxChild("outside"));
    loadBundle(zip);
    if (outsideUntouched(name, OutsideProbe{outside, {}, false}, watch.events(), g_cache_root)) pass(name);
    QFile::remove(zip);
    QFile::remove(outside);
    resetCache();
}

void testNotAZipWritesNothing() {
    const std::string name = "non_zip_rdbview_writes_nothing";
    resetCache();
    const QString zip = sandboxChild("bundles/garbage.rdbview");
    writeBytes(zip, QByteArray("this is not a zip"));
    const QString outside = sandboxChild("outside/pwned.bin");
    QFile::remove(outside);
    DirWatch watch;
    watch.add(g_sandbox);
    loadBundle(zip);
    if (g_queued_paths.isEmpty() &&
        outsideUntouched(name, OutsideProbe{outside, {}, false}, watch.events(), g_cache_root)) {
        pass(name);
    } else if (!g_queued_paths.isEmpty()) {
        fail(name, "queued a path for a file that is not a zip");
    }
    QFile::remove(zip);
    resetCache();
}

}  // namespace

int main(int argc, char** argv) {
    g_sandbox = QStringLiteral("/tmp/rdbview-zipslip-sandbox-") + QString::number(static_cast<qlonglong>(getpid()));
    QDir(g_sandbox).removeRecursively();
    QDir().mkpath(sandboxChild("bundles"));
    QDir().mkpath(sandboxChild("absolute"));
    ::setenv("TMPDIR", g_sandbox.toLocal8Bit().constData(), 1);
    ::setenv("TEMP", g_sandbox.toLocal8Bit().constData(), 1);
    ::setenv("TMP", g_sandbox.toLocal8Bit().constData(), 1);

    QCoreApplication app(argc, argv);
    g_cache_root = QDir(QStandardPaths::writableLocation(QStandardPaths::TempLocation)).filePath("ifcviewer-rdbview");
    const QString temp = QStandardPaths::writableLocation(QStandardPaths::TempLocation);
    if (QFileInfo(temp).absoluteFilePath() != QFileInfo(g_sandbox).absoluteFilePath()) {
        std::cerr << "FAIL temp location is " << temp.toStdString() << " not " << g_sandbox.toStdString()
                  << " (Qt resolved TempLocation before TMPDIR was set)\n";
        return 2;
    }

    testBenignBundleStaysInside();
    testRejectDoesNotLeavePartialOutsideWrite();
    testUnseededDotDotCreatesNoOutsideDirectory();
    testAbsolutePathDoesNotReplaceSentinel();
    testDriveLetterDoesNotEscape();
    testUppercaseExtensionReachesExtract();
    testBareDotDotIsNotAnEscape();
    testNotAZipWritesNothing();

    resetCache();
    QDir(g_sandbox).removeRecursively();
    if (g_failures != 0) {
        std::cerr << g_failures << " check(s) failed\n";
        return 1;
    }
    std::cerr << "all checks passed\n";
    return 0;
}
