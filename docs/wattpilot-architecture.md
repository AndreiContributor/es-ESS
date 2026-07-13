# Wattpilot Architecture Boundaries

This note documents the intended boundaries for the current Wattpilot
implementation. It describes the code as it exists today and the constraints
future refactors should preserve. It is not a new design or behavior change.

## Runtime Shape

The Wattpilot integration is enabled as an es-ESS service from
`config.ini` / `config.sample.ini`. The main runtime in `es-ESS.py` creates the
service, initializes its D-Bus paths, MQTT subscriptions, D-Bus subscriptions,
worker callbacks, and shutdown handling through the common `esESSService`
lifecycle.

Wattpilot control is safety-sensitive because it can start, stop, current-limit,
and phase-switch EV charging. Changes in this area must preserve Manual mode,
PV-only Auto/Eco behavior, grid-use guards, battery-assist limits, telemetry
freshness checks, and the public D-Bus/MQTT status contract.

For post-deploy, post-firmware, morning daylight and mid-day PV-surplus
validation, `scripts/es-ess-health-monitor.sh` reads the public service state
and Wattpilot D-Bus/runtime-status contract without issuing commands. Its
installation and interpretation notes live in `docs/es-ess-health-monitor.md`.

## Module Responsibilities

### `RuntimeCompatibility.py`

`RuntimeCompatibility.py` is the single validated runtime-version baseline.

It owns:

- Exact Venus OS compatibility (`v3.75`) before the application
  constructs services, connects MQTT, or writes the Victron grid setpoint.
- Exact Wattpilot firmware compatibility (`42.5`) from `fwv` telemetry.
- The operator-verified Solar.wattpilot mobile app baseline (`2.1.0`), which
  cannot be queried by es-ESS.
- Version normalization that accepts an optional leading `v` but retains beta
  or build qualifiers so an unvalidated candidate cannot match a clean release.

The module must not infer that a newer version is compatible. A baseline update
requires explicit integration validation and matching tests.

### `Wattpilot.py`

`Wattpilot.py` is the Wattpilot WebSocket client and transport boundary.

It owns:

- WebSocket connection setup and close/error/message callbacks.
- The single Wattpilot connection worker loop, including automatic reconnect
  attempts controlled by `_auto_reconnect` and `_reconnect_interval`.
- Wattpilot authentication and secure message wrapping.
- Parsing Wattpilot status messages into local client properties.
- Recording wall-clock receipt and change timestamps for raw `lmo` mode
  telemetry so delayed external mode transitions can be diagnosed.
- Sending direct Wattpilot protocol updates such as `amp`, `frc`, `psm`, and
  `lmo` when the controller asks for them.
- Enforcing a controller-installed compatibility callback at the common
  `setValue` transport boundary. Authentication and status requests remain
  available while commands are blocked so firmware can be identified.
- Publishing raw client events to registered event handlers.

It must not own:

- PV allowance decisions.
- No-grid policy.
- Battery-assist policy.
- Manual versus Auto/Eco control policy.
- Phase-switch eligibility rules.
- VRM, D-Bus, MQTT, or dashboard status semantics.

The client can expose transport and Wattpilot-state facts, but charging policy
belongs outside this module. WebSocket callbacks should remain lightweight:
they may update local transport state and emit registered events, but reconnect
ownership stays in the connection worker loop rather than recursively entering
`run_forever()` from a close callback.

### `FroniusWattpilot.py`

`FroniusWattpilot.py` is the current Wattpilot integration and controller
boundary.

It owns:

- The Victron EV-charger D-Bus service paths and writable command callbacks.
- Mapping Wattpilot state into VRM-compatible status values.
- Session energy/time compatibility paths: `/Ac/Energy/Forward` mirrors
  `/Session/Energy`, and `/ChargingTime` mirrors `/Session/Time`.
- Auto/Eco PV surplus charging decisions.
- SolarOverheadDistributor allowance requests and allowance consumption,
  delegating pure allowance freshness checks to `WattpilotDecisionInputs.py`.
- Grid telemetry state updates and no-grid stop behavior, delegating pure
  telemetry freshness checks to `WattpilotDecisionInputs.py` and grid-import
  guard decisions to `WattpilotSafetyDecisions.py`.
- Optional battery-assist rules for an already-running charge, delegating
  assist eligibility, timeout, lockout, and recovery decisions to
  `WattpilotSafetyDecisions.py`.
- One-phase and three-phase switching orchestration, delegating pure thresholds,
  target-current, distributor-request, and shared bidirectional phase timing
  decisions to
  `WattpilotPhaseDecisions.py`.
- Continuation-only grid fallback when `AllowGridCharging=true`. This can hold
  an already-running Auto/Eco charge through insufficient PV, but cannot start
  a new grid-only session. Victron ESS, not the Wattpilot controller, determines
  whether the physical shortfall comes from battery or grid.
- Explicit control-state dispatch through `WattpilotControlState.py`.
  The selector owns the `_update()` branch choice, while the controller still
  owns command side effects, D-Bus/MQTT publication, service messages, and
  mutable timers.
- Wattpilot command issuing through the `Wattpilot` client.
- Wattpilot shutdown behavior during es-ESS termination.

This file remains the place where command side effects are allowed. Refactors
should move decision logic only when the same behavior is covered by focused
tests and command side effects remain easy to audit.

### `WattpilotDecisionInputs.py`

`WattpilotDecisionInputs.py` owns pure or mostly pure input evaluation helpers
for the Wattpilot controller.

It owns:

- Finite numeric parsing for Wattpilot decision inputs.
- Grid telemetry validity and freshness evaluation across required phases.
- SolarOverheadDistributor assigned-allowance freshness evaluation.
- Minimum-allowance evaluation for Auto/Eco charging.
- Fresh raw-overhead evaluation for the safe three-to-one fallback path.

It must not own:

- D-Bus or MQTT subscriptions/publication.
- Wattpilot command issuing.
- Service messages.
- Manual versus Auto/Eco mode policy.
- Grid-import stop policy, battery-assist policy, or phase-switch commands.

The controller still stores the live timestamps and values. This helper only
answers whether a supplied input snapshot is fresh and usable.

### `WattpilotSafetyDecisions.py`

`WattpilotSafetyDecisions.py` owns pure decision helpers for two
safety-sensitive Auto/Eco policies.

It owns:

- Grid-import guard timing and threshold decisions.
- Battery-assist eligibility for an already-running charge.
- Battery-assist maximum-duration lockout decisions.
- Battery-assist recovery decisions after PV fully covers active EV demand.
- Internal reason codes used by tests and controller branching.

It must not own:

- Wattpilot command issuing.
- D-Bus or MQTT publication.
- Service messages.
- Grid telemetry sampling or freshness evaluation.
- PV allowance sampling or freshness evaluation.
- Manual versus Auto/Eco command-boundary policy.
- Phase-switch commands or phase-mode runtime-status publication.

The controller still stores mutable timestamps such as `gridImportSince`,
`batteryAssistSince`, and `batteryAssistRecoverySince`, publishes user-visible
messages, and issues Wattpilot commands. This helper only evaluates supplied
snapshots and returns the next controller-owned timer values.

### `WattpilotPhaseDecisions.py`

`WattpilotPhaseDecisions.py` owns pure decision helpers for one-phase and
three-phase Auto/Eco decisions.

It owns:

- Phase-up and phase-down PV threshold clamping against the electrical
  three-phase minimum.
- Desired phase-mode selection from assigned PV allowance and hysteresis.
- Target current calculation bounded by configured minimum/maximum current and
  the Wattpilot-reported effective maximum.
- SolarOverheadDistributor maximum-request sizing, including the limited
  one-phase phase-up probe and cooldown suppression.
- Shared one-to-three and three-to-one stability/cooldown decisions, returning
  the next controller-owned candidate timer values.
- One-to-three short-drop grace eligibility on the normal current-adjustment
  path, which may preserve an existing candidate only while assigned allowance
  remains above the effective three-phase floor.

It must not own:

- Wattpilot command issuing.
- D-Bus or MQTT publication.
- Service messages.
- Raw-overhead freshness checks or phase-down fallback authorization.
- Pending phase-switch confirmation from live Wattpilot telemetry.
- Manual versus Auto/Eco command-boundary policy.

The controller still stores mutable phase-switch timers, publishes
user-visible messages, starts transition grace, confirms pending phase
switches from live telemetry, and issues `set_phases()` / `set_power()`
commands.

### `WattpilotControlState.py`

`WattpilotControlState.py` owns the explicit, pure control-state ordering for
the Wattpilot controller.

It owns:

- The named controller states used to describe each `_update()` branch.
- Model-status classification for charging and not-charging Wattpilot states.
- Pure selection of the next controller branch from an input snapshot.
- Formatting of selector inputs for diagnostics and tests.

It must not own:

- Wattpilot command issuing.
- D-Bus or MQTT publication.
- Service messages.
- Mutable controller timers such as allowance, phase-switch, grid-import, or
  battery-assist timestamps.
- Live telemetry sampling.

`FroniusWattpilot.py` gathers the safety facts in the same order as the
pre-selector controller: stale no-grid telemetry short-circuits before
grid-import checks, grid import is evaluated before pending phase-switch
reconciliation, and pending phase-switch reconciliation is evaluated before
disconnect/model-status routing. The selector then chooses the explicit state,
and the controller dispatches that state to the existing side-effect handlers.

### `WattpilotRuntimeStatus.py`

`WattpilotRuntimeStatus.py` owns the separate runtime-status contract for
dashboards, Cerbo extensions, MQTT consumers, and diagnostics.

It owns:

- Runtime-status D-Bus paths such as `/ControlState`, `/PhaseMode`,
  `/BatteryAssistActive`, `/GridImportGuardActive`, `/TelemetryHealthy`, and
  the expected/actual runtime compatibility paths.
- Matching MQTT runtime-status publication under
  `es-ESS/FroniusWattpilot/RuntimeStatus`.
- Observation of controller transitions and Wattpilot transport health.
- Fault/status publication that does not interrupt charger control.

It must not issue Wattpilot commands. It is an observer and publisher only. Raw
WebSocket callbacks should record lightweight evidence and let the normal
controller path publish status.

### `SolarOverheadDistributor.py`

`SolarOverheadDistributor.py` is the PV surplus allocation service used by the
Wattpilot controller.

It owns the shared surplus calculation, battery-charge reservation, consumer
requests, and allowance publication. It does not own Wattpilot command policy.
The Wattpilot controller decides whether a Wattpilot allowance is fresh, valid,
and sufficient for a charge action.

## Safety Invariants

Future Wattpilot changes must preserve these invariants:

- Venus OS must match the explicitly supported clean release (`v3.75`) before
  es-ESS starts any service or grid-setpoint side effect.
- Wattpilot commands must remain blocked until `fwv` telemetry exactly matches
  validated firmware `42.5`. Missing telemetry fails closed.
- Solar.wattpilot app `2.1.0` is a commissioning baseline only; it cannot be
  asserted from the local es-ESS runtime.
- The Wattpilot WebSocket query value `version=1.2.9` is a protocol/client
  identifier, not the mobile app version.

- Normal Wattpilot Manual mode remains user-controlled. es-ESS may report
  Manual status, but must not start, stop, phase-switch, or current-limit a
  Manual charging session unless that behavior is explicitly approved and
  tested. The approved exception is a one-time release when leaving Auto/Eco
  for Manual/default mode: es-ESS may clear its previous Auto/Eco phase and
  current commands so the Manual session is not left constrained by PV control.
- Normal Manual/default startup is command-free even while Wattpilot telemetry
  is still arriving. es-ESS may infer the reported phase from finite live power,
  but it must not issue `psm`, `amp`, or `frc`; idle automatic-phase
  initialization is limited to explicitly confirmed ECO mode.
- Writable EV-charger `/SetCurrent` and `/StartStop` commands may issue
  Wattpilot current, phase, start, or stop commands only when Wattpilot mode
  telemetry confirms ECO mode. Missing or Manual/default mode telemetry must
  fail closed. `/Mode` selection is a separate explicit mode-change path.
- Auto/Eco mode is PV-surplus driven and must not intentionally use grid power
  when `AllowGridCharging=false`.
- `AllowGridCharging=true` may continue an already-running Auto/Eco charge
  despite import, but must not authorize a new grid-only start. The controller
  does not claim to select battery versus grid as the physical energy source.
- Battery assist may only bridge a short PV dip during an already-running
  charge and must remain bounded by SOC, duration, shortfall, and recovery
  settings.
- Battery assist must not start a charge, create a phase-up candidate, or issue
  a switch to three phases. An eligible continuation bridge may intentionally
  leave an already-existing one-to-three candidate timer unchanged; fresh
  assigned allowance must still meet the full phase-up threshold before the
  controller can issue the phase command.
- Fresh grid telemetry and fresh allowance data are required for no-grid
  Auto/Eco decisions.
- A confirmed physical vehicle disconnect must stop Auto/Eco current and phase
  control even if Wattpilot briefly continues to report a stale active charging
  model status.
- Raw overhead may help with a safe three-to-one fallback, but must not start
  charging or authorize a phase-up.
- Assigned Wattpilot allowance is authoritative for whether the consumer owns
  enough PV to remain on three phases. Raw overhead may estimate the physical
  shortfall and support a safer one-phase fallback, but must not override an
  insufficient assigned three-phase allowance or mutate controller phase state
  without a matching Wattpilot phase command.
- `MinPhaseSwitchSeconds` is the single normal stability/cooldown timer for
  both phase directions. A no-grid session may reduce phase or stop before the
  timer expires when bounded battery assist cannot safely bridge the deficit.
- On the normal current-adjustment path, `SurplusDropGraceSeconds` may preserve
  an active one-to-three candidate through a shorter-than-grace dip below the
  phase-up threshold only while fresh assigned allowance remains above the
  effective three-phase floor. A deeper or longer dip resets the candidate when
  that path evaluates it. An eligible battery-assist continuation returns while
  holding the existing one-phase command and may therefore leave an already-
  existing candidate's wall-clock timer running through the bounded assist
  window. Battery assist cannot create the candidate or issue phase-up. Raw
  overhead cannot authorize phase-up, and fresh assigned allowance must meet
  the full phase-up threshold at the command boundary.
- During a sustained three-phase PV deficit, bounded battery assist or
  explicitly allowed grid fallback may hold the running phase/current. Once
  the shared timer expires, one-phase PV availability authorizes the reduction.
- Current limits must respect configured per-phase bounds and the
  Wattpilot-reported effective limit.
- Public D-Bus and MQTT runtime-status paths are compatibility contracts.
- Keep read-only diagnostics such as `scripts/es-ess-health-monitor.sh`
  command-free. Monitoring tools may read the runtime-status contract, service
  state, selected config values and logs, but must not write Wattpilot, D-Bus,
  MQTT, service or configuration state.
- Raw `lmo` receipt/change timestamps are diagnostic transport facts only.
  They must not be treated as a generic mode-expiry timeout or independently
  widen Wattpilot command authority without hardware evidence and an approved
  controller policy.

## Refactoring Guidance

Refactors should be small and behavior-preserving:

- Add characterization tests before moving decision logic.
- Keep Wattpilot protocol details in `Wattpilot.py`.
- Keep Wattpilot reconnect lifecycle changes isolated from charger-control
  policy changes.
- Keep charger command side effects in `FroniusWattpilot.py` until a tested
  command boundary exists.
- Extract pure decision helpers before introducing a broader state machine.
- Keep the explicit state selector pure and command-free; command side effects
  remain in the controller dispatch handlers.
- Do not combine config/default changes with control-flow refactors.
- Do not add shared 16 A cable/current-limiting logic.
