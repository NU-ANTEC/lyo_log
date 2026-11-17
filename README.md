# lyo_log

Logger and daily plots for legacy Labconco FreeZone lyophilizers, with optional
email alerts and rclone uploads. Designed for Raspberry Pi 3B+ running Bookworm.

## Requirements

- Python 3.10+ with pyserial, python-dotenv, and matplotlib.
- Labconco RS-232 cable (or the alternative below) and an RS232-to-USB adapter.
- [Rclone](https://rclone.org) if uploads are enabled.

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp -n .env.example .env
chmod 600 .env
```

Edit `.env` for your existing data directory, serial port, plot settings, and
optional alerts/uploads. Select `LABCONCO_STYLE`:

- `freezone`: base only.
- `stoppering_combined`: base + stoppering tray.
- `stoppering_direct`: directly connected stoppering tray, without base data.

All modes default to 2400 baud, 8N1; pressures are µbar and temperatures °C.
Local `.env` files are ignored by Git. Example systemd services and an upload
timer are included; adapt their account and paths before installing.
See the [deployment guide](docs/DEPLOYMENT.md) for migration and setup details.

## Files

- `labconco_log.py`: records daily raw logs and reconnects after serial silence.
- `generate_png.py`: parses all three modes and generates daily PNGs.
- `send_alert_email.py`: sends enabled base-unit alerts.
- `rclone_lyo.py`: uploads files when enabled.

`generate_png_shelf.py` is a compatibility entry point; select the parser in `.env`.

## USB recovery and watchdog

The logger tries close/reopen recovery first; adapter-only reset is opt-in.
Disable the old `ttyerror_reboot.sh` launcher so it does not preempt recovery.
See [USB recovery](docs/DEPLOYMENT.md#serial-data-watchdog-and-usb-recovery) and
[hardware-watchdog setup](docs/DEPLOYMENT.md#optional-pi-hardware-watchdog).
The hardware watchdog monitors Pi responsiveness, not serial data flow.

## Cable wiring

Alternative to Labconco cable P/N 7537800:
- [RJ12 cable](https://www.amazon.com/dp/B0C1VJV1JW/)
- [DB9-to-RJ12 adapter](https://www.amazon.com/dp/B0779NCTG7/)

![Labconco RS-232 cable wiring diagram](https://github.com/user-attachments/assets/d1e74c2f-63f0-4bc2-b2db-69833f65bb5d)

Looking into the RJ12 port with the notch up, connect the rightmost wire to DB9
pin 2 and the leftmost to pin 5. Verify against the instrument manual; reversed
wiring produces garbled output. Do not connect RS-232 directly to Pi GPIO.
