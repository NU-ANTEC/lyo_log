import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import serial

from lyo_config import load_settings

# A legacy import must fail before it can touch real data or a serial port.
with patch("os.listdir", side_effect=AssertionError("import attempted cleanup")), \
     patch("serial.Serial", side_effect=AssertionError("import opened serial")):
    from labconco_log import purge_old_logs, record_stream


class Clock:
    def __init__(self, start=datetime(2026, 11, 16, 12)):
        self.value, self.start, self.waits = 0.0, start, []

    def __call__(self):
        return self.value

    def now(self):
        return self.start + timedelta(seconds=self.value)

    def wait(self, seconds):
        self.waits.append(seconds)
        self.value += seconds


class Port:
    def __init__(self, events, clock, stop):
        self.events, self.clock, self.stop = list(events), clock, stop
        self.closed = False

    def readline(self):
        self.clock.value += 1
        if not self.events:
            self.stop.set()
            return b""
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event

    def close(self):
        self.closed = True


class LoggerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = load_settings(project_dir=self.root, operation="record",
                                      environ={"LABCONCO_STYLE": "freezone"})
        self.settings = replace(self.settings, serial_expected_interval_seconds=1,
                                serial_idle_timeout_seconds=2)
        self.clock, self.stop = Clock(), threading.Event()

    def run_stream(self, factory, reset=lambda settings: False, settings=None):
        return record_stream(settings or self.settings, serial_factory=factory,
                             clock=self.clock, now=self.clock.now, wait=self.clock.wait,
                             stop=self.stop, reset=reset)

    def port(self, events):
        return Port(events, self.clock, self.stop)

    def test_single_timeout_is_not_a_fault_and_records_are_durable_quiet(self):
        port = self.port([b"", b"payload\n"])
        with patch("labconco_log.os.fsync") as sync, patch("builtins.print") as printed:
            count = self.run_stream(lambda **kw: port)
        self.assertEqual(count, 1)
        self.assertEqual((self.settings.log_directory / "261116.txt").read_text(),
                         "120002 payload\n")
        sync.assert_called_once()
        printed.assert_not_called()
        self.assertTrue(port.closed)
        self.assertEqual(self.clock.waits, [])

    def test_silence_closes_before_reopening_and_reapplies_settings(self):
        first, second = self.port([b"", b""]), self.port([b"fresh\n"])
        opened = []
        def factory(**kwargs):
            if opened:
                self.assertTrue(first.closed)
            opened.append(kwargs)
            return first if len(opened) == 1 else second
        self.assertEqual(self.run_stream(factory), 1)
        self.assertEqual(len(opened), 2)
        self.assertEqual(opened[1]["baudrate"], 2400)
        self.assertEqual(opened[1]["timeout"], 1)
        self.assertTrue(second.closed)

    def test_open_failures_use_capped_backoff(self):
        attempts = []
        port = self.port([b"ok\n"])
        def factory(**kw):
            attempts.append(kw)
            if len(attempts) < 6:
                raise serial.SerialException("unavailable")
            return port
        self.assertEqual(self.run_stream(factory, settings=replace(
            self.settings, serial_retry_max_seconds=4)), 1)
        self.assertEqual(self.clock.waits, [1, 2, 4, 4, 4])

    def test_read_error_reopens_and_only_data_confirms_recovery(self):
        ports = [self.port([serial.SerialException("read failed")]),
                 self.port([b"", b""]), self.port([b"ok\n"])]
        with self.assertLogs("labconco_log", level="INFO") as captured:
            self.assertEqual(self.run_stream(lambda **kw: ports.pop(0)), 1)
        self.assertEqual(sum("recovered" in line.lower() for line in captured.output), 1)

    def test_usb_reset_after_failed_reopen_and_cooldown(self):
        ports = [self.port([b"", b""]) for _ in range(4)] + [self.port([b"ok\n"])]
        resets = []
        def reset(settings):
            resets.append(self.clock.value)
            return False
        self.assertEqual(self.run_stream(lambda **kw: ports.pop(0), reset=reset,
                         settings=replace(self.settings, usb_reset_enabled=True,
                                          serial_reopen_attempts=1,
                                          usb_reset_min_interval_seconds=100)), 1)
        self.assertEqual(len(resets), 1)

    def test_initial_fault_is_not_counted_as_a_failed_reopen(self):
        ports = [self.port([b"", b""]) for _ in range(4)] + [self.port([b"ok\n"])]
        opened, reset_after = [], []
        def factory(**kwargs):
            opened.append(kwargs)
            return ports.pop(0)
        self.assertEqual(self.run_stream(factory,
                         settings=replace(self.settings, usb_reset_enabled=True,
                                          serial_reopen_attempts=3),
                         reset=lambda settings: reset_after.append(len(opened))), 1)
        self.assertEqual(reset_after, [4])  # Original stalled connection + 3 failed reopens.

    def test_usb_cooldown_survives_a_brief_successful_recovery(self):
        ports = [self.port([b"", b""]), self.port([b"", b""]),
                 self.port([b"brief recovery\n", b"", b""]),
                 self.port([b"", b""]), self.port([b"recovered again\n"])]
        resets = []
        self.assertEqual(self.run_stream(lambda **kw: ports.pop(0),
                         settings=replace(self.settings, usb_reset_enabled=True,
                                          serial_reopen_attempts=1,
                                          usb_reset_min_interval_seconds=100),
                         reset=lambda settings: resets.append(self.clock.value)), 2)
        self.assertEqual(len(resets), 1)

    def test_reset_disabled_and_disabled_recovery(self):
        first, second = self.port([b"", b""]), self.port([b"ok\n"])
        ports = [first, second]
        self.assertEqual(self.run_stream(lambda **kw: ports.pop(0),
                         reset=lambda settings: self.fail("reset was disabled")), 1)
        bad = self.port([serial.SerialException("disconnected")])
        self.stop.clear()
        with self.assertRaises(serial.SerialException):
            self.run_stream(lambda **kw: bad, settings=replace(
                self.settings, serial_recovery_enabled=False))
        self.assertTrue(bad.closed)

    def test_decode_error_does_not_reset_usb(self):
        port = self.port([b"\xff\n", b"valid\n"])
        self.assertEqual(self.run_stream(lambda **kw: port,
                         reset=lambda settings: self.fail("decode error reset USB")), 1)

    def test_storage_failure_is_not_a_serial_failure(self):
        port = self.port([b"record\n"])
        with patch("labconco_log.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.run_stream(lambda **kw: port,
                                reset=lambda settings: self.fail("storage failure reset USB"))
        self.assertTrue(port.closed)

    def test_midnight_rotation_without_process_restart(self):
        self.clock = Clock(datetime(2026, 11, 16, 23, 59, 58))
        port = self.port([b"old\n", b"new\n"])
        self.assertEqual(self.run_stream(lambda **kw: port), 2)
        self.assertEqual((self.settings.log_directory / "261116.txt").read_text(), "235959 old\n")
        self.assertEqual((self.settings.log_directory / "261117.txt").read_text(), "000000 new\n")

    def test_reconnect_outage_spanning_midnight_uses_new_daily_file(self):
        self.clock = Clock(datetime(2026, 11, 16, 23, 59, 56))
        ports = [self.port([b"before\n", b"", b""]), self.port([b"after\n"])]
        self.assertEqual(self.run_stream(lambda **kw: ports.pop(0)), 2)
        self.assertEqual((self.settings.log_directory / "261116.txt").read_text(), "235957 before\n")
        self.assertEqual((self.settings.log_directory / "261117.txt").read_text(), "000001 after\n")

    def test_opt_in_retention_is_narrow_and_skips_symlinks(self):
        root = self.settings.log_directory
        root.mkdir()
        for name in ("200101.txt", "261116.txt", "notes.txt", "200101.png", "999999.txt"):
            (root / name).write_text("keep unless expired dated data")
        outside = self.root / "outside.txt"
        outside.write_text("keep")
        (root / "190101.txt").symlink_to(outside)
        self.assertEqual(purge_old_logs(root, 0, datetime(2026, 11, 16).date()), 0)
        self.assertEqual(purge_old_logs(root, 60, datetime(2026, 11, 16).date()), 2)
        self.assertFalse((root / "200101.txt").exists())
        self.assertTrue((root / "190101.txt").is_symlink())
        self.assertEqual(outside.read_text(), "keep")
        self.assertFalse((root / "200101.png").exists())

    def test_retention_preserves_cutoff_day_future_invalid_and_unrelated_files(self):
        root = self.settings.log_directory
        root.mkdir()
        names = ("260917.txt", "260917.png", "260918.txt", "260918.png",
                 "261117.txt", "261117.png", "271101.txt", "271101.png",
                 "260230.txt", "260230.png", "200101.txt.bak", "notes.png", "200101.PNG")
        for name in names:
            (root / name).write_text("fixture")
        nested = root / "archive"
        nested.mkdir()
        (nested / "200101.png").write_text("nested image")
        (root / "200101.txt").mkdir()
        # 2026-11-17 minus 60 days is 2026-09-18; that exact date stays.
        self.assertEqual(purge_old_logs(root, 60, datetime(2026, 11, 17).date()), 2)
        for name in names[2:]:
            self.assertTrue((root / name).is_file(), name)
        self.assertFalse((root / "260917.txt").exists())
        self.assertFalse((root / "260917.png").exists())
        self.assertTrue((root / "200101.txt").is_dir())
        self.assertEqual((nested / "200101.png").read_text(), "nested image")

    def test_retention_skips_dated_png_symlinks(self):
        root = self.settings.log_directory
        root.mkdir()
        target = self.root / "precious.png"
        target.write_bytes(b"keep this image")
        link = root / "200101.png"
        link.symlink_to(target)
        self.assertEqual(purge_old_logs(root, 60, datetime(2026, 11, 17).date()), 0)
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_bytes(), b"keep this image")

    def test_startup_retention_cleans_separate_png_directory_but_not_its_text_files(self):
        plots = self.root / "plots"
        plots.mkdir()
        self.settings.log_directory.mkdir()
        old_log = self.settings.log_directory / "200101.txt"
        old_log.write_text("expired")
        old_plot = plots / "200101.png"
        old_plot.write_text("expired")
        text_in_plots = plots / "200101.txt"
        text_in_plots.write_text("not a raw log directory")
        self.stop.set()
        settings = replace(self.settings, png_directory=plots, data_retention_days=60)
        self.assertEqual(self.run_stream(lambda **kw: self.fail("stopped logger opened serial"),
                                         settings=settings), 0)
        self.assertFalse(old_log.exists())
        self.assertFalse(old_plot.exists())
        self.assertEqual(text_in_plots.read_text(), "not a raw log directory")

    def test_zero_retention_keeps_old_logs_and_plots_in_both_directories(self):
        plots = self.root / "plots"
        plots.mkdir()
        self.settings.log_directory.mkdir()
        paths = (self.settings.log_directory / "200101.txt",
                 self.settings.log_directory / "200101.png", plots / "200101.png")
        for path in paths:
            path.write_text("preserve")
        self.stop.set()
        settings = replace(self.settings, png_directory=plots, data_retention_days=0)
        self.assertEqual(self.run_stream(lambda **kw: self.fail("stopped logger opened serial"),
                                         settings=settings), 0)
        self.assertTrue(all(path.read_text() == "preserve" for path in paths))

    def test_startup_retention_tolerates_png_directory_not_created_yet(self):
        self.stop.set()
        settings = replace(self.settings, png_directory=self.root / "not-created",
                           data_retention_days=60)
        self.assertEqual(self.run_stream(lambda **kw: self.fail("stopped logger opened serial"),
                                         settings=settings), 0)
        self.assertFalse(settings.png_directory.exists())

    def test_undeletable_expired_png_warns_but_serial_recording_continues(self):
        plots = self.root / "plots"
        plots.mkdir()
        denied = plots / "200101.png"
        denied.write_bytes(b"old protected image")
        removable = plots / "200102.png"
        removable.write_bytes(b"old removable image")
        original = Path.unlink
        def unlink(path, *args, **kwargs):
            if path == denied:
                raise PermissionError("image deletion denied")
            return original(path, *args, **kwargs)
        port = self.port([b"fresh\n"])
        with patch.object(Path, "unlink", new=unlink), self.assertLogs("labconco_log", level="WARNING"):
            self.assertEqual(self.run_stream(lambda **kw: port, settings=replace(
                self.settings, png_directory=plots, data_retention_days=60)), 1)
        self.assertEqual(denied.read_bytes(), b"old protected image")
        self.assertFalse(removable.exists())
        self.assertEqual((self.settings.log_directory / "261116.txt").read_text(), "120001 fresh\n")

    def test_unreadable_png_directory_warns_but_serial_recording_continues(self):
        plots = self.root / "plots"
        plots.mkdir()
        original = Path.iterdir
        def iterdir(path):
            if path == plots:
                raise PermissionError("plot directory inaccessible")
            return original(path)
        port = self.port([b"fresh\n"])
        with patch.object(Path, "iterdir", new=iterdir), self.assertLogs("labconco_log", level="WARNING"):
            self.assertEqual(self.run_stream(lambda **kw: port, settings=replace(
                self.settings, png_directory=plots, data_retention_days=60)), 1)
        self.assertEqual((self.settings.log_directory / "261116.txt").read_text(), "120001 fresh\n")

    def test_failed_raw_log_cleanup_warns_but_new_recording_still_works(self):
        self.settings.log_directory.mkdir()
        denied = self.settings.log_directory / "200101.txt"
        denied.write_text("old protected raw log")
        original = Path.unlink
        def unlink(path, *args, **kwargs):
            if path == denied:
                raise PermissionError("old raw log deletion denied")
            return original(path, *args, **kwargs)
        port = self.port([b"fresh\n"])
        with patch.object(Path, "unlink", new=unlink), self.assertLogs("labconco_log", level="WARNING"):
            self.assertEqual(self.run_stream(lambda **kw: port, settings=replace(
                self.settings, data_retention_days=60)), 1)
        self.assertEqual(denied.read_text(), "old protected raw log")
        self.assertEqual((self.settings.log_directory / "261116.txt").read_text(), "120001 fresh\n")


if __name__ == "__main__":
    unittest.main()
