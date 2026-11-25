# This file was generated with the assistance of an AI coding tool.

add_executable(test_ifcopenshell_parse
    test_ifcopenshell_parse.cpp
)
target_compile_definitions(test_ifcopenshell_parse PRIVATE
    IFCOPENSHELL_TEST_FIXTURES="${CMAKE_CURRENT_SOURCE_DIR}/../../ifcopenshell-python/test/fixtures"
)
target_link_libraries(test_ifcopenshell_parse PRIVATE Catch2::Catch2WithMain IfcParse)
add_dependencies(test_ifcopenshell_parse parse_schema_ifc4)
catch_discover_tests(test_ifcopenshell_parse
    DL_PATHS
        $<TARGET_FILE_DIR:Catch2::Catch2>
        $<TARGET_FILE_DIR:Catch2::Catch2WithMain>
        $<TARGET_FILE_DIR:IfcParse>
        $<TARGET_FILE_DIR:plugin>
)

# The overflow is a single byte past a heap buffer. IfcParse and this executable
# both have to be instrumented with AddressSanitizer, via CMAKE_CXX_FLAGS, or the
# copy succeeds and these cases pass while the bug is still present.
if(CMAKE_CXX_FLAGS MATCHES "fsanitize=address" OR CMAKE_CXX_FLAGS_RELWITHDEBINFO MATCHES "fsanitize=address" OR CMAKE_CXX_FLAGS_DEBUG MATCHES "fsanitize=address")
    add_executable(test_rocksdb_id_list_overflow
        test_rocksdb_id_list_overflow.cpp
    )
    target_link_libraries(test_rocksdb_id_list_overflow PRIVATE Catch2::Catch2WithMain IfcParse)
    target_compile_options(test_rocksdb_id_list_overflow PRIVATE -fsanitize=address -fno-omit-frame-pointer)
    target_link_options(test_rocksdb_id_list_overflow PRIVATE -fsanitize=address)
    add_dependencies(test_rocksdb_id_list_overflow parse_schema_ifc4)
    catch_discover_tests(test_rocksdb_id_list_overflow
        DL_PATHS
            $<TARGET_FILE_DIR:Catch2::Catch2>
            $<TARGET_FILE_DIR:Catch2::Catch2WithMain>
            $<TARGET_FILE_DIR:IfcParse>
            $<TARGET_FILE_DIR:plugin>
    )
else()
    message(STATUS "Skipping test_rocksdb_id_list_overflow; pass -fsanitize=address in CMAKE_CXX_FLAGS")
endif()
