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
  daylight validation on 2026-07-13 confirmed one-phase PV charging,
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
- Supervised Auto/Eco validation on 2026-07-14 confirmed that a phase-up
  candidate active at `20/600s` was cleared by a confirmed physical disconnect:
  after reconnect, without an es-ESS restart, the next candidate began at
  `0/600s`. The same session exposed a separate commissioning/control-ownership
  gap: native Solar.wattpilot `2.1.0` PV regulation held the EV near its 6 A,
  1.4 kW minimum while es-ESS owned more than 5.5 kW of assigned allowance and
  requested 16 A, with the remaining PV charging the stationary battery.
- Manual charging remains user-controlled. Direct current/start/stop writes
  fail closed unless Wattpilot telemetry confirms ECO mode; a one-time release
  of stale Auto/Eco limits on entry to Manual is the sole approved exception.
- The native Eco/es-ESS command-ownership guard is implemented, merged on
  `main`, and live-validated on 2026-07-15. With native PV surplus and flexible
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
  mixed sources. Log-only GX validation on 2026-07-15 passed integrity, import
  ownership, D-Bus registration, MQTT recovery, and command-free new-process
  startup checks on Venus OS `v3.75`.
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

### Completed 2026-07-20 - Preserve Site-Current Recovery Across No-Op And Pre-Start Commands

- Supervised production evidence showed a stable 6.43-6.47 kW Wattpilot
  allowance, 19-20 A of site-current headroom, healthy command authority, and
  no grid guard or battery assist, while three-phase charging remained at 7 A
  for more than four minutes and `/SiteCurrentRecoveryElapsed` stayed at zero.
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
- Follow-up supervised evidence at 13:03:57 and 16:20:34 local time showed a
  second form of the same defect. Wattpilot retained a higher configured
  current while stopped; the lower pre-start `amp` command cleared mature
  recovery state, so the immediately following `frc=2` Start was rejected.
  The controller then incorrectly began transition grace and advertised about
  4.33 kW of EV demand even though measured EV power remained zero.
- Stopped current commands now use fresh site headroom and completed recovery
  without applying active-current recovery to the retained setpoint. Command
  helpers return guarded-send acceptance, and Auto/Eco publishes Start,
  transition power, and the successful on/off timestamp only after phase,
  current, and Start commands are all accepted. A rejection remains stopped,
  sends no later stage, and rebuilds the stable-PV interval.
- Added hardware-free coverage proving the pending timer survives the no-op,
  releases the next ampere at the configured boundary, rejects an unchanged
  command above newly reduced physical headroom, permits a lower stopped
  setpoint only after recovery, and prevents rejected start sequences from
  publishing false transition state. Supervised live GX revalidation remains
  required.

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
  constraint release. The guard protects the configured C20 site limit only
  and intentionally does not claim to protect the shared downstream C16 EV/hob
  circuit.
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
  record, such as `(UTC+3)` in Romanian summer and `(UTC+2)` in winter. Both
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
  scans with timestamp indexes after a large live APP_DEBUG report exposed the
  quadratic paths. A subsequent 189,007-record GX run completed but took five
  minutes and selected the UTC calendar window, exposing remaining collection
  overhead and OS-timezone coupling. The report now performs the same bounded
  Venus timezone query as logging, routes regex parsing by message markers,
  uses a fixed-format fast parser and ISO timestamp conversion, avoids
  single-file de-duplication/sorting, records loader/analysis stage durations,
  and indexes allowance and Manual-boundary lookups. The first follow-up GX run
  confirmed correct `Europe/Bucharest` boundaries and improved to 2m17s before
  the dedicated loader fast path was added. Final production validation
  processed 195,892 records in 1m16s (48.63s loading and 23.90s analysis) while
  es-ESS remained up with the same PID. Corrected the maintained log path,
  local-midnight, retention, and diagnostic-report documentation.
- Live validation confirmed configuration version 12 and ten-day cleanup. It
  also showed the shell in UTC while Venus reported `Europe/Bucharest`, which
  led to making the Venus setting explicitly authoritative.
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
- The production Venus OS `v3.75` validation on 2026-07-13 already confirmed
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

- Completed a vehicle-disconnected production observation on Venus OS `v3.75`,
  Wattpilot firmware `42.5`, and Solar.wattpilot app `2.1.0`. The capture is
  preserved on the GX as
  `/data/es-ess-mode-boundary-20260715-155537.log`.
- A local Solar.wattpilot Standard selection recorded an operator action around
  15:56:31 UTC, raw `lmo=3` at 15:56:33.785, and
  `/ModeLiteral=Manual` at 15:56:38.865. The physical Eco indication turned
  off. Raw-to-public propagation took 5.080 seconds, matching the normal
  controller cadence; the app/physical timestamp remains operator-recorded and
  is not treated as a tighter transport measurement.
- The first Android home-screen VRM EV Charging Station widget attempt remained
  pending for about one minute and reported that its MQTT action could not be
  sent because the installation might not be real-time. No `/Mode` handler,
  raw `lmo`, or public mode event reached es-ESS during that failed delivery.
- On the successful retry, es-ESS received VRM `/Mode=1` at 16:01:15.593 UTC,
  Wattpilot reported raw `lmo=4` at 16:01:15.706, and
  `/ModeLiteral=Auto` published at 16:01:15.723. The complete server-observed
  path took 130 ms, including 17 ms from raw receipt to public state. The app
  showed Eco and the physical white/orange status-114 indication returned.
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
- Pre-change production evidence was captured at 14:21 UTC. The post-change
  restart at 15:00 UTC changed PID `32228` to stable PID `3914`; both MQTT
  clients recovered, the four expected es-ESS D-Bus services registered once,
  pinned integrity and bundled origins passed, compatibility/telemetry/command
  authority remained healthy, and Wattpilot stayed disconnected, stopped, at
  `0 W` and `0 A` with no critical or import error.
- The old Auto-mode process issued its documented safe `Off` during SIGTERM at
  15:00:01 before shutdown. The replacement process began recovery around
  15:00:24 and issued no start, stop, current, or phase command. The Venus OS
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
  tests. A copied production excerpt was correctly rejected as incomplete
  rather than being treated as a full-day report.

### Completed 2026-07-15 - Live-Validate Implemented Auto/Eco Command Ownership

- Completed Gate 2 on production Venus OS `v3.75`, Wattpilot firmware `42.5`,
  and Solar.wattpilot app `2.1.0` with `AllowGridCharging=false`.
- With the vehicle disconnected and native `Use PV surplus` enabled, the
  runtime reported `/CommandAuthorityOk=0`, identified the conflicting native
  setting, and issued no positive-current or phase command. After both native
  PV and flexible tariff were disabled, selecting Auto from the VRM web EVCS
  tile produced stable raw `lmo=4`, both native observations at `0`, and
  `/CommandAuthorityOk=1`.
- Supervised active charging followed es-ESS one-phase requests from 13 A
  through 16 A without a native current rewrite. The es-ESS 600-second
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
  command-boundary tests provide the fail-closed evidence.

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
- Production GX validation passed on 2026-07-14: all three changed runtime
  modules matched the reviewed content after line-ending normalization; every
  deployed top-level Python file and lifecycle shell script passed syntax
  validation; configuration v11 passed the exact bootstrap and value
  validators with `0600 root:root` permissions; and the controlled Venus OS
  v3.75 restart recovered both MQTT clients, the Wattpilot D-Bus service,
  healthy telemetry, firmware compatibility, and the fail-closed `-50 W` grid
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
- Active-charging GX validation passed on 2026-07-14 with Venus OS `v3.75`,
  Wattpilot firmware `42.5`, and Solar.wattpilot app `2.1.0`. A candidate reached
  `20/600s` at 07:39:32 UTC, physical disconnect was confirmed at 07:39:57,
  reconnect occurred without an es-ESS restart at 07:42:37, and the next
  candidate began at `0/600s` at 07:43:47. This proves disconnected wall-clock
  time was not reused.

### Completed 2026-07-13 - Add Freshness Guard For Battery-Assist SOC

- Production GX validation found that unchanged SOC is not periodically
  republished by either `com.victronenergy.system` or the selected Pylontech
  service, contradicting the original SOC-callback freshness model. The system
  service did publish selected-battery power activity 26 times in 30 seconds;
  the Pylontech service published power activity 23 times in 30 seconds.
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
- Live GX validation on 2026-07-14 observed 36 selected-battery power updates
  in 45 seconds with a maximum 2.979-second gap, well inside the configured
  15-second window. With SOC unchanged at 74%, an already-running one-phase
  Auto/Eco charge sustained battery assist for at least 75 seconds across
  34-321 W shortfalls while the grid remained at net export. This confirms the
  corrected heartbeat prevents false SOC expiry without changing the bounded,
  continuation-only assist contract.
- The later closure review safely retired supervised battery-heartbeat
  interruption as a production requirement: the system path cannot be isolated
  without risking broader battery/system telemetry, while the fail-closed path
  remains covered by focused hardware-free tests.

### Completed 2026-07-13 - Fix Delayed Wattpilot Mode Telemetry At The Manual Boundary

- Added observer-only raw `lmo` receive/change timestamps and correlated
  `/ModeLiteral` publication diagnostics, including the same evidence in the
  read-only GX health monitor.
- Production evidence located the delay in the controller's disconnected
  five-minute idle early return: raw mode telemetry arrived promptly, but the
  public mode could remain stale for 276.9 seconds. The raw command boundary
  itself was already current and did not authorize commands from stale public
  state.
- A pending raw mode transition now bypasses idle throttling once and runs
  through the normal controller worker. WebSocket callbacks remain command-free,
  unchanged disconnected state returns to the low-frequency cadence, and the
  approved one-time Auto/Eco-to-Manual constraint release is preserved.
- Hardware-free timestamp, command-boundary, disconnected-idle, once-only
  release, no-command, and unchanged-idle coverage passed with the full
  277-test suite, Python syntax checks, shell syntax, and whitespace checks.
- Fixed-code production validation passed on Venus OS `v3.75`, Wattpilot
  firmware `42.5`, and Solar.wattpilot app `2.1.0` with the vehicle disconnected.
  Startup ECO published in 3.744 seconds; local same-Wi-Fi Eco-to-Standard
  published Manual in 4.687 seconds with one constraint release; and
  Standard-to-Eco published Auto in 3.793 seconds without a Wattpilot command.
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
- Production validation passed on 2026-07-13 with Venus OS `v3.75`, Wattpilot
  firmware `42.5`, Solar.wattpilot app `2.1.0`, and the vehicle disconnected.
  After a 13:59:45 UTC restart, startup reported Manual at 14:00:17.676 and the
  passive Manual/default branch at 14:00:17.687 without any `psm`, `amp`, or
  `frc` command; the service remained healthy and firmware telemetry recovered.

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

- Completed the attended daylight Auto/Eco validation on the production Cerbo
  GX running Venus OS `v3.75` build `20260624163305`.
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

## Backlog

Open implementation items appear first. Completed implementation records remain
below them so their decisions and evidence are not lost.

### P3 - Add Wattpilot Charging-Session Energy And Onboarding Reports

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
- This reporting task is independent of the future dedicated C20 meter and
  must not claim that Victron consumption current is meter-grade breaker
  evidence.

Open questions:

- Confirm during implementation approval whether the fixed one-minute
  connected-session checkpoint is acceptable; the default plan avoids a new
  configuration key.
- Confirm whether any downstream consumer requires the JSON schema to remain
  version 3. The preferred implementation increments it because the session
  contract gains material fields.

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

Outcome and retained production evidence:

- The fail-closed authority implementation merged through PR #70
  (`c01a783`) after command-boundary, policy, runtime-status,
  configuration-contract, and full-suite verification.
- Initial production evidence on 2026-07-14 disproved the former native
  start-threshold workaround: with 6.89 kW PV, the EV drew about 1.41 kW and the
  battery absorbed 4.487 kW while es-ESS had assigned 5.016-5.725 kW and
  repeatedly requested 16 A. The Solar.wattpilot `2.1.0` slider stopped at
  10 kW, and neither 10 kW nor the former 99 kW example established command
  ownership after an external start. The Fronius manual documents native
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
  Opel Corsa-e profile hid phase control.
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
- Supervised Gate 2 on 2026-07-15 validated the disconnected invalid-authority
  block, sole-owner Auto commissioning, es-ESS ownership across 13-16 A, the
  full 600-second phase-up candidate and telemetry-confirmed three-phase
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
- Production fault/recovery validation completed on Venus OS `v3.75` on
  2026-07-15 using an isolated loopback TCP proxy for the main client; the
  Venus local broker was never stopped. With `localhost:18884` unavailable,
  main MQTT logged one actionable failure, local MQTT connected normally,
  startup continued after the bounded 30-second wait, and es-ESS remained on
  PID 12561 from 40 through 55 seconds without a crash loop.
- Local-broker refusal was not induced because stopping the Venus broker would
  disrupt platform MQTT consumers. Equivalent local-client refusal/recovery is
  retained in hardware-free orchestration coverage; the live run confirmed
  normal local-client isolation while the main client was unavailable.
- Starting the proxy without restarting es-ESS produced exactly one main MQTT
  connect callback on the same PID, restored all SolarOverheadDistributor and
  Wattpilot subscriptions, republished `es-ESS/$SYS/Status=Online`, and resumed
  TimeToGo diagnostic publication.
- The original configuration was restored with a matching SHA-256, production
  main/local MQTT each connected normally after restart, PID 13293 remained
  stable, live main-MQTT publication succeeded, the verified proxy was stopped,
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
- Production validation on Venus OS `v3.75` completed on 2026-07-15 with
  `TimeToGoCalculator=true`, `BatteryCapacityInWh=32000`, and
  `UpdateInterval=1000`. During natural discharge, complete D-Bus inputs
  produced `es-ESS/TimeToGoCalculator/TimeToGo=108556` seconds, consistent
  with changing power, SOC, active SOC limit, and capacity. The same supervised
  PID remained healthy with increasing uptime and no recent critical error,
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

- The supported Venus OS `v3.75` GX processed a representative APP_DEBUG
  `current.log` containing 210,294 lines/records and 29,918,910 bytes while
  es-ESS remained online.
- Peak resident set was 107,656 KB from an initial 642,456 KB available. Even
  conservative subtraction left about 522 MiB available, and the post-run
  reading recovered to 640,836 KB.
- Log loading took 53.66 seconds and analysis 25.85 seconds. Exit code `2`
  reflected earlier operational anomalies in the complete current-day input,
  not a resource limit or report failure.
- The supervised es-ESS process remained PID 2494 and uptime advanced from 525
  to 636 seconds. The implementation had already passed 67 focused daily-report
  tests and the complete 415-test hardware-free suite.
- Decision: close measurement-only. Do not add line, continuation, record, or
  byte caps: the measured supported-GX workload has ample headroom, while
  arbitrary limits could silently discard the safety evidence the report is
  designed to retain. Any future measured need for bounds must report explicit
  `INCOMPLETE` status and exact truncation evidence rather than claiming
  `GOOD`.

### P1 - Integrate Shelly 3EM-63T Gen3 As The Dedicated C20 Site-Current Source

Goal:

Use a correctly installed Shelly 3EM-63T Gen3 to provide direct, fresh
physical L1/L2/L3 current measurements at the downstream house C20 boundary
for the mandatory Wattpilot Auto/Eco site-current guard.

Problem:

The current guard reads calculated Venus system consumption currents. Live
commissioning showed those current values alternating between approximately
4.5 A and 8.6 A while one-phase Wattpilot power remained near 1.33-1.37 kW and
the charger reported approximately 5.8 A. That calculated source is therefore
not sufficiently trustworthy as the future authoritative C20 measurement.
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
  physical C20 protective device.

Implementation:

- Do not start production implementation until the Shelly is installed at the
  C20 boundary and read-only captures prove its model/generation, firmware,
  `triphase` profile, authentication state, live `EM.GetStatus`,
  `EMData.GetStatus`, phase order, and physical A/B/C-to-L1/L2/L3 mapping.
- Add a bounded local Shelly Gen3 RPC client. Identify the device through the
  unauthenticated `/shelly` endpoint, require the expected Gen3 model/profile,
  poll `EM.GetStatus?id=0` for live current/voltage/power, and read
  `EMData.GetStatus?id=0` only for diagnostic/reporting energy. When device
  authentication is enabled, use Shelly's SHA-256 HTTP digest flow with user
  `admin`; never embed credentials in URLs or logs.
- Validate every required live phase value as finite and non-negative, reject
  missing phases and meter/phase errors, and timestamp only a fully successful
  upstream poll. A cached D-Bus `GetValue` must never refresh Shelly sample
  freshness after the HTTP source has stopped updating.
- Publish the meter through a dedicated es-ESS site-current boundary that
  cannot be selected or aggregated by Venus as a second grid meter. Keep the
  Fronius Smart Meter as the existing Venus/system grid meter and do not
  change grid-setpoint ownership.
- Add an explicit, validated Wattpilot site-current source selection and
  physical phase mapping. The default/migrated configuration must preserve the
  existing Venus-system source until the operator deliberately selects the
  commissioned Shelly source.
- Feed the Shelly source into the existing mandatory site-current decisions
  without adding overload grace. Missing, invalid, error-marked, stale, or
  unreachable Shelly data must fail Auto/Eco closed within the configured
  freshness contract. Recovery must retain the existing stable delay and
  1 A-per-cycle ramp.
- Preserve Manual observation-only behavior, equal current on all active
  three-phase conductors, the one-phase physical mapping, no-grid behavior,
  battery-assist bounds, command ownership, and every existing public
  Wattpilot diagnostic unless an explicitly documented source-status field is
  added.
- Keep this work on branch
  `feature/wattpilot-per-phase-site-current-guard` after the physical meter is
  installed and the prerequisite captures are reviewed.

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
- `tests/test_shelly3em_gen3_client.py`
- `tests/test_shelly3em_site_current.py`

Tests:

- Add hardware-free Gen3 RPC tests for unauthenticated and digest-authenticated
  access, exact `triphase` field mapping, energy-unit conversion, timeout,
  malformed/non-finite/negative values, missing phase fields, phase and device
  errors, wrong model/generation/profile, recovery, and secret-safe logging.
- Add source-service tests proving only complete successful polls update the
  sample timestamp, repeated identical zero/nonzero values remain fresh, an
  HTTP outage cannot be hidden by cached D-Bus values, and failure publishes a
  disconnected/invalid source state without registering a competing grid
  meter.
- Extend site-current guard tests for explicit source selection, A/B/C phase
  mapping, one- and three-phase headroom, stale/invalid/error fail-closed
  behavior, recovery delay/ramp, and configuration migration preserving the
  current source by default.
- Add characterization tests proving Manual mode issues no command and the
  Shelly source cannot change grid-meter selection, grid-setpoint ownership,
  no-grid policy, battery assist, or command authority.
- Keep all new test files compatible with `python -m unittest discover -s
  tests`; no CI workflow change is expected.

Expected coverage:

- Proves the mandatory Auto/Eco guard uses direct C20-boundary phase currents
  only after explicit commissioning and never silently falls back to a stale
  or calculated source.
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
3. With the electrician, correlate Shelly A/B/C with physical C20 L1/L2/L3
   using normal safe loads; confirm current direction and compare readings
   against an independent clamp meter where available.
4. Deploy the implementation with the old source still selected and confirm
   the Fronius service remains the sole Venus grid meter.
5. Select the Shelly site-current source, restart es-ESS, and confirm fresh
   phase currents, ages, limiting phase, allowed current, connection state,
   and no critical/traceback/command-boundary errors while the car is stopped.
6. During a normal supervised Auto/Eco PV charge, confirm one-phase mapping,
   equal three-phase commands, natural house-load current reduction, and
   delayed/ramped recovery. Do not deliberately exceed 20 A.
7. In a low-risk window, briefly isolate only Shelly network access and confirm
   Auto/Eco fails closed within the documented freshness bound while the
   physical C20 remains the final protection. Restore access and confirm
   recovery follows the existing delay/ramp.
8. Return to Manual and confirm es-ESS remains observation-only.

Risks and dependencies:

- Blocked until the Shelly 3EM-63T Gen3 is physically installed at the correct
  downstream C20 boundary and its live API/phase mapping evidence is supplied.
- Wi-Fi, digest-authentication compatibility on Venus OS `v3.75`, device
  firmware behavior, response cadence, and actual measurement latency require
  live validation; no API claim alone establishes breaker-protection timing.
- Incorrect conductor placement, phase mapping, voltage-reference pairing, or
  profile selection could produce plausible but unsafe headroom calculations.
- Registering the source as `com.victronenergy.grid` could compete with the
  Fronius meter and corrupt system topology; the implementation must retain a
  dedicated non-grid source boundary.
- The Shelly and es-ESS remain monitoring/load-management layers. Neither
  replaces the physical C20 or electrician-approved protection and wiring.
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
- The dedicated source supplies direct, fresh, validated C20 phase currents
  without appearing as a second Venus grid meter.
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

## Suggested Implementation Order / PR Execution Queue

Use this queue as the implementation order. Entries carrying the same PR-group
label form one PR-sized batch; unlabelled entries remain separate PRs. Do not
pull later items into the active PR. When the user says `fix next PR items`,
select the first PR group or unlabelled entry containing unfinished backlog
items, present the required implementation plan, risks, and verification, and
then follow the repository working agreement for approval and implementation.
After delivery, move every finished item in that group to `Completed` and
advance the queue on the next request.

1. P1 Integrate Shelly 3EM-63T Gen3 As The Dedicated C20 Site-Current Source —
   safety-critical source correction on the current branch, gated until the
   meter is installed and live API/phase evidence is reviewed.
2. P3 Add Wattpilot Charging-Session Energy And Onboarding Reports — additive,
   command-free observability requested for diagnosing connection/start issues;
   preserve the existing controller and safety boundaries.

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

One implementation-stage commissioning check remains. Do not force an
overcurrent, force grid import, disconnect a production grid, interrupt
critical telemetry, or alter the production energy system solely to exercise a
safety branch.

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
  created by intentionally overloading the site or the shared C16 branch.
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
