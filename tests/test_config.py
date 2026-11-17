import tempfile
import unittest
from pathlib import Path

from lyo_config import ConfigError, load_settings


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def load(self, **values):
        return load_settings(project_dir=self.root,
                             environ={"LABCONCO_STYLE": "freezone", **values})

    def test_safe_defaults_and_all_observed_modes(self):
        for mode in ("freezone", "stoppering_combined", "stoppering_direct"):
            with self.subTest(mode=mode):
                settings = self.load(LABCONCO_STYLE=mode)
                self.assertEqual(settings.serial_baudrate, 2400)
                self.assertEqual(settings.log_directory, self.root / "data")
                self.assertEqual(settings.png_directory, settings.log_directory)
                self.assertFalse(settings.alerts_enabled)
                self.assertFalse(settings.upload_enabled)
                self.assertFalse(settings.usb_reset_enabled)
                self.assertEqual(settings.data_retention_days, 0)
                self.assertTrue(settings.serial_recovery_enabled)

    def test_dotenv_location_and_environment_precedence(self):
        (self.root / ".env").write_text(
            "LABCONCO_STYLE=stoppering_direct\nPLOT_INTERVAL_SECONDS=80\n"
            "LOG_DIRECTORY=./recordings\nINSTRUMENT_NAME=Generic instrument\n")
        settings = load_settings(project_dir=self.root,
                                 environ={"PLOT_INTERVAL_SECONDS": "20"})
        self.assertEqual(settings.style, "stoppering_direct")
        self.assertEqual(settings.plot_interval_seconds, 20)
        self.assertEqual(settings.log_directory, self.root / "recordings")
        self.assertEqual(settings.instrument_name, "Generic instrument")

    def test_alternate_env_and_paths(self):
        env = self.root / "test.env"
        env.write_text("LABCONCO_STYLE=freezone\nLOG_DIRECTORY=/var/data\n")
        settings = load_settings(env_file=env, project_dir=self.root, environ={})
        self.assertEqual(settings.log_directory, Path("/var/data"))
        self.assertEqual(self.load(LOG_DIRECTORY="~/logs").log_directory,
                         Path.home() / "logs")

    def test_missing_or_unknown_modes_are_errors(self):
        for values in ({}, {"LABCONCO_STYLE": "bulk"}, {"LABCONCO_STYLE": "auto"}):
            with self.assertRaisesRegex(ConfigError, "LABCONCO_STYLE"):
                load_settings(project_dir=self.root, environ=values)

    def test_invalid_numeric_boolean_and_range_settings(self):
        cases = {
            "SERIAL_BAUDRATE": "0", "SERIAL_TIMEOUT_SECONDS": "nan",
            "ALERT_DURATION_HOURS": "-1", "PRESSURE_MIN_UBAR": "0",
            "TEMPERATURE_MAX_C": "-100", "PLOT_WIDTH_INCHES": "inf",
            "SERIAL_IDLE_TIMEOUT_SECONDS": "5", "SERIAL_REOPEN_ATTEMPTS": "1.5",
            "SERIAL_RETRY_MAX_SECONDS": "0.1", "DATA_RETENTION_DAYS": "-1",
            "SMTP_PORT": "65536", "UPLOAD_ENABLED": "maybe",
        }
        for key, value in cases.items():
            with self.subTest(key=key), self.assertRaisesRegex(ConfigError, key):
                self.load(**{key: value})

    def test_optional_credentials_do_not_block_recording(self):
        settings = load_settings(project_dir=self.root, operation="record",
                                 environ={"LABCONCO_STYLE": "freezone",
                                          "ALERTS_ENABLED": "true",
                                          "UPLOAD_ENABLED": "true"})
        self.assertTrue(settings.alerts_enabled)
        with self.assertRaisesRegex(ConfigError, "PRESSURE_THRESHOLD"):
            self.load(ALERTS_ENABLED="true")
        with self.assertRaisesRegex(ConfigError, "RCLONE_DESTINATION"):
            load_settings(project_dir=self.root, operation="upload", environ={
                "LABCONCO_STYLE": "freezone", "UPLOAD_ENABLED": "true"})

    def test_reset_requires_identity_without_leaking_credentials(self):
        with self.assertRaisesRegex(ConfigError, "USB_VENDOR_ID"):
            self.load(USB_RESET_ENABLED="true")
        settings = self.load(USB_RESET_ENABLED="true", USB_VENDOR_ID="1234",
                             USB_PRODUCT_ID="ABCD", USB_SERIAL_NUMBER="example")
        self.assertEqual(settings.usb_product_id, "abcd")
        settings = self.load(GMAIL_APP_PASSWORD="private-value")
        self.assertNotIn("private-value", repr(settings))


if __name__ == "__main__":
    unittest.main()
