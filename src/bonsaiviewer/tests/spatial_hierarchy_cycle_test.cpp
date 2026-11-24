// This file was generated with the assistance of an AI coding tool.
//
// Spec for the spatial-hierarchy cycle bug. These checks fail while
// buildNode / get_container walk aggregation with no visited set, and pass
// once a cycle is cut and a normal tree is still built.
//
// The IFC bytes are opened with the same ifcopenshell::file constructor
// GeometryStreamer::run uses. The tree is built by SpatialHierarchyPanelView,
// triggered the way a loaded model triggers it: modelGeometryReady sets the
// active model (SessionState::createLoader), which emits activeModelChanged
// and calls rebuild.

#include "../../ifcparse/file.h"
#include "../../ifcviewer/SceneLoader.h"
#include "spatial_hierarchy_cycle_install.h"

#include <QApplication>
#include <QMetaObject>
#include <QWindow>

#define private public
#include "../modules/spatial_hierarchy/Panel.h"
#include "../modules/spatial_hierarchy/View.h"
#include "../SessionState.h"
#undef private

#include "element.h"

#include <cstdio>
#include <fstream>
#include <functional>
#include <memory>
#include <string>
#include <sys/wait.h>
#include <unistd.h>
#include <utility>
#include <vector>

using bonsaiviewer::modules::spatial_hierarchy::SpatialHierarchyPanel;
using bonsaiviewer::modules::spatial_hierarchy::SpatialHierarchyPanelView;
using bonsaiviewer::modules::spatial_hierarchy::TreeNode;

namespace {

constexpr uint32_t kSessionModel = 7;
const char* kModelId = "model-1";
const char* g_case = "";

[[noreturn]] void fail(const std::string& message) {
    std::fprintf(stderr, "FAIL %s: %s\n", g_case, message.c_str());
    std::_Exit(1);
}

std::string guid(char mark) {
    return std::string(21, '0') + mark;
}

std::string write_ifc(const std::string& data_lines) {
    const std::string path = std::string("/tmp/spatial-cycle-") + std::to_string(::getpid()) + "-" + g_case + ".ifc";
    std::ofstream out(path);
    out << "ISO-10303-21;\nHEADER;\n"
        << "FILE_DESCRIPTION((''),'2;1');\n"
        << "FILE_NAME('cycle.ifc','2026-01-01T00:00:00',(''),(''),'','','');\n"
        << "FILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n"
        << data_lines << "ENDSEC;\nEND-ISO-10303-21;\n";
    if (!out) {
        fail("could not write " + path);
    }
    return path;
}

std::unique_ptr<ifcopenshell::file> open_ifc(const std::string& path) {
    try {
        // GeometryStreamer::run opens the path this way before any UI rebuild.
        return std::make_unique<ifcopenshell::file>(path, ifcopenshell::FT_AUTODETECT, true);
    } catch (const std::exception& ex) {
        fail(std::string("parser rejected the file: ") + ex.what());
    }
}

express::base only_of_type(ifcopenshell::file& file, const char* type) {
    const auto found = file.instances_by_type(type);
    if (found.size() != 1) {
        fail(std::string("expected one ") + type);
    }
    return found.front();
}

void expect_back_edge(ifcopenshell::file& file) {
    const auto project = only_of_type(file, "IfcProject");
    const auto sites = get_spatial_children(project);
    if (sites.size() != 1) {
        fail("project did not aggregate exactly one spatial child");
    }
    const auto buildings = get_spatial_children(sites.front());
    if (buildings.size() != 1) {
        fail("site did not aggregate exactly one spatial child");
    }
    const auto back = get_spatial_children(buildings.front());
    if (back.size() != 1 || back.front().id() != sites.front().id()) {
        fail("building did not aggregate the site back");
    }
}

std::string project_site_building() {
    return "  #1=IFCPROJECT('" + guid('1') + "',$,'Project',$,$,$,$,$,$);\n"
                                             "  #2=IFCSITE('" +
           guid('2') + "',$,'Site',$,$,$,$,$,$,$,$,$,$,$);\n"
                       "  #3=IFCBUILDING('" +
           guid('3') + "',$,'Building',$,$,$,$,$,$,$,$,$);\n";
}

std::string storey_line() {
    return "  #4=IFCBUILDINGSTOREY('" + guid('4') + "',$,'Storey',$,$,$,$,$,$,$);\n";
}

// Owns the parsed file, the streamer the loader consults, and the session
// the panel view reads. Mirrors queueModels + setModelMapping before the
// geometry-ready signal.
class LoadedSession {
  public:
    explicit LoadedSession(std::unique_ptr<ifcopenshell::file> file) {
        SpatialCycleInstall::session_model_id = kSessionModel;
        SpatialCycleInstall::streamer = &streamer_;
        loader_ = std::make_unique<SceneLoader>(nullptr);
        session_.loader_ = loader_.get();
        session_.setModelMapping(QString::fromLatin1(kModelId), kSessionModel);
        file_ = std::move(file);
    }

    ifcopenshell::file& file() { return *file_; }
    bonsaiviewer::SessionState& session() { return session_; }

    void attachFile() { streamer_.setIfcFile(std::move(file_)); }

    QList<TreeNode> onGeometryReady() {
        attachFile();
        SpatialHierarchyPanel panel;
        SpatialHierarchyPanelView view(&panel, &session_);
        // createLoader connects this after the view has subscribed.
        QObject::connect(&session_, &bonsaiviewer::SessionState::modelGeometryReady, &session_, [this](uint32_t session_model_id) {
            if (session_.activeModelId().isEmpty()) {
                session_.setActiveModelId(session_.modelIdForSessionModelId(session_model_id));
            }
        });
        session_.notifyModelGeometryReady(kSessionModel);
        return view.nodes_;
    }

    QList<TreeNode> onDataSourceReady() {
        SpatialHierarchyPanel panel;
        SpatialHierarchyPanelView view(&panel, &session_);
        // Sidecar geometry can select the model before the IFC file is open.
        session_.setActiveModelId(QString::fromLatin1(kModelId));
        attachFile();
        const bool invoked = QMetaObject::invokeMethod(&session_, "modelDataSourceReady", Qt::DirectConnection, Q_ARG(uint32_t, kSessionModel));
        if (!invoked) {
            fail("modelDataSourceReady was not emitted");
        }
        return view.nodes_;
    }

    QList<TreeNode> onProjectOpened() {
        SpatialHierarchyPanel panel;
        SpatialHierarchyPanelView view(&panel, &session_);
        session_.setActiveModelId(QString::fromLatin1(kModelId));
        attachFile();
        session_.notifyProjectOpened(QStringLiteral("opened.ifc"));
        return view.nodes_;
    }

    QList<TreeNode> onViewConstruction() {
        attachFile();
        session_.setActiveModelId(QString::fromLatin1(kModelId));
        SpatialHierarchyPanel panel;
        SpatialHierarchyPanelView view(&panel, &session_);
        return view.nodes_;
    }

  private:
    GeometryStreamer streamer_;
    std::unique_ptr<SceneLoader> loader_;
    bonsaiviewer::SessionState session_;
    std::unique_ptr<ifcopenshell::file> file_;
};

void expect_chain(const QList<TreeNode>& nodes, const std::vector<const char*>& names) {
    const QList<TreeNode>* level = &nodes;
    const TreeNode* current = nullptr;
    for (const char* name : names) {
        const TreeNode* found = nullptr;
        for (const auto& node : *level) {
            if (node.name == QString::fromLatin1(name)) {
                found = &node;
                break;
            }
        }
        if (found == nullptr) {
            fail(std::string("missing node ") + name);
        }
        current = found;
        level = &found->children;
    }
    if (current == nullptr || !current->children.isEmpty()) {
        const QString extra = current != nullptr ? current->children.front().name : QStringLiteral("?");
        fail("cycle continued through " + extra.toStdString());
    }
    int depth = 0;
    const QList<TreeNode>* walk = &nodes;
    while (walk != nullptr && !walk->isEmpty()) {
        ++depth;
        if (depth > 8) {
            fail("tree deeper than 8");
        }
        walk = &walk->front().children;
    }
}

void expect_diamond(const QList<TreeNode>& nodes) {
    if (nodes.size() != 1 || nodes.front().name != QLatin1String("Site")) {
        fail("diamond root was not the site");
    }
    const auto& buildings = nodes.front().children;
    if (buildings.size() != 2) {
        fail("site did not keep both buildings");
    }
    bool saw_storey = false;
    for (const auto& building : buildings) {
        if (building.name != QLatin1String("BuildingA") && building.name != QLatin1String("BuildingB")) {
            fail("unexpected building " + building.name.toStdString());
        }
        for (const auto& storey : building.children) {
            if (storey.name != QLatin1String("Shared") || !storey.children.isEmpty()) {
                fail("shared storey was expanded or renamed");
            }
            saw_storey = true;
        }
    }
    if (!saw_storey) {
        fail("shared storey was dropped");
    }
}

void with_ui(const std::function<void()>& body) {
    qputenv("QT_QPA_PLATFORM", QByteArray("offscreen"));
    int argc = 1;
    char argv0[] = "spatial_hierarchy_cycle_test";
    char* argv[] = {argv0, nullptr};
    QApplication app(argc, argv);
    body();
}

std::function<void()> g_body;

int run_forked(const char* name, std::function<void()> body) {
    g_case = name;
    g_body = std::move(body);
    const pid_t pid = fork();
    if (pid < 0) {
        std::fprintf(stderr, "FAIL %s: fork failed\n", name);
        return 1;
    }
    if (pid == 0) {
        g_case = name;
        try {
            g_body();
        } catch (const std::exception& ex) {
            std::fprintf(stderr, "FAIL %s: exception %s\n", name, ex.what());
            std::_Exit(1);
        }
        std::_Exit(0);
    }

    int status = 0;
    for (int tick = 0; tick < 50; ++tick) {
        const pid_t done = waitpid(pid, &status, WNOHANG);
        if (done == pid) {
            break;
        }
        if (done < 0) {
            std::fprintf(stderr, "FAIL %s: waitpid failed\n", name);
            return 1;
        }
        usleep(100000);
        status = 0;
    }
    if (waitpid(pid, &status, WNOHANG) == 0) {
        kill(pid, SIGKILL);
        waitpid(pid, &status, 0);
        std::fprintf(stderr, "FAIL %s: timed out (walk did not finish)\n", name);
        return 1;
    }
    if (WIFEXITED(status) && WEXITSTATUS(status) == 0) {
        std::printf("PASS %s\n", name);
        return 0;
    }
    if (WIFSIGNALED(status)) {
        std::fprintf(stderr, "FAIL %s: killed by signal %d\n", name, WTERMSIG(status));
    } else {
        std::fprintf(stderr, "FAIL %s: exit %d\n", name, WIFEXITED(status) ? WEXITSTATUS(status) : status);
    }
    return 1;
}

std::string acyclic_text() {
    return project_site_building() + storey_line() +
           "  #10=IFCRELAGGREGATES('" + guid('A') + "',$,$,$,#1,(#2));\n"
                                                    "  #11=IFCRELAGGREGATES('" +
           guid('B') + "',$,$,$,#2,(#3));\n"
                       "  #12=IFCRELAGGREGATES('" +
           guid('C') + "',$,$,$,#3,(#4));\n";
}

std::string mutual_text() {
    // Project aggregates the site, the site aggregates the building, and the
    // building aggregates the site. Relationship order matches the report.
    return project_site_building() +
           "  #10=IFCRELAGGREGATES('" + guid('A') + "',$,$,$,#1,(#2));\n"
                                                    "  #11=IFCRELAGGREGATES('" +
           guid('B') + "',$,$,$,#2,(#3));\n"
                       "  #12=IFCRELAGGREGATES('" +
           guid('C') + "',$,$,$,#3,(#2));\n";
}

std::string self_text() {
    return "  #1=IFCPROJECT('" + guid('1') + "',$,'Project',$,$,$,$,$,$);\n"
                                             "  #2=IFCSITE('" +
           guid('2') + "',$,'Site',$,$,$,$,$,$,$,$,$,$,$);\n"
                       "  #10=IFCRELAGGREGATES('" +
           guid('A') + "',$,$,$,#1,(#2));\n"
                       "  #11=IFCRELAGGREGATES('" +
           guid('B') + "',$,$,$,#2,(#2));\n";
}

std::string three_text() {
    return project_site_building() + storey_line() +
           "  #10=IFCRELAGGREGATES('" + guid('A') + "',$,$,$,#1,(#2));\n"
                                                    "  #11=IFCRELAGGREGATES('" +
           guid('B') + "',$,$,$,#2,(#3));\n"
                       "  #12=IFCRELAGGREGATES('" +
           guid('C') + "',$,$,$,#3,(#4));\n"
                       "  #13=IFCRELAGGREGATES('" +
           guid('D') + "',$,$,$,#4,(#2));\n";
}

std::string diamond_text() {
    return "  #1=IFCPROJECT('" + guid('1') + "',$,'Project',$,$,$,$,$,$);\n"
                                             "  #2=IFCSITE('" +
           guid('2') + "',$,'Site',$,$,$,$,$,$,$,$,$,$,$);\n"
                       "  #3=IFCBUILDING('" +
           guid('3') + "',$,'BuildingA',$,$,$,$,$,$,$,$,$);\n"
                       "  #4=IFCBUILDING('" +
           guid('4') + "',$,'BuildingB',$,$,$,$,$,$,$,$,$);\n"
                       "  #5=IFCBUILDINGSTOREY('" +
           guid('5') + "',$,'Shared',$,$,$,$,$,$,$);\n"
                       "  #10=IFCRELAGGREGATES('" +
           guid('A') + "',$,$,$,#1,(#2));\n"
                       "  #11=IFCRELAGGREGATES('" +
           guid('B') + "',$,$,$,#2,(#3,#4));\n"
                       "  #12=IFCRELAGGREGATES('" +
           guid('C') + "',$,$,$,#3,(#5));\n"
                       "  #13=IFCRELAGGREGATES('" +
           guid('D') + "',$,$,$,#4,(#5));\n";
}

std::string contained_wall_text() {
    return project_site_building() + storey_line() +
           "  #5=IFCWALL('" + guid('5') + "',$,'Wall',$,$,$,$,$,$);\n"
                                          "  #10=IFCRELAGGREGATES('" +
           guid('A') + "',$,$,$,#1,(#2));\n"
                       "  #11=IFCRELAGGREGATES('" +
           guid('B') + "',$,$,$,#2,(#3));\n"
                       "  #12=IFCRELAGGREGATES('" +
           guid('C') + "',$,$,$,#3,(#4));\n"
                       "  #13=IFCRELCONTAINEDINSPATIALSTRUCTURE('" +
           guid('E') + "',$,$,$,(#5),#4);\n";
}

// Back-edge relationship has the lower id, so Decomposes().front() on the
// site is the building and get_container recurses.
std::string parent_cycle_text() {
    return project_site_building() +
           "  #10=IFCRELAGGREGATES('" + guid('A') + "',$,$,$,#3,(#2));\n"
                                                    "  #11=IFCRELAGGREGATES('" +
           guid('B') + "',$,$,$,#2,(#3));\n"
                       "  #12=IFCRELAGGREGATES('" +
           guid('C') + "',$,$,$,#1,(#2));\n";
}

} // namespace

int main() {
    int failures = 0;

    failures += run_forked("acyclic geometry-ready chain", [] {
        with_ui([] {
            LoadedSession loaded(open_ifc(write_ifc(acyclic_text())));
            expect_chain(loaded.onGeometryReady(), {"Site", "Building", "Storey"});
        });
    });

    failures += run_forked("diamond is not a cycle", [] {
        with_ui([] {
            LoadedSession loaded(open_ifc(write_ifc(diamond_text())));
            expect_diamond(loaded.onGeometryReady());
        });
    });

    failures += run_forked("mutual cycle via geometry ready", [] {
        with_ui([] {
            LoadedSession loaded(open_ifc(write_ifc(mutual_text())));
            expect_back_edge(loaded.file());
            expect_chain(loaded.onGeometryReady(), {"Site", "Building"});
        });
    });

    failures += run_forked("self cycle via geometry ready", [] {
        with_ui([] {
            LoadedSession loaded(open_ifc(write_ifc(self_text())));
            const auto site = only_of_type(loaded.file(), "IfcSite");
            const auto children = get_spatial_children(site);
            if (children.size() != 1 || children.front().id() != site.id()) {
                fail("site did not aggregate itself");
            }
            expect_chain(loaded.onGeometryReady(), {"Site"});
        });
    });

    failures += run_forked("three-node cycle via geometry ready", [] {
        with_ui([] {
            LoadedSession loaded(open_ifc(write_ifc(three_text())));
            expect_chain(loaded.onGeometryReady(), {"Site", "Building", "Storey"});
        });
    });

    failures += run_forked("mutual cycle via data source ready", [] {
        with_ui([] {
            LoadedSession loaded(open_ifc(write_ifc(mutual_text())));
            expect_back_edge(loaded.file());
            expect_chain(loaded.onDataSourceReady(), {"Site", "Building"});
        });
    });

    failures += run_forked("mutual cycle via project opened", [] {
        with_ui([] {
            LoadedSession loaded(open_ifc(write_ifc(mutual_text())));
            expect_chain(loaded.onProjectOpened(), {"Site", "Building"});
        });
    });

    failures += run_forked("mutual cycle via view construction", [] {
        with_ui([] {
            LoadedSession loaded(open_ifc(write_ifc(mutual_text())));
            expect_chain(loaded.onViewConstruction(), {"Site", "Building"});
        });
    });

    failures += run_forked("contained wall container", [] {
        LoadedSession loaded(open_ifc(write_ifc(contained_wall_text())));
        const auto wall = only_of_type(loaded.file(), "IfcWall");
        const auto container = get_container(wall);
        const auto name = get_string_attribute(container, "Name");
        if (!name || *name != "Storey") {
            fail("wall container was not the storey");
        }
    });

    failures += run_forked("parent cycle get_container", [] {
        LoadedSession loaded(open_ifc(write_ifc(parent_cycle_text())));
        const auto building = only_of_type(loaded.file(), "IfcBuilding");
        const auto container = get_container(building);
        if (container) {
            const auto name = get_string_attribute(container, "Name");
            if (!name || (*name != "Project" && *name != "Site" && *name != "Building")) {
                fail("container escaped the model");
            }
        }
    });

    if (failures != 0) {
        std::fprintf(stderr, "%d case(s) failed\n", failures);
        return 1;
    }
    std::printf("all spatial hierarchy cycle cases passed\n");
    return 0;
}
