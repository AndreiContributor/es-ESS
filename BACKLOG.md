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
- The remaining known validation gap is winter live validation of grid-import /
  stale-telemetry control branches under natural low-PV conditions.

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

### Completed 2026-07-10 - Complete Wattpilot Control State-Machine Dispatch

Completion note:

- Updated `FroniusWattpilot._update()` so `WattpilotControlState` now owns the
  explicit branch selection for each duty cycle.
- Preserved the safety-sensitive evaluation order: stale no-grid telemetry
  short-circuits before grid-import checks, grid import is evaluated before
  pending phase-switch reconciliation, and pending phase-switch reconciliation
  is evaluated before disconnect/model-status routing.
- Moved the existing side-effect bodies behind explicit controller dispatch
  handlers while keeping Wattpilot commands, D-Bus/MQTT publication, service
  messages, timers, and mutable Auto/Eco state in `FroniusWattpilot.py`.
- Added a dispatch-ownership regression test proving `_update()` follows the
  selected control state rather than falling back to the old model-status
  ladder.
- Updated `docs/wattpilot-architecture.md` to document selector-owned dispatch
  and the preserved command boundary.
- Verified with selector tests, Wattpilot policy/runtime regression tests,
  syntax checks, and the full hardware-free unittest suite.
- Kept the change behavior-preserving; no Manual mode command ownership,
  Auto/Eco charging policy, phase thresholds, D-Bus path names, MQTT topic
  names, or configuration defaults were changed.

### Completed 2026-07-10 - Release Auto/Eco Limits When Entering Manual Mode

Completion note:

- Investigated live logs showing a charge that started in Auto/Eco one-phase
  mode, then moved to Manual/default mode while Wattpilot remained constrained
  to one phase.
- Added a one-time Manual-entry release path for both explicit VRM `/Mode`
  Auto-to-Manual writes and observed Wattpilot ECO-to-Default transitions.
- The release clears Auto/Eco transition state, sets Wattpilot phase selection
  back to automatic/unrestricted mode, and restores the configured effective
  maximum current without sending a Manual start or stop command.
- Added regression tests proving Manual entry releases stale Auto/Eco phase and
  current limits once and does not repeat those commands while Manual remains
  active.
- Updated README and `docs/wattpilot-architecture.md` to document the approved
  Manual-mode exception: es-ESS does not control normal Manual charging, but it
  may release its own stale Auto/Eco constraints when Manual is selected.
- Kept normal Manual `/SetCurrent` and `/StartStop` command rejection unchanged.

### Completed 2026-07-10 - Evaluate Fronius Module Packaging

Completion note:

- Inventoried the Fronius and Wattpilot root modules and their current import
  assumptions.
- Confirmed active services are loaded from `es-ESS.py` by root module/class
  name through `_checkAndEnable()`, so service names such as
  `FroniusWattpilot` and `FroniusSmartmeterJSON` currently double as import
  contracts.
- Confirmed `FroniusWattpilot.py`, `esESSService.py`, and the hardware-free
  tests still use direct root imports or direct root file loading for
  `Wattpilot.py`, `WattpilotRuntimeStatus.py`, and Wattpilot decision helpers.
- Confirmed Venus OS deployment runs `/data/es-ESS/es-ESS.py` directly through
  `service/run`, making root-module imports the lowest-risk layout for the
  current service bundle.
- Decided to keep the flat root service-module layout for now. A future
  `fronius` or `integrations/fronius` package move should be a standalone
  compatibility refactor with root wrappers or service-loader changes, explicit
  import tests, and live startup validation.
- Updated `docs/service-inventory.md` with the module-layout decision and the
  rule not to combine package refactors with Wattpilot control, safety,
  phase-switching, or runtime-status changes.
- Kept the change documentation/backlog-only; no production code, tests,
  imports, configuration defaults, D-Bus paths, MQTT topics, Manual mode, or
  Auto/Eco charging behavior were changed.

### Completed 2026-07-10 - Investigate EVCS UI Formatting Alignment

Completion note:

- Confirmed es-ESS publishes truthful numeric Wattpilot EVCS values:
  `/Session/Energy` mirrors `/Ac/Energy/Forward`, and `/Session/Time` mirrors
  `/ChargingTime`.
- Inspected current upstream Victron `gui-v2` sources for the EVCS overview,
  list, and detail surfaces.
- Confirmed `components/widgets/EvcsWidget.qml` reads `/Session/Energy` as
  kWh through a compact quantity label and formats `/Session/Time` with
  `HH:MM` once the value reaches 60 seconds, otherwise `HH:MM:SS`.
- Confirmed `pages/evcs/EvChargerPage.qml` uses `QuantityTableSummary` for the
  detail page and formats charging time through `Utils.formatAsHHMM(...)`.
- Confirmed `pages/evcs/EvChargerListPage.qml` summarizes EVCS power and
  energy through the standard quantity-table model.
- Decided not to change es-ESS numeric D-Bus values, not to round or publish
  display strings for UI alignment, and not to maintain a local GX/Venus UI
  patch for this cosmetic difference.
- Documented in README that EVCS precision, unit display, and charging-time
  text are controlled by Victron UI components and may differ between
  overview, list, and detail surfaces even when the underlying D-Bus values are
  correct.
- Kept the change documentation/backlog-only; no production code, tests,
  configuration defaults, D-Bus paths, MQTT topics, Manual mode, or Auto/Eco
  charging behavior were changed.

## Backlog

### P2 - Add Bounded Timeouts For SolarOverheadDistributor HTTP Consumers

Goal:

Keep SolarOverheadDistributor responsive when a configured HTTP consumer,
status endpoint, or power endpoint is slow, offline, or accepts a connection
without returning.

Problem:

`SolarOverheadDistributor` configured HTTP consumers call `requests.get()`
without a timeout. A hung consumer endpoint can block a worker-pool thread
during allowance updates, state validation, or power polling. Because
SolarOverheadDistributor publishes the Wattpilot PV allowance used by Auto/Eco
charging, blocked HTTP consumer work can indirectly delay or stale EV charging
inputs.

Evidence:

- `SolarOverheadDistributor.py` calls `requests.get(url=self.onUrl)` when
  turning on an HTTP consumer.
- `SolarOverheadDistributor.py` calls `requests.get(url=self.offUrl)` when
  turning off an HTTP consumer.
- `SolarOverheadDistributor.py` calls `requests.get(url=self.statusUrl)` when
  validating HTTP consumer state.
- `SolarOverheadDistributor.py` calls `requests.get(url=self.powerUrl)` when
  fetching HTTP consumer power.
- Other HTTP polling services, such as `FroniusSmartmeterJSON`, `Shelly3EMGrid`,
  and `ShellyPMInverter`, already use bounded request timeouts based on poll
  interval.

Implementation:

- Add a bounded HTTP timeout for SolarOverheadDistributor consumer requests.
- Prefer a small configurable default only if product intent requires it;
  otherwise use an internal constant that is safely shorter than the
  distributor update cadence.
- Apply the timeout consistently to on, off, status, and power requests.
- Treat timeout exceptions as failed validation/poll attempts and preserve the
  existing exception logging behavior.
- Avoid changing the allocation algorithm or Wattpilot allowance semantics in
  the same change.

Files to change:

- `SolarOverheadDistributor.py`
- Possibly `config.sample.ini`, `README.md`, and
  `docs/service-inventory.md` only if a user-facing timeout setting is added.

Files to add:

- None expected.

Tests:

- Add hardware-free tests for HTTP consumer control, status validation, and
  power polling that assert `requests.get()` receives the timeout.
- Add a timeout exception test proving a timed-out HTTP consumer does not
  crash the distribution update path.
- Run the full unittest suite.

Expected coverage:

- HTTP consumer on/off/status/power calls are always bounded.
- Timeout exceptions are handled without stopping SolarOverheadDistributor.
- Existing MQTT consumer behavior and Wattpilot allowance distribution are not
  changed.

Manual validation:

- Configure an HTTP consumer against a reachable endpoint and confirm normal
  on/off/status/power behavior.
- Configure or simulate an HTTP endpoint that does not respond and confirm
  SolarOverheadDistributor continues publishing calculations and service
  messages.
- When Wattpilot is enabled, confirm allowance topics continue to update after
  an HTTP consumer timeout.

Manual test steps:

1. Enable `SolarOverheadDistributor` with one test `HttpConsumer:*`.
2. Point `StatusUrl` or `PowerUrl` at a deliberately non-responsive endpoint.
3. Restart es-ESS and tail `/data/log/es-ESS/current.log`.
4. Confirm timeout errors are logged but the distributor worker continues to
   publish `es-ESS/SolarOverheadDistributor/Calculations/OverheadAvailable`.
5. If Wattpilot is active, confirm
   `es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Allowance` continues to
   update.

Risks and dependencies:

- Too-short timeouts may mark slow devices as unavailable unnecessarily.
- Too-long timeouts may still starve the shared worker pool.
- If a new config setting is added, configuration migration and documentation
  must be updated.

Open questions:

- ~~Should HTTP consumer timeout be globally fixed, globally configurable, or
  configurable per `HttpConsumer:*` section?~~ **Decided 2026-07-10:** Add
  `HttpRequestTimeout=5` to `[Common]` in `config.sample.ini`. Wire
  `SolarOverheadDistributor.py` and `FroniusSmartmeterRS485.py` to read that
  key. Leave `FroniusSmartmeterJSON`, `Shelly3EMGrid`, and `ShellyPMInverter`
  on their existing `pollFrequencyMs/2000` formula — their timeout is
  meaningfully tied to their own poll cadence.

Done criteria:

- All SolarOverheadDistributor HTTP consumer requests have bounded timeouts.
- Timeout behavior is covered by hardware-free tests.
- Full unittest suite passes.
- Any new setting is documented in `config.sample.ini`, README, and service
  inventory.

### P2 - Guard MqttPVInverter Zero-Feed-In Against Zero Target Power

Goal:

Make experimental MQTT PV inverter zero-feed-in control safe and deterministic
when the computed target inverter power is zero while one or more inverters are
still producing.

Problem:

`MqttPVInverter._dtuZeroFeedin()` calculates `target =
max(consumption - ZeroFeedinDistance, 0)`, then later calculates
`error / target` for producing inverters. When `target` is `0`, the controller
can raise a division-by-zero exception, skip throttle updates, and leave a
previous OpenDTU limit unchanged exactly when the system intends to reduce or
stop PV output.

Evidence:

- `MqttPVInverter.py` computes `target = max(consumption -
  self.zeroFeedinDistance, 0)`.
- The same method computes `c = share * (error / target)` inside the producing
  inverter loop.
- The broad exception handler logs `Exception during zero feedin calculation`
  but does not publish a safe replacement throttle for the cycle.
- `EnableZeroFeedin` is documented as experimental, but the code path can still
  send real OpenDTU limit commands through configured `DtuControlTopic`
  topics.

Implementation:

- Add an explicit `target <= 0` branch before proportional scaling.
- In that branch, set producing inverters with `DtuControlTopic` to a safe
  minimum throttle, likely `0.0`, unless product intent requires preserving a
  nonzero floor.
- Keep the existing full-throttle behavior when zero-feed-in is inactive or
  prerequisites are not met.
- Avoid changing MQTT topic names, instance config, or non-zero proportional
  scaling behavior in the same change.

Files to change:

- `MqttPVInverter.py`
- Possibly `README.md` and `docs/service-inventory.md` if the zero-target
  behavior is user-facing or the experimental warning changes.

Files to add:

- None expected.

Tests:

- Add a hardware-free test for `_dtuZeroFeedin()` with `target == 0`, producing
  inverter power, and configured `DtuControlTopic`; assert no exception and the
  safe limit is published.
- Add a regression test that nonzero target behavior still adjusts throttle
  proportionally.
- Run the full unittest suite.

Expected coverage:

- Zero-target feed-in cycles do not divide by zero.
- Producing inverters receive an intentional safe throttle command.
- Existing positive-target scaling remains unchanged.

Manual validation:

- On a non-production or carefully observed system, enable `MqttPVInverter`
  with `EnableZeroFeedin=true`.
- Create a condition where consumption minus `ZeroFeedinDistance` is zero or
  below zero while inverter MQTT telemetry still reports production.
- Confirm the OpenDTU limit topic receives the expected safe low throttle and
  es-ESS logs do not show `Exception during zero feedin calculation`.

Manual test steps:

1. Enable one MQTT PV inverter with `DtuControlTopic`.
2. Set `ZeroFeedinDistance` above current consumption so target power becomes
   `0`.
3. Publish inverter power telemetry above `0`.
4. Observe the configured OpenDTU command topic.
5. Confirm a safe limit is published and no divide-by-zero exception appears in
   `/data/log/es-ESS/current.log`.

Risks and dependencies:

- Some OpenDTU setups may interpret `0%` differently from a minimum operating
  limit.
- The desired zero-target throttle floor needs confirmation before treating
  this as production-ready PV shutdown behavior.

Open questions:

- ~~Should zero target command `0%`, `ZeroFeedinScaleStep`, or a configurable
  minimum inverter limit?~~ **Decided 2026-07-10:** Publish `throttle = 0.0`
  (0%) when `target == 0`. `ZeroFeedinScaleStep` is a rate-of-change limiter,
  not a floor value. A configurable minimum is scope creep. Add an early branch
  in `_dtuZeroFeedin()` before the proportional loop; no new config key.

Done criteria:

- Zero-target zero-feed-in behavior is explicit and tested.
- No divide-by-zero exception is possible in `_dtuZeroFeedin()`.
- Manual validation confirms the selected OpenDTU command is accepted by the
  target inverter setup.

### P3 - Fix Local MQTT Reconnect Resubscription Client

Goal:

Ensure local Venus MQTT subscriptions recover correctly after a local MQTT
disconnect/reconnect.

Problem:

`onLocalMqttConnect()` detects local subscriptions but re-subscribes and adds
message callbacks on `mainMqttClient` instead of `localMqttClient`. Initial
subscription registration uses the correct client, so this defect only appears
after a local broker reconnect. It is currently a latent reliability issue
because active services mostly publish to local MQTT, but it can break any
current or future local MQTT subscription after reconnect.

Evidence:

- `registerMqttSubscription()` subscribes `MqttSubscriptionType.Local` topics
  on `self.localMqttClient`.
- `onLocalMqttConnect()` checks `sub.type == MqttSubscriptionType.Local`.
- Inside that local branch, it calls `self.mainMqttClient.subscribe(...)` and
  `self.mainMqttClient.message_callback_add(...)`.
- Existing tests do not cover MQTT reconnect subscription routing.

Implementation:

- Change `onLocalMqttConnect()` to use `self.localMqttClient` for local
  subscription restoration.
- Add a small helper if needed to de-duplicate main/local reconnect logic.
- Keep topic names, QoS, and callback registrations unchanged.

Files to change:

- `es-ESS.py`

Files to add:

- Possibly a new orchestration-focused unit test file under `tests/`.

Tests:

- Add hardware-free tests with fake MQTT clients that register one main and one
  local subscription, invoke `onMainMqttConnect()` and `onLocalMqttConnect()`,
  and assert subscriptions/callbacks are attached to the correct client.
- Run the full unittest suite.

Expected coverage:

- Main reconnect restores only main subscriptions on the main client.
- Local reconnect restores only local subscriptions on the local client.
- Initial registration remains unchanged.

Manual validation:

- On a GX/Venus OS device, restart the local MQTT broker or simulate a local
  reconnect while a local subscription test service is active.
- Confirm subscriptions recover and callbacks receive messages after reconnect.

Manual test steps:

1. Start es-ESS with a test local MQTT subscription enabled.
2. Restart or briefly interrupt the local Venus MQTT broker.
3. Wait for reconnect.
4. Publish a matching local MQTT message.
5. Confirm the callback path runs after reconnect.

Risks and dependencies:

- Low runtime risk if covered by fake-client tests.
- Hardware validation may need a temporary test subscription because most
  active local-MQTT paths publish rather than subscribe.

Open questions:

- Should this change also add reconnect diagnostics for main/local subscription
  counts?

Done criteria:

- Local reconnect uses `localMqttClient` for local topics.
- Main reconnect behavior is unchanged.
- Hardware-free reconnect routing tests pass.

### P3 - Fix Service-Message Connected-State Guard

Goal:

Avoid silently attempting or skipping service-message publication based on the
truthiness of a method object rather than the current MQTT connection state.

Problem:

`publishServiceMessage()` checks `not self.mainMqttClient.is_connected` without
calling it. In common Paho MQTT versions, `is_connected` is a method. The guard
therefore tests the truthiness of the method object instead of the actual
connection state, which can make service-message behavior inaccurate during
startup, disconnects, or reconnects.

Evidence:

- `publishServiceMessage()` returns early only when
  `self.mainMqttClient is None or not self.mainMqttClient.is_connected`.
- Other runtime code tracks `mainMqttClientConnected`, but
  `publishServiceMessage()` does not use it.
- There is no hardware-free test proving service messages are suppressed while
  the main MQTT client is disconnected and published when connected.

Implementation:

- Update the guard to call `is_connected()` when available.
- Preserve compatibility with any older fake or legacy client that exposes a
  boolean `is_connected` attribute instead of a method.
- Consider also checking `mainMqttClientConnected` if it remains the runtime's
  authoritative reconnect flag.
- Keep service-message topic names, retention behavior, and ring-buffer index
  behavior unchanged.

Files to change:

- `es-ESS.py`

Files to add:

- Possibly a new orchestration-focused unit test file under `tests/`.

Tests:

- Add fake-client tests for `publishServiceMessage()` with connected,
  disconnected, and missing-client states.
- Assert disconnected clients do not receive publish calls.
- Assert connected clients publish the expected retained service-message topic.
- Run the full unittest suite.

Expected coverage:

- Service-message publication is gated by actual connection state.
- Existing message indexing and topic formatting remain unchanged.

Manual validation:

- Restart es-ESS with the main MQTT broker available and confirm service
  messages publish normally.
- Temporarily interrupt the main MQTT broker and confirm the log does not fill
  with publish errors from service-message attempts.
- Restore the broker and confirm service messages resume after reconnect.

Manual test steps:

1. Start es-ESS and subscribe to `es-ESS/+/ServiceMessages/#`.
2. Confirm startup service messages appear.
3. Stop or block the main MQTT broker briefly.
4. Confirm es-ESS remains running and does not log repeated publish failures
   from service messages.
5. Restore the broker and confirm later service messages publish again.

Risks and dependencies:

- Some Paho versions or tests may stub `is_connected` differently; keep the
  guard compatibility-focused.
- If `mainMqttClientConnected` can drift from Paho's state, choose one
  authoritative source and test reconnect behavior.

Open questions:

- Should `mainMqttClientConnected` be updated on disconnect and used as the
  single source of truth for publication guards?

Done criteria:

- `publishServiceMessage()` uses the actual MQTT connected state.
- Connected and disconnected cases are covered by unit tests.
- Existing service-message topic contract is unchanged.

### P3 - Align Dormant Service Docs, Sample Config, And Runtime Intent

Goal:

Make README, `config.sample.ini`, service inventory, and runtime service
loading agree about dormant and config-only services.

Problem:

The repository currently presents some dormant or missing services as if they
are configurable active services. This can lead users to enable settings that
the runtime never loads, and it can mislead future implementation work around
grid-setpoint ownership.

Evidence:

- README lists `ChargeCurrentReducer` in the `[Services]` configuration table.
- README includes a full `ChargeCurrentReducer` configuration section.
- `es-ESS.py` has `ChargeCurrentReducer`, `MqttDC`, `FroniusSmartmeterRS485`,
  and `Grid2Bat` runtime initialization commented out.
- `config.sample.ini` does not include `ChargeCurrentReducer`, `MqttDC`, or
  `FroniusSmartmeterRS485` service flags, but it does include `Grid2Bat=false`
  even though no `Grid2Bat.py` exists in this checkout.
- `docs/service-inventory.md` already marks these as dormant/config-only
  follow-up gaps.

Implementation:

- Decide whether each dormant service is supported, intentionally hidden, or
  obsolete.
- For unsupported dormant services, remove or clearly mark user-facing README
  configuration as dormant/unavailable.
- For config-only `Grid2Bat`, either remove it through a config migration or
  document it as reserved/obsolete with a compatibility reason.
- Do not reactivate any dormant service without a separate implementation task,
  tests, service-inventory update, and manual validation plan.
- Keep grid-setpoint ownership explicit: dormant `ChargeCurrentReducer` must
  not be reintroduced while writing `/Settings/CGwacs/AcPowerSetPoint`
  directly outside the shared request combiner.

Files to change:

- `README.md`
- `config.sample.ini`
- `docs/service-inventory.md`
- Possibly `es-ESS.py` only if a config migration removes obsolete flags.

Files to add:

- None expected.

Tests:

- Update or add config contract tests that assert documented active service
  flags match `config.sample.ini` and runtime `_checkAndEnable()` calls.
- Add config migration tests if any obsolete flag is removed or migrated.
- Run the full unittest suite.

Expected coverage:

- Active service docs, sample config, and runtime loading agree.
- Dormant services are clearly marked or removed from user-facing config.
- Grid-setpoint ownership remains centralized for active services.

Manual validation:

- Review an upgraded user config that contains legacy dormant-service flags and
  confirm es-ESS starts cleanly.
- Confirm README no longer tells users to enable a service that the runtime
  cannot start.

Manual test steps:

1. Prepare a legacy `config.ini` containing `ChargeCurrentReducer=true`,
   `MqttDC=true`, `FroniusSmartmeterRS485=true`, and `Grid2Bat=false`.
2. Run configuration migration in a hardware-free test or staging checkout.
3. Confirm the migrated config is valid and startup does not fail on missing or
   dormant services.
4. Compare README, `config.sample.ini`, and `docs/service-inventory.md` for
   matching active/dormant service status.

Risks and dependencies:

- Removing sample keys may surprise users who have legacy configs.
- Reactivating dormant services would be higher risk than documenting/removing
  stale user-facing configuration because some dormant code paths write device
  controls directly.

Open questions:

- Should `Grid2Bat=false` be retained as a compatibility placeholder or removed
  in the next config migration?
- Are any dormant services intended for near-term revival?

Done criteria:

- README, sample config, runtime service loading, and service inventory agree.
- Any config migration is covered by tests.
- No dormant service is reactivated accidentally.

### P4 - Winter Validate Wattpilot Grid-Import Dispatch Branches

Goal:

Use natural low-PV / higher-load winter conditions to live-validate the
Wattpilot control-state dispatch on grid-import and stale-telemetry branches
that are difficult to exercise safely during summer surplus.

Problem:

Summer production and available battery energy made sustained grid import
unlikely during the initial production validation. Selector-owned dispatch is
covered by unit tests and by live validation across normal Manual, Auto/Eco
start, active charging, battery assist, transport outage/recovery,
disconnect/reconnect, one-to-three phase switching, and three-to-one fallback
paths. The remaining live coverage gap is the no-grid safety path during real
sustained import or grid-telemetry outage.

Implementation:

- Wait for natural winter or low-PV operating conditions rather than forcing an
  artificial grid-import event.
- During representative winter Auto/Eco charging, monitor the normal service
  logs for grid-import guard or stale grid-telemetry safety messages.
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
- No new automated tests are required unless the winter run reveals unexpected
  behavior or unclear diagnostic output.

Manual validation:

1. Run normal winter Auto/Eco charging with `AllowGridCharging=false`.
2. Search the live log for relevant guard messages:
   `grep -Ei "Grid import guard|Grid telemetry is missing" /data/log/es-ESS/current.log`
3. If grid import occurs, capture the relevant log window around the guard
   decision.
4. Confirm the observed decision matches the documented no-grid policy.
5. Record the result in this backlog item.

Done criteria:

- Winter or naturally low-PV validation records correct behavior for any
  observed grid-import or stale-telemetry branch.
- If those branches still do not occur naturally, the item records that result
  without forcing unsafe or unrealistic system behavior.

### P2 - Guard NoBatToEV Worker Against None D-Bus Values

Goal:

Prevent `NoBatToEV._update()` from crashing with `TypeError` every two seconds
during the startup window before D-Bus paths deliver their first values.

Problem:

`NoBatToEV._update()` reads twelve D-Bus subscription values and two Wattpilot
per-phase power values, then immediately sums them with no None guard. Every
`DbusSubscription` starts with `value = None` and stays `None` until the backing
D-Bus path publishes. Because the worker fires every 2 seconds and `_update()`
has no try/except, the `TypeError` propagates to the GLib scheduler, which can
suppress the worker silently or log an unhandled exception on every tick until
all paths are populated.

There is an existing guard on `noPhasesDbus.value` (the outer `if` on line 77),
but it only protects the `numberOfPhases` check, not the arithmetic blocks inside.

Evidence:

- `NoBatToEV.py` line 82: `evPower = (Globals.esESS._services["FroniusWattpilot"].wattpilot.power1 + wattpilot.power2 + wattpilot.power3) * 1000` — `power1/2/3` initialize to `None` in `Wattpilot.py`.
- `NoBatToEV.py` lines 84–88: twelve `.value` reads summed directly with no None guard.
- `esESSService.py` registers `DbusSubscription` with `self.value = None` as the initial state.

Implementation:

- Add a None guard before the arithmetic blocks in `_update()`. Either return
  early if any required value is None, or substitute 0 for non-critical
  per-phase PV paths that may be absent on single-phase systems.
- For the Wattpilot power path (line 82), guard against `power1/2/3` being None
  before the multiplication; returning early or substituting 0 is both correct.
- Do not change the grid-setpoint logic, the relay-enable check, or the
  `FroniusWattpilot` service lookup.

Files to change:

- `NoBatToEV.py`

Files to add:

- None expected. Tests for `NoBatToEV` may be added if a test file is created.

Tests:

- Add hardware-free tests with None-valued dbus stubs that confirm `_update()`
  returns without raising when values are None.
- Add a test that confirms the grid-setpoint calculation is correct once all
  values are non-None.
- Run the full unittest suite.

Expected coverage:

- No TypeError during the startup window before D-Bus paths deliver values.
- Correct grid-setpoint behavior once all values are available.

Manual validation:

- Restart es-ESS with NoBatToEV enabled and monitor
  `/data/log/es-ESS/current.log` for the first 30 seconds after startup.
- Confirm no TypeError exceptions appear from the NoBatToEV worker.

Risks and dependencies:

- Substituting 0 for missing per-phase PV values may suppress a grid-setpoint
  request during the startup grace window; this is acceptable since no EV charge
  is present at that point.

Open questions:

- Should missing Wattpilot power values skip the setpoint calculation entirely
  (return early) or treat them as 0 W EV power?

Done criteria:

- `NoBatToEV._update()` does not raise `TypeError` when any D-Bus value is None.
- Startup window behavior is covered by hardware-free tests.
- Full unittest suite passes.

### P2 - Guard SolarOverheadDistributor Distribution Cycle Against None Grid Values

Goal:

Prevent None grid-phase or battery-power values from aborting the entire
SolarOverheadDistributor distribution cycle and leaving all consumers with
their previous allowances.

Problem:

`updateDistribution()` reads `gridL1Dbus.value`, `gridL2Dbus.value`,
`gridL3Dbus.value`, and `batteryPower.value`, then performs arithmetic on them
before any None check. When any of these values is None (device absent,
startup, or grid-loss), the arithmetic raises `TypeError`. The outer
`except Exception` at line 440 catches it and logs at CRITICAL level, but the
distribution cycle is skipped entirely for that tick. All consumers retain
their last-issued allowances indefinitely until a successful cycle runs.
During a prolonged grid outage or BMS disconnect this means consumers that
should be stopped or reduced continue to receive non-zero allowances.

Evidence:

- `SolarOverheadDistributor.py` lines 328–334: `l1Power`, `l2Power`, `l3Power`
  assigned from `self.gridL1Dbus.value` etc. with no None guard; `feedIn =
  (l1Power + l2Power + l3Power) * -1` raises `TypeError` if any is None.
- `SolarOverheadDistributor.py` line 335: `batPower = self.batteryPower.value`
  — also None at startup or when BMS is unavailable.
- `SolarOverheadDistributor.py` line 440: bare `except Exception` catches the
  TypeError and logs `"Exception"` at CRITICAL level without publishing safe
  zero allowances.

Implementation:

- Add None guards for all four D-Bus reads (`gridL1/L2/L3`, `batteryPower`)
  before the feedIn/overhead arithmetic.
- On None, emit a warning and publish safe zeroed overhead values (overhead=0,
  all consumer allowances=0), rather than skipping the cycle entirely.
- Keep the existing CRITICAL-level exception handler for genuinely unexpected
  errors, but move None handling before the arithmetic so it is explicit.
- Do not change the allocation algorithm, consumer-priority logic, or MQTT
  topic names.

Files to change:

- `SolarOverheadDistributor.py`

Files to add:

- None expected.

Tests:

- Add hardware-free tests for `updateDistribution()` with None grid L1/L2/L3
  and None battery power; assert the cycle publishes overhead=0 and does not
  raise.
- Add a regression test that normal non-None values still produce the correct
  overhead calculation.
- Run the full unittest suite.

Expected coverage:

- Distribution cycle completes with zeroed output when grid/battery values are None.
- No TypeError reaches the outer exception handler for None inputs.
- Existing allocation behavior for non-None inputs is unchanged.

Manual validation:

- On a GX/Venus OS device, briefly disconnect the grid meter or BMS from D-Bus
  while SolarOverheadDistributor is active.
- Confirm the log shows a warning (not CRITICAL exception) and consumers receive
  0 W allowances during the outage window.
- Confirm allowances recover when the grid meter reconnects.

Risks and dependencies:

- Publishing overhead=0 during a grid/BMS outage will stop or reduce all
  consumers; this is the safer behavior, but it should be documented.

Open questions:

- Should the None-grid cycle publish a service message so the user is notified
  of the missing input?

Done criteria:

- None grid/battery values are explicitly handled before arithmetic.
- Hardware-free tests cover None inputs.
- Full unittest suite passes.

### P2 - Fix Missing Lock In SolarOverheadDistributor _persistEnergyStats

Goal:

Prevent a `RuntimeError: dictionary changed size during iteration` crash in the
5-minute energy-stats persist cycle.

Problem:

`_persistEnergyStats()` iterates `self._knownSolarOverheadConsumers` without
holding `_knownSolarOverheadConsumersLock`. `onMqttMessage()` adds new
consumers while holding the lock. If a consumer registration MQTT message
arrives during the persist pass, CPython raises `RuntimeError`, aborting the
persist cycle and losing energy data for all consumers after the insertion
point. The existing `_validateNpcConsumerStates()` correctly acquires the lock
before iterating the same dict; `_persistEnergyStats()` does not.

Evidence:

- `SolarOverheadDistributor.py` lines 277–282: `_persistEnergyStats()` iterates
  `self._knownSolarOverheadConsumers` with no lock.
- `SolarOverheadDistributor.py` `onMqttMessage()`: adds consumers under
  `self._knownSolarOverheadConsumersLock`.
- `SolarOverheadDistributor.py` `_validateNpcConsumerStates()`: correctly
  acquires the lock before iterating.

Implementation:

- Acquire `_knownSolarOverheadConsumersLock` (or a copy of the dict under the
  lock) at the start of `_persistEnergyStats()`, matching the pattern in
  `_validateNpcConsumerStates()`.
- Do not change energy-stat persistence logic or MQTT topic names.

Files to change:

- `SolarOverheadDistributor.py`

Files to add:

- None expected.

Tests:

- Add a hardware-free test that registers consumers from one thread while
  `_persistEnergyStats()` runs concurrently and confirms no RuntimeError.
- Run the full unittest suite.

Expected coverage:

- `_persistEnergyStats()` holds the lock during iteration.
- Concurrent consumer registration does not corrupt the persist pass.

Manual validation:

- Tail `/data/log/es-ESS/current.log` with several consumers registered and
  confirm no RuntimeError in the 5-minute persist window.

Risks and dependencies:

- Lock contention is negligible at the 5-minute persist cadence.

Open questions:

- None.

Done criteria:

- `_persistEnergyStats()` acquires the consumer dict lock before iterating.
- Lock-pattern is consistent with `_validateNpcConsumerStates()`.
- Full unittest suite passes.

### P3 - Fix Duplicate OnKeywordRegex MQTT Subscription In SolarOverheadDistributor

Goal:

Remove the duplicate MQTT subscription that causes `onMqttMessage` to fire
twice for every `OnKeywordRegex` consumer registration message.

Problem:

`SolarOverheadDistributor.initMqttSubscriptions()` registers the topic
`es-ESS/SolarOverheadDistributor/Requests/+/OnKeywordRegex` twice with the
same callback. Paho MQTT calls `message_callback_add` twice for the same
pattern, so `onMqttMessage` fires twice per incoming message. On retained
messages this produces double log output on every reconnect; on live
registration messages it triggers double side-effects inside `setValue()`
(e.g., `dbusReportConsumption()` and consumer state updates).

Evidence:

- `SolarOverheadDistributor.py` line 109: first registration of
  `Requests/+/OnKeywordRegex`.
- `SolarOverheadDistributor.py` line 120: second registration of the same
  topic, in the "NPC Consumer Common" block. The comment on line 119 says
  "NPC Consumer Common" suggesting it was split from the basic props block
  but the duplicate was not removed.

Implementation:

- Remove the second `registerMqttSubscription` call for `OnKeywordRegex` at
  line 120.
- Keep the first registration at line 109.
- Do not change any other MQTT subscriptions.

Files to change:

- `SolarOverheadDistributor.py`

Files to add:

- None expected.

Tests:

- Add a hardware-free test that initializes `SolarOverheadDistributor` and
  confirms `OnKeywordRegex` is registered exactly once.
- Run the full unittest suite.

Expected coverage:

- Each consumer registration MQTT message triggers `onMqttMessage` exactly once.

Manual validation:

- Enable a NPC consumer and tail the log after a restart; confirm `OnKeywordRegex`
  messages appear once, not twice, per retained message.

Risks and dependencies:

- Low risk; removing a duplicate registration cannot affect non-duplicate
  subscriptions.

Open questions:

- None.

Done criteria:

- `OnKeywordRegex` is registered once in `initMqttSubscriptions()`.
- Callback fires once per message.
- Full unittest suite passes.

### P3 - Replace eval() With Safe Expression In MinBatteryCharge Config

Goal:

Remove the `eval()` call on the user-controlled `MinBatteryCharge` config value
and replace it with a safe arithmetic parser.

Problem:

`SolarOverheadDistributor.updateDistribution()` evaluates the raw
`MinBatteryCharge` config string with `eval()` after substituting the current
battery SOC. This executes arbitrary Python from `config.ini`. On a Venus OS
device where `config.ini` is writable by a local user or remotely via VRM, a
crafted `MinBatteryCharge` value such as
`__import__('os').system('reboot')` would execute with the process's privileges
on every distribution cycle. Even without a threat actor, a typo in the
equation can produce unexpected behavior that the broad `except Exception`
handler silently swallows.

Additionally, when `batterySoc.value` is None, `str(None)` substitutes the
literal string `"None"`, causing a `NameError` inside `eval()`. The handler
then silently uses `minBatCharge=0`, removing the battery reservation without
any warning beyond a logged exception.

Evidence:

- `SolarOverheadDistributor.py` lines 369–371:
  ```python
  equation = self.config["SolarOverheadDistributor"]["MinBatteryCharge"]
  equation = equation.replace("SOC", str(batSoc))
  minBatCharge = round(eval(equation))
  ```
- The `MinBatteryCharge` value in `config.sample.ini` is a simple arithmetic
  expression like `max(0, (80-SOC)*100)`.
- `batterySoc.value` is `None` at startup and when BMS is unavailable.

Implementation:

- Replace `eval()` with a purpose-built safe evaluator that supports only the
  operations documented in `config.sample.ini`: numeric literals, `SOC`
  substitution, `max()`/`min()`, and basic arithmetic operators (`+`, `-`, `*`,
  `/`).
- A simple approach: parse the substituted string with `ast.literal_eval` after
  confirming it only contains numeric tokens and known functions; or pre-parse
  the expression into a lambda at config-load time using only the `ast` module.
- When `batSoc` is None, emit a warning and use `minBatCharge=0` explicitly
  (the same fallback as today but intentional and logged clearly).
- Keep the `ZeroDivisionError` and general `except Exception` handlers for
  unexpected arithmetic errors.
- Do not change the overhead calculation or consumer-priority logic.

Files to change:

- `SolarOverheadDistributor.py`
- `README.md` and `config.sample.ini` if supported expression syntax is clarified.

Files to add:

- None expected.

Tests:

- Add hardware-free tests for valid `MinBatteryCharge` expressions with known
  SOC values and confirm correct `minBatCharge` output.
- Add a test with `batSoc=None` and confirm `minBatCharge=0` with a warning log
  and no exception.
- Add a test with an invalid/malicious expression and confirm it is rejected
  without executing.
- Run the full unittest suite.

Expected coverage:

- `MinBatteryCharge` evaluation cannot execute arbitrary Python.
- None SOC produces explicit fallback, not a silent swallowed exception.

Manual validation:

- Set `MinBatteryCharge=max(0,(80-SOC)*100)` in config and confirm correct
  reservation at known SOC values.
- Temporarily break the expression to confirm a clear error log.

Risks and dependencies:

- The safe parser must support all expression forms users currently rely on.
  If a user has a more complex expression, document the supported subset.

Open questions:

- Should the supported expression grammar be documented explicitly in
  `config.sample.ini` and README?

Done criteria:

- `MinBatteryCharge` is evaluated without `eval()`.
- Arbitrary Python in config cannot execute.
- Hardware-free tests cover valid expressions, None SOC, and invalid expressions.
- Full unittest suite passes.

### P3 - Replace os.popen Shell Interpolation In getUserTime

Goal:

Remove the shell-injection risk in `Globals.getUserTime()` by replacing
`os.popen()` string interpolation with `subprocess.run()` and explicit
argument passing.

Problem:

`Globals.getUserTime()` constructs a shell command by formatting `userTimezone`
directly into a string passed to `os.popen()`. If `userTimezone` contains
shell metacharacters (e.g., a value such as `UTC"; reboot; echo "` from
`config.ini`), they are executed verbatim by the shell. On a GX device running
as root this is a full privilege-escalation path from config file to shell. The
risk is mitigated by the fact that `config.ini` requires local write access,
but the pattern is unsafe by default and `os.popen()` is deprecated since
Python 3.0.

Evidence:

- `Globals.py` line 23:
  ```python
  usertime = os.popen('TZ=":{0}" date +"%Y-%m-%d %H:%M:%S"'.format(userTimezone)).read()
  ```
- `userTimezone` is read from the `[Common]` section of `config.ini` at
  startup. No sanitization is applied before the substitution.
- `os.popen()` passes the full string to `/bin/sh -c`, which interprets
  metacharacters.

Implementation:

- Replace `os.popen()` with `subprocess.run()` passing `TZ` as an environment
  variable and `date` arguments as a list, eliminating shell interpolation:
  ```python
  import subprocess, os
  env = {**os.environ, "TZ": ":" + userTimezone}
  result = subprocess.run(["date", '+%Y-%m-%d %H:%M:%S'], env=env,
                          capture_output=True, text=True, timeout=3)
  usertime = result.stdout.strip()
  ```
- Add a basic validation of `userTimezone` before use (e.g., allow only
  printable non-whitespace characters with no shell metacharacters).
- Keep the return value and call sites unchanged.

Files to change:

- `Globals.py`

Files to add:

- None expected.

Tests:

- Add a hardware-free test confirming `getUserTime()` calls `subprocess.run()`
  with `TZ` in the environment and not as a shell-interpolated string.
- Add a test with a timezone string containing a shell metacharacter and confirm
  it is rejected or sanitized before subprocess invocation.
- Run the full unittest suite.

Expected coverage:

- `getUserTime()` does not pass user config values to a shell.
- Timezone validation rejects malformed values before subprocess invocation.

Manual validation:

- On a GX/Venus OS device, confirm `getUserTime()` returns the correct local
  time for the configured timezone.

Risks and dependencies:

- `date` command behavior and TZ prefix (`":"`) must be verified on Venus OS's
  embedded shell.
- If the GX device's `date` binary does not support TZ override via environment,
  an alternative (Python `datetime`/`pytz`/`zoneinfo`) should be evaluated.

Open questions:

- Should `getUserTime()` be replaced entirely with Python's `datetime`/`zoneinfo`
  to eliminate the subprocess dependency?

Done criteria:

- `getUserTime()` does not interpolate `userTimezone` into a shell command.
- Shell metacharacters in the timezone config value cannot execute arbitrary
  commands.
- Hardware-free tests cover normal and malformed timezone values.
- Full unittest suite passes.

### P3 - Extract Wattpilot Dispatch Handlers To Named Methods

Goal:

Make each control-state handler in `FroniusWattpilot.dispatchControlState()` a
named method so the dispatch table is a thin router, each branch is individually
testable, and the call site documents intent without requiring inline reading.

Problem:

`dispatchControlState()` is a flat `if`-chain where every control state has its
side-effect body written inline. After `WattpilotControlState` took ownership of
branch selection, the dispatch method became the natural next extraction target.
Each branch is currently 3–15 lines of service messages, VRM-status updates, and
controller resets, making the method hard to scan and impossible to unit-test a
single handler without exercising all the state-selection machinery.

Evidence:

- `FroniusWattpilot.py` `dispatchControlState()` contains inline bodies for:
  `GRID_TELEMETRY_UNSAFE`, `GRID_IMPORT_PHASE_DOWN`, `GRID_IMPORT_STOP`,
  `PENDING_PHASE_SWITCH`, `DISCONNECTED`, `CHARGING`, `NOT_CHARGING`,
  `EXTERNAL_LOW_PRICE`, and `PHASE_SWITCHING`.
- `handleChargingState()` and `handleNotChargingState()` already exist as named
  methods called from the `CHARGING` and `NOT_CHARGING` branches, confirming the
  pattern is established.
- The safety ordering (transport outage → stale telemetry → grid import →
  pending phase switch → disconnect/model-status) must be preserved through
  extraction.

Implementation:

- Extract each unnamed inline body to a private method such as
  `_handleGridTelemetryUnsafe()`, `_handleGridImportPhaseDown()`,
  `_handleGridImportStop()`, `_handlePendingPhaseSwitch()`,
  `_handleDisconnected()`, `_handleExternalLowPrice()`, and
  `_handlePhaseSwitching()`.
- Keep `handleChargingState()` and `handleNotChargingState()` as-is; their
  existing names already follow the pattern.
- Keep `dispatchControlState()` as a thin router that delegates to the named
  methods and returns their result.
- Keep all Wattpilot commands, D-Bus/MQTT publication, service messages, and
  mutable timer resets inside `FroniusWattpilot.py`; do not move them to helper
  modules.
- Do not change the safety-sensitive evaluation order in `_update()` or the
  `WattpilotControlState` selector.

Files to change:

- `FroniusWattpilot.py`
- `docs/wattpilot-architecture.md` if the dispatch-handler boundary is worth
  documenting.

Files to add:

- None expected.

Tests:

- Add characterization tests for at least the two non-trivial renamed handlers
  (`_handleGridTelemetryUnsafe` and `_handleDisconnected`) that confirm the
  expected service messages, VRM-status values, and controller resets without
  going through the full state-selection machinery.
- Confirm the existing Wattpilot policy regression tests still pass without
  modification.
- Run the full unittest suite.

Expected coverage:

- Each named handler is callable in isolation from a unit test.
- `dispatchControlState()` delegates correctly for every control state.
- Existing charging policy and safety ordering are unchanged.

Manual validation:

- Restart es-ESS and confirm normal Auto/Eco charge cycles, grid-import stops,
  and disconnect events produce the same service messages as before.

Risks and dependencies:

- Purely structural; no command or policy behavior changes.
- Existing policy tests act as the behavioral safety net — they must pass before
  and after without modification.

Open questions:

- Should the `EXTERNAL_LOW_PRICE` handler be folded into `handleExternalChargingState()`
  or remain separate given the Auto-mode guard?

Done criteria:

- `dispatchControlState()` is a thin router with no inline side-effect bodies.
- Each state has a named private handler method.
- Existing regression tests pass unchanged.
- New characterization tests cover at least two handlers in isolation.
- Full unittest suite passes.

### P2 - Add Hardware-Free Tests For Untested Services

Goal:

Provide hardware-free test coverage for the six active service modules that
currently have no test files, prioritising the two with known crash-on-startup
bugs first.

Problem:

`NoBatToEV` and `SolarOverheadDistributor` each have confirmed crashes during
the startup window (None D-Bus values, missing lock) and zero test coverage.
`MqttPVInverter`, `Shelly3EMGrid`, `ShellyPMInverter`, and `FroniusSmartmeterJSON`
likewise have no tests. Additionally, the local MQTT reconnect resubscription
bug identified in the P3 reconnect item has no automated coverage anywhere in
the existing test suite. These gaps mean regressions in any of these services
will go undetected by CI.

Evidence:

- `tests/` contains no file for `NoBatToEV`, `SolarOverheadDistributor`,
  `MqttPVInverter`, `Shelly3EMGrid`, `ShellyPMInverter`, or `FroniusSmartmeterJSON`.
- `NoBatToEV.py` line 82: `power1 + power2 + power3` with `None` initial values
  → `TypeError` on every 2-second tick until Wattpilot connects.
- `SolarOverheadDistributor.py` lines 328–334: grid-phase arithmetic before any
  None check → `TypeError` aborts the full distribution cycle.
- `SolarOverheadDistributor.py` lines 277–282: `_persistEnergyStats()` iterates
  the consumer dict without holding `_knownSolarOverheadConsumersLock`.
- `es-ESS.py` `onLocalMqttConnect()` lines 186–187: resubscribes local topics on
  `mainMqttClient` instead of `localMqttClient` — identified as a latent bug
  with no automated test.

Implementation:

Write independent hardware-free test files for each service. Each file must stub
all Victron/D-Bus/MQTT/hardware dependencies using the same patterns already
established in `tests/test.py` and `tests/test_eco_pv_policy.py`.

Suggested test files and minimum coverage per file:

**`tests/test_nobattoev.py`** (highest priority — known crash bug)
- `_update()` with None Wattpilot power values returns without raising.
- `_update()` with None D-Bus consumption/PV values returns without raising.
- `_update()` with all values populated and `evPower > 0` and
  `consumption >= pvAvailable` registers the correct grid-setpoint delta.
- `_update()` with all values populated and `evPower == 0` revokes the setpoint.
- Relay-disabled path revokes the setpoint.

**`tests/test_solar_overhead_distributor.py`** (highest priority — known crash bug)
- `updateDistribution()` with None `gridL1/L2/L3` values publishes overhead=0
  without raising.
- `updateDistribution()` with None `batteryPower` publishes overhead=0 without
  raising.
- `updateDistribution()` with valid non-None values produces the correct
  overhead and consumer allowances.
- `_persistEnergyStats()` does not raise when a consumer registration arrives
  concurrently (threading test using the lock).
- `MinBatteryCharge` evaluation with `batSoc=None` uses fallback 0 without
  raising.

**`tests/test_mqtt_pv_inverter.py`**
- `_dtuZeroFeedin()` with `target == 0` and active production publishes `0%`
  throttle without raising.
- `_dtuZeroFeedin()` with positive target adjusts throttle proportionally.
- D-Bus service registration and MQTT topic subscriptions initialized correctly.

**`tests/test_shelly3em_grid.py`**
- HTTP polling path returns correct L1/L2/L3 power values from a fake response.
- Failed HTTP request sets `/Connected=0` without raising.
- Timeout produces the same safe failure behavior.

**`tests/test_shelly_pm_inverter.py`**
- HTTP polling path publishes correct power values per configured instance.
- Failed HTTP request sets `/Connected=0` without raising.

**`tests/test_fronius_smartmeter_json.py`**
- HTTP polling path returns correct grid values from a fake JSON response.
- Failed HTTP request sets `/Connected=0` without raising.

**`tests/test_es_ess_orchestration.py`** (local MQTT reconnect routing)
- `onMainMqttConnect()` subscribes only main-type topics on `mainMqttClient`.
- `onLocalMqttConnect()` subscribes only local-type topics on `localMqttClient`,
  not on `mainMqttClient`.
- `publishServiceMessage()` calls `is_connected()` as a method, not as a
  boolean attribute, and suppresses publication when the client is disconnected.

Files to change:

- None required. The open crash bugs (None guard, lock, zero-feedin,
  reconnect routing, `is_connected`) may be fixed in their own PRs first;
  these tests can land before or after those fixes — failing tests are still
  useful as regression anchors.

Files to add:

- `tests/test_nobattoev.py`
- `tests/test_solar_overhead_distributor.py`
- `tests/test_mqtt_pv_inverter.py`
- `tests/test_shelly3em_grid.py`
- `tests/test_shelly_pm_inverter.py`
- `tests/test_fronius_smartmeter_json.py`
- `tests/test_es_ess_orchestration.py`

Tests:

- Each new file is a self-contained `unittest.TestCase` with no hardware
  dependencies, following the stub pattern in `tests/test.py`.
- Run the full unittest suite including the new files.

Expected coverage:

- All six service modules have at least one passing hardware-free test.
- The local MQTT reconnect routing bug is locked in by a failing test before
  the fix and a passing test after.
- `NoBatToEV` and `SolarOverheadDistributor` startup-window crashes are
  confirmed by a failing test before the None guard is added and passing after.

Manual validation:

- Restart es-ESS on a GX device with `NoBatToEV` and `SolarOverheadDistributor`
  enabled and confirm no `TypeError` in the first 30 seconds of
  `/data/log/es-ESS/current.log`.

Risks and dependencies:

- HTTP-polling test files (`Shelly*`, `FroniusSmartmeterJSON`) must mock the
  `requests` library at the module level before import; follow the pattern used
  for Wattpilot WebSocket stubs.
- `SolarOverheadDistributor` threading test requires careful use of
  `threading.Thread` and the real `_knownSolarOverheadConsumersLock`; stub only
  at the D-Bus and MQTT boundaries.
- The orchestration tests (`test_es_ess_orchestration.py`) depend on the
  `esESS` class, which pulls in most of the app at import time; isolate with
  `unittest.mock.patch` at the `mqtt.Client` and `gi.repository.GLib` boundaries.

Open questions:

- Should `test_nobattoev.py` and `test_solar_overhead_distributor.py` be added
  in the same PR as the None-guard fixes, or in a separate PR that establishes
  failing tests first?

Done criteria:

- All seven test files are present and pass.
- CI runs all new files via `python -m unittest discover -s tests`.
- The `NoBatToEV` and `SolarOverheadDistributor` None-value and lock scenarios
  are explicitly covered.
- The local MQTT reconnect routing and `is_connected` call are explicitly tested.
- Full unittest suite passes.

### P3 - Add Startup Config Value Validation

Goal:

Reject obviously invalid `config.ini` values at startup with a clear error
message rather than silently producing wrong behavior or crashing mid-cycle.

Problem:

`_validateConfiguration()` handles version migration correctly but performs no
semantic validation of the loaded values. A misconfigured `config.ini` — for
example a negative `UpdateInterval`, a current outside `[6, 32]` A, a
`PollFrequencyMs` of 0, or an inverted phase threshold pair — causes no startup
error. The bad value propagates silently until it triggers a `TypeError`,
`ZeroDivisionError`, or a physical mismatch that is hard to trace back to the
config file.

Evidence:

- `FroniusWattpilot.py` reads `MinCurrentPerPhase` and `MaxCurrentPerPhase`
  directly as integers with no range check; inverted values (min > max) cause
  the target current calculation to behave incorrectly.
- `ThreePhasePvSurplusStartW` < `ThreePhasePvSurplusStopW` inverts the
  hysteresis and causes repeated phase oscillation.
- `UpdateInterval=0` in `[TimeToGoCalculator]` or `[SolarOverheadDistributor]`
  causes a GLib `timeout_add(0, ...)` — fires as fast as the event loop allows
  and can starve other workers.
- `PollFrequencyMs=0` in `[FroniusSmartmeterJSON]`, `[Shelly3EMGrid]`, or
  `[ShellyPMInverter]` causes the same runaway-poll effect.
- `AllowanceDropGraceSeconds`, `SurplusDropGraceSeconds`, and
  `CarDisconnectConfirmSeconds` of 0 disables intentional debounce windows that
  the Wattpilot policy relies on for stability.
- `BatteryAssistSocMin` outside `[0, 100]` produces mathematically incorrect
  eligibility checks.
- `BatteryAssistMaxSeconds=0` removes the battery-assist time limit, potentially
  allowing unlimited battery discharge during a charge.
- `StartupGraceSeconds=0` disables the Wattpilot startup window and can trigger
  No-allowance stops before the first PV reading arrives.

Implementation:

- Add a `_validateConfigValues()` method called from `_validateConfiguration()`
  after the version migration is applied and the final config is saved.
- Validation rules (minimum viable set; expand as needed):

  | Section | Key | Rule |
  |---|---|---|
  | `[FroniusWattpilot]` | `MinCurrentPerPhase` | `>= 6` (IEC 61851 minimum) |
  | `[FroniusWattpilot]` | `MaxCurrentPerPhase` | `<= 32`, `>= MinCurrentPerPhase` |
  | `[FroniusWattpilot]` | `ThreePhasePvSurplusStartW` | `> ThreePhasePvSurplusStopW` |
  | `[FroniusWattpilot]` | `BatteryAssistSocMin` | `0..100` |
  | `[FroniusWattpilot]` | `BatteryAssistMaxSeconds` | `> 0` if `BatteryAssistEnabled=true` |
  | `[FroniusWattpilot]` | `AllowanceDropGraceSeconds` | `>= 0` |
  | `[FroniusWattpilot]` | `SurplusDropGraceSeconds` | `>= 0` |
  | `[FroniusWattpilot]` | `CarDisconnectConfirmSeconds` | `>= 0` |
  | `[FroniusWattpilot]` | `StartupGraceSeconds` | `>= 0` |
  | `[SolarOverheadDistributor]` | `UpdateInterval` | `> 0` |
  | `[TimeToGoCalculator]` | `UpdateInterval` | `> 0` |
  | `[FroniusSmartmeterJSON]` | `PollFrequencyMs` | `> 0` (if section present) |
  | `[Shelly3EMGrid]` | `PollFrequencyMs` | `> 0` (if section present) |

- On validation failure, log a CRITICAL-level error naming the section, key, and
  violated rule, then raise `SystemExit(1)` so the daemontools supervisor logs
  the failure and backs off before restarting.
- Keep validation as a separate method so it can be unit-tested independently
  of the full `esESS` constructor.
- Do not change the migration logic or any config defaults.

Files to change:

- `es-ESS.py`
- `README.md` if the valid range for any key is not already documented.

Files to add:

- None expected; add validation tests to `tests/test_config_migration.py` or a
  new `tests/test_config_validation.py`.

Tests:

- Add hardware-free tests that construct a config with each invalid value in
  turn and assert `SystemExit` is raised with a message naming the offending key.
- Add a test with a fully valid config that confirms `_validateConfigValues()`
  does not raise.
- Add a test for the inverted phase-threshold pair
  (`ThreePhasePvSurplusStartW < ThreePhasePvSurplusStopW`) specifically.
- Run the full unittest suite.

Expected coverage:

- Every validated key has at least one invalid-value test and one boundary-valid
  test.
- A valid production config passes without raising.
- Startup failure is explicit and logged before the D-Bus/MQTT loop starts.

Manual validation:

- Set `MinCurrentPerPhase=20` and `MaxCurrentPerPhase=10` in `config.ini`.
- Start es-ESS and confirm a CRITICAL log entry and clean exit before any
  service is initialized.
- Correct the values and confirm normal startup resumes.

Risks and dependencies:

- `SystemExit` at startup will cause daemontools to restart the service
  repeatedly if the config is not corrected; this is intentional, but the
  operator must have access to the log to diagnose the failure.
- The minimum current rule (`>= 6 A`) is the IEC 61851 floor, but some
  Wattpilot hardware or firmware versions may advertise a different effective
  minimum; document the assumed floor in `config.sample.ini` comments.
- Do not validate `MinBatteryCharge` expression syntax here; that belongs in
  the `eval()` replacement item (P3).

Open questions:

- Should validation errors be collected and reported all at once, or fail on
  the first invalid key?
- Should `PollFrequencyMs` lower bounds be enforced only when the service is
  enabled (`=true` in `[Services]`)?

Done criteria:

- `_validateConfigValues()` is called during startup after migration.
- Every rule in the table above is implemented and tested.
- Invalid values cause a CRITICAL log and `SystemExit(1)` before services start.
- Valid production configs pass without raising.
- Full unittest suite passes.

## Suggested Implementation Order

This order is intentionally low-risk-first. The P0/P1 labels still show safety
and production impact, but the first PRs avoid live charging-control changes so
the project can build tests, docs, and confidence before touching sensitive
Wattpilot behavior.

1. P4 winter grid-import dispatch validation, because it needs natural low-PV
   conditions and should not be forced during summer surplus.
2. P2 NoBatToEV None D-Bus guard, because the worker crashes silently on every
   tick at startup until all twelve D-Bus paths deliver values.
3. P2 SolarOverheadDistributor distribution-cycle None guard, because None
   grid/battery values abort the entire cycle and leave consumers with stale
   allowances.
4. P2 SolarOverheadDistributor `_persistEnergyStats` lock fix, because a
   concurrent consumer registration can crash the 5-minute persist pass.
5. P2 SolarOverheadDistributor HTTP consumer timeouts, because a blocked HTTP
   endpoint can delay PV-allocation publication used by other consumers.
6. P2 MQTT PV inverter zero-target feed-in guard, because the experimental
   control path can skip safe throttle publication on a divide-by-zero cycle.
7. P2 add hardware-free tests for untested services, beginning with
   `NoBatToEV` and `SolarOverheadDistributor` to lock in the None-guard and
   lock fixes; then `MqttPVInverter`, `Shelly3EMGrid`, `ShellyPMInverter`,
   `FroniusSmartmeterJSON`, and the local MQTT reconnect routing.
8. P3 duplicate `OnKeywordRegex` subscription fix, because it is a one-line
   removal with no behavior change on correct messages.
9. P3 `eval()` replacement in `MinBatteryCharge`, because it removes a code-
   execution risk in a frequently evaluated config expression.
10. P3 `os.popen` replacement in `getUserTime`, because it removes shell
    injection while preserving the same output contract.
11. P3 local MQTT reconnect resubscription, because it is a low-risk
    app-orchestration reliability fix.
12. P3 service-message connected-state guard, because it improves diagnostics
    during MQTT outages without changing device-control policy.
13. P3 dormant service docs/config/runtime alignment, because it prevents
    configuration confusion and should not be mixed with behavior changes.
14. P3 startup config value validation, because a single invalid key can
    produce runaway-poll or oscillation behavior that is hard to trace back to
    the config file; place after the test coverage items so validation failures
    are already covered by hardware-free tests.
15. P3 extract Wattpilot dispatch handlers to named methods, because it is a
    pure structural improvement with no policy change; place last so the test
    suite is already exercising each handler before the extraction.

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
