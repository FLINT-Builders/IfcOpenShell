# This file was generated with the assistance of an AI coding tool.
"""Integrity tests for nix/build-all.py dependency downloads.

These tests are expected to fail until every ``download_tool="py"`` archive is
authenticated before it is written, extracted, or built. They pass ``sha256``
into ``build_dependency`` and also drive the Python and MPFR call sites.

Not covered here, because they are different code paths:

- ``download_tool="git"`` clones (swig, OCCT, manifold, OpenCOLLADA, CGAL, TBB, USD, zstd, rocksdb)
- Qt6 installation through aqtinstall in ``install_qt6``
- ``win/installers.py`` ``download_file`` (HTTPS URLs, Windows build)

Run:

    pytest nix/tests/test_unverified_http_downloads.py
"""

from __future__ import annotations

import ast
import ctypes
import hashlib
import io
import json
import os
import select
import shutil
import struct
import subprocess
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
BUILD_ALL = REPO / "nix" / "build-all.py"
LINUX_WORKFLOW = REPO / ".github" / "workflows" / "build-ifcopenshell-linux.yml"
OMIT = object()
ROOT = "pkgroot"

PWN_SCRIPT = """#!/bin/sh
echo PWN > "$IFCOS_PWNED_MARKER"
exit 0
"""

GOOD_CONFIGURE = """#!/bin/sh
prefix=/tmp/unused-prefix
for arg in "$@"; do
  case "$arg" in
    --prefix=*) prefix=${arg#--prefix=} ;;
  esac
done
cat > Makefile << EOF
all:
	@echo all
install:
	mkdir -p "$prefix"
	touch "$prefix/installed"
EOF
echo GOOD > "$IFCOS_GOOD_MARKER"
"""

CMAKE_LISTS = """cmake_minimum_required(VERSION 3.16)
project(pwn C)
execute_process(COMMAND /bin/sh -c "echo PWN > \\"$IFCOS_PWNED_MARKER\\"")
"""

# Second and later read-only opens of the archive basename return a different file.
# Models build_dependency hashing one open of the download path and then opening that
# path again for tar. The first read sees the bytes urlretrieve wrote.
PRELOAD_C = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int (*real_open)(const char *, int, ...);
static int (*real_open64)(const char *, int, ...);
static int (*real_openat)(int, const char *, int, ...);
static int (*real_openat64)(int, const char *, int, ...);
static int active;
static int reads;
static char want[256];
static char altpath[512];

__attribute__((constructor)) static void init_preload(void) {
    const char *w;
    const char *a;
    real_open = dlsym(RTLD_NEXT, "open");
    real_open64 = dlsym(RTLD_NEXT, "open64");
    real_openat = dlsym(RTLD_NEXT, "openat");
    real_openat64 = dlsym(RTLD_NEXT, "openat64");
    w = getenv("IFCOS_TOCTOU_BASENAME");
    a = getenv("IFCOS_TOCTOU_ALT");
    if (w && a && real_open && real_open64 && real_openat && real_openat64) {
        strncpy(want, w, sizeof(want) - 1);
        strncpy(altpath, a, sizeof(altpath) - 1);
        active = 1;
    }
}

static int is_target(const char *path) {
    const char *base;
    if (!active || !path) return 0;
    base = strrchr(path, '/');
    base = base ? base + 1 : path;
    return strcmp(base, want) == 0;
}

static int writing(int flags) {
    int acc = flags & O_ACCMODE;
    return acc == O_WRONLY || acc == O_RDWR;
}

static int swapped(int flags, mode_t mode, int have_mode) {
    int n = ++reads;
    if (n == 1) return -2;
    if (have_mode) return real_open(altpath, flags, mode);
    return real_open(altpath, flags);
}

int open(const char *path, int flags, ...) {
    mode_t mode = 0;
    int have_mode = 0;
    va_list ap;
    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
        have_mode = 1;
    }
    if (is_target(path) && !writing(flags)) {
        int fd = swapped(flags, mode, have_mode);
        if (fd != -2) return fd;
    }
    if (have_mode) return real_open(path, flags, mode);
    return real_open(path, flags);
}

int open64(const char *path, int flags, ...) {
    mode_t mode = 0;
    int have_mode = 0;
    va_list ap;
    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
        have_mode = 1;
    }
    if (is_target(path) && !writing(flags)) {
        int fd = swapped(flags, mode, have_mode);
        if (fd != -2) return fd;
    }
    if (have_mode) return real_open64(path, flags, mode);
    return real_open64(path, flags);
}

int openat(int dirfd, const char *path, int flags, ...) {
    mode_t mode = 0;
    int have_mode = 0;
    va_list ap;
    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
        have_mode = 1;
    }
    if (is_target(path) && !writing(flags)) {
        int fd = swapped(flags, mode, have_mode);
        if (fd != -2) return fd;
    }
    if (have_mode) return real_openat(dirfd, path, flags, mode);
    return real_openat(dirfd, path, flags);
}

int openat64(int dirfd, const char *path, int flags, ...) {
    mode_t mode = 0;
    int have_mode = 0;
    va_list ap;
    if (flags & O_CREAT) {
        va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
        have_mode = 1;
    }
    if (is_target(path) && !writing(flags)) {
        int fd = swapped(flags, mode, have_mode);
        if (fd != -2) return fd;
    }
    if (have_mode) return real_openat64(dirfd, path, flags, mode);
    return real_openat64(dirfd, path, flags);
}
"""

IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_NONBLOCK = 0x00000800
WATCH_MASK = IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE | IN_DELETE


def archive_bytes(mode: str, files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as handle:
        for name, data in files.items():
            payload = data.encode()
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o755
            handle.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload_files(entrypoint: str, script: str) -> dict[str, str]:
    return {f"{ROOT}/{entrypoint}": script, f"{ROOT}/README": "readme\n"}


class ArchiveServer:
    def __init__(self, body: bytes) -> None:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                server.paths.append(self.path)
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args: object) -> None:
                return

        self.paths: list[str] = []
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/src/"

    def close(self) -> None:
        self._httpd.shutdown()
        self._thread.join(timeout=5)
        self._httpd.server_close()


class DirWatch:
    """Records create and delete events under a directory. inotify is the Linux API used here."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.created: list[str] = []
        self.deleted: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        self._libc = libc
        libc.inotify_init1.argtypes = [ctypes.c_int]
        libc.inotify_init1.restype = ctypes.c_int
        libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        libc.inotify_add_watch.restype = ctypes.c_int
        self._fd = libc.inotify_init1(IN_NONBLOCK)
        if self._fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        watch = libc.inotify_add_watch(self._fd, os.fsencode(path), WATCH_MASK)
        if watch < 0:
            os.close(self._fd)
            raise OSError(ctypes.get_errno(), "inotify_add_watch")
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            ready, _, _ = select.select([self._fd], [], [], 0.05)
            if ready:
                self._drain()
        self._drain()

    def _drain(self) -> None:
        while True:
            try:
                raw = os.read(self._fd, 65536)
            except BlockingIOError:
                return
            if not raw:
                return
            offset = 0
            while offset + 16 <= len(raw):
                _, mask, _, length = struct.unpack_from("iIII", raw, offset)
                offset += 16
                name = raw[offset : offset + length].split(b"\x00", 1)[0].decode(errors="replace")
                offset += length
                with self._lock:
                    if mask & (IN_CREATE | IN_MOVED_TO | IN_CLOSE_WRITE) and name:
                        self.created.append(name)
                    if mask & (IN_DELETE | IN_MOVED_FROM) and name:
                        self.deleted.append(name)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        os.close(self._fd)


def load_build_all(deps: Path) -> dict[str, Any]:
    sys.dont_write_bytecode = True
    os.environ["BUILD_DIR"] = str(deps / "build-root")
    os.environ["DEPS_DIR"] = str(deps / "deps")
    nix = str(BUILD_ALL.parent)
    if nix not in sys.path:
        sys.path.insert(0, nix)
    saved_argv = sys.argv
    sys.argv = ["build-all.py", "json"]
    source = BUILD_ALL.read_text()
    stop_line = next(i for i, line in enumerate(source.splitlines(), 1) if line.startswith('if "json" in targets:'))

    class StopBuild(Exception):
        pass

    def trace(frame, event, arg):  # type: ignore[no-untyped-def]
        filename = frame.f_code.co_filename
        if event == "line" and os.path.abspath(filename) == str(BUILD_ALL) and frame.f_lineno >= stop_line:
            raise StopBuild()
        return trace

    namespace: dict[str, Any] = {"__name__": "build_all_under_test", "__file__": str(BUILD_ALL)}
    sys.settrace(trace)
    try:
        exec(compile(source, str(BUILD_ALL), "exec"), namespace)
    except StopBuild:
        pass
    finally:
        sys.settrace(None)
        sys.argv = saved_argv
    namespace["logger"].setLevel(40)
    namespace["_source"] = source
    return namespace


@pytest.fixture(scope="module")
def build_all() -> dict[str, Any]:
    deps = Path("/tmp/ifcos-download-tests-load")
    shutil.rmtree(deps, ignore_errors=True)
    deps.mkdir()
    return load_build_all(deps)


def unexpected_keyword(exc: BaseException, name: str) -> bool:
    return isinstance(exc, TypeError) and "unexpected keyword" in str(exc) and name in str(exc)


def call_build(
    ns: dict[str, Any],
    *,
    name: str,
    mode: str,
    base_url: str,
    download_name: str,
    sha256_hex: Any = OMIT,
) -> None:
    kwargs: dict[str, Any] = {}
    if sha256_hex is not OMIT:
        kwargs["sha256"] = sha256_hex
    try:
        ns["build_dependency"](
            name=name,
            mode=mode,
            build_tool_args=[],
            download_url=base_url,
            download_name=download_name,
            **kwargs,
        )
    except TypeError as exc:
        if sha256_hex is not OMIT and unexpected_keyword(exc, "sha256"):
            pytest.fail(
                "build_dependency has no sha256 parameter, so the downloaded archive is extracted "
                f"and built with no integrity check ({exc})"
            )
        raise


def assert_not_applied(
    marker: Path,
    watch: DirWatch,
    archive: Path,
    *,
    archive_should_exist: bool,
) -> None:
    problems: list[str] = []
    if marker.exists():
        problems.append(f"untrusted build script ran and wrote {marker.read_text().strip()!r}")
    if watch.created:
        problems.append(f"files were created under the build directory before refusal: {watch.created}")
    if watch.deleted:
        problems.append(f"files were deleted before refusal: {watch.deleted}")
    if archive_should_exist and not archive.exists():
        problems.append(f"pre-existing archive was removed: {archive}")
    if not archive_should_exist and archive.exists():
        problems.append(f"untrusted archive was stored at {archive}")
    assert not problems, "; ".join(problems)


def prepare_case(tmp: Path, mode_label: str) -> tuple[Path, Path, Path]:
    deps = tmp / "deps"
    build = deps / "build"
    build.mkdir(parents=True)
    marker = tmp / "pwned"
    os.environ["IFCOS_PWNED_MARKER"] = str(marker)
    os.environ["IFCOS_GOOD_MARKER"] = str(tmp / "good")
    return deps, build, marker


@pytest.mark.parametrize(
    ("mode", "tar_mode", "suffix", "entrypoint"),
    [
        ("autoconf", "w:bz2", ".tar.bz2", "configure"),
        ("autoconf", "w:gz", ".tgz", "configure"),
        ("autoconf", "w:gz", ".tar.gz", "configure"),
        ("bjam", "w:gz", ".tar.gz", "bootstrap.sh"),
        ("cmake", "w:xz", ".tar.xz", "CMakeLists.txt"),
    ],
)
def test_http_body_without_sha256_is_not_extracted_or_executed(
    build_all: dict[str, Any],
    tmp_path: Path,
    mode: str,
    tar_mode: str,
    suffix: str,
    entrypoint: str,
) -> None:
    script = CMAKE_LISTS if entrypoint == "CMakeLists.txt" else PWN_SCRIPT
    body = archive_bytes(tar_mode, payload_files(entrypoint, script))
    server = ArchiveServer(body)
    deps, build, marker = prepare_case(tmp_path, mode)
    download_name = f"pkg{suffix}"
    archive = build / download_name
    build_all["DEPS_DIR"] = str(deps)
    watch = DirWatch(build)
    try:
        try:
            call_build(
                build_all,
                name=f"probe-{mode}-{suffix.strip('.')}",
                mode=mode,
                base_url=server.base_url,
                download_name=download_name,
            )
        except Exception:
            pass
        assert server.paths, "build_dependency did not fetch the archive URL"
        assert_not_applied(marker, watch, archive, archive_should_exist=False)
    finally:
        watch.close()
        server.close()


def test_cached_archive_without_sha256_is_not_built(build_all: dict[str, Any], tmp_path: Path) -> None:
    body = archive_bytes("w:bz2", payload_files("configure", PWN_SCRIPT))
    deps, build, marker = prepare_case(tmp_path, "cache")
    download_name = "pkg.tar.bz2"
    archive = build / download_name
    archive.write_bytes(body)
    build_all["DEPS_DIR"] = str(deps)
    server = ArchiveServer(body)
    watch = DirWatch(build)
    try:
        try:
            call_build(
                build_all,
                name="probe-cache",
                mode="autoconf",
                base_url=server.base_url,
                download_name=download_name,
            )
        except Exception:
            pass
        assert_not_applied(marker, watch, archive, archive_should_exist=True)
    finally:
        watch.close()
        server.close()


def test_existing_extract_tree_without_sha256_is_not_built(build_all: dict[str, Any], tmp_path: Path) -> None:
    body = archive_bytes("w:bz2", payload_files("configure", PWN_SCRIPT))
    deps, build, marker = prepare_case(tmp_path, "tree")
    download_name = "pkg.tar.bz2"
    archive = build / download_name
    archive.write_bytes(body)
    tree = build / ROOT
    tree.mkdir()
    (tree / "configure").write_text(PWN_SCRIPT)
    (tree / "README").write_text("readme\n")
    build_all["DEPS_DIR"] = str(deps)
    watch = DirWatch(build)
    try:
        try:
            call_build(
                build_all,
                name="probe-tree",
                mode="autoconf",
                base_url="http://127.0.0.1:9/unused/",
                download_name=download_name,
            )
        except Exception:
            pass
        assert_not_applied(marker, watch, archive, archive_should_exist=True)
        assert (tree / "configure").exists(), "pre-existing extract tree was removed before refusal"
    finally:
        watch.close()


def test_sha256_mismatch_writes_nothing_and_does_not_run(build_all: dict[str, Any], tmp_path: Path) -> None:
    good = archive_bytes("w:bz2", payload_files("configure", GOOD_CONFIGURE))
    evil = archive_bytes("w:bz2", payload_files("configure", PWN_SCRIPT))
    server = ArchiveServer(evil)
    deps, build, marker = prepare_case(tmp_path, "mismatch")
    download_name = "pkg.tar.bz2"
    archive = build / download_name
    build_all["DEPS_DIR"] = str(deps)
    watch = DirWatch(build)
    try:
        try:
            call_build(
                build_all,
                name="probe-mismatch",
                mode="autoconf",
                base_url=server.base_url,
                download_name=download_name,
                sha256_hex=sha256(good),
            )
        except Exception:
            pass
        assert_not_applied(marker, watch, archive, archive_should_exist=False)
        assert not (tmp_path / "good").exists()
    finally:
        watch.close()
        server.close()


@pytest.mark.parametrize("bad_hash", [None, "", "0" * 64])
def test_bad_sha256_does_not_run_cached_or_downloaded_archive(
    build_all: dict[str, Any], tmp_path: Path, bad_hash: str | None
) -> None:
    evil = archive_bytes("w:bz2", payload_files("configure", PWN_SCRIPT))
    server = ArchiveServer(evil)
    deps, build, marker = prepare_case(tmp_path, "badhash")
    download_name = "pkg.tar.bz2"
    archive = build / download_name
    archive.write_bytes(evil)
    build_all["DEPS_DIR"] = str(deps)
    watch = DirWatch(build)
    try:
        try:
            call_build(
                build_all,
                name="probe-bad-hash",
                mode="autoconf",
                base_url=server.base_url,
                download_name=download_name,
                sha256_hex=bad_hash,
            )
        except Exception:
            pass
        assert_not_applied(marker, watch, archive, archive_should_exist=True)
    finally:
        watch.close()
        server.close()


def test_matching_sha256_builds_the_verified_bytes(build_all: dict[str, Any], tmp_path: Path) -> None:
    good = archive_bytes("w:bz2", payload_files("configure", GOOD_CONFIGURE))
    server = ArchiveServer(good)
    deps, _, marker = prepare_case(tmp_path, "match")
    build_all["DEPS_DIR"] = str(deps)
    try:
        call_build(
            build_all,
            name="probe-match",
            mode="autoconf",
            base_url=server.base_url,
            download_name="pkg.tar.bz2",
            sha256_hex=sha256(good),
        )
    finally:
        server.close()
    assert (tmp_path / "good").read_text().strip() == "GOOD"
    assert not marker.exists()
    assert server.paths == ["/src/pkg.tar.bz2"]


def test_second_read_of_archive_path_cannot_replace_verified_bytes(tmp_path: Path) -> None:
    """Fail if the digest is computed from one open and tar/configure uses a later open."""
    good = archive_bytes("w:bz2", payload_files("configure", GOOD_CONFIGURE))
    evil = archive_bytes("w:bz2", payload_files("configure", PWN_SCRIPT))
    alt = tmp_path / "replacement.tar.bz2"
    alt.write_bytes(evil)
    library = tmp_path / "toctou.so"
    source = tmp_path / "toctou.c"
    source.write_text(PRELOAD_C)
    compiled = subprocess.run(
        ["gcc", "-shared", "-fPIC", "-O2", "-o", str(library), str(source), "-ldl"],
        check=False,
        text=True,
        capture_output=True,
    )
    assert compiled.returncode == 0, compiled.stderr
    env = os.environ.copy()
    env.update(
        {
            "LD_PRELOAD": str(library),
            "IFCOS_TOCTOU_BASENAME": "pkg.tar.bz2",
            "IFCOS_TOCTOU_ALT": str(alt),
            "IFCOS_EXPECT_SHA256": sha256(good),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--toctou-child"],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    result_lines = [line for line in proc.stdout.splitlines() if line.startswith("TOCTOU_RESULT ")]
    assert result_lines, f"child failed\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    result = json.loads(result_lines[-1].split(" ", 1)[1])
    if result.get("unexpected_sha256"):
        pytest.fail(
            "build_dependency has no sha256 parameter, so it cannot bind the extracted bytes to a digest "
            f"({result.get('error')})"
        )
    assert result.get("pwned") is None, (
        f"a later open of the archive path supplied different bytes that were extracted and executed; result={result}"
    )
    assert result.get("good") == "GOOD", result


def _py_download_calls(source: str) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != "build_dependency":
            continue
        tool = next((kw.value for kw in node.keywords if kw.arg == "download_tool"), None)
        if isinstance(tool, ast.Name) and tool.id == "download_tool_git":
            continue
        if isinstance(tool, ast.Constant) and tool.value == "git":
            continue
        calls.append(node)
    return calls


def _download_url_expr(call: ast.Call) -> ast.AST:
    for kw in call.keywords:
        if kw.arg == "download_url":
            return kw.value
    if len(call.args) >= 4:
        return call.args[3]
    raise AssertionError(f"build_dependency call at line {call.lineno} has no download URL")


def _assignment_globals(build_all: dict[str, Any], source: str) -> dict[str, Any]:
    """Evaluate simple assignments from the build script, including ones inside target blocks."""
    globs = dict(build_all)

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Assign) and len(child.targets) == 1 and isinstance(child.targets[0], ast.Name):
                try:
                    globs[child.targets[0].id] = eval(
                        compile(ast.Expression(child.value), str(BUILD_ALL), "eval"), globs
                    )
                except Exception:
                    pass
            visit(child)

    visit(ast.parse(source))
    return globs


def test_every_py_download_declares_https_url_and_sha256(build_all: dict[str, Any]) -> None:
    source = build_all["_source"]
    calls = _py_download_calls(source)
    assert calls, "no download_tool=py build_dependency calls found"
    problems: list[str] = []
    versions = list(build_all["PYTHON_VERSIONS"])
    assigned = _assignment_globals(build_all, source)
    for call in calls:
        sha = next((kw.value for kw in call.keywords if kw.arg == "sha256"), None)
        if sha is None:
            problems.append(f"line {call.lineno}: sha256 is missing")
        elif isinstance(sha, ast.Constant) and (
            not isinstance(sha.value, str)
            or len(sha.value) != 64
            or any(c not in "0123456789abcdef" for c in sha.value)
        ):
            problems.append(f"line {call.lineno}: sha256 is not a 64-digit hex digest")
        url_expr = _download_url_expr(call)
        extras = [{}]
        names = {node.id for node in ast.walk(url_expr) if isinstance(node, ast.Name)}
        if "python_version_url" in names:
            extras = [{"python_version_url": version} for version in versions]
        for extra in extras:
            url = eval(compile(ast.Expression(url_expr), str(BUILD_ALL), "eval"), assigned, extra)
            if not (isinstance(url, str) and url.startswith("https://") and "http://" not in url):
                problems.append(f"line {call.lineno}: download URL is {url!r}")
    assert not problems, "\n".join(problems)


def _source_block(source: str, start: str, end: str) -> str:
    lines = source.splitlines()
    start_i = next(i for i, line in enumerate(lines) if line.startswith(start))
    end_i = next(i for i, line in enumerate(lines) if i > start_i and line.startswith(end))
    return "\n".join(lines[start_i:end_i]) + "\n"


def test_python_and_mpfr_call_sites_pass_https_urls_and_sha256(build_all: dict[str, Any]) -> None:
    workflow = LINUX_WORKFLOW.read_text()
    assert "uv run ./nix/build-all.py" in workflow
    saved_argv = sys.argv
    sys.argv = [
        "build-all.py",
        "-v",
        "--diskcleanup",
        "--ifcopenshell-shared",
        "--add-commit-sha",
        "--build-cfg",
        "Release",
        "--use-ninja",
    ]
    try:
        args, _dynamic = build_all["parse_args"]()
    finally:
        sys.argv = saved_argv
    assert list(args.explicit_targets) == []
    assert "python" in build_all["dependency_tree"]
    assert "cgal" in build_all["dependency_tree"]

    recorded: list[tuple[Any, ...]] = []
    original_build = build_all["build_dependency"]
    original_run = build_all["run"]

    def recording_build(*args: Any, **kwargs: Any) -> None:
        url = kwargs.get("download_url", args[3] if len(args) > 3 else None)
        name = kwargs.get("download_name", args[4] if len(args) > 4 else None)
        recorded.append((url, name, kwargs.get("sha256")))

    def quiet_run(*args: Any, **kwargs: Any) -> str:
        return ""

    saved_targets = set(build_all["targets"])
    saved_env = os.environ.copy()
    build_all["targets"].update({"python", "cgal"})
    build_all["build_dependency"] = recording_build
    build_all["run"] = quiet_run
    try:
        exec(_source_block(build_all["_source"], "def python_consider_rc", 'if "boost" in targets'), build_all)
        exec(_source_block(build_all["_source"], 'if "cgal" in targets', 'if "usd" in targets'), build_all)
    finally:
        build_all["build_dependency"] = original_build
        build_all["run"] = original_run
        build_all["targets"].clear()
        build_all["targets"].update(saved_targets)
        os.environ.clear()
        os.environ.update(saved_env)

    python_calls = [item for item in recorded if isinstance(item[1], str) and item[1].startswith("Python-")]
    mpfr_calls = [item for item in recorded if isinstance(item[1], str) and item[1].startswith("mpfr-")]
    assert python_calls, recorded
    assert mpfr_calls, recorded
    problems = []
    for url, name, digest in python_calls + mpfr_calls:
        if not (isinstance(url, str) and url.startswith("https://")):
            problems.append(f"{name} URL is {url!r}")
        if not (isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)):
            problems.append(f"{name} sha256 is {digest!r}")
    assert not problems, "\n".join(problems)


def toctou_child() -> None:
    deps = Path("/tmp/ifcos-toctou-child")
    shutil.rmtree(deps, ignore_errors=True)
    deps.mkdir()
    ns = load_build_all(deps)
    good = archive_bytes("w:bz2", payload_files("configure", GOOD_CONFIGURE))
    server = ArchiveServer(good)
    case = deps / "case"
    case_deps, _, _marker = prepare_case(case, "toctou")
    ns["DEPS_DIR"] = str(case_deps)
    result: dict[str, Any] = {"pwned": None, "good": None, "error": None, "unexpected_sha256": False}
    try:
        call_build(
            ns,
            name="probe-toctou",
            mode="autoconf",
            base_url=server.base_url,
            download_name="pkg.tar.bz2",
            sha256_hex=os.environ["IFCOS_EXPECT_SHA256"],
        )
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        text = str(exc)
        result["unexpected_sha256"] = unexpected_keyword(exc, "sha256") or "no sha256 parameter" in text
    finally:
        server.close()
    pwned = case / "pwned"
    good_marker = case / "good"
    if pwned.exists():
        result["pwned"] = pwned.read_text().strip()
    if good_marker.exists():
        result["good"] = good_marker.read_text().strip()
    print("TOCTOU_RESULT " + json.dumps(result), flush=True)


if __name__ == "__main__":
    if "--toctou-child" in sys.argv:
        toctou_child()
