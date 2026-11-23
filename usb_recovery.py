"""Optional Linux USB reset, restricted to one explicitly identified adapter.

The operator must grant access to that specific usbfs device. This module never
uses sudo or changes permissions and has no import-time operational effects.
"""

import fcntl
import logging
import os
import stat
from pathlib import Path

LOG = logging.getLogger(__name__)
USBDEVFS_RESET = 0x5514  # Linux _IO('U', 20), including Raspberry Pi ARM/ARM64.


def _identity(node):
    return ((node / "idVendor").read_text().strip().lower(),
            (node / "idProduct").read_text().strip().lower(),
            (node / "serial").read_text().strip())


def reset_adapter(settings, sysfs_root=Path("/sys/bus/usb/devices"),
                  dev_root=Path("/dev/bus/usb")):
    if not settings.usb_reset_enabled:
        return False
    expected = (settings.usb_vendor_id, settings.usb_product_id, settings.usb_serial_number)
    descriptor = None
    try:
        matches = []
        for node in Path(sysfs_root).iterdir():
            try:
                # Interfaces do not have these attributes; hubs are never targets.
                if ((node / "bDeviceClass").read_text().strip().lower() != "09"
                        and not node.name.startswith("usb") and _identity(node) == expected):
                    matches.append(node)
            except OSError:
                continue
        if len(matches) != 1:
            raise ValueError("USB reset requires exactly one non-hub identity match")
        node = matches[0]
        bus = int((node / "busnum").read_text().strip())
        device = int((node / "devnum").read_text().strip())
        if not 1 <= bus <= 999 or not 1 <= device <= 127:
            raise ValueError("Invalid USB device address")
        path = Path(dev_root) / f"{bus:03d}" / f"{device:03d}"
        descriptor = os.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        if (not stat.S_ISCHR(info.st_mode)
                or info.st_rdev != os.makedev(189, (bus - 1) * 128 + device - 1)):
            raise ValueError("Opened node is not the matched USB device")
        raw = os.read(descriptor, 18)
        if (len(raw) != 18 or raw[:2] != b"\x12\x01" or raw[4] == 9
                or int.from_bytes(raw[8:10], "little") != int(expected[0], 16)
                or int.from_bytes(raw[10:12], "little") != int(expected[1], 16)
                or _identity(node) != expected
                or int((node / "busnum").read_text()) != bus
                or int((node / "devnum").read_text()) != device):
            raise ValueError("USB identity changed before reset")
        fcntl.ioctl(descriptor, USBDEVFS_RESET, 0)
        LOG.info("Adapter-only USB reset completed; waiting for fresh serial data")
        return True
    except (OSError, ValueError) as error:
        LOG.warning("USB reset unavailable (%s); continuing gentle retries", error)
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)
