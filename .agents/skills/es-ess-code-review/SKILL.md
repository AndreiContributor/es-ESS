---
name: es-ess-code-review
description: Review es-ESS and update BACKLOG.md with safety-focused, architecture-aware, implementation-ready findings. Use when asked to run the es-ESS code review workflow, inspect Wattpilot or service risks, review Victron Venus OS / GX integration behavior, or maintain the es-ESS implementation backlog.
---

# es-ESS Code Review

Review es-ESS as a Python service bundle for Victron Venus OS / GX devices.

## Required Reading Before Any Review

Read these files first, in order:

1. `AGENTS.md` — delivery rules, safety invariants, and working agreement.
   Every finding and proposed implementation must comply with these rules.
2. `BACKLOG.md` — existing findings, completed items, and implementation order.
   Do not duplicate open items. Do not reopen completed items unless new
   evidence contradicts the completion note.
3. `docs/wattpilot-architecture.md` — module boundaries and safety invariants
   for any finding that touches Wattpilot behavior.
4. `docs/service-inventory.md` — active/dormant service status, D-Bus
   publishers, MQTT boundaries, HTTP polling, and grid-setpoint ownership for
   any finding that touches service initialization or integration.
5. `config.sample.ini` — the single maintained configuration reference.
   Active Wattpilot keys must be covered by `tests/test_config_contract.py`.
6. `README.md` — user-facing behavior, setup, and service configuration tables.

## Files To Inspect

Start with:

- `es-ESS.py` — orchestrator: MQTT setup, reconnect handlers, service lifecycle,
  config migration, grid-setpoint combiner, worker scheduling, signal handlers.
- `esESSService.py` — base class lifecycle and shared registration helpers.
- `Globals.py` — superglobals and `getUserTime()`.
- `FroniusWattpilot.py` — Wattpilot controller: D-Bus paths, command boundary,
  Auto/Eco policy, dispatch, phase switching, session paths.
- `Wattpilot.py` — WebSocket client and reconnect worker loop.
- `WattpilotRuntimeStatus.py` — observer/publisher; must not issue commands.
- `WattpilotDecisionInputs.py`, `WattpilotSafetyDecisions.py`,
  `WattpilotPhaseDecisions.py`, `WattpilotControlState.py` — pure helpers;
  must not issue commands, publish D-Bus/MQTT, or hold mutable state.
- `SolarOverheadDistributor.py` — PV surplus allocation, HTTP consumers,
  threaded consumer dict, energy stats persistence.
- `NoBatToEV.py` — grid-setpoint offset for AC-out EV charging.
- All other active service modules: `MqttPVInverter.py`, `Shelly3EMGrid.py`,
  `ShellyPMInverter.py`, `FroniusSmartmeterJSON.py`, `MqttExporter.py`,
  `MqttTemperature.py`, `TimeToGoCalculator.py`.
- `tests/` — hardware-free test suite; note which active service modules have
  no test file at all.
- `install.sh`, `restart.sh`, `kill_me.sh`, `uninstall.sh`, `service/run`.
- `.github/workflows/ci.yml` — CI triggers, Python version, test steps.

## Architecture Summary

Include in every review:

- Runtime entry points and service lifecycle order.
- Which services are active and which are dormant.
- External integrations: Wattpilot WebSocket, D-Bus, main MQTT, local Venus MQTT,
  HTTP polling (Fronius, Shelly), SolarOverheadDistributor request namespace.
- Current test coverage: which modules have test files, which do not.
- Any deployment or firmware details that remain unclear.

## Crash-Class Patterns To Check

Look for these in every service module:

- **None arithmetic**: D-Bus subscription `.value` starts as `None`. Any
  arithmetic before a None guard raises `TypeError`. Check every `_update()`
  method that reads `.value` fields before summing or comparing them.
- **Unguarded Wattpilot fields**: `wattpilot.power1/2/3` and similar client
  properties initialize to `None`. Check every caller for a None guard.
- **Missing lock in threaded iteration**: Compare every method that iterates a
  shared dict against the methods that mutate it under a lock. Flag any
  iterator that does not acquire the same lock.
- **Unbounded HTTP requests**: Every `requests.get()` without a `timeout=`
  argument can block a worker thread indefinitely. Flag all callsites.
- **Division by zero**: Check computed denominators (`target`, `overhead`,
  `consumption`, ratios) for a zero branch before division.
- **GLib runaway poll**: `gobject.timeout_add(0, ...)` or
  `interval=0` fires as fast as the event loop allows and starves other
  workers. Flag any interval read from config without a `> 0` guard.

## Security Patterns To Check

- **`eval()` on config values**: Any `eval()` on a string that includes a
  user-supplied config value executes arbitrary Python. Flag all `eval()` calls.
- **`os.popen()` with string interpolation**: Shell metacharacters in a
  format-string argument to `os.popen()` are executed by `/bin/sh -c`. Flag
  all `os.popen()` calls. Prefer `subprocess.run()` with an argument list.
- **Config value injection into shell commands**: Any `os.system()`,
  `subprocess.run(shell=True, ...)`, or similar call that formats a config
  value into a shell string. Flag all such callsites.

## MQTT Client Boundary Checks

- In every reconnect handler, verify the correct client is used:
  `onMainMqttConnect()` must subscribe on `mainMqttClient`;
  `onLocalMqttConnect()` must subscribe on `localMqttClient`.
- Verify `is_connected` is called as a method (`is_connected()`) not read as a
  boolean attribute. In Paho MQTT, `is_connected` is a method; the unguarded
  attribute is always truthy.
- Flag any `mainMqttClient` call inside a local-MQTT code path and vice versa.

## Wattpilot Safety Invariants To Verify

Before flagging any Wattpilot finding, confirm the proposed fix preserves:

- Manual mode is never commanded by es-ESS (start/stop/current/phase).
  The one approved exception: a one-time Auto/Eco constraint release when
  transitioning to Manual.
- `/SetCurrent` and `/StartStop` writes are accepted only when Wattpilot
  telemetry confirms ECO mode. Missing or Manual/default mode telemetry must
  fail closed.
- Auto/Eco does not intentionally use grid power when `AllowGridCharging=false`.
- Battery assist only bridges an already-running charge; it must not start a
  charge or trigger a phase-up.
- `WattpilotControlState` owns dispatch branch selection; command side effects
  stay in `FroniusWattpilot.py`.
- Pure helpers (`WattpilotDecisionInputs`, `WattpilotSafetyDecisions`,
  `WattpilotPhaseDecisions`, `WattpilotControlState`, `WattpilotRuntimeStatus`)
  must not issue Wattpilot commands, publish D-Bus/MQTT, or hold mutable state.

## Dormant Service Rules

Do not propose reactivating a dormant service unless a separate, complete
implementation task exists with its own config section, service-inventory
update, tests, and manual validation plan. Do not mix dormant-service
reactivation with Wattpilot control, safety, or phase-switching changes.
Do not write grid-setpoint commands directly outside the shared request
combiner (see `ChargeCurrentReducer.py` as the negative example).

## Test Coverage Check

For every finding, check whether the affected code path has a hardware-free
test. When it does not:

- Note the gap explicitly in the backlog item's Tests section.
- Propose at least the minimum test that would catch a regression.
- Follow the stub pattern established in `tests/test.py` and
  `tests/test_eco_pv_policy.py`: stub Victron/D-Bus/MQTT/Wattpilot
  dependencies with `types.ModuleType`, `unittest.mock.Mock`, and
  `importlib.util` — no real hardware, no real network.

Active service modules that currently have no test file are the highest-value
test coverage gap. List them explicitly in the review summary.

## CI Coverage Check

After proposing new test files, verify that `python -m unittest discover -s tests`
would pick them up automatically (file name matches `test_*.py`, class extends
`unittest.TestCase`). Confirm `.github/workflows/ci.yml` does not need changes
to cover them. If a new config key is added, confirm `tests/test_config_contract.py`
will fail until it is added to `config.sample.ini`.

## Manual Testing Guidance

When a finding requires manual validation, classify it by what the user actually
needs to do on the GX device:

- **Log-only** (safe in production): restart es-ESS, tail the log, no hardware
  action needed. Use for startup crashes, config validation, and structural
  changes.
- **Fault simulation** (do in a low-risk window): briefly disconnect a broker,
  meter, or consumer endpoint. Use for reconnect bugs, None-value guards, and
  HTTP timeout behavior.
- **Active charging required**: a car must be connected and charging. Use only
  for setpoint math verification, not for crash-fix confirmation.
- **Hardware not needed**: unit tests are the sole verifier. Use for pure
  helpers, security fixes, and structural refactors.

Document which category applies to each backlog item's manual validation section.

## Backlog Update Rules

- Read `references/backlog-format.md` before creating or substantially
  restructuring backlog content.
- Update `BACKLOG.md` in place. Preserve existing context, completion notes,
  and the Suggested Implementation Order section.
- Insert new items before the Suggested Implementation Order section.
- Add new items to the Suggested Implementation Order at the appropriate
  priority position with a one-line rationale.
- Do not renumber existing items in the order list; append new ones at the
  correct priority position.
- Before editing `BACKLOG.md`, ask concise questions only when missing
  information materially affects correctness or priority. Otherwise continue
  with clearly stated assumptions.
