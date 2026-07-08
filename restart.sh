#!/bin/bash
set -eu

PIDS=$(pgrep -f '^python[[:space:]]+/data/es-ESS/es-ESS.py$' || true)
if [ -n "$PIDS" ]; then
    kill -s 15 $PIDS
else
    echo "es-ESS is not running"
fi
