# Cerbo GX Firmware Upgrade And Rollback

This runbook covers a controlled Venus OS upgrade on a Cerbo GX that runs
es-ESS, with special notes for upgrading from `v3.73` to `v3.75`. It also
covers both supported rollback methods: booting the stored backup firmware and
installing a specific older firmware from USB or microSD.

The es-ESS checkout accepts only the clean Venus OS releases explicitly listed
in `RuntimeCompatibility.py`. It currently accepts `v3.73` and `v3.75` and
rejects beta/build-qualified releases such as `v3.75~1`.

## Safety Notes

- Schedule the work for a maintenance window with someone able to access the
  GX locally if networking does not recover.
- Do not update while an EV is actively charging. Put Wattpilot in Manual mode
  or disconnect the vehicle before the GX reboot, and supervise the first
  Auto/Eco session after the update.
- Disable automatic firmware updates. Select and install official releases
  deliberately.
- Do not use a factory reset or recovery-image reinstall for an ordinary
  rollback. Those are recovery operations and can erase the `/data` partition.
- `/data/es-ESS`, `config.ini`, and `/data/rc.local` normally survive a Venus OS
  update. Packages installed into the operating-system root filesystem may not.
- A Venus OS firmware update can reset the root password because the password
  is stored on the firmware root filesystem. After the reboot, check
  **Settings -> Access & Security** on the Cerbo console, enable SSH on LAN if
  it is off, and set a new root password if password login no longer works.

## Before The Upgrade

1. Open Remote Console and go to **Settings → General → Firmware**. Record the
   currently running firmware.
2. Open **Stored backup firmware** and record the version shown there. Before
   upgrading, it might not yet be `v3.73`; after a successful upgrade from
   `v3.73`, it should normally show `v3.73` as the stored boot option.
3. Confirm **Settings → General → Modification checks → Modifications enabled**.
   If modifications are disabled, Venus OS disables the `/data/rc.local` hook
   that restores the es-ESS service link.
4. Back up the es-ESS configuration over SSH:

   ```sh
   cp /data/es-ESS/config.ini /data/es-ESS/config.ini.before-venus-update
   ```

5. Record the current version and check persistent files:

   ```sh
   cat /opt/victronenergy/version
   ls -l /data/es-ESS /data/rc.local /service/es-ESS
   grep -F '/data/es-ESS/install.sh' /data/rc.local
   python -c "import paho.mqtt.client, websocket; print('Python dependencies OK')"
   ```

6. Save screenshots or notes for the ESS mode, grid setpoint, selected battery
   monitor, grid-meter assignment, PV-inverter AC position, MQTT settings, and
   enabled es-ESS services.
7. Confirm Remote Console and SSH both work, then disconnect the EV or leave
   Wattpilot in Manual mode for the update.

## Upgrade From Venus OS v3.73 To v3.75 Online

1. In Remote Console, open **Settings → General → Firmware → Online updates**.
2. Set the update feed to **Official release**, not Beta.
3. Select **Check for updates**.
4. Confirm the offered version is the clean `v3.75` release. For Cerbo GX, the
   final official image published by Victron is build `20260624163305`.
5. Select the offered update and confirm installation. Do not remove power
   while the inactive root filesystem is being written.
6. Wait for the Cerbo GX to reboot and reconnect to Remote Console and VRM.
7. Confirm the running and stored versions:

   - **Currently running firmware** should show `v3.75`.
   - **Stored backup firmware** should normally show `v3.73`.

## Upgrade Offline With USB Or microSD

Use this method when the GX has no internet access or when a specific official
image must be installed.

1. Download the Cerbo GX `venus-swu-einstein-...-v3.75.swu` file from Victron's
   official `einstein` release directory.
2. Use a FAT32-formatted USB stick or microSD card and place the `.swu` file in
   its root directory, not inside a folder.
3. Insert the storage device into the Cerbo GX.
4. Open **Settings → General → Firmware → Install from SD/USB**.
5. Select **Check for updates on SD/USB**, verify that `v3.75` was detected,
   then select it to install.
6. Wait for the reboot, remove the storage device, and confirm the running and
   stored versions.

## Checks Immediately After The Upgrade

1. Restore or confirm SSH access from the Cerbo console:

   - Open **Settings -> Access & Security**.
   - If required, set the access level to **User and installer** using the
     installer password.
   - Enable **Superuser** access.
   - Check that **SSH on LAN** is enabled.
   - Set a new root password if the previous password no longer works.

   Do not paste or store the root password in the project documentation.

2. Confirm the runtime version:

   ```sh
   cat /opt/victronenergy/version
   ```

3. Confirm es-ESS persistence and restore its service link if necessary:

   ```sh
   ls -l /data/es-ESS /data/rc.local /service/es-ESS
   grep -F '/data/es-ESS/install.sh' /data/rc.local
   /data/es-ESS/install.sh
   ```

4. Check Python dependencies before restarting es-ESS. Venus OS firmware
   updates can remove `python3-pip` and `websocket-client`; if
   FroniusWattpilot is enabled, a missing `websocket` module causes a
   `ModuleNotFoundError` during service startup.

   ```sh
   python -c "import paho.mqtt.client, websocket; print('Python dependencies OK')"
   ```

   If the import check fails, keep es-ESS stopped and reinstall the missing
   packages:

   ```sh
   svc -d /service/es-ESS
   opkg update
   opkg install python3-pip
   python -m pip install websocket-client
   python -c "import websocket; print('websocket-client OK')"
   python -c "import paho.mqtt.client, websocket; print('Python dependencies OK')"
   svstat /service/es-ESS
   ```

5. Restart es-ESS and inspect the log:

   ```sh
   /data/es-ESS/restart.sh
   tail -f -n 100 /data/log/es-ESS/current.log
   ```

6. Confirm there is no compatibility error and that the log reports Venus OS
   `v3.75`.
7. Verify that enabled D-Bus services register once, both MQTT connections
   recover, all three grid phases are fresh, and SolarOverheadDistributor
   publishes safe values.
8. Confirm the actual managed battery remains selected as the GX battery
   monitor and that PV/grid device assignments did not change.
9. In Wattpilot Manual mode, confirm es-ESS reports status but does not issue
   start, stop, current, or phase commands.
10. During a supervised low-risk window, validate one-phase Auto/Eco operation,
   no-grid protection, and then phase switching only when sufficient PV is
   naturally available.

Do not mark the `v3.75` migration as live-validated until these GX, D-Bus,
MQTT, Manual-mode, and supervised Auto/Eco checks have passed.

## Roll Back Using Stored Backup Firmware

This is the preferred and quickest rollback when `v3.73` is still present in
the other root filesystem.

1. Open **Settings → General → Firmware → Stored backup firmware**.
2. Verify that the stored version is exactly `v3.73`. Do not proceed based only
   on an assumption about which version is stored.
3. Select **Press to boot** and confirm.
4. Wait for the Cerbo GX to restart. Venus OS swaps the active and stored
   firmware, so `v3.73` becomes current and `v3.75` becomes the stored option.
5. Run all checks under **Checks Immediately After The Upgrade**, expecting
   `v3.73` instead of `v3.75`. Rerun `/data/es-ESS/install.sh` and restore
   Python packages if required.

## Roll Back Manually With USB Or microSD

Use this method if the stored backup is not `v3.73`, is unavailable, or cannot
boot.

1. Download the official Cerbo GX v3.73 file
   `venus-swu-einstein-20260518083922-v3.73.swu` from Victron's `einstein`
   release directory.
2. Copy the `.swu` file to the root of a FAT32 USB stick or microSD card.
3. Insert it into the Cerbo GX.
4. Open **Settings → General → Firmware → Install from SD/USB**.
5. Select **Check for updates on SD/USB**, verify that the detected file is the
   clean Cerbo GX `v3.73` release, and start the installation.
6. Wait for the reboot, remove the storage device, and verify `v3.73` with:

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
- [Cerbo GX firmware update and rollback manual](https://www.victronenergy.com/media/pg/Cerbo_GX/en/firmware-updates.html)
- [Official Cerbo GX `einstein` firmware archive](https://updates.victronenergy.com/feeds/venus/release/images/einstein/)
- [Victron guidance for persistent `/data` modifications](https://www.victronenergy.com/live/ccgx%3Aroot_access)
