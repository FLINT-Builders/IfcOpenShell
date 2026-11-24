#!/bin/bash
# This file was generated with the assistance of an AI coding tool.
# Build and run the 32-bit element string-table bounds tests.
# The web viewer is wasm32; this uses -m32 so size_t matches that build.
# Fails while a wrapping offset+length is still accepted.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SRC="$ROOT/src/ifcviewer"
CACHE="${ELEMENT_STRING_BOUNDS_CACHE:-/tmp/ifcview-string-bounds-deps}"
mkdir -p "$CACHE"

if ! g++ -m32 -x c++ -c -o /dev/null - <<< 'int x;' >/dev/null 2>&1; then
    echo "g++ -m32 is required (install g++-multilib)" >&2
    exit 1
fi

EIGEN_DIR=""
for candidate in /usr/include/eigen3 /usr/local/include/eigen3; do
    if [[ -f "$candidate/Eigen/Dense" ]]; then
        EIGEN_DIR="$candidate"
        break
    fi
done
if [[ -z "$EIGEN_DIR" ]]; then
    echo "Eigen3 headers not found (install libeigen3-dev)" >&2
    exit 1
fi

WGPU_INC="$CACHE/wgpu/include"
if [[ ! -f "$WGPU_INC/webgpu/webgpu.h" ]]; then
    echo "fetching wgpu-native v29.0.0.0 headers"
    curl -fsSL -o "$CACHE/wgpu.zip" -L \
        "https://github.com/gfx-rs/wgpu-native/releases/download/v29.0.0.0/wgpu-linux-x86_64-release.zip"
    rm -rf "$CACHE/wgpu"
    unzip -q "$CACHE/wgpu.zip" -d "$CACHE/wgpu"
fi

ZSTD_A="$CACHE/zstd-1.5.7/lib/libzstd.a"
ZSTD_INC="$CACHE/zstd-1.5.7/lib"
if [[ ! -f "$ZSTD_A" ]]; then
    echo "building zstd 1.5.7 for -m32"
    curl -fsSL -o "$CACHE/zstd.tar.gz" \
        "https://github.com/facebook/zstd/releases/download/v1.5.7/zstd-1.5.7.tar.gz"
    tar -xzf "$CACHE/zstd.tar.gz" -C "$CACHE"
    make -C "$CACHE/zstd-1.5.7/lib" libzstd.a CC="gcc -m32" -j"$(nproc)"
fi

python3 - "$SRC/../ifcviewer-web/main_web.cpp" "$CACHE/append_json_string.cpp" << 'PY'
import pathlib, re, sys
source = pathlib.Path(sys.argv[1]).read_text()
match = re.search(r"^void appendJsonString\b.*?^\}\n", source, re.M | re.S)
if not match:
    raise SystemExit("appendJsonString not found in main_web.cpp")
path = pathlib.Path(sys.argv[2])
path.write_text(
    "#include <cstdint>\n#include <cstdio>\n#include <string>\n"
    + match.group(0)
)
PY

OUT="$CACHE/element_string_bounds"
CXXFLAGS=(
    -m32 -std=c++17 -O0 -ffunction-sections -fdata-sections
    -I "$SRC" -I "$EIGEN_DIR" -I "$WGPU_INC" -I "$ZSTD_INC"
)
g++ "${CXXFLAGS[@]}" -c -o "$CACHE/test_element_string_bounds.o" \
    "$SRC/tests/test_element_string_bounds.cpp"
g++ "${CXXFLAGS[@]}" -c -o "$CACHE/ViewportCore.o" "$SRC/ViewportCore.cpp"
g++ "${CXXFLAGS[@]}" -c -o "$CACHE/StreamingLoader.o" "$SRC/StreamingLoader.cpp"
g++ "${CXXFLAGS[@]}" -c -o "$CACHE/SidecarCompress.o" "$SRC/SidecarCompress.cpp"
g++ "${CXXFLAGS[@]}" -c -o "$CACHE/InstanceCompose.o" "$SRC/InstanceCompose.cpp"
g++ "${CXXFLAGS[@]}" -c -o "$CACHE/append_json_string.o" "$CACHE/append_json_string.cpp"

g++ -m32 -Wl,--gc-sections -o "$OUT" \
    "$CACHE/test_element_string_bounds.o" \
    "$CACHE/ViewportCore.o" \
    "$CACHE/StreamingLoader.o" \
    "$CACHE/SidecarCompress.o" \
    "$CACHE/InstanceCompose.o" \
    "$CACHE/append_json_string.o" \
    "$ZSTD_A" \
    -pthread

"$OUT"
