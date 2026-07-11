#!/bin/bash
set -eu

TARGET_COMMAND='python /data/es-ESS/es-ESS.py '
TARGET_PATTERN='^python[[:space:]]+/data/es-ESS/es-ESS.py$'
GRACEFUL_TIMEOUT_SECONDS=10

PIDS=$(pgrep -f "$TARGET_PATTERN" || true)
if [ -z "$PIDS" ]; then
    echo "es-ESS is not running"
    exit 0
fi

original_processes=""
for pid in $PIDS; do
    if [ -r "/proc/$pid/stat" ]; then
        start_time=$(awk '{print $22}' "/proc/$pid/stat")
        if [ -n "$start_time" ]; then
            original_processes="$original_processes $pid:$start_time"
            kill -s 15 "$pid" || true
        fi
    fi
done

is_original_es_ess_process() {
    pid=$1
    expected_start_time=$2

    [ -r "/proc/$pid/stat" ] || return 1
    [ -r "/proc/$pid/cmdline" ] || return 1

    current_start_time=$(awk '{print $22}' "/proc/$pid/stat")
    [ "$current_start_time" = "$expected_start_time" ] || return 1

    current_command=$(tr '\000' ' ' < "/proc/$pid/cmdline")
    [ "$current_command" = "$TARGET_COMMAND" ]
}

elapsed=0
while [ "$elapsed" -lt "$GRACEFUL_TIMEOUT_SECONDS" ]; do
    still_running=false
    for process in $original_processes; do
        pid=${process%%:*}
        start_time=${process#*:}
        if is_original_es_ess_process "$pid" "$start_time" && kill -0 "$pid" 2>/dev/null; then
            still_running=true
            break
        fi
    done

    if [ "$still_running" = false ]; then
        exit 0
    fi

    sleep 1
    elapsed=$((elapsed + 1))
done

echo "Graceful shutdown timed out after ${GRACEFUL_TIMEOUT_SECONDS}s; terminating verified original es-ESS process(es)." >&2
for process in $original_processes; do
    pid=${process%%:*}
    start_time=${process#*:}
    if is_original_es_ess_process "$pid" "$start_time" && kill -0 "$pid" 2>/dev/null; then
        echo "Sending SIGKILL to stuck es-ESS PID $pid." >&2
        kill -s 9 "$pid" || true
    fi
done
