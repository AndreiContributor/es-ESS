# es-ESS Backlog

This is the implementation backlog for es-ESS. It preserves completed design
and validation decisions while keeping active work easy to find.

## Current App Analysis

es-ESS is a Python service bundle for Victron Venus OS / GX devices. The
`service/run` entry point starts `es-ESS.py`, which loads and migrates
configuration, validates runtime compatibility, initializes enabled services,
connects main/local MQTT, creates the GLib/D-Bus loop, schedules workers,
combines grid-setpoint requests, publishes service messages, and handles
shutdown. `esESSService.py` provides the shared service lifecycle and
registration helpers.

Current integration boundaries:

- Wattpilot control is centered in `FroniusWattpilot.py`; `Wattpilot.py` owns
  WebSocket transport, `WattpilotRuntimeStatus.py` publishes observer status,
  and the decision/state helpers remain pure and command-free.
- `SolarOverheadDistributor.py` allocates PV surplus and battery reservation.
  Other active services integrate MQTT inverters/exporters/temperature,
  Fronius and Shelly HTTP devices, D-Bus, and local/main MQTT.
- Active and dormant service status is authoritative in
  `docs/service-inventory.md`. Wattpilot command ownership and safety
  invariants are authoritative in `docs/wattpilot-architecture.md`.
- Hardware-free regression tests under `tests/` cover Wattpilot policy,
  runtime status, command boundaries, configuration, orchestration, and active
  service safety paths. CI runs Python 3.12 syntax, configuration-contract, and
  unittest checks.

Current validated state:

- Venus OS `v3.75`, Wattpilot firmware `42.5`, and operator-verified
  Solar.wattpilot app `2.1.0` are the approved runtime baseline. The v3.75
  upgrade, idle/no-vehicle, Manual charging, Manual current-change, and Manual
  recovery checks passed on the production Cerbo GX. Supervised Auto/Eco
  PV-surplus live validation remains outstanding until a suitable daylight/PV
  window.
- Auto/Eco PV-only control, no-grid protection, bounded running-session battery
  assist, telemetry freshness, phase switching, reconnect handling, runtime
  status, configuration migration/validation, and graceful shutdown are
  implemented and tested.
- Manual charging remains user-controlled. Direct current/start/stop writes
  fail closed unless Wattpilot telemetry confirms ECO mode; a one-time release
  of stale Auto/Eco limits on entry to Manual is the sole approved exception.
- The remaining Wattpilot live-validation gaps are supervised v3.75 Auto/Eco
  daylight validation and natural winter observation of grid-import and
  stale-grid-telemetry dispatch.
- The 2026-07-12 review confirmed additional crash, device-control, stale-data,
  persistence, configuration, security, and test-coverage work. Items with
  site-specific limits or uncertain Wattpilot protocol meaning retain explicit
  questions and must not be implemented by assumption.

Deployment information still not established:

- What additional live-device, MQTT, D-Bus, or hardware-in-the-loop facilities
  will be available for future work.

Global delivery and safety rules remain in `AGENTS.md`; this backlog does not
override them.

## Review Questions And Assumptions

Assumptions:

- The backlog supports production hardening and PR-sized implementation work.
- Hardware-dependent checks are recorded as manual validation when the required
  device or operating condition is unavailable.
- `config.sample.ini` remains the only maintained checked-in configuration
  example.

Resolved decisions retained for history:

- VRM/D-Bus `/Mode` may intentionally select Auto or Manual. `/SetCurrent` and
  `/StartStop` remain blocked unless Wattpilot telemetry confirms ECO mode.
- Uninstall preserves a dated `config.ini` backup under
  `/data/es-ESS-backups/` before removing the deployed directory.

Resolved runtime decision:

- Preserve exact clean-release support for Venus OS `v3.75` only in this
  checkout. Continue to reject qualified builds and unapproved future releases.
  If firmware rollback boots an older Venus OS release, restore an es-ESS
  checkout whose runtime baseline explicitly supports that firmware before
  starting services.

## Completed

All completed entries below retain their original identity and durable result.
Unless an entry explicitly says otherwise, the work preserved Manual-mode
ownership, Auto/Eco no-grid safety, bounded continuation-only battery assist,
Wattpilot command ownership, public D-Bus/MQTT contracts, configuration
compatibility, and the prohibition on shared 16 A cable/current-limiting logic.

### Completed 2026-07-13 - Structural Configuration Fail-Closed Startup

- Rejected missing, unreadable, and malformed configuration files plus missing
  or non-integer `[Common] ConfigVersion` values with clear status-1 startup
  failures before migration or runtime side effects.
- Aggregated mandatory `[Common]`, `[Mqtt]`, and active `[Services]` bootstrap
  structure and conversion-type diagnostics before MQTT clients, threads,
  D-Bus, or integration services are constructed, while preserving optional
  settings with existing runtime defaults.
- Stopped constructor and main-process exception handlers from returning a
  partially initialized runtime or a successful exit status; fallback logging
  remains available for structural diagnostics.
- Updated the service-inventory startup contract and added hardware-free
  missing-file, malformed-INI, missing-key, malformed-type, aggregation, and
  exception-propagation regressions. All 25 focused configuration tests and all
  268 hardware-free tests passed; tracked application/test Python syntax passed.

### Completed 2026-07-12 - PR Group 1 Runtime Fail-Safe Hardening

- Removed the Shelly 3EM debug-only 300 W subtraction so raw phase and total
  grid power now reach D-Bus and net-metering integration without resetting
  historically persisted counters.
- Fixed MQTT automatic-consumer status handling so matching state is recorded,
  zero allowance can publish the off command, and malformed payload/regex data
  is visible without overwriting the last valid state.
- Submitted D-Bus callbacks as callable/argument pairs and routed both D-Bus
  callback and worker Futures through shared exception reporting without
  blocking the GLib callback thread.
- Preserved recurring GLib timers after scheduling errors while retaining
  one-shot removal and existing worker-overrun skipping.
- Made NoBatToEV treat a missing Wattpilot client as unavailable telemetry and
  revoke its shared setpoint request before logging every unexpected update
  failure.
- Protected shared grid-setpoint requests with a narrow snapshot lock while
  preserving additive values, change-only publication, and the existing
  default fallback; no bounds or clamping were added.
- Added hardware-free raw-meter, MQTT consumer, D-Bus/worker Future,
  NoBatToEV failure, and grid-setpoint concurrency regressions. Python syntax,
  48 focused tests, and all 257 hardware-free tests passed.

### Completed 2026-07-11 - PR 9 Wattpilot Phase Anti-Flapping And Running Grid Fallback

- Made `MinPhaseSwitchSeconds` the continuous-condition timer and minimum
  command interval for both phase directions; configuration v10 removed the
  obsolete `PhaseSwitchDelaySeconds`.
- Added three-phase deficit handling: bounded battery assist or permitted grid
  fallback may hold an already-running charge, while no-grid operation reduces
  early to one phase or stops when the deficit cannot be bridged. Starts and
  phase-up still require fresh assigned PV.
- Fixed stale-high raw overhead so assigned allowance remains authoritative and
  controller phase state cannot change without the matching Wattpilot command.
- Production disconnect validation led to same-cycle publication of cleared
  battery-assist safety state instead of waiting for idle polling.
- Production phase-up validation confirmed the 600-second interval and led to
  short-drop grace above the electrical three-phase floor. Deeper/longer normal
  dips reset timing; an eligible assist may preserve, but never create, an
  existing candidate, and full fresh allowance is still required to switch.
- Added regression coverage for timing, recovery resets, bridging, early
  phase-down/stop, continuation-only grid fallback, stale raw overhead,
  disconnect publication, short dips, and migration.

### Completed 2026-07-11 - PR 8 Wattpilot Dispatch Handler Extraction

- Characterized every control-state return and the stale-grid/disconnect side
  effects, then extracted named controller handlers without changing selector
  ordering or behavior.
- Kept `EXTERNAL_LOW_PRICE` separate so its Auto/no-grid guard remains explicit
  and preserved unavailable/unknown fallback behavior.
- Added isolated handler and all-state delegation tests; verified 94 focused
  Wattpilot tests and all 204 hardware-free tests.

### Completed 2026-07-11 - PR 7 Startup Config Value Validation

- Added aggregate fail-fast startup validation for Wattpilot current/threshold/
  timing/assist bounds and positive worker/device polling intervals, including
  every `ShellyPMInverter:*` section.
- Preserved optional missing settings that use runtime defaults and documented
  ranges in README and `config.sample.ini`, including `6..32 A` and permitted
  zero-valued debounce delays.
- Added invalid-rule, boundary, sample, aggregate-diagnostic, non-numeric,
  optional-section, and startup-invocation tests; all 200 tests passed.

### Completed 2026-07-11 - PR 6 Dormant Service Alignment

- Removed the nonexistent `Grid2Bat` sample flag and aligned README/sample/
  inventory active services while documenting `MqttDC`,
  `ChargeCurrentReducer`, `FroniusSmartmeterRS485`, and `Grid2Bat` as dormant or
  unavailable.
- Preserved ignored legacy flags for compatibility and kept all dormant runtime
  hooks disabled.
- Added a contract across `_checkAndEnable()`, sample flags, and the README
  active-service table plus migration coverage for legacy flags.

### Completed 2026-07-11 - PR 5 Security Hardening

- Replaced `MinBatteryCharge` `eval()` with a constrained AST evaluator for
  numeric literals, `SOC`, `min()`/`max()`, parentheses, and arithmetic; missing
  SOC now warns and uses zero for that cycle.
- Replaced interpolated `os.popen()` time lookup with argv-based
  `subprocess.run()` and validated timezone input.
- Documented the expression grammar and added tests for valid, missing-SOC,
  malicious/invalid, structured-subprocess, and invalid-timezone cases.

### Completed 2026-07-11 - PR 4A Graceful Shutdown Reliability

- Made SIGTERM cleanup idempotent, preserved safety cleanup ordering, flushed
  logs, and used `os._exit(0)` only after cleanup; `service/run` now directly
  execs Python.
- Added a bounded graceful restart with verified-PID/start-time SIGKILL fallback
  and classified expected MQTT shutdown disconnects as synchronous,
  deduplicated INFO messages.
- GX validation across repeated restarts confirmed new supervised PIDs, one
  cleanup, complete service recovery, and no swallowed exit, traceback,
  timeout, SIGKILL fallback, or inert process.
- Production exposed CRLF shebang failure; shell/service files were normalized
  to LF and repository attributes now enforce it. Follow-up validation confirmed
  each shutdown message once before `Cleaned up. Bye.`
- Verified focused shutdown/orchestration tests, all 182 tests, repository
  compilation, shell syntax, and whitespace checks.

### Completed 2026-07-11 - PR 4 MQTT And Orchestration Reliability

- Corrected local reconnect subscriptions to use `localMqttClient`, made service
  publication check the real main-client connection state for method/boolean
  APIs, and removed the duplicate distributor `OnKeywordRegex` subscription.
- Added fake-client initial/reconnect routing, connected-state, compatibility,
  and subscription-count tests without changing topic contracts.

### Completed 2026-07-10 - SolarOverheadDistributor Startup Safety

- Missing grid phases or battery power now publish fail-safe zero overhead,
  zero allowances, and a warning instead of reaching the generic critical path.
- Protected energy-stat iteration with the consumer-dictionary lock.
- Added hardware-free missing-input, normal-calculation, and concurrent-lock
  coverage; syntax, focused, and full tests passed.

### Completed 2026-07-10 - NoBatToEV Startup Safety

- Missing Wattpilot phase power, external EV power, consumption, or PV data now
  revokes the shared grid-setpoint request instead of raising `TypeError`.
- Preserved normal setpoint delta, zero-EV, relay-disabled, and grid-loss
  behavior and added hardware-free coverage for each branch.

### Completed 2026-07-08 - Rebuild Wattpilot Configuration Around `config.sample.ini`

- Added missing charge-complete keys, removed unused `Username`, corrected
  `BatteryMaxChargeInWh`, and documented every active Wattpilot setting.
- Added `tests/test_config_contract.py` so missing active keys and unknown
  sample keys fail automatically; syntax, contract, and full tests passed.

### Completed 2026-07-08 - Make Configuration Upgrades Idempotent And Section-Safe

- Added idempotent migration helpers that preserve user service flags and
  existing `[NoBatToEV]` / `[MqttPvInverter]` values.
- Added migration tests for existing/missing later sections and legacy flags.
  Live v7-to-v8 validation preserved values, added defaults, and avoided the
  duplicate-section crash.

### Completed 2026-07-08 - Document Wattpilot Architecture Boundaries

- Added `docs/wattpilot-architecture.md`, defining transport, controller-command,
  runtime-observer, decision-helper, and safety boundaries.
- Linked it from README/AGENTS and incorporated it into the review workflow;
  this was documentation-only.

### Completed 2026-07-08 - Document App-Wide Service Inventory And Integration Boundaries

- Added `docs/service-inventory.md` covering active/dormant services, D-Bus,
  MQTT, HTTP, distributor consumers, and grid-setpoint ownership.
- Added the inventory to AGENTS and the review workflow; this was
  documentation-only.

### Completed 2026-07-08 - Harden Service Lifecycle Scripts

- Made install strict/idempotent, narrowed restart/kill process matching, and
  tolerated already-stopped services.
- Uninstall now stops gracefully, removes service/startup entries, backs up
  `config.ini`, removes the deployment, and safely rewrites `rc.local`.
- Updated README and verified shell syntax and the full unittest suite.

### Completed 2026-07-09 - Rewrite Wattpilot README And Correct Installation Source

- Corrected installation to `AndreiContributor/es-ESS` and made
  `config.sample.ini` the maintained configuration reference.
- Rewrote Wattpilot guidance for Auto/Eco, Manual ownership, no-grid/freshness,
  phases, timers, battery assist, runtime status, examples, and deployment
  verification without changing behavior.

### Completed 2026-07-09 - Add Wattpilot Decision Characterization Tests Before Refactoring

- Added controller-level tests for allowance freshness, raw-overhead fallback,
  grid-import debounce reset, assist rejection during import, and pending
  one-phase confirmation before refactoring; production behavior was unchanged.

### Completed 2026-07-09 - Add Automated Checks With GitHub Actions

- Added `.github/workflows/ci.yml` for pull requests and `main` pushes using
  Python 3.12, repository syntax, config-contract, and full unittest checks.
- Documented CI in README; no runtime behavior changed.

### Completed 2026-07-09 - Clean Up Wattpilot Startup Deferred State And Logs

- Initialized the early energy counter, corrected the worker-start log, and
  changed expected deferred readiness errors into accurate warnings.
- Added startup hygiene tests and verified focused and full suites without
  changing control or reconnect ownership.

### Completed 2026-07-09 - Publish Wattpilot Transport Outage Status To Victron Dashboard

- Controller-owned outage reporting now publishes `/Connected=0`, truthful
  disconnected status/literal, temporary `Wattpilot not reachable` naming, and
  one outage/recovery service message; recovery restores normal values.
- Runtime observation records close and error events while callbacks remain
  command-free. Intentional hibernate idle remains normal rather than an outage.
- Added outage/recovery, naming, deduplication, no-command, and dashboard-hook
  tests.

### Completed 2026-07-09 - Investigate Venus EVCS Overview Tile Outage Text

- Confirmed upstream `gui-v2` uses fixed `EVCS` title and standard status/mode/
  session paths, not `/CustomName` or `/StatusLiteral`.
- Chose truthful es-ESS values and documented detail-view, D-Bus, MQTT, service,
  and distributor messages as the supported outage route rather than a local UI
  patch or synthetic charger state.

### Completed 2026-07-09 - Replace Wattpilot Recursive Reconnect With A Bounded Connection Loop

- Replaced recursive close-callback reconnect with one daemon worker loop,
  idempotent `connect()`, and clean stop-event-driven `disconnect()`.
- Added fake-WebSocket tests for duplicate prevention, non-recursive close,
  reconnect, and shutdown and updated architecture/inventory/README.
- Repeated live outages confirmed correct dashboard/runtime health transitions,
  recovery, and no duplicate workers or unbounded exceptions.

### Completed 2026-07-09 - Guard Manual Wattpilot Mode From D-Bus/VRM Control Writes

- `/SetCurrent` and `/StartStop` commands now require confirmed ECO telemetry;
  Manual/default or missing telemetry fails closed with an operational message.
- `/Mode` remains the separate intentional Auto/Manual selector.
- Added Manual/missing/ECO/mode-switch tests and documented the boundary.

### Completed 2026-07-09 - Publish Venus EVCS Session Energy And Time Paths

- Added `/Session/Energy` and `/Session/Time` mirrors while preserving legacy
  paths and shared reset/time semantics.
- Added registration, value, reset, and mirroring tests and documented the
  additive D-Bus compatibility contract.

### Completed 2026-07-09 - Document Supported Wattpilot Unavailable Indicator Route

- Selected truthful detail-view, D-Bus, retained MQTT, service-message, and
  distributor-message outage visibility.
- Rejected synthetic status/mode values; custom dashboard or upstream UI work
  remains a separate future product decision.

### Completed 2026-07-09 - Extract Wattpilot Telemetry And Allowance Evaluation Helpers

- Added pure `WattpilotDecisionInputs.py` helpers for finite parsing, grid and
  allowance freshness, minimum allowance, and raw-overhead freshness.
- Kept live state, publication, messages, and commands in the controller; added
  focused cutoff/non-finite tests and updated architecture documentation.

### Completed 2026-07-09 - Extract Wattpilot Grid-Guard And Battery-Assist Decisions

- Added pure `WattpilotSafetyDecisions.py` helpers for grid-import debounce and
  bounded running-session battery-assist eligibility/timeout/recovery.
- Kept timestamps, publication, messages, and commands in the controller and
  added focused helper tests/documentation.

### Completed 2026-07-10 - Extract Wattpilot Phase-Switching Decisions

- Added pure `WattpilotPhaseDecisions.py` helpers for thresholds, desired phase,
  current, distributor requests, and phase timing.
- Kept commands, confirmation, publication, messages, and timers in the
  controller; focused and full tests passed.

### Completed 2026-07-10 - Stop Auto Control After Confirmed Wattpilot Disconnect

- After `CarDisconnectConfirmSeconds`, physical disconnect now overrides stale
  active model status, publishes disconnected state, and stops Auto/Eco current
  and phase control until reconnection.
- Added transient, stale-status, and full-update regression tests and documented
  the invariant.

### Completed 2026-07-10 - Add Wattpilot Control-State Shadow Selector

- Added pure `WattpilotControlState.py` with characterized safety ordering and a
  passive shadow comparison beside the existing branch flow.
- Mismatches logged input snapshots; commands, state, and publication stayed in
  the controller. Selector, policy, syntax, and full tests passed.

### Completed 2026-07-10 - Complete Wattpilot Control State-Machine Dispatch

- Made the selector own branch choice while preserving stale-grid-before-import,
  import-before-pending-switch, and pending-switch-before-model routing.
- Existing side effects moved behind controller handlers; a dispatch-ownership
  regression test proved `_update()` follows the selected state.

### Completed 2026-07-10 - Release Auto/Eco Limits When Entering Manual Mode

- Added a one-time release for explicit or observed Auto/Eco-to-Manual entry:
  clear transition state, restore automatic phase selection, and restore the
  effective maximum current without starting or stopping Manual charging.
- Added once-only/non-repetition tests and documented this approved exception;
  normal Manual current/start/stop rejection remains unchanged.

### Completed 2026-07-10 - Evaluate Fronius Module Packaging

- Confirmed root module/class names are runtime import contracts for the service
  loader, tests, and `/data/es-ESS/es-ESS.py` deployment.
- Chose to retain the flat layout. Any package move requires a standalone
  compatibility refactor with wrappers or loader changes, import tests, and live
  startup validation, separate from Wattpilot behavior.
- Recorded the decision in the service inventory; no code/import changed.

### Completed 2026-07-10 - Investigate EVCS UI Formatting Alignment

- Confirmed es-ESS publishes truthful mirrored numeric session values and that
  upstream overview/list/detail UI components independently format precision,
  units, and time.
- Chose not to publish display strings, alter numeric data, or maintain a local
  UI patch; documented the UI-owned formatting distinction.

### Completed 2026-07-11 - PR 3 Service I/O Safety And Remaining Service Coverage

- Added `[Common] HttpRequestTimeout=5` with v9 migration/docs and applied it to
  distributor HTTP consumers and dormant RS485 polling if re-enabled.
- Prevented zero-target inverter division by publishing explicit `0%` OpenDTU
  throttle for producing controllable inverters.
- Added active-service and timeout/migration tests; focused, compilation, and
  full tests passed. MQTT/orchestration reliability remained separate in PR 4.

## Backlog

### P2 - Define Safe Grid-Setpoint Bounds

Goal:

Prevent unreviewed extreme combined grid setpoints after safe site-independent
or configured limits are established.

Problem:

The shared combiner adds every active request to `DefaultPowerSetPoint` without
minimum or maximum bounds. The repository does not currently establish values
that are safe for every supported ESS site, so implementing an arbitrary clamp
could reject legitimate NoBatToEV operation or permit an unsafe range.

Evidence:

- `es-ESS.py:696-707` publishes the additive result without bounds.
- `config.sample.ini` defines `DefaultPowerSetPoint` but no approved combined
  minimum or maximum.

Implementation:

- Select bounds from an operator-approved production range or a validated
  Victron source available on the supported Venus OS `v3.75` baseline.
- Decide whether the bounds are configured or discovered at runtime.
- Clamp the final combined value and log every clamp without changing request
  ownership, additive delta semantics, or change-only publication.
- Add an idempotent configuration migration and user documentation if new
  settings are introduced.

Files to change:

- `es-ESS.py`
- `config.sample.ini` and `README.md` if configured bounds are approved

Files to add:

- None expected.

Tests:

- Extend `tests/test_grid_setpoint.py` with exact lower/upper boundaries,
  below/above-bound clamps, clamp diagnostics, and unchanged in-range sums
  using hardware-free MQTT stubs.
- Extend configuration migration and contract tests if settings are added.

Expected coverage:

- Proves combined requests cannot exceed explicitly approved bounds while
  legitimate in-range NoBatToEV behavior remains unchanged.
- Existing passing tests remain unchanged.

Manual validation:

Fault simulation in a low-risk NoBatToEV window after bounds are approved.

Manual test steps:

1. Exercise requests near each approved boundary.
2. Confirm in-range values remain unchanged and out-of-range values clamp with
   one clear diagnostic.
3. Confirm revocation restores the configured default setpoint.

Risks and dependencies:

- Incorrect bounds can break legitimate ESS behavior or fail to constrain an
  unsafe request.
- Land the grid-setpoint combiner lock before implementing this item.

Open questions:

- What minimum and maximum AC power setpoints are safe for the production ESS?
- Should the limits be configured or read from a validated Victron source?

Done criteria:

- The bounds and their source are explicitly approved and documented.
- Combined setpoints are clamped and every clamp is observable.
- In-range additive behavior and request ownership remain unchanged.
- Full unittest suite passes.

### P2 - Add Freshness Guard For Battery-Assist SOC

Goal:

Prevent battery assist and battery-priority bypass from relying on stale SOC.

Problem:

Grid phases are receive-time tracked, but the SOC subscription has no callback
or timestamp. A retained high SOC can authorize a bounded assist window after
the real battery has crossed its configured floor.

Evidence:

- `FroniusWattpilot.py:317-320` registers SOC/battery power without callbacks.
- `batterySoc()` at line 2005 returns the cached value directly.
- `shouldIgnoreBatteryReservation()` and `startOrContinueBatteryAssist()` use it.

Implementation:

- Track SOC validity and receive time in the controller.
- Treat missing, invalid, or stale SOC as ineligible for assist and reservation
  bypass.
- Keep helpers pure and preserve Manual ownership, continuation-only assist,
  thresholds, duration, shortfall, recovery, and command boundaries.

Files to change:

- `FroniusWattpilot.py`
- `WattpilotDecisionInputs.py` if a generic freshness helper is appropriate
- `docs/wattpilot-architecture.md`
- `config.sample.ini` and `README.md` only if a new setting is approved.

Files to add:

- None expected.

Tests:

- Extend controller decision tests for fresh, stale, invalid, and missing SOC;
  confirm stale SOC cannot activate assist or reservation bypass.

Expected coverage:

- Proves SOC-dependent safety decisions fail closed while existing fresh-SOC
  behavior remains unchanged.

Manual validation:

Fault simulation during a supervised active charge.

Manual test steps:

1. Interrupt SOC updates during an eligible assist scenario.
2. Confirm assist clears/refuses and Manual charging is untouched.

Risks and dependencies:

- An overly short freshness window may reject normally slow SOC updates.
- Read and update the Wattpilot architecture contract in the implementation.

Open questions:

- Reuse `GridTelemetryFreshSeconds` or introduce a dedicated SOC freshness
  setting based on observed GX update cadence?

Done criteria:

- Missing/stale SOC cannot authorize assist or battery-reservation bypass.
- Full unittest suite passes.

### P2 - Define Safe Control For Unclassified Charging Model Statuses

Goal:

Give Wattpilot model statuses 8-11 and 13-14 an explicit verified controller
policy instead of silently routing them to `UNKNOWN`.

Problem:

The enum names describe charging conditions, but the control-state sets omit
them. The `UNKNOWN` handler performs no PV-following or explicit safety action.
Blindly mapping every status to normal charging is also unsafe without protocol
or live evidence.

Evidence:

- `WattpilotControlState.py:5-6` omits values 8-11 and 13-14.
- `enums.py:63-69` names them AutomaticStop/Fallback charging states.
- `select_control_state()` falls through to `UNKNOWN`.

Implementation:

- Establish each status's observed/protocol meaning for firmware `42.5`.
- Choose explicit PV-following or fail-safe stop behavior per status.
- Keep selection pure and side effects in `FroniusWattpilot.py`; preserve Manual
  ownership and no-grid safety.

Files to change:

- `WattpilotControlState.py`
- `FroniusWattpilot.py` only if a new explicit handler is required
- `docs/wattpilot-architecture.md`

Files to add:

- None expected.

Tests:

- Extend `tests/test_wattpilot_control_state.py` and dispatch tests for all six
  statuses in Auto/no-grid and Manual contexts using hardware-free stubs.

Expected coverage:

- Proves every known charging status has deliberate behavior and cannot bypass
  PV/no-grid policy; existing mappings remain unchanged.

Manual validation:

Active charging only if one of these rare statuses occurs naturally; unit tests
are the primary verifier.

Manual test steps:

1. Capture firmware `42.5` telemetry/log evidence if a listed status occurs.
2. Confirm the selected controller state matches the approved policy.

Risks and dependencies:

- Incorrect classification could stop a valid session or permit unintended
  power use.
- Protocol/observed evidence must precede implementation.

Open questions:

- Which of statuses 8-11 and 13-14 are safe to PV-follow, and which must stop in
  Auto/no-grid mode?

Done criteria:

- All six statuses have evidence-backed, tested control-state mappings.
- Full unittest suite passes.

### P2 - Publish Null And Disconnected On All Meter Failure Modes

Goal:

Prevent failed grid/PV devices from remaining connected with frozen D-Bus
measurements.

Problem:

Fronius JSON, Shelly 3EM, and Shelly PM route only request timeouts through
their failure counters. Connection errors and malformed/partial JSON are logged
without clearing last-known values.

Evidence:

- Generic handlers at `FroniusSmartmeterJSON.py:148`,
  `Shelly3EMGrid.py:199`, and `ShellyPMInverter.py:170` do not invoke their
  disconnected/null paths.

Implementation:

- Route all `RequestException` and structural payload failures through each
  service's existing consecutive-failure policy.
- Validate required payload structure before indexing.
- Preserve thresholds and recovery behavior; update `docs/service-inventory.md`
  if the documented failure contract changes.

Files to change:

- `FroniusSmartmeterJSON.py`
- `Shelly3EMGrid.py`
- `ShellyPMInverter.py`
- `docs/service-inventory.md` if needed

Files to add:

- None expected.

Tests:

- Extend the three existing service test files for connection refusal and
  partial/malformed payloads, retaining hardware-free request/D-Bus stubs.

Expected coverage:

- Proves non-timeout failures eventually publish null and `Connected=0` while
  single transient failures retain the current debounce.

Manual validation:

Fault simulation in a low-risk window.

Manual test steps:

1. Briefly disconnect each configured device network path.
2. Confirm null/disconnected publication after the existing threshold and
   normal recovery after reconnect.

Risks and dependencies:

- Payload validation must not reject legitimate firmware variants without
  evidence.
- No other item must land first.

Open questions:

- None.

Done criteria:

- Connection and parse failures use the established disconnected/null policy.
- Full unittest suite passes.

### P3 - Fix PV Inverter Stale Window And Cached-Power Contribution

Goal:

Detect a silent MQTT PV inverter promptly and exclude its frozen power from
zero-feed-in control.

Problem:

The stale threshold is ten hours, and `setStale()` nulls D-Bus paths without
clearing cached phase power. A silent inverter can therefore influence control
math long after its telemetry is invalid.

Evidence:

- `MqttPVInverter.py:105` uses `10 * 3600` seconds.
- `setStale()` at line 290 leaves `l1power/l2power/l3power` unchanged.
- `total_power` continues summing those fields.

Implementation:

- Select a timeout safely above the configured devices' normal publication
  cadence, fixed or configurable with migration/docs.
- Clear cached phase power when stale and preserve reconnect recovery, topics,
  D-Bus paths, and zero-feed-in ownership.

Files to change:

- `MqttPVInverter.py`
- `config.sample.ini` and `README.md` if configurable

Files to add:

- None expected.

Tests:

- Extend `tests/test_mqtt_pv_inverter.py` for threshold boundaries, stale power
  exclusion, and recovery using hardware-free time/MQTT/D-Bus stubs.

Expected coverage:

- Proves silent inverters become disconnected promptly and contribute zero to
  control math; existing passing tests remain unchanged.

Manual validation:

Fault simulation in a low-risk window.

Manual test steps:

1. Stop one inverter's MQTT publication.
2. Confirm stale state within the approved window and removal from total power.

Risks and dependencies:

- A timeout shorter than normal publication gaps would create false stale
  transitions.
- No other item must land first.

Open questions:

- Use a documented fixed timeout or add a per-service configurable value?

Done criteria:

- Stale detection uses an approved window and stale power contributes zero.
- Full unittest suite passes.

### P3 - Fix Zero-Feed-In Logger Shadowing And None Telemetry

Goal:

Make zero-feed-in calculation None-safe and preserve its real error diagnostic.

Problem:

The calculation sums consumption values without None guards. Local variable
`c` shadows the imported critical logger, so the exception handler can raise a
second error and hide the original failure.

Evidence:

- `MqttPVInverter.py:113` sums three values without checking them.
- Lines 133-146 assign `c` and later try to call it as the logger.

Implementation:

- Rename local calculation variables.
- Skip/release the control cycle safely when required consumption telemetry is
  missing; preserve the experimental algorithm and topic contract otherwise.

Files to change:

- `MqttPVInverter.py`

Files to add:

- None expected.

Tests:

- Extend `tests/test_mqtt_pv_inverter.py` for each missing consumption phase and
  a raised calculation error, using hardware-free stubs.

Expected coverage:

- Proves telemetry gaps do not raise and the original exception is logged;
  existing passing tests remain unchanged.

Manual validation:

Fault simulation in a low-risk zero-feed-in window.

Manual test steps:

1. Briefly remove one consumption path.
2. Confirm no `TypeError` or logger-shadow error and normal recovery.

Risks and dependencies:

- Preserve the explicit zero-target `0%` behavior completed in PR 3.
- No other item must land first.

Open questions:

- None.

Done criteria:

- Missing consumption skips safely and exception logging remains callable.
- Full unittest suite passes.

### P3 - Make Shelly Net-Energy Persistence Robust And Atomic

Goal:

Survive corrupt counter files, avoid partial writes, and prevent outage gaps
from becoming false energy.

Problem:

Counter reads parse untrusted file content without recovery, writes truncate
files in place, and net integration applies the latest power across the full
time since the last successful poll.

Evidence:

- `Shelly3EMGrid.py:41-49` performs unguarded `float()` reads.
- Lines 218-222 write non-atomically.
- Lines 164-173 integrate the complete successful-poll gap.

Implementation:

- Recover invalid/missing counters to zero with a clear warning.
- Write a sibling temporary file, flush/fsync as supported, and `os.replace()`.
- Reset measurement time on failed attempts or cap the integrated duration to
  a documented poll-derived maximum.

Files to change:

- `Shelly3EMGrid.py`

Files to add:

- None expected.

Tests:

- Extend `tests/test_shelly3em_grid.py` for empty/garbage files, atomic replace,
  interrupted persistence, and long poll gaps using temporary directories.

Expected coverage:

- Proves startup survives corrupt state and persistence/integration cannot
  inject a large artificial counter jump; existing passing tests remain.

Manual validation:

Log-only on staging.

Manual test steps:

1. Supply a truncated counter file and restart.
2. Confirm warning, successful service registration, and valid later writes.

Risks and dependencies:

- Preserve counter units, paths, and existing valid values.
- No other item must land first.

Open questions:

- Prefer resetting the timestamp on every poll attempt or a documented maximum
  integration duration derived from `PollFrequencyMs`?

Done criteria:

- Corrupt files recover safely, writes are atomic, and outage gaps are bounded.
- Full unittest suite passes.

### P3 - Guard TimeToGoCalculator Against Missing Telemetry

Goal:

Avoid repeated critical failures and stale operator output during normal
battery-telemetry gaps.

Problem:

The calculator handles SOC zero but not missing power, SOC, or active SOC
limit. Arithmetic raises every update and the broad handler logs critical.

Evidence:

- `TimeToGoCalculator.py:35-56` uses the three values without complete None
  guards; the handler is at line 68.

Implementation:

- Return early on missing required telemetry with a deduplicated warning or
  debug diagnostic.
- Preserve valid charge/discharge calculations and MQTT paths.

Files to change:

- `TimeToGoCalculator.py`

Files to add:

- `tests/test_time_to_go_calculator.py`

Tests:

- Cover each missing input and representative charge/discharge calculations
  with hardware-free D-Bus/MQTT stubs.

Expected coverage:

- Proves normal gaps are non-critical and valid data resumes publication;
  existing passing tests remain unchanged.

Manual validation:

Fault simulation in a low-risk window.

Manual test steps:

1. Briefly interrupt a battery subscription.
2. Confirm no critical spam and publication resumes afterward.

Risks and dependencies:

- Low; do not change formula semantics.
- No other item must land first.

Open questions:

- None.

Done criteria:

- Missing telemetry is handled without exceptions and valid data recovers.
- Full unittest suite passes.

### P3 - Restrict Config And Backup File Permissions

Goal:

Prevent MQTT and Wattpilot credentials from being world-readable on the GX.

Problem:

Install, migration, versioned backup, and uninstall backup paths rely on the
process umask. Files containing passwords can therefore be created as `0644`,
and the external backup directory is not explicitly restricted.

Evidence:

- `install.sh` copies `config.sample.ini` without `chmod`.
- `es-ESS.py:489-500` writes config and backups without applying mode `0600`.
- `uninstall.sh:26-27` creates/copies backups without explicit restrictive modes.

Implementation:

- Apply `0600` to config and every backup after creation/update.
- Create the uninstall backup directory as `0700` and reassert its mode.
- Preserve ownership and existing install/migration/uninstall behavior.

Files to change:

- `install.sh`
- `uninstall.sh`
- `es-ESS.py`
- `README.md`

Files to add:

- None expected.

Tests:

- Extend config-write tests to assert `os.chmod(..., 0o600)`; validate script
  structure without real GX paths.

Expected coverage:

- Proves Python-created secret files receive restrictive modes; existing
  passing tests remain unchanged.

Manual validation:

Log-only/shell inspection on staging.

Manual test steps:

1. Install and perform a migration; check `config.ini*` are `0600`.
2. Verify `/data/es-ESS-backups` is `0700` and backups are `0600`.

Risks and dependencies:

- Confirm root/service ownership still permits runtime access.
- No other item must land first.

Open questions:

- None.

Done criteria:

- Configs/backups are `0600` and the external backup directory is `0700`.
- Full unittest suite passes.

### P3 - Make MQTT TLS Certificate Verification The Default

Goal:

Provide certificate and hostname verification whenever MQTT TLS is enabled.

Problem:

Both MQTT clients currently use `CERT_NONE` and `tls_insecure_set(True)`.
Encryption therefore does not authenticate the broker and cannot prevent a
man-in-the-middle from receiving credentials.

Evidence:

- `es-ESS.py:122-123` configures insecure main MQTT TLS.
- Lines 149-150 do the same for local MQTT.

Implementation:

- Use verified TLS by default for enabled TLS connections.
- Add an explicit, documented compatibility opt-in only if existing self-signed
  deployments require it, with idempotent migration.
- Select system trust or a CA path before implementation; never silently fall
  back to insecure mode.

Files to change:

- `es-ESS.py`
- `config.sample.ini`
- `README.md`

Files to add:

- None expected.

Tests:

- Extend MQTT orchestration, config migration, and config contract tests for
  verified default and explicit insecure compatibility behavior.

Expected coverage:

- Proves TLS verification cannot be disabled accidentally and legacy migration
  is deterministic; existing passing tests remain unchanged.

Manual validation:

Fault simulation against test brokers.

Manual test steps:

1. Connect with a trusted certificate and confirm success.
2. Confirm an untrusted certificate fails unless explicit compatibility mode
   was deliberately configured.

Risks and dependencies:

- Default verification can break self-signed installations; migration and
  operator guidance must land together.
- No other backlog item must land first.

Open questions:

- Rely on the Venus OS trust store, add a CA-file setting, or support both?
- Should an existing `SslEnabled=true` config migrate to explicit insecure
  compatibility once, or fail until the operator supplies trust configuration?

Done criteria:

- Verified TLS is the default and any insecure mode is explicit/documented.
- Full unittest suite passes.

### P3 - Validate Remaining Safety And Operational Values

Goal:

Reject remaining unsafe or nonsensical configured values before side effects.

Problem:

PR 7 already validates current bounds, hysteresis, assist duration/SOC, and
positive service/device intervals. It does not yet validate several grid guard,
freshness, assist, startup ratio, zero-feed-in, and `[Common]` operational
values. The old review claim that update intervals are wholly unvalidated is
obsolete and must not reopen completed work.

Evidence:

- `es-ESS.py:254-386` lacks rules for `GridImportStopW`,
  `GridImportStopSeconds`, `GridTelemetryFreshSeconds`,
  `AllowanceFreshSeconds`, `RawOverheadFreshSeconds`,
  `BatteryAssistMaxShortfallW`, `BatteryAssistRecoverySeconds`,
  `StartupTelemetryRatio`, `ZeroFeedin*`, `NumberOfThreads`, and
  `HttpRequestTimeout`.
- The same method already validates service update and polling intervals.

Implementation:

- Define evidence-based lower/cross-field bounds; add upper bounds only where
  product behavior or hardware limits establish them.
- Extend aggregate fail-fast validation without changing existing defaults.
- Update README/sample ranges and migration only when needed.

Files to change:

- `es-ESS.py`
- `config.sample.ini`
- `README.md`

Files to add:

- None expected.

Tests:

- Extend `tests/test_config_migration.py` and `tests/test_config_contract.py`
  for every new rule, valid boundaries, aggregate diagnostics, and unchanged
  optional/default behavior.

Expected coverage:

- Proves remaining unsafe values fail before startup while PR 7 validation and
  compatible configurations remain intact.

Manual validation:

Hardware not needed; optional log-only invalid-config check.

Manual test steps:

1. Supply one invalid remaining value on staging.
2. Confirm aggregate critical diagnostics and exit before service startup.

Risks and dependencies:

- Arbitrary maximums could reject valid sites; document the basis for each
  bound.
- Structural configuration validation should land first or in a separate PR.

Open questions:

- Approve exact bounds after reviewing controller semantics and documented
  units; do not infer site limits.

Done criteria:

- Every approved remaining rule is documented, migrated if necessary, and
  enforced before side effects.
- Full unittest suite passes.

### P3 - Add Hardware-Free Tests For Untested Active Services

Goal:

Add dedicated regression coverage for every currently untested active service.

Problem:

`TimeToGoCalculator`, `MqttExporter`, and `MqttTemperature` have no dedicated
test files. Their calculation, interval publication, parsing, and D-Bus output
can regress without focused CI failures.

Evidence:

- `tests/` has no `test_time_to_go_calculator.py`,
  `test_mqtt_exporter.py`, or `test_mqtt_temperature.py`.
- All three are active services in `docs/service-inventory.md`.

Implementation:

- Add tests using `types.ModuleType`, `Mock`, and isolated imports; no real
  hardware, broker, network, or D-Bus.
- Reuse the TimeToGo test created by its None-guard fix rather than duplicate it.

Files to change:

- None expected.

Files to add:

- `tests/test_time_to_go_calculator.py`
- `tests/test_mqtt_exporter.py`
- `tests/test_mqtt_temperature.py`

Tests:

- Cover TimeToGo valid/missing inputs, exporter change and 1/10/60-second
  publication, and temperature/humidity/pressure topic-to-D-Bus mapping.

Expected coverage:

- `python -m unittest discover -s tests` automatically discovers all files and
  proves the three active service contracts; existing tests remain unchanged.

Manual validation:

Hardware not needed.

Manual test steps:

1. Run unittest discovery and confirm all three files execute.

Risks and dependencies:

- Land after related behavior fixes so tests encode the corrected contracts.

Open questions:

- None.

Done criteria:

- Each active service has focused, passing hardware-free tests.
- Full unittest suite passes.

### P4 - Harden Wattpilot Reconnect And Startup None Handling

Goal:

Close the confirmed reconnect race and make startup phase detection safe before
power telemetry arrives.

Problem:

`connect()` returns when an old worker remains briefly alive even if
`disconnect()` has set its stop event, so no replacement worker is started.
Startup also compares `None > 0` when a connected car is known before phase
power arrives. The prior review's proposed disconnect stop command is excluded:
it is unproven and an unconditional command could violate Manual ownership.

Evidence:

- `Wattpilot.py:381-388` returns before clearing a set stop event.
- `FroniusWattpilot.py:440-443` compares phase power without None guards.

Implementation:

- Serialize stop/start handoff and replace or join a stopping worker with a
  bounded wait; retain one-worker reconnect ownership.
- Add explicit None guards to startup phase detection.
- Do not add any stop/current/phase command on disconnect in this item.

Files to change:

- `Wattpilot.py`
- `FroniusWattpilot.py`
- `docs/wattpilot-architecture.md` if lifecycle wording changes

Files to add:

- None expected.

Tests:

- Extend `tests/test_wattpilot_client.py` for disconnect/connect handoff and
  single-worker ownership; extend `tests/test_wattpilot_startup.py` for a
  connected car with missing phase power.

Expected coverage:

- Proves intended reconnect always has a worker and startup is None-safe without
  changing charger commands; existing passing tests remain unchanged.

Manual validation:

Fault simulation in a low-risk window; active charging is not required.

Manual test steps:

1. Rapidly interrupt and restore Wattpilot networking.
2. Confirm one reconnect worker, status recovery, and no unintended commands.

Risks and dependencies:

- Worker joining must be short/bounded and must not deadlock callbacks.
- Preserve Manual command-free behavior and the architecture boundary.

Open questions:

- None for the confirmed scope. Any armed-resume claim requires separate live
  evidence and a separately approved Auto/Eco-only design.

Done criteria:

- Reconnect handoff is deterministic and startup accepts missing phase power.
- No new disconnect command is introduced.
- Full unittest suite passes.

### P4 - Remove Distributor Lock-Held I/O And Correct Runtime Data

Goal:

Prevent slow consumer I/O from blocking allocation and fix confirmed consumer
state/publication defects.

Problem:

HTTP status/control can run while `_knownSolarOverheadConsumersLock` is held,
blocking all consumers. Consumer lookup is partly unlocked, `energyToday`
publishes `energyTotal`, and `dbusReportConsumption()` compares request before
checking for None.

Evidence:

- `_validateNpcConsumerStates()` holds the lock while calling HTTP control.
- `SolarOverheadDistributor.py:280-289` checks/reads the dictionary outside one
  consistent lock scope.
- Line 840 evaluates `request > 0` before the None guard.
- Line 1000 publishes `energyTotal` on the `energyToday` topic.

Implementation:

- Snapshot required consumer work under the lock and perform bounded I/O after
  release; keep state updates synchronized.
- Make lookup atomic, correct the None-guard order, and publish `energyToday`.
- Preserve request namespace, timeout behavior, and allocation policy.

Files to change:

- `SolarOverheadDistributor.py`

Files to add:

- None expected.

Tests:

- Extend `tests/test_solar_overhead_distributor.py` to prove I/O runs outside
  the lock, lookup is safe, None request does not raise, and energy topics carry
  the matching values.

Expected coverage:

- Proves one slow endpoint cannot freeze allocation and runtime data is
  truthful; existing passing tests remain unchanged.

Manual validation:

Fault simulation in a low-risk window.

Manual test steps:

1. Point one HTTP consumer at an unreachable endpoint.
2. Confirm other allowances continue on their normal cadence.

Risks and dependencies:

- Moving I/O can create state races unless the snapshot and result application
  boundaries are explicit.
- No other item must land first.

Open questions:

- None.

Done criteria:

- Consumer I/O is outside the shared dictionary lock and listed data defects
  are corrected.
- Full unittest suite passes.

### P4 - Fix Automatic NPC Minimum-To-Request Allocation

Goal:

Allow automatic HTTP/MQTT consumers with `0 < Minimum < Request` to reach their
turn-on request without consuming an unusable partial allowance indefinitely.

Problem:

Automatic NPC parsing forces `StepSize=Request`. Distribution first grants
`Minimum`, then rejects the next full-request step because it would exceed the
request. The allowance remains below the control activation threshold.

Evidence:

- `SolarOverheadDistributor.py:244-267` publishes `StepSize=Request` for HTTP
  and MQTT consumers.
- Lines 589-606 grant Minimum first and require `assigned + increment <= request`.
- HTTP/MQTT control turns on only when allowance reaches request.

Implementation:

- For automatic NPC consumers, cap the next increment to the remaining request
  or treat the eligible start grant atomically, without changing scripted
  consumer priority shifting.
- Characterize current allocation ordering before selecting the smaller fix.

Files to change:

- `SolarOverheadDistributor.py`
- `README.md` if user-visible allocation behavior is clarified

Files to add:

- None expected.

Tests:

- Extend distributor tests for `Minimum < Request`, insufficient overhead,
  exact remaining grant, competing priorities, turn-on, and later turn-off.

Expected coverage:

- Proves an NPC never reserves unusable partial power and scripted allocation
  remains unchanged.

Manual validation:

Fault simulation with a non-critical automatic consumer.

Manual test steps:

1. Configure `0 < Minimum < Request` with sufficient overhead.
2. Confirm allowance reaches request and the consumer turns on once.

Risks and dependencies:

- Allocation changes can affect priority fairness; scope strictly to automatic
  NPC consumers.
- Land separately from lock/I/O restructuring.

Open questions:

- Prefer a capped remaining increment or a single atomic start grant after
  reviewing expected Minimum semantics?

Done criteria:

- Eligible NPC consumers reach request without over-allocation or starvation.
- Full unittest suite passes.

### P4 - Make Shutdown Setpoint Restore And Early Logging Reliable

Goal:

Ensure graceful shutdown transmits the default grid setpoint and early warning/
error logging works before the global runtime is assigned.

Problem:

The shutdown restore is subject to MQTT throttling and the process disconnects
and calls `os._exit()` without proving delivery. `Helper.w()` and `Helper.e()`
also dereference `Globals.esESS` unconditionally during early construction.

Evidence:

- `es-ESS.py:876` publishes the restore without `forceSend=True`; cleanup exits
  at line 913.
- `Helper.py:47-65` lacks the guard used by `Helper.c()`.

Implementation:

- Force-send the restore and retain its publish result so QoS completion can be
  awaited for a short bounded interval before disconnect/exit.
- Guard service-message publication in `w()`/`e()` while always logging locally.
- Preserve the completed graceful-shutdown ordering and idempotency.

Files to change:

- `es-ESS.py`
- `Helper.py`

Files to add:

- None expected.

Tests:

- Extend orchestration/shutdown and globals tests for forced restore, bounded
  completion handling, and warning/error logging with `Globals.esESS=None`.

Expected coverage:

- Proves the restore bypasses throttling and early diagnostics cannot mask the
  original construction error; existing passing tests remain unchanged.

Manual validation:

Fault simulation in a low-risk restart window.

Manual test steps:

1. Gracefully stop es-ESS while a non-default request is active.
2. Confirm the Victron setting returns to the configured default before exit.

Risks and dependencies:

- The delivery wait must be short and bounded so service supervision cannot
  hang.
- Preserve PR 4A cleanup semantics.

Open questions:

- None.

Done criteria:

- Shutdown restore is force-sent with bounded completion handling and early
  warning/error helpers are None-safe.
- Full unittest suite passes.

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

Evidence:

- Hardware-free selector and dispatch tests cover stale telemetry and sustained
  import ordering, but natural production conditions have not exercised every
  branch on the supported v3.75 GX/Wattpilot baseline.
- Completed production notes record Manual, normal Auto/Eco, assist,
  disconnect/reconnect, and phase-transition validation while retaining this
  winter observation gap.

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

Files to add:

- None expected.

Tests:

- Existing unit tests already cover stale grid telemetry and grid-import guard
  ordering.
- No new automated tests are required unless the winter run reveals unexpected
  behavior or unclear diagnostic output.

Expected coverage:

- Adds live evidence for natural conditions that hardware-free tests cannot
  reproduce; existing passing tests remain unchanged.

Manual validation:

Active charging required only during a naturally suitable, attended low-PV
window. Do not manufacture grid import or a telemetry outage.

Manual test steps:

1. Run normal winter Auto/Eco charging with `AllowGridCharging=false`.
2. Search the live log for relevant guard messages:
   `grep -Ei "Grid import guard|Grid telemetry is missing" /data/log/es-ESS/current.log`
3. If grid import occurs, capture the relevant log window around the guard
   decision.
4. Confirm the observed decision matches the documented no-grid policy.
5. Record the result in this backlog item.

Risks and dependencies:

- Weather and household load may not naturally expose the branch.
- Complete relevant confirmed telemetry/controller fixes before treating a new
  observation as final validation evidence.

Open questions:

- None. Record an inconclusive natural window rather than forcing the state.

Done criteria:

- Winter or naturally low-PV validation records correct behavior for any
  observed grid-import or stale-telemetry branch.
- If those branches still do not occur naturally, the item records that result
  without forcing unsafe or unrealistic system behavior.
- Full unittest suite passes if any code changes result from an observed defect.

### P4 - Audit And Pin The Victron `velib_python` Dependency

Goal:

Make the Victron D-Bus dependency reproducible and auditable while preserving
the behavior supported on Venus OS `v3.75`.

Problem:

The repository contains `velib_python-master` as ordinary copied source files,
but does not record the upstream Victron commit or snapshot date. The main
entry point prepends the bundled path, while individual service modules also
prepend the Venus OS copy under
`/opt/victronenergy/dbus-systemcalc-py/ext/velib_python`. Python module caching
normally makes the main entry point's first import authoritative, but the mixed
paths make standalone imports and future maintenance ambiguous. The bundled
files also differ from current upstream sources, so replacing them blindly
could change D-Bus service registration or monitoring behavior.

Evidence:

- `es-ESS.py:28-30` loads `vedbus` and `dbusmonitor` from
  `/data/es-ESS/velib_python-master`.
- `FroniusWattpilot.py:13-14`, `FroniusSmartmeterJSON.py:14-15`,
  `Helper.py:10-11`, `MqttPVInverter.py:14-15`, `MqttTemperature.py:13-14`,
  `Shelly3EMGrid.py:15-16`, `ShellyPMInverter.py:14-15`, and
  `SolarOverheadDistributor.py:17-18` prepend the Venus OS system copy before
  importing `VeDbusService`.
- `velib_python-master` is tracked as normal files rather than a Git submodule
  and contains no upstream commit manifest.
- `RuntimeCompatibility.py` permits only the clean Venus OS `v3.75` release,
  so dependency selection must be evaluated against that supported runtime
  rather than current upstream `master` alone.

Implementation:

- Identify the exact Victron upstream revision represented by the bundled
  files, or record that it cannot be recovered.
- Compare the bundled `vedbus.py`, `dbusmonitor.py`, `settingsdevice.py`, and
  `ve_utils.py` with both current upstream and the copies shipped by Venus OS
  `v3.75`.
- Choose one explicit runtime source: a pinned bundled snapshot or the
  validated Venus OS copy. Do not track an unpinned branch such as `master`.
- Record the chosen source, commit/hash, license, update procedure, and Venus OS
  compatibility baseline in the repository.
- Normalize import paths only after the chosen source passes hardware-free and
  GX validation. Preserve all existing D-Bus path names, write callbacks,
  service registration order, Manual-mode command boundaries, Auto/Eco safety
  behavior, MQTT contracts, and configuration defaults.
- Treat any actual dependency replacement as a separate compatibility change;
  do not combine it with Wattpilot control or phase-policy work.

Files to change:

- `BACKLOG.md`
- `es-ESS.py` and service modules that currently select a `velib_python` path,
  if import-source normalization is approved
- `velib_python-master/*`, only if a different pinned snapshot is validated
- `docs/service-inventory.md`
- `README.md`

Files to add:

- An upstream provenance/version manifest beside the bundled dependency
- `tests/test_velib_dependency_contract.py`

Tests:

- Add a hardware-free dependency-contract test that verifies the selected
  source and recorded revision/hash cannot drift silently.
- Test that the orchestrator and representative services resolve the same
  `vedbus` module under the supported deployment layout.
- Exercise representative `VeDbusService` registration, path publication,
  writable callbacks, and `DbusMonitor` subscription setup with stubbed D-Bus
  dependencies following the existing hardware-free test pattern.
- Run existing Wattpilot runtime-status, command-boundary, session-path, service
  orchestration, and active-service tests unchanged.

Expected coverage:

- Proves dependency provenance and import-source selection are deterministic.
- Proves the D-Bus integration surface used by es-ESS remains compatible
  without requiring real hardware in CI.
- Existing passing tests remain unchanged.

Manual validation:

Log-only (safe in production). Validate on supported Venus OS `v3.75` with no
active charging or other controlled transition required.

Manual test steps:

1. Deploy the pinned dependency/import change to a staging path or during a
   normal low-risk restart window.
2. Restart es-ESS and confirm startup completes without import, D-Bus, or
   registration errors.
3. Inspect D-Bus and confirm enabled services and their existing paths register
   once with unchanged values and writable behavior.
4. Confirm main/local MQTT connections and normal worker heartbeats recover.
5. Confirm Wattpilot status reporting recovers without issuing a start, stop,
   current, or phase command while Manual mode or no active charge is present.

Risks and dependencies:

- A newer upstream snapshot may depend on Venus OS components or D-Bus behavior
  not present in the supported release.
- Selecting the system copy couples es-ESS behavior to Venus OS packaging;
  selecting a bundled copy requires explicit license/provenance maintenance.
- Import-order changes can affect every D-Bus-publishing service and therefore
  require GX validation even when hardware-free tests pass.
- No other backlog item must land first.

Open questions:

- Should es-ESS retain a pinned bundled snapshot for reproducibility, or use
  the exact system copy supplied by the validated Venus OS release?

Done criteria:

- The selected `velib_python` source and exact revision/hash are documented.
- All runtime imports resolve deterministically to that source.
- No unpinned download from `master` is used in deployment or maintenance.
- D-Bus service registration and monitoring pass hardware-free regression
  tests and log-only GX validation on Venus OS `v3.75`.
- Wattpilot Manual/Auto safety boundaries and public D-Bus/MQTT contracts are
  unchanged.
- Full unittest suite passes.

### P1 - Live-Validate Venus OS v3.75 Auto/Eco PV-Surplus Operation

Goal:

Complete the remaining live validation for v3.75 by proving supervised
Auto/Eco PV-surplus behavior under natural daylight/PV conditions.

Problem:

The production Cerbo GX has already validated the v3.75 upgrade path,
configuration persistence, service startup, dependency recovery, idle/no-vehicle
operation, Manual charging, Manual current changes, and Manual recovery. The
remaining external behavior that CI and the night-time validation cannot prove
is live Auto/Eco PV-surplus charging, no-grid protection, and phase-switching
under naturally sufficient PV.

Evidence:

- `RuntimeCompatibility.py` accepts only clean `v3.75`.
- v3.75 build `20260624163305` booted successfully on the Cerbo GX.
- `/data/es-ESS/config.ini` survived unchanged, `/data/rc.local` restored the
  service link, `python3-pip` and `websocket-client` were restored after the
  firmware update, and es-ESS ran stably.
- Manual-mode validation confirmed that es-ESS reports Manual charging but does
  not issue start, stop, current, phase, or other Wattpilot control commands.

Implementation:

- Do not make charger-policy changes as part of this validation.
- Perform the test only during an attended daylight/PV window with a vehicle
  connected and enough surplus for the intended check.
- Confirm one-phase Auto/Eco start, no-grid behavior when grid charging is
  disabled, configured current limits, and phase switching only when natural PV
  satisfies the configured thresholds and timers.
- If behavior differs from the documented safety contract, stop the test,
  collect logs, and diagnose before changing application behavior.

Files to change:

- `BACKLOG.md` after validation, to move this item to Completed with the date
  and observed GX results.
- Compatibility code, tests, or documentation only if live evidence identifies
  a concrete defect.

Files to add:

- None expected.

Tests:

- Run `python -m unittest discover -s tests` before any code change.
- Preserve the hardware-free stub pattern and all existing passing tests.

Expected coverage:

- Live validation proves the Auto/Eco GX, Wattpilot, D-Bus, MQTT, and grid
  telemetry surfaces that CI cannot emulate.

Manual validation:

Active charging is required. Do not force unsafe grid import, do not force a
phase transition without natural PV surplus, and keep the test attended.

Manual test steps:

1. Confirm v3.75 is running, dependencies import, es-ESS is up, and the latest
   log has no critical errors.
2. Confirm the vehicle and Wattpilot are ready, grid telemetry is fresh on all
   phases, and the actual managed battery remains selected.
3. Enable Auto/Eco under supervision and validate one-phase start only when
   configured PV surplus is available.
4. Confirm current remains inside configured limits and no-grid behavior holds
   when grid charging is disabled.
5. Validate phase switching only if natural PV remains above the configured
   threshold for the configured timing guard.
6. Stop or return to Manual if unexpected grid use, stale telemetry, or
   unbounded battery discharge appears.

Risks and dependencies:

- Active charging checks require a vehicle, sufficient natural PV, fresh grid
  telemetry, and an attended low-risk window.
- Weather may prevent phase-switch validation; record that result rather than
  forcing unsafe conditions.

Open questions:

- Which natural PV window will be used for the supervised phase-switch check?

Done criteria:

- One-phase Auto/Eco, no-grid protection, current bounds, and any naturally
  available phase-switch behavior are validated on v3.75.
- Manual mode remains command-free throughout the validation window.
- The observed build and validation date are recorded in Completed.
- Full unittest suite passes for any code change made from the results.

## Suggested Implementation Order / PR Execution Queue

Use this queue as the implementation order. Entries carrying the same PR-group
label form one PR-sized batch; unlabelled entries remain separate PRs. Do not
pull later items into the active PR. When the user says `fix next PR items`,
select the first PR group or unlabelled entry containing unfinished backlog
items, present the required implementation plan, risks, and verification, and
then follow the repository working agreement for approval and implementation.
After delivery, move every finished item in that group to `Completed` and
advance the queue on the next request.

8. P2 add freshness guard for battery-assist SOC — fail closed when the SOC
   used by assist or battery-priority bypass is stale.
9. P2 define safe control for unclassified charging model statuses — obtain
   firmware evidence and encode explicit no-grid-safe mappings.
10. P2 publish null and disconnected on all meter failure modes — stop frozen
    grid/PV measurements remaining authoritative after non-timeout failures.
11. P4 harden Wattpilot reconnect and startup None handling — close confirmed
    lifecycle/None defects without adding a disconnect command.
12. P1 live-validate Venus OS v3.75 Auto/Eco PV-surplus operation — run the
    daylight active-charging checks only after relevant telemetry/controller
    fixes above are deployed and their automated tests pass.
13. P3 fix zero-feed-in logger shadowing and None telemetry — preserve real
    diagnostics and avoid experimental-control crashes.
14. P3 fix PV inverter stale window and cached-power contribution — remove
    frozen inverter power from zero-feed-in control.
15. P3 make Shelly net-energy persistence robust and atomic — survive corrupt
    files and avoid false energy across failed-poll gaps.
16. P3 guard TimeToGoCalculator against missing telemetry — remove repeated
    critical failures and add the first focused test coverage.
17. P3 restrict config and backup file permissions — protect stored MQTT and
    Wattpilot credentials.
18. P3 make MQTT TLS certificate verification the default — select and migrate
    an explicit trust model before changing existing deployments.
19. P3 validate remaining safety and operational values — extend PR 7 without
    reopening interval/value rules already completed.
20. P3 add hardware-free tests for untested active services — cover TimeToGo,
    MqttExporter, and MqttTemperature after related fixes.
21. P4 remove distributor lock-held I/O and correct runtime data — prevent one
    slow endpoint blocking every consumer and correct confirmed publications.
22. P4 fix automatic NPC minimum-to-request allocation — correct the isolated
    allocation edge without changing scripted-consumer priority behavior.
23. P4 make shutdown setpoint restore and early logging reliable — preserve PR
    4A cleanup while proving restore delivery and construction-safe logging.
24. P4 audit and pin the Victron `velib_python` dependency — establish v3.75
   provenance and deterministic import ownership as a separate compatibility
   change.
25. P2 define safe grid-setpoint bounds — after the combiner lock lands, obtain
   approved site-safe limits or a validated Victron source before adding any
   clamp.

The P4 winter grid-import dispatch validation is an observation task, not a
code PR, and remains open independently of this queue. Complete it only under
natural suitable low-PV conditions; do not force production grid import or
disconnect critical telemetry to satisfy it.

Hardware validation scope for the remaining backlog:

- Meter, MQTT, and HTTP failure-path items require controlled low-risk fault
  simulation; they do not require forced grid import.
- Wattpilot SOC/status behavior changes require focused hardware-free tests and
  only supervised active-charging validation where the relevant state can occur
  naturally.
- The P1 Venus OS Auto/Eco validation requires supervised daylight active
  charging for final PV-surplus verification.
- The P4 `velib_python` audit requires log-only startup and D-Bus registration
  validation on the supported Venus OS release; active charging is not
  required.
- The P4 winter validation requires an active Auto/Eco charging session to
  observe real grid-import phase-down or stop behavior.

## Verification Plan

For backlog-only changes:

- Confirm every open and completed item identity remains present, resolved
  decisions remain recorded, active-item templates and queue content are
  preserved, and no file besides `BACKLOG.md` changes.

For implementation PRs:

- Syntax-check changed Python files and run focused tests appropriate to the
  change, followed by `python -m unittest discover -s tests`.
- Run config migration/contract tests when configuration logic, sample keys, or
  README configuration contracts change; run shell syntax checks for lifecycle
  scripts.
- Record any GX/Venus OS, MQTT, D-Bus, Wattpilot, or natural-condition checks
  that remain manual.

## Outstanding Manual Validation

- **Active charging required:** complete supervised v3.75 Auto/Eco PV-surplus,
  no-grid, current-limit, and naturally available phase-switch validation.
- **Log-only:** validate the future `velib_python` provenance/import change on
  supported Venus OS releases, including startup, D-Bus registration, MQTT
  recovery, and absence of unintended Wattpilot commands.
- **Active charging required:** observe natural winter/low-PV grid-import or
  stale-grid-telemetry dispatch with `AllowGridCharging=false`; do not force an
  unsafe import or telemetry outage.
- The complete operator behavior checklist remains in README and the safety
  invariants remain in `docs/wattpilot-architecture.md`.
