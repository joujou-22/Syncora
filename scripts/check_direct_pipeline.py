"""Benchmark KDE PipeWire -> VA-API H.264 without the PIL capture path."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import av

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syncora.display import KDEVirtualDisplay, VirtualDisplayError


def check(resolution: str, fps: int, bitrate_mbps: float, frame_count: int) -> None:
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
    except (ImportError, ValueError) as exc:
        raise SystemExit("GStreamer Python bindings are required") from exc

    Gst.init(None)
    if Gst.ElementFactory.find("vaapih264enc") is None:
        raise SystemExit("vaapih264enc is unavailable (install gstreamer1.0-vaapi)")

    display = KDEVirtualDisplay(resolution=resolution, name="Syncora-Benchmark")
    display.start()
    try:
        if display.pipewire_node is None:
            raise VirtualDisplayError("the benchmark requires the direct PipeWire helper")
        bitrate_kbps = max(500, round(bitrate_mbps * 1000))
        keepalive_ms = max(1, round(1000 / fps))
        pipeline = Gst.parse_launch(
            f"pipewiresrc path={display.pipewire_node} do-timestamp=true "
            f"always-copy=false resend-last=true keepalive-time={keepalive_ms} ! "
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
        sink = pipeline.get_by_name("sink")
        decoder = av.CodecContext.create("h264", "r")
        encoded_bytes = 0
        decoded_frames = 0
        started = time.monotonic()
        pipeline.set_state(Gst.State.PLAYING)
        try:
            for _ in range(frame_count):
                sample = sink.emit("try-pull-sample", 3 * Gst.SECOND)
                if sample is None:
                    message = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
                    if message:
                        error, debug = message.parse_error()
                        raise RuntimeError(f"GStreamer: {error.message}\n{debug}")
                    raise RuntimeError("timed out waiting for an encoded frame")
                buffer = sample.get_buffer()
                ok, mapped = buffer.map(Gst.MapFlags.READ)
                if not ok:
                    raise RuntimeError("could not map an encoded frame")
                try:
                    data = bytes(mapped.data)
                finally:
                    buffer.unmap(mapped)
                encoded_bytes += len(data)
                decoded_frames += len(decoder.decode(av.Packet(data)))
        finally:
            pipeline.set_state(Gst.State.NULL)
        elapsed = time.monotonic() - started
        print(
            f"Direct pipeline: {frame_count} encoded / {decoded_frames} decoded frames, "
            f"{frame_count / elapsed:.1f} fps, "
            f"{encoded_bytes * 8 / elapsed / 1_000_000:.2f} Mbps"
        )
    finally:
        display.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", default="1920x1080")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--video-bitrate", type=float, default=10)
    parser.add_argument("--frames", type=int, default=120)
    args = parser.parse_args()
    check(args.resolution, args.fps, args.video_bitrate, args.frames)


if __name__ == "__main__":
    main()
