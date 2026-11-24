# This file was generated with the assistance of an AI coding tool.
# Standalone spec tests for unvalidated sidecar triangle indices.
# They are expected to fail until the viewer stops storing and chasing
# out-of-range indices. Configure and run:
#
#   cmake -S src/ifcviewer/tests/triangle_index_oob -B build/triangle-index-oob
#   cmake --build build/triangle-index-oob
#   ctest --test-dir build/triangle-index-oob --output-on-failure
cmake_minimum_required(VERSION 3.16)
project(triangle_index_oob_tests CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
enable_testing()

find_package(Eigen3 3.3.9 REQUIRED)
find_package(Threads REQUIRED)

find_path(ZSTD_INCLUDE_DIR zstd.h)
find_library(ZSTD_LIBRARY NAMES zstd)
if(NOT ZSTD_INCLUDE_DIR OR NOT ZSTD_LIBRARY)
    message(FATAL_ERROR "libzstd development files are required")
endif()

set(WGPU_NATIVE_VERSION "v29.0.0.0")
set(_wgpu_archive "wgpu-linux-x86_64-release.zip")
include(FetchContent)
FetchContent_Declare(
    wgpu_native
    URL https://github.com/gfx-rs/wgpu-native/releases/download/${WGPU_NATIVE_VERSION}/${_wgpu_archive}
)
FetchContent_MakeAvailable(wgpu_native)
set(WGPU_INCLUDE "${wgpu_native_SOURCE_DIR}/include")
set(WGPU_LIB "${wgpu_native_SOURCE_DIR}/lib/libwgpu_native.so")
find_program(PATCHELF_EXECUTABLE patchelf)
if(PATCHELF_EXECUTABLE)
    execute_process(
        COMMAND ${PATCHELF_EXECUTABLE} --set-soname libwgpu_native.so "${WGPU_LIB}"
        RESULT_VARIABLE _patchelf_rc)
    if(NOT _patchelf_rc EQUAL 0)
        message(FATAL_ERROR "patchelf failed on libwgpu_native.so")
    endif()
endif()

set(VIEWER "${CMAKE_CURRENT_SOURCE_DIR}/../..")
set(HELPERS "${VIEWER}/../helpers")
set(CORE_SOURCES
    ${VIEWER}/AxisIndicatorRenderer.cpp
    ${VIEWER}/BufferPool.cpp
    ${VIEWER}/ChunkPlanner.cpp
    ${VIEWER}/InstanceCompose.cpp
    ${VIEWER}/LodBuilder.cpp
    ${VIEWER}/FederationMath.cpp
    ${VIEWER}/GpuAllocScope.cpp
    ${VIEWER}/GpuBudget.cpp
    ${VIEWER}/GpuMemory.cpp
    ${VIEWER}/SidecarCache.cpp
    ${VIEWER}/SidecarCompress.cpp
    ${VIEWER}/StreamingLoader.cpp
    ${VIEWER}/StreamingThread.cpp
    ${VIEWER}/SectionGizmoRenderer.cpp
    ${VIEWER}/ViewportCore.cpp
    ${VIEWER}/WgpuDynamicOffsets.cpp
    ${HELPERS}/unit_convert.cpp
    ${HELPERS}/geolocation_transform.cpp
)

add_library(viewer_core_for_tests STATIC ${CORE_SOURCES})
target_include_directories(viewer_core_for_tests PUBLIC
    ${VIEWER} ${HELPERS} ${WGPU_INCLUDE} ${ZSTD_INCLUDE_DIR})
target_link_libraries(viewer_core_for_tests PUBLIC
    Eigen3::Eigen Threads::Threads ${ZSTD_LIBRARY} ${WGPU_LIB})
target_compile_options(viewer_core_for_tests PRIVATE
    -fsanitize=address,undefined -fno-omit-frame-pointer -g)
target_link_options(viewer_core_for_tests PUBLIC
    -fsanitize=address,undefined)

function(add_core_test name src)
    add_executable(${name} ${src})
    target_link_libraries(${name} PRIVATE viewer_core_for_tests)
    target_compile_options(${name} PRIVATE
        -fsanitize=address,undefined -fno-omit-frame-pointer -g)
    target_link_options(${name} PRIVATE
        -Wl,-rpath,${wgpu_native_SOURCE_DIR}/lib)
    add_test(NAME ${name} COMMAND ${name})
    set_tests_properties(${name} PROPERTIES
        ENVIRONMENT "ASAN_OPTIONS=detect_leaks=0:halt_on_error=1;UBSAN_OPTIONS=halt_on_error=1")
endfunction()

add_core_test(test_sidecar_index_cache test_sidecar_index_cache.cpp)
# The queue write inside applyStreamedChunk must not dereference the fake
# pool buffer. The index vector itself is not modified there.
target_link_options(test_sidecar_index_cache PRIVATE -Wl,--wrap=wgpuQueueWriteBuffer)
add_core_test(test_raycast_index_bounds test_raycast_index_bounds.cpp)

set(STUBS "${CMAKE_CURRENT_SOURCE_DIR}/stubs")

function(rewrite_measurement src dst)
    file(READ "${src}" txt)
    string(REPLACE "#include \"ViewportWindow.h\"" "#include \"meas_viewport.h\"" txt "${txt}")
    string(REPLACE "#include \"OverlayRenderer.h\"" "#include \"meas_overlay.h\"" txt "${txt}")
    string(REPLACE "#include <QString>" "#include \"meas_qt.h\"" txt "${txt}")
    string(REPLACE "#include <QStringList>" "#include \"meas_qt.h\"" txt "${txt}")
    string(REPLACE "#include <QDebug>" "#include \"meas_qt.h\"" txt "${txt}")
    string(REPLACE "#include <QtGlobal>" "#include \"meas_qt.h\"" txt "${txt}")
    string(REPLACE "#include <QtMath>" "#include \"meas_qt.h\"" txt "${txt}")
    file(WRITE "${dst}" "${txt}")
endfunction()

set(RE_IFC "${CMAKE_CURRENT_BINARY_DIR}/rewritten_ifcviewer")
set(RE_BONSAI "${CMAKE_CURRENT_BINARY_DIR}/rewritten_bonsai")
file(MAKE_DIRECTORY "${RE_IFC}" "${RE_BONSAI}")
rewrite_measurement("${VIEWER}/AreaMeasurement.cpp" "${RE_IFC}/AreaMeasurement.cpp")
rewrite_measurement("${VIEWER}/LengthMeasurement.cpp" "${RE_IFC}/LengthMeasurement.cpp")
rewrite_measurement("${VIEWER}/LengthMeasurement.h" "${RE_IFC}/LengthMeasurement.h")
rewrite_measurement("${VIEWER}/../bonsaiviewer/Measurement.cpp" "${RE_BONSAI}/Measurement.cpp")
rewrite_measurement("${VIEWER}/../bonsaiviewer/Measurement.h" "${RE_BONSAI}/Measurement.h")

add_executable(test_ifcviewer_measure
    test_ifcviewer_measure.cpp
    "${RE_IFC}/AreaMeasurement.cpp"
    "${RE_IFC}/LengthMeasurement.cpp")
target_include_directories(test_ifcviewer_measure PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}" "${STUBS}" "${RE_IFC}" "${VIEWER}")
target_compile_options(test_ifcviewer_measure PRIVATE
    -fsanitize=address,undefined -fno-omit-frame-pointer -g)
target_link_options(test_ifcviewer_measure PRIVATE -fsanitize=address,undefined)
foreach(mode area length area-valid length-valid)
    add_test(NAME test_ifcviewer_measure_${mode} COMMAND test_ifcviewer_measure ${mode})
    set_tests_properties(test_ifcviewer_measure_${mode} PROPERTIES
        ENVIRONMENT "ASAN_OPTIONS=detect_leaks=0:halt_on_error=1;UBSAN_OPTIONS=halt_on_error=1")
endforeach()

add_executable(test_bonsai_measure
    test_bonsai_measure.cpp
    "${RE_BONSAI}/Measurement.cpp")
target_include_directories(test_bonsai_measure PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}" "${STUBS}" "${RE_BONSAI}" "${VIEWER}/../bonsaiviewer")
target_link_libraries(test_bonsai_measure PRIVATE Eigen3::Eigen)
target_compile_options(test_bonsai_measure PRIVATE
    -fsanitize=address,undefined -fno-omit-frame-pointer -g)
target_link_options(test_bonsai_measure PRIVATE -fsanitize=address,undefined)
foreach(mode area length volume area-valid length-valid volume-valid)
    add_test(NAME test_bonsai_measure_${mode} COMMAND test_bonsai_measure ${mode})
    set_tests_properties(test_bonsai_measure_${mode} PROPERTIES
        ENVIRONMENT "ASAN_OPTIONS=detect_leaks=0:halt_on_error=1;UBSAN_OPTIONS=halt_on_error=1")
endforeach()
