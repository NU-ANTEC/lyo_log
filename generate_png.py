"""Parse Labconco records; the configured report mode is always explicit."""

import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime

from lyo_config import ConfigError, configure_logging, load_settings

LOG = logging.getLogger(__name__)
CHANNELS = ("collector_temperature", "base_pressure", "shelf_temperature",
            "shelf_pressure", "probe_1", "probe_2", "probe_3")


class ParseError(ValueError):
    """An invalid timestamp, frame, or configured report mode."""


@dataclass
class Record:
    timestamp: str
    measurements: dict
    metadata: dict
    blocks: frozenset

    @property
    def hours(self):
        return (int(self.timestamp[:2]) + int(self.timestamp[2:4]) / 60
                + int(self.timestamp[4:]) / 3600)


def _fields(block, keys):
    alternatives = "|".join(sorted(keys, key=len, reverse=True))
    pattern = rf"({alternatives})\s*=\s*(.*?)(?=(?:{alternatives})\s*=|$)"
    return {key: value.strip() for key, value in re.findall(pattern, block)}


def _measurement(value, pressure=False):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(result) or (pressure and result <= 0):
        return None
    if not pressure and result == 999:
        return None
    return result


def _base(block, measurements):
    fields = _fields(block, ("T", "V", "SF", "C", "PG"))
    if not {"T", "V"}.intersection(fields):
        raise ParseError("Base frame has no recognized measurement fields")
    measurements["collector_temperature"] = _measurement(fields.get("T"))
    measurements["base_pressure"] = _measurement(fields.get("V"), pressure=True)


def _shelf(block, measurements, direct=False):
    keys = (("PROG", "SEG", "TRM", "SYS", "PRB1", "PRB2", "PRB3", "VAC")
            if direct else ("PR", "S", "TR", "ST", "P1", "P2", "P3", "V"))
    fields = _fields(block, keys)
    temp, pressure = ("SYS", "VAC") if direct else ("ST", "V")
    if not {temp, pressure, *(f"PRB{i}" if direct else f"P{i}" for i in range(1, 4))}.intersection(fields):
        raise ParseError("Tray frame has no recognized measurement fields")
    measurements["shelf_temperature"] = _measurement(fields.get(temp))
    measurements["shelf_pressure"] = _measurement(fields.get(pressure), pressure=True)
    for i in range(1, 4):
        measurements[f"probe_{i}"] = _measurement(fields.get(f"PRB{i}" if direct else f"P{i}"))
    return {
        "program": fields.get("PROG" if direct else "PR", ""),
        "segment": fields.get("SEG" if direct else "S", ""),
        "remaining_time": fields.get("TRM" if direct else "TR", ""),
        "state": "STNDBY" if direct and block.lstrip().startswith("STNDBY") else "",
    }


def parse_freezone(payload, measurements):
    match = re.fullmatch(r"B<([^<>]*)>", payload)
    if not match:
        raise ParseError("Expected base-only B<...> report")
    _base(match[1], measurements)
    return {}, frozenset({"base"})


def parse_stoppering_combined(payload, measurements):
    match = re.fullmatch(r"(?:B<(?P<base>[^<>]*)>\s*)?(?:TD<(?P<tray>[^<>]*)>)?", payload)
    if not match or not any(value is not None for value in match.groups()):
        raise ParseError("Expected B<...>TD<...> report (partial blocks allowed)")
    blocks = set()
    metadata = {}
    if match["base"] is not None:
        _base(match["base"], measurements)
        blocks.add("base")
    if match["tray"] is not None:
        metadata = _shelf(match["tray"], measurements)
        blocks.add("tray")
    return metadata, frozenset(blocks)


def parse_stoppering_direct(payload, measurements):
    match = re.fullmatch(r":\s*<([^<>]*)>", payload)
    if not match:
        raise ParseError("Expected direct stoppering :<...> report")
    return _shelf(match[1], measurements, direct=True), frozenset({"tray"})


def parse_record(line, style):
    parsers = {"freezone": parse_freezone,
               "stoppering_combined": parse_stoppering_combined,
               "stoppering_direct": parse_stoppering_direct}
    if style not in parsers:
        raise ParseError("Unsupported report mode")
    parts = line.strip().split(maxsplit=1)
    if len(parts) != 2 or not re.fullmatch(r"\d{6}", parts[0]):
        raise ParseError("Expected HHMMSS followed by an instrument report")
    try:
        datetime.strptime(parts[0], "%H%M%S")
    except ValueError:
        raise ParseError("Invalid HHMMSS timestamp") from None
    measurements = dict.fromkeys(CHANNELS)
    metadata, blocks = parsers[style](parts[1].strip(), measurements)
    return Record(parts[0], measurements, metadata, blocks)


def parse_log_file(path, style):
    records, rejected = [], 0
    with open(path, encoding="utf-8", errors="replace") as source:
        for line in source:
            if not line.strip():
                continue
            try:
                records.append(parse_record(line, style))
            except ParseError:
                rejected += 1
    return records, rejected


def main():
    try:
        settings = load_settings()
        configure_logging(settings)
        path = settings.log_directory / (datetime.now().strftime("%y%m%d") + ".txt")
        records, rejected = parse_log_file(path, settings.style)
        LOG.info("Read %d records (%d rejected)", len(records), rejected)
        return 0
    except (ConfigError, OSError) as error:
        LOG.error("%s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
