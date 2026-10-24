cmake_minimum_required(VERSION 3.24)
project(UmekoInputMethod LANGUAGES C CXX)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets DBus)
# Build against this application's Qt, never a distribution's private Qt ABI.
set(ENABLE_QT4 OFF CACHE BOOL "" FORCE)
set(ENABLE_QT5 OFF CACHE BOOL "" FORCE)
set(ENABLE_QT6 ON CACHE BOOL "" FORCE)
set(BUILD_ONLY_PLUGIN ON CACHE BOOL "" FORCE)
set(BUILD_STATIC_PLUGIN OFF CACHE BOOL "" FORCE)
# Use Qt's native Wayland text-input support; avoid a second private Wayland ABI.
set(ENABLE_QT6_WAYLAND_WORKAROUND OFF CACHE BOOL "" FORCE)
set(CMAKE_INSTALL_QT6PLUGINDIR plugins CACHE PATH "" FORCE)
set(fcitx5_qt_SOURCE_DIR "${CMAKE_CURRENT_BINARY_DIR}/source")
execute_process(COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/fetch.py" "${fcitx5_qt_SOURCE_DIR}"
  RESULT_VARIABLE fetched)
if(NOT fetched EQUAL 0)
  message(FATAL_ERROR "Could not prepare the pinned fcitx5-qt sources")
endif()
add_subdirectory("${fcitx5_qt_SOURCE_DIR}" "${CMAKE_CURRENT_BINARY_DIR}/fcitx5-qt")
set_target_properties(fcitx5platforminputcontextplugin-qt6 PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/plugins/platforminputcontexts"
  INSTALL_RPATH "$ORIGIN/../../lib"
  INSTALL_RPATH_USE_LINK_PATH FALSE)
install(TARGETS fcitx5platforminputcontextplugin-qt6
  LIBRARY DESTINATION plugins/platforminputcontexts COMPONENT Runtime)
install(DIRECTORY "${fcitx5_qt_SOURCE_DIR}/LICENSES/"
  DESTINATION licenses/fcitx5-qt COMPONENT Runtime)
file(WRITE "${CMAKE_BINARY_DIR}/input-method-build.json"
  "{\"fcitx5Qt\":\"5.1.13\",\"qt\":\"${Qt6_VERSION}\",\"sourceSha256\":\"74b2c43ca865ec9ede257bcd3bdadafc20f571900cb2440a4488335e4d4e91cc\"}\n")
