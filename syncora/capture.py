"""In-memory screen capture and JPEG frame production."""

from __future__ import annotations

import io
import logging
import os
import threading
import time

import mss
from PIL import Image

from .config import Config
from .display import capture_kde_virtual_display, virtual_display_for

LOGGER = logging.getLogger(__name__)


class FrameProducer:
    """Capture once and share the latest encoded frame with every client."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._condition = threading.Condition()
        self._frame: bytes | None = None
        self._image: Image.Image | None = None
        self._sequence = 0
        self._error: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._mjpeg_enabled = False
        self._virtual_display = (
            virtual_display_for(config.virtual_resolution) if config.extend else None
        )

    @property
    def error(self) -> str | None:
        with self._condition:
            return self._error

    @property
    def direct_pipewire_node(self) -> int | None:
        """Return the KDE virtual display's node after it has started."""
        if self._virtual_display is None:
            return None
        return self._virtual_display.pipewire_node

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self.start_display()
        self._thread = threading.Thread(target=self._run, name="syncora-capture", daemon=True)
        self._thread.start()

    def start_display(self) -> None:
        """Create the virtual output without starting the legacy raw-frame path."""
        if self._virtual_display:
            self._virtual_display.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._virtual_display:
            self._virtual_display.stop()

    def enable_mjpeg(self) -> None:
        """Enable JPEG encoding only when a compatibility client needs it."""
        with self._condition:
            self._mjpeg_enabled = True

    def wait_for_frame(self, after: int, timeout: float = 3.0) -> tuple[int, bytes | None]:
        with self._condition:
            self._condition.wait_for(
                lambda: self._sequence > after or self._stop_event.is_set(), timeout=timeout
            )
            return self._sequence, self._frame

    def wait_for_image(self, after: int, timeout: float = 3.0) -> tuple[int, Image.Image | None]:
        """Wait for a new raw image, used by real-time transports such as WebRTC."""
        with self._condition:
            self._condition.wait_for(
                lambda: self._sequence > after or self._stop_event.is_set(), timeout=timeout
            )
            return self._sequence, self._image

    def latest_image(self) -> tuple[int, Image.Image | None]:
        """Return the newest image immediately without blocking the caller."""
        with self._condition:
            return self._sequence, self._image

    def _run(self) -> None:
        try:
            if self._virtual_display:
                capture_kde_virtual_display(
                    self._virtual_display,
                    self._stop_event,
                    self.config.fps,
                    self._publish_image,
                )
                return
            if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
                from .wayland import capture_wayland

                capture_wayland(self._stop_event, self.config.fps, self._publish_image)
                return
            self._run_mss()
        except Exception as exc:  # capture errors depend on the desktop/session
            LOGGER.exception("Screen capture stopped")
            with self._condition:
                self._error = str(exc)
                self._condition.notify_all()

    def _run_mss(self) -> None:
        interval = 1.0 / self.config.fps
        with mss.mss() as screen:
            if len(screen.monitors) < 2:
                raise RuntimeError("no physical monitor was detected")
            monitor = screen.monitors[1]
            while not self._stop_event.is_set():
                started = time.monotonic()
                shot = screen.grab(monitor)
                self._publish_image(Image.frombytes("RGB", shot.size, shot.rgb))
                self._stop_event.wait(max(0.0, interval - (time.monotonic() - started)))

    def _publish_image(self, image: Image.Image) -> None:
        """Resize, encode and atomically publish a captured image."""
        if self.config.scale != 1.0:
            size = (
                max(1, round(image.width * self.config.scale)),
                max(1, round(image.height * self.config.scale)),
            )
            image = image.resize(size, Image.Resampling.LANCZOS)
        jpeg: bytes | None = None
        if self._mjpeg_enabled:
            output = io.BytesIO()
            image.save(output, "JPEG", quality=self.config.jpeg_quality, optimize=False)
            jpeg = output.getvalue()
        with self._condition:
            self._image = image
            if jpeg is not None:
                self._frame = jpeg
            self._sequence += 1
            self._error = None
            self._condition.notify_all()
