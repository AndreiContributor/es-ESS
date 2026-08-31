# Cerbo GX Firmware Upgrade And Rollback

This runbook covers a controlled Venus OS upgrade on a Cerbo GX that runs
es-ESS, with special notes for upgrading from `v3.75` to `v3.79`. It also
covers both firmware rollback methods: booting the stored backup firmware and
installing a specific older firmware from USB or microSD.

The es-ESS checkout accepts only the clean Venus OS releases explicitly listed
in `RuntimeCompatibility.py`. It accepts clean `v3.75` and clean `v3.79` and
rejects beta/build-qualified releases such as `v3.79~1` as well as unvalidated
future releases. v3.79 is the preferred target; v3.75 remains accepted so the
same checkout can operate after a stored-firmware rollback.

## Safety Notes

- Schedule the work for a maintenance window with someone able to access the
  GX locally if networking does not recover.
- Do not update while an EV is actively charging. Put Wattpilot in Manual mode
  or disconnect the vehicle before the GX reboot, and supervise the first
  Auto/Eco session after the update.
- Keep es-ESS stopped across the first v3.79 boot. Complete the read-only
  dependency, D-Bus-path, device-assignment, and telemetry checks before
  starting it with the vehicle disconnected or Wattpilot confirmed in Manual.
- Disable automatic firmware updates. Select and install official releases
  deliberately.
- Do not use a factory reset or recovery-image reinstall for an ordinary
  rollback. Those are recovery operations and can erase the `/data` partition.
- `/data/es-ESS`, `config.ini`, and `/data/rc.local` normally survive a Venus OS
  update. Packages installed into the operating-system root filesystem may not.
- A Venus OS firmware update resets the root password because the password is
  stored on the firmware root filesystem that the update replaces. After every
  update, use the Cerbo console to set a new root password before relying on
  password-based SSH. Public SSH keys installed under `/data` normally persist,
  but key login and **SSH on LAN** must still be tested after the reboot.

## Before The Upgrade

1. Open Remote Console and go to **Settings → General → Firmware**. Record the
   currently running firmware.
2. Open **Stored backup firmware** and record the version shown there. Do not
   assume the stored slot is compatible with this es-ESS checkout.
3. Confirm **Settings → General → Modification checks → Modifications enabled**.
   If modifications are disabled, Venus OS disables the `/data/rc.local` hook
   that restores the es-ESS service link.
4. Back up the es-ESS configuration outside the application directory with
   owner-only permissions:

   ```sh
   mkdir -p /data/es-ESS-backups
   chmod 700 /data/es-ESS-backups
   backup_file="/data/es-ESS-backups/config.ini.pre-venus-update-$(date +%Y%m%d-%H%M%S)"
   cp -p /data/es-ESS/config.ini "$backup_file"
   chmod 600 "$backup_file"
   test -s "$backup_file" && echo "Config backup OK"
   ```

   Expected result: `Config backup OK`. Stop if the copy is missing or empty.

5. Record the current version and check persistent files and dependencies:

   ```sh
   cat /opt/victronenergy/version
   test -d /data/es-ESS && echo "Application directory OK"
   test -L /service/es-ESS && echo "Service link OK"
   grep -F '/data/es-ESS/install.sh' /data/rc.local
   python3 -c "import paho.mqtt.client, websocket; print('Python dependencies OK')"
   ```

   Expected results are the supported current Venus OS release, both `OK`
   markers, the exact `/data/es-ESS/install.sh` line, and `Python dependencies
   OK`. Resolve any missing persistent path before installing firmware.

6. Save screenshots or notes for the ESS mode, grid setpoint, selected battery
   monitor, grid-meter assignment, PV-inverter AC position, MQTT settings, and
   enabled es-ESS services.
7. Confirm Remote Console and SSH both work, then disconnect the EV or leave
   Wattpilot in Manual mode for the update.
8. Stop es-ESS and create the persistent runit `down` marker so the service
   cannot start automatically on the first v3.79 boot:

   ```sh
   svc -d /service/es-ESS
   touch /data/es-ESS/service/down
   sleep 15
   svstat /service/es-ESS
   pgrep -af '^python[[:space:]]+/data/es-ESS/es-ESS.py$' || true
   ```

   Expected result: `svstat` reports `down` and `pgrep` prints nothing. `want
   down` is not yet complete; wait and check again. Do not install firmware
   while the Python process still exists.

9. Verify the copied v3.79 compatibility payload before installing firmware.
   Generate the hashes from the files that will actually run; they can change
   whenever the reviewed payload is updated:

   ```sh
   cd /data/es-ESS
   sha256sum RuntimeCompatibility.py VelibDependency.py velib_python-master/PINNED.json scripts/es-ess-health-monitor.sh
   python3 -m py_compile RuntimeCompatibility.py VelibDependency.py
   python3 -c "from RuntimeCompatibility import require_validated_venus_os; print('Compatibility precheck:', require_validated_venus_os())"
   ```

   Save or copy the four hash lines and compare them manually or with AI
   assistance against the trusted deployment source used for this update. Do
   not rely on hashes embedded in this runbook because later reviewed code
   changes would make them stale. Syntax compilation prints nothing on success.
   Before the firmware update, the final command must print `Compatibility
   precheck: v3.75`. Stop on an unexpected file, syntax error, compatibility
   error, or mismatch against the trusted deployment source.

## Upgrade To Venus OS v3.79 Online

1. In Remote Console, open **Settings → General → Firmware → Online updates**.
2. Set the update feed to **Official release**, not Beta.
3. Select **Check for updates**.
4. Confirm the offered version is the clean `v3.79` release. For Cerbo GX, the
   official image published by Victron is build `20260826152305`.
5. Select the offered update and confirm installation. Do not remove power
   while the inactive root filesystem is being written.
6. Wait for the Cerbo GX to reboot and reconnect to Remote Console and VRM.
7. Confirm the running and stored versions:

   - **Currently running firmware** should show `v3.79`.
   - **Stored backup firmware** should show `v3.75` before proceeding with live
     validation. If it does not, ensure the official v3.75 image is available
     for manual rollback.

## Upgrade Offline With USB Or microSD

Use this method when the GX has no internet access or when a specific official
image must be installed.

1. Download the Cerbo GX `venus-swu-einstein-...-v3.79.swu` file from Victron's
   official `einstein` release directory.
2. Use a FAT32-formatted USB stick or microSD card and place the `.swu` file in
   its root directory, not inside a folder.
3. Insert the storage device into the Cerbo GX.
4. Open **Settings → General → Firmware → Install from SD/USB**.
5. Select **Check for updates on SD/USB**, verify that `v3.79` was detected,
   then select it to install.
6. Wait for the reboot, remove the storage device, and confirm the running and
   stored versions.

## Checks Immediately After The Upgrade

This section is a self-contained operator checklist. Complete it in order; do
not remove the persistent stop marker until the relevant step explicitly says
to do so.

1. Restore SSH access from the Cerbo console. This is mandatory for
   password-based SSH because a firmware update resets the root password:

   - In the New UI, open **Settings -> Access & Security**. In the Classic UI,
     use **Settings -> General**.
   - Set or reveal the **Superuser** access level using the documented local
     console procedure.
   - Select **Set root password** and create a new unique password of at least
     six characters. Do not reuse or document the old password.
   - Confirm **SSH on LAN** is enabled.
   - From a machine on the same LAN, test `ssh root@venus.local`, then run
     `exit`. Use the GX device's private LAN address only when local name
     resolution is unavailable; never copy that address into public project
     files.

   Public keys in `/data/home/root/.ssh/authorized_keys` normally survive the
   update and avoid the password-reset problem, but the operator must still
   prove that the intended key or new password works. Do not paste or store a
   password, private address, or private key in project documentation.

2. Confirm the runtime version:

   ```sh
   cat /opt/victronenergy/version
   ```

   Expected output begins with `v3.79` and includes Cerbo GX build
   `20260826152305`. Stop if the release is qualified, different, or missing.

3. In Remote Console, open **Settings -> General -> Firmware -> Stored backup
   firmware**. It should show `v3.75`. Do not continue without an available
   supported rollback image.

4. Confirm es-ESS persistence and its intentional stopped state. Restore the
   service link if necessary, but keep the persistent `down` marker in place:

   ```sh
   test -d /data/es-ESS && echo "Application directory OK"
   grep -F '/data/es-ESS/install.sh' /data/rc.local
   /data/es-ESS/install.sh
   test -L /service/es-ESS && echo "Service link OK"
   test -e /data/es-ESS/service/down && echo "Stop marker preserved"
   svstat /service/es-ESS
   ```

   Expected results: all three `OK` markers, the exact install-hook line, and a
   service state of `down`. Stop if the service is up or the marker is missing.

5. Recheck the copied compatibility and bundled dependency integrity on v3.79:

   ```sh
   cd /data/es-ESS
   sha256sum RuntimeCompatibility.py VelibDependency.py velib_python-master/PINNED.json scripts/es-ess-health-monitor.sh
   python3 -m py_compile RuntimeCompatibility.py VelibDependency.py
   python3 -c "from RuntimeCompatibility import require_validated_venus_os; print('Compatibility precheck:', require_validated_venus_os())"
   python3 -c "from VelibDependency import verify_bundled_velib; print('Bundled velib integrity OK:', ', '.join(verify_bundled_velib()['validated_venus_os_versions']))"
   ```

   The four hashes must match step 9 under **Before The Upgrade**. Compilation
   prints nothing on success. The final two lines must report
   `Compatibility precheck: v3.79` and bundled integrity for `v3.75, v3.79`.
   Stop on any mismatch or exception.

6. Complete the Python dependency-restoration checkpoint before restarting
   es-ESS. A clean Venus OS v3.79 update can remove both `python3-pip` and
   `websocket-client`; if FroniusWattpilot is enabled, a missing `websocket`
   module causes a `ModuleNotFoundError` during service startup. Keep the
   persistent `service/down` marker in place until both imports succeed.

   ```sh
   python3 -c "import paho.mqtt.client, websocket; print('Python dependencies OK')"
   ```

   If the import check fails because `websocket` is missing, first check whether
   `pip` survived the firmware update, then restore the missing packages while
   es-ESS remains stopped:

   ```sh
   svc -d /service/es-ESS
   python3 -m pip --version || true
   opkg update
   opkg install python3-pip
   python3 -m pip install websocket-client
   python3 -c "import websocket; print('websocket-client OK')"
   python3 -c "import paho.mqtt.client, websocket; print('Python dependencies OK')"
   svstat /service/es-ESS
   ```

   Do not continue to service startup unless the final combined import prints
   `Python dependencies OK`.

7. With the vehicle disconnected or Wattpilot confirmed in Manual, remove only
   the intentional validation marker, start es-ESS, and inspect the log.
   `restart.sh` only signals an existing process; it cannot bring a service
   back up after `svc -d`, which is why this procedure uses `svc -u` first:

   ```sh
   rm /data/es-ESS/service/down
   svc -u /service/es-ESS
   sleep 15
   svstat /service/es-ESS
   pgrep -af '^python[[:space:]]+/data/es-ESS/es-ESS.py$'
   ```

   Expected result: `svstat` reports `up` and `pgrep` reports exactly one es-ESS
   process. If the service is down, repeatedly respawns, or has more than one
   matching process, stop it again with `svc -d /service/es-ESS`, restore the
   marker with `touch /data/es-ESS/service/down`, and investigate before retry.

8. Search the startup log for required success and failure evidence:

   ```sh
   sleep 30
   tail -n 800 /data/log/es-ESS/current.log | grep -E 'Validated Venus OS compatibility baseline confirmed: v3.79|Wattpilot firmware compatibility confirmed: 42.5'
   tail -n 800 /data/log/es-ESS/current.log | grep -Ei 'CRITICAL|Traceback|ModuleNotFoundError|Unsupported Venus OS|CompatibilityError|UNCOUGHT|Exception' || true
   ```

   The first command must show the v3.79 compatibility line. When Wattpilot is
   enabled and authenticated, it must also show firmware `42.5`. The second
   command should print nothing from the new startup. Any new critical error,
   traceback, missing dependency, unsupported version, compatibility error, or
   unhandled exception is a stop condition: stop es-ESS and restore the
   persistent marker before troubleshooting.

9. Run the read-only health monitor with v3.79 required explicitly:

   ```sh
   cd /data/es-ESS
   chmod +x scripts/es-ess-health-monitor.sh
   EXPECTED_VENUS_OS=v3.79 LOG_LINES=800 EVENT_LINES=120 scripts/es-ess-health-monitor.sh
   ```

   Validate all of the following without changing D-Bus, MQTT, or Wattpilot:

   - service state is up with one stable process;
   - Venus OS compatibility reports `OK` for v3.79;
   - bundled velib integrity is healthy and selected from `/data/es-ESS`;
   - enabled D-Bus services are present once;
   - main and local MQTT connections recovered;
   - Wattpilot telemetry is healthy and firmware `42.5` is confirmed;
   - all three grid/site-current phases are fresh;
   - no recent critical/error/compatibility event is reported.

   Any `WARN`, missing required service, stale mandatory telemetry, or recent
   critical event requires inspection before unattended use.

10. Confirm device assignments without changing them from memory or inference:

    - **Settings -> System Setup -> Batteries -> Battery monitor** must name the
      actual managed battery/BMS explicitly, not `Automatic` and not an es-ESS
      virtual service.
    - **Settings -> System Setup -> ESS -> Grid metering** must still match the
      physical installation: `External meter` only when GX uses a supported
      external grid meter, otherwise `Inverter/Charger`.
    - Under **Settings -> Integrations -> PV Inverters**, verify each PV
      inverter's configured AC position, phase assignment, and visibility.
    - Under **Settings -> System Setup -> AC System**, verify the AC-input types
      and position of AC loads.

    Stop and obtain installation records or installer confirmation if any value
    is unexpected. Do not guess topology from live power values.

11. Complete the supervised Manual-mode boundary test described under
    **v3.79 Validation Status** below.
12. Complete the disconnected Auto command-authority test and the connected
    zero-surplus no-start test described below.
13. Complete the remaining daylight one-phase, no-grid, phase-up, and
    phase-down tests before unattended v3.79 production use.

## v3.79 Validation Status

The following generic gates have been completed for official Cerbo GX v3.79
build `20260826152305`. Exact timestamps, identifiers, screenshots, topology,
and correlated telemetry remain private diagnostic evidence and must not be
copied into this repository:

- firmware boot, stored supported rollback, persistent application directory,
  service link, `/data/rc.local` recovery hook, and intentional first-boot stop;
- post-update root-password restoration and successful SSH recovery;
- exact compatibility-payload hashes, Python syntax, v3.79 allowlist check,
  bundled velib integrity, and restored Python dependencies;
- stable single-process startup, v3.79 and Wattpilot `42.5` confirmation, fresh
  selected site-current telemetry, and no new critical startup event;
- explicit physical battery-monitor selection and unchanged grid/PV/AC
  assignments;
- a supervised minimum-current Manual session in which es-ESS remained
  observation-only through connect, charge, user stop, and disconnect;
- Auto command authority with both native competing controls disabled; and
- a connected Auto test with zero assigned PV allowance in which es-ESS issued
  a safe Force Off, never attempted a start, and recorded zero charging energy.

These completed checks prove upgrade, Manual-boundary, command-authority, and
zero-surplus behavior. They do **not** complete v3.79 production validation.
The following gates remain:

- daylight one-phase Auto/Eco start from fresh assigned PV allowance;
- current tracking and no sustained grid import with
  `AllowGridCharging=false`;
- supervised one-to-three phase switching after the configured PV stability
  interval; and
- supervised three-to-one reduction or stop after a natural PV decline,
  followed by a final clean health snapshot.

The earlier v3.75 migration completed the equivalent daylight checks. Do not
mark v3.79 complete merely because the same checkout passed them on v3.75.

## Detailed Supervised v3.79 Wattpilot Validation

Perform these steps at the equipment with the ability to stop charging and
disconnect the vehicle. Use natural PV conditions; do not switch large loads,
interrupt telemetry, create grid import, or manipulate protective devices just
to force a test condition.

### 1. Safe pause when daylight conditions are unavailable

Disconnect the EV, select Manual in the Wattpilot app, and then stop es-ESS if
the incomplete v3.79 validation would otherwise be left unattended:

```sh
svc -d /service/es-ESS
touch /data/es-ESS/service/down
sleep 15
svstat /service/es-ESS
pgrep -af '^python[[:space:]]+/data/es-ESS/es-ESS.py$' || true
```

Pass only when `svstat` reports `down` and `pgrep` prints nothing. A `want down`
state is not complete.

### 2. Resume in a safe disconnected state

With the vehicle disconnected and Wattpilot confirmed in Manual, restart the
validated checkout and require one stable process:

```sh
rm /data/es-ESS/service/down
svc -u /service/es-ESS
sleep 15
svstat /service/es-ESS
pgrep -af '^python[[:space:]]+/data/es-ESS/es-ESS.py$'

cd /data/es-ESS
EXPECTED_VENUS_OS=v3.79 MAX_SAMPLES=1 LOG_LINES=300 EVENT_LINES=120 scripts/es-ess-health-monitor.sh
```

Before selecting Auto, require all of these:

- `CompatibilityOk: 1`, actual Venus OS `v3.79`, and actual Wattpilot firmware
  `42.5`;
- service state `up` with exactly one process;
- `TelemetryHealthy: 1`, selected site-current source connected and healthy,
  `SiteCurrentTelemetryHealthy: 1`, and all phase ages inside
  `SiteCurrentFreshSeconds`;
- `NativePvSurplusEnabled: 0` and `FlexibleTariffEnabled: 0`; and
- no recent critical, traceback, missing-dependency, or compatibility event.

### 3. Select Auto and validate command authority while disconnected

Select Auto from the GX/VRM es-ESS EV-charger control, wait at least 30 seconds,
and rerun the one-sample health command above. Require:

- `/ModeLiteral: Auto`;
- `/CommandAuthorityOk: 1` and the literal stating that es-ESS is the sole
  Auto/Eco command owner;
- both native competing controls still `0`;
- fresh site-current telemetry and `SiteCurrentGuardBlocked: 0`; and
- `/Ac/Power: 0` while the vehicle is disconnected.

Do not connect the vehicle if command authority, compatibility, selected-source
identity, or any mandatory telemetry is unavailable.

### 4. Start a bounded private transition capture

The full health monitor performs many sequential D-Bus reads and is intended
for checkpoints, not second-by-second transition capture. Use the raw service
log for the live interval and the health monitor before and after it. Venus OS
may not provide the `timeout` utility, so this portable capture tracks and
terminates the exact background `tail` process:

```sh
mkdir -p /data/es-ESS-validation
chmod 700 /data/es-ESS-validation
capture_file="/data/es-ESS-validation/v379-wattpilot-$(date +%Y%m%d-%H%M%S).log"
capture_seconds=900
capture_pid=""

cleanup_capture() {
    if [ -n "$capture_pid" ]; then
        kill "$capture_pid" 2>/dev/null || true
        wait "$capture_pid" 2>/dev/null || true
    fi
}

trap cleanup_capture INT TERM EXIT
tail -n 0 -f /data/log/es-ESS/current.log > "$capture_file" &
capture_pid=$!
echo "Private capture running as PID $capture_pid"
echo "Private capture file: $capture_file"
sleep "$capture_seconds"
cleanup_capture
capture_pid=""
trap - INT TERM EXIT
echo "Private capture complete: $capture_file"
test -s "$capture_file" && echo "Capture contains data"
```

The example records 15 minutes, long enough to cover the configured 600-second
phase-stability interval plus setup time. Change `capture_seconds` before
starting when a shorter zero-surplus or one-phase test is sufficient. Store the
file privately; do not commit it or paste its identifiers, timestamps, or raw
telemetry into public documentation.

### 5. Validate zero-surplus no-start behavior

This gate is complete for the current v3.79 build, but repeat it after any
relevant controller, configuration, meter, or Wattpilot firmware change.

1. Start the bounded capture with Auto selected and assigned allowance below
   the effective one-phase minimum.
2. Connect the EV and observe it locally for at least 60 seconds.
3. Require repeated `0W` consumer assignments, `Waiting for Sun`, zero measured
   charging power/energy, and no accepted start attempt. A single safe Force Off
   on connection is expected.
4. Battery assist must remain inactive; it may bridge only an already-running
   session and must never create a start.

The consumer's multi-kilowatt `request` is demand, not permission. Only the
fresh assigned `/PvAllowance` authorizes a start or increase.

### 6. Validate a daylight one-phase Auto/Eco start

Choose a naturally stable window where fresh assigned allowance is above the
effective one-phase minimum (normally about 1.3-1.5 kW at six amperes) but below
`ThreePhasePvSurplusStartW`. Start the private capture, select Auto, and connect
the EV. Allow for the configured site-current recovery and on/off guards.

Require all of the following:

- assigned `/PvAllowance`, not raw overhead or requested power, remains fresh
  and sufficient for the commanded current;
- the first start attempt is accepted only after fresh grid, allowance, command
  authority, and three-phase site-current checks pass; battery activity must
  additionally be fresh before battery assist or the battery-reservation bypass
  can be used;
- `/PhaseModeLiteral` confirms one phase and the configured physical one-phase
  mapping is used;
- commanded current stays between `MinCurrentPerPhase`,
  `MaxCurrentPerPhase`, the Wattpilot effective limit, and calculated physical
  phase headroom;
- all three site-current ages remain fresh, no physical phase exceeds
  `SiteMaxCurrent`, and `SiteCurrentGuardBlocked` remains `0`; and
- the GX grid view and logs show no sustained import attributable to the EV.

Stop the test if Auto starts below minimum assigned allowance, site telemetry
becomes stale, command authority drops, a physical phase lacks headroom, a
breaker operates, or sustained grid import occurs.

### 7. Validate reduction and no-grid protection

Observe a natural variation while one-phase charging is already active. Do not
force an outage or artificial overload. The controller must reduce current as
fresh assigned allowance falls. A short allowance dip may use only the
configured grace, and optional battery assist may bridge only the remaining
minimum-current deficit of this already-running charge.

Require that battery assist never raises current, starts a session, creates a
phase-up candidate, exceeds its SOC/duration/per-phase-shortfall bounds, or
overrides stale telemetry or site-current protection. With
`AllowGridCharging=false`, sustained import must cause a safe reduction or stop
according to the configured guard. Record any naturally occurring guard event
privately; do not deliberately create production grid import.

### 8. Validate one-to-three phase switching

Continue only when fresh assigned allowance remains at or above
`ThreePhasePvSurplusStartW` and all three physical phases have sufficient
headroom. The configured `MinPhaseSwitchSeconds` must remain satisfied
continuously; a deep allowance deficit resets the candidate.

Require:

- no phase-up command before the full stability interval;
- the command sequence remains inside both the old and requested phase-mode
  headroom;
- live Wattpilot telemetry confirms three phases before the public state is
  treated as stable;
- equal commanded current respects the smallest three-phase site headroom; and
- no stale telemetry, sustained grid import, breaker operation, or unexpected
  battery-assist authorization occurs.

### 9. Validate three-to-one reduction or stop

During a natural decline below `ThreePhasePvSurplusStopW`, verify current first
reduces toward the PV-supported value. After any permitted grace or bounded
battery-assist window, the controller must confirm a safe one-phase transition
when one-phase continuation PV remains available, or stop when it does not.
The shared phase stability/cooldown guard applies unless an earlier safety
reduction is required. Do not manufacture the decline by switching large loads.

### 10. Finish and record the result privately

Stop charging using the vehicle or Wattpilot user control, wait for measured
power to reach zero, and disconnect the EV. Run a final read-only snapshot:

```sh
cd /data/es-ESS
final_health="/data/es-ESS-validation/v379-final-health-$(date +%Y%m%d-%H%M%S).log"
EXPECTED_VENUS_OS=v3.79 MAX_SAMPLES=1 LOG_LINES=800 EVENT_LINES=160 scripts/es-ess-health-monitor.sh | tee "$final_health"
echo "Private final health file: $final_health"
```

Pass only when the service is stable, compatibility and command authority are
validated, selected-source telemetry is fresh, charging is stopped, and there
is no new critical/error/compatibility event. Keep the evidence private. After
all remaining daylight gates pass, update the public project status using only
generic results and public release/build identifiers.

If any gate fails, stop the vehicle normally, wait for zero power, disconnect
it, and then pin es-ESS down before investigation:

```sh
svc -d /service/es-ESS
touch /data/es-ESS/service/down
sleep 15
svstat /service/es-ESS
pgrep -af '^python[[:space:]]+/data/es-ESS/es-ESS.py$' || true
```

## Roll Back Using Stored Backup Firmware

This is the preferred and quickest firmware rollback when the intended previous
firmware is still present in the other root filesystem. This es-ESS checkout
supports clean `v3.75` and clean `v3.79`; the same checkout can therefore start
after the expected v3.79-to-v3.75 rollback. For any other firmware, restore an
es-ESS checkout whose `RuntimeCompatibility.py` explicitly supports it before
starting services.

1. Open **Settings → General → Firmware → Stored backup firmware**.
2. Verify that the stored version is the firmware you intend to boot. Do not
   proceed based only on an assumption about which version is stored.
3. Select **Press to boot** and confirm.
4. Wait for the Cerbo GX to restart. Venus OS swaps the active and stored
   firmware, so v3.75 becomes current and v3.79 becomes the stored option.
5. Rerun `/data/es-ESS/install.sh`, check Python dependencies, inspect the
   es-ESS log, and repeat D-Bus, MQTT, Manual-mode, and Auto/Eco checks.

## Roll Back Manually With USB Or microSD

Use this method if the stored backup is unavailable, cannot boot, or is not the
firmware you intend to run. This es-ESS checkout supports clean `v3.75` and
clean `v3.79`. After installing any other firmware, restore an es-ESS checkout
compatible with that firmware before starting es-ESS.

1. Download the intended official Cerbo GX `.swu` file from Victron's
   `einstein` release directory.
2. Copy the `.swu` file to the root of a FAT32 USB stick or microSD card.
3. Insert it into the Cerbo GX.
4. Open **Settings → General → Firmware → Install from SD/USB**.
5. Select **Check for updates on SD/USB**, verify that the detected file is the
   clean Cerbo GX release you intend to install, and start the installation.
6. Wait for the reboot, remove the storage device, and verify the version with:

   ```sh
   cat /opt/victronenergy/version
   ```

7. Rerun `/data/es-ESS/install.sh`, check dependencies, inspect the es-ESS log,
   and repeat the D-Bus, MQTT, Manual-mode, and Auto/Eco checks.

## If The GX Does Not Return Normally

- Try local Remote Console or a directly connected GX Touch before assuming
  the device failed to boot.
- Check Ethernet addressing and Wi-Fi status; v3.75 specifically restores the
  Wi-Fi connection-status behavior changed in v3.74.
- Use stored backup firmware if Remote Console is available.
- Use the official `.swu` rollback method next.
- Use Victron's full recovery-image procedure only as a last resort. It can
  wipe settings and `/data`, so restore es-ESS and `config.ini` from the backup
  afterward.

## Official References

- [Venus OS v3.75 release announcement](https://professional.victronenergy.com/news/detail/370/)
- [Venus OS v3.79 release announcement](https://professional.victronenergy.com/news/detail/377/)
- [Cerbo GX firmware update and rollback manual](https://www.victronenergy.com/media/pg/Cerbo_GX/en/firmware-updates.html)
- [Official Cerbo GX `einstein` firmware archive](https://updates.victronenergy.com/feeds/venus/release/images/einstein/)
- [Victron root access, firmware password reset, and persistent SSH-key guidance](https://www.victronenergy.com/live/ccgx%3Aroot_access)
- [Local es-ESS production health monitor](es-ess-health-monitor.md)
