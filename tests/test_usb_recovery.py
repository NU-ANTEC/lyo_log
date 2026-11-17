import os
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from lyo_config import load_settings
from usb_recovery import reset_adapter


class UsbResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sysfs = self.root / "sysfs"
        self.sysfs.mkdir()
        self.settings = load_settings(project_dir=self.root, operation="record", environ={
            "LABCONCO_STYLE": "freezone", "USB_RESET_ENABLED": "true",
            "USB_VENDOR_ID": "1234", "USB_PRODUCT_ID": "abcd", "USB_SERIAL_NUMBER": "example"})
        self.node = self.make_device("1-2", 4)
        descriptor = bytearray(18)
        descriptor[0:2] = bytes([18, 1])
        descriptor[8:12] = bytes.fromhex("3412cdab")
        self.descriptor = bytes(descriptor)

    def make_device(self, name, devnum, device_class="00", serial="example"):
        node = self.sysfs / name
        node.mkdir()
        for key, value in {"idVendor": "1234", "idProduct": "abcd", "serial": serial,
                           "bDeviceClass": device_class, "busnum": "1", "devnum": str(devnum)}.items():
            (node / key).write_text(value)
        return node

    def reset(self, settings=None):
        return reset_adapter(settings or self.settings, sysfs_root=self.sysfs,
                             dev_root=self.root / "usb")

    def test_disabled_no_open(self):
        with patch("usb_recovery.os.open", side_effect=AssertionError("disabled reset opened USB")):
            self.assertFalse(self.reset(replace(self.settings, usb_reset_enabled=False)))

    def test_unique_match_uses_current_device_number(self):
        (self.node / "devnum").write_text("7")
        info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=os.makedev(189, 6))
        with patch("usb_recovery.os.open", return_value=42) as opened, \
             patch("usb_recovery.os.fstat", return_value=info), \
             patch("usb_recovery.os.read", return_value=self.descriptor), \
             patch("usb_recovery.os.close") as closed, \
             patch("usb_recovery.fcntl.ioctl") as ioctl:
            self.assertTrue(self.reset())
        self.assertEqual(opened.call_args.args[0], self.root / "usb/001/007")
        ioctl.assert_called_once_with(42, 0x5514, 0)
        closed.assert_called_once_with(42)

    def test_missing_ambiguous_hub_or_wrong_serial_is_rejected(self):
        with patch("usb_recovery.os.open", side_effect=AssertionError("unsafe open")):
            self.make_device("1-3", 5)
            self.assertFalse(self.reset())
            (self.sysfs / "1-3/serial").write_text("another")
            (self.node / "bDeviceClass").write_text("09")
            self.assertFalse(self.reset())
            (self.node / "bDeviceClass").write_text("00")
            self.assertFalse(self.reset(replace(self.settings, usb_serial_number="absent")))

    def test_permission_denial_is_not_escalated(self):
        with patch("usb_recovery.os.open", side_effect=PermissionError("denied")):
            self.assertFalse(self.reset())

    def test_changed_opened_device_is_never_reset(self):
        info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=os.makedev(189, 3))
        for descriptor in (b"", self.descriptor[:8] + b"\x00\x00" + self.descriptor[10:]):
            with self.subTest(descriptor=descriptor), \
                 patch("usb_recovery.os.open", return_value=42), \
                 patch("usb_recovery.os.fstat", return_value=info), \
                 patch("usb_recovery.os.read", return_value=descriptor), \
                 patch("usb_recovery.os.close"), patch("usb_recovery.fcntl.ioctl") as ioctl:
                self.assertFalse(self.reset())
                ioctl.assert_not_called()

    def test_ioctl_error_closes_handle(self):
        info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=os.makedev(189, 3))
        with patch("usb_recovery.os.open", return_value=42), \
             patch("usb_recovery.os.fstat", return_value=info), \
             patch("usb_recovery.os.read", return_value=self.descriptor), \
             patch("usb_recovery.os.close") as closed, \
             patch("usb_recovery.fcntl.ioctl", side_effect=OSError("reset failed")):
            self.assertFalse(self.reset())
        closed.assert_called_once_with(42)


if __name__ == "__main__":
    unittest.main()
