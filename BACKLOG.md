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
  boundaries, WebSocket reconnect lifecycle behavior, and lifecycle shell
  scripts.

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
- README still documents `ConfigVersion=1`, while the sample config uses
  `ConfigVersion=8`.
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
- README documents `ConfigVersion=1` while `config.sample.ini` uses
  `ConfigVersion=8`.
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

### P2 - Refactor Wattpilot Control Into An Explicit State Machine

Depends on:

- Manual command-boundary hardening.
- Config/sample contract.
- README behavior rewrite.
- CI checks.

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

1. P0 Manual command-boundary hardening, because it protects the most important
   product invariant: Manual mode remains user-controlled.
2. P1 Wattpilot reconnect loop, because recovery reliability affects live
   safety/status behavior.
3. P1 config/sample cleanup, because it creates the config contract and removes
   duplicate config maintenance.
4. P1 README rewrite, because user-facing behavior should match the completed
   sample config.
5. P1 CI, because it should run the config contract and existing behavior tests.
6. P2 lifecycle script hardening, because it reduces deployment risk but should
   avoid mixing with Wattpilot behavior changes.
7. P2 state-machine refactor, because it needs the previous behavior and config
   contracts in place before touching control flow.

## Verification Plan

For backlog-only changes:

- Review `BACKLOG.md` for structure, preserved context, and duplicate items.
- Confirm no code, config, or docs besides `BACKLOG.md` were changed.

For implementation PRs:

- Run `python -m py_compile` on changed Python files.
- Run the full unittest suite.
- Run focused Wattpilot tests for any Wattpilot behavior change.
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
