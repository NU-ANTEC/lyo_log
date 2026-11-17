# Configurable Labconco logging and plotting

Status: approved for implementation on a new branch; planning approval waived by
the user. Hardware validation will be performed separately on the Pis.

## Goal and scope

Run the same version-controlled software on different instruments without editing
Python source. Select the serial format and deployment settings in an untracked
`.env`. Use one plotting script with parser functions for all supported formats.
Keep recording, plotting, email delivery, and uploading as separate operations.

This change covers `labconco_log.py`, `generate_png.py`, the compatibility entry
point `generate_png_shelf.py`, `send_alert_email.py`, and `rclone_lyo.py`. Add a
shared `lyo_config.py`, a narrowly scoped `usb_recovery.py`, `.env.example`,
dependency instructions, tests, and migration documentation. Add serial reconnect
recovery, opt-in adapter-only USB reset, and README instructions for both logger
supervision and an optional Pi hardware watchdog. Update example service files
where needed, without modifying any running Pi or enabling services automatically.

Automatic Pi reboot on serial silence, whole-controller resets, controller-driver
configuration changes, journal retention, instrument control, new operating-state
alarm policies, and web interfaces are out of scope. Bulk Tray Dryers are excluded
because no hardware is available for validation; add no
bulk parser, configuration mode, plotting layout, or sample-data test suite.

## References and observed records

The existing `generate_png_shelf.py` is the reference for combined base/shelf
measurements and plotting labels, not for its string-splitting implementation.
It currently requires base fields and silently skips unsupported records.

Protocol and platform references; manual pages use printed page numbers:

- [FreeZone 6, 12 and 18 Liter manual, Chapter 6, pp. 33–34](https://www.labconco.com/download/freezone-6-12-and-18-liter-freeze-dry-systems-ma/2HAAkjkFQE7FvPyN6HxcDw).
- [Stoppering Tray Dryers manual, Chapter 6, pp. 30–31](https://www.labconco.com/download/freezone-stoppering-tray-dryers-manual/7bTeYHdi1bzTDXRawrIQyJ).
- [systemd 252 hardware-watchdog configuration](https://github.com/systemd/systemd/blob/v252/man/systemd-system.conf.xml), matching the Bookworm systemd generation.
- [Raspberry Pi 6.12 BCM2835 watchdog driver](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/drivers/watchdog/bcm2835_wdt.c).

User-supplied fixtures, with no deployment identifiers:

```text
134341  :<PROG=1 SEG=2H TRM=INDF SYS=+16 PRB1=+18 PRB2=+18 PRB3=+18 VAC=  24>
134351  :<STNDBY SEG=   TRM=9999 SYS=+16 PRB1=+18 PRB2=+18 PRB3=+18 VAC=  24>
000010  B<T=-58V=470  SF=999C=999PG=0>TD<PR=0S=  TR=9999ST=+23P1=+24P2=+23P3=+23V= 570>
152808  B<T=-56V=90   SF=999C=999PG=0>
```

The user confirmed that direct shelf `VAC` values are microbar. All supported
pressure measurements use µbar; temperatures use °C. Do not infer conversions
from front-panel display settings.

Combined base-plus-stoppering output and direct stoppering-only output are two
connection/reporting modes of the same stoppering system, not different instrument
models. The direct connection bypasses the currently faulty base-to-tray
communication link and does not carry base telemetry. All three selected modes
use the existing 2400-baud configuration and the user's actual sample records.

## Application boundaries

- `lyo_config.py` loads and validates configuration without opening serial ports,
  deleting files, rendering plots, sending mail, or starting subprocesses.
- `labconco_log.py` records the raw payload with the existing `HHMMSS` prefix in
  daily `YYMMDD.txt` files. Keep immediate flush/fsync and quiet per-record output.
  Own its serial connection and recover without spawning a second reader.
- `usb_recovery.py` resolves an explicitly identified USB adapter and optionally
  issues Linux `USBDEVFS_RESET`. It never resets a hub/controller, detaches the
  entire driver module, runs a shell, invokes sudo, or reboots the Pi.
- `generate_png.py` contains the parser functions, shared measurement model,
  plotting, and the existing alert evaluation integration. A guarded `main()`
  runs the monitor; importing the module has no external side effects.
- `generate_png_shelf.py` becomes a thin compatibility entry point to the same
  main function. It has no parser or plot implementation and does not override
  the configured style. Document its deprecation and the service migration.
- `send_alert_email.py` reads shared settings and sends mail only when called.
- `rclone_lyo.py` performs a configured copy, separately from plotting. Use a
  subprocess argument list, not a shell command assembled from `.env` values.
- Tests import functions without starting infinite loops, SMTP, uploads, serial
  communication, or cleanup. Add main guards to the executable scripts.

## Configuration contract

Load `.env` beside `lyo_config.py`, not by searching the current working directory
or its ancestors. Existing process environment variables take precedence. Resolve
relative filesystem paths against the project directory; support absolute paths
and user-home expansion. Treat the rclone destination as a remote specification,
not a local filesystem path. Read settings once at startup; changes require a
service restart.

Use these public settings, documented with units and defaults in `.env.example`:

| Group | Settings and behavior |
| --- | --- |
| Input mode | `LABCONCO_STYLE=freezone\|stoppering_combined\|stoppering_direct` and generic `INSTRUMENT_NAME` |
| Serial | `SERIAL_PORT`, optional `SERIAL_BAUDRATE`, `SERIAL_TIMEOUT_SECONDS`; fixed 8N1 |
| Serial recovery | `SERIAL_RECOVERY_ENABLED`, `SERIAL_EXPECTED_INTERVAL_SECONDS`, `SERIAL_IDLE_TIMEOUT_SECONDS`, `SERIAL_REOPEN_ATTEMPTS`, `SERIAL_RETRY_INITIAL_SECONDS`, `SERIAL_RETRY_MAX_SECONDS` |
| Optional USB reset | `USB_RESET_ENABLED`, `USB_VENDOR_ID`, `USB_PRODUCT_ID`, `USB_SERIAL_NUMBER`, `USB_RESET_MIN_INTERVAL_SECONDS` |
| Paths | `LOG_DIRECTORY`, `PNG_DIRECTORY`, `ALERT_FLAG_FILE`, `ALERT_LOG_FILE` |
| Plot | `PLOT_INTERVAL_SECONDS`, `PLOT_WIDTH_INCHES`, `PLOT_HEIGHT_INCHES`, `PRESSURE_MIN_UBAR`, `PRESSURE_MAX_UBAR`, `TEMPERATURE_MIN_C`, `TEMPERATURE_MAX_C` |
| Alerts | `ALERTS_ENABLED`, `ALERT_DURATION_HOURS`, `PRESSURE_THRESHOLD`, `TEMPERATURE_THRESHOLD` |
| Mail | Existing `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_RECIPIENT`; add `SMTP_HOST` and `SMTP_PORT` with Gmail-compatible defaults |
| Upload | `UPLOAD_ENABLED`, `RCLONE_EXECUTABLE`, `RCLONE_SOURCE`, `RCLONE_DESTINATION` |
| Retention | `DATA_RETENTION_DAYS`; zero disables deletion |
| Diagnostics | `LOG_LEVEL`, default `INFO`; permit standard Python severity names |

`LABCONCO_STYLE` is required and selects the reporting mode, not just the model
family. A missing or blank baud override uses 2400 for all three modes. An explicit
baud override is allowed. Expected telemetry follows the selected mode; do not add
a separate base-expectation boolean that could contradict it:

| Mode | Serial record | Expected telemetry |
| --- | --- | --- |
| `freezone` | `B<...>` | Base only |
| `stoppering_combined` | `B<...>TD<...>` | Base and stoppering tray |
| `stoppering_direct` | `:<...>` | Stoppering tray only; base absence is intentional |

Operators switch between combined and direct stoppering connections by changing
`LABCONCO_STYLE` and restarting the relevant services, without editing Python.

Default paths are `./data` for logs, the log directory for PNGs,
`./state/alert_active.flag` for alert state, and `./state/alerts.log` for alert
history. The generic instrument name is `Freeze dryer`. Serial defaults to
`/dev/ttyUSB0`, with a note recommending a stable by-id path for deployment.
The plot interval defaults to 60 seconds, serial timeout to one second, plot size
to 10 by 6 inches, pressure limits to 5–5000 µbar, and temperature limits to
-90–40 °C. Make these defaults visible in the example, not deployment-specific
constants in the executable scripts.
Pressure limits must be positive and increasing because pressure uses a log axis.
Temperature limits must be finite and increasing; durations, dimensions, and
intervals must be positive. Baud rate must be a positive integer, retention a
nonnegative integer, and SMTP port an integer from 1 to 65535. Pressure thresholds
must be positive and finite; temperature thresholds must be finite. Reject
unrecognized booleans, styles, and nonfinite numbers with setting-specific errors
that do not print secrets.

Alerts, uploads, and data deletion default to disabled, both in the loader and
the example configuration. Alert duration defaults to 0.25 hours. Thresholds have
no deployment-independent default and remain blank until alerts are enabled.
Require alarm thresholds when alerts are enabled, mail credentials when delivery
is enabled, and an upload destination only when uploads are enabled. Validate
settings per operation: a disabled optional subsystem must not prevent recording
or plotting because its credentials are absent. Retain the existing email
environment variable names for migration.

Serial recovery defaults to enabled. Defaults are a 10-second expected record
interval, 120-second idle timeout, three failed reopen attempts before considering
USB reset, and exponential retry delays capped from one to 30 seconds. The idle
timeout must exceed the configured expected interval; document that instruments
can transmit as slowly as once per 600 seconds and need corresponding settings.
A single one-second read timeout is not a fault. Validate positive durations,
initial delay no greater than maximum delay, and a positive integer attempt count.

USB reset defaults to disabled with blank device identifiers and a 600-second
minimum interval between reset attempts. When explicitly enabled, require a
four-digit hexadecimal vendor ID and product ID plus a nonempty USB serial
number. Identify the physical adapter independently of its changing bus/device
number or tty name. Never fill `.env.example` with an actual adapter identity.

SMTP defaults to SSL at `smtp.gmail.com:465`. Rclone defaults to the executable
name `rclone`, resolved on PATH, and copies from `LOG_DIRECTORY`; its destination
remains blank until explicitly configured. Let operators override the source when
their existing upload layout spans several directories. A separate PNG directory
is not implicitly added to an unrelated rclone source; document that choice.

Credentials and recipient fields in `.env.example` are blank. Include no actual
hostnames, serial numbers, usernames, email addresses, absolute home paths, rclone
remote names, or instrument identifiers. Rclone authentication stays in its own
protected configuration; the project config only selects the copy operation.

Keep `.env` and `.env.*` ignored, with the existing exception for `.env.example`.
Ignore standard runtime data/output/state directories and legacy
`alert_active.flag`/`alert_log.txt` artifacts. Do not broadly ignore all `.txt` or
`.png` files, which could hide fixtures. Never overwrite an existing `.env` or
untrack/delete existing user files automatically. Recommend `.env` permissions
of 0600.

## Parsers and measurement model

Keep all parser functions in `generate_png.py`. Explicit configuration chooses
one reporting-mode parser; do not auto-switch modes or fall back after malformed
input. The two stoppering parsers share channel normalization, but combined and
direct frames remain explicitly selected. In combined mode, retain measurements
from a valid partial base or tray block and report the expected missing block.
Do not interpret an intentionally selected direct connection as a failed combined
connection. Frames from an incompatible mode produce a configuration/format
diagnostic rather than silently changing the selection.

Each parsed record has its time and optional named measurements: collector
temperature, base pressure, shelf/system temperature, shelf pressure, and probes
1–3. Preserve program, segment, state, and remaining-time fields separately from
measurements.

Rules:

- Parse the timestamp prefix as `HHMMSS`. Use the daily filename's date for record
  identity where a full datetime is needed. Never substitute the render time.
- Scope token extraction to its base or shelf block. `B<V>` and `TD<V>` are
  different channels. Recognize key boundaries even when values touch the next
  key, as in `T=-58V=470` and `PR=0S=`.
- Map combined `ST/P1/P2/P3/V` to direct `SYS/PRB1/PRB2/PRB3/VAC` channels, without
  calling a shelf measurement a collector or base measurement.
- Preserve `INDF`, blank segments, `STNDBY`, and numeric-looking remaining-time
  markers as metadata. Do not convert these fields into temperatures.
- Convert documented temperature sentinel `999` to unavailable for the relevant
  sensor fields. Do not treat pressure `999` as missing merely because temperature
  uses that marker.
- Unknown or invalid measurements are unavailable, never zero. Retain other valid
  channels from a recognized partial record. An invalid timestamp or unrecognized
  frame rejects the record with an aggregated diagnostic, not a traceback or a
  silent successful parse.
- Nonpositive pressures cannot appear on the log axis; show a gap, not an invented
  positive floor. Do not include invalid pressures in alarm evaluation.
- Preserve timestamp alignment by keeping missing-channel entries as gaps rather
  than joining the previous valid sample to the next across a missing record.

## Plot behavior

Use a headless Matplotlib backend. Plot pressure on a logarithmic axis in µbar
and temperatures on a linear axis in °C.
Keep the existing daily hour axis and distinguish base and shelf pressure in the
legend. Plot configured title, source date, and available channels.
Legends must not claim that an absent channel has measurements.

For `stoppering_direct`, show shelf pressure, system temperature, and valid
probes. Omit collector/base traces and annotate `Base telemetry unavailable
(direct stoppering connection)`; do not invent base data. For
`stoppering_combined`, absent base or tray telemetry in the latest recognized
record is unexpected and must be distinguished from intentional direct operation.
Keep earlier valid base readings as history, with gaps afterward. If no valid
pressure exists, retain an explicitly labeled unavailable-pressure panel for
the selected mode.

Write `YYMMDD.png` into `PNG_DIRECTORY`; default it to the configured log directory
when omitted to preserve the existing upload layout. Replace completed PNGs
atomically so a concurrent uploader cannot copy a partially rendered file. Close
figures after each render. Recalculate the input filename every poll so midnight
rollover does not depend on process restarts. Missing input files produce a
bounded diagnostic and retry, not a busy loop.

## Serial stall recovery

Recovery handles the confirmed failure mode: USB bulk reads can stop with `-32`
while the process remains alive and pyserial continues returning empty reads.
It is a workaround for the outage, not a claim that the initiating USB defect is
fixed. `dwc2` remains a separately managed host configuration.

Use this sequence:

1. Open the configured port with the configured baud, 8N1, and finite read timeout.
   Resolve the configured path on every attempt; recommend `/dev/serial/by-id/` so
   tty renumbering does not select another adapter.
2. Track time since the last nonempty received payload with `time.monotonic()`.
   Give a newly opened port a full idle-timeout window to produce data. Write and
   durably flush the record before reporting recovery as successful. A successful
   `open()` alone is not recovery and does not clear the failure counter.
3. On a pyserial connection/read error, or prolonged empty reads, close the old
   connection and reopen it with bounded exponential backoff. Use a single owning
   reader; never start overlapping logger instances. Close resources on shutdown.
4. After the configured failed-reopen count, consider a USB reset only if enabled,
   the exact configured identity has one match, and the cooldown has elapsed.
   Close the tty first, reset that adapter, wait using bounded retry delays for
   enumeration, then reopen and reapply serial settings. Re-resolve identity and
   device nodes each time. Count failed reset calls against the cooldown too.
5. If no unique target exists, access is denied, reset is unsupported, or reopening
   still fails, log a bounded diagnostic and continue gentle retries. Never
   escalate automatically to sudo, root execution, controller reset, or Pi reboot.
   Reset counters only after recording resumes; avoid repeated success messages.

Within the running process, the last-reset timestamp remains in force even if
data briefly resumes; successful recovery must not bypass the reset cooldown.

Do not reset USB in response to malformed instrument text, a decoding error, an
SMTP/upload failure, or a data-file write/fsync failure. Report these according
to their own cause. A fatal storage failure exits nonzero for systemd rather
than pretending that the record was saved. When serial recovery is explicitly
disabled, keep ordinary empty-read behavior and let connection errors exit
nonzero instead of silently swallowing them.

The optional reset implementation uses only the standard library and Linux sysfs
plus usbfs. Match vendor, product, and serial; reject root hubs, hubs, unmatched
devices, and ambiguous results. Use current sysfs bus/device numbers only after
matching, then validate the opened device's identity before resetting; do not
reset a different device if enumeration changes. Keep device access and timing
injectable for tests.

Keep the logger unprivileged. README setup for optional USB reset grants raw USB
access only to the identified adapter, using an administrator-installed udev rule
and a dedicated group. Explain that this grants raw access to that adapter, not
merely reset permission. Include generic placeholders, a least-privilege group
assignment, device-permission verification, and rollback. Do not grant broad
access to all USB devices or install a privileged helper from a user-writable
project directory. Permission failure leaves gentle recovery operational.

## Watchdog documentation

Document three separate layers without implying they detect the same faults:

- The logger's data-flow watchdog handles serial silence and connection failures.
- systemd service supervision restarts an exited logger, using restart delay and
  start-rate limits. A running process is not proof of data flow. Do not add a
  service `WatchdogSec=` setting unless a real notification heartbeat is also
  implemented; such heartbeat support is not part of this change.
- The optional Pi hardware watchdog is fed by systemd PID 1. It can reset the
  computer when that heartbeat stops, but a silent serial reader can coexist with
  a healthy PID 1. It is not a replacement for serial recovery or a guarantee
  against every kernel/process hang.

The README's optional Pi 3B+/Bookworm procedure must cover:

1. Inspect watchdog sysfs identity/state and existing watchdog ownership/config.
   Do not probe by reading, writing, or casually opening `/dev/watchdog*`, which
   can arm the timer. Do not run a separate watchdog daemon alongside PID 1.
2. Check hardware availability first. If needed, enable `dtparam=watchdog=on` in
   `/boot/firmware/config.txt`, preserving the existing `dwc2` setting and other
   configuration. The Pi device-tree default may already enable the device;
   its presence is separate from arming it for runtime supervision.
3. Use an opt-in administrator-managed drop-in under
   `/etc/systemd/system.conf.d/` with a `[Manager]` section,
   `WatchdogDevice=/dev/watchdog0`, and `RuntimeWatchdogSec=10s`. The manager setting
   is not a service-unit setting or an application `.env` option. Ten seconds fits
   the Pi 3's roughly 15-second physical watchdog interval; read back the actual
   selected timeout rather than promising every requested timeout is supported.
4. Explain that activation can lead to abrupt automatic reboots and data loss.
   Back up configuration first, arrange local recovery access, and activate only
   in a maintenance window with a planned reboot. Provide read-only checks of
   manager settings, kernel/journal messages, and sysfs timeout/state afterward.
5. Provide rollback to disable this optional manager configuration, accounting
   for other drop-ins, watchdog ownership, and `nowayout` settings. Do not claim
   that deleting one file always immediately disarms an already running timer.
6. Do not include destructive "test" commands that freeze the kernel, kill PID 1,
   starve the machine, or intentionally stop watchdog pings. Hardware recovery
   remains unverified until an operator performs a separate supervised test.

Keep `ttyerror_reboot.sh` as a clearly deprecated legacy artifact, not part of the
recommended setup. Explain how to locate and disable its existing service, cron,
or shell launch before enabling the new recovery, so it cannot reboot the Pi
before gentle recovery runs. Never invent a service name that is not supplied.
No repository command may enable a watchdog, reboot a Pi, or install permissions
automatically.

## Alerts, logging, uploads, and retention

Keep the existing base-derived alert categories and threshold directions for
records with valid base pressure and collector temperature. Never apply the
collector threshold to shelf/system or probe temperatures. For shelf-only and
other records without valid base telemetry, mark those base-derived checks
unavailable rather than healthy.
Unavailable telemetry must not send a recovery notification or clear an existing
alarm flag. Additional shelf-specific alarm policies are a separate change.

The existing short-history duration helper can evaluate conditions before the
configured duration has elapsed. This configuration/parser migration does not
silently redefine that policy; document the limitation and preserve it in
characterization tests pending a separately reviewed alert-timing change.

Use the current Python interpreter and absolute helper path if retaining an email
subprocess. Report delivery failure as failure; write a delivered-alarm flag only
after successful sending. Preserve existing suppression behavior for successful
alerts. Configure instrument names in mail subjects/bodies rather than embedding
deployment-specific names.

Send operational diagnostics to the journal, not raw serial records. Use DEBUG
for routine plot refresh messages and INFO/WARNING/ERROR for startup, transitions,
missing telemetry, malformed-input summaries, and failures. Do not log secrets.

Uploads remain timer-driven `rclone copy`, never `sync`. Disabled uploads exit
without executing rclone. A plotting or upload failure must not stop recording.

Move the duplicated raw-log cleanup responsibility to the logger alone. Retention
is opt-in, restricted to valid `YYMMDD.txt` regular files directly under
`LOG_DIRECTORY`, and never deletes PNGs, unrelated files, or symlink targets.
Document how to explicitly retain the old 60-day policy if desired. No tests or
verification commands may operate on real instrument data.

## Migration and acceptance

Provide `.env.example`, dependency installation instructions, and example services
that all use the same project directory/configuration. Recommend unbuffered Python
for service diagnostics. Do not put real credentials in unit files. Explain that
systemd does not need `EnvironmentFile` because Python loads `.env` itself.

Document configurations for base-only, combined stoppering, and direct
stoppering-only installations. Warn that the old shelf wrapper no longer selects
a profile implicitly. Create and verify `.env` before restarting services; restart
one operation at a time and verify fresh raw data and PNGs. Do not enable email,
uploads, or deletion implicitly during migration.

Acceptance tests use `unittest`, temporary directories, mocks, and Matplotlib's
headless backend:

1. All four supplied records parse to the expected distinct channels and metadata.
   Combined and direct stoppering samples use their explicitly selected modes;
   mismatched modes produce diagnostics rather than auto-selection.
2. Missing sensors, malformed records, compact keys, blanks, and indefinite time
   are covered for the base and both stoppering reporting modes.
3. Each style creates a nonempty PNG. Tests inspect plotted data/labels for correct
   units, source separation, missing-data gaps, and mode-specific annotations.
4. Configuration tests cover dotenv location, environment precedence, path
   resolution, style/baud defaults, invalid values, and optional subsystem isolation.
5. Missing base data never becomes a collector measurement, clears an alarm, or
   triggers collector-derived mail. Delivery failures do not mark alerts delivered.
6. Logger tests retain the raw file format, quiet output, durability calls, and
   date rollover. Retention is disabled by default and constrained when enabled.
7. Upload/email tests mock every external action; importing scripts has no such
   effects. Rclone arguments preserve paths with spaces and contain no shell use.
8. Ignore checks exclude local env/runtime artifacts but allow `.env.example` and
    test fixtures. A fixture-only smoke test renders all styles with network,
    serial, upload, email, and real-data cleanup disabled.
9. A fake serial connection and fake monotonic clock exercise ordinary read
   timeouts, idle detection, open/read exceptions, close-before-reopen, recovery
   only after fresh saved records, retry limits, backoff, shutdown, and rollover
   during an outage. No test sleeps for a real idle period or opens real serial.
10. USB-reset tests mock every sysfs/usbfs operation. Cover disabled reset,
    unique-identity matching, tty renumbering, device-identity changes, permission
    denial, ambiguous/no matches, hub rejection, ioctl failure, cooldown on failed
    attempts, and return to gentle retries. Never issue a real USB ioctl in tests.
11. Review watchdog instructions against the linked systemd 252 and Raspberry Pi
    sources. Validate example service units without starting them. Do not arm or
    test an actual hardware watchdog as part of development verification.

Keep the implementation dependency-light: existing python-dotenv, Matplotlib, and
pyserial plus the standard library. Do not add a daemon framework or database.
