"""Pure parsing for validated Wattpilot vehicle-compatibility telemetry.

This module is command-free.  It interprets an already-received full-status
dictionary and never owns transport, D-Bus, MQTT, configuration, or mutable
controller state.
"""

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple


VALIDATED_FIRMWARE = "42.5"
MAX_DURATION_MS = 2_147_483_647


def _strict_bool(properties, key):
    value = properties.get(key)
    return value if type(value) is bool else None


def _bounded_int(properties, key, minimum=0, maximum=MAX_DURATION_MS):
    value = properties.get(key)
    if type(value) is not int or value < minimum or value > maximum:
        return None
    return value


@dataclass(frozen=True)
class VehicleCompatibilitySnapshot:
    firmware_valid: bool
    full_status_ready: bool
    minimum_current_a: Optional[int]
    allow_charge_pause: Optional[bool]
    minimum_charging_interval_ms: Optional[int]
    minimum_charge_pause_duration_ms: Optional[int]
    minimum_charge_pause_ends_at_ms: Optional[int]
    minimum_charge_time_ms: Optional[int]
    simulate_unplugging_short: Optional[bool]
    simulate_unplugging_always: Optional[bool]
    simulate_unplugging_duration_ms: Optional[int]
    minimum_phase_wish_switch_time_ms: Optional[int]
    minimum_phase_toggle_wait_time_ms: Optional[int]
    model_status_raw: Optional[int]
    missing_fields: Tuple[str, ...]
    invalid_fields: Tuple[str, ...]

    @property
    def minimum_current_valid(self):
        return bool(
            self.firmware_valid
            and self.full_status_ready
            and self.minimum_current_a is not None
        )

    @property
    def diagnostics_literal(self):
        if not self.firmware_valid:
            return "Unavailable: firmware not validated"
        if not self.full_status_ready:
            return "Unavailable: full status pending"
        if self.invalid_fields:
            return "Invalid fields: {0}".format(",".join(self.invalid_fields))
        if self.missing_fields:
            return "Partial: missing {0}".format(",".join(self.missing_fields))
        return "Validated"

    def effective_minimum_current(self, configured_minimum, effective_maximum):
        if not self.minimum_current_valid:
            return None
        configured = int(configured_minimum)
        maximum = int(effective_maximum)
        effective = max(configured, int(self.minimum_current_a))
        return effective if effective <= maximum else None


def parse_vehicle_compatibility(properties, firmware, full_status_ready):
    """Parse one immutable compatibility snapshot from Wattpilot status."""
    source = properties if isinstance(properties, Mapping) else {}
    firmware_valid = str(firmware) == VALIDATED_FIRMWARE
    full_status_ready = bool(full_status_ready)

    parsers = {
        "mca": lambda: _bounded_int(source, "mca", 6, 32),
        "acp": lambda: _strict_bool(source, "acp"),
        "mci": lambda: _bounded_int(source, "mci"),
        "mcpd": lambda: _bounded_int(source, "mcpd"),
        "fmt": lambda: _bounded_int(source, "fmt"),
        "su": lambda: _strict_bool(source, "su"),
        "sua": lambda: _strict_bool(source, "sua"),
        "sumd": lambda: _bounded_int(source, "sumd"),
        "mpwst": lambda: _bounded_int(source, "mpwst"),
        "mptwt": lambda: _bounded_int(source, "mptwt"),
        "modelStatus": lambda: _bounded_int(source, "modelStatus", 0, 255),
    }
    parsed = {}
    missing = []
    invalid = []
    for key, parser in parsers.items():
        if key not in source:
            missing.append(key)
            parsed[key] = None
            continue
        parsed[key] = parser()
        if parsed[key] is None:
            invalid.append(key)

    pause_ends = None
    if "mcpea" not in source:
        missing.append("mcpea")
    elif source.get("mcpea") is not None:
        pause_ends = _bounded_int(source, "mcpea")
        if pause_ends is None:
            invalid.append("mcpea")

    return VehicleCompatibilitySnapshot(
        firmware_valid=firmware_valid,
        full_status_ready=full_status_ready,
        minimum_current_a=parsed["mca"],
        allow_charge_pause=parsed["acp"],
        minimum_charging_interval_ms=parsed["mci"],
        minimum_charge_pause_duration_ms=parsed["mcpd"],
        minimum_charge_pause_ends_at_ms=pause_ends,
        minimum_charge_time_ms=parsed["fmt"],
        simulate_unplugging_short=parsed["su"],
        simulate_unplugging_always=parsed["sua"],
        simulate_unplugging_duration_ms=parsed["sumd"],
        minimum_phase_wish_switch_time_ms=parsed["mpwst"],
        minimum_phase_toggle_wait_time_ms=parsed["mptwt"],
        model_status_raw=parsed["modelStatus"],
        missing_fields=tuple(sorted(missing)),
        invalid_fields=tuple(sorted(invalid)),
    )
