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


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app(Config(), FakeProducer(), FakeWebRTC()).test_client()

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


if __name__ == "__main__":
    unittest.main()
