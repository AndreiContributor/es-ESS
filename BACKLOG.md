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

### Completed 2026-07-11 - PR 5 Security Hardening

Completion note:

- Replaced the `MinBatteryCharge` `eval()` path in
  `SolarOverheadDistributor.py` with a constrained AST evaluator that supports
  numeric literals, `SOC`, `min()`/`max()`, parentheses, and `+`, `-`, `*`,
  `/`.
- Added an explicit `batterySoc=None` fallback that logs a warning and uses
  `MinBatteryCharge=0` for the current distribution cycle instead of relying on
  a swallowed `NameError`.
- Replaced `Globals.getUserTime()` shell interpolation through `os.popen()`
  with `subprocess.run()` using explicit argv and a `TZ` environment variable.
- Added timezone validation so shell metacharacters and malformed timezone
  values are rejected before subprocess invocation.
- Documented the supported `MinBatteryCharge` expression grammar in
  `README.md` and `config.sample.ini`.
- Added hardware-free tests for safe `MinBatteryCharge` expressions,
  unavailable SOC fallback, malicious/invalid expression rejection, structured
  time subprocess invocation, and malformed timezone rejection.
- Kept the change limited to security hardening, documentation, tests, and
  backlog; no Wattpilot Manual/Auto control behavior, D-Bus path names, MQTT
  topics, service initialization boundaries, or configuration defaults were
  changed.

### Completed 2026-07-11 - PR 4A Graceful Shutdown Reliability

Completion note:

- Made SIGTERM cleanup idempotent while preserving grid-setpoint restoration,
  MQTT unsubscribe, service cleanup, and disconnect ordering.
- Replaced the swallowable `SystemExit` path with explicit log flushing and
  `os._exit(0)` after all safety cleanup has completed.
- Changed `service/run` to exec Python directly so daemontools supervises the
  application process rather than an intermediate shell.
- Added a 10-second graceful wait to `restart.sh`, followed by SIGKILL only
  for original PIDs whose command and `/proc` start time still match.
- Downgraded expected main/local MQTT shutdown disconnect messages to INFO
  while preserving warnings for unexpected runtime disconnects.
- Extended hardware-free orchestration coverage for idempotent cleanup,
  shutdown ordering, process termination, MQTT log severity, and lifecycle
  script safeguards.
- Verified 14 focused tests, all 182 hardware-free tests, repository Python
  compilation, lifecycle shell syntax, and `git diff --check`.
- Completed repeated GX log-only validation with the EV disconnected: three
  graceful restarts each exited the original PID, started a new directly
  supervised Python PID, ran cleanup once, and recovered MQTT, Wattpilot,
  consumer initialization, and non-zero worker heartbeats without `SystemExit`,
  traceback, timeout, SIGKILL fallback, or an inert process.
- Production deployment exposed CRLF in a copied `service/run`, which prevented
  daemontools from resolving its shebang. Added repository LF attributes for
  shell scripts and `service/run` after normalizing the deployed file.
- Made intentional main/local MQTT shutdown INFO messages synchronous and
  deduplicated because production showed the asynchronous disconnect callbacks
  can arrive late or not run before `os._exit(0)`. A follow-up GX restart
  confirmed each main/local disconnect and reconnect-disabled message appeared
  exactly once before `Cleaned up. Bye.`, followed by full service recovery.
- Kept the change limited to lifecycle reliability, tests, README, and backlog;
  Wattpilot Manual/Auto behavior, charging policy, D-Bus/MQTT contracts, and
  configuration were not changed.


### Completed 2026-07-11 - PR 4 MQTT And Orchestration Reliability

Completion note:

- Fixed local MQTT reconnect restoration in `es-ESS.py` so
  `onLocalMqttConnect()` re-subscribes local topics and callbacks on
  `localMqttClient` instead of `mainMqttClient`.
- Fixed `publishServiceMessage()` to test the actual main MQTT connection
  state, including compatibility for clients that expose `is_connected` as a
  method or as a boolean attribute.
- Removed the duplicate SolarOverheadDistributor `OnKeywordRegex` MQTT
  subscription while preserving the original basic-property registration and
  all other consumer registration topics.
- Added hardware-free fake-client orchestration tests for reconnect routing,
  initial MQTT subscription routing, connected/disconnected service-message
  publication, and boolean `is_connected` compatibility.
- Added SolarOverheadDistributor subscription coverage proving
  `OnKeywordRegex` is registered exactly once.
- Kept the change limited to MQTT/orchestration reliability, tests, and
  backlog; no Wattpilot charging behavior, D-Bus path names, MQTT topic names,
  configuration defaults, README guidance, or service-inventory contracts were
  changed.

### Completed 2026-07-10 - SolarOverheadDistributor Startup Safety

Completion note:

- Added explicit startup/grid-loss telemetry guards to
  `SolarOverheadDistributor.updateDistribution()` so missing grid L1/L2/L3 or
  battery-power values publish fail-safe zero overhead instead of falling into
  the generic CRITICAL exception path.
- Published zero consumer allowances, zero assigned/remaining overhead, and a
  warning service message when required distribution inputs are unavailable.
- Preserved existing allocation behavior when all grid and battery telemetry is
  present.
- Wrapped `SolarOverheadDistributor._persistEnergyStats()` with
  `_knownSolarOverheadConsumersLock` so concurrent consumer registration cannot
  mutate the consumer dictionary during the persist pass.
- Added `tests/test_solar_overhead_distributor.py` with hardware-free coverage
  for missing grid telemetry, missing battery power, normal overhead
  calculation, and lock behavior during concurrent persist/registration.
- Verified with `py_compile`, the focused SolarOverheadDistributor unittest
  file, and the full hardware-free unittest suite through
  `uv --cache-dir .uv-cache run --no-project python`.
- Kept the change limited to SolarOverheadDistributor startup safety, tests,
  and backlog; no Wattpilot behavior, D-Bus path names, MQTT topic names,
  configuration defaults, service initialization boundaries, architecture
  contracts, or README guidance were changed.

### Completed 2026-07-10 - NoBatToEV Startup Safety

Completion note:

- Added startup telemetry guards to `NoBatToEV._update()` so missing Wattpilot
  phase power, external EV charger power, consumption, or PV D-Bus values
  revoke the shared grid-setpoint request instead of raising `TypeError`.
- Preserved existing NoBatToEV setpoint behavior once all telemetry is present,
  including EV-load delta calculation, zero-EV revocation, relay-disabled
  revocation, and grid-loss revocation.
- Added `tests/test_nobattoev.py` with hardware-free coverage for missing
  Wattpilot power, missing D-Bus consumption/PV values, populated setpoint
  delta calculation, zero EV power, and relay-disabled behavior.
- Verified with `py_compile`, the focused NoBatToEV unittest file, and the full
  hardware-free unittest suite through `uv --cache-dir .uv-cache run
  --no-project python`.
- Kept the change limited to NoBatToEV startup safety, tests, and backlog; no
  Wattpilot Manual/Auto control behavior, D-Bus path names, MQTT topics,
  configuration defaults, or service initialization boundaries were changed.

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

### Completed 2026-07-11 - PR 3 Service I/O Safety And Remaining Service Coverage

Completion note:

- Added `[Common] HttpRequestTimeout=5` with a v9 config migration and
  documentation in `config.sample.ini`, README, and the service inventory.
- Applied the shared timeout to SolarOverheadDistributor HTTP consumer on,
  off, status, and power requests, preserving existing exception logging and
  allocation behavior.
- Wired dormant `FroniusSmartmeterRS485` HTTP polling to the same shared
  timeout setting if it is re-enabled.
- Guarded `MqttPVInverter._dtuZeroFeedin()` so zero-target cycles publish an
  explicit `0%` OpenDTU throttle for producing controllable inverters instead
  of dividing by zero.
- Added hardware-free coverage for `MqttPVInverter`, `Shelly3EMGrid`,
  `ShellyPMInverter`, and `FroniusSmartmeterJSON`, and extended
  SolarOverheadDistributor/config-migration regression tests for the new
  timeout behavior.
- Verified with focused PR 3 tests, `py_compile` on changed Python files, and
  the full hardware-free unittest suite through `uv --cache-dir .uv-cache run
  --no-project python`.
- Kept PR 4 MQTT/orchestration reliability items open and out of this PR.

## Backlog


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

## PR Execution Queue

Use this queue as the implementation order. Each numbered entry is one
PR-sized batch. Do not pull later items into the active PR. When the user says
`fix next PR items`, select the first PR below containing unfinished backlog
items, present the required implementation plan, risks, and verification, and
then follow the repository working agreement for approval and implementation.
After delivery, move the finished backlog items to `Completed` and advance the
queue on the next request.

1. **PR 6 - Dormant service alignment:** reconcile README, sample config,
   service inventory, and runtime intent for dormant or missing services. Keep
   this documentation/configuration alignment separate from active-service
   behavior changes.
2. **PR 7 - Startup config value validation:** add bounded, cross-field config
   validation with tests for valid production values and clean startup failure
   for invalid values.
3. **PR 8 - Wattpilot dispatch handler extraction:** extract the existing
   `dispatchControlState()` side-effect bodies into named controller methods,
   add isolated characterization tests for the non-trivial handlers, and prove
   delegation for every control state without changing state selection,
   command ownership, Manual behavior, or Auto/Eco policy.

The P4 winter grid-import dispatch validation is an observation task, not a
code PR, and remains open independently of this queue. Complete it only under
natural suitable low-PV conditions; do not force production grid import or
disconnect critical telemetry to satisfy it.

Hardware validation scope for this queue:

- PR 4A requires repeated log-only restart validation on GX with the EV
  disconnected or confirmed not charging. It does not require an active charge.
- PRs 5-7 do not require a connected car for their acceptance criteria.
  A real or simulated EV load adds end-to-end confidence for NoBatToEV grid-
  setpoint math, but is not required to verify the None guard.
- PR 8 uses focused characterization, all-state delegation, and the full
  hardware-free suite as its merge gate. A short normal GX/Wattpilot smoke test
  is recommended before production deployment, but the previously validated
  Manual/Auto, phase-switch, transport-reconnect, and car-debounce matrices do
  not need to be repeated when the change remains purely structural.
- The separate P4 winter validation requires an active Auto/Eco charging
  session to observe real grid-import phase-down or stop behavior.

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
