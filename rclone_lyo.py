"""Optional timer-driven rclone copy; raw-log retention belongs to the logger."""

import logging
import subprocess

from lyo_config import ConfigError, configure_logging, load_settings

LOG = logging.getLogger(__name__)


def upload(settings, runner=None):
    if not settings.upload_enabled:
        LOG.info("Uploads disabled; rclone was not run")
        return 0
    runner = runner if runner is not None else subprocess.run
    command = [settings.rclone_executable, "copy", str(settings.rclone_source),
               settings.rclone_destination]
    try:
        result = runner(command, check=True)
        if result.returncode:
            LOG.error("Upload failed (exit %d)", result.returncode)
            return 1
        LOG.info("Upload completed")
        return 0
    except (OSError, subprocess.CalledProcessError) as error:
        LOG.error("Upload failed (%s)", type(error).__name__)
        return 1


def main():
    try:
        settings = load_settings(operation="upload")
        configure_logging(settings)
        return upload(settings)
    except ConfigError as error:
        LOG.error("%s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
