"""Upload stable data snapshots; original-file retention belongs to the logger."""

import argparse
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from lyo_config import ConfigError, configure_logging, load_settings

LOG = logging.getLogger(__name__)


def _snapshot_copy(source, destination):
    # Pin the opened file and its initial size. Appends are left for the next
    # upload; an atomic PNG replacement cannot change this open descriptor.
    with open(source, "rb") as original, open(destination, "wb") as target:
        metadata = os.fstat(original.fileno())
        remaining = metadata.st_size
        while remaining:
            block = original.read(min(remaining, 1024 * 1024))
            if not block:
                raise OSError("Source file shrank while preparing upload snapshot")
            target.write(block)
            remaining -= len(block)
    os.utime(destination, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    return destination


def _snapshot_ignores(directory, names):
    # Match rclone's default refusal to follow symlinks, and never capture the
    # plotter's temporary, unfinished images alongside the published PNGs.
    return [name for name in names
            if name.startswith(".plot-") or (Path(directory) / name).is_symlink()]


def upload(settings, runner=None, *, additional_destinations=()):
    if not settings.upload_enabled:
        LOG.info("Uploads disabled; rclone was not run")
        return 0
    runner = runner if runner is not None else subprocess.run
    try:
        # Stage beside, not inside, the source tree. This uses disk space on
        # that filesystem instead of assuming the Pi's /tmp has enough RAM.
        source = settings.rclone_source
        with tempfile.TemporaryDirectory(prefix=".lyo-upload-", dir=source.parent) as staging:
            snapshot = Path(staging) / "data"
            shutil.copytree(source, snapshot, copy_function=_snapshot_copy,
                            ignore=_snapshot_ignores)
            LOG.info("Upload snapshot prepared")
            destinations = [settings.rclone_destination, *additional_destinations]
            failed = False
            for number, destination in enumerate(destinations, 1):
                command = [settings.rclone_executable, "copy", str(snapshot), destination]
                try:
                    result = runner(command, check=True)
                    if result.returncode:
                        raise subprocess.CalledProcessError(result.returncode, command)
                    LOG.info("Upload destination %d/%d completed", number, len(destinations))
                except (OSError, subprocess.CalledProcessError) as error:
                    LOG.error("Upload destination %d/%d failed (%s)",
                              number, len(destinations), type(error).__name__)
                    failed = True
            if failed:
                return 1
        LOG.info("Upload completed")
        return 0
    except (OSError, shutil.Error) as error:
        LOG.error("Upload snapshot failed (%s): %s", type(error).__name__, error)
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--additional-destination", action="append", default=[],
                        help="also copy the same snapshot to this rclone destination; repeatable")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(operation="upload")
        configure_logging(settings)
        return upload(settings, additional_destinations=args.additional_destination)
    except ConfigError as error:
        LOG.error("%s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
