#!/bin/sh

# Read-only live validation for Wattpilot current-command deduplication.
#
# The script reads the es-ESS EV-charger D-Bus service and new current.log
# entries. It never writes D-Bus, MQTT, configuration, service state, or a
# Wattpilot value.

WATTPILOT_DBUS_SERVICE="${WATTPILOT_DBUS_SERVICE:-com.victronenergy.evcharger.esESS_FroniusWattpilot}"
LOG_FILE="${LOG_FILE:-/data/log/es-ESS/current.log}"
SAMPLE_SECONDS="${SAMPLE_SECONDS:-5}"
DURATION_SECONDS="${DURATION_SECONDS:-60}"
STABLE_SAMPLES="${STABLE_SAMPLES:-3}"
MAX_WARMUP_SECONDS="${MAX_WARMUP_SECONDS:-60}"

usage() {
    cat <<'EOF'
Usage: wattpilot-current-command-monitor.sh

Observe a stable Auto/Eco charge and check that es-ESS does not repeatedly
dispatch the same positive current target.

Environment overrides:
  DURATION_SECONDS       Stable observation duration (default: 60)
  SAMPLE_SECONDS         D-Bus sampling interval (default: 5)
  STABLE_SAMPLES         Equal target samples required first (default: 3)
  MAX_WARMUP_SECONDS     Maximum stabilization wait (default: 60)
  LOG_FILE               es-ESS log path
  WATTPILOT_DBUS_SERVICE Wattpilot D-Bus service name

Example:
  DURATION_SECONDS=120 sh /data/es-ESS/scripts/wattpilot-current-command-monitor.sh

The result is controller-level evidence from D-Bus and logs. It is not a
packet capture of the encrypted Wattpilot WebSocket connection.
EOF
}

fail() {
    echo "ERROR: $*" >&2
    exit 2
}

is_positive_integer() {
    case "$1" in
        ''|*[!0-9]*|0) return 1 ;;
        *) return 0 ;;
    esac
}

dbus_get() {
    path="$1"
    value="$(dbus -y "$WATTPILOT_DBUS_SERVICE" "$path" GetValue 2>/dev/null | tr -d "'\r")"
    if [ -n "$value" ]
    then
        printf '%s' "$value"
    else
        printf '%s' "unavailable"
    fi
}

read_snapshot() {
    connected="$(dbus_get /Connected)"
    mode="$(dbus_get /ModeLiteral)"
    control_state="$(dbus_get /ControlStateLiteral)"
    phase_mode="$(dbus_get /PhaseModeLiteral)"
    target_total_a="$(dbus_get /SetCurrent)"
    measured_total_a="$(dbus_get /Current)"
    power_w="$(dbus_get /Ac/Power)"
    l1_a="$(dbus_get /Ac/L1/Current)"
    l2_a="$(dbus_get /Ac/L2/Current)"
    l3_a="$(dbus_get /Ac/L3/Current)"
    l1_v="$(dbus_get /Ac/L1/Voltage)"
    l2_v="$(dbus_get /Ac/L2/Voltage)"
    l3_v="$(dbus_get /Ac/L3/Voltage)"
    allowance_w="$(dbus_get /PvAllowance)"
    telemetry_healthy="$(dbus_get /TelemetryHealthy)"
    authority_ok="$(dbus_get /CommandAuthorityOk)"
    site_guard="$(dbus_get /SiteCurrentGuardBlocked)"
    grid_guard="$(dbus_get /GridImportGuardActive)"
    battery_assist="$(dbus_get /BatteryAssistActive)"
    session_kwh="$(dbus_get /Session/Energy)"
    session_seconds="$(dbus_get /Session/Time)"

    case "$phase_mode" in
        "3 phases")
            target_per_phase_a="$(awk -v value="$target_total_a" 'BEGIN { if (value + 0 == value) printf "%.1f", value / 3; else print "unavailable" }')"
            ;;
        "1 phase")
            target_per_phase_a="$target_total_a"
            ;;
        *)
            target_per_phase_a="unavailable"
            ;;
    esac

    target_signature="$phase_mode|$target_total_a|$control_state"
}

print_snapshot() {
    printf '%s | %-17s | target=%-5s A/phase | measured L1/L2/L3=%s/%s/%s A | power=%s W | allowance=%s W\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$phase_mode" \
        "$target_per_phase_a" \
        "$l1_a" "$l2_a" "$l3_a" \
        "$power_w" "$allowance_w"
}

print_current_charge() {
    echo
    echo "Current charging snapshot"
    echo "  Connected:              $connected"
    echo "  Mode:                   $mode"
    echo "  Controller state:       $control_state"
    echo "  Phase mode:             $phase_mode"
    echo "  Charging power:         $power_w W"
    echo "  Target current:         $target_per_phase_a A per phase ($target_total_a A on the Victron total-current path)"
    echo "  Measured total current: $measured_total_a A"
    echo "  Measured L1/L2/L3:      $l1_a / $l2_a / $l3_a A"
    echo "  Voltage L1/L2/L3:       $l1_v / $l2_v / $l3_v V"
    echo "  Session energy/time:    $session_kwh kWh / $session_seconds s"
    echo "  PV allowance:           $allowance_w W"
    echo "  Telemetry healthy:      $telemetry_healthy"
    echo "  Command authority OK:   $authority_ok"
    echo "  Site/grid guards:       $site_guard / $grid_guard"
    echo "  Battery assist:         $battery_assist"
}

new_log_range() {
    first_line="$1"
    last_line="$2"
    if [ "$last_line" -ge "$first_line" ] 2>/dev/null
    then
        sed -n "${first_line},${last_line}p" "$LOG_FILE"
    fi
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]
then
    usage
    exit 0
fi

[ "$#" -eq 0 ] || fail "unknown argument: $1 (use --help)"
command -v dbus >/dev/null 2>&1 || fail "the Venus OS 'dbus' command is missing"
command -v awk >/dev/null 2>&1 || fail "awk is missing"
is_positive_integer "$SAMPLE_SECONDS" || fail "SAMPLE_SECONDS must be a positive integer"
is_positive_integer "$DURATION_SECONDS" || fail "DURATION_SECONDS must be a positive integer"
is_positive_integer "$STABLE_SAMPLES" || fail "STABLE_SAMPLES must be a positive integer"
is_positive_integer "$MAX_WARMUP_SECONDS" || fail "MAX_WARMUP_SECONDS must be a positive integer"
[ -r "$LOG_FILE" ] || fail "cannot read $LOG_FILE"

echo "Read-only Wattpilot current-command monitor"
echo "Service: $WATTPILOT_DBUS_SERVICE"
echo "Log:     $LOG_FILE"
echo
echo "Waiting for $STABLE_SAMPLES equal target/state samples before testing..."

stable_count=0
warmup_elapsed=0
previous_signature=""

while [ "$warmup_elapsed" -lt "$MAX_WARMUP_SECONDS" ]
do
    read_snapshot
    print_snapshot

    if [ "$connected" != "1" ] || [ "$telemetry_healthy" != "1" ] || [ "$authority_ok" != "1" ]
    then
        stable_count=0
        previous_signature=""
    elif [ "$target_signature" = "$previous_signature" ]
    then
        stable_count=$((stable_count + 1))
    else
        stable_count=1
        previous_signature="$target_signature"
    fi

    if [ "$stable_count" -ge "$STABLE_SAMPLES" ]
    then
        break
    fi

    sleep "$SAMPLE_SECONDS"
    warmup_elapsed=$((warmup_elapsed + SAMPLE_SECONDS))
done

if [ "$stable_count" -lt "$STABLE_SAMPLES" ]
then
    print_current_charge
    echo
    echo "RESULT: INCONCLUSIVE"
    echo "The charger did not provide a healthy, authoritative, stable target during warm-up."
    exit 1
fi

baseline_signature="$target_signature"
baseline_phase="$phase_mode"
baseline_target="$target_per_phase_a"
log_start_line="$(wc -l < "$LOG_FILE" | tr -d ' ')"
test_first_line=$((log_start_line + 1))

echo
echo "Stable baseline established: $baseline_phase at $baseline_target A per phase."
echo "Observing for $DURATION_SECONDS seconds. Press Ctrl-C to stop."

elapsed=0
target_changes=0
unhealthy_samples=0

while [ "$elapsed" -lt "$DURATION_SECONDS" ]
do
    sleep "$SAMPLE_SECONDS"
    elapsed=$((elapsed + SAMPLE_SECONDS))
    read_snapshot
    print_snapshot

    if [ "$target_signature" != "$baseline_signature" ]
    then
        target_changes=$((target_changes + 1))
    fi
    if [ "$connected" != "1" ] || [ "$telemetry_healthy" != "1" ] || [ "$authority_ok" != "1" ]
    then
        unhealthy_samples=$((unhealthy_samples + 1))
    fi
done

log_end_line="$(wc -l < "$LOG_FILE" | tr -d ' ')"

print_current_charge
echo
echo "New controller current-command evidence"

if [ "$log_end_line" -lt "$log_start_line" ] 2>/dev/null
then
    echo "  Log rotated or was truncated during the test."
    echo
    echo "RESULT: INCONCLUSIVE"
    echo "Rerun the monitor in a window that does not cross log rotation."
    exit 1
fi

adjustment_lines="$(new_log_range "$test_first_line" "$log_end_line" | grep -F 'Adjusting charge current to' || true)"
noop_lines="$(new_log_range "$test_first_line" "$log_end_line" | grep -F 'Wattpilot current setpoint already confirmed; accepting guarded no-op' || true)"
blocked_lines="$(new_log_range "$test_first_line" "$log_end_line" | grep -F 'Blocked Wattpilot setValue amp=' || true)"

adjustment_count="$(printf '%s\n' "$adjustment_lines" | grep -c '[^[:space:]]' || true)"
noop_count="$(printf '%s\n' "$noop_lines" | grep -c '[^[:space:]]' || true)"
blocked_count="$(printf '%s\n' "$blocked_lines" | grep -c '[^[:space:]]' || true)"

echo "  Dispatched normal adjustments: $adjustment_count"
echo "  Confirmed guarded no-ops:       $noop_count"
echo "  Blocked amp commands:           $blocked_count"

if [ -n "$adjustment_lines" ]
then
    echo
    printf '%s\n' "$adjustment_lines"
fi
if [ -n "$noop_lines" ]
then
    echo
    printf '%s\n' "$noop_lines"
fi
if [ -n "$blocked_lines" ]
then
    echo
    printf '%s\n' "$blocked_lines"
fi

echo
if [ "$unhealthy_samples" -gt 0 ] || [ "$blocked_count" -gt 0 ]
then
    echo "RESULT: INCONCLUSIVE"
    echo "Telemetry/authority became unhealthy or a safety guard blocked a command."
elif [ "$target_changes" -gt 0 ]
then
    echo "RESULT: INCONCLUSIVE"
    echo "The target, phase, or controller state changed during the stable-window test."
    echo "The adjustment lines above show whether es-ESS responded to those changes."
elif [ "$adjustment_count" -gt 0 ]
then
    echo "RESULT: FAIL"
    echo "es-ESS logged a normal positive-current dispatch while the confirmed target remained unchanged."
else
    echo "RESULT: PASS"
    echo "No repeated positive-current adjustment was dispatched during the stable target window."
    if [ "$noop_count" -eq 0 ]
    then
        echo "No guarded no-op line appeared; that APP_DEBUG message is emitted only once per stable target."
    fi
fi
