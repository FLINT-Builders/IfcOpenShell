# This file was generated with the assistance of an AI coding tool.
#
# Standalone spec tests for cyclic spatial aggregation in the Bonsai viewer.
# They are not wired into the main tree: building them needs IfcParse (IFC4)
# and the wgpu-native headers the viewer headers include. They do not link
# the GPU library.
#
#   cmake -S cmake -B build-parse -G Ninja \
#     -DBUILD_IFCGEOM=OFF -DBUILD_IFCPYTHON=OFF -DBUILD_CONVERT=OFF \
#     -DBUILD_GEOMSERVER=OFF -DBUILD_EXAMPLES=OFF -DWITH_CGAL=OFF \
#     -DWITH_OPENCASCADE=OFF -DCOLLADA_SUPPORT=OFF -DSCHEMA_VERSIONS=4
#   cmake --build build-parse --target IfcParse parse_schema_ifc4 -j
#
#   cmake -S src/bonsaiviewer/tests -B build-spatial-tests -G Ninja \
#     -DIFCOPENSHELL_BUILD_DIR=$PWD/build-parse \
#     -DWGPU_INCLUDE_DIR=/path/to/wgpu-native/include
#   cmake --build build-spatial-tests -j
#   QT_QPA_PLATFORM=offscreen ./build-spatial-tests/spatial_hierarchy_cycle_test
#
# The cases that open a cyclic file fail until the walk stops repeating an
# element that is already on the path.

cmake_minimum_required(VERSION 3.21)
project(spatial_hierarchy_cycle_test LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

if(NOT IFCOPENSHELL_BUILD_DIR)
    message(FATAL_ERROR "Set IFCOPENSHELL_BUILD_DIR to a build that produced libifcopenshell.parse and ifcopenshell_parse_schema_ifc4")
endif()
if(NOT WGPU_INCLUDE_DIR)
    message(FATAL_ERROR "Set WGPU_INCLUDE_DIR to the wgpu-native include directory (it contains webgpu/webgpu.h)")
endif()

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Svg)
find_package(Eigen3 REQUIRED)

set(REPO_SRC ${CMAKE_CURRENT_SOURCE_DIR}/../..)
set(VIEWER_SRC ${CMAKE_CURRENT_SOURCE_DIR}/..)

add_executable(spatial_hierarchy_cycle_test
    spatial_hierarchy_cycle_test.cpp
    spatial_hierarchy_cycle_shims.cpp
    ${VIEWER_SRC}/SessionState.h
    ${REPO_SRC}/ifcviewer/SceneLoader.h
    ${REPO_SRC}/ifcviewer/GeometryStreamer.h
    ${VIEWER_SRC}/modules/spatial_hierarchy/View.cpp
    ${VIEWER_SRC}/modules/spatial_hierarchy/Panel.cpp
    ${VIEWER_SRC}/components/Panel.cpp
    ${VIEWER_SRC}/components/Section.cpp
    ${VIEWER_SRC}/components/SvgIcon.cpp
    ${VIEWER_SRC}/ViewerSettings.cpp
    ${REPO_SRC}/helpers/element.cpp
    ${REPO_SRC}/helpers/placement.cpp
)

target_compile_definitions(spatial_hierarchy_cycle_test PRIVATE
    IFCOPENSHELL_HELPER_SCHEMA_4
)

target_include_directories(spatial_hierarchy_cycle_test PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${VIEWER_SRC}
    ${REPO_SRC}/helpers
    ${REPO_SRC}
    ${WGPU_INCLUDE_DIR}
    ${Eigen3_INCLUDE_DIRS}
)

target_link_libraries(spatial_hierarchy_cycle_test PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    Qt6::Svg
    Eigen3::Eigen
    ${IFCOPENSHELL_BUILD_DIR}/ifcparse/libifcopenshell.parse.so
    ${IFCOPENSHELL_BUILD_DIR}/plugin/libifcopenshell.plugin.so
    ${IFCOPENSHELL_BUILD_DIR}/ifcparse/ifcopenshell_parse_schema_ifc4.so
)

set_target_properties(spatial_hierarchy_cycle_test PROPERTIES
    BUILD_RPATH "${IFCOPENSHELL_BUILD_DIR}/ifcparse;${IFCOPENSHELL_BUILD_DIR}/plugin"
)

# Keep the recursive walk from being rewritten into a loop so a cycle faults
# the test instead of spinning until the harness times out.
target_compile_options(spatial_hierarchy_cycle_test PRIVATE -O0 -fno-optimize-sibling-calls)
