# es-ESS
es-ESS (equinox solutions Energy Storage Systems) is an extension for Victrons VenusOS running on GX-Devices.
es-ESS brings various functions starting with tiny helpers, but also including major functionalities.

es-ESS is structered into individual services and every service can be enabled or disabled. So, only certain
features can be enabled, based on your needs.

Services are marked according to their current development state: 

> :white_check_mark: Production Ready: Feature is finished, tested and fully operable.

> :large_orange_diamond: Release-Candiate-Version: Feature is still undergoing development, but current version is already satisfying.

> :red_circle: Work-in-progress, beta: Feature is a beta, may have bugs or not work at all. Only use if you are a dev and want to contribute.

# About me

I'm a software engineer since about 20 years, pretty new to python, tho. es-ESS is provided free of charge and created during my spare-time after work. 
Feel free to create [issues](https://github.com/realdognose/es-ESS/issues) for questions or bugs, but bear with me that i cannot provide a 24/7 support or guarantee some sort of 8h response time. 
If you are a developer yourself and want to help to improve es-ESS, feel free to do so and create pull requests.

I've switched to a Victron-System some months ago, and immediately digged into customizing it. Lot has been done, Lot is still todo. Since I will run this 
system for at least 10ish years, there will be plenty of updates and/or bugfixes in the future.

# Table of Contents
- [Setup](#setup) - General setup process and requirements for es-ESS.
- [Developer Notes](#developer-notes) - Contributor guidance and Wattpilot architecture boundaries.
- [TimeToGoCalculator](#timetogocalculator) - Tiny helper filling out the `Time to Go` field in VRM, when BMS do not report this value.
- [MqttTemperatures](#mqtttemperatures) - Display various temperature sensors you have on mqtt in VRM.
- [MqttExporter](#mqttexporter) - Export selected values form dbus to your MQTT-Server.
- [MqttPvInverter](#mqttpvinverter) - Use values available on mqtt to mimic a PVInverter in VenusOS
- [FroniusWattpilot](#FroniusWattpilot) - Full integration of Fronius Wattpilot in VRM / cerbo, including bidirectional remote control and improved eco mode.
- [NoBatToEV](#nobattoev) - Avoid discharge of your home-battery when charging your ev with an `ac-out` connected wallbox.
- [Shelly3EMGrid](#shelly3emgrid) - Use a shelly 3 EM as grid meter.
- [ShellyPMInverter](#shellypminverter) - Use a shelly PM (second generation) as meter for any inverter. (Single phased, phase configurable)
- [SolarOverheadDistributor](#solaroverheaddistributor) - Utility to manage and distribute available solar overhead between various consumers.
  - [Scripted-SolarOverheadConsumer](#scripted-solaroverheadconsumer) - Consumers managed by external scripts can to be more complex and join the solar overhead pool.
  - [NPC-SolarOverheadConsumer](#npc-solaroverheadconsumer) - Manage consumers on a simple on/off level, based on available overhead. No programming required.
- [Production health monitor](#production-health-monitor) - Read-only GX health snapshot after firmware updates, deploys, config changes and Wattpilot validation runs.
- [Dormant service modules](#dormant-service-modules) - Legacy code that is retained for reference but is not available for configuration.
- [This and that](#this-and-that) - Various information that doesn't fit elsewhere.
- [F.A.Q](#faq) - Frequently Asked Questions

# Developer Notes

Wattpilot control is safety-sensitive. Before changing or reviewing Wattpilot
behavior, read [docs/wattpilot-architecture.md](docs/wattpilot-architecture.md).
That note documents the current module boundaries, command side-effect
ownership, runtime-status contract, and safety invariants that future
implementation tasks must preserve and update when they change.

GitHub Actions CI is defined in
[.github/workflows/ci.yml](.github/workflows/ci.yml). It runs on pull requests
and on pushes to `main`, using Python 3.12 to syntax-check the repository,
validate the `config.sample.ini` contract, and run the hardware-free unittest
suite.

`MqttDC`, `ChargeCurrentReducer`, and `FroniusSmartmeterRS485` are dormant
legacy modules: the runtime does not initialize them and the maintained sample
does not expose service flags for them. `Grid2Bat` is unavailable because no
module exists in this checkout. Legacy user configuration flags for these names
are left untouched for compatibility but are ignored; do not add or enable
them in new configurations.

# Setup
Your system needs to match the following requirements in order to use es-ESS:
- Be an ESS
- Have a mqtt server (or the use builtin one, to minimize system load an external mqtt is recommended)
- Have shell access enabled and know how to use it. (See: https://www.victronenergy.com/live/ccgx:root_access)

## Supported runtime versions

This checkout deliberately fails closed outside its explicitly approved runtime
versions. Venus OS v3.75 is the only approved clean Venus OS runtime in this
checkout. The upgrade, idle/no-vehicle, Manual charging, Manual current-change,
Manual recovery, and supervised Auto/Eco PV-surplus daylight checks passed on a
Cerbo GX running Venus OS v3.75 build `20260624163305`:

| Component | Approved version | Runtime enforcement |
| --- | --- | --- |
| Venus OS on the GX device | `v3.75` | This exact clean release is required before es-ESS constructs services, connects MQTT, or writes the grid setpoint. A missing or different version exits with status 1. Qualifiers such as `v3.75~1` do not match the clean release. |
| Fronius Wattpilot firmware | `42.5` | Read from Wattpilot `fwv` telemetry. Until it matches exactly, every es-ESS Wattpilot `setValue` command is blocked and Auto/Eco reports a compatibility fault. Other es-ESS services may continue. |
| Fronius Solar.wattpilot mobile app | `2.1.0` | Commissioning baseline only. The app version is not exposed to es-ESS and cannot be checked automatically. |

The compatibility constants and version comparison live in
`RuntimeCompatibility.py`. Do not change them merely to bypass a failed start.
First validate Manual-mode ownership, command names and values, PV-only starts,
current limits, phase switching, grid-import stops, battery-assist bounds,
telemetry freshness, reconnection, D-Bus/MQTT contracts, and graceful shutdown
on the proposed new versions. Then update the baseline and tests in the same
change.

For preparation, online/offline upgrade steps, post-update checks, and both
stored-firmware and manual rollback procedures, see
[`docs/cerbo-gx-firmware-upgrade-and-rollback.md`](docs/cerbo-gx-firmware-upgrade-and-rollback.md).
If a rollback boots an older Venus OS release, restore an es-ESS checkout whose
`RuntimeCompatibility.py` explicitly supports that firmware before starting
services.

The `?version=1.2.9` value used by the optional Wattpilot cloud WebSocket URL is
a protocol/client identifier. It is not the Solar.wattpilot mobile app version
and must not be changed to `2.1.0`.

On a Wattpilot mismatch es-ESS intentionally sends no best-effort stop command,
because command semantics are precisely what is unvalidated. Use the Wattpilot
app to stop or select Manual when necessary, and restore firmware `42.5` before
returning Auto/Eco control to es-ESS. A high native start threshold is not a
command-ownership boundary. Fronius documents that stored firmware can
be selected again after an update and that the mobile app may also need an
update after firmware changes.

Run the following lines of code on your gx device: 

```
wget https://github.com/AndreiContributor/es-ESS/archive/refs/heads/main.zip
unzip main.zip "es-ESS-main/*" -d /data
mv /data/es-ESS-main /data/es-ESS
chmod a+x /data/es-ESS/install.sh
/data/es-ESS/install.sh
rm main.zip
```

`es-ESS` will automatically start - with the default configuration with all services DISABLED. You can now start to modify the file `/data/es-ESS/config.ini` as required. 
I recommend to complete configuration of a single service, then restart and validate functionality. If you rush through the (quite huge) configuration in a single go, and it
is not working at the end, it may become hard to find the error without starting over.

Handy commands to use during configuration and in generall: 

Restart es-ESS (gracefully - config changes require restart!). The script waits
up to 10 seconds for the original process to exit and applies a narrowly
targeted SIGKILL only if that verified process remains stuck:

```
/data/es-ESS/restart.sh
```

Emergency-stop es-ESS with SIGKILL only if graceful restart does not work:
```
/data/es-ESS/kill_me.sh
```

Uninstall es-ESS:
```
/data/es-ESS/uninstall.sh
```
The uninstall script stops es-ESS, removes the service symlink and `rc.local`
startup entry, and removes `/data/es-ESS`. If `/data/es-ESS/config.ini` exists,
it is backed up first under `/data/es-ESS-backups/`. The active configuration
and every backup are restricted to owner-only access (`0600`); the external
backup directory is restricted to `0700` because these files can contain MQTT
and Wattpilot credentials.

Tail current log file (log file rotated daily, 14 days kept, see [logging](#logging) for more details): 
```
tail -f -n 20 /data/log/es-ESS/current.log
```

#### Global Configuration
Configuration of es-ESS is performed through the file `/data/es-ESS/config.ini`.
The maintained reference configuration is `config.sample.ini`; new installs copy
that file to `/data/es-ESS/config.ini`. Not all of the Global / Common Values
are required, it depends on the combination of services that should be active.
However, it easiest to setup the common values for every usecase, so you don't
have to mind adding / remove values as you enable or disable certain services. 

Install and startup reassert owner-only `0600` permissions on `config.ini`.
Configuration migration backups use the same mode and startup fails clearly if
the credential-bearing file cannot be secured.

| Section                  | Value name           |  Descripion                                                                                            | Type          | Example Value                |
| ------------------------ | ---------------------|------------------------------------------------------------------------------------------------------- | ------------- |------------------------------|
| [Common]                 | LogLevel             | LogLevel to use. See [Logging](#logging) use `INFO` if you are unsure.                                 | String        | INFO                         |  
| [Common]                 | NumberOfThreads      | Number of Threads to use. 3-XX depending on enabled service count.                                     | Integer       | 5                            |
| [Common]                 | ServiceMessageCount  | Number of ServiceMessages to publish on Mqtt. See [Service Messages](#service-messages)                | Integer       | 50                           |
| [Common]                 | ConfigVersion        | Just don't touch this.                                                                                 | Integer       | 11                           |
| [Common]                 | VRMPortalID          | Your VRMPortalID, required to publish/read some values of your local mqtt.                             | String        | VRM0815                      |
| [Common]                 | BatteryCapacityInWh  | Your battery capacity in Watthours.                                                                    | Integer       | 28000                        |
| [Common]                 | BatteryMaxChargeInWh | Your battery maximum charge power in W                                                                 | Integer       | 9000                         |
| [Common]                 | DefaultPowerSetPoint | Default Power Setpoint (W), when using features that manipulte the set point programmatically.         | Integer       | -50                          |
| [Common]                 | GridSetPointMinW     | Site-approved minimum combined Victron ESS grid setpoint. Must contain `DefaultPowerSetPoint`.         | Number (W)    | -50                          |
| [Common]                 | GridSetPointMaxW     | Site-approved maximum combined Victron ESS grid setpoint. Must contain `DefaultPowerSetPoint`.         | Number (W)    | -50                          |
| [Common]                 | HttpRequestTimeout   | Maximum seconds for shared HTTP requests used by SolarOverheadDistributor HTTP consumers.                       | Double        | 5                            |
| [Mqtt]                   | Host                 | Hostname / IP of your main-mqtt to work with.                                                          | String        | mqtt.ad.equinox-solutions.de |
| [Mqtt]                   | User                 | Username to connect to your main-mqtt.                                                                 | String        | user                         |
| [Mqtt]                   | Password             | Password to connect to your main-mqtt.                                                                 | String        | secure123!                   |
| [Mqtt]                   | Port                 | Port to connect to your main-mqtt.                                                                     | Integer       | 1833                         |
| [Mqtt]                   | SslEnabled           | Flag indicating whether the main MQTT connection uses TLS.                                             | Boolean       | true                         |
| [Mqtt]                   | SslVerification      | `Required`, `CertificateOnly`, or explicit legacy `Insecure`.                                          | String        | Required                     |
| [Mqtt]                   | SslCaFile            | Optional readable CA/certificate file. Empty `Required` mode uses the system trust store.              | Path          | /data/keys/broker-ca.crt     |
| [Mqtt]                   | LocalSslEnabled      | Flag indicating whether the local Venus MQTT connection uses TLS.                                      | Boolean       | true                         |
| [Mqtt]                   | LocalSslVerification | Local-client TLS policy: `Required`, `CertificateOnly`, or explicit legacy `Insecure`.                 | String        | Required                     |
| [Mqtt]                   | LocalSslCaFile       | Optional readable CA/certificate file for local Venus MQTT.                                            | Path          | /data/keys/mosquitto.crt     |
| [Services]               | SolarOverheadDistributor  | Flag, if [SolarOverheadDistributor](#solaroverheaddistributor) is enabled.                        | Boolean       | true                         |
| [Services]               | TimeToGoCalculator        | Flag, if [TimeToGoCalculator](#timetogocalculator) is enabled.                                    | Boolean       | true                         |
| [Services]               | FroniusSmartmeterJSON     | Flag, if the Fronius JSON smart-meter integration is enabled.                                     | Boolean       | true                         |
| [Services]               | FroniusWattpilot          | Flag, if [FroniusWattpilot](#FroniusWattpilot) is enabled.                                        | Boolean       | true                         |
| [Services]               | MqttExporter              | Flag, if [MqttExporter](#mqttexporter) is enabled.                                                | Boolean       | true                         |
| [Services]               | MqttTemperature           | Flag, if [MqttTemperatures](#mqtttemperatures) is enabled.                                        | Boolean       | true                         |
| [Services]               | NoBatToEV                 | Flag, if [NoBatToEV](#nobattoev) is enabled.                                                      | Boolean       | true                         |
| [Services]               | Shelly3EMGrid                 | Flag, if [Shelly3EMGrid](#shelly3emgrid) is enabled.                                                      | Boolean       | true                         |
| [Services]               | ShellyPMInverter                 | Flag, if [ShellyPMInverter](#shellypminverter) is enabled.                                                      | Boolean       | true                         |
| [Services]               | MqttPVInverter            | Flag, if [MqttPvInverter](#mqttpvinverter) is enabled.                                            | Boolean       | true                         |

#### Startup value validation

After applying configuration migrations, es-ESS validates safety-sensitive
numeric values before MQTT, D-Bus, or any service is initialized. All detected
configuration errors are logged at CRITICAL level and startup exits with status
1 so the operator can correct `config.ini`.

- Wattpilot `MinCurrentPerPhase` and `MaxCurrentPerPhase` must both be within
  `6..32 A`, with the maximum greater than or equal to the minimum.
- `ThreePhasePvSurplusStartW` must be greater than
  `ThreePhasePvSurplusStopW` so phase-switch hysteresis is not inverted.
- `BatteryAssistSocMin` must be within `0..100`. When battery assist is enabled,
  `BatteryAssistMaxSeconds` must be greater than `0`.
- `BatterySocFreshSeconds` must be greater than `0`; it limits the age of
  selected-battery activity used to trust the cached SOC. Missing settings in
  older configurations use the compatible 15-second default.
- `MinPhaseSwitchSeconds`, `AllowanceDropGraceSeconds`, `SurplusDropGraceSeconds`,
  `CarDisconnectConfirmSeconds`, and `StartupGraceSeconds` must be `0` or
  greater. Existing controller-side minimums still apply where defined.
- `TimeToGoCalculator` and `SolarOverheadDistributor` `UpdateInterval` values,
  plus `FroniusSmartmeterJSON`, `Shelly3EMGrid`, and every
  `ShellyPMInverter:*` `PollFrequencyMs`, must be greater than `0` milliseconds.
- Grid-import and battery-assist thresholds must be non-negative. Grid and
  allowance freshness windows must be positive, `RawOverheadFreshSeconds`
  must be at least `5`, and `StartupTelemetryRatio` must be in `(0, 1]`.
- `[MqttPvInverter] StaleTimeoutSeconds` must be at least `5`,
  `ZeroFeedinScaleStep` must be in `(0, 1]`, `ZeroFeedinDistance` must be
  non-negative, and `ZeroFeedinStartSoc` must be in `0..100`.
- `[Common] NumberOfThreads` and `HttpRequestTimeout` must be greater than `0`.
  The finite grid-setpoint bounds must contain `DefaultPowerSetPoint`.

#### MQTT TLS verification

TLS authenticates the broker by default. `Required` validates both certificate
and hostname. Leave the CA-file setting empty to use the system trust store, or
provide a readable CA/certificate file. `CertificateOnly` still validates the
certificate but explicitly disables hostname checking; it is intended for a
pinned self-signed Venus certificate whose name does not match the connection
hostname. `Insecure` disables both checks and should be temporary only.

Configuration version 11 migrates an existing TLS-enabled client to explicit
`Insecure` so an upgrade does not silently disconnect a legacy self-signed
broker. TLS-disabled clients and new installations default to `Required`.
Every non-required mode emits a startup warning, and es-ESS never silently
falls back from verified TLS.

> :warning: NOTE: I recommend to enable one service after each other and finalize configuration, before enabling another one. Else configuration may become a bit clumsy and error-prone.

# TimeToGoCalculator 

> :white_check_mark: Production Ready

> :warning: This is currently broken since 3.50.

<img align="right" src="https://github.com/realdognose/es-ESS/blob/main/img/TimeToGo.png" /> 

#### Overview

Some BMS - say the majority of them - don't provide values for the `Time to go`-Value visible in VRM. This is an important figure when looking at a dashboard. This helper script 
fills that gap and calculates the time, when BMS don't. Calculation is done in both directions: 

- **When discharging**: Time based on current discharge rate until the active SoC Limit is reached.
- **When charging**: Time based on current charge rate until 100% SoC is reached. 

If power, state of charge, or the active state-of-charge limit is temporarily
unavailable, the calculator skips that cycle without replacing the last valid
time-to-go value. Calculation resumes automatically when all inputs recover.

#### Configuration

TimeToGoCalculatore requires your local mqtt to be enabled, either in plain or ssl mode.<br />
TimeToGoCalculator requires a few variables to be set in `/data/es-ESS/config.ini`: 

| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [Common]    | VRMPortalID |  Your portal ID to access values on mqtt / dbus |String | VRM0815 |
| [Common]  | BatteryCapacityInWh  | Your batteries capacity in Wh.  | Integer| 28000 |
| [Mqtt]     | LocalSslEnabled | Flag, if local Mqtt is SSL or plain. | Boolean | true |
| [Services]    | TimeToGoCalculator | Flag, if the service should be enabled or not | Boolean | true |
| [TimeToGoCalculator]  | UpdateInterval | Time in milliseconds for TimeToGo calculations. Must be greater than `0`; smaller values reduce flickering when a BMS sends `null`, but also run the calculation more frequently. | Integer  | 1000 |

# MqttTemperatures
> :white_check_mark: Production Ready

### Overview
MqttTemperatures is a streight-forward feature: It allows you to read temperature sensors from your mqtt server and injects them as temperaturesensors in dbus/vrm. (Including the `Pressure` and `Humidity` Fields, if present.)

| Example View |
|:-------------------------:|
|<img src="https://github.com/realdognose/es-ESS/blob/main/img/mqttTemperature.png"> |

| Example View with Details |
|:-------------------------:|
|<img src="https://github.com/realdognose/es-ESS/blob/main/img/mqttTemperatureGarden.png"> |

### Configuration
MqttTemperatures requires a few variables to be set in `/data/es-ESS/config.ini`: 


| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [Services]    | MqttTemperatures | Flag, if the service should be enabled or not | Boolean | true |
| [MqttTemperature:XYZ]  | VRMInstanceID |  VRMInstanceId to be used on dbus | Integer  | 1000 |
| [MqttTemperature:XYZ]  | CustomName |  Custom name to be used for this sensor | String  | MPPT2 Wiring |
| [MqttTemperature:XYZ]  | Topic |  Topic on Mqtt, delivering the measurement value. | String  | Devices/d1Garden/Sensors/TEMP/Value |
| [MqttTemperature:XYZ]  | TopicHumidity |  Topic on Mqtt, delivering the measurement value for humidity (optional). | String  | Devices/d1Garden/Sensors/HUM/Value |
| [MqttTemperature:XYZ]  | TopicPressure |  Topic on Mqtt, delivering the measurement value for pressure (optional). | String  | Devices/d1Garden/Sensors/PRESSURE/Value |

> :warning: You can create as many `[MqttTemperature:XYZ]` sections as you need, just take care to ensure unique names and VRM-Ids.

| Example Config file with multiple sections added |
|:-------------------------:|
|<img src="https://github.com/realdognose/es-ESS/blob/main/img/mqttTemperatureExampleConf.png"> |

# MqttExporter

> :white_check_mark: Production Ready

### Overview
Victrons Venus OS / Cerbo Devices have a builtin Mqtt-Server. However, there are some flaws with that: You have to constantly post a Keep-Alive message, in order to keep values beeing published. VRM uses this in order to receive data. On one hand, it is a unnecessary performance-penalty to keep thausands of values up-to-date, just because you want to use 10-12 of them for display purpose. 

Second issue is - according to the forums: while Keep-Alive is enabled, topics are continiously forwarded to the upstream-server, causing bandwith usage, which is bad on metered connections or at least general bandwith pollution. 

So, the MqttExporter has been created. You can define which values should be tracked on dbus, and then be forwarded to your mqtt server for further processing and/or display purpose.

# Configuration

MqttExporter requires a few variables to be set in `/data/es-ESS/config.ini`: 

| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [Services]    | MqttExporter | Flag, if the service should be enabled or not | Boolean | true 

For every value you want to export, you have to create a additional section, specifying export-conditions. This is quite a bunch of work, but generally only done once. 

Each section needs to match the pattern `[MattExporter:uniqueKey]` where uniqueKey should be an unique identifier.

| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [MqttExporter:XXX]  | Service |  Service name, see details bellow | String  | com.victronenergy.system |
| [MqttExporter:XXX]  | DbusKey |  Key of the dbus-value to export | String  | /Ac/Grid/L1/Power |
| [MqttExporter:XXX]  | MqttTopic |  Topic on Mqtt | String  | Grid/Ac/L1/Power |
| [MqttExporter:XXX]  | PublishType |  How to publish? | String, optional, Default ONCHANGE  | ONCHANGE, INTERVAL_1S, INTERVAL_10S, INTERVAL_60S |

**Note that dbus-paths start with a "/" and MQTT Topics don't.**

To export values from DBus to your mqtt server, you need to specify 3 variables per export
You can create as many exports as you like, just increase the number of the sections added to the ini file.

### Service name ###
if you want to export from a certain service (like bms) you can use dbus-spy in ssh to figure out the service name to use. 

### Example relation between dbus-spy, config and MQTT ###


<div align="center">
  
| use `dbus-spy` to find the servicename |
|:-------:|
|<img src="https://github.com/realdognose/es-ESS/blob/main/img/mqttExporter1.png" />|
</div>

<div align="center">

| use `dbus-spy` to find the desired Dbus-keys (right arrow key) |
|:-------:|
|<img src="https://github.com/realdognose/es-ESS/blob/main/img/mqttExporter2.png" />|
</div>

<div align="center">

| create config entries |
|:-------:|
|<img src="https://github.com/realdognose/es-ESS/blob/main/img/mqttExporter3.png" />|
</div>

<div align="center">

| Values on MQTT |
|:-------:|
|<img src="https://github.com/realdognose/es-ESS/blob/main/img/mqttExporter4.png" />|
</div>

Hint: You can use a trailing `*` on the Mqtt Topic. This will cause the original dbus path to be appended, for example: 

<img src="https://github.com/realdognose/es-ESS/blob/main/img/mqttExporterStar1.png" />

<img src="https://github.com/realdognose/es-ESS/blob/main/img/mqttExporterStar2.png" />

# MqttPvInverter

> :white_check_mark: Production Ready

### Overview
For proper overview it is sometimes required to pair any additional inverter with VenusOS / VRM. While there is a very broad support to read out inverters and export their values on your mqtt, getting these Values back into 
VenusOS can be tricky. 

therefore, the MqttPvInverter Service allows you to extract values from Mqtt and mimic a PV Inverter on VenusOS: 




# Configuration

MqttPvInverter requires a few variables to be set in `/data/es-ESS/config.ini`: 

| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [Services]    | MqttPvInverter | Flag, if the service should be enabled or not | Boolean | true 
| [MqttPvInverter]    | EnableZeroFeedin | Experimental, leave to false! | Boolean | false 
| [MqttPvInverter]    | EnablePvShutdown | Flag, if the Inverters should be shutdown through OpenDTU, when the GX is shutting down PV. | Boolean | true 
| [MqttPvInverter]    | ZeroFeedinScaleStep | Experimental OpenDTU throttle rate-of-change limit per zero-feed-in cycle. | Double | 0.05
| [MqttPvInverter]    | ZeroFeedinDistance | Experimental buffer in W subtracted from measured consumption before calculating target inverter power. | Double | 50
| [MqttPvInverter]    | ZeroFeedinStartSoc | Experimental SOC threshold where zero-feed-in control may begin. | Double | 100
| [MqttPvInverter]    | StaleTimeoutSeconds | Maximum age of any MQTT message from one inverter before its D-Bus state and cached phase power are invalidated. Must be at least `5`. | Integer (seconds) | 300

When zero-feed-in is enabled and the calculated target inverter power is `0`,
producing inverters with `DtuControlTopic` receive an explicit `0%` OpenDTU
limit command.

Zero-feed-in calculation requires all three consumption phases. If one phase is
temporarily unavailable, es-ESS keeps the last inverter limit and skips that
cycle until complete telemetry returns.

An inverter that publishes no MQTT message for `StaleTimeoutSeconds` is marked
disconnected, its D-Bus measurements are nulled, and its cached phase power is
cleared so frozen production cannot influence zero-feed-in calculations. The
first later message restores the normal connected state; fresh phase-power
topics rebuild the cached total.

For every inverter you want to create you have to create a additional section, specifying paths on mqtt. This is quite a bunch of work, but generally only done once. 

Each section needs to match the pattern `[MqttPvInverter:uniqueKey]` where uniqueKey should be an unique identifier.

| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [MqttPvInverter:XXX]  | CustomName |  Service name, see details bellow | String  | com.victronenergy.system |
| [MqttPvInverter:XXX]  | VRMInstanceID |  Key of the dbus-value to export | String  | /Ac/Grid/L1/Power |
| [MqttPvInverter:XXX]  | L1VoltageTopic |  Voltage reported for L1 | String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | L2VoltageTopic |  Voltage reported for L2 | String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | L3VoltageTopic |  Voltage reported for L3 | String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | L1PowerTopic |  Power reported for L1 | String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | L2PowerTopic |  Power reported for L2 | String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | L3PowerTopic |  Power reported for L3 | String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | L1CurrentTopic |  Current reported for L1 | String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | L2CurrentTopic |  Current reported for L2 | String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | L3CurrentTopic |  Current reported for L3 | String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | L1EnergyForwardedTopic |  Counter for the amount of Energy produced on L1 | String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | L2EnergyForwardedTopic |  Counter for the amount of Energy produced on L2 | String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | L3EnergyForwardedTopic |  Counter for the amount of Energy produced on L3 | String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | TotalEnergyForwardedTopic |  Counter for the amount of Energy produced| String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | TotalPowerTopic |  Total output power | String  | my/mqtt/topic |
| [MqttPvInverter:XXX]  | DtuControlTopic |  Experimental | String  | my/mqtt/topic|

Example: You don't need to provide all values, if it's a single phased inverter: 
<img width="647" height="374" alt="image" src="https://github.com/user-attachments/assets/33bc3d45-37d1-4f3f-a220-1b828e705fc7" />

Seamless Integration through all layers: 

<img width="959" height="291" alt="image" src="https://github.com/user-attachments/assets/5af0c076-a4b1-4220-95e1-ca57ca23dabe" />


<img width="954" height="333" alt="image" src="https://github.com/user-attachments/assets/28413827-3db4-418f-b839-4133fa2e922d" />


<img width="302" height="196" alt="image" src="https://github.com/user-attachments/assets/203d2406-9364-4cc3-bc06-b79cd7a92144" />


<img width="753" height="255" alt="image" src="https://github.com/user-attachments/assets/205cd23c-a9e1-4a03-8a05-79200d16f9e5" />

# FroniusWattpilot

> :white_check_mark: Production Ready. 
> Known Issue: When no EV is connected AND Hibernate Mode is enabled, control through VRM doesn't work. Waking up Wattpilot through the "scheduled charge" option isn't helping, wattpilot will immediately go into hibernation again. 

### Overview

The native Wattpilot ECO mode does not know the full Victron ESS state. In
particular, it cannot see the same battery reservation, grid import, and
SolarOverheadDistributor allowance decisions that es-ESS uses. That can lead to
unexpected home-battery discharge or grid import when the wallbox keeps charging
after PV surplus has fallen.

The FroniusWattpilot service integrates Wattpilot into Venus OS / VRM as a
Victron EV charger and lets es-ESS manage Auto/Eco charging from fresh PV
surplus:

- Wattpilot status is exposed on D-Bus, VRM, and MQTT.
- Auto/Eco charging uses [SolarOverheadDistributor](#solaroverheaddistributor)
  allowances, fresh grid telemetry, configured current limits, and no-grid
  guards.
- Manual Wattpilot mode remains user-controlled. es-ESS reports Manual status,
  but Auto/Eco PV policy does not start, stop, current-limit, or phase-switch a
  normal Manual session, including during service startup while telemetry is
  still arriving. When leaving Auto/Eco for Manual, es-ESS releases its previous
  Auto/Eco phase and current commands once so Manual charging is not left
  constrained by the PV controller.
- Battery assist is optional and only bridges a short PV dip during an
  already-running Auto/Eco charge. It cannot start a charge and cannot authorize
  a phase-up.
- The standard VRM EV-charger tile is limited to the normal Victron `/Status`
  values. Phase-qualified state and safety details are available through the
  runtime-status D-Bus and MQTT contract, and need a custom Cerbo UI/dashboard
  if you want to display them directly.

| Charging | Phase Switch | Waiting for Sun | Cooldown Information |
|:-------:|:-------:|:-------:|:-------:|
| <img src="https://github.com/realdognose/es-ESS/blob/main/img/wattpilot_3phases.png" /> | <img src="https://github.com/realdognose/es-ESS/blob/main/img/wattpilot_switching_to_3.png" /> | <img src="https://github.com/realdognose/es-ESS/blob/main/img/wattpilot_waitingSun.png" />| <img src="https://github.com/realdognose/es-ESS/blob/main/img/wattpilot_start.png" /> <br /> <img src="https://github.com/realdognose/es-ESS/blob/main/img/wattpilot_stop.png" />| 

<div align="center">

| Full integration |
|:-------:|
|<img src="https://github.com/realdognose/es-ESS/blob/main/img/SolarOverheadConsumers%202.png" />|
| VRM and the Wattpilot app both show useful status. Auto/Eco PV control is owned by es-ESS; Manual mode remains owned by the Wattpilot user. |
</div>

### Installation
Despite the installation of es-ESS, an additional python module *websocket-client* is required to communicate with Wattpilot. 
The installation is a *one-liner* through *pythons pip* - which in turn might need to be installed first. 
If you have already installed *python pip* on your system, can skip this.

Install *python pip*: 
```
opkg update
opkg install python3-pip
```

Install *websocket-client*:
```
python -m pip install websocket-client
```

> :warning: **Venus-Update**:<br /> Updating Venus-OS will remove these modules again, so you need to execute the commands again.


### Configuration

<img align="right" src="https://github.com/realdognose/es-ESS/blob/main/img/wattpilot_controls.png" /> 

FroniusWattpilot uses `/data/es-ESS/config.ini` at runtime. The complete
maintained sample is `config.sample.ini`; new installs copy that file to
`/data/es-ESS/config.ini`, and production config should keep the same supported
keys while adjusting values for the local system.

Before enabling Auto/Eco PV control:

- Enable both `FroniusWattpilot` and
  [SolarOverheadDistributor](#solaroverheaddistributor). Without the
  distributor, Wattpilot Auto/Eco requests do not receive a PV allowance.
- With the vehicle disconnected, turn off the Solar.wattpilot app's native
  `Use PV surplus` and flexible-tariff switches. Firmware `42.5` exposes these
  as `fup=false` and `ful=false`. Missing, malformed, or enabled values block
  es-ESS Auto/Eco commands.
- Disabling native PV may move the wallbox from Eco to Standard. After both
  native switches are off, select Auto from the VRM web dashboard: click the
  EVCS tile/module and use its mode control. The VRM mobile app did not expose
  this mode control during operator validation on 2026-07-15. Solar.wattpilot
  app `2.1.0` also refuses to activate Eco while both Eco options are off, so
  it cannot perform this transition. es-ESS permits the VRM-requested `lmo=4`
  transition only when both settings are confirmed off. Do not connect the
  vehicle until `/CommandAuthorityOk=1`.
- Firmware `42.5` reports native status `114` whenever raw Eco mode is active
  while both native PV surplus and flexible tariff are disabled. The Eco LED
  therefore flashes orange/yellow and may continue flashing while es-ESS is
  successfully charging. This is an expected single-owner commissioning
  artifact when `/CommandAuthorityOk=1`, both native-setting paths are `0`, and
  telemetry is healthy; it does not authorize ignoring a red LED, another
  status code, unhealthy telemetry, or lost command authority.
- Do not treat Wattpilot's native PV-start threshold as a command-ownership
  boundary. Production evidence with firmware `42.5` and Solar.wattpilot app
  `2.1.0` showed that native PV regulation can still hold charging near its
  minimum after es-ESS forces a start and requests more current. The exact
  `10 kW` maximum remains only a start-up power setting and is not an authority
  control.
- Before changing native PV, tariff, phase, or control-response settings, use
  the command-free discovery and supervised validation procedure in
  [docs/wattpilot-command-ownership-validation.md](docs/wattpilot-command-ownership-validation.md).
- Keep the Wattpilot app's own cable/current limits correct. es-ESS will not
  raise charging beyond the configured per-phase limits or the
  Wattpilot-reported effective limit.
- Use `Scheduled Charging` in VRM only as the wake-up path when hibernate is
  enabled.

VRM controls do not offer an explicit one-phase/three-phase selector. Direct
current selection maps to phase mode like this:

- Selecting `6` to `16` A requests one-phase charging at that current.
- Selecting `18` to `48` A requests three-phase charging at one third of the
  selected total current per phase.

Positive direct-current requests and start commands are accepted only while
Wattpilot telemetry confirms ECO mode, `fup=false`, and `ful=false`. Missing or
conflicting authority telemetry fails closed. A zero-current request or stop
remains available in confirmed ECO mode so a conflicting controller can be
stopped safely; phase-up and current increase remain blocked. When Wattpilot is
in normal Manual/default mode, es-ESS rejects current/start/stop writes and
leaves the session under Wattpilot app/user control. The VRM `/Mode` selector
can switch Manual to Auto/ECO only after both native settings are confirmed
off. Selecting Manual still sends the one-time release of previous Auto/Eco
phase/current limits, then leaves subsequent Manual charging user-controlled.

For diagnosis of externally selected mode delays, es-ESS logs timestamped raw
Wattpilot `lmo` changes and the matching `/ModeLiteral` publication. These
timestamps are observation-only: they do not expire a stable ECO session,
authorize a command, or change Manual ownership. The production health monitor
collects the matching mode-boundary events for vehicle-disconnected validation.
When a raw mode transition arrives while the vehicle is disconnected, it
bypasses the normal five-minute idle-report throttle and is reflected on
`/ModeLiteral` by the next five-second controller cycle. Unchanged disconnected
state remains on the low-frequency idle cadence.

> :warning: **FAKE-BMS injection**:<br /> This feature is creating FAKE-BMS information on dbus. Make sure to manually select your *actual* BMS unter *Settings > System setup > Battery Monitor* else your ESS may not behave correctly anymore. Don't leave this setting to *Automatic*

> :warning: **Dependency**:<br /> If you want to enable Solar-Overhead Charging, you need to enable the [SolarOverheadDistributor](#solaroverheaddistributor) as well. (It will be responsible for giving a clearence to Wattpilots charge request)

| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [Services]    | FroniusWattpilot | Flag, if the service should be enabled or not | Boolean | true |
| [FroniusWattpilot]  | VRMInstanceID |  VRMInstanceId to be used on dbus | Integer  | 1007 |
| [FroniusWattpilot]  | VRMInstanceID_OverheadRequest |  VRMInstanceId to be used on dbus for the FAKE-BMS | Integer  | 1006 |
| [FroniusWattpilot]  | MinPhaseSwitchSeconds  | Shared continuous-condition timer for both 1-to-3 and 3-to-1 changes, and minimum interval between phase commands. During a 3-to-1 wait, only bounded battery assist or explicitly permitted grid fallback may hold the running charge. | Integer (seconds) | 600 |
| [FroniusWattpilot]  | MinOnOffSeconds | Seconds between starting/stopping charging. | Integer | 60 |
| [FroniusWattpilot]  | OverheadPriority | SolarOverheadDistributor priority used for Wattpilot allowance requests. | Integer | 35 |
| [FroniusWattpilot]  | ResetChargedEnergyCounter |  Define when the counters *Charge Time* and *Charged Energy* in VRM should reset. Options: OnDisconnect, OnConnect| String  | OnDisconnect |
| [FroniusWattpilot]  | Position | Position, where the Wattpilot is connected to. Options: 0:=ac-out, 1:=ac-in | Integer  | 0 |
| [FroniusWattpilot]  | Host | hostname / ip of Wattpilot | String  | 10.10.20.47 |
| [FroniusWattpilot]  | Password | Password of Wattpilot | String  | password |
| [FroniusWattpilot]  | HibernateMode | When the car is disconnected, es-ESS will switch into idle mode, stop doing heavy lifting. Connection to wattpilot remains established and VRM control enabled. <br /><br />With hibernate enabled, wattpilot will also be disconnected, and connected every 5 minutes for a car-state-check. This greatly reduces the number of incoming socket messages from wattpilot by about 95% per day, but causes an delay of up to 5 minutes when the car is connected.<br /><br />You can force a wakeup by switching to *Scheduled charging* in VRM at any time. | Boolean  | false |
| [FroniusWattpilot] | MinCurrentPerPhase | Minimum configured EV current per active phase. Must be within `6..32 A`. | Integer (A) | 6 |
| [FroniusWattpilot] | MaxCurrentPerPhase | Maximum configured EV current per active phase. Must be within `6..32 A` and at least `MinCurrentPerPhase`; the controller also respects the Wattpilot-reported effective limit. | Integer (A) | 16 |
| [FroniusWattpilot] | ThreePhasePvSurplusStartW | Fresh real PV allowance required before Auto/Eco may switch from 1 phase to 3 phases. Must be greater than `ThreePhasePvSurplusStopW`. The maintained 4500 W default is above the typical 3-phase 6 A electrical floor while matching observed Wattpilot-app-style behavior more closely than a very conservative 5000 W threshold. | Integer (W) | 4500 |
| [FroniusWattpilot] | ThreePhasePvSurplusStopW | PV threshold below which Auto/Eco falls back from 3 phases to 1 phase when one-phase charging is still supportable. Must be lower than `ThreePhasePvSurplusStartW`. | Integer (W) | 4100 |
| [FroniusWattpilot] | EvPriorityOverBatteryCharge | Lets Wattpilot use real PV that would otherwise charge the battery while the car is connected in Auto mode. This does not allow battery-to-EV charging from a stopped state. | Boolean | true |
| [FroniusWattpilot] | EvPriorityMinSoc | Minimum battery SOC required before EV priority over battery charging is allowed. | Number (%) | 60 |
| [FroniusWattpilot] | BatteryAssistEnabled | Enables the optional short battery bridge for an already-running Auto/Eco charge. | Boolean | true |
| [FroniusWattpilot] | BatteryAssistSocMin | Minimum battery SOC required before battery assist can be used. Must be within `0..100`. | Number (%) | 50 |
| [FroniusWattpilot] | BatteryAssistMaxSeconds | Maximum duration for one battery-assist window. Use at least `MinPhaseSwitchSeconds` when battery should be able to bridge the full phase-down waiting interval. Must be greater than `0` when enabled. | Integer (seconds) | 600 |
| [FroniusWattpilot] | BatteryAssistMaxShortfallW | Maximum non-negative PV shortfall that battery assist may bridge for an already-running charge. The maintained 1000 W default bridges small clouds but makes larger deficits reduce current, phase down, or stop earlier instead of leaning heavily on the home battery. | Number (W) | 1000 |
| [FroniusWattpilot] | BatterySocFreshSeconds | Maximum age of selected-battery activity used to trust the cached SOC for battery assist or the EV-priority battery-reservation bypass. Valid finite SOC and a recent finite `/Dc/Battery/Power` update are both required; otherwise both features are ineligible. Must be greater than `0`. | Integer (seconds) | 15 |
| [FroniusWattpilot] | BatteryAssistRecoverySeconds | Non-negative sustained PV-recovery time required before battery assist can be used again after lockout. | Integer (seconds) | 120 |
| [FroniusWattpilot] | AllowGridCharging | Allows an already-running Auto/Eco charge to continue despite grid import when PV/battery assistance is insufficient. It never permits a new grid-only start. Victron ESS determines the actual battery/grid energy source. Recommended no-grid mode is `false`. | Boolean | false |
| [FroniusWattpilot] | GridImportPositive | Site grid-power sign convention. `true` means positive grid power is import. | Boolean | true |
| [FroniusWattpilot] | GridImportStopW | Non-negative sustained grid-import power threshold that stops Auto/Eco when grid charging is disabled. | Number (W) | 300 |
| [FroniusWattpilot] | GridImportStopSeconds | Non-negative duration grid import must exceed `GridImportStopW` before Auto/Eco is stopped. | Integer (seconds) | 15 |
| [FroniusWattpilot] | AllowanceFreshSeconds | Positive maximum age of the assigned SolarOverheadDistributor Wattpilot allowance. Missing, malformed, or stale allowance is treated as insufficient. | Integer (seconds) | 15 |
| [FroniusWattpilot] | GridTelemetryFreshSeconds | Positive maximum age of each required grid-power value (L1, L2, and L3) while no-grid Auto/Eco control is enabled. | Integer (seconds) | 15 |
| [FroniusWattpilot] | AllowanceDropGraceSeconds | Non-negative grace period before an already-running Auto/Eco session is phase-reduced or stopped for an insufficient or stale allowance. A fresh truthful `0 W` allowance remains published as `0 W`; this setting only debounces the controller response. Stale grid telemetry and the grid-import guard are not delayed. | Integer (seconds) | 15 |
| [FroniusWattpilot] | CarDisconnectConfirmSeconds | Non-negative time a disconnected car-state reading must remain stable before es-ESS accepts it as a disconnect. | Integer (seconds) | 15 |
| [FroniusWattpilot] | SurplusDropGraceSeconds | Non-negative grace period before continuous low surplus resets the Auto/Eco start timer. On the normal current-adjustment path it also preserves an active 1-to-3 candidate through a shorter-than-grace dip only while allowance remains above the effective three-phase floor. Eligible battery assist may leave an already-existing candidate timer running through its bounded bridge, including a deeper dip; it cannot create the candidate or issue a phase command. Full phase-up allowance is always required at the command boundary. | Integer (seconds) | 20 |
| [FroniusWattpilot] | StartupGraceSeconds | Non-negative time after a start or phase switch where commanded EV demand may be reported while Wattpilot telemetry catches up. | Integer (seconds) | 60 |
| [FroniusWattpilot] | StartupTelemetryRatio | Fraction of commanded demand that Wattpilot telemetry must reach before startup grace is considered satisfied. Must be greater than `0` and at most `1`. | Number | 0.80 |
| [FroniusWattpilot] | RawOverheadFreshSeconds | Maximum age of raw distributor overhead used only for safe 3-to-1 fallback decisions. Must be at least `5`. | Integer (seconds) | 15 |
| [FroniusWattpilot] | ChargeCompletePowerThresholdW | Sustained low EV power treated as charge-complete hold instead of restarting Auto/Eco PV control. | Number (W) | 100 |
| [FroniusWattpilot] | ChargeCompleteConfirmSeconds | Time low EV power must remain below `ChargeCompletePowerThresholdW` before charge-complete hold starts. | Integer (seconds) | 120 |
| [FroniusWattpilot] | ChargeCompleteResumePowerW | EV power above this value starts the confirmation for leaving charge-complete hold. | Number (W) | 300 |
| [FroniusWattpilot] | ChargeCompleteResumeSeconds | Time EV power must remain above `ChargeCompleteResumePowerW` before charge-complete hold clears. | Integer (seconds) | 30 |

### Eco/PV policy

In `Auto` / Wattpilot `ECO` mode, es-ESS follows this PV-start policy with an
optional running-session grid fallback:

- A new charge starts only after a fresh, distributor-assigned **real PV allowance** has continuously met the electrical minimum for `MinOnOffSeconds`. It starts on one phase when allowance is below the phase-up threshold, or directly on three phases when allowance already meets the full phase-up threshold. Battery assist cannot create either start.
- Both one-to-three and three-to-one phase changes use `MinPhaseSwitchSeconds` as their normal stability timer and minimum interval between phase commands. On the normal current-adjustment path, an active one-to-three candidate survives a shorter-than-`SurplusDropGraceSeconds` dip below the phase-up threshold only while fresh allowance remains above the effective three-phase floor; a deeper or longer normally evaluated dip resets it. During eligible battery assist, the controller holds the running one-phase charge and intentionally leaves an already-existing phase-up candidate timer unchanged, potentially for up to `BatteryAssistMaxSeconds`. Assist cannot create a candidate or command phase-up, and fresh allowance must recover to the full phase-up threshold before any three-phase command is sent.
- A confirmed vehicle disconnect clears any pending phase-switch candidate, so reconnecting requires a new complete `MinPhaseSwitchSeconds` interval from fresh assigned PV. A transient false connection reading inside `CarDisconnectConfirmSeconds` does not reset the timer, and disconnect does not erase the cooldown from the last confirmed phase command.
- During the three-to-one waiting interval, bounded battery assist may hold the existing phase/current. When `AllowGridCharging=true`, an already-running charge may instead continue despite grid import. Neither fallback can start a session or authorize a phase-up.
- With `AllowGridCharging=false`, loss of an eligible battery bridge normally reduces to one phase when fresh assigned PV supports the one-phase minimum; otherwise Auto/Eco stops. A running charge first receives `AllowanceDropGraceSeconds` when the assigned allowance itself is below the usable minimum, including a transient atomic `0 W` assignment. An explicit one-phase-capable assignment can reduce phase immediately, while stale grid telemetry and the grid-import guard can still act sooner.
- After a sustained phase-down interval, es-ESS changes to one phase when fresh PV supports it. If PV is below the one-phase minimum, bounded battery assist or allowed grid fallback may keep the running charge active; without either source, charging stops.
- Battery assist is optional and may only bridge a short cloud for an **already-running** charge. It is limited by valid SOC, recent selected-battery activity, shortfall-power, duration, and PV-recovery settings; it cannot create a new charging session. Missing or invalid SOC, or a missing, invalid, or older-than-`BatterySocFreshSeconds` `/Dc/Battery/Power` update, clears/refuses assist and also disables the `EvPriorityOverBatteryCharge` reservation bypass for that cycle. The maintained `BatteryAssistMaxShortfallW=1000` default favors daily battery protection: small dips are bridged, while larger deficits reduce current, phase down, or stop earlier. To cover the full phase waiting interval, `BatteryAssistMaxSeconds` must be at least `MinPhaseSwitchSeconds`.
- Auto/Eco stops when sustained grid import exceeds `GridImportStopW` for `GridImportStopSeconds`. With `AllowGridCharging=false`, Auto/Eco therefore does not intentionally use grid power. Very short transients can still appear before the guard threshold and timer are reached.
- `MinOnOffSeconds` applies to normal starts and stops. `MinPhaseSwitchSeconds` is the single shared stability and cooldown setting for both phase directions; no-grid safety may still reduce phase or stop earlier when a running deficit cannot be bridged.
- Normal Wattpilot `Manual` mode remains under the user's control and is not changed by this Auto/Eco policy.

### Auto/Eco telemetry fail-safe

When `AllowGridCharging=false` (the recommended no-grid configuration), Auto/Eco charging requires valid, fresh grid-power telemetry for all three grid phases. If any L1, L2, or L3 value is missing, invalid, or older than `GridTelemetryFreshSeconds`, es-ESS will not start a new Auto/Eco session and will stop an active Auto/Eco session immediately. This means a grid-meter or D-Bus telemetry outage can stop charging until fresh values recover.

Auto/Eco also requires a valid Wattpilot allowance received within `AllowanceFreshSeconds`. Missing, malformed, or stale allowance is never replaced with raw-overhead data. The distributor may truthfully assign `0 W` when the active three-phase request is atomic and its full minimum is temporarily unavailable. For a running session, `/PvAllowance` remains `0 W`, while `AllowanceDropGraceSeconds` debounces phase reduction or stop so one short worker-ordering or cloud sample does not reset three-phase operation. Recovery during the grace clears the timer; a sustained deficit follows the normal phase-down/stop policy at expiry. This allowance-only grace never delays stale-grid or grid-import safety handling. SOC-dependent battery assist and battery-reservation bypass require valid finite system SOC plus a finite selected-battery `/Dc/Battery/Power` update received within `BatterySocFreshSeconds`. This power path is the liveness heartbeat because unchanged SOC is not periodically republished by Venus OS. Missing or invalid SOC, or missing, invalid, or stale battery activity, fails closed without changing Manual charging. Manual Wattpilot mode remains under the Wattpilot user's control and is not changed by these Auto/Eco freshness guards.

### Runtime status

The normal Victron EV-charger status stays compatible with VRM. More detailed
state is published on the Wattpilot runtime-status contract:

- When the Wattpilot transport is unreachable, es-ESS sets the standard charger
  `/Connected` path to `0`, keeps `/Status` VRM-compatible as `Disconnected`,
  sets `/StatusLiteral` to `Wattpilot not accessible`, and sets
  `/CustomName` to `Wattpilot not reachable` for detail views, D-Bus
  inspection, MQTT consumers, and SolarOverheadDistributor messages.
- After the normal connection debounce confirms that the car is disconnected,
  the detailed control state is `Stopped`, `/PhaseMode` is `0`, and
  `/PhaseModeLiteral` is `Unknown`. A transient disconnect indication inside
  the debounce window keeps the active state and phase to avoid status flicker.
- A reconnect request waits for a stopping connection worker for a bounded
  interval before starting its replacement, preventing overlapping workers
  from owning the Wattpilot transport.
- The supported es-ESS visibility route for a wallbox transport outage is the
  EV-charger detail view, D-Bus, retained MQTT runtime status, es-ESS service
  messages, or SolarOverheadDistributor messages. es-ESS does not publish a
  synthetic charger fault or change `/Mode` only to force text into the standard
  EVCS overview tile.
- D-Bus paths on `com.victronenergy.evcharger.*_FroniusWattpilot`:
  `/ControlState`, `/ControlStateLiteral`, `/PhaseMode`,
  `/PhaseModeLiteral`, `/BatteryAssistActive`, `/GridImportGuardActive`, and
  `/TelemetryHealthy`, plus `/CompatibilityOk`, `/CompatibilityLiteral`,
  `/ExpectedVenusOsVersion`, `/ActualVenusOsVersion`,
  `/ExpectedWattpilotFirmware`, `/ActualWattpilotFirmware`, and
  `/ValidatedWattpilotAppVersion`.
- Retained MQTT topics under
  `es-ESS/FroniusWattpilot/RuntimeStatus/...` with the same value names.

The state values are documented in
[FroniusWattpilot runtime-status contract](#froniuswattpilot-runtime-status-contract).

### Example Auto/Eco configurations

PV-only, no battery assist:

```ini
[FroniusWattpilot]
BatteryAssistEnabled=false
AllowGridCharging=false
MinOnOffSeconds=60
MinPhaseSwitchSeconds=600
```

PV charging with a 600-second cloud bridge for an already-running session:

```ini
[FroniusWattpilot]
BatteryAssistEnabled=true
BatteryAssistSocMin=60
BatteryAssistMaxSeconds=600
BatteryAssistMaxShortfallW=1000
BatterySocFreshSeconds=15
BatteryAssistRecoverySeconds=120
AllowGridCharging=false
```

The `1000W` shortfall default is a daily-use compromise. It smooths short PV
dips without letting a three-phase EV session draw heavily from the home
battery; if the deficit is larger, Auto/Eco should reduce current, phase down,
or stop according to fresh allowance and no-grid safety.

Conservative five-minute start and phase confirmation timers:

```ini
[FroniusWattpilot]
MinOnOffSeconds=300
MinPhaseSwitchSeconds=600
AllowGridCharging=false
```

### Deployment verification

Before deploying a changed checkout, run the hardware-free checks where
available:

```bash
python -m py_compile es-ESS.py esESSService.py FroniusWattpilot.py Wattpilot.py WattpilotRuntimeStatus.py
python -m unittest discover -s tests
/data/es-ESS/restart.sh
tail -f -n 20 /data/log/es-ESS/current.log
```

Live Wattpilot behavior still needs validation on a GX/Wattpilot system. Check
that Manual mode is only reported, Auto/Eco waits for fresh PV allowance, and
the runtime-status D-Bus/MQTT values match the observed charging state. For
transport changes, also power-cycle or disconnect the Wattpilot network link
several times and confirm es-ESS reconnects without duplicate WebSocket worker
messages or unbounded exceptions.

### Production health monitor

For firmware-update, deploy, config-change, early daylight and mid-day
PV-surplus validation windows, use the read-only GX monitor:

```bash
/data/es-ESS/scripts/es-ess-health-monitor.sh
```

For a longer observation window with a saved log:

```bash
INTERVAL_SECONDS=10 MAX_SAMPLES=120 /data/es-ESS/scripts/es-ess-health-monitor.sh | tee /data/es-ess-health-$(date +%Y%m%d-%H%M%S).log
```

The script reads service state, Venus OS version, Python dependency imports,
selected config keys, Wattpilot D-Bus/runtime-status paths, disk usage and
recent controller logs, including raw `lmo` and `/ModeLiteral` transition
timestamps. It does not write D-Bus, MQTT, config, service state or Wattpilot
control values. Installation, mode-boundary validation, and interpretation
steps are documented in
[docs/es-ess-health-monitor.md](docs/es-ess-health-monitor.md).

Native Solar.wattpilot PV/tariff/phase setting discovery uses the separate
command-free `scripts/wattpilot-setting-capture.py` utility with the vehicle
disconnected and es-ESS stopped. Its two-gate procedure, redaction rules,
automated checks, restoration steps, and later active-charging validation are
documented in
[docs/wattpilot-command-ownership-validation.md](docs/wattpilot-command-ownership-validation.md).

### Low Price Charging. 
Wattpilot supports the function to charge due to cheap grid prices, you can use the builtin feature as you are used to. es-ESS will then detect,
whenever Wattpilot is charging due to cheap prices and NOT take over any control. 

> :warning: **Hint**:<br /> Using Low Price-Charging would cause your home battery to kick in. Using this feature therefore only makes sence, if you enable the [NoBatToEV](#nobattoev) Service as well, which will offload any power drawn by the EV to the grid,
as long as it is NOT covered by local solar production.

### Credits
Wattpilot control functionality has been taken from https://github.com/joscha82/wattpilot and modified to extract all variables required for full integration.
All buggy overhead (Home-Assistant / Mqtt) has been removed and some bug fixes have been applied to achieve a stable running Wattpilot-Core. (It seems to be unmaintained
since 2 years, lot of pull-requests are not accepted.)

### F.A.Q.

> The wattpilot app is reporting a different charge time than displayed in VRM?

The wattpilot app is reporting the time since the car has been plugged in. Especially with solar overhead charging, that includes a lot of idle time. es-ESS is tracking only the time the car is actually charging and displaying this time in VRM.

> Sometimes VRM is displaying `Stop charging`, `Start charging` or `Switching phasemode` for a long time? 

Whenever one of the preconfigured Start/Stop- or Phaseswitchtimes are exhausted, es-ESS will display the status until the cooldown is passed, or conditions change again. 
So, whenever a sun shortage requires to stop charging, but you have 250s left on the on/off cooldown, VRM will display `Stop charging` for 250s. This is, so you are aware that - even if there is grid-pull happening - wattpilot is about to stop as soon as conditions allow for it. For more details about the current state, you can review the respective service messages topic on mqtt: `es-ESS/{service}/ServiceMessages/ServiceMessageType.Operational`

# NoBatToEV
> :large_orange_diamond: Release-Candiate-Version: Feature is still undergoing development, but current version is already satisfying.

### Overview

If you have your wallbox connected to the AC-OUT (because you like to be able to charge in emergencies) but generally don't want to discharge your home batteries, *NoBatToEV* is what you need. The service monitors
your ev charge, consumption and available solar - and offloads any overhead-ev-charge that is not covered by solar to the grid. 

| Example |
|:-------------------------:|
|<img src="https://github.com/realdognose/es-ESS/blob/main/img/nobattoev.png"> |
| With 0 Solar available, basically the whole ev-charge is offloaded to the grid, while the battery only powers the remaining loads.|

| Example 2 |
|:-------------------------:|
|<img src="https://github.com/realdognose/es-ESS/blob/main/img/nobattoev2.png"> |
| With Solar available, critical loads and EV Charger is covered as good as possible - and the remaining difference is offloaded to the grid.|

Adjusting the Grid-Setpoints of the multiplus is not resulting in a 10W-Precission. Especially with Solar beeing available, the battery will 
naturally switch between charge / discharge as solar changes, until the multiplus have catched up with their new grid set point. 

### Configuration
NoBatToEV requires your gx-local mqtt-server to be enabled, either as plain or ssl.
NoBatToEV requires a few variables to be set in `/data/es-ESS/config.ini`: 


| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [Services]    | NoBatToEV   | Flag, if the service should be enabled or not | Boolean | true |
| [Common]     | VRMPortalID |  Your portal ID to access values on mqtt / dbus |String | VRM0815 |
| [Common]     | DefaultPowerSetPoint |  Default Power SetPoint, so it can be restored after ev charge finished. | double | -50 |
| [Common]     | GridSetPointMinW | Minimum site-approved final grid setpoint. | double | -50 |
| [Common]     | GridSetPointMaxW | Maximum site-approved final grid setpoint. | double | 12000 |
| [NoBatToEV]  | UseRelay | can be -1 (disabled) or 0 or 1. Then NoBatToEV will only be "active", when the Relay 0 or 1 is turned on. (Relay Toggles are available in VRM)|

> :warning: NOTE: this feature manipulates the grid set point in order to achieve proper offloading of your evs energy demand. Several precautions ensure that the configured default grid set point
> is restored when the service is receiving proper shutdown signals (aka SIGTERM) or any kind of internal error appears. - However, in case of unexpected
> powerlosses of your GX-device, complete Hardware-failure, networking-issues or usage of the `reboot` command on the cerbo that may not be the case.
> I have never expierienced issues with that, hence I can't tell what the multiplus will do, if the cerbo `dies`, while the grid set point is -5000 Watt or something.
> I assume, Worstcase, your multiplus will keep charging your houses battery until there is no more consumer for such a (stuck) grid request.

During an orderly shutdown, es-ESS sends the configured default grid set point
as a forced QoS 1 MQTT publication and waits for acknowledgement for up to two
seconds before disconnecting MQTT. Shutdown still continues if the broker does
not acknowledge within that bound.

The final combined setpoint is clamped to `GridSetPointMinW..GridSetPointMaxW`
and each distinct clamp is logged. Version 11 migrates both bounds to the
existing `DefaultPowerSetPoint`, which deliberately prevents dynamic
NoBatToEV adjustments until the operator enters limits approved for the local
ESS, grid connection, protection, and contract. The bounds are safety policy,
not a substitute for Victron input-current or inverter limits.

# Shelly3EMGrid
> :large_orange_diamond: Release-Candiate-Version: Feature is still undergoing development, but current version is already satisfying: NET-Metering is untested so far, need to get hands on a shelly 3EM, fist.

Utilize a Shelly 3 EM as Grid Meter. 

### Configuration

Shelly3EMGrid requires a few variables to be set in `/data/es-ESS/config.ini`: 

| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [Services]    | Shelly3EMGrid   | Flag, if the service should be enabled or not | Boolean | true |
| [Shelly3EMGrid]     | VRMInstanceID |  InstanceID the Meter should get in VRM | Integer | 47 |
| [Shelly3EMGrid]     | CustomName |  Display Name of the device in VRM | String | Shelly 3EM (Grid) |
| [Shelly3EMGrid]     | PollFrequencyMs | Interval in milliseconds to query the Shelly JSON API. Must be greater than `0`. | int | 1000 |
| [Shelly3EMGrid]     | Username |  Username of the Shelly | String | User |
| [Shelly3EMGrid]     | Password |  Password of the Shelly | String | JG372FDr |
| [Shelly3EMGrid]     | Host |  IP / Hostname of the Shelly | String | 192.168.136.87 |
| [Shelly3EMGrid]     | Metering | Type of Measurement. See Info bellow. `Default` or `Net` | String | Default

When adjusting the `PollFrequencyMs`, you should check the log file regulary. The Device is polled with exactly `PollFrequencyMs`
Timeout, so requests do not pile up. Whenever there are 3 consecutive timeouts, the dbus service will be feed with `null` values, and 
the device is marked offline, so the overall system notes that it now has to work without grid-meter values.

### Metering
By Default, the Shelly 3EM uses Gross-Metering. Feed-In and Consumption are counted for each phase individually. 

In some countries however (f.e.: Germany, Switzerland, Austria, ... ) Net-Metering is used by the providers. 
Values of each phase are saldated immediately, and then it will be either counted as Feed-In or Grid-Pull.

The Shelly does not support this kind of measurement, so the script can take over this. It therefore needs to 
manually keep track of the momentary values for each phase and manually count. These values are persisted on the cerbo
every 5 minutes, so in case of a unexpected shutdown, they are not lost. 

However, since this requires to count the momentary values and derive a hourly consumption from that values, it 
may be less precise than any other meter. Also flows that happen while the shelly or es-ESS is offline cannot be 
recovered, leading to temporary "gaps" on the consumption/feed-in records.

Persisted net counters are written with flush, filesystem synchronization, and
atomic replacement. Missing files start at zero; corrupt, non-finite, or
negative values are ignored with a warning. A failed Shelly poll resets the
integration timestamp, so power observed after an outage is never applied to
the unknown outage interval. This intentionally leaves an energy gap instead
of inventing consumption or feed-in.

### Example config

<img src="https://github.com/realdognose/es-ESS/blob/main/img/shelly3emexample.png">

<img src="https://github.com/realdognose/es-ESS/blob/main/img/shelly3emexample2.png">

# ShellyPMInverter
> :white_check_mark: Production Ready. 

Utilize a Shelly PM (any Kind, Generation 3) as a meter to detect PV-Inverter Production. 
Phase on which the inverter is feeding in can be adjusted, mostly usefull for single phased micro inverters without any other
communication possibility. 

### Configuration

ShellyPMInverter requires a few variables to be set in `/data/es-ESS/config.ini`: 

| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [Services]    | Shelly3EMGrid   | Flag, if the service should be enabled or not | Boolean | true |

After enabling the service in general, you need to create 1 additional config-section per shelly to use. 
each config Section needs to match the pattern `[ShellyPMInverter:aUniqueKey]` and contain the following values: 

| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [ShellyPMInverter:aUniqueKey]     | VRMInstanceID |  InstanceID the Meter should get in VRM | Integer | 1008 |
| [ShellyPMInverter:aUniqueKey]     | CustomName |  Display Name of the device in VRM | String | HMS-Garage |
| [ShellyPMInverter:aUniqueKey]     | PollFrequencyMs | Interval in milliseconds to query the Shelly JSON API. Must be greater than `0`. | int | 1000 |
| [ShellyPMInverter:aUniqueKey]     | Username |  Username of the Shelly | String | User |
| [ShellyPMInverter:aUniqueKey]     | Password |  Password of the Shelly | String | JG372FDr |
| [ShellyPMInverter:aUniqueKey]     | Host |  IP / Hostname of the Shelly | String | 192.168.136.87 |
| [ShellyPMInverter:aUniqueKey]     | Phase |  Phase the Shelly / Inverter is connected to. (1-3) | Integer | 2 |
| [ShellyPMInverter:aUniqueKey]     | Position |  Position, the Shelly / Inverter is connected to your multiplus. 0 = ACIN; 1=ACOUT | Integer | 1 |
| [ShellyPMInverter:aUniqueKey]     | Relay |  id of the relay, if multiple. | Integer | 0 |

When adjusting the `PollFrequencyMs`, you should check the log file regulary. The Device is polled with exactly `PollFrequencyMs`
Timeout, so requests do not pile up. Whenever there are 3 consecutive timeouts, the dbus service will be feed with `null` values, and 
the device is marked offline, so the overall system notes that the inverter is currently considered not producing.

Example Configuration:

<img src="https://github.com/realdognose/es-ESS/blob/main/img/pmInverterExample.png">

<img src="https://github.com/realdognose/es-ESS/blob/main/img/pmInverterExample2.png">

<img src="https://github.com/realdognose/es-ESS/blob/main/img/pmInverterExample3.png">

<img src="https://github.com/realdognose/es-ESS/blob/main/img/pmInverterExample4.png">


# SolarOverheadDistributor

> :large_orange_diamond: Release-Candiate-Version

> :warning: This Feature requires a grid-connection and feedin to be enabled. (The amount beeing feed in is used to detect available overhead, when soc reached 100%)

#### Overview
Sometimes you wish to manage multiple consumers based on solar overhead available. If every consumer is deciding on it's own, it can 
lead to a continious up and down on available energy, causing consumers to turn on/off in a uncontrolled, frequent fashion. 

To overcome this problem, the SolarOverheadDistributor has been created. Each consumer can register itself, send a request containing certain parameters - and
SolarOverheadDistributor will determine the total available overhead of the system and calculate allowances for each individual consumer based on preconfigured
priorities. 

A minimum battery reservation can be defined through a SOC-based equation to make sure your home-battery receives the power it needs to fully charge during the day.

Each consumer is represented as a FAKE-BMS in VRM, so you can see where your energy is currently going. 

> :warning: **Fake-BMS injection**:<br /> This feature is creating Fake-BMS information on dbus. Make sure to manually select your *actual* BMS unter *Settings > System setup > Battery Monitor* else your ESS may not behave correctly anymore. Don't leave this setting to *Automatic*

| Example View |
|:-------------------------:|
|<img src="https://github.com/realdognose/es-ESS/blob/main/img/SolarOverheadConsumers%203.png"> |
| <div align="left">The example shows the view in VRM and presents the following information: <br /><br />- There is a a Battery reservation active (only 250W), because it reached 100% SoC. (Idling at 26W)<br />- The consumer *Pool Filter* is requesting a total of 220W, and due to the current allowance, 205W currently beeing consumed, equaling 92.7% of it's request. <br />- The consumer  *Pool Heater* is requesting a total of 750W, and due to the current allowance, 650W currently beeing consumed, equaling 86.6% of it's request. <br />- The consumer  *Waterplay* is requesting a total of 120W, and due to the current allowance, 120W currently beeing consumed, equaling 100% of it's request. <br />- The consumer  *PV Heater* is requesting a total of 3300W, and due to the current allowance, 1067W currently beeing consumed, equaling 32.3% of it's request. <br /> - The consumer [WattPilot](#FroniusWattpilot) is requesting a total of 11388W, and due to the current allowance, 6073W currently beeing consumed, equaling 53.3% of it's request. <br /> - All Consumers are currently running in automatic mode (listening to distribution), this is indicated through the tiny sun icon: ☼ </div>|

#### General functionality
The SolarOverheadDistributor (re-)distributes power every minute. We have been running tests with more frequent updates, but it turned out that the delay in processing a request/allowance by some consumers is causing issues. 
Also, when consumption changes, the whole ESS itself needs to adapt, adjust battery-usage, grid-meter has to catch up, values have to be re-read and published in dbus and so on. Finally also the sun may have some ups and downs
during ongoing calculations. So we decided to go with a fixed value of 1 minute, which is fast enough to adapt quickly but not causing any issues with consumers going on/off due to delays in processing.

### Usage
Each consumer can create a SolarOverhead-Request, which then will be accepted or not by the SolarOverheadDistributor based on various parameters. The overall request has to be send to the mqtt topic `es-ESS/SolarOverheadDistributor/Requests` where es-ESS will catch up the request, process it and add the `allowance` property to the request.

A request is made out of the following values, where some are mandatory, some optional: 

each key has to be published in the topic `es-ESS/SolarOverheadDistributor/Requests/{consumerIdentifier}/`

| Mqtt-Key             | To be set by Consumer |  Descripion                                                             | Type          | Example Value| Required |
| -------------------- | ----------------------|------------------------------------------------------------------------ | ------------- |--------------| ---------|
|IsAutomatic             | yes                   | Flag, indicating if the consumer is currently in automatic mode         | Boolean       | true         | yes      |
|Consumption           | yes                   | Current consumption of the consumer                                     | Double        | 1234.0       | yes      |
|CustomName            | yes                   | DisplayName on VRM                                                      | String        | My Consumer 1| yes      |
|IgnoreBatReservation  | yes                   | Consumer shall be enabled when there is sufficent solar, despite active Battery Reservation            | Boolean       | true         | no       |
|Request               | yes                   | Total power this consumer would ever need.                              | Double        | 8500.0       | yes      |
|StepSize              | yes                   | StepSize in which the allowance should be generated, until the total requests value is reached. | Double       | 123.0         | yes      |
|Minimum               | yes                   | A miminum power that needs to be assigned as step1. Usefull for EVs that require a minimum start power.    | Double        | 512.0         | no      |
|Priority               | yes                   | Priority compared to other Consumers. defaults to 100    | Integer        | 56         | no      |
|PriorityShift          | yes                   | Priority decrease after an assignment (See example bellow)    | Integer        | 1         | no      |
|VRMInstanceID         | yes                   | The ID the battery monitor should use in VRM                            | Integer       | 1008          | yes     |
|Allowance             | no                    | Allowance in Watts, calculated by SolarOverheadDistributor. Has to be picked up by the consumer.                 | Double        | 768.0         | n/a     |

SolarOverheadDistributor will process these requests and finally publish the result under: `es-ESS/SolarOverheadDistributor/Requests/{consumerIdentifier}/allowance`

- It is important to report back consumption by the consumer. Only then the calculated values are correct, because the consumption of every controlled consumer is *available Budget*.
- Only consumers reporting as automatic will be considered. (So maintain this, when implementing manual overrides, i.e. an unplugged EV should not request overhead-share, else it will receive an allowance and block other consumers with lower priority)

### Scripted-SolarOverheadConsumer
A Scripted-SolarOverheadConsumer is an external script (Powershell, bash, arduino, php, ...) you are using to control a consumer. This allows the requests to be more precice and granular
than using a NPC-SolarOverheadConsumer (explained later). 

The basic workflow of an external script can be described as follows: 

```
   every x seconds or event based:
      check own environment variables.
      determine suitable request values.
      send request to mqtt server
      process current allowance
      report actual consumer consumption to mqtt.
```

For example, I have an electric water heater (called *PV-Heater*) that can deliver roughly 3500 Watts of total power, about 1150 Watts per phase. The script controlling this consumer
takes various environment conditions into account before creating a request: 

 - If the temperature of my water reservoir is bellow 60°C, a full request of 3500 Watts is created.
 - If the temperature of my water reservoir is between 60°C and 70°C, the maximum request is 2 phases, so roughly 2300 Watts.
 - If the temperature of my water reservoir is between 70°C and 80°C, the maximum request is 1 phase, so roughly 1150 Watts.
 - If the temperature of my water reservoir is above 80°C, no heating is required, so the request will be 0 Watts.
 - If the EV is connected and waiting for charging, the maximum request will be 2 phases, so roughly 2300 Watts.
 - If the co-existing thermic solar system is producing more than 3000W power, no additional electric heating is required, so request is 0 Watts.

After evaluating and creating the proper request, the current allowance is processed, consumer is adjusted based on allowance, and actual consumption is reported back.

> :warning: NOTE: es-ESS will set the allowance for every consumer to 0, when the service is receiving proper shutdown signals (aka SIGTERM) - However, in case of unexpected
> powerlosses of your GX-device, complete Hardware-failure, networking-issues or usage of the `reboot` command on the cerbo that may not be the case.
> To ensure your scripted consumers don't run for an indefinite amount of time, you should not only validate the `allowance` as outlined above, but also the topic
> `es-ESS/$SYS/Status`. This is set to `Online` at startup and set to `Offline` per last-will. So, if your consumers note that es-ESS is going offline - it is
> up to you if they should keep running or stop as well.

### NPC-SolarOverheadConsumer
Some consumers are not controllable in steps or you simply don't want to write scripts for them. To eliminate the need to create multiple on/off-scripts for these consumers, 
the NPC-SolarOverheadConsumer has been introduced. es-ESS can automatically control consumers that can be switched on/off through `http` or `mqtt`.

HTTP consumer control, status, and power requests are bounded by
`[Common] HttpRequestTimeout` so slow or unavailable endpoints cannot block
SolarOverheadDistributor worker threads indefinitely.

It can be fully configured in `/data/es-ESS/config.ini` and will be orchestrated by the SolarOverhead-Distributer itself. An example would be our *waterplay* in the front garden. It is connected through a (first-gen, dumb) shelly device, which is at least http-controllable - and I know it consumes roughly 120 Watts AND I want this to run as soon as Solar-Overhead is available, despite any battery reservation. (Doesn't make sence to wait, until the battery reached 90% Soc or more)

The following lines inside `/data/es-ESS/config.ini` can be used to create such an NPC-SolarOverheadConsumer. A config section has to be created, containing
the required request values plus some additional parameters for remote-control. The section has to be prefixed with `HttpConsumer:` or `MqttConsumer:` to identify it correctly. These devices are explicitly configured; es-ESS does not discover pool pumps, heaters, Shelly devices, or other loads automatically.

HTTP/MQTT NPC consumers are binary loads, so their allocation is atomic. Set
`Request` to the complete power that the device needs while on. The distributor
grants either the complete `Request` or `0`; it never reserves a partial
allowance that the device cannot use. `Minimum` and `StepSize` are obsolete for
NPC sections and are ignored by NPC allocation. Scripted consumers still use
their published minimum and step size.

For example, assume an explicitly configured 1000 W pool pump has higher
priority than an explicitly configured 500 W heater, but only 800 W is
available after the battery reservation. The pump cannot use a partial grant,
so it receives `0`. The eligible lower-priority heater may receive its complete
500 W request, leaving 300 W unassigned. This is intentional. Configure
`Request` from the load's real steady/start operating requirement, and use only
non-critical equipment whose on/off endpoint, status feedback, measured power,
and safe fallback behavior have been verified.

the example consumerKey is *waterplay* here.

| Section    | Value name |  Descripion | Type | Example Value|
| ------------------ | ---------|---- | ------------- |--|
| [HttpConsumer:waterplay]    | CustomName |  DisplayName on VRM   |String | Waterplay |
| [HttpConsumer:waterplay]    | IgnoreBatReservation             | Consumer shall be enabled despite active Battery Reservation            | Boolean       | true         |
| [HttpConsumer:waterplay]    | VRMInstanceID                    | The ID the battery monitor should use in VRM                            | Integer       | 1008          | 
| [HttpConsumer:waterplay]    | ~~minimum~~                       | obsolete for on/off NPC-consumers     | ~~Double~~        | ~~0~~|
| [HttpConsumer:waterplay]    | ~~stepSize~~                         | obsolete for on/off NPC-consumers | ~~Double~~       | ~~120.0~~|
| [HttpConsumer:waterplay]    | Request                              | Total power this consumer would ever need.                              | Double        | 120.0       | 
| [HttpConsumer:waterplay]    | OnUrl                              | http(s) url to active the consumer                            | String        | http://shellyOneWaterPlayFilter.ad.equinox-solutions.de/relay/0/?turn=on       | 
| [HttpConsumer:waterplay]    | OffUrl                              | http(s) url to deactive the consumer                               | String        | http://shellyOneWaterPlayFilter.ad.equinox-solutions.de/relay/0/?turn=off      | 
| [HttpConsumer:waterplay]    | StatusUrl                              | http(s) url to determine the current operation state of the consumer                            | String        | http://shellyOneWaterPlayFilter.ad.equinox-solutions.de/status       | 
| [HttpConsumer:waterplay]    | IsOnKeywordRegex                              | If this Regex-Match is positive, the consumer is considered *On* (evaluated against the result of statusUrl)                            | String        | "ison":\s*true      | 
| [HttpConsumer:waterplay]    | PowerUrl                              | http(s) url to determine the current consumption state of the consumer. If left empty, es-ESS will assume `Consumption=Request` while the consumer is switched on.                            | String        | 'http://shellyOneWaterPlayFilter.ad.equinox-solutions.de/status'       | 
| [HttpConsumer:waterplay]    | PowerExtractRegex     | Regex to extract the consumption. Has to have a SINGLE matchgroup.                            | String        | "apower":([^,]+),      | 

If the NPC is mqtt controlled, you need to provide the Topics, instead of the URLs:
| Section    | Value name |  Descripion | Type | Example Value|
| ------------------ | ---------|---- | ------------- |--|
| [MqttConsumer:poolHeater]    | OnTopic               | MqttTopic to activate the consumer                                                                              | String        | Devices/shellyPro2PMPoolControl/IO/Heater/Set       | 
| [MqttConsumer:poolHeater]    | OnValue               | MqttValue to publish on `OnTopic` to activate the consumer                                                      | String        | true      | 
| [MqttConsumer:poolHeater]    | OffTopic              | MqttTopic to deactivate the consumer                                                                            | String        | Devices/shellyPro2PMPoolControl/IO/Heater/Set     | 
| [MqttConsumer:poolHeater]    | OffValue              | MqttValue to publish on `OffTopic` to deactivate the consumer                                                     | String        | false      | 
| [MqttConsumer:poolHeater]    | StatusTopic           | MqttTopic to determine the current operation state of the consumer                                             | String        | Devices/shellyPro2PMPoolControl/IO/Heater/State       | 
| [MqttConsumer:poolHeater]    | IsOnKeywordRegex      | If this Regex-Match is positive, the consumer is considered *On* (evaluated against the Messages on StatusTopic)                            | String / Regex        | true         | 
| [MqttConsumer:poolHeater]    | PowerTopic            | MqttTopic to determine the current consumption state of the consumer. If left empty, es-ESS will assume `Consumption=Request` while the consumer is switched on.                            | String        | Devices/shellyPro2PMPoolControl/IO/Heater/Power       | 
| [MqttConsumer:poolHeater]    | PowerExtractRegex     | Regex to extract the consumption. Has to have a SINGLE matchgroup. (evaluated against the Messages on PowerTopic). Using `(.*)` because it's a well-formated decimal value here.            | String / Regex        | (.*)      | 

Example (Screenshots)

Pool-Filter (via a Shelly Pro2 PM) as http-consumer:

<img align="center" src="https://github.com/realdognose/es-ESS/blob/main/img/poolFilterAsHTTP.png">

Pool-Heater (via s Shally Pro2 PM) as mqtt-consumer. (Got my own mqtt/rpc infrastructure, tho)

<img align="center" src="https://github.com/realdognose/es-ESS/blob/main/img/poolHeaterAsMqtt.png">

### Configuration
SolarOverheadDistributer requires a few variables to be set in `/data/es-ESS/config.ini`: 

> :warning: **Fake-BMS injection**:<br /> This feature is creating Fake-BMS information on dbus. Make sure to manually select your *actual* BMS unter *Settings > System setup > Battery Monitor* else your ESS may not behave correctly anymore. Don't leave this setting to *Automatic*

| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [Common]    | VRMPortalID |  Your portal ID to access values on mqtt / dbus |String | VRM0815 |
| [Services]    | SolarOverheadDistributor | Flag, if the service should be enabled or not | Boolean | true |
| [SolarOverheadDistributor]  | VRMInstanceID |  VRMInstanceId to be used on dbus | Integer  | 1000 |
| [SolarOverheadDistributor]  | VRMInstanceID_ReservationMonitor |  VRMInstanceId to be used on dbus (for the injected Fake-BMS of the active battery reservation) | Integer  | 1001 |
| [SolarOverheadDistributor]  | MinBatteryCharge |  Equation to determine the active battery reservation. Use SOC as keyword to adjust. Supported syntax is numeric literals, `SOC`, `min()`/`max()`, parentheses, and `+`, `-`, `*`, `/`. If SOC is unavailable or the expression is invalid, es-ESS logs the issue and uses `0` for that cycle. | String  | 5000 - 40 * SOC |
| [SolarOverheadDistributor]  | UpdateInterval | Worker interval in milliseconds. Must be greater than `0`. | Integer | 5000 |

In order to have the FAKE-BMS visible in VRM, you need to go to *Settings -> System Setup -> Battery Measurement* and set the ones you'd like to see to *Visible*:



<div align="center">

| Cerbo Configuration for FAKE-BMS |
|:-----------:|
| <img align="center" src="https://github.com/realdognose/es-ESS/blob/main/img/cerboSettings.png" /> |
</div>

<div align="center">

| Typically usefull equations for `MinBatCharge` |
|:-----------:|
| Blue := Linear going down, with a maxium of 5400Watts and a minimum of 400W: `5000-50*SOC+400`|
| Green := Enforce battery charge of 3000W upto ~ 90% SoC: `3000/(min(SOC,99)-100)+3000`|
| Red := Just enforce at very low SoC, but 1500W minimum: `(1/(SOC/8)*5000)+1000`|
| <img align="center" src="https://github.com/realdognose/es-ESS/blob/main/img/socFormula.png"> |
</div>

### Priority Shifting ###
Priority shifting is a powerfull feature allowing you to control your consumers in a sophisticated way. SolarOverheadDistributor will always give away `StepSize` Watts to a single consumer.
Once an assignment has been done, and priority shifting is enabled for this consumer, it's priority for the next distribution round is lowered by the given `PriorityShift` value. (defaults to 0,
if not provided)

i.e.: My EV could consume upto 11.000 Watts, leaving nothing for other consumers. I have a 3*1000 Watt electric heater that should have kinda lower priority, but 
also be considered with energy. 

So, I configured the following Values: 

- EV: Priority `35`, PriorityShift `1`, StepSize: `250`, Minimum: `1365`
- Heater: Priority `40`, PriorityShift `5`, StepSize: `1000`

Now, SolarOverheadDistributor will give away available Energy in the following pattern. 

> :information_source: es-ESS will also add another `0.0001` with every shift performed. This ensures that once two consumers hit the same priority, the priority stays predictable: 
> The consumer received lesser assignments so far will have the higher priority, as illustrated bellow. If you are using the same `Priority` and `PriorityShift` value for all consumers,
> you'll effectively achieve a round-robin distribution.

1) EV +1365 due to priority 35 and minimum start power.
2) EV +250 due to priority 36.0001
3) EV +250 due to priority 37.0002
4) EV +250 due to priority 38.0003
5) EV +250 due to priority 39.0004
6) PV Heater +1000 due to priority 40
7) EV +250 due to priority 40.0005
8) EV +250 due to priority 41.0006
9) EV +250 due to priority 42.0007
10) EV +250 due to priority 43.0008
11) EV +250 due to priority 44.0009
12) PV Heater +1000 due to priority 45.0001
13) EV +250 due to priority 45.0010
14) EV +250 due to priority 46.0011
....

### Nough' said

The SolarOverheadDistributor is a quite a lot of configuration and not something that is fully configured within 10 minutes. But once setup properly, the results are just flawless. 
Here are some graphs of my (not yet published) Dashboard, which shows how well SolarOverheadDistributor is managing consumers of any shape - starting with the tiny waterplay
of 200 Watts, ending at my 11kW EV-Charging station: 

<div align="center">

| Good day :) |
|:-----------:|
| <img align="center" src="https://github.com/realdognose/es-ESS/blob/main/img/example_overhead2.png" /> |

</div>

<div align="center">

| Not so sunny day, but consumers taking any chance. |
|:-----------:|
| <img align="center" src="https://github.com/realdognose/es-ESS/blob/main/img/solarOverhead_Gaps.png" /> |

</div>

<div align="center">

| yet another day |
|:-----------:|
| <img align="center" src="https://github.com/realdognose/es-ESS/blob/main/img/example_overhead1.png" /> |

</div>

# Dormant service modules

The repository retains legacy source modules for `MqttDC`,
`ChargeCurrentReducer`, and `FroniusSmartmeterRS485`, but `es-ESS.py` does not
load them. They are not supported configuration options and are intentionally
absent from `config.sample.ini`. `Grid2Bat` is also unavailable; its runtime
hook is disabled and no implementation module exists in this checkout.

Do not enable these names in `[Services]`. In particular,
`ChargeCurrentReducer` must not be reactivated without first moving its direct
grid-setpoint writes behind the shared request combiner and completing a
separate implementation, safety review, documentation, and test task.


# This and that

### Logging
es-ESS can log a lot of information helpfull to debug things. For this, the loglevel in the configuration can be adjusted.
The log file is placed in `/data/logs/es-ESS/current.log` and rotated every day at midnight (UTC). A total of 14 log files is kept, then recycled.

> :warning: Having es-ESS running at log level `TRACE` for a long time will produce huge log files and negatively impact system performance. This will log all incoming and outgoing values, we are talking about thausands of lines of log per minute here, depending on enabled services. Rather usefull for development purpose with single service(s) enabled. 

| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [Common]    | LogLevel |  Options: TRACE, DEBUG, APP_DEBUG, INFO, WARNING, ERROR, CRITICAL | String | INFO |

`APP_DEBUG` is a level higher than regular `DEBUG`, so this will surpress Debug messages of third party modules as long as they obey the setup log level.

<div align="center">

| Logrotation to avoid filling up the disk |
|:-----------:|
| <img align="center" src="https://github.com/realdognose/es-ESS/blob/main/img/logrotate.png" /> |

</div>

### More Configx

Additionally there are the following configuration options available: 

| Section    | Value name |  Descripion | Type | Example Value|
| ---------- | ---------|---- | ------------- |--|
| [Common]    | NumberOfThreads |  Number of threads, es-ESS should use. | int | 5 |
| [Common]    | ServiceMessageCount | Number of service messages published on mqtt | int | 50 |
| [Common]    | ConfigVersion | Current Config Version. DO NOT TOUCH THIS, it is required to update configuration files on new releases. | int | 11 |
| [Common]    | HttpRequestTimeout | Maximum seconds for shared HTTP requests used by SolarOverheadDistributor HTTP consumers. | double | 5 |

### Service Messages
es-ESS also publishes Operational-Messages as well as Errors, Warnings and Critical failures under the `service`-Topic of the serivce. Check these from time to time to ensure proper functionality

<div align="center">

| Service Messages on MQTT |
|:-----------:|
| <img align="center" src="https://github.com/realdognose/es-ESS/blob/main/img/ServiceMessages.png" /> |

</div>


# F.A.Q.

See also the service-specific F.A.Q. at the end of each service-description.

# FroniusWattpilot runtime-status contract

FroniusWattpilot publishes an authoritative runtime-status contract for
Cerbo extensions, dashboards, MQTT consumers, and diagnostics. The contract
is separate from the normal Victron EV-charger status path.

The standard `/Status` path remains VRM-compatible and is not changed to
force a custom Charging label. `/CustomName` is optional presentation metadata
only; it is not used as a source of phase or runtime state. During a Wattpilot
transport outage, `/CustomName` is temporarily set to
`Wattpilot not reachable` for detail views, D-Bus inspection, MQTT consumers,
and SolarOverheadDistributor messages.

The standard Venus OS / GX EVCS overview tile has a display limitation: current
gui-v2 sources render the tile title from a fixed translated `EVCS` label and
the single-charger details from the standard `/Status`, `/Mode`,
`/Session/Energy`, and `/Session/Time` values. That tile does not read the
service `/CustomName` or `/StatusLiteral`, so a Wattpilot transport outage may
still appear there as `EVCS`, `Disconnected`, and the selected mode such as
`Auto`. Use the EV-charger detail view, D-Bus, MQTT runtime status, es-ESS
service messages, or SolarOverheadDistributor messages for the specific
`Wattpilot not accessible` / `Wattpilot not reachable` outage text. This is the
supported route in es-ESS until a maintained GX dashboard extension or upstream
Victron `gui-v2` change is selected.

For EVCS overview compatibility, es-ESS publishes Wattpilot session energy and
time on both the older project paths and the current Venus session paths:
`/Ac/Energy/Forward` mirrors `/Session/Energy`, and `/ChargingTime` mirrors
`/Session/Time`.

EVCS precision, unit display, and charging-time text are formatted by the
selected Victron UI surface. Current `gui-v2` overview, list, and detail pages
use different compact labels and quantity-table components, so the same
truthful D-Bus values can appear with different rounding or time text. es-ESS
does not round these numeric paths or publish display strings to force visual
alignment; if exact cross-surface formatting is important, handle it as a
Victron UI change rather than an es-ESS data-contract change.

The following D-Bus values are published on the existing
`com.victronenergy.evcharger.*_FroniusWattpilot` service:

| D-Bus path | Type | Meaning |
| --- | --- | --- |
| `/ControlState` | Integer | Stable numeric runtime state, as defined below. |
| `/ControlStateLiteral` | String | Exact human-readable runtime-state literal. |
| `/PhaseMode` | Integer | `0` for unknown/transition, `1` for one phase, `3` for three phases. |
| `/PhaseModeLiteral` | String | `Unknown`, `Transition`, `1 phase`, or `3 phases`. |
| `/BatteryAssistActive` | Integer | `1` only during the optional, time-limited battery bridge; otherwise `0`. |
| `/GridImportGuardActive` | Integer | `1` while the Auto/Eco grid-import guard is active; otherwise `0`. |
| `/TelemetryHealthy` | Integer | `1` when the telemetry needed for the current control mode is healthy; otherwise `0`. |
| `/CommandAuthorityOk` | Integer | `1` only when firmware is validated, raw mode is ECO, and native PV/tariff command competitors are both disabled. |
| `/CommandAuthorityLiteral` | String | Actionable authority state, including which Solar.wattpilot setting must be changed. |
| `/NativePvSurplusEnabled` | Integer | Strict `fup` observation: `1` enabled, `0` disabled, `-1` unavailable or malformed. |
| `/FlexibleTariffEnabled` | Integer | Strict `ful` observation: `1` enabled, `0` disabled, `-1` unavailable or malformed. |

`/ControlState` and `/ControlStateLiteral` always represent the same state:

| Value | Literal |
| ---: | --- |
| 0 | `Stopped` |
| 1 | `Waiting for PV` |
| 2 | `Waiting for stable PV` |
| 3 | `Charging 1 phase` |
| 4 | `Charging 3 phases` |
| 5 | `Switching to 1 phase` |
| 6 | `Switching to 3 phases` |
| 7 | `Battery assist` |
| 8 | `Stopped for grid import` |
| 9 | `Stopped for stale telemetry` |
| 10 | `Fault` |
| 11 | `Stopped: command authority blocked` |

All eighteen runtime-status values are mirrored to retained main-MQTT topics:

```text
es-ESS/FroniusWattpilot/RuntimeStatus/ControlState
es-ESS/FroniusWattpilot/RuntimeStatus/ControlStateLiteral
es-ESS/FroniusWattpilot/RuntimeStatus/PhaseMode
es-ESS/FroniusWattpilot/RuntimeStatus/PhaseModeLiteral
es-ESS/FroniusWattpilot/RuntimeStatus/BatteryAssistActive
es-ESS/FroniusWattpilot/RuntimeStatus/GridImportGuardActive
es-ESS/FroniusWattpilot/RuntimeStatus/TelemetryHealthy
es-ESS/FroniusWattpilot/RuntimeStatus/CompatibilityOk
es-ESS/FroniusWattpilot/RuntimeStatus/CompatibilityLiteral
es-ESS/FroniusWattpilot/RuntimeStatus/CommandAuthorityOk
es-ESS/FroniusWattpilot/RuntimeStatus/CommandAuthorityLiteral
es-ESS/FroniusWattpilot/RuntimeStatus/NativePvSurplusEnabled
es-ESS/FroniusWattpilot/RuntimeStatus/FlexibleTariffEnabled
es-ESS/FroniusWattpilot/RuntimeStatus/ExpectedVenusOsVersion
es-ESS/FroniusWattpilot/RuntimeStatus/ActualVenusOsVersion
es-ESS/FroniusWattpilot/RuntimeStatus/ExpectedWattpilotFirmware
es-ESS/FroniusWattpilot/RuntimeStatus/ActualWattpilotFirmware
es-ESS/FroniusWattpilot/RuntimeStatus/ValidatedWattpilotAppVersion
```

All runtime-status MQTT topics are retained. The status is republished
immediately when a charge starts or stops, a phase change starts or finishes,
the grid-import guard or command-authority state changes, required telemetry
becomes stale or healthy, battery assist changes, the Wattpilot disconnects or
reconnects, or the controller enters a fault state.

For an active charge, `/PhaseMode` and the phase-qualified charging state use
the Wattpilot's live L1/L2/L3 power telemetry. This keeps Manual mode accurate
when the Auto/Eco controller's remembered phase command is unavailable or
stale. A pending Auto/Eco phase transition remains `Transition` until the
controller confirms the result; the controller's phase command is used only as
a fallback while live phase telemetry is unavailable. After a confirmed vehicle
disconnect, the public phase state is cleared to `0` / `Unknown` even if those
inputs still contain the last session's phase. Internal phase memory is not
changed and no Wattpilot command is issued.

No extra configuration setting is required for the runtime-status contract.
Normal Wattpilot Manual mode remains unchanged. In Auto/Eco mode, the runtime
contract only reports the existing PV-only control decisions; it does not
authorise grid power. Battery assist remains an optional, time-limited bridge
for an already-running charge and never starts a session or triggers a
phase-up. The contract adds no shared 16 A cable/current-limiting logic.

### Startup, reconnect, and stale-transport behavior

A Wattpilot that is unavailable when es-ESS or the GX starts no longer makes
Wattpilot initialization wait through consecutive 30-second field checks. The
Wattpilot client is started with its automatic reconnect behavior, and the
client keeps reconnect attempts inside one daemon WebSocket worker loop. Close
callbacks only record the close event; they do not recursively re-enter the
WebSocket loop. The runtime contract remains in a safe neutral state until a
usable controller cycle is available:

```text
/ControlState = 0
/ControlStateLiteral = Stopped
/TelemetryHealthy = 0
/CommandAuthorityOk = 0
```

This is an unavailable-startup state, not `Stopped for stale telemetry`.
When the Wattpilot reconnects and the normal Auto/Eco telemetry baseline is
healthy, the contract recovers automatically to the actual state, for example
`Waiting for PV` and `TelemetryHealthy = 1`.

For a live connection, the reporter observes raw Wattpilot WebSocket traffic.
After at least one healthy message has been received, more than 60 seconds with
no further message while the client still appears connected is treated as stale
transport. In Auto/Eco the contract publishes `Stopped for stale telemetry` and
`TelemetryHealthy = 0`; it does not alter the existing controller command path.
The first later Wattpilot message restores transport health on the next normal
controller update. In Manual mode the same condition reports
`TelemetryHealthy = 0` but does not impose an Auto/Eco stop or otherwise change
Manual charging behavior.

A normal WebSocket close or Wattpilot power loss reports `Stopped` and
`TelemetryHealthy = 0`. The status is republished on the next normal controller
update, which runs on the existing five-second Wattpilot control cadence; raw
WebSocket callback threads do not publish D-Bus or MQTT values directly.
