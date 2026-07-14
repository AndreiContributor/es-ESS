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

On the GX device:

```sh
cd /data/es-ESS
python -m py_compile scripts/wattpilot-setting-capture.py
python -m unittest tests.test_wattpilot_setting_capture
```

Pass criteria:

- syntax compilation succeeds;
- all capture-tool unit tests pass;
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
install -d -m 700 /data/es-ESS-validation
umask 077
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

1. Deploy the reviewed implementation and complete its syntax, focused, config,
   and full-suite checks.
2. Keep the vehicle disconnected and restart es-ESS.
3. Confirm Venus OS `v3.75`, firmware `42.5`, app `2.1.0`, fresh Wattpilot
   telemetry, and the expected authority diagnostic.
4. Deliberately select one invalid/conflicting native setting with the vehicle
   disconnected.
5. Confirm Auto/Eco reports the expected fail-closed diagnostic and does not
   issue start, current-increase, or phase-up commands.
6. Restore the validated setting and confirm authority becomes healthy without
   weakening firmware or ECO-mode checks.

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
