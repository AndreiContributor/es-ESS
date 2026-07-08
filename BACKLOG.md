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
  project uses `config.sample.ini` as the single configuration artifact.
- `ChargeCompletePowerThresholdW`, `ChargeCompleteConfirmSeconds`,
  `ChargeCompleteResumePowerW`, and `ChargeCompleteResumeSeconds` are supported
  in `FroniusWattpilot.py`, but are not listed in the sample config.
- `Username` appears in config and README, but `FroniusWattpilot.py` constructs
  `Wattpilot(host, password)`, and `Wattpilot.py` authenticates with password
  only. Treat `Username` as a dead setting unless the client is changed.
- README still contains upstream `realdognose/es-ESS` install/source links in
  the setup section and config comments.
- Configuration migration currently performs unconditional section creation for
  some legacy upgrades, which can break older user configs that already contain
  those sections.
- There is no `.github/workflows` CI configuration in this checkout.
- Tests cover many Wattpilot control decisions, but there is no config contract
  test that fails on undocumented or unknown Wattpilot config keys.

Current test strategy:

- Hardware-free regression tests live under `tests/`.
- Existing tests stub Victron/D-Bus/MQTT/Wattpilot dependencies and exercise
  Wattpilot PV-control policy, runtime status, grid guards, phase switching,
  stale telemetry, battery assist, charge-complete hold, and several Manual
  mode safety cases.
- Remaining gaps are around config-contract coverage, writable D-Bus command
  boundaries, WebSocket reconnect lifecycle behavior, configuration migration
  compatibility, and lifecycle shell scripts.

Unclear deployment details:

- Exact supported Venus OS / GX Python versions are not stated in CI or README.
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

- Which Venus OS / GX versions and Python versions must CI target?
- Should VRM/D-Bus writes to `/Mode` remain allowed to switch between Auto and
  Manual, while `/SetCurrent` and `/StartStop` are blocked whenever Wattpilot is
  already in Manual?
- Should uninstall behavior keep a dated backup of `/data/es-ESS/config.ini`
  before removing the deployed directory?

## Completed

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

### P1 - Replace Wattpilot Recursive Reconnect With A Bounded Connection Loop

Problem:

Wattpilot reconnect handling currently calls `run_forever()` from the WebSocket
close callback. Re-entering the WebSocket loop from inside its own callback can
make repeated disconnects hard to reason about and may create brittle behavior
during Wattpilot power loss, Wi-Fi outages, router restarts, or GX network
changes.

Evidence:

- `Wattpilot.py` starts `self._wsapp.run_forever` in a daemon thread in
  `connect()`.
- `Wattpilot.py` `__on_close()` sleeps, then calls `self._wsapp.run_forever()`
  again when `_auto_reconnect` is true.
- `FroniusWattpilot.py` enables `_auto_reconnect` during normal startup and
  wake-up handling.
- Runtime-status tests cover startup-deferred behavior, but not the underlying
  client reconnect loop mechanics.

Implementation:

- Move reconnect responsibility out of `__on_close()` recursion into one
  connection worker loop controlled by an event/flag.
- Ensure `connect()` is idempotent and does not start multiple live worker
  threads for the same client.
- Ensure `disconnect(auto_reconnect=False)` stops reconnect attempts cleanly and
  closes the socket once.
- Preserve existing Wattpilot event callbacks used by
  `WattpilotRuntimeStatus.py`.
- Add bounded sleep/backoff using the existing `_reconnect_interval`.

Files to change:

- `Wattpilot.py`
- `tests/test_wattpilot_runtime_status.py` or a new Wattpilot-client test module
- Possibly `WattpilotRuntimeStatus.py` if event timing expectations need a small
  adaptation.

Files to add:

- Possibly `tests/test_wattpilot_client.py`.

Tests:

- Add hardware-free tests with a fake WebSocketApp proving `connect()` starts
  only one worker.
- Add a test proving close events schedule reconnect through the worker loop
  without recursively calling `run_forever()` from `__on_close()`.
- Add a test proving `disconnect(auto_reconnect=False)` prevents further
  reconnect attempts.
- Run existing runtime-status reconnect tests.

Expected coverage:

- Startup-unavailable behavior remains non-blocking.
- Runtime status still records open/message/close/error events.
- Repeated close events do not create nested loops or multiple active worker
  threads.

Manual validation:

- Required on GX/Wattpilot hardware or a representative network test.

Manual test steps:

1. Start es-ESS with Wattpilot reachable.
2. Confirm normal Wattpilot runtime status and Auto/Eco behavior.
3. Power off or disconnect Wattpilot from the network.
4. Confirm es-ESS remains running and publishes unavailable/stopped status.
5. Restore Wattpilot network/power.
6. Confirm reconnect, runtime status recovery, and normal Auto/Eco safety
   checks.
7. Repeat the outage several times and inspect logs for duplicate reconnect
   workers or unbounded exceptions.

Risks and dependencies:

- The Wattpilot client is used by runtime-status event hooks; preserve event
  names and callback order where practical.
- WebSocket behavior may differ across `websocket-client` versions on Venus OS.

Open questions:

- Should reconnect backoff stay fixed at 30 seconds, or should repeated failures
  use a capped exponential backoff?

Done criteria:

- Reconnect loop tests pass.
- Existing Wattpilot runtime-status tests pass.
- Manual outage/recovery validation succeeds without duplicate worker threads.

### P1 - Rebuild Wattpilot Configuration Around `config.sample.ini`

Goal:

Make every active Wattpilot parameter discoverable, grouped by feature, and
unambiguous while using only `config.sample.ini` as the checked-in config
artifact.

Problem:

Wattpilot has active settings in code that are missing from the sample config,
README defaults are stale in places, and maintaining multiple config examples
risks drift. The user has confirmed that production config should match the
sample.

Evidence:

- The project should use one checked-in config example so sample and production
  structure stay aligned.
- `FroniusWattpilot.py` reads many Wattpilot settings through
  `settings.get(...)` defaults, including charge-complete hold keys that are
  not in `config.sample.ini`.
- `config.sample.ini` uses `BatteryMaxChargeInWh`, while README documents
  `BatteryMaxChargeInW`.
- `Username` appears in sample/README but is not used by the Wattpilot client.

Implementation:

- Treat `config.sample.ini` as the complete sample for active settings.
- Group `[FroniusWattpilot]` settings by feature:
  connection and identity, VRM/D-Bus identifiers, electrical current limits,
  PV start/stop behavior, phase switching, battery-charge reservation priority,
  battery assist for clouds, no-grid protection, telemetry freshness and grace
  periods, charge-complete hold, and display/status.
- Decide whether to remove `Username` or implement username support in
  `Wattpilot.py`.
- Add missing charge-complete hold keys to `config.sample.ini` if they remain
  supported configuration.
- Ensure `BatteryAssistRecoverySeconds`, `RawOverheadFreshSeconds`,
  `AllowanceFreshSeconds`, `AllowanceDropGraceSeconds`,
  `CarDisconnectConfirmSeconds`, `SurplusDropGraceSeconds`,
  `GridTelemetryFreshSeconds`, `StartupGraceSeconds`, and
  `StartupTelemetryRatio` are documented in `config.sample.ini`.
- Keep credentials as placeholders only.
- Add a config contract test that fails when a supported Wattpilot config key is
  undocumented in `config.sample.ini` or when the sample includes an unknown
  Wattpilot key.
- Update README to state that `config.sample.ini` is the single maintained
  config artifact and production config is expected to match it.
- Reconcile global config key names between README, runtime code, and
  `config.sample.ini`, including `BatteryMaxChargeInW` versus
  `BatteryMaxChargeInWh`.

Files to change:

- `config.sample.ini`
- `README.md`
- Tests under `tests/`

Files to add:

- Possibly `tests/test_config_contract.py`.

Tests:

- Add a config contract test comparing active Wattpilot keys in
  `FroniusWattpilot.py` with documented keys in `config.sample.ini`.
- Add a test proving only `config.sample.ini` is required by runtime or tests.
- Run `python -m py_compile` for changed Python files.
- Run the full unittest suite.

Expected coverage:

- A user can configure Wattpilot behavior without reading source code.
- The sample config remains valid after future refactors.
- Config tests catch unknown sample keys and undocumented supported keys.
- Global config names documented in README match the maintained sample config
  and runtime usage.

Manual validation:

- Required on a deployed system after config-file changes.

Manual test steps:

1. Compare production `/data/es-ESS/config.ini` with the updated
   `config.sample.ini` structure.
2. Confirm no required production setting exists outside `config.sample.ini`.
3. Restart es-ESS with Wattpilot enabled.
4. Confirm config loads without migration or missing-key errors.
5. Confirm Auto/Eco and Manual reporting still work.

Risks and dependencies:

- Removing the duplicate config artifact may break scripts, docs, or user
  workflows if anything references it indirectly. Search before deletion.
- If production configs rely on omitted code defaults, making the sample
  complete may reveal settings users have never consciously chosen.

Open questions:

- Should `ConfigVersion` be bumped for sample-only documentation changes, or
  only for runtime migration changes?

Done criteria:

- `config.sample.ini` is the complete source for supported settings.
- README no longer points users at duplicate config documentation.
- Config contract tests pass.

### P1 - Rewrite Wattpilot README And Correct Installation Source

Goal:

Make installation and expected Wattpilot behavior clear for a non-developer.

Problem:

README contains stale setup/source references, incomplete Wattpilot config
coverage, and behavior descriptions that need to align with the current
Auto/Eco safety policy and the single-sample-config decision.

Evidence:

- README contains upstream `realdognose/es-ESS` links in setup/source areas.
- README includes Wattpilot behavior sections, but the current config table does
  not fully match active code settings.
- Runtime-status behavior is documented later in README and should remain
  consistent with Wattpilot code and MQTT/D-Bus paths.

Implementation:

- Replace setup commands that download `realdognose/es-ESS` with
  `AndreiContributor/es-ESS` or a tagged release.
- State that `config.sample.ini` is the complete maintained configuration
  sample and that production config is expected to match it.
- Remove stale duplicate config-file guidance.
- Add a complete Wattpilot configuration table matching `config.sample.ini`.
- Explain that Wattpilot must be in ECO mode for es-ESS Auto/Eco PV control.
- Explain that the native Wattpilot PV-start threshold should be set high so
  es-ESS controls PV charging.
- Explain one-phase start behavior.
- Explain three-phase switch behavior.
- Explain `MinOnOffSeconds` versus `MinPhaseSwitchSeconds` versus
  `PhaseSwitchDelaySeconds`.
- Explain battery-assist limits and recovery.
- Explain no-grid guard behavior and transient-import limitations.
- Explain telemetry fail-safe behavior.
- Document phase/status values available through D-Bus and MQTT.
- Explain the standard VRM EVCS tile limitation and the custom Cerbo UI
  requirement.
- Add example configuration for PV-only, no battery assist.
- Add example configuration for PV plus a 300-second cloud bridge.
- Add example configuration for conservative five-minute start/phase timers.
- Add deployment verification commands for `py_compile`, `unittest`, service
  restart, and log monitoring.

Files to change:

- `README.md`
- `config.sample.ini` if wording or settings need to stay in sync

Files to add:

- None expected.

Tests:

- Run README/config contract tests from the config item.
- Run syntax checks and the full unittest suite if any code changes accompany
  the documentation update.

Expected coverage:

- README and sample config agree exactly with the code.
- A non-developer can install, configure, verify, and reason about Wattpilot
  behavior from README alone.

Manual validation:

- Required for installation instructions and live-device verification commands.

Manual test steps:

1. Follow the updated install/setup commands on a test GX or staging path.
2. Copy/update production config from `config.sample.ini`.
3. Restart the service.
4. Monitor logs and MQTT/D-Bus status paths described in README.
5. Confirm Manual mode remains user-controlled and Auto/Eco follows PV/no-grid
   policy.

Risks and dependencies:

- README examples must not imply that battery assist can start a charge or
  authorize grid use.
- Installation source changes should ideally point to a stable tag when release
  packaging is ready.

Open questions:

- Should README examples use the exact production values or conservative
  recommended values where they differ from production?

Done criteria:

- README no longer references duplicate config-file guidance.
- README config table matches `config.sample.ini`.
- README install commands point to the intended repository/release source.

### P1 - Add Automated Checks With GitHub Actions

Goal:

Prevent regressions from reaching `main`.

Problem:

There is no CI workflow in this checkout, so syntax errors, failing regression
tests, and config/sample drift can land unnoticed.

Evidence:

- No `.github/workflows` directory exists in the current file list.
- Tests are present under `tests/` and can be run without hardware stubs.
- The planned config contract test needs CI enforcement.

Implementation:

- Add a workflow triggered by pull requests and pushes to `main`.
- Run Python syntax checks for changed Python files or all repository Python
  files.
- Run the complete unittest suite.
- Validate `config.sample.ini` through the config contract test.
- Ensure CI expects only `config.sample.ini`.
- Use and document a Python version compatible with the supported Venus OS
  target.
- Optionally add a README CI badge.
- Optionally upload unittest output as a failure artifact.

Files to change:

- `.github/workflows/ci.yml`
- `README.md` if adding a badge or documenting CI Python version

Files to add:

- `.github/workflows/ci.yml`

Tests:

- Run the workflow locally where possible with equivalent commands.
- Run the full unittest suite.

Expected coverage:

- A pull request cannot be merged with broken syntax, failing tests, or invalid
  sample configuration.

Manual validation:

- Required once pushed to GitHub.

Manual test steps:

1. Push a branch with the workflow.
2. Confirm PR and push triggers run.
3. Confirm syntax checks, unittest, and config contract checks pass.
4. Temporarily test a failing branch or local equivalent to ensure failures are
   visible.

Risks and dependencies:

- CI Python version must match the oldest supported runtime closely enough to
  avoid accepting syntax unsupported on Venus OS.

Open questions:

- Which exact Python version should CI use for the supported GX/Venus OS target?

Done criteria:

- GitHub Actions workflow is present and passing.
- CI validates `config.sample.ini` as the single config artifact.

### P2 - Harden Service Lifecycle Scripts

Problem:

Lifecycle scripts use broad process matching, non-idempotent install commands,
and destructive uninstall behavior. On a production GX device these scripts can
fail noisily, kill unintended matching processes, or remove deployed config
without a backup.

Evidence:

- `restart.sh` uses `kill -s 15 $(pgrep -f 'python /data/es-ESS/es-ESS.py')`.
- `kill_me.sh` uses `kill -s 9 $(pgrep -f 'python /data/es-ESS/es-ESS.py')`.
- `uninstall.sh` uses the same broad kill pattern and then `rm -r /data/es-ESS`.
- `install.sh` uses `ln -s /data/es-ESS/service /service/es-ESS` without
  checking whether the symlink already exists.
- `uninstall.sh` rewrites `/data/rc.local` via a temp file without shell safety
  options or cleanup handling.

Implementation:

- Add `set -eu` where compatible with Venus OS shell behavior.
- Make install idempotent: create or repair `/service/es-ESS` only when needed.
- Make restart/kill scripts handle no matching process without passing an empty
  PID list to `kill`.
- Narrow process matching where practical.
- Prefer graceful stop in restart, and reserve SIGKILL for explicit emergency
  behavior.
- Preserve or back up `/data/es-ESS/config.ini` before uninstall removes the
  deployed directory, unless the user explicitly wants full deletion.
- Rewrite `rc.local` removal with a safe temp file and move.

Files to change:

- `install.sh`
- `restart.sh`
- `kill_me.sh`
- `uninstall.sh`
- Possibly `README.md` for updated lifecycle commands

Files to add:

- None expected.

Tests:

- Add shellcheck-style review if tooling is available.
- Add lightweight script tests only if a portable pattern already exists or can
  be added without overengineering.
- Run syntax checks with `bash -n install.sh restart.sh kill_me.sh uninstall.sh`
  where Bash is available.

Expected coverage:

- Scripts are idempotent and safe when the service is already installed,
  stopped, missing, or partially removed.
- Uninstall behavior does not accidentally erase production config without an
  intentional path.

Manual validation:

- Required on a non-production GX or staging directory before production use.

Manual test steps:

1. Run install twice and confirm the service symlink and `rc.local` entry are
   stable.
2. Run restart when the service is running and when it is stopped.
3. Run emergency kill only on a test instance.
4. Run uninstall on a staging copy and confirm config backup/retention behavior.
5. Reinstall and confirm service starts.

Risks and dependencies:

- Venus OS shell utilities may be BusyBox variants; keep commands portable.
- Changing uninstall semantics may surprise users who expect full deletion.

Open questions:

- Should uninstall preserve `config.ini` by default or only after prompting in
  documentation?

Done criteria:

- Lifecycle scripts are idempotent for common repeated operations.
- No command fails solely because no matching process exists.
- Uninstall behavior around production config is explicit and documented.

### P2 - Document App-Wide Service Inventory And Integration Boundaries

Goal:

Make the non-Wattpilot services understandable before broad documentation,
config cleanup, or cross-service refactoring.

Problem:

The backlog is intentionally Wattpilot-heavy because EV charging control is the
highest-risk area, but es-ESS contains several other independent services.
Those services have their own D-Bus, MQTT, HTTP, configuration, and worker
boundaries. Without a concise service inventory, future README/config cleanup
or service refactors can miss inactive services, config-only entries, or
cross-service dependencies.

Evidence:

- `es-ESS.py` initializes enabled services from `[Services]`, including
  `SolarOverheadDistributor`, `TimeToGoCalculator`, `FroniusSmartmeterJSON`,
  `MqttExporter`, `FroniusWattpilot`, `MqttTemperature`, `NoBatToEV`,
  `Shelly3EMGrid`, `ShellyPMInverter`, and `MqttPVInverter`.
- `es-ESS.py` also contains disabled/commented service hooks for `Grid2Bat`,
  `MqttDC`, `ChargeCurrentReducer`, and `FroniusSmartmeterRS485`.
- `config.sample.ini` includes `Grid2Bat=false` but this checkout does not
  contain an active `Grid2Bat.py` service module or active initializer call.
- Service modules use different integration styles: D-Bus monitors,
  VeDbusService publishing, main/local MQTT subscriptions, HTTP polling of
  Shelly/Fronius endpoints, and SolarOverheadDistributor consumer requests.
- README lists many services, but the backlog currently lacks a single
  developer-facing map of non-Wattpilot service ownership and integration
  boundaries.

Implementation:

- Add a small developer note, such as `docs/service-inventory.md`, that maps
  each service to its module, config section, enabled/disabled state, primary
  D-Bus paths or service type, MQTT topics, external dependencies, and runtime
  worker/subscription model.
- Separate active initialized services from dormant/commented/config-only
  entries.
- Include the relationship between `SolarOverheadDistributor`,
  `FroniusWattpilot`, scripted consumers, MQTT consumers, and HTTP consumers.
- Include service ownership boundaries for sensor ingestion, D-Bus device
  publishing, MQTT export, grid-setpoint requests, and HTTP device polling.
- Note documentation/config gaps discovered during the inventory as follow-up
  backlog items instead of fixing them in the same PR.
- Keep this task documentation-only.

Files to change:

- A small developer-facing markdown file

Files to add:

- Possibly `docs/service-inventory.md`

Tests:

- No runtime tests expected for documentation-only work.
- Run markdown/link review manually.

Expected coverage:

- Contributors can see which services exist, which ones are active, which ones
  are dormant or config-only, and where each service's integration boundary
  belongs before editing app-wide docs or shared runtime code.

Manual validation:

- Maintainer review only.

Manual test steps:

1. Read the new service-inventory note.
2. Confirm the active service list matches `es-ESS.py` initialization behavior.
3. Confirm dormant/config-only services are labelled clearly and not presented
   as active supported features.
4. Confirm each service summary matches the current module and
   `config.sample.ini`.

Risks and dependencies:

- Keep this PR documentation-only so it is safe to do early.
- Avoid turning the inventory into a README rewrite or config cleanup PR.
- Some modules may be present but intentionally disabled; do not infer product
  intent without maintainer confirmation.

Open questions:

- Should dormant services such as `MqttDC`, `ChargeCurrentReducer`, and
  `FroniusSmartmeterRS485` be documented as legacy/internal, or as future
  supported services?
- Should `Grid2Bat` remain in `config.sample.ini` if there is no active service
  module in this checkout?

Done criteria:

- The non-Wattpilot service inventory is documented.
- Active, dormant, and config-only entries are clearly distinguished.
- No production behavior, config defaults, D-Bus paths, or MQTT topics are
  changed.

### P2 - Add Wattpilot Decision Characterization Tests Before Refactoring

Goal:

Make the next refactor PRs safer by locking down current behavior first.

Problem:

Existing tests cover many Wattpilot decisions, but the controller still has
large branches where telemetry freshness, allowance, battery assist, phase
switching, and grid guards interact. Before extracting helpers, add focused
characterization tests for the seams that will be moved.

Evidence:

- `FroniusWattpilot.py` contains multiple decision helpers and side effects in
  one controller.
- Existing tests under `tests/` already use hardware-free stubs and mocks, so
  more characterization coverage can be added without live D-Bus, MQTT, Venus
  OS, or Wattpilot hardware.
- The planned architecture refactor should preserve behavior, not change
  charging policy.

Implementation:

- Add focused tests around current telemetry freshness behavior.
- Add focused tests around allowance evaluation and raw-overhead fallback
  boundaries.
- Add focused tests around grid-import guard stop/start behavior.
- Add focused tests around battery-assist eligibility, lockout, and recovery.
- Add focused tests around one-to-three and three-to-one phase decisions.
- Prefer tests against existing public/internal methods before moving code.

Files to change:

- Tests under `tests/`

Files to add:

- Possibly a focused test module such as
  `tests/test_wattpilot_decision_characterization.py`.

Tests:

- Run the new focused tests.
- Run the full unittest suite.

Expected coverage:

- Existing behavior is captured before helper extraction.
- Refactor PRs can be reviewed as moves plus tests instead of behavior changes.

Manual validation:

- None required for tests-only work.

Manual test steps:

1. Review the new test names and fixtures.
2. Confirm they describe existing behavior, not desired future behavior.
3. Run the full test suite on the development machine.

Risks and dependencies:

- Tests that overfit private implementation can make later refactors noisy.
  Prefer observable controller outcomes where practical.

Open questions:

- Should duplicated Wattpilot test fixtures be consolidated before adding more
  tests, or left alone until after the characterization PR?

Done criteria:

- Characterization tests pass.
- No production code changes are included unless a tiny test seam is required.
- The tests document current behavior for the next extraction PRs.

### P2 - Extract Wattpilot Telemetry And Allowance Evaluation Helpers

Depends on:

- Wattpilot decision characterization tests.

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

1. P1 config/sample cleanup, because it creates the config contract and removes
   duplicate config maintenance.
2. P1 README rewrite, because user-facing behavior should match the completed
   sample config.
3. P1 CI, because it should run the config contract and existing behavior tests.
4. P2 lifecycle script hardening, because it reduces deployment risk but should
   avoid mixing with Wattpilot behavior changes.
5. P2 app-wide service inventory, because it is documentation-only and makes
   the non-Wattpilot scope explicit before broader README/config cleanup.
6. P2 Wattpilot decision characterization tests, because it strengthens the
   safety net before production code moves.
7. P1 Wattpilot reconnect loop, because recovery reliability affects live
   safety/status behavior but should be isolated to the client lifecycle.
8. P0 Manual command-boundary hardening, because it protects the most important
   product invariant once the test base is stronger.
9. P2 telemetry and allowance helper extraction, because it is the first
    low-side-effect Wattpilot control extraction.
10. P2 grid-guard and battery-assist helper extraction, because it is more
    safety-sensitive and should follow characterization coverage.
11. P2 phase-switching helper extraction, because phase switching is
    user-visible and high-impact.
12. P3 state-machine refactor, because it needs the previous behavior, config,
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
