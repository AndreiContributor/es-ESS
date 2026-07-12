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

- Venus OS `v3.73`, Wattpilot firmware `42.5`, and operator-verified
  Solar.wattpilot app `2.1.0` are the only approved runtime baseline.
- Auto/Eco PV-only control, no-grid protection, bounded running-session battery
  assist, telemetry freshness, phase switching, reconnect handling, runtime
  status, configuration migration/validation, and graceful shutdown are
  implemented and tested.
- Manual charging remains user-controlled. Direct current/start/stop writes
  fail closed unless Wattpilot telemetry confirms ECO mode; a one-time release
  of stale Auto/Eco limits on entry to Manual is the sole approved exception.
- The remaining Wattpilot live-validation gap is natural winter observation of
  grid-import and stale-grid-telemetry dispatch. The remaining implementation
  item is deterministic provenance for `velib_python`.

Deployment information still not established:

- Whether Venus OS / GX releases beyond the validated `v3.73` must be
  supported.
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

Open question:

- Which Venus OS / GX versions, if any, must be supported beyond `v3.73`?

## Completed

All completed entries below retain their original identity and durable result.
Unless an entry explicitly says otherwise, the work preserved Manual-mode
ownership, Auto/Eco no-grid safety, bounded continuation-only battery assist,
Wattpilot command ownership, public D-Bus/MQTT contracts, configuration
compatibility, and the prohibition on shared 16 A cable/current-limiting logic.

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

### P4 - Audit And Pin The Victron `velib_python` Dependency

Goal:

Make the Victron D-Bus dependency reproducible and auditable while preserving
the behavior validated on Venus OS `v3.73`.

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
- `RuntimeCompatibility.py` permits only the validated Venus OS `v3.73`
  baseline, so dependency selection must be evaluated against that exact
  runtime rather than current upstream `master` alone.

Implementation:

- Identify the exact Victron upstream revision represented by the bundled
  files, or record that it cannot be recovered.
- Compare the bundled `vedbus.py`, `dbusmonitor.py`, `settingsdevice.py`, and
  `ve_utils.py` with both current upstream and the copy shipped by Venus OS
  `v3.73`.
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

Log-only (safe in production). Validate on the supported Venus OS `v3.73` GX
device with no active charging or other controlled transition required.

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
  not present in `v3.73`.
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
  tests and log-only GX validation on Venus OS `v3.73`.
- Wattpilot Manual/Auto safety boundaries and public D-Bus/MQTT contracts are
  unchanged.
- Full unittest suite passes.

## Suggested Implementation Order / PR Execution Queue

Use this queue as the implementation order. Each numbered entry is one
PR-sized batch. Do not pull later items into the active PR. When the user says
`fix next PR items`, select the first PR below containing unfinished backlog
items, present the required implementation plan, risks, and verification, and
then follow the repository working agreement for approval and implementation.
After delivery, move the finished backlog items to `Completed` and advance the
queue on the next request.

1. P4 audit and pin the Victron `velib_python` dependency — establish
   provenance and deterministic import ownership before considering any
   dependency replacement; keep this separate from Wattpilot behavior changes.

The P4 winter grid-import dispatch validation is an observation task, not a
code PR, and remains open independently of this queue. Complete it only under
natural suitable low-PV conditions; do not force production grid import or
disconnect critical telemetry to satisfy it.

Hardware validation scope for the remaining backlog:

- The P4 `velib_python` audit requires log-only startup and D-Bus registration
  validation on the supported Venus OS `v3.73` GX device; active charging is
  not required.
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

- **Log-only:** validate the future `velib_python` provenance/import change on
  Venus OS `v3.73`, including startup, D-Bus registration, MQTT recovery, and
  absence of unintended Wattpilot commands.
- **Active charging required:** observe natural winter/low-PV grid-import or
  stale-grid-telemetry dispatch with `AllowGridCharging=false`; do not force an
  unsafe import or telemetry outage.
- The complete operator behavior checklist remains in README and the safety
  invariants remain in `docs/wattpilot-architecture.md`.
