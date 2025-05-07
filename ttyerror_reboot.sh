#!/bin/bash

# Monitor journalctl for the specific log line in real-time using grep
journalctl -f | grep --line-buffered "pl2303 ttyUSB0: usb_serial_generic_read_bulk_callback - urb stopped" | while read -r line; do
    echo "Detected the specified log line. Rebooting..."
    sudo reboot
done
