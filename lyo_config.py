"""Shared, side-effect-free configuration for the lyophilizer tools."""

import logging
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

STYLES = ("freezone", "stoppering_combined", "stoppering_direct")
PROJECT_DIR = Path(__file__).resolve().parent


class ConfigError(ValueError):
    """A deployment setting is absent or invalid."""


@dataclass(frozen=True)
class Settings:
    style: str
    instrument_name: str
    serial_port: str
    serial_baudrate: int
    serial_timeout_seconds: float
    serial_recovery_enabled: bool
    serial_expected_interval_seconds: float
    serial_idle_timeout_seconds: float
    serial_reopen_attempts: int
    serial_retry_initial_seconds: float
    serial_retry_max_seconds: float
    usb_reset_enabled: bool
    usb_vendor_id: str
    usb_product_id: str
    usb_serial_number: str = field(repr=False)
    usb_reset_min_interval_seconds: float
    log_directory: Path
    png_directory: Path
    alert_flag_file: Path
    alert_log_file: Path
    plot_interval_seconds: float
    plot_width_inches: float
    plot_height_inches: float
    pressure_min_ubar: float
    pressure_max_ubar: float
    temperature_min_c: float
    temperature_max_c: float
    alerts_enabled: bool
    alert_duration_hours: float
    pressure_threshold: float | None
    temperature_threshold: float | None
    gmail_user: str = field(repr=False)
    gmail_app_password: str = field(repr=False)
    alert_recipient: str = field(repr=False)
    smtp_host: str
    smtp_port: int
    upload_enabled: bool
    rclone_executable: str
    rclone_source: Path
    rclone_destination: str = field(repr=False)
    data_retention_days: int
    log_level: str


def load_settings(env_file=None, environ=None, project_dir=None, operation="plot"):
    """Read a project-local .env, then overlay process environment variables.

    Inject ``environ`` and ``project_dir`` for deterministic tests. No settings
    are exported to the process and no operational resources are opened here.
    """
    root = Path(project_dir or PROJECT_DIR).expanduser().resolve()
    values = dict(dotenv_values(Path(env_file) if env_file else root / ".env"))
    values.update(os.environ if environ is None else environ)

    def text(key, default=""):
        value = values.get(key)
        return str(value).strip() if value is not None else str(default)

    def boolean(key, default=False):
        value = (text(key) or ("true" if default else "false")).lower()
        if value not in ("true", "false"):
            raise ConfigError(f"{key} must be true or false")
        return value == "true"

    def number(key, default, *, integer=False, positive=True):
        value = text(key)
        if not value:
            value = default
        if value is None:
            return None
        try:
            result = int(value) if integer else float(value)
        except (TypeError, ValueError):
            raise ConfigError(f"{key} must be {'an integer' if integer else 'a number'}") from None
        if not math.isfinite(result) or (positive and result <= 0):
            raise ConfigError(f"{key} must be finite{' and positive' if positive else ''}")
        return result

    def path(key, default):
        result = Path(text(key) or default).expanduser()
        return result if result.is_absolute() else (root / result).resolve()

    style = text("LABCONCO_STYLE")
    if style not in STYLES:
        raise ConfigError("LABCONCO_STYLE must be one of: " + ", ".join(STYLES))
    args = {"style": style, "instrument_name": text("INSTRUMENT_NAME") or "Freeze dryer",
            "serial_port": text("SERIAL_PORT") or "/dev/ttyUSB0"}
    defaults = {
        "SERIAL_BAUDRATE": 2400, "SERIAL_TIMEOUT_SECONDS": 1,
        "SERIAL_EXPECTED_INTERVAL_SECONDS": 10, "SERIAL_IDLE_TIMEOUT_SECONDS": 120,
        "SERIAL_REOPEN_ATTEMPTS": 3, "SERIAL_RETRY_INITIAL_SECONDS": 1,
        "SERIAL_RETRY_MAX_SECONDS": 30, "USB_RESET_MIN_INTERVAL_SECONDS": 600,
        "PLOT_INTERVAL_SECONDS": 60, "PLOT_WIDTH_INCHES": 10,
        "PLOT_HEIGHT_INCHES": 6, "PRESSURE_MIN_UBAR": 5,
        "PRESSURE_MAX_UBAR": 5000, "ALERT_DURATION_HOURS": 0.25,
        "SMTP_PORT": 465, "DATA_RETENTION_DAYS": 0,
    }
    integers = {"SERIAL_BAUDRATE", "SERIAL_REOPEN_ATTEMPTS", "SMTP_PORT", "DATA_RETENTION_DAYS"}
    for key, default in defaults.items():
        args[key.lower()] = number(key, default, integer=key in integers,
                                   positive=key != "DATA_RETENTION_DAYS")
    for key, default in (("TEMPERATURE_MIN_C", -90), ("TEMPERATURE_MAX_C", 40),
                         ("PRESSURE_THRESHOLD", None), ("TEMPERATURE_THRESHOLD", None)):
        args[key.lower()] = number(key, default, positive=key == "PRESSURE_THRESHOLD")
    for key, default in (("SERIAL_RECOVERY_ENABLED", True), ("USB_RESET_ENABLED", False),
                         ("ALERTS_ENABLED", False), ("UPLOAD_ENABLED", False)):
        args[key.lower()] = boolean(key, default)
    for low, high in (("PRESSURE_MIN_UBAR", "PRESSURE_MAX_UBAR"),
                      ("TEMPERATURE_MIN_C", "TEMPERATURE_MAX_C")):
        if args[low.lower()] >= args[high.lower()]:
            raise ConfigError(f"{high} must exceed {low}")
    if args["serial_idle_timeout_seconds"] <= args["serial_expected_interval_seconds"]:
        raise ConfigError("SERIAL_IDLE_TIMEOUT_SECONDS must exceed SERIAL_EXPECTED_INTERVAL_SECONDS")
    if args["serial_retry_max_seconds"] < args["serial_retry_initial_seconds"]:
        raise ConfigError("SERIAL_RETRY_MAX_SECONDS must not be less than SERIAL_RETRY_INITIAL_SECONDS")
    if args["data_retention_days"] < 0:
        raise ConfigError("DATA_RETENTION_DAYS must not be negative")
    if args["smtp_port"] > 65535:
        raise ConfigError("SMTP_PORT must be at most 65535")
    args["log_directory"] = path("LOG_DIRECTORY", "data")
    args["png_directory"] = path("PNG_DIRECTORY", args["log_directory"])
    args["alert_flag_file"] = path("ALERT_FLAG_FILE", "state/alert_active.flag")
    args["alert_log_file"] = path("ALERT_LOG_FILE", "state/alerts.log")
    args["rclone_source"] = path("RCLONE_SOURCE", args["log_directory"])
    for key, default in (("GMAIL_USER", ""), ("GMAIL_APP_PASSWORD", ""),
                         ("ALERT_RECIPIENT", ""), ("SMTP_HOST", "smtp.gmail.com"),
                         ("RCLONE_EXECUTABLE", "rclone"), ("RCLONE_DESTINATION", ""),
                         ("USB_VENDOR_ID", ""), ("USB_PRODUCT_ID", ""),
                         ("USB_SERIAL_NUMBER", ""), ("LOG_LEVEL", "INFO")):
        args[key.lower()] = text(key, default)
    args["log_level"] = args["log_level"].upper()
    if args["log_level"] not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ConfigError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    if args["usb_reset_enabled"]:
        for key in ("USB_VENDOR_ID", "USB_PRODUCT_ID"):
            if not re.fullmatch(r"[0-9a-fA-F]{4}", args[key.lower()]):
                raise ConfigError(f"{key} must contain four hexadecimal digits")
            args[key.lower()] = args[key.lower()].lower()
        if not args["usb_serial_number"]:
            raise ConfigError("USB_SERIAL_NUMBER is required for USB reset")
    if operation in ("plot", "mail") and args["alerts_enabled"]:
        for key in ("PRESSURE_THRESHOLD", "TEMPERATURE_THRESHOLD"):
            if args[key.lower()] is None:
                raise ConfigError(f"{key} is required when alerts are enabled")
        for key in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "ALERT_RECIPIENT"):
            if not args[key.lower()]:
                raise ConfigError(f"{key} is required when alerts are enabled")
    if operation == "upload" and args["upload_enabled"]:
        if not args["rclone_destination"]:
            raise ConfigError("RCLONE_DESTINATION is required when uploads are enabled")
        if not args["rclone_executable"]:
            raise ConfigError("RCLONE_EXECUTABLE must not be blank")
    return Settings(**args)


def configure_logging(settings):
    logging.basicConfig(level=settings.log_level,
                        format="%(levelname)s %(name)s: %(message)s")
