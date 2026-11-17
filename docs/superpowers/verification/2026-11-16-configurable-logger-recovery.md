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
