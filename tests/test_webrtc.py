import asyncio
import unittest

from PIL import Image

from syncora.webrtc import ScreenVideoTrack


class FakeImageProducer:
    error = None

    def latest_image(self):
        if not hasattr(self, "sequence"):
            self.sequence = 0
        self.sequence += 1
        return self.sequence, Image.new("RGB", (64, 36), "navy")


class WebRTCTests(unittest.TestCase):
    def test_screen_track_builds_timestamped_video_frames(self):
        async def receive_two_frames():
            track = ScreenVideoTrack(FakeImageProducer())
            return await track.recv(), await track.recv()

        first, second = asyncio.run(receive_two_frames())
        self.assertEqual((first.width, first.height), (64, 36))
        self.assertEqual(str(first.time_base), "1/90000")
        self.assertGreater(second.pts, first.pts)


if __name__ == "__main__":
    unittest.main()
