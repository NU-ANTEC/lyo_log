# Snapshot uploads and logger-owned retention

User-approved extension on `feature/configurable-logger-recovery`, based on
`9cd4223`. Exactly two production scripts change: `labconco_log.py` and
`rclone_lyo.py`; configuration comments, documentation, and tests also change.

## Reproduced issue and behavior

The deployed legacy uploader failed all three rclone retries while today's raw
log grew and the plotted PNG changed. The journal explicitly reported source
size changes and differing MD5 hashes. The deployed legacy script also deleted
raw logs after a hardcoded 60 days, independently of the new logger setting.

The shared uploader now prepares a real temporary copy beside its source tree.
Files are bounded to the initial size of their open descriptor, with modification
times preserved. Symlinks and `.plot-*` intermediates are excluded. No original
data or remote copies are deleted. The same snapshot is uploaded to the primary
configured destination and any repeatable `--additional-destination` arguments.
All destinations are attempted, and any failure returns a nonzero result.

The logger alone applies `DATA_RETENTION_DAYS` at startup. Zero disables cleanup;
positive days delete dated TXT/PNG files strictly older than the cutoff directly
in the log directory, plus dated PNG files in a separate configured PNG directory.
The cutoff date, future files, invalid dates, unrelated names, symlinks and nested
directories are retained. A not-yet-created PNG directory is skipped.

## Verification

- New feature tests were observed failing before implementation: snapshot versus
  live-source behavior, excluded transient plots, copy-failure handling, PNG
  retention and separate PNG-directory cleanup, and multiple CLI destinations.
- All **111 tests pass** on Python 3.10, 3.11, and 3.13.
- New coverage exercises concurrent source appends, atomic PNG replacement during
  snapshot capture, source shrinkage, separate directories, age boundaries,
  retention disabled, preservation of old data by the uploader, both destinations
  sharing a snapshot, failure propagation, and staging cleanup.
- A separate end-to-end smoke ran the actual CLI and actual subprocess invocation
  with an isolated local fake rclone executable. Both destination trees received
  the same original TXT/PNG contents even as live sources changed; original old
  logs remained and staging was removed. No network or serial access occurred.
- A second actual-CLI smoke made the first fake destination fail with exit 9.
  The second was still attempted, the CLI returned exit 1, original data remained,
  and staging was cleaned. No real rclone, cloud destination, or hardware was used.
- Focused review identified a startup risk from unreadable plot directories or
  undeletable expired files. Three new regression tests reproduced recording
  aborting before fresh serial input. Retention now logs directory/per-file
  warnings and continues; the tests confirm fresh recording and preservation of
  denied files while other eligible files can still be removed.
- Staging failures now retain the actual error detail (for example, disk full)
  instead of only an exception class. That logging regression was also observed
  failing before the fix. Remote subprocess failures still avoid logging full
  command arguments.
- The focused read-only review and follow-up verified the changes and found no
  remaining blockers. Compilation and whitespace checks also pass.

## Deployment constraints

The legacy service must be switched to the new uploader, not left invoking both
scripts. Preserve each Pi's destination paths in its local configuration/service;
do not publish those identifiers in shared code. The snapshot needs free disk
space for one source-tree copy and write access to the source's parent. A forced
kill or power loss may leave temporary staging behind. Remote copy behavior,
live Pi storage capacity, and actual cloud uploads still require deployment
verification. Back up data before opting into deletion or restarting the logger
with positive retention. No remote configuration or hardware changes were made.
