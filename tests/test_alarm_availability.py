"""Operator-visible alarm health, without email, hardware, or real waiting."""

import logging
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import generate_png as plot
from lyo_config import load_settings
from tests.fixtures import PADDED_DIRECT_ROWS


class AlarmAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        settings = load_settings(project_dir=self.root, operation="record",
                                 environ={"LABCONCO_STYLE": "stoppering_direct"})
        self.settings = replace(settings, alerts_enabled=True, pressure_threshold=800,
                                serial_idle_timeout_seconds=120, plot_interval_seconds=60)
        self.now = datetime(2026, 11, 17, 14, 26, 51)

    def test_warning_is_deduplicated_and_recovery_is_visible(self):
        reporter = plot.AlarmAvailability()
        with self.assertLogs("generate_png", level="INFO") as captured:
            for status in ("unavailable", "unavailable", "Shelf pressure", None, "unavailable"):
                reporter.report(status)
        self.assertEqual(sum(record.levelno == logging.WARNING for record in captured.records), 2)
        self.assertEqual(sum(record.levelno == logging.INFO for record in captured.records), 1)

    def test_stale_file_processing_warns_and_keeps_alarm_state(self):
        path = self.root / "261116.txt"
        path.write_bytes(PADDED_DIRECT_ROWS[-1].replace(b"VAC=  24", b"VAC=  900"))
        self.settings.alert_flag_file.parent.mkdir()
        self.settings.alert_flag_file.write_text("Shelf pressure")
        with patch("generate_png.render_plot", return_value=self.root / "preview.png"), \
             patch("generate_png.datetime", wraps=datetime) as wallclock, \
             patch("send_alert_email.send_alert", side_effect=AssertionError("stale input sent mail")), \
             self.assertLogs("generate_png", level="WARNING") as captured:
            wallclock.now.return_value = self.now
            plot.process_log_file(path, self.settings)
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(self.settings.alert_flag_file.read_text(), "Shelf pressure")

    def test_repeated_unavailable_records_share_one_monitor_warning(self):
        path = self.root / "261116.txt"
        path.write_bytes(PADDED_DIRECT_ROWS[-1])
        reporter = plot.AlarmAvailability()
        with patch("generate_png.render_plot", return_value=self.root / "preview.png"), \
             patch("generate_png.datetime", wraps=datetime) as wallclock, \
             self.assertLogs("generate_png", level="WARNING") as captured:
            wallclock.now.return_value = self.now
            for _ in range(3):
                plot.process_log_file(path, self.settings, availability=reporter)
        self.assertEqual(len(captured.records), 1)

    def test_disabled_alarms_do_not_warn_about_stale_alarm_inputs(self):
        path = self.root / "261116.txt"
        path.write_bytes(PADDED_DIRECT_ROWS[-1])
        with patch("generate_png.render_plot", return_value=self.root / "preview.png"), \
             self.assertNoLogs("generate_png", level="WARNING"):
            plot.process_log_file(path, replace(self.settings, alerts_enabled=False))

    def test_static_file_becomes_unavailable_without_rerender_or_replayed_alarm(self):
        path = self.settings.log_directory / "261117.txt"
        path.parent.mkdir()
        path.write_bytes(PADDED_DIRECT_ROWS[-1])
        os.utime(path, (self.now.timestamp(), self.now.timestamp()))
        clock = {"now": self.now, "polls": 0}
        def sleep(seconds):
            clock["now"] += timedelta(seconds=seconds)
            clock["polls"] += 1
            if clock["polls"] == 4:
                raise KeyboardInterrupt
        with patch("generate_png.load_settings", return_value=self.settings), \
             patch("generate_png.configure_logging"), \
             patch("generate_png.render_plot", return_value=self.root / "preview.png") as render, \
             patch("generate_png.datetime", wraps=datetime) as wallclock, \
             patch("generate_png.time.time", side_effect=lambda: clock["now"].timestamp()), \
             patch("generate_png.time.sleep", side_effect=sleep), \
             patch("send_alert_email.send_alert", side_effect=AssertionError("static input sent mail")), \
             self.assertLogs("generate_png", level="WARNING") as captured:
            wallclock.now.side_effect = lambda: clock["now"]
            self.assertEqual(plot.main([]), 0)
        self.assertEqual(render.call_count, 1)
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(clock["polls"], 4)


if __name__ == "__main__":
    unittest.main()
