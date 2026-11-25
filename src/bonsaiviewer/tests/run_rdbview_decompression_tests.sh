#!/usr/bin/env bash
# This file was generated with the assistance of an AI coding tool.
# Build and run the .rdbview decompression tests against the sources in this tree.
# Requires Qt 6.8 private headers (the viewer build pins 6.8.3), Eigen, Boost,
# and zlib. The tests exit non-zero until extraction refuses the bombs below.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
QT_DIR="${QT_DIR:-/tmp/qt/6.8.3/gcc_64}"
BUILD_DIR="${BUILD_DIR:-/tmp/rdbview-decompression-tests}"
SRC="$ROOT/src"

if [[ ! -f "$QT_DIR/lib/libQt6Core.so" ]]; then
    echo "Qt 6.8 not found at QT_DIR=$QT_DIR" >&2
    exit 2
fi

mkdir -p "$BUILD_DIR/moc"
QT_INC=(
    -I"$QT_DIR/include"
    -I"$QT_DIR/include/QtCore" -I"$QT_DIR/include/QtCore/6.8.3" -I"$QT_DIR/include/QtCore/6.8.3/QtCore"
    -I"$QT_DIR/include/QtGui" -I"$QT_DIR/include/QtGui/6.8.3" -I"$QT_DIR/include/QtGui/6.8.3/QtGui"
    -I"$QT_DIR/include/QtWidgets" -I"$QT_DIR/include/QtWidgets/6.8.3" -I"$QT_DIR/include/QtWidgets/6.8.3/QtWidgets"
    -I"$QT_DIR/include/QtSvg" -I"$QT_DIR/include/QtSvg/6.8.3" -I"$QT_DIR/include/QtSvg/6.8.3/QtSvg"
    -I"$SRC/bonsaiviewer/tests/stubs"
    -I/usr/include/eigen3
    -I"$SRC/helpers"
    -I"$SRC/ifcviewer"
)
FLAGS=(-std=c++17 -fPIC -ffunction-sections -fdata-sections -DQT_NO_DEBUG -DQT_CORE_LIB -DQT_GUI_LIB -DQT_WIDGETS_LIB -DQT_SVG_LIB)

moc() {
    local header="$1"
    local out="$2"
    "$QT_DIR/libexec/moc" "${QT_INC[@]}" "$header" -o "$out"
}

moc "$SRC/bonsaiviewer/SessionState.h" "$BUILD_DIR/moc/moc_session.cpp"
moc "$SRC/bonsaiviewer/ElementRegistry.h" "$BUILD_DIR/moc/moc_elements.cpp"
moc "$SRC/ifcviewer/Federation.h" "$BUILD_DIR/moc/moc_federation.cpp"
moc "$SRC/bonsaiviewer/modules/connectors/Registry.h" "$BUILD_DIR/moc/moc_registry.cpp"
moc "$SRC/bonsaiviewer/modules/connectors/Process.h" "$BUILD_DIR/moc/moc_process.cpp"
moc "$SRC/ifcviewer/SceneLoader.h" "$BUILD_DIR/moc/moc_sceneloader.cpp"
moc "$SRC/ifcviewer/ViewportWindow.h" "$BUILD_DIR/moc/moc_viewport.cpp"

OBJS=()
compile() {
    local src="$1"
    local rel="${src#$ROOT/}"
    local obj="$BUILD_DIR/${rel//\//_}.o"
    mkdir -p "$(dirname "$obj")"
    g++ "${FLAGS[@]}" "${QT_INC[@]}" -c "$src" -o "$obj"
    OBJS+=("$obj")
}

compile "$SRC/bonsaiviewer/modules/models/Commands.cpp"
compile "$SRC/bonsaiviewer/modules/project/Commands.cpp"
compile "$SRC/bonsaiviewer/SessionState.cpp"
compile "$SRC/bonsaiviewer/ElementRegistry.cpp"
compile "$SRC/ifcviewer/Federation.cpp"
compile "$SRC/bonsaiviewer/modules/connectors/Registry.cpp"
compile "$SRC/bonsaiviewer/modules/connectors/Discovery.cpp"
compile "$SRC/bonsaiviewer/modules/connectors/Process.cpp"
compile "$SRC/bonsaiviewer/tests/test_rdbview_decompression.cpp"
compile "$SRC/bonsaiviewer/tests/scene_loader_stub.cpp"
compile "$SRC/bonsaiviewer/tests/viewport_window_stub.cpp"
compile "$BUILD_DIR/moc/moc_session.cpp"
compile "$BUILD_DIR/moc/moc_elements.cpp"
compile "$BUILD_DIR/moc/moc_federation.cpp"
compile "$BUILD_DIR/moc/moc_registry.cpp"
compile "$BUILD_DIR/moc/moc_process.cpp"
compile "$BUILD_DIR/moc/moc_sceneloader.cpp"
compile "$BUILD_DIR/moc/moc_viewport.cpp"

g++ -Wl,--gc-sections -Wl,-rpath,"$QT_DIR/lib" "${OBJS[@]}" \
    -o "$BUILD_DIR/rdbview_decompression_tests" \
    -L"$QT_DIR/lib" -lQt6Widgets -lQt6Gui -lQt6Core -lz -lpthread

export LD_LIBRARY_PATH="$QT_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export QT_PLUGIN_PATH="$QT_DIR/plugins"
"$BUILD_DIR/rdbview_decompression_tests"
