// This file was generated with the assistance of an AI coding tool.
//
// Spec for .rdbview extraction. These tests fail while extractRdbview inflates
// every zip entry with QZipReader::fileData and writes it under the temp
// cache. They pass once a bundle is refused, with no cache file or directory
// created at any point, when any of the following holds:
//
//   * the archive contains more than 4096 entries
//   * any entry's declared uncompressed size exceeds 1 GiB
//   * the sum of declared uncompressed sizes exceeds 2 GiB
//   * an entry whose declared or actual uncompressed size is at least 1 MiB
//     expands by more than 100x its compressed size
//   * the bytes actually inflated from one entry exceed 1 GiB, or from the
//     whole bundle exceed 2 GiB, even if the central directory understates them
//
// A bundle of a few megabytes of incompressible data must still load, and the
// loader must be given the extracted model.rdb path.
//
// Refusing after creating or deleting a cache file is a failure: the tests
// watch the temp directory while loadModels / openProjectPath run.

#include "../modules/models/Commands.h"
#include "../modules/project/Commands.h"
#include "../SessionState.h"
#include "../../ifcviewer/ViewportWindow.h"

#include <QApplication>
#include <QByteArray>
#include <QCryptographicHash>
#include <QDir>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStandardPaths>
#include <QThread>
#include <QWidget>

#include <zlib.h>

#include <atomic>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

#include <poll.h>
#include <sys/inotify.h>
#include <unistd.h>

QStringList rdbview_test_queued_paths();
void rdbview_test_reset_queued_paths();
void* rdbview_test_queue_thread();

namespace {

int g_failures = 0;

void expect(bool ok, const char* name, const std::string& detail) {
    if (ok) {
        std::cout << "PASS " << name << "\n";
        return;
    }
    std::cout << "FAIL " << name << ": " << detail << "\n";
    ++g_failures;
}

QString cacheRoot() {
    return QDir(QStandardPaths::writableLocation(QStandardPaths::TempLocation))
        .filePath("ifcviewer-rdbview");
}

struct CacheStats {
    qint64 bytes = 0;
    int files = 0;
    int dirs = 0;
};

CacheStats inspectCache() {
    CacheStats stats;
    const QString root = cacheRoot();
    if (!QFileInfo::exists(root)) return stats;
    QDirIterator it(root, QDir::AllEntries | QDir::NoDotAndDotDot | QDir::Hidden,
                    QDirIterator::Subdirectories);
    while (it.hasNext()) {
        it.next();
        const QFileInfo info = it.fileInfo();
        if (info.isDir()) ++stats.dirs;
        else {
            ++stats.files;
            stats.bytes += info.size();
        }
    }
    return stats;
}

// Watches temp for creation of the rdbview cache. A create that is later
// deleted still counts.
class CacheWatch {
public:
    explicit CacheWatch(const QString& temp_root) : root_(temp_root) {
        fd_ = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
        if (fd_ < 0) return;
        root_wd_ = addWatch(temp_root);
        stop_ = false;
        thread_ = std::thread([this] { loop(); });
    }

    ~CacheWatch() {
        stop_.store(true);
        if (thread_.joinable()) thread_.join();
        if (fd_ >= 0) close(fd_);
    }

    int creates() const { return creates_.load(); }

private:
    int addWatch(const QString& path) {
        return inotify_add_watch(fd_, path.toUtf8().constData(),
                                 IN_CREATE | IN_MOVED_TO | IN_ONLYDIR);
    }

    void loop() {
        while (!stop_.load()) {
            pollfd pfd{fd_, POLLIN, 0};
            if (poll(&pfd, 1, 20) <= 0) continue;
            alignas(inotify_event) char buf[4096];
            const ssize_t n = read(fd_, buf, sizeof(buf));
            if (n <= 0) continue;
            for (ssize_t off = 0; off < n;) {
                const auto* event = reinterpret_cast<const inotify_event*>(buf + off);
                if (event->mask & IN_Q_OVERFLOW) creates_.fetch_add(1);
                if ((event->mask & (IN_CREATE | IN_MOVED_TO)) && event->len > 0) {
                    const QString name = QString::fromUtf8(event->name);
                    if (event->wd == root_wd_) {
                        if (name == QStringLiteral("ifcviewer-rdbview")) {
                            creates_.fetch_add(1);
                            if (event->mask & IN_ISDIR) addWatch(root_ + "/ifcviewer-rdbview");
                        }
                    } else {
                        // Nested create under the cache directory.
                        creates_.fetch_add(1);
                        if (event->mask & IN_ISDIR) {
                            addWatch(root_ + "/ifcviewer-rdbview/" + name);
                        }
                    }
                }
                off += sizeof(inotify_event) + event->len;
            }
        }
    }

    QString root_;
    int fd_ = -1;
    int root_wd_ = -1;
    std::atomic<bool> stop_{true};
    std::atomic<int> creates_{0};
    std::thread thread_;
};

void resetCache() {
    bonsaiviewer::modules::models::commands::cleanupRdbviewCache();
    QDir(cacheRoot()).removeRecursively();
    rdbview_test_reset_queued_paths();
}

struct ZipEntry {
    std::string name;
    std::string payload;          // compressed bytes stored in the zip
    uint32_t method = 0;          // 0 stored, 8 deflate
    uint32_t uncompressed_size = 0;
    uint32_t crc = 0;
};

void appendU16(std::string& out, uint32_t value) {
    out.push_back(static_cast<char>(value & 0xff));
    out.push_back(static_cast<char>((value >> 8) & 0xff));
}

void appendU32(std::string& out, uint32_t value) {
    out.push_back(static_cast<char>(value & 0xff));
    out.push_back(static_cast<char>((value >> 8) & 0xff));
    out.push_back(static_cast<char>((value >> 16) & 0xff));
    out.push_back(static_cast<char>((value >> 24) & 0xff));
}

std::string deflateRaw(const std::string& input) {
    z_stream stream{};
    if (deflateInit2(&stream, Z_BEST_COMPRESSION, Z_DEFLATED, -MAX_WBITS, 8, Z_DEFAULT_STRATEGY) != Z_OK) {
        return {};
    }
    stream.next_in = reinterpret_cast<Bytef*>(const_cast<char*>(input.data()));
    stream.avail_in = static_cast<uInt>(input.size());
    std::string out(input.size() + 64, '\0');
    stream.next_out = reinterpret_cast<Bytef*>(out.data());
    stream.avail_out = static_cast<uInt>(out.size());
    const int rc = deflate(&stream, Z_FINISH);
    const size_t produced = stream.total_out;
    deflateEnd(&stream);
    if (rc != Z_STREAM_END) return {};
    out.resize(produced);
    return out;
}

ZipEntry storedEntry(std::string name, std::string bytes) {
    ZipEntry entry;
    entry.name = std::move(name);
    entry.crc = static_cast<uint32_t>(crc32(0, reinterpret_cast<const Bytef*>(bytes.data()),
                                            static_cast<uInt>(bytes.size())));
    entry.uncompressed_size = static_cast<uint32_t>(bytes.size());
    entry.method = 0;
    entry.payload = std::move(bytes);
    return entry;
}

ZipEntry deflatedEntry(std::string name, std::string bytes, uint32_t declared_size) {
    ZipEntry entry;
    entry.name = std::move(name);
    entry.crc = static_cast<uint32_t>(crc32(0, reinterpret_cast<const Bytef*>(bytes.data()),
                                            static_cast<uInt>(bytes.size())));
    entry.uncompressed_size = declared_size;
    entry.method = 8;
    entry.payload = deflateRaw(bytes);
    return entry;
}

std::string buildZip(const std::vector<ZipEntry>& entries) {
    std::string local;
    struct Central {
        uint32_t local_offset;
        ZipEntry entry;
    };
    std::vector<Central> centrals;
    for (const ZipEntry& entry : entries) {
        Central central;
        central.local_offset = static_cast<uint32_t>(local.size());
        central.entry = entry;
        centrals.push_back(central);

        appendU32(local, 0x04034b50);
        appendU16(local, 20);                  // version needed
        appendU16(local, 1u << 11);            // UTF-8 names
        appendU16(local, entry.method);
        appendU16(local, 0);                   // time
        appendU16(local, 0);                   // date
        appendU32(local, entry.crc);
        appendU32(local, static_cast<uint32_t>(entry.payload.size()));
        appendU32(local, entry.uncompressed_size);
        appendU16(local, static_cast<uint32_t>(entry.name.size()));
        appendU16(local, 0);                   // extra
        local.append(entry.name);
        local.append(entry.payload);
    }

    const uint32_t dir_offset = static_cast<uint32_t>(local.size());
    std::string dir;
    for (const Central& central : centrals) {
        const ZipEntry& entry = central.entry;
        appendU32(dir, 0x02014b50);
        appendU16(dir, 3u << 8);               // version made by, Unix
        appendU16(dir, 20);
        appendU16(dir, 1u << 11);
        appendU16(dir, entry.method);
        appendU16(dir, 0);
        appendU16(dir, 0);
        appendU32(dir, entry.crc);
        appendU32(dir, static_cast<uint32_t>(entry.payload.size()));
        appendU32(dir, entry.uncompressed_size);
        appendU16(dir, static_cast<uint32_t>(entry.name.size()));
        appendU16(dir, 0);                     // extra
        appendU16(dir, 0);                     // comment
        appendU16(dir, 0);                     // disk
        appendU16(dir, 0);                     // internal attr
        // Unix regular file 0100644 in the high 16 bits, so QZipReader marks isFile.
        appendU32(dir, 0100644u << 16);
        appendU32(dir, central.local_offset);
        dir.append(entry.name);
    }

    std::string eocd;
    appendU32(eocd, 0x06054b50);
    appendU16(eocd, 0);
    appendU16(eocd, 0);
    appendU16(eocd, static_cast<uint32_t>(entries.size()));
    appendU16(eocd, static_cast<uint32_t>(entries.size()));
    appendU32(eocd, static_cast<uint32_t>(dir.size()));
    appendU32(eocd, dir_offset);
    appendU16(eocd, 0);

    return local + dir + eocd;
}

QString writeBytes(const QString& path, const std::string& bytes) {
    QDir().mkpath(QFileInfo(path).absolutePath());
    QFile file(path);
    file.open(QIODevice::WriteOnly | QIODevice::Truncate);
    file.write(bytes.data(), static_cast<qint64>(bytes.size()));
    file.close();
    return path;
}

std::string randomBytes(size_t n, uint32_t seed) {
    std::string out(n, '\0');
    uint32_t state = seed;
    for (size_t i = 0; i < n; ++i) {
        state = state * 1664525u + 1013904223u;
        out[i] = static_cast<char>(state >> 24);
    }
    return out;
}

QString writeBundle(const QString& path, const std::vector<ZipEntry>& entries) {
    return writeBytes(path, buildZip(entries));
}

void loadBundle(bonsaiviewer::SessionState& session, const QString& path, const QString& model_id) {
    rdbview_test_reset_queued_paths();
    bonsaiviewer::modules::models::commands::detail::loadModels(
        session, QStringList{path}, QStringList{model_id});
}

// A realistic small database: incompressible bytes, two entries, ratio 1.
QString writeBenign(const QString& path) {
    std::vector<ZipEntry> entries;
    entries.push_back(storedEntry("model.rdb/CURRENT", randomBytes(1024, 1)));
    entries.push_back(storedEntry("model.ifcview", randomBytes(2 * 1024 * 1024, 2)));
    return writeBundle(path, entries);
}

// 8 MiB of zeros deflates to a few kilobytes. Honest sizes.
QString writeRatioBomb(const QString& path) {
    const std::string zeros(8 * 1024 * 1024, '\0');
    std::vector<ZipEntry> entries;
    entries.push_back(storedEntry("model.rdb/CURRENT", "CURRENT\n"));
    entries.push_back(deflatedEntry("model.rdb/bomb.sst", zeros, static_cast<uint32_t>(zeros.size())));
    return writeBundle(path, entries);
}

// Central-directory uncompressed size is 2.5 GiB. The inflater's actual
// output is a few bytes. 0xA0000000 does not fit in the signed 32-bit size
// QZipReader::fileData uses, so the current code still inflates the real
// payload instead of allocating 2.5 GiB.
QString writeDeclaredSizeBomb(const QString& path) {
    const std::string bytes(64, 'A');
    std::vector<ZipEntry> entries;
    entries.push_back(storedEntry("model.rdb/CURRENT", "CURRENT\n"));
    entries.push_back(deflatedEntry("model.rdb/bomb.sst", bytes, 0xA0000000u));
    return writeBundle(path, entries);
}

// Declared uncompressed size is 32 bytes. The deflate stream is 8 MiB of zeros.
QString writeUnderstatedBomb(const QString& path) {
    const std::string zeros(8 * 1024 * 1024, '\0');
    std::vector<ZipEntry> entries;
    entries.push_back(storedEntry("model.rdb/CURRENT", "CURRENT\n"));
    entries.push_back(deflatedEntry("model.rdb/bomb.sst", zeros, 32));
    return writeBundle(path, entries);
}

// Three entries whose declared sizes sum past 2 GiB. Each declared size is
// 0xA0000000 so fileData does not allocate that much up front.
QString writeSummedSizeBomb(const QString& path) {
    const std::string bytes(32, 'B');
    std::vector<ZipEntry> entries;
    entries.push_back(storedEntry("model.rdb/CURRENT", "CURRENT\n"));
    entries.push_back(deflatedEntry("model.rdb/a.sst", bytes, 0xA0000000u));
    entries.push_back(deflatedEntry("model.rdb/b.sst", bytes, 0xA0000000u));
    entries.push_back(deflatedEntry("model.rdb/c.sst", bytes, 0xA0000000u));
    return writeBundle(path, entries);
}

QString writeEntryCountBomb(const QString& path) {
    std::vector<ZipEntry> entries;
    entries.push_back(storedEntry("model.rdb/CURRENT", "CURRENT\n"));
    for (int i = 0; i < 4096; ++i) {
        entries.push_back(storedEntry("model.rdb/f" + std::to_string(i), "x"));
    }
    return writeBundle(path, entries);
}

struct BombResult {
    CacheStats during;
    CacheStats after;
    int creates = 0;
    QStringList queued;
    QString status_mode;
    QString status_detail;
};

BombResult runLoad(bonsaiviewer::SessionState& session, const QString& bundle, const QString& model_id) {
    resetCache();
    const QString temp = QStandardPaths::writableLocation(QStandardPaths::TempLocation);
    CacheWatch watch(temp);
    loadBundle(session, bundle, model_id);
    // A worker that starts after loadModels returns still has to be caught.
    QThread::msleep(200);
    BombResult result;
    result.creates = watch.creates();
    result.after = inspectCache();
    result.queued = rdbview_test_queued_paths();
    result.status_mode = session.statusMode();
    result.status_detail = session.statusDetail();
    return result;
}

void expectRefused(const char* name, const BombResult& result) {
    const bool clean = result.creates == 0 && result.after.files == 0 && result.after.dirs == 0
        && result.after.bytes == 0 && !QFileInfo::exists(cacheRoot()) && result.queued.isEmpty();
    std::string detail = "creates=" + std::to_string(result.creates)
        + " files=" + std::to_string(result.after.files)
        + " dirs=" + std::to_string(result.after.dirs)
        + " bytes=" + std::to_string(result.after.bytes)
        + " queued=" + std::to_string(result.queued.size())
        + " status=" + result.status_mode.toStdString() + " " + result.status_detail.toStdString();
    if (!result.queued.isEmpty()) detail += " first=" + result.queued.front().toStdString();
    expect(clean, name, detail);
}

void test_benign_bundle_is_queued(bonsaiviewer::SessionState& session, const QString& dir) {
    resetCache();
    const QString path = writeBenign(dir + "/benign.rdbview");
    loadBundle(session, path, "benign");
    const QStringList queued = rdbview_test_queued_paths();
    const CacheStats stats = inspectCache();
    const bool queued_rdb = queued.size() == 1 && queued.front().endsWith("/model.rdb");
    const bool extracted = stats.bytes >= (2 * 1024 * 1024) && stats.bytes < (3 * 1024 * 1024);
    const bool same_thread = rdbview_test_queue_thread() == QThread::currentThreadId();
    expect(queued_rdb && extracted && same_thread && QFileInfo(queued.value(0)).exists(),
           "test_benign_bundle_is_queued",
           "queued=" + std::to_string(queued.size())
               + " bytes=" + std::to_string(stats.bytes)
               + " same_thread=" + std::to_string(same_thread));
}

void test_plain_ifc_is_not_unzipped(bonsaiviewer::SessionState& session, const QString& dir) {
    resetCache();
    const QString path = writeBytes(dir + "/plain.ifc", "ISO-10303-21;");
    CacheWatch watch(QStandardPaths::writableLocation(QStandardPaths::TempLocation));
    loadBundle(session, path, "ifc");
    QThread::msleep(50);
    const QStringList queued = rdbview_test_queued_paths();
    const bool ok = queued.size() == 1 && queued.front() == path && watch.creates() == 0
        && !QFileInfo::exists(cacheRoot());
    expect(ok, "test_plain_ifc_is_not_unzipped",
           "queued=" + (queued.isEmpty() ? std::string{} : queued.front().toStdString())
               + " creates=" + std::to_string(watch.creates()));
}

void test_ratio_bomb(bonsaiviewer::SessionState& session, const QString& dir) {
    const QString path = writeRatioBomb(dir + "/ratio.rdbview");
    expectRefused("test_ratio_bomb", runLoad(session, path, "ratio"));
}

void test_declared_size_bomb(bonsaiviewer::SessionState& session, const QString& dir) {
    const QString path = writeDeclaredSizeBomb(dir + "/declared.rdbview");
    expectRefused("test_declared_size_bomb", runLoad(session, path, "declared"));
}

void test_understated_size_bomb(bonsaiviewer::SessionState& session, const QString& dir) {
    const QString path = writeUnderstatedBomb(dir + "/under.rdbview");
    expectRefused("test_understated_size_bomb", runLoad(session, path, "under"));
}

void test_summed_declared_size_bomb(bonsaiviewer::SessionState& session, const QString& dir) {
    const QString path = writeSummedSizeBomb(dir + "/sum.rdbview");
    expectRefused("test_summed_declared_size_bomb", runLoad(session, path, "sum"));
}

void test_entry_count_bomb(bonsaiviewer::SessionState& session, const QString& dir) {
    const QString path = writeEntryCountBomb(dir + "/count.rdbview");
    expectRefused("test_entry_count_bomb", runLoad(session, path, "count"));
}

void test_suffix_case(bonsaiviewer::SessionState& session, const QString& dir) {
    const QString path = writeRatioBomb(dir + "/Case.RDBVIEW");
    expectRefused("test_suffix_case", runLoad(session, path, "case"));
}

void test_cloud_style_path(bonsaiviewer::SessionState& session, const QString& dir) {
    // addModelFromCloud and resolveCloudModels pass the connector's local
    // path straight into detail::loadModels. Same extraction.
    const QString path = writeRatioBomb(dir + "/cloud.rdbview");
    expectRefused("test_cloud_style_path", runLoad(session, path, "cloud-model"));
}

void test_mixed_list_skips_bomb(bonsaiviewer::SessionState& session, const QString& dir) {
    resetCache();
    const QString benign = writeBenign(dir + "/mixed-ok.rdbview");
    const QString bomb = writeRatioBomb(dir + "/mixed-bomb.rdbview");
    const QString temp = QStandardPaths::writableLocation(QStandardPaths::TempLocation);
    CacheWatch watch(temp);
    rdbview_test_reset_queued_paths();
    bonsaiviewer::modules::models::commands::detail::loadModels(
        session,
        QStringList{bomb, benign},
        QStringList{"bomb", "ok"});
    QThread::msleep(200);
    const CacheStats stats = inspectCache();
    const QStringList queued = rdbview_test_queued_paths();
    // The bomb is 8 MiB. The benign bundle is just over 2 MiB. Anything past
    // 3 MiB means the bomb was written. The bomb must also not be queued.
    bool bomb_queued = false;
    for (const QString& path : queued) {
        if (path.contains("mixed-bomb")) bomb_queued = true;
    }
    const bool ok = stats.bytes < (3 * 1024 * 1024) && !bomb_queued && queued.size() == 1;
    expect(ok, "test_mixed_list_skips_bomb",
           "bytes=" + std::to_string(stats.bytes)
               + " queued=" + std::to_string(queued.size())
               + " creates=" + std::to_string(watch.creates()));
}

void test_open_project_path(bonsaiviewer::SessionState& session, QWidget& host, ViewportWindow& viewport,
                            const QString& dir) {
    resetCache();
    const QString bundle = writeRatioBomb(dir + "/proj/model.rdbview");
    QJsonObject source;
    source.insert("connector", "local");
    source.insert("path", "model.rdbview");
    QJsonObject model;
    model.insert("id", "m1");
    model.insert("display_name", "model.rdbview");
    model.insert("source", source);
    QJsonArray models;
    models.append(model);
    QJsonObject root;
    root.insert("schema", "ifcfed/1");
    root.insert("name", "bomb");
    root.insert("models", models);
    const QString project = writeBytes(
        dir + "/proj/project.ifcfed",
        QJsonDocument(root).toJson(QJsonDocument::Compact).toStdString());

    const QString temp = QStandardPaths::writableLocation(QStandardPaths::TempLocation);
    CacheWatch watch(temp);
    rdbview_test_reset_queued_paths();
    const bool opened = bonsaiviewer::modules::project::commands::openProjectPath(
        session, host, viewport, project);
    QThread::msleep(200);
    const CacheStats stats = inspectCache();
    const bool clean = watch.creates() == 0 && stats.files == 0 && stats.bytes == 0
        && !QFileInfo::exists(cacheRoot()) && rdbview_test_queued_paths().isEmpty();
    expect(opened && clean, "test_open_project_path",
           "opened=" + std::to_string(opened)
               + " creates=" + std::to_string(watch.creates())
               + " bytes=" + std::to_string(stats.bytes)
               + " queued=" + std::to_string(rdbview_test_queued_paths().size()));
}

} // namespace

int main(int argc, char** argv) {
    const QString temp = QDir::temp().filePath("rdbview-bomb-tests");
    QDir().mkpath(temp);
    qputenv("TMPDIR", temp.toUtf8());
    qputenv("TMP", temp.toUtf8());
    qputenv("TEMP", temp.toUtf8());

    QApplication app(argc, argv);
    const QString resolved = QStandardPaths::writableLocation(QStandardPaths::TempLocation);
    if (!resolved.startsWith(QFileInfo(temp).canonicalFilePath())) {
        std::cerr << "temp location " << resolved.toStdString()
                  << " is outside " << temp.toStdString() << "\n";
        return 2;
    }

    ViewportWindow viewport;
    QWidget host;
    bonsaiviewer::SessionState session;
    session.createLoader(&viewport);

    const QString dir = temp + "/fixtures";
    QDir().mkpath(dir);

    test_benign_bundle_is_queued(session, dir);
    test_plain_ifc_is_not_unzipped(session, dir);
    test_ratio_bomb(session, dir);
    test_declared_size_bomb(session, dir);
    test_understated_size_bomb(session, dir);
    test_summed_declared_size_bomb(session, dir);
    test_entry_count_bomb(session, dir);
    test_suffix_case(session, dir);
    test_cloud_style_path(session, dir);
    test_mixed_list_skips_bomb(session, dir);
    test_open_project_path(session, host, viewport, dir);

    bonsaiviewer::modules::models::commands::cleanupRdbviewCache();
    std::cout << (g_failures == 0 ? "ALL PASSED\n" : "FAILURES " + std::to_string(g_failures) + "\n");
    return g_failures == 0 ? 0 : 1;
}
