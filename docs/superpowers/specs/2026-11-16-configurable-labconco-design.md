# Configurable Labconco logging and plotting

Status: conversation design approved; written specification pending user review.

## Goal and scope

Run the same version-controlled software on different instruments without editing
Python source. Select the serial format and deployment settings in an untracked
`.env`. Use one plotting script with parser functions for all supported formats.
Keep recording, plotting, email delivery, and uploading as separate operations.

This change covers `labconco_log.py`, `generate_png.py`, the compatibility entry
point `generate_png_shelf.py`, `send_alert_email.py`, and `rclone_lyo.py`. Add a
shared `lyo_config.py`, `.env.example`, dependency instructions, tests, and migration
documentation. Update example service files where needed, without modifying any
running Pi or enabling services automatically.

USB recovery, controller configuration, journal retention, instrument control,
new operating-state alarm policies, and web interfaces are out of scope. Bulk
Tray Dryers are excluded because no hardware is available for validation; add no
bulk parser, configuration mode, plotting layout, or sample-data test suite.

## References and observed records

The existing `generate_png_shelf.py` is the reference for combined base/shelf
measurements and plotting labels, not for its string-splitting implementation.
It currently requires base fields and silently skips unsupported records.

Manufacturer references, using the printed page numbers:

- [FreeZone 6, 12 and 18 Liter manual, Chapter 6, pp. 33–34](https://www.labconco.com/download/freezone-6-12-and-18-liter-freeze-dry-systems-ma/2HAAkjkFQE7FvPyN6HxcDw).
- [Stoppering Tray Dryers manual, Chapter 6, pp. 30–31](https://www.labconco.com/download/freezone-stoppering-tray-dryers-manual/7bTeYHdi1bzTDXRawrIQyJ).

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

Keep the implementation dependency-light: existing python-dotenv, Matplotlib, and
pyserial plus the standard library. Do not add a daemon framework or database.
