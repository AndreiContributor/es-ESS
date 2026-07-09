# es-ESS Backlog

This backlog was created from the requested Wattpilot PR roadmap and a
safety-focused review of the current application state in this checkout.

## Current App Analysis

es-ESS is a Python service bundle for Victron Venus OS / GX devices. The app is
structured as independent services that are enabled from `config.ini`.

Runtime entry points and orchestration:

- `service/run` starts `python /data/es-ESS/es-ESS.py`.
- `es-ESS.py` loads and upgrades configuration, configures MQTT, starts the
  GLib/D-Bus loop, initializes enabled services, dispatches D-Bus and MQTT
  subscriptions, schedules worker callbacks, publishes service messages, and
  handles SIGTERM cleanup.
- `esESSService.py` is the base class used by services to register D-Bus paths,
  D-Bus subscriptions, MQTT subscriptions, worker threads, service messages,
  and grid-setpoint requests.

Major services and integrations:

- Wattpilot support is centered in `FroniusWattpilot.py`.
- The Wattpilot WebSocket client lives in `Wattpilot.py`.
- Runtime status for dashboards, Cerbo extensions, MQTT consumers, and
  diagnostics lives in `WattpilotRuntimeStatus.py`.
- PV allowance and battery-reservation coordination come from
  `SolarOverheadDistributor.py`.
- Other integrations include MQTT inverter/export services, Shelly grid and PV
  devices, Fronius smart meters, temperature publishing, D-Bus paths on Venus
  OS, and local/main MQTT brokers.

Current Wattpilot state:

- Auto/Eco PV-only control, no-grid protection, battery assist, telemetry
  freshness, startup grace, raw-overhead freshness, and runtime status reporting
  are already present in code and tests.
- Manual-mode reporting is present, but the writable EV-charger command paths
  still need an explicit command-boundary review so Manual Wattpilot mode cannot
  be controlled accidentally through VRM/D-Bus writes.
- `config.sample.ini` and the production config are intended to match. The
  project uses `config.sample.ini` as the single configuration artifact, and
  the Wattpilot sample keys are covered by a config contract test.
- The unused Wattpilot `Username` setting has been removed from the maintained
  sample and README; `Wattpilot.py` authenticates with password only.
- README now points setup and config-comment source links at the maintained
  repository and documents the current Wattpilot Auto/Eco policy, examples, and
  runtime-status contract.
- Wattpilot WebSocket reconnect handling is now owned by one bounded worker
  loop in `Wattpilot.py`; close callbacks no longer recursively call
  `run_forever()`.
- Configuration migration currently performs unconditional section creation for
  some legacy upgrades, which can break older user configs that already contain
  those sections.
- A GitHub Actions CI workflow now runs hardware-free Python 3.12 syntax,
  config-contract, and unittest checks on pull requests and pushes to `main`.
- Tests cover many Wattpilot control decisions and now include a config
  contract test for undocumented or unknown Wattpilot config keys.

Current test strategy:

- Hardware-free regression tests live under `tests/`.
- Existing tests stub Victron/D-Bus/MQTT/Wattpilot dependencies and exercise
  Wattpilot PV-control policy, runtime status, grid guards, phase switching,
  stale telemetry, battery assist, charge-complete hold, and several Manual
  mode safety cases.
- Remaining gaps are around writable D-Bus command boundaries, Venus EVCS
  session energy/time compatibility, user-visible Wattpilot transport-outage
  presentation, broader configuration migration compatibility, CI, and
  lifecycle shell scripts.

Unclear deployment details:

- The checked GX/Venus OS device reported Python 3.12.13. The oldest supported
  Venus OS / GX Python version is still not explicitly stated in README.
- Available live-device, MQTT, D-Bus, or hardware-in-the-loop validation is not
  known.
- Firmware behavior across Wattpilot revisions is not described beyond the
  current WebSocket client assumptions.

Global delivery rules:

- Implement only the task described in the active PR.
- Keep normal Wattpilot Manual mode unchanged. Reporting status is allowed;
  controlling Manual charging is not.
- In Auto/Eco mode, do not intentionally use grid power when
  `AllowGridCharging=false`.
- Battery assist remains an optional, time-limited bridge for an already-running
  charge only.
- Add or update unit tests for every behavior change.
- Run syntax checks and the full test suite before opening a PR.
- Update README and config documentation whenever a new setting or behavior is
  introduced.
- Do not add shared 16 A cable/current-limiting logic.

## Review Questions And Assumptions

Assumptions:

- The review is for production hardening and implementation planning, not for a
  single active bug fix.
- Hardware access is not available in this checkout, so live Wattpilot, D-Bus,
  MQTT, and Venus OS validation must be documented as manual validation.
- The user's configuration decision is accepted: use `config.sample.ini` as the
  only checked-in config example.

Open questions:

- Which Venus OS / GX versions, beyond the checked Python 3.12.13 device, must
  CI target?
- Should VRM/D-Bus writes to `/Mode` remain allowed to switch between Auto and
  Manual, while `/SetCurrent` and `/StartStop` are blocked whenever Wattpilot is
  already in Manual?
- Should uninstall behavior keep a dated backup of `/data/es-ESS/config.ini`
  before removing the deployed directory?

## Completed

### Completed 2026-07-08 - Rebuild Wattpilot Configuration Around `config.sample.ini`

Completion note:

- Added the missing charge-complete hold settings to `[FroniusWattpilot]` in
  `config.sample.ini`.
- Removed the unused Wattpilot `Username` sample/README entry because the
  Wattpilot client authenticates with password only.
- Updated README to name `config.sample.ini` as the maintained reference,
  corrected `BatteryMaxChargeInWh`, and documented every active Wattpilot
  setting from the sample.
- Added `tests/test_config_contract.py`, which parses
  `FroniusWattpilot.py` and fails if active Wattpilot keys are missing from
  `config.sample.ini` or if the sample contains unknown Wattpilot keys.
- Verified with `py_compile`, the config contract test, and the full unittest
  suite.
- Kept the change config/docs/tests-only; no production control behavior,
  D-Bus paths, MQTT topics, or architecture boundaries were changed.

### Completed 2026-07-08 - Make Configuration Upgrades Idempotent And Section-Safe

Completion note:

- Added idempotent config migration helpers in `es-ESS.py`.
- Updated existing migration defaults so user-provided service flags,
  `[NoBatToEV]`, and `[MqttPvInverter]` values are preserved.
- Added hardware-free regression tests in `tests/test_config_migration.py` for
  existing later sections, missing later sections, and preserved legacy service
  flags.
- Verified with `py_compile` and the full unittest suite.
- Manual validation confirmed a v7 config with existing `[MqttPvInverter]`
  upgraded to v8, preserved custom values, added missing defaults, and started
  without the duplicate-section crash.

### Completed 2026-07-08 - Document Wattpilot Architecture Boundaries

Completion note:

- Added `docs/wattpilot-architecture.md` with current Wattpilot module
  boundaries and safety invariants.
- Documented `Wattpilot.py` as the transport/client boundary, not a PV/no-grid
  policy module.
- Documented `FroniusWattpilot.py` as the current controller and command
  side-effect boundary until smaller decision helpers are extracted.
- Documented `WattpilotRuntimeStatus.py` as an observer/status publisher that
  must not issue charger commands.
- Linked the architecture note from `README.md` and added it to `AGENTS.md`
  implementation guidance.
- Added the architecture note to the es-ESS code-review skill inspection list
  and update rules.
- Kept the change documentation-only; no production code, config defaults,
  D-Bus paths, MQTT topics, or tests were changed.

### Completed 2026-07-08 - Document App-Wide Service Inventory And Integration Boundaries

Completion note:

- Added `docs/service-inventory.md` with active initialized services, dormant
  and config-only entries, shared integration patterns, and follow-up gaps.
- Documented D-Bus publishers/readers, MQTT boundaries, HTTP/device polling,
  SolarOverheadDistributor consumers, and grid-setpoint ownership.
- Added `docs/service-inventory.md` to `AGENTS.md` inspection and maintenance
  guidance.
- Added the service inventory to the es-ESS code-review skill inspection list
  and update rules.
- Kept the change documentation-only; no production code, config defaults,
  D-Bus paths, MQTT topics, or tests were changed.

### Completed 2026-07-08 - Harden Service Lifecycle Scripts

Completion note:

- Made `install.sh` strict and idempotent for script permissions, service
  symlink creation/repair, `rc.local` registration, and first-install config
  creation.
- Made `restart.sh` and `kill_me.sh` tolerate an already-stopped service
  without passing an empty PID list to `kill`.
- Narrowed process matching for lifecycle scripts to the expected
  `/data/es-ESS/es-ESS.py` command.
- Updated `uninstall.sh` to stop gracefully before SIGKILL fallback, remove the
  service symlink, preserve `config.ini` under `/data/es-ESS-backups/`, remove
  `/data/es-ESS`, and rewrite `rc.local` through a temp file.
- Updated README lifecycle-command text to document emergency-stop and uninstall
  config-backup behavior.
- Verified shell syntax with Git Bash `bash -n` and ran the full hardware-free
  unittest suite with `uv --cache-dir .uv-cache run --no-project python -m
  unittest discover -s tests`.

### Completed 2026-07-09 - Rewrite Wattpilot README And Correct Installation Source

Completion note:

- Updated README setup commands to download from
  `AndreiContributor/es-ESS`.
- Clarified that `config.sample.ini` is the complete maintained sample and that
  production config should keep the same supported keys.
- Rewrote the Wattpilot overview/configuration guidance around current
  Auto/Eco PV control, Manual-mode ownership, no-grid guard behavior,
  telemetry freshness, one-phase starts, three-phase switching, timer
  differences, battery-assist limits, and runtime-status D-Bus/MQTT values.
- Added PV-only, 300-second cloud-bridge, and conservative timer example
  snippets.
- Added deployment verification commands for syntax checks, the hardware-free
  unittest suite, service restart, and log monitoring.
- Updated the stale README link comment in `config.sample.ini`.
- Kept the change documentation/config-comment/backlog-only; no production
  code, config defaults, D-Bus paths, MQTT topics, or Wattpilot control
  behavior were changed.

### Completed 2026-07-09 - Add Wattpilot Decision Characterization Tests Before Refactoring

Completion note:

- Added hardware-free characterization tests for current Wattpilot allowance
  freshness, raw-overhead phase-down boundaries, grid-import debounce reset,
  battery-assist grid-import rejection, and pending one-phase confirmation
  safety behavior.
- Reused the existing `tests/test_eco_pv_policy.py` controller fixture so the
  tests describe observable controller decisions and Wattpilot command calls.
- Kept the change tests/backlog-only; no production code, configuration
  defaults, D-Bus paths, MQTT topics, architecture boundaries, or charging
  behavior were changed.

### Completed 2026-07-09 - Add Automated Checks With GitHub Actions

Completion note:

- Added `.github/workflows/ci.yml`.
- Configured CI to run on pull requests and pushes to `main`.
- Set CI to Python 3.12, matching the checked GX/Venus OS device Python
  3.12.13 runtime.
- Added hardware-free checks for repository Python syntax via `compileall`,
  the `config.sample.ini` contract test, and the full unittest suite.
- Documented the workflow path and triggers in README Developer Notes.
- Kept the change CI/docs/backlog-only; no production code, configuration
  defaults, D-Bus paths, MQTT topics, architecture boundaries, or charging
  behavior were changed.

### Completed 2026-07-09 - Clean Up Wattpilot Startup Deferred State And Logs

Completion note:

- Initialized `Wattpilot._energyCounterSinceStart` to `None` during client
  construction so early runtime-status publication can read the property before
  the first Wattpilot status update.
- Reworded the Wattpilot client startup log from `Wattpilot connected` to
  `Wattpilot WebSocket worker started`, matching the actual lifecycle point.
- Downgraded expected deferred Wattpilot startup readiness messages in
  `FroniusWattpilot.initFinalize()` from error logging to warning logging and
  removed misleading `within 30 seconds` hard-failure wording.
- Added hardware-free startup hygiene tests for the early energy-counter field,
  WebSocket worker log wording, and deferred-start warning behavior.
- Verified with `py_compile`, targeted Wattpilot startup/runtime-status tests,
  and the full hardware-free unittest suite.
- Kept the change limited to initialization/logging/tests/backlog; no Manual
  mode, Auto/Eco control decisions, reconnect-loop ownership, D-Bus paths, MQTT
  topics, or configuration defaults were changed.

### Completed 2026-07-09 - Publish Wattpilot Transport Outage Status To Victron Dashboard

Completion note:

- Added controller-owned Wattpilot transport dashboard reporting in
  `FroniusWattpilot.py`.
- Extended runtime-status transport observation to record `WS_ERROR` as well as
  `WS_CLOSE`, while keeping raw WebSocket callbacks side-effect-free.
- Set standard Victron EV-charger paths to `/Connected=0`,
  `/Status=Disconnected`, and `/StatusLiteral="Wattpilot not accessible"` when
  the Wattpilot transport is unavailable, and restored `/Connected=1` on
  recovery.
- Added a visible naming hint for EV-charger detail views, D-Bus inspection,
  MQTT consumers, and SolarOverheadDistributor messages by setting
  `/CustomName` and the SolarOverheadDistributor Wattpilot custom-name topic to
  `Wattpilot not reachable` during transport outages, then restoring the normal
  Wattpilot name on recovery.
- Published one outage service message and one recovery service message per
  outage/recovery cycle.
- Preserved intentional hibernate idle disconnects as normal idle behavior, not
  dashboard transport outages.
- Added hardware-free tests for WebSocket close/error outage reporting,
  visible custom-name publication, recovery, message de-duplication, no
  Wattpilot command side effects, and the direct Fronius dashboard hook.
- Verified with targeted Wattpilot startup/runtime-status tests and the full
  hardware-free unittest suite.
- Kept the change limited to dashboard/status publication, runtime transport
  observation, README, tests, and backlog; no Manual mode, Auto/Eco charge
  policy, reconnect-loop ownership, configuration defaults, D-Bus path names,
  or MQTT topic names were changed.

### Completed 2026-07-09 - Investigate Venus EVCS Overview Tile Outage Text

Completion note:

- Investigated the current upstream Victron `gui-v2` EVCS overview tile source.
- Confirmed `components/widgets/EvcsWidget.qml` renders the overview tile title
  from a fixed translated `EVCS` label and reads single-charger detail text from
  standard `/Status`, `/Mode`, `/Session/Energy`, and `/Session/Time` values.
- Confirmed the overview tile does not read the EV-charger service
  `/CustomName` or `/StatusLiteral`, so there is no safe es-ESS-only
  tile-title path to show `Wattpilot not reachable` there without changing
  truthful `/Status` or `/Mode` values or patching Venus GUI behavior.
- Updated README to document the Venus/GX overview-tile limitation and to point
  users to the EV-charger detail view, D-Bus, MQTT runtime status, es-ESS
  service messages, and SolarOverheadDistributor messages for specific
  Wattpilot transport-outage text.
- Kept the change documentation/backlog-only; no production code, tests,
  configuration defaults, D-Bus path names, MQTT topic names, Manual mode, or
  Auto/Eco charging behavior were changed.

### Completed 2026-07-09 - Replace Wattpilot Recursive Reconnect With A Bounded Connection Loop

Completion note:

- Replaced recursive `run_forever()` calls from the Wattpilot WebSocket close
  callback with a single daemon connection worker loop in `Wattpilot.py`.
- Added an idempotent `connect()` guard so repeated wake-up/start calls do not
  create duplicate live WebSocket worker threads.
- Updated `disconnect(auto_reconnect=False)` to set a stop event, close the
  WebSocket once, and prevent further reconnect attempts.
- Preserved existing Wattpilot event callbacks used by
  `WattpilotRuntimeStatus.py`; close callbacks now only update transport state
  and emit `WS_CLOSE`.
- Added `tests/test_wattpilot_client.py` with fake-WebSocket coverage for
  idempotent connect behavior, non-recursive close handling, worker-loop
  reconnect, and clean disconnect stopping.
- Updated README, `docs/wattpilot-architecture.md`, and
  `docs/service-inventory.md` to document the connection-worker ownership and
  manual outage/recovery validation path.
- Live GX/Wattpilot validation confirmed baseline reachability, outage
  publication (`/Connected=0`, `Wattpilot not accessible`, `Wattpilot not
  reachable`, `TelemetryHealthy=0`), recovery publication
  (`/Connected=1`, normal custom name, `TelemetryHealthy=1`), and repeated
  outage/recovery without duplicate WebSocket workers or worker-loop
  exceptions.
- Kept the change limited to Wattpilot client lifecycle, tests, and docs; no
  Manual mode, Auto/Eco charge policy, phase switching, grid guards,
  configuration defaults, D-Bus path names, or MQTT topic names were changed.

## Backlog

### P0 - Guard Manual Wattpilot Mode From D-Bus/VRM Control Writes

Problem:

Normal Wattpilot Manual mode must remain user-controlled. The current controller
reports Manual mode and avoids Auto/Eco policy control in several paths, but the
writable EV-charger D-Bus callbacks can still send direct Wattpilot commands for
current, phase, start, and stop without first proving Auto/Eco control is active.

Evidence:

- `FroniusWattpilot.py` registers `/SetCurrent`, `/Mode`, and `/StartStop` as
  writable paths with `_froniusHandleChangedValue()` callbacks.
- `_froniusHandleChangedValue()` can call `self.wattpilot.set_power()`,
  `self.wattpilot.set_phases()`, and `self.wattpilot.set_start_stop()` for
  `/SetCurrent` and `/StartStop`.
- `switchMode()` intentionally calls `self.wattpilot.set_mode()` when changing
  between Manual and Auto, which is a separate mode-selection concern from
  controlling an already-Manual charging session.
- Tests cover Manual mode against Auto/Eco allowance and telemetry guards, but
  do not lock the writable D-Bus command boundary.

Implementation:

- Add a small helper such as `wattpilotAutoControlSelected()` or reuse a
  carefully reviewed `autoControlActive()` check for D-Bus command writes.
- Allow `/Mode` handling to switch modes according to the intended UX, but block
  `/SetCurrent` and `/StartStop` from sending Wattpilot current/phase/start/stop
  commands while Wattpilot is in Manual mode.
- Keep Manual mode status reporting to VRM/D-Bus/MQTT unchanged.
- Publish an operational service message when a VRM/D-Bus command is ignored
  because Wattpilot is in Manual mode.
- Make the guard conservative when Wattpilot mode telemetry is missing: do not
  send current, phase, start, or stop commands unless Auto/ECO control is known
  to be selected.

Files to change:

- `FroniusWattpilot.py`
- `tests/test.py` or `tests/test_eco_pv_policy.py`
- Possibly `README.md` if the Manual-mode command boundary is clarified for
  users.
- Possibly `config.sample.ini` only if related user-facing config text changes.

Files to add:

- None expected.

Tests:

- Add tests proving `/SetCurrent` does not call `set_power()` or `set_phases()`
  while Wattpilot reports Manual/default mode.
- Add tests proving `/StartStop` does not call `set_start_stop()` while
  Wattpilot reports Manual/default mode.
- Add tests proving `/Mode` can still intentionally switch to Auto/ECO and back
  if that remains supported behavior.
- Add tests proving missing Wattpilot mode telemetry does not allow control
  commands.

Expected coverage:

- Manual charging cannot be started, stopped, phase-switched, or current-limited
  by es-ESS command callbacks.
- Auto/Eco command behavior remains unchanged.
- Manual status reporting still updates VRM/D-Bus/MQTT.

Manual validation:

- Required on a Wattpilot or representative test system.

Manual test steps:

1. Put Wattpilot in Manual mode from the Fronius app.
2. Confirm es-ESS reports Manual mode to VRM/D-Bus/MQTT.
3. Attempt VRM/D-Bus `/SetCurrent` and `/StartStop` writes.
4. Confirm Wattpilot does not change current, phase mode, start state, or stop
   state.
5. Switch to Auto/ECO through the intended UI path.
6. Confirm Auto/Eco PV control still starts, stops, and adjusts only under valid
   PV/no-grid conditions.

Risks and dependencies:

- Over-blocking `/Mode` could prevent the intended VRM workflow for selecting
  Auto/ECO. Keep mode selection separate from current/start/phase control.
- Runtime mode telemetry may briefly be unavailable during reconnect; the guard
  should fail closed for direct charge commands.

Open questions:

- Should `/StartStop=Stop` be allowed as an emergency stop even while Wattpilot
  is Manual, or should Manual mode be fully untouched by es-ESS except for
  reporting?

Done criteria:

- Manual-mode command-boundary tests pass.
- Existing Wattpilot behavior tests pass.
- No new control commands are sent in Manual mode except any explicitly
  approved mode-selection behavior.

### P2 - Publish Venus EVCS Session Energy And Time Paths

Problem:

The standard Venus OS / GX EVCS overview tile can show `--kWh` for the
FroniusWattpilot service even while live EV power is displayed. Current
`gui-v2` sources read the overview tile's session energy and timer from
`/Session/Energy` and `/Session/Time`, but es-ESS currently publishes the same
concepts only on older/existing paths.

Evidence:

- Upstream Victron `gui-v2` `components/widgets/EvcsWidget.qml` reads
  `serviceUid + "/Session/Energy"` for the kWh value and
  `serviceUid + "/Session/Time"` for the charging-time value.
- `FroniusWattpilot.py` registers and publishes `/Ac/Energy/Forward`.
- `FroniusWattpilot.py` registers and publishes `/ChargingTime`.
- `FroniusWattpilot.py` does not currently register or publish
  `/Session/Energy` or `/Session/Time`.
- Live GX observation showed the EVCS tile displaying `--kWh` while EVCS power
  was present.

Implementation:

- Add `/Session/Energy` and `/Session/Time` to the FroniusWattpilot D-Bus
  service during initialization.
- Keep `/Ac/Energy/Forward` and `/ChargingTime` unchanged for existing
  consumers.
- When Wattpilot session energy is valid and published to `/Ac/Energy/Forward`,
  publish the same kWh value to `/Session/Energy`.
- When energy is reset to `0.0` by the existing reset policy, reset
  `/Session/Energy` at the same time.
- Publish `/Session/Time` from the same `chargingTime` value currently used for
  `/ChargingTime`.
- Do not change Wattpilot commands, Auto/Eco policy, phase switching, grid
  guards, Manual mode, MQTT topics, or configuration defaults.

Files to change:

- `FroniusWattpilot.py`
- `tests/`
- `README.md`
- `BACKLOG.md`
- Possibly `docs/service-inventory.md` if the EV-charger D-Bus contract summary
  is expanded.
- Possibly `docs/wattpilot-architecture.md` if the public D-Bus contract is
  updated there.

Files to add:

- None expected.

Tests:

- Add or update hardware-free tests proving `/Session/Energy` and
  `/Session/Time` are registered at D-Bus service initialization.
- Add tests proving valid Wattpilot `energyCounterSinceStart` publishes the
  same kWh value to `/Ac/Energy/Forward` and `/Session/Energy`.
- Add tests proving reset behavior clears both `/Ac/Energy/Forward` and
  `/Session/Energy`.
- Add tests proving `chargingTime` publishes to both `/ChargingTime` and
  `/Session/Time`.
- Run focused Wattpilot startup/session-path tests.
- Run `python -m py_compile FroniusWattpilot.py`.
- Run the full hardware-free unittest suite.

Expected coverage:

- The Venus/GX EVCS overview tile can display session kWh and session time for
  the es-ESS FroniusWattpilot EV-charger service.
- Existing D-Bus consumers that read `/Ac/Energy/Forward` or `/ChargingTime`
  continue to work.
- Charging behavior remains unchanged.

Manual validation:

- Required on the GX/Venus OS overview screen because this fixes a
  GUI-rendered value.

Manual test steps:

1. Start es-ESS with Wattpilot enabled and a reachable Wattpilot.
2. Start an EV charge and confirm `/Ac/Energy/Forward` and `/Session/Energy`
   both report the current session kWh.
3. Confirm `/ChargingTime` and `/Session/Time` both report the session timer.
4. Confirm the Venus/GX EVCS overview tile no longer shows `--kWh` once
   Wattpilot energy telemetry is available.
5. Disconnect/reconnect according to the configured `ResetChargedEnergyCounter`
   behavior and confirm both energy paths reset consistently.

Risks and dependencies:

- Low implementation risk because this is additive D-Bus publication.
- Venus GUI behavior is outside es-ESS and must be validated on a live GX or
  representative Venus OS UI.
- Avoid changing the existing reset policy while adding the compatibility
  paths.

Open questions:

- Should README document `/Session/Energy` and `/Session/Time` as compatibility
  aliases or as part of the public Wattpilot D-Bus contract?

Done criteria:

- `/Session/Energy` and `/Session/Time` are published with values matching the
  existing energy/time paths.
- Existing session reset behavior is preserved.
- Hardware-free tests and full unittest suite pass.
- Live GX validation confirms the EVCS overview tile displays session kWh when
  Wattpilot telemetry is available.

### P3 - Add A Supported User-Visible Wattpilot Unavailable Indicator

Problem:

es-ESS now publishes truthful Wattpilot transport-outage state on D-Bus, MQTT,
service messages, and SolarOverheadDistributor messages, but the standard Venus
OS / GX EVCS overview tile can still show only generic `EVCS`, `Disconnected`,
and the selected mode such as `Auto`. Users need an obvious supported way to see
that the Wattpilot wallbox itself is unreachable, not merely that the vehicle is
disconnected.

Evidence:

- Live GX validation during a Wattpilot outage showed
  `/CustomName = 'Wattpilot not reachable'`,
  `/StatusLiteral = 'Wattpilot not accessible'`, `/Connected = 0`,
  `/Status = Disconnected`, and `/ModeLiteral = 'Auto'`.
- The completed Venus EVCS overview-tile investigation confirmed current
  upstream `gui-v2` `EvcsWidget.qml` does not read `/CustomName` or
  `/StatusLiteral` for the overview tile.
- Changing `/Status` or `/Mode` only to force overview text would misrepresent
  the charger state to automation and VRM consumers.
- Existing es-ESS service messages and MQTT runtime status contain the specific
  outage text but are not as obvious as the standard overview tile.

Implementation:

- Investigate supported Venus OS / GX surfaces for a communication outage that
  do not misuse the EV-charger `/Status` or `/Mode` contract.
- Candidate approaches include:
  - a small Cerbo/GX dashboard extension or custom overview widget that reads
    `/StatusLiteral`, `/CustomName`, or the Wattpilot runtime-status contract;
  - an upstream `gui-v2` issue or patch to show `/StatusLiteral` for EVCS
    transport outages when present;
  - a truthful notification/alarm path if Venus OS has a supported D-Bus
    contract for service communication alarms;
  - improved retained MQTT status intended for external dashboards.
- Keep the existing standard EV-charger D-Bus values truthful:
  `/Status=Disconnected` and `/Mode=Auto` may both remain correct during a
  transport outage.
- Do not mark the charger as an electrical fault unless the team explicitly
  decides that communication loss should be represented as a charger fault and
  tests the downstream behavior.
- Prefer additive visibility over control-policy changes.

Files to change:

- Possibly `README.md`
- Possibly `docs/service-inventory.md`
- Possibly `docs/wattpilot-architecture.md`
- Possibly `FroniusWattpilot.py` and tests if a supported D-Bus notification or
  status surface is added.
- Possibly a new dashboard/extension artifact if that route is chosen.
- `BACKLOG.md`

Files to add:

- Possibly a small GX/Cerbo extension or documentation page, depending on the
  selected approach.

Tests:

- If production code publishes a new notification/status path, add
  hardware-free tests proving it appears on outage and clears on recovery.
- Keep existing transport-outage tests proving `/Connected`, `/Status`,
  `/StatusLiteral`, `/CustomName`, and service-message behavior.
- Run focused Wattpilot runtime-status/startup tests and the full unittest
  suite for any production-code change.
- If a dashboard/extension is added, include manual or automated rendering
  checks appropriate to that artifact.

Expected coverage:

- A user can clearly identify "Wattpilot not accessible" from a supported UI,
  notification, dashboard, or documented MQTT/D-Bus surface.
- The standard EV-charger state remains truthful for automation and VRM.
- No Wattpilot control behavior changes.

Manual validation:

- Required on a GX/Venus OS system because the desired result is user-visible
  outage presentation.

Manual test steps:

1. Start with Wattpilot reachable and confirm the selected visible indicator is
   normal or absent.
2. Trigger a Wattpilot transport outage.
3. Confirm the selected indicator clearly says the Wattpilot/wallbox is not
   reachable.
4. Confirm `/Status` and `/Mode` remain truthful and compatible.
5. Restore Wattpilot transport and confirm the indicator clears.
6. Repeat outage/recovery to confirm no stale alarms or duplicate messages.

Risks and dependencies:

- Venus OS may not offer a supported alarm/notification path for third-party
  EV-charger communication outages.
- A custom dashboard extension may not affect the standard overview tile.
- Upstream `gui-v2` changes would depend on Victron acceptance and the Venus OS
  release cycle.
- Misusing fault/status enums for display could confuse automation, VRM, and
  dashboards.

Open questions:

- Is a Venus OS service communication alarm available and appropriate for an
  external EV-charger service?
- Is a local Cerbo/GX extension acceptable, or should this be proposed upstream
  to Victron `gui-v2`?
- Should the indicator be always-on in a custom dashboard, or only appear
  during transport outage?

Done criteria:

- A supported visibility route is selected and documented.
- If implemented in es-ESS, outage and recovery behavior is covered by tests.
- Live GX validation confirms the user can clearly see Wattpilot transport
  outage without misleading `/Status` or `/Mode`.

### P2 - Extract Wattpilot Telemetry And Allowance Evaluation Helpers

Depends on:

- Completed Wattpilot decision characterization tests.

Goal:

Reduce `FroniusWattpilot.py` complexity without changing charging behavior.

Problem:

Telemetry freshness and SolarOverheadDistributor allowance checks are core
inputs to Auto/Eco control, but they are mixed into the large controller with
command side effects. This makes later safety review harder than it needs to
be.

Evidence:

- `FroniusWattpilot.py` tracks grid telemetry timestamps, Wattpilot allowance,
  raw overhead, startup grace, allowance drop grace, and related status flags.
- Tests already exercise stale allowance, missing allowance, raw-overhead
  freshness, and telemetry fail-safe behavior.

Implementation:

- Extract pure or mostly pure helper functions/classes for telemetry freshness
  and allowance status.
- Keep D-Bus, MQTT, and Wattpilot command side effects in `FroniusWattpilot.py`
  for this PR.
- Preserve existing config keys, defaults, D-Bus paths, MQTT topics, and public
  runtime-status behavior.
- Move tests or add focused tests for the extracted helpers.

Files to change:

- `FroniusWattpilot.py`
- Tests under `tests/`

Files to add:

- Possibly a small helper module such as `WattpilotDecisionInputs.py`.

Tests:

- Run telemetry and allowance characterization tests.
- Run existing Wattpilot control tests.
- Run the full unittest suite.
- Run `python -m py_compile` for changed Python files.

Expected coverage:

- Stale telemetry behavior is unchanged.
- Missing, malformed, stale, and fresh allowance behavior is unchanged.
- Raw-overhead data still cannot start charging or authorize a phase-up.

Manual validation:

- Not required if the PR is a pure extraction and tests show unchanged behavior.
  Optional live observation is useful before deploying broadly.

Manual test steps:

1. Start es-ESS with Wattpilot enabled on a staging system.
2. Confirm runtime status and Auto/Eco waiting state still publish normally.
3. Temporarily interrupt allowance or grid telemetry.
4. Confirm fail-safe status matches pre-refactor behavior.

Risks and dependencies:

- This code is safety-sensitive. Keep the PR limited to extraction and tests.
- Do not change timing defaults, control commands, or Manual mode behavior.

Open questions:

- Should helper code stay in the same file first, then move to a new module in a
  later PR?

Done criteria:

- Extracted helper behavior matches existing tests.
- No command behavior changes are introduced.
- Full unittest suite passes.

### P2 - Extract Wattpilot Grid-Guard And Battery-Assist Decisions

Depends on:

- Wattpilot decision characterization tests.
- Telemetry and allowance helper extraction.

Goal:

Separate two safety-sensitive Auto/Eco decisions into reviewable helpers while
preserving behavior.

Problem:

Grid-import stopping and battery assist are intentionally conservative but are
currently embedded in the large controller. Keeping the decision logic separate
from command side effects will make future changes easier to reason about.

Evidence:

- `FroniusWattpilot.py` contains `AllowGridCharging`, `GridImportStopW`,
  `GridImportStopSeconds`, `GridTelemetryFreshSeconds`,
  `BatteryAssistEnabled`, `BatteryAssistSocMin`,
  `BatteryAssistMaxSeconds`, `BatteryAssistMaxShortfallW`, and
  `BatteryAssistRecoverySeconds` handling.
- Existing tests cover several no-grid and battery-assist cases, but the code
  path is still intertwined with controller state and status publishing.

Implementation:

- Extract grid-import guard decision logic into a small helper with explicit
  inputs and result reasons.
- Extract battery-assist eligibility, lockout, and recovery decisions into a
  small helper with explicit inputs and result reasons.
- Keep actual `set_power()`, `set_start_stop()`, D-Bus, MQTT, and service
  message side effects in `FroniusWattpilot.py`.
- Preserve current battery-assist invariant: it may only bridge an
  already-running charge and must never start a session or trigger phase-up.

Files to change:

- `FroniusWattpilot.py`
- Tests under `tests/`

Files to add:

- Possibly helper modules for grid guard and battery assist decisions.

Tests:

- Run grid telemetry fail-safe tests.
- Run battery-assist tests.
- Run existing Wattpilot control tests.
- Run the full unittest suite.
- Run `python -m py_compile` for changed Python files.

Expected coverage:

- Auto/Eco still stops on sustained grid import when grid charging is disabled.
- Battery assist still respects SOC, shortfall, duration, and recovery limits.
- Battery assist still cannot start a charge or cause phase-up.
- Manual mode remains unaffected by Auto/Eco guards.

Manual validation:

- Recommended on a staging GX/Wattpilot system because this touches
  safety-sensitive decisions, even if intended as extraction-only.

Manual test steps:

1. Validate Manual mode reporting and non-control behavior.
2. Validate Auto/Eco start from PV allowance.
3. Validate sustained grid import stop.
4. Validate a short PV dip during active charging with battery assist enabled.
5. Validate battery assist lockout and recovery.

Risks and dependencies:

- High safety sensitivity. Keep side effects in the existing controller until
  helper behavior is proven.
- Do not combine with config/default changes.

Open questions:

- Should helper results expose machine-readable reason codes for future runtime
  status, or stay internal for now?

Done criteria:

- Extracted helpers are covered by focused tests.
- Existing behavior tests pass unchanged.
- Manual live validation confirms no unintended grid use.

### P2 - Extract Wattpilot Phase-Switching Decisions

Depends on:

- Wattpilot decision characterization tests.
- Telemetry and allowance helper extraction.

Goal:

Make phase-switching decisions reviewable without introducing a full state
machine yet.

Problem:

One-phase and three-phase switching is a high-impact EV-control behavior. The
current implementation works through controller flags, pending confirmations,
timing guards, current limits, and live phase telemetry inside the large
controller.

Evidence:

- `FroniusWattpilot.py` contains `MinPhaseSwitchSeconds`,
  `PhaseSwitchDelaySeconds`, `ThreePhasePvSurplusStartW`,
  `ThreePhasePvSurplusStopW`, `pendingPhaseSwitchMode`,
  `phaseSwitchCandidateMode`, and phase telemetry confirmation logic.
- Tests cover several phase-switching and fallback behaviors, but the logic is
  still mixed with command issuing and runtime status reporting.

Implementation:

- Extract phase-mode eligibility and target-current decisions into pure helpers
  first.
- Keep actual `set_phases()` and `set_power()` calls in `FroniusWattpilot.py`
  for this PR.
- Preserve current one-phase start behavior, three-phase phase-up threshold,
  three-to-one safety reduction, pending-confirmation behavior, and cooldowns.
- Preserve current D-Bus `/PhaseMode` and runtime-status semantics.

Files to change:

- `FroniusWattpilot.py`
- Tests under `tests/`

Files to add:

- Possibly a small phase-decision helper module.

Tests:

- Run phase-switching tests.
- Add focused helper tests for one-phase, three-phase, cooldown, and fallback
  decisions.
- Run existing Wattpilot control tests.
- Run the full unittest suite.
- Run `python -m py_compile` for changed Python files.

Expected coverage:

- One-phase and three-phase decisions remain unchanged.
- Current is still bounded by configured min/max and Wattpilot effective limit.
- Phase-up still requires real fresh PV allowance and timing guards.
- Battery assist and raw overhead still cannot trigger phase-up.

Manual validation:

- Required before production deployment because phase switching affects live EV
  charging.

Manual test steps:

1. Validate one-phase Auto/Eco start from fresh allowance.
2. Validate one-to-three phase-up after the configured stable PV delay.
3. Validate three-to-one fallback when PV drops below the three-phase stop
   threshold.
4. Validate pending phase confirmation and runtime status.
5. Validate no phase changes occur in Manual mode.

Risks and dependencies:

- Phase switching is safety-sensitive and user-visible.
- Avoid combining this with grid guard, battery assist, or reconnect changes.

Open questions:

- Should phase-switch helper results include explicit reason strings for logs
  and runtime status?

Done criteria:

- Phase decision helpers are tested.
- Existing phase behavior is preserved.
- Manual staging validation confirms expected phase switching.

### P3 - Refactor Wattpilot Control Into An Explicit State Machine

Depends on:

- Manual command-boundary hardening.
- Config/sample contract.
- README behavior rewrite.
- CI checks.
- Wattpilot architecture boundary documentation.
- Wattpilot decision characterization tests.
- Telemetry, allowance, grid guard, battery assist, and phase decision helper
  extraction.

Goal:

Improve maintainability without changing established behavior.

Problem:

Wattpilot control is safety-sensitive and currently spread across many flags,
timestamps, telemetry freshness helpers, and status/reporting side effects in
one large controller. This is workable but hard to reason about as behavior
grows.

Evidence:

- `FroniusWattpilot.py` contains startup, Manual/Auto mode reflection, grid
  guards, allowance handling, battery assist, phase switching, charge-complete
  hold, runtime D-Bus publishing, MQTT distributor requests, and shutdown
  behavior in one class.
- Existing tests already encode many expected transitions and should become the
  safety net for refactoring.

Implementation:

- Separate telemetry input, PV allowance evaluation, grid guard, battery assist,
  phase switching, and status publishing.
- Introduce explicit state transitions instead of scattered flags and
  timestamps.
- Preserve all public D-Bus and MQTT paths from the runtime-status contract.
- Preserve existing config keys and defaults in `config.sample.ini`.
- Keep Manual mode behavior unchanged.
- Avoid combining this refactor with new features.
- Keep the existing behavior suite passing unchanged.
- Add transition tests for every state-machine edge.

Files to change:

- `FroniusWattpilot.py`
- Possibly new Wattpilot control helper modules
- Tests under `tests/`
- README only if code organization affects documented behavior
- `config.sample.ini` only if config behavior changes, which should be avoided
  for this refactor

Files to add:

- Possibly a dedicated state-machine module and focused test module.

Tests:

- Keep all existing Wattpilot behavior tests passing.
- Add transition tests for start, stop, phase-up, phase-down, stale telemetry,
  grid import, battery assist, charge-complete hold, Manual mode, reconnect, and
  command fault paths.

Expected coverage:

- The controller is easier to reason about and produces one clear reason for
  each stop/start/phase decision.
- Behavior remains compatible with existing tests and public D-Bus/MQTT paths.

Manual validation:

- Required on a Wattpilot/GX system because this touches safety-sensitive
  control flow.

Manual test steps:

1. Validate Manual mode reporting and non-control behavior.
2. Validate Auto/Eco PV-only start.
3. Validate no-grid stop on sustained import.
4. Validate telemetry outage fail-safe.
5. Validate one-to-three and three-to-one phase behavior.
6. Validate battery assist duration and recovery.
7. Validate reconnect and service restart behavior.

Risks and dependencies:

- High regression risk if combined with feature work.
- Requires strong tests and a simple rollback plan before live testing.

Open questions:

- Should the state machine be introduced behind internal helper methods first,
  or moved to a separate module in one PR?

Done criteria:

- Existing behavior is preserved.
- State transitions are explicit and covered by tests.
- Manual live-device validation confirms no unintended grid use or Manual-mode
  control.

## Suggested Implementation Order

This order is intentionally low-risk-first. The P0/P1 labels still show safety
and production impact, but the first PRs avoid live charging-control changes so
the project can build tests, docs, and confidence before touching sensitive
Wattpilot behavior.

1. P2 Venus EVCS session energy/time paths, because it is additive D-Bus UI
   compatibility work and does not change charging control behavior.
2. P3 supported Wattpilot unavailable indicator, because it improves outage
   visibility without changing charging control behavior if a supported surface
   is available.
3. P0 Manual command-boundary hardening, because it protects the most important
   product invariant once the test base is stronger.
4. P2 telemetry and allowance helper extraction, because it is the first
   low-side-effect Wattpilot control extraction.
5. P2 grid-guard and battery-assist helper extraction, because it is more
   safety-sensitive and should follow characterization coverage.
6. P2 phase-switching helper extraction, because phase switching is
   user-visible and high-impact.
7. P3 state-machine refactor, because it needs the previous behavior, config,
   docs, and helper boundaries in place before touching overall control flow.

## Verification Plan

For backlog-only changes:

- Review `BACKLOG.md` for structure, preserved context, and duplicate items.
- Confirm no code, config, or docs besides `BACKLOG.md` were changed.

For implementation PRs:

- Run `python -m py_compile` on changed Python files.
- Run the full unittest suite.
- Run focused Wattpilot tests for any Wattpilot behavior change.
- Run config migration tests for any `_validateConfiguration()` change.
- Run config contract tests for any config/sample/README change.
- Run shell syntax checks for lifecycle script changes where available.
- Document any checks that cannot run without GX/Venus OS, MQTT, D-Bus, or
  Wattpilot hardware.

## User Manual Test Checklist

- Confirm production `config.ini` matches the maintained `config.sample.ini`
  structure after config cleanup.
- Confirm Wattpilot Manual mode can be reported but is not controlled by es-ESS.
- Confirm Auto/Eco starts only from fresh PV allowance.
- Confirm Auto/Eco does not intentionally use grid power when
  `AllowGridCharging=false`.
- Confirm stale grid telemetry blocks starts and stops active Auto/Eco charging.
- Confirm stale or missing allowance blocks starts and stops active Auto/Eco
  after the configured debounce.
- Confirm battery assist only bridges an already-running charge and respects
  SOC, duration, shortfall, and recovery settings.
- Confirm one-phase and three-phase switching follows configured thresholds and
  timing guards.
- Confirm Wattpilot reconnect after outage recovers without duplicate workers.
- Confirm service install/restart/uninstall behavior on a non-production GX or
  staging path.
