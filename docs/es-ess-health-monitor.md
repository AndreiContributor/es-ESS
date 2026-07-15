# es-ESS Production Health Monitor

`scripts/es-ess-health-monitor.sh` is a read-only shell monitor for a Cerbo GX
or other Venus OS GX device running es-ESS. Use it after a firmware upgrade,
after deploying a new checkout, after editing `config.ini`, during early
morning daylight validation, during mid-day PV-surplus/phase-switch validation,
and after dependency recovery such as reinstalling `websocket-client`.

The script does not write to D-Bus, MQTT, configuration files, service state, or
Wattpilot control values. It only reads local files, D-Bus paths, service
status, selected config keys, disk usage, Python dependency imports, and recent
logs.

## Install The Script

### Option 1: the script is already in the es-ESS checkout

After updating or copying the repository to `/data/es-ESS`, make the script
executable:

```sh
cd /data/es-ESS
chmod +x scripts/es-ess-health-monitor.sh
```

Optionally verify shell syntax:

```sh
sh -n scripts/es-ess-health-monitor.sh
```

### Option 2: copy only the script manually

If you are using WinSCP, SCP, or another manual copy method, create the scripts
directory first and place `es-ess-health-monitor.sh` inside it:

```sh
mkdir -p /data/es-ESS/scripts
```

Then copy the local file:

```text
scripts/es-ess-health-monitor.sh
```

to:

```text
/data/es-ESS/scripts/es-ess-health-monitor.sh
```

Finally, make it executable and verify syntax:

```sh
chmod +x /data/es-ESS/scripts/es-ess-health-monitor.sh
sh -n /data/es-ESS/scripts/es-ess-health-monitor.sh
```

## Run A Single Health Snapshot

Use this after a deploy, restart, dependency install, or firmware update:

```sh
/data/es-ESS/scripts/es-ess-health-monitor.sh
```

To save the output:

```sh
/data/es-ESS/scripts/es-ess-health-monitor.sh | tee /data/es-ess-health-$(date +%Y%m%d-%H%M%S).log
```

## Run A Longer Observation Window

For early morning Auto/Eco start validation or mid-day PV-surplus/phase-switch
validation, run repeated samples:

```sh
INTERVAL_SECONDS=10 MAX_SAMPLES=120 /data/es-ESS/scripts/es-ess-health-monitor.sh | tee /data/es-ess-health-$(date +%Y%m%d-%H%M%S).log
```

That captures about 20 minutes. Use `Ctrl-C` to stop earlier. For continuous
monitoring until stopped:

```sh
INTERVAL_SECONDS=10 MAX_SAMPLES=0 /data/es-ESS/scripts/es-ess-health-monitor.sh | tee /data/es-ess-health-$(date +%Y%m%d-%H%M%S).log
```

## What It Checks

The monitor gathers the operational evidence most useful after firmware,
deployment, or Wattpilot validation work:

- Venus OS version, expected runtime baseline, and service uptime.
- `/data/es-ESS`, `/service/es-ESS`, and `/data/rc.local` persistence.
- Wattpilot dependency imports for `paho.mqtt.client` and `websocket`, using
  `python` when available and falling back to `python3`.
- Pinned bundled `velib_python` integrity, the resolved `vedbus` import path,
  and a read-only per-file comparison with the Venus OS system copy.
- Disk usage for `/` and `/data`.
- Selected config values that affect Wattpilot safety and PV policy.
- Wattpilot standard EV-charger D-Bus paths such as `/Connected`,
  `/StatusLiteral`, `/ModeLiteral`, `/StartStopLiteral`, `/Ac/Power`,
  `/Current`, `/SetCurrent`, `/PvAllowance`, and `/PhaseModeLiteral`.
- Wattpilot runtime-status contract paths such as `/ControlStateLiteral`,
  `/BatteryAssistActive`, `/GridImportGuardActive`, `/TelemetryHealthy`,
  `/CompatibilityOk`, `/CompatibilityLiteral`, `/CommandAuthorityOk`,
  `/CommandAuthorityLiteral`, `/NativePvSurplusEnabled`,
  `/FlexibleTariffEnabled`, and expected/actual firmware values.
- Recent log entries for compatibility, dependency, controller, battery-assist,
  grid-import, phase-switch, Wattpilot command evidence, and raw-to-published
  Wattpilot mode transitions.

## Validate The Wattpilot Mode Boundary

Use this read-only observation with the vehicle disconnected. Synchronize the
phone and GX clocks, then run the monitor continuously with enough log history:

```sh
INTERVAL_SECONDS=5 MAX_SAMPLES=0 LOG_LINES=1000 EVENT_LINES=120 /data/es-ESS/scripts/es-ess-health-monitor.sh | tee /data/es-ess-mode-boundary-$(date +%Y%m%d-%H%M%S).log
```

For each Standard-to-Eco and Eco-to-Standard transition, record the phone-app
selection time and the physical Eco LED change. The mode-boundary log section
then provides two es-ESS timestamps:

- `Wattpilot mode telemetry changed` is the raw WebSocket `lmo` receipt.
- `Published Wattpilot mode telemetry` is the controller's matching
  `/ModeLiteral` publication.

The matching publication should follow on the next five-second controller
cycle even while the vehicle is disconnected. Production diagnosis on
2026-07-13 established that raw `lmo` changed promptly but the prior idle path
could defer `/ModeLiteral` for up to five minutes. The controller now bypasses
that idle throttle only for an unpublished raw mode transition.

Repeat once through the local/hotspot app path and once through remote/cloud
access when both are available. The timestamps are diagnostic facts only; they
do not expire an otherwise stable ECO session or authorize any Wattpilot
command. Confirm that neither transition produces an unintended `psm`, `amp`,
or `frc` command. Stop and retain the capture if the physical Eco LED changes
to Manual before es-ESS receives the matching non-ECO `lmo` value.

This correlation was completed in production on 2026-07-15 with the vehicle
disconnected; the retained GX capture is
`/data/es-ess-mode-boundary-20260715-155537.log`. Local raw `lmo=3` to public
Manual propagation took 5.080 seconds. A failed Android widget request reported
a VRM realtime/MQTT delivery error and produced no es-ESS `/Mode` event. The
successful retry progressed from `/Mode=1` to raw `lmo=4` and public Auto in
130 ms server-observed time, restored the physical white/orange status-114
indication, and produced no unintended `psm`, `amp`, or `frc` command. Retain
this procedure for regression checks after relevant runtime or integration
changes.

## How To Read The Output

Healthy output normally shows:

- Service state is `up`.
- Python dependencies import successfully.
- Venus OS matches the expected clean release.
- Compatibility status is OK after Wattpilot firmware telemetry is received.
- Auto/Eco command ownership shows `CommandAuthorityOk=1`,
  `NativePvSurplusEnabled=0`, and `FlexibleTariffEnabled=0` before a vehicle is
  connected.
- `TelemetryHealthy` is `1` during Auto/Eco decisions.
- `GridImportGuardActive` is `0` during normal no-grid operation.
- Battery assist, when active, remains bounded and later recovers.
- Manual mode reports state but does not produce repeated Wattpilot
  start/stop/current/phase commands.
- Raw `lmo` changes are followed by the matching `/ModeLiteral` publication on
  the next eligible controller cycle.

Stop the active validation and inspect logs immediately if:

- The service is down or restarting repeatedly.
- The recent log section shows `CRITICAL`, `Traceback`, `ModuleNotFoundError`,
  `Unsupported Venus OS`, `not validated`, or `CompatibilityError`.
- Auto/Eco charging shows sustained grid import while
  `AllowGridCharging=false`.
- Auto/Eco reports `CommandAuthorityOk=0`; follow the actionable authority
  literal and keep the vehicle disconnected until both native settings report
  `0` and authority reports `1`.
- Battery assist exceeds configured duration or shortfall expectations.
- Manual mode produces Wattpilot start, stop, current, or phase commands.

## Useful Environment Overrides

Defaults are chosen for the production Cerbo GX layout:

```sh
INTERVAL_SECONDS=10
MAX_SAMPLES=1
LOG_LINES=300
EVENT_LINES=40
CONFIG_FILE=/data/es-ESS/config.ini
LOG_FILE=/data/log/es-ESS/current.log
SERVICE_DIR=/service/es-ESS
APP_DIR=/data/es-ESS
WATTPILOT_DBUS_SERVICE=com.victronenergy.evcharger.esESS_FroniusWattpilot
EXPECTED_VENUS_OS=v3.75
```

Override them only when intentionally validating a different layout:

```sh
LOG_LINES=800 EVENT_LINES=120 /data/es-ESS/scripts/es-ess-health-monitor.sh
```

## Related Documentation

- [es-ESS daily report](es-ess-daily-report.md)
- [Cerbo GX firmware upgrade and rollback](cerbo-gx-firmware-upgrade-and-rollback.md)
- [Wattpilot architecture boundaries](wattpilot-architecture.md)
- [es-ESS service inventory](service-inventory.md)
- [System guide](system-guide.html)
