"""Virtual display backends used by extended-screen mode."""

from __future__ import annotations

import logging
import os
import secrets
import select
import shutil
import socket
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from PIL import Image

LOGGER = logging.getLogger(__name__)


class VirtualDisplayError(RuntimeError):
    """Raised when the desktop cannot create a virtual output."""


def _free_port() -> int:
    """Ask the kernel for an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return int(sock.getsockname()[1])


def _find_direct_helper() -> str | None:
    """Find the KDE helper even when Fish does not include ~/.local/bin in PATH."""
    candidates = [
        shutil.which("syncora-kde-virtual-monitor"),
        str(Path.home() / ".local/bin/syncora-kde-virtual-monitor"),
        str(
            Path(__file__).resolve().parents[1]
            / "native/kde-virtual-monitor/build/syncora-kde-virtual-monitor"
        ),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class KDEVirtualDisplay:
    """Keep a KWin virtual output alive through krfb-virtualmonitor."""

    def __init__(
        self,
        resolution: str,
        name: str = "Syncora",
        scale: float = 1.0,
    ) -> None:
        self.resolution = resolution
        self.name = name
        self.scale = scale
        self.port: int | None = None
        self.password = secrets.token_urlsafe(32)
        self.pipewire_node: int | None = None
        self._direct = False
        self._process: subprocess.Popen | None = None

    def command(self) -> list[str]:
        direct = _find_direct_helper()
        if direct:
            try:
                width, height = self.resolution.split("x", 1)
            except ValueError as exc:
                raise VirtualDisplayError("virtual resolution must use WIDTHxHEIGHT") from exc
            self._direct = True
            return [direct, self.name, width, height]

        executable = shutil.which("krfb-virtualmonitor")
        if not executable:
            raise VirtualDisplayError(
                "extended mode on KDE needs syncora-kde-virtual-monitor or krfb-virtualmonitor"
            )
        self._direct = False
        self.port = _free_port()
        return [
            executable,
            "--resolution",
            self.resolution,
            "--name",
            self.name,
            "--password",
            self.password,
            "--port",
            str(self.port),
            "--scale",
            str(self.scale),
        ]

    def start(self) -> None:
        if self._process and self._process.poll() is None:
            return
        if os.environ.get("XDG_SESSION_TYPE", "").lower() != "wayland":
            raise VirtualDisplayError("the KDE extended-screen backend requires a Wayland session")
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if "kde" not in desktop:
            raise VirtualDisplayError("this extended-screen backend currently supports KDE Plasma only")
        command = self.command()
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if self._direct else subprocess.DEVNULL,
            stderr=subprocess.PIPE if self._direct else subprocess.DEVNULL,
            text=self._direct,
            bufsize=1,
            start_new_session=True,
        )
        if self._direct:
            assert self._process.stdout is not None
            readable, _, _ = select.select([self._process.stdout], [], [], 5.0)
            if not readable:
                self.stop()
                raise VirtualDisplayError("KWin did not create the direct PipeWire display")
            line = self._process.stdout.readline().strip()
            try:
                self.pipewire_node = int(line)
            except ValueError as exc:
                details = ""
                if self._process.stderr is not None and self._process.poll() is not None:
                    details = self._process.stderr.read().strip()
                self.stop()
                raise VirtualDisplayError(details or "invalid PipeWire node from KDE helper") from exc
        else:
            time.sleep(0.8)
        return_code = self._process.poll()
        if return_code is not None:
            self._process = None
            raise VirtualDisplayError(
                f"krfb-virtualmonitor stopped during startup (exit code {return_code})"
            )
        backend = "PipeWire directly" if self._direct else "local RFB fallback"
        LOGGER.info("Virtual display Virtual-%s (%s) is ready via %s", self.name, self.resolution, backend)

    def stop(self) -> None:
        process, self._process = self._process, None
        if not process or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def virtual_display_for(resolution: str) -> KDEVirtualDisplay:
    """Select the appropriate virtual-display backend for the current desktop."""
    return KDEVirtualDisplay(resolution=resolution)


def capture_kde_virtual_display(
    display: KDEVirtualDisplay,
    stop_event,
    fps: float,
    on_image: Callable[[Image.Image], None],
) -> None:
    """Read the helper's loopback RFB stream into RGB images."""
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
    except (ImportError, ValueError) as exc:
        raise VirtualDisplayError("extended mode needs the GStreamer PipeWire or RFB plugin") from exc

    Gst.init(None)
    if display.pipewire_node is not None:
        pipeline = Gst.parse_launch(
            "pipewiresrc name=source ! "
            "queue max-size-buffers=1 max-size-bytes=0 max-size-time=0 leaky=downstream ! "
            "videorate drop-only=true ! "
            f"video/x-raw,framerate={max(1, round(fps))}/1 ! "
            "videoconvert ! video/x-raw,format=RGB ! "
            "appsink name=sink sync=false max-buffers=1 drop=true"
        )
    else:
        pipeline = Gst.parse_launch(
            f"rfbsrc name=source ! videorate ! "
            f"video/x-raw,framerate={max(1, round(fps))}/1 ! "
            "videoconvert ! video/x-raw,format=RGB ! "
            "appsink name=sink sync=false max-buffers=1 drop=true"
        )
    source = pipeline.get_by_name("source")
    if display.pipewire_node is not None:
        source.set_property("path", str(display.pipewire_node))
        source.set_property("do-timestamp", True)
        source.set_property("always-copy", False)
    else:
        source.set_property("host", "127.0.0.1")
        source.set_property("port", display.port)
        source.set_property("password", display.password)
        source.set_property("shared", True)
        source.set_property("view-only", True)
        source.set_property("do-timestamp", True)
        source.set_property("incremental", False)
    sink = pipeline.get_by_name("sink")
    try:
        pipeline.set_state(Gst.State.PLAYING)
        while not stop_event.is_set():
            sample = sink.emit("try-pull-sample", Gst.SECOND)
            if sample is None:
                message = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
                if message:
                    if stop_event.is_set():
                        return
                    error, _debug = message.parse_error()
                    raise VirtualDisplayError(f"virtual display capture failed: {error.message}")
                continue
            caps = sample.get_caps().get_structure(0)
            width, height = caps.get_value("width"), caps.get_value("height")
            buffer = sample.get_buffer()
            ok, mapped = buffer.map(Gst.MapFlags.READ)
            if not ok:
                raise VirtualDisplayError("could not read a virtual display frame")
            try:
                stride = len(mapped.data) // height
                image = Image.frombytes("RGB", (width, height), mapped.data, "raw", "RGB", stride)
                on_image(image)
            finally:
                buffer.unmap(mapped)
    finally:
        pipeline.set_state(Gst.State.NULL)
