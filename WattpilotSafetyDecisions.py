from dataclasses import dataclass


GRID_IMPORT_ALLOWED = "grid_charging_allowed"
GRID_IMPORT_STARTED = "grid_import_started"
GRID_IMPORT_WAITING = "grid_import_waiting"
GRID_IMPORT_EXCEEDED = "grid_import_exceeded"
GRID_IMPORT_BELOW_THRESHOLD = "grid_import_below_threshold"

BATTERY_RECOVERY_NOT_LOCKED = "not_locked_out"
BATTERY_RECOVERY_INTERRUPTED = "recovery_interrupted"
BATTERY_RECOVERY_STARTED = "recovery_started"
BATTERY_RECOVERY_WAITING = "recovery_waiting"
BATTERY_RECOVERY_COMPLETE = "recovery_complete"

BATTERY_ASSIST_NO_SHORTFALL = "no_shortfall"
BATTERY_ASSIST_LOCKED_OUT = "locked_out"
BATTERY_ASSIST_INELIGIBLE = "ineligible"
BATTERY_ASSIST_STARTED = "started"
BATTERY_ASSIST_ACTIVE = "active"
BATTERY_ASSIST_TIME_LIMIT = "time_limit"


@dataclass(frozen=True)
class GridImportGuardDecision:
    limit_exceeded: bool
    next_import_since: float
    reason: str


@dataclass(frozen=True)
class BatteryAssistRecoveryDecision:
    next_recovery_since: float
    clear_lockout: bool
    recovery_started: bool
    recovery_interrupted: bool
    reason: str


@dataclass(frozen=True)
class BatteryAssistDecision:
    allow_assist: bool
    next_assist_since: float
    assist_started: bool
    time_limit_reached: bool
    reason: str


def evaluate_grid_import_guard(
    allow_grid_charging,
    grid_import_w,
    import_since,
    stop_w,
    stop_seconds,
    now,
):
    if allow_grid_charging:
        return GridImportGuardDecision(False, 0, GRID_IMPORT_ALLOWED)

    if grid_import_w > stop_w:
        if import_since == 0:
            return GridImportGuardDecision(False, now, GRID_IMPORT_STARTED)

        if now - import_since >= stop_seconds:
            return GridImportGuardDecision(
                True, import_since, GRID_IMPORT_EXCEEDED
            )

        return GridImportGuardDecision(False, import_since, GRID_IMPORT_WAITING)

    return GridImportGuardDecision(False, 0, GRID_IMPORT_BELOW_THRESHOLD)


def evaluate_battery_assist_recovery(
    locked_out,
    shortfall_w,
    recovery_since,
    recovery_seconds,
    now,
):
    if not locked_out:
        return BatteryAssistRecoveryDecision(
            recovery_since,
            False,
            False,
            False,
            BATTERY_RECOVERY_NOT_LOCKED,
        )

    if shortfall_w > 0:
        return BatteryAssistRecoveryDecision(
            0,
            False,
            False,
            recovery_since != 0,
            BATTERY_RECOVERY_INTERRUPTED,
        )

    if recovery_since == 0:
        return BatteryAssistRecoveryDecision(
            now,
            recovery_seconds <= 0,
            True,
            False,
            (
                BATTERY_RECOVERY_COMPLETE
                if recovery_seconds <= 0
                else BATTERY_RECOVERY_STARTED
            ),
        )

    if now - recovery_since >= recovery_seconds:
        return BatteryAssistRecoveryDecision(
            recovery_since,
            True,
            False,
            False,
            BATTERY_RECOVERY_COMPLETE,
        )

    return BatteryAssistRecoveryDecision(
        recovery_since,
        False,
        False,
        False,
        BATTERY_RECOVERY_WAITING,
    )


def evaluate_battery_assist(
    enabled,
    shortfall_w,
    locked_out,
    active_charge_power_w,
    soc,
    soc_min,
    max_shortfall_w,
    grid_import_w,
    grid_import_stop_w,
    assist_since,
    max_seconds,
    now,
):
    if shortfall_w <= 0:
        return BatteryAssistDecision(
            False, 0, False, False, BATTERY_ASSIST_NO_SHORTFALL
        )

    if locked_out:
        return BatteryAssistDecision(
            False, 0, False, False, BATTERY_ASSIST_LOCKED_OUT
        )

    can_assist = (
        enabled
        and active_charge_power_w is not None
        and active_charge_power_w > 0
        and soc is not None
        and soc >= soc_min
        and shortfall_w <= max_shortfall_w
        and grid_import_w <= grid_import_stop_w
    )

    if not can_assist:
        return BatteryAssistDecision(
            False, 0, False, False, BATTERY_ASSIST_INELIGIBLE
        )

    next_assist_since = assist_since if assist_since != 0 else now
    elapsed_seconds = now - next_assist_since
    time_limit_reached = elapsed_seconds >= max_seconds

    if time_limit_reached:
        return BatteryAssistDecision(
            False,
            next_assist_since,
            assist_since == 0,
            True,
            BATTERY_ASSIST_TIME_LIMIT,
        )

    return BatteryAssistDecision(
        True,
        next_assist_since,
        assist_since == 0,
        False,
        BATTERY_ASSIST_STARTED if assist_since == 0 else BATTERY_ASSIST_ACTIVE,
    )
