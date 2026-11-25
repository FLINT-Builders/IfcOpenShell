# This file was generated with the assistance of an AI coding tool.

find_package(nlohmann_json 3.6.1 REQUIRED)
# The product CMake gate asks for PROJ 9.4.1. This test links the PROJ that
# provides the same calls setup_georeferencing makes; 9.4.0 is sufficient.
find_package(PROJ REQUIRED)

add_executable(test_gltf_georef_bounds
    test_gltf_georef_bounds.cpp
    ../gltf_serializer.cpp
)

target_compile_definitions(test_gltf_georef_bounds PRIVATE
    WITH_GLTF
    WITH_PROJ
    SERIALIZERS_EXPORTS
    _GLIBCXX_ASSERTIONS
)

target_include_directories(test_gltf_georef_bounds PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../..
    ${CMAKE_CURRENT_SOURCE_DIR}/..
)

# Instrument the serializer translation unit so an unchecked vector index
# aborts this test. The flags are part of the test, not the product build.
target_compile_options(test_gltf_georef_bounds PRIVATE
    -fsanitize=address
    -fno-omit-frame-pointer
    -fno-sanitize-recover=address
    -g
    -O1
)

target_link_options(test_gltf_georef_bounds PRIVATE
    -fsanitize=address
)

target_link_libraries(test_gltf_georef_bounds PRIVATE
    IfcGeom
    IfcParse
    nlohmann_json::nlohmann_json
    ${PROJ_LIBRARIES}
    ${Boost_LIBRARIES}
)

if(NOT TARGET parse_schema_ifc4)
    message(FATAL_ERROR "test_gltf_georef_bounds reads IFC4 files. SCHEMA_VERSIONS must include 4.")
endif()
add_dependencies(test_gltf_georef_bounds parse_schema_ifc4)
