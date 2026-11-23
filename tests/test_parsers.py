import tempfile
import unittest
from pathlib import Path

from generate_png import ParseError, parse_record, parse_log_file
from tests.fixtures import BASE, COMBINED, DIRECT, PADDED_DIRECT_ROWS, STANDBY


class ParserTests(unittest.TestCase):
    def test_actual_nul_padded_direct_records_parse_without_rewriting_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "261117.txt"
            original = b"".join(PADDED_DIRECT_ROWS)
            path.write_bytes(original)
            records, rejected = parse_log_file(path, "stoppering_direct")
            self.assertEqual(rejected, 0)
            self.assertEqual(len(records), 5)
            self.assertEqual(records[0].timestamp, "142611")
            self.assertEqual(records[-1].timestamp, "142651")
            for record in records:
                self.assertEqual(record.measurements["shelf_pressure"], 24)
                self.assertEqual(record.measurements["shelf_temperature"], 26)
                self.assertIsNone(record.measurements["base_pressure"])
                self.assertEqual(record.metadata["state"], "STNDBY")
            self.assertEqual(records[2].measurements["probe_3"], 26)
            self.assertEqual(records[4].measurements["probe_2"], 26)
            self.assertEqual(path.read_bytes(), original)

    def test_only_leading_nul_padding_is_ignored(self):
        for padding in ("\x00", "\x00\x00", "\x00 \t\x00"):
            with self.subTest(padding=padding):
                line = DIRECT.replace(":<", padding + ":<", 1)
                record = parse_record(line, "stoppering_direct")
                self.assertEqual(record.measurements["shelf_pressure"], 24)
        corrupt = DIRECT.replace("VAC=  24", "VAC= 2\x004")
        self.assertIsNone(parse_record(corrupt, "stoppering_direct").measurements["shelf_pressure"])
        with self.assertRaises(ParseError):
            parse_record(DIRECT.replace(":<", "\x02:<", 1), "stoppering_direct")

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

    def test_empty_combined_block_does_not_discard_valid_sibling(self):
        for tray in ("", " ", "PR=1S=2H TR=INDF"):
            with self.subTest(tray=tray):
                record = parse_record(f"000010 B<T=-58V=470>TD<{tray}>", "stoppering_combined")
                self.assertEqual(record.measurements["base_pressure"], 470)
                self.assertIsNone(record.measurements["shelf_pressure"])
                self.assertEqual(record.blocks, frozenset({"base"}))
        record = parse_record("000010 B<>TD<ST=23V=570>", "stoppering_combined")
        self.assertEqual(record.measurements["shelf_pressure"], 570)
        self.assertIsNone(record.measurements["base_pressure"])
        self.assertEqual(record.blocks, frozenset({"tray"}))
        with self.assertRaises(ParseError):
            parse_record("000010 B<>TD< >", "stoppering_combined")

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
