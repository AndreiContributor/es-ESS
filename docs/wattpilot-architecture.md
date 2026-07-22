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

### Example electrical topology

An illustrative installation may place a grid-exchange meter before the
Victron inverter/chargers, use an optional interlocked maintenance changeover,
connect an AC-coupled PV inverter at a site-side bus, and distribute loads
through a site protective device. A dedicated site-current meter then measures
all loads at the boundary governed by `SiteMaxCurrent` before they split into
separately protected downstream circuits, including the EV circuit. A 20 A
site limit and a 16 A EV branch are examples, not repository requirements.

Actual installations vary. The Cerbo GX is a supervisory/data device rather
than an AC series component, and batteries are on the Victron DC side.
`Position=0` or `Position=1` must match the Wattpilot's actual placement; the
setting does not prove wiring or detect a changeover position. The selected
site-current boundary must include non-EV and Wattpilot current before their
downstream split so the existing EV-subtraction and headroom calculation
remains valid.

An optional maintenance bypass is not currently a controller state or
command-authority input. The GX may remain powered from DC or may become
unavailable, depending on installation wiring. An abrupt loss cannot execute
the graceful SIGTERM stop path, and no verified Wattpilot-native
controller-loss fallback is owned by this checkout. Any future fallback must
use explicit, validated evidence and semantics for the target installation;
it must not infer bypass from generic telemetry or transport loss.

For post-deploy, post-firmware, morning daylight and mid-day PV-surplus
validation, `scripts/es-ess-health-monitor.sh` reads the public service state
and Wattpilot D-Bus/runtime-status contract without issuing commands. Its
installation and interpretation notes live in `docs/es-ess-health-monitor.md`.

For the separate native-PV command-ownership investigation,
`scripts/wattpilot-setting-capture.py` authenticates with the vehicle
disconnected, blocks every `setValue` request, compares two full-status
snapshots around one operator-controlled app setting change, and emits only
redacted/fingerprinted property differences. The procedure and pass/fail gates
live in `docs/wattpilot-command-ownership-validation.md`. This is evidence
collection only and does not widen Auto/Eco command authority.

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
- A bounded stop/start handoff that waits outside the connection lock before
  replacing a worker whose stop event is already set, preserving single-worker
  ownership during rapid disconnect/reconnect sequences.
- Wattpilot authentication and secure message wrapping.
- Parsing Wattpilot status messages into local client properties.
- Strict read-only parsing of firmware `42.5` native-command settings `fup`
  (`Use PV surplus`) and `ful` (flexible tariff). Non-booleans and reconnect
  gaps become unavailable rather than truthy/falsy guesses.
- Recording wall-clock receipt and change timestamps for raw `lmo` mode
  telemetry so delayed external mode transitions can be diagnosed.
- Sending direct Wattpilot protocol updates such as `amp`, `frc`, `psm`, and
  `lmo` when the controller asks for them.
- Returning the common guarded-send acceptance result from the phase, current,
  and start/stop command helpers so the controller does not publish a
  transition for a command rejected before transport.
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
- Command-free connection/charging statistics integration through
  `WattpilotSessionStatistics.py`. The controller supplies confirmed state and
  telemetry, logs returned versioned records at transition boundaries, and
  emits at most one APP_DEBUG checkpoint per connected minute.
- Auto/Eco PV surplus charging decisions.
- SolarOverheadDistributor allowance requests and allowance consumption,
  delegating pure allowance freshness checks to `WattpilotDecisionInputs.py`.
- Grid telemetry state updates and no-grid stop behavior, delegating pure
  telemetry freshness checks to `WattpilotDecisionInputs.py` and grid-import
  guard decisions to `WattpilotSafetyDecisions.py`.
- Mandatory whole-site physical L1/L2/L3 current sampling, freshness,
  headroom enforcement, and diagnostics. `WattpilotSiteCurrentSource.py`
  normalizes the explicitly selected provider, `Shelly3EMSiteCurrent.py` owns
  the asynchronous Shelly snapshot, and pure calculations remain delegated to
  `WattpilotSiteCurrentDecisions.py`. The default Venus provider live-reads the
  three subscribed BusItems once at the start of each controller cycle. That
  immutable guard result is passed through state selection and command
  dispatch, so one cycle cannot act on two contradictory provider reads. The
  Shelly provider timestamps only a complete successful RPC sample. There is
  no automatic provider fallback.
- Optional battery-assist rules for an already-running charge, delegating
  assist eligibility, timeout, lockout, and recovery decisions to
  `WattpilotSafetyDecisions.py`.
- Phase-aware EV-charger diagnostics under `/BatteryAssist/Shortfall`,
  `/BatteryAssist/ShortfallPerPhase`, `/BatteryAssist/ActivePhases`, and
  `/BatteryAssist/EffectiveLimit`.
- Battery-SOC validity and receive-time tracking for battery assist and the
  EV-priority battery-reservation bypass, delegating pure timestamp freshness
  evaluation to `WattpilotDecisionInputs.py`.
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
- A final common command guard that applies exact firmware validation first,
  then rejects positive Auto/Eco current, start, or phase commands without
  fresh and sufficient physical site-current headroom. Safe zero-current,
  Force Off, and automatic-phase release commands remain available.
- Transactional Auto/Eco start-state publication. The controller sends the
  guarded phase, current, and Start commands in that order and begins public
  transition grace only after all three are accepted. A rejection leaves the
  session stopped and rebuilds the stable-PV interval.
- Read-only command-authority evaluation. Positive current, start, phase-up,
  and normal Auto/Eco dispatch require ECO plus `fup=false` and `ful=false`;
  missing or conflicting settings fail closed while zero-current and safe stop
  remain available.
- Rejection of a Manual-to-Auto request until both native command competitors
  are observed disabled. The user-requested transition may then send `lmo=4`;
  any firmware-side re-enable blocks authority again.
- Wattpilot shutdown behavior during es-ESS termination.

This file remains the place where command side effects are allowed. Refactors
should move decision logic only when the same behavior is covered by focused
tests and command side effects remain easy to audit.

### `WattpilotSessionStatistics.py`

`WattpilotSessionStatistics.py` is the isolated mutable observer for durable
connection and charging evidence.

It owns:

- Separate confirmed vehicle-connection and measured charging-interval state.
- Process-local, non-identifying connection and interval correlation IDs.
- Monotonic Wattpilot session-counter deltas, with explicit reset, missing,
  partial-start, and partial-end evidence.
- Fresh sampled-power integration by one-/three-phase mode and physical phase,
  bounded by a maximum observation gap and accompanied by coverage and
  counter-reconciliation fields.
- First start-attempt and first measured-power timing, interruptions, current
  range, peak power, phase segments, minute checkpoints, and final summaries.
- Versioned, JSON-safe record dictionaries returned to the controller.

It must not own or access:

- Wattpilot command methods or the transport object.
- Auto/Eco, Manual, site-current, no-grid, battery-assist, phase-switch, or
  command-authority decisions.
- D-Bus/MQTT publication, service messages, configuration writes, or logging.

The component is stateful by design but command-free. `FroniusWattpilot.py`
remains responsible for converting live client properties into observation
samples and selecting INFO versus APP_DEBUG for returned records. A service
restart begins a partial observed connection when the vehicle is already
attached; it never joins unobserved energy across the restart.

For one-phase observations, `Charger1PhaseMapping` assigns the sampled energy
to the configured physical phase. In three-phase mode, the component records
all three Wattpilot-reported conductors but does not claim their individual
L1/L2/L3 ordering is electrician-verified. A session containing any
three-phase interval therefore publishes incomplete physical-phase mapping
unless a future separately validated mapping contract is introduced.

### `WattpilotDecisionInputs.py`

`WattpilotDecisionInputs.py` owns pure or mostly pure input evaluation helpers
for the Wattpilot controller.

It owns:

- Finite numeric parsing for Wattpilot decision inputs.
- Grid telemetry validity and freshness evaluation across required phases.
- SolarOverheadDistributor assigned-allowance freshness evaluation.
- Minimum-allowance evaluation for Auto/Eco charging.
- Fresh raw-overhead evaluation for reduction or minimum-current continuation
  of an already-running charge.

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

### `WattpilotSiteCurrentDecisions.py`

`WattpilotSiteCurrentDecisions.py` owns pure whole-site current calculations.

It owns:

- Validation of physical L1/L2/L3 site and Wattpilot phase-current snapshots.
- One-phase EV subtraction on the configured physical phase.
- Conservative three-phase EV subtraction using the smallest measured
  Wattpilot phase current on every physical phase.
- Per-phase non-EV load, headroom, limiting-phase, and equal three-phase
  allowed-current calculation.
- Immediate-reduction, stable-delay, and one-amp-per-cycle recovery decisions.

It must not sample telemetry, store timestamps, publish status, decide command
ownership, or issue Wattpilot commands. Those mutable and side-effect
responsibilities remain in `FroniusWattpilot.py`.

### Site-current providers

`WattpilotSiteCurrentSource.py` defines the normalized, command-free provider
snapshot and the default `VenusSystem` implementation. The Venus provider
live-reads all three configured D-Bus subscriptions and preserves the previous
timestamp for a phase whose transport read fails.

`Shelly3EMGen3Client.py` is a bounded, read-only HTTP RPC client. It validates
generation 3, model `S3EM-003CXCEU63`, the `triphase` profile, component id 0,
finite non-negative A/B/C currents, and empty phase/component error lists. It
uses local digest authentication when configured and never embeds credentials
in URLs or logs.

`Shelly3EMSiteCurrent.py` owns the lock-protected asynchronous meter snapshot,
periodic identity revalidation, and electrician-verified A/B/C-to-L1/L2/L3
mapping. Only a complete successful poll refreshes all three timestamps. A
failure invalidates the selected source without refreshing cached age. These
provider modules do not publish commands or register a Victron grid service.

### `WattpilotControlState.py`

`WattpilotControlState.py` owns the explicit, pure control-state ordering for
the Wattpilot controller.

It owns:

- The named controller states used to describe each `_update()` branch,
  including command-authority and site-current blocking before grid, phase,
  disconnect, or model-status dispatch.
- Model-status classification for charging and not-charging Wattpilot states.
  The [upstream API specification](https://github.com/goecharger/go-eCharger-API-v2/blob/main/API_KEYS_FIRMWARE/apikeys-en.md)
  defines `modelStatus` as the reason charging is currently allowed or denied
  and labels values `8`-`11` and `13`-`14` as
  `ChargingBecause...`; es-ESS therefore classifies all six as active charging.
  This classification is applied only after command-authority, site-current,
  no-grid telemetry/import, pending-phase, and confirmed-disconnect gates.
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
pre-selector controller: command authority is followed by mandatory stale or
insufficient site-current headroom, then stale no-grid telemetry before
grid-import checks. Grid import is evaluated before pending phase-switch
reconciliation, and pending phase-switch reconciliation is evaluated before
disconnect/model-status routing. The selector then chooses the explicit state,
and the controller dispatches that state to the existing side-effect handlers.
The controller also owns transition-only INFO diagnostics for protocol charging
statuses `8`-`11` and `13`-`14`. It logs entry, a change between those values,
and exit with the stable text `Wattpilot special charging model status`; it does
not log every five-second controller cycle. The selector and shared
classification helpers remain pure and log-free.

### `WattpilotRuntimeStatus.py`

`WattpilotRuntimeStatus.py` owns the separate runtime-status contract for
dashboards, Cerbo extensions, MQTT consumers, and diagnostics.

It owns:

- Runtime-status D-Bus paths such as `/ControlState`, `/PhaseMode`,
  `/BatteryAssistActive`, `/GridImportGuardActive`, `/TelemetryHealthy`,
  `/CommandAuthorityOk`, `/CommandAuthorityLiteral`, the strict native-setting
  observations, and the expected/actual runtime compatibility paths.
- Matching MQTT runtime-status publication under
  `es-ESS/FroniusWattpilot/RuntimeStatus`.
- Observation of controller transitions and Wattpilot transport health.
- Fault/status publication that does not interrupt charger control.
- Runtime state `12`, `Stopped for site current limit`, while the controller
  remains latched off after a site-current intervention. Stale site inputs use
  the existing stale-telemetry state.

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
- Invalid grid-import, telemetry-freshness, battery-assist, or startup-ratio
  configuration must fail before MQTT, D-Bus, or service initialization. Zero
  remains valid only for deliberately immediate/non-negative thresholds; all
  freshness windows remain positive and raw-overhead freshness is at least the
  controller's five-second floor.
- `SiteMaxCurrent` is a mandatory physical per-phase Auto/Eco limit.
  `SiteCurrentSource` must explicitly select `VenusSystem` or
  `Shelly3EMGen3`; `Charger1PhaseMapping` must be L1, L2, or L3;
  site-current freshness must be positive and recovery time non-negative.
  Shelly channel mapping must be a one-to-one permutation of L1/L2/L3.
- Wattpilot commands must remain blocked until `fwv` telemetry exactly matches
  validated firmware `42.5`. Missing telemetry fails closed.
- Auto/Eco command authority additionally requires raw ECO telemetry,
  `fup=false`, and `ful=false`. Missing/malformed fields, native PV enabled, or
  flexible tariff enabled must block positive current, start, phase-up, and
  normal control dispatch. A safe zero-current/stop remains permitted only in
  confirmed ECO; Manual remains user-controlled.
- Auto/Eco always requires fresh, finite, non-negative physical consumption
  currents for L1/L2/L3. An active charge also requires fresh Wattpilot `nrg`
  phase-current telemetry. Missing, stale, invalid, negative, or phase-uncertain
  data blocks starts and stops an active charge without a phase command.
- D-Bus value-change callbacks are not site-current heartbeats because a valid
  zero or nonzero current may remain unchanged. The Venus provider performs a
  live `GetValue` read of all three physical phase paths once per eligible
  controller cycle. The resulting timestamped guard snapshot is reused for
  state selection and active-charge dispatch; it fails closed without another
  provider read if it expires before dispatch. The Shelly provider uses the
  timestamp of its last complete HTTP poll. A failed selected-source read never
  refreshes cached age and fails Auto/Eco closed; the controller must not
  silently fall back to another provider.
- One-phase charging subtracts measured EV current only from
  `Charger1PhaseMapping`. Three-phase charging subtracts the smallest measured
  EV phase current from all physical phases and receives one equal current
  command capped by the smallest headroom. Wattpilot cannot receive different
  current commands per phase.
- Site-current reductions and stops run before allowance grace, battery assist,
  grid fallback, or transition grace. Recovery must remain continuously safe
  for `SiteCurrentRecoverySeconds`; increases then rise by 1 A per normal
  controller cycle.
- A stopped Wattpilot may retain its prior configured `amp` value. Changing
  that inactive setpoint before a start must not be treated as measured EV
  current or clear an already-mature site-recovery timer. The following Start
  command still requires the same fresh headroom and completed recovery delay.
- Auto/Eco start commands remain ordered phase, current, then Force On. If the
  final command boundary rejects any stage, later stages are not sent and the
  controller must not publish Start state, transition power, or a successful
  on/off timestamp.
- `SiteMaxCurrent` has no hidden margin and does not replace the site breaker or
  downstream branch protection. A roughly five-second response cannot
  guarantee interception of short inrush, and stopping the EV cannot correct a
  house-only overload.
- Where an installation has a maintenance bypass, selecting it is not currently
  visible to the controller. Do not infer bypass from a missing GX, stale D-Bus value, MQTT
  disconnect, or Wattpilot transport event. A powered-down GX cannot issue a
  release command, while automatically selecting Manual before the operating
  contract is validated could enable unintended grid charging.
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
- Writable EV-charger positive `/SetCurrent` and Start `/StartStop` commands
  may issue Wattpilot current, phase, or start commands only when command
  authority is validated. Zero current and Stop remain safe reductions in
  confirmed ECO. Missing or Manual/default mode telemetry must fail closed.
  Manual-to-Auto `/Mode` selection is rejected until `fup` and `ful` are both
  observed false; leaving Auto for Manual retains the approved one-time release.
- Auto/Eco mode is PV-surplus driven and must not intentionally use grid power
  when `AllowGridCharging=false`.
- `AllowGridCharging=true` may continue an already-running Auto/Eco charge
  despite import, but must not authorize a new grid-only start. The controller
  does not claim to select battery versus grid as the physical energy source.
- Battery assist may only bridge a short PV dip during an already-running
  charge. Auto/Eco must first reduce the common Wattpilot current to the
  PV-supported value and then to the configured minimum, requiring fresh
  charger-current telemetry before assistance begins. Assistance covers only
  the remaining minimum-current deficit and remains bounded by SOC, duration,
  per-active-phase shortfall, and recovery settings.
- Battery assist and the EV-priority battery-reservation bypass require valid
  finite system SOC plus selected-battery activity within
  `BatterySocFreshSeconds`. Venus OS does not periodically republish unchanged
  SOC, so finite `/Dc/Battery/Power` updates from `com.victronenergy.system`
  provide the liveness heartbeat for its cached SOC. Missing or invalid SOC,
  or a missing, invalid, or stale heartbeat, fails closed for both features
  and does not change Manual charging.
- Battery assist must not start a charge, preserve or create a phase-up
  candidate, increase current, or issue a switch to three phases. Fresh
  assigned allowance must satisfy the normal phase-up timing and threshold
  before the controller can issue that phase command.
- Fresh grid telemetry and fresh allowance data are required for no-grid
  Auto/Eco decisions.
- Protocol charging statuses `8`-`11` and `13`-`14` follow the normal active
  charging branch. They cannot bypass command-authority, stale-grid,
  grid-import, pending-phase, or confirmed-disconnect guards. In Manual mode
  they change reporting only and do not grant es-ESS command authority.
- A fresh distributor allowance below the usable minimum, including a truthful
  atomic `0 W` assignment during an already-running charge, must remain
  truthfully published on `/PvAllowance`. Current reduction is immediate;
  `AllowanceDropGraceSeconds` debounces only phase-down or stop and begins at
  the original deficit. A completed battery-assist window cannot receive a new
  grace period. This allowance-only grace must not delay stale-grid handling or
  the sustained grid-import guard.
- A confirmed physical vehicle disconnect must stop Auto/Eco current and phase
  control even if Wattpilot briefly continues to report a stale active charging
  model status.
- The public runtime-status observer must also publish `Stopped` after that
  debounced confirmed disconnect. It also publishes `/PhaseMode=0` and
  `/PhaseModeLiteral=Unknown`; stale active model status, live-power fields, or
  remembered controller phase state cannot remain visible as a current vehicle
  phase. The observer does not clear the controller-owned phase memory or issue
  a command. Transient raw disconnect samples inside
  `CarDisconnectConfirmSeconds` retain the active runtime and phase state.
- A confirmed physical vehicle disconnect also clears every pending phase-switch
  stability candidate, including its below-threshold grace timestamp. A
  reconnect must build a new complete `MinPhaseSwitchSeconds` interval from
  fresh assigned PV; transient false connection telemetry inside
  `CarDisconnectConfirmSeconds` does not clear the candidate, and the last
  confirmed phase-command cooldown remains unchanged.
- Fresh raw overhead may estimate continuation PV only for an already-running
  charge. It may reduce or maintain the current setpoint and support a safer
  one-phase fallback, but must not start charging, increase current, authorize
  phase-up, or mutate phase state without a matching Wattpilot phase command.
- Assigned Wattpilot allowance remains authoritative for starts, increases,
  and phase-up. Raw overhead never replaces the truthful public allowance.
- `MinPhaseSwitchSeconds` is the single normal stability/cooldown timer for
  both phase directions. A no-grid session may reduce phase or stop before the
  timer expires when bounded battery assist cannot safely bridge the deficit,
  but an assigned allowance below the usable minimum first receives the short
  `AllowanceDropGraceSeconds` debounce described above.
- On the normal current-adjustment path, `SurplusDropGraceSeconds` may preserve
  an active one-to-three candidate through a shorter-than-grace dip below the
  phase-up threshold only while fresh assigned allowance remains above the
  effective three-phase floor. A deeper deficit that enters minimum-current
  fallback resets the candidate. Battery assist and raw overhead cannot preserve
  or authorize phase-up.
- During a sustained three-phase PV deficit, the controller first reduces the
  equal phase current from PV. After fresh telemetry confirms the configured
  minimum, bounded battery assist may hold that phase mode until its window
  expires. Explicit grid fallback follows the same minimum-current-first rule.
  Once the applicable fallback ends, one-phase continuation PV authorizes
  phase-down; otherwise Auto/Eco stops.
- Current limits must respect configured per-phase bounds and the
  Wattpilot-reported effective limit.
- Phase-switch command ordering must keep both the old and requested phase mode
  inside the calculated site-current headroom before any increase.
- Public D-Bus and MQTT runtime-status paths are compatibility contracts.
- Keep read-only diagnostics such as `scripts/es-ess-health-monitor.sh` and
  `scripts/es-ess-daily-report.py` command-free. Monitoring tools may read the
  runtime-status contract, service state, selected config values and logs, but
  must not write Wattpilot, D-Bus, MQTT, service or configuration state. The
  daily report may invoke only allowlisted `svstat` and D-Bus `GetValue`
  snapshots. Historical dates must stop unless APP_DEBUG (or more verbose)
  covers the complete requested window. A current-day partial report may
  analyze available diagnostic records, but must remain incomplete unless it
  proves an anomaly and must report its evidence period and coverage rather
  than infer a successful safety action from silence. Progress output belongs
  on stderr so JSON stdout remains machine-readable. Snapshot commands must be
  time-bounded and may skip remaining paths after repeated timeouts without
  changing the historical findings.
- Session statistics remain observer-only in both Manual and Auto/Eco. They may
  record the first attempted start and whether the existing command sequence
  accepted it, but they must never call a command, alter dispatch selection,
  change a timer, or publish a control path. Structured INFO output is limited
  to transitions/final summary and APP_DEBUG output to one checkpoint per
  connected minute.
- Wattpilot session-counter energy must not combine a decrease/reset or an
  unobserved process gap into an authoritative total. Sampled one-/three-phase
  and L1/L2/L3 energy must remain explicitly estimated, must not extrapolate
  across stale/long-gap/phase-transition input, and must publish coverage and
  reconciliation evidence. Correlation IDs are not vehicle identity.
- Keep `scripts/wattpilot-setting-capture.py` command-free. It may authenticate,
  request complete status, and compare redacted property snapshots only while
  the vehicle is disconnected. It must reject unvalidated firmware, a missing
  vehicle-state baseline, or a connected vehicle, and must never call
  `setValue`, Wattpilot command helpers, pairing methods, or configuration
  writes.
- Raw `lmo` receipt/change timestamps are diagnostic transport facts only.
  They must not be treated as a generic mode-expiry timeout or independently
  widen Wattpilot command authority without hardware evidence and an approved
  controller policy.
- A newly received raw `lmo` transition bypasses the disconnected five-minute
  idle-report throttle and is mapped by the normal controller worker on its
  next five-second cycle. WebSocket callbacks remain command-free and do not
  publish D-Bus or MQTT directly. After the transition is correlated and
  published, unchanged disconnected state returns to the idle cadence.

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
