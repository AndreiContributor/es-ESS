# es-ESS Diagnostic Tools

The `scripts/` directory contains six diagnostic files representing five
read-only tools. You do not need to run all of them. Choose the smallest tool
that answers the question being investigated.

## Which Tool To Use

| Question | Tool | Typical duration | Files required on the GX |
| --- | --- | --- | --- |
| Is the deployment, service, compatibility baseline, configuration, storage, and current telemetry healthy? | Production health monitor | One snapshot or a supervised 20-minute window | `es-ess-health-monitor.sh` |
| Is an unchanged positive current target being dispatched repeatedly? | Current-command monitor | About 1–2 minutes after charging stabilizes | `wattpilot-current-command-monitor.sh` |
| Was one complete live charging session healthy, including starts, stops, phase changes, per-phase power/current, selected site-current health, and command cadence? | Charging-session capture | Six hours by default | `wattpilot-session-capture.sh` and `wattpilot-session-capture.py` |
| Was a completed day healthy across restarts, charging sessions, safety guards, energy evidence, and unusual states? | Daily report | A completed APP_DEBUG day, or an explicitly incomplete current-day report | `es-ess-daily-report.py` |
| Which native Wattpilot property changes when one Solar.wattpilot setting is changed manually? | Setting capture | A short attended before/after experiment with the vehicle disconnected and es-ESS stopped | `wattpilot-setting-capture.py` |

The two charging-session files are one tool, not duplicate implementations.
The small POSIX-shell file is the operator-friendly Venus OS launcher. It
selects `python` or `python3` and starts the companion Python implementation,
which owns the persistent D-Bus connection, timestamp integration, transition
tracking, and report generation. Both files must be copied to the same
directory on the GX device.

## Selection Rules

- Use the **health monitor** immediately after an install, deployment, restart,
  firmware update, dependency repair, or `config.ini` change. It is a checkpoint
  and short observation tool, not a complete charging-session analyzer.
- Use the **current-command monitor** only for a fast, focused check of current
  command deduplication. The longer session capture includes command counts and
  target transitions, so this short monitor is optional during a six-hour
  capture.
- Use the **charging-session capture** when start/stop behavior, phase-up or
  phase-down behavior, energy, per-phase loading, selected site-current
  telemetry, or message frequency must be correlated over one live session.
- Use the **daily report** after APP_DEBUG evidence covers the requested period.
  It analyzes retained history; it does not replace high-frequency live session
  sampling.
- Use the **setting capture** only for the command-ownership discovery procedure.
  It is not needed for ordinary charging validation, health monitoring, or
  daily reporting.

## Selected Site-Current Source

The charging-session capture does not parse credentials or independently choose
between `Shelly3EMGen3` and `VenusSystem`. It reads the running Wattpilot
service's controller-normalized D-Bus contract, including `/SiteCurrentSource`,
`/SiteCurrentL1..L3`, phase ages, headroom, source health, limiting phase, and
`/Charger1PhaseMapping`. The values therefore follow the source actually
initialized from `config.ini`, including an L1, L2, or L3 one-phase mapping.

## Commands

Run a single production health snapshot:

```sh
/data/es-ESS/scripts/es-ess-health-monitor.sh
```

Run the focused current-command check:

```sh
DURATION_SECONDS=120 sh /data/es-ESS/scripts/wattpilot-current-command-monitor.sh
```

Start the default six-hour charging-session capture after copying both session
files:

```sh
chmod 700 /data/es-ESS/scripts/wattpilot-session-capture.sh
nohup sh /data/es-ESS/scripts/wattpilot-session-capture.sh \
  >/data/wattpilot-capture-launch.log 2>&1 &
echo $!
```

Analyze yesterday after a complete APP_DEBUG day:

```sh
python /data/es-ESS/scripts/es-ess-daily-report.py --date yesterday
```

Do not run the setting capture casually. Follow the attended, vehicle-
disconnected procedure in
[Wattpilot command-ownership validation](wattpilot-command-ownership-validation.md).

## Privacy And Safety

All five tools are designed to avoid charger, D-Bus, MQTT, service, and
configuration writes within their documented operating boundaries. The setting
capture additionally installs a command guard, but its procedure still requires
the vehicle to be disconnected and es-ESS to be stopped.

Diagnostic output remains private operational evidence:

- Do not commit captures, reports, screenshots, launch logs, or raw application
  logs to the public repository.
- The charging-session summary and TSV files do not copy `config.ini` passwords,
  host addresses, or complete configuration data. Its `es-ESS-events.log` file
  is an unmodified copy of new application log records and may contain private
  operational details.
- The setting capture redacts or fingerprints known sensitive fields, but its
  reports can still reveal operational property names and correlated values.
- Store retained output outside the checkout in an owner-only directory and
  redact it before sharing.

## Detailed Guides

- [Production health monitor](es-ess-health-monitor.md)
- [Daily report](es-ess-daily-report.md)
- [Wattpilot command-ownership validation](wattpilot-command-ownership-validation.md)
- [Wattpilot architecture boundaries](wattpilot-architecture.md)
