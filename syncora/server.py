"""Flask application and command-line entry point."""

from __future__ import annotations

import logging
import socket
from collections.abc import Iterator
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from .capture import FrameProducer
from .config import Config, ConfigError, parse_config
from .webrtc import WebRTCManager
from .rtsp import DirectRtspServer
from .udp import DirectUdpStreamer

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def local_ip() -> str:
    """Best-effort local address detection without sending network traffic."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def create_app(
    config: Config,
    producer: FrameProducer | None = None,
    webrtc: WebRTCManager | None = None,
    direct: DirectRtspServer | None = None,
    udp: DirectUdpStreamer | None = None,
) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )
    frames = producer or FrameProducer(config)
    rtc = webrtc or WebRTCManager(frames)
    direct_server = direct or DirectRtspServer(frames)
    udp_streamer = udp or DirectUdpStreamer(frames)
    app.extensions["syncora_frames"] = frames
    app.extensions["syncora_webrtc"] = rtc
    app.extensions["syncora_direct"] = direct_server
    app.extensions["syncora_udp"] = udp_streamer

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/health")
    def health() -> tuple[Response, int] | Response:
        if frames.error:
            return jsonify(status="error", message=frames.error), 503
        return jsonify(status="ok")

    @app.get("/stream")
    def stream() -> Response:
        frames.enable_mjpeg()
        frames.start()

        def generate() -> Iterator[bytes]:
            sequence = 0
            while True:
                sequence, frame = frames.wait_for_frame(sequence)
                if frame is None:
                    if frames.error:
                        return
                    continue
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"

        return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.post("/webrtc/offer")
    def webrtc_offer() -> tuple[Response, int] | Response:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="a JSON WebRTC offer is required"), 400
        try:
            answer = rtc.handle_offer(str(payload.get("sdp", "")), str(payload.get("type", "")))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception:
            LOGGER.exception("Could not negotiate WebRTC")
            return jsonify(error="WebRTC negotiation failed"), 500
        return jsonify(answer)

    @app.post("/direct/start")
    def direct_start() -> tuple[Response, int] | Response:
        payload = request.get_json(silent=True) or {}
        try:
            port = int(payload.get("port", 5004))
            return jsonify(udp_streamer.start(request.remote_addr or "", port))
        except (TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            LOGGER.exception("Could not start Syncora Direct")
            return jsonify(error=str(exc)), 503

    @app.post("/direct/rtsp/start")
    def direct_rtsp_start() -> tuple[Response, int] | Response:
        try:
            return jsonify(direct_server.start())
        except Exception as exc:
            LOGGER.exception("Could not start Syncora Direct RTSP fallback")
            return jsonify(error=str(exc)), 503

    return app


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        config = parse_config()
    except ConfigError as exc:
        LOGGER.error("Invalid configuration: %s", exc)
        return 2

    producer = FrameProducer(config)
    rtc = WebRTCManager(producer)
    direct = DirectRtspServer(producer)
    udp = DirectUdpStreamer(producer)
    app = create_app(config, producer, rtc, direct, udp)
    display_host = local_ip() if config.host in {"0.0.0.0", "::"} else config.host
    print(f"Syncora is ready: http://{display_host}:{config.port}", flush=True)
    if config.extend:
        print(
            f"Extended mode: a {config.virtual_resolution} virtual display will be created "
            "when the first viewer connects.",
            flush=True,
        )
    print("Open this address on a device connected to the same local network.", flush=True)
    try:
        app.run(**config.server_options())
    except OSError as exc:
        LOGGER.error("Could not start the server: %s", exc)
        return 1
    except KeyboardInterrupt:
        print("\nStopping Syncora…")
    finally:
        try:
            udp.stop()
        finally:
            try:
                direct.stop()
            finally:
                try:
                    rtc.stop()
                finally:
                    # The virtual monitor must disappear even if media shutdown times out.
                    producer.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
