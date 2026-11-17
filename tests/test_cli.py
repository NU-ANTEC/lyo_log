"""Fixture-only end-to-end checks. All optional external operations stay off."""

import ast
import os
import select
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.fixtures import BASE, COMBINED, DIRECT

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {**os.environ, "LABCONCO_STYLE": "freezone", "ALERTS_ENABLED": "false",
                    "UPLOAD_ENABLED": "false", "USB_RESET_ENABLED": "false",
                    "DATA_RETENTION_DAYS": "0", "LOG_DIRECTORY": str(self.root / "data"),
                    "PNG_DIRECTORY": str(self.root / "png"), "MPLCONFIGDIR": str(self.root / "cache")}

    def run_cli(self, script, *args):
        return subprocess.run([sys.executable, str(ROOT / script), *map(str, args)],
                              cwd=self.root, env=self.env, capture_output=True,
                              text=True, timeout=30)

    def test_all_modes_render_from_an_unrelated_working_directory(self):
        for mode, line in (("freezone", BASE), ("stoppering_combined", COMBINED),
                           ("stoppering_direct", DIRECT)):
            self.env["LABCONCO_STYLE"] = mode
            source = self.root / "261116.txt"
            source.write_text(line + "\n")
            target = self.root / f"{mode}.png"
            result = self.run_cli("generate_png.py", "--once", "--input", source, "--output", target)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(target.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(result.stdout, "")

    def test_disabled_mail_and_upload_cli_exit_without_side_effects(self):
        for script in ("send_alert_email.py", "rclone_lyo.py"):
            result = self.run_cli(script)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "data").exists())
        self.assertFalse((self.root / "state").exists())

    def test_wrong_mode_cli_fails_without_producing_plot(self):
        source = self.root / "261116.txt"
        source.write_text(DIRECT)
        result = self.run_cli("generate_png.py", "--once", "--input", source)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "png/261116.png").exists())

    def test_shelf_compatibility_filename_does_not_override_mode(self):
        source = self.root / "261116.txt"
        source.write_text(BASE)
        target = self.root / "compatibility.png"
        result = self.run_cli("generate_png_shelf.py", "--once", "--input", source,
                              "--output", target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_no_alerts_preview_needs_no_mail_credentials_or_state_writes(self):
        self.env.update(ALERTS_ENABLED="true", PRESSURE_THRESHOLD="100",
                        TEMPERATURE_THRESHOLD="-50", GMAIL_USER="", GMAIL_APP_PASSWORD="",
                        ALERT_RECIPIENT="", ALERT_FLAG_FILE=str(self.root / "state/flag"),
                        ALERT_LOG_FILE=str(self.root / "state/alerts.log"))
        source = self.root / "261116.txt"
        source.write_text(BASE)
        target = self.root / "preview.png"
        result = self.run_cli("generate_png.py", "--once", "--no-alerts", "--input", source,
                              "--output", target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(target.exists())
        self.assertFalse((self.root / "state").exists())

    def test_invalid_configuration_exits_before_hardware_or_network(self):
        self.env["LABCONCO_STYLE"] = "unsupported"
        self.env["GMAIL_APP_PASSWORD"] = "do-not-print-this"
        for script in ("labconco_log.py", "generate_png.py", "send_alert_email.py", "rclone_lyo.py"):
            result = self.run_cli(script)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("LABCONCO_STYLE", result.stderr)
            self.assertNotIn("do-not-print-this", result.stderr)
        self.assertFalse((self.root / "data").exists())

    @unittest.skipUnless(os.name == "posix", "POSIX signal/pipe test")
    def test_sigterm_interrupts_long_retry_wait_without_waiting_for_timeout(self):
        code = '''
import serial, threading
import labconco_log
class NotifyingEvent(threading.Event):
    def wait(self, timeout=None):
        print("waiting", flush=True)
        return super().wait(timeout)
def disconnected(**kwargs):
    raise serial.SerialException("test disconnect")
labconco_log.threading.Event = NotifyingEvent
serial.Serial = disconnected
raise SystemExit(labconco_log.main())
'''
        env = {**self.env, "PYTHONPATH": str(ROOT), "SERIAL_RETRY_INITIAL_SECONDS": "30",
               "SERIAL_RETRY_MAX_SECONDS": "30"}
        child = subprocess.Popen([sys.executable, "-u", "-c", code], cwd=self.root,
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertTrue(select.select([child.stdout], [], [], 10)[0], "no retry handshake")
            self.assertEqual(child.stdout.readline(), b"waiting\n")
            started = time.monotonic()
            child.terminate()  # Only this private fake-hardware child; never a service/PID 1.
            _, errors = child.communicate(timeout=3)
            self.assertEqual(child.returncode, 0, errors.decode())
            self.assertLess(time.monotonic() - started, 3)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=3)

    def test_shipped_modules_use_python_310_compatible_syntax(self):
        for name in ("lyo_config.py", "generate_png.py", "generate_png_shelf.py",
                     "labconco_log.py", "usb_recovery.py", "send_alert_email.py", "rclone_lyo.py"):
            with self.subTest(name=name):
                ast.parse((ROOT / name).read_text(), filename=name, feature_version=(3, 10))

    def test_ignore_rules_protect_runtime_data_not_example_or_fixtures(self):
        paths = [".env", ".env.local", "data/261116.txt", "state/alert_active.flag",
                 "output/261116.png", "alert_log.txt", "alert_active.flag",
                 ".env.example", "tests/fixtures/261116.txt", "tests/fixtures/plot.png"]
        result = subprocess.run(["git", "check-ignore", "--no-index", "--stdin"],
                                input="\n".join(paths) + "\n", cwd=ROOT,
                                capture_output=True, text=True, check=False)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        self.assertEqual(set(result.stdout.splitlines()), set(paths[:7]))


if __name__ == "__main__":
    unittest.main()
