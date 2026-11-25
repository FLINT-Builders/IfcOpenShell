#!/bin/sh
# This file was generated with the assistance of an AI coding tool.
# The cases that describe a too-short RefLatitude, RefLongitude, or
# TrueNorth list fail until those indexes are guarded.
set -eu
binary=${1:-./test_gltf_georef_bounds}
export ASAN_OPTIONS="${ASAN_OPTIONS:-halt_on_error=1:detect_leaks=0:abort_on_error=1}"
exec "$binary"
