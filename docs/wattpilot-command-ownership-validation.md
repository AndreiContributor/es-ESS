# Wattpilot Auto/Eco Command-Ownership Validation

This guide closes the evidence gap between native Solar.wattpilot PV regulation
and es-ESS Auto/Eco commands. It is split into two gates:

1. command-free firmware-setting discovery with the vehicle disconnected;
2. supervised active-charging validation only after the discovered firmware
   fields have been reviewed and an authority rule has been implemented.

Do not skip the first gate. Wattpilot firmware settings are not a public es-ESS
API, and a guessed mapping could either block safe charging or leave two
controllers issuing conflicting current and phase decisions.

## Safety boundaries

- Use Venus OS `v3.75`, Wattpilot firmware `42.5`, and operator-verified
  Solar.wattpilot app `2.1.0` only.
- Keep the vehicle physically disconnected throughout setting discovery.
- Keep flexible-tariff charging disabled when the vehicle is connected.
- Do not select Standard/Manual as a workaround for Auto/Eco control.
- Do not force grid import, battery discharge, low PV, or a telemetry outage.
- Restore every Solar.wattpilot setting before reconnecting the vehicle.
- Keep raw captures outside Git. They may still contain operational property
  names and numeric values even though strings and known sensitive fields are
  redacted or fingerprinted.
- Stop immediately if the firmware is not exactly `42.5`, the script reports a
  connected vehicle, the charger behaves unexpectedly, or the original settings
  cannot be restored confidently.

The capture utility installs a command guard that rejects every Wattpilot
`setValue` request. It uses only authentication and `requestFullStatus` after
connecting. The unit test suite also rejects any state-changing Wattpilot method
call added to the script.

## Gate 1 - Command-free firmware-setting discovery

### 1. Record the baseline

Before changing anything, record:

- Venus OS version: `v3.75`;
- Wattpilot firmware: `42.5`;
- Solar.wattpilot app version: `2.1.0`;
- vehicle physically disconnected;
- `Use PV surplus` state;
- flexible-tariff state and provider;
- start-up power level;
- 3-phase power level or phase-change setting;
- control-response setting;
- zero-feed-in setting;
- selected inverter;
- current-limit and cable settings.

Take screenshots of the relevant app pages. Do not include passwords, API keys,
Wi-Fi credentials, or unrelated site identifiers in the delivery package.

### 2. Verify the deployed capture files

Run the capture-tool unit tests in the development checkout or CI; test files
do not need to be copied to production. On the GX device, verify the deployed
script syntax and compare its checksum with the reviewed artifact:

```sh
cd /data/es-ESS
python -m py_compile scripts/wattpilot-setting-capture.py
sha256sum scripts/wattpilot-setting-capture.py
```

Pass criteria:

- syntax compilation succeeds;
- the checksum matches the reviewed script (the 2026-07-14 Gate-1 artifact was
  `7500734393d18ec7feb21f852b661cd8fc41a14b987cee14c3d8becd48280ba0`);
- all capture-tool unit tests pass in development/CI;
- no dependency is installed or upgraded for this procedure.

### 3. Stop es-ESS and confirm the vehicle is disconnected

Use an attended low-risk window:

```sh
svc -d /service/es-ESS
svstat /service/es-ESS
pgrep -af '^python[[:space:]]+/data/es-ESS/es-ESS.py$' || true
```

Pass criteria:

- `svstat` reports the service down;
- no es-ESS Python process remains;
- the vehicle is physically disconnected;
- the Wattpilot remains reachable from the GX device and app.

Do not continue if another controller can start charging independently while
the vehicle is disconnected or if the service cannot be stopped cleanly.

### 4. Create a protected capture directory

```sh
mkdir -p /data/es-ESS-validation
chmod 700 /data/es-ESS-validation
umask 077
ls -ld /data/es-ESS-validation
```

Each command below captures one direction of one app setting. The script first
connects and records a baseline. Only after it prints its prompt should the
operator change exactly the named setting in Solar.wattpilot, wait for the app
to confirm it, and press Enter in SSH. JSON is then written to the named file.

### 5. Capture `Use PV surplus` in both directions

Example when the original state is enabled:

```sh
python scripts/wattpilot-setting-capture.py \
  --config config.ini \
  --label use-pv-on-to-off \
  > /data/es-ESS-validation/use-pv-on-to-off.json

python scripts/wattpilot-setting-capture.py \
  --config config.ini \
  --label use-pv-off-to-on \
  > /data/es-ESS-validation/use-pv-off-to-on.json
```

Pass criteria:

- both reports show firmware `42.5` and `vehicle_connected: false`;
- at least one candidate property changes in one direction and reverses in the
  other;
- the second run restores the original `Use PV surplus` state.

### 6. Capture the flexible-tariff switch in both directions

Perform this only with the vehicle disconnected and es-ESS stopped. If the
normal state is disabled, enable it only long enough for the first capture and
immediately disable it in the reverse capture:

```sh
python scripts/wattpilot-setting-capture.py \
  --config config.ini \
  --label flexible-tariff-off-to-on \
  > /data/es-ESS-validation/flexible-tariff-off-to-on.json

python scripts/wattpilot-setting-capture.py \
  --config config.ini \
  --label flexible-tariff-on-to-off \
  > /data/es-ESS-validation/flexible-tariff-on-to-off.json
```

Pass criteria:

- the candidate property reverses between the two reports;
- flexible-tariff charging is confirmed disabled after the second run;
- the vehicle remains disconnected throughout.

Do not reconnect the vehicle if the tariff state is uncertain.

### 7. Capture numeric and phase-policy settings

Repeat the two-direction pattern for each setting available in app `2.1.0`:

- start-up power level: current value to a second non-zero value and back;
- 3-phase power level or automatic phase-change setting: current value to a
  second safe value and back;
- control response: current value to one other documented value and back;
- zero feed-in: capture only if changing it is safe for the commissioned site;
  otherwise record it as intentionally not tested.

Use descriptive labels and separate files, for example:

```sh
python scripts/wattpilot-setting-capture.py \
  --config config.ini \
  --label startup-power-original-to-alternate \
  > /data/es-ESS-validation/startup-power-original-to-alternate.json
```

Never set the start-up power to zero for this investigation. Fronius documents
that zero can allow charging without PV surplus.

### 8. Inspect and package only the redacted reports

```sh
chmod 600 /data/es-ESS-validation/*.json
grep -R '"command_policy"' /data/es-ESS-validation
grep -R '"firmware": "42.5"' /data/es-ESS-validation
grep -R '"vehicle_connected": false' /data/es-ESS-validation
```

Review every JSON file before sharing it. The report intentionally fingerprints
arbitrary strings and known sensitive keys, but numeric setting values and raw
property names remain visible because they are required to establish the field
mapping.

Gate-1 pass criteria:

- each tested app setting has a reproducible forward and reverse property
  change;
- original commissioning settings are restored;
- no capture ran with a connected vehicle;
- flexible tariff is disabled;
- no report contains an unredacted password, API key, SSID, serial number, or
  arbitrary string;
- ambiguous or unrelated live-telemetry changes are retained as evidence but
  are not classified as settings without a reversible pair.

### Gate-1 evidence recorded on 2026-07-14

The production capture passed with Venus OS `v3.75`, firmware `42.5`, app
`2.1.0`, and the vehicle disconnected for all eight reports. Every report
recorded `all setValue requests blocked` and was protected with mode `0600`.

- `fup` reversibly mapped `Use PV surplus`: `true` when enabled and `false`
  when disabled.
- `ful` reversibly mapped flexible tariff: `true` when enabled and `false`
  when disabled.
- `fst` mapped the start-up-power slider (`10000` W to `9900` W and back), but
  this is not a command-ownership control.
- `frm` mapped control response (`1` Default, `2` Prefer power to grid).
- Disabling `Use PV surplus` also changed `lmo` from ECO (`4`) to Standard
  (`3`). Re-enabling it did not restore ECO automatically; the operator
  restored ECO deliberately.
- `cdci`/`dci` changed in only one control-response direction and remain
  unclassified. Zero feed-in was intentionally not changed. Phase settings
  were unavailable because the selected Opel Corsa-e vehicle profile owns that
  app surface.

These captures justify only the strict read-only `fup=false` and `ful=false`
authority guard. They do not authorize writes to undocumented setting fields.

### 9. Restart es-ESS without reconnecting the vehicle

```sh
svc -u /service/es-ESS
svstat /service/es-ESS
sleep 15
/data/es-ESS/scripts/es-ess-health-monitor.sh
```

Pass criteria:

- the service is up;
- Venus OS and Wattpilot firmware compatibility are healthy;
- main/local MQTT and Wattpilot telemetry recover;
- the vehicle remains disconnected;
- no unexpected `frc`, `amp`, or `psm` command is observed;
- the app still shows the recorded original commissioning settings.

Do not proceed to active charging. Supply the redacted JSON reports and setting
screenshots for review first.

## Gate 2 - Post-implementation active validation

Gate 2 must not be run until Gate 1 evidence has selected and tested one narrow
authority rule. The final implementation must provide an actionable authority
diagnostic and hardware-free tests before deployment.

### A. Vehicle-disconnected preflight

1. Complete syntax, focused, config, and full-suite checks in the development
   checkout, then deploy the reviewed files.
2. Keep the vehicle disconnected and restart es-ESS with `Use PV surplus`
   enabled and flexible tariff disabled. Confirm `/CommandAuthorityOk=0`,
   `/NativePvSurplusEnabled=1`, `/FlexibleTariffEnabled=0`, and the actionable
   instruction to disable native PV control. Confirm no start, positive-current,
   or phase command is issued.
3. In Solar.wattpilot, turn off `Use PV surplus`. The app may move from ECO to
   Standard. Confirm `/NativePvSurplusEnabled=0`,
   `/FlexibleTariffEnabled=0`, and the instruction to select Auto.
4. In the VRM web dashboard, click the EVCS tile/module and use its mode control
   to select Auto. The VRM mobile app did not expose this control during
   operator validation on 2026-07-15. Solar.wattpilot app `2.1.0` also disabled
   its Eco activation action and required at least one Eco option while both
   native settings were off; therefore it cannot make this transition. The VRM
   web EVCS control is the supported user transition. Do not use
   Standard/Manual as an Auto-control workaround. Confirm raw `lmo=4` remains
   stable, both native settings remain `0`,
   `/CommandAuthorityOk=1`, and the literal reports that es-ESS is the sole
   Auto/Eco command owner.
5. If either native setting changes, authority stays blocked, or any unexpected
   `frc=On`, positive `amp`, or `psm` command appears, stop before connecting
   the vehicle and retain the evidence.

Expected firmware `42.5` visual artifact: raw Eco mode with both native PV
surplus and flexible tariff disabled produces native status `114`. The Eco LED
flashes orange/yellow and, as confirmed during operator validation on
2026-07-15, may keep flashing while es-ESS is successfully charging. This state
can be selected through the VRM web EVCS control even though Solar.wattpilot
app `2.1.0` refuses to select Eco with both native options disabled. Accept this
indication only while `/CommandAuthorityOk=1`, both native-setting paths are
`0`, and telemetry is healthy. A red LED, a different status code, lost
authority, or unhealthy telemetry remains a stop-and-inspect condition.

### B. One-phase PV ownership

1. Use an attended daylight window with fresh grid telemetry,
   `AllowGridCharging=false`, and enough assigned PV for one-phase charging.
2. Connect the vehicle only after the authority diagnostic is healthy.
3. Correlate the es-ESS `frc=On` and `amp` requests with acknowledgements,
   Wattpilot requested current, measured current/power, assigned allowance,
   grid exchange, and stationary-battery power.
4. Hold at two distinct es-ESS current requests long enough to prove the
   Wattpilot does not rewrite or clamp them to its native PV value.
5. Confirm grid exchange remains at the normal no-grid target and the stationary
   battery does not supply an unbounded shortfall.

### C. Phase ownership

1. Wait for naturally sufficient assigned PV; do not lower safety thresholds to
   force a transition.
2. Confirm only the es-ESS `MinPhaseSwitchSeconds` candidate authorizes `psm`.
3. Correlate the command, acknowledgement, live phase power, runtime phase state,
   assigned allowance, grid exchange, and battery power.
4. Confirm no native phase change or current rewrite races the es-ESS command.
5. Wait for naturally lower PV and confirm current reduction, phase-down, or
   stop follows the existing no-grid and bounded-assist policy.

### D. Invalid-authority fail-closed behavior

1. With the vehicle disconnected, make exactly one native setting conflicting.
2. Reconnect only if the reviewed test plan for the chosen implementation says
   this is safe.
3. Confirm es-ESS refuses a new Auto/Eco start while authority is invalid.
4. During an already-running controlled session, test authority loss only if
   the reviewed implementation explicitly supports that fault simulation.
5. Confirm a safe stop remains permitted while current increase and phase-up are
   blocked.
6. Restore the validated setting and repeat the vehicle-disconnected preflight.

### E. Manual ownership regression

1. Stop Auto/Eco and disconnect/reconnect the vehicle as required by the normal
   operating procedure.
2. Select Standard/Manual in Solar.wattpilot.
3. Confirm the one-time Auto/Eco constraint release occurs at most once.
4. Change Manual charging current in the app and confirm es-ESS reports it but
   does not send subsequent `frc`, `amp`, or `psm` commands.
5. Return to the validated commissioning state before ending the window.

Gate-2 completion requires recorded evidence for every executed step, focused
and full automated tests passing, no intentional grid charging, unchanged
Manual ownership, bounded continuation-only battery assist, and a completed
backlog entry. An inconclusive natural-PV window is recorded as inconclusive;
unsafe conditions are never forced merely to close the item.

### Gate-2 evidence recorded on 2026-07-15

The production run used Venus OS `v3.75`, Wattpilot firmware `42.5`,
Solar.wattpilot app `2.1.0`, `AllowGridCharging=false`, and the reviewed files
merged through PR #70. The run produced these results:

- With the vehicle disconnected and native `Use PV surplus` enabled,
  `/CommandAuthorityOk=0`, `/NativePvSurplusEnabled=1`, and
  `/FlexibleTariffEnabled=0`. The diagnostic named the conflicting setting and
  no positive-current or phase command was issued.
- Turning native PV off moved Solar.wattpilot from Eco to Standard. Both native
  observations then reported `0`; selecting Auto from the VRM web dashboard
  EVCS tile produced raw `lmo=4`, `/ModeLiteral=Auto`, and
  `/CommandAuthorityOk=1` with the sole-owner diagnostic.
- During supervised one-phase charging, es-ESS requests progressed from 13 A
  through 16 A and the measured charger power followed them without a native
  current rewrite or clamp to the previous native 6 A behavior.
- Assigned allowance remained above the configured phase-up threshold for the
  full `600`-second candidate. es-ESS issued the phase-up at 07:15:35 UTC and
  live telemetry confirmed three-phase charging. A later single-cycle atomic
  `0 W` assignment produced a telemetry-confirmed phase-down and exposed that
  the three-phase deficit path bypassed `AllowanceDropGraceSeconds`; the
  follow-up controller fix now holds the existing command through that grace
  while keeping `/PvAllowance=0`. No native phase race was observed.
- Grid exchange stayed near the configured no-grid target and
  `/GridImportGuardActive` remained `0`. Small observed battery-assist
  shortfalls were bounded continuation behavior; the stationary battery
  remained charging rather than supplying an unbounded EV shortfall.
- Selecting Standard/Manual produced the approved one-time release and no
  repeated es-ESS control commands. The previously completed Venus OS `v3.75`
  Manual-current validation remains the evidence for user current ownership;
  it was not needlessly repeated during this disconnected boundary check.
- Solar.wattpilot app `2.1.0` refused to activate Eco while both native Eco
  options were disabled. The VRM web EVCS mode control successfully restored
  Auto. Firmware status `114` and the orange/yellow Eco LED flash persisted
  even during successful es-ESS charging, matching the documented native
  indication for Eco with neither native Eco option selected. Do not change a
  native authority setting merely to suppress this expected indicator.
- The final health snapshot at 07:35:33 UTC showed the vehicle disconnected,
  Auto selected, zero EV power/current, stopped control state, unknown phase,
  healthy telemetry, validated runtime compatibility, both native observations
  at `0`, `/CommandAuthorityOk=1`, and no recent critical or error event.

An authority-loss fault was not simulated during an active charge. Doing so was
not required to prove the selected boundary and would have introduced avoidable
native-controller behavior. The disconnected conflicting-authority preflight,
combined with the hardware-free command-boundary tests, is the fail-closed
evidence for invalid authority.
