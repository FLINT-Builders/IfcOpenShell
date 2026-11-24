# This file was generated with the assistance of an AI coding tool.

find_package(Threads REQUIRED)

add_executable(test_cyclic_ifc_relationships
    test_cyclic_ifc_relationships.cpp
)
target_link_libraries(test_cyclic_ifc_relationships PRIVATE
    Catch2::Catch2WithMain
    helpers
    Threads::Threads
)
add_dependencies(test_cyclic_ifc_relationships parse_schema_ifc4)
catch_discover_tests(test_cyclic_ifc_relationships
    DL_PATHS
        $<TARGET_FILE_DIR:Catch2::Catch2>
        $<TARGET_FILE_DIR:Catch2::Catch2WithMain>
        $<TARGET_FILE_DIR:IfcParse>
        $<TARGET_FILE_DIR:plugin>
)
