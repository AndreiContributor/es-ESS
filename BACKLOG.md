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
- Wattpilot decision helpers live in `WattpilotDecisionInputs.py`,
  `WattpilotSafetyDecisions.py`, and `WattpilotPhaseDecisions.py`.
- PV allowance and battery-reservation coordination come from
  `SolarOverheadDistributor.py`.
- Other integrations include MQTT inverter/export services, Shelly grid and PV
  devices, Fronius smart meters, temperature publishing, D-Bus paths on Venus
  OS, and local/main MQTT brokers.

Current Wattpilot state:

- Auto/Eco PV-only control, no-grid protection, battery assist, telemetry
  freshness, startup grace, raw-overhead freshness, and runtime status reporting
  are already present in code and tests.
- Manual-mode reporting is present, and writable EV-charger command paths are
  guarded so direct current/start/stop/phase commands are accepted only when
  Wattpilot mode telemetry confirms ECO mode.
- The Wattpilot EV-charger service publishes both legacy project energy/time
  paths and the standard Venus `/Session/Energy` and `/Session/Time` paths.
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
- Configuration migration uses idempotent helpers so legacy user configs with
  existing later sections can upgrade without duplicate-section crashes.
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
- Remaining gaps are around UI-format alignment across Venus/VRM surfaces,
  Fronius module packaging evaluation, and completing the Wattpilot
  state-machine dispatch after passive shadow validation.

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

### Completed 2026-07-09 - Guard Manual Wattpilot Mode From D-Bus/VRM Control Writes

Completion note:

- Added a conservative Wattpilot command-boundary helper in
  `FroniusWattpilot.py` that accepts direct `/SetCurrent` and `/StartStop`
  writes only when Wattpilot mode telemetry confirms ECO mode.
- Rejected direct current, phase, start, and stop commands when Wattpilot
  reports Manual/default mode or mode telemetry is unavailable.
- Kept `/Mode` handling separate so VRM/D-Bus can still intentionally switch
  between Manual and Auto/ECO.
- Published an operational service message and refreshed charger info when a
  direct command write is rejected.
- Added `tests/test_wattpilot_command_boundary.py` coverage for blocked
  Manual/default writes, fail-closed missing mode telemetry, preserved ECO
  command behavior, and preserved `/Mode` switching.
- Updated README to clarify that direct VRM current and start/stop controls are
  accepted only while Wattpilot telemetry confirms ECO mode.
- Updated `docs/wattpilot-architecture.md` to document the writable command
  boundary and fail-closed Manual/default telemetry rule.
- Kept the change limited to the D-Bus/VRM command boundary, tests, README,
  architecture docs, and backlog; no Auto/Eco PV policy, phase thresholds, grid
  guards, MQTT topic names, D-Bus path names, or configuration defaults were
  changed.

### Completed 2026-07-09 - Publish Venus EVCS Session Energy And Time Paths

Completion note:

- Added `/Session/Energy` and `/Session/Time` to the FroniusWattpilot
  EV-charger D-Bus service for Venus/GX EVCS overview compatibility.
- Kept existing `/Ac/Energy/Forward` and `/ChargingTime` paths unchanged and
  mirrored the same values to the new session paths.
- Preserved the existing charged-energy reset policy so both energy paths reset
  together and both time paths publish the same `chargingTime` value.
- Added hardware-free tests in `tests/test_wattpilot_session_paths.py` for path
  registration, valid session energy, `onconnect` reset-policy preservation,
  reset clearing, and charging-time mirroring.
- Updated README, `docs/wattpilot-architecture.md`, and
  `docs/service-inventory.md` to document the standard EV-charger session path
  compatibility.
- Kept the change limited to additive D-Bus/MQTT path publication, tests, docs,
  and backlog; no Wattpilot commands, Auto/Eco policy, Manual mode, phase
  switching, grid guards, MQTT topic names, or configuration defaults were
  changed.

### Completed 2026-07-09 - Document Supported Wattpilot Unavailable Indicator Route

Completion note:

- Selected the supported es-ESS visibility route for Wattpilot transport
  outages: EV-charger detail view fields, D-Bus inspection, retained MQTT
  runtime status, es-ESS service messages, and SolarOverheadDistributor
  consumer messages.
- Documented that es-ESS will not publish a synthetic charger fault or change
  `/Status` or `/Mode` only to force outage-specific text into the standard
  Venus/GX EVCS overview tile.
- Kept the standard EV-charger contract truthful during wallbox transport
  outages: `/Connected=0`, `/Status=Disconnected`, and the selected mode such
  as `/Mode=Auto` can remain simultaneously correct.
- Left custom GX dashboard extension work and upstream Victron `gui-v2`
  changes as future explicit product decisions rather than introducing an
  unproven local UI artifact in this task.
- Kept the change documentation/backlog-only; no production code, tests,
  configuration defaults, D-Bus path names, MQTT topic names, Manual mode, or
  Auto/Eco charging behavior were changed.

### Completed 2026-07-09 - Extract Wattpilot Telemetry And Allowance Evaluation Helpers

Completion note:

- Added `WattpilotDecisionInputs.py` for pure Wattpilot decision-input
  evaluation: finite numeric parsing, grid telemetry freshness, assigned
  allowance freshness, minimum-allowance checks, and fresh raw-overhead checks.
- Updated `FroniusWattpilot.py` to delegate telemetry/allowance evaluation to
  the helper while keeping MQTT callbacks, D-Bus publication, service messages,
  Wattpilot command issuing, and mutable controller state in the controller.
- Added focused helper tests in `tests/test_wattpilot_decision_inputs.py`,
  including freshness cutoff behavior and stale/non-finite input rejection.
- Updated `docs/wattpilot-architecture.md` to document the new helper boundary
  and preserve the controller as the command side-effect owner.
- Verified with `py_compile`, focused helper tests, existing Wattpilot
  policy/runtime/startup/session/command-boundary/client tests, and the full
  hardware-free unittest suite.
- Kept the change extraction-only; no Manual mode, Auto/Eco control policy,
  phase thresholds, grid-guard behavior, battery-assist behavior, D-Bus path
  names, MQTT topic names, or configuration defaults were changed.

### Completed 2026-07-09 - Extract Wattpilot Grid-Guard And Battery-Assist Decisions

Completion note:

- Added `WattpilotSafetyDecisions.py` for pure grid-import guard and
  battery-assist decisions.
- Updated `FroniusWattpilot.py` to delegate grid-import debounce, battery-assist
  eligibility, timeout lockout, and recovery timing decisions to the helper.
- Kept Wattpilot commands, mutable controller timestamps, D-Bus/MQTT
  publication, and service messages in `FroniusWattpilot.py`.
- Added focused helper tests in `tests/test_wattpilot_safety_decisions.py`.
- Updated `docs/wattpilot-architecture.md` to document the new helper boundary.
- Kept the change extraction-only; no Manual mode, Auto/Eco charging policy,
  phase thresholds, D-Bus path names, MQTT topic names, configuration defaults,
  or Wattpilot command side effects were changed.

### Completed 2026-07-10 - Extract Wattpilot Phase-Switching Decisions

Completion note:

- Added `WattpilotPhaseDecisions.py` for pure phase threshold, desired phase,
  target-current, distributor-request, and phase-up timing decisions.
- Updated `FroniusWattpilot.py` to delegate those calculations while keeping
  `set_phases()`, `set_power()`, pending confirmation, D-Bus/MQTT publication,
  service messages, and mutable controller timers in the controller.
- Added focused helper tests in `tests/test_wattpilot_phase_decisions.py`.
- Updated `docs/wattpilot-architecture.md` to document the new helper boundary.
- Verified with `py_compile`, focused phase helper tests, existing Wattpilot
  Eco/PV policy tests, and the full hardware-free unittest suite.
- Kept the change extraction-only; no Manual mode, Auto/Eco charging policy,
  phase thresholds, D-Bus path names, MQTT topic names, configuration defaults,
  or Wattpilot command side effects were changed.

### Completed 2026-07-10 - Stop Auto Control After Confirmed Wattpilot Disconnect

Completion note:

- Fixed the Wattpilot car-disconnect debounce so a stale active Wattpilot model
  status can only hold `carConnected=false` during the configured confirmation
  window.
- After `CarDisconnectConfirmSeconds`, a physical disconnect now wins, clears
  the effective connected state, reports `Disconnected`, and prevents Auto/Eco
  current or phase control from continuing until the car is connected again.
- Added regression tests for the short transient disconnect window, the stale
  charging-status disconnect field case, and the full `_update()` path.
- Updated `docs/wattpilot-architecture.md` with the confirmed-disconnect safety
  invariant.
- Kept the change limited to disconnect handling; no Manual mode command
  ownership, grid policy, battery-assist thresholds, phase thresholds, D-Bus
  path names, MQTT topic names, or configuration defaults were changed.

### Completed 2026-07-10 - Add Wattpilot Control-State Shadow Selector

Completion note:

- Added `WattpilotControlState.py` with explicit pure state names and selection
  order for the existing `FroniusWattpilot._update()` branch routing.
- Added `tests/test_wattpilot_control_state.py` before implementation and used
  it to lock safety ordering: transport outage, stale grid telemetry, grid
  import phase-down/stop, pending phase switch, confirmed disconnect, charging,
  not-charging, external low-price, phase-switching, and unknown model states.
- Wired `FroniusWattpilot.py` to run the selector as a passive shadow check
  beside the existing branch flow. Matching cycles stay quiet; mismatches are
  logged as warnings with the relevant input snapshot.
- Kept existing Wattpilot command dispatch, D-Bus/MQTT publication, service
  messages, timers, and Auto/Eco policy in the controller. The selector does
  not issue commands or publish state.
- Updated `docs/wattpilot-architecture.md` to document the new helper boundary
  and the production-validation stage before the selector owns dispatch.
- Verified with the new selector tests, existing Wattpilot policy regression
  tests, syntax checks, and the full hardware-free unittest suite.
- Kept the change behavior-preserving except for diagnostic warning logs on a
  shadow-selector mismatch; no Manual mode, Auto/Eco charging policy, phase
  thresholds, D-Bus path names, MQTT topic names, or configuration defaults
  were changed.

## Backlog

### P4 - Winter Validate Wattpilot Grid-Import Shadow Branches

Goal:

Use natural low-PV / higher-load winter conditions to live-validate the
Wattpilot control-state shadow selector on grid-import and stale-telemetry
branches that are difficult to exercise safely during summer surplus.

Problem:

Summer production and available battery energy made sustained grid import
unlikely during the initial production validation. The shadow selector already
showed zero mismatches across normal Manual, Auto/Eco start, active charging,
battery assist, transport outage/recovery, disconnect/reconnect, one-to-three
phase switching, and three-to-one fallback paths. The remaining live coverage
gap is the no-grid safety path during real sustained import or grid-telemetry
outage.

Implementation:

- Wait for natural winter or low-PV operating conditions rather than forcing an
  artificial grid-import event.
- During representative winter Auto/Eco charging, check logs for
  `Wattpilot control-state shadow mismatch`.
- If sustained grid import naturally occurs with `AllowGridCharging=false`,
  confirm the existing grid-import guard either phase-downs first when safe or
  stops Auto/Eco charging.
- If a real grid-meter / D-Bus telemetry outage occurs, confirm Auto/Eco blocks
  starts or stops active charging according to the existing fail-safe policy.
- Do not change Wattpilot settings, force grid import, disconnect critical
  telemetry, or modify the production energy system only to satisfy this
  validation item.

Files to change:

- Possibly `BACKLOG.md` only, when recording the result.

Tests:

- Existing unit tests already cover stale grid telemetry and grid-import guard
  ordering.
- No new automated tests are required unless the winter run reveals a mismatch
  or unclear diagnostic output.

Manual validation:

1. Run normal winter Auto/Eco charging with `AllowGridCharging=false`.
2. Search the live log:
   `grep -i "Wattpilot control-state shadow mismatch" /data/log/es-ESS/current.log`
3. If grid import occurs, capture the relevant log window around the guard
   decision.
4. Confirm there are no selector mismatches.
5. Record the result in this backlog item.

Done criteria:

- Winter or naturally low-PV validation records no control-state shadow
  mismatches for any observed grid-import or stale-telemetry branch.
- If those branches still do not occur naturally, the item records that result
  without forcing unsafe or unrealistic system behavior.

### P4 - Investigate EVCS UI Formatting Alignment

Problem:

After es-ESS publishes correct Wattpilot EVCS session energy/time values, the
Venus/GX web overview and VRM/mobile detail views may display the same
underlying values with different precision, units, rounding, and refresh
cadence. This can look inconsistent even though the D-Bus values are correct.

Evidence:

- Live GX validation confirmed `/Session/Energy` mirrors
  `/Ac/Energy/Forward`, and `/Session/Time` mirrors `/ChargingTime`.
- The Venus/GX overview tile showed real EVCS energy and time rather than
  `--kWh`.
- The web overview and mobile/detail views formatted similar values
  differently, such as rounded power on the overview, energy in Wh versus kWh,
  and `00h 07m` versus `6m, 15s`.
- These formatting differences come from UI presentation layers, not from the
  es-ESS D-Bus numeric values.

Implementation:

- Treat this as a UI-layer investigation, not an es-ESS control or D-Bus-value
  change.
- Identify where Venus/GX web overview formatting is implemented for EVCS
  power, session energy, and session time.
- If local Venus/GX customization is acceptable, evaluate a small UI patch or
  extension that formats overview values closer to the mobile/detail view.
- If broad consistency is desired, consider documenting or proposing an
  upstream Victron `gui-v2` formatting improvement.
- Do not change es-ESS numeric units, round published D-Bus values, or publish
  strings on numeric paths to force UI alignment.

Files to change:

- Possibly documentation only.
- Possibly local Venus/GX UI or extension files if that route is explicitly
  selected.
- Possibly no es-ESS production code.
- `BACKLOG.md`

Files to add:

- Possibly a local UI patch note, custom dashboard extension, or upstream issue
  reference.

Tests:

- If no es-ESS code changes are made, no Python tests are required.
- If a UI artifact is added, validate rendering on the target GX/Venus OS UI.
- Recheck D-Bus values to prove `/Session/Energy`, `/Ac/Energy/Forward`,
  `/Session/Time`, and `/ChargingTime` remain numeric and truthful.

Expected coverage:

- The team has a clear decision on whether cosmetic web/mobile formatting
  alignment is worth a UI customization or upstream proposal.
- es-ESS continues publishing precise numeric D-Bus values for automations,
  VRM, MQTT consumers, and dashboards.

Manual validation:

- Required on the relevant UI surface because this is a presentation concern.

Manual test steps:

1. Start an EV charging session and confirm es-ESS D-Bus values are correct.
2. Capture Venus/GX web overview formatting for power, energy, and time.
3. Capture VRM/mobile detail formatting for the same values at about the same
   time.
4. If a UI patch is tested, confirm the display alignment improves without
   losing useful precision or breaking standard units.

Risks and dependencies:

- Local Venus/GX UI patches may be overwritten by Venus OS updates.
- VRM/mobile formatting is controlled by Victron app/cloud UI behavior and is
  not realistically changeable from es-ESS.
- Changing es-ESS numeric outputs for display consistency would reduce data
  quality and risk breaking consumers.

Open questions:

- Is local GX/web formatting consistency important enough to maintain a custom
  UI patch?
- Should formatting feedback be proposed upstream to Victron instead?

Done criteria:

- A decision is documented: no change, local UI customization, or upstream
  proposal.
- Any implemented UI-only change is validated visually.
- es-ESS D-Bus numeric contracts remain unchanged.

### P3 - Evaluate Fronius Module Packaging

Goal:

Decide whether Fronius-related root modules should move into a package without
disrupting Venus OS deployment or existing imports.

Problem:

The repository root contains several Fronius-focused modules, including
`FroniusWattpilot.py`, `FroniusSmartmeterJSON.py`,
`FroniusSmartmeterRS485.py`, `Wattpilot.py`, `WattpilotRuntimeStatus.py`, and
Wattpilot decision helpers. Grouping them could improve navigation, but moving
files is a cross-cutting import and deployment refactor.

Implementation:

- Inventory all root-level Fronius and Wattpilot modules and their imports.
- Check `es-ESS.py`, service initialization, tests, install scripts, and any
  documented command examples for direct root-module assumptions.
- Decide between keeping the flat service-module layout, introducing a
  `fronius`/`integrations/fronius` package, or adding compatibility wrappers.
- If moving files, make the package refactor a standalone PR with no charging
  behavior changes.
- Do not combine this with Wattpilot safety, phase-switching, or state-machine
  changes.

Files to change:

- Possibly Fronius/Wattpilot Python modules and imports.
- Possibly tests under `tests/`.
- Possibly README and architecture/service-inventory docs.
- `BACKLOG.md`

Tests:

- Run repository syntax checks.
- Run the full hardware-free unittest suite.
- Run any import-focused tests added for package compatibility.

Expected coverage:

- Runtime imports still work from the service entry point.
- Existing tests can import the moved or wrapped modules.
- Venus OS deployment paths and service scripts remain compatible.

Risks and dependencies:

- Root-module imports may be used by tests, user scripts, or deployment
  assumptions.
- Venus OS service startup is sensitive to `PYTHONPATH` and working-directory
  assumptions.
- Compatibility wrappers may be worthwhile for one release if external imports
  are plausible.

Done criteria:

- A packaging decision is documented.
- Any file move is isolated from behavior changes and covered by import tests.
- Full hardware-free tests pass after the packaging change.

### P3 - Complete Wattpilot Control State-Machine Dispatch

Depends on:

- Manual command-boundary hardening.
- Config/sample contract.
- README behavior rewrite.
- CI checks.
- Wattpilot architecture boundary documentation.
- Wattpilot decision characterization tests.
- Telemetry, allowance, grid guard, battery assist, and phase decision helper
  extraction.
- Wattpilot control-state shadow selector live validation with no mismatches.

Goal:

Improve maintainability without changing established behavior by making the
already-tested explicit state selector own `_update()` dispatch.

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
- `WattpilotControlState.py` now defines the intended branch order and
  `FroniusWattpilot.py` passively logs selector mismatches, but the existing
  controller branch flow still owns actual dispatch.

Implementation:

- First run the shadow selector in production during normal Wattpilot use and
  confirm there are no `Wattpilot control-state shadow mismatch` warnings.
- Replace the current `_update()` branch ladder with dispatch from
  `WattpilotControlState.select_control_state()`.
- Keep telemetry input, PV allowance evaluation, grid guard, battery assist,
  phase switching, status publishing, and command side effects in their
  existing ownership boundaries unless a smaller helper extraction is required.
- Introduce explicit transition handlers around the selected state instead of
  adding new scattered flags and timestamps.
- Preserve all public D-Bus and MQTT paths from the runtime-status contract.
- Preserve existing config keys and defaults in `config.sample.ini`.
- Keep Manual mode behavior unchanged.
- Avoid combining this refactor with new features.
- Keep the existing behavior suite passing unchanged.
- Extend transition tests for every state-machine dispatch edge.

Files to change:

- `FroniusWattpilot.py`
- Possibly new Wattpilot control helper modules
- Tests under `tests/`
- README only if code organization affects documented behavior
- `config.sample.ini` only if config behavior changes, which should be avoided
  for this refactor

Files to add:

- Possibly no new files if `WattpilotControlState.py` remains sufficient.
- Possibly focused dispatch tests if they are clearer than extending existing
  policy tests.

Tests:

- Keep all existing Wattpilot behavior tests passing.
- Add transition tests for start, stop, phase-up, phase-down, stale telemetry,
  grid import, battery assist, charge-complete hold, Manual mode, reconnect, and
  command fault paths.

Expected coverage:

- The controller is easier to reason about and dispatches each cycle from one
  explicit selected state.
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

- How long should the passive shadow selector run on the live GX/Wattpilot
  before dispatch is switched to the selector?

Done criteria:

- Production validation finds no selector mismatch warnings during representative
  Manual, Auto/Eco, disconnect, stale-telemetry, phase-switch, and cloud-dip
  scenarios.
- Existing behavior is preserved.
- State selection owns `_update()` dispatch and is covered by tests.
- Manual live-device validation confirms no unintended grid use or Manual-mode
  control.

## Suggested Implementation Order

This order is intentionally low-risk-first. The P0/P1 labels still show safety
and production impact, but the first PRs avoid live charging-control changes so
the project can build tests, docs, and confidence before touching sensitive
Wattpilot behavior.

1. P3 state-machine refactor, because it needs the previous behavior, config,
   docs, and helper boundaries in place before touching overall control flow.
2. P3 Fronius module packaging evaluation, because it is a cross-cutting
   import/deployment refactor and should stay separate from behavior changes.
3. P4 EVCS UI formatting alignment, because it is cosmetic and should stay
   separate from the es-ESS numeric D-Bus contract.

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
