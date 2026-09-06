#!/bin/sh

# Read-only long-running Wattpilot charging-session capture for Venus OS / GX.
# The capture reads D-Bus and the es-ESS log. It never writes charger, D-Bus,
# MQTT, configuration, or service state.

DURATION_SECONDS="${DURATION_SECONDS:-21600}"
SAMPLE_SECONDS="${SAMPLE_SECONDS:-10}"
EV_SERVICE="${WATTPILOT_DBUS_SERVICE:-com.victronenergy.evcharger.esESS_FroniusWattpilot}"
SYSTEM_SERVICE="${SYSTEM_DBUS_SERVICE:-com.victronenergy.system}"
SOURCE_LOG="${LOG_FILE:-/data/log/es-ESS/current.log}"
OUTPUT_ROOT="${OUTPUT_ROOT:-/data/es-ESS-private-diagnostics}"
RUN_ID="$(date '+%Y%m%d-%H%M%S')"
OUTPUT_DIR="${OUTPUT_DIR:-$OUTPUT_ROOT/wattpilot-session-$RUN_ID}"

usage() {
    cat <<'EOF'
Usage: wattpilot-session-capture.sh

Capture Wattpilot and whole-site per-phase telemetry plus new es-ESS log
records. The default run lasts six hours and samples D-Bus every ten seconds.

Run in the foreground:
  sh /data/es-ESS/scripts/wattpilot-session-capture.sh

Keep running after SSH disconnects:
  nohup sh /data/es-ESS/scripts/wattpilot-session-capture.sh >/data/wattpilot-capture-launch.log 2>&1 &

Environment overrides:
  DURATION_SECONDS         Capture duration; default 21600 (six hours)
  SAMPLE_SECONDS           D-Bus sampling interval; default 10
  OUTPUT_ROOT              Private capture parent directory
  OUTPUT_DIR               Exact capture directory
  LOG_FILE                 es-ESS current log
  WATTPILOT_DBUS_SERVICE   Wattpilot D-Bus service name
  SYSTEM_DBUS_SERVICE      Venus system D-Bus service name

Outputs:
  samples.tsv              Periodic charger/site/grid phase measurements
  transitions.tsv          Measured start, stop, phase, target and guard events
  es-ESS-events.log        New es-ESS log lines during the capture
  summary.txt              End-of-run measurements and event counts
  progress.log             Periodic progress records

The output is private operational evidence and must not be committed to the
public repository. Command counts are controller/log evidence, not an encrypted
WebSocket packet capture. APP_DEBUG is needed for frc and guarded-no-op lines.
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

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    usage
    exit 0
fi

[ "$#" -eq 0 ] || fail "unknown argument: $1 (use --help)"
is_positive_integer "$DURATION_SECONDS" || fail "DURATION_SECONDS must be a positive integer"
is_positive_integer "$SAMPLE_SECONDS" || fail "SAMPLE_SECONDS must be a positive integer"
command -v dbus >/dev/null 2>&1 || fail "the Venus OS 'dbus' command is missing"
command -v awk >/dev/null 2>&1 || fail "awk is missing"
command -v tail >/dev/null 2>&1 || fail "tail is missing"
[ -r "$SOURCE_LOG" ] || fail "cannot read $SOURCE_LOG"

umask 077
mkdir -p "$OUTPUT_DIR" || fail "cannot create $OUTPUT_DIR"

SAMPLES="$OUTPUT_DIR/samples.tsv"
TRANSITIONS="$OUTPUT_DIR/transitions.tsv"
EVENT_LOG="$OUTPUT_DIR/es-ESS-events.log"
SUMMARY="$OUTPUT_DIR/summary.txt"
PROGRESS="$OUTPUT_DIR/progress.log"

progress() {
    line="$(date '+%Y-%m-%d %H:%M:%S %z') $*"
    echo "$line"
    echo "$line" >> "$PROGRESS"
}

dbus_get() {
    value="$(
        dbus -y "$1" "$2" GetValue 2>/dev/null |
            tr -d "'\r\n\t"
    )"
    if [ -n "$value" ]; then
        printf '%s' "$value"
    else
        printf 'NA'
    fi
}

event() {
    printf '%s\t%s\t%s\t%s\n' \
        "$(date '+%s')" \
        "$(date '+%Y-%m-%d %H:%M:%S %z')" \
        "$1" "$2" >> "$TRANSITIONS"
}

count_log() {
    grep -Ec "$1" "$EVENT_LOG" 2>/dev/null || true
}

rate_per_hour() {
    awk -v count="$1" -v seconds="$2" '
        BEGIN {
            if (seconds > 0)
                printf "%.2f", count * 3600 / seconds
            else
                printf "0.00"
        }
    '
}

printf '%b\n' \
    "epoch\ttimestamp\tconnected\tmode\tcontrol_state\tphase_mode\tstatus\ttarget_total_a\tmeasured_total_a\tpv_allowance_w\tev_power_w\tev_l1_power_w\tev_l2_power_w\tev_l3_power_w\tev_l1_current_a\tev_l2_current_a\tev_l3_current_a\tev_l1_voltage_v\tev_l2_voltage_v\tev_l3_voltage_v\tsite_l1_power_w\tsite_l2_power_w\tsite_l3_power_w\tsite_l1_current_a\tsite_l2_current_a\tsite_l3_current_a\tgrid_l1_power_w\tgrid_l2_power_w\tgrid_l3_power_w\ttelemetry_healthy\tcommand_authority_ok\tsite_guard\tgrid_guard\tbattery_assist\tsession_energy_kwh\tsession_time_s" \
    > "$SAMPLES"
printf '%b\n' "epoch\ttimestamp\tevent\tdetail" > "$TRANSITIONS"

# Follow rotation when supported. Venus OS BusyBox normally provides -F; fall
# back to -f with an explicit warning when it does not.
if tail --help 2>&1 | grep -q -- '-F'; then
    tail -n 0 -F "$SOURCE_LOG" > "$EVENT_LOG" 2>"$OUTPUT_DIR/tail-errors.log" &
else
    progress "WARNING: tail -F unavailable; log capture will not follow midnight rotation"
    tail -n 0 -f "$SOURCE_LOG" > "$EVENT_LOG" 2>"$OUTPUT_DIR/tail-errors.log" &
fi
TAIL_PID=$!

STOP_REQUESTED=0
trap 'STOP_REQUESTED=1' INT TERM

START_EPOCH="$(date '+%s')"
END_EPOCH=$((START_EPOCH + DURATION_SECONDS))
NEXT_SAMPLE_EPOCH="$START_EPOCH"

last_phase=""
last_stable_phase=""
last_target=""
last_state=""
last_connected=""
last_charging=0
last_telemetry=""
last_authority=""
last_site_guard=""
last_grid_guard=""
last_assist=""

progress "Capture started; output=$OUTPUT_DIR duration=${DURATION_SECONDS}s sample=${SAMPLE_SECONDS}s"
event "CAPTURE_START" "duration=${DURATION_SECONDS}s sample=${SAMPLE_SECONDS}s"

while [ "$(date '+%s')" -lt "$END_EPOCH" ] && [ "$STOP_REQUESTED" -eq 0 ]; do
    epoch="$(date '+%s')"
    timestamp="$(date '+%Y-%m-%d %H:%M:%S %z')"

    connected="$(dbus_get "$EV_SERVICE" /Connected)"
    mode="$(dbus_get "$EV_SERVICE" /ModeLiteral)"
    state="$(dbus_get "$EV_SERVICE" /ControlStateLiteral)"
    phase="$(dbus_get "$EV_SERVICE" /PhaseModeLiteral)"
    status="$(dbus_get "$EV_SERVICE" /StatusLiteral)"
    target="$(dbus_get "$EV_SERVICE" /SetCurrent)"
    measured_total="$(dbus_get "$EV_SERVICE" /Current)"
    allowance="$(dbus_get "$EV_SERVICE" /PvAllowance)"
    ev_power="$(dbus_get "$EV_SERVICE" /Ac/Power)"
    ev_l1_power="$(dbus_get "$EV_SERVICE" /Ac/L1/Power)"
    ev_l2_power="$(dbus_get "$EV_SERVICE" /Ac/L2/Power)"
    ev_l3_power="$(dbus_get "$EV_SERVICE" /Ac/L3/Power)"
    ev_l1_current="$(dbus_get "$EV_SERVICE" /Ac/L1/Current)"
    ev_l2_current="$(dbus_get "$EV_SERVICE" /Ac/L2/Current)"
    ev_l3_current="$(dbus_get "$EV_SERVICE" /Ac/L3/Current)"
    ev_l1_voltage="$(dbus_get "$EV_SERVICE" /Ac/L1/Voltage)"
    ev_l2_voltage="$(dbus_get "$EV_SERVICE" /Ac/L2/Voltage)"
    ev_l3_voltage="$(dbus_get "$EV_SERVICE" /Ac/L3/Voltage)"
    site_l1_power="$(dbus_get "$SYSTEM_SERVICE" /Ac/Consumption/L1/Power)"
    site_l2_power="$(dbus_get "$SYSTEM_SERVICE" /Ac/Consumption/L2/Power)"
    site_l3_power="$(dbus_get "$SYSTEM_SERVICE" /Ac/Consumption/L3/Power)"
    site_l1_current="$(dbus_get "$SYSTEM_SERVICE" /Ac/Consumption/L1/Current)"
    site_l2_current="$(dbus_get "$SYSTEM_SERVICE" /Ac/Consumption/L2/Current)"
    site_l3_current="$(dbus_get "$SYSTEM_SERVICE" /Ac/Consumption/L3/Current)"
    grid_l1_power="$(dbus_get "$SYSTEM_SERVICE" /Ac/Grid/L1/Power)"
    grid_l2_power="$(dbus_get "$SYSTEM_SERVICE" /Ac/Grid/L2/Power)"
    grid_l3_power="$(dbus_get "$SYSTEM_SERVICE" /Ac/Grid/L3/Power)"
    telemetry="$(dbus_get "$EV_SERVICE" /TelemetryHealthy)"
    authority="$(dbus_get "$EV_SERVICE" /CommandAuthorityOk)"
    site_guard="$(dbus_get "$EV_SERVICE" /SiteCurrentGuardBlocked)"
    grid_guard="$(dbus_get "$EV_SERVICE" /GridImportGuardActive)"
    assist="$(dbus_get "$EV_SERVICE" /BatteryAssistActive)"
    session_energy="$(dbus_get "$EV_SERVICE" /Session/Energy)"
    session_time="$(dbus_get "$EV_SERVICE" /Session/Time)"

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$epoch" "$timestamp" "$connected" "$mode" "$state" "$phase" "$status" \
        "$target" "$measured_total" "$allowance" "$ev_power" \
        "$ev_l1_power" "$ev_l2_power" "$ev_l3_power" \
        "$ev_l1_current" "$ev_l2_current" "$ev_l3_current" \
        "$ev_l1_voltage" "$ev_l2_voltage" "$ev_l3_voltage" \
        "$site_l1_power" "$site_l2_power" "$site_l3_power" \
        "$site_l1_current" "$site_l2_current" "$site_l3_current" \
        "$grid_l1_power" "$grid_l2_power" "$grid_l3_power" \
        "$telemetry" "$authority" "$site_guard" "$grid_guard" "$assist" \
        "$session_energy" "$session_time" >> "$SAMPLES"

    charging="$(awk -v value="$ev_power" 'BEGIN { print ((value + 0) > 100) ? 1 : 0 }')"

    if [ -n "$last_connected" ] && [ "$connected" != "$last_connected" ]; then
        event "CONNECTION_CHANGE" "$last_connected -> $connected"
    fi
    if [ -n "$last_state" ] && [ "$state" != "$last_state" ]; then
        event "CONTROL_STATE_CHANGE" "$last_state -> $state"
    fi
    if [ -n "$last_phase" ] && [ "$phase" != "$last_phase" ]; then
        event "PHASE_STATE_CHANGE" "$last_phase -> $phase"
    fi

    case "$phase" in
        "1 phase"|"3 phases")
            if [ -n "$last_stable_phase" ] && [ "$phase" != "$last_stable_phase" ]; then
                if [ "$last_stable_phase" = "1 phase" ] && [ "$phase" = "3 phases" ]; then
                    event "PHASE_UP_CONFIRMED" "$last_stable_phase -> $phase"
                elif [ "$last_stable_phase" = "3 phases" ] && [ "$phase" = "1 phase" ]; then
                    event "PHASE_DOWN_CONFIRMED" "$last_stable_phase -> $phase"
                fi
            fi
            last_stable_phase="$phase"
            ;;
    esac

    if [ -n "$last_target" ] && [ "$target" != "$last_target" ]; then
        event "CURRENT_TARGET_CHANGE" "$last_target -> $target total A; phase=$phase"
    fi
    if [ "$last_charging" -eq 0 ] && [ "$charging" -eq 1 ]; then
        event "MEASURED_CHARGING_START" "power=${ev_power}W phase=$phase target=${target}A"
    elif [ "$last_charging" -eq 1 ] && [ "$charging" -eq 0 ]; then
        event "MEASURED_CHARGING_STOP" "power=${ev_power}W state=$state"
    fi
    if [ -n "$last_telemetry" ] && [ "$telemetry" != "$last_telemetry" ]; then
        event "TELEMETRY_HEALTH_CHANGE" "$last_telemetry -> $telemetry"
    fi
    if [ -n "$last_authority" ] && [ "$authority" != "$last_authority" ]; then
        event "COMMAND_AUTHORITY_CHANGE" "$last_authority -> $authority"
    fi
    if [ -n "$last_site_guard" ] && [ "$site_guard" != "$last_site_guard" ]; then
        event "SITE_GUARD_CHANGE" "$last_site_guard -> $site_guard"
    fi
    if [ -n "$last_grid_guard" ] && [ "$grid_guard" != "$last_grid_guard" ]; then
        event "GRID_GUARD_CHANGE" "$last_grid_guard -> $grid_guard"
    fi
    if [ -n "$last_assist" ] && [ "$assist" != "$last_assist" ]; then
        event "BATTERY_ASSIST_CHANGE" "$last_assist -> $assist"
    fi

    last_connected="$connected"
    last_state="$state"
    last_phase="$phase"
    last_target="$target"
    last_charging="$charging"
    last_telemetry="$telemetry"
    last_authority="$authority"
    last_site_guard="$site_guard"
    last_grid_guard="$grid_guard"
    last_assist="$assist"

    elapsed=$((epoch - START_EPOCH))
    if [ $((elapsed % 300)) -lt "$SAMPLE_SECONDS" ]; then
        progress "elapsed=${elapsed}s power=${ev_power}W phase=$phase target=${target}A allowance=${allowance}W"
    fi

    NEXT_SAMPLE_EPOCH=$((NEXT_SAMPLE_EPOCH + SAMPLE_SECONDS))
    now_epoch="$(date '+%s')"
    sleep_seconds=$((NEXT_SAMPLE_EPOCH - now_epoch))
    if [ "$sleep_seconds" -gt 0 ]; then
        sleep "$sleep_seconds"
    fi
done

FINAL_EPOCH="$(date '+%s')"
ACTUAL_SECONDS=$((FINAL_EPOCH - START_EPOCH))
kill "$TAIL_PID" 2>/dev/null || true
wait "$TAIL_PID" 2>/dev/null || true
event "CAPTURE_END" "actual_duration=${ACTUAL_SECONDS}s"

amp_adjustments="$(count_log 'Adjusting charge current to|Reducing charge current from continuation PV|Reducing to [0-9]+A')"
start_actions="$(count_log 'Starting to charge after')"
frc_messages="$(count_log 'Start/Stop to send: frc=')"
phase_up_actions="$(count_log 'Switching to 3-phase from PV surplus')"
phase_down_actions="$(count_log 'Switching to 1-phase')"
stop_actions="$(count_log 'STOP send!|Stopping (Auto/Eco |Eco |EV )?charging')"
guarded_noops="$(count_log 'current setpoint already confirmed; accepting guarded no-op')"
blocked_commands="$(count_log 'Blocked Wattpilot setValue')"
authentication_events="$(count_log 'Authentication successful')"
disconnect_events="$(count_log 'Wattpilot disconnected|WebSocket worker did not stop')"

measured_starts="$(grep -c 'MEASURED_CHARGING_START' "$TRANSITIONS" 2>/dev/null || true)"
measured_stops="$(grep -c 'MEASURED_CHARGING_STOP' "$TRANSITIONS" 2>/dev/null || true)"
confirmed_phase_ups="$(grep -c 'PHASE_UP_CONFIRMED' "$TRANSITIONS" 2>/dev/null || true)"
confirmed_phase_downs="$(grep -c 'PHASE_DOWN_CONFIRMED' "$TRANSITIONS" 2>/dev/null || true)"
target_changes="$(grep -c 'CURRENT_TARGET_CHANGE' "$TRANSITIONS" 2>/dev/null || true)"

duplicate_candidates="$(
    grep -E 'Adjusting charge current to [0-9]+A' "$EVENT_LOG" 2>/dev/null |
        sed -n 's/.*Adjusting charge current to \([0-9][0-9]*\)A.*/\1/p' |
        awk 'previous == $1 { duplicates++ } { previous=$1 } END { print duplicates+0 }'
)"

{
    echo "Wattpilot charging-session capture summary"
    echo "Started epoch:  $START_EPOCH"
    echo "Finished epoch: $FINAL_EPOCH"
    echo "Duration:       $ACTUAL_SECONDS seconds"
    echo
    echo "Measured transitions"
    echo "  Charging starts:          $measured_starts"
    echo "  Charging stops:           $measured_stops"
    echo "  Confirmed phase-ups:      $confirmed_phase_ups"
    echo "  Confirmed phase-downs:    $confirmed_phase_downs"
    echo "  Current-target changes:   $target_changes"
    echo
    echo "Controller command evidence"
    echo "  Current adjustments:      $amp_adjustments ($(rate_per_hour "$amp_adjustments" "$ACTUAL_SECONDS") per hour)"
    echo "  Start actions:            $start_actions ($(rate_per_hour "$start_actions" "$ACTUAL_SECONDS") per hour)"
    echo "  frc transport markers:    $frc_messages ($(rate_per_hour "$frc_messages" "$ACTUAL_SECONDS") per hour)"
    echo "  Phase-up actions:         $phase_up_actions"
    echo "  Phase-down actions:       $phase_down_actions"
    echo "  Stop actions:             $stop_actions"
    echo "  Guarded current no-ops:   $guarded_noops"
    echo "  Blocked commands:         $blocked_commands"
    echo "  Consecutive same-target adjustment candidates: $duplicate_candidates"
    echo
    echo "Connection evidence"
    echo "  Authentication events:    $authentication_events"
    echo "  Disconnect/reconnect evidence: $disconnect_events"
    echo
    echo "Charging measurements"

    awk -F '\t' -v interval="$SAMPLE_SECONDS" '
        NR > 1 && ($11 + 0) > 100 {
            count++
            total_power += $11
            p1 += $12; p2 += $13; p3 += $14
            a1 += $15; a2 += $16; a3 += $17
            site1 += $21; site2 += $22; site3 += $23
            if (count == 1 || $11 < min_power) min_power=$11
            if (count == 1 || $11 > max_power) max_power=$11
            if ($6 == "1 phase") one_phase++
            if ($6 == "3 phases") three_phase++
            if ($30 != "1") unhealthy++
            if ($31 != "1") no_authority++
            if ($32 == "1") site_guard++
            if ($33 == "1") grid_guard++
            if ($34 == "1") assist++
        }
        END {
            if (count == 0) {
                print "  No measured charging samples."
                exit
            }
            printf "  Charging samples:          %d\n", count
            printf "  Approx. charging time:     %.2f h\n", count*interval/3600
            printf "  Approx. integrated energy: %.3f kWh\n", total_power*interval/3600000
            printf "  EV power min/avg/max:      %.0f / %.0f / %.0f W\n", min_power, total_power/count, max_power
            printf "  EV L1/L2/L3 avg power:     %.0f / %.0f / %.0f W\n", p1/count, p2/count, p3/count
            printf "  EV L1/L2/L3 avg current:   %.2f / %.2f / %.2f A\n", a1/count, a2/count, a3/count
            printf "  Site L1/L2/L3 avg power:   %.0f / %.0f / %.0f W\n", site1/count, site2/count, site3/count
            printf "  One-phase duration:        %.2f h\n", one_phase*interval/3600
            printf "  Three-phase duration:      %.2f h\n", three_phase*interval/3600
            printf "  Unhealthy telemetry samples while charging: %d\n", unhealthy
            printf "  Missing authority samples while charging:   %d\n", no_authority
            printf "  Site-guard samples while charging:           %d\n", site_guard
            printf "  Grid-guard samples while charging:           %d\n", grid_guard
            printf "  Battery-assist samples while charging:       %d\n", assist
        }
    ' "$SAMPLES"

    echo
    echo "Important limitation"
    echo "  Counts are controller/D-Bus/log evidence, not an encrypted WebSocket packet capture."
    echo "  APP_DEBUG is required to see frc transport markers and guarded no-op messages."
    echo
    echo "Files"
    echo "  Samples:     $SAMPLES"
    echo "  Transitions: $TRANSITIONS"
    echo "  New log:     $EVENT_LOG"
} > "$SUMMARY"

progress "Capture finished; summary=$SUMMARY"
cat "$SUMMARY"
