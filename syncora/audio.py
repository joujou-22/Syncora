"""Capture the computer's default output monitor for WebRTC audio."""

from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
import threading
from fractions import Fraction

from av import AudioFrame

LOGGER = logging.getLogger(__name__)
AUDIO_RATE = 48_000
AUDIO_LAYOUT = "stereo"


class AudioCaptureError(RuntimeError):
    """Raised when the system output audio cannot be captured."""


def _gstreamer():
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
    except (ImportError, ValueError) as exc:
        raise AudioCaptureError("system audio needs PyGObject and GStreamer") from exc
    return Gst


def default_monitor() -> str:
    """Resolve the monitor of the default output without invoking a shell."""
    override = os.environ.get("SYNCORA_AUDIO_DEVICE", "").strip()
    if override:
        return override
    if shutil.which("pactl"):
        try:
            result = subprocess.run(
                ["pactl", "get-default-sink"],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            sink = result.stdout.strip()
            if sink:
                return sink + ".monitor"
        except (OSError, subprocess.SubprocessError):
            LOGGER.warning("Could not resolve the default audio output with pactl")
    return "@DEFAULT_MONITOR@"


class SystemAudioProducer:
    """Capture PCM chunks from the default speaker monitor on one thread."""

    def __init__(self) -> None:
        # PyGObject's importer is not thread-safe during its first import. Load
        # GStreamer before capture threads can start concurrently on Wayland.
        self._Gst = _gstreamer()
        self._frames: queue.Queue[AudioFrame] = queue.Queue(maxsize=10)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: str | None = None
        self._pts = 0
        self.device = default_monitor()

    @property
    def error(self) -> str | None:
        return self._error

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._error = None
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="syncora-audio", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def read(self, timeout: float = 1.0) -> AudioFrame | None:
        try:
            return self._frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def _publish(self, data: bytes) -> None:
        samples = len(data) // 4  # signed 16-bit, two interleaved channels
        if samples <= 0:
            return
        frame = AudioFrame(format="s16", layout=AUDIO_LAYOUT, samples=samples)
        frame.planes[0].update(data[: samples * 4])
        frame.sample_rate = AUDIO_RATE
        frame.pts = self._pts
        frame.time_base = Fraction(1, AUDIO_RATE)
        self._pts += samples
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                pass
            self._frames.put_nowait(frame)

    def _run(self) -> None:
        Gst = self._Gst
        Gst.init(None)
        pipeline = None
        try:
            pipeline = Gst.parse_launch(
                "pulsesrc name=source do-timestamp=true ! "
                "audioconvert ! audioresample ! "
                "audio/x-raw,format=S16LE,rate=48000,channels=2,layout=interleaved ! "
                "appsink name=sink sync=false max-buffers=4 drop=true"
            )
            source = pipeline.get_by_name("source")
            source.set_property("device", self.device)
            sink = pipeline.get_by_name("sink")
            pipeline.set_state(Gst.State.PLAYING)
            while not self._stop_event.is_set():
                sample = sink.emit("try-pull-sample", Gst.SECOND)
                if sample is None:
                    message = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
                    if message:
                        error, _debug = message.parse_error()
                        raise AudioCaptureError(error.message)
                    continue
                buffer = sample.get_buffer()
                ok, mapped = buffer.map(Gst.MapFlags.READ)
                if ok:
                    try:
                        self._publish(bytes(mapped.data))
                    finally:
                        buffer.unmap(mapped)
        except Exception as exc:
            self._error = str(exc)
            LOGGER.exception("System audio capture stopped")
        finally:
            if pipeline is not None:
                pipeline.set_state(Gst.State.NULL)
