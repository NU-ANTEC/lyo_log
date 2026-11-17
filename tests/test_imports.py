import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ImportSafetyTests(unittest.TestCase):
    def test_plot_import_does_not_start_monitor(self):
        code = """
import matplotlib.pyplot, time
def forbidden(*args, **kwargs):
    raise RuntimeError('import started a monitor')
time.sleep = forbidden
import generate_png
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
