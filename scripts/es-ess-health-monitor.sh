#!/bin/sh

# Read-only production health monitor for es-ESS on Victron Venus OS / GX.
# Intended for post-deploy, post-firmware, morning daylight, and supervised
# Wattpilot Auto/Eco validation windows. It does not write D-Bus, MQTT, config,
# service state, or Wattpilot control values.

INTERVAL_SECONDS="${INTERVAL_SECONDS:-10}"
MAX_SAMPLES="${MAX_SAMPLES:-1}"
LOG_LINES="${LOG_LINES:-300}"
EVENT_LINES="${EVENT_LINES:-40}"
CONFIG_FILE="${CONFIG_FILE:-/data/es-ESS/config.ini}"
LOG_FILE="${LOG_FILE:-/data/log/es-ESS/current.log}"
SERVICE_DIR="${SERVICE_DIR:-/service/es-ESS}"
APP_DIR="${APP_DIR:-/data/es-ESS}"
WATTPILOT_DBUS_SERVICE="${WATTPILOT_DBUS_SERVICE:-com.victronenergy.evcharger.esESS_FroniusWattpilot}"
EXPECTED_VENUS_OS="${EXPECTED_VENUS_OS:-v3.75}"

sample=0

print_header() {
    echo
    echo "================================================================"
    echo "es-ESS health monitor | $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "================================================================"
}

print_kv() {
    key="$1"
    value="$2"
    printf '%-34s %s\n' "$key:" "$value"
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

read_first_line() {
    file="$1"
    if [ -r "$file" ]
    then
        sed -n '1p' "$file" 2>/dev/null
    else
        echo "unavailable"
    fi
}

dbus_get_from() {
    service="$1"
    path="$2"
    if ! command_exists dbus
    then
        echo "unavailable: dbus command missing"
        return
    fi

    value="$(dbus -y "$service" "$path" GetValue 2>/dev/null | tr -d "'")"
    if [ -n "$value" ]
    then
        echo "$value"
    else
        echo "unavailable"
    fi
}

dbus_get() {
    dbus_get_from "$WATTPILOT_DBUS_SERVICE" "$1"
}

check_python_dependencies() {
    if python -c "import paho.mqtt.client, websocket" >/dev/null 2>&1
    then
        echo "OK: paho.mqtt.client and websocket import"
    else
        echo "WARN: Python dependency import failed"
    fi
}

print_runtime() {
    version="$(read_first_line /opt/victronenergy/version)"
    print_kv "Venus OS version" "$version"

    if [ "$version" = "$EXPECTED_VENUS_OS" ]
    then
        print_kv "Venus OS compatibility" "OK: expected $EXPECTED_VENUS_OS"
    else
        print_kv "Venus OS compatibility" "WARN: expected $EXPECTED_VENUS_OS"
    fi

    if command_exists svstat
    then
        service_state="$(svstat "$SERVICE_DIR" 2>/dev/null)"
    else
        service_state="unavailable: svstat command missing"
    fi
    print_kv "Service state" "$service_state"

    case "$service_state" in
        *": up "*)
            print_kv "Service health" "OK"
            ;;
        *)
            print_kv "Service health" "WARN: not confirmed up"
            ;;
    esac

    print_kv "Python dependencies" "$(check_python_dependencies)"

    if [ -e "$APP_DIR" ]
    then
        print_kv "App directory" "OK: $APP_DIR"
    else
        print_kv "App directory" "WARN: missing $APP_DIR"
    fi

    if [ -L "$SERVICE_DIR" ] || [ -d "$SERVICE_DIR" ]
    then
        service_link="$(ls -ld "$SERVICE_DIR" 2>/dev/null)"
        print_kv "Service link" "$service_link"
    else
        print_kv "Service link" "WARN: missing $SERVICE_DIR"
    fi

    if [ -r /data/rc.local ] && grep -F "$APP_DIR/install.sh" /data/rc.local >/dev/null 2>&1
    then
        print_kv "rc.local recovery hook" "OK"
    else
        print_kv "rc.local recovery hook" "WARN: $APP_DIR/install.sh not found in /data/rc.local"
    fi
}

print_disk() {
    echo
    echo "-- Disk usage --"
    df -h / /data 2>/dev/null
}

print_config() {
    echo
    echo "-- Selected config values --"
    if [ ! -r "$CONFIG_FILE" ]
    then
        echo "WARN: cannot read $CONFIG_FILE"
        return
    fi

    grep -E '^(FroniusWattpilot|SolarOverheadDistributor|AllowGridCharging|MinCurrentPerPhase|MaxCurrentPerPhase|ThreePhasePvSurplusStartW|ThreePhasePvSurplusStopW|MinOnOffSeconds|MinPhaseSwitchSeconds|BatteryAssistEnabled|BatteryAssistSocMin|BatteryAssistMaxSeconds|BatteryAssistMaxShortfallW|BatterySocFreshSeconds|BatteryAssistRecoverySeconds|GridImportPositive)=' "$CONFIG_FILE" 2>/dev/null || echo "No selected config values found"
}

print_wattpilot_dbus() {
    echo
    echo "-- Wattpilot D-Bus snapshot --"
    echo "Service: $WATTPILOT_DBUS_SERVICE"

    for path in \
        /Connected \
        /StatusLiteral \
        /ModeLiteral \
        /StartStopLiteral \
        /Ac/Power \
        /Current \
        /SetCurrent \
        /PvAllowance \
        /PhaseModeLiteral \
        /ControlStateLiteral \
        /BatteryAssistActive \
        /GridImportGuardActive \
        /TelemetryHealthy \
        /CompatibilityOk \
        /CompatibilityLiteral \
        /ExpectedVenusOsVersion \
        /ActualVenusOsVersion \
        /ExpectedWattpilotFirmware \
        /ActualWattpilotFirmware \
        /ValidatedWattpilotAppVersion
    do
        print_kv "$path" "$(dbus_get "$path")"
    done
}

print_system_battery_dbus() {
    echo
    echo "-- Selected system-battery D-Bus snapshot --"
    echo "Repeated samples should show /Dc/Battery/Power changing inside BatterySocFreshSeconds."

    for path in \
        /ActiveBatteryService \
        /Dc/Battery/Soc \
        /Dc/Battery/Power
    do
        print_kv "$path" "$(dbus_get_from com.victronenergy.system "$path")"
    done
}

print_log_health() {
    echo
    echo "-- Recent log health --"

    if [ ! -r "$LOG_FILE" ]
    then
        echo "WARN: cannot read $LOG_FILE"
        return
    fi

    recent_errors="$(tail -n "$LOG_LINES" "$LOG_FILE" 2>/dev/null | grep -Ei 'CRITICAL|Traceback|ModuleNotFoundError|Unsupported Venus OS|not validated|CompatibilityError|Exception' | tail -n "$EVENT_LINES")"
    if [ -n "$recent_errors" ]
    then
        echo "WARN: recent error/compatibility events:"
        echo "$recent_errors"
    else
        echo "OK: no recent critical/error/compatibility events in last $LOG_LINES log lines"
    fi

    echo
    echo "-- Recent Wattpilot safety/control events --"
    recent_events="$(tail -n "$LOG_LINES" "$LOG_FILE" 2>/dev/null | grep -Ei 'Validated Venus OS compatibility|Battery assist|Grid import guard|Telemetry|Waiting for stable PV allowance|Starting to charge|Stopping|Stopped|Charging|NotCharging|Phase|phase|set_start_stop|Start/Stop to send|set_current|set_phase|setValue|frc=|amp=|psm=' | tail -n "$EVENT_LINES")"
    if [ -n "$recent_events" ]
    then
        echo "$recent_events"
    else
        echo "No recent Wattpilot safety/control events in last $LOG_LINES log lines"
    fi

    echo
    echo "-- Recent Wattpilot mode-boundary events --"
    mode_events="$(tail -n "$LOG_LINES" "$LOG_FILE" 2>/dev/null | grep -E 'Wattpilot mode telemetry changed|Published Wattpilot mode telemetry|Manual mode selected' | tail -n "$EVENT_LINES")"
    if [ -n "$mode_events" ]
    then
        echo "$mode_events"
    else
        echo "No recent Wattpilot mode-boundary events in last $LOG_LINES log lines"
    fi
}

print_interpretation_hint() {
    echo
    echo "-- Interpretation hints --"
    echo "OK signs:"
    echo "  - Service state is up."
    echo "  - Python dependencies import successfully."
    echo "  - CompatibilityOk is 1, or CompatibilityLiteral reports validated firmware."
    echo "  - TelemetryHealthy is 1 during Auto/Eco decisions."
    echo "  - GridImportGuardActive stays 0 during normal no-grid operation."
    echo "  - BatteryAssistActive is bounded and later recovers."
    echo "  - Raw lmo change and /ModeLiteral publication timestamps follow in the expected order."
    echo
    echo "Stop and inspect immediately if:"
    echo "  - Service is down or restarting repeatedly."
    echo "  - Recent logs show CRITICAL, Traceback, ModuleNotFoundError, or not validated."
    echo "  - Auto/Eco charging shows sustained grid import with AllowGridCharging=false."
    echo "  - Battery assist exceeds configured duration/shortfall expectations."
    echo "  - Manual mode produces Wattpilot start/stop/current/phase commands."
}

run_sample() {
    print_header
    print_runtime
    print_disk
    print_config
    print_system_battery_dbus
    print_wattpilot_dbus
    print_log_health
    print_interpretation_hint
}

echo "Read-only es-ESS health monitor."
echo "INTERVAL_SECONDS=$INTERVAL_SECONDS MAX_SAMPLES=$MAX_SAMPLES LOG_LINES=$LOG_LINES"
echo "Set MAX_SAMPLES=0 for continuous monitoring. Press Ctrl-C to stop."

while :
do
    sample=$((sample + 1))
    run_sample

    if [ "$MAX_SAMPLES" -gt 0 ] 2>/dev/null && [ "$sample" -ge "$MAX_SAMPLES" ]
    then
        break
    fi

    sleep "$INTERVAL_SECONDS"
done
