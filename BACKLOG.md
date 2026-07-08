# es-ESS Backlog

This backlog was created from the requested Wattpilot PR roadmap and a quick
analysis of the current application state in this checkout.

## Current App Analysis

es-ESS is a Python service bundle for Victron Venus OS / GX devices. The app is
structured as independent services that are enabled from `config.ini`, with
Wattpilot support centered in `FroniusWattpilot.py`, the WebSocket client in
`Wattpilot.py`, runtime status reporting in `WattpilotRuntimeStatus.py`, and
hardware-free regression tests under `tests/`.

Current Wattpilot state:

- Auto/Eco PV-only control, no-grid protection, battery assist, telemetry
  freshness, startup grace, raw-overhead freshness, and runtime status reporting
  are already present in code and tests.
- `config.sample.ini` and `config.reference.ini` currently contain the same
  values and comments. The reference file is not yet a complete reference with
  default/unit/range documentation for every active setting.
- `ChargeCompletePowerThresholdW`, `ChargeCompleteConfirmSeconds`,
  `ChargeCompleteResumePowerW`, and `ChargeCompleteResumeSeconds` are supported
  in `FroniusWattpilot.py`, but are not listed in the sample/reference config.
- `Username` appears in config and README, but `FroniusWattpilot.py` constructs
  `Wattpilot(host, password)`, and `Wattpilot.py` authenticates with password
  only. Treat `Username` as a dead setting unless the client is changed.
- README still contains upstream `realdognose/es-ESS` install/source links in
  the setup section and config comments.
- There is no `.github/workflows` CI configuration in this checkout.
- Tests cover many Wattpilot control decisions, but there is no config
  contract test that fails on undocumented or unknown Wattpilot config keys.

Global delivery rules:

- Implement only the task described in the active PR.
- Keep normal Wattpilot Manual mode unchanged.
- In Auto/Eco mode, do not intentionally use grid power.
- Battery assist remains an optional, time-limited bridge for an already-running
  charge only.
- Add or update unit tests for every behavior change.
- Run syntax checks and the full test suite before opening a PR.
- Update README and config documentation whenever a new setting or behavior is
  introduced.
- Do not add shared 16 A cable/current-limiting logic.

## PR 05 - P1: Rebuild Wattpilot Configuration As A Complete Reference

Goal: make every active Wattpilot parameter discoverable, grouped by feature,
and unambiguous.

Files:

- `config.sample.ini`
- `config.reference.ini`
- New or updated config contract tests

Required groups inside `[FroniusWattpilot]`:

- Connection and identity
- VRM/D-Bus identifiers
- Electrical current limits
- PV start/stop behavior
- Phase switching
- Battery-charge reservation priority
- Battery assist for clouds
- No-grid protection
- Telemetry freshness and grace periods
- Charge-complete hold
- Display/status

Tasks:

- [ ] Decide whether to remove `Username` or implement username support in
  `Wattpilot.py`.
- [ ] Make `config.reference.ini` a complete reference, not a duplicate sample.
- [ ] Document every supported Wattpilot key once with default, unit, allowed
  value/range, and recommended sample value where different.
- [ ] Add missing charge-complete hold keys to the reference and sample if they
  remain supported configuration.
- [ ] Ensure `BatteryAssistRecoverySeconds`, `RawOverheadFreshSeconds`,
  `AllowanceFreshSeconds`, and `GridTelemetryFreshSeconds` are documented.
- [ ] Keep all credentials as placeholders only.
- [ ] Add a config contract test that fails when a supported Wattpilot config
  key is undocumented or when the sample includes an unknown key.
- [ ] Run `python -m py_compile` for changed Python files and the full unittest
  suite.

Acceptance:

- A user can configure Wattpilot behavior without reading source code.
- Config examples remain valid after future refactors.
- Config tests catch unknown sample keys and undocumented supported keys.

## PR 06 - P1: Rewrite Wattpilot README And Correct Installation Source

Goal: make installation and expected Wattpilot behavior clear for a
non-developer.

Files:

- `README.md`
- Possibly `config.reference.ini` if table wording must stay in sync

Tasks:

- [ ] Replace setup commands that download `realdognose/es-ESS` with
  `AndreiContributor/es-ESS` or a tagged release.
- [ ] Add a complete Wattpilot configuration table matching
  `config.reference.ini`.
- [ ] Explain that Wattpilot must be in ECO mode.
- [ ] Explain that the native Wattpilot PV-start threshold should be set high so
  es-ESS controls PV charging.
- [ ] Explain one-phase start behavior.
- [ ] Explain three-phase switch behavior.
- [ ] Explain `MinOnOffSeconds` versus `MinPhaseSwitchSeconds`.
- [ ] Explain battery-assist limits and recovery.
- [ ] Explain no-grid guard behavior and transient-import limitations.
- [ ] Explain telemetry fail-safe behavior.
- [ ] Document phase/status values available through D-Bus and MQTT.
- [ ] Explain the standard VRM EVCS tile limitation and the custom Cerbo UI
  requirement.
- [ ] Add example configuration for PV-only, no battery assist.
- [ ] Add example configuration for PV plus a 300-second cloud bridge.
- [ ] Add example configuration for conservative five-minute start/phase timers.
- [ ] Add deployment verification commands for `py_compile`, `unittest`,
  service restart, and log monitoring.
- [ ] Run syntax checks and the full unittest suite.

Acceptance:

- README and reference config agree exactly with the code.
- A non-developer can install, configure, verify, and reason about Wattpilot
  behavior from README alone.

## PR 07 - P1: Add Automated Checks With GitHub Actions

Goal: prevent regressions from reaching `main`.

Files:

- `.github/workflows/ci.yml`
- `README.md` if adding a badge or documenting CI Python version

Tasks:

- [ ] Add a workflow triggered by pull requests and pushes to `main`.
- [ ] Run Python syntax checks for changed Python files.
- [ ] Run the complete unittest suite.
- [ ] Validate `config.sample.ini` and `config.reference.ini` through the config
  contract test from PR 05.
- [ ] Use and document a Python version compatible with the supported Venus OS
  target.
- [ ] Optionally add a README CI badge.
- [ ] Optionally upload unittest output as a failure artifact.

Acceptance:

- A pull request cannot be merged with broken syntax, failing tests, or invalid
  reference configuration.

## PR 08 - P2: Refactor Wattpilot Control Into An Explicit State Machine

Depends on:

- PR 01
- PR 02

Goal: improve maintainability without changing established behavior.

Tasks:

- [ ] Separate telemetry input, PV allowance evaluation, grid guard, battery
  assist, phase switching, and status publishing.
- [ ] Introduce explicit state transitions instead of scattered flags and
  timestamps.
- [ ] Preserve all public D-Bus and MQTT paths from the runtime-status contract.
- [ ] Preserve existing config keys and defaults.
- [ ] Keep Manual mode behavior unchanged.
- [ ] Avoid combining this refactor with new features.
- [ ] Keep the existing behavior suite passing unchanged.
- [ ] Add transition tests for every state-machine edge.

Acceptance:

- The controller is easier to reason about, safer to modify, and produces one
  clear reason for each stop/start/phase decision.

## Suggested Implementation Order

1. PR 05, because it creates the config contract and exposes the current
   supported key set.
2. PR 06, because README should be generated or reviewed against the completed
   reference config.
3. PR 07, because CI should run the new config contract and existing behavior
   tests.
4. PR 08, because the state-machine refactor needs the previous behavior and
   config contracts in place before touching control flow.
