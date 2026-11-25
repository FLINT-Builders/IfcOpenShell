#!/bin/sh
# Build and run the .rdbview path-traversal spec tests.
# QT_DIR is the Qt 6.8 prefix that contains lib/cmake/Qt6 (the viewer builds
# against Qt 6.8.3). Example:
#   QT_DIR=/opt/Qt/6.8.3/gcc_64 src/bonsaiviewer/tests/run_rdbview_path_traversal.sh
set -eu
cd "$(dirname "$0")"
if [ -z "${QT_DIR:-}" ]; then
    echo "Set QT_DIR to a Qt 6.8 prefix (directory containing lib/cmake/Qt6)." >&2
    exit 2
fi
build_dir="${BUILD_DIR:-$(pwd)/build-rdbview-path}"
# c++ may be a clang that does not link libstdc++; the tree builds with g++.
export CXX="${CXX:-g++}"
cmake -S . -B "$build_dir" -DQT_DIR="$QT_DIR"
cmake --build "$build_dir"
"$build_dir/rdbview_path_traversal_test"
