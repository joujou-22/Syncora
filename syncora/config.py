"""Application configuration and command-line parsing."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import Mapping, Sequence


class ConfigError(ValueError):
    """Raised when a configuration value is outside its accepted range."""


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"
    port: int = 8080
    fps: float = 15.0
    jpeg_quality: int = 75
    scale: float = 1.0

    def validate(self) -> "Config":
        if not self.host.strip():
            raise ConfigError("host must not be empty")
        if not 1 <= self.port <= 65535:
            raise ConfigError("port must be between 1 and 65535")
        if not 1 <= self.fps <= 30:
            raise ConfigError("fps must be between 1 and 30")
        if not 1 <= self.jpeg_quality <= 95:
            raise ConfigError("JPEG quality must be between 1 and 95")
        if not 0.1 <= self.scale <= 1.0:
            raise ConfigError("scale must be between 0.1 and 1.0")
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
    return Config(
        host=values.get("SYNCORA_HOST", "0.0.0.0"),
        port=_number("SYNCORA_PORT", values.get("SYNCORA_PORT", "8080"), int),
        fps=_number("SYNCORA_FPS", values.get("SYNCORA_FPS", "15"), float),
        jpeg_quality=_number(
            "SYNCORA_JPEG_QUALITY", values.get("SYNCORA_JPEG_QUALITY", "75"), int
        ),
        scale=_number("SYNCORA_SCALE", values.get("SYNCORA_SCALE", "1.0"), float),
    ).validate()


def parse_config(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> Config:
    defaults = config_from_env(env)
    parser = argparse.ArgumentParser(description="Share the primary screen on the local network.")
    parser.add_argument("--host", default=defaults.host, help="listening address")
    parser.add_argument("--port", type=int, default=defaults.port, help="TCP port (default: 8080)")
    parser.add_argument("--fps", type=float, default=defaults.fps, help="frames per second")
    parser.add_argument("--quality", type=int, default=defaults.jpeg_quality, help="JPEG quality")
    parser.add_argument("--scale", type=float, default=defaults.scale, help="resize factor (0.1 to 1.0)")
    args = parser.parse_args(argv)
    return Config(args.host, args.port, args.fps, args.quality, args.scale).validate()
