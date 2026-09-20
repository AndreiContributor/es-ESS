from dataclasses import dataclass
from math import ceil, floor


PHASE_SWITCH_WAIT_STABLE = "wait_stable"
PHASE_SWITCH_WAIT_COOLDOWN = "wait_cooldown"
PHASE_SWITCH_READY = "switch"

PHASE_UP_DROP_NOT_APPLICABLE = "not_applicable"
PHASE_UP_DROP_RECOVERED = "recovered"
PHASE_UP_DROP_BELOW_MINIMUM = "below_minimum"
PHASE_UP_DROP_GRACE_DISABLED = "grace_disabled"
PHASE_UP_DROP_GRACE_STARTED = "grace_started"
PHASE_UP_DROP_GRACE_ACTIVE = "grace_active"
PHASE_UP_DROP_GRACE_EXPIRED = "grace_expired"

CURRENT_INCREASE_NOT_NEEDED = "not_needed"
CURRENT_INCREASE_BLOCKED = "blocked"
CURRENT_INCREASE_STARTED = "started"
CURRENT_INCREASE_WAITING = "waiting"
CURRENT_INCREASE_READY = "ready"

CURRENT_INCREASE_RESERVE_AMPS = 1
CURRENT_INCREASE_SLOW_MIN_SECONDS = 600
CURRENT_INCREASE_SUPPORT_ONE_STEP = 1
CURRENT_INCREASE_SUPPORT_WITH_RESERVE = 2

# Compatibility aliases for existing callers and diagnostics. New code uses
# the direction-neutral names because the same timing decision now controls
# both 1-to-3 and 3-to-1 changes.
PHASE_UP_WAIT_STABLE = PHASE_SWITCH_WAIT_STABLE
PHASE_UP_WAIT_COOLDOWN = PHASE_SWITCH_WAIT_COOLDOWN
PHASE_UP_SWITCH = PHASE_SWITCH_READY


@dataclass(frozen=True)
class PhaseSwitchTimingDecision:
    action: str
    next_candidate_mode: int
    next_candidate_since: float
    stable_seconds: float
    cooldown_seconds: float


@dataclass(frozen=True)
class PhaseUpDropGraceDecision:
    preserve_candidate: bool
    next_below_threshold_since: float
    drop_seconds: float
    reason: str


@dataclass(frozen=True)
class CurrentIncreaseDecision:
    allowed_current: int
    next_candidate_phase_mode: int
    next_candidate_since: float
    next_allowance_updated_at: float
    next_observation_count: int
    stable_seconds: float
    reason: str
    next_candidate_support_level: int = 0
    required_seconds: float = 0


def phase_up_threshold_w(three_phase_start_w, three_phase_minimum_power):
    """Return the PV allocation required before changing to three phases."""
    return max(float(three_phase_start_w), three_phase_minimum_power)


def phase_down_threshold_w(three_phase_stop_w, three_phase_minimum_power):
    """Return the PV allocation below which three-phase should step down."""
    return max(float(three_phase_stop_w), three_phase_minimum_power)


def desired_phase_mode(
    current_phase_mode,
    allowance_w,
    phase_up_threshold,
    phase_down_threshold,
    allow_three_phase=True,
):
    """Select one-phase or three-phase using the existing hysteresis rule."""
    if not allow_three_phase:
        return 1

    if current_phase_mode == 2:
        return 2 if allowance_w >= phase_down_threshold else 1

    return 2 if allowance_w >= phase_up_threshold else 1


def target_current_for_phase(
    phase_mode,
    allowance_w,
    one_phase_allocation_step,
    three_phase_allocation_step,
    min_current,
    max_current,
):
    """Return the bounded Wattpilot current for the requested phase mode."""
    if max_current < min_current:
        return 0

    allocation_step = (
        three_phase_allocation_step
        if phase_mode == 2
        else one_phase_allocation_step
    )
    target = int(floor(max(0, allowance_w) / allocation_step))

    if target < min_current:
        return 0

    return min(max_current, target)


def stabilize_current_increase(
    current_command,
    target_current,
    phase_mode,
    candidate_phase_mode,
    candidate_since,
    candidate_allowance_updated_at,
    observation_count,
    allowance_updated_at,
    recovery_seconds,
    now,
    increase_allowed,
    reserve_amps=CURRENT_INCREASE_RESERVE_AMPS,
    candidate_support_level=0,
    slow_recovery_seconds=CURRENT_INCREASE_SLOW_MIN_SECONDS,
):
    """Delay only increases until fresh PV support remains continuous.

    Reductions are returned immediately. Reserve-backed increases use the
    ordinary recovery interval; one-step-only increases use a separate slow
    interval with a ten-minute floor. Both require at least two distinct
    allowance observations, so one still-fresh MQTT value cannot mature an
    increase by itself.
    """
    current = max(0, int(current_command))
    target = max(0, int(target_current))
    current_phase = int(phase_mode)
    delay = max(0.0, float(recovery_seconds))
    reserve = max(0, int(reserve_amps))
    current_time = float(now)
    allowance_time = float(allowance_updated_at)

    def reset(allowed_current, reason):
        return CurrentIncreaseDecision(
            allowed_current,
            0,
            0,
            0,
            0,
            0,
            reason,
        )

    if target <= current:
        return reset(target, CURRENT_INCREASE_NOT_NEEDED)

    if not increase_allowed or current_phase not in (1, 2) or allowance_time <= 0:
        return reset(current, CURRENT_INCREASE_BLOCKED)

    # The reserve-backed path is fast. A one-step-only allowance uses a
    # separate, much longer candidate instead of permanently blocking the
    # effective maximum (where the bounded target cannot include a reserve).
    # Never transfer elapsed time between the two support levels.
    support_level = (
        CURRENT_INCREASE_SUPPORT_WITH_RESERVE
        if target >= current + 1 + reserve
        else CURRENT_INCREASE_SUPPORT_ONE_STEP
    )
    if support_level == CURRENT_INCREASE_SUPPORT_ONE_STEP:
        delay = max(
            float(CURRENT_INCREASE_SLOW_MIN_SECONDS),
            float(slow_recovery_seconds),
        )

    if delay <= 0:
        return CurrentIncreaseDecision(
            min(target, current + 1),
            current_phase,
            current_time,
            allowance_time,
            1,
            0,
            CURRENT_INCREASE_READY,
            support_level,
            delay,
        )

    if (
        candidate_phase_mode != current_phase
        or candidate_support_level != support_level
        or candidate_since <= 0
    ):
        return CurrentIncreaseDecision(
            current,
            current_phase,
            current_time,
            allowance_time,
            1,
            0,
            CURRENT_INCREASE_STARTED,
            support_level,
            delay,
        )

    observations = max(1, int(observation_count))
    last_allowance_time = float(candidate_allowance_updated_at)
    if allowance_time > last_allowance_time:
        observations += 1
        last_allowance_time = allowance_time

    stable_seconds = max(0.0, current_time - float(candidate_since))
    reason = (
        CURRENT_INCREASE_READY
        if stable_seconds >= delay and observations >= 2
        else CURRENT_INCREASE_WAITING
    )
    allowed_current = min(target, current + 1) if reason == CURRENT_INCREASE_READY else current
    return CurrentIncreaseDecision(
        allowed_current,
        current_phase,
        float(candidate_since),
        last_allowance_time,
        observations,
        stable_seconds,
        reason,
        support_level,
        delay,
    )


def maximum_request_for_distributor_w(
    current_phase_mode,
    max_current,
    min_current,
    one_phase_allocation_step,
    three_phase_allocation_step,
    phase_up_threshold,
    cooldown_seconds,
    allow_three_phase=True,
):
    """Return the maximum PV allocation request for the current phase state."""
    if max_current < min_current:
        return 0

    one_phase_maximum = max_current * one_phase_allocation_step

    if not allow_three_phase:
        return one_phase_maximum

    if current_phase_mode == 2:
        return max_current * three_phase_allocation_step

    if cooldown_seconds > 0:
        return one_phase_maximum

    allocation_step = max(1.0, one_phase_allocation_step)
    phase_up_probe = ceil(phase_up_threshold / allocation_step) * allocation_step
    return max(one_phase_maximum, phase_up_probe)


def evaluate_phase_switch_timing(
    candidate_mode,
    candidate_since,
    target_phase_mode,
    delay_seconds,
    cooldown_seconds,
    now,
):
    """Evaluate shared phase-change stability and cooldown timing."""
    if delay_seconds <= 0:
        stable_seconds = delay_seconds
        action = (
            PHASE_SWITCH_READY
            if cooldown_seconds <= 0
            else PHASE_SWITCH_WAIT_COOLDOWN
        )
        return PhaseSwitchTimingDecision(
            action,
            candidate_mode,
            candidate_since,
            stable_seconds,
            cooldown_seconds,
        )

    if candidate_mode != target_phase_mode:
        return PhaseSwitchTimingDecision(
            PHASE_SWITCH_WAIT_STABLE,
            target_phase_mode,
            now,
            0,
            cooldown_seconds,
        )

    stable_seconds = now - candidate_since
    if stable_seconds < delay_seconds:
        return PhaseSwitchTimingDecision(
            PHASE_SWITCH_WAIT_STABLE,
            candidate_mode,
            candidate_since,
            stable_seconds,
            cooldown_seconds,
        )

    action = (
        PHASE_SWITCH_READY
        if cooldown_seconds <= 0
        else PHASE_SWITCH_WAIT_COOLDOWN
    )
    return PhaseSwitchTimingDecision(
        action,
        candidate_mode,
        candidate_since,
        stable_seconds,
        cooldown_seconds,
    )


def evaluate_phase_up_drop_grace(
    candidate_mode,
    allowance_w,
    phase_up_threshold,
    phase_down_threshold,
    below_threshold_since,
    grace_seconds,
    now,
):
    """Preserve a phase-up candidate through a short, safe PV dip.

    A candidate can only be preserved while assigned allowance remains at or
    above the effective three-phase-capable floor. The controller must still
    require the full phase-up threshold again before issuing a phase command.
    """
    if candidate_mode != 2:
        return PhaseUpDropGraceDecision(
            False, 0, 0, PHASE_UP_DROP_NOT_APPLICABLE
        )

    if allowance_w >= phase_up_threshold:
        return PhaseUpDropGraceDecision(
            False, 0, 0, PHASE_UP_DROP_RECOVERED
        )

    if allowance_w < phase_down_threshold:
        return PhaseUpDropGraceDecision(
            False, 0, 0, PHASE_UP_DROP_BELOW_MINIMUM
        )

    if grace_seconds <= 0:
        return PhaseUpDropGraceDecision(
            False, 0, 0, PHASE_UP_DROP_GRACE_DISABLED
        )

    if below_threshold_since <= 0:
        return PhaseUpDropGraceDecision(
            True, now, 0, PHASE_UP_DROP_GRACE_STARTED
        )

    drop_seconds = max(0, now - below_threshold_since)
    if drop_seconds < grace_seconds:
        return PhaseUpDropGraceDecision(
            True,
            below_threshold_since,
            drop_seconds,
            PHASE_UP_DROP_GRACE_ACTIVE,
        )

    return PhaseUpDropGraceDecision(
        False, 0, drop_seconds, PHASE_UP_DROP_GRACE_EXPIRED
    )


def evaluate_phase_up_timing(
    candidate_mode,
    candidate_since,
    target_phase_mode,
    delay_seconds,
    cooldown_seconds,
    now,
):
    """Compatibility wrapper for the former phase-up-only helper."""
    return evaluate_phase_switch_timing(
        candidate_mode,
        candidate_since,
        target_phase_mode,
        delay_seconds,
        cooldown_seconds,
        now,
    )
