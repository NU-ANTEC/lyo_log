"""Durable daily serial recording with gentle, bounded recovery."""

import logging
import os
import re
import signal
import threading
import time
from datetime import datetime, timedelta

import serial

from lyo_config import ConfigError, configure_logging, load_settings
from usb_recovery import reset_adapter

LOG = logging.getLogger(__name__)


def purge_old_logs(directory, days, today, *, extensions=(".txt", ".png")):
    """Delete expired dated regular data files, only when explicitly enabled."""
    if days <= 0:
        return 0
    cutoff = today - timedelta(days=days)
    deleted = 0
    try:
        paths = list(directory.iterdir())
    except FileNotFoundError:
        return 0  # A separate PNG directory may not have been created yet.
    except OSError as error:
        LOG.warning("Retention unavailable for %s: %s", directory, error)
        return 0
    for path in paths:
        try:
            if (path.is_symlink() or not path.is_file() or path.suffix not in extensions
                    or not re.fullmatch(r"\d{6}", path.stem)):
                continue
            try:
                recorded = datetime.strptime(path.stem, "%y%m%d").date()
            except ValueError:
                continue
            if recorded < cutoff:
                path.unlink()
                deleted += 1
        except OSError as error:
            LOG.warning("Retention could not remove/check %s: %s", path, error)
    if deleted:
        LOG.info("Purged %d expired dated data files", deleted)
    return deleted


def _close_serial(connection):
    if connection is not None:
        try:
            connection.close()
        except (OSError, serial.SerialException) as error:
            LOG.warning("Serial close failed: %s", error)


def record_stream(settings, *, serial_factory=None, clock=time.monotonic,
                  now=datetime.now, wait=None, stop=None, reset=reset_adapter):
    """Own one connection. Test seams replace hardware and elapsed time only."""
    stop = stop if stop is not None else threading.Event()
    wait = wait if wait is not None else stop.wait
    serial_factory = serial_factory if serial_factory is not None else serial.Serial
    settings.log_directory.mkdir(parents=True, exist_ok=True)
    purge_old_logs(settings.log_directory, settings.data_retention_days, now().date())
    if settings.png_directory != settings.log_directory:
        purge_old_logs(settings.png_directory, settings.data_retention_days, now().date(),
                       extensions=(".png",))
    connection, output, current_path = None, None, None
    last_input, last_reset = clock(), None
    recovering, failures, saved = False, 0, 0
    delay = settings.serial_retry_initial_seconds
    last_problem = None

    def failed(reason):
        nonlocal connection, recovering, failures, delay, last_reset, last_problem
        _close_serial(connection)
        connection = None
        if recovering:
            failures += 1
        else:
            recovering = True
            failures = 0
        if reason != last_problem:
            LOG.warning("Serial recovery: %s; closing/reopening", reason)
            last_problem = reason
        LOG.debug("Failed reopen count: %d; retry delay: %.1fs", failures, delay)
        if (settings.usb_reset_enabled and failures >= settings.serial_reopen_attempts
                and (last_reset is None or clock() - last_reset >= settings.usb_reset_min_interval_seconds)):
            last_reset = clock()  # Failed calls also consume the cooldown.
            try:
                reset(settings)
            except (OSError, ValueError) as error:
                LOG.warning("USB reset failed: %s; continuing gentle retries", error)
        wait(delay)
        delay = min(delay * 2, settings.serial_retry_max_seconds)

    try:
        while not stop.is_set():
            try:
                if connection is None:
                    connection = serial_factory(
                        port=settings.serial_port, baudrate=settings.serial_baudrate,
                        bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE, timeout=settings.serial_timeout_seconds,
                        exclusive=True)
                    last_input = clock()
                    LOG.debug("Serial port opened; awaiting data")
                raw = connection.readline()
            except (serial.SerialException, OSError) as error:
                if not settings.serial_recovery_enabled:
                    raise
                failed(str(error))
                continue
            if stop.is_set():
                break
            if not raw:
                if (settings.serial_recovery_enabled
                        and clock() - last_input >= settings.serial_idle_timeout_seconds):
                    failed("no serial input within configured idle timeout")
                continue
            last_input = clock()
            try:
                data = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                LOG.warning("Discarded undecodable serial input; USB reset not requested")
                continue
            if not data:
                continue
            moment = now()
            path = settings.log_directory / f"{moment:%y%m%d}.txt"
            if path != current_path:
                if output is not None:
                    output.close()
                    output = None
                output = path.open("a", encoding="utf-8")
                current_path = path
            # Keep storage errors outside the serial-recovery exception handler.
            output.write(f"{moment:%H%M%S} {data}\n")
            output.flush()
            os.fsync(output.fileno())
            saved += 1
            if recovering:
                LOG.info("Serial recording recovered after fresh data was saved")
            recovering, failures, last_problem = False, 0, None
            delay = settings.serial_retry_initial_seconds
    finally:
        try:
            if output is not None:
                output.close()
        finally:
            _close_serial(connection)
    return saved


def main():
    try:
        settings = load_settings(operation="record")
        configure_logging(settings)
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
        LOG.info("Serial logger started (%s, %d baud)", settings.style, settings.serial_baudrate)
        record_stream(settings, stop=stop)
        LOG.info("Serial logger stopped")
        return 0
    except KeyboardInterrupt:
        return 0
    except (ConfigError, OSError, serial.SerialException) as error:
        LOG.error("Logger stopped: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
