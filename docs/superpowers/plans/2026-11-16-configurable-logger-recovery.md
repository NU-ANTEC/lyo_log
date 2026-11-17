# Configurable Logger and Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The user authorized inline execution, completion, and pushing the new branch without another planning approval.

**Goal:** Ship configurable parsing/plotting for three observed report modes, serial recovery, and safe Pi deployment instructions on a test branch.

**Architecture:** `lyo_config.py` owns typed settings; `generate_png.py` owns all three parsers and rendering. The logger owns its serial lifecycle and delegates optional adapter-only reset to `usb_recovery.py`. Email and rclone remain separate guarded entry points.

**Tech Stack:** Python 3.10+, standard-library unittest, python-dotenv, Matplotlib, pyserial, Linux sysfs/usbfs, systemd.

**Spec:** `docs/superpowers/specs/2026-11-16-configurable-labconco-design.md`

## Global Constraints

- Modes: `freezone`, `stoppering_combined`, `stoppering_direct`; default baud 2400, fixed 8N1. No bulk-tray support.
- Pressure is µbar and temperature °C. Missing telemetry is never zero or a healthy alarm result.
- One plotting script with all parser functions. A shelf compatibility entry point must not select a mode implicitly.
- Existing process environment variables take precedence. Relative paths resolve against the project directory.
- Keep the raw daily `YYMMDD.txt` / `HHMMSS payload` format, immediate flush/fsync, and quiet per-record output.
- Alerts, uploads, deletion, and USB reset default disabled; gentle serial recovery defaults enabled.
- No real serial, SMTP, rclone, USB ioctl, hardware watchdog, or real-data cleanup in tests.
- No automatic reboot for serial silence, controller reset, or privilege escalation. Do not change a running Pi.
- Run on `feature/configurable-logger-recovery`; push that branch, never master.

## File map

- Create `lyo_config.py`: frozen Settings dataclass, ConfigError, `load_settings(env_file=None, environ=None, project_dir=None, operation="plot")`, logging setup.
- Modify `generate_png.py`: Record/ParseError, `parse_record(line, style)`, three named parsers, `parse_log_file(path, style)`, `build_figure(records, settings, day)`, `render_plot`, legacy alert characterization, `evaluate_alerts`, guarded monitor.
- Modify `generate_png_shelf.py`: compatibility main only.
- Create `usb_recovery.py`: identity-checked sysfs lookup and `reset_adapter(settings, ...)` using usbfs; no sudo/shell.
- Modify `labconco_log.py`: `record_stream(settings, ..., stop=None)` with injectable serial, clocks, waits, reset; narrow `purge_old_logs`; guarded main.
- Modify `send_alert_email.py`: testable `send_alert(alert_type, settings)` and CLI.
- Modify `rclone_lyo.py`: `upload(settings)` with argument-list execution and CLI.
- Create `tests/test_config.py`, `tests/test_parsers.py`, `tests/test_plotting.py`, `tests/test_logger.py`, `tests/test_usb_recovery.py`, `tests/test_integrations.py`, fixtures/helpers.
- Create `.env.example`, `requirements.txt`; update `.gitignore`, README, example service units, legacy watchdog warning.

## Task 1: Configuration

- [x] Add tests for location/precedence, path resolution, all three modes, per-operation validation, invalid booleans/numbers/ranges, and quiet safe defaults. Core assertion:
  ```python
  settings = load_settings(environ={"LABCONCO_STYLE": "stoppering_direct"}, project_dir=root)
  self.assertEqual(settings.serial_baudrate, 2400)
  self.assertEqual(settings.log_directory, root / "data")
  self.assertFalse(settings.usb_reset_enabled)
  ```
- [x] Run `.venv/bin/python -m unittest tests.test_config -v`; confirm missing configuration implementation is the failure.
- [x] Implement the typed loader with explicit parsing helpers and operation-specific optional credentials. Add dependencies/example/ignore patterns alongside the consuming feature.
- [x] Run configuration tests; commit only the task's files.

## Task 2: Parsers

- [x] Add the four supplied records as identifier-free fixtures. Assert base pressure 470 differs from shelf pressure 570, direct pressure 24 has no collector, standby/INDF remain metadata, and 999 temperatures become unavailable.
  ```python
  record = parse_record(COMBINED, "stoppering_combined")
  self.assertEqual(record.measurements["base_pressure"], 470)
  self.assertEqual(record.measurements["shelf_pressure"], 570)
  ```
- [x] Test wrong mode, partial blocks, invalid timestamps, compact field boundaries, missing channels, and malformed frames.
- [x] Run `.venv/bin/python -m unittest tests.test_parsers -v`; confirm unavailable parser APIs, without executing the old monitor.
- [x] Replace the top-level script with guarded parser/main boundaries; use scoped key extraction rather than positional splits. Record fields: timestamp, measurements dict, metadata dict.
- [x] Run parser/config tests and commit.

## Task 3: Plotting and alerts

- [x] Add headless plot tests that inspect axes/line data, pressure units, direct-mode annotations, NaN gaps, historic base traces, and source date. Render real PNGs into temporary directories.
  ```python
  fig = build_figure(records, settings, date(2026, 11, 16))
  self.assertEqual(fig.axes[0].get_yscale(), "log")
  ```
- [x] Characterize the existing short-history alert helper; test missing-base suppression and no clearing during unavailability. Test delivered flags only follow successful email delivery.
- [x] Run `.venv/bin/python -m unittest tests.test_plotting -v` and observe the missing behavior.
- [x] Implement atomic PNG replacement, mode-dependent traces, aggregated parse diagnostics, daily monitor rollover, and alert integration. Keep helper semantics documented rather than redesigning alarm timing.
- [x] Replace shelf duplicate with the forwarding entry point. Run all tests and commit.

## Task 4: Serial and optional USB recovery

- [x] Add fake-clock/serial tests for one harmless timeout, silence followed by close/reopen, fresh-data confirmation, repeated open errors, capped backoff, optional reset threshold/cooldown, decode/storage failures, shutdown, and midnight rollover. Real file writes use temporary directories.
  ```python
  record_stream(settings, serial_factory=factory, clock=clock,
                wait=clock.wait, now=clock.now, stop=stop, reset=reset)
  self.assertIn("120001 payload", daily_file.read_text())
  ```
- [x] Add sysfs fixtures and mocked usbfs tests: disabled reset, exact identity, unique match, hub rejection, renumbering/identity change, access failure, and expected ioctl target.
- [x] Run both modules; confirm no real serial/ioctl is accessed and the new APIs fail before implementation.
- [x] Implement the logger state machine, safe opt-in cleanup, and isolated USB helper. Keep reset cooldown across brief successful reconnections; no counter reset solely on opening a port.
- [x] Run the full suite; commit.

## Task 5: Mail/upload integration and deployment

- [x] Test SMTP messages with generic configured labels, disabled integrations, credential isolation, failed delivery, and safe rclone arguments containing spaces. Test subprocess imports have no external effects.
  ```python
  result = upload(settings)
  self.assertEqual(result, 0)
  self.assertEqual(captured_command[1], "copy")
  ```
- [x] Run `.venv/bin/python -m unittest tests.test_integrations -v`; confirm the old unguarded code does not satisfy the new contract.
- [x] Implement guarded mail/upload entry points with shared settings; remove duplicate uploader cleanup. Use SMTP_SSL and `subprocess.run([...], check=True)`.
- [x] Document configuration migration, optional exact-device udev permissions, service restart/rate limits, and separate hardware watchdog instructions with safe rollback. Deprecate the reboot-on-error script without enabling replacements automatically.
- [x] Validate example systemd units without starting them; run all tests and commit.

## Task 6: Review, verification, and push

- [x] Review every spec section against implementation and tests; fix gaps with test-first changes.
- [x] Run `.venv/bin/python -m unittest discover -s tests -v`, `.venv/bin/python -m compileall -q` on shipped modules, `.venv/bin/python -m pip check`, `git diff --check`, and behavioral ignore checks.
- [x] Run fixture-only PNG smoke tests in a temporary directory and CLI failure-path checks with no real operations enabled. Check Python 3.10 syntax compatibility and available systemd verification tools.
- [x] Record exact results and hardware limits in the final handoff. Mark task checkboxes complete as evidence is obtained.
- [ ] Commit final reviewed changes, verify no secrets/runtime artifacts are tracked, push with `git push -u origin feature/configurable-logger-recovery`, and verify the remote branch SHA.

## Plan review

Coverage: configuration and privacy (Task 1); explicit modes and real fixtures (2);
plots/legacy alarms (3); logger/retention/USB recovery (4); external integrations,
services, README/watchdog (5); complete regression/side-effect checks and push (6).
Hardware recovery is deliberately not claimed by mocked or fixture-only tests.

## Review follow-up

Independent local-worker review covered all implementation modules and deployment
documents. Follow-up changes have regression tests: blank booleans use defaults,
valid combined blocks survive an empty sibling, and `--no-alerts` allows previews
without credentials or alarm-state changes. Tests document the initial-fault vs.
failed-reopen count, verify reset cooldown across brief recoveries, and prove that
SIGTERM interrupts a 30-second retry wait. The reviewer observed test additions
during its read-only pass; all are committed in the final handoff, not foreign
untracked work. See the verification report for runtime matrices and limitations.
