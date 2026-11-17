# Verification: configurable logger and recovery

Branch: `feature/configurable-logger-recovery`.

Implementation commit `67235101894ca8a951552e3900a311db7aabf547` was pushed to
`origin/feature/configurable-logger-recovery` and its remote SHA was verified with
`git ls-remote`. Subsequent publication bookkeeping changes documentation only.

## Automated results

The final implementation passes **62 tests** in each isolated Linux x86-64
environment below. These are software checks, not Raspberry Pi hardware tests.

| Python | Matplotlib | NumPy | python-dotenv | Result |
| --- | --- | --- | --- | --- |
| 3.13.5 | 3.11.2 | 2.5.5 | 1.2.4 | 62 passed |
| 3.11.18 | 3.6.3 | 1.26.4 | 1.0.0 | 62 passed |
| 3.10.22 | 3.10.9 | 2.2.6 | 1.2.4 | 62 passed |

All use pyserial 3.5. The suite also passed under Python 3.11 with newer
Matplotlib before the final review corrections; the table records the final
tested configurations. Matplotlib 3.6.3 with the installed newer pyparsing emits
upstream deprecation warnings but all tests pass. Expected simulated failure
cases emit recovery warnings in test output.

Commands:

```bash
<environment>/bin/python -m unittest discover -s tests -q
<environment>/bin/python -m pip check
.venv/bin/python -m compileall -q lyo_config.py generate_png.py generate_png_shelf.py labconco_log.py usb_recovery.py send_alert_email.py rclone_lyo.py tests
git diff --check
```

`pip check` reports no broken requirements in all three environments. Compilation
and whitespace checks pass. The suite also parses shipped source using Python
3.10 syntax rules and checks ignore behavior with Git, not source-text matching.

The three example service templates and upload timer pass `systemd-analyze verify
--man=no` after substituting the actual local interpreter/project path and
existing test account into temporary copies. No unit was installed or started.

## Coverage and side effects

- All four supplied records, explicit mode selection, compact keys, sentinels,
  partial/empty sibling blocks, and malformed input.
- Actual headless PNG rendering for each mode, separate base/shelf channels,
  missing-data gaps and labels, and CLI invocation from an unrelated directory.
- Safe `--once --no-alerts` previews without credentials or alert-state writes.
- Fake serial clocks exercise idle detection, failures, bounded reconnects,
  reset thresholds/cooldowns, successful data confirmation, and midnight outages.
- A private pseudo-terminal tests real pyserial parameters and durable recording;
  it does not connect to a physical instrument.
- A private fake-hardware child confirms SIGTERM exits promptly during a
  30-second retry wait. No service, PID 1, or watchdog keeper was signaled.
- USB identity changes, hub/ambiguous-target rejection, permission/ioctl errors,
  and disabled reset paths use mocked usbfs operations and temporary sysfs data.
- Mail and rclone tests mock the external operations; no messages or uploads.
- Cleanup tests use only temporary files and verify disabled cleanup and symlink
  safety. No real instrument data was read, modified, or deleted.
- `.env.example` validates for all operations with optional actions disabled.
  Local env, runtime data, virtualenvs, and bytecode are not tracked.

## Review disposition

The independent review's actionable findings were reproduced and corrected with
test-first changes: blank booleans now use their defaults, and an empty or
field-less combined block no longer discards valid sibling measurements. A safe
preview flag addresses the one-shot-email concern. Reopen counting is intentional:
the original fault is not a failed reopen; tests and docs now state that contract.
The possible retry-wait shutdown delay was tested and did not reproduce.

No unsupported firmware fields, undocumented negative sentinel, or hypothetical
state vocabulary was invented. Parsers remain scoped to the observed formats.
The suggested alphanumeric token-boundary guard was not applied because the
supported format deliberately places keys immediately after numeric values.
Raw serial payloads remain available for future parser extensions.

## Limits and Pi bring-up

No ARM/Pi hardware, endpoint stall, adapter reset, hardware watchdog, real SMTP,
or real rclone destination was exercised. A successful close/reopen or USB reset
on an actual `-32` stall still requires supervised Pi testing. The root trigger
of the original stall is not claimed fixed.

Start with gentle recovery alone. Preserve local source edits and `.env` before
switching branches, select the correct reporting mode, set the existing data
directory and stable serial path, and match the real transmission interval.
Use the README's no-alert preview before restarting the plotter. Disable the old
reboot watcher so it cannot preempt recovery. Leave USB reset, mail, uploads,
deletion, and hardware watchdog activation opt-in until individually checked.

The existing short-history alarm-duration behavior is deliberately preserved and
documented; it is not a guaranteed minimum alarm delay. Bulk-tray hardware remains
out of scope. No changes were installed on either Pi, and master is not merged or
pushed by the feature-branch handoff.

## 2026-11-17: direct-tray NUL framing regression

Pi diagnostics revealed a literal NUL byte between the timestamp separator and
the direct-tray `:<...>` frame. That byte was invisible in the original pasted
examples. The previous strict frame match rejected these otherwise valid records.

Three regression tests were observed failing before the fix: the five exact
byte-level samples, padding/embedded-corruption boundaries, and a real one-shot
PNG render. The parser now removes only leading NUL/space/tab padding before
dispatch. It does not remove NULs from measurement values or rewrite raw logs.

All **65 tests pass** on Python 3.10.22, 3.11.18, and 3.13.5 with the dependency
configurations listed above. The exact supplied samples render without rejected
records, and their input bytes remain unchanged. No hardware operations or alarm
policy changes are part of this fix.

## 2026-11-17: direct-tray pressure alarm

The user subsequently approved a direct pressure alarm in all states, including
`STNDBY`. This is a separate extension to the original base-only alarm scope.

The latest valid shelf `VAC` strictly above `PRESSURE_THRESHOLD` now triggers one
`Shelf pressure` email per excursion. No temperature or legacy duration condition
applies in direct mode. A fresh reading at or below threshold re-arms the alarm.
Missing, invalid, stale, future, or undated readings cannot send or clear it;
freshness uses the dated source file, its latest record timestamp, and the
existing serial idle-timeout window. Checks occur at the plot interval, not on
every serial byte. Existing base/combined alarm classification is unchanged.

New tests were observed failing before implementation. All **88 tests pass** on
Python 3.10.22, 3.11.18, and 3.13.5, with no actual mail or hardware operations.
Coverage includes threshold equality, pressure `999` versus missing temperature
`999`, standby/program states, no delay, no temperature requirement, old base-flag
migration, duplicate suppression and re-arming, failed delivery, and source-date
propagation through the file-processing path.

A separate end-to-end smoke check also rendered real PNGs and used the actual
email-message builder with a fake SMTP server: high pressure delivered once,
continued high pressure did not duplicate, pressure equal to threshold re-armed,
and a new excursion delivered again. No network connection was made.

Review follow-ups add deduplicated WARNING/INFO transitions for unavailable and
recovered alarm inputs, including a static input file. Corrupt/unreadable or
concurrently removed state cannot silently suppress a current alert. Known
profile flags migrate in both directions; legacy suppression among base alarm
categories remains unchanged. These fixes were reproduced with failing tests
before implementation. Stale file processing is also tested end-to-end.

A proposed review restriction requiring the idle window to exceed the plot
interval was not applied: every changed-file poll reloads the newest row, not
the row from the preceding poll. Tests verify that a 60-second plot interval,
10-second report cadence, and 30-second freshness window are accepted, and that
a latest reading five seconds old remains eligible. Poll interval affects
detection latency; it does not inherently determine record age.

The focused read-only review and follow-up review found no remaining blockers.
The final pipeline smoke also exercised a genuinely invalid UTF-8 state file,
real PNG rendering and email-message construction with fake SMTP, and switching
from direct-tray to base alarms; no network connection was made.
