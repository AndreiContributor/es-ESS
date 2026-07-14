#!/bin/bash
set -eu

ES_ESS_DIR=/data/es-ESS
SERVICE_LINK=/service/es-ESS
RC_LOCAL=/data/rc.local
CONFIG_TARGET="$ES_ESS_DIR/config.ini"
BACKUP_DIR=/data/es-ESS-backups
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

if [ -f "$ES_ESS_DIR/service/run" ]; then
    chmod a-x "$ES_ESS_DIR/service/run" || true
fi

PIDS=$(pgrep -f '^python[[:space:]]+/data/es-ESS/es-ESS.py$' || true)
if [ -n "$PIDS" ]; then
    kill -s 15 $PIDS || true
    sleep 2
    PIDS=$(pgrep -f '^python[[:space:]]+/data/es-ESS/es-ESS.py$' || true)
    if [ -n "$PIDS" ]; then
        kill -s 9 $PIDS || true
    fi
fi

if [ -f "$CONFIG_TARGET" ]; then
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    BACKUP_TARGET="$BACKUP_DIR/config.ini.$TIMESTAMP"
    cp "$CONFIG_TARGET" "$BACKUP_TARGET"
    chmod 600 "$BACKUP_TARGET"
    echo "Backed up config.ini to $BACKUP_TARGET"
fi

if [ -L "$SERVICE_LINK" ]; then
    rm -f "$SERVICE_LINK"
fi

if [ -d "$ES_ESS_DIR" ]; then
    rm -r "$ES_ESS_DIR"
fi

if [ -f "$RC_LOCAL" ]; then
    TEMP_LOCAL="${RC_LOCAL}.$$"
    grep -vxF '/data/es-ESS/install.sh' "$RC_LOCAL" > "$TEMP_LOCAL" || true
    mv "$TEMP_LOCAL" "$RC_LOCAL"
    chmod 755 "$RC_LOCAL"
fi
