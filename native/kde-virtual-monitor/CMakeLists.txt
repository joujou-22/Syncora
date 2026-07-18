cmake_minimum_required(VERSION 3.16)
project(syncora-kde-virtual-monitor C)

include(GNUInstallDirs)
find_package(PkgConfig REQUIRED)
pkg_check_modules(WAYLAND REQUIRED IMPORTED_TARGET wayland-client)
find_program(WAYLAND_SCANNER wayland-scanner REQUIRED)

set(PROTOCOL_XML "/usr/share/plasma-wayland-protocols/zkde-screencast-unstable-v1.xml"
    CACHE FILEPATH "Path to KDE's screencast Wayland protocol")
set(PROTOCOL_HEADER "${CMAKE_CURRENT_BINARY_DIR}/kde-screencast-client.h")
set(PROTOCOL_CODE "${CMAKE_CURRENT_BINARY_DIR}/kde-screencast-protocol.c")

add_custom_command(
    OUTPUT "${PROTOCOL_HEADER}"
    COMMAND "${WAYLAND_SCANNER}" client-header "${PROTOCOL_XML}" "${PROTOCOL_HEADER}"
    DEPENDS "${PROTOCOL_XML}"
)
add_custom_command(
    OUTPUT "${PROTOCOL_CODE}"
    COMMAND "${WAYLAND_SCANNER}" private-code "${PROTOCOL_XML}" "${PROTOCOL_CODE}"
    DEPENDS "${PROTOCOL_XML}"
)

add_executable(syncora-kde-virtual-monitor
    main.c
    "${PROTOCOL_HEADER}"
    "${PROTOCOL_CODE}"
)
target_include_directories(syncora-kde-virtual-monitor PRIVATE "${CMAKE_CURRENT_BINARY_DIR}")
target_link_libraries(syncora-kde-virtual-monitor PRIVATE PkgConfig::WAYLAND)
target_compile_options(syncora-kde-virtual-monitor PRIVATE -Wall -Wextra -Wpedantic)

configure_file(
    org.syncora.virtualmonitor.desktop.in
    org.syncora.virtualmonitor.desktop
    @ONLY
)
install(TARGETS syncora-kde-virtual-monitor RUNTIME DESTINATION bin)
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/org.syncora.virtualmonitor.desktop"
        DESTINATION share/applications)
