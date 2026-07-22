# Syncora Android client

Native Android and Android TV client for Syncora. It validates local-network
access through `/health`, negotiates directly with `/webrtc/offer`, and renders
the H.264 stream through Android's native WebRTC hardware-decoding path.

The experimental Syncora Direct path requests `/direct/start`, receives H.264
over RTP/RTSP, and renders it with Android MediaCodec through Media3. WebRTC is
kept as the compatibility fallback while Direct is developed.

The primary Direct path uses a tiny custom H.264/RTP receiver with a single
atomic pending-frame slot feeding MediaCodec. Late encoded and decoded frames
are discarded instead of accumulating playback latency.

Open this directory as a project in Android Studio. The application supports
Android 6.0 (API 23) and newer and appears in both regular and Android TV launchers.
