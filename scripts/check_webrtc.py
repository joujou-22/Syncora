"""Manual end-to-end check of a running Syncora WebRTC server."""

from __future__ import annotations

import argparse
import asyncio
import json
import urllib.request

from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription


async def check(base_url: str) -> None:
    peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    video_ready: asyncio.Future = asyncio.get_running_loop().create_future()
    audio_ready: asyncio.Future = asyncio.get_running_loop().create_future()

    @peer.on("track")
    def on_track(track) -> None:
        target = video_ready if track.kind == "video" else audio_ready
        if not target.done():
            target.set_result(track)

    try:
        peer.addTransceiver("video", direction="recvonly")
        peer.addTransceiver("audio", direction="recvonly")
        await peer.setLocalDescription(await peer.createOffer())
        payload = json.dumps(
            {"sdp": peer.localDescription.sdp, "type": peer.localDescription.type}
        ).encode()
        request = urllib.request.Request(
            base_url.rstrip("/") + "/webrtc/offer",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            answer = json.load(response)
        await peer.setRemoteDescription(
            RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
        )
        track = await asyncio.wait_for(video_ready, timeout=15)
        frame = await asyncio.wait_for(track.recv(), timeout=20)
        print(f"WebRTC frame received: {frame.width}x{frame.height}, pts={frame.pts}")
        audio_track = await asyncio.wait_for(audio_ready, timeout=15)
        audio_frame = await asyncio.wait_for(audio_track.recv(), timeout=20)
        print(
            f"WebRTC audio received: {audio_frame.sample_rate} Hz, "
            f"{audio_frame.layout.name}, {audio_frame.samples} samples"
        )
    finally:
        await peer.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    asyncio.run(check(args.url))


if __name__ == "__main__":
    main()
