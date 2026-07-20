"""Direct single-client H.264/RTP output for the native Android client."""

from __future__ import annotations

import ipaddress
import logging
import threading

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
            keepalive_ms = max(1, round(1000 / fps))
            bitrate_kbps = max(
                500, round(self.producer.config.video_bitrate_mbps * 1000)
            )
            pipeline = Gst.parse_launch(
                f"pipewiresrc path={node} do-timestamp=true always-copy=false "
                f"resend-last=true keepalive-time={keepalive_ms} ! "
                "queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 "
                "leaky=downstream ! videorate drop-only=true ! "
                f"video/x-raw,framerate={fps}/1 ! videoconvert ! "
                "video/x-raw,format=NV12 ! "
                f"vaapih264enc bitrate={bitrate_kbps} keyframe-period={fps} "
                "max-bframes=0 ! video/x-h264,profile=constrained-baseline ! "
                "h264parse config-interval=-1 ! "
                "rtph264pay pt=96 mtu=1200 config-interval=1 "
                "aggregate-mode=zero-latency ! "
                f"udpsink host={address} port={port} sync=false async=false"
            )
            if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                pipeline.set_state(Gst.State.NULL)
                raise RuntimeError("could not start the direct UDP pipeline")
            self._pipeline = pipeline
            self._target = target
            LOGGER.info("Syncora Direct UDP ready for %s:%d", address, port)
            return self.info(port)

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
