import unittest
from unittest.mock import MagicMock, patch

from syncora.display import KDEVirtualDisplay, VirtualDisplayError


class VirtualDisplayTests(unittest.TestCase):
    def setUp(self):
        port_patch = patch("syncora.display._free_port", return_value=5901)
        port_patch.start()
        self.addCleanup(port_patch.stop)

    @patch("syncora.display.shutil.which", return_value="/usr/bin/krfb-virtualmonitor")
    def test_kde_command_contains_requested_geometry_and_random_password(self, _which):
        display = KDEVirtualDisplay("1280x720", name="Syncora", scale=1.0)
        command = display.command()
        self.assertEqual(command[0], "/usr/bin/krfb-virtualmonitor")
        self.assertIn("1280x720", command)
        self.assertIn("Syncora", command)
        self.assertNotEqual(display.password, "")

    @patch("syncora.display.shutil.which", return_value=None)
    def test_missing_kde_helper_has_clear_error(self, _which):
        with self.assertRaisesRegex(VirtualDisplayError, "install the krfb package"):
            KDEVirtualDisplay("1280x720").command()

    @patch("syncora.display.time.sleep")
    @patch("syncora.display.subprocess.Popen")
    def test_stop_terminates_the_helper(self, popen, _sleep):
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
