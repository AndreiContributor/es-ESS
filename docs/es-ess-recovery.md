# es-ESS Accidental-Deletion Recovery

Use this runbook when `/data/es-ESS` was deleted outside the supported
`uninstall.sh` workflow, for example through WinSCP. It is intentionally
different from a normal fresh installation: the old Python process may still
be running from memory, the service symlink may be dangling, and the process
may recreate `runtimeData` after the application directory disappears.

Wattpilot control is safety-sensitive. Keep the vehicle disconnected or use
the Solar.wattpilot app to stop charging or select Manual before changing
service state. Manual mode remains user-controlled.

## What Survives A Manual Folder Deletion

- A running `python /data/es-ESS/es-ESS.py` process can continue from memory
  until it exits. Deleting its source directory does not stop it.
- `/data/log/es-ESS` is outside the application directory and normally remains
  available.
- The running process may recreate `/data/es-ESS/runtimeData` and persist
  Wattpilot energy counters there during graceful shutdown.
- `/service/es-ESS` can remain as a symlink to the now-missing
  `/data/es-ESS/service` directory.
- Manual WinSCP deletion does not run `uninstall.sh` and therefore does not
  create `/data/es-ESS-backups/config.ini.TIMESTAMP`.

Do not assume the surviving process is inert. Until it is stopped, it can
continue the previously loaded configuration and Auto/Eco control behavior.

## Preserve Evidence Before Rebooting Or Stopping

If the deleted configuration is important, avoid rebooting and avoid new
writes to `/data` until the read-only checks below are complete. A reboot
destroys the remaining process-memory and open-file opportunity.

Check external backups and remaining files:

```sh
find /data /media -type f \( \
  -name 'config.ini' -o \
  -name 'config.ini.*' -o \
  -iname '*es-ess*.zip' \
\) 2>/dev/null
```

Check whether the old process is alive and whether it still has a deleted file
open:

```sh
PID=$(pgrep -f '^python[[:space:]]+/data/es-ESS/es-ESS.py$' | head -n 1)
echo "Old es-ESS PID: $PID"

if [ -n "$PID" ]; then
  tr '\0' ' ' < "/proc/$PID/cmdline"
  echo
  ls -l "/proc/$PID/fd"
fi
```

If an entry explicitly points to `config.ini (deleted)`, copy that descriptor
before stopping the process. Replace `FD_NUMBER` with the descriptor shown by
`ls`:

```sh
cp "/proc/$PID/fd/FD_NUMBER" /data/config.ini.recovered
chmod 600 /data/config.ini.recovered
```

This is uncommon because es-ESS normally closes `config.ini` after reading it,
but it must be checked before the process is stopped. Do not print recovered
configuration contents to a shared terminal or log because it may contain
MQTT and Wattpilot credentials.

Download `/data/log/es-ESS` with WinSCP before changing service state. The logs
can identify enabled services and successful shutdown, but they are not a
complete configuration backup and intentionally should not expose passwords.

If `config.ini` was edited through WinSCP, also search the operator PC's local
temporary directory before declaring it lost. On Windows PowerShell:

```powershell
Get-ChildItem $env:TEMP -Recurse -File -Filter "config.ini*" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object FullName, LastWriteTime
```

Filesystem undelete is a last-resort specialist operation. It requires an
offline image and is not safe to attempt against a mounted, actively written
`/data` filesystem.

## Prepare A Disabled Replacement In A Staging Directory

Do not reconstruct the application directly under `/data/es-ESS` while the
old service symlink exists. A partially copied `service/run` can become visible
to the supervisor before configuration and dependencies are ready.

Create a separate staging directory and extract a complete checkout:

```sh
test ! -e /data/es-ESS-stage && test ! -e /data/es-ESS-main || {
  echo "Recovery staging path already exists; inspect it before continuing."
  exit 1
}

mkdir /data/es-ESS-stage
chmod 755 /data/es-ESS-stage

wget -O /data/es-ESS-main.zip \
  https://github.com/AndreiContributor/es-ESS/archive/refs/heads/main.zip
unzip -q /data/es-ESS-main.zip -d /data
cp -a /data/es-ESS-main/. /data/es-ESS-stage/
```

Use a fresh, disabled configuration for the first replacement start:

```sh
cp /data/es-ESS-stage/config.sample.ini /data/es-ESS-stage/config.ini
chmod 600 /data/es-ESS-stage/config.ini
chmod 755 /data/es-ESS-stage/install.sh
chmod 755 /data/es-ESS-stage/service/run
```

Keep any recovered production configuration outside the active application
directory until the disabled replacement has started and passed its health
checks. Set `RECOVERED_CONFIG` to the exact descriptor recovery or external
backup path found earlier, then store it in a private directory or download it
to the operator PC:

```sh
RECOVERED_CONFIG=/data/config.ini.recovered
test -f "$RECOVERED_CONFIG" || {
  echo "Recovered configuration path does not exist"
  exit 1
}

mkdir -p /data/es-ESS-recovery
chmod 700 /data/es-ESS-recovery
cp "$RECOVERED_CONFIG" /data/es-ESS-recovery/config.ini
chmod 600 /data/es-ESS-recovery/config.ini
```

Skip that block when no recovered file exists.

## Run Preflight Checks

These checks do not start es-ESS or control Wattpilot:

```sh
cd /data/es-ESS-stage

python -m py_compile *.py
python -c 'import configparser; c=configparser.ConfigParser(); files=c.read("config.ini"); assert files; print("Configuration syntax passed")'
python -c 'import VelibDependency; VelibDependency.verify_bundled_velib(); print("Pinned velib_python integrity passed")'

cat /opt/victronenergy/version 2>/dev/null || \
cat /etc/venus/version 2>/dev/null
```

The supported runtime must report the exact clean Venus OS version documented
in `RuntimeCompatibility.py` and the README. Do not bypass a mismatch.

Confirm all `[Services]` flags remain disabled before cutover:

```sh
python -c 'import configparser; c=configparser.ConfigParser(); c.read("config.ini"); enabled=[name for name,value in c._sections["Services"].items() if value.strip().lower()=="true"]; assert not enabled, "Enabled services: " + str(enabled); print("All services disabled")'
```

## Stop The Surviving Process Gracefully

First stop charging or select Manual in the Solar.wattpilot app. Then capture
the exact es-ESS PID, remove only the verified service symlink so it cannot
restart, and request graceful shutdown:

```sh
cd /
OLD_PIDS=$(pgrep -f '^python[[:space:]]+/data/es-ESS/es-ESS.py$' || true)
echo "Old es-ESS PID(s): $OLD_PIDS"

if [ -L /service/es-ESS ]; then
  rm -f /service/es-ESS
elif [ -e /service/es-ESS ]; then
  echo "STOP: /service/es-ESS exists but is not a symlink"
  exit 1
fi

if [ -n "$OLD_PIDS" ]; then
  kill -TERM $OLD_PIDS
fi

sleep 10
pgrep -f '^python[[:space:]]+/data/es-ESS/es-ESS.py$' || \
  echo "Old es-ESS process stopped"
```

Do not continue while a matching PID remains. A forced kill skips orderly
Wattpilot stop, grid-setpoint restoration, MQTT disconnect, and runtime-data
persistence. Use it only as a supervised last resort after recovery evidence
has been preserved and the graceful path has demonstrably failed.

The shutdown log should show safe service exits, default grid-setpoint
restoration, Wattpilot stop when the old mode was Auto/Eco, runtime-data
persistence, MQTT disconnect, and `Cleaned up. Bye.`.

## Preserve Runtime Data And Activate The Replacement

After the old process stops, copy any recreated runtime data into staging:

```sh
if [ -d /data/es-ESS/runtimeData ]; then
  mkdir -p /data/es-ESS-stage/runtimeData
  chmod 755 /data/es-ESS-stage/runtimeData
  cp -Rp /data/es-ESS/runtimeData/. /data/es-ESS-stage/runtimeData/
fi
```

Retain the deleted-directory remainder until the replacement is validated,
then move staging into the production path:

```sh
if [ -e /data/es-ESS ]; then
  REMAINDER="/data/es-ESS-deleted-remainder-$(date +%Y%m%d-%H%M%S)"
  mv /data/es-ESS "$REMAINDER"
  echo "Old directory remainder retained at $REMAINDER"
fi

mv /data/es-ESS-stage /data/es-ESS
chmod 755 /data/es-ESS/install.sh
/data/es-ESS/install.sh
```

The installer recreates `/service/es-ESS`, restores the `/data/rc.local`
recovery hook, secures `config.ini`, and allows the supervisor to start the
disabled replacement.

## Verify Before Restoring Production Configuration

```sh
sleep 10

ls -ld /service/es-ESS
pgrep -f '^python[[:space:]]+/data/es-ESS/es-ESS.py$'
tail -n 100 /data/log/es-ESS/current.log
/data/es-ESS/scripts/es-ess-health-monitor.sh
```

Require a stable PID, `Initialization completed`, the supported Venus OS
version, valid bundled `velib_python`, and no traceback or compatibility error.
The fresh configuration should report every optional service as disabled.

Only after this clean baseline passes should production settings be restored
or re-entered. Configure one service at a time, restart gracefully, and rerun
the health monitor. For Wattpilot commissioning, keep the vehicle disconnected
until all of these are true:

- Authentication succeeds.
- Actual Wattpilot firmware is exactly `42.5`.
- `CompatibilityOk=1` and `TelemetryHealthy=1`.
- `NativePvSurplusEnabled=0` and `FlexibleTariffEnabled=0`.
- `CommandAuthorityOk=1` before Auto/Eco charging.
- `AllowGridCharging=false` when no-grid charging is required.
- Battery-assist settings match the operator's intended battery-use policy.
- Solar.wattpilot app version `2.1.0` is operator-confirmed.

An initial firmware `<unavailable>` warning before Wattpilot authentication is
expected. It must be followed by `Authentication successful` and firmware
compatibility confirmation; otherwise Wattpilot commands remain blocked.

## Create And Maintain External Configuration Backups

After each known-good configuration change, create a private backup outside
the application directory:

```sh
mkdir -p /data/es-ESS-backups
chmod 700 /data/es-ESS-backups

BACKUP="/data/es-ESS-backups/config.ini.known-good-$(date +%Y%m%d-%H%M%S)"
cp /data/es-ESS/config.ini "$BACKUP"
chmod 600 "$BACKUP"
ls -l "$BACKUP"
```

Also download a private copy to another device. A backup under `/data` helps
with accidental application-folder deletion but does not protect against
storage failure, factory reset, or recovery-image operations that erase the
whole `/data` partition.

After the replacement and restored configuration are fully validated, inspect
and deliberately remove obsolete staging archives and the retained old
directory remainder. Do not use wildcard deletion against `/data`.

The supported deployment is the complete checkout. Do not ad-hoc delete
runtime, dependency, license, or recovery files to create a smaller production
tree. A future minimal package should use an explicit, tested deployment
manifest rather than manual pruning.

## Related Documentation

- [README setup and configuration](../README.md#setup)
- [Production health monitor](es-ess-health-monitor.md)
- [Cerbo GX firmware upgrade and rollback](cerbo-gx-firmware-upgrade-and-rollback.md)
- [Wattpilot architecture boundaries](wattpilot-architecture.md)
- [System guide](system-guide.html)
