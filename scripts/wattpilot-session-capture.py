#!/usr/bin/env python3
"""Read-only long-running Wattpilot charging-session capture.

The process keeps one D-Bus connection and cached read methods for its entire
run. It writes private diagnostic evidence outside the repository and never
writes D-Bus, MQTT, Wattpilot, configuration, or service state.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import re
import signal
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, TextIO


DEFAULT_DURATION_SECONDS = 6 * 60 * 60
DEFAULT_SAMPLE_SECONDS = 10.0
DEFAULT_LOG_FILE = "/data/log/es-ESS/current.log"
DEFAULT_OUTPUT_ROOT = "/data/es-ESS-private-diagnostics"
DEFAULT_EV_SERVICE = "com.victronenergy.evcharger.esESS_FroniusWattpilot"
DEFAULT_SYSTEM_SERVICE = "com.victronenergy.system"
BUS_ITEM_INTERFACE = "com.victronenergy.BusItem"
CHARGING_POWER_THRESHOLD_W = 100.0
PROGRESS_INTERVAL_SECONDS = 5 * 60

EV_FIELDS = (
    ("connected", "/Connected"),
    ("mode", "/ModeLiteral"),
    ("control_state", "/ControlStateLiteral"),
    ("phase_mode", "/PhaseModeLiteral"),
    ("status", "/StatusLiteral"),
    ("target_total_a", "/SetCurrent"),
    ("measured_total_a", "/Current"),
    ("pv_allowance_w", "/PvAllowance"),
    ("ev_power_w", "/Ac/Power"),
    ("ev_l1_power_w", "/Ac/L1/Power"),
    ("ev_l2_power_w", "/Ac/L2/Power"),
    ("ev_l3_power_w", "/Ac/L3/Power"),
    ("ev_l1_current_a", "/Ac/L1/Current"),
    ("ev_l2_current_a", "/Ac/L2/Current"),
    ("ev_l3_current_a", "/Ac/L3/Current"),
    ("ev_l1_voltage_v", "/Ac/L1/Voltage"),
    ("ev_l2_voltage_v", "/Ac/L2/Voltage"),
    ("ev_l3_voltage_v", "/Ac/L3/Voltage"),
    ("telemetry_healthy", "/TelemetryHealthy"),
    ("command_authority_ok", "/CommandAuthorityOk"),
    ("site_current_source", "/SiteCurrentSource"),
    ("site_source_connected", "/SiteCurrentSourceConnected"),
    ("site_source_status", "/SiteCurrentSourceStatus"),
    ("site_source_error", "/SiteCurrentSourceError"),
    ("site_source_last_sample_age_s", "/SiteCurrentSourceLastSampleAge"),
    ("charger_one_phase_mapping", "/Charger1PhaseMapping"),
    ("selected_site_l1_current_a", "/SiteCurrentL1"),
    ("selected_site_l2_current_a", "/SiteCurrentL2"),
    ("selected_site_l3_current_a", "/SiteCurrentL3"),
    ("selected_site_l1_age_s", "/SiteCurrentAgeL1"),
    ("selected_site_l2_age_s", "/SiteCurrentAgeL2"),
    ("selected_site_l3_age_s", "/SiteCurrentAgeL3"),
    ("selected_site_l1_headroom_a", "/SiteHeadroomL1"),
    ("selected_site_l2_headroom_a", "/SiteHeadroomL2"),
    ("selected_site_l3_headroom_a", "/SiteHeadroomL3"),
    ("site_allowed_current_a", "/SiteAllowedCurrent"),
    ("site_limiting_phase", "/SiteLimitingPhase"),
    ("site_current_telemetry_healthy", "/SiteCurrentTelemetryHealthy"),
    ("site_guard", "/SiteCurrentGuardBlocked"),
    ("site_guard_reason", "/SiteCurrentGuardReason"),
    ("site_current_recovery_elapsed_s", "/SiteCurrentRecoveryElapsed"),
    ("grid_guard", "/GridImportGuardActive"),
    ("battery_assist", "/BatteryAssistActive"),
    ("session_energy_kwh", "/Session/Energy"),
    ("session_time_s", "/Session/Time"),
)

SYSTEM_FIELDS = (
    ("venus_consumption_l1_power_w", "/Ac/Consumption/L1/Power"),
    ("venus_consumption_l2_power_w", "/Ac/Consumption/L2/Power"),
    ("venus_consumption_l3_power_w", "/Ac/Consumption/L3/Power"),
    ("venus_consumption_l1_current_a", "/Ac/Consumption/L1/Current"),
    ("venus_consumption_l2_current_a", "/Ac/Consumption/L2/Current"),
    ("venus_consumption_l3_current_a", "/Ac/Consumption/L3/Current"),
    ("grid_l1_power_w", "/Ac/Grid/L1/Power"),
    ("grid_l2_power_w", "/Ac/Grid/L2/Power"),
    ("grid_l3_power_w", "/Ac/Grid/L3/Power"),
)

CSV_FIELDS = (
    "epoch",
    "timestamp",
    "read_seconds",
    *(name for name, _path in EV_FIELDS),
    *(name for name, _path in SYSTEM_FIELDS),
)

LOG_PATTERNS = {
    "current_adjustments": re.compile(
        r"Adjusting charge current to|"
        r"Reducing charge current from continuation PV|"
        r"current EV setpoint\. Reducing to \d+A"
    ),
    "start_actions": re.compile(r"Starting to charge after"),
    "frc_transport_markers": re.compile(r"Start/Stop to send: frc="),
    "phase_up_actions": re.compile(r"Switching to 3-phase from PV surplus"),
    "phase_down_actions": re.compile(r"Switching to 1-phase"),
    "stop_actions": re.compile(
        r"STOP send!|Stopping (?:Auto/Eco |Eco |EV )?charging"
    ),
    "guarded_current_noops": re.compile(
        r"current setpoint already confirmed; accepting guarded no-op"
    ),
    "blocked_commands": re.compile(r"Blocked Wattpilot setValue"),
    "authentication_events": re.compile(r"Authentication successful"),
    "disconnect_events": re.compile(
        r"Wattpilot disconnected|WebSocket worker did not stop"
    ),
    "site_source_failures": re.compile(
        r"Wattpilot site-current source failure:"
    ),
    "site_source_recoveries": re.compile(
        r"Wattpilot site-current source recovered:"
    ),
    "site_current_safety_stops": re.compile(
        r"Site-current telemetry is missing.*Stopping Auto/Eco charging"
    ),
    "site_poll_skips": re.compile(
        r"Thread pollSiteCurrentSource .*Future not done, skipping"
    ),
    "phase_confirmations": re.compile(
        r"Wattpilot phase telemetry confirmed [13]-phase charging"
    ),
    "phase_confirmation_failures": re.compile(
        r"(?:3-phase switch was not confirmed by Wattpilot telemetry|"
        r"1-phase switch was not confirmed by Wattpilot telemetry)"
    ),
    "session_summaries": re.compile(
        r"Wattpilot session statistics: .*\"event\":\"connection_summary\""
    ),
}

LOG_TIMESTAMP_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)"
)
ADJUSTMENT_TARGET_RE = re.compile(
    r"Adjusting charge current to (?P<amps>\d+)A"
)


def finite_number(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def normalise_dbus_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    numeric = finite_number(value)
    if numeric is not None:
        return numeric
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def is_one(value: Any) -> bool:
    return finite_number(value) == 1.0


def is_charging(sample: dict[str, Any]) -> bool:
    power = finite_number(sample.get("ev_power_w"))
    return power is not None and power > CHARGING_POWER_THRESHOLD_W


def local_timestamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).astimezone().isoformat(
        timespec="milliseconds"
    )


class DbusReader:
    """Cache read-only GetValue methods on one persistent D-Bus connection."""

    def __init__(self, bus: Any):
        self.bus = bus
        self._methods: dict[tuple[str, str], Callable[[], Any]] = {}
        self.failures: Counter[tuple[str, str]] = Counter()

    def _get_method(self, service: str, path: str) -> Callable[[], Any]:
        proxy = self.bus.get_object(service, path)
        return proxy.get_dbus_method("GetValue", BUS_ITEM_INTERFACE)

    def get(self, service: str, path: str) -> Any:
        key = (service, path)
        try:
            method = self._methods.get(key)
            if method is None:
                method = self._get_method(service, path)
                self._methods[key] = method
            return normalise_dbus_value(method())
        except Exception:
            # Discard a stale proxy after a service restart. The next sample
            # resolves it again without doubling calls during this sample.
            self._methods.pop(key, None)
            self.failures[key] += 1
            return None


class LogFollower:
    """Copy only newly appended log records and follow file replacement."""

    def __init__(self, source: Path, destination: Path):
        self.source = source
        self.destination = destination
        self._source_file: Optional[TextIO] = None
        self._source_identity: Optional[tuple[int, int]] = None
        self._destination_file: Optional[TextIO] = None
        self.lines_copied = 0

    @staticmethod
    def _identity(stat_result: os.stat_result) -> tuple[int, int]:
        return (int(stat_result.st_dev), int(stat_result.st_ino))

    def start(self) -> None:
        self._destination_file = self.destination.open(
            "w", encoding="utf-8", errors="replace", buffering=1
        )
        self._open_source(seek_to_end=True)

    def _open_source(self, seek_to_end: bool) -> bool:
        try:
            stat_result = self.source.stat()
            source_file = self.source.open(
                "r", encoding="utf-8", errors="replace"
            )
        except OSError:
            return False
        if seek_to_end:
            source_file.seek(0, os.SEEK_END)
        self._source_file = source_file
        self._source_identity = self._identity(stat_result)
        return True

    def _drain(self) -> int:
        if self._source_file is None or self._destination_file is None:
            return 0
        copied = 0
        for line in self._source_file:
            self._destination_file.write(line)
            copied += 1
        self.lines_copied += copied
        return copied

    def poll(self) -> int:
        copied = self._drain()
        try:
            stat_result = self.source.stat()
        except OSError:
            return copied

        identity = self._identity(stat_result)
        current_position = (
            self._source_file.tell() if self._source_file is not None else 0
        )
        replaced = self._source_identity is not None and (
            identity != self._source_identity
        )
        truncated = (
            self._source_identity == identity
            and stat_result.st_size < current_position
        )

        if self._source_file is None or replaced or truncated:
            if self._source_file is not None:
                self._source_file.close()
            self._source_file = None
            self._source_identity = None
            if self._open_source(seek_to_end=False):
                copied += self._drain()
        return copied

    def close(self) -> None:
        self.poll()
        if self._source_file is not None:
            self._source_file.close()
        if self._destination_file is not None:
            self._destination_file.flush()
            self._destination_file.close()


class TransitionTracker:
    """Derive observed transitions without treating the first sample as one."""

    def __init__(self, emit: Callable[[float, str, str], None]):
        self.emit = emit
        self.previous: Optional[dict[str, Any]] = None
        self.last_stable_phase: Optional[str] = None
        self.counts: Counter[str] = Counter()

    def _emit(self, epoch: float, event: str, detail: str) -> None:
        self.counts[event] += 1
        self.emit(epoch, event, detail)

    def update(self, sample: dict[str, Any]) -> None:
        epoch = float(sample["epoch"])
        phase = sample.get("phase_mode")
        if self.previous is None:
            if is_charging(sample) and phase in ("1 phase", "3 phases"):
                self.last_stable_phase = str(phase)
            self.previous = sample
            self._emit(
                epoch,
                "CAPTURE_BASELINE",
                "charging={0} phase={1} target_total_a={2} "
                "site_source={3} one_phase_mapping={4}".format(
                    int(is_charging(sample)),
                    phase,
                    sample.get("target_total_a"),
                    sample.get("site_current_source"),
                    sample.get("charger_one_phase_mapping"),
                ),
            )
            return

        previous = self.previous
        comparisons = (
            ("connected", "CONNECTION_CHANGE"),
            ("control_state", "CONTROL_STATE_CHANGE"),
            ("phase_mode", "PHASE_STATE_CHANGE"),
            ("target_total_a", "CURRENT_TARGET_CHANGE"),
            ("telemetry_healthy", "TELEMETRY_HEALTH_CHANGE"),
            ("command_authority_ok", "COMMAND_AUTHORITY_CHANGE"),
            ("site_source_connected", "SITE_SOURCE_CONNECTION_CHANGE"),
            ("site_source_status", "SITE_SOURCE_STATUS_CHANGE"),
            (
                "site_current_telemetry_healthy",
                "SITE_CURRENT_HEALTH_CHANGE",
            ),
            ("site_limiting_phase", "SITE_LIMITING_PHASE_CHANGE"),
            ("site_guard", "SITE_GUARD_CHANGE"),
            ("site_guard_reason", "SITE_GUARD_REASON_CHANGE"),
            ("grid_guard", "GRID_GUARD_CHANGE"),
            ("battery_assist", "BATTERY_ASSIST_CHANGE"),
        )
        for field, event in comparisons:
            before = previous.get(field)
            after = sample.get(field)
            if before != after:
                self._emit(epoch, event, f"{before} -> {after}")

        was_charging = is_charging(previous)
        charging = is_charging(sample)
        if not was_charging and charging:
            self._emit(
                epoch,
                "MEASURED_CHARGING_START",
                "power={0}W phase={1} target_total_a={2}".format(
                    sample.get("ev_power_w"),
                    phase,
                    sample.get("target_total_a"),
                ),
            )
        elif was_charging and not charging:
            self._emit(
                epoch,
                "MEASURED_CHARGING_STOP",
                "power={0}W state={1}".format(
                    sample.get("ev_power_w"), sample.get("control_state")
                ),
            )

        if not charging:
            self.last_stable_phase = None
        elif phase in ("1 phase", "3 phases"):
            stable_phase = str(phase)
            if self.last_stable_phase and stable_phase != self.last_stable_phase:
                event = (
                    "PHASE_UP_CONFIRMED"
                    if self.last_stable_phase == "1 phase"
                    else "PHASE_DOWN_CONFIRMED"
                )
                self._emit(
                    epoch,
                    event,
                    f"{self.last_stable_phase} -> {stable_phase}",
                )
            self.last_stable_phase = stable_phase

        self.previous = sample


def numeric_stats(
    samples: Iterable[dict[str, Any]], field: str
) -> Optional[tuple[float, float, float]]:
    values = [
        numeric
        for sample in samples
        if (numeric := finite_number(sample.get(field))) is not None
    ]
    if not values:
        return None
    return min(values), sum(values) / len(values), max(values)


def observed_values(samples: Iterable[dict[str, Any]], field: str) -> list[str]:
    """Return unique non-empty values in first-observed order."""
    result: list[str] = []
    for sample in samples:
        value = sample.get(field)
        if value is None or value == "":
            continue
        rendered = str(value)
        if rendered not in result:
            result.append(rendered)
    return result


def format_observed(samples: Iterable[dict[str, Any]], field: str) -> str:
    values = observed_values(samples, field)
    return " -> ".join(values) if values else "unavailable"


def analyze_samples(
    samples: list[dict[str, Any]],
    requested_interval: float,
    max_gap_seconds: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "sample_count": len(samples),
        "charging_sample_count": 0,
        "capture_span_seconds": 0.0,
        "charging_seconds": 0.0,
        "energy_kwh": 0.0,
        "one_phase_seconds": 0.0,
        "three_phase_seconds": 0.0,
        "skipped_gap_count": 0,
        "skipped_gap_seconds": 0.0,
        "late_interval_count": 0,
        "mean_interval_seconds": 0.0,
        "max_interval_seconds": 0.0,
        "mean_read_seconds": 0.0,
        "max_read_seconds": 0.0,
        "safety_sample_counts": Counter(),
        "safety_seconds": defaultdict(float),
        "stats": {},
    }
    if not samples:
        return result

    charging_samples = [sample for sample in samples if is_charging(sample)]
    result["charging_sample_count"] = len(charging_samples)
    result["capture_span_seconds"] = max(
        0.0, float(samples[-1]["epoch"]) - float(samples[0]["epoch"])
    )

    read_seconds = [
        value
        for sample in samples
        if (value := finite_number(sample.get("read_seconds"))) is not None
    ]
    if read_seconds:
        result["mean_read_seconds"] = statistics.fmean(read_seconds)
        result["max_read_seconds"] = max(read_seconds)

    stat_fields = (
        "ev_power_w",
        "ev_l1_power_w",
        "ev_l2_power_w",
        "ev_l3_power_w",
        "ev_l1_current_a",
        "ev_l2_current_a",
        "ev_l3_current_a",
        "selected_site_l1_current_a",
        "selected_site_l2_current_a",
        "selected_site_l3_current_a",
        "site_source_last_sample_age_s",
        "selected_site_l1_age_s",
        "selected_site_l2_age_s",
        "selected_site_l3_age_s",
        "selected_site_l1_headroom_a",
        "selected_site_l2_headroom_a",
        "selected_site_l3_headroom_a",
        "site_allowed_current_a",
        "venus_consumption_l1_power_w",
        "venus_consumption_l2_power_w",
        "venus_consumption_l3_power_w",
    )
    result["stats"] = {
        field: numeric_stats(charging_samples, field) for field in stat_fields
    }

    safety_conditions = {
        "unhealthy_telemetry": lambda sample: not is_one(
            sample.get("telemetry_healthy")
        ),
        "missing_authority": lambda sample: not is_one(
            sample.get("command_authority_ok")
        ),
        "site_source_disconnected": lambda sample: not is_one(
            sample.get("site_source_connected")
        ),
        "unhealthy_site_current": lambda sample: not is_one(
            sample.get("site_current_telemetry_healthy")
        ),
        "site_guard": lambda sample: is_one(sample.get("site_guard")),
        "grid_guard": lambda sample: is_one(sample.get("grid_guard")),
        "battery_assist": lambda sample: is_one(sample.get("battery_assist")),
    }
    for sample in charging_samples:
        for name, condition in safety_conditions.items():
            if condition(sample):
                result["safety_sample_counts"][name] += 1

    intervals: list[float] = []
    for previous, current in zip(samples, samples[1:]):
        delta = float(current["epoch"]) - float(previous["epoch"])
        if delta <= 0:
            continue
        intervals.append(delta)
        if delta > requested_interval * 1.5:
            result["late_interval_count"] += 1
        if delta > max_gap_seconds:
            result["skipped_gap_count"] += 1
            result["skipped_gap_seconds"] += delta
            continue

        previous_power = max(0.0, finite_number(previous.get("ev_power_w")) or 0.0)
        current_power = max(0.0, finite_number(current.get("ev_power_w")) or 0.0)
        previous_active = previous_power > CHARGING_POWER_THRESHOLD_W
        current_active = current_power > CHARGING_POWER_THRESHOLD_W
        result["energy_kwh"] += (
            (previous_power + current_power) * 0.5 * delta / 3_600_000.0
        )
        result["charging_seconds"] += (
            (int(previous_active) + int(current_active)) * 0.5 * delta
        )

        for endpoint, active in (
            (previous, previous_active),
            (current, current_active),
        ):
            if not active:
                continue
            phase = endpoint.get("phase_mode")
            if phase == "1 phase":
                result["one_phase_seconds"] += delta * 0.5
            elif phase == "3 phases":
                result["three_phase_seconds"] += delta * 0.5
            for name, condition in safety_conditions.items():
                if condition(endpoint):
                    result["safety_seconds"][name] += delta * 0.5

    if intervals:
        result["mean_interval_seconds"] = statistics.fmean(intervals)
        result["max_interval_seconds"] = max(intervals)
    return result


def parse_log_timestamp(line: str) -> Optional[float]:
    match = LOG_TIMESTAMP_RE.match(line)
    if not match:
        return None
    try:
        return datetime.strptime(
            match.group("timestamp"), "%Y-%m-%d %H:%M:%S,%f"
        ).timestamp()
    except ValueError:
        return None


def analyze_log(path: Path, duration_seconds: float) -> dict[str, Any]:
    matches: dict[str, list[float]] = defaultdict(list)
    adjustment_targets: list[int] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            timestamp = parse_log_timestamp(line)
            for name, pattern in LOG_PATTERNS.items():
                if pattern.search(line):
                    matches[name].append(timestamp if timestamp is not None else math.nan)
            target_match = ADJUSTMENT_TARGET_RE.search(line)
            if target_match:
                adjustment_targets.append(int(target_match.group("amps")))

    results: dict[str, Any] = {}
    for name in LOG_PATTERNS:
        timestamps = [value for value in matches[name] if math.isfinite(value)]
        intervals = [
            current - previous
            for previous, current in zip(timestamps, timestamps[1:])
            if current >= previous
        ]
        count = len(matches[name])
        results[name] = {
            "count": count,
            "rate_per_hour": (
                count * 3600.0 / duration_seconds if duration_seconds > 0 else 0.0
            ),
            "average_interval_seconds": (
                statistics.fmean(intervals) if intervals else None
            ),
        }
    results["consecutive_same_adjustment_candidates"] = sum(
        previous == current
        for previous, current in zip(
            adjustment_targets, adjustment_targets[1:]
        )
    )
    return results


def format_duration(seconds: float) -> str:
    return f"{seconds / 3600.0:.3f} h ({seconds:.1f} s)"


def format_stats(stats: Optional[tuple[float, float, float]], unit: str) -> str:
    if stats is None:
        return "unavailable"
    minimum, average, maximum = stats
    precision = 2 if unit == "A" else 0
    return (
        f"{minimum:.{precision}f} / {average:.{precision}f} / "
        f"{maximum:.{precision}f} {unit}"
    )


def command_line(name: str, evidence: dict[str, Any]) -> str:
    item = evidence[name]
    interval = item["average_interval_seconds"]
    interval_text = "n/a" if interval is None else f"{interval:.1f}s"
    return (
        f"  {name.replace('_', ' '):34s} {item['count']:5d}  "
        f"{item['rate_per_hour']:7.2f}/h  avg interval {interval_text}"
    )


def build_summary(
    samples: list[dict[str, Any]],
    metrics: dict[str, Any],
    tracker: TransitionTracker,
    log_evidence: dict[str, Any],
    reader: DbusReader,
    follower: LogFollower,
    requested_duration: float,
    actual_duration: float,
    requested_interval: float,
    max_gap_seconds: float,
    interrupted: bool,
    capture_error: Optional[str],
    output_dir: Path,
) -> str:
    stats = metrics["stats"]
    safety_counts = metrics["safety_sample_counts"]
    safety_seconds = metrics["safety_seconds"]
    lines = [
        "Wattpilot charging-session capture summary",
        f"Result: {'ERROR' if capture_error else ('INTERRUPTED' if interrupted else 'COMPLETED')}",
        f"Requested duration: {format_duration(requested_duration)}",
        f"Actual duration:    {format_duration(actual_duration)}",
        f"Requested interval: {requested_interval:.1f} s",
        f"Maximum integration gap: {max_gap_seconds:.1f} s",
        f"Samples: {metrics['sample_count']}",
        f"Mean/max sample interval: {metrics['mean_interval_seconds']:.2f} / {metrics['max_interval_seconds']:.2f} s",
        f"Mean/max D-Bus read time: {metrics['mean_read_seconds']:.3f} / {metrics['max_read_seconds']:.3f} s",
        f"Late sample intervals: {metrics['late_interval_count']}",
        f"Skipped long gaps: {metrics['skipped_gap_count']} covering {metrics['skipped_gap_seconds']:.1f} s",
    ]
    if capture_error:
        lines.append(f"Capture error: {capture_error}")

    lines.extend(
        [
            "",
            "Selected site-current safety source",
            f"  Source observed:          {format_observed(samples, 'site_current_source')}",
            f"  Source status observed:   {format_observed(samples, 'site_source_status')}",
            "  Source errors observed:   "
            + (
                " | ".join(observed_values(samples, "site_source_error"))
                or "none"
            ),
            f"  One-phase mapping:        {format_observed(samples, 'charger_one_phase_mapping')}",
            f"  Limiting phase observed:  {format_observed(samples, 'site_limiting_phase')}",
            "  Selected-source L1 current min/avg/max: "
            f"{format_stats(stats.get('selected_site_l1_current_a'), 'A')}",
            "  Selected-source L2 current min/avg/max: "
            f"{format_stats(stats.get('selected_site_l2_current_a'), 'A')}",
            "  Selected-source L3 current min/avg/max: "
            f"{format_stats(stats.get('selected_site_l3_current_a'), 'A')}",
            "  Selected-source L1 age min/avg/max:     "
            f"{format_stats(stats.get('selected_site_l1_age_s'), 's')}",
            "  Selected-source L2 age min/avg/max:     "
            f"{format_stats(stats.get('selected_site_l2_age_s'), 's')}",
            "  Selected-source L3 age min/avg/max:     "
            f"{format_stats(stats.get('selected_site_l3_age_s'), 's')}",
            "  Selected-source sample age min/avg/max: "
            f"{format_stats(stats.get('site_source_last_sample_age_s'), 's')}",
            "  Site headroom L1 min/avg/max:           "
            f"{format_stats(stats.get('selected_site_l1_headroom_a'), 'A')}",
            "  Site headroom L2 min/avg/max:           "
            f"{format_stats(stats.get('selected_site_l2_headroom_a'), 'A')}",
            "  Site headroom L3 min/avg/max:           "
            f"{format_stats(stats.get('selected_site_l3_headroom_a'), 'A')}",
            "  Allowed EV current min/avg/max:         "
            f"{format_stats(stats.get('site_allowed_current_a'), 'A')}",
            "",
            "Measured transitions",
            f"  Charging starts:       {tracker.counts['MEASURED_CHARGING_START']}",
            f"  Charging stops:        {tracker.counts['MEASURED_CHARGING_STOP']}",
            f"  Confirmed phase-ups:   {tracker.counts['PHASE_UP_CONFIRMED']}",
            f"  Confirmed phase-downs: {tracker.counts['PHASE_DOWN_CONFIRMED']}",
            f"  Current-target changes:{tracker.counts['CURRENT_TARGET_CHANGE']:5d}",
            "",
            "Controller command evidence",
        ]
    )
    for name in LOG_PATTERNS:
        lines.append(command_line(name, log_evidence))
    lines.append(
        "  consecutive same-target adjustment candidates "
        f"{log_evidence['consecutive_same_adjustment_candidates']}"
    )

    lines.extend(
        [
            "",
            "Charging measurements (actual timestamp integration)",
            f"  Charging samples:       {metrics['charging_sample_count']}",
            f"  Approx. charging time:  {format_duration(metrics['charging_seconds'])}",
            f"  Approx. energy:         {metrics['energy_kwh']:.3f} kWh",
            f"  One-phase duration:     {format_duration(metrics['one_phase_seconds'])}",
            f"  Three-phase duration:   {format_duration(metrics['three_phase_seconds'])}",
            f"  EV power min/avg/max:   {format_stats(stats.get('ev_power_w'), 'W')}",
            f"  EV L1 power min/avg/max:{format_stats(stats.get('ev_l1_power_w'), 'W')}",
            f"  EV L2 power min/avg/max:{format_stats(stats.get('ev_l2_power_w'), 'W')}",
            f"  EV L3 power min/avg/max:{format_stats(stats.get('ev_l3_power_w'), 'W')}",
            f"  EV L1 current min/avg/max: {format_stats(stats.get('ev_l1_current_a'), 'A')}",
            f"  EV L2 current min/avg/max: {format_stats(stats.get('ev_l2_current_a'), 'A')}",
            f"  EV L3 current min/avg/max: {format_stats(stats.get('ev_l3_current_a'), 'A')}",
            "  Venus consumption L1 power min/avg/max: "
            f"{format_stats(stats.get('venus_consumption_l1_power_w'), 'W')}",
            "  Venus consumption L2 power min/avg/max: "
            f"{format_stats(stats.get('venus_consumption_l2_power_w'), 'W')}",
            "  Venus consumption L3 power min/avg/max: "
            f"{format_stats(stats.get('venus_consumption_l3_power_w'), 'W')}",
            "",
            "Sampled safety evidence while charging",
        ]
    )
    for name in (
        "unhealthy_telemetry",
        "missing_authority",
        "site_source_disconnected",
        "unhealthy_site_current",
        "site_guard",
        "grid_guard",
        "battery_assist",
    ):
        lines.append(
            f"  {name.replace('_', ' '):24s} "
            f"samples={safety_counts[name]:4d}  "
            f"estimated duration={safety_seconds[name]:.1f}s"
        )

    lines.extend(
        [
            "",
            f"Copied es-ESS log lines: {follower.lines_copied}",
            f"D-Bus read failures: {sum(reader.failures.values())}",
        ]
    )
    for (service, path), count in reader.failures.most_common(10):
        lines.append(f"  {count:5d} {service} {path}")

    lines.extend(
        [
            "",
            "Important limitations",
            "  Command counts are controller/D-Bus/log evidence, not an encrypted WebSocket packet capture.",
            "  APP_DEBUG is required for frc transport markers and guarded current no-op messages.",
            "  Consecutive same-target entries are review candidates, not proof of an unsafe duplicate command.",
            "  Intervals longer than the maximum gap are excluded instead of being extrapolated.",
            "",
            "Files",
            f"  Samples:     {output_dir / 'samples.tsv'}",
            f"  Transitions: {output_dir / 'transitions.tsv'}",
            f"  New log:     {output_dir / 'es-ESS-events.log'}",
        ]
    )
    return "\n".join(lines) + "\n"


def open_system_bus() -> Any:
    try:
        import dbus  # type: ignore
    except ImportError as error:
        raise RuntimeError("Python dbus bindings are unavailable") from error
    return dbus.SystemBus()


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"{name} must be numeric; got {raw!r}"
        ) from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture a read-only Wattpilot charging session with one persistent "
            "D-Bus process."
        )
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=env_float("DURATION_SECONDS", DEFAULT_DURATION_SECONDS),
        help="capture duration in seconds (default: 21600)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=env_float("SAMPLE_SECONDS", DEFAULT_SAMPLE_SECONDS),
        help="sample interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--max-gap",
        type=float,
        default=None,
        help="largest interval integrated into energy/durations",
    )
    parser.add_argument(
        "--output-root",
        default=os.environ.get("OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT),
    )
    parser.add_argument("--output-dir", default=os.environ.get("OUTPUT_DIR"))
    parser.add_argument(
        "--log-file", default=os.environ.get("LOG_FILE", DEFAULT_LOG_FILE)
    )
    parser.add_argument(
        "--ev-service",
        default=os.environ.get("WATTPILOT_DBUS_SERVICE", DEFAULT_EV_SERVICE),
    )
    parser.add_argument(
        "--system-service",
        default=os.environ.get("SYSTEM_DBUS_SERVICE", DEFAULT_SYSTEM_SERVICE),
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if not math.isfinite(args.duration) or args.duration <= 0:
        raise ValueError("duration must be a positive finite number")
    if not math.isfinite(args.interval) or args.interval <= 0:
        raise ValueError("interval must be a positive finite number")
    if args.max_gap is not None and (
        not math.isfinite(args.max_gap) or args.max_gap <= 0
    ):
        raise ValueError("max-gap must be a positive finite number")
    log_path = Path(args.log_file)
    if not log_path.is_file():
        raise ValueError(f"cannot read log file: {log_path}")


def run_capture(args: argparse.Namespace, bus: Any = None) -> int:
    validate_args(args)
    os.umask(0o077)
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else Path(args.output_root)
        / ("wattpilot-session-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        output_dir.chmod(0o700)
    except OSError:
        pass

    samples_path = output_dir / "samples.tsv"
    transitions_path = output_dir / "transitions.tsv"
    log_capture_path = output_dir / "es-ESS-events.log"
    summary_path = output_dir / "summary.txt"
    progress_path = output_dir / "progress.log"
    (output_dir / "pid").write_text(f"{os.getpid()}\n", encoding="ascii")

    progress_handle = progress_path.open(
        "w", encoding="utf-8", buffering=1
    )

    def progress(message: str) -> None:
        line = f"{local_timestamp(time.time())} {message}"
        print(line, flush=True)
        progress_handle.write(line + "\n")

    reader = DbusReader(bus if bus is not None else open_system_bus())
    follower = LogFollower(Path(args.log_file), log_capture_path)
    follower.start()
    stop_event = threading.Event()
    interrupted = False

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal interrupted
        interrupted = True
        stop_event.set()

    previous_handlers: dict[int, Any] = {}
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signal_number] = signal.signal(
            signal_number, request_stop
        )

    samples: list[dict[str, Any]] = []
    capture_error: Optional[str] = None
    max_gap_seconds = args.max_gap or max(args.interval * 3.0, args.interval + 5.0)
    start_monotonic = time.monotonic()
    next_deadline = start_monotonic
    last_progress_elapsed = -PROGRESS_INTERVAL_SECONDS

    with samples_path.open(
        "w", encoding="utf-8", newline="", buffering=1
    ) as samples_handle, transitions_path.open(
        "w", encoding="utf-8", newline="", buffering=1
    ) as transitions_handle:
        sample_writer = csv.DictWriter(
            samples_handle, fieldnames=CSV_FIELDS, delimiter="\t"
        )
        transition_writer = csv.writer(transitions_handle, delimiter="\t")
        sample_writer.writeheader()
        transition_writer.writerow(("epoch", "timestamp", "event", "detail"))

        def emit_transition(epoch: float, event: str, detail: str) -> None:
            transition_writer.writerow(
                (f"{epoch:.3f}", local_timestamp(epoch), event, detail)
            )
            transitions_handle.flush()

        tracker = TransitionTracker(emit_transition)
        emit_transition(
            time.time(),
            "CAPTURE_START",
            f"duration={args.duration:.1f}s sample={args.interval:.1f}s",
        )
        progress(
            f"Capture started; output={output_dir} "
            f"duration={args.duration:.1f}s sample={args.interval:.1f}s"
        )

        try:
            while (
                time.monotonic() - start_monotonic < args.duration
                and not stop_event.is_set()
            ):
                follower.poll()
                read_started_epoch = time.time()
                read_started_monotonic = time.monotonic()
                values: dict[str, Any] = {}
                for name, path in EV_FIELDS:
                    values[name] = reader.get(args.ev_service, path)
                for name, path in SYSTEM_FIELDS:
                    values[name] = reader.get(args.system_service, path)
                read_finished_epoch = time.time()
                read_seconds = time.monotonic() - read_started_monotonic
                sample_epoch = (read_started_epoch + read_finished_epoch) * 0.5
                sample = {
                    "epoch": sample_epoch,
                    "timestamp": local_timestamp(sample_epoch),
                    "read_seconds": read_seconds,
                    **values,
                }
                samples.append(sample)
                sample_writer.writerow(
                    {
                        name: (
                            "NA" if sample.get(name) is None else sample.get(name)
                        )
                        for name in CSV_FIELDS
                    }
                )
                samples_handle.flush()
                tracker.update(sample)
                follower.poll()

                elapsed = time.monotonic() - start_monotonic
                if elapsed - last_progress_elapsed >= PROGRESS_INTERVAL_SECONDS:
                    progress(
                        "elapsed={0:.0f}s read={1:.3f}s power={2}W "
                        "phase={3} target_total={4}A allowance={5}W "
                        "site_source={6} site_status={7} "
                        "site_L1/L2/L3={8}/{9}/{10}A".format(
                            elapsed,
                            read_seconds,
                            sample.get("ev_power_w"),
                            sample.get("phase_mode"),
                            sample.get("target_total_a"),
                            sample.get("pv_allowance_w"),
                            sample.get("site_current_source"),
                            sample.get("site_source_status"),
                            sample.get("selected_site_l1_current_a"),
                            sample.get("selected_site_l2_current_a"),
                            sample.get("selected_site_l3_current_a"),
                        )
                    )
                    last_progress_elapsed = elapsed

                next_deadline += args.interval
                now = time.monotonic()
                if next_deadline <= now:
                    missed = math.floor((now - next_deadline) / args.interval) + 1
                    next_deadline += missed * args.interval
                stop_event.wait(max(0.0, next_deadline - time.monotonic()))
        except Exception as error:
            capture_error = f"{type(error).__name__}: {error}"
            progress(f"ERROR: {capture_error}")
        finally:
            follower.close()
            actual_duration = time.monotonic() - start_monotonic
            emit_transition(
                time.time(),
                "CAPTURE_END",
                f"actual_duration={actual_duration:.3f}s",
            )

    for signal_number, previous_handler in previous_handlers.items():
        signal.signal(signal_number, previous_handler)

    metrics = analyze_samples(
        samples, args.interval, max_gap_seconds
    )
    log_evidence = analyze_log(log_capture_path, actual_duration)
    summary = build_summary(
        samples,
        metrics,
        tracker,
        log_evidence,
        reader,
        follower,
        args.duration,
        actual_duration,
        args.interval,
        max_gap_seconds,
        interrupted,
        capture_error,
        output_dir,
    )
    summary_path.write_text(summary, encoding="utf-8")
    progress(f"Capture finished; summary={summary_path}")
    progress_handle.close()
    print(summary, end="")

    if capture_error:
        return 2
    if interrupted:
        return 130
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return run_capture(args)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
