# This file was generated with the assistance of an AI coding tool.

find_package(LibXml2 REQUIRED)
find_package(OpenCASCADE REQUIRED)

add_executable(test_svg_globalid_escape
    test_svg_globalid_escape.cpp
)
target_include_directories(test_svg_globalid_escape PRIVATE "${CMAKE_SOURCE_DIR}/../src")
target_include_directories(test_svg_globalid_escape SYSTEM PRIVATE ${OpenCASCADE_INCLUDE_DIR})
target_compile_definitions(test_svg_globalid_escape PRIVATE
    IfcSchema=Ifc4
    "IFCGEOM_TEST_SCHEMA_HEADER=\"ifcparse/schemas/Ifc4.h\""
)
target_link_libraries(test_svg_globalid_escape PRIVATE
    Catch2::Catch2WithMain
    geometry_serializer_svg
    IfcGeom
    IfcParse
    parse_schema_ifc4
    LibXml2::LibXml2
    ${OpenCASCADE_LIBRARIES}
)
add_dependencies(test_svg_globalid_escape
    geometry_mapping_ifc4
    geometry_kernel_opencascade
    parse_schema_ifc4
)
catch_discover_tests(test_svg_globalid_escape
    DL_PATHS
        $<TARGET_FILE_DIR:Catch2::Catch2>
        $<TARGET_FILE_DIR:Catch2::Catch2WithMain>
        $<TARGET_FILE_DIR:IfcGeom>
        $<TARGET_FILE_DIR:IfcParse>
        $<TARGET_FILE_DIR:parse_schema_ifc4>
        $<TARGET_FILE_DIR:plugin>
        $<TARGET_FILE_DIR:geometry_serializer_svg>
        $<TARGET_FILE_DIR:IfcGeom>
)
