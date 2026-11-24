// This file was generated with the assistance of an AI coding tool.

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

// Spec for the sidecar chunk-table bounds check.
//
// A .ifcview chunk record carries a uint32 mesh_count. The geometry-metadata
// parser accepts any count that fits in the buffer, and ViewportCore::applyCachedModel
// then reserves that many uint32s and loops that many times. These tests
// feed a few-kilobyte sidecar (and the same metadata in memory) and require
// the loader to refuse it before that reserve and before that loop.
//
// They fail while the check is missing. A fix that still reserves or walks
// the file's mesh_count, or that still uploads the model, fails too: the
// in-process allocator records a request of a megabyte or more, the child
// process's address-space cap turns that request into bad_alloc, a tight
// loop blows the time budget, and a fake wgpu device is a tripwire for any
// path that continues into createModelBuffers.

#include "SidecarCache.h"
#include "SidecarCompress.h"
#include "StreamingLoader.h"

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <Eigen/Dense>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <linux/perf_event.h>
#include <new>
#include <signal.h>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/ioctl.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>
#include <webgpu/webgpu.h>

#define private public
#include "ViewportCore.h"
#undef private

namespace fs = std::filesystem;

namespace {

int g_failed = 0;

// Set around the production call. A reserve of the attacker mesh_count asks
// for about 16 GiB; anything of a megabyte or more from these tiny models is
// that request, including when the callee catches the failure and returns.
thread_local bool g_counting = false;
thread_local bool g_huge_request = false;
thread_local int g_in_new = 0;

bool hugeRequest(std::size_t n) {
    return g_counting && g_in_new == 0 && n >= (1u << 20);
}

} // namespace

void* operator new(std::size_t n) {
    if (hugeRequest(n)) {
        g_huge_request = true;
    }
    ++g_in_new;
    void* p = std::malloc(n ? n : 1);
    --g_in_new;
    if (!p) {
        throw std::bad_alloc();
    }
    return p;
}
void* operator new[](std::size_t n) {
    return operator new(n);
}
void operator delete(void* p) noexcept {
    std::free(p);
}
void operator delete(void* p, std::size_t) noexcept {
    std::free(p);
}
void operator delete[](void* p) noexcept {
    std::free(p);
}
void operator delete[](void* p, std::size_t) noexcept {
    std::free(p);
}

namespace {

struct MockHost : ViewportHost {
    WGPUSurface createSurface(WGPUInstance) override { return nullptr; }
    void framebufferSize(int& w, int& h) const override {
        w = 800;
        h = 600;
    }
    float dpr() const override { return 1.0f; }
    void requestFrame() override {}
    void quit() override {}
};

void check(bool ok, const char* name, const std::string& detail) {
    if (ok) {
        std::printf("PASS %s\n", name);
        return;
    }
    std::printf("FAIL %s%s%s\n", name, detail.empty() ? "" : ": ", detail.c_str());
    ++g_failed;
}

void appendBytes(std::vector<std::uint8_t>& buffer, const void* data, std::size_t n) {
    const auto* bytes = static_cast<const std::uint8_t*>(data);
    buffer.insert(buffer.end(), bytes, bytes + n);
}

template <typename T>
void appendVec(std::vector<std::uint8_t>& buffer, const std::vector<T>& values) {
    const std::uint32_t count = static_cast<std::uint32_t>(values.size());
    appendBytes(buffer, &count, 4);
    if (count > 0) {
        appendBytes(buffer, values.data(), sizeof(T) * count);
    }
}

// Same geometry-metadata layout writeSidecar emits and parseSidecarGeometryMetadata reads.
std::vector<std::uint8_t> geometryMetadata(const SidecarData& data) {
    std::vector<std::uint8_t> buffer;
    appendVec(buffer, data.meshes);
    appendVec(buffer, data.instances);
    appendBytes(buffer, &data.has_coordinate_operation, 4);
    appendBytes(buffer, data.coordinate_operation_meters, sizeof(double) * 16);
    appendBytes(buffer, &data.project_length_to_meters, sizeof(double));
    appendBytes(buffer, &data.map_unit_to_meters, sizeof(double));
    appendVec(buffer, data.chunks);
    return buffer;
}

std::vector<std::uint8_t> elementMetadata() {
    std::vector<std::uint8_t> buffer;
    const std::vector<ElementTableRecord> elements;
    appendVec(buffer, elements);
    const std::uint32_t string_bytes = 0;
    appendBytes(buffer, &string_bytes, 4);
    return buffer;
}

SidecarData makeModel(std::uint32_t n_meshes, std::vector<SidecarChunk> chunks) {
    SidecarData data;
    data.meshes.resize(n_meshes);
    // One instance, so a desktop open that requires a non-empty instance table
    // still reaches applyCachedModel. mesh_id 0 is only meaningful when a mesh exists.
    data.instances.resize(1);
    data.instances[0].object_id = 1;
    data.project_length_to_meters = 1.0;
    data.map_unit_to_meters = 1.0;
    data.coordinate_operation_meters[0] = 1.0;
    data.coordinate_operation_meters[5] = 1.0;
    data.coordinate_operation_meters[10] = 1.0;
    data.coordinate_operation_meters[15] = 1.0;
    data.chunks = std::move(chunks);
    return data;
}

SidecarChunk chunk(std::uint32_t first_mesh, std::uint32_t mesh_count) {
    SidecarChunk record{};
    record.first_mesh = first_mesh;
    record.mesh_count = mesh_count;
    return record;
}

bool parseGeometry(const SidecarData& data, SidecarData& out) {
    const std::vector<std::uint8_t> bytes = geometryMetadata(data);
    return parseSidecarGeometryMetadata(bytes.data(), bytes.size(), out);
}

fs::path scratchDir() {
    const fs::path dir = fs::temp_directory_path() / "ifcviewer_mesh_count_bounds";
    fs::remove_all(dir);
    fs::create_directories(dir);
    return dir;
}

// Attacker file: valid head, empty geometry section, zstd metadata whose chunk
// table is the caller's. Returns the on-disk size.
std::uint64_t writeAttackerSidecar(const fs::path& ifc_path, const SidecarData& data) {
    const std::vector<std::uint8_t> geometry = geometryMetadata(data);
    const std::vector<std::uint8_t> elements = elementMetadata();
    const std::vector<std::uint8_t> geometry_zstd =
        SidecarCompress::compress(geometry.data(), geometry.size(), 1);
    const std::vector<std::uint8_t> element_zstd =
        SidecarCompress::compress(elements.data(), elements.size(), 1);
    if (geometry_zstd.empty() || element_zstd.empty()) {
        throw std::runtime_error("harness: zstd compress failed");
    }

    const fs::path sidecar = fs::path(ifc_path).replace_extension(".ifcview");
    FILE* file = std::fopen(sidecar.string().c_str(), "wb");
    if (!file) {
        throw std::runtime_error("harness: fopen failed");
    }

    const std::uint32_t magic = SIDECAR_MAGIC;
    const std::uint32_t version = SIDECAR_VERSION;
    const std::uint32_t endian = SIDECAR_ENDIAN;
    const std::uint64_t geometry_bytes = 0;
    std::fwrite(&magic, 4, 1, file);
    std::fwrite(&version, 4, 1, file);
    std::fwrite(&endian, 4, 1, file);
    std::fwrite(&geometry_bytes, 8, 1, file);

    auto writeBlock = [&](const std::vector<std::uint8_t>& raw, const std::vector<std::uint8_t>& zstd) {
        const std::uint64_t comp = zstd.size();
        const std::uint64_t raw_size = raw.size();
        std::fwrite(&comp, 8, 1, file);
        std::fwrite(&raw_size, 8, 1, file);
        std::fwrite(zstd.data(), 1, zstd.size(), file);
    };
    writeBlock(geometry, geometry_zstd);
    writeBlock(elements, element_zstd);
    std::fclose(file);
    return static_cast<std::uint64_t>(fs::file_size(sidecar));
}

std::string chunkSummary(const SidecarData& data) {
    std::ostringstream out;
    out << "chunks=" << data.chunks.size();
    for (const SidecarChunk& record : data.chunks) {
        out << " [" << record.first_mesh << "," << record.mesh_count << ")";
    }
    return out.str();
}

// ---- parser / file tests (no GPU) ------------------------------------------

void testValidTocRoundTrips() {
    const char* name = "valid_toc_round_trips";
    const SidecarData model = makeModel(2, {chunk(0, 1), chunk(1, 1)});
    SidecarData parsed;
    if (!parseGeometry(model, parsed)) {
        check(false, name, "in-range chunk table was rejected");
        return;
    }
    if (parsed.meshes.size() != 2 || parsed.instances.size() != 1 || parsed.chunks.size() != 2 ||
        parsed.chunks[0].mesh_count != 1 || parsed.chunks[1].first_mesh != 1) {
        check(false, name, "parsed metadata does not match the in-range table");
        return;
    }

    const fs::path dir = scratchDir();
    const fs::path ifc = dir / "valid.ifc";
    std::uint64_t bytes = 0;
    try {
        bytes = writeAttackerSidecar(ifc, model);
    } catch (const std::exception& ex) {
        check(false, name, ex.what());
        return;
    }
    const std::optional<StreamingSidecar> loaded = readSidecarMetadata(ifc.string());
    if (!loaded) {
        check(false, name, "readSidecarMetadata rejected an in-range sidecar");
        return;
    }
    const bool ok = loaded->meta.meshes.size() == 2 && loaded->meta.instances.size() == 1 &&
                    loaded->meta.chunks.size() == 2 && loaded->meta.chunks[0].mesh_count == 1 &&
                    loaded->meta.chunks[1].mesh_count == 1 && bytes < 65536;
    check(ok, name, ok ? "" : "file metadata mismatch, size=" + std::to_string(bytes));
}

void testParseRejects(const char* name, SidecarData model) {
    SidecarData parsed;
    const bool accepted = parseGeometry(model, parsed);
    if (!accepted) {
        check(true, name, "");
        return;
    }
    check(false, name, "parser accepted " + chunkSummary(parsed));
}

void testFileRejects(const char* name, SidecarData model) {
    const fs::path dir = scratchDir();
    const fs::path ifc = dir / "evil.ifc";
    std::uint64_t bytes = 0;
    try {
        bytes = writeAttackerSidecar(ifc, model);
    } catch (const std::exception& ex) {
        check(false, name, ex.what());
        return;
    }
    if (bytes >= 65536) {
        check(false, name, "fixture is not a few-kilobyte sidecar (" + std::to_string(bytes) + " bytes)");
        return;
    }
    const std::optional<StreamingSidecar> loaded = readSidecarMetadata(ifc.string());
    if (!loaded) {
        check(true, name, "");
        return;
    }
    check(false, name, "readSidecarMetadata returned metadata from a " + std::to_string(bytes) + " byte file: " + chunkSummary(loaded->meta));
}

// ---- applyCachedModel / loadSidecarFromPath --------------------------------
//
// The child exits 0 only when the call returns, installs nothing, requests no
// megabyte-scale allocation, and stays inside the time budget. Any other exit
// — including a signal from the fake device — is a failure.

enum ChildCode : int {
    kRejected = 0,
    kInstalled = 2,
    kHugeAlloc = 3,
    kTooSlow = 4,
    kNoCap = 6,
};

bool capAddressSpace() {
    unsigned long vm_kb = 0;
    std::ifstream status("/proc/self/status");
    std::string line;
    while (std::getline(status, line)) {
        if (std::sscanf(line.c_str(), "VmSize: %lu", &vm_kb) == 1) {
            break;
        }
    }
    if (vm_kb == 0) {
        return false;
    }
    struct rlimit limit;
    limit.rlim_cur = limit.rlim_max = (vm_kb + 256UL * 1024UL) * 1024UL;
    struct rlimit core = {};
    setrlimit(RLIMIT_CORE, &core);
    return setrlimit(RLIMIT_AS, &limit) == 0;
}

int taskClockFd() {
    perf_event_attr attr = {};
    attr.type = PERF_TYPE_SOFTWARE;
    attr.size = sizeof(attr);
    attr.config = PERF_COUNT_SW_TASK_CLOCK;
    attr.disabled = 1;
    attr.exclude_kernel = 1;
    attr.exclude_hv = 1;
    const int fd = static_cast<int>(syscall(__NR_perf_event_open, &attr, 0, -1, -1, 0));
    if (fd < 0) {
        return -1;
    }
    ioctl(fd, PERF_EVENT_IOC_RESET, 0);
    ioctl(fd, PERF_EVENT_IOC_ENABLE, 0);
    return fd;
}

std::uint64_t readTaskClock(int fd) {
    if (fd < 0) {
        return 0;
    }
    std::uint64_t ticks = 0;
    if (read(fd, &ticks, sizeof(ticks)) != static_cast<ssize_t>(sizeof(ticks))) {
        return 0;
    }
    return ticks;
}

// 200 ms of task CPU. One mesh_count of 0xFFFFFFFF is a few hundred
// milliseconds of the production loop on a fast core; several such chunks
// cannot finish under this budget, and a reject returns in well under it.
constexpr std::uint64_t kMaxTaskClockNs = 200000000ULL;
constexpr std::int64_t kMaxWallMs = 200;

int finishCall(int clock_fd, std::chrono::steady_clock::time_point started, bool installed) {
    const auto wall_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                             std::chrono::steady_clock::now() - started)
                             .count();
    const std::uint64_t task_ns = readTaskClock(clock_fd);
    if (g_huge_request) {
        return kHugeAlloc;
    }
    if (installed) {
        return kInstalled;
    }
    if (wall_ms > kMaxWallMs) {
        return kTooSlow;
    }
    if (clock_fd >= 0 && task_ns > kMaxTaskClockNs) {
        return kTooSlow;
    }
    return kRejected;
}

template <typename Fn>
int invokeBounded(Fn&& fn, bool* installed) {
    if (!capAddressSpace()) {
        return kNoCap;
    }
    const int clock_fd = taskClockFd();
    g_huge_request = false;
    g_counting = true;
    const auto started = std::chrono::steady_clock::now();
    try {
        fn();
    } catch (const std::bad_alloc&) {
        g_counting = false;
        return kHugeAlloc;
    } catch (const std::length_error&) {
        g_counting = false;
        return kHugeAlloc;
    }
    g_counting = false;
    return finishCall(clock_fd, started, installed && *installed);
}

void armDevice(ViewportCore& core) {
    core.device_ = reinterpret_cast<WGPUDevice>(static_cast<std::uintptr_t>(0x1));
    core.queue_ = reinterpret_cast<WGPUQueue>(static_cast<std::uintptr_t>(0x1));
}

int childApply(SidecarData model) {
    MockHost host;
    ViewportCore core(&host);
    armDevice(core);
    bool installed = false;
    return invokeBounded(
        [&] {
            StreamingSidecar sidecar;
            sidecar.meta = std::move(model);
            sidecar.file_path = "attacker.ifcview";
            sidecar.geometry_section_offset = SIDECAR_HEAD_BYTES;
            core.applyCachedModel(7, std::move(sidecar));
            installed = core.models_gpu_.find(7) != core.models_gpu_.end();
        },
        &installed);
}

int childLoadPath(std::string path) {
    MockHost host;
    ViewportCore core(&host);
    armDevice(core);
    bool installed = false;
    return invokeBounded(
        [&] {
            const std::uint32_t id = core.loadSidecarFromPath(path);
            installed = id != 0 || !core.models_gpu_.empty();
        },
        &installed);
}

std::string childDetail(int status) {
    if (WIFEXITED(status)) {
        switch (WEXITSTATUS(status)) {
        case kRejected:
            return "rejected";
        case kInstalled:
            return "model was installed / load returned an id";
        case kHugeAlloc:
            return "allocation followed the file mesh_count";
        case kTooSlow:
            return "call looped long enough to blow the time budget";
        case kNoCap:
            return "harness could not cap the address space";
        default:
            return "exit " + std::to_string(WEXITSTATUS(status));
        }
    }
    if (WIFSIGNALED(status)) {
        return std::string("killed by signal ") + std::to_string(WTERMSIG(status)) +
               " (continued into wgpu with the fake device)";
    }
    return "unknown wait status";
}

template <typename Fn>
void testChild(const char* name, Fn&& body) {
    const pid_t pid = fork();
    if (pid < 0) {
        check(false, name, "fork failed");
        return;
    }
    if (pid == 0) {
        alarm(5);
        const int code = body();
        _exit(code);
    }
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    int status = 0;
    for (;;) {
        const pid_t waited = waitpid(pid, &status, WNOHANG);
        if (waited == pid) {
            break;
        }
        if (std::chrono::steady_clock::now() > deadline) {
            kill(pid, SIGKILL);
            waitpid(pid, &status, 0);
            check(false, name, "timed out (mesh_count loop still running)");
            return;
        }
        usleep(1000);
    }
    const bool ok = WIFEXITED(status) && WEXITSTATUS(status) == kRejected;
    check(ok, name, ok ? "" : childDetail(status));
}

} // namespace

int main() {
    testValidTocRoundTrips();

    testParseRejects("parse_rejects_mesh_count_past_table", makeModel(1, {chunk(0, 2)}));
    testParseRejects("parse_rejects_mesh_count_uint32_max",
                     makeModel(1, {chunk(0, 0xFFFFFFFFu)}));
    testParseRejects("parse_rejects_uint32_wrap", makeModel(2, {chunk(1, 0xFFFFFFFFu)}));
    testParseRejects("parse_rejects_first_mesh_past_end", makeModel(1, {chunk(1, 1)}));
    testParseRejects("parse_rejects_later_unbounded_chunk",
                     makeModel(1, {chunk(0, 1), chunk(0, 0xFFFFFFFFu)}));
    testParseRejects("parse_rejects_chunk_with_no_meshes", makeModel(0, {chunk(0, 0xFFFFFFFFu)}));

    const SidecarData max_count = makeModel(1, {chunk(0, 0xFFFFFFFFu)});
    const SidecarData wrapped = makeModel(2, {chunk(1, 0xFFFFFFFFu)});
    testFileRejects("readSidecarMetadata_rejects_mesh_count_uint32_max", max_count);
    testFileRejects("readSidecarMetadata_rejects_uint32_wrap", wrapped);
    testFileRejects("readSidecarMetadata_rejects_mesh_count_past_table", makeModel(1, {chunk(0, 2)}));

    std::vector<SidecarChunk> eight;
    for (int i = 0; i < 8; ++i) {
        eight.push_back(chunk(0, 0xFFFFFFFFu));
    }
    testChild("applyCachedModel_rejects_uint32_max", [&] { return childApply(makeModel(1, eight)); });
    testChild("applyCachedModel_rejects_modest_overrun",
              [&] { return childApply(makeModel(1, {chunk(0, 4)})); });
    testChild("applyCachedModel_rejects_uint32_wrap", [&] { return childApply(wrapped); });
    testChild("applyCachedModel_rejects_later_unbounded_chunk", [&] {
        return childApply(makeModel(1, {chunk(0, 1), chunk(0, 0xFFFFFFFFu)}));
    });

    const fs::path dir = scratchDir();
    const fs::path ifc = dir / "load.ifc";
    try {
        const std::uint64_t bytes = writeAttackerSidecar(ifc, max_count);
        if (bytes >= 65536) {
            check(false, "loadSidecarFromPath_rejects_attacker_file", "fixture too large");
        } else {
            const std::string path = ifc.string();
            testChild("loadSidecarFromPath_rejects_attacker_file",
                      [&] { return childLoadPath(path); });
        }
    } catch (const std::exception& ex) {
        check(false, "loadSidecarFromPath_rejects_attacker_file", ex.what());
    }

    std::printf("%d failed\n", g_failed);
    return g_failed == 0 ? 0 : 1;
}
