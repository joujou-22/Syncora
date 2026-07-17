import unittest

from unittest.mock import patch

from syncora.audio import AUDIO_RATE, SystemAudioProducer, default_monitor


class AudioProducerTests(unittest.TestCase):
    def test_audio_device_can_be_overridden_without_system_lookup(self):
        with patch.dict("os.environ", {"SYNCORA_AUDIO_DEVICE": "custom.monitor"}):
            self.assertEqual(default_monitor(), "custom.monitor")

    def test_pcm_bytes_become_timestamped_stereo_frame(self):
        producer = SystemAudioProducer()
        producer._publish(bytes(960 * 2 * 2))
        frame = producer.read(timeout=0.01)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.sample_rate, AUDIO_RATE)
        self.assertEqual(frame.layout.name, "stereo")
        self.assertEqual(frame.samples, 960)
        self.assertEqual(frame.pts, 0)
        self.assertEqual(str(frame.time_base), "1/48000")

    def test_queue_drops_old_audio_instead_of_growing_forever(self):
        producer = SystemAudioProducer()
        for _ in range(20):
            producer._publish(bytes(480 * 2 * 2))
        self.assertLessEqual(producer._frames.qsize(), 10)


if __name__ == "__main__":
    unittest.main()
