#!/bin/bash

# DEPRECATED: do not enable with the logger's reconnect recovery. This legacy
# watcher can reboot before recovery runs and can match historical journal lines.
# See README for gentle serial recovery and optional PID 1 hardware watchdog setup.

# Monitor journalctl for the specific log line in real-time using grep
journalctl -f | grep --line-buffered "pl2303 ttyUSB0: usb_serial_generic_read_bulk_callback - urb stopped" | while read -r line; do
    echo "Detected the specified log line. Rebooting..."
    sudo reboot
done
