"""Low-latency H.264 RTSP output for native Syncora clients."""

from __future__ import annotations

import logging
import threading

from .capture import FrameProducer

LOGGER = logging.getLogger(__name__)


def _rtsp_modules():
    import gi

    gi.require_version("Gst", "1.0")
    gi.require_version("GstRtspServer", "1.0")
    from gi.repository import GLib, Gst, GstRtspServer

    Gst.init(None)
    return GLib, GstRtspServer


class DirectRtspServer:
    """Serve the KDE PipeWire node as hardware-encoded H.264 over RTP/RTSP."""

    path = "/syncora"

    def __init__(self, producer: FrameProducer) -> None:
        self.producer = producer
        self.port = producer.config.rtsp_port
        self._server = None
        self._loop = None
        self._thread: threading.Thread | None = None
        self._source_id = 0
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._source_id != 0

    def start(self) -> dict[str, object]:
        with self._lock:
            if self.running:
                return self.info()
            self.producer.start_display()
            node = self.producer.direct_pipewire_node
            if node is None:
                raise RuntimeError(
                    "Syncora Direct currently requires KDE extended-display mode"
                )

            GLib, GstRtspServer = _rtsp_modules()
            fps = max(1, round(self.producer.config.fps))
            keepalive_ms = max(1, round(1000 / fps))
            bitrate_kbps = max(
                500, round(self.producer.config.video_bitrate_mbps * 1000)
            )
            pipeline = (
                f"( pipewiresrc path={node} do-timestamp=true always-copy=false "
                f"resend-last=true keepalive-time={keepalive_ms} ! "
                "queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 "
                "leaky=downstream ! videorate drop-only=true ! "
                f"video/x-raw,framerate={fps}/1 ! videoconvert ! "
                "video/x-raw,format=NV12 ! "
                f"vaapih264enc bitrate={bitrate_kbps} keyframe-period={fps} "
                "max-bframes=0 ! video/x-h264,profile=constrained-baseline ! "
                "h264parse config-interval=-1 ! "
                "rtph264pay name=pay0 pt=96 config-interval=1 "
                "aggregate-mode=zero-latency )"
            )

            server = GstRtspServer.RTSPServer.new()
            server.set_address("0.0.0.0")
            server.set_service(str(self.port))
            factory = GstRtspServer.RTSPMediaFactory.new()
            factory.set_launch(pipeline)
            factory.set_shared(True)
            factory.set_stop_on_disconnect(True)
            server.get_mount_points().add_factory(self.path, factory)
            loop = GLib.MainLoop.new(None, False)
            source_id = server.attach(None)
            if source_id == 0:
                raise RuntimeError(f"could not bind the RTSP server on port {self.port}")

            self._server = server
            self._loop = loop
            self._source_id = source_id
            self._thread = threading.Thread(
                target=loop.run, name="syncora-rtsp", daemon=True
            )
            self._thread.start()
            LOGGER.info("Syncora Direct RTSP ready on port %d%s", self.port, self.path)
            return self.info()

    def info(self) -> dict[str, object]:
        return {"transport": "rtsp", "port": self.port, "path": self.path}

    def stop(self) -> None:
        with self._lock:
            if not self.running:
                return
            GLib, _GstRtspServer = _rtsp_modules()
            GLib.source_remove(self._source_id)
            self._source_id = 0
            if self._loop is not None:
                self._loop.quit()
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=2)
            self._thread = None
            self._loop = None
            self._server = None
