#!/usr/bin/env python3
"""Capture redacted Wattpilot setting changes without issuing commands.

The utility connects to the Wattpilot transport, waits for a complete status
snapshot, asks the operator to change exactly one Solar.wattpilot app setting,
requests another full status snapshot, and prints only the changed properties.

It deliberately installs a command guard that rejects every ``setValue``
request. Authentication and ``requestFullStatus`` remain available because
they are read-only protocol operations.
"""

import argparse
import configparser
import hashlib
import json
import logging
import math
import sys
import threading
from pathlib import Path


VALIDATED_FIRMWARE = "42.5"
DEFAULT_CONFIG_PATH = "/data/es-ESS/config.ini"
DEFAULT_TIMEOUT_SECONDS = 30.0

SENSITIVE_KEY_PARTS = (
    "access",
    "api",
    "cak",
    "credential",
    "host",
    "key",
    "mac",
    "name",
    "password",
    "secret",
    "serial",
    "ssid",
    "token",
    "user",
)

SAFE_TEXT_VALUES = {
    "automatic",
    "default",
    "disabled",
    "eco",
    "enabled",
    "false",
    "manual",
    "off",
    "on",
    "standard",
    "true",
}


class CaptureError(RuntimeError):
    """Raised when a safe, complete capture cannot be produced."""


def _canonical_value(value):
    """Return a deterministic JSON-compatible representation for comparison."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return {"non_finite_float": str(value)}
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if hasattr(value, "__dict__"):
        return _canonical_value(vars(value))
    return {
        "unsupported_type": type(value).__name__,
        "fingerprint": _fingerprint(repr(value)),
    }


def snapshot_properties(properties):
    """Copy Wattpilot properties into a stable comparison snapshot."""
    return {
        str(key): _canonical_value(value)
        for key, value in sorted(properties.items(), key=lambda pair: str(pair[0]))
    }


def _fingerprint(value):
    payload = value if isinstance(value, str) else json.dumps(
        value, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _is_sensitive_key(key):
    normalized = str(key).lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def safe_report_value(key, value):
    """Return useful scalar evidence without exposing credentials or strings."""
    if _is_sensitive_key(key):
        return {
            "redacted": True,
            "type": type(value).__name__,
            "fingerprint": _fingerprint(value),
        }

    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in SAFE_TEXT_VALUES:
            return value
        return {
            "redacted": True,
            "type": "str",
            "length": len(value),
            "fingerprint": _fingerprint(value),
        }

    return {
        "redacted": True,
        "type": type(value).__name__,
        "fingerprint": _fingerprint(value),
    }


def diff_snapshots(before, after):
    """Return added, removed, and changed properties with safe values only."""
    changes = []
    for key in sorted(set(before) | set(after)):
        if key not in before:
            changes.append(
                {
                    "key": key,
                    "change": "added",
                    "after": safe_report_value(key, after[key]),
                }
            )
        elif key not in after:
            changes.append(
                {
                    "key": key,
                    "change": "removed",
                    "before": safe_report_value(key, before[key]),
                }
            )
        elif before[key] != after[key]:
            changes.append(
                {
                    "key": key,
                    "change": "changed",
                    "before": safe_report_value(key, before[key]),
                    "after": safe_report_value(key, after[key]),
                }
            )
    return changes


def validate_capture_state(client):
    """Fail closed unless firmware and vehicle state are safe for capture."""
    firmware = getattr(client, "firmware", None)
    if str(firmware) != VALIDATED_FIRMWARE:
        raise CaptureError(
            "Wattpilot firmware must be {0}; received {1}.".format(
                VALIDATED_FIRMWARE,
                firmware if firmware is not None else "<unavailable>",
            )
        )

    if not bool(getattr(client, "carStateReady", False)):
        raise CaptureError("Wattpilot vehicle state is not ready.")
    if bool(getattr(client, "carConnected", False)):
        raise CaptureError(
            "Disconnect the vehicle before capturing app-setting changes."
        )


def capture_setting_change(
    client,
    full_status_event,
    label,
    confirm_change,
    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
):
    """Capture one operator-controlled setting change from an initialized client."""
    validate_capture_state(client)
    before = snapshot_properties(client.allProps)

    confirm_change()

    full_status_event.clear()
    client.request_full_status()
    if not full_status_event.wait(timeout_seconds):
        raise CaptureError(
            "Timed out waiting for the post-change full Wattpilot status."
        )

    validate_capture_state(client)
    after = snapshot_properties(client.allProps)
    changes = diff_snapshots(before, after)
    return {
        "schema": 1,
        "label": label,
        "firmware": str(client.firmware),
        "vehicle_connected": False,
        "command_policy": "all setValue requests blocked",
        "changed_property_count": len(changes),
        "changes": changes,
    }


def load_connection_settings(config_path):
    parser = configparser.ConfigParser(interpolation=None)
    loaded = parser.read(config_path)
    if not loaded:
        raise CaptureError("Could not read configuration: {0}".format(config_path))
    if not parser.has_section("FroniusWattpilot"):
        raise CaptureError("Configuration is missing [FroniusWattpilot].")

    host = parser.get("FroniusWattpilot", "Host", fallback="").strip()
    password = parser.get("FroniusWattpilot", "Password", fallback="")
    if not host:
        raise CaptureError("[FroniusWattpilot] Host is empty.")
    if not password:
        raise CaptureError("[FroniusWattpilot] Password is empty.")
    return host, password


def _operator_confirmation(label):
    print(
        "Baseline captured for '{0}'. Change exactly that one app setting, "
        "wait for the app to confirm it, then press Enter.".format(label),
        file=sys.stderr,
    )
    if sys.stdin.readline() == "":
        raise CaptureError("Standard input closed before operator confirmation.")


def _ensure_logging_compatibility():
    """Provide the custom levels expected by Helper outside es-ESS.py startup."""
    if not hasattr(logging, "appDebug"):
        logging.appDebug = logging.debug
    if not hasattr(logging.Logger, "appDebug"):
        logging.Logger.appDebug = logging.Logger.debug
    if not hasattr(logging, "trace"):
        logging.trace = logging.debug
    if not hasattr(logging.Logger, "trace"):
        logging.Logger.trace = logging.Logger.debug


def run_capture(config_path, label, timeout_seconds):
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    _ensure_logging_compatibility()

    # Import Globals first to preserve the application's existing Globals /
    # Helper initialization order before Wattpilot imports Helper itself.
    import Globals  # noqa: F401
    from Wattpilot import Event, Wattpilot

    host, password = load_connection_settings(config_path)
    full_status_event = threading.Event()
    client = Wattpilot(host, password)
    client.set_command_guard(lambda _name, _value: False)
    client.add_event_handler(
        Event.WP_FULL_STATUS_FINISHED,
        lambda _event, *_args: full_status_event.set(),
    )

    client.connect()
    try:
        if not full_status_event.wait(timeout_seconds):
            raise CaptureError("Timed out waiting for the initial full Wattpilot status.")
        return capture_setting_change(
            client,
            full_status_event,
            label,
            lambda: _operator_confirmation(label),
            timeout_seconds,
        )
    finally:
        client.disconnect(auto_reconnect=False)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Capture one redacted Solar.wattpilot app-setting change without "
            "issuing Wattpilot setValue commands."
        )
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Seconds to wait for each complete status response.",
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        report = run_capture(args.config, args.label, args.timeout)
    except CaptureError as ex:
        print("Capture failed: {0}".format(ex), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Capture cancelled.", file=sys.stderr)
        return 130

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
