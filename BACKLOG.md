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
  Supervised live revalidation is complete. No Wattpilot implementation or
  mandatory production-validation task remains. The optional natural-winter
  observation and battery-heartbeat fault simulation were safely retired; the
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
  `BatteryAssistMaxShortfallW=1000` preserves a small cloud bridge while
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

#### Implementation record - completed in Group B: Define Safe Grid-Setpoint Bounds

Goal:

Prevent unreviewed extreme combined grid setpoints after safe site-independent
or configured limits are established.

Original problem:

The shared combiner adds every active request to `DefaultPowerSetPoint` without
minimum or maximum bounds. The repository does not currently establish values
that are safe for every supported ESS site, so implementing an arbitrary clamp
could reject legitimate NoBatToEV operation or permit an unsafe range.

Pre-fix evidence:

- `es-ESS.py:696-707` publishes the additive result without bounds.
- `config.sample.ini` defines `DefaultPowerSetPoint` but no approved combined
  minimum or maximum.

Implemented:

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

Resolved decisions:

- Bounds are explicit site configuration because the repository has no
  universal production-safe range. Migration sets both to the existing default
  setpoint, so adjustments fail closed until an operator approves wider limits.

Done criteria:

- The bounds and their source are explicitly approved and documented.
- Combined setpoints are clamped and every clamp is observable.
- In-range additive behavior and request ownership remain unchanged.
- Full unittest suite passes.

#### Implementation record - completed in Group B: Fix PV Inverter Stale Window And Cached-Power Contribution

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

Resolved decision:

- Use a service-wide configurable timeout with a documented 300-second default
  and a validated five-second minimum.

Done criteria:

- Stale detection uses an approved window and stale power contributes zero.
- Full unittest suite passes.

#### Implementation record - completed in Group B: Make Shelly Net-Energy Persistence Robust And Atomic

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

Resolved decision:

- Reset the timestamp on every poll attempt. Unknown outage energy is omitted
  instead of applying the next successful power sample across the gap.

Done criteria:

- Corrupt files recover safely, writes are atomic, and outage gaps are bounded.
- Full unittest suite passes.

#### Implementation record - completed in Group B: Make MQTT TLS Certificate Verification The Default

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

Resolved decisions:

- Support both system trust and an explicit CA/certificate file. Full
  verification is the default, certificate-only pinning is explicit, and
  insecure operation remains a warning-producing compatibility mode.
- Migrate an already-enabled legacy TLS client once to explicit `Insecure` so
  upgrade does not silently disconnect it; new and previously disabled clients
  default to `Required`.

Done criteria:

- Verified TLS is the default and any insecure mode is explicit/documented.
- Full unittest suite passes.

#### Implementation record - completed in Group B: Validate Remaining Safety And Operational Values

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

Resolved decision:

- Validate non-negative grid/assist thresholds, positive freshness, a
  five-second raw-overhead floor, startup ratio in `(0, 1]`, positive common
  runtime values, zero-feed-in scale in `(0, 1]`, non-negative distance, and
  SOC in `0..100`. Do not add site-specific upper limits.

Done criteria:

- Every approved remaining rule is documented, migrated if necessary, and
  enforced before side effects.
- Full unittest suite passes.

#### Implementation record - completed 2026-07-15: Live-Validate Implemented Auto/Eco Command Ownership

Goal:

Live-validate the merged Solar.wattpilot `2.1.0` command-authority guard and
confirm that es-ESS is the sole effective owner of Auto/Eco start, stop,
current, and phase decisions.

Implementation status:

- The fail-closed authority implementation is merged on `main` through PR #70
  (`c01a783`). Hardware-free command-boundary, policy, runtime-status,
  configuration-contract, and full-suite verification passed before merge.
- Gate 1 command-free setting capture and Gate 2 vehicle-disconnected preflight
  plus supervised daylight active-charging validation are complete. The final
  production state restored sole-owner Auto authority with the vehicle
  disconnected.

Problem:

Wattpilot native PV-surplus regulation remains active in ECO mode and can
compete with es-ESS commands. Raising the app's native start-up power threshold
does not disable its closed-loop current regulation after es-ESS forces a
charge. On the validated production system, es-ESS repeatedly requested 16 A
from more than 5.5 kW of distributor-assigned PV, but the charger remained near
the native 6 A / 1.4 kW minimum while the stationary battery absorbed the
remaining PV. This defeats deterministic es-ESS current and phase control and
can produce misleading battery-assist state even when the measured EV draw is
fully covered by assigned allowance.

The former README recommendation placed the native start threshold above
reachable site surplus and used `99 kW` as an example. Solar.wattpilot app
`2.1.0` offers a slider only up to 10 kW on the validated device, and production
observation shows that the start threshold alone is not a command-ownership
boundary. Replacing `99 kW` with `10 kW` without resolving native regulation
would document an ineffective workaround. The investigation stage now labels
the threshold as non-authoritative without prescribing an unvalidated
replacement.

Evidence:

- Production validation on 2026-07-14 used Venus OS `v3.75`, Wattpilot firmware
  `42.5`, Solar.wattpilot app `2.1.0`, ECO mode, and
  `AllowGridCharging=false`.
- With 6.89 kW PV production, the EV drew 1.41 kW, the stationary battery
  charged at 4.487 kW, and grid exchange stayed near zero. Solar.wattpilot
  reported approximately 1.4 kW of PV surplus.
- In the same session, SolarOverheadDistributor assigned 5.016-5.725 kW and
  `FroniusWattpilot.adjustChargeForPvAllowance()` repeatedly logged 16 A
  one-phase requests, while measured EV power remained approximately
  1.3-1.4 kW.
- After reconnect, es-ESS issued no new `frc=On`; the Wattpilot resumed its
  retained start state. A short 18 W shortfall then activated battery assist
  before allowance increased, demonstrating that native and es-ESS state can
  interact in ways not represented by the current commissioning contract.
- `Wattpilot.py:set_power()` sends only `amp`; `set_start_stop()` sends `frc`,
  and `set_phases()` sends `psm`. The client does not read, validate, disable,
  or own the app's native `Use PV surplus`, start-up level, flexible-tariff, or
  native phase-switch settings.
- `FroniusWattpilot.py` treats confirmed `WattpilotControlMode.ECO` as the
  Auto/Eco command-authority condition, but ECO telemetry does not prove the
  native PV controller is inactive.
- `README.md` previously recommended an unreachable native threshold, for
  example `99 kW`, as the way to prevent two controllers competing. The
  command-free investigation stage removes that claim as a safety boundary but
  intentionally does not prescribe `10 kW` or another unvalidated replacement.
- The official Fronius Wattpilot manual states that native PV mode starts at a
  configured power level and then regulates one-phase power in 0.23 kW steps
  and three-phase power in 0.69 kW steps. It does not define a high start-up
  level as disabling native regulation after an external forced start:
  <https://manuals.fronius.com/html/4204260400/en.html>.

Implementation:

- Gate 1 used the command-free, firmware- and disconnect-gated capture utility
  to compare redacted firmware `42.5` status before and after reversible
  Solar.wattpilot `2.1.0` setting changes. The validated authority inputs are
  strict read-only `fup` (`Use PV surplus`) and `ful` (flexible tariff) booleans;
  es-ESS does not write either undocumented setting.
- In a supervised no-grid window, test ECO mode with native `Use PV surplus`
  disabled and flexible tariff disabled. Determine whether explicit es-ESS
  `frc`, `amp`, and `psm` commands remain authoritative or whether ECO refuses
  charging. A stopped charge is the safe failure; do not enable a tariff merely
  to make the test pass.
- Determine whether the native controller rewrites `amp`, `frc`, or `psm`
  after an acknowledged es-ESS command, and record the command/telemetry timing
  needed to distinguish charger enforcement from a vehicle-side current limit.
- Based on validated evidence, choose one narrow result:
  - a commissioning-only contract that disables native regulation while ECO
    still accepts es-ESS commands;
  - a readable native-setting compatibility guard that fails Auto/Eco closed
    when competing regulation is active; or
  - a separately approved controller/transport change if firmware `42.5`
    provides no safe commissioning state.
- Do not switch normal Auto/Eco operation to Standard/Manual mode, weaken the
  ECO command boundary, enable intentional grid charging, or let battery assist
  start a session or authorize phase-up.
- Correct README, configuration comments, architecture, service inventory, and
  HTML guidance only after the validated commissioning/runtime contract is
  known. Do not replace `99 kW` with `10 kW` as an isolated documentation fix.

Investigation progress 2026-07-14:

- Added `scripts/wattpilot-setting-capture.py`, which authenticates and requests
  full status but installs a guard that blocks every `setValue` request. It
  refuses firmware other than `42.5`, a missing vehicle-state baseline, or a
  connected vehicle, and emits only changed properties with sensitive/arbitrary
  strings redacted or fingerprinted.
- Added hardware-free tests that cover redaction, deterministic snapshots,
  forward/reverse diffs, firmware and disconnect gates, timeout behavior,
  interpolation-safe credential loading, and an AST-level prohibition on every
  Wattpilot command/pairing helper.
- Added a two-gate operator guide covering protected evidence capture,
  restoration, pass/fail criteria, and the later supervised no-grid current,
  phase, invalid-authority, and Manual regression sequence.
- Removed the disproven `99 kW` README recommendation as a command-ownership
  boundary without substituting the app's ineffective `10 kW` maximum.
- Completed eight protected forward/reverse reports with the vehicle
  disconnected. Every report recorded firmware `42.5`,
  `vehicle_connected=false`, and `all setValue requests blocked`. The reports
  reversibly mapped `fup` to `Use PV surplus`, `ful` to flexible tariff, `fst`
  to start-up power (`10000`/`9900` W), and `frm` to control response
  (`1` Default/`2` Prefer power to grid).
- Observed that turning `Use PV surplus` off also changed `lmo` from ECO (`4`)
  to Standard (`3`), while turning it back on did not restore ECO. Zero
  feed-in was intentionally not changed, the Opel Corsa-e profile hid the
  phase setting, and one-direction `cdci`/`dci` changes remain unclassified.
- Implemented a read-only fail-closed authority guard requiring validated
  firmware `42.5`, raw ECO, `fup=false`, and `ful=false`. Missing, malformed,
  or conflicting telemetry blocks starts, positive current/current increases,
  and phase-up; safe zero-current/stop remains permitted in ECO. Manual remains
  user-owned, and Manual-to-Auto selection is rejected until both native
  settings are observed off.
- Added actionable D-Bus/MQTT diagnostics for authority and both native-setting
  observations, a distinct stopped-for-authority runtime state, health-monitor
  output, focused regression coverage, and updated operator documentation.
- Gate 1 completed the protected setting capture. Gate 2 on 2026-07-15 proved
  the disconnected invalid-authority block, sole-owner Auto commissioning,
  es-ESS current ownership across 13-16 A, the full 600-second phase-up
  candidate and telemetry-confirmed three-phase transition, safe phase-down,
  bounded assist behavior, Manual one-time release, and final disconnected
  restoration. No intentional grid charging or native command rewrite was
  observed.

Files to change:

- `BACKLOG.md` when recording the Gate 2 result
- Production code, maintained configuration, documentation, and focused tests
  only if supervised evidence contradicts the implemented authority contract

Files to add:

- None expected.

Tests:

- Existing setting-capture, client parsing, command-boundary, Eco/PV policy,
  runtime-status, configuration-contract, and full-suite tests are the
  automated verifier for the merged implementation.
- No new test is required for a successful observation-only Gate 2 run. If it
  exposes a defect, add focused hardware-free coverage before changing the
  command boundary.

Expected coverage:

- Proves Auto/Eco commands are issued only under one validated authority model.
- Proves a competing or unobservable native controller cannot silently be
  documented as disabled by an ineffective start threshold.
- Preserves no-grid behavior, Manual ownership, continuation-only battery
  assist, phase timing, firmware compatibility, and existing public contracts.
- Existing passing tests remain unchanged.

Manual validation:

Active charging required in a supervised daylight, no-grid window. App setting
changes must first be made with the vehicle disconnected; raw status capture is
log-only, but current/phase ownership requires a connected charging session.

Manual test steps:

1. With the vehicle disconnected, record Solar.wattpilot app version `2.1.0`,
   firmware `42.5`, every native PV/tariff/phase setting, and the corresponding
   raw Wattpilot status fields.
2. Disable native `Use PV surplus` and the flexible tariff while retaining ECO
   mode; do not select Standard or Next Trip.
3. Reconnect only when fresh es-ESS allowance safely supports one-phase PV
   charging and confirm no native grid-only start occurs.
4. Correlate each es-ESS `frc` and `amp` command with acknowledgement, Wattpilot
   set current, measured current/power, assigned allowance, grid exchange, and
   stationary-battery power.
5. Under naturally sufficient PV, confirm only es-ESS phase timing authorizes
   `psm` and that no native phase transition or current rewrite races it.
6. Reduce or wait for naturally lower PV and confirm es-ESS current reduction
   and stop remain authoritative without intentional grid use.
7. Restore the original app/config settings after any unsuccessful variant and
   retain the logs needed to document the supported result.

Risks and dependencies:

- Disabling native PV surplus may make ECO refuse every charge, including
  forced `frc=On`; that outcome must be recorded rather than bypassed with an
  unsafe tariff or Manual-mode workaround.
- Enabling or loosening a native flexible tariff can start charging from grid
  independently of es-ESS and is outside this investigation's safe scope.
- Writing undocumented Wattpilot configuration fields can persist across
  restarts and alter user commissioning. Start with read-only field capture and
  operator-controlled app changes.
- A vehicle-side current limit can resemble native regulation; command
  acknowledgement, requested current, and repeated behavior across app setting
  changes must be correlated before assigning cause.
- The stopped/phase runtime-state cleanup is completed observer behavior and is
  independent of this command-ownership validation.

Resolved questions:

- ECO accepted es-ESS `frc`, `amp`, and `psm` commands with native PV surplus
  and flexible tariff disabled. Charging followed changing 13-16 A requests
  and the es-ESS-timed phase transition.
- Native regulation did not rewrite the acknowledged es-ESS current or phase
  requests during the supervised window. Read-only `fup`/`ful` observations and
  raw ECO mode provided the pre-command authority gate.
- Firmware kept `fup=false` and `ful=false` stable after VRM selected Auto
  (`lmo=4`). Solar.wattpilot app `2.1.0` cannot select Eco with both options
  off. The VRM web/Remote Console EVCS mode control and the dedicated Android
  home-screen VRM EV Charging Station widget are validated transitions; the
  in-app installation-schematic EVCS area remains informational.
- The selected Opel Corsa-e profile still hides the app phase control, but live
  evidence showed that only the es-ESS 600-second candidate issued phase-up and
  that telemetry confirmed both the three-phase result and later safe
  phase-down.

Done criteria:

- A single validated Auto/Eco command owner is demonstrated on Venus OS
  `v3.75`, firmware `42.5`, and Solar.wattpilot app `2.1.0`.
- The charger follows es-ESS current and phase requests within documented
  hardware/vehicle tolerances, or Auto/Eco fails closed with an actionable
  diagnostic instead of running two controllers.
- No native tariff or PV rule starts or sustains intentional grid charging when
  `AllowGridCharging=false`.
- README, sample configuration, architecture, inventory, and HTML guidance
  describe the validated app setting and explicitly reject ineffective values.
- Manual-mode ownership, battery-assist limits, phase timing, compatibility
  guards, and D-Bus/MQTT contracts remain intact.
- Focused tests and configuration-contract checks pass where applicable.
- Full unittest suite passes.

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

Goal:

Allow es-ESS to survive a main or local MQTT broker that is not yet listening
during process startup and recover without depending on a process crash/restart
loop.

Problem:

Both MQTT clients use blocking `connect()` before `loop_start()`. An initial
socket or TLS connection failure can therefore raise before Paho's background
network loop owns reconnect behavior. The source TODO calls out the local
broker boot race, but the same ordering exists for main/local and TLS/plain
branches.

Evidence:

- `es-ESS.py:339-351` connects the main client before starting its loop.
- `es-ESS.py:370-385` contains the startup-race TODO and connects the local
  client before starting its loop.
- `tests/test_es_ess_mqtt_orchestration.py` covers routing after connect and
  reconnect callbacks, but not recovery from an initial connection refusal.

Implementation:

- Characterize the supported Paho callback/API variants already handled by the
  runtime.
- Move initial main/local connection ownership to a non-blocking or explicitly
  bounded retry path that lets the existing loop recover when the broker
  appears.
- Preserve main/local client separation, TLS trust policies, last-will/status
  topics, reconnect subscriptions, orderly shutdown, and fail-closed runtime
  compatibility checks.
- Do not hide permanent DNS, certificate, authentication, or configuration
  failures; keep actionable, deduplicated diagnostics.

Files to change:

- `es-ESS.py`
- `docs/service-inventory.md` if startup/recovery semantics change materially
- `README.md` if operator-visible recovery guidance changes
- `BACKLOG.md` on completion

Files to add:

- None expected.

Tests:

- Extend `tests/test_es_ess_mqtt_orchestration.py` for initial main/local
  refusal, TLS/plain parity, later recovery, subscription restoration, and
  non-duplicated loops/callbacks.
- Cover permanent failure diagnostics and graceful shutdown before a first
  successful connection.
- Use fake Paho clients only; no real broker or network.

Expected coverage:

- Proves broker startup ordering cannot terminate es-ESS before reconnect
  ownership begins.
- Proves existing main/local routing, TLS configuration, retained status, and
  shutdown behavior remain unchanged after recovery.

Manual validation:

Fault simulation in a low-risk GX window; no charging or other hardware action
is required.

Manual test steps:

1. Temporarily keep the local broker unavailable while starting es-ESS.
2. Confirm the process remains supervised and reports bounded connection
   diagnostics rather than repeatedly crashing.
3. Restore the broker and confirm both MQTT clients, subscriptions, services,
   and grid-setpoint publication recover once without duplicate callbacks.
4. Repeat for a deliberately unavailable test main broker without exposing
   production credentials.

Risks and dependencies:

- Starting services before MQTT is ready can expose assumptions that were
  previously hidden by blocking startup; tests must characterize queued
  publications and registration order.
- Do not weaken certificate or authentication failures into silent retries.
- No other backlog item must land first.

Open questions:

- Whether the supported Paho versions are best served by `connect_async()` or
  a small explicit initial-retry owner; select from tests and GX behavior, not
  assumption.

Done criteria:

- Main and local MQTT initial unavailability no longer terminates startup.
- Later broker availability restores the correct subscriptions and status.
- TLS/authentication failures remain actionable and do not fall back insecurely.
- Full unittest suite passes.

### Completed 2026-07-15 - Gate Experimental Zero-Feed-In On Confirmed Grid Connection

Completion record:

- Implemented in `48fe83a`. Commands now require an explicitly connected grid
  or shore AC input; missing, malformed, genset, off-grid, and transition states
  issue no new OpenDTU command and preserve the last nonpersistent limit so
  frequency shifting remains authoritative.
- Hardware-free confirmed-grid, second-input shore, missing, malformed,
  disconnected, transition, and recovery coverage passes together with the
  full hardware-free suite.
- The operator confirmed that no separate GX/OpenDTU/inverter staging setup is
  available. Production has `MqttPVInverter=false`; neither it nor experimental
  zero-feed-in will be enabled merely to force this test, and the production
  grid will not be disconnected.
- Closure is an explicit acceptance of the implemented, default-disabled guard
  without hardware-in-the-loop evidence; it is not recorded as hardware
  validation. README retains the isolated procedure that must be completed by
  any site choosing to commission experimental zero-feed-in later.

Goal:

Prevent experimental OpenDTU throttle commands when the GX is off-grid or its
grid-connected state is missing or uncertain.

Problem:

`MqttPVInverter._dtuZeroFeedin()` treats a non-`None`
`/Ac/ActiveIn/NumberOfPhases` value as its on-grid condition. Phase-count
availability does not by itself prove that the grid is connected, so the
experimental controller can compete with the intended off-grid frequency-
shifting behavior. The feature is disabled by default, limiting current
exposure but not removing the device-control gap when enabled.

Evidence:

- `MqttPVInverter.py:68-70` contains the explicit TODO for a grid-connected
  value and subscribes only to active-input phase count.
- `MqttPVInverter.py:117-165` permits throttle calculations whenever phase
  count is non-`None` and SOC meets the configured threshold.
- `tests/test_mqtt_pv_inverter.py` covers zero target, proportional scaling,
  incomplete consumption, stale data, and recovery, but has no off-grid or
  unknown-grid-state scenario.

Implementation:

- Identify and validate the authoritative grid-connected D-Bus path available
  on the supported Venus OS `v3.75` baseline.
- Subscribe to that path and require an explicit connected state before any
  zero-feed-in throttle publication.
- Define a fail-safe no-command/limit-release behavior for missing, malformed,
  disconnected, and recovery transitions based on OpenDTU/frequency-shifting
  ownership; do not guess a protocol value.
- Preserve the existing disabled default, stale-inverter handling, zero-target
  behavior, configuration keys, and shared grid-setpoint ownership.

Files to change:

- `MqttPVInverter.py`
- `README.md`
- `config.sample.ini` only if a new setting is demonstrably required
- `docs/service-inventory.md`
- `BACKLOG.md` on completion

Files to add:

- None expected.

Tests:

- Extend `tests/test_mqtt_pv_inverter.py` for confirmed on-grid, confirmed
  off-grid, missing/malformed state, startup `None`, transition to off-grid,
  and recovery to on-grid.
- Prove no OpenDTU command is issued from uncertain/off-grid evidence and
  normal on-grid proportional/zero-target behavior remains unchanged.
- Extend config migration/contract tests only if configuration changes.

Expected coverage:

- Proves experimental inverter limiting cannot take control from off-grid
  frequency shifting based only on a cached phase count.
- Proves recovery requires a fresh, explicit connected state.

Manual validation:

Fault simulation on staging or hardware-in-the-loop only. Do not disconnect
the production grid solely to complete this item.

Manual test steps:

1. With zero-feed-in enabled on a safe test system, record confirmed on-grid
   throttle behavior.
2. Simulate or observe grid-connected state becoming unavailable/off-grid.
3. Confirm es-ESS issues no conflicting OpenDTU throttle command and the
   inverter's supported off-grid control remains authoritative.
4. Restore grid state and confirm normal control resumes only after fresh
   connected telemetry.

Risks and dependencies:

- The exact D-Bus path and value semantics must be verified on Venus OS
  `v3.75`; choosing the wrong signal could disable valid control or interfere
  with island operation.
- Hardware validation must not create an unsafe production outage.
- No other backlog item must land first.

Open questions:

- Which Venus OS `v3.75` service/path is the authoritative, sufficiently fresh
  grid-connected signal for this controller?
- Whether off-grid transition should leave the last nonpersistent limit or
  explicitly release it depends on validated OpenDTU behavior.

Done criteria:

- Only confirmed on-grid state authorizes zero-feed-in throttle commands.
- Missing/off-grid state fails safely without competing with frequency shifting.
- The maintained sample and user guidance describe the gate accurately.
- Full unittest suite passes.

### Completed 2026-07-15 - Resolve Time-To-Go Ownership And Publication

Resolution:

- Official Venus `dbus-systemcalc-py` behavior establishes that systemcalc owns
  `/Dc/Battery/TimeToGo` and sources it from `/TimeToGo` on the selected battery
  service. An MQTT `N/...` topic is an outbound notification, not a supported
  write mechanism. es-ESS owns neither D-Bus service.
- Commit `bb90d6f` removed the ineffective local notification injection and
  retained the estimate as a main-MQTT diagnostic at
  `es-ESS/TimeToGoCalculator/TimeToGo`. Zero power/SOC, incomplete telemetry,
  publish failure, and charge/discharge calculations are covered without
  stopping the worker.
- README, sample configuration, and service inventory now state that GX/VRM
  time-to-go requires the selected BMS to publish `/TimeToGo`; es-ESS does not
  create a competing owner. The original UI-restoration goal below is retained
  as review history but is superseded by this supported ownership decision.
- Production validation on Venus OS `v3.75` completed on 2026-07-15 with
  `TimeToGoCalculator=true`, `BatteryCapacityInWh=32000`, and
  `UpdateInterval=1000`. With natural battery discharge, all three required
  D-Bus inputs were present and main MQTT published
  `es-ESS/TimeToGoCalculator/TimeToGo=108556` seconds. The value was consistent
  with the observed changing discharge power, SOC, active SOC limit, and
  configured capacity. es-ESS remained healthy on the same PID with increasing
  uptime and no recent critical error, traceback, or exception. The optional
  live diagnostic observation is complete.

Goal:

Make `TimeToGoCalculator` publish a calculated value through a mechanism that
is verified on Venus OS `v3.75` and visible in the intended GX/VRM surface.

Problem:

The service calculates time-to-go and publishes MQTT messages, but its direct
D-Bus publication is commented out and README still labels the feature broken
since Venus OS 3.50. Hardware-free tests currently prove only that the existing
MQTT helper calls occur, not that Venus accepts or displays the value.

Evidence:

- `TimeToGoCalculator.py:64-70` contains the unresolved D-Bus publication TODO,
  commented-out publisher, and current local/main MQTT calls.
- `README.md:267-298` simultaneously marks the service Production Ready and
  warns that it is broken since 3.50.
- `tests/test_time_to_go_calculator.py` covers calculation, incomplete inputs,
  and MQTT calls without a Venus D-Bus/VRM integration contract.

Implementation:

- Establish from the supported Venus OS `v3.75` interface which service owns
  `/Dc/Battery/TimeToGo` and the supported write/publication mechanism.
- Characterize the current local MQTT topic and payload on a GX before
  replacing or retaining it.
- Implement the narrow verified publication path while preserving calculation
  units, missing-input behavior, main-MQTT diagnostic output, and service
  lifecycle.
- Do not create a competing D-Bus service or write an unrelated system path to
  force a UI value.

Files to change:

- `TimeToGoCalculator.py`
- `README.md`
- `docs/service-inventory.md` if its D-Bus/MQTT contract changes
- `BACKLOG.md` on completion

Files to add:

- None expected.

Tests:

- Extend `tests/test_time_to_go_calculator.py` for the selected publication
  boundary, exact path/topic and payload, charge/discharge values, zero power,
  missing telemetry, failure handling, and recovery.
- Add a stubbed D-Bus publisher/service only if that is the validated Venus
  mechanism; never require real hardware in unittest.

Expected coverage:

- Proves calculations reach the selected integration boundary correctly and
  incomplete telemetry cannot overwrite the last valid value.
- Existing main-MQTT diagnostics remain compatible unless explicitly
  documented otherwise.

Manual validation:

Log-only and read-only GX/VRM observation; no charging or hardware manipulation
is required.

Manual test steps:

1. Enable the service on Venus OS `v3.75` with stable battery telemetry.
2. Observe discharge and charge calculations in logs/main MQTT.
3. Confirm the same value appears at the authoritative D-Bus path and intended
   GX/VRM surface with correct seconds/format.
4. Briefly observe an unavailable input and confirm the last valid value is not
   replaced by an invalid calculation.

Risks and dependencies:

- Writing the wrong Venus namespace can be ignored silently or conflict with
  systemcalc ownership.
- The README warning must remain until live GX/VRM validation succeeds.
- No other backlog item must land first.

Open questions:

- What publication mechanism does Venus OS `v3.75` accept for this system
  value, and which UI surface is the required success criterion?

Done criteria:

- A documented, supported publication mechanism is implemented and covered.
- Live GX/VRM evidence confirms the calculated value is visible and updates.
- The contradictory README status is corrected only after that evidence.
- Full unittest suite passes.

### Completed 2026-07-15 - Decide And Align Wattpilot Hibernate-Mode Remote Control

Resolution:

- Selected the conservative existing-product boundary: with
  `HibernateMode=true` and no EV connected, es-ESS intentionally disconnects;
  remote VRM mode changes are unsupported while disconnected. Scheduled is a
  best-effort status probe, not a supported keep-awake/control path.
- Commit `e3dd6c1` removed the unresolved source TODO and aligned README,
  `config.sample.ini`, the service inventory, and the HTML guide without adding
  reconnect ownership, charger commands, or Manual/Auto authority changes.
- Documentation-contract and full-suite tests pass. This documentation-only
  resolution requires no Wattpilot hardware action.

Goal:

Establish one supported contract for remote mode/wake control while Wattpilot
hibernate is enabled, then make code and documentation agree with it.

Problem:

The controller records that switching mode can fail while hibernating. README
both says Scheduled Charging does not help because the Wattpilot immediately
hibernates again and presents Scheduled Charging as the wake-up path. The
maintained default is `HibernateMode=false`, but enabled installations lack a
single reliable operator contract.

Evidence:

- `FroniusWattpilot.py:673-676` contains the unresolved hibernate mode-switch
  TODO.
- `README.md:492` says Scheduled Charging does not resolve the known issue.
- `README.md:603` and `README.md:676` describe Scheduled Charging as the
  supported wake-up action.
- `config.sample.ini:126-131` says Scheduled Charging forces a wake-up.

Implementation:

- First reproduce the disconnected hibernate/VRM transition on the validated
  firmware/app baseline without a vehicle and record raw `lmo`, transport, and
  public mode timing.
- Choose one narrow result: implement a bounded wake/keepalive transition, or
  explicitly declare remote mode control unsupported while hibernate is
  enabled.
- If code changes, keep WebSocket reconnect ownership in `Wattpilot.py` and
  command policy in `FroniusWattpilot.py`; callbacks remain command-free.
- Preserve Manual ownership, the one-time Manual release exception, Auto/Eco
  command-authority checks, no-grid behavior, and the disabled default.

Files to change:

- `README.md`
- `config.sample.ini`
- `FroniusWattpilot.py` and/or `Wattpilot.py` only if implementation is chosen
- `docs/wattpilot-architecture.md` if command/reconnect responsibilities change
- `docs/service-inventory.md` if reconnect behavior changes
- `docs/system-guide.html`
- `BACKLOG.md` on completion

Files to add:

- None expected.

Tests:

- Extend `tests/test_wattpilot_command_boundary.py`,
  `tests/test_wattpilot_client.py`, and/or `tests/test_wattpilot_runtime_status.py`
  according to the selected contract.
- Cover disconnected hibernate, Scheduled request, bounded wake failure,
  recovery, no duplicate workers, Manual no-command behavior, and authority
  rejection before Auto.

Expected coverage:

- Proves the selected hibernate contract is deterministic and cannot widen
  Auto/Eco or Manual command authority.
- Proves documentation no longer promises mutually incompatible behavior.

Manual validation:

Fault simulation with the vehicle disconnected in a low-risk window.

Manual test steps:

1. Enable hibernate with the vehicle disconnected and wait for the documented
   idle state.
2. Request Scheduled/Auto/Manual only through the documented VRM surface.
3. Correlate request delivery, WebSocket wake/reconnect, raw mode, public mode,
   and absence of unintended current/start/phase commands.
4. Confirm timeout/failure behavior is bounded and actionable.

Risks and dependencies:

- An automatic keepalive can defeat the purpose of hibernate or create
  reconnect-worker overlap.
- A mode transition must never command normal Manual charging or bypass native
  `fup`/`ful` authority checks.
- Complete this decision before finalizing hibernate text in the documentation
  alignment item.

Open questions:

- Should remote mode control be supported at all while hibernate is enabled,
  or is documented incompatibility the intended product boundary?

Done criteria:

- One hibernate remote-control contract is selected from reproduced evidence.
- Code, sample, README, architecture, inventory, and HTML guidance agree where
  applicable.
- Manual and Auto/Eco safety invariants remain covered.
- Full unittest suite passes.

### Completed 2026-07-15 - Audit And Enforce Maintained Documentation Contracts

Completion record:

- Commit `e3dd6c1` corrected the singular `MqttTemperature` service flag,
  `[MqttExporter:*]` prefix, Shelly PM service flag, all four stale Wattpilot
  example values, and conflicting hibernate promises.
- Contract tests now compare the complete maintained README Wattpilot table and
  the system-guide Wattpilot block against `config.sample.ini`, plus canonical
  service-specific names and the hibernate boundary. No runtime default changed.

Goal:

Make every maintained documentation surface agree with runtime service names,
`config.sample.ini`, current defaults/examples, and supported behavior, with
automated checks for high-value contracts.

Problem:

The prior alignment review spot-checked only a subset of values and incorrectly
reported the documentation clean. README contains confirmed service-name,
section-name, copy/paste, default/example, and hibernate contradictions. The
HTML guide and service inventory match the checked Wattpilot values/service
names today, but were not audited comprehensively and should not be assumed
correct from shallow checks.

Evidence:

- `README.md:320` documents the nonexistent plural `MqttTemperatures` service
  flag instead of `MqttTemperature`.
- `README.md:354` documents `[MattExporter:uniqueKey]` instead of
  `[MqttExporter:uniqueKey]`.
- `README.md:1051` tells Shelly PM users to enable `Shelly3EMGrid`.
- `README.md:682`, `README.md:697`, and `README.md:701-704` drift from
  maintained Wattpilot sample values such as `EvPriorityMinSoc=50`,
  `SurplusDropGraceSeconds=30`, and charge-completion thresholds.
- `docs/system-guide.html:793-817` currently matches those checked sample
  values; `docs/service-inventory.md:112-119` currently names the checked
  active services correctly.
- `tests/test_config_contract.py` checks the global README active-service table
  but not each service-specific configuration row or maintained HTML values.

Implementation:

- Compare README, `config.sample.ini`, the HTML guide, service inventory, and
  runtime service loading line-by-line for service flags, section names, keys,
  example/default values, units, supported ranges, active/dormant status, and
  integration contracts.
- Correct confirmed mismatches without changing runtime behavior or defaults.
- Treat site examples explicitly as examples; do not silently convert them
  into defaults.
- Extend contract tests for canonical service-specific flag/section names and
  the high-value Wattpilot values duplicated in maintained documentation.
- Resolve hibernate text from the dedicated decision item rather than guessing.

Files to change:

- `README.md`
- `docs/system-guide.html`
- `docs/service-inventory.md`
- `config.sample.ini` only if the audit proves the canonical sample is wrong
- `tests/test_config_contract.py`
- `BACKLOG.md` on completion

Files to add:

- None expected.

Tests:

- Extend `tests/test_config_contract.py` for singular runtime service flags,
  service-specific section prefixes, Shelly PM enable guidance, documented
  Wattpilot defaults/examples, and active/dormant inventory alignment.
- Keep checks semantic and narrowly parsed rather than snapshotting entire
  prose or HTML files.

Expected coverage:

- Proves the previously missed service/config mismatches cannot recur silently.
- Proves maintained Wattpilot examples remain aligned where they are intended
  to represent sample defaults.

Manual validation:

Hardware not needed; review rendered Markdown/HTML after automated checks.

Manual test steps:

1. Run the configuration-contract tests.
2. Render README and `docs/system-guide.html` and inspect tables, links, code
   blocks, and special characters.
3. Confirm no runtime/configuration file changed merely to match stale prose.

Risks and dependencies:

- Over-broad prose snapshot tests would be brittle; test exact contracts only.
- Changing a documented example can be mistaken for a runtime default change;
  label intent explicitly.
- The hibernate decision item should land first or provide the exact text used
  here.

Open questions:

- Which README table values are intentionally site-shaped examples rather than
  maintained defaults? Preserve that distinction during the audit.

Done criteria:

- All four maintained surfaces are fully audited and confirmed mismatches fixed.
- Automated tests cover service names, section names, and selected duplicated
  defaults/contracts.
- Rendered documentation remains readable and internally consistent.
- Full unittest suite passes.

### Completed 2026-07-15 - Restrict Daily-Report D-Bus Reads To Exact Paths

Completion record:

- Commit `4b50c6a` defines an immutable allowlist containing every declared
  Wattpilot snapshot pair plus the exact Venus timezone pair. Arbitrary
  Wattpilot paths, all generic system paths, other services, writes,
  non-absolute paths, and extra arguments are rejected before subprocess use.
- Tests accept every declared pair and preserve the existing `svstat`, timeout,
  circuit-breaker, and command-free behavior.

Goal:

Make the daily report's read-only subprocess boundary permit only the exact
service/path pairs used by its current snapshot and timezone functions.

Problem:

`_run_readonly_command()` restricts commands to `GetValue` and a small service
set, but accepts any slash-prefixed Wattpilot/system path. Current callsites use
fixed tuples, so this is not an active vulnerability; it is a latent defense-
in-depth gap if the helper is later reused with dynamic input.

Evidence:

- `scripts/es-ess-daily-report.py:883-909` checks the exact settings timezone
  path but only `startswith("/")` for Wattpilot/system services.
- `scripts/es-ess-daily-report.py:65-90` defines the actual Wattpilot snapshot
  path tuple.
- `tests/test_es_ess_daily_report.py:501-558` rejects writes and the wrong
  settings path but accepts only one example Wattpilot read; arbitrary
  Wattpilot/system read rejection is not covered.

Implementation:

- Define an immutable set of exact `(service, path)` pairs from
  `SNAPSHOT_DBUS_PATHS` plus the Venus timezone pair.
- Remove the unused generic system-service allowance unless an actual fixed
  read requires it.
- Keep `svstat`, `GetValue`, two-second timeouts, timeout circuit breaker, and
  command-free analyzer isolation unchanged.

Files to change:

- `scripts/es-ess-daily-report.py`
- `tests/test_es_ess_daily_report.py`
- `docs/es-ess-daily-report.md` only if the documented read set changes
- `BACKLOG.md` on completion

Files to add:

- None expected.

Tests:

- Extend `tests/test_es_ess_daily_report.py` to accept every declared snapshot
  path and the exact timezone path.
- Reject arbitrary Wattpilot paths, all generic system paths, other services,
  writes, extra arguments, and non-absolute paths without invoking the runner.

Expected coverage:

- Proves future callsites cannot expand D-Bus read scope accidentally.
- Preserves the existing command-free monitoring contract and snapshot output.

Manual validation:

Hardware not needed; unit tests are the verifier. An optional log-only GX run
may confirm the same snapshot fields remain available.

Manual test steps:

1. Run focused daily-report tests.
2. Optionally run one current snapshot on GX and confirm all documented paths
   still populate without an allowlist rejection.

Risks and dependencies:

- Adding a new legitimate snapshot path will require an intentional allowlist
  and test update.
- No other backlog item must land first.

Open questions:

- None.

Done criteria:

- Only exact current D-Bus reads can reach `subprocess.run()`.
- Existing snapshot and timezone behavior remains unchanged.
- Full unittest suite passes.

### Completed 2026-07-15 - Evaluate Low-Risk Lifecycle And Diagnostic-Script Hygiene

Completion record:

- Retained exact-command emergency/uninstall behavior: adding shared PID
  lifecycle machinery would increase risk without evidence of a practical
  defect. No lifecycle script changed.
- Retained the private `ConfigParser._sections` access because public mapping
  APIs include inherited `[DEFAULT]` keys, but replaced private boolean
  conversion with public `getboolean()` and documented the explicit-key reason.
- Commit `4b50c6a` labels Paho/websocket checks as the Wattpilot external
  dependency subset, distinguishes missing config from unreadable/malformed
  existing config, and adds `python3` fallback to the health monitor. Focused
  static/behavioral and full-suite tests pass.

Goal:

Decide from evidence whether three low-severity script internals merit narrow
hardening without changing supported runtime behavior.

Problem:

The emergency/uninstall scripts do not use the PID/start-time verification in
`restart.sh`; the daily report uses private `ConfigParser` internals to avoid
inherited defaults; and its current dependency snapshot names only Paho and
websocket. Exact process matching, intentional uninstall semantics, explicit
configuration warnings, and the validated dependency scope make these hygiene
observations rather than confirmed production defects.

Evidence:

- `kill_me.sh:4-6` and `uninstall.sh:15-21` use exact-command `pgrep` followed
  by signals; `restart.sh:14-65` also records `/proc/<pid>/stat` start time.
- `scripts/es-ess-daily-report.py:816-825` uses private `_sections` and
  `_convert_to_boolean` so `[DEFAULT]` documentation keys are not interpreted
  as service flags.
- `scripts/es-ess-daily-report.py:1056-1068` reports only `paho.mqtt.client`
  and `websocket` dependency availability.

Implementation:

- Audit each observation separately and close any part whose current behavior
  is already the safer supported contract.
- If useful, share the verified PID/start-time predicate with lifecycle scripts
  without weakening emergency-stop or uninstall behavior.
- Replace private ConfigParser access only with a public approach that still
  excludes inherited `[DEFAULT]` keys exactly.
- Either label the dependency result explicitly as the Wattpilot external
  dependency subset or derive checks from enabled services without importing
  production modules or initiating network/device access.

Files to change:

- `kill_me.sh`, `uninstall.sh`, and/or `restart.sh` only for an approved
  lifecycle change
- `scripts/es-ess-daily-report.py`
- `tests/test_es_ess_daily_report.py`
- lifecycle/orchestration tests as appropriate
- relevant script documentation if output or semantics change
- `BACKLOG.md` on completion

Files to add:

- None expected.

Tests:

- Preserve exact process-command and start-time behavior with shell/static
  lifecycle tests if PID hardening proceeds.
- Extend daily-report tests for `[DEFAULT]` exclusion using only public parser
  behavior and for explicitly scoped dependency output.
- Keep all tests hardware-free and command/network-free.

Expected coverage:

- Proves any accepted cleanup preserves emergency, uninstall, configuration,
  and read-only diagnostic semantics.
- Allows evidence-based closure without code when a proposed cleanup has no
  practical or compatibility benefit.

Manual validation:

Hardware not needed for parser/dependency changes. Any lifecycle change needs a
log-only staging/GX uninstall or restart rehearsal with configuration backup
verified first.

Manual test steps:

1. Run focused script and orchestration tests.
2. If lifecycle code changes, exercise it only on staging or after confirming a
   current external `config.ini` backup.
3. Confirm only the exact es-ESS process is signaled and uninstall backup/
   cleanup behavior remains unchanged.

Risks and dependencies:

- Refactoring emergency/uninstall process selection can reduce reliability for
  negligible practical benefit.
- Public ConfigParser alternatives may reintroduce inherited defaults.
- A broad dependency scanner can import side-effectful production modules;
  retain `find_spec()`-style read-only checks.
- No other backlog item must land first.

Open questions:

- Whether each of the three observations is worth changing after focused audit;
  code change is not required merely to close this conditional item.

Done criteria:

- Each observation has an explicit keep/change decision with evidence.
- Any accepted change is narrow, tested, and documented without widening
  process or dependency behavior.
- Full unittest suite passes.

### Completed 2026-07-15 - Measure Daily-Report Peak Memory And Retain Complete Evidence

Completion record:

- The supported Venus OS `v3.75` GX processed a representative APP_DEBUG
  `current.log` containing 210,294 lines/records and 29,918,910 bytes while
  es-ESS remained online.
- The report's peak resident set was 107,656 KB from an initial 642,456 KB of
  available memory. Even the conservative subtraction leaves approximately
  522 MiB available; the post-run reading recovered to 640,836 KB.
- Log loading took 53.66 seconds and analysis took 25.85 seconds. The report
  exited `2` because the whole current-day input contained earlier operational
  anomalies, not because of a resource limit or report failure.
- The supervised es-ESS process remained PID 2494 and its uptime advanced from
  525 to 636 seconds during the run.
- Decision: close measurement-only. Do not add line, continuation, record, or
  byte caps: the observed GX workload has ample headroom, and arbitrary limits
  could discard the safety evidence this report is intended to preserve.
- The implementation had already passed 67 focused daily-report tests and the
  complete 415-test hardware-free suite before this production measurement.

Goal:

Confirm that the revised daily report has safe memory headroom on the supported
GX baseline and add explicit resource bounds only if measurement demonstrates
a real need.

Problem:

The revised loader streams files and the analyzer avoids prior quadratic scans,
but retains every selected `LogRecord`; traceback continuations can also grow a
single record without an explicit size limit. Production successfully processed
195,892 records, so this is a conditional resource investigation rather than a
confirmed defect. Arbitrary truncation could discard safety evidence and would
be worse than the current behavior.

Evidence:

- `scripts/es-ess-daily-report.py:489-545` reads line-by-line but retains
  selected records and appends continuation text to the current record.
- `BACKLOG.md:140-162` records the final 195,892-record GX run in 1m16s and a
  synthetic 189,000-record analysis benchmark after the performance rewrite.
- No current constant or test defines maximum line, continuation, record count,
  byte budget, or peak resident memory.

Implementation:

- Measure peak RSS, available memory, input bytes/lines, retained records,
  loader time, and analysis time on a representative large APP_DEBUG day while
  es-ESS remains running.
- If headroom is adequate, record the evidence and close without production
  changes.
- If not, design bounded line/continuation/record or byte handling from measured
  limits. Any skipped/truncated evidence must force an explicit `INCOMPLETE`
  result, report exact counts/bytes, preserve JSON validity, and never silently
  claim `GOOD`.
- Do not reintroduce full-file reads, quadratic scans, or size-based deletion of
  source logs.

Files to change:

- `BACKLOG.md` for measurement-only closure
- `scripts/es-ess-daily-report.py`, `tests/test_es_ess_daily_report.py`,
  `docs/es-ess-daily-report.md`, README, and HTML guide only if bounds are
  justified and implemented

Files to add:

- None expected.

Tests:

- For measurement-only closure, rerun focused daily-report tests and retain the
  GX measurement summary.
- If bounds are implemented, add oversized single-line, long continuation,
  record/byte-boundary, explicit `INCOMPLETE`, progress, JSON, and normal-large-
  input regression tests.

Expected coverage:

- Establishes whether the theoretical unbounded structures are an operational
  risk on the supported GX rather than assuming from source size.
- If limits land, proves evidence loss is always visible and cannot yield a
  false successful report.

Manual validation:

Log-only and safe in production: run the read-only report while measuring the
process and confirming es-ESS stays healthy.

Manual test steps:

1. Select a retained APP_DEBUG day at least as large as the validated
   approximately 195,000-record workload.
2. Record report peak RSS, free memory, input size/lines, retained records,
   loader/analysis duration, exit result, and es-ESS PID/health before and after.
3. Decide from measured headroom whether implementation is required.
4. If bounds are later added, repeat and confirm any triggered limit reports
   `INCOMPLETE` with exact truncation evidence.

Risks and dependencies:

- Arbitrary limits can discard the evidence the report exists to analyze.
- Running multiple large reports concurrently can distort memory evidence;
  measure one controlled process.
- The final threshold, if any, requires observed GX memory headroom rather than
  a desktop-derived constant.
- No other backlog item must land first.

Open questions:

- What minimum free-memory headroom should be retained on the production Cerbo
  GX while the report runs?

Done criteria:

- Peak memory and system headroom are recorded on a representative GX workload.
- The item closes measurement-only when headroom is safe, or measured,
  transparent `INCOMPLETE` bounds are implemented and documented.
- es-ESS remains healthy throughout the validation.
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

No unfinished implementation items remain.

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

No implementation-stage manual validation remains. Do not force grid import,
disconnect a production grid, interrupt critical telemetry, or alter the
production energy system solely to reproduce historical safety branches.

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
