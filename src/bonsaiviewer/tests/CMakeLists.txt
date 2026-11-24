# This file was generated with the assistance of an AI coding tool.
################################################################################
#                                                                              #
# This file is part of Bonsai.                                                 #
#                                                                              #
# Bonsai is free software: you can redistribute it and/or modify               #
# it under the terms of the GNU General Public License as published by         #
# the Free Software Foundation, either version 3.0 of the License, or          #
# (at your option) any later version.                                          #
#                                                                              #
# Bonsai is distributed in the hope that it will be useful,                    #
# but WITHOUT ANY WARRANTY; without even the implied warranty of               #
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the                 #
# GNU General Public License for more details.                                 #
#                                                                              #
# You should have received a copy of the GNU General Public License            #
# along with this program. If not, see <http://www.gnu.org/licenses/>.         #
#                                                                              #
################################################################################

# Regression test for model text rendered by the properties panel. Compiles the
# panel sources directly so the test does not need the wgpu viewer.

set(QT_VERSION 6 CACHE STRING "Qt version")
find_package(Qt${QT_VERSION} REQUIRED
    COMPONENTS Core Gui Widgets Svg Test
    OPTIONAL_COMPONENTS CorePrivate
    PATHS ${QT_DIR})

set(BONSAI_SRC ${CMAKE_CURRENT_SOURCE_DIR}/..)

add_executable(test_properties_richtext
    test_properties_richtext.cpp
    ${BONSAI_SRC}/ViewerSettings.cpp
    ${BONSAI_SRC}/components/KeyValueTable.cpp
    ${BONSAI_SRC}/components/Panel.cpp
    ${BONSAI_SRC}/components/Section.cpp
    ${BONSAI_SRC}/components/SvgIcon.cpp
    ${BONSAI_SRC}/modules/properties/Panel.cpp
)

set_target_properties(test_properties_richtext PROPERTIES
    AUTOMOC ON
    BUILD_RPATH "${QT_DIR}/lib;$<TARGET_FILE_DIR:IfcParse>"
)

target_include_directories(test_properties_richtext PRIVATE
    ${BONSAI_SRC}
    ${Qt${QT_VERSION}Core_PRIVATE_INCLUDE_DIRS}
)

target_link_libraries(test_properties_richtext PRIVATE
    helpers
    Qt${QT_VERSION}::Core
    Qt${QT_VERSION}::Gui
    Qt${QT_VERSION}::Widgets
    Qt${QT_VERSION}::Svg
    Qt${QT_VERSION}::Test
)

if(TARGET Qt${QT_VERSION}::CorePrivate)
    target_link_libraries(test_properties_richtext PRIVATE Qt${QT_VERSION}::CorePrivate)
endif()

add_test(NAME test_properties_richtext COMMAND test_properties_richtext)
set_tests_properties(test_properties_richtext PROPERTIES
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen;LD_LIBRARY_PATH=${QT_DIR}/lib:$<TARGET_FILE_DIR:IfcParse>"
)
