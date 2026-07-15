# es-ESS Daily Report

`scripts/es-ess-daily-report.py` is the single historical/end-of-day analyzer
for es-ESS. It reconstructs the available Wattpilot charging timeline and
checks runtime, allowance, phase, current, battery-assist, command-authority,
grid-safety, and rare-status evidence against the safe values in `config.ini`.
The existing `scripts/es-ess-health-monitor.sh` remains the live snapshot tool.

## Mandatory APP_DEBUG And Coverage Rules

The analyzer always requires `[Common] LogLevel=APP_DEBUG` (or the more verbose
`DEBUG`/`TRACE`) in `/data/es-ESS/config.ini`.

Historical dates and rolling windows require diagnostic records covering the
complete requested period, including records close to both boundaries. Today is
handled differently: `--date today` analyzes existing records from midnight to
the execution time when at least one parseable diagnostic record exists. Its
overall result cannot be `GOOD`; it remains `INCOMPLETE` unless available
evidence already proves an `ANOMALY`.

To prepare production evidence:

```ini
[Common]
LogLevel=APP_DEBUG
LogRetentionDays=10
```

Restart es-ESS, leave it running for at least one complete day, and analyze
yesterday:

```sh
/data/es-ESS/restart.sh
python /data/es-ESS/scripts/es-ess-daily-report.py --date yesterday
```

An `INFO` log, a filtered `grep` excerpt, or a truncated historical file is not
enough evidence. A partial-today report clearly identifies its requested
period, analysis cutoff, first/last evidence, evidence duration, span coverage,
and the next midnight when a complete calendar-day report becomes available.
Choose `LogRetentionDays` long enough to cover the dates you intend to analyze.
The current local day counts toward that setting; the maintained value `10`
keeps `current.log` plus at most nine dated daily rotations.

## Read-Only Boundary

The tool reads only:

- `/data/es-ESS/config.ini`;
- `/data/log/es-ESS/current.log` and standard dated rotations such as
  `current.log.2026-07-15`; and
- when available, current service state through `svstat` plus selected D-Bus
  values through exact `dbus ... GetValue` calls.

It never writes D-Bus, MQTT, Wattpilot settings, configuration, files, or
service state. It does not import the es-ESS controller. The command helper
rejects service control and every D-Bus operation except the allowlisted
`GetValue` snapshots. Use `--no-current-snapshot` to perform log/config analysis
without invoking even those optional read commands. Each snapshot command has a
two-second timeout. After three consecutive D-Bus timeouts, remaining snapshot
paths are marked unavailable and historical analysis continues.

New log records use local wall time with the applicable offset, for example
`2026-07-15 18:42:10,123 (UTC+3) APP_DEBUG ...`. The analyzer uses that offset
to order records and calculate durations across daylight-saving changes. It
continues to accept pre-upgrade records that do not contain an offset, so a
rotation window spanning the upgrade remains readable.

## Install And Run

```sh
cd /data/es-ESS
chmod +x scripts/es-ess-daily-report.py
python -m py_compile scripts/es-ess-daily-report.py
python scripts/es-ess-daily-report.py --date yesterday
```

No test files are required on production. The default is `--date yesterday`.
Use `--date today` for an explicitly partial diagnostic report. Available forms
are:

```sh
python /data/es-ESS/scripts/es-ess-daily-report.py --date today
python /data/es-ESS/scripts/es-ess-daily-report.py --date 2026-07-15
python /data/es-ESS/scripts/es-ess-daily-report.py --hours 24
python /data/es-ESS/scripts/es-ess-daily-report.py --date yesterday --json
```

Interactive runs display a six-stage progress bar on stderr: configuration,
byte-level log loading, evidence validation, read-only snapshot paths, analysis,
and rendering. This is particularly useful on GX hardware when a large
APP_DEBUG log contains more than 100,000 records. Progress never enters report
stdout, so JSON remains parseable. Disable it for automation with:

```sh
python /data/es-ESS/scripts/es-ess-daily-report.py --date yesterday --no-progress
```

`--date today` reports the available part of the day and exits `1` with
`INCOMPLETE`, unless it detects an anomaly and exits `2`. It stops only when
there are no parseable current-day records or no diagnostic-level record.
`--hours` accepts only 24 hours or more. Current and rotated logs are discovered
automatically. `--log-file` is available for a copied raw log; historical and
rolling requests still require complete-window evidence.

To retain a private JSON report:

```sh
mkdir -p /data/es-ESS-validation
chmod 700 /data/es-ESS-validation
umask 077
python /data/es-ESS/scripts/es-ess-daily-report.py --date yesterday --json \
  > /data/es-ESS-validation/es-ess-daily-report-$(date +%Y%m%d).json
```

Only sanitized configuration fields are emitted. Hosts, passwords, MQTT
credentials, portal IDs, and unrelated configuration are not included.

## Overall Results

- `GOOD` — no anomaly was found in complete available evidence.
- `ATTENTION` — a safety intervention, recognized rare status, or unusual event
  occurred. This is not automatically a controller defect.
- `ANOMALY` — available evidence probably contradicts expected behavior or
  contains a runtime/safety failure.
- `INCOMPLETE` — the log level, duration, continuity, telemetry, or other
  evidence is insufficient.

Individual checks use `PASS`, `INFO`, `NOT_OBSERVED`, `ATTENTION`, `WARN`, and
`FAIL`. A rare status marked `NOT OBSERVED` is informational and does not lower
a healthy result.

Exit codes are `0` for `GOOD`, `1` for `ATTENTION` or `INCOMPLETE`, `2` for
`ANOMALY`, and `3` for invalid arguments or unreadable explicit input.

## Report Sections

The human and JSON reports contain:

- coverage metadata: complete/partial state, requested start/end, analysis
  cutoff, first/last evidence, evidence duration, elapsed requested duration,
  evidence-span percentage, and full-day availability time;
- runtime health: initialization/restart evidence, Wattpilot reconnects, log
  continuity, exceptions, dependencies, and compatibility;
- sanitized configuration: enabled services and important Wattpilot safety
  parameters only;
- current state: optional service, mode, connectivity, authority, telemetry,
  phase, firmware, and native-setting snapshots;
- approximate charging sessions: start/end, Auto/Manual/unknown mode, phases,
  compact current-change counts/range/transitions, phase commands, stop reason,
  battery assist, grid guards,
  stale telemetry, rare statuses, and restart evidence;
- rare firmware statuses 8–11 and 13–14: protocol name, occurrences, selected
  controller state, observed duration, and transition result;
- anomalies, correctly activated safety interventions, evidence gaps,
  recommendations, metrics, and limitations.

## Safety-Aware Checks

Version 3 detects or summarizes:

- `CRITICAL`, `ERROR`, traceback, dependency, firmware, and Venus OS
  compatibility failures;
- repeated service initializations or Wattpilot reconnect lifecycle events;
- Auto/Eco actions while command authority is blocked;
- stale grid or distributor-allowance evidence;
- grid-import guard activation when `AllowGridCharging=false`, distinguishing a
  correct intervention from sustained unguarded import;
- battery assist exceeding configured shortfall/time expectations or reaching
  its limit;
- allowance freshness and `AllowanceDropGraceSeconds`, including a transient
  `0 W` allocation during three-phase charging;
- excessive, premature, low-allowance, or unconfirmed phase switching;
- current outside configured per-phase bounds;
- raw or interpreted start/stop/current/phase commands while Manual mode owns
  charging, while allowing the documented immediate command-authority release;
- configuration combinations inconsistent with the documented no-grid
  commissioning profile; and
- rare charging-status entry/exit through recognized active or safety states.

## Evidence Limitation

The defensible statement is:

> No anomaly was detected in the complete available evidence.

The report must not be interpreted as proof that an entire session was
definitely perfect. Logs cannot always prove how much historical grid or
battery energy supplied a completed charge. D-Bus values are current snapshots,
not historical storage, and Wattpilot session energy can reset after
disconnection. Session boundaries and stop reasons are approximate unless the
corresponding transition records exist.

For live investigation, run `scripts/es-ess-health-monitor.sh`. For stronger
future historical summaries, add stable transition-only INFO records for
session start/end, phase changes, stop reasons, safety interventions, and final
energy/time; do not add high-frequency log spam.

## Related Documentation

- [Production health monitor](es-ess-health-monitor.md)
- [Wattpilot architecture](wattpilot-architecture.md)
- [Wattpilot command-ownership validation](wattpilot-command-ownership-validation.md)
