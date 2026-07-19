"""Pre-encoded WebRTC video tracks for direct PipeWire capture."""

from __future__ import annotations

import asyncio
import logging
from fractions import Fraction

from aiortc import MediaStreamError, VideoStreamTrack
from av import Packet

from .capture import FrameProducer

LOGGER = logging.getLogger(__name__)
VIDEO_CLOCK_RATE = 90_000


def _gstreamer():
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
    return Gst


class DirectH264Track(VideoStreamTrack):
    """Return VA-API H.264 access units captured straight from PipeWire."""

    def __init__(self, producer: FrameProducer) -> None:
        super().__init__()
        self.producer = producer
        self._pipeline = None
        self._sink = None
        self._first_pts: int | None = None
        self._last_pts = -1
        self._start()

    @staticmethod
    def available(producer: FrameProducer) -> bool:
        if producer.direct_pipewire_node is None or producer.config.scale != 1.0:
            return False
        try:
            Gst = _gstreamer()
            return Gst.ElementFactory.find("vaapih264enc") is not None
        except (ImportError, ValueError):
            return False

    def _start(self) -> None:
        Gst = _gstreamer()
        node = self.producer.direct_pipewire_node
        if node is None:
            raise RuntimeError("the direct PipeWire display is unavailable")
        fps = max(1, round(self.producer.config.fps))
        keepalive_ms = max(1, round(1000 / fps))
        bitrate_kbps = max(500, round(self.producer.config.video_bitrate_mbps * 1000))
        self._pipeline = Gst.parse_launch(
            f"pipewiresrc path={node} do-timestamp=true always-copy=false "
            f"resend-last=true keepalive-time={keepalive_ms} ! "
            "queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream ! "
            "videorate drop-only=true ! "
            f"video/x-raw,framerate={fps}/1 ! "
            "videoconvert ! video/x-raw,format=NV12 ! "
            f"vaapih264enc bitrate={bitrate_kbps} keyframe-period={fps} max-bframes=0 ! "
            "video/x-h264,profile=constrained-baseline ! "
            "h264parse config-interval=-1 ! "
            "video/x-h264,stream-format=byte-stream,alignment=au ! "
            "appsink name=sink sync=false max-buffers=1 drop=true"
        )
        self._sink = self._pipeline.get_by_name("sink")
        if self._pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("could not start the direct VA-API pipeline")

    def _pull_packet(self) -> Packet:
        Gst = _gstreamer()
        if self._pipeline is None:
            self._start()
        while True:
            sample = self._sink.emit("try-pull-sample", Gst.SECOND)
            if sample is not None:
                break
            if self._pipeline is None or self.readyState != "live":
                raise MediaStreamError
            message = self._pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
            if message:
                error, _debug = message.parse_error()
                raise RuntimeError(f"direct H.264 pipeline failed: {error.message}")
        buffer = sample.get_buffer()
        ok, mapped = buffer.map(Gst.MapFlags.READ)
        if not ok:
            raise RuntimeError("could not read a direct H.264 access unit")
        try:
            packet = Packet(bytes(mapped.data))
        finally:
            buffer.unmap(mapped)

        source_pts = buffer.pts
        if source_pts == Gst.CLOCK_TIME_NONE:
            source_pts = 0 if self._first_pts is None else self._last_pts + 1
        if self._first_pts is None:
            self._first_pts = source_pts
        pts = round((source_pts - self._first_pts) * VIDEO_CLOCK_RATE / Gst.SECOND)
        self._last_pts = max(self._last_pts + 1, pts)
        packet.pts = self._last_pts
        packet.time_base = Fraction(1, VIDEO_CLOCK_RATE)
        return packet

    async def recv(self) -> Packet:
        if self.readyState != "live":
            raise MediaStreamError
        return await asyncio.get_running_loop().run_in_executor(None, self._pull_packet)

    def stop(self) -> None:
        if self._pipeline is not None:
            Gst = _gstreamer()
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
        super().stop()
