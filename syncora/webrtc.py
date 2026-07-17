"""Local-only WebRTC signaling and video track support."""

from __future__ import annotations

import asyncio
import logging
import threading
from fractions import Fraction
from typing import Any

from aiortc import (
    AudioStreamTrack,
    MediaStreamError,
    RTCConfiguration,
    RTCPeerConnection,
    RTCSessionDescription,
    VideoStreamTrack,
)
from aiortc.contrib.media import MediaRelay
from av import VideoFrame

from .audio import SystemAudioProducer
from .capture import FrameProducer

LOGGER = logging.getLogger(__name__)
VIDEO_CLOCK_RATE = 90_000


class ScreenVideoTrack(VideoStreamTrack):
    """Expose the newest captured image without building a frame queue."""

    def __init__(self, producer: FrameProducer) -> None:
        super().__init__()
        self.producer = producer
        self.sequence = 0
        self._last_pts = 0

    async def recv(self) -> VideoFrame:
        loop = asyncio.get_running_loop()
        image = None
        while image is None:
            sequence, candidate = self.producer.latest_image()
            if sequence > self.sequence:
                image = candidate
            else:
                await asyncio.sleep(0.005)
            if image is None and self.producer.error:
                raise RuntimeError(self.producer.error)
        self.sequence = sequence
        frame = VideoFrame.from_image(image)
        pts = int(loop.time() * VIDEO_CLOCK_RATE)
        self._last_pts = max(self._last_pts + 1, pts)
        frame.pts = self._last_pts
        frame.time_base = Fraction(1, VIDEO_CLOCK_RATE)
        return frame


class SystemAudioTrack(AudioStreamTrack):
    """Expose captured speaker-monitor PCM as a WebRTC audio track."""

    def __init__(self, producer: SystemAudioProducer) -> None:
        super().__init__()
        self.producer = producer

    async def recv(self):
        loop = asyncio.get_running_loop()
        while True:
            if self.readyState != "live":
                raise MediaStreamError
            frame = await loop.run_in_executor(None, self.producer.read, 1.0)
            if frame is not None:
                return frame
            if self.producer.error:
                raise RuntimeError(self.producer.error)


class WebRTCManager:
    """Run aiortc on a dedicated asyncio loop behind the synchronous Flask app."""

    def __init__(
        self,
        producer: FrameProducer,
        audio: SystemAudioProducer | None = None,
    ) -> None:
        self.producer = producer
        self.audio = audio or SystemAudioProducer()
        self._audio_source = SystemAudioTrack(self.audio)
        self._audio_relay = MediaRelay()
        self._peers: set[RTCPeerConnection] = set()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="syncora-webrtc", daemon=True
        )
        self._thread.start()

    @property
    def peer_count(self) -> int:
        return len(self._peers)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def handle_offer(self, sdp: str, offer_type: str) -> dict[str, str]:
        if offer_type != "offer" or not sdp.strip():
            raise ValueError("a non-empty WebRTC offer is required")
        future = asyncio.run_coroutine_threadsafe(self._answer(sdp, offer_type), self._loop)
        return future.result(timeout=20)

    async def _answer(self, sdp: str, offer_type: str) -> dict[str, str]:
        self.producer.start()
        self.audio.start()
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self._peers.add(peer)

        @peer.on("connectionstatechange")
        async def connection_state_changed() -> None:
            LOGGER.info("WebRTC connection state: %s", peer.connectionState)
            if peer.connectionState in {"failed", "closed"}:
                await peer.close()
                self._peers.discard(peer)

        try:
            await peer.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))
            peer.addTrack(ScreenVideoTrack(self.producer))
            peer.addTrack(self._audio_relay.subscribe(self._audio_source))
            answer = await peer.createAnswer()
            await peer.setLocalDescription(answer)
            return {"sdp": peer.localDescription.sdp, "type": peer.localDescription.type}
        except Exception:
            self._peers.discard(peer)
            await peer.close()
            raise

    async def _close_all(self) -> None:
        self._audio_source.stop()
        peers = list(self._peers)
        self._peers.clear()
        await asyncio.gather(*(peer.close() for peer in peers), return_exceptions=True)
        await asyncio.sleep(0.05)

    def stop(self) -> None:
        if not self._loop.is_running():
            return
        future = asyncio.run_coroutine_threadsafe(self._close_all(), self._loop)
        try:
            future.result(timeout=5)
        finally:
            self.audio.stop()
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=2)
