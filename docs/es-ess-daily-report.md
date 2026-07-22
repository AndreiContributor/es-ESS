# es-ESS Daily Report

`scripts/es-ess-daily-report.py` is the single historical/end-of-day analyzer
for es-ESS. It reconstructs the available Wattpilot connection and charging
timeline, reports authoritative available session-counter energy separately
from sampled-power estimates, and checks runtime, allowance, phase, current,
battery-assist, command-authority, grid-safety, and rare-status evidence against
the safe values in `config.ini`.
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
- the authoritative Venus timezone through one bounded, exact
  `com.victronenergy.settings /Settings/System/TimeZone GetValue` query; and
- when available, current service state through `svstat` plus selected D-Bus
  values through exact `dbus ... GetValue` calls.

It never writes D-Bus, MQTT, Wattpilot settings, configuration, files, or
service state. It does not import the es-ESS controller. The command helper
rejects service control and every D-Bus operation except the exact Wattpilot
snapshot and Venus-timezone service/path pairs declared by the tool. The
dependency result is explicitly limited to the Wattpilot external Python
dependencies, Paho MQTT and websocket-client. Use `--no-current-snapshot` to
skip the optional service and
runtime-status snapshot; the required read-only timezone query still runs so
`today`, `yesterday`, explicit dates, and local-midnight boundaries agree with
logging even when the service process runs in UTC. Each command has a two-second
timeout. After three consecutive snapshot timeouts, remaining optional snapshot
paths are marked unavailable and historical analysis continues. If the timezone
query or timezone database is unavailable, the report warns, uses OS-local time,
and cannot silently claim a complete authoritative calendar window.

A missing configuration produces safe fallbacks and an incomplete prerequisite
result. A configuration that exists but cannot be opened or parsed is an input
error; the report stops instead of silently analyzing with all-default settings.

New log records use the Venus `/Settings/System/TimeZone` wall time with the
applicable offset, for example
`2026-07-15 18:42:10,123 (UTC+3) APP_DEBUG ...`. The analyzer uses that offset
to order records and calculate durations across daylight-saving changes. It
continues to accept pre-upgrade records that do not contain an offset, so a
rotation window spanning the upgrade remains readable. Grid-to-charge
correlation, allowance lookup, Manual-boundary checks, and charging-session stop
lookup use timestamp indexes. Message-marker routing avoids applying every
event regex to unrelated lines, and timestamp parsing uses the ISO fast path,
keeping APP_DEBUG reports practical when a day contains many samples.

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
stdout, so JSON remains parseable. The report header records separate log-load
and evidence-analysis durations to make GX performance regressions visible.
Automatic discovery reads only rotations whose Venus-local calendar dates
intersect the requested window. The active `current.log` is included for the
current day and as a conservative fallback when an expected completed-day
rotation is missing. Parsed timestamps and the existing coverage checks remain
authoritative, so filename selection cannot turn incomplete evidence into a
complete report. Report cost therefore follows the requested window instead of
the total retention period.
Disable progress for automation with:

```sh
python /data/es-ESS/scripts/es-ess-daily-report.py --date yesterday --no-progress
```

`--date today` reports the available part of the day and exits `1` with
`INCOMPLETE`, unless it detects an anomaly and exits `2`. It stops only when
there are no parseable current-day records or no diagnostic-level record.
`--hours` accepts only 24 hours or more. Current and rotated logs are discovered
and selected automatically. `--log-file` is available for a copied raw log;
historical and rolling requests still require complete-window evidence.
Pressing `Ctrl+C` stops cleanly with exit code `130`.

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
Connection and charging-interval IDs are process-local timestamp correlations;
they do not contain a vehicle identity, VIN, account, charger password, or
persistent device identifier.

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
`ANOMALY`, `3` for invalid arguments or unreadable explicit input, and `130`
when the operator interrupts the report.

## Report Sections

The human and JSON reports contain:

- coverage metadata: complete/partial state, requested start/end, analysis
  cutoff, first/last evidence, evidence duration, elapsed requested duration,
  evidence-span percentage, and full-day availability time;
- runtime health: initialization/restart evidence, Wattpilot reconnects, log
  continuity, exceptions, dependencies, and compatibility;
- sanitized configuration: enabled services and important Wattpilot safety
  parameters, including site-current limit/mapping/freshness/recovery;
- current state: optional service, mode, connectivity, authority, telemetry,
  phase, firmware, and native-setting snapshots;
- structured connection sessions and their charging intervals: plug/first-start/
  first-measured-power timing, interruptions, Auto/Manual/unknown mode, phases,
  compact current and peak-power ranges, phase segments, stop reason, command
  rejections, battery assist, grid guards, stale telemetry, rare statuses,
  restart evidence, and partial-start/end flags;
- energy evidence: authoritative Wattpilot counter deltas only when continuity
  is proven; observed-but-incomplete counter deltas after resets or restarts;
  explicitly estimated one-/three-phase and conductor splits, with the
  configured physical phase identified for one-phase operation; sampled
  coverage, uncovered time, physical-mapping completeness, and
  estimate-to-counter reconciliation error;
- rare firmware statuses 8–11 and 13–14: protocol name, occurrences, selected
  controller state, observed duration, and transition result;
- anomalies, correctly activated safety interventions, evidence gaps,
  recommendations, metrics, and limitations.

## Safety-Aware Checks

Version 4 detects or summarizes:

- `CRITICAL`, `ERROR`, traceback, dependency, firmware, and Venus OS
  compatibility failures;
- repeated service initializations or Wattpilot reconnect lifecycle events;
- site-current stops and stale site-current telemetry found in controller logs;
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

## Structured Session Evidence

`FroniusWattpilot.py` observes confirmed controller state once per normal duty
cycle through the command-free `WattpilotSessionStatistics.py` component. The
component cannot access Wattpilot commands, D-Bus, MQTT, or configuration
writes. The controller emits versioned JSON after the stable marker
`Wattpilot session statistics:`:

- INFO on confirmed connection, the first start attempt, measured charge
  start/stop, completed phase segment, and final connection summary; and
- at most one APP_DEBUG checkpoint per connected minute.

The structured event version is independent from daily-report JSON schema 4 so
future log parsing can remain explicit. A connection may contain multiple
charging intervals. Correlation IDs distinguish those observed intervals only;
they never claim which vehicle was connected.

The Wattpilot `wh` session counter is cumulative. The report accepts only
non-negative monotonic deltas and marks decreases/resets rather than subtracting
or joining incompatible counter segments. A service restart while connected
creates a partial session because energy delivered while the process was not
observing cannot be reconstructed.

L1/L2/L3 and one-/three-phase values are trapezoidal integrations of fresh
sampled Wattpilot power. The component does not extrapolate across stale input,
a phase transition, a non-monotonic timestamp, or a sampling gap longer than
the accepted bound. Coverage and reconciliation fields therefore make the
accuracy limitation measurable. These estimates are not certified meter
counters. In one-phase mode, `Charger1PhaseMapping` selects the physical phase.
Three-phase mode proves that all three conductors were used, but its individual
L1/L2/L3 labels follow Wattpilot-reported conductor order because the existing
configuration verifies only the one-phase conductor. A session containing a
three-phase interval is therefore marked as having incomplete physical-phase
mapping; the report does not imply electrician-verified three-phase ordering.

For a session spanning a report boundary, the analyzer subtracts the first
available cumulative checkpoint from the last available checkpoint/summary in
the selected window. The unobserved boundary portion remains partial. Abrupt
GX/process failure may lose a final summary, but the last minute checkpoint
retains bounded recovery evidence.

## Evidence Limitation

The defensible statement is:

> No anomaly was detected in the complete available evidence.

The report must not be interpreted as proof that an entire session was
definitely perfect. Logs cannot prove how much historical grid or battery
energy supplied a completed charge. D-Bus values are current snapshots, not
historical storage. Counter kWh is authoritative only when the report proves a
continuous monotonic Wattpilot session counter; sampled phase splits remain
estimates even when coverage is complete. Older logs without structured records
retain approximate session reconstruction but cannot provide connection counts
or historical energy.

The optional read-only snapshot includes physical site-current values, sample
ages, calculated headrooms, limiting phase, allowed current, guard health,
blocked reason, and recovery elapsed time. These describe only the capture
instant; absence from historical logs is not proof that the guard succeeded.

For live investigation, run `scripts/es-ess-health-monitor.sh`. Keep the
structured records transition-only plus the fixed one-minute connected
checkpoint; do not add five-second logging spam.

## Related Documentation

- [Production health monitor](es-ess-health-monitor.md)
- [Wattpilot architecture](wattpilot-architecture.md)
- [Wattpilot command-ownership validation](wattpilot-command-ownership-validation.md)
