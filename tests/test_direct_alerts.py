"""Direct-tray alarm tests use real parsing/state files but never real SMTP."""

import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from generate_png import evaluate_alerts, parse_record, process_log_file
from lyo_config import load_settings
from tests.fixtures import BASE, PADDED_DIRECT_ROWS


class DirectPressureAlarmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        settings = load_settings(project_dir=self.root, operation="record",
                                 environ={"LABCONCO_STYLE": "stoppering_direct"})
        self.settings = replace(settings, alerts_enabled=True, pressure_threshold=800,
                                temperature_threshold=None, serial_idle_timeout_seconds=120)
        self.day = date(2026, 11, 17)
        self.now = datetime(2026, 11, 17, 14, 26, 51)
        self.deliveries = []

    def record(self, pressure, timestamp="142651", state="STNDBY"):
        # Missing temperatures are intentional: pressure must be independent.
        return parse_record(
            f"{timestamp} \x00:<{state} SEG= TRM=9999 SYS=999 PRB1=999 PRB2=999 PRB3=999 VAC={pressure}>",
            "stoppering_direct")

    def sender(self, alert_type, settings):
        self.deliveries.append(alert_type)
        return True

    def evaluate(self, records, **overrides):
        return evaluate_alerts(records, self.settings, sender=overrides.pop("sender", self.sender),
                               record_date=overrides.pop("record_date", self.day),
                               now=overrides.pop("now", self.now), **overrides)

    def test_high_pressure_triggers_in_standby_and_program_without_delay_or_temperature(self):
        self.settings = replace(self.settings, alert_duration_hours=48)
        for state in ("STNDBY", "PROG=1"):
            with self.subTest(state=state):
                self.settings.alert_flag_file.unlink(missing_ok=True)
                record = self.record(801, state=state)
                self.assertIsNone(record.measurements["shelf_temperature"])
                self.assertIsNone(record.measurements["collector_temperature"])
                self.assertEqual(self.evaluate([record]), "Shelf pressure")
                self.assertEqual(self.settings.alert_flag_file.read_text(), "Shelf pressure")
        self.assertEqual(self.deliveries, ["Shelf pressure", "Shelf pressure"])

    def test_threshold_is_strict_and_latest_normal_reading_does_not_replay_old_high(self):
        for pressure in (799, 800):
            with self.subTest(pressure=pressure):
                self.assertIsNone(self.evaluate([self.record(900, "142641"), self.record(pressure)]))
        self.assertEqual(self.deliveries, [])
        self.assertFalse(self.settings.alert_flag_file.exists())

    def test_one_email_per_excursion_and_rearm_at_threshold(self):
        self.evaluate([self.record(900)])
        self.evaluate([self.record(1000)])
        self.assertEqual(len(self.deliveries), 1)
        self.assertIsNone(self.evaluate([self.record(800)]))
        self.assertFalse(self.settings.alert_flag_file.exists())
        self.evaluate([self.record(901)])
        self.assertEqual(len(self.deliveries), 2)

    def test_old_base_alarm_flag_does_not_mask_new_direct_pressure_alarm(self):
        self.settings.alert_flag_file.parent.mkdir()
        self.settings.alert_flag_file.write_text("Vacuum")
        self.assertEqual(self.evaluate([self.record(900)]), "Shelf pressure")
        self.assertEqual(self.deliveries, ["Shelf pressure"])
        self.assertEqual(self.settings.alert_flag_file.read_text(), "Shelf pressure")

    def test_pressure_999_is_real_not_a_temperature_sentinel(self):
        self.assertEqual(self.evaluate([self.record(999)]), "Shelf pressure")
        self.assertEqual(len(self.deliveries), 1)

    def test_latest_invalid_pressure_does_not_look_back_send_or_clear(self):
        for value in ("HI", "nan", "0", "-1", "2\x004"):
            with self.subTest(value=value):
                self.assertEqual(self.evaluate([self.record(900, "142641"), self.record(value)]),
                                 "unavailable")
        self.assertEqual(self.deliveries, [])
        self.settings.alert_flag_file.parent.mkdir()
        self.settings.alert_flag_file.write_text("Shelf pressure")
        self.assertEqual(self.evaluate([self.record("HI")]), "unavailable")
        self.assertEqual(self.settings.alert_flag_file.read_text(), "Shelf pressure")

    def test_stale_future_and_undated_readings_are_unavailable_and_keep_alarm_state(self):
        self.settings.alert_flag_file.parent.mkdir()
        self.settings.alert_flag_file.write_text("Shelf pressure")
        for options in ({"now": self.now + timedelta(seconds=120)},
                        {"now": self.now - timedelta(seconds=1)},
                        {"record_date": self.day - timedelta(days=1)},
                        {"record_date": None}):
            with self.subTest(options=options):
                self.assertEqual(self.evaluate([self.record(900)], **options), "unavailable")
                self.assertEqual(self.settings.alert_flag_file.read_text(), "Shelf pressure")
        self.assertEqual(self.deliveries, [])

    def test_recent_record_inside_idle_window_is_eligible(self):
        self.assertEqual(self.evaluate([self.record(900)], now=self.now + timedelta(seconds=119)),
                         "Shelf pressure")
        self.assertEqual(len(self.deliveries), 1)

    def test_plot_interval_does_not_make_the_newest_reading_old(self):
        # A 60-second poll reloads the file; at that time its newest row can be 5s old.
        self.settings = replace(self.settings, plot_interval_seconds=60,
                                serial_expected_interval_seconds=10,
                                serial_idle_timeout_seconds=30)
        self.assertEqual(self.evaluate([self.record(900)], now=self.now + timedelta(seconds=5)),
                         "Shelf pressure")
        self.assertEqual(self.deliveries, ["Shelf pressure"])

    def test_unreadable_or_corrupt_state_does_not_suppress_current_high_pressure(self):
        self.settings.alert_flag_file.parent.mkdir()
        for error in (PermissionError("unreadable state"), ValueError("corrupt state")):
            with self.subTest(error=type(error).__name__):
                self.settings.alert_flag_file.write_text("Shelf pressure")
                with patch.object(Path, "read_text", side_effect=error), \
                     self.assertLogs("generate_png", level="WARNING"):
                    self.assertEqual(self.evaluate([self.record(900)]), "Shelf pressure")
                self.assertEqual(self.settings.alert_flag_file.read_text(), "Shelf pressure")
        self.assertEqual(self.deliveries, ["Shelf pressure", "Shelf pressure"])

    def test_deleted_flag_between_exists_and_read_is_recreated_after_delivery(self):
        self.settings.alert_flag_file.parent.mkdir()
        self.settings.alert_flag_file.write_text("Shelf pressure")
        def disappeared(*args, **kwargs):
            self.settings.alert_flag_file.unlink()
            raise FileNotFoundError("state disappeared")
        with patch.object(Path, "read_text", side_effect=disappeared), \
             self.assertLogs("generate_png", level="WARNING"):
            self.assertEqual(self.evaluate([self.record(900)]), "Shelf pressure")
        self.assertEqual(self.deliveries, ["Shelf pressure"])
        self.assertEqual(self.settings.alert_flag_file.read_text(), "Shelf pressure")

    def test_direct_flag_does_not_suppress_base_alarm_after_switching_back(self):
        self.settings.alert_flag_file.parent.mkdir()
        for style in ("freezone", "stoppering_combined"):
            with self.subTest(style=style):
                self.settings.alert_flag_file.write_text("Shelf pressure")
                settings = replace(self.settings, style=style, temperature_threshold=-50)
                record = parse_record(BASE.replace("V=90", "V=900"), style)
                self.assertEqual(evaluate_alerts([record], settings, sender=self.sender), "Vacuum")
                self.assertEqual(settings.alert_flag_file.read_text(), "Vacuum")
        self.assertEqual(self.deliveries, ["Vacuum", "Vacuum"])

    def test_normal_direct_reading_clears_retained_base_flag(self):
        self.settings.alert_flag_file.parent.mkdir()
        self.settings.alert_flag_file.write_text("Vacuum")
        self.assertIsNone(self.evaluate([self.record(24)]))
        self.assertFalse(self.settings.alert_flag_file.exists())
        self.assertEqual(self.deliveries, [])

    def test_failed_delivery_is_not_marked_and_can_retry(self):
        with self.assertLogs("generate_png", level="WARNING"):
            self.assertEqual(self.evaluate([self.record(900)], sender=lambda *args: False),
                             "Shelf pressure")
        self.assertFalse(self.settings.alert_flag_file.exists())
        self.evaluate([self.record(900)])
        self.assertEqual(self.settings.alert_flag_file.read_text(), "Shelf pressure")

    def test_disabled_direct_alarm_has_no_side_effects(self):
        self.settings = replace(self.settings, alerts_enabled=False)
        self.assertIsNone(self.evaluate([self.record(900)]))
        self.assertEqual(self.deliveries, [])
        self.assertFalse(self.settings.alert_flag_file.exists())

    def test_file_processing_supplies_source_date_to_real_alarm_evaluation(self):
        path = self.root / "261117.txt"
        path.write_bytes(PADDED_DIRECT_ROWS[-1].replace(b"VAC=  24", b"VAC=  900"))
        with patch("generate_png.render_plot", return_value=self.root / "preview.png"), \
             patch("generate_png.datetime", wraps=datetime) as wallclock, \
             patch("send_alert_email.send_alert", side_effect=self.sender):
            wallclock.now.return_value = self.now
            process_log_file(path, self.settings)
        self.assertEqual(self.deliveries, ["Shelf pressure"])
        self.assertEqual(self.settings.alert_flag_file.read_text(), "Shelf pressure")


if __name__ == "__main__":
    unittest.main()
