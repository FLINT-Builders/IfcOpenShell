/* This file was generated with the assistance of an AI coding tool. */
/********************************************************************************
 *                                                                              *
 * This file is part of IfcOpenShell.                                           *
 *                                                                              *
 * IfcOpenShell is free software: you can redistribute it and/or modify         *
 * it under the terms of the Lesser GNU General Public License as published by  *
 * the Free Software Foundation, either version 3.0 of the License, or          *
 * (at your option) any later version.                                          *
 *                                                                              *
 * IfcOpenShell is distributed in the hope that it will be useful,              *
 * but WITHOUT ANY WARRANTY; without even the implied warranty of               *
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the                 *
 * Lesser GNU General Public License for more details.                          *
 *                                                                              *
 * You should have received a copy of the Lesser GNU General Public License     *
 * along with this program. If not, see <http://www.gnu.org/licenses/>.         *
 *                                                                              *
 ********************************************************************************/

// Federation files must not cause the viewer to touch a network path.
//
// Federation::load (src/ifcviewer/Federation.cpp) copies source.path through
// resolvePath, which returns an absolute path after QDir::cleanPath and does
// not reject UNC, device, or extended-length paths. openProjectAt
// (src/bonsaiviewer/modules/project/Commands.cpp) then calls
// QFileInfo::exists on every local source_path and, when that returns true,
// hands the same path to loadModels. On the Windows build, Qt 6.8.3
// implements that exists() call as GetFileAttributesEx on the native path
// (qfilesystemengine_win.cpp) and treats ERROR_LOGON_FAILURE as "not found".
//
// These tests fail while a federation-supplied network path is still stored
// or touched. They pass once such paths are dropped before any existence
// check or open. Absolute paths on a local drive, which the federation
// format already round-trips, must keep loading.
//
// The UI entry points that share this load-then-probe sequence are
// openProject, openProjectPath (Open Recent), openCloudProject, and
// syncCloudProject. They are not linked here: each one calls openProjectAt,
// and openProjectAt's probe is the loop replayed below against the models
// Federation::load actually stored. Command-line and file-association open
// are not tested because main.cpp does not pass a positional path to
// openProjectPath. addModel is not tested: that path comes from a file
// dialog the user confirmed, not from the federation document.

#include "Federation.h"

#include <catch2/catch_test_macros.hpp>

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>

#include <cstdlib>
#include <string>
#include <vector>

#if defined(__linux__)
#include <fcntl.h>
#include <limits.h>
#include <unistd.h>
#endif

namespace {

#if defined(__linux__)
// Reload this process with the filesystem probe before any test calls Qt.
// The probe records stat/open paths so a fix that looks a network path up
// and then refuses still fails.
struct InstallFilesystemProbe {
    InstallFilesystemProbe() {
        if (std::getenv("FEDERATION_PROBE_ACTIVE") != nullptr) return;
        char exe[PATH_MAX];
        const ssize_t n = ::readlink("/proc/self/exe", exe, sizeof(exe) - 1);
        if (n <= 0) return;
        exe[n] = '\0';
        std::string so(exe);
        const auto slash = so.find_last_of('/');
        if (slash == std::string::npos) return;
        so.replace(slash + 1, std::string::npos, "libfederation_fs_probe.so");
        if (::access(so.c_str(), R_OK) != 0) return;

        std::vector<std::string> args;
        const int cmd = ::open("/proc/self/cmdline", O_RDONLY);
        if (cmd < 0) return;
        std::string raw;
        char buf[512];
        ssize_t got = 0;
        while ((got = ::read(cmd, buf, sizeof(buf))) > 0) raw.append(buf, static_cast<size_t>(got));
        ::close(cmd);
        for (size_t i = 0; i < raw.size();) {
            const std::string arg(raw.c_str() + i);
            if (!arg.empty()) args.push_back(arg);
            i += arg.size() + 1;
        }
        if (args.empty()) return;

        std::vector<char*> argv;
        argv.reserve(args.size() + 1);
        for (auto& arg : args) argv.push_back(arg.data());
        argv.push_back(nullptr);

        ::setenv("LD_PRELOAD", so.c_str(), 1);
        ::setenv("FEDERATION_PROBE_ACTIVE", "1", 1);
        if (std::getenv("FEDERATION_PROBE_LOG") == nullptr) {
            ::setenv("FEDERATION_PROBE_LOG", "/tmp/ifcos-federation-network-probe.log", 1);
        }
        ::execv(exe, argv.data());
    }
};

const InstallFilesystemProbe kInstallFilesystemProbe;
#endif

void ensureQApp() {
    if (QCoreApplication::instance()) return;
    static int argc = 1;
    static char arg0[] = "test_federation_network_paths";
    static char* argv[] = { arg0, nullptr };
    new QCoreApplication(argc, argv);
}

// Windows fromNativeSeparators + QFileSystemEntry::removeUncOrLongPathPrefix
// as implemented in Qt 6.8.3 (qdir.cpp, qfilesystementry.cpp). Used only to
// decide which raw strings the Windows build will treat as UNC or device
// paths. It does not replace Federation::load.
QString windowsInternalPath(QString path) {
    constexpr qsizetype minPrefixSize = 4;
    if (path.size() >= minPrefixSize) {
        const QChar slash = path[0];
        if (slash == u'\\' || slash == u'/') {
            const auto data = path.data();
            if (data[2] == u'?' && data[3] == slash && (data[1] == slash || data[1] == u'?')) {
                path = path.sliced(minPrefixSize);
                if (path.size() >= 4) {
                    auto rest = path.data();
                    if (rest[0] == u'U' && rest[1] == u'N' && rest[2] == u'C' && rest[3] == slash) {
                        rest[2] = slash;
                        path = path.sliced(2);
                    }
                }
            }
        }
    }
    return path.replace(u'\\', u'/');
}

// True when Qt 6.8.3 on Windows reports the path absolute because it is a
// UNC path (QFileSystemEntry::isAbsolute: two leading slashes) or a Win32
// device / extended path that normalises to one.
bool windowsQtTreatsAsNetworkPath(const QString& raw) {
    const QString internal = windowsInternalPath(raw);
    return internal.size() >= 2 && internal[0] == u'/' && internal[1] == u'/';
}

QString writeFederation(const QString& fed_path, const QString& local_relative,
                        const std::vector<QString>& network_paths) {
    QJsonArray models;
    {
        QJsonObject source;
        source["connector"] = "local";
        source["path"] = local_relative;
        QJsonObject model;
        model["id"] = "local-ok";
        model["display_name"] = "local.ifc";
        model["source"] = source;
        models.append(model);
    }
    int n = 0;
    for (const QString& network_path : network_paths) {
        QJsonObject source;
        source["connector"] = "local";
        source["path"] = network_path;
        QJsonObject model;
        model["id"] = QString("net-%1").arg(n++);
        model["source"] = source;
        models.append(model);
    }
    QJsonObject root;
    root["schema"] = "ifcfed/1";
    root["name"] = "network-path";
    root["models"] = models;
    QFile out(fed_path);
    REQUIRE(out.open(QIODevice::WriteOnly));
    out.write(QJsonDocument(root).toJson(QJsonDocument::Compact));
    out.close();
    return fed_path;
}

QString probeLogPath() {
    const QByteArray env = qgetenv("FEDERATION_PROBE_LOG");
    return QString::fromUtf8(env);
}

void truncateProbeLog() {
    const QString path = probeLogPath();
    REQUIRE_FALSE(path.isEmpty());
    QFile log(path);
    REQUIRE(log.open(QIODevice::WriteOnly | QIODevice::Truncate));
    log.close();
}

QString readProbeLog() {
    QFile log(probeLogPath());
    REQUIRE(log.open(QIODevice::ReadOnly));
    return QString::fromUtf8(log.readAll());
}

// Same decision as openProjectAt (Commands.cpp): every local source_path is
// passed to QFileInfo::exists, and only paths that exist are opened.
// A path Qt on Windows would already treat as UNC or a device path is not
// touched here; retaining it is a failure on its own.
struct ProbeResult {
    QStringList exists_paths;
    QStringList opened_paths;
    QStringList retained_network_paths;
};

ProbeResult probeLikeOpenProjectAt(const Federation& fed) {
    ProbeResult result;
    for (const auto& model : fed.models()) {
        if (model.source_connector != "local") continue;
        if (windowsQtTreatsAsNetworkPath(model.source_path)) {
            result.retained_network_paths << model.source_path;
            continue;
        }
        result.exists_paths << model.source_path;
        if (!QFileInfo::exists(model.source_path)) continue;
        result.opened_paths << model.source_path;
        QFile file(model.source_path);
        if (file.open(QIODevice::ReadOnly)) file.close();
    }
    return result;
}

const char* kHost = "attacker.example";

} // namespace

TEST_CASE("Windows Qt treats federation UNC and device paths as network paths",
          "[federation][network-path]") {
    const char* samples[] = {
        "//attacker.example/share/model.ifc",
        "\\\\attacker.example\\share\\model.ifc",
        "\\\\?\\UNC\\attacker.example\\share\\model.ifc",
        "//?/UNC/attacker.example/share/model.ifc",
        "\\\\.\\UNC\\attacker.example\\share\\model.ifc",
        "//attacker.example/share/../share/model.ifc",
    };
    for (const char* sample : samples) {
        CAPTURE(sample);
        REQUIRE(windowsQtTreatsAsNetworkPath(QString::fromUtf8(sample)));
    }
    REQUIRE_FALSE(windowsQtTreatsAsNetworkPath("/tmp/local-model.ifc"));
    REQUIRE_FALSE(windowsQtTreatsAsNetworkPath("models/local.ifc"));
    REQUIRE_FALSE(windowsQtTreatsAsNetworkPath("file://attacker.example/share/model.ifc"));
}

TEST_CASE("federation load does not retain or probe network model paths",
          "[federation][network-path]") {
    ensureQApp();
#ifdef __linux__
    REQUIRE(qEnvironmentVariableIsSet("FEDERATION_PROBE_ACTIVE"));
#endif

    QTemporaryDir tmp;
    REQUIRE(tmp.isValid());
    const QString local_abs = tmp.filePath("models/local.ifc");
    {
        QFileInfo info(local_abs);
        REQUIRE(QDir().mkpath(info.absolutePath()));
        QFile local(local_abs);
        REQUIRE(local.open(QIODevice::WriteOnly));
        local.write("ISO-10303-21;");
        local.close();
    }

    const std::vector<QString> network_paths = {
        QString::fromUtf8("//attacker.example/share/model.ifc"),
        QString::fromUtf8("\\\\attacker.example\\share\\model.ifc"),
        QString::fromUtf8("\\\\?\\UNC\\attacker.example\\share\\model.ifc"),
        QString::fromUtf8("//?/UNC/attacker.example/share/model.ifc"),
        QString::fromUtf8("\\\\.\\UNC\\attacker.example\\share\\model.ifc"),
        QString::fromUtf8("//attacker.example/share/../share/model.ifc"),
    };
    for (const QString& network_path : network_paths) {
        REQUIRE(windowsQtTreatsAsNetworkPath(network_path));

        const QString fed_path = tmp.filePath("project.ifcfed");
        writeFederation(fed_path, "models/local.ifc", { network_path });

#ifdef __linux__
        truncateProbeLog();
#endif
        Federation fed;
        QStringList warnings;
        QString err;
        const bool loaded = fed.load(fed_path, &warnings, &err);
        const ProbeResult probed = loaded ? probeLikeOpenProjectAt(fed) : ProbeResult{};
#ifdef __linux__
        const QString trace = readProbeLog();
#else
        const QString trace;
#endif

        INFO("network path " << network_path.toStdString());
        INFO("load error " << err.toStdString());
        INFO("warnings " << warnings.join(" | ").toStdString());
        if (loaded) {
            QStringList stored;
            for (const auto& model : fed.models()) stored << model.source_path;
            INFO("stored " << stored.join(" | ").toStdString());
        }
        INFO("probe log\n" << trace.toStdString());

        // A network source is dropped. The local model is still loaded.
        CHECK(loaded);
        CHECK(fed.models().size() == 1);
        if (fed.models().size() == 1) {
            CHECK(fed.models()[0].id == "local-ok");
            CHECK(fed.models()[0].source_path == local_abs);
        }
        CHECK(probed.retained_network_paths.isEmpty());
        CHECK(probed.opened_paths.size() == 1);
        if (probed.opened_paths.size() == 1) {
            CHECK(probed.opened_paths[0] == local_abs);
        }

        // exists() / open during load or the openProjectAt probe must not
        // name the attacker host. That includes a check that stats the path
        // and then refuses to parse it. On Windows the retained UNC path is
        // rejected above without calling exists(), so this log is Linux-only.
#ifdef __linux__
        CHECK_FALSE(trace.contains(QString::fromUtf8(kHost)));
        CHECK(trace.contains(local_abs));
#else
        Q_UNUSED(trace);
#endif
    }
}

TEST_CASE("federation load still opens an absolute local model path",
          "[federation][network-path]") {
    ensureQApp();
    QTemporaryDir tmp;
    REQUIRE(tmp.isValid());
    const QString fed_dir = tmp.filePath("fed");
    const QString outside = tmp.filePath("elsewhere/outside.ifc");
    REQUIRE(QDir().mkpath(fed_dir));
    {
        QFileInfo info(outside);
        REQUIRE(QDir().mkpath(info.absolutePath()));
        QFile file(outside);
        REQUIRE(file.open(QIODevice::WriteOnly));
        file.write("ISO-10303-21;");
        file.close();
    }

    QJsonObject source;
    source["connector"] = "local";
    source["path"] = outside;
    QJsonObject model;
    model["id"] = "abs-local";
    model["display_name"] = "outside.ifc";
    model["source"] = source;
    QJsonArray models;
    models.append(model);
    QJsonObject root;
    root["schema"] = "ifcfed/1";
    root["models"] = models;
    const QString fed_path = fed_dir + "/project.ifcfed";
    QFile out(fed_path);
    REQUIRE(out.open(QIODevice::WriteOnly));
    out.write(QJsonDocument(root).toJson(QJsonDocument::Compact));
    out.close();

    Federation fed;
    QStringList warnings;
    QString err;
    REQUIRE(fed.load(fed_path, &warnings, &err));
    REQUIRE(fed.models().size() == 1);
    REQUIRE(fed.models()[0].source_path == QDir::cleanPath(outside));
    REQUIRE_FALSE(windowsQtTreatsAsNetworkPath(fed.models()[0].source_path));
}
