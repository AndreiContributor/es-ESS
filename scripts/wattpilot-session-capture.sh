#!/bin/sh

# Thin launcher for the persistent, read-only Python D-Bus capture. Keeping the
# shell entry point preserves the documented Venus OS / GX invocation.

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    echo "ERROR: neither python nor python3 is available" >&2
    exit 2
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/wattpilot-session-capture.py" "$@"
