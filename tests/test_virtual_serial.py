"""Exercise real pyserial against a private pseudo-terminal, never USB hardware."""

import os
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import serial

from labconco_log import record_stream
from lyo_config import load_settings


@unittest.skipUnless(hasattr(os, "openpty"), "requires POSIX pseudo-terminals")
class VirtualSerialTests(unittest.TestCase):
    def test_real_pyserial_parameters_and_record_durability(self):
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        with tempfile.TemporaryDirectory() as directory:
            settings = load_settings(project_dir=directory, operation="record",
                                     environ={"LABCONCO_STYLE": "freezone"})
            settings = replace(settings, serial_port=os.ttyname(slave),
                               serial_timeout_seconds=0.05)
            target = Path(directory) / "data/261116.txt"
            deadline = time.monotonic() + 3
            class StopAfterRecord(threading.Event):
                def is_set(self):
                    return (super().is_set() or time.monotonic() >= deadline
                            or (target.exists() and target.read_text().endswith("\n")))
            def open_virtual_port(**kwargs):
                connection = serial.Serial(**kwargs)
                os.write(master, b"virtual instrument record\r\n")
                return connection
            count = record_stream(settings, serial_factory=open_virtual_port,
                                  stop=StopAfterRecord(), now=lambda: datetime(2026, 11, 16, 12))
            self.assertEqual(count, 1)
            self.assertEqual(target.read_text(), "120000 virtual instrument record\n")
