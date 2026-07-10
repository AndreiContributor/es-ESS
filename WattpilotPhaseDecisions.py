from dataclasses import dataclass
from math import ceil, floor


PHASE_UP_WAIT_STABLE = "wait_stable"
PHASE_UP_WAIT_COOLDOWN = "wait_cooldown"
PHASE_UP_SWITCH = "switch"


@dataclass(frozen=True)
class PhaseUpTimingDecision:
    action: str
    next_candidate_mode: int
    next_candidate_since: float
    stable_seconds: float
    cooldown_seconds: float


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
):
    """Select one-phase or three-phase using the existing hysteresis rule."""
    if current_phase_mode == 2:
        return 2 if allowance_w >= phase_down_threshold else 1

    return 2 if allowance_w >= phase_up_threshold else 1


def target_current_for_phase(
    phase_mode,
    allowance_w,
    one_phase_voltage,
    three_phase_voltage,
    min_current,
    max_current,
):
    """Return the bounded Wattpilot current for the requested phase mode."""
    if max_current < min_current:
        return 0

    voltage = three_phase_voltage if phase_mode == 2 else one_phase_voltage
    target = int(floor(max(0, allowance_w) / voltage))

    if target < min_current:
        return 0

    return min(max_current, target)


def maximum_request_for_distributor_w(
    current_phase_mode,
    max_current,
    min_current,
    one_phase_voltage,
    three_phase_voltage,
    phase_up_threshold,
    cooldown_seconds,
):
    """Return the maximum PV allocation request for the current phase state."""
    if max_current < min_current:
        return 0

    one_phase_maximum = max_current * one_phase_voltage

    if current_phase_mode == 2:
        return max_current * three_phase_voltage

    if cooldown_seconds > 0:
        return one_phase_maximum

    allocation_step = max(1.0, one_phase_voltage)
    phase_up_probe = ceil(phase_up_threshold / allocation_step) * allocation_step
    return max(one_phase_maximum, phase_up_probe)


def evaluate_phase_up_timing(
    candidate_mode,
    candidate_since,
    target_phase_mode,
    delay_seconds,
    cooldown_seconds,
    now,
):
    """Evaluate phase-up stability and cooldown without mutating controller state."""
    if delay_seconds <= 0:
        stable_seconds = delay_seconds
        action = (
            PHASE_UP_SWITCH
            if cooldown_seconds <= 0
            else PHASE_UP_WAIT_COOLDOWN
        )
        return PhaseUpTimingDecision(
            action,
            candidate_mode,
            candidate_since,
            stable_seconds,
            cooldown_seconds,
        )

    if candidate_mode != target_phase_mode:
        return PhaseUpTimingDecision(
            PHASE_UP_WAIT_STABLE,
            target_phase_mode,
            now,
            0,
            cooldown_seconds,
        )

    stable_seconds = now - candidate_since
    if stable_seconds < delay_seconds:
        return PhaseUpTimingDecision(
            PHASE_UP_WAIT_STABLE,
            candidate_mode,
            candidate_since,
            stable_seconds,
            cooldown_seconds,
        )

    action = (
        PHASE_UP_SWITCH
        if cooldown_seconds <= 0
        else PHASE_UP_WAIT_COOLDOWN
    )
    return PhaseUpTimingDecision(
        action,
        candidate_mode,
        candidate_since,
        stable_seconds,
        cooldown_seconds,
    )
