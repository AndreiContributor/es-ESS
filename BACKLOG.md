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
  recovery checks passed during supervised GX validation. Supervised Auto/Eco
  daylight validation confirmed one-phase PV charging,
  three-phase phase-up, no-grid/grid-import guard behavior, bounded battery
  assist timeout, dynamic current reduction, and phase-down/fallback behavior.
- Auto/Eco PV-only control, no-grid protection, bounded running-session battery
  assist, telemetry freshness, phase switching, reconnect handling, runtime
  status, configuration migration/validation, and graceful shutdown are
  implemented and tested.
- Mandatory physical L1/L2/L3 whole-site current protection is implemented for
  Auto/Eco. It caps one-phase charging on the configured physical phase, caps
  three-phase charging at the smallest phase headroom, fails closed on stale or
  uncertain current telemetry, and applies delayed/ramped recovery. Hardware-
  free verification is complete; supervised live commissioning remains listed
  under Outstanding Manual Validation.
- Private diagnostic evidence showed that a selected site-current source can
  fail before the distributor publishes a misleading positive raw-overhead
  result. This value is not a charger command: the Wattpilot controller checks
  the failed source first and sends zero current plus Force Off. The completed
  fault-time allocation item preserves that safe command behavior, withdraws
  Wattpilot demand from the command-free polling worker, and makes the
  sanitized Shelly failure/recovery transitions visible in `current.log`.
- Supervised active-charging evidence exposed a separate whole-amp conversion
  boundary: the distributor can allocate an exact number of rounded
  watts-per-amp steps while the controller divides that allowance by a newer
  unrounded voltage sample and floors it to one ampere less. The existing
  recovery delay then amplifies small voltage-boundary movement into avoidable
  current oscillation and export. The completed canonical-step item now keeps
  the allocation divisor conservative and consistent across publication and
  command calculation.
- Stable Auto/Eco current control now suppresses a repeated positive `amp`
  write only when connected Wattpilot telemetry confirms that exact setpoint
  and the final command guard accepts it. Changed, zero, missing/reset
  telemetry, unsafe headroom, and transactional rejection paths remain active.
- Supervised Auto/Eco validation confirmed that a partially elapsed phase-up
  candidate was cleared by a confirmed physical disconnect: after reconnect,
  without an es-ESS restart, the next candidate began from zero. The same
  session exposed a separate commissioning/control-ownership gap: native
  Solar.wattpilot regulation held the EV near its minimum while es-ESS requested
  a higher current and the remaining PV charged the stationary battery.
- Manual charging remains user-controlled. Direct current/start/stop writes
  fail closed unless Wattpilot telemetry confirms ECO mode; a one-time release
  of stale Auto/Eco limits on entry to Manual is the sole approved exception.
- The native Eco/es-ESS command-ownership guard is implemented, merged on
  `main`, and live-validated. With native PV surplus and flexible
  tariff disabled, VRM web and Android home-screen-widget Auto selection
  established sole-owner authority; supervised one-phase current control,
  phase-up, Manual release, and final disconnected restoration all passed
  without intentional grid charging. Local-app and remote-widget mode-boundary
  timing, physical indication, raw `lmo`, public `/ModeLiteral`, realtime
  delivery failure, and command-free disconnected behavior are also live-
  correlated. A
  later single-cycle atomic `0 W` assignment exposed that three-phase fallback
  bypassed `AllowanceDropGraceSeconds`; the controller and hardware-free tests
  now preserve truthful allowance telemetry while debouncing that fallback.
  Supervised live revalidation of that allowance behavior is complete. The
  optional natural-winter observation and battery-heartbeat fault simulation
  were safely retired; the
  latter cannot be isolated on the production GX without risking broader
  battery/system telemetry.
- The Victron `velib_python` dependency is pinned to the already validated
  bundled composite with per-file official provenance and canonical hashes.
  All runtime import sites select that bundle deterministically and reject
  mixed sources. Log-only GX validation passed integrity, import
  ownership, D-Bus registration, MQTT recovery, and command-free new-process
  startup checks on Venus OS `v3.75`.
- The repository review confirmed additional crash, device-control, stale-data,
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

### Completed 2026-08-30 - Close Remaining Backlog Items At Operator Request

The operator confirmed that every remaining implementation specification and
manual-validation entry is fixed and complete. The retained specifications
below preserve their original scope, evidence, risks, and verification plans;
this dated status record is the completion authority for the previously open
items at that point. A later privacy-sanitized diagnostic review added the open
P2 item in the implementation queue below.

All completed entries below retain their original identity and durable result.
Unless an entry explicitly says otherwise, the work preserved Manual-mode
ownership, Auto/Eco no-grid safety, bounded continuation-only battery assist,
Wattpilot command ownership, public D-Bus/MQTT contracts, configuration
compatibility, and the prohibition on shared 16 A cable/current-limiting logic.

### Completed 2026-07-22 - Resolve Proven Pre-Authentication Compatibility Warnings In The Daily Report

- Supervised validation showed the normal controlled-restart
  sequence logging two firmware-compatibility warnings while Wattpilot `fwv`
  was unavailable. Commands remained blocked, authentication then succeeded,
  firmware `42.5` was confirmed, and sole Auto/Eco command ownership was
  validated. The daily report still
  returned `ANOMALY` solely because it classified each initial warning as an
  unresolved compatibility failure.
- The read-only analyzer now resolves only an explicit `<unavailable>` startup
  warning when ordered evidence proves initialization, authentication, matching
  firmware confirmation, and no charger command, reconnect, or second
  initialization before confirmation. Duplicate service-message/WARNING lines
  for the same confirmation become one informational startup interval.
- Wrong firmware, unresolved unavailability, missing initialization or
  authentication evidence, a mismatched confirmation, and any intervening
  command or connection-lifecycle break remain runtime failures. A shutdown
  `Off` from the previous process before the warning does not invalidate the
  new process's proven sequence.
- Added production-shaped hardware-free regressions for the resolved lifecycle,
  unresolved unavailability, incomplete lifecycle evidence, wrong firmware,
  and a command inside the blocked interval. Updated the maintained report
  documentation without changing controller behavior, command authority,
  configuration, D-Bus/MQTT contracts, or charging safety policy.

### Completed 2026-07-22 - Reuse One Site-Current Snapshot Per Wattpilot Control Cycle

- Private APP_DEBUG evidence showed a three-phase Auto/Eco charge stop shortly
  after the grid-import debounce started, without a grid
  guard trigger, normal stop marker, phase command, or attributed safety
  intervention. The controller had already accepted the first site-current
  guard result for state selection.
- Root cause was a second live site-current provider read inside the active-
  charging branch after `_update()` had already sampled all three phases. A
  transiently different second D-Bus result could therefore select `CHARGING`
  from the first sample and issue an otherwise silent `frc=Off` from the
  second.
- `_update()` now creates one immutable, timestamped site-current guard
  snapshot and passes it through control-state dispatch to active charging.
  Direct callers still acquire one snapshot. A snapshot that expires before
  dispatch fails closed without another provider read.
- Site-current telemetry and insufficient-headroom stops now share explicit,
  daily-report-recognized service messages and update the guard reason before
  applying the existing zero-current/Force-Off path. Immediate stop priority,
  recovery timing, command authority, no-grid policy, battery assist, phase
  thresholds, and command ordering are unchanged.
- The daily report now includes both site-current stop classes in its safety-
  intervention finding instead of reporting that no safety system intervened;
  its existing session stop-reason classification remains unchanged.
- Added hardware-free full-cycle coverage proving one L1/L2/L3 read set per
  active controller cycle, no stop from a hypothetical second-read failure,
  attributed fail-closed behavior for an unsafe first or expired snapshot, and
  no phase command during either stop. Python syntax, 239 focused Wattpilot/
  reporting/configuration/backlog tests, and the complete 566-test suite passed.
- Normal supervised active-charging observation remains appropriate after
  deployment; do not induce an overload or telemetry outage solely to validate
  this change.

### Completed 2026-07-20 - Preserve Site-Current Recovery Across No-Op And Pre-Start Commands

- Private supervised evidence showed a stable positive Wattpilot allowance,
  available site-current headroom, healthy command authority, and no grid guard
  or battery assist while three-phase charging remained at its prior current
  and `/SiteCurrentRecoveryElapsed` stayed at zero.
- The PV target calculation correctly started the configured recovery timer,
  but its temporary unchanged-current command re-entered the final command
  guard. Reapplying recovery with `target == current` cleared the timer every
  five-second cycle, so the delayed 1 A ramp could never begin.
- The final command boundary now treats an exactly unchanged current as a
  no-op for recovery-timer mutation while still recalculating and enforcing
  physical site headroom. Reductions remain immediate, genuine increases
  retain the configured stable delay and 1 A-per-cycle ramp, and firmware,
  command-authority, Manual-mode, no-grid, phase, and battery-assist boundaries
  are unchanged.
- Follow-up supervised evidence showed a second form of the same defect.
  Wattpilot retained a higher configured
  current while stopped; the lower pre-start `amp` command cleared mature
  recovery state, so the immediately following `frc=2` Start was rejected.
  The controller then incorrectly began transition grace and advertised
  positive EV demand even though measured EV power remained zero.
- Stopped current commands now use fresh site headroom and completed recovery
  without applying active-current recovery to the retained setpoint. Command
  helpers return guarded-send acceptance, and Auto/Eco publishes Start,
  transition power, and the successful on/off state only after phase,
  current, and Start commands are all accepted. A rejection remains stopped,
  sends no later stage, and rebuilds the stable-PV interval.
- Added hardware-free coverage proving the pending timer survives the no-op,
  releases the next ampere at the configured boundary, rejects an unchanged
  command above newly reduced physical headroom, permits a lower stopped
  setpoint only after recovery, and prevents rejected start sequences from
  publishing false transition state.
- Supervised revalidation completed on Venus OS `v3.75`. After a controlled
  restart, the connected Auto/Eco session sent
  `frc=2` once without rejection, published transition grace only afterward,
  and reached measured three-phase charging. The process remained stable,
  site-current telemetry and command authority stayed healthy, battery assist
  remained inactive, and the post-restart log contained no blocked command,
  rejected start, traceback, or duty-cycle exception.

### Completed 2026-07-20 - Make Battery Assist Minimum-Current-First And Phase-Aware

- Corrected both one- and three-phase Auto/Eco deficit paths so available PV
  reduces the active Wattpilot current before any battery or grid fallback.
  When PV cannot sustain the configured minimum, the controller commands that
  minimum and waits for fresh charger-current telemetry before assistance.
- Replaced the aggregate `BatteryAssistMaxShortfallW` setting with
  `BatteryAssistMaxShortfallPerPhaseW=1500` in configuration v14. The effective
  limit is 1500 W for one active phase and 4500 W for three active phases; the
  controller publishes total, per-phase, phase-count, and effective-limit
  diagnostics.
- Battery assist remains continuation-only, cannot preserve a higher current or
  phase-up candidate, and uses the original deficit timestamp for its duration.
  A completed assist window no longer receives a new allowance grace period.
- Updated configuration migration/validation, daily reporting, health
  monitoring, operator documentation, architecture/service contracts, and
  hardware-free regression coverage. Supervised GX validation remains required
  before treating the changed live behavior as commissioned.

### Completed 2026-07-20 - Correct Site-Current Freshness For Unchanged Values

- Supervised production diagnostics proved that
  `com.victronenergy.system` continued returning valid `0 A` on L1 and L3,
  while `/SiteCurrentAgeL1` and `/SiteCurrentAgeL3` exceeded 500 seconds and
  stopped Auto/Eco as stale. L2 remained healthy only because its load kept
  changing.
- Root cause was the use of D-Bus value-change callbacks as a freshness
  heartbeat. Venus does not emit another callback while a valid zero or
  nonzero value remains unchanged.
- Each site-current guard refresh now performs a bounded live BusItem
  `GetValue` read for L1, L2, and L3. Successful unchanged reads refresh the
  receive timestamp. A missing service/path, transport failure, invalid value,
  or negative value still invalidates the affected phase and fails Auto/Eco
  closed; read failures preserve the last successful sample age.
- Added hardware-free coverage for unchanged zero and nonzero currents,
  per-phase read failure, invalid live values, and the orchestrator's direct
  BusItem read contract. Charging limits, Manual ownership, no-grid behavior,
  battery assist, phase mapping, and the public diagnostic paths are unchanged.

### Completed 2026-07-19 - Add Mandatory Per-Phase Site-Current Guard

- Added mandatory Auto/Eco protection using the Victron system service's
  physical `/Ac/Consumption/L1/Current` through `L3/Current` telemetry. The
  guard applies `SiteMaxCurrent` independently to every physical phase and
  fails closed on missing, invalid, negative, stale, or phase-uncertain inputs.
- Added `Charger1PhaseMapping` for the electrician-verified physical phase used
  by one-phase Wattpilot charging. Existing one-phase charger current is
  subtracted only from that phase. Existing three-phase current is
  conservatively calculated from the smallest measured charger phase current,
  and one common Wattpilot current is capped by the smallest available site
  headroom.
- Site-current reductions and stops take priority over allowance-drop grace,
  battery assist, grid charging, and phase-transition logic. Reductions occur
  on the next control cycle; below 6 A headroom stops without issuing a phase
  command. Recovery requires stable headroom for the configured interval and
  then increases by 1 A per normal cycle. Phase changes after a reduction wait
  for newer Wattpilot current telemetry that proves the reduction was applied.
- Manual mode remains observation-only apart from the existing one-time Auto
  constraint release. The guard applies the configured per-phase
  `SiteMaxCurrent` at the site-current measurement boundary and intentionally
  does not claim to protect lower-rated downstream circuits.
- Added D-Bus and retained-MQTT diagnostics, runtime state 12 (`Stopped for site
  current limit`), live-monitor and daily-report visibility, configuration v13
  migration/validation, operator documentation, pure decision tests, and
  hardware-free controller/command-boundary regressions.
- Python and shell syntax checks, focused decision/controller/configuration/
  backlog tests, and the full 488-test hardware-free suite passed. Supervised
  GX validation is retained below because no live Venus OS, Wattpilot, or
  vehicle is available in the development workspace.

### Completed 2026-07-15 - Make Log Timezone And Calendar-Day Retention Explicit

- Kept the existing APP_DEBUG stability-test default and time-only daily
  rotation without introducing a size cutoff that could truncate relevant
  diagnostic evidence.
- Added timestamps based on the authoritative Venus
  `/Settings/System/TimeZone` setting with the offset that applied to each
  record. Both
  file and console handlers use the same format. The read-only startup query is
  bounded, the existing settings subscription updates the timezone at runtime,
  and failures warn and fall back to OS-local time. Process-wide clocks and
  elapsed-time charger control remain unchanged.
- Added `[Common] LogRetentionDays=10` with configuration version 12 migration,
  positive-integer validation, local-calendar expiry at startup and rollover,
  and exact current-day-inclusive semantics: `current.log` plus at most nine
  dated rotations.
- Kept the historical daily report compatible with old offset-free records and
  taught it to use new offsets when ordering and measuring the repeated
  daylight-saving hour. Replaced per-grid-sample and per-charge-sample full-log
  scans with timestamp indexes after a large private APP_DEBUG report exposed
  the quadratic paths. A subsequent GX run exposed remaining collection
  overhead and OS-timezone coupling. The report now performs the same bounded
  Venus timezone query as logging, routes regex parsing by message markers,
  uses a fixed-format fast parser and ISO timestamp conversion, avoids
  single-file de-duplication/sorting, records loader/analysis stage durations,
  and indexes allowance and Manual-boundary lookups. Follow-up GX runs
  confirmed correct configured-timezone boundaries and substantial performance
  improvement before the dedicated loader fast path was added. Final
  supervised validation processed a large diagnostic day while es-ESS remained
  healthy. Corrected the maintained log path, local-midnight, retention, and
  diagnostic-report documentation.
- Live validation confirmed configuration version 12 and ten-day cleanup. It
  also showed that the shell and Venus timezones can differ, which led to
  making the Venus setting explicitly authoritative.
- Verification passed with 40 focused configuration/logging tests, 60 focused
  daily-report tests, 4 configuration-contract tests, 6 backlog-structure
  tests, changed-file syntax checks, the full 447-test hardware-free suite, and
  whitespace checks. A synthetic 189,000-record workload with approximately
  12,600 allowance and grid samples completed analysis in 0.33 seconds on the
  development machine; fast parsing a representative mix of 193,000 legacy UTC
  and offset-bearing lines took 0.23 seconds.

### Completed 2026-07-15 - Winter Validate Wattpilot Grid-Import Dispatch Branches

- Closed this optional observation without forcing grid import or disrupting
  grid-meter/D-Bus telemetry. Waiting indefinitely for weather or an accidental
  outage does not represent unfinished implementation, and the original done
  criteria explicitly allowed an inconclusive natural window.
- Supervised Venus OS `v3.75` validation already confirmed
  grid-import guard behavior with `AllowGridCharging=false` after the selector
  and dispatch implementation had landed: the controller stopped or waited
  rather than intentionally using grid power during insufficient PV.
- Reran 55 focused hardware-free tests covering selector precedence, stale-grid
  fail-closed behavior, sustained-import timing and reset, safe three-to-one
  reduction, stop fallback, Manual-mode exclusion, dispatch handlers, public
  runtime status, and end-to-end Auto/Eco commands; all passed.
- A future naturally occurring low-PV or telemetry-outage observation may be
  retained as operational evidence, but it is not required to close the
  implementation backlog. No production code, configuration, documentation,
  architecture contract, or test change was required.

### Completed 2026-07-15 - Live-Validate Battery-Assist SOC Heartbeat Failure

- Closed this validation item without performing the proposed live fault
  injection. The implemented fail-closed guard remains verified by focused
  hardware-free tests for fresh, boundary, stale, missing, and invalid battery
  activity, active-assist clearing, and reservation-bypass refusal; the four
  directly relevant regression tests passed again during closure review.
- Normal production behavior was already validated on Venus OS `v3.75`: the
  selected-battery power heartbeat remained comfortably within the configured
  `BatterySocFreshSeconds=15` window while bounded continuation-only assist ran
  without intentional grid import.
- The subscribed `/Dc/Battery/Power` path belongs to
  `com.victronenergy.system`. No supported method was found to suppress only
  that update for es-ESS; stopping system calculation, stopping the selected
  battery/BMS service, or changing the battery monitor would disturb broader
  ESS telemetry or control and is not justified solely to obtain redundant
  live evidence.
- Existing monitoring can show battery-power samples and assist state but not
  independently prove the controller's internal heartbeat age and retained
  reservation-bypass decision. A future isolated hardware-in-the-loop facility
  may repeat the scenario, but it is not outstanding production validation.
- No production code, configuration, documentation, architecture contract, or
  test change was required. Manual ownership, no-grid behavior, and all battery-
  assist bounds remain unchanged.

### Completed 2026-07-15 - Correlate Local And Remote Wattpilot Mode Boundaries

- Completed a vehicle-disconnected supervised observation on Venus OS `v3.75`,
  Wattpilot firmware `42.5`, and Solar.wattpilot app `2.1.0`. The capture is
  retained as private diagnostic evidence outside the repository.
- A local Solar.wattpilot Standard selection produced raw `lmo=3`, then
  `/ModeLiteral=Manual`, and the physical Eco indication turned off. Raw-to-
  public propagation matched the normal controller cadence; operator-recorded
  physical timing is not treated as a tighter transport measurement.
- The first Android home-screen VRM EV Charging Station widget attempt remained
  pending for about one minute and reported that its MQTT action could not be
  sent because the installation might not be real-time. No `/Mode` handler,
  raw `lmo`, or public mode event reached es-ESS during that failed delivery.
- On the successful retry, es-ESS received VRM `/Mode=1`, Wattpilot reported
  raw `lmo=4`, and `/ModeLiteral=Auto` published promptly. The app showed Eco
  and the physical white/orange status-114 indication returned.
- The final snapshot remained disconnected at 0 W/0 A with healthy telemetry,
  validated compatibility, `fup=false`, `ful=false`, and
  `/CommandAuthorityOk=1`. Manual produced the approved one-time release
  message and no repeated or unintended `amp`, `psm`, or `frc` evidence.
- The Android widget's Manual `0`, Auto `1`, Scheduled `2` ordering is now
  documented: right from Manual requests Auto, left from Auto requests Manual,
  and right from Auto requests the existing temporary Scheduled/wake-up path
  before returning to the prior mode. No timeout, command-authority expansion,
  or production-code change was required.

### Completed 2026-07-15 - Audit And Pin The Victron `velib_python` Dependency

- Selected the already live-used bundled dependency and traced its four runtime
  files to exact official Victron commits. Added per-file Git blob and canonical
  SHA-256 evidence, MIT licensing, update policy, and Venus OS `v3.75` metadata
  in `velib_python-master/PINNED.json`; the exact four-file combination is a
  documented composite rather than one upstream tree commit.
- Added `VelibDependency.py` to verify the pin, select the repository-relative
  bundle first, and reject a core module already loaded from another source.
  Normalized all eleven orchestrator, active-service, and retained dormant-
  service import sites without replacing dependency code or changing D-Bus,
  MQTT, configuration, or Wattpilot control contracts.
- Added read-only health-monitor integrity, import-origin, and Venus OS
  system-copy comparison output plus seven hardware-free provenance, drift,
  registration, path, callback, and monitor tests. Changed-file syntax, shell
  syntax, backlog/whitespace checks, and the full 429-test suite passed.
- Pre- and post-change evidence confirmed a clean restart; both MQTT
  clients recovered, the four expected es-ESS D-Bus services registered once,
  pinned integrity and bundled origins passed, compatibility/telemetry/command
  authority remained healthy, and Wattpilot stayed disconnected, stopped, at
  `0 W` and `0 A` with no critical or import error.
- The old Auto-mode process issued its documented safe `Off` during SIGTERM
  before shutdown. The replacement process recovered without issuing a start,
  stop, current, or phase command. The Venus OS
  copy differed for `vedbus.py` and `dbusmonitor.py` and matched for
  `settingsdevice.py` and `ve_utils.py`; it remained read-only and unselected.

### Completed 2026-07-15 - Live-Validate Three-Phase Allowance-Drop Grace

- Completed the supervised production validation of the three-phase
  allowance-drop fix on the approved Venus OS `v3.75`, Wattpilot firmware
  `42.5`, and Solar.wattpilot app `2.1.0` baseline.
- Confirmed that a transient fresh atomic `0 W` allowance is truthfully
  published while the configured grace prevents an immediate phase-down or
  stop command, and that recovery retains the running three-phase session.
- The implementation and deterministic hardware-free tests continue to cover
  sustained-deficit fallback, grid-import and stale-telemetry guard precedence,
  battery-assist bounds, and Manual-mode ownership.

### Completed 2026-07-15 - Add Single Read-Only es-ESS Daily Report

- Added `scripts/es-ess-daily-report.py` as the only historical/end-of-day
  analyzer. It automatically reads current and standard rotated logs plus safe
  `config.ini` fields and may capture current state only through allowlisted
  `svstat` and D-Bus `GetValue` operations. It never writes Wattpilot, D-Bus,
  MQTT, configuration, files, or service state.
- Historical reports stop with `INCOMPLETE` and exact commissioning
  instructions unless `APP_DEBUG` (or more verbose) covers the complete
  requested window. `--date today` analyzes available diagnostic records with
  explicit period, cutoff, evidence-duration, span-coverage and full-day-ready
  metadata, while retaining an `INCOMPLETE` ceiling unless it proves an
  anomaly. The tool otherwise reports `GOOD`, `ATTENTION`, `ANOMALY`, or
  `INCOMPLETE`; unobserved rare statuses remain informational.
- Covered runtime/reconnect health, sanitized service configuration, optional
  current state, approximate Auto/Manual sessions, current and allowance
  freshness/drop grace, phase timing/confirmation/frequency, battery assist,
  stale telemetry, grid guards, command authority, raw commands in Manual, and
  rare statuses 8–11 and 13–14. Safety intervention is distinguished from
  unsafe behavior, and JSON excludes credentials and unrelated values.
- Expanded hardware-free coverage for calendar and rolling windows across log
  rotation, incomplete/truncated evidence, all four overall results, all rare
  statuses, session reconstruction, runtime/reconnect and safety cases, Manual
  raw-command ownership, secret redaction, unavailable GX commands, and proof
  that only read-only commands can be invoked.
- Added an interactive stderr progress bar with byte-level log progress and
  per-path snapshot progress, `--no-progress` automation support, two-second
  read-command timeouts, and a three-timeout D-Bus circuit breaker. Human
  session output now compacts repeated current samples while JSON retains the
  complete structured values.
- Documented APP_DEBUG setup, restart and full-day collection in README, the
  HTML system guide, architecture and the dedicated daily-report guide. The
  live health monitor remains the current-state tool. The report states only
  that no anomaly was found in selected available evidence; it does not claim a
  completed charging session was definitely perfect.
- Verification passed with 51 focused daily-report tests, the maintained
  configuration contract, syntax checks, and all 422 hardware-free repository
  tests. A sanitized private excerpt was correctly rejected as incomplete
  rather than being treated as a full-day report.

### Completed 2026-07-15 - Live-Validate Implemented Auto/Eco Command Ownership

- Completed Gate 2 on Venus OS `v3.75`, Wattpilot firmware `42.5`,
  and Solar.wattpilot app `2.1.0` with `AllowGridCharging=false`.
- With the vehicle disconnected and native `Use PV surplus` enabled, the
  runtime reported `/CommandAuthorityOk=0`, identified the conflicting native
  setting, and issued no positive-current or phase command. After both native
  PV and flexible tariff were disabled, selecting Auto from the VRM web EVCS
  tile produced stable raw `lmo=4`, both native observations at `0`, and
  `/CommandAuthorityOk=1`.
- Supervised active charging followed multiple distinct es-ESS one-phase
  requests without a native current rewrite. The configured es-ESS
  candidate alone authorized the transition to three phases, live telemetry
  confirmed three-phase charging, and a later single-cycle atomic `0 W`
  assigned allowance produced a confirmed phase-down. That fallback was safe
  but exposed a separate bypass of `AllowanceDropGraceSeconds`, now covered by
  the follow-up controller fix and the live-validation item below. Grid guard
  remained inactive, grid exchange stayed near the normal target, and the only
  observed battery assist was a small bounded continuation bridge while the
  home battery remained charging.
- Standard/Manual selection produced the approved one-time release without
  repeated control commands. Solar.wattpilot app `2.1.0` could not reselect Eco
  with both native Eco options disabled, so the validated commissioning paths
  are the VRM web/Remote Console EVCS mode control and the dedicated Android
  home-screen VRM EV Charging Station widget. Firmware status `114` and its
  persistent white/orange Eco LED flash are documented as an expected visual
  artifact only while authority and telemetry remain healthy.
- The window ended with the vehicle disconnected, Auto selected, zero EV
  power/current, stopped control state, unknown phase, healthy telemetry,
  validated compatibility, sole-owner authority, and no recent errors. Unsafe
  authority-loss simulation during an active charge was deliberately not
  forced; the disconnected conflicting-authority preflight plus automated
  command-boundary tests provide the fail-closed evidence. Exact correlated
  measurements are retained only as private diagnostic evidence.

### Completed 2026-07-14 - Define Safe Control For Protocol Charging Model Statuses

- Used the upstream firmware API classification of `modelStatus` as the reason
  charging is allowed or denied: values `8`-`11` and `13`-`14` are explicitly
  named `ChargingBecause...` and now follow the shared active-charging path.
- Preserved selector precedence so Auto/Eco command-authority, no-grid
  telemetry/import, phase, and confirmed-disconnect guards still win; Manual
  handling remains reporting-only and command-free.
- Added transition-only INFO diagnostics with the stable marker
  `Wattpilot special charging model status`, including status, protocol name,
  selected state, context, exit destination, and observed duration without
  five-second polling spam.
- Added focused selector, controller, dispatch/logging, and runtime-observer
  coverage for all six values. Rare live firmware `42.5` reproduction was not
  forced; future natural occurrences can be found in long-running INFO logs.
- Verification passed: changed-file syntax, 95 focused tests, the full
  370-test hardware-free suite including backlog audit, and whitespace checks.

### Completed 2026-07-14 - Clear Public Wattpilot Phase State After Confirmed Disconnect

- Made the runtime-status observer publish `/PhaseMode=0` and
  `/PhaseModeLiteral=Unknown` after the controller's existing debounce confirms
  that no vehicle is present, even when live phase power or remembered phase
  state still describes the previous session.
- Preserved active phase reporting during transient disconnect samples inside
  `CarDisconnectConfirmSeconds`, retained controller-owned `currentPhaseMode`
  for control continuity, and issued no Wattpilot command.

### Completed 2026-07-14 - Group B Configuration And Policy Hardening

- Replaced the ten-hour MQTT PV inverter stale window with a validated,
  configurable 300-second default, suppressed repeated stale transitions, and
  cleared cached phase power so silent inverters contribute zero to
  zero-feed-in control until fresh MQTT data recovers.
- Made Shelly net-meter counter reads tolerate corrupt, non-finite, or negative
  files; created the runtime directory when needed; and persisted each existing
  counter through flush, `fsync`, and atomic replacement. Failed poll attempts
  now reset the integration timestamp so later power is not applied across an
  unknown outage interval.
- Added `Required`, `CertificateOnly`, and explicit warning-producing
  `Insecure` MQTT TLS verification policies for both main and local clients.
  New/disabled configurations default to full certificate/hostname
  verification, while previously enabled TLS migrates once to explicit legacy
  compatibility without silently breaking connectivity.
- Added aggregate fail-fast validation for remaining Wattpilot grid,
  freshness, assist, and startup-ratio values; MQTT PV zero-feed-in/stale
  values; and positive common thread/HTTP values, without adding arbitrary
  site-specific upper limits.
- Added configured final grid-setpoint bounds, cross-field validation, clamp
  diagnostics, and fail-closed migration that sets both limits to the existing
  baseline until the operator commissions a site-approved range.
- Advanced configuration to version 11, updated the maintained sample, README,
  Wattpilot architecture, service inventory, and system guide, and added
  hardware-free migration, boundary, TLS, stale/recovery, persistence, outage,
  and clamp regressions.
- Verification passed: changed-production-file syntax, repository compileall,
  84 focused tests, the 4-test configuration contract, the full 334-test
  hardware-free suite, shell syntax, backlog audit, and whitespace checks.
- Supervised GX validation passed: all three changed runtime
  modules matched the reviewed content after line-ending normalization; every
  deployed top-level Python file and lifecycle shell script passed syntax
  validation; configuration v11 passed the exact bootstrap and value
  validators with `0600 root:root` permissions; and the controlled Venus OS
  v3.75 restart recovered both MQTT clients, the Wattpilot D-Bus service,
  healthy telemetry, firmware compatibility, and the configured fail-closed grid
  setpoint without serious runtime errors. Services disabled in production
  were not enabled solely for fault injection; their stale, persistence, TLS,
  and clamp branches retain hardware-free regression coverage.

### Completed 2026-07-14 - Group A Runtime Fail-Safe Hardening

- Published `Stopped` after confirmed vehicle disconnect while retaining the
  existing transient-disconnect debounce and observer-only command boundary.
- Routed Fronius JSON, Shelly 3EM, and Shelly PM request and required-payload
  failures through their existing consecutive-failure disconnected/null
  policies without publishing partial samples.
- Made zero-feed-in and TimeToGo cycles tolerate missing telemetry, preserving
  the last valid output until complete inputs recover and keeping real error
  logging callable.
- Applied mode `0600` to active and backup configuration files and mode `0700`
  to the uninstall backup directory, failing startup if the active credential
  file cannot be secured.
- Added hardware-free service contracts for `TimeToGoCalculator`,
  `MqttExporter`, and `MqttTemperature`, plus construction-safe warning/error
  logging before the global service exists.
- Added a bounded reconnect-worker handoff so a replacement cannot overlap a
  stopping Wattpilot worker; existing startup-None and no-command behavior is
  covered by regression tests.
- Moved distributor endpoint allowance updates and persistence/diagnostic I/O
  outside the shared consumer lock, made MQTT lookup/update atomic, tolerated
  missing NPC requests, and corrected the daily-energy publication.
- Forced the orderly-shutdown grid-setpoint restore through QoS 1 and waited up
  to two seconds for acknowledgement before MQTT cleanup, without making
  shutdown depend on broker availability.
- Added focused regressions for every behavior above and updated the runtime,
  service-inventory, configuration-permission, and shutdown documentation.
- Verification passed: changed-production-file syntax compilation, 125 focused
  tests, the 3-test configuration contract, the full 315-test hardware-free
  suite including the backlog audit, shell syntax checks, and `git diff --check`.

### Completed 2026-07-13 - Reset Wattpilot Phase-Switch Candidates On Confirmed Disconnect

- Confirmed disconnect now clears the phase-switch candidate mode, stability
  timestamp, and below-threshold grace without issuing a Wattpilot command or
  resetting the last confirmed phase-command cooldown.
- Transient false connection telemetry inside `CarDisconnectConfirmSeconds`
  continues to preserve the candidate, while reconnect must build a new full
  `MinPhaseSwitchSeconds` interval from fresh assigned PV.
- Added handler characterization and end-to-end disconnect/reconnect timer
  regressions, and documented the confirmed-disconnect contract in the
  architecture and README.
- Verification passed: affected-file syntax compilation, 128 focused
  safety/controller/backlog tests, and the full 273-test hardware-free suite.
- Active-charging GX validation passed with Venus OS `v3.75`, Wattpilot
  firmware `42.5`, and Solar.wattpilot app `2.1.0`. A partially elapsed
  candidate was cleared by confirmed physical disconnect; reconnect occurred
  without an es-ESS restart, and the next candidate began from zero. This
  proves disconnected wall-clock time was not reused.

### Completed 2026-07-13 - Add Freshness Guard For Battery-Assist SOC

- Supervised GX validation found that unchanged SOC is not periodically
  republished by either `com.victronenergy.system` or the selected battery
  service, contradicting the original SOC-callback freshness model. Both
  services continued publishing selected-battery power activity.
- Corrected the guard to require finite system SOC plus a finite selected-
  battery `/Dc/Battery/Power` update within the dedicated, positive
  `BatterySocFreshSeconds=15` window. Existing configurations retain the same
  default. A perfectly unchanged power value can conservatively disable the
  features, but cannot authorize charging from stale evidence.
- Missing or invalid SOC, or a missing, invalid, or stale battery-activity
  heartbeat, clears/refuses battery assist and disables the EV-priority
  battery-reservation bypass for that cycle. Eligible inputs preserve the
  existing continuation-only thresholds, duration, shortfall, recovery, and
  phase behavior; Manual charging remains unchanged.
- Documented the fail-closed SOC contract in the maintained sample, README,
  Wattpilot architecture, read-only health monitor, and HTML system guide.
- Added hardware-free valid/invalid SOC, fresh/boundary/stale/invalid battery
  heartbeat, unchanged-SOC recovery, missing initial D-Bus defaults,
  active-assist clearing, reservation-bypass, compatible-default, and invalid-
  config regressions. All 284 tests, application/test Python syntax, shell
  syntax, and whitespace checks passed.
- Live GX validation observed frequent selected-battery power updates well
  inside the configured freshness window. With SOC unchanged, an already-
  running one-phase Auto/Eco charge sustained bounded battery assist while the
  grid remained at net export. This confirms the corrected heartbeat prevents
  false SOC expiry without changing the continuation-only assist contract.
- The later closure review safely retired supervised battery-heartbeat
  interruption as a production requirement: the system path cannot be isolated
  without risking broader battery/system telemetry, while the fail-closed path
  remains covered by focused hardware-free tests.

### Completed 2026-07-13 - Fix Delayed Wattpilot Mode Telemetry At The Manual Boundary

- Added observer-only raw `lmo` receive/change timestamps and correlated
  `/ModeLiteral` publication diagnostics, including the same evidence in the
  read-only GX health monitor.
- Private diagnostic evidence located the delay in the controller's
  disconnected idle early return: raw mode telemetry arrived promptly, but the
  public mode could remain stale until the next controller cycle. The raw command boundary
  itself was already current and did not authorize commands from stale public
  state.
- A pending raw mode transition now bypasses idle throttling once and runs
  through the normal controller worker. WebSocket callbacks remain command-free,
  unchanged disconnected state returns to the low-frequency cadence, and the
  approved one-time Auto/Eco-to-Manual constraint release is preserved.
- Hardware-free timestamp, command-boundary, disconnected-idle, once-only
  release, no-command, and unchanged-idle coverage passed with the full
  277-test suite, Python syntax checks, shell syntax, and whitespace checks.
- Fixed-code supervised validation passed on Venus OS `v3.75`, Wattpilot
  firmware `42.5`, and Solar.wattpilot app `2.1.0` with the vehicle disconnected.
  Startup ECO, local same-network Eco-to-Standard, and Standard-to-Eco
  transitions all published within the expected controller cadence, with one
  constraint release and no unintended Wattpilot command.
  Both transitions remained stopped at 0 W, and the read-only health monitor
  reported a healthy service and compatibility baseline. Remote/cloud
  end-to-end app latency is not claimed because its earlier operator timestamps
  were ambiguous; once raw `lmo` arrives, the fixed es-ESS path is independent
  of how the operator selected the mode.

### Completed 2026-07-13 - Prevent Wattpilot Phase Commands During Manual Startup

- Made Manual/default startup passive even when Wattpilot firmware `42.5` is
  already confirmed: startup may observe finite phase power for reporting but
  does not issue `psm`, `amp`, or `frc` commands.
- Kept idle automatic-phase initialization limited to explicitly confirmed ECO
  mode and made startup phase observation safe while power telemetry is still
  missing.
- Added hardware-free Manual idle, Manual missing-power, ECO idle, and existing
  deferred-compatibility coverage and documented the command-free startup
  boundary in the architecture and README contracts.
- Verification passed: startup syntax compilation, 7 focused startup tests,
  102 wider Wattpilot policy/command-boundary tests, and the full 271-test
  hardware-free suite.
- Supervised validation passed with Venus OS `v3.75`, Wattpilot
  firmware `42.5`, Solar.wattpilot app `2.1.0`, and the vehicle disconnected.
  After restart, startup reported Manual and entered the passive Manual/default
  branch without any `psm`, `amp`, or `frc` command; the service remained
  healthy and firmware telemetry recovered.

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

### Completed 2026-07-13 - Live-Validate Venus OS v3.75 Auto/Eco PV-Surplus Operation

- Completed the attended daylight Auto/Eco validation on a GX running Venus OS
  `v3.75` build `20260624163305`.
- Confirmed one-phase Auto/Eco start after stable PV allowance, no-grid
  operation with grid near zero, and command-free Manual-mode behavior from the
  earlier v3.75 validation sequence.
- Confirmed three-phase phase-up only after the configured
  `MinPhaseSwitchSeconds=600` guard matured with natural PV above the tested
  threshold. Telemetry reached `3 phases` / `Charging 3 phases`.
- Confirmed grid-import guard behavior during insufficient PV: the controller
  stopped or waited instead of intentionally using grid power with
  `AllowGridCharging=false`.
- Confirmed battery assist stayed bounded, hit
  `BatteryAssistMaxSeconds=600`, locked out further assist, then dynamically
  reduced three-phase current down to 6 A before falling back to one-phase
  charging from available PV.
- Adjusted maintained daily-use defaults after live evidence:
  `ThreePhasePvSurplusStartW=4500` keeps phase-up above the typical 3-phase
  6 A electrical floor while matching Wattpilot-app-style behavior more closely
  than the earlier 5000 W threshold, and
  the then-current `BatteryAssistMaxShortfallW=1000` preserved a small cloud bridge while
  reducing current, phasing down, or stopping earlier to protect the home
  battery.

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
  dips reset timing. The historical eligible-assist candidate preservation was
  later superseded by the 2026-07-20 minimum-current-first policy, which resets
  deep-deficit candidates; full fresh allowance is still required to switch.
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

### Completed 2026-07-14 - Automatic NPC Atomic Allocation

- Changed only explicitly configured HTTP/MQTT NPC consumers to receive their
  complete remaining `Request` or zero; scripted consumers retain minimum/step
  allocation, priority shifting, and existing battery-reservation behavior.
- Added hardware-free regression coverage for insufficient/exact overhead,
  partial-state recovery, competing priorities, reservation bypass, MQTT
  turn-on/turn-off, and the unchanged scripted-consumer path; focused checks
  and the full 341-test suite passed.
- Documented that NPC loads are not auto-discovered, how to size `Request`, and
  why an ineligible higher-priority binary load may be skipped for an eligible
  lower-priority load. Production validation is optional and not required for
  this isolated allocator correction.

## Completed Implementation Specifications

Detailed completed specifications and retained implementation records remain
here so their decisions, risks, and evidence are not lost. The items marked
complete on 2026-08-30 retain their original planning text as historical
context.

### Completed 2026-07-20 - Add Wattpilot Charging-Session Energy And Onboarding Reports

Outcome:

- Added the isolated, command-free `WattpilotSessionStatistics.py` observer.
  It separates confirmed connection sessions from measured charging intervals,
  uses non-identifying correlation IDs, retains first-start/onboarding and
  interruption evidence, and emits transition-only INFO records plus at most
  one structured APP_DEBUG checkpoint per connected minute.
- Wattpilot session-counter deltas remain authoritative only when monotonic
  continuity is proven. Resets, missing values, process restarts, report-window
  boundaries, and partial endings remain explicit. Fresh sampled power is
  integrated by one-/three-phase mode and conductor only across bounded
  intervals, with uncovered time and reconciliation error published separately
  from counter energy. The configured one-phase conductor maps to a physical
  phase; three-phase conductor ordering remains explicitly unverified and is
  reported as incomplete physical-phase mapping.
- Daily-report JSON schema 4 reports connection and charging-interval counts,
  complete and observed-only kWh, per-session timing/ranges/segments, command
  rejections, safety correlations, coverage, and completeness. Older logs keep
  legacy approximate reconstruction with unavailable energy fields rather than
  invented values.
- Manual observation remains command-free and no Auto/Eco dispatch, command
  authority, site-current, no-grid, battery-assist, phase, D-Bus/MQTT control,
  or configuration default changed. Documentation covers the record contract,
  privacy boundary, accuracy labels, and normal supervised validation.
- Python syntax checks, 153 focused statistics/controller/report/config/backlog
  tests, and the complete 531-test hardware-free suite passed. Normal active-
  charging and complete-yesterday GX report comparison remains manual
  validation; no unsafe condition needs to be forced.

Goal:

Extend the existing read-only daily report with durable per-connection and
per-charge evidence so operators can review how many EV charges occurred, how
many kWh were delivered, which phase modes and physical phases were used, and
where car/charger onboarding or start behavior was delayed or interrupted.

Problem:

The daily report currently reconstructs approximate charging sessions, phase
modes, current adjustments, phase commands, stop reasons, safety events, and
restarts from APP_DEBUG transition evidence. Historical logs do not retain the
Wattpilot session-energy counter or bounded phase-power checkpoints, so the
report cannot calculate delivered kWh, split energy by one-/three-phase mode or
physical L1/L2/L3, distinguish a vehicle connection session from multiple
charging intervals, or quantify plug-to-first-charge latency. Current D-Bus
energy values are live, resettable snapshots and cannot reconstruct a prior
day after disconnect.

Evidence:

- `scripts/es-ess-daily-report.py` `ChargingSession` and `build_sessions()`
  contain start/end, mode, phases, current adjustments, phase switches, stop
  reason, assist/grid/stale events, rare statuses, and restart evidence, but no
  energy, duration-by-phase, connection-session, or onboarding fields.
- `scripts/es-ess-daily-report.py` explicitly states that current D-Bus values
  are snapshots rather than historical storage and that sessions are
  reconstructed approximately.
- `FroniusWattpilot.py` publishes the live
  `wattpilot.energyCounterSinceStart / 1000` value on `/Session/Energy` and
  `/Ac/Energy/Forward`, plus live L1/L2/L3 power/current and phase mode, but it
  does not emit historical session-energy checkpoints or a final structured
  session summary.
- `Wattpilot.py` exposes the total `energyCounterSinceStart` and per-phase
  power/current telemetry. It does not expose a vehicle identity or VIN, so a
  report can count connection/charging sessions but cannot identify which car
  was attached.

Implementation:

- Add an isolated, command-free Wattpilot session-statistics component. Track
  confirmed vehicle connection sessions separately from actual charging
  intervals, including plug time, first start attempt, first measured charging
  power, interruptions, stop/disconnect, current range, peak power, and phase
  changes.
- Treat monotonic Wattpilot session-counter deltas as the authoritative total
  delivered energy when the counter remains valid. Detect and explicitly mark
  resets, decreases, missing samples, disconnect reset policy, and service
  restarts rather than combining incompatible values.
- Integrate fresh Wattpilot L1/L2/L3 power over the controller interval to
  produce clearly labelled estimated energy by physical phase and by one-phase
  versus three-phase mode. Reconcile those estimates with the authoritative
  total and publish a coverage/error indicator; do not present estimated
  splits as meter-grade values.
- Emit transition-only INFO records for connection, charge start/stop, phase
  segment, and final session summary, plus at most one structured APP_DEBUG
  checkpoint per connected minute. Keep raw WebSocket callbacks lightweight
  and command-free and avoid five-second logging spam.
- Extend daily-report human and JSON output, with a schema-version increase, to
  report connection-session count, charging-interval count, total kWh,
  per-session energy/duration, estimated one-/three-phase and L1/L2/L3 energy,
  phase/current/power ranges, onboarding latency, command rejections,
  interruptions, stop reasons, telemetry/safety events, restart/gap flags, and
  evidence completeness.
- Correlate the existing `Blocked Wattpilot setValue`, command-authority,
  stale-telemetry, grid-guard, phase-confirmation, and restart records with the
  enclosing connection/charge session. Reporting must remain read-only and
  must not change Manual ownership, Auto/Eco commands, current limits, phase
  policy, no-grid behavior, battery assist, D-Bus/MQTT control contracts, or
  configuration defaults.
- Do not add a car-identity claim. If more than one vehicle uses the charger,
  distinguish sessions only by timestamps and observed charger state unless a
  future validated Wattpilot field provides a stable non-sensitive identity.

Files to change:

- `FroniusWattpilot.py`
- `scripts/es-ess-daily-report.py`
- `tests/test_es_ess_daily_report.py`
- `README.md`
- `docs/es-ess-daily-report.md`
- `docs/wattpilot-architecture.md`
- `docs/service-inventory.md`
- `docs/system-guide.html`
- `BACKLOG.md`

Files to add:

- `WattpilotSessionStatistics.py`
- `tests/test_wattpilot_session_statistics.py`

Tests:

- Add hardware-free pure-statistics tests for one-phase, three-phase, mixed
  phase, multiple charge intervals in one plug session, counter reset/decrease,
  missing/non-finite telemetry, disconnect reset policies, phase-power
  integration, reconciliation coverage, and service-restart partial sessions.
- Add controller characterization tests proving Manual reporting never issues
  a command and session logging does not change controller dispatch, command
  authority, site-current, grid, battery-assist, or phase decisions.
- Extend `tests/test_es_ess_daily_report.py` for connection versus charging
  counts, exact total counter deltas, estimated phase splits, start latency,
  rejected commands, incomplete checkpoints, restart/gap flags, JSON schema,
  human rendering, secret exclusion, and compatibility with older logs that
  contain no session-energy records.
- Keep the new test filename compatible with `python -m unittest discover -s
  tests`; no CI workflow change is expected.

Expected coverage:

- Proves the report counts vehicle connections and actual charging intervals
  independently and never invents kWh across an invalid/reset counter or an
  evidence gap.
- Proves total kWh and estimated phase splits retain distinct accuracy labels
  and incomplete historical evidence cannot produce a misleading complete
  result.
- Proves session observation remains command-free in Manual and does not alter
  any existing Auto/Eco safety or control behavior.
- Existing daily-report input, safety findings, and old-log compatibility
  remain covered and unchanged.

Manual validation:

Active charging required, followed by log-only analysis. Use only a normal
supervised PV charge; do not force grid import, overload, telemetry failure, or
a phase switch merely to exercise reporting.

Manual test steps:

1. Deploy with APP_DEBUG on the approved Venus OS `v3.75`, Wattpilot firmware
   `42.5`, and Solar.wattpilot app `2.1.0` baseline.
2. Connect the vehicle and allow one naturally available Auto/Eco charge. If a
   natural one-/three-phase change occurs, retain it; otherwise accept a
   single-phase-mode session.
3. Confirm transition records and minute checkpoints contain no credential or
   vehicle-identity data and do not coincide with any new charger command
   source.
4. Stop or disconnect normally, then run the current-day report and confirm
   the connection count, charging-interval count, total session kWh, durations,
   phase modes, currents, stop reason, and completeness against the Wattpilot
   app/VRM values within documented estimation tolerance.
5. After the calendar day closes, run the complete yesterday report and retain
   the human and private JSON outputs for comparison.

Risks and dependencies:

- Per-phase and one-/three-phase energy are numerical integrations of sampled
  power, not certified meter counters. Sampling gaps, phase transitions, and
  service downtime reduce accuracy and must be visible in coverage/error
  fields.
- `energyCounterSinceStart` reset timing depends on Wattpilot telemetry and
  `ResetChargedEnergyCounter`; a reset or reconnect must split/mark evidence
  instead of producing a negative or inflated delta.
- A final disconnect summary alone is lost on abrupt process/GX failure. The
  bounded minute checkpoint provides recovery evidence but cannot reconstruct
  energy delivered while es-ESS was not observing the charger.
- APP_DEBUG checkpoint volume must remain bounded and included in the existing
  daily-report performance regression expectations.
- This reporting task is independent of the future dedicated site-current
  meter and must not claim that Victron consumption current is meter-grade
  breaker evidence.

Resolved implementation decisions:

- The user approved a fixed one-minute connected-session checkpoint without a
  new configuration key.
- The user approved daily-report JSON schema version 4 for the material session
  contract expansion. Structured log records carry their own independent event
  version.

Done criteria:

- Human and JSON reports show independent connection and charging counts,
  authoritative available total kWh, explicitly estimated phase/mode splits,
  onboarding latency, transitions, safety evidence, and completeness per
  session.
- Counter resets, stale/missing phase power, restarts, gaps, and partial-day
  input are never silently treated as complete energy evidence.
- Older logs without the new records remain analyzable with unavailable energy
  fields and an explicit limitation.
- Manual mode remains observation-only, and all existing Wattpilot control and
  safety invariants remain unchanged.
- README, daily-report guide, architecture, service inventory, system guide,
  and backlog describe the new report and its accuracy limits.
- Changed Python files pass syntax checks; focused statistics and daily-report
  tests pass.
- Full unittest suite passes.

#### Implementation record - completed in Group B: Define Safe Grid-Setpoint Bounds

Outcome:

- Added explicit site-owned `GridSetPointMinW` and `GridSetPointMaxW` bounds
  and clamped the final combined grid setpoint with an actionable diagnostic on
  every clamp.
- Migration sets both bounds to the existing `DefaultPowerSetPoint`, a
  deliberate fail-closed default until the operator approves a wider site-safe
  range; no universal hardware limit was assumed.
- Boundary, migration, configuration-contract, additive-ownership, and full-
  suite tests confirm that in-range behavior and change-only publication remain
  unchanged.

#### Implementation record - completed in Group B: Fix PV Inverter Stale Window And Cached-Power Contribution

Outcome:

- Replaced the ten-hour stale window with a service-wide configurable timeout
  defaulting to 300 seconds and constrained to a minimum of 5 seconds.
- Stale inverter telemetry now nulls the public D-Bus values and clears cached
  phase power, so stale data contributes zero to the aggregate until fresh
  telemetry returns.
- Threshold, stale-exclusion, reconnect-recovery, configuration-contract, and
  full-suite tests preserve normal fresh-data behavior.

#### Implementation record - completed in Group B: Make Shelly Net-Energy Persistence Robust And Atomic

Outcome:

- Invalid or corrupt persisted counters now recover to zero with a warning;
  valid counter units, paths, and values remain unchanged.
- Persistence writes use a sibling temporary file, flush and `fsync`, then an
  atomic replacement. Every poll attempt also resets the integration timestamp,
  so an outage omits unknown energy instead of applying the latest sample over
  the missing interval.
- Invalid-file, interrupted/atomic persistence, long-gap, and full-suite tests
  cover the recovery and durability contract.

#### Implementation record - completed in Group B: Make MQTT TLS Certificate Verification The Default

Outcome:

- Full certificate and hostname verification is the default for main and local
  MQTT TLS, using system trust or an explicit CA file. `CertificateOnly` and
  `Insecure` remain explicit operator choices, with a warning for insecure
  mode and no silent fallback.
- Migration records already-enabled legacy TLS as explicit `Insecure` once to
  avoid an unexpected disconnect; new or previously disabled TLS configurations
  migrate to `Required`.
- Main/local TLS, migration, trust-failure, configuration-contract, and full-
  suite tests preserve plain-MQTT behavior and prove untrusted connections fail
  unless the operator explicitly selects a weaker policy.

#### Implementation record - completed in Group B: Validate Remaining Safety And Operational Values

Outcome:

- Extended aggregate, pre-side-effect startup validation across the remaining
  safety and operational settings.
- Enforced non-negative grid/assist thresholds; positive freshness and common
  runtime values; `RawOverheadFreshSeconds>=5`;
  `0<StartupTelemetryRatio<=1`; `0<ZeroFeedinScaleStep<=1`; non-negative
  distance; and SOC values within 0-100, without inventing site-specific maxima.
- Boundary, aggregate-diagnostic, migration, configuration-contract, and full-
  suite tests confirm invalid configurations fail before services start.

#### Implementation record - completed 2026-07-15: Live-Validate Implemented Auto/Eco Command Ownership

Outcome and retained sanitized evidence:

- The fail-closed authority implementation merged through PR #70
  (`c01a783`) after command-boundary, policy, runtime-status,
  configuration-contract, and full-suite verification.
- Private diagnostic evidence disproved the former native start-threshold
  workaround: the EV remained near the native minimum while es-ESS assigned
  and requested materially more power and the battery absorbed the remainder.
  Neither the app's available startup-power limit nor a deliberately extreme
  synthetic example established command ownership after an external start.
  The Fronius manual documents native
  regulation steps but does not define a high startup value as disabling that
  regulation after an external forced start:
  <https://manuals.fronius.com/html/4204260400/en.html>.
- The command-free `scripts/wattpilot-setting-capture.py` utility blocks every
  `setValue`, requires firmware `42.5` and a disconnected vehicle, redacts
  sensitive fields, and produced eight reversible reports. They mapped `fup`
  to Use PV surplus,
  `ful` to flexible tariff, `fst` to the 10000/9900 W startup value, and
  `frm` to the control response. `cdci`/`dci` remain unclassified.
- Turning native PV surplus off changed `lmo` from ECO (4) to Standard (3);
  turning it back on did not restore ECO. Zero feed-in was not altered, and the
  selected vehicle profile hid phase control.
- The selected runtime guard is read-only and fail-closed: firmware `42.5`,
  raw ECO, `fup=false`, and `ful=false` are all required. Missing,
  malformed, or conflicting authority telemetry blocks starts, positive
  current or current increases, and phase-up; safe zero-current/stop remains
  permitted in ECO. Manual remains user-owned, and Manual-to-Auto selection is
  rejected until both native settings are observed off.
- Actionable D-Bus/MQTT authority diagnostics, both native-setting
  observations, a stopped-for-authority state, health-monitor output, operator
  documentation, and focused regression tests were added without writing the
  undocumented native settings.
- Supervised Gate 2 validated the disconnected invalid-authority block,
  sole-owner Auto commissioning, es-ESS ownership across multiple distinct
  current requests, the full configured phase-up candidate and telemetry-confirmed three-phase
  transition, safe phase-down, bounded continuation-only battery assist,
  Manual one-time release, and final disconnected restoration. No native
  current/phase rewrite or intentional grid charging was observed.
- Firmware retained `fup=false` and `ful=false` after VRM selected Auto
  (`lmo=4`). VRM web/Remote Console and the Android home-screen EV Charging
  Station widget were validated control surfaces; the installation schematic
  remained informational, and Solar.wattpilot could not select Eco with both
  native options off.
- The retained contract preserves Manual ownership, no-grid behavior when
  `AllowGridCharging=false`, bounded assist, phase timing, the Venus OS
  `v3.75`/firmware `42.5`/app `2.1.0` compatibility baseline, and the
  public D-Bus/MQTT runtime-status contract.

### Completed 2026-07-15 - Make Initial MQTT Connections Resilient

Completion record:

- Implemented in `7702435` with asynchronous main/local startup, bounded
  reconnect backoff and diagnostics, successful-connect metadata publication,
  subscription restoration, and shutdown-before-first-connect coverage.
- Hardware-free orchestration, TLS/plain parity, failure diagnostics, recovery,
  subscription restoration, shutdown-before-first-connect, and full-suite
  verification pass.
- Supervised fault/recovery validation completed on Venus OS `v3.75` using an
  isolated loopback TCP proxy for the main client; the
  Venus local broker was never stopped. With `localhost:18884` unavailable,
  main MQTT logged one actionable failure, local MQTT connected normally,
  startup continued after the bounded wait, and es-ESS remained stable without
  a crash loop.
- Local-broker refusal was not induced because stopping the Venus broker would
  disrupt platform MQTT consumers. Equivalent local-client refusal/recovery is
  retained in hardware-free orchestration coverage; the live run confirmed
  normal local-client isolation while the main client was unavailable.
- Starting the proxy without restarting es-ESS produced exactly one main MQTT
  connect callback in the same process, restored all SolarOverheadDistributor and
  Wattpilot subscriptions, republished `es-ESS/$SYS/Status=Online`, and resumed
  TimeToGo diagnostic publication.
- The original configuration was restored with a matching SHA-256, main/local
  MQTT each connected normally after restart, the process remained stable,
  live main-MQTT publication succeeded, the verified proxy was stopped,
  port 18884 became free, and all temporary files were removed.
- Main/local separation, TLS/authentication policy, retained status/last-will
  behavior, and orderly shutdown remain unchanged; permanent failures stay
  actionable and never fall back insecurely.

### Completed 2026-07-15 - Gate Experimental Zero-Feed-In On Confirmed Grid Connection

Completion record:

- Implemented in `48fe83a`. Commands now require an explicitly connected grid
  or shore AC input; missing, malformed, genset, off-grid, and transition states
  issue no new OpenDTU command and preserve the last nonpersistent limit so
  frequency shifting remains authoritative.
- Hardware-free confirmed-grid, second-input shore, missing, malformed,
  disconnected, transition, and recovery coverage passes together with the
  full hardware-free suite.
- No separate GX/OpenDTU/inverter staging setup is available. Production has
  `MqttPVInverter=false`; neither it nor experimental zero-feed-in will be
  enabled merely to force this test, and the production grid will not be
  disconnected.
- Closure explicitly accepts the default-disabled, fail-safe guard without
  claiming hardware-in-the-loop validation. README retains the isolated
  commissioning procedure for any site that later enables the experiment.

### Completed 2026-07-15 - Resolve Time-To-Go Ownership And Publication

Resolution:

- Official Venus `dbus-systemcalc-py` behavior establishes that systemcalc
  owns `/Dc/Battery/TimeToGo` and sources it from `/TimeToGo` on the selected
  battery service. An MQTT `N/...` topic is an outbound notification, not a
  supported write path; es-ESS owns neither D-Bus service.
- Commit `bb90d6f` removed the ineffective local notification injection and
  retained the estimate as the main-MQTT diagnostic
  `es-ESS/TimeToGoCalculator/TimeToGo`. Zero power/SOC, incomplete telemetry,
  publish failure, and charge/discharge calculations are covered without
  stopping the worker.
- README, sample configuration, and service inventory now state that GX/VRM
  time-to-go requires the selected BMS to publish `/TimeToGo`; es-ESS does not
  create a competing owner.
- Supervised validation on Venus OS `v3.75` completed with
  `TimeToGoCalculator=true`, `BatteryCapacityInWh=32000`, and
  `UpdateInterval=1000`. During natural discharge, complete D-Bus inputs
  produced a plausible time-to-go estimate consistent with changing power,
  SOC, active SOC limit, and capacity. The same supervised process remained
  healthy with increasing uptime and no recent critical error,
  traceback, or exception.

### Completed 2026-07-15 - Decide And Align Wattpilot Hibernate-Mode Remote Control

Resolution:

- Selected the conservative existing-product boundary: with
  `HibernateMode=true` and no EV connected, es-ESS intentionally disconnects;
  remote VRM mode changes are unsupported while disconnected. Scheduled is a
  best-effort status probe, not a supported keep-awake/control path.
- Commit `e3dd6c1` removed the unresolved source TODO and aligned README,
  `config.sample.ini`, the service inventory, and the HTML guide without
  adding reconnect ownership, charger commands, or Manual/Auto authority
  changes.
- Documentation-contract and full-suite tests pass. This documentation-only
  resolution required no Wattpilot hardware action and preserves Manual
  ownership, Auto/Eco authority checks, no-grid behavior, and the disabled
  default.

### Completed 2026-07-15 - Audit And Enforce Maintained Documentation Contracts

Completion record:

- Commit `e3dd6c1` corrected the singular `MqttTemperature` service flag,
  `[MqttExporter:*]` prefix, Shelly PM service flag, all four stale Wattpilot
  example values, and conflicting hibernate promises.
- README, `config.sample.ini`, `docs/system-guide.html`, and
  `docs/service-inventory.md` were audited against runtime service loading,
  including flags, section names, values, units, active/dormant status, and
  integration contracts; site-shaped examples remain explicitly examples.
- Contract tests compare the complete maintained README Wattpilot table and
  system-guide Wattpilot block against `config.sample.ini`, plus canonical
  service-specific names and the hibernate boundary. No runtime default or
  behavior changed, and rendered Markdown/HTML remained readable.

### Completed 2026-07-15 - Restrict Daily-Report D-Bus Reads To Exact Paths

Completion record:

- Commit `4b50c6a` defines an immutable allowlist containing every declared
  Wattpilot snapshot pair plus the exact Venus timezone pair.
- Arbitrary Wattpilot paths, all generic system paths, other services, writes,
  non-absolute paths, and extra arguments are rejected before subprocess use.
- Tests accept every declared pair and preserve the existing `svstat`,
  two-second timeout, circuit-breaker, command-free analyzer isolation, and
  full-suite behavior. Any future legitimate snapshot path requires an
  intentional allowlist and test update.

### Completed 2026-07-15 - Evaluate Low-Risk Lifecycle And Diagnostic-Script Hygiene

Completion record:

- Retained exact-command emergency/uninstall behavior: adding shared PID
  lifecycle machinery would increase risk without evidence of a practical
  defect. No lifecycle script changed.
- Retained private `ConfigParser._sections` access because public mapping APIs
  include inherited `[DEFAULT]` keys, but replaced private boolean conversion
  with public `getboolean()` and documented the explicit-key reason.
- Commit `4b50c6a` labels Paho/websocket checks as the Wattpilot external
  dependency subset, distinguishes missing config from unreadable/malformed
  existing config, and adds `python3` fallback to the health monitor.
- Focused static/behavioral and full-suite tests pass. Dependency checks remain
  read-only and do not import side-effectful production modules.

### Completed 2026-07-15 - Measure Daily-Report Peak Memory And Retain Complete Evidence

Completion record:

- The supported Venus OS `v3.75` GX processed a large representative APP_DEBUG
  `current.log` while es-ESS remained online.
- Peak resident memory left substantial available headroom, and the post-run
  reading recovered normally.
- Loading and analysis completed successfully. Exit code `2`
  reflected earlier operational anomalies in the complete current-day input,
  not a resource limit or report failure.
- The supervised es-ESS process remained stable with increasing uptime. The
  implementation had already passed 67 focused daily-report
  tests and the complete 415-test hardware-free suite.
- Decision: close measurement-only. Do not add line, continuation, record, or
  byte caps: the measured supported-GX workload has ample headroom, while
  arbitrary limits could silently discard the safety evidence the report is
  designed to retain. Any future measured need for bounds must report explicit
  `INCOMPLETE` status and exact truncation evidence rather than claiming
  `GOOD`.

## Backlog

Open implementation items appear here. The queue below remains authoritative
for selecting the next PR-sized task.

### Completed 2026-08-30 - P1 Integrate Shelly 3EM-63T Gen3 As The Dedicated Site-Current Source

Goal:

Use a correctly installed Shelly 3EM-63T Gen3 to provide direct, fresh
physical L1/L2/L3 current measurements at the configured site-current
measurement boundary for the mandatory Wattpilot Auto/Eco guard.

Implementation status (2026-07-21):

- Hardware-free implementation and regression coverage are complete on
  `feature/wattpilot-per-phase-site-current-guard`.
- Configuration version 15 preserves `SiteCurrentSource=VenusSystem` for
  existing and migrated installations. The new source is never selected
  automatically and never falls back silently to Venus data after selection.
- The item remains open only for installation-dependent commissioning. Do not
  select `Shelly3EMGen3` in production until the installed meter identity,
  authentication, phase order, A/B/C-to-L1/L2/L3 mapping, polling reliability,
  and fail-closed behavior have been verified from the GX device.

Problem:

The default current source reads calculated Venus system consumption currents.
Private commissioning evidence showed those values diverging materially from
the charger's direct current and power telemetry. That calculated source is
therefore not sufficiently trustworthy as the future authoritative site-
current measurement.
The existing Shelly integration cannot be substituted directly: it consumes
the Gen1 `/status`/`emeters[]` schema and registers a Venus
`com.victronenergy.grid` service at position 0, while the planned Gen3 meter
uses local RPC and must not compete with the existing Fronius grid meter.

Evidence:

- `FroniusWattpilot.py` registers the mandatory site-current subscriptions at
  `com.victronenergy.system` `/Ac/Consumption/L1/Current` through
  `/Ac/Consumption/L3/Current`.
- `Shelly3EMGrid.py` requests `http://<host>/status`, expects
  `total_power` and `emeters[]`, and publishes as
  `com.victronenergy.grid` with `/Position=0`.
- The official Shelly Gen3 API documents the `triphase` profile with `em:0`
  and `emdata:0`. `EM.GetStatus?id=0` exposes direct `a_current`, `b_current`,
  and `c_current` plus phase errors; `EMData.GetStatus?id=0` exposes per-phase
  forward and returned active-energy counters in Wh.
- The official device specifications rate the integrated phase-current
  measurements at 0-63 A, with +/-1% current accuracy from 2-63 A. This is a
  measurement input for software load management, not a replacement for the
  site's physical overcurrent protective device.

Implemented:

- Added a generic, command-free site-current provider contract with separate
  Venus-system and Shelly Gen3 implementations. The Shelly provider is private
  to Wattpilot and never registers a `com.victronenergy.grid` service, so the
  Fronius Smart Meter and grid-setpoint ownership remain unchanged.
- Added a bounded local Gen3 RPC client. It validates `/shelly` identity as the
  expected Gen3 `S3EM-003CXCEU63` in `triphase` profile, supports HTTP digest
  authentication with user `admin`, and polls `EM.GetStatus?id=0` for the live
  A/B/C currents used by the guard. Credentials and response bodies are not
  included in diagnostics.
- Added explicit, validated source selection and A/B/C phase mapping. Existing
  and migrated configurations remain on `VenusSystem`; selecting
  `Shelly3EMGen3` requires a complete `[Shelly3EMSiteCurrent]` section.
- Required all three Shelly currents to be finite, non-negative, and free of
  component/phase errors before updating their shared successful-poll
  timestamp. A failed poll invalidates all phases while preserving their age;
  it cannot refresh from cached Venus D-Bus values or fall back to Venus.
- Reused the existing mandatory current guard without overload grace. Missing,
  invalid, error-marked, stale, or unreachable selected-source data blocks or
  stops Auto/Eco; recovery retains the existing stable delay and 1 A-per-cycle
  ramp. Manual behavior and every other charging safety boundary are unchanged.
- Published source name, connection, state, sanitized error, device model,
  firmware, and last-sample age through Wattpilot D-Bus diagnostics and the
  maintained MQTT/runtime reporting, health-monitor, and daily-report paths.
- Deliberately left energy-counter polling outside the safety-source runtime.
  `EMData.GetStatus?id=0` remains a read-only commissioning/reporting capture,
  not an input to instantaneous current protection.

Files to change:

- `FroniusWattpilot.py`
- `es-ESS.py`
- `config.sample.ini`
- `README.md`
- `docs/wattpilot-architecture.md`
- `docs/service-inventory.md`
- `docs/system-guide.html`
- `scripts/es-ess-health-monitor.sh`
- `scripts/es-ess-daily-report.py`
- `tests/test_wattpilot_site_current_guard.py`
- `tests/test_config_contract.py`
- `tests/test_config_migration.py`
- `BACKLOG.md`

Files to add:

- `Shelly3EMGen3Client.py`
- `Shelly3EMSiteCurrent.py`
- `WattpilotSiteCurrentSource.py`
- `tests/test_shelly3em_gen3_client.py`
- `tests/test_shelly3em_site_current.py`

Tests:

- Added hardware-free Gen3 RPC tests for unauthenticated and digest-authenticated
  access, exact `triphase` current mapping, timeout, malformed/non-finite/
  negative values, missing phase fields, phase and device errors, wrong model/
  generation/profile, recovery, host validation, and secret-safe errors.
- Added source-provider tests proving only complete successful polls update the
  sample timestamp, repeated identical zero/nonzero values remain fresh, an
  HTTP outage cannot be hidden by cached D-Bus values, and failure publishes a
  disconnected/invalid source state without registering a competing grid
  meter.
- Extended site-current guard tests for explicit source selection, A/B/C phase
  mapping, one- and three-phase headroom, stale/invalid/error fail-closed
  behavior, recovery delay/ramp, and configuration migration preserving the
  current source by default.
- Existing characterization tests continue proving Manual mode issues no command and the
  Shelly source cannot change grid-meter selection, grid-setpoint ownership,
  no-grid policy, battery assist, or command authority.
- All new test files remain compatible with `python -m unittest discover -s
  tests`; no CI workflow change was required.

Expected coverage:

- Proves the mandatory Auto/Eco guard uses direct phase currents from the
  configured site-current measurement boundary only after explicit
  commissioning and never silently falls back to a stale or calculated source.
- Proves Shelly loss, invalid data, wrong profile, phase errors, and
  authentication failures stop or block Auto/Eco safely while Manual remains
  user-controlled.
- Proves enabling the dedicated source does not create a second Venus grid
  meter or alter the existing Fronius/system energy topology.
- Existing site-current, phase-switching, no-grid, battery-assist, command-
  boundary, configuration, and reporting tests remain passing.

Manual validation:

Hardware installation and fault simulation in a low-risk window, followed by
active charging only after read-only commissioning succeeds. Installation and
phase identification must be performed or verified by the electrician; do not
create an overload to test the guard.

Manual test steps:

1. After installation, reserve the Shelly IP address and capture `/shelly`,
   `EM.GetStatus?id=0`, and `EMData.GetStatus?id=0` locally from the GX without
   enabling the new es-ESS source.
2. Confirm the device is the expected Gen3 model in `triphase` profile, record
   firmware/authentication state, and verify no reported phase/device error.
3. With the electrician, correlate Shelly A/B/C with physical site L1/L2/L3
   using normal safe loads; confirm current direction and compare readings
   against an independent clamp meter where available.
4. Deploy the implementation with the old source still selected and confirm
   the Fronius service remains the sole Venus grid meter.
5. Select the Shelly site-current source, restart es-ESS, and confirm fresh
   phase currents, ages, limiting phase, allowed current, connection state,
   and no critical/traceback/command-boundary errors while the car is stopped.
6. During a normal supervised Auto/Eco PV charge, confirm one-phase mapping,
   equal three-phase commands, natural house-load current reduction, and
   delayed/ramped recovery. Do not deliberately exceed the configured
   per-phase `SiteMaxCurrent`.
7. In a low-risk window, briefly isolate only Shelly network access and confirm
   Auto/Eco fails closed within the documented freshness bound while the
   site's physical overcurrent protection remains the final protection.
   Restore access and confirm recovery follows the existing delay/ramp.
8. Return to Manual and confirm es-ESS remains observation-only.

Risks and dependencies:

- Production activation is blocked until the Shelly 3EM-63T Gen3 is physically
  installed at the configured site-current measurement boundary and its live
  API/phase-mapping evidence is supplied. Implementation and deployment with
  the default `VenusSystem` selection are not blocked.
- Wi-Fi, digest-authentication compatibility on Venus OS `v3.75`, device
  firmware behavior, response cadence, and actual measurement latency require
  live validation; no API claim alone establishes breaker-protection timing.
- Incorrect conductor placement, phase mapping, voltage-reference pairing, or
  profile selection could produce plausible but unsafe headroom calculations.
- Registering the source as `com.victronenergy.grid` could compete with the
  Fronius meter and corrupt system topology; the implementation must retain a
  dedicated non-grid source boundary.
- The Shelly and es-ESS remain monitoring/load-management layers. Neither
  replaces the site's physical overcurrent protection or electrician-approved
  wiring.
- The separate charging-session reporting item may consume Shelly energy
  diagnostics later, but it is not a prerequisite for this safety source and
  must not expand this task into energy reconciliation.

Open questions:

- Exact Shelly model identifier, firmware version, authentication state, local
  IP, `triphase` profile response, and A/B/C-to-L1/L2/L3 mapping remain pending
  until installation.
- Confirm from the installed device whether one-second polling is reliable on
  the production Wi-Fi network and whether the supported GX `requests` build
  completes SHA-256 digest authentication within the required timeout.

Done criteria:

- Installation/API/phase-mapping evidence is retained and matches the expected
  Gen3 `triphase` contract.
- The dedicated source supplies direct, fresh, validated phase currents from
  the configured site-current measurement boundary without appearing as a
  second Venus grid meter.
- Auto/Eco fails closed on source loss, invalid values, meter errors, wrong
  profile, authentication failure, and stale samples; recovery retains the
  existing stable delay and ramp.
- Normal supervised charging confirms correct physical phase mapping and safe
  current limiting without intentionally overloading the site.
- Manual mode remains observation-only and the existing Fronius grid meter,
  no-grid policy, battery-assist bounds, phase behavior, and command ownership
  remain unchanged.
- README, sample configuration, architecture, service inventory, system guide,
  health monitor, daily report, and backlog document the source and its limits.
- Changed Python files pass syntax checks; focused Shelly, site-current,
  configuration, and reporting tests pass.
- Full unittest suite passes.

### Completed 2026-08-30 - Optional / Gated Define Wattpilot Fallback For Explicitly Signalled Maintenance Bypass

Goal:

For a target installation that has a maintenance bypass and an explicit,
validated indication of its state, establish an opt-in operating contract for
the Wattpilot without causing unintended grid charging or violating Manual-mode
ownership. Do not enable this work for installations without that evidence and
an approved fallback definition.

Problem:

Some installations route normal power through Victron inverter/chargers and
provide an interlocked maintenance bypass to a site-side bus. Depending on the
wiring, the Wattpilot may remain powered while the Cerbo GX loses power or
remains alive with telemetry that no longer represents the active AC path.
Downstream EV protection is installation-specific; a 16 A EV branch is only an
example. The current runtime has no bypass-switch input or controller-loss
fallback contract.

`FroniusWattpilot.handleSigterm()` sends Force Off only during a graceful Auto
shutdown and then disconnects. An abrupt GX power loss cannot execute that
path, release phase/current constraints, select a Wattpilot mode, or prove what
the charger does after its WebSocket controller disappears. Automatically
selecting Manual/Standard without evidence could also start grid charging when
the operator expected a stopped EV. "Return to normal usage" therefore needs a
precise, hardware-validated definition before code changes.

Evidence:

- `FroniusWattpilot.py` `handleSigterm()` sends `frc=Off` only when the client
  is connected and the controller is in Auto, then disables reconnect and
  disconnects. It does not release `psm`/`amp` constraints or select Manual.
- `Wattpilot.py` command helpers send `amp`, `frc`, `psm`, and `lmo` only while
  the process is running; no local daemon can act after Cerbo power is lost.
- `FroniusWattpilot.py` permits a one-time phase/current release only after an
  observed or requested Auto-to-Manual transition. That approved exception is
  not a generic controller-loss policy.
- `es-ESS.py` invokes service cleanup on SIGTERM/SIGINT, but sudden power loss
  bypasses the complete shutdown sequence.
- `config.sample.ini`, `README.md`, `docs/wattpilot-architecture.md`,
  `docs/service-inventory.md`, and `docs/system-guide.html` describe an example
  topology, installation-dependent downstream protection, and the absence of a
  validated automatic fallback.
- No active service subscribes to a bypass auxiliary contact or publishes a
  bypass state through D-Bus or MQTT.

Implementation:

- For each target installation, first retain an electrician-verified one-line
  drawing and identify whether the bypass switch has an isolated auxiliary
  contact, whether Cerbo remains powered from DC in bypass, and which
  grid/site/battery telemetry stays valid in each switch position.
- With the vehicle disconnected, characterize Wattpilot firmware `42.5`
  behavior after WebSocket loss, Cerbo loss, graceful es-ESS shutdown,
  Wattpilot power cycle, and later controller reconnection. Record retained
  `lmo`, `frc`, `psm`, and `amp` state without assuming a native watchdog.
- Define the operator-approved fallback explicitly: for example remain Off,
  restore the pre-Auto Manual/Standard state, or require an app action. Specify
  whether a connected vehicle may start from grid and how the installation's
  EV branch limit remains physically enforced.
- Prefer a deterministic physical bypass indication if automatic behavior is
  required while GX remains powered. Do not infer bypass from MQTT loss,
  Wattpilot WebSocket loss, stale D-Bus telemetry, or a generic Victron service
  outage.
- If bypass removes GX power, select a mechanism that can operate without
  es-ESS: a documented pre-bypass procedure, a validated Wattpilot-native
  setting/watchdog, or an electrician-approved external interlock. Do not claim
  that Python shutdown code can handle loss of its own power.
- Only after the evidence and product decision are approved, implement the
  smallest one-time state transition behind the existing firmware and command
  boundaries. Preserve ordinary Manual observation-only behavior, the current
  Auto/Eco no-grid policy, continuation-only battery assist, transactional
  starts, and the prohibition on generic shared cable/current-limiting logic.
- Publish an explicit bypass/fallback state and actionable reason if runtime
  detection is implemented. Update monitoring and daily reporting without
  adding another command owner.

Files to change:

- `FroniusWattpilot.py`
- `Wattpilot.py` only if a validated charger-side fallback command is required
- `WattpilotControlState.py` only if a live, explicit bypass input becomes a
  controller state
- `WattpilotRuntimeStatus.py`
- `es-ESS.py` only if an explicit bypass input/lifecycle boundary is added
- `config.sample.ini`
- `README.md`
- `docs/wattpilot-architecture.md`
- `docs/service-inventory.md`
- `docs/system-guide.html`
- `scripts/es-ess-health-monitor.sh`
- `scripts/es-ess-daily-report.py`
- `tests/test_wattpilot_command_boundary.py`
- `tests/test_wattpilot_runtime_status.py`
- `tests/test_config_contract.py` and `tests/test_config_migration.py` if a
  setting is added
- `BACKLOG.md`

Files to add:

- `tests/test_wattpilot_bypass_fallback.py` if the approved behavior is large
  enough to justify an isolated hardware-free contract test.

Tests:

- Characterize the existing graceful Auto shutdown as Force Off followed by
  disconnect, and prove Manual shutdown remains command-free.
- Prove missing or ambiguous bypass evidence cannot select Manual, start,
  phase-switch, increase current, or widen command authority.
- If an explicit live bypass input is approved, cover transition entry,
  one-time fallback, repeated samples, process restart while already bypassed,
  return to normal topology, input loss, and command rejection.
- Prove the approved fallback cannot be triggered by only MQTT loss,
  Wattpilot transport loss, stale site/grid telemetry, or a generic Victron
  D-Bus outage.
- Prove a release-to-Manual design, if explicitly approved, restores only the
  validated phase/current constraints and does not issue Start/Stop as part of
  normal Manual operation.
- Follow the existing hardware-free stub patterns in `tests/test.py` and
  `tests/test_eco_pv_policy.py`; no real bypass switch, charger, D-Bus, MQTT, or
  network is used in CI.

Expected coverage:

- Distinguishes graceful shutdown, abrupt controller loss, explicit live
  bypass, and ordinary telemetry/transport faults instead of treating them as
  equivalent.
- Proves any implemented fallback is one-time, firmware-guarded, observable,
  and cannot silently enable grid charging or interfere with ordinary Manual
  mode.
- Existing site-current, no-grid, phase, battery-assist, command-authority,
  shutdown, and reconnect tests remain passing.

Manual validation:

Fault simulation in a low-risk, electrician-approved window with the vehicle
disconnected. Initial evidence collection must not rely on an active charge or
force grid import. Active charging may be considered only after the exact
fallback contract passes disconnected validation and receives separate
approval.

Manual test steps:

1. Retain the electrician's one-line diagram, switch make/model and contact
   schedule; identify normal, off and bypass positions plus any auxiliary
   contact and neutral switching.
2. With no vehicle connected, record Cerbo power, Victron services, Fronius
   grid/PV visibility, site-current source, MQTT and network availability in
   normal, off and bypass positions. Do not operate the switch unless the
   installer confirms the procedure and load conditions.
3. Separately capture Wattpilot `lmo`, `frc`, `psm`, `amp`, connection state
   and app-visible mode before and after graceful es-ESS shutdown and isolated
   controller/network loss. Do not change native settings during capture.
4. Confirm the desired standalone result in writing, including whether the EV
   must remain stopped or may charge from grid and which user/app action owns
   the transition.
5. After implementation, repeat the disconnected transitions and verify one
   fallback action, truthful runtime status, no command loop, no stale Auto
   limit, and correct recovery when normal topology returns.
6. Perform any later connected/charging check only under a separately approved
   supervised procedure; do not use maintenance bypass merely to exercise a
   software branch.

Risks and dependencies:

- If bypass removes GX power, es-ESS cannot guarantee a final network command;
  the solution must be procedural, charger-native, or externally interlocked.
- Automatically selecting Manual/Standard may permit immediate grid charging
  and conflicts with the established Manual ownership boundary unless the
  operator explicitly approves the transition semantics.
- A bypass auxiliary contact, GX digital input, D-Bus path, or external relay
  interface is installation-specific and must be electrically isolated and
  commissioned by the installer.
- Incorrect switch-state detection could disable PV-only protection or create
  a second command owner. Generic telemetry loss must continue to use existing
  fail-closed paths.
- Wattpilot firmware behavior after controller loss or power cycling is not
  established by the repository and requires direct evidence on firmware
  `42.5`.

Open questions:

- Does the Cerbo GX remain powered from the batteries in normal, off and bypass
  positions, and do its D-Bus/MQTT services remain operational?
- Does the bypass provide a safe auxiliary contact that can be read by the GX?
- What exact state means "normal usage": remain stopped, restore the prior
  Manual/Standard state, or allow immediate standalone grid charging?
- Which `lmo`, `frc`, `psm`, and `amp` values does Wattpilot firmware `42.5`
  retain after WebSocket loss, GX loss, charger power loss and reconnection?
- Is the Fronius AC PV inverter on the maintained load-side bus in every switch
  position, and what monitoring/control remains available while bypassed?

Done criteria:

- The target installation's power, control, protective-device, and bypass
  contact topology is retained and electrician-verified before the optional
  integration is enabled.
- GX availability and Wattpilot firmware behavior are characterized for every
  relevant transition without an active vehicle.
- The operator explicitly approves the standalone fallback and grid-charging
  semantics.
- Any runtime implementation uses explicit evidence, remains one-time and
  observable, and cannot be triggered by generic telemetry or network loss.
- Abrupt GX loss has an honest non-Python fallback or a documented limitation;
  no shutdown guarantee depends on code running after its power is removed.
- Manual ownership, Auto/Eco no-grid behavior, battery-assist bounds,
  site-current protection, command authority and public contracts are
  preserved or intentionally updated with matching documentation and tests.
- Changed Python files pass syntax checks; focused fallback, shutdown,
  configuration and reporting tests pass.
- Full unittest suite passes.

### Completed 2026-08-30 - P2 Add Read-Only Pre-Flight Configuration Validator

Goal:

Give operators a standalone, read-only way to validate the deployed
`/data/es-ESS/config.ini` before restarting the production service.

Problem:

Startup validation in `es-ESS.py` correctly fails closed on unreadable,
malformed, incompatible, or out-of-range configuration, but the operator only
gets that verdict during service startup. A production restart can therefore
be spent discovering a typo, missing mandatory key, unsupported version, weak
permissions, or invalid threshold that could have been detected beforehand.

Evidence:

- `es-ESS.py` `_validateConfiguration()` reads `config.ini`, enforces owner-only
  permissions, verifies `[Common] ConfigVersion`, applies migrations, writes
  migrated configuration, and then calls `_validateConfigValues()`.
- `es-ESS.py` `_validateConfigValues()` contains the authoritative range and
  consistency checks for Wattpilot, site-current, MQTT TLS, logging, grid
  setpoint, and service-specific values.
- `tests/test_config_migration.py` proves startup validation can create backup
  files, rewrite `config.ini`, and change permissions. A pre-flight validator
  must not reuse that path blindly if the promised behavior is read-only.
- `README.md` documents that install and startup reassert `0600` permissions
  and that invalid configuration exits with an operator-visible diagnostic.

Implementation:

- Add a `scripts/validate-config.py` CLI that defaults to
  `/data/es-ESS/config.ini` and accepts `--config PATH`.
- Extract or wrap the existing configuration checks so read-only validation can
  parse the file, verify mandatory `[Common] ConfigVersion`, reject unsupported
  future versions, report stale versions that would require migration at
  startup, check exact file permissions, and run the same value-range checks
  without creating backups, modifying contents, or changing file mode.
- Distinguish errors from warnings. Treat parse failure, missing mandatory
  sections/options, unsupported versions, unsafe permissions, and invalid
  values as nonzero exit results. Treat known legacy ignored settings and
  migration-needed old versions as warnings unless an explicit strict mode is
  added.
- Do not add service initialization, MQTT, D-Bus, Wattpilot WebSocket access,
  file writes, chmod, or migration side effects to the validator. Startup
  remains the only path that mutates a legacy configuration.
- If unknown-key detection is added, make it opt-in or warning-only at first so
  existing operator compatibility keys are not rejected without a migration
  decision.

Files to change:

- `es-ESS.py`
- `README.md`
- `docs/service-inventory.md`
- `docs/system-guide.html`
- `BACKLOG.md`

Files to add:

- `scripts/validate-config.py`
- `tests/test_validate_config.py`

Tests:

- Add hardware-free tests for valid current configuration, missing file,
  unreadable or malformed file, missing `[Common]`, missing or non-integer
  `ConfigVersion`, unsupported future version, legacy version warning,
  permission mismatch, and representative invalid values from each active
  validation group.
- Prove the validator does not create `config.ini.v*.backup`, does not rewrite
  the file, and does not chmod the file while reporting permission failures.
- Add CLI exit-code tests for pass, warning-only, validation failure, and input
  error.
- Reuse the existing hardware-free module-stub pattern from
  `tests/test_config_migration.py`; no D-Bus, MQTT, Wattpilot, or network is
  used.

Expected coverage:

- Operators can validate a production candidate config before restart without
  changing it.
- The pre-flight verdict uses the same maintained range rules as startup for
  active settings.
- Existing startup migration, permission tightening, fail-closed errors, and
  service initialization behavior remain unchanged.

Manual validation:

Log-only. On the GX device, run the validator against a copied production
configuration and then against the live `/data/es-ESS/config.ini` before a
normal restart.

Manual test steps:

1. Run `python3 scripts/validate-config.py --config /data/es-ESS/config.ini`
   on the GX device and confirm a valid config reports success without
   modifying file timestamp, contents, backups, or mode.
2. Temporarily validate a copied config with a known bad value and confirm the
   script exits nonzero with the same field-level diagnostic class as startup.
3. Confirm `restart.sh` still performs the authoritative startup migration and
   permission behavior when a legacy config is intentionally used.

Risks and dependencies:

- Duplicating validation rules would let startup and pre-flight checks drift,
  so the implementation should share the rules or add tests that prove parity.
- Rejecting unknown keys too aggressively could break existing deployments with
  harmless compatibility leftovers.
- A read-only old-version warning is less complete than a real startup
  migration; operator messaging must make that distinction clear.
- This item has no dependency on Shelly commissioning or Wattpilot bypass work.

Open questions:

- Should the first implementation include an explicit `--strict-unknown-keys`
  mode, or leave unknown-key detection for a later documentation-contract PR?

Done criteria:

- `scripts/validate-config.py` validates current and candidate configs without
  file writes, chmod, backups, service startup, MQTT, D-Bus, or Wattpilot
  access.
- Startup and pre-flight validation share the maintained active value rules or
  have parity tests covering every supported active section.
- README and operator docs describe when to run the validator and what its exit
  statuses mean.
- Changed Python files pass syntax checks; focused validator and configuration
  tests pass.
- Full unittest suite passes.

### Completed 2026-08-30 - P3 Expand Daily-Report Regression Coverage

Goal:

Protect the read-only daily report from correctness and scalability regressions
as log formats, session records, and safety findings evolve.

Problem:

The daily report processes large APP_DEBUG logs on resource-constrained GX
hardware and correlates many evidence types. Prior work removed known
quadratic scans and measured a 210,294-line production report successfully,
but CI currently relies mainly on unit-sized synthetic cases plus focused
algorithmic checks. Future parser or regex changes could reintroduce slow
paths or break production-shaped evidence without an early signal.

Evidence:

- `scripts/es-ess-daily-report.py` is a single operational analyzer with
  marker-routed parsing, timestamp indexes, current snapshots, session schema
  4 rendering, and many literal log-message correlations.
- `tests/test_es_ess_daily_report.py` already contains focused hardware-free
  parser, coverage, snapshot, session, and large irrelevant-record checks, so
  additional regression coverage will be picked up by unittest discovery.
- `docs/es-ess-daily-report.md` documents progress output and separate
  log-loading/evidence-analysis durations to make GX performance regressions
  visible.
- Completed backlog evidence records a representative GX run with 210,294
  APP_DEBUG records and ample memory headroom.

Implementation:

- Add generated synthetic-log tests that include at least 50,000 records with a
  production-shaped mix of irrelevant APP_DEBUG lines, allowance samples,
  grid samples, current changes, session statistics, startup compatibility
  records, rare statuses, and safety interventions.
- Use a generous, CI-stable performance budget or operation-shape assertion
  rather than a brittle tight wall-clock threshold. Prefer checks that catch
  accidental repeated full-log scans, event-regex application to irrelevant
  lines, or per-session quadratic loops.
- Add replay-style fixture tests only for sanitized archived logs that contain
  no credentials, private IPs, vehicle-identifying details, or sensitive site
  information. Generated fixtures remain the default and require no production
  evidence.
- Keep the analyzer read-only, single-file, and compatible with the current
  CLI, exit codes, APP_DEBUG/full-day evidence model, and JSON schema unless a
  separate behavior-change task approves otherwise.

Files to change:

- `tests/test_es_ess_daily_report.py`
- `scripts/es-ess-daily-report.py` only if small test seams are needed
- `docs/es-ess-daily-report.md` if fixture or performance expectations become
  user-visible
- `BACKLOG.md`

Files to add:

- `tests/fixtures/daily-report/` only if sanitized archived fixtures are
  approved; none expected for generated-only coverage.

Tests:

- Add a generated 50,000+ line complete-window test proving the report finishes
  within the selected stable budget and returns the expected key findings.
- Add a regression that counts or spies on selected parsing paths to prove
  irrelevant records bypass expensive event regexes.
- Add production-shaped session-statistics and startup-compatibility sequences
  inside the large dataset so performance coverage also exercises meaningful
  evidence correlations.
- If archived fixtures are added, test only redacted/sanitized files and
  document their source and sanitization boundary in the fixture directory.

Expected coverage:

- Detects accidental quadratic scans or broad regex application before they
  reach a GX device.
- Proves large synthetic logs preserve core safety, session, and compatibility
  findings.
- Keeps old-log compatibility and existing focused daily-report tests intact.

Manual validation:

Hardware not needed for generated tests. Sanitized archived replay fixtures
require manual privacy review before being committed.

Manual test steps:

1. For generated coverage, run the focused daily-report tests locally and in CI.
2. If archived fixtures are proposed, review every fixture for secrets, private
   endpoints, vehicle identity, and site-specific sensitive data before adding
   it to the repository.
3. After implementation, optionally compare the synthetic runtime with a recent
   GX daily report duration to confirm the CI budget remains realistic.

Risks and dependencies:

- Wall-clock assertions can be flaky across CI runners; the implementation must
  favor stable budgets and algorithmic guards.
- Archived logs can leak private operational details unless sanitization is
  explicit and reviewed.
- Large generated tests can slow normal CI if they are too broad or repeated.
- This item is independent of daily-report maintainability cleanup; do not mix
  broad parser refactors into the regression-coverage PR.

Open questions:

- Are sanitized archived APP_DEBUG logs available and approved for repository
  fixtures, or should the first PR use generated synthetic logs only?

Done criteria:

- A large generated dataset exercises meaningful report paths and catches
  performance-shape regressions without flaky tight timing.
- Any archived fixtures are sanitized, documented, and explicitly approved.
- Existing daily-report behavior, CLI, exit codes, schema, and read-only
  boundary remain unchanged unless separately approved.
- Changed Python files pass syntax checks; focused daily-report tests pass.
- Full unittest suite passes.

### Completed 2026-08-30 - P3 Add Static CI Checks For Lifecycle And Diagnostic Scripts

Goal:

Extend CI so shell lifecycle scripts and standalone diagnostic utilities receive
basic static verification before changes reach `main`.

Problem:

The CI workflow currently syntax-checks Python, validates the sample
configuration contract, and runs hardware-free unit tests. It does not
statically check shell scripts, service entry scripts, or standalone diagnostic
script style. Unquoted variables, non-portable shell constructs, accidental
syntax regressions, or script-only Python lint issues can therefore escape the
current automated gate.

Evidence:

- `.github/workflows/ci.yml` runs `python -m compileall -q .`,
  `python -m unittest tests.test_config_contract`, and
  `python -m unittest discover -s tests`.
- Lifecycle and diagnostic shell files include `install.sh`, `restart.sh`,
  `kill_me.sh`, `uninstall.sh`, `service/run`, and
  `scripts/es-ess-health-monitor.sh`.
- Standalone Python utilities include `scripts/es-ess-daily-report.py` and
  `scripts/wattpilot-setting-capture.py`; compileall already checks syntax but
  does not enforce lint/style contracts.
- Completed backlog work hardened lifecycle scripts, but CI does not yet encode
  a static shell check.

Implementation:

- Add `shellcheck` to CI for maintained shell scripts and `service/run`, using
  targeted exclusions only when the script's Venus OS `/bin/sh` compatibility
  or service-supervisor context requires them.
- Add a narrow Python-script lint step only after selecting an explicit,
  low-noise tool and configuration. Scope it to standalone utilities first and
  avoid repo-wide formatting or type enforcement in this item.
- Do not enable broad `mypy` or large service-class typing checks here; keep
  type checking as a separate incremental backlog item.
- Document any intentional shellcheck exclusions inline in the CI command or a
  small config file so future contributors understand the deployment reason.

Files to change:

- `.github/workflows/ci.yml`
- `install.sh`, `restart.sh`, `kill_me.sh`, `uninstall.sh`,
  `service/run`, or `scripts/es-ess-health-monitor.sh` only if static checks
  expose real script issues
- `BACKLOG.md`

Files to add:

- Optional lint configuration only if needed, such as a minimal Python linter
  config. None expected for shellcheck-only implementation.

Tests:

- Add CI steps that run shellcheck over every maintained shell/service script.
- If Python linting is included, add a command that targets only standalone
  scripts and is stable on Python 3.12.
- Run existing lifecycle/static tests if any script changes are required.
- Confirm unittest discovery remains unchanged and existing hardware-free tests
  still run.

Expected coverage:

- Shell syntax, quoting, and common portability issues are caught automatically.
- Standalone Python utilities retain compileall coverage and may gain targeted
  lint coverage without forcing style churn across production service modules.
- Existing CI syntax, config-contract, and unittest checks remain intact.

Manual validation:

Hardware not needed for CI-only changes. If lifecycle scripts change to satisfy
shellcheck, perform log-only validation on the GX during the next normal
deployment window.

Manual test steps:

1. Verify the GitHub Actions workflow passes on a PR containing the new checks.
2. If lifecycle scripts changed, run the normal install/restart path in a safe
   maintenance window and confirm the service starts with unchanged behavior.

Risks and dependencies:

- Shellcheck can flag patterns that are intentional for the Venus OS
  environment; suppressions must be narrow and explained.
- Adding a Python linter without a small config could create noisy style churn
  unrelated to script correctness.
- CI package installation may increase runtime modestly.
- This item is independent of the configuration validator and daily-report
  regression work.

Open questions:

- Which Python linter, if any, should be used for standalone scripts in the
  first PR, or should the first PR be shellcheck-only?

Done criteria:

- CI runs shellcheck against all maintained shell/service scripts.
- Any selected Python script linting is narrow, documented, and low-noise.
- No broad service-module formatting, type-checking, or behavior refactor is
  mixed into this PR.
- Changed scripts pass syntax/static checks; existing hardware-free tests pass.
- Full unittest suite passes.

### Completed 2026-08-30 - P4 Document Exact Configuration Section Casing

Goal:

Provide contributors and deployment authors with an exact reference for
`ConfigParser` section and instance-section casing.

Problem:

The repository intentionally preserves historical casing differences between
service flags, global sections, and instance sections. For example, the global
MQTT PV inverter section uses `[MqttPvInverter]`, while instance sections use
`MqttPVInverter:*`. Without a single table of exact names, new contributors or
deployment scripts can accidentally create sections that look correct but are
not read by the runtime.

Evidence:

- `docs/service-inventory.md` already records that some service names and
  config section casing differ and that compatibility should be preserved
  unless a migration task explicitly changes it.
- `config.sample.ini` is the maintained configuration reference and contains
  the active global and instance-section names.
- `tests/test_config_contract.py` checks that documentation references active
  configuration sections, but the service inventory currently lacks a complete
  exact-casing developer table.
- Completed backlog work retained private `ConfigParser._sections` access in
  one diagnostic path because public mapping APIs include inherited defaults,
  reinforcing that exact config parsing behavior matters.

Implementation:

- Add a developer reference table to `docs/service-inventory.md` listing each
  service flag, global section, instance-section pattern, owner module,
  active/dormant status, and exact casing.
- Use `config.sample.ini` as the source of truth. Preserve every existing
  section name and do not introduce aliases or migrations.
- Update or add documentation-contract tests if needed so the table cannot
  drift from `config.sample.ini` and active service inventory.
- Do not change runtime configuration parsing, migration behavior, service flag
  names, or existing compatibility handling.

Files to change:

- `docs/service-inventory.md`
- `tests/test_config_contract.py` if a contract assertion is added
- `BACKLOG.md`

Files to add:

- None expected.

Tests:

- Extend `tests/test_config_contract.py` only if a stable contract can compare
  the table against `config.sample.ini` without brittle prose matching.
- Otherwise run the existing documentation/config contract test and inspect the
  table manually.

Expected coverage:

- Contributors can find exact section casing in one inventory document.
- Existing deployment files and compatibility casing remain unchanged.
- Future documentation drift is either covered by tests or made easy to review.

Manual validation:

Hardware not needed. Review the table against `config.sample.ini` and existing
service initialization paths.

Manual test steps:

1. Compare every table row against `config.sample.ini`.
2. Compare service flags and active/dormant status against
   `docs/service-inventory.md` and runtime service loading.
3. Run documentation/config contract tests.

Risks and dependencies:

- A manually maintained table can drift unless the implementation adds a simple
  contract test or keeps the table tightly scoped.
- Overcorrecting casing in docs could imply a migration that is not being
  implemented.
- No dependency on hardware, Shelly commissioning, or Wattpilot control work.

Open questions:

- None.

Done criteria:

- `docs/service-inventory.md` contains an exact-casing table for maintained
  service flags, global sections, and instance-section patterns.
- The table explicitly distinguishes documentation from a runtime migration and
  preserves existing compatibility behavior.
- Config/documentation contract tests pass, or the manual table review is
  recorded if a stable automated assertion is not practical.
- Changed documentation passes existing checks.
- Full unittest suite passes.

### Completed 2026-08-30 - P4 Improve Daily-Report Parser Maintainability Without Splitting Deployment

Goal:

Make the daily report analyzer easier to navigate and modify while preserving
its single-file deployment model and operational behavior.

Problem:

`scripts/es-ess-daily-report.py` is intentionally a standalone operational
tool, but it has grown to more than 4,000 lines. The central parser contains
many repeated substring/regex extraction patterns and adjacent evidence
correlations. The current layout is workable, but future log-format changes
would be safer if the script had clearer section boundaries, small parsing
helpers, and more explicit local naming without being split into a package.

Evidence:

- `scripts/es-ess-daily-report.py` contains constants, regex definitions,
  dataclasses, configuration loading, snapshot capture, parser collection,
  validators, renderers, and CLI handling in one file for simple GX
  deployment.
- `EsEssDailyReport.collect()` already uses substring guards before regex
  searches for performance, but the long ordered method repeats extraction and
  append patterns across allowance, grid, current, assist, phase, session,
  firmware, rare-status, and failure records.
- `tests/test_es_ess_daily_report.py` has broad hardware-free coverage and
  therefore can protect a readability-only cleanup when changed in small
  batches.
- The daily report is a specialized diagnostic tool, not a reusable library;
  splitting it into modules would add deployment and support complexity.

Implementation:

- Keep `scripts/es-ess-daily-report.py` as one executable file with the current
  CLI, report flow, exit codes, evidence-based PASS/WARN/FAIL model, and JSON
  schema.
- Add clear section dividers for constants, dataclasses, regex definitions,
  configuration/snapshot helpers, parser collection, validators, rendering, and
  CLI.
- Introduce small helper functions only where they remove repeated,
  error-prone parser boilerplate, such as guarded regex extraction or typed
  conversion of matched groups.
- Improve local variable names opportunistically inside touched parser and
  validation blocks. Expand type hints around stable helper and dataclass
  boundaries.
- Centralize only durable shared log markers. Do not replace every evidence
  phrase with constants if that makes the parser harder to read next to the
  log text it recognizes.
- Treat dispatch tables as optional and small-scope only. Do not hide ordering
  or side-effect relationships in `collect()` unless tests prove the behavior
  is unchanged.

Files to change:

- `scripts/es-ess-daily-report.py`
- `tests/test_es_ess_daily_report.py` only if helper extraction needs targeted
  characterization tests
- `BACKLOG.md`

Files to add:

- None expected.

Tests:

- Run the focused daily-report test suite before and after each cleanup batch.
- Add targeted tests only for extracted helper behavior that is not already
  covered by report-level tests.
- Confirm old-log compatibility, startup compatibility resolution, session
  schema 4, safety findings, current snapshots, and prerequisite rendering
  remain unchanged.

Expected coverage:

- Navigation and parser changes are protected by existing daily-report tests.
- Maintainers can change log parsers with less repetitive boilerplate and
  clearer domain names.
- Single-file deployment remains unchanged.

Manual validation:

Hardware not needed for the cleanup itself. Optional log-only validation may
run the report on a recent GX log after deployment to confirm identical output.

Manual test steps:

1. Run focused daily-report tests and compare output for representative
   generated logs before and after the cleanup.
2. Optionally run the analyzer against a recent private GX APP_DEBUG log and
   compare the human/JSON report with the previous version.

Risks and dependencies:

- Refactoring the parser can accidentally change event ordering or evidence
  correlation; keep PRs small and test-backed.
- Excessive constants or a broad dispatch table could reduce readability
  rather than improve it.
- This item should follow the daily-report regression-coverage item where
  practical.

Open questions:

- None.

Done criteria:

- The analyzer remains one executable file with the same CLI and deployment
  contract.
- Parser helpers, section organization, naming, and type hints improve
  maintainability without behavior or schema changes.
- Focused daily-report tests pass and any intentional output changes are
  explicitly approved in a separate behavior task.
- Changed Python files pass syntax checks.
- Full unittest suite passes.

### Completed 2026-08-30 - P5 Add Type Hints To Stable Service Boundaries Incrementally

Goal:

Improve editor support and refactoring safety by adding Python type hints to
stable service boundaries in small, behavior-preserving batches.

Problem:

Pure decision modules already use type annotations, while larger active
service classes still have many unannotated method signatures. Broadly typing
large files in one PR would create review noise and risk accidental behavior
changes, but incremental annotations at stable boundaries would improve
maintainability over time.

Evidence:

- `WattpilotSiteCurrentDecisions.py`, `WattpilotControlState.py`, and related
  pure helpers use explicit dataclasses and typed functions.
- Larger service modules such as `FroniusWattpilot.py`,
  `SolarOverheadDistributor.py`, and `NoBatToEV.py` retain many dynamic,
  unannotated methods due to their D-Bus/MQTT/runtime integration history.
- CI does not currently run a broad type checker, and the active service
  modules depend on runtime-stubbed external Venus OS libraries.

Implementation:

- Add annotations only to stable, well-understood method parameters and return
  values in small PRs. Start with helpers and service-boundary methods whose
  types are already clear from tests.
- Avoid sweeping rewrites, mass variable renames, runtime imports solely for
  typing, or annotations that require changing behavior.
- Use `typing.TYPE_CHECKING`, forward references, or local aliases where needed
  to avoid importing unavailable Venus OS dependencies at runtime.
- Keep broad `mypy` enforcement out of this item until enough annotations and
  stubs exist to make the signal useful.

Files to change:

- Candidate batches may include `FroniusWattpilot.py`,
  `SolarOverheadDistributor.py`, `NoBatToEV.py`, and adjacent tests only as
  needed.
- `BACKLOG.md`

Files to add:

- None expected.

Tests:

- Run syntax checks for changed Python files.
- Run focused tests for any touched service module.
- Run the full hardware-free unittest suite after each annotation batch.
- Add tests only when the annotation work exposes a real behavioral ambiguity
  that needs characterization.

Expected coverage:

- Type hints document stable service contracts without changing runtime
  behavior or command authority.
- Existing hardware-free tests remain the primary verifier.
- Future optional type checking can be considered from a stronger baseline.

Manual validation:

Hardware not needed. This is structural maintainability work only.

Manual test steps:

1. Review each batch for import-time compatibility on non-Venus development
   machines and Venus OS.
2. Run focused tests for touched modules and the full unittest suite.

Risks and dependencies:

- Typing dynamic integration code can accidentally introduce runtime imports or
  circular dependencies.
- Large annotation sweeps create review noise and make behavior regressions
  harder to spot.
- This item should not be mixed with Wattpilot control, safety, or config
  behavior changes.

Open questions:

- Which service boundary should be the first annotation batch after higher
  priority hardening work is complete?

Done criteria:

- Each PR annotates a narrow, stable boundary and preserves runtime behavior.
- No broad type-checker gate is introduced without a separate plan and stubs.
- Focused module tests and syntax checks pass.
- Full unittest suite passes.

### Completed 2026-08-30 - Optional / P5 Add Deterministic Wattpilot Control Scenario Runner

Goal:

Give developers a local, hardware-free way to replay synthetic Wattpilot
control scenarios and inspect the resulting timeline of allowance, site-current
headroom, control state, and command intent.

Problem:

Unit tests prove individual safety and control behaviors, but they are not an
interactive way to understand phase-switch timing, allowance-drop grace,
site-current clamping, or battery-assist boundaries over a multi-minute
scenario. A proposed fake D-Bus/MQTT broker simulator would be costly to
maintain and could create another misleading integration stack.

Evidence:

- Hardware-free tests under `tests/` already stub D-Bus, MQTT, Wattpilot, and
  Venus dependencies with `types.ModuleType`, mocks, and explicit synthetic
  inputs.
- `WattpilotControlState.py`, `WattpilotDecisionInputs.py`,
  `WattpilotSafetyDecisions.py`, `WattpilotPhaseDecisions.py`, and
  `WattpilotSiteCurrentDecisions.py` expose pure or mostly pure decision seams
  that can be replayed without real hardware.
- `FroniusWattpilot.py` remains the command side-effect owner; any developer
  tool must not issue real Wattpilot commands or publish D-Bus/MQTT writes.

Implementation:

- Add a deterministic scenario runner only if there is a concrete developer
  need after higher-priority safety, validation, and reporting work.
- Prefer a script that reads simple JSON/YAML or built-in scenarios and replays
  synthetic PV allowance, grid import, battery SOC, Wattpilot telemetry, and
  site-current samples through existing decision/control seams.
- Print or emit JSON timeline rows for selected control state, allowed current,
  phase candidate elapsed time, site-current clamp, battery-assist state, and
  proposed command intent.
- Do not run a fake D-Bus daemon, fake MQTT broker, real GLib loop, Wattpilot
  WebSocket, or any service that can command hardware.
- Clearly label output as developer simulation, not commissioning evidence or
  a substitute for supervised GX validation.

Files to change:

- Candidate script and tests only if the optional item is selected.
- `docs/wattpilot-architecture.md` if the tool exercises or documents command
  boundaries.
- `BACKLOG.md`

Files to add:

- `scripts/dev-wattpilot-scenario.py` or similar
- `tests/test_wattpilot_scenario_runner.py`
- Optional `tests/fixtures/wattpilot-scenarios/`

Tests:

- Add hardware-free tests for representative one-phase start, phase-up
  candidate, site-current clamp, allowance-drop grace, battery-assist
  continuation, telemetry stale stop, and Manual observation-only scenarios.
- Prove the runner never calls real Wattpilot command helpers, D-Bus publish,
  MQTT publish, network, or subprocesses.
- Confirm deterministic output for fixed inputs.

Expected coverage:

- Developers can inspect multi-cycle control evolution without a Cerbo GX,
  Wattpilot, D-Bus, MQTT, or live network.
- The runner remains an explanatory tool and does not expand command ownership.
- Existing unit tests remain the authoritative automated safety verifier.

Manual validation:

Hardware not needed. The tool is not commissioning evidence.

Manual test steps:

1. Run the scenario runner with bundled examples on a development machine.
2. Confirm output is deterministic and explicitly marked as simulated.
3. Confirm no network, D-Bus, MQTT, or Wattpilot process is contacted.

Risks and dependencies:

- A simulator can give false confidence if users mistake it for live validation.
- Modeling too much runtime infrastructure would become brittle and expensive.
- This optional item should not precede safety, validator, regression, or docs
  work.

- The runner is deterministic, hardware-free, command-free, and clearly scoped
  to developer understanding.
- It reuses existing decision seams rather than inventing a second controller.
- Focused runner tests pass and prove no external side effects.
- Changed Python files pass syntax checks.
- Full unittest suite passes.

### Completed 2026-08-30 - P2 Sanitize HTTP Credentials, Exception Logs, And Counter Lock In Active Shelly Services

Goal:

Prevent HTTP Basic credentials from embedding inside request URLs and leaking into log files during exception handling, protect multi-threaded counter persistence with explicit locks in Shelly3EMGrid, and ensure D-Bus telemetry arithmetic handles non-finite or missing payload values safely in active Shelly services.

Problem:

Both `Shelly3EMGrid.py` and `ShellyPMInverter.py` construct HTTP polling URLs by interpolating username and password directly into the URL string (e.g. `http://user:pass@host/...`). If a network connection error, timeout, or HTTP error occurs, Python's `requests` library stringifies the exception including the full URL with embedded credentials. Logging `w(...)` or `e(...)` with `str(ex)` writes plaintext user credentials to `current.log`. Furthermore, in `Shelly3EMGrid.py`, `queryShelly()` mutates `self.energyForwarded` and `self.energyReversed` on the polling worker thread while `persistCounters()` reads both floats on a separate 5-minute worker thread or SIGTERM handler without an explicit reentrant lock to ensure consistent snapshot pairs.

Evidence:

- `Shelly3EMGrid.py` line 145: `URL = "http://%s:%s@%s/status" % (self.shellyUsername, self.shellyPassword, self.shellyHost)` and line 224: `w(self, "Shelly 3EM request failed: {0}".format(ex))`.
- `ShellyPMInverter.py` line 125: `URL = "http://%s:%s@%s/rpc/Switch.GetStatus?id=%s" % (self.shellyUsername, self.shellyPassword, self.shellyHost, self.shellyRelay)` and line 165: `w(self.rootService, "Shelly PM ({0}) request failed: {1}".format(ex))`.
- `Shelly3EMGrid.py` lines 201-206: Unlocked mutation of `energyForwarded` / `energyReversed` during Net-metering polling; lines 258-262: Unlocked read of both counters during `persistCounters()`.
- Security & crash-class pattern checklist: Config value injection into HTTP request URLs exposing credentials in log files; missing lock in multi-threaded iteration/reads.

Implementation:

- Update `Shelly3EMGrid.py` and `ShellyPMInverter.py` to construct clean URLs without inline basic-auth user:pass pairs: `http://<host>/status` and `http://<host>/rpc/Switch.GetStatus?id=<relay>`.
- Pass credentials safely via `auth=(username, password)` (or `requests.auth.HTTPBasicAuth`) when username or password are supplied.
- Ensure exception log formatters redact any unexpected residual credentials in error strings.
- Add a `threading.RLock()` in `Shelly3EMGrid.py` around `self.energyForwarded` and `self.energyReversed` updates in `queryShelly()` and around counter snapshot reads in `persistCounters()`.
- Verify D-Bus telemetry calculations check for non-finite values before arithmetic, ensuring `publishNone()` clears `/Ac/Power` and per-phase paths on consecutive failures.

Files to change:

- `Shelly3EMGrid.py`
- `ShellyPMInverter.py`
- `tests/test_shelly3em_grid.py`
- `tests/test_shelly_pm_inverter.py`
- `BACKLOG.md`

Files to add:

- None expected.

Tests:

- Add unit test in `test_shelly3em_grid.py` proving `requests.get` is invoked with clean URLs and `auth=` parameter, exception logs redact credentials on network errors, concurrent counter persistence reads a consistent lock-protected snapshot, and `publishNone()` sets paths to `None` after failures.
- Add unit test in `test_shelly_pm_inverter.py` proving `requests.get` is invoked with clean URLs and `auth=` parameter, exception logs redact credentials on network errors, and invalid payload handling triggers `publishNone()`.

Expected coverage:

- Proves HTTP Basic Auth credentials are never included in URL strings or logged during connection failures.
- Proves multi-threaded counter persistence in `Shelly3EMGrid` reads consistent locked counter snapshots.
- Existing passing tests in `test_shelly3em_grid.py` and `test_shelly_pm_inverter.py` remain updated and passing.

Manual validation:

Hardware not needed; unit tests are the sole verifier.

Manual test steps:

1. Run `python -m unittest tests.test_shelly3em_grid tests.test_shelly_pm_inverter`.
2. Verify in test logs that mock connection errors do not expose credentials.

Risks and dependencies:

- None. Fix is localized to Shelly HTTP URL construction, exception logging, and counter thread-safety.

Open questions:

- None.

Done criteria:

- URLs are constructed without `username:password@`.
- Credentials are provided via `auth=` tuple.
- Exception logs do not contain raw embedded credentials.
- Multi-threaded counter persistence in `Shelly3EMGrid` uses `threading.RLock()`.
- Unit tests cover credential-free URLs, safe error logging, and counter lock snapshots.
- Full unittest suite passes.

### Completed 2026-08-31 - P2 Suppress Fault-Time Wattpilot Allocation And Log Shelly Poll Failure Reasons

Completion record:

- Added a controller-owned asynchronous site-current poll wrapper that
  immediately publishes a zero Wattpilot distributor request on selected-source
  failure without issuing charger commands or mutating controller timers.
- Added transition-only sanitized failure/recovery diagnostics and kept
  measured consumption and calculated raw overhead truthful.
- Positive Wattpilot demand now requires healthy fresh site-current telemetry,
  an unblocked guard, and the existing recovery interval; global distributor
  arithmetic and other consumers remain independent.
- Updated the daily report, operator/architecture/service documentation, and
  hardware-free fault/allocation regressions. Focused syntax checks and 147
  tests passed; the low-risk supervised network-isolation procedure remains in
  Outstanding Manual Validation.

Goal:

Prevent a failed selected site-current source from leaving a positive,
apparently usable Wattpilot distributor allowance, and make the exact sanitized
Shelly failure and recovery transitions visible in `current.log` without
changing the existing fail-closed charger-command boundary.

Problem:

Private diagnostic evidence showed that a grid/topology change and loss of the
selected Shelly source can precede a high distributor line. The distributor
may combine apparent feed-in, still-reported Wattpilot consumption, and battery
power into a positive raw-overhead calculation and allocation. The controller
does not turn that allowance into a positive current command: it selects the
unsafe site-current path, sends zero current, and sends Force Off. The raw-
overhead and assigned-allowance diagnostics can nevertheless be misread as a
charger increase.

After the controller detects the source failure, `reportBaseRequest()` can
still advertise a positive Wattpilot request because eligibility currently
depends on Auto mode, effective vehicle connection, charge-complete state, and
the effective current limit, but not on the mandatory site-current source
health or recovery state. This permits later distributor cycles to continue
publishing a positive allowance even though controller dispatch remains safely
blocked.

Separately, `Shelly3EMSiteCurrentSource.poll()` catches connection, device, and
payload failures and records a sanitized status/error in its snapshot without
logging the transition. The private diagnostic log consequently contains only
the generic worker-overrun warning plus the controller's combined
missing/invalid/stale/phase-uncertain message. It cannot show whether the
selected source timed out, rejected authentication, returned an invalid
payload, or reported a device error, even though the sanitized distinction is
already available in the provider snapshot.

Evidence:

- `SolarOverheadDistributor.py:461-506` treats every finite negative grid
  phase sum as feed-in and calculates `overhead = max(0, feedIn +
  assignedConsumption + batPower)`. Its `Available Overhead` message does not
  distinguish the raw calculation from a consumer allowance or Wattpilot
  command.
- `FroniusWattpilot.py:1508-1527` correctly refreshes and dispatches the
  site-current guard before normal charging control. This ordering prevented a
  positive command in the observed fault condition and must remain unchanged.
- `FroniusWattpilot.py:2103-2181` publishes the Wattpilot distributor request
  without checking selected-source health, `siteCurrentGuardBlocked`, or the
  site-current recovery timer.
- `FroniusWattpilot.py:3999-4031` proves the unsafe site-current stop sends
  zero current before Force Off and issues no phase command.
- `Shelly3EMSiteCurrent.py:43-91` converts poll failures into
  `Unavailable`/`Invalid` snapshots and returns `False`, but emits no
  transition log.
- `Shelly3EMGen3Client.py:96-105` already reduces request exceptions to a
  credential-free class name such as `Timeout`; the implementation must retain
  that sanitization and must never log the host, URL, username, password, or
  raw exception text.
- `tests/test_solar_overhead_distributor.py`,
  `tests/test_wattpilot_site_current_guard.py`, and
  `tests/test_shelly3em_site_current.py` cover the individual arithmetic,
  fail-closed controller, and provider invalidation paths, but no fault-shaped
  synthetic regression proves their allocation and diagnostic behavior
  together.

Implementation:

1. In `FroniusWattpilot.py`, wrap the selected asynchronous provider poll in a
   controller-owned method rather than registering `source.poll` directly.
   The provider remains command-free. On a failed Shelly poll, the wrapper must
   immediately publish a zero Wattpilot `Request` on the existing
   SolarOverheadDistributor request topic and record the source status/error
   transition. It must not call `set_power`, `set_start_stop`, `set_phases`, or
   dispatch controller state from the polling worker.
2. Make source failure and recovery logging transition-only. The warning must
   include the selected source, normalized status, sanitized error class/reason,
   last-success age, current reported Wattpilot consumption, raw overhead when
   available, and the explicit fact that allocation was suppressed and no
   positive charger command was authorized. Recovery must produce one INFO
   record. Repeated one-second failures must not flood the log.
3. Extend `reportBaseRequest()` so Auto/Eco publishes `Request=0` while the
   mandatory site-current source is disconnected, invalid, stale, blocked, or
   still inside `SiteCurrentRecoverySeconds`. Continue reporting measured
   `Consumption` truthfully; do not replace stale measured power with invented
   zero consumption merely to change the overhead formula. Resume a positive
   request only from the normal five-second controller cycle after fresh
   telemetry and the existing recovery policy permit it.
4. Keep the global distributor arithmetic and other consumers independent of
   Wattpilot-specific source health. In `SolarOverheadDistributor.py`, clarify
   diagnostics so `OverheadAvailable` is described as the calculated raw
   overhead, consumer `Allowance` is described as an allocation, and neither
   is described as a charger command. Preserve existing D-Bus paths, MQTT topic
   names, numeric values, atomic allocation behavior, and external-consumer
   compatibility.
5. Teach the daily report to recognize the new transition-only source-failure,
   allocation-suppression, and recovery records as site-current safety
   evidence while remaining backward compatible with historical generic
   messages.
6. Preserve Manual mode as observation-only, keep site-current dispatch ahead
   of grid/allowance/battery logic, retain zero-current-before-Force-Off order,
   and do not change phase switching, battery assist, grid-import policy,
   configuration defaults, firmware allowlists, or public runtime-status
   values.

Files to change:

- `FroniusWattpilot.py`
- `SolarOverheadDistributor.py`
- `scripts/es-ess-daily-report.py`
- `tests/test_wattpilot_site_current_guard.py`
- `tests/test_solar_overhead_distributor.py`
- `tests/test_es_ess_daily_report.py`
- `README.md`
- `docs/wattpilot-architecture.md`
- `docs/service-inventory.md`

Files to add:

- None expected.

Tests:

- Extend `tests/test_wattpilot_site_current_guard.py` with a synthetic fault-
  shaped asynchronous Shelly failure: a previously healthy, actively charging
  three-phase controller has a positive request/allowance and measured
  consumption, the provider poll returns `Unavailable`, and the poll wrapper
  publishes `Request=0` without issuing any Wattpilot command from that worker.
- Prove the next normal controller cycle sends exactly zero current then Force
  Off, sends no phase command, retains truthful measured consumption, and does
  not restore a positive request until fresh source telemetry remains safe for
  `SiteCurrentRecoverySeconds`.
- Prove source failure and recovery produce one sanitized WARNING and one INFO
  transition even across repeated failures; connection, authentication/device,
  and payload errors remain distinguishable without credentials, hostnames,
  URLs, or raw exception text.
- Extend `tests/test_solar_overhead_distributor.py` with clearly synthetic,
  non-derived feed-in, consumption, and battery inputs. Confirm the raw
  calculation can remain visible for diagnosis while a zero Wattpilot request
  receives a zero allowance and no external consumer behavior changes.
- Extend `tests/test_es_ess_daily_report.py` to recognize the new records,
  distinguish raw overhead, assigned allowance, requested amperes, and actual
  stop commands, and retain compatibility with the historical generic log
  wording.
- Use the existing hardware-free `unittest`, `Mock`, `SimpleNamespace`, and
  stub-module patterns. No real Shelly, MQTT, Wattpilot, D-Bus, or network
  access is permitted in automated tests.
- Run `python -m py_compile FroniusWattpilot.py SolarOverheadDistributor.py
  scripts/es-ess-daily-report.py`.
- Run `python -m unittest tests.test_wattpilot_site_current_guard
  tests.test_solar_overhead_distributor tests.test_es_ess_daily_report`.
- No configuration-contract or migration test change is expected because this
  item adds no setting. If implementation introduces a setting despite this
  specification, update `config.sample.ini`, README, migration validation, and
  `tests/test_config_contract.py` in the same PR.

Expected coverage:

- Proves selected-source failure withdraws Wattpilot demand quickly enough for
  the next distributor cycle and prevents a positive allowance from persisting
  while charger control is ineligible.
- Proves a race may still expose one raw pre-suppression calculation, but that
  value is explicitly diagnostic, is not a charger command, and cannot bypass
  the controller's existing fail-closed ordering.
- Proves current consumption remains truthful, other distributor consumers are
  unaffected, and recovery cannot bypass the existing continuous-safe timer.
- Proves operators and the daily report receive the exact sanitized provider
  failure class and a single recovery transition instead of only a generic
  scheduler warning.
- Existing Manual-mode, no-grid, battery-assist, phase-switching, command-
  authority, runtime-status, and atomic-allocation tests remain unchanged and
  passing.

Manual validation:

Fault simulation in a low-risk window. Use a normal supervised Auto/Eco PV
charge, but isolate only GX-to-Shelly network access. Do not open the main
breaker, create an overload, alter phase mapping, or interrupt unrelated site
telemetry to validate this item.

Manual test steps:

1. Deploy on an approved Venus OS release with Wattpilot firmware `42.5`, the
   validated native-controller settings, APP_DEBUG logging, and the
   electrician-verified Shelly source selected.
2. During a normal low-risk Auto/Eco PV charge, record the healthy Shelly
   source status, positive request/allowance, per-phase current, and charger
   setpoint.
3. Briefly block only local GX access to the Shelly for longer than
   `RequestTimeoutSeconds`; do not remove mains power or operate the breaker.
4. Confirm one sanitized source-failure WARNING identifies the failure class,
   the Wattpilot request and next allowance become zero, and the normal
   controller cycle sends zero current plus Force Off without a phase command.
   Confirm any raw-overhead value is labelled as a calculation rather than a
   command.
5. Keep the fault present for several poll intervals and confirm the warning is
   not repeated every second and no positive Wattpilot request returns.
6. Restore Shelly access and confirm exactly one recovery INFO record. Confirm
   positive allocation does not return until telemetry is fresh and the
   existing site-current recovery interval completes.
7. Run the current-day daily report and confirm it attributes the stop to the
   selected site-current source failure and does not describe the raw overhead
   as a charger power increase.

Risks and dependencies:

- Publishing MQTT from the site-current polling worker is a new concurrency
  edge. Reuse the existing thread-safe publication path and protect only the
  transition state needed to prevent duplicate records; do not move controller
  timers or Wattpilot commands into that worker.
- A distributor cycle can race ahead of the first failed-source notification,
  so one raw calculated-overhead sample may remain observable. The safety
  requirement is that it cannot become a positive charger command and does not
  persist as a usable Wattpilot allocation after failure detection.
- Zeroing reported consumption would make the energy evidence false and can
  distort the raw formula in the opposite direction; suppress only the request
  and resulting allowance.
- A global grid-topology gate must not be inferred from retained AC-input
  labels, voltage alone, a missing GX, or the private Wattpilot Shelly source.
  Such a gate would affect every consumer and requires separate authoritative
  hardware evidence if pursued.
- No prior open backlog item is a prerequisite.

Open questions:

- Whether Venus exposes an authoritative, timely grid/main-breaker state for
  a supported installation remains unproven. This does not block the scoped
  Wattpilot-request suppression and logging work; do not expand the item into a
  global distributor topology policy without supervised evidence.

Done criteria:

- A failed selected site-current poll withdraws the Wattpilot distributor
  request without issuing a charger command from the polling worker.
- No positive Wattpilot allowance persists after the failure notification and
  next distributor cycle.
- The normal controller cycle retains zero-current-before-Force-Off ordering
  and sends no phase command.
- Failure and recovery are logged once per transition with useful sanitized
  evidence and no credentials or endpoint details.
- Raw overhead, request, allowance, displayed aggregate current, per-phase
  current, and charger commands are unambiguously distinguished in logs,
  documentation, and the daily report.
- Manual mode remains command-free and every existing Wattpilot safety
  invariant remains intact.
- README, Wattpilot architecture, and service inventory describe the new
  allocation-suppression and diagnostic behavior.
- Focused syntax and unittest commands pass.
- Full unittest suite passes.

### Completed 2026-08-31 - P2 Stabilize Wattpilot Allocation-Step Conversion Across Voltage Updates

Completion record:

- Added controller-owned canonical one-/three-phase allocation steps initialized
  from the ceiling of usable live voltage, monotonic within each phase interval,
  and reset at phase/disconnect boundaries.
- The same integer step now governs Wattpilot minimum, distributor increment,
  maximum request, and allowance-to-current conversion. Higher voltage is
  applied before dispatch; partially funded amperes remain unassigned.
- Added transition-only APP_DEBUG diagnostics plus pure and controller-level
  round-trip, changing-voltage, recovery, phase-boundary, disconnect, and
  distributor-residual regressions.
- Updated operator and architecture documentation. Focused syntax,
  configuration-contract, and 187 hardware-free tests passed; supervised
  natural charging observation remains a deployment validation step.

Goal:

Prevent an allowance representing a complete number of Wattpilot amperes from
being interpreted as one ampere less after a small voltage update, while
preserving integer-ampere control, strict no-grid behavior, and the existing
site-current recovery guard.

Problem:

The Wattpilot controller publishes the SolarOverheadDistributor `StepSize` as
the rounded integer watts required for one ampere in the active phase mode.
The distributor constructs the allowance from exact multiples of that value.
When the allowance returns asynchronously, the controller converts watts back
to amperes by dividing by a newly sampled, unrounded voltage value and applying
`floor()`. A small voltage or rounding difference can therefore convert an
allowance for `N` complete steps into `N-1` amperes.

The lower target is applied immediately. Returning to `N` amperes then waits
for `SiteCurrentRecoverySeconds` and rises only one ampere per controller cycle.
If voltage movement repeatedly crosses the conversion boundary, the recovery
timer restarts and the charge can oscillate one ampere below the fully funded
target even when site-current headroom is ample. This produces avoidable export
in addition to the unavoidable residual below one whole three-phase ampere.

This is a control-quality defect, not a site-current overload or evidence of a
cloud/load event. A residual smaller than one complete Wattpilot step remains
normal because firmware `42.5` accepts whole-ampere current targets; this item
must not round up into intentional grid use merely to consume that residual.

Evidence:

- `FroniusWattpilot.py:2142-2148` samples the current one- or three-phase
  voltage and publishes `StepSize` using `int(round(stepSize))`.
- `FroniusWattpilot.py:2279-2291` returns live floating-point voltage values;
  three-phase voltage is the current sum of all three Wattpilot phase samples.
- `FroniusWattpilot.py:2356-2371` converts an assigned allowance through
  `targetCurrentForPhase()` and then applies site-current recovery.
- `WattpilotPhaseDecisions.py:65-83` independently divides the allowance by
  the supplied live voltage and applies `floor()`. It does not know which
  rounded step produced that allowance.
- `WattpilotSiteCurrentDecisions.py:93-119` immediately accepts a lower target,
  resets recovery when `target <= current`, and delays a later increase. That
  behavior is correct for a genuine reduction but amplifies a false one-step
  conversion caused by the mismatched voltage basis.
- Private supervised evidence showed allowances alternating by exactly one
  active three-phase step, a current target remaining one ampere below a fully
  allocated step count, continuously ample site-current headroom, and repeated
  recovery restarts. Exact operational timestamps, values, and topology remain
  outside the public repository.
- `tests/test_wattpilot_phase_decisions.py` covers basic current bounds but has
  no changing-voltage or allocation-round-trip case. Existing controller tests
  do not exercise an asynchronous `StepSize` publication followed by an
  allowance conversion with a slightly different voltage sample.

Implementation:

1. Add a controller-owned, per-phase-mode canonical allocation-step state. On
   first usable telemetry for a phase mode, initialize it conservatively from
   the ceiling of the relevant live voltage. While an Auto/Eco charge remains
   in that phase mode, permit the canonical step to increase when a later live
   voltage exceeds it, but do not decrease it on ordinary voltage movement.
   Reset/reinitialize it only at an explicitly tested phase-mode boundary,
   confirmed disconnect, or controller restart.
2. Use that same canonical integer watts-per-ampere value for the Wattpilot
   `Minimum`, `StepSize`, maximum distributor request, and allowance-to-current
   conversion. Do not publish a rounded value and then divide by a separately
   sampled floating-point value.
3. When live voltage raises the canonical step, apply the larger conservative
   divisor before issuing any current increase and publish the new step for the
   next distributor cycle. A stale allowance based on the smaller prior step
   may cause one safe reduction, but it must not authorize an extra ampere.
   The step must not move downward during the active phase interval and create
   repeated boundary chatter.
4. Keep the assigned allowance in watts truthful and retain whole-ampere
   Wattpilot commands. Do not add a tolerance that rounds a partially funded
   ampere upward, do not infer extra PV from grid-export screenshots, and do
   not weaken `AllowGridCharging=false`, grid-import stops, battery-assist
   limits, or physical site-current protection.
5. Preserve the existing recovery behavior for genuine target or headroom
   reductions. With a consistent allocation step, an unchanged fully funded
   target must no longer reset recovery merely because the live voltage moved
   across the old rounded conversion boundary.
6. Add transition-only APP_DEBUG diagnostics for canonical step initialization
   and upward adjustment, including phase count and old/new non-identifying
   watt values. Do not log every five-second cycle and do not include private
   endpoint, vehicle, site, or correlated telemetry details.
7. Document that strict PV-only whole-ampere charging can normally export less
   than one active-phase step, while a persistent additional full-step deficit
   indicates a control or telemetry issue. Do not introduce a new user setting
   for the internal conversion contract.
8. Preserve Manual mode as observation-only, command side effects in
   `FroniusWattpilot.py`, pure helper boundaries, phase-switch timing,
   transactional phase-current-Start ordering, public D-Bus/MQTT paths,
   compatibility allowlists, and every existing safety invariant.

Files to change:

- `FroniusWattpilot.py`
- `WattpilotPhaseDecisions.py`
- `tests/test_wattpilot_phase_decisions.py`
- `tests/test_eco_pv_policy.py`
- `tests/test_solar_overhead_distributor.py`
- `README.md`
- `docs/wattpilot-architecture.md`

Files to add:

- None expected.

Tests:

- Extend `tests/test_wattpilot_phase_decisions.py` with clearly synthetic
  one- and three-phase allocation round trips. Prove that an allowance built
  from exactly `N` canonical steps returns `N` amperes and that an allowance
  even slightly below the next complete step never rounds upward.
- Prove canonical step initialization uses a conservative ceiling, ordinary
  lower voltage samples do not reduce an active phase-mode step, and a higher
  voltage raises the step before any current-increase decision.
- Extend `tests/test_eco_pv_policy.py` with asynchronous cycles where the live
  voltage moves slightly around an integer boundary between StepSize
  publication and allowance receipt. Prove the fully funded current does not
  alternate between `N` and `N-1`, the recovery timer is not falsely reset,
  and only a genuine lower allowance or reduced site headroom causes an
  immediate reduction.
- Prove an upward canonical-step adjustment treats an allowance calculated
  with the prior smaller step conservatively, sends no increase, and recovers
  only after the distributor returns an allowance based on the new step.
- Extend `tests/test_solar_overhead_distributor.py` to prove scripted-consumer
  minimum-first and whole-step allocation remain unchanged when StepSize is a
  canonical integer, and that less than one remaining step stays unassigned
  rather than being rounded into a command.
- Prove phase changes and confirmed disconnects reinitialize the correct
  one-/three-phase step without issuing any additional command; Manual mode
  remains command-free.
- Use the existing hardware-free `unittest`, `Mock`, `SimpleNamespace`, and
  stub-module patterns. No real Wattpilot, vehicle, D-Bus, MQTT, or network is
  permitted in automated tests.
- Run `python -m py_compile FroniusWattpilot.py WattpilotPhaseDecisions.py`.
- Run `python -m unittest tests.test_wattpilot_phase_decisions
  tests.test_eco_pv_policy tests.test_solar_overhead_distributor
  tests.test_wattpilot_site_current_guard`.
- Run `python -m unittest tests.test_config_contract` because README behavior
  documentation changes, even though no configuration key is added.

Expected coverage:

- Proves distributor step publication and controller current conversion share
  one conservative watts-per-ampere contract across asynchronous cycles.
- Proves small voltage movement cannot turn a fully funded `N`-ampere allowance
  into an `N-1`-ampere command or repeatedly restart site-current recovery.
- Proves a genuine allowance/headroom reduction remains immediate and every
  later increase retains the configured delay and one-ampere-per-cycle ramp.
- Proves strict no-grid behavior leaves a sub-step residual unassigned rather
  than intentionally drawing the next ampere from grid or battery.
- Existing Manual-mode, phase-switching, battery-assist, command-authority,
  site-current, runtime-status, distributor, and firmware-compatibility tests
  remain unchanged and passing.

Manual validation:

Active charging required. Observe a normal, supervised Auto/Eco PV charge
during naturally stable production. Do not create grid import, switch loads,
alter protective limits, or operate a breaker solely to validate this item.

Manual test steps:

1. Deploy on an approved runtime and confirm healthy Wattpilot command
   authority, grid telemetry, and site-current telemetry before connecting the
   vehicle.
2. During a naturally stable three-phase charge, observe allowance, canonical
   step diagnostics, per-phase measured current, aggregate setpoint,
   site-allowed current, recovery elapsed time, and grid exchange for several
   minutes.
3. Confirm an allowance containing `N` complete canonical steps reaches `N`
   amperes after any legitimate recovery delay and does not alternate to
   `N-1` solely because phase voltage changes slightly.
4. Confirm canonical step changes are transition-only and upward during the
   active phase interval. A higher step must not cause a current increase from
   an allowance produced with the previous lower step.
5. Confirm remaining export is smaller than one complete active-phase step
   when no other consumer or battery reservation can use it. Do not require
   the controller to round up when doing so would intentionally import grid
   power.
6. Allow only natural PV/load movement to exercise a genuine lower target.
   Confirm reduction remains immediate and recovery retains the configured
   continuous-safe delay and one-ampere-per-cycle ramp.
7. Return to Manual and disconnect normally; confirm no new Manual command path
   and correct one-/three-phase step reinitialization on a later Auto session.

Risks and dependencies:

- A canonical step that can decrease during an active phase interval may
  recreate the oscillation. Keep it monotonic until an explicit reset boundary.
- A canonical step that does not rise before dispatch when voltage rises can
  overstate funded current. Apply upward adjustments conservatively before
  current increases and let the next distributor cycle provide new allowance.
- Changing generic distributor arithmetic or allowance topics would affect
  every consumer. Keep this item inside the Wattpilot step contract and retain
  existing SolarOverheadDistributor allocation semantics.
- Do not solve the residual below one whole ampere by weakening no-grid policy,
  using battery assist outside its continuation bounds, or adding fractional
  current commands unsupported by the validated Wattpilot contract.
- The P3 duplicate-command suppression item is complementary but not a
  prerequisite. This allocation fix should land first so deduplication tests
  observe the corrected stable target.

Open questions:

- None. The implementation must remain conservative if live voltage rises;
  supervised validation determines whether transition diagnostics need further
  tuning without changing the no-grid contract.

Done criteria:

- One canonical conservative watts-per-ampere value governs Wattpilot minimum,
  step, maximum request, and target-current conversion for each active phase
  interval.
- A complete `N`-step allowance cannot become `N-1` solely from rounding or a
  later voltage sample.
- A later higher voltage raises the canonical step before any increase and
  cannot authorize current from a stale lower-step allowance.
- Genuine reductions remain immediate; increases retain the configured delay
  and one-ampere-per-cycle ramp.
- Residual export below one complete step remains truthful and no partial step
  is rounded into intentional grid use.
- Manual mode and every existing Wattpilot safety invariant remain intact.
- README and Wattpilot architecture document the canonical-step and residual-
  export behavior.
- Focused syntax, configuration-contract, and unittest commands pass.
- Full unittest suite passes.

### Completed 2026-08-31 - P3 Suppress Duplicate Wattpilot Current-Setpoint Commands

Completion record:

- Added one controller-owned positive-current helper that returns independent
  accepted/dispatched results. A connected, explicitly timestamped matching
  Wattpilot `amp` value is a no-op only after the normal final guard accepts it.
- Added Wattpilot `amp` receipt timestamps that reset across transport
  disconnect/reconnect boundaries. Missing, malformed, reset, or different
  telemetry dispatches normally; zero-current commands are never suppressed.
- Routed every Auto/Eco positive-current call site through the helper, retained
  transactional start ordering, and limited INFO adjustment records to actual
  dispatches while keeping one transition-scoped APP_DEBUG no-op diagnostic.
- Added stable-cycle, reduction, zero, command-boundary, reconnect-timestamp,
  and accepted/rejected start-transaction regressions. Syntax checks, 189
  focused/configuration/legacy tests, and the complete 597-test suite passed;
  normal supervised charging remains the firmware no-keepalive validation gate.

Goal:

Avoid retransmitting an unchanged positive Wattpilot current setpoint on every
five-second controller cycle while preserving every existing command guard,
safety reduction, and transactional start invariant.

Problem:

The normal Auto/Eco current-adjustment branch logs an adjustment and calls
`set_power(targetAmps)` on every eligible controller cycle, even when fresh
Wattpilot telemetry already reports the same `amp` setpoint. The transport then
sends another `setValue amp=<target>` request because it has no unchanged-value
suppression. During a stable charge this can produce one redundant WebSocket
write and one misleading INFO adjustment record approximately every five
seconds.

This is a transport-efficiency and diagnostic-quality issue, not evidence that
the EV draws a new current step on every cycle. The Wattpilot treats `amp` as
its requested current limit; the vehicle chooses its actual draw up to the
advertised limit. Repeating the same limit is not known to have caused a
charging or protective-device fault.

Evidence:

- `FroniusWattpilot.py:666-671` registers `_update()` at a 5000 ms interval.
- `FroniusWattpilot.py:4229-4242` calculates the target, emits `Adjusting charge
  current`, and unconditionally calls `self.wattpilot.set_power(targetAmps)` on
  the no-phase-change path.
- `Wattpilot.py:514-515` maps every `set_power()` call directly to
  `send_update("amp", power)`.
- `Wattpilot.py:531-560` runs the common guard and then constructs and sends a
  new `setValue` request without comparing the requested value with the latest
  reported `amp` value.
- `FroniusWattpilot.py:1391-1409` recognizes an unchanged current only to avoid
  resetting site-current recovery state. It still authorizes and transmits the
  repeated command.
- Existing current-policy and command-boundary tests assert individual command
  calls, but no two-cycle regression proves that an unchanged confirmed
  positive setpoint is accepted without another transport write.

Implementation:

1. Introduce one controller-owned current-command helper used by every
   Auto/Eco positive-current call site. It must distinguish `accepted` from
   `dispatched`: a safely accepted unchanged setpoint is a no-op, while a
   changed setpoint is sent through the existing `Wattpilot.set_power()` common
   command boundary.
2. Before suppressing a repeated positive target, require finite current
   telemetry confirming that Wattpilot currently reports exactly that `amp`
   value. Missing, malformed, or different telemetry must send the command.
   Do not suppress zero-current commands, Force Off, phase commands, mode
   commands, or any changed current value.
3. Run the same firmware, command-authority, mode, and fresh site-current
   command guard even for a proposed no-op. If the guard rejects the target,
   return rejection rather than treating equality as authorization. Do not let
   deduplication become a bypass around newly reduced physical headroom.
4. Return accepted success for a guarded no-op so the existing phase-current-
   Start transaction can proceed when the inactive Wattpilot already holds the
   requested current. A rejected target must still prevent every later stage.
5. Emit the existing INFO adjustment record only when a current command is
   actually dispatched. Keep any unchanged-target diagnostic at APP_DEBUG or
   lower and rate-limit or transition-scope it so stable charging does not
   replace WebSocket spam with log spam.
6. Preserve the five-second safety evaluation cadence, immediate reductions,
   one-amp-per-cycle site-current recovery, Manual observation-only behavior,
   no-grid policy, battery-assist bounds, phase-switch timing, public D-Bus/MQTT
   contracts, configuration defaults, and firmware allowlists.

Files to change:

- `FroniusWattpilot.py`
- `tests/test_eco_pv_policy.py`
- `tests/test_wattpilot_command_boundary.py`
- `README.md`
- `docs/wattpilot-architecture.md`

Files to add:

- None expected.

Tests:

- Extend `tests/test_eco_pv_policy.py` with two consecutive stable three-phase
  cycles whose calculated target and confirmed Wattpilot `amp` are equal.
  Prove the first required change is sent once and the next unchanged target
  produces no second transport call or repeated INFO adjustment record.
- Prove a changed target, an immediate reduction, and zero-current stop are
  never suppressed.
- Extend `tests/test_wattpilot_command_boundary.py` to prove an unchanged
  positive target still executes the final command guard and is rejected when
  current site headroom no longer permits it.
- Prove an accepted no-op in a stopped phase-current-Start sequence permits the
  following Start command, while a rejected no-op prevents Start.
- Prove missing, malformed, or stale `amp` telemetry does not suppress the
  command, and Manual mode gains no new command path.
- Use the existing hardware-free `unittest`, `Mock`, `SimpleNamespace`, and
  stub-module patterns. No real Wattpilot, vehicle, D-Bus, MQTT, or network is
  permitted in automated tests.
- Run `python -m py_compile FroniusWattpilot.py Wattpilot.py` if the transport
  file is touched; otherwise syntax-check `FroniusWattpilot.py`.
- Run `python -m unittest tests.test_eco_pv_policy
  tests.test_wattpilot_command_boundary tests.test_wattpilot_site_current_guard`.
- No configuration-contract or migration change is expected because this item
  adds no setting.

Expected coverage:

- Proves stable Auto/Eco charging does not retransmit the same confirmed
  positive current setpoint every five seconds.
- Proves all controller safety checks continue to run at the existing cadence
  and an unchanged value cannot bypass reduced site headroom.
- Proves current reductions, stops, phase transitions, and transactional starts
  retain their existing command ordering and acceptance semantics.
- Existing Manual-mode, no-grid, battery-assist, phase-switching, site-current,
  command-authority, runtime-status, and firmware-compatibility tests remain
  unchanged and passing.

Manual validation:

Active charging required. Observe only a normal, supervised Auto/Eco PV charge;
do not induce overload, grid import, telemetry loss, or a protective-device
trip solely to validate command deduplication.

Manual test steps:

1. Start a normal Auto/Eco charge on an approved runtime with healthy command
   authority and site-current telemetry.
2. Allow PV and the calculated current target to remain stable for several
   five-second cycles. Confirm one actual target change produces one adjustment
   INFO record and stable later cycles do not repeat that record or the
   corresponding outbound `amp` command.
3. Let a natural PV change produce a different target and confirm the changed
   current command is dispatched promptly and the Wattpilot reports the new
   `amp` value.
4. Stop or disconnect normally and confirm zero-current/Force-Off behavior and
   Manual-mode ownership are unchanged.

Risks and dependencies:

- Some controller branches use command acceptance to decide whether a later
  phase or Start stage may run. An unchanged safe target must therefore return
  accepted success even though no WebSocket request was dispatched.
- Suppression based on desired controller state rather than confirmed
  Wattpilot telemetry could hide a lost, rejected, or externally changed
  setpoint. Compare only against finite live `amp` telemetry.
- Moving suppression ahead of the final command guard could bypass newly
  reduced site headroom. The guard must execute before accepting every no-op.
- Verify against the validated Wattpilot firmware that repeatedly writing an
  unchanged `amp` value is not a required keepalive. No other open backlog item
  is a prerequisite.

Open questions:

- None. Firmware-side no-keepalive behavior remains a manual validation gate,
  not an implementation assumption that widens command authority.

Done criteria:

- A confirmed unchanged positive `amp` target is safely accepted without a
  second WebSocket `setValue` request or repeated INFO adjustment message.
- Missing or different current telemetry sends the requested value normally.
- The final command guard evaluates every proposed no-op and can reject it.
- Reductions, zero-current/Force-Off, phase commands, and changed current
  targets are never suppressed.
- Transactional Auto/Eco starts retain phase-current-Start ordering and do not
  fail merely because the current stage is already satisfied.
- Manual mode and every existing Wattpilot safety invariant remain intact.
- README and Wattpilot architecture describe the deduplication boundary.
- Focused syntax and unittest commands pass.
- Full unittest suite passes.

### Completed 2026-09-06 - P1 Require Accepted Running Phase Commands Before State Changes

Completion record:

- `commandSiteSafePhaseTransition()` now checks the guarded `set_phases()`
  result before changing `currentPhaseMode`; rejected phase commands retain the
  prior controller phase state.
- An unconfirmed three-phase transition whose one-phase recovery command is
  rejected now stops Auto/Eco fail-closed instead of reporting a successful
  fallback.
- Phase-up, PV phase-down, and grid-guard messages distinguish current-reduction
  preparation from an accepted phase command. The established `Switching to
  ...` records are emitted only after phase dispatch is accepted, so diagnostic
  reports no longer count preparation as a phase action.
- Added hardware-free accepted, reducing, rejected, recovery-stop, and message-
  ordering regressions while preserving Manual ownership, no-grid policy,
  site-current limits, battery-assist bounds, and phase confirmation.

### Completed 2026-09-06 - P2 Make Wattpilot Shutdown Cleanup Exception-Safe

Completion record:

- `Wattpilot.disconnect()` is idempotent for each connection lifecycle and
  catches WebSocket close races as a sanitized warning while always clearing
  connection state, command-authority telemetry, and freshness timestamps.
- Explicit Wattpilot disconnect notification and its INFO record are emitted
  once per connection lifecycle, including when the underlying WebSocket close
  raises.
- `FroniusWattpilot.handleSigterm()` now isolates Wattpilot cleanup failures and
  closes the selected site-current source from a `finally` path, after the
  existing Auto/Eco Force Off attempt.
- Added hardware-free regressions for a synthetic WebSocket close race,
  repeated disconnect, and independent site-current-source cleanup.

### Completed 2026-09-08 - P2 Add Opt-In Shelly Connection-Failure Grace

Completion record:

- Added `TransientFailureGraceSeconds` under `[Shelly3EMSiteCurrent]`, bounded
  to `0..5` seconds and no longer than `SiteCurrentFreshSeconds`. The default
  remains `0`, preserving strict immediate failure unless an operator opts in
  after commissioning the meter.
- Only transport connection failures can retain the last complete still-fresh
  snapshot as `Degraded`. Authentication, HTTP/device, payload, stale, and
  expired data invalidate the selected source immediately, with no provider
  fallback.
- Every failed poll still immediately withdraws the Wattpilot distributor
  request. During the bounded grace, an existing Auto/Eco charge may hold or
  reduce current or phase down, while starts, current increases, and phase-up
  remain blocked at the final command boundary.
- Grace entry resets site-current recovery eligibility. A complete successful
  poll must be followed by the existing continuous
  `SiteCurrentRecoverySeconds` interval before positive allocation, restart,
  or current increase can resume.
- Extended configuration migration/validation, the private-safe daily report,
  public operator documentation, and hardware-free regressions. The full test
  suite passes with 574 tests and 322 subtests.

### Completed 2026-09-08 - P2 Close Equal-Target Allocation Recovery Loop

Completion record:

- New supervised evidence showed the Wattpilot accepting 10 A before returning
  to a lower three-phase current, while the Shelly source remained healthy,
  physical headroom allowed a higher current, the positive distributor
  allowance stayed at zero, and site-current recovery repeatedly returned to
  zero.
- This contradicted the earlier equal-current completion boundary: the final
  command guard already preserved recovery for a confirmed no-op, but the
  controller-level target limiter still treated `target == current` as a
  reduction before that command boundary and cleared the timer.
- `WattpilotSiteCurrentDecisions.limit_current_recovery()` now distinguishes a
  genuine lower target from an equal safe target. Reductions still apply
  immediately and clear recovery; equality holds current while preserving the
  existing recovery timestamp and elapsed time.
- Added pure-helper and production-shaped controller regressions proving that
  a reduction suppresses positive demand, an equal active target lets the
  recovery interval mature, and the Wattpilot request becomes positive only
  after the complete configured delay. Manual ownership, source-failure grace,
  stale telemetry, no-grid policy, physical headroom, and the one-amp increase
  ramp remain unchanged. The full test suite passes with 576 tests and 322
  subtests.

## Suggested Implementation Order / PR Execution Queue

- No open implementation items remain.

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

## Manual Validation History

The following historical commissioning guidance was marked complete at the
operator's request. Do not force an overcurrent, force grid
import, disconnect a production grid, interrupt critical telemetry, or alter
the production energy system solely to recreate historical validation.

- Active charging followed by log-only analysis: with APP_DEBUG enabled on the
  approved Venus OS `v3.75`, Wattpilot firmware `42.5`, and Solar.wattpilot app
  `2.1.0` baseline, retain one normal connection containing a naturally
  available Auto/Eco charge. Confirm transition records and one-minute
  checkpoints contain no secret or vehicle identity and introduce no command
  source. After normal stop/disconnect, compare schema-4 connection/interval
  counts, counter kWh, duration, phase/current/power ranges, onboarding latency,
  coverage, reconciliation, and completeness with Wattpilot/VRM. Repeat with a
  complete yesterday report after local midnight. A natural phase change may
  be retained, but must not be forced solely for reporting validation.

- Active charging required: on the approved Venus OS `v3.75`, Wattpilot
  firmware `42.5`, and Solar.wattpilot app `2.1.0` baseline, first confirm that
  `/SiteCurrentL1` through `/SiteCurrentL3` agree with the installation and that
  `Charger1PhaseMapping` names the physical phase actually used in one-phase
  charging. During a naturally safe Auto/Eco session, observe that
  `/SiteAllowedCurrent` follows the limiting physical phase, three-phase uses
  one equal current command, a natural house-load increase reduces EV current,
  and recovery waits for `/SiteCurrentRecoveryElapsed` before rising 1 A per
  cycle. Return to Manual and confirm es-ESS remains observation-only. A
  naturally occurring stop below 6 A headroom may be recorded, but must not be
  created by intentionally overloading the site or a downstream branch.
- Shelly source commissioning required after installation: retain read-only
  `/shelly`, `EM.GetStatus?id=0`, and `EMData.GetStatus?id=0` captures from the
  GX; verify the exact model/profile, digest authentication, A/B/C physical
  mapping, and one-second poll reliability before selecting
  `Shelly3EMGen3`. Then validate fresh source diagnostics, normal supervised
  Auto/Eco limiting, source-loss fail-closed timing, delayed/ramped recovery,
  Manual observation-only behavior, and that the Fronius meter remains the
  sole Venus grid meter.
- Log-only: capture the site-current diagnostic paths and health-monitor output
  before, during, and after the supervised session; confirm no command-boundary
  rejection, traceback, unintended grid charging, or battery-assist bypass of
  the site guard.

- Hibernate remote control was resolved as documentation-only unsupported
  behavior while disconnected; no hardware action remains.
- Hardware not needed: documentation-contract, exact D-Bus read-allowlist, and
  lifecycle-script changes are covered by focused automated/static checks.

The general Venus OS `v3.75` daylight Auto/Eco PV-surplus, no-grid, battery-
assist, current-reduction, and naturally available phase-switch validation is
complete and is not a separate outstanding item. The native-PV command-
ownership guard, its supervised Gate 2 live validation, and the local/remote
mode-boundary correlation are also complete. Battery-heartbeat fault injection
is safely retired as a production requirement and is not outstanding manual
validation. Natural winter grid-import observation is also optional operational
evidence rather than an open backlog requirement.

- The complete operator behavior checklist remains in README and the safety
  invariants remain in `docs/wattpilot-architecture.md`.

## Outstanding Manual Validation

- P2 Shelly connection-grace commissioning: leave the default at `0` until the
  dedicated meter identity, phase mapping, and one-second polling are verified.
  If a five-second grace is enabled, use only a supervised low-risk
  GX-to-meter network interruption to confirm `Degraded`, immediate zero
  request, no start/increase/phase-up, expiry stop, healthy recovery, and the
  full site-current recovery delay. Do not operate the main breaker, induce an
  overload, or force grid import.
- P2 canonical Wattpilot allocation step: during a naturally stable supervised
  Auto/Eco charge, confirm complete-step allowances do not oscillate one ampere
  lower solely from voltage movement and that any residual remains below one
  active-phase step. Do not induce grid import or switch loads solely for this
  check.
- P3 duplicate current-command suppression: during a normal supervised
  Auto/Eco charge, confirm stable confirmed targets do not repeat outbound
  `amp` writes or INFO adjustment records and that a natural changed target is
  dispatched. Do not induce an overload, telemetry loss, or protective trip.
