import unittest

from syncora.config import Config
from syncora.server import create_app


class FakeProducer:
    error = None

    def start(self):
        pass

    def enable_mjpeg(self):
        pass

    def wait_for_frame(self, after, timeout=3.0):
        return after + 1, b"jpeg"


class FakeWebRTC:
    def handle_offer(self, sdp, offer_type):
        if not sdp or offer_type != "offer":
            raise ValueError("a non-empty WebRTC offer is required")
        return {"sdp": "answer-sdp", "type": "answer"}


class FakeDirect:
    def __init__(self):
        self.starts = 0

    def start(self):
        self.starts += 1
        return {"transport": "rtsp", "port": 8554, "path": "/syncora"}


class FakeUdp:
    def __init__(self):
        self.target = None

    def start(self, host, port):
        self.target = (host, port)
        return {
            "transport": "rtp-h264-udp", "port": port,
            "width": 1280, "height": 720,
        }


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.direct = FakeDirect()
        self.udp = FakeUdp()
        self.client = create_app(
            Config(), FakeProducer(), FakeWebRTC(), self.direct, self.udp
        ).test_client()

    def test_index_is_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Syncora", response.data)

    def test_health_is_json(self):
        self.assertEqual(self.client.get("/health").json, {"status": "ok"})

    def test_stream_uses_mjpeg_boundary(self):
        response = self.client.get("/stream", buffered=False)
        self.assertIn("multipart/x-mixed-replace", response.content_type)
        self.assertIn(b"Content-Type: image/jpeg", next(response.response))

    def test_webrtc_offer_returns_answer(self):
        response = self.client.post("/webrtc/offer", json={"sdp": "offer-sdp", "type": "offer"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"sdp": "answer-sdp", "type": "answer"})

    def test_webrtc_offer_rejects_invalid_payload(self):
        self.assertEqual(self.client.post("/webrtc/offer", json={}).status_code, 400)

    def test_direct_start_returns_udp_video_parameters(self):
        response = self.client.post("/direct/start", json={"port": 5004})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json,
            {
                "transport": "rtp-h264-udp", "port": 5004,
                "width": 1280, "height": 720,
            },
        )
        self.assertEqual(self.udp.target, ("127.0.0.1", 5004))

    def test_direct_rtsp_fallback_remains_available(self):
        response = self.client.post("/direct/rtsp/start")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["transport"], "rtsp")

    def test_direct_metrics_require_all_counters(self):
        self.assertEqual(self.client.post("/direct/metrics", json={}).status_code, 400)
        response = self.client.post(
            "/direct/metrics",
            json={
                "packets": 100, "missing": 0, "frames": 30,
                "damaged": 0, "replaced": 1, "codec_drops": 0,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["ok"])


if __name__ == "__main__":
    unittest.main()
