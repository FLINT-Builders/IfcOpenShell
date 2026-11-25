// This file was generated with the assistance of an AI coding tool.
/********************************************************************************
 *                                                                              *
 * This file is part of Bonsai.                                                 *
 *                                                                              *
 * Bonsai is free software: you can redistribute it and/or modify               *
 * it under the terms of the GNU General Public License as published by         *
 * the Free Software Foundation, either version 3.0 of the License, or          *
 * (at your option) any later version.                                          *
 *                                                                              *
 * Bonsai is distributed in the hope that it will be useful,                    *
 * but WITHOUT ANY WARRANTY; without even the implied warranty of               *
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the                 *
 * GNU General Public License for more details.                                 *
 *                                                                              *
 * You should have received a copy of the GNU General Public License            *
 * along with this program. If not, see <http://www.gnu.org/licenses/>.         *
 *                                                                              *
 ********************************************************************************/

#include "Commands.h"

#include "AddModelDialog.h"
#include "SettingsDialog.h"

#include "../../ElementRegistry.h"
#include "../../SessionState.h"
#include "../connectors/PickerDialog.h"
#include "../connectors/Process.h"
#include "../connectors/Registry.h"
#include "../../../ifcviewer/Federation.h"
#include "../../../ifcviewer/SceneLoader.h"
#include "../../../ifcviewer/SidecarBuilder.h"
#include "../../../ifcviewer/ViewportWindow.h"
#include "../../../ifcgeom/serializer.h"
#include "../../../serializers/document_serializer_plugin.h"

#include <QDebug>
#include <QDir>
#include <QDirIterator>
#include <QElapsedTimer>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QInputDialog>
#include <QJsonArray>
#include <QJsonObject>
#include <QJsonValue>
#include <QLineEdit>
#include <QListView>
#include <QMessageBox>
#include <QPointer>
#include <QStandardPaths>
#include <QThread>
#include <QTreeView>
#include <QUuid>

#include <QtCore/private/qzipwriter_p.h>
#include <QCryptographicHash>
#include <QtEndian>

#include <Eigen/Dense>
#ifdef QT_ZLIB_LIB
#include <QtZlib/zlib.h>
#else
#include <zlib.h>
#endif

#include <algorithm>
#include <memory>
#include <vector>

namespace bonsaiviewer::modules::models {

namespace {
bool should_guess_federated_false_origin_ = false;
} // namespace

void armFederatedFalseOriginGuess() {
    should_guess_federated_false_origin_ = true;
}

bool consumeFederatedFalseOriginGuess() {
    const bool armed = should_guess_federated_false_origin_;
    should_guess_federated_false_origin_ = false;
    return armed;
}

} // namespace bonsaiviewer::modules::models

namespace bonsaiviewer::modules::models::commands {

namespace {

QString formatElapsed(qint64 ms) {
    return (ms >= 1000)
        ? QString::number(ms / 1000.0, 'f', 2) + " s"
        : QString::number(ms) + " ms";
}

// Session-scoped scratch root where .rdbview bundles are unzipped for loading.
QString rdbviewCacheRoot() {
    return QDir(QStandardPaths::writableLocation(QStandardPaths::TempLocation))
        .filePath("ifcviewer-rdbview");
}

// Limits on what a .rdbview may expand to, well above real model databases.
// They are checked against the central directory before anything is written,
// and the bytes actually inflated are held to the validated sizes.
constexpr int kRdbviewMaxEntries = 4096;
constexpr quint64 kRdbviewMaxEntryBytes = quint64(1) << 30;
constexpr quint64 kRdbviewMaxTotalBytes = quint64(2) << 30;
constexpr quint64 kRdbviewMaxRatio = 100;
constexpr quint64 kRdbviewRatioFloorBytes = quint64(1) << 20;
constexpr qint64 kRdbviewChunk = 64 * 1024;

struct RdbviewEntry {
    QString target;          // absolute output path inside the extraction dir
    quint16 method = 0;      // 0 stored, 8 deflate
    quint64 compressed_size = 0;
    quint64 size = 0;
    qint64 data_offset = 0;
};

quint16 le16(const char* p) { return qFromLittleEndian<quint16>(p); }
quint32 le32(const char* p) { return qFromLittleEndian<quint32>(p); }

bool readAt(QFile& file, qint64 offset, char* out, qint64 n) {
    return file.seek(offset) && file.read(out, n) == n;
}

// Reads the zip's central directory and checks every regular file entry
// against the limits above. Nothing is written to disk.
bool readRdbviewEntries(QFile& zip, const QString& dir, std::vector<RdbviewEntry>& entries) {
    constexpr qint64 eocd_size = 22;
    const qint64 file_size = zip.size();
    if (file_size < eocd_size) return false;
    const qint64 tail_size = std::min<qint64>(file_size, eocd_size + 0xFFFF);
    const qint64 tail_offset = file_size - tail_size;
    QByteArray tail(tail_size, Qt::Uninitialized);
    if (!readAt(zip, tail_offset, tail.data(), tail_size)) return false;
    qint64 eocd = -1;
    for (qint64 i = tail_size - eocd_size; i >= 0; --i) {
        if (le32(tail.constData() + i) == 0x06054b50) { eocd = i; break; }
    }
    if (eocd < 0) return false;

    const char* e = tail.constData() + eocd;
    const quint16 entry_count = le16(e + 10);
    const qint64 cd_offset = le32(e + 16);
    const qint64 cd_end = cd_offset + le32(e + 12);
    if (le16(e + 4) != 0 || le16(e + 6) != 0 || le16(e + 8) != entry_count) return false;
    if (entry_count > kRdbviewMaxEntries) return false;
    if (cd_end > tail_offset + eocd) return false;

    const QString base = QDir::cleanPath(dir) + '/';
    quint64 total_size = 0;
    quint64 total_compressed = 0;
    qint64 pos = cd_offset;
    for (int i = 0; i < entry_count; ++i) {
        char h[46];
        if (pos + 46 > cd_end || !readAt(zip, pos, h, 46) || le32(h) != 0x02014b50) return false;
        const quint8 host = quint8(h[5]);
        const quint16 flags = le16(h + 8);
        const quint16 method = le16(h + 10);
        const quint64 compressed_size = le32(h + 20);
        const quint64 size = le32(h + 24);
        const quint16 name_len = le16(h + 28);
        const quint32 attributes = le32(h + 38);
        const qint64 local_offset = le32(h + 42);
        pos += 46;
        if (pos + name_len > cd_end) return false;
        QByteArray raw_name(name_len, Qt::Uninitialized);
        if (!readAt(zip, pos, raw_name.data(), name_len)) return false;
        pos += qint64(name_len) + le16(h + 30) + le16(h + 32);
        if (pos > cd_end) return false;

        QString name = (flags & (1 << 11)) ? QString::fromUtf8(raw_name) : QString::fromLocal8Bit(raw_name);
        name = QDir::fromNativeSeparators(name);
        // Same entry typing as QZipReader: Unix hosts by mode, DOS-style hosts by attribute.
        const quint32 type = (attributes >> 16) & 0170000;
        bool is_file = false;
        if (host == 3) is_file = type != 0040000 && type != 0120000;
        else if (host == 0 || host == 6 || host == 11 || host == 14) is_file = !(attributes & 0x10);
        if (!is_file || name.endsWith('/')) continue;  // directories are recreated as needed

        while (name.startsWith('.') || name.startsWith('/')) name.remove(0, 1);
        const QString target = QDir::cleanPath(base + name);
        if (name.isEmpty() || !target.startsWith(base)) return false;

        if (flags & 1) return false;  // encrypted
        if (method != 0 && method != 8) return false;
        if (method == 0 && compressed_size != size) return false;
        if (size > kRdbviewMaxEntryBytes) return false;
        if (size >= kRdbviewRatioFloorBytes && size > kRdbviewMaxRatio * compressed_size) return false;
        total_size += size;
        total_compressed += compressed_size;
        if (total_size > kRdbviewMaxTotalBytes) return false;

        char lh[30];
        if (local_offset + 30 > cd_offset || !readAt(zip, local_offset, lh, 30) || le32(lh) != 0x04034b50) {
            return false;
        }
        RdbviewEntry entry;
        entry.target = target;
        entry.method = method;
        entry.compressed_size = compressed_size;
        entry.size = size;
        entry.data_offset = local_offset + 30 + le16(lh + 26) + le16(lh + 28);
        if (entry.data_offset + qint64(compressed_size) > cd_offset) return false;
        entries.push_back(entry);
    }
    // Many small entries must not add up to a bomb either.
    if (total_size >= kRdbviewRatioFloorBytes && total_size > kRdbviewMaxRatio * total_compressed) return false;
    return true;
}

// Streams one entry into `out`, or nowhere when `out` is null. Fails unless the
// data decodes to exactly the validated size, and never produces more.
bool copyRdbviewEntry(QFile& zip, const RdbviewEntry& entry, QFile* out) {
    if (!zip.seek(entry.data_offset)) return false;
    QByteArray in(kRdbviewChunk, Qt::Uninitialized);
    quint64 remaining_in = entry.compressed_size;

    if (entry.method == 0) {
        while (remaining_in > 0) {
            const qint64 n = qint64(std::min<quint64>(remaining_in, kRdbviewChunk));
            if (zip.read(in.data(), n) != n) return false;
            if (out && out->write(in.constData(), n) != n) return false;
            remaining_in -= quint64(n);
        }
        return true;
    }

    QByteArray buf(kRdbviewChunk, Qt::Uninitialized);
    z_stream stream{};
    if (inflateInit2(&stream, -MAX_WBITS) != Z_OK) return false;
    quint64 produced = 0;
    bool ok = false;
    for (;;) {
        if (stream.avail_in == 0 && remaining_in > 0) {
            const qint64 n = qint64(std::min<quint64>(remaining_in, kRdbviewChunk));
            if (zip.read(in.data(), n) != n) break;
            remaining_in -= quint64(n);
            stream.next_in = reinterpret_cast<Bytef*>(in.data());
            stream.avail_in = uInt(n);
        }
        stream.next_out = reinterpret_cast<Bytef*>(buf.data());
        stream.avail_out = uInt(kRdbviewChunk);
        const int rc = inflate(&stream, Z_NO_FLUSH);
        if (rc != Z_OK && rc != Z_STREAM_END) break;  // Z_BUF_ERROR here means truncated input
        const qint64 n = kRdbviewChunk - qint64(stream.avail_out);
        produced += quint64(n);
        if (produced > entry.size) break;
        if (out && out->write(buf.constData(), n) != n) break;
        if (rc == Z_STREAM_END) {
            ok = produced == entry.size;
            break;
        }
    }
    inflateEnd(&stream);
    return ok;
}

bool writeRdbviewEntries(QFile& zip, const std::vector<RdbviewEntry>& entries) {
    for (const RdbviewEntry& entry : entries) {
        QDir().mkpath(QFileInfo(entry.target).absolutePath());
        QFile f(entry.target);
        if (!f.open(QIODevice::WriteOnly) || !copyRdbviewEntry(zip, entry, &f)) return false;
    }
    return true;
}

// A .rdbview is a zip of `model.rdb/` (the data DB) + `model.ifcview` (geometry
// sidecar). Unzip it into a per-source subdir (hashed from path + mtime + size,
// so a re-open reuses an existing extraction) and return the extracted
// `model.rdb` path — from there it loads exactly like any pure .rdb (geometry
// from the co-extracted sibling .ifcview). Returns empty on failure.
QString extractRdbview(const QString& rdbview_path) {
    const QFileInfo info(rdbview_path);
    const QString key = rdbview_path + '|'
        + QString::number(info.lastModified().toMSecsSinceEpoch()) + '|'
        + QString::number(info.size());
    const QString hash = QString::fromLatin1(
        QCryptographicHash::hash(key.toUtf8(), QCryptographicHash::Sha1).toHex());
    const QString dir = QDir(rdbviewCacheRoot()).filePath(hash);
    const QString rdb = QDir(dir).filePath("model.rdb");

    if (QFileInfo::exists(rdb)) return rdb;  // already extracted this session

    // Everything is validated, including the real inflated size of each
    // deflated entry, before the extraction dir is created. Extraction then
    // reads the same open file against the same validated entry list.
    QFile zip(rdbview_path);
    if (!zip.open(QIODevice::ReadOnly)) return {};
    std::vector<RdbviewEntry> entries;
    if (!readRdbviewEntries(zip, dir, entries)) return {};
    for (const RdbviewEntry& entry : entries) {
        if (entry.method == 8 && !copyRdbviewEntry(zip, entry, nullptr)) return {};
    }

    if (!writeRdbviewEntries(zip, entries)) {
        QDir(dir).removeRecursively();
        return {};
    }
    return QFileInfo::exists(rdb) ? rdb : QString();  // empty if the bundle lacked model.rdb
}

// Map a source path to the path the loader should open: a .rdbview is unzipped
// to its extracted .rdb; everything else passes through unchanged.
QString resolveLoadPath(const QString& path) {
    if (path.endsWith(".rdbview", Qt::CaseInsensitive)) return extractRdbview(path);
    return path;
}

} // namespace

void cleanupRdbviewCache() {
    QDir(rdbviewCacheRoot()).removeRecursively();
}

void toggleVisibility(SessionState& session, ItemKind kind, const QString& id) {
    Federation* federation = session.federation();
    if (kind == ItemKind::Group) {
        const Federation::Group* group = federation->findGroupById(id);
        if (!group) return;
        federation->setGroupVisible(id, !group->visible);
        session.notifyVisibilityChanged();
        session.setStatusMessage("Models", group->visible ? "Group hidden" : "Group shown");
    } else {
        const Federation::Model* model = federation->findById(id);
        if (!model) return;
        federation->setModelVisible(id, !model->visible);
        session.notifyVisibilityChanged();
        session.setStatusMessage("Models", model->visible ? "Model hidden" : "Model shown");
    }
}

void addGroup(SessionState& session, QWidget& host, const QString& parent_group_id) {
    bool ok = false;
    const QString name = QInputDialog::getText(
        &host, "New Group", "Group name:", QLineEdit::Normal, "Group", &ok);
    if (!ok) return;
    const QString trimmed = name.trimmed();
    if (trimmed.isEmpty()) return;

    session.federation()->addGroup(trimmed, parent_group_id);
    session.notifyFederationChanged();
    session.setStatusMessage("Models", "Group added");
}

void renameGroup(SessionState& session, QWidget& host, const QString& group_id) {
    const Federation::Group* group = session.federation()->findGroupById(group_id);
    if (!group) return;

    bool ok = false;
    const QString name = QInputDialog::getText(
        &host, "Rename Group", "Group name:", QLineEdit::Normal, group->display_name, &ok);
    if (!ok) return;
    const QString trimmed = name.trimmed();
    if (trimmed.isEmpty()) return;

    session.federation()->setGroupName(group_id, trimmed);
    session.notifyFederationChanged();
    session.setStatusMessage("Models", "Group renamed");
}

void renameModel(SessionState& session, QWidget& host, const QString& model_id) {
    const Federation::Model* model = session.federation()->findById(model_id);
    if (!model) return;

    bool ok = false;
    const QString name = QInputDialog::getText(
        &host, "Rename Model", "Model name:", QLineEdit::Normal, model->display_name, &ok);
    if (!ok) return;
    const QString trimmed = name.trimmed();
    if (trimmed.isEmpty()) return;

    session.federation()->setModelDisplayName(model_id, trimmed);
    session.notifyFederationChanged();
    session.setStatusMessage("Models", "Model renamed");
}

void moveGroup(SessionState& session, const QString& id, const QString& parent_group_id) {
    session.federation()->setGroupParent(id, parent_group_id);
    session.notifyFederationChanged();
    session.setStatusMessage("Models", parent_group_id.isEmpty() ? "Group moved to root" : "Group moved");
}

void moveModels(SessionState& session, const QStringList& ids, const QString& parent_group_id) {
    for (const auto& id : ids) {
        session.federation()->setModelGroup(id, parent_group_id);
    }
    session.notifyFederationChanged();
    session.setStatusMessage("Models", parent_group_id.isEmpty() ? "Model(s) moved to root" : "Model(s) moved");
}

void removeGroup(SessionState& session, QWidget& host, const QString& group_id) {
    const Federation::Group* group = session.federation()->findGroupById(group_id);
    if (!group) return;

    const auto choice = QMessageBox::question(
        &host, "Remove Group",
        QString("Remove group '%1'? Models inside it will move to the parent.").arg(group->display_name),
        QMessageBox::Yes | QMessageBox::No, QMessageBox::No);
    if (choice != QMessageBox::Yes) return;

    session.federation()->removeGroup(group_id);
    session.notifyFederationChanged();
    session.setStatusMessage("Models", "Group removed");
}

void removeModel(SessionState& session, ViewportWindow& viewport, QWidget& host, const QString& model_id) {
    const Federation::Model* model = session.federation()->findById(model_id);
    const QString label = model ? model->display_name : model_id;
    const auto choice = QMessageBox::question(
        &host, "Remove Model",
        QString("Remove model '%1' from the federation?").arg(label),
        QMessageBox::Yes | QMessageBox::No, QMessageBox::No);
    if (choice != QMessageBox::Yes) return;

    const uint32_t session_model_id = session.sessionModelIdForModelId(model_id);
    if (session_model_id == 0) {
        session.federation()->removeModel(model_id);
        session.notifyFederationChanged();
        session.setStatusMessage("Models", "Model removed");
        return;
    }
    if (session.loader()->isLoadingModel(session_model_id)) return;

    viewport.setSelectedObjectId(0);
    session.setSelectedObjectId(0);
    session.federation()->removeModel(model_id);
    viewport.removeModel(session_model_id);
    session.loader()->removeModel(session_model_id);
    session.elementRegistry()->removeModel(session_model_id);
    session.removeModelMappingByModelId(model_id);
    session.notifySelectionChanged();
    session.notifyModelsChanged();
    session.setStatusMessage("Models", "Model removed");
}

void unloadModel(SessionState& session, ViewportWindow& viewport, const QString& model_id) {
    const uint32_t session_model_id = session.sessionModelIdForModelId(model_id);
    if (session_model_id == 0) return;
    if (session.loader()->isLoadingModel(session_model_id)) return;
    const double freed_mb = double(viewport.modelVramBytes(session_model_id)) / (1024.0 * 1024.0);
    viewport.unloadModel(session_model_id);
    session.notifyModelLoadStateChanged(model_id);
    session.setStatusMessage("Models", QString("Model unloaded (freed %1 MB of GPU memory)")
                                           .arg(freed_mb, 0, 'f', 0));
}

void loadModel(SessionState& session, ViewportWindow& viewport, const QString& model_id) {
    const uint32_t session_model_id = session.sessionModelIdForModelId(model_id);
    if (session_model_id == 0) return;
    if (!viewport.loadModel(session_model_id)) {
        session.setStatusMessage("Models", "Not enough GPU memory to load this model");
        return;
    }
    session.notifyModelLoadStateChanged(model_id);
    session.setStatusMessage("Models", "Model loaded");
}

void viewModels(SessionState& session, ViewportWindow& viewport, const QStringList& model_ids) {
    // Federation ids are the panel's currency; the viewport speaks session
    // model ids. sessionModelIdForModelId returns 0 for a model the viewport
    // has never been given geometry for — skip those rather than framing id 0.
    std::vector<uint32_t> session_model_ids;
    session_model_ids.reserve(std::size_t(model_ids.size()));
    for (const QString& model_id : model_ids) {
        const uint32_t session_model_id = session.sessionModelIdForModelId(model_id);
        if (session_model_id != 0) session_model_ids.push_back(session_model_id);
    }

    if (!viewport.viewModels(session_model_ids)) {
        session.setStatusMessage("Models", "Nothing to view — no loaded geometry");
        return;
    }

    QString label = QString("%1 models").arg(model_ids.size());
    if (model_ids.size() == 1) {
        const Federation::Model* model = session.federation()->findById(model_ids.front());
        label = model ? model->display_name : model_ids.front();
    }
    session.setStatusMessage("Models", QString("Viewing %1").arg(label));
}

namespace detail {

void loadModels(SessionState& session, const QStringList& paths, const QStringList& model_ids) {
    if (paths.isEmpty()) return;

    // The Federation stores the source paths (e.g. a .rdbview); the loader gets
    // the resolved load path (a .rdbview is unzipped at load time to its .rdb).
    // Keep model_ids aligned with the paths that actually resolve.
    QStringList load_paths;
    QStringList load_model_ids;
    for (int i = 0; i < paths.size(); ++i) {
        const QString resolved = resolveLoadPath(paths[i]);
        if (resolved.isEmpty()) {
            session.setStatusMessage("Error",
                QString("Could not open %1").arg(QFileInfo(paths[i]).fileName()));
            continue;
        }
        load_paths.push_back(resolved);
        load_model_ids.push_back(i < model_ids.size() ? model_ids[i] : QString());
    }
    if (load_paths.isEmpty()) return;

    const auto session_model_ids = session.loader()->queueModels(load_paths);
    for (int i = 0; i < load_paths.size()
                 && i < static_cast<int>(session_model_ids.size())
                 && i < load_model_ids.size(); ++i) {
        session.setModelMapping(load_model_ids[i], session_model_ids[i]);
    }
}

} // namespace detail

void addModel(SessionState& session, QWidget& host) {
    AddModelDialog dialog(&host);
    if (dialog.exec() != QDialog::Accepted) return;

    QStringList paths;
    switch (dialog.selectedMode()) {
    case SourceMode::IfcFile: {
        QFileDialog file_dialog(&host, "Add IFC Files");
        file_dialog.setFileMode(QFileDialog::ExistingFiles);
        file_dialog.setNameFilter("IFC Files (*.ifc);;All Files (*)");
        file_dialog.setOption(QFileDialog::DontUseNativeDialog, true);
        if (file_dialog.exec() == QDialog::Accepted) {
            paths = file_dialog.selectedFiles();
        }
        break;
    }
    case SourceMode::IfcDatabase: {
        QFileDialog database_dialog(&host, "Add IFC Databases");
        database_dialog.setFileMode(QFileDialog::Directory);
        database_dialog.setOption(QFileDialog::ShowDirsOnly, true);
        database_dialog.setOption(QFileDialog::DontResolveSymlinks, true);
        database_dialog.setOption(QFileDialog::DontUseNativeDialog, true);
        if (auto* list = database_dialog.findChild<QListView*>("listView")) {
            list->setSelectionMode(QAbstractItemView::ExtendedSelection);
        }
        if (auto* tree = database_dialog.findChild<QTreeView*>()) {
            tree->setSelectionMode(QAbstractItemView::ExtendedSelection);
        }
        if (database_dialog.exec() == QDialog::Accepted) {
            paths = database_dialog.selectedFiles();
        }
        break;
    }
    case SourceMode::GeometryOnly: {
        QFileDialog file_dialog(&host, "Add Geometry");
        file_dialog.setFileMode(QFileDialog::ExistingFiles);
        file_dialog.setNameFilter(
            "Viewer Model (*.ifcview *.rdbview);;IFC Viewer Cache (*.ifcview);;"
            "Geometry Database (*.rdbview);;All Files (*)");
        file_dialog.setOption(QFileDialog::DontUseNativeDialog, true);
        if (file_dialog.exec() == QDialog::Accepted) {
            paths = file_dialog.selectedFiles();
        }
        break;
    }
    case SourceMode::CloudModel:
        addModelFromCloud(session, host);
        return;
    case SourceMode::ConvertToDatabase:
        convertIfcToDatabase(session, host);
        return;
    case SourceMode::ExportGeometryDatabase:
        exportGeometryDatabase(session, host);
        return;
    case SourceMode::None:
        return;
    }

    // Arm the false-origin guess if we're adding into a session with no
    // models yet — the first model that finishes loading will set the
    // origin via ViewportView. Checked here (before federation->addModel)
    // because federation->addModel doesn't yet populate SessionState's
    // model mapping; sessionModelIds() reflects pre-add state at this point.
    if (session.sessionModelIds().isEmpty()) {
        armFederatedFalseOriginGuess();
    }

    QStringList accepted_paths;
    QStringList accepted_model_ids;
    for (const auto& path : paths) {
        const QString model_id =
            session.federation()->addModel(path, QFileInfo(path).fileName());
        if (model_id.isEmpty()) continue;
        accepted_paths << path;
        accepted_model_ids << model_id;
    }
    detail::loadModels(session, accepted_paths, accepted_model_ids);
    session.notifyModelsChanged();
}

void addModelFromCloud(SessionState& session, QWidget& host) {
    auto* registry = session.connectorRegistry();
    const auto& manifests = registry->available();
    if (manifests.empty()) {
        QMessageBox::information(&host, "Add From Cloud",
            "No connectors are installed.");
        return;
    }

    modules::connectors::ConnectorPickerDialog picker(
        manifests, "Add From Cloud",
        "Pick a connector to browse models on.", &host);
    if (picker.exec() != QDialog::Accepted) return;
    const QString connector_id = picker.selectedId();
    if (connector_id.isEmpty()) return;

    auto* proc = registry->get(connector_id);
    if (!proc) {
        QMessageBox::warning(&host, "Add From Cloud",
            QString("Could not launch connector '%1':\n%2")
                .arg(connector_id, registry->lastError()));
        return;
    }

    session.setStatusMessage("Cloud", QString("Browsing %1...").arg(connector_id));

    QPointer<SessionState> sguard(&session);

    proc->call("pull_models_interactive", QJsonValue(),
        [sguard, connector_id](const QJsonValue& result) {
            if (!sguard) return;
            // Arm before the first addCloudModel — sessionModelIds() reflects the
            // session state at the moment the connector returns, which is
            // when the user's "add into empty session" intent applies.
            if (sguard->sessionModelIds().isEmpty()) {
                armFederatedFalseOriginGuess();
            }
            const QJsonArray arr = result.toArray();
            QStringList paths;
            QStringList model_ids;
            int added = 0;
            for (const QJsonValue& value : arr) {
                if (value.isNull() || !value.isObject()) continue;
                const QJsonObject entry = value.toObject();
                const QString display_name = entry.value("display_name").toString();
                const QString path = entry.value("path").toString();
                if (path.isEmpty()) continue;
                const QJsonObject source = entry.value("source").toObject();
                QString src_connector = source.value("connector").toString();
                if (src_connector.isEmpty()) src_connector = connector_id;

                const QString model_id = sguard->federation()->addCloudModel(
                    display_name, src_connector, source);
                if (model_id.isEmpty()) continue;

                const QJsonObject meta = entry.value("metadata").toObject();
                sguard->setCloudMetadata(model_id, meta.toVariantMap());

                paths << path;
                model_ids << model_id;
                ++added;
            }
            if (!paths.isEmpty()) {
                detail::loadModels(*sguard, paths, model_ids);
                sguard->notifyModelsChanged();
            }
            sguard->setStatusMessage("Cloud",
                QString("Added %1 model(s) from %2").arg(added).arg(connector_id));
        },
        [sguard, connector_id](int code, const QString& message) {
            qWarning() << "pull_models_interactive from" << connector_id
                       << "failed:" << code << message;
            if (sguard) {
                sguard->setStatusMessage("Cloud",
                    QString("%1 reported an error (see connector UI)").arg(connector_id));
            }
        });
}

namespace {

// Shared "local path on disk" lookup for the right-click cloud commands:
// the loader keeps the path keyed by session_model_id (set when a file or pull_models
// path was queued). Both local-sourced and resolved cloud-sourced models
// have one; only un-resolved cloud models (where pull_models hasn't
// returned yet) won't.
QString localPathForModel(SessionState& session, const QString& model_id) {
    const uint32_t session_model_id = session.sessionModelIdForModelId(model_id);
    if (session_model_id == 0 || !session.loader()) return {};
    return session.loader()->filePath(session_model_id);
}

} // namespace

void saveModelToCloud(SessionState& session, QWidget& host, const QString& model_id) {
    auto* federation = session.federation();
    const Federation::Model* model = federation->findById(model_id);
    if (!model) return;
    if (model->source_connector == "local") {
        QMessageBox::information(&host, "Save Model To Cloud",
            "This model has no cloud target. Use \"Save As To Cloud\" first.");
        return;
    }
    const QString local_path = localPathForModel(session, model_id);
    if (local_path.isEmpty()) {
        QMessageBox::warning(&host, "Save Model To Cloud",
            "Cannot find a local copy of this model to push.");
        return;
    }
    const QString connector_id = model->source_connector;
    auto* registry = session.connectorRegistry();
    auto* proc = registry->get(connector_id);
    if (!proc) {
        QMessageBox::warning(&host, "Save Model To Cloud",
            QString("Could not launch connector '%1':\n%2")
                .arg(connector_id, registry->lastError()));
        return;
    }

    QJsonObject source = model->source_data;
    source["connector"] = connector_id;
    QJsonObject params;
    params["path"] = local_path;
    params["source"] = source;

    session.setStatusMessage("Cloud",
        QString("Saving %1 to %2...").arg(model->display_name, connector_id));

    QPointer<SessionState> sguard(&session);
    proc->call("push_model", params,
        [sguard, model_id, connector_id](const QJsonValue& result) {
            if (!sguard) return;
            const QJsonObject obj = result.toObject();
            const QJsonObject new_source = obj.value("source").toObject();
            QString new_connector = new_source.value("connector").toString();
            if (new_connector.isEmpty()) new_connector = connector_id;
            sguard->federation()->setModelSource(model_id, new_connector, new_source);
            const QJsonObject meta = obj.value("metadata").toObject();
            sguard->setCloudMetadata(model_id, meta.toVariantMap());
            sguard->setStatusMessage("Cloud",
                QString("Saved to %1").arg(new_connector));
        },
        [sguard, connector_id](int code, const QString& message) {
            qWarning() << "push_model to" << connector_id
                       << "failed:" << code << message;
            if (sguard) {
                sguard->setStatusMessage("Cloud",
                    QString("%1 reported an error (see connector UI)").arg(connector_id));
            }
        });
}

void saveModelAsToCloud(SessionState& session, QWidget& host, const QString& model_id) {
    const Federation::Model* model = session.federation()->findById(model_id);
    if (!model) return;
    const QString local_path = localPathForModel(session, model_id);
    if (local_path.isEmpty()) {
        QMessageBox::warning(&host, "Save Model As To Cloud",
            "Cannot find a local copy of this model to push.");
        return;
    }

    auto* registry = session.connectorRegistry();
    const auto& manifests = registry->available();
    if (manifests.empty()) {
        QMessageBox::information(&host, "Save Model As To Cloud",
            "No connectors are installed.");
        return;
    }

    modules::connectors::ConnectorPickerDialog picker(
        manifests, "Save Model As To Cloud",
        QString("Pick a connector to push '%1' to.").arg(model->display_name),
        &host);
    if (picker.exec() != QDialog::Accepted) return;
    const QString connector_id = picker.selectedId();
    if (connector_id.isEmpty()) return;

    auto* proc = registry->get(connector_id);
    if (!proc) {
        QMessageBox::warning(&host, "Save Model As To Cloud",
            QString("Could not launch connector '%1':\n%2")
                .arg(connector_id, registry->lastError()));
        return;
    }

    QJsonObject params;
    params["path"] = local_path;

    session.setStatusMessage("Cloud",
        QString("Pushing %1 to %2...").arg(model->display_name, connector_id));

    QPointer<SessionState> sguard(&session);
    proc->call("push_model_interactive", params,
        [sguard, model_id, connector_id](const QJsonValue& result) {
            if (!sguard) return;
            const QJsonObject obj = result.toObject();
            const QJsonObject new_source = obj.value("source").toObject();
            QString new_connector = new_source.value("connector").toString();
            if (new_connector.isEmpty()) new_connector = connector_id;
            sguard->federation()->setModelSource(model_id, new_connector, new_source);

            const QString new_name = obj.value("display_name").toString();
            if (!new_name.isEmpty()) {
                sguard->federation()->setModelDisplayName(model_id, new_name);
            }
            const QJsonObject meta = obj.value("metadata").toObject();
            sguard->setCloudMetadata(model_id, meta.toVariantMap());
            sguard->setStatusMessage("Cloud",
                QString("Pushed to %1").arg(new_connector));
        },
        [sguard, connector_id](int code, const QString& message) {
            qWarning() << "push_model_interactive to" << connector_id
                       << "failed:" << code << message;
            if (sguard) {
                sguard->setStatusMessage("Cloud",
                    QString("%1 reported an error (see connector UI)").arg(connector_id));
            }
        });
}

void convertIfcToDatabase(SessionState& session, QWidget& host) {
    QFileDialog input_dialog(&host, "Select IFC File to Convert");
    input_dialog.setFileMode(QFileDialog::ExistingFile);
    input_dialog.setNameFilter("IFC Files (*.ifc);;All Files (*)");
    input_dialog.setOption(QFileDialog::DontUseNativeDialog, true);
    if (input_dialog.exec() != QDialog::Accepted) return;
    const QStringList inputs = input_dialog.selectedFiles();
    if (inputs.isEmpty()) return;
    const QString input_path = inputs.first();

    const QFileInfo input_info(input_path);
    const QString default_output = input_info.absoluteDir().filePath(input_info.completeBaseName() + ".rdb");

    QFileDialog output_dialog(&host, "Save IFC Database As");
    output_dialog.setAcceptMode(QFileDialog::AcceptSave);
    output_dialog.setFileMode(QFileDialog::AnyFile);
    output_dialog.setNameFilter("IFC Database (*.rdb);;All Files (*)");
    output_dialog.setDefaultSuffix("rdb");
    output_dialog.selectFile(default_output);
    output_dialog.setOption(QFileDialog::DontUseNativeDialog, true);
    output_dialog.setOption(QFileDialog::DontConfirmOverwrite, true);
    if (output_dialog.exec() != QDialog::Accepted) return;
    const QStringList outputs = output_dialog.selectedFiles();
    if (outputs.isEmpty()) return;
    QString output_path = outputs.first();
    if (!output_path.endsWith(".rdb", Qt::CaseInsensitive)) {
        output_path += ".rdb";
    }

    const QFileInfo output_info(output_path);
    if (output_info.exists()) {
        const QString message = QString("'%1' already exists. Overwrite?").arg(output_info.fileName());
        if (QMessageBox::question(&host, "Convert IFC to Database", message,
                                  QMessageBox::Yes | QMessageBox::No, QMessageBox::No) != QMessageBox::Yes) {
            return;
        }
    }

    session.beginProgress(QString("Converting %1 to %2…")
                        .arg(QFileInfo(input_path).fileName(),
                             QFileInfo(output_path).fileName()));
    session.setStatusMessage("Converting",
        QString("%1 → %2").arg(QFileInfo(input_path).fileName(), QFileInfo(output_path).fileName()));

    auto timer = std::make_shared<QElapsedTimer>();
    timer->start();
    auto error_message = std::make_shared<QString>();

    QThread* thread = QThread::create([input_path, output_path, error_message]() {
        try {
            ifcopenshell::serializers::document_serializer_context context;
            context.file = nullptr;
            context.input_filename = input_path.toStdString();
            context.output_filename = output_path.toStdString();
            context.stream = true;

            auto& registry = ifcopenshell::serializers::document_serializer_registry_instance();
            const auto* info = registry.find("rdb");
            if (!info) {
                throw ifcopenshell::exception(
                    "No 'rdb' document serializer is registered. The RocksDB serializer plugin may not be installed.");
            }
            if (!info->supports_input_filename) {
                throw ifcopenshell::exception("RDB serializer does not support streaming from an input filename");
            }

            std::shared_ptr<ifcopenshell::geom::serializer> serializer = registry.create("rdb", context);
            serializer->finalize();
        } catch (const std::exception& e) {
            *error_message = QString::fromUtf8(e.what());
        } catch (...) {
            *error_message = "Unknown error during IFC to RDB conversion";
        }
    });

    QObject::connect(thread, &QThread::finished, &host,
            [&session, host_ptr = &host, thread, timer, error_message, input_path, output_path]() {
        const qint64 elapsed = timer->elapsed();

        session.endProgress();
        thread->deleteLater();

        if (!error_message->isEmpty()) {
            session.setStatusMessage("Error", *error_message);
            QMessageBox::warning(host_ptr, "Convert IFC to Database",
                                 QString("Conversion failed:\n%1").arg(*error_message));
            return;
        }

        session.setStatusMessage(
            "Converted",
            QString("%1 → %2 in %3")
                .arg(QFileInfo(input_path).fileName(),
                     QFileInfo(output_path).fileName(),
                     formatElapsed(elapsed)));
        QMessageBox::information(host_ptr, "Convert IFC to Database",
                                 QString("Database written to:\n%1").arg(output_path));
    });

    thread->start();
}

void exportGeometryDatabase(SessionState& session, QWidget& host) {
    QFileDialog input_dialog(&host, "Select IFC File to Export");
    input_dialog.setFileMode(QFileDialog::ExistingFile);
    input_dialog.setNameFilter("IFC Files (*.ifc);;All Files (*)");
    input_dialog.setOption(QFileDialog::DontUseNativeDialog, true);
    if (input_dialog.exec() != QDialog::Accepted) return;
    const QStringList inputs = input_dialog.selectedFiles();
    if (inputs.isEmpty()) return;
    const QString input_path = inputs.first();

    const QFileInfo input_info(input_path);
    const QString default_output = input_info.absoluteDir().filePath(input_info.completeBaseName() + ".rdbview");

    QFileDialog output_dialog(&host, "Save Geometry Database As");
    output_dialog.setAcceptMode(QFileDialog::AcceptSave);
    output_dialog.setFileMode(QFileDialog::AnyFile);
    output_dialog.setNameFilter("Geometry Database (*.rdbview);;All Files (*)");
    output_dialog.setDefaultSuffix("rdbview");
    output_dialog.selectFile(default_output);
    output_dialog.setOption(QFileDialog::DontUseNativeDialog, true);
    if (output_dialog.exec() != QDialog::Accepted) return;
    const QStringList outputs = output_dialog.selectedFiles();
    if (outputs.isEmpty()) return;
    QString output_path = outputs.first();
    if (!output_path.endsWith(".rdbview", Qt::CaseInsensitive)) {
        output_path += ".rdbview";
    }

    session.beginProgress(QString("Exporting %1 to %2…")
                        .arg(QFileInfo(input_path).fileName(),
                             QFileInfo(output_path).fileName()));
    session.setStatusMessage("Exporting",
        QString("%1 → %2").arg(QFileInfo(input_path).fileName(), QFileInfo(output_path).fileName()));

    auto timer = std::make_shared<QElapsedTimer>();
    timer->start();
    auto error_message = std::make_shared<QString>();

    QThread* thread = QThread::create([input_path, output_path, error_message]() {
        // Scratch dir holds the intermediate .ifcview and .rdb directory
        // until they're zipped into the .rdbview.  RAII-like cleanup at the
        // bottom of this lambda; on early exception we leak it (cheap
        // tradeoff to keep the failure log around for the user).
        const QString tmp_root = QDir(QStandardPaths::writableLocation(QStandardPaths::TempLocation))
                                     .filePath(QString("ifcviewer-export-%1")
                                                   .arg(QUuid::createUuid().toString(QUuid::Id128)));
        QDir().mkpath(tmp_root);

        const QString tmp_anchor   = QDir(tmp_root).filePath("model.ifc");
        const QString tmp_sidecar  = QDir(tmp_root).filePath("model.ifcview");
        const QString tmp_rdb_dir  = QDir(tmp_root).filePath("model.rdb");

        try {
            ifcopenshell::serializers::document_serializer_context context;
            context.file = nullptr;
            context.input_filename  = input_path.toStdString();
            context.output_filename = tmp_rdb_dir.toStdString();
            context.stream = true;
            context.skip_supertypes = { "IfcRepresentationItem" };

            auto& registry = ifcopenshell::serializers::document_serializer_registry_instance();
            const auto* info = registry.find("rdb");
            if (!info) {
                throw ifcopenshell::exception(
                    "No 'rdb' document serializer is registered. The RocksDB serializer plugin may not be installed.");
            }
            if (!info->supports_input_filename) {
                throw ifcopenshell::exception("RDB serializer does not support streaming from an input filename");
            }

            std::shared_ptr<ifcopenshell::geom::serializer> serializer = registry.create("rdb", context);
            serializer->finalize();
            serializer.reset();

            SidecarBuilder builder;
            if (!builder.build(input_path, tmp_anchor)) {
                throw ifcopenshell::exception(
                    ("Sidecar build failed: " + builder.lastError()).toStdString());
            }
            if (!QFileInfo::exists(tmp_sidecar)) {
                throw ifcopenshell::exception(
                    ("Sidecar build reported success but " + tmp_sidecar + " is missing").toStdString());
            }

            // Write to a sibling `.tmp` then rename so a partial file never
            // appears at the destination (matters for cloud-sync folders).
            const QString temporary_zip = output_path + ".tmp";
            QFile::remove(temporary_zip);
            {
                QZipWriter writer(temporary_zip);
                if (writer.status() != QZipWriter::NoError) {
                    throw ifcopenshell::exception(
                        ("Failed to open " + temporary_zip + " for writing").toStdString());
                }
                writer.setCompressionPolicy(QZipWriter::AutoCompress);

                {
                    QFile sf(tmp_sidecar);
                    if (!sf.open(QIODevice::ReadOnly)) {
                        throw ifcopenshell::exception(
                            ("Failed to read sidecar " + tmp_sidecar).toStdString());
                    }
                    writer.addFile("model.ifcview", sf.readAll());
                }

                QDirIterator it(tmp_rdb_dir, QDir::Files | QDir::NoDotAndDotDot,
                                QDirIterator::Subdirectories);
                const QDir rdb_root(tmp_rdb_dir);
                while (it.hasNext()) {
                    const QString file_path = it.next();
                    const QString rel = rdb_root.relativeFilePath(file_path);
                    QFile f(file_path);
                    if (!f.open(QIODevice::ReadOnly)) {
                        throw ifcopenshell::exception(
                            ("Failed to read " + file_path + " for zip").toStdString());
                    }
                    writer.addFile(QString("model.rdb/%1").arg(rel), f.readAll());
                }

                writer.close();
                if (writer.status() != QZipWriter::NoError) {
                    throw ifcopenshell::exception(
                        ("Failed to finalize " + temporary_zip).toStdString());
                }
            }

            QFile::remove(output_path);
            if (!QFile::rename(temporary_zip, output_path)) {
                QFile::remove(temporary_zip);
                throw ifcopenshell::exception(
                    ("Failed to move " + temporary_zip + " to " + output_path).toStdString());
            }
        } catch (const std::exception& e) {
            *error_message = QString::fromUtf8(e.what());
        } catch (...) {
            *error_message = "Unknown error during geometry database export";
        }

        QDir(tmp_root).removeRecursively();
    });

    QObject::connect(thread, &QThread::finished, &host,
            [&session, host_ptr = &host, thread, timer, error_message, input_path, output_path]() {
        const qint64 elapsed = timer->elapsed();

        session.endProgress();
        thread->deleteLater();

        if (!error_message->isEmpty()) {
            session.setStatusMessage("Error", *error_message);
            QMessageBox::warning(host_ptr, "Export Geometry Database",
                                 QString("Export failed:\n%1").arg(*error_message));
            return;
        }

        session.setStatusMessage(
            "Exported",
            QString("%1 → %2 in %3")
                .arg(QFileInfo(input_path).fileName(),
                     QFileInfo(output_path).fileName(),
                     formatElapsed(elapsed)));
        QMessageBox::information(host_ptr, "Export Geometry Database",
                                 QString("Geometry database written to:\n%1").arg(output_path));
    });

    thread->start();
}

void openSettings(SessionState& session, QWidget& host) {
    SettingsDialog dialog(&session, &host);
    dialog.exec();
}

} // namespace bonsaiviewer::modules::models::commands
