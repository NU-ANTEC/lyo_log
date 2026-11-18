import smtplib
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lyo_config import load_settings

with patch("smtplib.SMTP_SSL", side_effect=AssertionError("import attempted mail")), \
     patch("os.listdir", side_effect=AssertionError("import attempted cleanup")):
    from send_alert_email import send_alert
    from rclone_lyo import upload


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = load_settings(project_dir=self.root,
                                      environ={"LABCONCO_STYLE": "freezone"})

    def test_disabled_integrations_have_no_external_effect(self):
        with patch("send_alert_email.smtplib.SMTP_SSL", side_effect=AssertionError("disabled mail")):
            self.assertFalse(send_alert("Vacuum", self.settings))
        self.assertEqual(upload(self.settings, runner=lambda *a, **kw: self.fail("disabled upload")), 0)

    def test_mail_uses_configured_instrument_and_credentials(self):
        settings = replace(self.settings, alerts_enabled=True, instrument_name="Test instrument",
                           gmail_user="sender@example.invalid", gmail_app_password="test-secret",
                           alert_recipient="recipient@example.invalid")
        messages = []
        class Server:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def login(server, user, password):
                self.assertEqual((user, password), ("sender@example.invalid", "test-secret"))
            def send_message(server, message):
                messages.append(message)
        with patch("send_alert_email.smtplib.SMTP_SSL", return_value=Server()):
            self.assertTrue(send_alert("Vacuum", settings))
        self.assertEqual(messages[0]["Subject"], "Test instrument Alert: Vacuum")
        self.assertIn("Test instrument", messages[0].get_content())
        self.assertEqual(messages[0]["To"], "recipient@example.invalid")

    def test_mail_failure_is_false_and_does_not_log_password(self):
        settings = replace(self.settings, alerts_enabled=True, gmail_app_password="test-secret")
        with patch("send_alert_email.smtplib.SMTP_SSL",
                   side_effect=smtplib.SMTPAuthenticationError(535, b"test-secret")), \
             self.assertLogs("send_alert_email", level="ERROR") as captured:
            self.assertFalse(send_alert("Vacuum", settings))
        self.assertNotIn("test-secret", "\n".join(captured.output))

    def test_rclone_uses_argument_list_and_does_not_purge_source(self):
        source = self.root / "data with spaces"
        source.mkdir()
        old = source / "000101.txt"
        old.write_text("preserve")
        settings = replace(self.settings, upload_enabled=True, rclone_source=source,
                           rclone_destination="example:folder with spaces")
        commands = []
        def run(command, **kwargs):
            snapshot = Path(command[2])
            self.assertNotEqual(snapshot, source)
            self.assertEqual((snapshot / "000101.txt").read_text(), "preserve")
            commands.append((command, kwargs))
            return SimpleNamespace(returncode=0)
        self.assertEqual(upload(settings, runner=run), 0)
        self.assertEqual(len(commands), 1)
        command, kwargs = commands[0]
        self.assertEqual(len(command), 4)
        self.assertEqual(command[:2], ["rclone", "copy"])
        self.assertEqual(command[3], "example:folder with spaces")
        self.assertEqual(kwargs, {"check": True})
        self.assertFalse(Path(command[2]).exists())
        self.assertEqual(old.read_text(), "preserve")

    def test_upload_failure_returns_nonzero(self):
        def fail(*args, **kwargs):
            raise subprocess.CalledProcessError(1, args[0])
        with self.assertLogs("rclone_lyo", level="ERROR"):
            self.assertEqual(upload(replace(self.settings, upload_enabled=True), runner=fail), 1)


if __name__ == "__main__":
    unittest.main()
