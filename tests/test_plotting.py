import math
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt

from generate_png import (build_figure, check_continuous_segment, evaluate_alerts,
                          parse_record, render_plot)
from lyo_config import load_settings
from tests.fixtures import BASE, COMBINED, DIRECT


class PlotAndAlertTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(plt.close, "all")
        self.root = Path(self.temp.name)
        self.settings = load_settings(project_dir=self.root,
                                      environ={"LABCONCO_STYLE": "freezone"})

    def test_combined_units_channels_and_date(self):
        settings = replace(self.settings, style="stoppering_combined")
        fig = build_figure([parse_record(COMBINED, settings.style)], settings, date(2026, 11, 16))
        pressure, temp = fig.axes
        self.assertEqual(pressure.get_yscale(), "log")
        self.assertIn("µbar", pressure.get_ylabel())
        self.assertIn("2026-11-16", pressure.get_title())
        lines = {line.get_label(): list(line.get_ydata()) for line in pressure.lines}
        self.assertEqual(lines["Base pressure"], [470])
        self.assertEqual(lines["Shelf pressure"], [570])
        self.assertIn("Collector temperature", [line.get_label() for line in temp.lines])

    def test_direct_plot_has_only_shelf_channels_and_annotation(self):
        settings = replace(self.settings, style="stoppering_direct")
        fig = build_figure([parse_record(DIRECT, settings.style)], settings, date(2026, 11, 16))
        labels = [line.get_label() for axis in fig.axes for line in axis.lines]
        self.assertNotIn("Collector temperature", labels)
        self.assertNotIn("Base pressure", labels)
        self.assertIn("Shelf pressure", labels)
        self.assertTrue(any("direct stoppering" in text.get_text().lower()
                            for axis in fig.axes for text in axis.texts))

    def test_missing_channels_keep_gaps_and_history(self):
        settings = replace(self.settings, style="stoppering_combined")
        first = parse_record(COMBINED, settings.style)
        second = parse_record("000020 TD<ST=999P1=999V=0>", settings.style)
        third = parse_record(COMBINED.replace("000010", "000030"), settings.style)
        fig = build_figure([first, second, third], settings, date(2026, 11, 16))
        base_line = next(line for line in fig.axes[0].lines if line.get_label() == "Base pressure")
        self.assertEqual(base_line.get_ydata()[0], 470)
        self.assertTrue(math.isnan(base_line.get_ydata()[1]))
        self.assertEqual(base_line.get_ydata()[2], 470)

    def test_expected_missing_base_is_annotated(self):
        settings = replace(self.settings, style="stoppering_combined")
        record = parse_record("000020 TD<ST=20V=10>", settings.style)
        fig = build_figure([record], settings, date(2026, 11, 16))
        self.assertTrue(any("expected" in text.get_text().lower()
                            for axis in fig.axes for text in axis.texts))

    def test_real_png_for_each_mode_without_temporary_leftovers(self):
        for mode, line in (("freezone", BASE), ("stoppering_combined", COMBINED),
                           ("stoppering_direct", DIRECT)):
            settings = replace(self.settings, style=mode, png_directory=self.root / mode)
            target = render_plot([parse_record(line, mode)], settings, date(2026, 11, 16))
            self.assertEqual(target.name, "261116.png")
            self.assertEqual(target.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_legacy_short_history_duration_is_characterized(self):
        self.assertTrue(check_continuous_segment([1.0], [True], 0.25))
        self.assertFalse(check_continuous_segment([1.0, 1.5], [False, True], 0.25))
        self.assertTrue(check_continuous_segment([1.0, 1.3], [True, True], 0.25))

    def test_missing_base_neither_sends_nor_clears_alarm(self):
        settings = replace(self.settings, alerts_enabled=True, style="freezone",
                           pressure_threshold=800, temperature_threshold=-50)
        settings.alert_flag_file.parent.mkdir()
        settings.alert_flag_file.write_text("Vacuum")
        def forbidden(*args):
            self.fail("Missing base must not send an email")
        record = parse_record(BASE.replace("V=90", "V=HI"), settings.style)
        result = evaluate_alerts([record], settings, sender=forbidden)
        self.assertEqual(result, "unavailable")
        self.assertEqual(settings.alert_flag_file.read_text(), "Vacuum")

    def test_delivery_flag_only_on_success_and_healthy_clear(self):
        settings = replace(self.settings, alerts_enabled=True,
                           pressure_threshold=800, temperature_threshold=-50)
        high = parse_record(BASE.replace("V=90", "V=900"), "freezone")
        result = evaluate_alerts([high], settings, sender=lambda *args: False)
        self.assertEqual(result, "Vacuum")
        self.assertFalse(settings.alert_flag_file.exists())
        evaluate_alerts([high], settings, sender=lambda *args: True)
        self.assertEqual(settings.alert_flag_file.read_text(), "Vacuum")
        evaluate_alerts([high], settings, sender=lambda *args: self.fail("duplicate mail"))
        evaluate_alerts([parse_record(BASE, "freezone")], settings,
                        sender=lambda *args: self.fail("healthy must not send"))
        self.assertFalse(settings.alert_flag_file.exists())


if __name__ == "__main__":
    unittest.main()
