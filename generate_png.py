"""Parse Labconco records; the configured report mode is always explicit."""

import argparse
import logging
import math
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

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
    for name in ("base", "tray"):
        if match[name] is None:
            continue
        try:
            if name == "base":
                _base(match[name], measurements)
            else:
                metadata = _shelf(match[name], measurements)
        except ParseError:
            # Keep a valid sibling; missing channels remain explicit plot gaps.
            continue
        blocks.add(name)
    if not blocks:
        raise ParseError("Combined report has no recognized measurement block")
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


def build_figure(records, settings, day):
    if not records:
        raise ValueError("No recognized records to plot; check LABCONCO_STYLE and input")
    fig, axes = plt.subplots(2, 1, sharex=True,
                             figsize=(settings.plot_width_inches, settings.plot_height_inches))
    hours = [record.hours for record in records]
    channels = {
        "base_pressure": (0, "Base pressure"), "shelf_pressure": (0, "Shelf pressure"),
        "collector_temperature": (1, "Collector temperature"),
        "shelf_temperature": (1, "Shelf/system temperature"),
        "probe_1": (1, "Probe 1"), "probe_2": (1, "Probe 2"), "probe_3": (1, "Probe 3"),
    }
    for key, (axis, label) in channels.items():
        if settings.style == "stoppering_direct" and key in ("base_pressure", "collector_temperature"):
            continue
        if settings.style == "freezone" and key not in ("base_pressure", "collector_temperature"):
            continue
        values = [record.measurements[key] for record in records]
        if any(value is not None for value in values):
            axes[axis].plot(hours, [math.nan if value is None else value for value in values],
                            ".-", label=label, markersize=3)
    axes[0].set_ylabel("Pressure (µbar)")
    axes[0].set_yscale("log")
    axes[0].set_ylim(settings.pressure_min_ubar, settings.pressure_max_ubar)
    axes[0].set_title(f"{settings.instrument_name} — {day:%Y-%m-%d}")
    axes[1].set_ylabel("Temperature (°C)")
    axes[1].set_ylim(settings.temperature_min_c, settings.temperature_max_c)
    axes[1].set_xlim(0, 24)
    axes[1].set_xlabel("Hour")
    last = records[-1]
    notes = []
    if settings.style == "stoppering_direct":
        notes.append("Base telemetry unavailable (direct stoppering connection)")
    else:
        if (last.measurements["base_pressure"] is None
                or last.measurements["collector_temperature"] is None):
            notes.append("Expected base telemetry unavailable/incomplete")
        if settings.style == "stoppering_combined" and (last.measurements["shelf_pressure"] is None
                                                       or last.measurements["shelf_temperature"] is None):
            notes.append("Expected tray telemetry unavailable/incomplete")
    if not any(record.measurements[key] is not None for record in records
               for key in ("base_pressure", "shelf_pressure")):
        notes.append("Pressure unavailable")
    if notes:
        axes[0].text(0.01, 0.98, "\n".join(notes), transform=axes[0].transAxes,
                     va="top", fontsize="small")
    for axis in axes:
        if axis.lines:
            axis.legend(loc="center left", bbox_to_anchor=(1, 0.5))
        axis.grid(True, alpha=0.2)
    fig.tight_layout()
    return fig


def render_plot(records, settings, day, output_path=None):
    target = Path(output_path) if output_path else settings.png_directory / f"{day:%y%m%d}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    fig = build_figure(records, settings, day)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".plot-", suffix=".png",
                                         delete=False) as output:
            temporary = Path(output.name)
            fig.savefig(output, format="png", bbox_inches="tight")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        LOG.debug("Updated plot: %s", target)
        return target
    finally:
        plt.close(fig)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def check_continuous_segment(hours, condition_mask, min_duration):
    """Legacy behavior, including the short-history rule; see README."""
    if not hours or not condition_mask or len(hours) != len(condition_mask):
        return False
    if hours[-1] - hours[0] < min_duration:
        return all(condition_mask)
    active = []
    for hour, condition in zip(hours, condition_mask):
        if condition:
            active.append(hour)
        else:
            active = []
    return len(active) >= 2 and active[-1] - active[0] >= min_duration


def evaluate_alerts(records, settings, sender=None):
    if not settings.alerts_enabled:
        return None
    if not records or settings.style == "stoppering_direct":
        return "unavailable"
    latest = records[-1].measurements
    if latest["base_pressure"] is None or latest["collector_temperature"] is None:
        return "unavailable"
    hours = [record.hours for record in records]
    # Missing points break continuous conditions; they are not healthy samples.
    cold = [record.measurements["collector_temperature"] is not None
            and record.measurements["collector_temperature"] < settings.temperature_threshold
            for record in records]
    high = [record.measurements["base_pressure"] is not None
            and record.measurements["base_pressure"] > settings.pressure_threshold
            for record in records]
    cold_duration = check_continuous_segment(hours, cold, settings.alert_duration_hours)
    high_duration = check_continuous_segment(hours, high, settings.alert_duration_hours)
    alert = ("Vacuum" if cold_duration else "Defrosting") if high_duration else (
        None if cold_duration else "Temperature")
    flag = settings.alert_flag_file
    event = None
    if alert and not flag.exists():
        if sender is None:
            from send_alert_email import send_alert
            sender = send_alert
        if sender(alert, settings):
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(alert, encoding="utf-8")
            event = "ALERT: " + alert
        else:
            LOG.warning("Alert delivery failed; delivered flag was not set")
    elif alert is None and flag.exists():
        flag.unlink()
        event = "Alert cleared"
    if event:
        settings.alert_log_file.parent.mkdir(parents=True, exist_ok=True)
        with settings.alert_log_file.open("a", encoding="utf-8") as output:
            output.write(f"{datetime.now().isoformat()} - {event}\n")
        LOG.info("%s", event)
    return alert


def process_log_file(path, settings, output_path=None):
    day = datetime.strptime(Path(path).stem, "%y%m%d").date()
    records, rejected = parse_log_file(path, settings.style)
    if rejected:
        LOG.warning("Rejected %d records in %s; check input/report mode", rejected, path)
    target = render_plot(records, settings, day, output_path)
    status = evaluate_alerts(records, settings)
    if status == "unavailable":
        LOG.debug("Base-derived alerts unavailable for current telemetry")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render the configured Labconco report mode")
    parser.add_argument("--once", action="store_true", help="render once, then exit")
    parser.add_argument("--no-alerts", action="store_true",
                        help="disable email and alarm-state changes (safe preview)")
    parser.add_argument("--input", type=Path, help="dated YYMMDD.txt input (requires --once)")
    parser.add_argument("--output", type=Path, help="PNG destination (requires --once)")
    args = parser.parse_args(argv)
    if (args.input or args.output) and not args.once:
        parser.error("--input and --output require --once")
    try:
        overrides = {**os.environ, "ALERTS_ENABLED": "false"} if args.no_alerts else None
        settings = load_settings(environ=overrides)
        configure_logging(settings)
        if args.once:
            path = args.input or settings.log_directory / (datetime.now().strftime("%y%m%d") + ".txt")
            process_log_file(path, settings, args.output)
            return 0
        LOG.info("Plot monitor started (%s)", settings.style)
        last_signature, last_error = None, None
        while True:
            path = settings.log_directory / (datetime.now().strftime("%y%m%d") + ".txt")
            try:
                stat = path.stat()
                signature = (path, stat.st_mtime_ns, stat.st_size)
                if signature != last_signature:
                    process_log_file(path, settings)
                    last_signature, last_error = signature, None
            except (OSError, ValueError) as error:
                message = str(error)
                if message != last_error:
                    LOG.warning("Plot unavailable: %s", message)
                    last_error = message
            time.sleep(settings.plot_interval_seconds)
    except KeyboardInterrupt:
        return 0
    except (ConfigError, OSError, ValueError) as error:
        LOG.error("%s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
