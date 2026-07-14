# es-ESS Service Inventory

This note maps the current es-ESS service modules and integration boundaries.
It is developer-facing context for app-wide documentation, config cleanup,
service refactors, and reviews. It does not introduce new behavior.

Update this file whenever service initialization, `[Services]` flags, config
sections, D-Bus service contracts, MQTT topics, external dependencies,
grid-setpoint ownership, or active/dormant service status changes.

For Wattpilot command policy and safety invariants, also read
`docs/wattpilot-architecture.md`. For read-only post-deploy and post-firmware
operator evidence, use `scripts/es-ess-health-monitor.sh`; install and usage
steps are in `docs/es-ess-health-monitor.md`.

## Runtime Service Loading

`es-ESS.py` owns service startup. During `_initializeServices()`, it calls
`_checkAndEnable()` for services listed in `[Services]`. Each enabled service is
imported by module/class name, created, and then initialized through the common
`esESSService` lifecycle:

- `initDbusSubscriptions()`
- `initDbusService()`
- `initMqttSubscriptions()`
- `initWorkerThreads()`
- `initFinalize()`

Before MQTT, D-Bus, or service initialization, `_validateConfiguration()`
rejects missing, unreadable, or malformed configuration files before applying
version migrations. Startup then verifies the mandatory `[Common]`, `[Mqtt]`,
and active `[Services]` bootstrap keys and their conversion types before
constructing MQTT clients, threads, D-Bus services, or integration services.
It also validates bounded/cross-field Wattpilot values, positive service update
intervals, positive device polling intervals, MQTT PV stale/zero-feed-in
values, common thread/HTTP values, TLS trust modes, and configured combined
grid-setpoint bounds. Invalid bootstrap values are
logged together at CRITICAL level and startup exits with status 1; optional
sections and settings that already have runtime defaults remain compatible when
absent.

Before constructing the runtime at all, `RuntimeCompatibility.py` also requires
the GX device to report the exact supported clean Venus OS release, `v3.75`. A
missing, qualified, or different version exits with status
1 before services, MQTT, or grid-setpoint writes begin. The Wattpilot service
separately requires firmware `42.5` from
`fwv` telemetry before its common `setValue` command boundary opens. The
Solar.wattpilot app `2.1.0` baseline is operator-verified because the app version
is not visible to es-ESS.

The runtime also owns the shared D-Bus monitor, main MQTT client, local Venus
MQTT client, worker scheduling, service messages, and combined grid-setpoint
requests.

## Module Layout

The active service modules intentionally remain in the repository root for now.
`es-ESS.py` loads services by a root module/class name pair such as
`FroniusWattpilot` -> `FroniusWattpilot.py`, and existing tests and deployment
scripts also assume direct root-module imports from `/data/es-ESS`.

Moving Fronius or Wattpilot modules into a package would require a standalone
compatibility refactor that preserves those service names, import paths, tests,
and Venus OS startup behavior. Do not combine that package refactor with
Wattpilot control, safety, phase-switching, or runtime-status changes.

## Active Initialized Services

These services are actively initialized by `es-ESS.py` when their `[Services]`
flag is set to `true`.

| Service | Module | Primary config | Main role | Integration boundaries |
| --- | --- | --- | --- | --- |
| `SolarOverheadDistributor` | `SolarOverheadDistributor.py` | `[SolarOverheadDistributor]`, `[Common]`, `HttpConsumer:*`, `MqttConsumer:*` | Calculates available PV surplus, battery reservation, and per-consumer allowances. | Reads Victron system grid and battery D-Bus paths, publishes settings and fake battery reservation D-Bus services, subscribes and publishes under `es-ESS/SolarOverheadDistributor/Requests/...`, and controls configured HTTP/MQTT consumers with bounded `[Common] HttpRequestTimeout` requests outside the shared consumer-map lock. |
| `TimeToGoCalculator` | `TimeToGoCalculator.py` | `[TimeToGoCalculator]`, `[Common]` | Calculates battery time-to-go when the system does not provide it. | Reads Victron system battery power, SOC, and active SOC limit D-Bus paths; skips incomplete telemetry without publishing stale calculations, then resumes local/main MQTT publication when all inputs recover. |
| `FroniusSmartmeterJSON` | `FroniusSmartmeterJSON.py` | `[FroniusSmartmeterJSON]` | Exposes a Fronius smart meter as a Victron grid meter. | Polls the Fronius JSON API over HTTP and publishes a `com.victronenergy.grid` D-Bus service. |
| `MqttExporter` | `MqttExporter.py` | `MqttExporter:*` | Exports selected D-Bus values to main MQTT. | Subscribes to configured D-Bus service/path pairs and republishes on configured MQTT topics on change or at 1 s, 10 s, or 60 s intervals. |
| `FroniusWattpilot` | `FroniusWattpilot.py` | `[FroniusWattpilot]` | Integrates and controls a Fronius Wattpilot EV charger. | Owns Victron EV-charger D-Bus paths, including session energy/time compatibility paths, Wattpilot WebSocket commands through `Wattpilot.py`, SolarOverheadDistributor requests, grid telemetry safety checks, runtime-status publication, and shutdown behavior. The underlying `Wattpilot.py` client owns a single worker reconnect loop for WebSocket outages. See `docs/wattpilot-architecture.md` before changing it. |
| `MqttTemperature` | `MqttTemperature.py` | `MqttTemperature:*` | Exposes MQTT temperature sensors in VRM/D-Bus. | Subscribes to configured MQTT value, humidity, and pressure topics; publishes one `com.victronenergy.temperature` D-Bus service per configured sensor. |
| `NoBatToEV` | `NoBatToEV.py` | `[NoBatToEV]`, `[Common]` | Offloads EV load to grid-setpoint requests so an AC-out EV charge does not drain the home battery. | Reads Victron system consumption, PV, phase-count, optional relay, and EV-charger power data; registers or revokes shared grid-setpoint requests through the es-ESS runtime. |
| `Shelly3EMGrid` | `Shelly3EMGrid.py` | `[Shelly3EMGrid]` | Exposes a Shelly 3EM as a Victron grid meter. | Polls the Shelly HTTP status API and publishes a `com.victronenergy.grid` D-Bus service; net-meter counters use atomic persistence, corrupt-value recovery, and exclude unknown failed-poll intervals. |
| `ShellyPMInverter` | `ShellyPMInverter.py` | `ShellyPMInverter:*` | Exposes one or more Shelly PM devices as PV inverters. | Polls Shelly Gen2 HTTP RPC status endpoints and publishes one `com.victronenergy.pvinverter` D-Bus service per configured device. |
| `MqttPVInverter` | `MqttPVInverter.py` | `[MqttPvInverter]`, `MqttPVInverter:*` | Exposes MQTT-reported PV inverters in VRM/D-Bus. | Subscribes to configured MQTT voltage, current, power, and energy topics; publishes `com.victronenergy.pvinverter` D-Bus services; optionally publishes OpenDTU limit commands for experimental zero-feed-in control. A zero target still publishes `0%`; incomplete consumption telemetry keeps the last limit, while a fully silent inverter is invalidated after the configured timeout and contributes zero cached power. |

## Dormant Or Commented Services

These modules exist, but `es-ESS.py` does not currently call `_checkAndEnable()`
for them. Treat them as dormant unless a task explicitly reactivates them and
adds config, docs, and tests for the new active behavior.

| Service | Module | Observed behavior if re-enabled | Current runtime status |
| --- | --- | --- | --- |
| `MqttDC` | `MqttDC.py` | Reads `MqttDC:*` sections, subscribes to MQTT power, voltage, and current topics, and publishes `com.victronenergy.dcsystem` D-Bus services. | Intentionally unavailable: commented out in `es-ESS.py` and absent from the maintained sample and active-service README table. Legacy user flags are ignored and preserved for compatibility. |
| `ChargeCurrentReducer` | `ChargeCurrentReducer.py` | Reads battery and grid D-Bus values and writes local Venus MQTT grid-setpoint commands to reduce battery charge current. | Intentionally unavailable: commented out in `es-ESS.py` and absent from the maintained sample and active-service README table. It requires a separate safety and shared-setpoint-ownership implementation before reactivation. |
| `FroniusSmartmeterRS485` | `FroniusSmartmeterRS485.py` | Creates a grid-meter D-Bus service and has experimental Modbus RTU setup in `initFinalize()`; its worker is commented out. | Intentionally unavailable: commented out in `es-ESS.py` and absent from the maintained sample and active-service README table. Legacy user flags are ignored and preserved for compatibility. |
| `Grid2Bat` | none in this checkout | No module is present in this checkout. | Unavailable: its commented runtime hook is retained as historical context, but the stale sample flag was removed. Legacy user flags are ignored and preserved for compatibility. |

## Shared Integration Patterns

### D-Bus publishers

Several services create Victron-compatible D-Bus services through
`VeDbusService`:

- Grid meters: `FroniusSmartmeterJSON`, `Shelly3EMGrid`, dormant
  `FroniusSmartmeterRS485`.
- PV inverters: `ShellyPMInverter`, `MqttPVInverter`.
- Temperature sensors: `MqttTemperature`.
- Solar overhead status and reservation monitor: `SolarOverheadDistributor`.
- EV charger and runtime status: `FroniusWattpilot` and
  `WattpilotRuntimeStatus`.
- Dormant DC systems: `MqttDC`.

For a Fronius Wattpilot transport outage, the supported es-ESS user-visible
surfaces are the EV-charger detail paths (`/StatusLiteral`, `/CustomName`),
the Wattpilot runtime-status D-Bus/MQTT contract, es-ESS service messages, and
SolarOverheadDistributor consumer messages. The standard Venus/GX EVCS overview
tile is not forced with synthetic `/Status` or `/Mode` values.

When changing any published D-Bus path, check README/config expectations,
runtime-status consumers, the production health monitor, and VRM/Cerbo
compatibility.

### D-Bus readers

Services consume Victron system state through `DbusSubscription` registered via
`esESSService`:

- `SolarOverheadDistributor` reads grid power, battery power, and SOC.
- `TimeToGoCalculator` reads battery power, SOC, and active SOC limit.
- `MqttExporter` reads configured service/path pairs.
- `NoBatToEV` reads EV power, consumption, PV power, phase count, and optional
  relay state.
- `MqttPVInverter` reads consumption, phase count, SOC, and PV-disabled state
  for optional inverter control.
- Dormant `ChargeCurrentReducer` reads battery, grid voltage, and CGwacs
  setpoint paths.

### MQTT boundaries

The main MQTT broker is used for es-ESS status, configured exports, MQTT-backed
sensors/inverters, and SolarOverheadDistributor requests. The local Venus MQTT
broker is used for writes to Venus settings or system values, such as
TimeToGoCalculator and grid-setpoint commands.

When TLS is enabled, each client has an explicit trust mode. `Required` uses
certificate and hostname verification with either system trust or a configured
CA file. `CertificateOnly` requires a CA/certificate file but explicitly
disables hostname verification for pinned self-signed deployments. `Insecure`
is an explicit warning-producing legacy mode; there is no silent fallback from
verification failure.

The SolarOverheadDistributor request namespace is shared by internal consumers
such as Wattpilot and by external/scripted consumers:

`es-ESS/SolarOverheadDistributor/Requests/{consumer}/...`

Changes under this namespace can affect dashboards, scripted consumers, MQTT
consumers, HTTP consumers, and Wattpilot Auto/Eco charging.

### HTTP and device polling

HTTP polling services use the `requests` library and publish `Connected=0` or
null values after their existing consecutive-failure thresholds. Timeouts,
connection/request failures, and malformed or incomplete required payloads all
feed the same threshold; one transient failure retains the current debounce:

- `FroniusSmartmeterJSON` polls the Fronius inverter meter JSON API.
- `Shelly3EMGrid` polls the Shelly 3EM `/status` endpoint.
- `ShellyPMInverter` polls Shelly Gen2 `Switch.GetStatus` RPC endpoints.
- `SolarOverheadDistributor` can call configured HTTP consumer control,
  status, and power URLs with `[Common] HttpRequestTimeout`.

The dormant `FroniusSmartmeterRS485` HTTP polling path also reads
`[Common] HttpRequestTimeout` if it is re-enabled.

Keep timeout behavior, poll frequency, and failure publication in mind when
changing these services; stale or null telemetry can influence downstream
energy decisions.

### Grid-setpoint ownership

The es-ESS runtime combines grid-setpoint requests from services and publishes
one local Venus MQTT write to `/Settings/CGwacs/AcPowerSetPoint`. Active service
use in this checkout:

- `NoBatToEV` registers and revokes grid-setpoint requests through the shared
  runtime API.

The final additive value is clamped to the configured site-approved
`[Common] GridSetPointMinW..GridSetPointMaxW` range. Configuration migration
defaults both limits to the existing baseline setpoint, so dynamic adjustments
remain fail-closed until an operator commissions a wider range.

Dormant `ChargeCurrentReducer` writes local Venus MQTT setpoints directly and
uses a hard-coded VRM portal ID in its current file. Do not reactivate or mix it
with shared setpoint ownership without a focused review.

## Follow-Up Gaps

Dormant service intent is now explicit: dormant and missing services remain
unavailable unless a separate implementation task reactivates them with config,
documentation, tests, and manual validation. Legacy flags in existing user
configurations remain harmless ignored compatibility data.

Remaining inventory observation:

- Some service names and config section casing differ, such as
  `[MqttPvInverter]` for global settings and `MqttPVInverter:*` for instances.
  Preserve compatibility unless a migration task explicitly changes it.
