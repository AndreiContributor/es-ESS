# AGENTS.md

Repository guidance for AI coding agents working on es-ESS.

## Working Agreement

- For non-trivial code changes, inspect the repo first, explain the proposed
  solution, risks, and verification plan, then wait for explicit approval before
  editing files, installing dependencies, starting servers, or running modifying
  commands.
- Do not assume product intent, deployment constraints, hardware behavior,
  architecture boundaries, or test expectations when they are missing.
- Ask concise questions when missing information could materially affect the
  implementation or review result.
- Preserve unrelated user work. Do not revert, delete, or overwrite changes
  outside the approved task.

## Application Scope

es-ESS is a Python service bundle deployed on Victron Venus OS / Cerbo GX and
other GX devices. It is configured from `config.ini`-style files and exposes
independent services for energy-system integrations and automations.

The Fronius Wattpilot service is safety-sensitive EV-charge control. Its main
purpose is to integrate Wattpilot with VRM/D-Bus so an EV can charge from
available PV surplus while avoiding unintended grid use and avoiding discharge
of the home battery. In Auto/Eco mode, es-ESS uses SolarOverheadDistributor
allowances and fresh grid telemetry to start, stop, and adjust charging.

Wattpilot behavior to preserve and understand before changing code:

- Manual Wattpilot mode remains user-controlled. es-ESS may report Manual
  charging status to VRM/D-Bus/MQTT, but must not start, stop, phase-switch,
  current-limit, or otherwise control Manual charging.
- Auto/Eco mode is PV-surplus driven and must not intentionally use grid power
  when `AllowGridCharging=false`.
- Battery assist is optional and may only bridge short cloud dips for an
  already-running charge. It is bounded by config parameters such as SOC,
  maximum duration, maximum shortfall, and recovery time.
- The controller supports one-phase and three-phase charging and switches
  between them according to configured PV thresholds and timing guards.
- Current is bounded by configured per-phase minimum/maximum values and by the
  Wattpilot-reported effective limit.
- Runtime and user-visible state is published through the Victron EV-charger
  D-Bus/VRM paths plus a separate Wattpilot runtime-status contract for
  dashboards, Cerbo extensions, MQTT consumers, and diagnostics.

Key areas to inspect before changing behavior:

- Runtime entry points: `es-ESS.py` and `esESSService.py`.
- Wattpilot control and reporting: `FroniusWattpilot.py`, `Wattpilot.py`,
  `WattpilotRuntimeStatus.py`, and the command-free
  `WattpilotSessionStatistics.py` observer.
- Wattpilot architecture boundaries and safety invariants:
  `docs/wattpilot-architecture.md`.
- App-wide service inventory and integration boundaries:
  `docs/service-inventory.md`.
- Configuration documentation: `config.sample.ini` and `README.md`.
- Hardware and external integrations: Victron Venus OS, Cerbo GX, D-Bus, MQTT,
  Fronius Wattpilot, Fronius meters, Shelly devices, PV inverter data, and
  temperature data.
- Tests: hardware-free regression tests live under `tests/`.
- Service scripts: `install.sh`, `restart.sh`, `kill_me.sh`, `uninstall.sh`,
  and `service/run`.

Treat charging behavior, phase switching, grid usage, battery discharge, stale
telemetry, reconnection handling, and configuration compatibility as
safety-sensitive.

## Global Rules For Every PR

- Implement only the task described in that PR.
- Before implementing or reviewing Wattpilot behavior, read
  `docs/wattpilot-architecture.md`.
- Keep normal Wattpilot Manual mode unchanged. Reporting status is allowed;
  controlling Manual charging is not.
- In Auto/Eco mode, do not intentionally use grid power.
- Battery assist remains an optional, time-limited bridge for an
  already-running charge only.
- Wattpilot session statistics remain observation-only: no command, dispatch,
  D-Bus/MQTT control, configuration-default, or vehicle-identity ownership.
- Add or update unit tests for every behavior change.
- Run syntax checks and the full test suite before opening the PR.
- Update README/config documentation when a new setting or behavior is
  introduced.
- Update `docs/wattpilot-architecture.md` whenever a task changes Wattpilot
  module responsibilities, command boundaries, safety invariants, or the public
  D-Bus/MQTT runtime-status contract.
- Do not add shared 16 A cable/current-limiting logic.
- Preserve the supported runtime baseline in `RuntimeCompatibility.py`: clean
  Venus OS `v3.75` only, Wattpilot firmware `42.5`, and operator-verified
  Solar.wattpilot app `2.1.0`. The v3.75 migration and supervised live GX
  validation are complete. Do not add or restore another version without
  explicit integration validation and matching tests.

## Backlog And Review Workflow

- Use `.agents/skills/es-ess-code-review/` for architecture-aware code reviews.
- Use `.agents/skills/maintain-es-ess-backlog/` for manually invoked periodic
  backlog refresh, evidence review, structural checks, and safe compaction.
- Keep the implementation backlog in root `BACKLOG.md`.
- If `BACKLOG.md` exists, update it in place. If it does not exist, create it.
- Do not create duplicate backlog files unless explicitly requested.
- Preserve useful existing backlog context.
- Move finished items to a completed section with a short completion note/date;
  do not delete them immediately unless the user asks or the item is clearly
  obsolete.
- Mark obsolete items only when the repository review proves they no longer
  apply, and explain why.

## Testing Expectations

- Every production behavior change must include updated or new tests.
- Prefer existing test patterns under `tests/`.
- Include targeted tests for the changed behavior and run the full test suite
  before delivery when feasible.
- If hardware, Venus OS, MQTT, or D-Bus access is required and unavailable,
  document what could not be tested and provide manual validation steps.

## Documentation Expectations

- Update `README.md` and `config.sample.ini` whenever
  user-facing behavior, configuration, defaults, units, or supported ranges
  change.
- Update `docs/wattpilot-architecture.md` whenever Wattpilot architecture,
  command ownership, safety invariants, or runtime-status contracts change.
- Update `docs/service-inventory.md` whenever service initialization,
  `[Services]` flags, service config sections, D-Bus/MQTT contracts, external
  dependencies, grid-setpoint ownership, or active/dormant service status
  changes.
- If any of those files are changed, provide complete updated versions in the
  delivery package.
- At the end of each task, check whether this file needs an update. If agent
  guidance changed, update and compact `AGENTS.md` in the same change.

## Delivery Requirements

- Return complete replacement files for every changed file.
- Do not provide diff patches, partial snippets, line-number edits, or
  "replace this section" instructions.
- Preserve unrelated content in each file.
- Include a short list of files changed.
- Include complete updated tests whenever production code changes.
- Include complete updated `config.sample.ini` and `README.md` files whenever
  those files are changed.
