# Deployment and recovery

Detailed setup for Raspberry Pi 3B+ and Raspberry Pi OS Bookworm. Run commands
from the project directory unless stated otherwise. For the project overview
and cable diagram, see the [README](../README.md).

## Select the report mode

All parsers live in `generate_png.py`. Choose **one** input mode in `.env`:

| `LABCONCO_STYLE` | Connection / report | Plotted measurements |
| --- | --- | --- |
| `freezone` | Base only: `B<T=...V=...>` | Collector temperature, base pressure |
| `stoppering_combined` | Base forwards both: `B<...>TD<...>` | Base and shelf pressures, collector, shelf/system, three probes |
| `stoppering_direct` | RS-232 connected directly to stoppering tray: `:<PROG=...>` or `:<STNDBY...>` | Shelf pressure, shelf/system temperature, three probes |

The two stoppering modes describe the **same type of instrument**, with different
connection/reporting paths. Direct mode is useful when base-to-tray communication
is unavailable. It explicitly annotates missing base telemetry; it never invents
collector readings or substitutes shelf measurements for base measurements.
Combined mode flags unexpected missing base/tray telemetry while retaining valid
partial data. Modes do not auto-switch when a record is malformed.

All three modes default to **2400 baud, 8N1**. Pressures, including direct `VAC`,
are **µbar**; temperatures are **°C**. Missing temperature markers (`999`), invalid
values, and absent channels create gaps, not zeros. Program/segment/time metadata
includes blank segments, `STNDBY`, and `INDF`. Bulk-tray hardware is **not supported**.
Leading NUL padding before a report is accepted without rewriting the raw logs;
NUL bytes inside measurement fields are not removed.

Protocol references: [FreeZone manual, pp. 33–34](https://www.labconco.com/download/freezone-6-12-and-18-liter-freeze-dry-systems-ma/2HAAkjkFQE7FvPyN6HxcDw)
and [Stoppering manual, pp. 30–31](https://www.labconco.com/download/freezone-stoppering-tray-dryers-manual/7bTeYHdi1bzTDXRawrIQyJ).
The direct stoppering parser also uses real instrument records supplied for this
project. Test fixtures contain no device identities or credentials.

## Install and configure

Use a maintenance window when migrating an existing installation. Back up local
Python edits and service files **outside the checkout** before changing branches;
do not force checkout over local changes. Preserve existing data and `.env`.

For the test branch in an existing clone:

```bash
git fetch origin
git switch feature/configurable-logger-recovery
```

The branch tracks `origin/feature/configurable-logger-recovery` on a fresh switch
when no local branch exists. No merge into master is required to test it.

Install dependencies in the project directory (install `python3-venv` through
your OS package manager first if needed):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Copy the example **only if `.env` does not already exist**:

```bash
cp -n .env.example .env
chmod 600 .env
nano .env
```

The scripts always load `.env` beside `lyo_config.py`, independent of the shell's
working directory. Process environment variables override `.env`; relative
filesystem paths resolve against the project directory. Configuration changes
take effect on process restart. `.env` and local variants are ignored by Git;
only `.env.example` is tracked. Do not commit credentials or device identifiers.
Blank optional values use their documented defaults. Use explicit `false` to
disable a boolean, especially serial recovery, whose default is enabled.

Set at least:

- `LABCONCO_STYLE`: select the mode from the table above.
- `LOG_DIRECTORY`: **your existing raw-data directory**, so migration continues
  the same daily files instead of silently recording to a new directory.
- `SERIAL_PORT`: preferably a unique path listed by `ls -l /dev/serial/by-id/`.
- `INSTRUMENT_NAME`: local plot title and email label.
- `SERIAL_EXPECTED_INTERVAL_SECONDS`: the interval configured on the instrument.

The example lists all settings and units. `PNG_DIRECTORY` defaults to
`LOG_DIRECTORY`; plots retain `YYMMDD.png` filenames. Plot limits, size, refresh
interval, alert paths, and thresholds are configurable. Use separate project
directories/configurations for separate instruments on one computer.

Validate the configuration without opening serial or sending anything:

```bash
.venv/bin/python -c 'from lyo_config import load_settings; load_settings(operation="record"); load_settings(operation="plot"); load_settings(operation="upload"); print("Configuration valid")'
```

Optional email, uploads, deletion, and USB reset are disabled by default. Enabling
an operation requires its associated configuration. Recording does not require
email or upload credentials. Use `LOG_LEVEL=DEBUG` only for troubleshooting;
ordinary records and successful plot refreshes are not echoed at INFO.

## Running and checking output

The logger retains `YYMMDD.txt` files containing `HHMMSS payload` records, with
immediate flush/fsync. It rolls files at midnight without a process restart:

```bash
.venv/bin/python -u labconco_log.py
```

Only one reader should own the port. Stop the old logger before manually starting
a replacement. The logger requests exclusive serial access on Linux.

Render one existing file to check parsing before enabling the monitor:

```bash
.venv/bin/python generate_png.py --once --no-alerts --input /path/to/YYMMDD.txt --output /path/to/check.png
```

Replace `YYMMDD.txt` with a real six-digit dated filename. Its date labels the
plot. `--no-alerts` suppresses email and alarm-state changes and does not require
mail credentials. **Without it, a one-shot render follows `ALERTS_ENABLED` and can
send real alerts.** Then run the monitor with `.venv/bin/python -u generate_png.py`.
`generate_png_shelf.py` is a deprecated forwarding entry point: its filename no
longer chooses the parser. Select the style in `.env` before restarting it.

Completed PNGs replace their destination atomically. If input is missing or
unparseable, the monitor retries and logs the problem; an older PNG can remain.
Check file date/mtime and the journal instead of assuming an existing PNG is fresh.

## Services and supervision

The supplied `.service` files are **templates**, using `/opt/lyo_log` and an
unprivileged `lyolog` account. Before installing, change `User`, `Group`,
`WorkingDirectory`, and both paths in `ExecStart` to your actual account and
project/virtualenv. You can retain an existing service account and directory.
Ensure the account can read `.env`, write the configured directories, and access
the serial port through `dialout` or the appropriate OS group. Never run the
logger as root to bypass a permission problem.

Python loads `.env` itself; do not duplicate it with systemd `EnvironmentFile`.
The templates use unbuffered output, private file permissions, and
`NoNewPrivileges=true`. The logger and plotter restart on failure after three
seconds, with at most five starts per five minutes. Repeated configuration/storage
errors eventually leave the unit failed rather than causing a tight restart loop.

After adapting and installing the templates under `/etc/systemd/system/`:

```bash
sudo systemd-analyze verify /etc/systemd/system/labconco_log.service /etc/systemd/system/generate_png.service
sudo systemctl daemon-reload
sudo systemctl enable --now labconco_log.service generate_png.service
systemctl status labconco_log.service generate_png.service --no-pager
```

If already running, use `systemctl restart` after configuration changes; enabling
an active service does not restart it. After fixing a rate-limited failure, use
`sudo systemctl reset-failed labconco_log.service`, then start it again.

Check both service state **and fresh data**:

```bash
sudo journalctl -u labconco_log.service -u generate_png.service --since "10 minutes ago" --no-pager
```

Inspect the newest records in your configured daily file and the PNG modification
time. An `active` service alone does not prove data flow. Per-record stdout from
older scripts caused journal growth; this version leaves records in data files.
Journald retention is separate from logrotate and from raw-data retention.

## Serial-data watchdog and USB recovery

An endpoint stall such as `usb_serial_generic_read_bulk_callback - urb stopped:
-32` can leave the process alive while reads return no data. Restart-on-failure
alone cannot detect that condition. The logger therefore checks serial inactivity
using a monotonic clock:

1. Wait through ordinary read timeouts.
2. After `SERIAL_IDLE_TIMEOUT_SECONDS` of silence, close and reopen the port.
3. Retry open/read failures with exponential backoff from
   `SERIAL_RETRY_INITIAL_SECONDS` up to `SERIAL_RETRY_MAX_SECONDS`.
4. Confirm recovery only after fresh data is written and fsynced.
5. Optionally try an **adapter-only reset** after `SERIAL_REOPEN_ATTEMPTS` failed
   reopen attempts, with `USB_RESET_MIN_INTERVAL_SECONDS` between reset attempts.

Defaults are a 120-second inactivity threshold for a 10-second transmission
interval, three failed reopens, 1–30-second backoff, and **USB reset disabled**.
The original faulty connection is not a failed reopen: with a limit of three,
reset is considered only after the original fault and three unsuccessful
reconnections. Opening a port without receiving fresh data is unsuccessful.
Instruments can transmit every 10–600 seconds: set the expected interval correctly
and the inactivity threshold comfortably above the **actual** interval. Increase
both for slower reporting. If long silence is normal, either choose a suitable
threshold or disable inactivity recovery with `SERIAL_RECOVERY_ENABLED=false`.
With recovery disabled, connection errors exit for systemd to handle; ordinary
empty reads continue waiting.

The connection is resolved again each time; use a stable by-id serial path to
survive tty renumbering. Storage errors are not mistaken for USB failures.
Malformed/undecodable text does not request a USB reset. This is a recovery
workaround, not proof that the initiating USB defect has been fixed. Keep any
working `dwc2` setup separately managed and unchanged during initial testing.

### Remove the conflicting legacy reboot watcher

`ttyerror_reboot.sh` is deprecated: it can match historical lines and reboot before
gentle recovery gets a chance. Inspect how it was launched, then disable **that
specific** service/cron job/startup command. No standard service name is assumed:

```bash
pgrep -af '[t]tyerror_reboot.sh'
sudo grep -R -n 'ttyerror_reboot' /etc/systemd/system /etc/cron.d /etc/rc.local
crontab -l
sudo crontab -l
```

Some paths or crontabs may not exist. An already-running shell pipeline can have
child processes; stop its actual parent service/launcher and verify it is gone.
Do not run the old watcher alongside the new logger recovery.

### Optional adapter-only reset permissions

Start with gentle recovery alone. Test whether it restores recording during an
actual stall before enabling this fallback. Software USB reset is not a power
cycle and may not recover every adapter fault. The helper never resets a hub or
the Pi USB controller, which also carries Ethernet on Pi 3B+.

For reset, set `USB_RESET_ENABLED=true` and the exact `USB_VENDOR_ID`,
`USB_PRODUCT_ID` (four hex digits without `0x`), and `USB_SERIAL_NUMBER` in `.env`.
The helper requires one unique non-hub match, verifies the opened device, and
re-resolves bus/device numbers each time. Failed resets also consume the cooldown.
An unmatched/ambiguous target or permission denial leaves gentle retries active.

Grant access only to that physical adapter. **This grants raw USB access to the
adapter, not just reset permission.** Use a maintenance window and local recovery
access; never grant global `/dev/bus/usb` permissions or passwordless sudo.

1. Inspect `lsusb`, `sudo lsusb -v -d VVVV:PPPP`, and
   `udevadm info --attribute-walk --name=/dev/ttyUSB0` for the intended adapter.
   Replace placeholder IDs/port with the selected device; do not copy another
   adapter's serial number. Devices without a unique USB serial are not supported
   by this optional reset path.
2. Create a dedicated group if it does not already exist:
   `sudo groupadd --system lyo-usb-reset`.
3. As administrator, create `/etc/udev/rules.d/99-lyo-usb-reset.rules` with one
   rule, replacing **all** three placeholders with the same identity as `.env`:

   ```udev
   SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="VVVV", ATTR{idProduct}=="PPPP", ATTR{serial}=="SERIAL", GROUP="lyo-usb-reset", MODE="0660"
   ```

4. Change the logger service to `SupplementaryGroups=dialout lyo-usb-reset`.
   Keep `User` unprivileged and `NoNewPrivileges=true`. There is no root helper
   installed from this user-writable checkout.
5. Reload udev rules with `sudo udevadm control --reload-rules`. During maintenance,
   unplug/replug **only the selected adapter** so its rule applies, then recheck
   its current node with `lsusb` and `ls -l /dev/bus/usb/BBB/DDD`.
6. Reload systemd and restart the logger. Inspect
   `systemctl show labconco_log.service --property=SupplementaryGroups` and the
   journal. No installation step automatically issues a USB reset.

Rollback: set `USB_RESET_ENABLED=false`, restart the logger, remove the optional
group from that service, and remove only the udev rule you created. Reload rules;
existing device permissions may persist until the adapter is re-enumerated.
Do not remove unrelated rules or groups used by other applications.

## Optional Pi hardware watchdog

This is a **different watchdog** from the logger's inactivity check. systemd PID 1
feeds `/dev/watchdog0`; if those pings cease, hardware can abruptly reboot the Pi.
It does **not** necessarily detect a stuck logger, stalled USB, unavailable Wi-Fi,
or every kernel hang. PID 1 can remain responsive during all of those. Service
`WatchdogSec=` also needs an application notification heartbeat; this logger does
not implement that protocol, so do not add that service setting.

Nothing in this project enables a hardware watchdog automatically. It can cause
data loss, interrupted logging, or reboot loops. Back up configuration, arrange
physical access, and enable it only during maintenance. Do not run a separate
`watchdog` daemon alongside systemd's device ownership.

### Inspect without arming the device

```bash
ls -l /dev/watchdog*
cat /sys/class/watchdog/watchdog0/identity
cat /sys/class/watchdog/watchdog0/state
cat /sys/class/watchdog/watchdog0/timeout
cat /sys/class/watchdog/watchdog0/nowayout
systemctl show --property=RuntimeWatchdogUSec
systemd-analyze cat-config systemd/system.conf
```

Missing paths mean availability must be investigated first. **Do not `cat`,
`echo` to, or casually open `/dev/watchdog*` itself**: opening it can arm the timer.
Inspect sysfs and existing system configuration/ownership instead.

### Configure explicitly (Pi 3B+, Bookworm)

1. If hardware support is absent, inspect `/boot/firmware/config.txt`. Enable
   `dtparam=watchdog=on` if needed, preserving your existing `dwc2` and all other
   settings. The device-tree default can already be on; device presence does not
   mean PID 1 runtime supervision is enabled.
2. Back up any existing watchdog configuration. Create
   `/etc/systemd/system.conf.d/90-lyo-watchdog.conf` as administrator, preserving
   unrelated configuration:

   ```ini
   [Manager]
   WatchdogDevice=/dev/watchdog0
   RuntimeWatchdogSec=10s
   ```

   Create the directory first if necessary. This is a **manager** drop-in, not a
   service unit or `.env` setting. Ten seconds fits the Pi 3's approximately
   15-second physical timer; actual timeout selection depends on kernel/hardware.
3. Activate with a planned maintenance reboot, not by killing or stopping a
   running watchdog owner. Afterward repeat the read-only checks above and inspect
   `sudo journalctl -b --no-pager --grep='[Ww]atchdog'`. Confirm the actual timeout
   and active state; configuration text alone is not proof of operation.

Rollback: change this drop-in to `RuntimeWatchdogSec=off`, review other drop-ins
and watchdog owners for overrides, then use a planned maintenance reboot with
local access. An already-armed timer may remain active until properly disarmed;
`nowayout` can prevent runtime disarming. Removing a file alone is not a guarantee
of immediate safety. Do not stop its keeper or open a second owner casually.

Do **not** test by killing PID 1, freezing the kernel, exhausting resources, or
deliberately withholding pings on a production Pi. A real watchdog recovery test
requires a separate supervised maintenance procedure and is not part of this
project's automated verification.

References: [systemd 252 manager watchdog options](https://github.com/systemd/systemd/blob/v252/man/systemd-system.conf.xml)
and [Pi 6.12 BCM2835 driver](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/drivers/watchdog/bcm2835_wdt.c).

## Email, uploads, and raw-data retention

**Alarms:** set `ALERTS_ENABLED=true`, choose `PRESSURE_THRESHOLD` (µbar), and
configure the existing `GMAIL_USER`,
`GMAIL_APP_PASSWORD`, and `ALERT_RECIPIENT` keys. `SMTP_HOST`/`SMTP_PORT` default to
Gmail SSL. Plot titles and email labels use `INSTRUMENT_NAME`; credentials stay
local. Delivery failures do not set a delivered-alarm flag. Keep alert state on
persistent storage so a plotter restart does not resend an existing alarm.

**Direct stoppering tray:** a fresh latest `VAC` reading strictly above
`PRESSURE_THRESHOLD` triggers a `Shelf pressure` email in every state, including
`STNDBY`. No collector/system temperature or duration condition is applied;
`TEMPERATURE_THRESHOLD` may remain blank and `ALERT_DURATION_HOURS` is ignored.
One email is delivered per high-pressure episode. A valid pressure at or below
the threshold clears the delivered flag and re-arms the alarm. Failed delivery
leaves the alarm eligible for retry. A retained flag from the other report profile
cannot suppress an alarm after switching between direct and base/combined modes.
Unreadable/corrupt state logs a warning and attempts the current high-pressure
alert rather than suppressing it. Fix state-file permissions promptly: broken
state persistence can cause repeated delivery attempts.

Pressure decisions run on changed data at plot polls (`PLOT_INTERVAL_SECONDS`,
default 60 seconds), not directly in the serial reader. Set this to 10 seconds if
faster checks are needed. Detection can take a report interval plus a plot interval
(about 70 seconds at defaults), plus rendering/email time; this is not a hard
real-time guarantee. Each update reloads the newest record, so a longer plot
interval does not by itself make that record stale.
Only the latest record is considered; old high-pressure segments are not replayed.
The source file's date and record timestamp must be current: readings aged
`SERIAL_IDLE_TIMEOUT_SECONDS` (default 120 seconds) or more, future-dated readings, and
invalid/missing pressures are unavailable. They neither send nor clear an alarm.
Keep the Pi's clock correct. `--no-alerts` continues to suppress all alarm effects.

At the default INFO logging level, unavailable checks produce one WARNING per
unavailable episode and an INFO message when checks resume. In direct-tray mode,
a file that stops changing also produces this warning after its idle window; static input is never
replayed as a new alarm. Check the journal for these messages, not just the
delivered-alarm flag or service status.

**Base and combined modes:** also set `TEMPERATURE_THRESHOLD` (°C). The existing
base-derived Vacuum/Temperature/Defrosting classification is retained.
**Its legacy duration helper can evaluate a short history before
`ALERT_DURATION_HOURS` has elapsed; that setting is not a guaranteed minimum alarm
delay.** Review/qualify that policy before relying on alerts. This release does
not redesign it. With missing base measurements, checks are unavailable, not
healthy; an existing flag is not cleared. Collector-temperature thresholds are
never substituted onto shelf temperatures.

**Uploads:** install/configure rclone separately under the service account. Set
`UPLOAD_ENABLED=true`, `RCLONE_DESTINATION=remote:path`, and optionally
`RCLONE_SOURCE`/`RCLONE_EXECUTABLE`. The destination is a remote specification, not
a local path. Rclone uses `copy`, not `sync`, and the uploader never deletes
original files or prunes the remote destination.
If PNGs are in a separate directory, explicitly choose an upload source that
contains them. Authentication remains in rclone's protected config.

Each run first makes an independent temporary copy of the source tree, then
uploads that unchanged snapshot. Live log appends or atomic PNG replacements
cannot change files while rclone is uploading them. Each file is captured
separately, not as one simultaneous filesystem-wide snapshot; appends after a
file's initial captured size wait for the next upload. Unfinished `.plot-*` files
and symlinks are excluded. File modification times are preserved so unchanged
history is not uploaded again just because a new snapshot was made.

The snapshot is staged in a private `.lyo-upload-*` directory **beside** the source,
not inside it or in the Pi's potentially RAM-backed `/tmp`. The service account
needs write access to the source's parent and free disk space for one complete
copy of the source tree. Staging failure prevents upload and reports failure;
normal completion and handled failures remove staging. A power loss or forced
termination can leave a staging directory behind; inspect it before removing it.

Before switching the service, check source size and free space on the staging
filesystem (replace these example paths):

```bash
du -sh /path/to/data
df -h /path/to
find /path/to -maxdepth 1 -type d -name '.lyo-upload-*' -print
```

Leave headroom for new records as well as the snapshot. Avoid running a manual
uploader alongside the timer: two independent processes need two snapshots.

For multiple destinations, keep the primary in `RCLONE_DESTINATION` and append
repeatable arguments to the service's `ExecStart`, for example:

```text
/path/to/.venv/bin/python -u /path/to/rclone_lyo.py --additional-destination second:path
```

All destinations receive the same snapshot. A failed destination does not prevent
attempting the others, but any destination failure makes the overall service run
fail. When replacing an existing uploader, preserve all intended destination
paths, remove the old command from the service with a blank `ExecStart=`, and
verify there is only one effective command. Do not run the old retention-bearing
uploader alongside this one.

Adapt/install `rclone_lyo.service` and `rclone_lyo.timer`, validate the unit, then
enable the timer only when ready. It runs hourly. Inspect with:

```bash
systemctl list-timers --all rclone_lyo.timer
sudo journalctl -u rclone_lyo.service --since "1 day ago" --no-pager
```

**Retention:** `DATA_RETENTION_DAYS=0` keeps all local logs and PNGs. A positive
value enables startup cleanup by `labconco_log.py` alone (for example, `60`). It
deletes files whose filename date is **strictly older** than today minus that many
days; the exact cutoff date is retained. Cleanup is not a daily timer: changing
the setting takes effect the next time the logger starts.

Cleanup touches only valid dated `YYMMDD.txt` and `YYMMDD.png` regular files
directly in `LOG_DIRECTORY`. If `PNG_DIRECTORY` is separate, it also cleans dated
PNGs there, but not TXT files in that separate directory. A PNG directory that
does not exist yet is skipped. Symlinks, nested directories, invalid dates, and
unrelated files are untouched. Remote copies are not deleted. Back up data before
enabling deletion or restarting the logger with a positive retention value.
For migration, start with `DATA_RETENTION_DAYS=0`, verify the new logger/uploader,
then choose a positive value only after backing up and reviewing the dated PNG
backlog. Directory-access and deletion failures log retention warnings and do
not prevent serial recording; actual recording/storage errors still fail loudly.

## Development verification

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests use the real supplied record formats, actual headless PNG rendering,
temporary data files, fake serial connections/clocks, and mocked SMTP/rclone/USB.
An isolated POSIX pseudo-terminal also exercises the real pyserial API without
using a physical serial port. A private fake-hardware child verifies prompt
SIGTERM shutdown during retry backoff; no running service or PID 1 is signaled.
No test opens a real serial port, issues a USB reset, arms a watchdog, uploads,
sends mail, or deletes real instrument data. Hardware recovery and watchdog
behavior must still be validated separately on the target Pis.

For a supervised Pi test, first confirm continued raw records and correct plots
with optional actions disabled. During maintenance, disconnecting the RS-232 data
lead while leaving USB present tests silence handling; unplug/replugging USB tests
disappearance/re-enumeration. Neither faithfully reproduces a `-32` endpoint
stall. Do not induce undervoltage or overheating to provoke one.

For the cable alternative and original wiring diagram, see
[Cable wiring](../README.md#cable-wiring).
