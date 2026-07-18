import unittest
from unittest.mock import MagicMock, patch

from syncora.display import KDEVirtualDisplay, VirtualDisplayError


class VirtualDisplayTests(unittest.TestCase):
    def setUp(self):
        port_patch = patch("syncora.display._free_port", return_value=5901)
        port_patch.start()
        self.addCleanup(port_patch.stop)

    @patch("syncora.display._find_direct_helper", return_value=None)
    @patch("syncora.display.shutil.which", return_value="/usr/bin/krfb-virtualmonitor")
    def test_kde_command_contains_requested_geometry_and_random_password(self, _which, _direct):
        display = KDEVirtualDisplay("1280x720", name="Syncora", scale=1.0)
        command = display.command()
        self.assertEqual(command[0], "/usr/bin/krfb-virtualmonitor")
        self.assertIn("1280x720", command)
        self.assertIn("Syncora", command)
        self.assertNotEqual(display.password, "")

    @patch(
        "syncora.display._find_direct_helper",
        return_value="/usr/bin/syncora-kde-virtual-monitor",
    )
    def test_direct_command_uses_separate_width_and_height(self, _direct):
        display = KDEVirtualDisplay("1920x1080", name="Syncora")
        self.assertEqual(
            display.command(),
            ["/usr/bin/syncora-kde-virtual-monitor", "Syncora", "1920", "1080"],
        )

    @patch("syncora.display._find_direct_helper", return_value=None)
    @patch("syncora.display.shutil.which", return_value=None)
    def test_missing_kde_helper_has_clear_error(self, _which, _direct):
        with self.assertRaisesRegex(VirtualDisplayError, "syncora-kde-virtual-monitor"):
            KDEVirtualDisplay("1280x720").command()

    @patch("syncora.display.time.sleep")
    @patch("syncora.display.subprocess.Popen")
    @patch("syncora.display._find_direct_helper", return_value=None)
    @patch("syncora.display.shutil.which", return_value="/usr/bin/krfb-virtualmonitor")
    def test_stop_terminates_the_helper(self, _which, _direct, popen, _sleep):
        process = MagicMock()
        process.poll.side_effect = [None, None]
        popen.return_value = process
        display = KDEVirtualDisplay("1280x720")
        with patch.dict(
            "os.environ", {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"}
        ):
            display.start()
            display.stop()
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=3)


if __name__ == "__main__":
    unittest.main()
