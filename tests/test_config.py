import unittest

from syncora.config import Config, ConfigError, config_from_env, parse_config


class ConfigTests(unittest.TestCase):
    def test_defaults_are_valid(self):
        config = Config().validate()
        self.assertEqual(config.port, 8080)
        self.assertEqual(config.fps, 15)

    def test_server_options_disable_debug_and_reloader(self):
        options = Config(port=9000).server_options()
        self.assertEqual(options["host"], "0.0.0.0")
        self.assertEqual(options["port"], 9000)
        self.assertFalse(options["debug"])
        self.assertFalse(options["use_reloader"])

    def test_environment_values_are_loaded(self):
        config = config_from_env({"SYNCORA_FPS": "5", "SYNCORA_SCALE": "0.5"})
        self.assertEqual(config.fps, 5)
        self.assertEqual(config.scale, 0.5)

    def test_command_line_overrides_environment(self):
        config = parse_config(["--port", "9090"], {"SYNCORA_PORT": "8081"})
        self.assertEqual(config.port, 9090)

    def test_invalid_ranges_are_rejected(self):
        for config in (Config(port=0), Config(fps=0), Config(jpeg_quality=100), Config(scale=2)):
            with self.subTest(config=config), self.assertRaises(ConfigError):
                config.validate()

    def test_non_numeric_environment_value_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "SYNCORA_PORT must be a number"):
            config_from_env({"SYNCORA_PORT": "nope"})


if __name__ == "__main__":
    unittest.main()
