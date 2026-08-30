from dataclasses import dataclass
from math import floor, isfinite


PHASE_NAMES = ("L1", "L2", "L3")


@dataclass(frozen=True)
class SiteCurrentDecision:
    allowed_current: int
    limiting_phase: str
    site_currents: tuple[float, float, float]
    charger_contribution: tuple[float, float, float]
    non_ev_currents: tuple[float, float, float]
    headrooms: tuple[float, float, float]


@dataclass(frozen=True)
class SiteCurrentRecoveryDecision:
    allowed_current: int
    next_recovery_since: float
    recovery_elapsed: float


def _validated_currents(values, name):
    if values is None or len(values) != 3:
        raise ValueError("{0} must contain L1, L2, and L3".format(name))

    result = tuple(float(value) for value in values)
    if any(not isfinite(value) or value < 0 for value in result):
        raise ValueError("{0} must contain finite non-negative values".format(name))
    return result


def evaluate_site_current(
    site_currents,
    charger_currents,
    measured_phase_mode,
    requested_phase_mode,
    one_phase_mapping,
    site_max_current,
):
    """Return safe Wattpilot headroom for one- or three-phase charging.

    Site currents are whole-site physical L1/L2/L3 measurements. For an
    existing three-phase charge, the smallest Wattpilot phase current is
    subtracted from every physical site phase. This avoids relying on a phase
    rotation while remaining conservative when the charger measurements are
    unequal.
    """
    site = _validated_currents(site_currents, "site_currents")
    charger = _validated_currents(charger_currents, "charger_currents")
    maximum = float(site_max_current)

    if not isfinite(maximum) or maximum <= 0:
        raise ValueError("site_max_current must be finite and positive")
    if one_phase_mapping not in PHASE_NAMES:
        raise ValueError("one_phase_mapping must be L1, L2, or L3")
    if measured_phase_mode not in (0, 1, 2):
        raise ValueError("measured_phase_mode must be 0, 1, or 2")
    if requested_phase_mode not in (1, 2):
        raise ValueError("requested_phase_mode must be 1 or 2")

    contribution = [0.0, 0.0, 0.0]
    if measured_phase_mode == 1:
        contribution[PHASE_NAMES.index(one_phase_mapping)] = charger[0]
    elif measured_phase_mode == 2:
        conservative_current = min(charger)
        contribution = [conservative_current] * 3

    non_ev = tuple(
        max(0.0, site[index] - contribution[index]) for index in range(3)
    )
    headrooms = tuple(maximum - current for current in non_ev)
    active_indexes = (
        range(3)
        if requested_phase_mode == 2
        else (PHASE_NAMES.index(one_phase_mapping),)
    )
    limiting_index = min(active_indexes, key=lambda index: headrooms[index])
    allowed = max(0, min(floor(maximum), floor(headrooms[limiting_index])))

    return SiteCurrentDecision(
        allowed_current=allowed,
        limiting_phase=PHASE_NAMES[limiting_index],
        site_currents=site,
        charger_contribution=tuple(contribution),
        non_ev_currents=non_ev,
        headrooms=headrooms,
    )


def limit_current_recovery(
    current_command,
    target_current,
    recovery_since,
    recovery_seconds,
    now,
):
    """Apply immediate reductions and delayed one-amp-per-cycle recovery."""
    current = max(0, int(current_command))
    target = max(0, int(target_current))
    since = float(recovery_since)
    delay = max(0.0, float(recovery_seconds))
    current_time = float(now)

    if target <= current:
        return SiteCurrentRecoveryDecision(target, 0, 0)

    if since <= 0:
        return SiteCurrentRecoveryDecision(current, current_time, 0)

    elapsed = max(0.0, current_time - since)
    if elapsed < delay:
        return SiteCurrentRecoveryDecision(current, since, elapsed)

    return SiteCurrentRecoveryDecision(min(target, current + 1), since, elapsed)
