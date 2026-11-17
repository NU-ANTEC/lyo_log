"""Fixture-only end-to-end checks. All optional external operations stay off."""

import ast
import os
import subprocess
import sys
import tempfile
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

    def test_invalid_configuration_exits_before_hardware_or_network(self):
        self.env["LABCONCO_STYLE"] = "unsupported"
        self.env["GMAIL_APP_PASSWORD"] = "do-not-print-this"
        for script in ("labconco_log.py", "generate_png.py", "send_alert_email.py", "rclone_lyo.py"):
            result = self.run_cli(script)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("LABCONCO_STYLE", result.stderr)
            self.assertNotIn("do-not-print-this", result.stderr)
        self.assertFalse((self.root / "data").exists())

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
