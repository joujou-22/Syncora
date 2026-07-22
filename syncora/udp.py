"""Direct single-client H.264/RTP output for the native Android client."""

from __future__ import annotations

import ipaddress
import logging
import os
import threading
import time

from .capture import FrameProducer
from .direct_media import _gstreamer

LOGGER = logging.getLogger(__name__)


class DirectUdpStreamer:
    """Send the newest hardware-encoded display frames to one LAN client."""

    def __init__(self, producer: FrameProducer) -> None:
        self.producer = producer
        self._pipeline = None
        self._target: tuple[str, int] | None = None
        self._lock = threading.Lock()
        self._encoded_frames = 0
        self._source_frames = 0
        self._stats_started = 0.0
        self._stats_last_report = 0.0
        self._stats_last_source = 0
        self._stats_last_encoded = 0

    @staticmethod
    def _video_chain(Gst, fps: int, bitrate_kbps: int) -> tuple[str, str]:
        """Choose the fastest available VA-API path, with portable fallbacks."""
        available = lambda name: Gst.ElementFactory.find(name) is not None
        keyframe_interval = fps
        if available("vapostproc") and available("vah264lpenc"):
            return (
                "vapostproc ! video/x-raw(memory:VAMemory),format=NV12 ! "
                f"vah264lpenc bitrate={bitrate_kbps} key-int-max={keyframe_interval} "
                "b-frames=0 ref-frames=1 target-usage=7 cabac=false dct8x8=false",
                "modern VA-API low-power",
            )
        if available("vah264lpenc"):
            conversion_threads = max(1, min(4, os.cpu_count() or 1))
            return (
                f"videoconvert n-threads={conversion_threads} ! "
                "video/x-raw,format=NV12 ! "
                f"vah264lpenc bitrate={bitrate_kbps} key-int-max={keyframe_interval} "
                "b-frames=0 ref-frames=1 target-usage=7 cabac=false dct8x8=false",
                f"modern VA-API low-power with {conversion_threads}-thread conversion",
            )
        if available("vaapipostproc") and available("vaapih264enc"):
            return (
                "vaapipostproc ! video/x-raw,format=NV12 ! "
                f"vaapih264enc bitrate={bitrate_kbps} rate-control=cbr "
                f"keyframe-period={keyframe_interval} max-bframes=0 quality-level=7",
                "legacy VA-API CBR with GPU conversion",
            )
        if available("vaapih264enc"):
            conversion_threads = max(1, min(4, os.cpu_count() or 1))
            return (
                f"videoconvert n-threads={conversion_threads} ! "
                "video/x-raw,format=NV12 ! "
                f"vaapih264enc bitrate={bitrate_kbps} rate-control=cbr "
                f"keyframe-period={keyframe_interval} max-bframes=0 quality-level=7",
                f"legacy VA-API CBR with {conversion_threads}-thread conversion",
            )
        raise RuntimeError("no VA-API H.264 encoder is available")

    @property
    def running(self) -> bool:
        return self._pipeline is not None

    def start(self, host: str, port: int) -> dict[str, object]:
        address = ipaddress.ip_address(host)
        if not address.is_private and not address.is_loopback:
            raise ValueError("the direct client must use a private LAN address")
        if not 1024 <= port <= 65535:
            raise ValueError("the direct UDP port must be between 1024 and 65535")

        with self._lock:
            target = (str(address), port)
            if self._pipeline is not None and self._target == target:
                return self.info(port)
            self._stop_locked()
            self.producer.start_display()
            node = self.producer.direct_pipewire_node
            if node is None:
                raise RuntimeError(
                    "Syncora Direct currently requires KDE extended-display mode"
                )

            Gst = _gstreamer()
            fps = max(1, round(self.producer.config.fps))
            # Poll KWin at 60 Hz even when the client target is 30 FPS. The
            # one-frame leaky queue then gives the encoder the newest capture,
            # without forcing a modest Android TV to decode 60 frames/second.
            capture_fps = max(60, fps)
            keepalive_ms = max(1, round(1000 / capture_fps))
            bitrate_kbps = max(
                500, round(self.producer.config.video_bitrate_mbps * 1000)
            )
            video_chain, video_backend = self._video_chain(Gst, fps, bitrate_kbps)
            pipeline = Gst.parse_launch(
                f"pipewiresrc path={node} do-timestamp=true always-copy=false "
                f"resend-last=true keepalive-time={keepalive_ms} ! "
                "identity name=syncora_source_stats silent=true ! "
                "queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 "
                "leaky=downstream ! videorate ! "
                f"video/x-raw,framerate={fps}/1 ! {video_chain} ! "
                "video/x-h264,profile=constrained-baseline ! "
                "h264parse config-interval=-1 ! "
                "identity name=syncora_stats silent=true ! "
                "rtph264pay pt=96 mtu=1200 config-interval=1 "
                "aggregate-mode=zero-latency ! "
                f"udpsink host={address} port={port} sync=true async=false "
                "processing-deadline=0"
            )
            if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                pipeline.set_state(Gst.State.NULL)
                raise RuntimeError("could not start the direct UDP pipeline")
            # Parsing a pipeline only validates property syntax. Negotiation and
            # driver failures are asynchronous, so inspect the bus before telling
            # the Android client that the stream is ready.
            pipeline.get_state(2 * Gst.SECOND)
            message = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
            if message is not None:
                error, debug = message.parse_error()
                pipeline.set_state(Gst.State.NULL)
                details = f" ({debug})" if debug else ""
                raise RuntimeError(f"direct UDP pipeline failed: {error.message}{details}")
            self._pipeline = pipeline
            self._target = target
            self._encoded_frames = 0
            self._source_frames = 0
            self._stats_started = time.monotonic()
            self._stats_last_report = self._stats_started
            self._stats_last_source = 0
            self._stats_last_encoded = 0
            source_stats = pipeline.get_by_name("syncora_source_stats")
            source_stats.get_static_pad("sink").add_probe(
                Gst.PadProbeType.BUFFER,
                lambda pad, info: self._on_source_frame(Gst, pad, info),
            )
            stats = pipeline.get_by_name("syncora_stats")
            stats.get_static_pad("sink").add_probe(
                Gst.PadProbeType.BUFFER,
                lambda pad, info: self._on_encoded_frame(Gst, pad, info),
            )
            LOGGER.info(
                "Syncora Direct UDP ready for %s:%d using %s "
                "(capture %d Hz, encode %d FPS)",
                address,
                port,
                video_backend,
                capture_fps,
                fps,
            )
            return self.info(port)

    def _on_source_frame(self, Gst, _pad, _info):
        self._source_frames += 1
        return Gst.PadProbeReturn.OK

    def _on_encoded_frame(self, Gst, _pad, _info):
        self._encoded_frames += 1
        now = time.monotonic()
        if now - self._stats_last_report >= 5:
            elapsed = max(0.001, now - self._stats_last_report)
            source_delta = self._source_frames - self._stats_last_source
            encoded_delta = self._encoded_frames - self._stats_last_encoded
            LOGGER.info(
                "Syncora Direct source %.1f FPS -> encoded %.1f FPS",
                source_delta / elapsed,
                encoded_delta / elapsed,
            )
            self._stats_last_report = now
            self._stats_last_source = self._source_frames
            self._stats_last_encoded = self._encoded_frames
        return Gst.PadProbeReturn.OK

    def info(self, port: int) -> dict[str, object]:
        width, height = map(int, self.producer.config.virtual_resolution.split("x"))
        return {
            "transport": "rtp-h264-udp",
            "port": port,
            "width": width,
            "height": height,
        }

    def _stop_locked(self) -> None:
        if self._pipeline is not None:
            Gst = _gstreamer()
            self._pipeline.set_state(Gst.State.NULL)
        self._pipeline = None
        self._target = None

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()
