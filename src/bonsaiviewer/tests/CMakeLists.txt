# This file was generated with the assistance of an AI coding tool.
# Standalone spec tests for .rdbview extraction. Not wired into the viewer
# build: that target pulls the geometry kernel, which these checks do not run.
cmake_minimum_required(VERSION 3.16)
project(rdbview_path_traversal_tests LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT QT_DIR)
    message(FATAL_ERROR "Set QT_DIR to a Qt 6.8 prefix (the directory containing lib/cmake/Qt6).")
endif()
list(PREPEND CMAKE_PREFIX_PATH "${QT_DIR}")
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets PATHS "${QT_DIR}")

add_executable(rdbview_path_traversal_test test_rdbview_path_traversal.cpp)
target_compile_options(rdbview_path_traversal_test PRIVATE -ffunction-sections -fdata-sections)
target_link_options(rdbview_path_traversal_test PRIVATE -Wl,--gc-sections)
target_include_directories(rdbview_path_traversal_test PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/..
    /usr/include/eigen3
)
target_link_libraries(rdbview_path_traversal_test PRIVATE Qt6::Core Qt6::CorePrivate Qt6::Gui Qt6::Widgets)
