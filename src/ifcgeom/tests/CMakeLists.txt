# This file was generated with the assistance of an AI coding tool.

add_executable(test_ifcopenshell_geometry
    test_ifcopenshell_geometry.cpp
)
list(GET SCHEMA_VERSIONS -1 IFCGEOM_TEST_SCHEMA_VERSION)
set(IFCGEOM_TEST_SCHEMA_TARGET parse_schema_ifc${IFCGEOM_TEST_SCHEMA_VERSION})
set(IFCGEOM_TEST_MAPPING_TARGET geometry_mapping_ifc${IFCGEOM_TEST_SCHEMA_VERSION})
if(NOT TARGET ${IFCGEOM_TEST_SCHEMA_TARGET})
    message(FATAL_ERROR "test_ifcopenshell_geometry requires ${IFCGEOM_TEST_SCHEMA_TARGET}.")
endif()
if(NOT TARGET ${IFCGEOM_TEST_MAPPING_TARGET})
    message(FATAL_ERROR "test_ifcopenshell_geometry requires ${IFCGEOM_TEST_MAPPING_TARGET}.")
endif()
target_include_directories(test_ifcopenshell_geometry PRIVATE "${CMAKE_SOURCE_DIR}/../src")
target_compile_definitions(test_ifcopenshell_geometry PRIVATE
    IfcSchema=Ifc${IFCGEOM_TEST_SCHEMA_VERSION}
    "IFCGEOM_TEST_SCHEMA_HEADER=\"ifcparse/schemas/Ifc${IFCGEOM_TEST_SCHEMA_VERSION}.h\""
)
target_link_libraries(test_ifcopenshell_geometry PRIVATE
    Catch2::Catch2WithMain
    IfcGeom
    IfcParse
    ${IFCGEOM_TEST_SCHEMA_TARGET}
)
add_dependencies(test_ifcopenshell_geometry ${IFCGEOM_TEST_MAPPING_TARGET} geometry_kernel_passthrough)
catch_discover_tests(test_ifcopenshell_geometry
    DL_PATHS
        $<TARGET_FILE_DIR:Catch2::Catch2>
        $<TARGET_FILE_DIR:Catch2::Catch2WithMain>
        $<TARGET_FILE_DIR:IfcGeom>
        $<TARGET_FILE_DIR:IfcParse>
        $<TARGET_FILE_DIR:${IFCGEOM_TEST_SCHEMA_TARGET}>
        $<TARGET_FILE_DIR:plugin>
        # Catch2 discovery uses DL_PATHS in order; CTest PATH prepends reverse it.
        $<TARGET_FILE_DIR:IfcGeom>
)

# Bounds-checked libstdc++ vector::operator[] so a one-element coordinate or
# direction list aborts inside the mapping plugin instead of silently reading
# past the allocation. The check is inline in the library headers, so the
# mapping plugin itself has to be built with it. IfcCurveSegment exists on IFC4X3.
if(IFCGEOM_TEST_SCHEMA_VERSION STREQUAL "4x3_add2")
    target_compile_definitions(${IFCGEOM_TEST_MAPPING_TARGET} PRIVATE _GLIBCXX_ASSERTIONS)

    add_executable(test_curve_segment_line_bounds
        test_curve_segment_line_bounds.cpp
    )
    target_include_directories(test_curve_segment_line_bounds PRIVATE "${CMAKE_SOURCE_DIR}/../src")
    target_compile_definitions(test_curve_segment_line_bounds PRIVATE
        _GLIBCXX_ASSERTIONS
        IfcSchema=Ifc4x3_add2
        "IFCGEOM_TEST_SCHEMA_HEADER=\"ifcparse/schemas/Ifc4x3_add2.h\""
    )
    target_link_libraries(test_curve_segment_line_bounds PRIVATE
        Catch2::Catch2WithMain
        IfcGeom
        IfcParse
        ${IFCGEOM_TEST_SCHEMA_TARGET}
    )
    add_dependencies(test_curve_segment_line_bounds ${IFCGEOM_TEST_MAPPING_TARGET} geometry_kernel_passthrough)
    catch_discover_tests(test_curve_segment_line_bounds
        DL_PATHS
            $<TARGET_FILE_DIR:Catch2::Catch2>
            $<TARGET_FILE_DIR:Catch2::Catch2WithMain>
            $<TARGET_FILE_DIR:IfcGeom>
            $<TARGET_FILE_DIR:IfcParse>
            $<TARGET_FILE_DIR:${IFCGEOM_TEST_SCHEMA_TARGET}>
            $<TARGET_FILE_DIR:plugin>
            $<TARGET_FILE_DIR:IfcGeom>
    )
endif()
