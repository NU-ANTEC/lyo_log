import tempfile
import unittest
from pathlib import Path

from generate_png import ParseError, parse_record, parse_log_file
from tests.fixtures import BASE, COMBINED, DIRECT, STANDBY


class ParserTests(unittest.TestCase):
    def test_combined_keeps_base_and_shelf_separate(self):
        record = parse_record(COMBINED, "stoppering_combined")
        self.assertEqual(record.timestamp, "000010")
        self.assertEqual(record.measurements["collector_temperature"], -58)
        self.assertEqual(record.measurements["base_pressure"], 470)
        self.assertEqual(record.measurements["shelf_temperature"], 23)
        self.assertEqual(record.measurements["shelf_pressure"], 570)
        self.assertEqual(record.measurements["probe_1"], 24)
        self.assertEqual(record.metadata["program"], "0")
        self.assertEqual(record.metadata["segment"], "")
        self.assertEqual(record.metadata["remaining_time"], "9999")

    def test_direct_has_no_invented_collector(self):
        record = parse_record(DIRECT, "stoppering_direct")
        self.assertIsNone(record.measurements["collector_temperature"])
        self.assertIsNone(record.measurements["base_pressure"])
        self.assertEqual(record.measurements["shelf_pressure"], 24)
        self.assertEqual(record.measurements["shelf_temperature"], 16)
        self.assertEqual(record.metadata["program"], "1")
        self.assertEqual(record.metadata["segment"], "2H")
        self.assertEqual(record.metadata["remaining_time"], "INDF")

    def test_standby_and_base(self):
        standby = parse_record(STANDBY, "stoppering_direct")
        self.assertEqual(standby.metadata["state"], "STNDBY")
        self.assertEqual(standby.metadata["segment"], "")
        record = parse_record(BASE, "freezone")
        self.assertEqual(record.measurements["collector_temperature"], -56)
        self.assertEqual(record.measurements["base_pressure"], 90)
        self.assertIsNone(record.measurements["shelf_pressure"])

    def test_field_scoping_spacing_and_sentinels(self):
        record = parse_record(COMBINED.replace("ST=+23", "ST =999")
                              .replace("P2=+23", "P2=oops")
                              .replace("V= 570", "V=999"), "stoppering_combined")
        self.assertIsNone(record.measurements["shelf_temperature"])
        self.assertIsNone(record.measurements["probe_2"])
        self.assertEqual(record.measurements["shelf_pressure"], 999)
        self.assertEqual(record.measurements["base_pressure"], 470)

    def test_partial_combined_keeps_available_block(self):
        record = parse_record(BASE, "stoppering_combined")
        self.assertEqual(record.measurements["base_pressure"], 90)
        self.assertIsNone(record.measurements["shelf_pressure"])
        record = parse_record("000010 TD<ST=-20P1=999V=10>", "stoppering_combined")
        self.assertEqual(record.measurements["shelf_temperature"], -20)
        self.assertIsNone(record.measurements["probe_1"])

    def test_wrong_modes_invalid_frames_and_times(self):
        for line, mode in ((BASE, "stoppering_direct"), (DIRECT, "stoppering_combined"),
                           (COMBINED, "freezone"), (BASE, "bulk"),
                           (BASE.replace("152808", "256001"), "freezone"),
                           (BASE[:-1], "freezone"), ("152808 B<garbage>", "freezone")):
            with self.subTest(line=line, mode=mode), self.assertRaises(ParseError):
                parse_record(line, mode)

    def test_nonfinite_and_nonpositive_pressures_are_missing(self):
        for value in ("0", "-5", "nan", "inf", "HI"):
            record = parse_record(BASE.replace("V=90", "V=" + value), "freezone")
            self.assertIsNone(record.measurements["base_pressure"])

    def test_file_parser_summarizes_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "261116.txt"
            path.write_text(BASE + "\nbad record\n\n" + BASE)
            records, rejected = parse_log_file(path, "freezone")
            self.assertEqual(len(records), 2)
            self.assertEqual(rejected, 1)


if __name__ == "__main__":
    unittest.main()
