from math import isfinite


def finite_number(value):
    """Return a finite float or None for missing, invalid, or infinite values."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return number if isfinite(number) else None


def parse_finite_payload(payload):
    """Parse an MQTT payload as a finite float.

    Raises ValueError for malformed or non-finite values so callers can decide
    whether an existing input should be invalidated.
    """
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")

    number = finite_number(str(payload).strip())
    if number is None:
        raise ValueError("value must be finite")

    return number


def telemetry_sample(value, now):
    """Return validity and receive time for one telemetry value."""
    return finite_number(value) is not None, now


def timestamped_value_is_fresh(valid, updated_at, fresh_seconds, now):
    """Return True when a timestamped value is valid and inside its freshness window."""
    return (
        bool(valid)
        and updated_at > 0
        and now - updated_at <= fresh_seconds
    )


def grid_telemetry_is_fresh(samples, fresh_seconds, now):
    """Return True only when every required grid phase is valid and fresh."""
    for valid, updated_at in samples:
        if not timestamped_value_is_fresh(valid, updated_at, fresh_seconds, now):
            return False
    return True


def allowance_is_fresh(valid, updated_at, fresh_seconds, now):
    """Return True when the assigned distributor allowance is valid and fresh."""
    return timestamped_value_is_fresh(valid, updated_at, fresh_seconds, now)


def has_minimum_allowance(
    allowance,
    valid,
    updated_at,
    fresh_seconds,
    now,
    minimum_power,
    can_charge_at_minimum_current,
):
    """Return True when a fresh assigned allowance can start/continue charging."""
    allowance_w = finite_number(allowance)
    minimum_w = finite_number(minimum_power)
    return (
        allowance_is_fresh(valid, updated_at, fresh_seconds, now)
        and bool(can_charge_at_minimum_current)
        and allowance_w is not None
        and minimum_w is not None
        and allowance_w >= minimum_w
    )


def fresh_raw_overhead(value, updated_at, fresh_seconds, now):
    """Return fresh non-negative raw overhead, or None when unavailable/stale."""
    overhead_w = finite_number(value)
    if overhead_w is None:
        return None

    if updated_at <= 0 or now - updated_at > fresh_seconds:
        return None

    return max(0.0, overhead_w)
