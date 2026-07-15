#!/usr/bin/env python3
"""Read-only daily es-ESS report for production logs and optional snapshots.

The report never treats an absent log event as proof that a safety mechanism
worked. It reads configuration and logs, uses one allowlisted read-only
``dbus ... GetValue`` command for the Venus timezone, and may use additional
allowlisted ``svstat`` and D-Bus reads for a current snapshot. It never writes
D-Bus, MQTT, Wattpilot settings, configuration, or service state.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
import configparser
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional, TextIO

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:
    class ZoneInfoNotFoundError(Exception):
        pass

    def ZoneInfo(timezone_name: str):
        raise ZoneInfoNotFoundError(
            f"Python zoneinfo support is unavailable for {timezone_name}"
        )


SCHEMA_VERSION = 3
EXIT_PASS = 0
EXIT_INCOMPLETE = 1
EXIT_FAIL = 2
EXIT_INPUT_ERROR = 3

DEFAULT_LOG_FILE = "/data/log/es-ESS/current.log"
DEFAULT_CONFIG_FILE = "/data/es-ESS/config.ini"
DEFAULT_SERVICE_DIR = "/service/es-ESS"
DEFAULT_WATTPILOT_DBUS_SERVICE = (
    "com.victronenergy.evcharger.esESS_FroniusWattpilot"
)
DEFAULT_SETTINGS_DBUS_SERVICE = "com.victronenergy.settings"
VENUS_TIMEZONE_DBUS_PATH = "/Settings/System/TimeZone"
VERBOSE_LOG_LEVELS = frozenset({"APP_DEBUG", "DEBUG", "TRACE"})
FULL_DAY_BOUNDARY_TOLERANCE = timedelta(minutes=10)
HEARTBEAT_GAP_SECONDS = 180
RARE_STATUS_NAMES = {
    8: "ChargingBecauseAutomaticStopTestLadung",
    9: "ChargingBecauseAutomaticStopNotEnoughTime",
    10: "ChargingBecauseAutomaticStop",
    11: "ChargingBecauseAutomaticStopNoClock",
    13: "ChargingBecauseFallbackGoEDefault",
    14: "ChargingBecauseFallbackGoEScheduler",
}
SNAPSHOT_DBUS_PATHS = (
    "/Connected",
    "/StatusLiteral",
    "/ModeLiteral",
    "/StartStopLiteral",
    "/Ac/Power",
    "/Current",
    "/SetCurrent",
    "/PvAllowance",
    "/PhaseModeLiteral",
    "/ControlStateLiteral",
    "/BatteryAssistActive",
    "/GridImportGuardActive",
    "/TelemetryHealthy",
    "/CompatibilityOk",
    "/CompatibilityLiteral",
    "/CommandAuthorityOk",
    "/CommandAuthorityLiteral",
    "/NativePvSurplusEnabled",
    "/FlexibleTariffEnabled",
    "/ExpectedVenusOsVersion",
    "/ActualVenusOsVersion",
    "/ExpectedWattpilotFirmware",
    "/ActualWattpilotFirmware",
    "/ValidatedWattpilotAppVersion",
)
READONLY_DBUS_PAIRS = frozenset(
    (DEFAULT_WATTPILOT_DBUS_SERVICE, path) for path in SNAPSHOT_DBUS_PATHS
) | frozenset(
    {(DEFAULT_SETTINGS_DBUS_SERVICE, VENUS_TIMEZONE_DBUS_PATH)}
)
SNAPSHOT_COMMAND_TIMEOUT_SECONDS = 2
SNAPSHOT_MAX_CONSECUTIVE_TIMEOUTS = 3
PROGRESS_BAR_WIDTH = 24
PROGRESS_STAGE_COUNT = 6
LOG_PROGRESS_LINE_INTERVAL = 2000


class ProgressReporter:
    """Small stderr progress bar that never contaminates report stdout."""

    def __init__(
        self,
        enabled: bool,
        stream: Optional[TextIO] = None,
    ) -> None:
        self.enabled = enabled
        self.stream = stream or sys.stderr
        self._last_width = 0
        self._finished = False

    def update(
        self,
        stage: int,
        label: str,
        current: int = 0,
        total: int = 1,
    ) -> None:
        if not self.enabled or self._finished:
            return
        fraction = min(1.0, max(0.0, current / max(1, total)))
        overall = min(
            1.0,
            max(0.0, (stage + fraction) / PROGRESS_STAGE_COUNT),
        )
        filled = int(PROGRESS_BAR_WIDTH * overall)
        bar = "#" * filled + "-" * (PROGRESS_BAR_WIDTH - filled)
        line = f"[{bar}] {overall * 100:5.1f}% {label}"
        padding = " " * max(0, self._last_width - len(line))
        self.stream.write("\r" + line + padding)
        self.stream.flush()
        self._last_width = len(line)

    def finish(self, label: str = "Report ready") -> None:
        if not self.enabled or self._finished:
            return
        self.update(PROGRESS_STAGE_COUNT, label, 0, 1)
        self.stream.write("\n")
        self.stream.flush()
        self._finished = True

    def stop(self, label: str = "Stopped") -> None:
        if not self.enabled or self._finished:
            return
        line = f"\r[{'-' * PROGRESS_BAR_WIDTH}] {label}"
        padding = " " * max(0, self._last_width - len(line))
        self.stream.write(line + padding + "\n")
        self.stream.flush()
        self._finished = True

LOG_LINE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) "
    r"(?P<time>\d{2}:\d{2}:\d{2}),(?P<millis>\d+) "
    r"(?:\(UTC(?P<offset_sign>[+-])(?P<offset_hours>\d{1,2})"
    r"(?::(?P<offset_minutes>\d{2}))?\) )?"
    r"(?P<level>[A-Z_]+) (?P<message>.*)$"
)
ALLOWANCE_RE = re.compile(
    r"Assigned\s+(?P<watts>-?\d+(?:\.\d+)?)W\s+to\s+.*Wattpilot.*?"
    r"\s-\s(?P<state>.+?)\s+\([^\n]*Wattpilot\)"
)
ALLOCATION_INPUT_RE = re.compile(
    r"Allocation input for Wattpilot:.*?request=(?P<request>-?\d+(?:\.\d+)?)W, "
    r"minimum=(?P<minimum>-?\d+(?:\.\d+)?)W, "
    r"step=(?P<step>-?\d+(?:\.\d+)?)W, "
    r"consumption=(?P<consumption>-?\d+(?:\.\d+)?)W"
)
GRID_RE = re.compile(
    r"L1/L2/L3/Bat/Soc/Feedin is "
    r"(?P<l1>-?\d+(?:\.\d+)?)/(?P<l2>-?\d+(?:\.\d+)?)/"
    r"(?P<l3>-?\d+(?:\.\d+)?)/(?P<battery>-?\d+(?:\.\d+)?)/"
    r"(?P<soc>-?\d+(?:\.\d+)?)/(?P<feedin>-?\d+(?:\.\d+)?)"
)
CURRENT_RE = re.compile(
    r"Adjusting charge current to (?P<amps>\d+)A on (?P<phase>[13])-phase"
)
ASSIST_RE = re.compile(
    r"Battery assist active: (?P<shortfall>\d+(?:\.\d+)?)W shortfall "
    r"for (?P<elapsed>\d+(?:\.\d+)?)s"
)
GRACE_RE = re.compile(
    r"EV allowance fell below the usable minimum\. Waiting up to "
    r"(?P<seconds>\d+)s"
)
PHASE_UP_WAIT_RE = re.compile(
    r"waiting for stable phase-up allowance "
    r"\((?P<stable>\d+(?:\.\d+)?)/(?P<required>\d+)s\)",
    re.IGNORECASE,
)
PHASE_CONFIRM_RE = re.compile(
    r"Wattpilot phase telemetry confirmed (?P<phase>[13])-phase charging"
)
START_RE = re.compile(
    r"Starting to charge after (?P<stable>\d+(?:\.\d+)?)s of continuous PV allowance"
)
MODEL_CHARGING_RE = re.compile(
    r"Wattpilot Modelstatus:\s+(?:WattpilotModelStatus\.)?Charging", re.IGNORECASE
)
RARE_ENTER_RE = re.compile(
    r"Wattpilot special charging model status entered: "
    r"model_status=(?P<status>8|9|10|11|13|14) "
    r"name=(?P<name>\S+) mode=(?P<mode>\S+) "
    r"selected_state=(?P<state>\S+) .*?"
    r"command_authority_ok=(?P<authority>\S+)"
)
RARE_EXIT_RE = re.compile(
    r"Wattpilot special charging model status exited: "
    r"model_status=(?P<status>8|9|10|11|13|14) "
    r"name=(?P<name>\S+) next_model_status=(?P<next>\S+) "
    r"observed_seconds=(?P<seconds>\d+)"
)
RAW_COMMAND_RE = re.compile(
    r"(?:Start/Stop to send: frc=|Blocked Wattpilot setValue |"
    r'"type"\s*:\s*"setValue"|\bsetValue\s+(?:amp|frc|psm)=|'
    r"\b(?:amp|frc|psm)=)",
    re.IGNORECASE,
)
STOP_REASONS = (
    ("grid import guard triggered. stopping", "grid import guard"),
    ("grid telemetry is missing, invalid, or stale", "stale grid telemetry"),
    ("stopping auto/eco charging", "insufficient allowance"),
    ("stopping ev charging", "controller stop"),
    ("charge complete", "charge complete"),
    ("disconnect confirmed", "vehicle disconnected"),
    ("wattpilot modelstatus: notcharging", "Wattpilot not charging"),
    ("blocked:", "command authority blocked"),
)
STOP_MARKERS = (
    "Stopping",
    "stopping",
    "Blocked:",
    "blocked:",
    "charge complete",
    "Charge complete",
    "disconnect confirmed",
    "Disconnect confirmed",
    "NotCharging",
    "notcharging",
    "Grid telemetry",
    "grid telemetry",
)


@dataclass
class LogRecord:
    timestamp: datetime
    level: str
    message: str
    raw: str

    def evidence(self) -> str:
        first_line = self.raw.splitlines()[0]
        return first_line.strip()


@dataclass
class Finding:
    status: str
    check: str
    message: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class AuditSettings:
    log_level: str = "INFO"
    enabled_services: list[str] = field(default_factory=list)
    min_current_per_phase: int = 6
    max_current_per_phase: int = 16
    three_phase_start_w: float = 4500.0
    three_phase_stop_w: float = 4100.0
    min_on_off_seconds: int = 60
    min_phase_switch_seconds: int = 600
    allowance_fresh_seconds: int = 15
    allowance_drop_grace_seconds: int = 15
    battery_assist_enabled: bool = True
    battery_assist_max_seconds: int = 600
    battery_assist_max_shortfall_w: float = 1000.0
    allow_grid_charging: bool = False
    grid_import_positive: bool = True
    grid_import_stop_w: float = 300.0
    grid_import_stop_seconds: int = 15
    startup_grace_seconds: int = 60


@dataclass
class AuditInput:
    target_date: str
    log_file: str
    config_file: str
    window_type: str = "calendar-day"
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    report_timezone: Optional[str] = None
    log_files: list[str] = field(default_factory=list)
    total_log_lines: int = 0
    dated_log_lines: int = 0
    first_timestamp: Optional[str] = None
    last_timestamp: Optional[str] = None
    partial_window: bool = False
    analysis_cutoff: Optional[str] = None
    evidence_duration_seconds: float = 0.0
    elapsed_window_seconds: float = 0.0
    evidence_span_percent: float = 0.0
    full_window_available_at: Optional[str] = None
    log_load_seconds: float = 0.0
    analysis_seconds: float = 0.0


@dataclass
class AllowanceEvent:
    record: LogRecord
    watts: float
    state: str
    phase: Optional[int]


@dataclass
class GridSample:
    record: LogRecord
    import_w: float
    charging_nearby: bool = False


@dataclass
class PhaseAction:
    record: LogRecord
    target_phase: int
    reason: str


@dataclass
class ChargingSession:
    start: str
    end: str
    mode: str
    phases: list[int]
    current_adjustments_a: list[int]
    phase_switches: list[str]
    stop_reason: str
    battery_assist_events: int
    grid_guard_events: int
    stale_telemetry_events: int
    rare_statuses: list[int]
    restart_during_session: bool
    evidence: list[str] = field(default_factory=list)


@dataclass
class RareStatusSummary:
    status: int
    protocol_name: str
    occurrences: int
    observed_seconds: int
    selected_states: list[str]
    result: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class CurrentSnapshot:
    captured_at: str
    service_state: str
    dependencies: str
    dbus_values: dict[str, str]
    available: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class AuditResult:
    schema: int
    overall: str
    exit_code: int
    inputs: AuditInput
    configuration: AuditSettings
    metrics: dict
    findings: list[Finding]
    sessions: list[ChargingSession]
    rare_statuses: list[RareStatusSummary]
    current_snapshot: CurrentSnapshot
    recommendations: list[str]
    limitations: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _localize_wall_datetime(value: datetime) -> datetime:
    """Attach the device's historical local offset to a naive wall time."""
    seconds = time.mktime(value.timetuple()) + value.microsecond / 1_000_000
    return datetime.fromtimestamp(seconds).astimezone()


def parse_log_timestamp(match: re.Match[str]) -> datetime:
    millis_text = match.group("millis")[:3].ljust(3, "0")
    base = datetime.fromisoformat(
        f"{match.group('date')}T{match.group('time')}.{millis_text}000"
    )

    if match.group("offset_sign") is None:
        return _localize_wall_datetime(base)

    hours = int(match.group("offset_hours"))
    minutes = int(match.group("offset_minutes") or "0")
    offset = timedelta(hours=hours, minutes=minutes)
    if match.group("offset_sign") == "-":
        offset = -offset
    return base.replace(tzinfo=timezone(offset))


def parse_log_line(
    line: str, legacy_timezone=None
) -> Optional[tuple[datetime, str, str]]:
    """Parse the maintained log format without a regex on the common path."""
    try:
        if (
            len(line) < 25
            or line[4] != "-"
            or line[7] != "-"
            or line[10] != " "
            or line[13] != ":"
            or line[16] != ":"
            or line[19] != ","
        ):
            return None
        millis_end = line.find(" ", 20)
        if millis_end < 21:
            return None
        millis_text = line[20:millis_end]
        if not millis_text.isdigit():
            return None
        millis_text = millis_text[:3].ljust(3, "0")
        timestamp = datetime.fromisoformat(
            f"{line[:10]}T{line[11:19]}.{millis_text}000"
        )

        cursor = millis_end + 1
        if line.startswith("(UTC", cursor):
            offset_end = line.find(") ", cursor + 5)
            if offset_end < 0:
                return None
            offset_text = line[cursor + 4 : offset_end]
            if not offset_text or offset_text[0] not in "+-":
                return None
            hour_text, separator, minute_text = offset_text[1:].partition(":")
            if not hour_text.isdigit() or (
                separator and (len(minute_text) != 2 or not minute_text.isdigit())
            ):
                return None
            offset = timedelta(
                hours=int(hour_text),
                minutes=int(minute_text or "0"),
            )
            if offset_text[0] == "-":
                offset = -offset
            timestamp = timestamp.replace(tzinfo=timezone(offset))
            cursor = offset_end + 2
        else:
            timestamp = (
                timestamp.replace(tzinfo=legacy_timezone)
                if legacy_timezone is not None
                else _localize_wall_datetime(timestamp)
            )

        level_end = line.find(" ", cursor)
        if level_end <= cursor:
            return None
        level = line[cursor:level_end]
        if not all(character.isupper() or character == "_" for character in level):
            return None
        return timestamp, level, line[level_end + 1 :]
    except (OverflowError, ValueError):
        return None


def _align_window_to_timestamp(
    timestamp: datetime, window_start: datetime, window_end: datetime
) -> tuple[datetime, datetime]:
    if timestamp.tzinfo is not None and window_start.tzinfo is None:
        return (
            _localize_wall_datetime(window_start),
            _localize_wall_datetime(window_end),
        )
    if timestamp.tzinfo is None and window_start.tzinfo is not None:
        return window_start.replace(tzinfo=None), window_end.replace(tzinfo=None)
    return window_start, window_end


def _load_log_path(
    path: Path,
    window_start: datetime,
    window_end: datetime,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    progress_offset: int = 0,
    progress_total: int = 1,
) -> tuple[list[LogRecord], int]:
    records: list[LogRecord] = []
    total_lines = 0
    current_record: Optional[LogRecord] = None
    processed_bytes = 0
    legacy_timezone = (
        timezone.utc
        if time.timezone == 0 and not time.daylight
        else None
    )

    with path.open("rb") as handle:
        for raw_bytes in handle:
            total_lines += 1
            processed_bytes += len(raw_bytes)
            raw_line = raw_bytes.decode("utf-8", errors="replace")
            if (
                progress_callback is not None
                and total_lines % LOG_PROGRESS_LINE_INTERVAL == 0
            ):
                progress_callback(
                    progress_offset + processed_bytes,
                    progress_total,
                    path.name,
                )
            line = raw_line.rstrip("\r\n")
            parsed = parse_log_line(line, legacy_timezone=legacy_timezone)
            if parsed is not None:
                current_record = None
                timestamp, level, message = parsed
                comparable_start, comparable_end = _align_window_to_timestamp(
                    timestamp, window_start, window_end
                )
                if not (comparable_start <= timestamp < comparable_end):
                    continue
                record = LogRecord(
                    timestamp=timestamp,
                    level=level,
                    message=message,
                    raw=line,
                )
                records.append(record)
                current_record = record
                continue

            # Preserve traceback/exception continuation lines belonging to a
            # selected-date record. They are important failure evidence.
            if current_record is not None and line:
                current_record.message += "\n" + line
                current_record.raw += "\n" + line

    if progress_callback is not None:
        progress_callback(
            progress_offset + processed_bytes,
            progress_total,
            path.name,
        )

    return records, total_lines


def load_log_records(path: Path, target_date: str) -> tuple[list[LogRecord], int]:
    """Compatibility helper for one explicitly selected calendar-day file."""
    day = datetime.strptime(target_date, "%Y-%m-%d")
    return _load_log_path(path, day, day + timedelta(days=1))


def load_log_window(
    paths: Iterable[Path],
    window_start: datetime,
    window_end: datetime,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> tuple[list[LogRecord], int]:
    paths = list(paths)
    records: list[LogRecord] = []
    total_lines = 0
    total_bytes = max(
        1,
        sum(path.stat().st_size for path in paths if path.is_file()),
    )
    processed_offset = 0
    for path in paths:
        selected, line_count = _load_log_path(
            path,
            window_start,
            window_end,
            progress_callback=progress_callback,
            progress_offset=processed_offset,
            progress_total=total_bytes,
        )
        records.extend(selected)
        total_lines += line_count
        processed_offset += path.stat().st_size

    if len(paths) == 1:
        return records, total_lines

    # A line can briefly exist in both current.log and the newly rotated file.
    # De-duplicate exact records while retaining distinct same-millisecond logs.
    deduplicated: dict[tuple[datetime, str, str], LogRecord] = {}
    for record in records:
        deduplicated[(record.timestamp, record.level, record.raw)] = record
    return sorted(deduplicated.values(), key=lambda item: item.timestamp), total_lines


def discover_log_files(base_log: Path) -> list[Path]:
    """Return current.log and standard TimedRotatingFileHandler day files."""
    parent = base_log.parent
    name = base_log.name
    candidates: list[Path] = []
    if base_log.is_file():
        candidates.append(base_log)
    if parent.is_dir():
        rotated_name = re.compile(re.escape(name) + r"\.\d{4}-\d{2}-\d{2}$")
        candidates.extend(
            path
            for path in parent.glob(name + ".*")
            if path.is_file() and rotated_name.fullmatch(path.name)
        )
    return sorted(set(candidates), key=lambda path: path.name)


def resolve_window(
    date_value: Optional[str],
    hours: Optional[float],
    now: Optional[datetime] = None,
    local_timezone=None,
) -> tuple[str, datetime, datetime, str]:
    if now is None:
        now = (
            datetime.now(local_timezone)
            if local_timezone is not None
            else datetime.now().astimezone()
        )
    elif local_timezone is not None:
        now = (
            now.replace(tzinfo=local_timezone)
            if now.tzinfo is None
            else now.astimezone(local_timezone)
        )
    if hours is not None:
        if hours < 24:
            raise ValueError("--hours must be at least 24 for a complete report")
        end = now
        start = end - timedelta(hours=hours)
        return f"last-{hours:g}-hours", start, end, "rolling-hours"

    value = (date_value or "yesterday").strip().lower()
    if value == "today":
        selected = now.date()
    elif value == "yesterday":
        selected = now.date() - timedelta(days=1)
    else:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        if parsed.strftime("%Y-%m-%d") != value:
            raise ValueError("--date must be today, yesterday, or YYYY-MM-DD")
        selected = parsed.date()

    wall_start = datetime.combine(selected, datetime.min.time())
    wall_end = wall_start + timedelta(days=1)
    window_timezone = local_timezone or now.tzinfo
    if window_timezone is None:
        start = wall_start
        end = wall_end
    else:
        start = wall_start.replace(tzinfo=window_timezone)
        end = wall_end.replace(tzinfo=window_timezone)
    return selected.isoformat(), start, end, "calendar-day"


def coverage_problem(
    records: list[LogRecord],
    window_start: datetime,
    window_end: datetime,
    now: Optional[datetime] = None,
) -> Optional[str]:
    if records:
        window_start, window_end = _align_window_to_timestamp(
            records[0].timestamp, window_start, window_end
        )
    if now is None:
        now = (
            datetime.now().astimezone()
            if window_end.tzinfo is not None
            else datetime.now()
        )
    elif window_end.tzinfo is not None and now.tzinfo is None:
        now = _localize_wall_datetime(now)
    elif window_end.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    if window_end > now:
        return (
            "The selected calendar day has not finished. Analyze yesterday after "
            "a complete APP_DEBUG day has been recorded."
        )
    if not records:
        return "No parseable es-ESS records exist in the selected window."
    if records[0].timestamp > window_start + FULL_DAY_BOUNDARY_TOLERANCE:
        return (
            "The first record is too far after the requested window start "
            f"({records[0].timestamp.isoformat()})."
        )
    if records[-1].timestamp < window_end - FULL_DAY_BOUNDARY_TOLERANCE:
        return (
            "The last record is too far before the requested window end "
            f"({records[-1].timestamp.isoformat()})."
        )
    return None


def diagnostic_coverage_problem(
    records: list[LogRecord],
    window_start: datetime,
    window_end: datetime,
    now: Optional[datetime] = None,
) -> Optional[str]:
    diagnostic_records = [
        record for record in records if record.level in VERBOSE_LOG_LEVELS
    ]
    problem = coverage_problem(
        diagnostic_records,
        window_start,
        window_end,
        now=now,
    )
    if problem:
        return (
            "APP_DEBUG/DEBUG/TRACE records do not cover the complete selected "
            f"window. {problem}"
        )
    return None


def calculate_coverage_metadata(
    records: list[LogRecord],
    window_start: datetime,
    analysis_cutoff: datetime,
) -> tuple[float, float, float]:
    if records:
        window_start, analysis_cutoff = _align_window_to_timestamp(
            records[0].timestamp, window_start, analysis_cutoff
        )
    elapsed_seconds = max(
        0.0, (analysis_cutoff - window_start).total_seconds()
    )
    evidence_seconds = (
        max(0.0, (records[-1].timestamp - records[0].timestamp).total_seconds())
        if records
        else 0.0
    )
    percent = (
        min(100.0, evidence_seconds / elapsed_seconds * 100.0)
        if elapsed_seconds > 0
        else 0.0
    )
    return evidence_seconds, elapsed_seconds, percent


def prerequisite_instructions(reason: str, config_file: str) -> list[str]:
    return [
        f"Daily report stopped: {reason}",
        f"Edit {config_file} and set [Common] LogLevel=APP_DEBUG.",
        "Restart es-ESS with /data/es-ESS/restart.sh.",
        "Leave es-ESS running at APP_DEBUG for at least one complete day.",
        "Then run: python /data/es-ESS/scripts/es-ess-daily-report.py --date yesterday",
    ]


def _get_int(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    fallback: int,
    warnings: list[str],
) -> int:
    try:
        return parser.getint(section, key)
    except (configparser.Error, ValueError):
        warnings.append(f"[{section}] {key} missing or invalid; using {fallback}")
        return fallback


def _get_float(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    fallback: float,
    warnings: list[str],
) -> float:
    try:
        return parser.getfloat(section, key)
    except (configparser.Error, ValueError):
        warnings.append(f"[{section}] {key} missing or invalid; using {fallback}")
        return fallback


def _get_bool(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    fallback: bool,
    warnings: list[str],
) -> bool:
    try:
        return parser.getboolean(section, key)
    except (configparser.Error, ValueError):
        warnings.append(f"[{section}] {key} missing or invalid; using {fallback}")
        return fallback


class ConfigurationReadError(RuntimeError):
    """Configuration exists but cannot be safely read or parsed."""


def load_settings(path: Path) -> tuple[AuditSettings, list[str]]:
    warnings: list[str] = []
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            parser.read_file(handle)
    except FileNotFoundError as exc:
        warnings.append(f"configuration is missing: {exc}; using safe fallbacks")
        return AuditSettings(), warnings
    except OSError as exc:
        raise ConfigurationReadError(
            f"cannot open configuration {path}: {exc}"
        ) from exc
    except configparser.Error as exc:
        raise ConfigurationReadError(
            f"cannot parse configuration {path}: {exc}"
        ) from exc

    enabled_services: list[str] = []
    if parser.has_section("Services"):
        # ConfigParser's public mapping/items APIs include inherited [DEFAULT]
        # values. The private section dictionary is deliberately retained here
        # because it is the only parser-owned representation of keys explicitly
        # declared in [Services]; replacing it would reclassify documentation
        # defaults as service flags.
        for key in parser._sections.get("Services", {}):
            try:
                if parser.getboolean("Services", key):
                    enabled_services.append(key)
            except (configparser.Error, ValueError):
                warnings.append(f"[Services] {key} is not a valid boolean")
    else:
        warnings.append("[Services] section missing; enabled services unavailable")

    section = "FroniusWattpilot"
    settings = AuditSettings(
        log_level=parser.get("Common", "LogLevel", fallback="INFO").upper(),
        enabled_services=sorted(enabled_services),
        min_current_per_phase=_get_int(parser, section, "MinCurrentPerPhase", 6, warnings),
        max_current_per_phase=_get_int(parser, section, "MaxCurrentPerPhase", 16, warnings),
        three_phase_start_w=_get_float(
            parser, section, "ThreePhasePvSurplusStartW", 4500.0, warnings
        ),
        three_phase_stop_w=_get_float(
            parser, section, "ThreePhasePvSurplusStopW", 4100.0, warnings
        ),
        min_on_off_seconds=_get_int(
            parser, section, "MinOnOffSeconds", 60, warnings
        ),
        min_phase_switch_seconds=_get_int(
            parser, section, "MinPhaseSwitchSeconds", 600, warnings
        ),
        allowance_fresh_seconds=_get_int(
            parser, section, "AllowanceFreshSeconds", 15, warnings
        ),
        # Keep the controller's backward-compatible missing-key fallback. The
        # maintained sample currently configures 30 seconds explicitly.
        allowance_drop_grace_seconds=_get_int(
            parser, section, "AllowanceDropGraceSeconds", 15, warnings
        ),
        battery_assist_enabled=_get_bool(
            parser, section, "BatteryAssistEnabled", True, warnings
        ),
        battery_assist_max_seconds=_get_int(
            parser, section, "BatteryAssistMaxSeconds", 600, warnings
        ),
        battery_assist_max_shortfall_w=_get_float(
            parser, section, "BatteryAssistMaxShortfallW", 1000.0, warnings
        ),
        allow_grid_charging=_get_bool(
            parser, section, "AllowGridCharging", False, warnings
        ),
        grid_import_positive=_get_bool(
            parser, section, "GridImportPositive", True, warnings
        ),
        grid_import_stop_w=_get_float(
            parser, section, "GridImportStopW", 300.0, warnings
        ),
        grid_import_stop_seconds=_get_int(
            parser, section, "GridImportStopSeconds", 15, warnings
        ),
        startup_grace_seconds=_get_int(
            parser, section, "StartupGraceSeconds", 60, warnings
        ),
    )
    return settings, warnings


def _run_readonly_command(
    args: list[str],
    runner=subprocess.run,
    timeout_seconds: int = SNAPSHOT_COMMAND_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Run only exact service-status and D-Bus read operations."""
    if not args:
        return False, "empty command"
    if args[0] == "svstat":
        allowed = len(args) == 2 and args[1] == DEFAULT_SERVICE_DIR
    elif args[0] == "dbus":
        allowed = (
            len(args) == 5
            and args[1] == "-y"
            and args[4] == "GetValue"
            and (args[2], args[3]) in READONLY_DBUS_PAIRS
        )
    else:
        allowed = False
    if not allowed:
        return False, "command rejected by read-only allowlist"

    try:
        completed = runner(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"timeout after {timeout_seconds}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    output = (completed.stdout or "").strip().strip("'")
    if completed.returncode != 0 or not output:
        detail = (completed.stderr or "").strip() or "unavailable"
        return False, detail
    return True, output


def resolve_report_timezone(
    runner=subprocess.run,
    which=shutil.which,
    zone_factory=ZoneInfo,
):
    """Return the authoritative Venus timezone or a safe OS-local fallback."""
    fallback = datetime.now().astimezone().tzinfo
    if not which("dbus"):
        return (
            "OS local timezone",
            fallback,
            "Venus timezone unavailable because the dbus command is not installed; "
            "using OS-local time.",
        )

    ok, value = _run_readonly_command(
        [
            "dbus",
            "-y",
            DEFAULT_SETTINGS_DBUS_SERVICE,
            VENUS_TIMEZONE_DBUS_PATH,
            "GetValue",
        ],
        runner=runner,
    )
    if not ok:
        return (
            "OS local timezone",
            fallback,
            f"Venus timezone query failed ({value}); using OS-local time.",
        )
    try:
        report_timezone = zone_factory(value)
    except (OSError, ValueError, ZoneInfoNotFoundError) as exc:
        return (
            "OS local timezone",
            fallback,
            f"Venus timezone {value!r} is unavailable ({exc}); using OS-local time.",
        )
    return value, report_timezone, None


def capture_current_snapshot(
    runner=subprocess.run,
    which=shutil.which,
    now: Optional[datetime] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> CurrentSnapshot:
    captured_at = (now or datetime.now()).isoformat()
    notes: list[str] = []
    service_state = "unavailable"
    dbus_values: dict[str, str] = {}
    progress_total = len(SNAPSHOT_DBUS_PATHS) + 2
    progress_current = 0

    if which("svstat"):
        ok, service_state = _run_readonly_command(
            ["svstat", DEFAULT_SERVICE_DIR], runner=runner
        )
        if not ok:
            notes.append(f"service snapshot unavailable: {service_state}")
            service_state = "unavailable"
    else:
        notes.append("svstat command is not available")
    progress_current += 1
    if progress_callback is not None:
        progress_callback(progress_current, progress_total, "service state")

    if which("dbus"):
        consecutive_timeouts = 0
        for index, path in enumerate(SNAPSHOT_DBUS_PATHS):
            ok, value = _run_readonly_command(
                [
                    "dbus",
                    "-y",
                    DEFAULT_WATTPILOT_DBUS_SERVICE,
                    path,
                    "GetValue",
                ],
                runner=runner,
            )
            dbus_values[path] = value if ok else "unavailable"
            consecutive_timeouts = (
                consecutive_timeouts + 1
                if not ok and value.startswith("timeout after ")
                else 0
            )
            progress_current += 1
            if progress_callback is not None:
                progress_callback(
                    progress_current,
                    progress_total,
                    f"D-Bus {index + 1}/{len(SNAPSHOT_DBUS_PATHS)} {path}",
                )
            if consecutive_timeouts >= SNAPSHOT_MAX_CONSECUTIVE_TIMEOUTS:
                remaining = SNAPSHOT_DBUS_PATHS[index + 1 :]
                dbus_values.update({item: "unavailable" for item in remaining})
                progress_current += len(remaining)
                notes.append(
                    "remaining D-Bus snapshot paths skipped after "
                    f"{consecutive_timeouts} consecutive timeouts"
                )
                if progress_callback is not None:
                    progress_callback(
                        progress_current,
                        progress_total,
                        "remaining D-Bus paths skipped after timeouts",
                    )
                break
    else:
        notes.append("dbus command is not available")
        dbus_values.update(
            {path: "unavailable" for path in SNAPSHOT_DBUS_PATHS}
        )
        progress_current += len(SNAPSHOT_DBUS_PATHS)
        if progress_callback is not None:
            progress_callback(
                progress_current,
                progress_total,
                "D-Bus command unavailable",
            )

    dependency_names = ("paho.mqtt.client", "websocket")
    missing_dependencies: list[str] = []
    for dependency in dependency_names:
        try:
            if importlib.util.find_spec(dependency) is None:
                missing_dependencies.append(dependency)
        except (ImportError, ModuleNotFoundError, AttributeError, ValueError):
            missing_dependencies.append(dependency)
    dependencies = (
        "available"
        if not missing_dependencies
        else "missing: " + ", ".join(missing_dependencies)
    )
    progress_current += 1
    if progress_callback is not None:
        progress_callback(progress_current, progress_total, "dependencies")

    return CurrentSnapshot(
        captured_at=captured_at,
        service_state=service_state,
        dependencies=dependencies,
        dbus_values=dbus_values,
        available=(
            service_state != "unavailable"
            or any(value != "unavailable" for value in dbus_values.values())
        ),
        notes=notes,
    )


class EsEssDailyReport:
    def __init__(
        self,
        records: list[LogRecord],
        settings: AuditSettings,
        audit_input: AuditInput,
        config_warnings: Optional[list[str]] = None,
        current_snapshot: Optional[CurrentSnapshot] = None,
    ) -> None:
        self.records = records
        self.settings = settings
        self.audit_input = audit_input
        self.config_warnings = config_warnings or []
        self.current_snapshot = current_snapshot or CurrentSnapshot(
            captured_at=datetime.now().isoformat(),
            service_state="not captured",
            dependencies="not captured",
            dbus_values={},
            available=False,
            notes=["current snapshot was not requested"],
        )
        self.findings: list[Finding] = []

        self.allowances: list[AllowanceEvent] = []
        self._allowance_timestamps: list[datetime] = []
        self.grid_samples: list[GridSample] = []
        self.current_adjustments: list[tuple[LogRecord, int, int]] = []
        self.assist_samples: list[tuple[LogRecord, float, float]] = []
        self.grace_starts: list[tuple[LogRecord, int]] = []
        self.phase_actions: list[PhaseAction] = []
        self.phase_confirmations: list[tuple[LogRecord, int]] = []
        self.phase_up_waits: list[tuple[LogRecord, float, int]] = []
        self.charge_records: list[LogRecord] = []
        self._charge_timestamps: list[datetime] = []
        self._stop_records: list[LogRecord] = []
        self._stop_timestamps: list[datetime] = []
        self.start_records: list[tuple[LogRecord, float]] = []
        self.authority_valid: list[LogRecord] = []
        self.authority_blocked: list[LogRecord] = []
        self.manual_boundaries: list[LogRecord] = []
        self.grid_guard_actions: list[LogRecord] = []
        self.safety_override_records: list[LogRecord] = []
        self.failure_records: list[LogRecord] = []
        self.restart_records: list[LogRecord] = []
        self.reconnect_records: list[LogRecord] = []
        self.stale_telemetry_records: list[LogRecord] = []
        self.battery_assist_limit_records: list[LogRecord] = []
        self.raw_command_records: list[LogRecord] = []
        self._manual_control_records: list[LogRecord] = []
        self._manual_control_timestamps: list[datetime] = []
        self.rare_entries: list[tuple[LogRecord, dict[str, str]]] = []
        self.rare_exits: list[tuple[LogRecord, dict[str, str]]] = []

    def add(
        self,
        status: str,
        check: str,
        message: str,
        records: Iterable[LogRecord] = (),
    ) -> None:
        evidence = [record.evidence() for record in list(records)[:5]]
        self.findings.append(Finding(status, check, message, evidence))

    @staticmethod
    def _phase_from_state(state: str) -> Optional[int]:
        match = re.search(r"(?:Charging|Ready)\s*\(?(?P<phase>[13]) phase", state)
        if not match:
            return None
        return int(match.group("phase"))

    def collect(self) -> None:
        for record in self.records:
            message = record.message

            allowance_match = (
                ALLOWANCE_RE.search(message)
                if "Assigned " in message and "Wattpilot" in message
                else None
            )
            if allowance_match:
                state = allowance_match.group("state")
                event = AllowanceEvent(
                    record=record,
                    watts=float(allowance_match.group("watts")),
                    state=state,
                    phase=self._phase_from_state(state),
                )
                self.allowances.append(event)
                if "Charging" in state:
                    self.charge_records.append(record)

            grid_match = (
                GRID_RE.search(message)
                if "L1/L2/L3/Bat/Soc/Feedin is " in message
                else None
            )
            if grid_match:
                phase_total = sum(
                    float(grid_match.group(name)) for name in ("l1", "l2", "l3")
                )
                import_w = phase_total if self.settings.grid_import_positive else -phase_total
                self.grid_samples.append(GridSample(record, import_w))

            current_match = (
                CURRENT_RE.search(message)
                if "Adjusting charge current to " in message
                else None
            )
            if current_match:
                self.current_adjustments.append(
                    (
                        record,
                        int(current_match.group("amps")),
                        int(current_match.group("phase")),
                    )
                )
                self.charge_records.append(record)

            assist_match = (
                ASSIST_RE.search(message)
                if "Battery assist active: " in message
                else None
            )
            if assist_match:
                self.assist_samples.append(
                    (
                        record,
                        float(assist_match.group("shortfall")),
                        float(assist_match.group("elapsed")),
                    )
                )
            if "Battery assist time limit reached" in message:
                self.battery_assist_limit_records.append(record)

            grace_match = (
                GRACE_RE.search(message)
                if "EV allowance fell below the usable minimum" in message
                else None
            )
            if grace_match:
                self.grace_starts.append((record, int(grace_match.group("seconds"))))

            wait_match = (
                PHASE_UP_WAIT_RE.search(message)
                if "phase-up allowance" in message
                else None
            )
            if wait_match:
                self.phase_up_waits.append(
                    (
                        record,
                        float(wait_match.group("stable")),
                        int(wait_match.group("required")),
                    )
                )

            confirmation_match = (
                PHASE_CONFIRM_RE.search(message)
                if "Wattpilot phase telemetry confirmed " in message
                else None
            )
            if confirmation_match:
                self.phase_confirmations.append(
                    (record, int(confirmation_match.group("phase")))
                )
                self.charge_records.append(record)

            if "Switching to 3-phase from PV surplus" in message:
                self.phase_actions.append(PhaseAction(record, 3, "PV phase-up"))
            elif (
                "PV allowance dropped below the three-phase threshold" in message
                and "Switching to 1-phase" in message
            ):
                self.phase_actions.append(PhaseAction(record, 1, "PV phase-down"))
            elif (
                "Grid import guard triggered, but PV supports 1-phase" in message
                and "Switching to 1-phase" in message
            ):
                self.phase_actions.append(PhaseAction(record, 1, "grid guard"))

            start_match = (
                START_RE.search(message)
                if "Starting to charge after " in message
                else None
            )
            if start_match:
                self.start_records.append(
                    (record, float(start_match.group("stable")))
                )
                self.charge_records.append(record)
            elif (
                "Wattpilot Modelstatus:" in message
                and "Charging" in message
                and MODEL_CHARGING_RE.search(message)
            ):
                self.charge_records.append(record)

            if "Validated: es-ESS is the sole Auto/Eco command owner" in message:
                self.authority_valid.append(record)
            authority_blocked = (
                "Blocked: native Wattpilot command settings unavailable" in message
                or "Blocked: Wattpilot firmware compatibility unavailable" in message
                or "Blocked: disable Use PV surplus" in message
                or "Blocked: disable flexible tariff" in message
                or "Ready: select Auto on GX/VRM" in message
                or "Auto selection rejected." in message
            )
            if authority_blocked:
                self.authority_blocked.append(record)
            if "Manual mode selected. Releasing Auto/Eco" in message:
                self.manual_boundaries.append(record)

            if "Grid import guard triggered" in message:
                self.grid_guard_actions.append(record)
                self.safety_override_records.append(record)
            if "Grid telemetry is missing, invalid, or stale" in message:
                self.safety_override_records.append(record)
                self.stale_telemetry_records.append(record)
            if authority_blocked:
                self.safety_override_records.append(record)

            if "Initialization completed." in message and "is up and running" in message:
                self.restart_records.append(record)
            if (
                "Wattpilot disconnected" in message
                or "Previous Wattpilot WebSocket worker did not stop" in message
            ):
                self.reconnect_records.append(record)

            raw_command = bool(
                (
                    "setValue" in message
                    or "frc=" in message
                    or "amp=" in message
                    or "psm=" in message
                )
                and RAW_COMMAND_RE.search(message)
            )
            if raw_command:
                self.raw_command_records.append(record)
            if (
                "Adjusting charge current" in message
                or "Switching to 3-phase from PV surplus" in message
                or "Switching to 1-phase" in message
                or "Starting to charge after" in message
                or "Stopping EV charging" in message
                or "Battery assist active" in message
                or raw_command
            ):
                self._manual_control_records.append(record)

            rare_enter = (
                RARE_ENTER_RE.search(message)
                if "Wattpilot special charging model status entered:" in message
                else None
            )
            if rare_enter:
                self.rare_entries.append((record, rare_enter.groupdict()))
            rare_exit = (
                RARE_EXIT_RE.search(message)
                if "Wattpilot special charging model status exited:" in message
                else None
            )
            if rare_exit:
                self.rare_exits.append((record, rare_exit.groupdict()))

            if (
                record.level in ("ERROR", "CRITICAL")
                or "Traceback (most recent call last)" in message
                or "ModuleNotFoundError" in message
                or "CompatibilityError" in message
                or "Unsupported Venus OS" in message
                or "Wattpilot firmware compatibility not confirmed" in message
            ):
                self.failure_records.append(record)
            if (
                "3-phase switch was not confirmed" in message
                or "1-phase fallback was not confirmed" in message
            ):
                self.failure_records.append(record)

            if self._stop_reason(record) is not None:
                self._stop_records.append(record)

        self.charge_records = sorted(
            {record.timestamp: record for record in self.charge_records}.values(),
            key=lambda record: record.timestamp,
        )
        self._charge_timestamps = [
            record.timestamp for record in self.charge_records
        ]
        self._allowance_timestamps = [
            event.record.timestamp for event in self.allowances
        ]
        self._stop_timestamps = [record.timestamp for record in self._stop_records]
        self._manual_control_records = sorted(
            {
                (record.timestamp, record.raw): record
                for record in self._manual_control_records
            }.values(),
            key=lambda record: record.timestamp,
        )
        self._manual_control_timestamps = [
            record.timestamp for record in self._manual_control_records
        ]
        self.failure_records = sorted(
            {record.timestamp: record for record in self.failure_records}.values(),
            key=lambda record: record.timestamp,
        )

    def check_inputs(self) -> None:
        if not self.records:
            self.add(
                "WARN",
                "log coverage",
                "No parseable log records were found for the requested date.",
            )
            return

        adequate_levels = {"TRACE", "DEBUG", "APP_DEBUG"}
        if self.settings.log_level not in adequate_levels:
            self.add(
                "WARN",
                "log coverage",
                f"Configured LogLevel={self.settings.log_level}; APP_DEBUG or more verbose "
                "is required for a comprehensive allowance and phase audit.",
            )
        else:
            self.add(
                "PASS",
                "log coverage",
                f"Configured LogLevel={self.settings.log_level} provides controller and "
                "distributor diagnostic events.",
            )

        if self.audit_input.partial_window:
            self.add(
                "WARN",
                "partial calendar day",
                "Today is still in progress. Findings cover only the available records "
                f"through {self.audit_input.analysis_cutoff}; this report cannot conclude GOOD.",
            )

        if self.config_warnings:
            self.findings.append(
                Finding(
                    "WARN",
                    "configuration",
                    "Some audit parameters were unavailable; fallback values were used.",
                    self.config_warnings[:5],
                )
            )
        else:
            self.add("PASS", "configuration", "Required audit parameters were read successfully.")

    def check_failures(self) -> None:
        if self.failure_records:
            self.add(
                "FAIL",
                "runtime errors",
                f"Detected {len(self.failure_records)} error, traceback, compatibility, or "
                "failed-phase-confirmation event(s).",
                self.failure_records,
            )
        else:
            self.add(
                "PASS",
                "runtime errors",
                "No error, critical, traceback, compatibility, or failed phase-confirmation "
                "events were detected.",
            )

    def check_runtime_health(self) -> None:
        if len(self.restart_records) > 1:
            self.add(
                "ATTENTION",
                "service restarts",
                f"Observed {len(self.restart_records)} es-ESS initializations in the report window.",
                self.restart_records,
            )
        elif self.restart_records:
            self.add(
                "INFO",
                "service restarts",
                "One es-ESS initialization was observed in the report window.",
                self.restart_records,
            )
        else:
            self.add(
                "INFO",
                "service restarts",
                "No initialization marker was observed; the service may have remained up across the window boundary.",
            )

        if len(self.reconnect_records) > 1:
            self.add(
                "ATTENTION",
                "Wattpilot reconnects",
                f"Observed {len(self.reconnect_records)} Wattpilot worker/disconnect/reconnect events.",
                self.reconnect_records,
            )
        elif self.reconnect_records:
            self.add(
                "INFO",
                "Wattpilot reconnects",
                "One Wattpilot connection-lifecycle event was observed.",
                self.reconnect_records,
            )
        else:
            self.add(
                "INFO",
                "Wattpilot reconnects",
                "No Wattpilot reconnect event was observed.",
            )

        long_gaps: list[LogRecord] = []
        for previous, current in zip(self.records, self.records[1:]):
            if (current.timestamp - previous.timestamp).total_seconds() > HEARTBEAT_GAP_SECONDS:
                long_gaps.extend([previous, current])
        if long_gaps:
            self.add(
                "WARN",
                "log continuity",
                "One or more log gaps exceeded three minutes despite the normal one-minute service heartbeat.",
                long_gaps,
            )
        else:
            self.add(
                "PASS",
                "log continuity",
                "No log gap exceeded the conservative three-minute heartbeat window.",
            )

        snapshot = self.current_snapshot
        if not snapshot.available:
            self.add(
                "INFO",
                "current snapshot",
                "Current service/D-Bus commands were unavailable or the snapshot was disabled; historical analysis continues without treating current state as past evidence.",
            )
            return

        if snapshot.service_state != "unavailable" and ": up " not in snapshot.service_state:
            self.add(
                "FAIL",
                "current service state",
                f"es-ESS is not currently confirmed up: {snapshot.service_state}",
            )
        elif snapshot.service_state != "unavailable":
            self.add(
                "PASS",
                "current service state",
                f"es-ESS is currently up: {snapshot.service_state}",
            )

        if snapshot.dependencies != "available":
            self.add(
                "FAIL",
                "Wattpilot external dependencies",
                "Wattpilot external Python dependencies are "
                f"{snapshot.dependencies}.",
            )
        else:
            self.add(
                "PASS",
                "Wattpilot external dependencies",
                "Wattpilot external Python dependencies are available.",
            )

        dbus = snapshot.dbus_values
        if dbus.get("/CompatibilityOk") not in (None, "unavailable", "1"):
            self.add(
                "FAIL",
                "current compatibility",
                f"Current /CompatibilityOk={dbus.get('/CompatibilityOk')}",
            )
        if (
            dbus.get("/ModeLiteral") == "Auto"
            and dbus.get("/CommandAuthorityOk") not in ("1",)
        ):
            self.add(
                "FAIL",
                "current command authority",
                "Current Auto mode is not accompanied by CommandAuthorityOk=1.",
            )

    def check_commissioning_profile(self) -> None:
        services = {name.lower() for name in self.settings.enabled_services}
        if "froniuswattpilot" not in services:
            self.add(
                "INFO",
                "commissioning profile",
                "FroniusWattpilot is not enabled in the sanitized service list.",
            )
            return

        problems: list[str] = []
        if "solaroverheaddistributor" not in services:
            problems.append("SolarOverheadDistributor is disabled")
        if "nobattoev" in services:
            problems.append("NoBatToEV is enabled with Wattpilot no-grid/battery-assist control")
        if self.settings.allow_grid_charging:
            problems.append("AllowGridCharging=true")

        if problems:
            self.findings.append(
                Finding(
                    "FAIL",
                    "commissioning profile",
                    "Configuration is inconsistent with the documented no-grid commissioning profile.",
                    problems,
                )
            )
        else:
            self.add(
                "PASS",
                "commissioning profile",
                "Enabled services and AllowGridCharging match the documented no-grid Wattpilot profile.",
            )

    def check_safety_interventions(self) -> None:
        events = (
            self.grid_guard_actions
            + self.stale_telemetry_records
            + self.battery_assist_limit_records
            + self.authority_blocked
        )
        if events:
            self.add(
                "ATTENTION",
                "safety interventions",
                "One or more safety systems intervened or blocked control. This is not automatically a controller defect; inspect the matching outcome findings.",
                sorted(events, key=lambda record: record.timestamp),
            )
        else:
            self.add(
                "INFO",
                "safety interventions",
                "No grid, stale-telemetry, battery-assist-timeout, or authority-block intervention was observed.",
            )

    def check_charging(self) -> None:
        if not self.charge_records:
            self.add(
                "NOT_OBSERVED",
                "charging",
                "No Wattpilot charging evidence was observed; charging behavior cannot be "
                "validated for this date.",
            )
            return

        session_count = 1
        prior = self.charge_records[0].timestamp
        for record in self.charge_records[1:]:
            if (record.timestamp - prior).total_seconds() > 60:
                session_count += 1
            prior = record.timestamp

        self.add(
            "PASS",
            "charging",
            f"Charging evidence was observed in approximately {session_count} session(s), "
            f"from {self.charge_records[0].timestamp.time()} to "
            f"{self.charge_records[-1].timestamp.time()}.",
            [self.charge_records[0], self.charge_records[-1]],
        )

    def check_current_bounds(self) -> None:
        if not self.current_adjustments:
            self.add(
                "NOT_OBSERVED",
                "current limits",
                "No logged Auto/Eco current-adjustment event was available to validate "
                "configured current bounds.",
            )
            return

        invalid = [
            record
            for record, amps, _phase in self.current_adjustments
            if amps < self.settings.min_current_per_phase
            or amps > self.settings.max_current_per_phase
        ]
        if invalid:
            self.add(
                "FAIL",
                "current limits",
                f"Current adjustment fell outside configured "
                f"{self.settings.min_current_per_phase}..{self.settings.max_current_per_phase} A bounds.",
                invalid,
            )
        else:
            amps = [value for _record, value, _phase in self.current_adjustments]
            self.add(
                "PASS",
                "current limits",
                f"All {len(amps)} logged current adjustments stayed within configured bounds "
                f"({min(amps)}..{max(amps)} A observed).",
            )

    def _allowance_at_or_before(
        self, timestamp: datetime
    ) -> Optional[AllowanceEvent]:
        index = bisect_right(self._allowance_timestamps, timestamp) - 1
        return self.allowances[index] if index >= 0 else None

    def _allowance_after(self, timestamp: datetime) -> Optional[AllowanceEvent]:
        index = bisect_right(self._allowance_timestamps, timestamp)
        return self.allowances[index] if index < len(self.allowances) else None

    def check_allowance(self) -> None:
        if not self.allowances:
            status = "WARN" if self.charge_records else "NOT_OBSERVED"
            self.add(
                status,
                "allowance",
                "No numeric Wattpilot allowance assignments were found; allowance handling "
                "cannot be reconstructed from this log.",
            )
            return

        zero_three_phase = [
            event.record
            for event in self.allowances
            if event.watts <= 0 and event.phase == 3 and "Charging" in event.state
        ]
        values = [event.watts for event in self.allowances]
        self.add(
            "PASS",
            "allowance",
            f"Parsed {len(values)} Wattpilot assignments ({min(values):.0f}..{max(values):.0f} W); "
            f"{len(zero_three_phase)} atomic 0 W three-phase event(s) were observed.",
            zero_three_phase,
        )

        early_starts = [
            record
            for record, stable_seconds in self.start_records
            if stable_seconds + 1 < self.settings.min_on_off_seconds
        ]
        if early_starts:
            self.add(
                "FAIL",
                "start timing",
                "A new Auto/Eco charge started before MinOnOffSeconds of continuous PV allowance.",
                early_starts,
            )
        elif self.start_records:
            self.add(
                "PASS",
                "start timing",
                f"All {len(self.start_records)} logged start(s) met MinOnOffSeconds before charging.",
                [record for record, _stable in self.start_records],
            )

        command_records = [record for record, _stable in self.start_records]
        command_records.extend(record for record, _amps, _phase in self.current_adjustments)
        command_records.extend(
            action.record for action in self.phase_actions if action.target_phase == 3
        )
        stale_commands: list[LogRecord] = []
        missing_evidence: list[LogRecord] = []
        for command in command_records:
            prior = self._allowance_at_or_before(command.timestamp)
            if prior is None:
                missing_evidence.append(command)
                continue
            age = (command.timestamp - prior.record.timestamp).total_seconds()
            if age > self.settings.allowance_fresh_seconds + 1:
                stale_commands.append(command)

        if stale_commands:
            self.add(
                "FAIL",
                "allowance freshness",
                "A logged start, phase-up, or current adjustment used allowance evidence older "
                "than AllowanceFreshSeconds.",
                stale_commands,
            )
        elif command_records and not missing_evidence:
            self.add(
                "PASS",
                "allowance freshness",
                "Every logged positive Auto/Eco control action had a recent preceding numeric "
                "allowance assignment.",
            )
        if missing_evidence:
            self.add(
                "WARN",
                "allowance freshness",
                "Some control actions had no preceding numeric allowance in the selected-day "
                "window, so freshness could not be proven.",
                missing_evidence,
            )

    def _records_between(
        self, start: datetime, end: datetime, records: Iterable[LogRecord]
    ) -> list[LogRecord]:
        return [record for record in records if start <= record.timestamp <= end]

    def check_allowance_grace(self) -> None:
        if not self.grace_starts:
            zero_three_phase = [
                event
                for event in self.allowances
                if event.watts <= 0 and event.phase == 3 and "Charging" in event.state
            ]
            premature_state_changes: list[LogRecord] = []
            missing_grace_evidence: list[LogRecord] = []
            for zero_event in zero_three_phase:
                next_assignment = self._allowance_after(
                    zero_event.record.timestamp
                )
                if next_assignment is None:
                    missing_grace_evidence.append(zero_event.record)
                    continue
                elapsed = (
                    next_assignment.record.timestamp - zero_event.record.timestamp
                ).total_seconds()
                safety_override = self._records_between(
                    zero_event.record.timestamp,
                    next_assignment.record.timestamp,
                    self.safety_override_records,
                )
                if (
                    next_assignment.phase == 1
                    and elapsed < self.settings.allowance_drop_grace_seconds
                    and not safety_override
                ):
                    premature_state_changes.extend(
                        [zero_event.record, next_assignment.record]
                    )
                else:
                    missing_grace_evidence.append(zero_event.record)

            if premature_state_changes:
                self.add(
                    "FAIL",
                    "allowance drop grace",
                    "A three-phase atomic 0 W assignment was followed by one-phase state before "
                    "AllowanceDropGraceSeconds, with no logged grace or higher-priority safety "
                    "override.",
                    premature_state_changes,
                )
                return
            if missing_grace_evidence:
                self.add(
                    "WARN",
                    "allowance drop grace",
                    "Atomic 0 W three-phase evidence was present, but no controller grace event "
                    "was logged. The selected log may be filtered or the controller may not have "
                    "processed the sample before recovery.",
                    missing_grace_evidence,
                )
                return
            self.add(
                "NOT_OBSERVED",
                "allowance drop grace",
                "No running-session allowance-drop grace event occurred; its production "
                "timing was not exercised on this date.",
            )
            return

        passed = 0
        unresolved: list[LogRecord] = []
        premature: list[LogRecord] = []
        details: list[LogRecord] = []
        last_timestamp = self.records[-1].timestamp

        for index, (start_record, logged_seconds) in enumerate(self.grace_starts):
            configured_seconds = self.settings.allowance_drop_grace_seconds
            grace_seconds = configured_seconds
            if logged_seconds != configured_seconds:
                self.add(
                    "WARN",
                    "allowance drop grace",
                    f"Log announced {logged_seconds}s but config contains {configured_seconds}s.",
                    [start_record],
                )
                grace_seconds = logged_seconds

            start = start_record.timestamp
            next_start = (
                self.grace_starts[index + 1][0].timestamp
                if index + 1 < len(self.grace_starts)
                else None
            )
            deadline = start + timedelta(seconds=grace_seconds)
            audit_end = min(
                next_start if next_start is not None else last_timestamp,
                deadline + timedelta(seconds=10),
            )

            recovery = next(
                (
                    event
                    for event in self.allowances
                    if start < event.record.timestamp <= audit_end
                    and event.phase == 3
                    and "Charging" in event.state
                    and event.watts >= self.settings.three_phase_stop_w
                ),
                None,
            )
            action = next(
                (
                    item
                    for item in self.phase_actions
                    if start < item.record.timestamp <= audit_end and item.target_phase == 1
                ),
                None,
            )
            stop_record = next(
                (
                    record
                    for record in self.records
                    if start < record.timestamp <= audit_end
                    and (
                        "STOP send!" in record.message
                        or "Stopping Auto/Eco charging" in record.message
                        or "Stopping EV charging" in record.message
                    )
                ),
                None,
            )
            response_record = action.record if action is not None else stop_record
            safety_override = self._records_between(
                start, response_record.timestamp if response_record else audit_end,
                self.safety_override_records,
            )

            if recovery is not None and (
                response_record is None or recovery.record.timestamp <= response_record.timestamp
            ):
                passed += 1
                details.extend([start_record, recovery.record])
                continue

            if response_record is not None:
                elapsed = (response_record.timestamp - start).total_seconds()
                positive_assignment = next(
                    (
                        event
                        for event in self.allowances
                        if start < event.record.timestamp <= response_record.timestamp
                        and event.watts > 0
                    ),
                    None,
                )
                if elapsed + 0.001 < grace_seconds and not safety_override and positive_assignment is None:
                    premature.extend([start_record, response_record])
                else:
                    passed += 1
                    details.extend([start_record, response_record])
                continue

            if last_timestamp < deadline:
                unresolved.append(start_record)
            else:
                unresolved.append(start_record)

        if premature:
            self.add(
                "FAIL",
                "allowance drop grace",
                "A phase-down or stop occurred before the configured allowance grace without "
                "a logged grid/telemetry/authority safety override or a positive replacement "
                "allowance.",
                premature,
            )
        if unresolved:
            self.add(
                "WARN",
                "allowance drop grace",
                "One or more grace events had no provable recovery or fallback outcome in the "
                "available log window.",
                unresolved,
            )
        if passed:
            self.add(
                "PASS",
                "allowance drop grace",
                f"Validated {passed} grace event(s): recovery, expiry fallback, or an earlier "
                "higher-priority safety/positive-allocation response was logged.",
                details,
            )

    def check_phase_switching(self) -> None:
        failed_messages = [
            record
            for record in self.records
            if "phase was not confirmed" in record.message
            or "phase switch was not confirmed" in record.message
            or "phase fallback was not confirmed" in record.message
        ]
        if failed_messages:
            self.add(
                "FAIL",
                "phase confirmation",
                "A phase transition failed Wattpilot telemetry confirmation.",
                failed_messages,
            )

        if not self.phase_actions:
            self.add(
                "NOT_OBSERVED",
                "phase switching",
                "No logged one-to-three or three-to-one phase command was observed.",
            )
            return

        report_seconds = max(
            1.0,
            (self.records[-1].timestamp - self.records[0].timestamp).total_seconds(),
        )
        normal_capacity = int(report_seconds / max(1, self.settings.min_phase_switch_seconds)) + 2
        if len(self.phase_actions) > normal_capacity:
            self.add(
                "ATTENTION",
                "phase switching frequency",
                f"Observed {len(self.phase_actions)} phase commands, above the conservative "
                f"{normal_capacity}-command expectation for this window. Safety-driven phase-downs may be valid; inspect the timeline.",
                [action.record for action in self.phase_actions],
            )

        confirmed = 0
        unconfirmed: list[LogRecord] = []
        early_phase_up: list[LogRecord] = []
        low_allowance_phase_up: list[LogRecord] = []
        last_timestamp = self.records[-1].timestamp

        for action in self.phase_actions:
            confirmation = next(
                (
                    record
                    for record, phase in self.phase_confirmations
                    if phase == action.target_phase
                    and action.record.timestamp <= record.timestamp
                    <= action.record.timestamp
                    + timedelta(seconds=self.settings.startup_grace_seconds + 5)
                ),
                None,
            )
            if confirmation is not None:
                confirmed += 1
            elif (
                last_timestamp - action.record.timestamp
            ).total_seconds() >= self.settings.startup_grace_seconds:
                unconfirmed.append(action.record)
            else:
                unconfirmed.append(action.record)

            if action.target_phase == 3:
                prior_allowance = self._allowance_at_or_before(
                    action.record.timestamp
                )
                if (
                    prior_allowance is not None
                    and prior_allowance.watts + 1 < self.settings.three_phase_start_w
                ):
                    low_allowance_phase_up.extend(
                        [prior_allowance.record, action.record]
                    )
                prior_waits = [
                    item
                    for item in self.phase_up_waits
                    if item[0].timestamp <= action.record.timestamp
                    and (
                        action.record.timestamp - item[0].timestamp
                    ).total_seconds()
                    <= self.settings.min_phase_switch_seconds + 30
                ]
                if prior_waits:
                    wait_record, stable_seconds, required_seconds = prior_waits[-1]
                    candidate_start = wait_record.timestamp - timedelta(seconds=stable_seconds)
                    elapsed = (action.record.timestamp - candidate_start).total_seconds()
                    # The worker runs on five-second cycles; allow one cycle of
                    # timestamp/log ordering tolerance, never a material early switch.
                    if elapsed < required_seconds - 5:
                        early_phase_up.extend([wait_record, action.record])
                elif self.settings.log_level in {"TRACE", "DEBUG", "APP_DEBUG"}:
                    self.add(
                        "WARN",
                        "phase timing",
                        "A PV phase-up command had no matching stability-countdown evidence in "
                        "the selected-day log window.",
                        [action.record],
                    )

        if early_phase_up:
            self.add(
                "FAIL",
                "phase timing",
                "A one-to-three command appears earlier than MinPhaseSwitchSeconds allowed.",
                early_phase_up,
            )
        if low_allowance_phase_up:
            self.add(
                "FAIL",
                "phase threshold",
                "A one-to-three command was logged without the configured three-phase PV "
                "allowance threshold.",
                low_allowance_phase_up,
            )
        if unconfirmed:
            self.add(
                "WARN",
                "phase confirmation",
                "One or more phase commands had no matching confirmation in the selected log "
                "window. This may be an incomplete end-of-day window, but is not a proven pass.",
                unconfirmed,
            )
        if confirmed:
            self.add(
                "PASS",
                "phase switching",
                f"{confirmed}/{len(self.phase_actions)} logged phase command(s) received matching "
                "Wattpilot telemetry confirmation.",
                [record for record, _phase in self.phase_confirmations],
            )

    def check_battery_assist(self) -> None:
        if not self.assist_samples:
            self.add(
                "NOT_OBSERVED",
                "battery assist",
                "No battery-assist interval was observed; its configured bounds were not "
                "exercised on this date.",
            )
            return

        violations = [
            record
            for record, shortfall, elapsed in self.assist_samples
            if shortfall > self.settings.battery_assist_max_shortfall_w + 1
            or elapsed > self.settings.battery_assist_max_seconds + 1
        ]
        if violations:
            self.add(
                "FAIL",
                "battery assist",
                "Logged battery assist exceeded configured shortfall or duration bounds.",
                violations,
            )
        else:
            max_shortfall = max(sample[1] for sample in self.assist_samples)
            max_elapsed = max(sample[2] for sample in self.assist_samples)
            self.add(
                "PASS",
                "battery assist",
                f"Battery assist stayed within configured bounds: maximum {max_shortfall:.0f} W "
                f"shortfall and {max_elapsed:.0f} s elapsed observed.",
            )

    def _charging_near(self, timestamp: datetime, seconds: int = 10) -> bool:
        if not self._charge_timestamps:
            return False
        index = bisect_left(self._charge_timestamps, timestamp)
        for candidate_index in (index - 1, index):
            if 0 <= candidate_index < len(self._charge_timestamps):
                candidate = self._charge_timestamps[candidate_index]
                if abs((candidate - timestamp).total_seconds()) <= seconds:
                    return True
        return False

    def check_grid_import(self) -> None:
        if self.settings.allow_grid_charging:
            self.add(
                "INFO",
                "grid import",
                "AllowGridCharging=true; the no-grid sustained-import audit is not applicable.",
            )
            return

        charging_samples = []
        for sample in self.grid_samples:
            sample.charging_nearby = self._charging_near(sample.record.timestamp)
            if sample.charging_nearby:
                charging_samples.append(sample)

        if not charging_samples:
            self.add(
                "NOT_OBSERVED",
                "grid import",
                "No per-phase grid samples could be correlated with charging evidence.",
            )
            return

        over_threshold = [
            sample
            for sample in charging_samples
            if sample.import_w > self.settings.grid_import_stop_w
        ]
        if not over_threshold:
            max_import = max(sample.import_w for sample in charging_samples)
            self.add(
                "PASS",
                "grid import",
                f"No charging-correlated grid sample exceeded {self.settings.grid_import_stop_w:.0f} W; "
                f"maximum observed import was {max_import:.0f} W.",
            )
            return

        sustained_runs: list[list[GridSample]] = []
        current_run: list[GridSample] = []
        for sample in charging_samples:
            if sample.import_w > self.settings.grid_import_stop_w:
                if current_run and (
                    sample.record.timestamp - current_run[-1].record.timestamp
                ).total_seconds() > 10:
                    sustained_runs.append(current_run)
                    current_run = []
                current_run.append(sample)
            elif current_run:
                sustained_runs.append(current_run)
                current_run = []
        if current_run:
            sustained_runs.append(current_run)

        sustained = [
            run
            for run in sustained_runs
            if len(run) > 1
            and (
                run[-1].record.timestamp - run[0].record.timestamp
            ).total_seconds()
            >= self.settings.grid_import_stop_seconds
        ]
        if not sustained:
            self.add(
                "INFO",
                "grid import",
                f"Observed {len(over_threshold)} short grid-import sample(s) above the threshold, "
                "but none persisted for GridImportStopSeconds.",
                [sample.record for sample in over_threshold],
            )
            return

        missing_guard: list[LogRecord] = []
        for run in sustained:
            end = run[-1].record.timestamp + timedelta(seconds=10)
            guard = self._records_between(
                run[0].record.timestamp, end, self.grid_guard_actions
            )
            if not guard:
                missing_guard.append(run[-1].record)

        if missing_guard:
            self.add(
                "FAIL",
                "grid import",
                "Sustained charging-correlated grid import exceeded configured limits without a "
                "matching logged grid-guard response.",
                missing_guard,
            )
        else:
            self.add(
                "PASS",
                "grid import",
                "Every sustained over-threshold grid-import interval had a logged grid-guard "
                "phase-down or stop response.",
                self.grid_guard_actions,
            )

    def check_authority_and_manual(self) -> None:
        unsafe_authority: list[LogRecord] = []
        auto_control_records = [
            record for record, _stable_seconds in self.start_records
        ]
        auto_control_records.extend(
            record for record, _amps, _phase in self.current_adjustments
        )
        auto_control_records.extend(action.record for action in self.phase_actions)
        auto_control_records.extend(
            record for record, _shortfall, _elapsed in self.assist_samples
        )
        for blocked in self.authority_blocked:
            next_valid = next(
                (
                    record
                    for record in self.authority_valid
                    if record.timestamp > blocked.timestamp
                ),
                None,
            )
            end = next_valid.timestamp if next_valid else self.records[-1].timestamp
            blocked_control = next(
                (
                    record
                    for record in auto_control_records
                    if record.timestamp > blocked.timestamp
                    and (next_valid is None or record.timestamp < end)
                ),
                None,
            )
            if blocked_control:
                unsafe_authority.extend([blocked, blocked_control])

        if unsafe_authority:
            self.add(
                "FAIL",
                "command authority",
                "An Auto/Eco start, current, phase, or battery-assist action was logged while "
                "command authority was blocked.",
                unsafe_authority,
            )
        elif self.authority_blocked:
            self.add(
                "PASS",
                "command authority",
                "Blocked command-authority state(s) were observed without subsequent es-ESS "
                "Auto/Eco control actions before authority was validated.",
                self.authority_blocked,
            )
        elif self.authority_valid:
            self.add(
                "PASS",
                "command authority",
                "Sole-owner Auto/Eco command authority was explicitly validated in the log.",
                self.authority_valid,
            )
        else:
            self.add(
                "INFO",
                "command authority",
                "No command-authority transition was logged today; authority may have remained "
                "unchanged across midnight.",
            )

        manual_violations: list[LogRecord] = []
        for boundary in self.manual_boundaries:
            next_auto = next(
                (
                    record
                    for record in self.authority_valid
                    if record.timestamp > boundary.timestamp
                ),
                None,
            )
            end = next_auto.timestamp if next_auto else self.records[-1].timestamp
            first_control = bisect_right(
                self._manual_control_timestamps, boundary.timestamp
            )
            last_control = bisect_right(self._manual_control_timestamps, end)
            for record in self._manual_control_records[first_control:last_control]:
                seconds_after_boundary = (
                    record.timestamp - boundary.timestamp
                ).total_seconds()
                approved_release = (
                    seconds_after_boundary <= 10
                    and "frc=" not in record.message.lower()
                    and (
                        re.search(r"\bpsm=0\b", record.message, re.IGNORECASE)
                        or re.search(
                            r'"key"\s*:\s*"psm".*?"value"\s*:\s*0',
                            record.message,
                            re.IGNORECASE,
                        )
                        or re.search(
                            rf"\bamp={self.settings.max_current_per_phase}\b",
                            record.message,
                            re.IGNORECASE,
                        )
                        or re.search(
                            rf'"key"\s*:\s*"amp".*?"value"\s*:\s*{self.settings.max_current_per_phase}',
                            record.message,
                            re.IGNORECASE,
                        )
                    )
                )
                if approved_release:
                    continue
                manual_violations.append(record)

        if manual_violations:
            self.add(
                "FAIL",
                "Manual ownership",
                "Auto/Eco control activity was logged after Manual selection and before the next "
                "validated Auto boundary.",
                manual_violations,
            )
        elif self.manual_boundaries:
            self.add(
                "PASS",
                "Manual ownership",
                "Manual boundary event(s) had no subsequent logged Auto/Eco control activity "
                "before the next validated Auto boundary.",
                self.manual_boundaries,
            )
        else:
            self.add(
                "NOT_OBSERVED",
                "Manual ownership",
                "No Manual-mode boundary was exercised on this date.",
            )

    def _mode_at(self, timestamp: datetime) -> str:
        boundaries: list[tuple[datetime, str]] = []
        boundaries.extend((record.timestamp, "Manual") for record in self.manual_boundaries)
        boundaries.extend((record.timestamp, "Auto") for record in self.authority_valid)
        prior = [item for item in boundaries if item[0] <= timestamp]
        return max(prior, key=lambda item: item[0])[1] if prior else "Unknown"

    @staticmethod
    def _stop_reason(record: LogRecord) -> Optional[str]:
        if not any(marker in record.message for marker in STOP_MARKERS):
            return None
        message = record.message.lower()
        for marker, reason in STOP_REASONS:
            if marker in message:
                return reason
        return None

    def build_sessions(self) -> list[ChargingSession]:
        if not self.charge_records:
            return []

        groups: list[list[LogRecord]] = [[self.charge_records[0]]]
        for record in self.charge_records[1:]:
            prior = groups[-1][-1]
            first_stop = bisect_right(self._stop_timestamps, prior.timestamp)
            stop_between = (
                first_stop < len(self._stop_timestamps)
                and self._stop_timestamps[first_stop] < record.timestamp
            )
            if stop_between or (record.timestamp - prior.timestamp).total_seconds() > 300:
                groups.append([record])
            else:
                groups[-1].append(record)

        sessions: list[ChargingSession] = []
        for index, group in enumerate(groups):
            start = group[0].timestamp
            last_charge = group[-1].timestamp
            next_start = groups[index + 1][0].timestamp if index + 1 < len(groups) else None
            search_end = min(
                next_start if next_start else self.records[-1].timestamp,
                last_charge + timedelta(minutes=5),
            )
            stop_index = bisect_left(self._stop_timestamps, last_charge)
            stop_record = (
                self._stop_records[stop_index]
                if stop_index < len(self._stop_records)
                and self._stop_timestamps[stop_index] <= search_end
                else None
            )
            end = stop_record.timestamp if stop_record else last_charge
            phases = sorted(
                {
                    phase
                    for _record, phase in self.phase_confirmations
                    if start <= _record.timestamp <= end
                }
                | {
                    phase
                    for _record, _amps, phase in self.current_adjustments
                    if start <= _record.timestamp <= end
                }
                | {
                    event.phase
                    for event in self.allowances
                    if event.phase is not None and start <= event.record.timestamp <= end
                }
            )
            currents = [
                amps
                for record, amps, _phase in self.current_adjustments
                if start <= record.timestamp <= end
            ]
            switches = [
                f"{action.record.timestamp.isoformat()} -> {action.target_phase} phase ({action.reason})"
                for action in self.phase_actions
                if start <= action.record.timestamp <= end
            ]
            rare = sorted(
                {
                    int(data["status"])
                    for record, data in self.rare_entries
                    if start <= record.timestamp <= end
                }
            )
            evidence = [group[0].evidence(), group[-1].evidence()]
            if stop_record:
                evidence.append(stop_record.evidence())
            sessions.append(
                ChargingSession(
                    start=start.isoformat(),
                    end=end.isoformat(),
                    mode=self._mode_at(start),
                    phases=phases,
                    current_adjustments_a=currents,
                    phase_switches=switches,
                    stop_reason=(
                        self._stop_reason(stop_record)
                        if stop_record is not None
                        else "not observable in selected window"
                    ),
                    battery_assist_events=len(
                        [
                            record
                            for record, _shortfall, _elapsed in self.assist_samples
                            if start <= record.timestamp <= end
                        ]
                    ),
                    grid_guard_events=len(
                        [record for record in self.grid_guard_actions if start <= record.timestamp <= end]
                    ),
                    stale_telemetry_events=len(
                        [record for record in self.stale_telemetry_records if start <= record.timestamp <= end]
                    ),
                    rare_statuses=rare,
                    restart_during_session=any(
                        start <= record.timestamp <= end for record in self.restart_records
                    ),
                    evidence=evidence,
                )
            )
        return sessions

    def build_rare_statuses(self) -> list[RareStatusSummary]:
        summaries: list[RareStatusSummary] = []
        for status, default_name in RARE_STATUS_NAMES.items():
            entries = [item for item in self.rare_entries if int(item[1]["status"]) == status]
            exits = [item for item in self.rare_exits if int(item[1]["status"]) == status]
            if not entries:
                summaries.append(
                    RareStatusSummary(
                        status=status,
                        protocol_name=default_name,
                        occurrences=0,
                        observed_seconds=0,
                        selected_states=[],
                        result="NOT OBSERVED",
                    )
                )
                continue

            selected_states = sorted({data["state"] for _record, data in entries})
            total_seconds = sum(int(data["seconds"]) for _record, data in exits)
            evidence = [record.evidence() for record, _data in entries + exits][:5]
            unexpected = [
                record
                for record, data in entries
                if data["state"]
                not in {
                    "charging",
                    "transport_unavailable",
                    "command_authority_blocked",
                    "grid_telemetry_unsafe",
                    "grid_import_phase_down",
                    "grid_import_stop",
                    "pending_phase_switch",
                    "disconnected",
                }
            ]
            if unexpected:
                result = "ANOMALY"
                self.add(
                    "FAIL",
                    "rare charging statuses",
                    f"Rare status {status} entered an unexpected selected state.",
                    unexpected,
                )
            elif len(exits) < len(entries):
                result = "INCOMPLETE"
                self.add(
                    "WARN",
                    "rare charging statuses",
                    f"Rare status {status} has an entry without a matching exit in the selected window.",
                    [record for record, _data in entries],
                )
            else:
                result = "ATTENTION"
                self.add(
                    "ATTENTION",
                    "rare charging statuses",
                    f"Rare status {status} was observed and followed a recognized active/safety path.",
                    [record for record, _data in entries],
                )
            summaries.append(
                RareStatusSummary(
                    status=status,
                    protocol_name=entries[0][1].get("name") or default_name,
                    occurrences=len(entries),
                    observed_seconds=total_seconds,
                    selected_states=selected_states,
                    result=result,
                    evidence=evidence,
                )
            )
        return summaries

    def run(self) -> AuditResult:
        self.collect()
        self.check_inputs()
        self.check_failures()
        self.check_runtime_health()
        self.check_commissioning_profile()
        self.check_charging()
        self.check_current_bounds()
        self.check_allowance()
        self.check_allowance_grace()
        self.check_phase_switching()
        self.check_battery_assist()
        self.check_grid_import()
        self.check_authority_and_manual()
        self.check_safety_interventions()
        rare_statuses = self.build_rare_statuses()
        sessions = self.build_sessions()

        statuses = {finding.status for finding in self.findings}
        if "FAIL" in statuses:
            overall = "ANOMALY"
            exit_code = EXIT_FAIL
        elif "WARN" in statuses:
            overall = "INCOMPLETE"
            exit_code = EXIT_INCOMPLETE
        elif "ATTENTION" in statuses:
            overall = "ATTENTION"
            exit_code = EXIT_INCOMPLETE
        else:
            overall = "GOOD"
            exit_code = EXIT_PASS

        metrics = {
            "records": len(self.records),
            "charging_records": len(self.charge_records),
            "allowance_assignments": len(self.allowances),
            "zero_watt_three_phase_assignments": len(
                [
                    event
                    for event in self.allowances
                    if event.watts <= 0 and event.phase == 3
                ]
            ),
            "allowance_grace_events": len(self.grace_starts),
            "phase_commands": len(self.phase_actions),
            "phase_confirmations": len(self.phase_confirmations),
            "current_adjustments": len(self.current_adjustments),
            "battery_assist_samples": len(self.assist_samples),
            "grid_samples": len(self.grid_samples),
            "service_initializations": len(self.restart_records),
            "wattpilot_reconnect_events": len(self.reconnect_records),
            "charging_sessions": len(sessions),
            "rare_status_occurrences": sum(
                summary.occurrences for summary in rare_statuses
            ),
        }
        recommendations: list[str] = []
        if overall == "ANOMALY":
            recommendations.append(
                "Inspect the cited raw records before relying on unattended Auto/Eco charging."
            )
        if overall == "INCOMPLETE":
            if self.audit_input.partial_window:
                recommendations.append(
                    "Use this partial result for current evidence only, then rerun with --date yesterday after the calendar day closes."
                )
            else:
                recommendations.append(
                    "Resolve the listed evidence gaps and rerun the report over a complete APP_DEBUG window."
                )
        if overall == "ATTENTION":
            recommendations.append(
                "Review the recorded safety interventions or unusual transitions; they are not automatically controller defects."
            )
        if not sessions:
            recommendations.append(
                "No charging session was reconstructed; run the report for a complete day that includes charging if session validation is required."
            )
        recommendations.append(
            "Use es-ess-health-monitor.sh for a live snapshot; this report is the historical/end-of-day analyzer."
        )
        limitations = [
            "No anomaly detected means only that no anomaly was found in the selected available evidence; it does not prove the entire charging session was perfect.",
            "Logs do not independently measure historical grid or battery energy. Current D-Bus values are snapshots, not historical storage.",
            "Charging sessions and stop reasons are reconstructed approximately from transition evidence and may span an evidence gap or log rotation.",
            "NOT_OBSERVED means a mechanism was not exercised, not that it failed.",
        ]
        if self.audit_input.partial_window:
            limitations.insert(
                0,
                "This is a partial current-day report. It excludes activity before the first available record and after the analysis cutoff and therefore cannot conclude GOOD.",
            )
        return AuditResult(
            schema=SCHEMA_VERSION,
            overall=overall,
            exit_code=exit_code,
            inputs=self.audit_input,
            configuration=self.settings,
            metrics=metrics,
            findings=self.findings,
            sessions=sessions,
            rare_statuses=rare_statuses,
            current_snapshot=self.current_snapshot,
            recommendations=recommendations,
            limitations=limitations,
        )


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}"


def _summarize_current_adjustments(values: list[int]) -> str:
    if not values:
        return "none"
    transitions = [values[0]]
    for value in values[1:]:
        if value != transitions[-1]:
            transitions.append(value)
    display = transitions[:20]
    suffix = f", ... ({len(transitions)} transitions)" if len(transitions) > 20 else ""
    return (
        f"{len(values)} samples; range={min(values)}..{max(values)} A; "
        f"transitions={display}{suffix}"
    )


def render_human(result: AuditResult) -> str:
    lines = [
        "es-ESS daily report",
        "===================",
        f"OVERALL: {result.overall}",
        f"Window status: {'PARTIAL - TODAY IN PROGRESS' if result.inputs.partial_window else 'COMPLETE REQUESTED WINDOW'}",
        f"Requested period: {result.inputs.window_start} to {result.inputs.window_end}",
        f"Report timezone:  {result.inputs.report_timezone or 'unavailable'}",
        f"Analysis cutoff:  {result.inputs.analysis_cutoff or result.inputs.window_end}",
        f"Evidence period:  {result.inputs.first_timestamp or 'unavailable'} to "
        f"{result.inputs.last_timestamp or 'unavailable'}",
        f"Evidence duration: {_format_duration(result.inputs.evidence_duration_seconds)}; "
        f"elapsed requested period: {_format_duration(result.inputs.elapsed_window_seconds)}; "
        f"span coverage: {result.inputs.evidence_span_percent:.1f}%",
        f"Logs:    {', '.join(result.inputs.log_files) or result.inputs.log_file}",
        f"Config:  {result.inputs.config_file}",
        f"Records: {result.inputs.dated_log_lines}",
        f"Processing time: log load {result.inputs.log_load_seconds:.2f}s; "
        f"analysis {result.inputs.analysis_seconds:.2f}s",
        "",
        "Sanitized configuration",
        "-----------------------",
        f"LogLevel={result.configuration.log_level}",
        f"EnabledServices={','.join(result.configuration.enabled_services) or 'unavailable'}",
        f"Current={result.configuration.min_current_per_phase}.."
        f"{result.configuration.max_current_per_phase} A per phase",
        f"ThreePhaseStart/Stop={result.configuration.three_phase_start_w:.0f}/"
        f"{result.configuration.three_phase_stop_w:.0f} W",
        f"MinOnOff/MinPhaseSwitch={result.configuration.min_on_off_seconds}/"
        f"{result.configuration.min_phase_switch_seconds} s",
        f"AllowanceFresh/DropGrace={result.configuration.allowance_fresh_seconds}/"
        f"{result.configuration.allowance_drop_grace_seconds} s",
        f"BatteryAssistMax={result.configuration.battery_assist_max_shortfall_w:.0f} W/"
        f"{result.configuration.battery_assist_max_seconds} s",
        f"AllowGridCharging={str(result.configuration.allow_grid_charging).lower()} "
        f"GridImportStop={result.configuration.grid_import_stop_w:.0f} W/"
        f"{result.configuration.grid_import_stop_seconds} s",
        "",
        "Current state (read-only snapshot)",
        "----------------------------------",
        f"Captured={result.current_snapshot.captured_at}",
        f"Service={result.current_snapshot.service_state}",
        "WattpilotExternalDependencies="
        f"{result.current_snapshot.dependencies}",
    ]
    if result.inputs.full_window_available_at:
        lines.insert(
            8,
            "Full calendar-day report available after: "
            f"{result.inputs.full_window_available_at}",
        )
    if result.current_snapshot.dbus_values:
        for path, value in sorted(result.current_snapshot.dbus_values.items()):
            lines.append(f"{path}={value}")
    for note in result.current_snapshot.notes:
        lines.append(f"NOTE: {note}")

    lines.extend(["", "Charging sessions", "-----------------"])
    if not result.sessions:
        lines.append("No charging session was reconstructed from this window.")
    for index, session in enumerate(result.sessions, 1):
        lines.append(
            f"Session {index}: {session.start} to {session.end}; mode={session.mode}; "
            f"phases={session.phases or ['unknown']}; stop={session.stop_reason}"
        )
        lines.append(
            "  current adjustments="
            f"{_summarize_current_adjustments(session.current_adjustments_a)}; phase switches="
            f"{len(session.phase_switches)}; battery assist={session.battery_assist_events}; "
            f"grid guards={session.grid_guard_events}; stale telemetry="
            f"{session.stale_telemetry_events}; restart={session.restart_during_session}"
        )
        for evidence in session.evidence:
            lines.append(f"  - {evidence}")

    lines.extend(["", "Rare charging statuses", "----------------------"])
    for summary in result.rare_statuses:
        lines.append(
            f"[{summary.result}] {summary.status} {summary.protocol_name}: "
            f"occurrences={summary.occurrences}, observed_seconds="
            f"{summary.observed_seconds}, selected_states={summary.selected_states or ['none']}"
        )

    sections = (
        ("Anomalies", {"FAIL"}),
        ("Safety interventions and unusual events", {"ATTENTION"}),
        ("Evidence gaps", {"WARN"}),
        ("Other checks", {"PASS", "INFO", "NOT_OBSERVED"}),
    )
    for title, statuses in sections:
        lines.extend(["", title, "-" * len(title)])
        selected = [finding for finding in result.findings if finding.status in statuses]
        if not selected:
            lines.append("None.")
        for finding in selected:
            lines.append(f"[{finding.status}] {finding.check}: {finding.message}")
            for evidence in finding.evidence:
                lines.append(f"  - {evidence}")

    lines.extend(["", "Metrics", "-------"])
    for key, value in result.metrics.items():
        lines.append(f"{key}: {value}")

    lines.extend(["", "Limitations", "-----------"])
    for limitation in result.limitations:
        lines.append(f"- {limitation}")
    lines.extend(["", "Recommendations", "---------------"])
    for recommendation in result.recommendations:
        lines.append(f"- {recommendation}")
    lines.append(f"Exit code: {result.exit_code}")
    return "\n".join(lines)


def render_prerequisite(
    reason: str,
    config_file: str,
    json_output: bool,
) -> str:
    instructions = prerequisite_instructions(reason, config_file)
    if json_output:
        return json.dumps(
            {
                "schema": SCHEMA_VERSION,
                "overall": "INCOMPLETE",
                "exit_code": EXIT_INCOMPLETE,
                "stopped": True,
                "reason": reason,
                "instructions": instructions[1:],
            },
            indent=2,
            sort_keys=True,
        )
    return "\n".join(["es-ESS daily report", "===================", "OVERALL: INCOMPLETE", ""] + instructions)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze complete es-ESS APP_DEBUG history without changing production state."
    )
    window = parser.add_mutually_exclusive_group()
    window.add_argument(
        "--date",
        help="Calendar day: today, yesterday, or YYYY-MM-DD (default: yesterday).",
    )
    window.add_argument(
        "--hours",
        type=float,
        help="Rolling history window; must be at least 24 hours.",
    )
    parser.add_argument(
        "--log-file",
        help="Explicit log file. By default current.log and dated rotations are discovered.",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_FILE)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of the human report.",
    )
    parser.add_argument(
        "--no-current-snapshot",
        action="store_true",
        help=(
            "Skip optional read-only service/runtime snapshots; the required "
            "read-only Venus timezone query still runs."
        ),
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable the stderr progress bar (useful for automation).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    progress = ProgressReporter(
        enabled=not args.no_progress and sys.stderr.isatty()
    )
    progress.update(0, "Reading configuration")
    config_path = Path(args.config)
    try:
        settings, config_warnings = load_settings(config_path)
    except ConfigurationReadError as exc:
        progress.stop("Stopped: configuration read failed")
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    if settings.log_level not in VERBOSE_LOG_LEVELS:
        reason = (
            f"[Common] LogLevel is {settings.log_level or 'missing'}, but APP_DEBUG "
            "or a more verbose level is required."
        )
        progress.stop("Stopped: APP_DEBUG required")
        print(render_prerequisite(reason, str(config_path), args.json))
        return EXIT_INCOMPLETE

    progress.update(0, "Reading Venus timezone")
    timezone_name, report_timezone, timezone_warning = resolve_report_timezone()
    if timezone_warning is not None:
        config_warnings.append(timezone_warning)
    report_now = datetime.now(report_timezone)

    try:
        label, window_start, window_end, window_type = resolve_window(
            args.date,
            args.hours,
            now=report_now,
            local_timezone=report_timezone,
        )
    except ValueError as exc:
        progress.stop("Stopped: invalid report window")
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    progress.update(1, "Discovering log files")
    base_log = Path(args.log_file or DEFAULT_LOG_FILE)
    log_paths = [base_log] if args.log_file else discover_log_files(base_log)
    if not log_paths:
        reason = f"No current or rotated es-ESS log files were found at {base_log}."
        progress.stop("Stopped: logs not found")
        print(render_prerequisite(reason, str(config_path), args.json))
        return EXIT_INCOMPLETE
    unreadable = [str(path) for path in log_paths if not path.is_file()]
    if unreadable:
        progress.stop("Stopped: unreadable log input")
        print(f"ERROR: log file is not readable: {', '.join(unreadable)}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    partial_today = (
        window_type == "calendar-day"
        and window_start.date() == report_now.date()
        and window_end > report_now
    )
    analysis_cutoff = report_now if partial_today else window_end

    log_load_started = time.monotonic()
    try:
        records, total_lines = load_log_window(
            log_paths,
            window_start,
            analysis_cutoff,
            progress_callback=lambda current, total, name: progress.update(
                1,
                f"Loading logs: {name} ({current}/{total} bytes)",
                current,
                total,
            ),
        )
    except OSError as exc:
        progress.stop("Stopped: log read failed")
        print(f"ERROR: cannot read log file: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    log_load_seconds = time.monotonic() - log_load_started

    progress.update(2, "Validating evidence coverage")
    if partial_today:
        if not records:
            progress.stop("Stopped: no current-day records")
            print(
                render_prerequisite(
                    "No parseable es-ESS records exist yet for today.",
                    str(config_path),
                    args.json,
                )
            )
            return EXIT_INCOMPLETE
        if not any(record.level in VERBOSE_LOG_LEVELS for record in records):
            progress.stop("Stopped: no diagnostic records")
            print(
                render_prerequisite(
                    "No APP_DEBUG/DEBUG/TRACE record exists in today's available evidence.",
                    str(config_path),
                    args.json,
                )
            )
            return EXIT_INCOMPLETE
    else:
        problem = coverage_problem(records, window_start, window_end)
        if problem:
            progress.stop("Stopped: incomplete historical coverage")
            print(render_prerequisite(problem, str(config_path), args.json))
            return EXIT_INCOMPLETE
        diagnostic_problem = diagnostic_coverage_problem(
            records, window_start, window_end
        )
        if diagnostic_problem:
            progress.stop("Stopped: incomplete APP_DEBUG coverage")
            print(
                render_prerequisite(
                    diagnostic_problem, str(config_path), args.json
                )
            )
            return EXIT_INCOMPLETE

    evidence_seconds, elapsed_seconds, evidence_percent = (
        calculate_coverage_metadata(records, window_start, analysis_cutoff)
    )

    progress.update(3, "Capturing read-only current snapshot")
    snapshot = (
        CurrentSnapshot(
            captured_at=datetime.now().isoformat(),
            service_state="not captured",
            dependencies="not captured",
            dbus_values={},
            available=False,
            notes=["current snapshot disabled by --no-current-snapshot"],
        )
        if args.no_current_snapshot
        else capture_current_snapshot(
            progress_callback=lambda current, total, detail: progress.update(
                3,
                f"Current snapshot: {detail}",
                current,
                total,
            )
        )
    )
    audit_input = AuditInput(
        target_date=label,
        log_file=str(base_log),
        config_file=str(config_path),
        window_type=window_type,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        report_timezone=timezone_name,
        log_files=[str(path) for path in log_paths],
        total_log_lines=total_lines,
        dated_log_lines=len(records),
        first_timestamp=records[0].timestamp.isoformat() if records else None,
        last_timestamp=records[-1].timestamp.isoformat() if records else None,
        partial_window=partial_today,
        analysis_cutoff=analysis_cutoff.isoformat(),
        evidence_duration_seconds=evidence_seconds,
        elapsed_window_seconds=elapsed_seconds,
        evidence_span_percent=evidence_percent,
        full_window_available_at=(
            window_end.isoformat() if partial_today else None
        ),
        log_load_seconds=log_load_seconds,
    )
    progress.update(4, "Analyzing controller evidence")
    analysis_started = time.monotonic()
    result = EsEssDailyReport(
        records, settings, audit_input, config_warnings, snapshot
    ).run()
    audit_input.analysis_seconds = time.monotonic() - analysis_started
    progress.update(5, "Rendering report")
    if args.json:
        output = json.dumps(result.to_dict(), indent=2, sort_keys=True)
    else:
        output = render_human(result)
    progress.finish()
    print(output)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
