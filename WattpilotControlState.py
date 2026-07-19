from dataclasses import dataclass
from enum import Enum


PROTOCOL_CHARGING_STATUS_VALUES = frozenset([8, 9, 10, 11, 13, 14])
ACTIVE_CHARGING_STATUS_VALUES = frozenset([3, 12, 15, 19, 20]).union(
    PROTOCOL_CHARGING_STATUS_VALUES
)
NOT_CHARGING_STATUS_VALUES = frozenset([4, 5, 6, 16, 17, 18, 22, 24])


class WattpilotControlState(Enum):
    TRANSPORT_UNAVAILABLE = "transport_unavailable"
    COMMAND_AUTHORITY_BLOCKED = "command_authority_blocked"
    SITE_CURRENT_TELEMETRY_UNSAFE = "site_current_telemetry_unsafe"
    SITE_CURRENT_LIMIT_STOP = "site_current_limit_stop"
    GRID_TELEMETRY_UNSAFE = "grid_telemetry_unsafe"
    GRID_IMPORT_PHASE_DOWN = "grid_import_phase_down"
    GRID_IMPORT_STOP = "grid_import_stop"
    PENDING_PHASE_SWITCH = "pending_phase_switch"
    DISCONNECTED = "disconnected"
    CHARGING = "charging"
    NOT_CHARGING = "not_charging"
    EXTERNAL_LOW_PRICE = "external_low_price"
    PHASE_SWITCHING = "phase_switching"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ControlStateInputs:
    transport_unavailable: bool = False
    auto_mode: bool = False
    command_authority_ok: bool = True
    site_current_telemetry_fresh: bool = True
    site_current_limit_exceeded: bool = False
    allow_grid_charging: bool = False
    grid_telemetry_fresh: bool = True
    grid_import_limit_exceeded: bool = False
    current_phase_mode: int = 0
    phase_down_for_pv_dip: bool = False
    pending_phase_status: bool = False
    effective_car_connected: bool = False
    model_status_value: int | None = None
    external_low_price: bool = False
    phase_switching: bool = False


def is_active_charging_status(model_status_value):
    return model_status_value in ACTIVE_CHARGING_STATUS_VALUES


def is_protocol_charging_status(model_status_value):
    return model_status_value in PROTOCOL_CHARGING_STATUS_VALUES


def select_control_state(inputs):
    if inputs.transport_unavailable:
        return WattpilotControlState.TRANSPORT_UNAVAILABLE

    if inputs.auto_mode and not inputs.command_authority_ok:
        return WattpilotControlState.COMMAND_AUTHORITY_BLOCKED

    if inputs.auto_mode and not inputs.site_current_telemetry_fresh:
        return WattpilotControlState.SITE_CURRENT_TELEMETRY_UNSAFE

    if inputs.auto_mode and inputs.site_current_limit_exceeded:
        return WattpilotControlState.SITE_CURRENT_LIMIT_STOP

    if (
        inputs.auto_mode
        and not inputs.allow_grid_charging
        and not inputs.grid_telemetry_fresh
    ):
        return WattpilotControlState.GRID_TELEMETRY_UNSAFE

    if (
        inputs.auto_mode
        and not inputs.allow_grid_charging
        and inputs.grid_import_limit_exceeded
    ):
        if inputs.current_phase_mode == 2 and inputs.phase_down_for_pv_dip:
            return WattpilotControlState.GRID_IMPORT_PHASE_DOWN
        return WattpilotControlState.GRID_IMPORT_STOP

    if inputs.pending_phase_status:
        return WattpilotControlState.PENDING_PHASE_SWITCH

    if not inputs.effective_car_connected:
        return WattpilotControlState.DISCONNECTED

    if is_active_charging_status(inputs.model_status_value):
        return WattpilotControlState.CHARGING

    if inputs.model_status_value in NOT_CHARGING_STATUS_VALUES:
        return WattpilotControlState.NOT_CHARGING

    if inputs.external_low_price:
        return WattpilotControlState.EXTERNAL_LOW_PRICE

    if inputs.phase_switching:
        return WattpilotControlState.PHASE_SWITCHING

    return WattpilotControlState.UNKNOWN


def describe_control_inputs(inputs):
    return (
        "transport_unavailable={0}, auto_mode={1}, command_authority_ok={2}, "
        "site_current_telemetry_fresh={3}, site_current_limit_exceeded={4}, "
        "allow_grid_charging={5}, grid_telemetry_fresh={6}, "
        "grid_import_limit_exceeded={7}, current_phase_mode={8}, "
        "phase_down_for_pv_dip={9}, pending_phase_status={10}, "
        "effective_car_connected={11}, model_status_value={12}, "
        "external_low_price={13}, phase_switching={14}"
    ).format(
        inputs.transport_unavailable,
        inputs.auto_mode,
        inputs.command_authority_ok,
        inputs.site_current_telemetry_fresh,
        inputs.site_current_limit_exceeded,
        inputs.allow_grid_charging,
        inputs.grid_telemetry_fresh,
        inputs.grid_import_limit_exceeded,
        inputs.current_phase_mode,
        inputs.phase_down_for_pv_dip,
        inputs.pending_phase_status,
        inputs.effective_car_connected,
        inputs.model_status_value,
        inputs.external_low_price,
        inputs.phase_switching,
    )
