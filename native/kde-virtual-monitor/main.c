/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wayland-client.h>

#include "kde-screencast-client.h"

struct state {
    struct wl_display *display;
    struct zkde_screencast_unstable_v1 *screencast;
    struct zkde_screencast_stream_unstable_v1 *stream;
    int failed;
};

static volatile sig_atomic_t running = 1;

static void stop_running(int signal_number)
{
    (void)signal_number;
    running = 0;
}

static void stream_closed(void *data, struct zkde_screencast_stream_unstable_v1 *stream)
{
    (void)stream;
    ((struct state *)data)->failed = 1;
    running = 0;
}

static void stream_created(void *data,
                           struct zkde_screencast_stream_unstable_v1 *stream,
                           uint32_t node)
{
    (void)data;
    (void)stream;
    printf("%u\n", node);
    fflush(stdout);
}

static void stream_failed(void *data,
                          struct zkde_screencast_stream_unstable_v1 *stream,
                          const char *message)
{
    (void)stream;
    fprintf(stderr, "KWin rejected the virtual monitor: %s\n", message);
    ((struct state *)data)->failed = 1;
    running = 0;
}

static const struct zkde_screencast_stream_unstable_v1_listener stream_listener = {
    .closed = stream_closed,
    .created = stream_created,
    .failed = stream_failed,
};

static void registry_global(void *data,
                            struct wl_registry *registry,
                            uint32_t name,
                            const char *interface,
                            uint32_t version)
{
    struct state *state = data;
    if (strcmp(interface, zkde_screencast_unstable_v1_interface.name) != 0) {
        return;
    }
    uint32_t supported = version < 5 ? version : 5;
    state->screencast = wl_registry_bind(
        registry, name, &zkde_screencast_unstable_v1_interface, supported);
}

static void registry_removed(void *data, struct wl_registry *registry, uint32_t name)
{
    (void)data;
    (void)registry;
    (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = registry_global,
    .global_remove = registry_removed,
};

static int parse_positive(const char *value, const char *label)
{
    char *end = NULL;
    errno = 0;
    long result = strtol(value, &end, 10);
    if (errno || !end || *end || result < 1 || result > 16384) {
        fprintf(stderr, "Invalid %s: %s\n", label, value);
        exit(2);
    }
    return (int)result;
}

int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "Usage: %s NAME WIDTH HEIGHT\n", argv[0]);
        return 2;
    }

    struct state state = {0};
    state.display = wl_display_connect(NULL);
    if (!state.display) {
        fprintf(stderr, "Could not connect to the Wayland session\n");
        return 1;
    }

    struct wl_registry *registry = wl_display_get_registry(state.display);
    wl_registry_add_listener(registry, &registry_listener, &state);
    wl_display_roundtrip(state.display);
    if (!state.screencast) {
        fprintf(stderr, "KWin's virtual-monitor protocol is unavailable\n");
        wl_registry_destroy(registry);
        wl_display_disconnect(state.display);
        return 1;
    }

    int width = parse_positive(argv[2], "width");
    int height = parse_positive(argv[3], "height");
    state.stream = zkde_screencast_unstable_v1_stream_virtual_output(
        state.screencast,
        argv[1],
        width,
        height,
        wl_fixed_from_double(1.0),
        ZKDE_SCREENCAST_UNSTABLE_V1_POINTER_HIDDEN);
    zkde_screencast_stream_unstable_v1_add_listener(
        state.stream, &stream_listener, &state);

    signal(SIGINT, stop_running);
    signal(SIGTERM, stop_running);
    while (running && wl_display_dispatch(state.display) >= 0) {
    }

    if (state.stream) {
        zkde_screencast_stream_unstable_v1_close(state.stream);
    }
    zkde_screencast_unstable_v1_destroy(state.screencast);
    wl_registry_destroy(registry);
    wl_display_disconnect(state.display);
    return state.failed ? 1 : 0;
}
