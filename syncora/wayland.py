"""Wayland screen capture through the standard ScreenCast portal and PipeWire."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable

from PIL import Image

LOGGER = logging.getLogger(__name__)
PORTAL_NAME = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"


class PortalError(RuntimeError):
    """Raised when the desktop portal cannot provide a screen stream."""


def _libraries():
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gio, GLib, Gst
    except (ImportError, ValueError) as exc:
        raise PortalError(
            "Wayland capture needs PyGObject and GStreamer. See the README system packages."
        ) from exc
    return Gio, GLib, Gst


class PortalSession:
    """Own a portal ScreenCast session and its restricted PipeWire connection."""

    def __init__(self) -> None:
        self.Gio, self.GLib, self.Gst = _libraries()
        self.bus = self.Gio.bus_get_sync(self.Gio.BusType.SESSION, None)
        self.session_handle: str | None = None
        self.pipewire_fd: int | None = None
        self.node_id: int | None = None

    def _request(self, method: str, signature: str, values: tuple, options: dict) -> dict:
        token = "syncora_" + uuid.uuid4().hex
        sender = self.bus.get_unique_name()[1:].replace(".", "_")
        request_path = f"{PORTAL_PATH}/request/{sender}/{token}"
        options = dict(options)
        options["handle_token"] = self.GLib.Variant("s", token)
        parameters = self.GLib.Variant(signature, values + (options,))
        loop = self.GLib.MainLoop()
        response: dict[str, object] = {}

        def on_response(_bus, _sender, _path, _iface, _signal, params, _data=None):
            code, results = params.unpack()
            response["code"] = code
            response["results"] = results
            loop.quit()

        subscription = self.bus.signal_subscribe(
            PORTAL_NAME,
            "org.freedesktop.portal.Request",
            "Response",
            request_path,
            None,
            self.Gio.DBusSignalFlags.NONE,
            on_response,
        )
        try:
            self.bus.call_sync(
                PORTAL_NAME,
                PORTAL_PATH,
                SCREENCAST_IFACE,
                method,
                parameters,
                self.GLib.VariantType.new("(o)"),
                self.Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            loop.run()
        finally:
            self.bus.signal_unsubscribe(subscription)
        if response.get("code") != 0:
            raise PortalError(f"screen sharing was cancelled or refused (portal code {response.get('code')})")
        return response.get("results", {})  # type: ignore[return-value]

    def open(self) -> tuple[int, int]:
        session_token = "syncora_session_" + uuid.uuid4().hex
        created = self._request(
            "CreateSession",
            "(a{sv})",
            (),
            {"session_handle_token": self.GLib.Variant("s", session_token)},
        )
        self.session_handle = created["session_handle"]
        self._request(
            "SelectSources",
            "(oa{sv})",
            (self.session_handle,),
            {
                "types": self.GLib.Variant("u", 1),  # monitors
                "multiple": self.GLib.Variant("b", False),
                "cursor_mode": self.GLib.Variant("u", 2),  # embedded
            },
        )
        started = self._request("Start", "(osa{sv})", (self.session_handle, ""), {})
        streams = started.get("streams", [])
        if not streams:
            raise PortalError("the portal returned no screen stream")
        self.node_id = int(streams[0][0])

        reply, fd_list = self.bus.call_with_unix_fd_list_sync(
            PORTAL_NAME,
            PORTAL_PATH,
            SCREENCAST_IFACE,
            "OpenPipeWireRemote",
            self.GLib.Variant("(oa{sv})", (self.session_handle, {})),
            self.GLib.VariantType.new("(h)"),
            self.Gio.DBusCallFlags.NONE,
            -1,
            None,
            None,
        )
        fd_index = reply.unpack()[0]
        self.pipewire_fd = fd_list.get(fd_index)
        return self.pipewire_fd, self.node_id

    def close(self) -> None:
        if not self.session_handle:
            return
        try:
            self.bus.call_sync(
                PORTAL_NAME,
                self.session_handle,
                "org.freedesktop.portal.Session",
                "Close",
                None,
                None,
                self.Gio.DBusCallFlags.NONE,
                2000,
                None,
            )
        except Exception:
            LOGGER.debug("Could not close the portal session", exc_info=True)
        self.session_handle = None


def capture_wayland(
    stop_event: threading.Event,
    fps: float,
    on_image: Callable[[Image.Image], None],
) -> None:
    """Read RGB frames from a portal-authorized PipeWire stream."""
    portal = PortalSession()
    Gst = portal.Gst
    Gst.init(None)
    pipeline = None
    try:
        pipewire_fd, node_id = portal.open()
        pipeline = Gst.parse_launch(
            f"pipewiresrc fd={pipewire_fd} path={node_id} do-timestamp=true ! "
            f"videorate ! video/x-raw,framerate={max(1, round(fps))}/1 ! "
            "videoconvert ! video/x-raw,format=RGB ! "
            "appsink name=sink sync=false max-buffers=1 drop=true"
        )
        sink = pipeline.get_by_name("sink")
        pipeline.set_state(Gst.State.PLAYING)
        while not stop_event.is_set():
            sample = sink.emit("try-pull-sample", Gst.SECOND)
            if sample is None:
                message = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
                if message:
                    error, _debug = message.parse_error()
                    raise PortalError(f"PipeWire capture failed: {error.message}")
                continue
            caps = sample.get_caps().get_structure(0)
            width, height = caps.get_value("width"), caps.get_value("height")
            buffer = sample.get_buffer()
            ok, mapped = buffer.map(Gst.MapFlags.READ)
            if not ok:
                raise PortalError("could not read a PipeWire video frame")
            try:
                stride = len(mapped.data) // height
                image = Image.frombytes("RGB", (width, height), mapped.data, "raw", "RGB", stride)
                on_image(image)
            finally:
                buffer.unmap(mapped)
    finally:
        if pipeline is not None:
            pipeline.set_state(Gst.State.NULL)
        portal.close()
