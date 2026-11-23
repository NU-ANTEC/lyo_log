"""Snapshot tests use real files, replacing only external rclone execution."""

import os
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from lyo_config import load_settings
from rclone_lyo import main, upload


class UploadSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        settings = load_settings(project_dir=self.root, environ={"LABCONCO_STYLE": "freezone"})
        self.source = self.root / "data"
        self.base = self.source / "24port"
        self.base.mkdir(parents=True)
        self.log = self.base / "261117.txt"
        self.log.write_bytes(b"185400 B<T=-56V=24>\n")
        self.png = self.base / "261117.png"
        self.png.write_bytes(b"first-complete-png")
        self.old = self.base / "200101.txt"
        self.old.write_bytes(b"preserve this old log\n")
        self.settings = replace(settings, upload_enabled=True, rclone_source=self.source,
                                rclone_destination="example:folder with spaces", data_retention_days=1)

    def test_source_updates_during_upload_cannot_change_snapshot(self):
        seen = []
        def runner(command, check):
            snapshot = Path(command[2])
            self.assertTrue(check)
            self.assertEqual(command[:2], ["rclone", "copy"])
            self.assertEqual(command[3], "example:folder with spaces")
            self.assertNotEqual(snapshot, self.source)
            self.assertNotIn(self.source, snapshot.parents)
            self.assertNotEqual((snapshot / "24port/261117.txt").stat().st_ino, self.log.stat().st_ino)
            self.log.write_bytes(b"next live reading\n")
            replacement = self.base / "replacement"
            replacement.write_bytes(b"next complete png")
            replacement.replace(self.png)
            self.assertEqual((snapshot / "24port/261117.txt").read_bytes(), b"185400 B<T=-56V=24>\n")
            self.assertEqual((snapshot / "24port/261117.png").read_bytes(), b"first-complete-png")
            seen.append(snapshot)
            return subprocess.CompletedProcess(command, 0)
        self.assertEqual(upload(self.settings, runner=runner), 0)
        self.assertEqual(len(seen), 1)
        self.assertFalse(seen[0].exists())

    def test_uploader_never_deletes_old_logs_or_plots_even_when_retention_is_positive(self):
        old_plot = self.base / "200101.png"
        old_plot.write_bytes(b"old image")
        copied = []
        def runner(command, check):
            snapshot = Path(command[2])
            copied.append(((snapshot / "24port/200101.txt").read_bytes(),
                           (snapshot / "24port/200101.png").read_bytes()))
            return subprocess.CompletedProcess(command, 0)
        self.assertEqual(upload(self.settings, runner=runner), 0)
        self.assertEqual(copied, [(b"preserve this old log\n", b"old image")])
        self.assertEqual(self.old.read_bytes(), b"preserve this old log\n")
        self.assertEqual(old_plot.read_bytes(), b"old image")

    def test_snapshot_preserves_modification_times_for_unchanged_history(self):
        os.utime(self.old, ns=(1500000000000000000, 1500000000123456789))
        copied = []
        def runner(command, check):
            copied.append((Path(command[2]) / "24port/200101.txt").stat().st_mtime_ns)
            return subprocess.CompletedProcess(command, 0)
        self.assertEqual(upload(self.settings, runner=runner), 0)
        self.assertEqual(copied, [1500000000123456789])

    def test_snapshot_includes_sibling_instrument_directories(self):
        other = self.source / "6port"
        other.mkdir()
        (other / "261117.txt").write_bytes(b"other instrument\n")
        copied = []
        def runner(command, check):
            copied.append((Path(command[2]) / "6port/261117.txt").read_bytes())
            return subprocess.CompletedProcess(command, 0)
        self.assertEqual(upload(self.settings, runner=runner), 0)
        self.assertEqual(copied, [b"other instrument\n"])

    def test_snapshot_excludes_temporary_plots_and_symlinks(self):
        (self.base / ".plot-in-progress.png").write_bytes(b"unfinished")
        private = self.root / "private"
        private.mkdir()
        (private / "secret").write_bytes(b"not an upload")
        (self.source / "linked-directory").symlink_to(private, target_is_directory=True)
        (self.base / "linked-file").symlink_to(private / "secret")
        copied = []
        def runner(command, check):
            snapshot = Path(command[2])
            copied.append(sorted(str(path.relative_to(snapshot)) for path in snapshot.rglob("*")
                                 if path.is_file()))
            return subprocess.CompletedProcess(command, 0)
        self.assertEqual(upload(self.settings, runner=runner), 0)
        self.assertEqual(copied, [["24port/200101.txt", "24port/261117.png", "24port/261117.txt"]])

    def test_missing_source_fails_without_running_rclone(self):
        calls = []
        def runner(command, check):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0)
        with self.assertLogs("rclone_lyo", level="ERROR"):
            result = upload(replace(self.settings, rclone_source=self.root / "missing"),
                            runner=runner)
        self.assertEqual(result, 1)
        self.assertEqual(calls, [])

    def test_snapshot_copy_failure_prevents_upload_and_cleans_staging(self):
        calls = []
        before = set(self.root.iterdir())
        def runner(command, check):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0)
        with patch("shutil.copytree", side_effect=OSError("disk full")), \
             self.assertLogs("rclone_lyo", level="ERROR") as captured:
            result = upload(self.settings, runner=runner)
        self.assertEqual(result, 1)
        self.assertEqual(calls, [])
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertEqual(self.log.read_bytes(), b"185400 B<T=-56V=24>\n")
        self.assertIn("disk full", "\n".join(captured.output))

    def test_rclone_failure_cleans_snapshot_and_reports_nonzero(self):
        seen = []
        def runner(command, check):
            seen.append(Path(command[2]))
            raise subprocess.CalledProcessError(1, command)
        with self.assertLogs("rclone_lyo", level="ERROR"):
            self.assertEqual(upload(self.settings, runner=runner), 1)
        self.assertEqual(len(seen), 1)
        self.assertNotEqual(seen[0], self.source)
        self.assertFalse(seen[0].exists())
        self.assertEqual(self.log.read_bytes(), b"185400 B<T=-56V=24>\n")

    def test_snapshot_copy_is_bounded_to_file_size_at_open(self):
        original = os.fstat
        def fstat(fd):
            metadata = original(fd)
            if metadata.st_ino == self.log.stat().st_ino:
                with self.log.open("ab") as target:
                    target.write(b"a later reading\n")
            return metadata
        copied = []
        def runner(command, check):
            copied.append((Path(command[2]) / "24port/261117.txt").read_bytes())
            return subprocess.CompletedProcess(command, 0)
        with patch("os.fstat", side_effect=fstat):
            self.assertEqual(upload(self.settings, runner=runner), 0)
        self.assertEqual(copied, [b"185400 B<T=-56V=24>\n"])
        self.assertEqual(self.log.read_bytes(), b"185400 B<T=-56V=24>\na later reading\n")

    def test_atomic_png_replacement_during_snapshot_keeps_the_opened_complete_image(self):
        original = os.fstat
        image_inode = self.png.stat().st_ino
        def fstat(fd):
            metadata = original(fd)
            if metadata.st_ino == image_inode:
                replacement = self.base / ".plot-new.png"
                replacement.write_bytes(b"next complete png")
                replacement.replace(self.png)
            return metadata
        copied = []
        def runner(command, check):
            copied.append((Path(command[2]) / "24port/261117.png").read_bytes())
            return subprocess.CompletedProcess(command, 0)
        with patch("os.fstat", side_effect=fstat):
            self.assertEqual(upload(self.settings, runner=runner), 0)
        self.assertEqual(copied, [b"first-complete-png"])
        self.assertEqual(self.png.read_bytes(), b"next complete png")

    def test_source_shrinking_during_snapshot_aborts_without_upload_or_leftovers(self):
        original = os.fstat
        def fstat(fd):
            metadata = original(fd)
            if metadata.st_ino == self.log.stat().st_ino:
                self.log.write_bytes(b"")
            return metadata
        calls = []
        before = set(self.root.iterdir())
        with patch("os.fstat", side_effect=fstat), self.assertLogs("rclone_lyo", level="ERROR"):
            self.assertEqual(upload(self.settings, runner=lambda *a, **kw: calls.append(a)), 1)
        self.assertEqual(calls, [])
        self.assertEqual(set(self.root.iterdir()), before)

    def test_cli_uploads_same_snapshot_to_primary_and_repeated_additional_destinations(self):
        seen = []
        def runner(command, check):
            snapshot = Path(command[2])
            seen.append((snapshot, command[3]))
            self.log.write_bytes(b"next live reading\n")
            self.assertEqual((snapshot / "24port/261117.txt").read_bytes(), b"185400 B<T=-56V=24>\n")
            return subprocess.CompletedProcess(command, 0)
        with patch("rclone_lyo.load_settings", return_value=self.settings), \
             patch("rclone_lyo.configure_logging"), \
             patch("rclone_lyo.subprocess.run", side_effect=runner), \
             patch("sys.argv", ["rclone_lyo.py", "--additional-destination", "second:other folder",
                                "--additional-destination", "third:archive"]):
            self.assertEqual(main(), 0)
        self.assertEqual([destination for _, destination in seen],
                         ["example:folder with spaces", "second:other folder", "third:archive"])
        self.assertEqual(len({snapshot for snapshot, _ in seen}), 1)
        self.assertFalse(seen[0][0].exists())

    def test_failed_primary_still_attempts_additional_destination_and_fails_service(self):
        seen = []
        def runner(command, check):
            seen.append((Path(command[2]), command[3]))
            if command[3] == "example:folder with spaces":
                raise subprocess.CalledProcessError(1, command)
            self.assertEqual((Path(command[2]) / "24port/261117.txt").read_bytes(),
                             b"185400 B<T=-56V=24>\n")
            return subprocess.CompletedProcess(command, 0)
        with patch("rclone_lyo.load_settings", return_value=self.settings), \
             patch("rclone_lyo.configure_logging"), \
             patch("rclone_lyo.subprocess.run", side_effect=runner), \
             patch("sys.argv", ["rclone_lyo.py", "--additional-destination", "second:archive"]), \
             self.assertLogs("rclone_lyo", level="ERROR"):
            self.assertEqual(main(), 1)
        self.assertEqual([destination for _, destination in seen],
                         ["example:folder with spaces", "second:archive"])
        self.assertEqual(seen[0][0], seen[1][0])
        self.assertFalse(seen[0][0].exists())
        self.assertEqual(self.log.read_bytes(), b"185400 B<T=-56V=24>\n")

    def test_disabled_uploads_with_extra_destinations_do_not_even_prepare_snapshot(self):
        before = set(self.root.iterdir())
        with patch("rclone_lyo.load_settings", return_value=replace(self.settings, upload_enabled=False)), \
             patch("rclone_lyo.configure_logging"), \
             patch("rclone_lyo.subprocess.run", side_effect=AssertionError("disabled upload")), \
             patch("sys.argv", ["rclone_lyo.py", "--additional-destination", "second:archive"]):
            self.assertEqual(main(), 0)
        self.assertEqual(set(self.root.iterdir()), before)

    def test_nonzero_runner_return_code_is_not_mistaken_for_success(self):
        def runner(command, check):
            return subprocess.CompletedProcess(command, 7)
        with self.assertLogs("rclone_lyo", level="ERROR"):
            self.assertEqual(upload(self.settings, runner=runner), 1)


if __name__ == "__main__":
    unittest.main()
