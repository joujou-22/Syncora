"""Application configuration and command-line parsing."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from typing import Mapping, Sequence


class ConfigError(ValueError):
    """Raised when a configuration value is outside its accepted range."""


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"
    port: int = 8080
    rtsp_port: int = 8554
    fps: float = 15.0
    video_bitrate_mbps: float = 6.0
    jpeg_quality: int = 75
    scale: float = 1.0
    extend: bool = False
    virtual_resolution: str = "1280x720"

    def validate(self) -> "Config":
        if not self.host.strip():
            raise ConfigError("host must not be empty")
        if not 1 <= self.port <= 65535:
            raise ConfigError("port must be between 1 and 65535")
        if not 1 <= self.rtsp_port <= 65535 or self.rtsp_port == self.port:
            raise ConfigError("RTSP port must be valid and different from the HTTP port")
        if not 1 <= self.fps <= 60:
            raise ConfigError("fps must be between 1 and 60")
        if not 0.5 <= self.video_bitrate_mbps <= 50:
            raise ConfigError("video bitrate must be between 0.5 and 50 Mbps")
        if not 1 <= self.jpeg_quality <= 95:
            raise ConfigError("JPEG quality must be between 1 and 95")
        if not 0.1 <= self.scale <= 1.0:
            raise ConfigError("scale must be between 0.1 and 1.0")
        match = re.fullmatch(r"([1-9]\d{2,3})x([1-9]\d{2,3})", self.virtual_resolution)
        if not match:
            raise ConfigError("virtual resolution must use WIDTHxHEIGHT, for example 1280x720")
        width, height = map(int, match.groups())
        if not 640 <= width <= 7680 or not 480 <= height <= 4320:
            raise ConfigError("virtual resolution must be between 640x480 and 7680x4320")
        return self

    def server_options(self) -> dict[str, object]:
        """Return the safe options passed to Flask's development server."""
        return {
            "host": self.host,
            "port": self.port,
            "debug": False,
            "use_reloader": False,
            "threaded": True,
        }


def _number(name: str, value: str, converter: type[int] | type[float]) -> int | float:
    try:
        return converter(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {value!r}") from exc


def config_from_env(env: Mapping[str, str] | None = None) -> Config:
    values = os.environ if env is None else env
    extend_value = values.get("SYNCORA_EXTEND", "false").strip().lower()
    if extend_value not in {"1", "true", "yes", "0", "false", "no"}:
        raise ConfigError("SYNCORA_EXTEND must be true or false")
    return Config(
        host=values.get("SYNCORA_HOST", "0.0.0.0"),
        port=_number("SYNCORA_PORT", values.get("SYNCORA_PORT", "8080"), int),
        rtsp_port=_number(
            "SYNCORA_RTSP_PORT", values.get("SYNCORA_RTSP_PORT", "8554"), int
        ),
        fps=_number("SYNCORA_FPS", values.get("SYNCORA_FPS", "15"), float),
        video_bitrate_mbps=_number(
            "SYNCORA_VIDEO_BITRATE", values.get("SYNCORA_VIDEO_BITRATE", "6"), float
        ),
        jpeg_quality=_number(
            "SYNCORA_JPEG_QUALITY", values.get("SYNCORA_JPEG_QUALITY", "75"), int
        ),
        scale=_number("SYNCORA_SCALE", values.get("SYNCORA_SCALE", "1.0"), float),
        extend=extend_value in {"1", "true", "yes"},
        virtual_resolution=values.get("SYNCORA_VIRTUAL_RESOLUTION", "1280x720"),
    ).validate()


def parse_config(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> Config:
    defaults = config_from_env(env)
    parser = argparse.ArgumentParser(description="Share the primary screen on the local network.")
    parser.add_argument("--host", default=defaults.host, help="listening address")
    parser.add_argument("--port", type=int, default=defaults.port, help="TCP port (default: 8080)")
    parser.add_argument(
        "--rtsp-port", type=int, default=defaults.rtsp_port,
        help="native RTSP port (default: 8554)",
    )
    parser.add_argument("--fps", type=float, default=defaults.fps, help="frames per second")
    parser.add_argument(
        "--video-bitrate",
        type=float,
        default=defaults.video_bitrate_mbps,
        help="target WebRTC video bitrate in Mbps (default: 6)",
    )
    parser.add_argument("--quality", type=int, default=defaults.jpeg_quality, help="JPEG quality")
    parser.add_argument("--scale", type=float, default=defaults.scale, help="resize factor (0.1 to 1.0)")
    parser.add_argument(
        "--extend", action="store_true", default=defaults.extend,
        help="create and stream a virtual extended display (KDE Wayland prototype)",
    )
    parser.add_argument(
        "--virtual-resolution", default=defaults.virtual_resolution,
        help="virtual display resolution (default: 1280x720)",
    )
    args = parser.parse_args(argv)
    return Config(
        host=args.host,
        port=args.port,
        rtsp_port=args.rtsp_port,
        fps=args.fps,
        video_bitrate_mbps=args.video_bitrate,
        jpeg_quality=args.quality,
        scale=args.scale,
        extend=args.extend,
        virtual_resolution=args.virtual_resolution,
    ).validate()
