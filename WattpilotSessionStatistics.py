"""Command-free Wattpilot connection and charging-session statistics.

The controller supplies already-observed Wattpilot telemetry to this component.
It has no access to Wattpilot commands, D-Bus, MQTT, configuration, or logging.
Returned dictionaries are durable structured-log records owned and emitted by
``FroniusWattpilot``.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Optional


EVENT_VERSION = 1
CHECKPOINT_INTERVAL_SECONDS = 60.0
MAX_INTEGRATION_GAP_SECONDS = 15.0


def _finite_non_negative(value) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(parsed) or parsed < 0:
        return None
    return parsed


@dataclass(frozen=True)
class SessionSample:
    observed_at: float
    connected: bool
    total_power_w: object
    phase_powers_w: tuple[object, object, object]
    phase_currents_a: tuple[object, object, object]
    phase_mode: int
    energy_counter_wh: object
    telemetry_fresh: bool
    mode: str


class WattpilotSessionStatistics:
    """Track one process's command-free evidence for plugged-in sessions."""

    def __init__(
        self,
        checkpoint_interval_seconds=CHECKPOINT_INTERVAL_SECONDS,
        max_integration_gap_seconds=MAX_INTEGRATION_GAP_SECONDS,
        one_phase_mapping="L1",
    ):
        self.checkpoint_interval_seconds = max(
            1.0, float(checkpoint_interval_seconds)
        )
        self.max_integration_gap_seconds = max(
            1.0, float(max_integration_gap_seconds)
        )
        mapping = str(one_phase_mapping).upper()
        self.one_phase_mapping = mapping if mapping in ("L1", "L2", "L3") else "L1"
        self._sequence = 0
        self._has_observed = False
        self._connected = False
        self._reset_session_state()

    def _reset_session_state(self):
        self.connection_id = None
        self.connection_started_at = None
        self.connection_partial_start = False
        self.last_checkpoint_at = None
        self.last_sample = None
        self.last_connected_sample_at = None
        self.last_counter_wh = None
        self.counter_energy_wh = 0.0
        self.counter_baseline_seen = False
        self.counter_reset_count = 0
        self.counter_missing_samples = 0
        self.integrated_by_mode_wh = {"one_phase": 0.0, "three_phase": 0.0}
        self.integrated_by_phase_wh = {"L1": 0.0, "L2": 0.0, "L3": 0.0}
        self.integration_coverage_seconds = 0.0
        self.integration_gap_seconds = 0.0
        self.charging = False
        self.interval_id = None
        self.interval_started_at = None
        self.charging_interval_count = 0
        self.interruption_count = 0
        self.first_charge_at = None
        self.first_start_attempt_at = None
        self.first_start_attempt_source = None
        self.first_start_accepted = None
        self.first_start_failure_stage = None
        self.current_min_a = None
        self.current_max_a = None
        self.power_min_w = None
        self.peak_power_w = 0.0
        self.phase_modes_used = set()
        self.phase_segment_mode = None
        self.phase_segment_started_at = None
        self.phase_segment_start_energy_wh = 0.0

    def _new_id(self, prefix, observed_at):
        self._sequence += 1
        return "{0}-{1}-{2}".format(
            prefix, int(float(observed_at) * 1000), self._sequence
        )

    def _base_record(self, event, observed_at):
        return {
            "event_version": EVENT_VERSION,
            "event": event,
            "observed_at_epoch": round(float(observed_at), 3),
            "connection_id": self.connection_id,
        }

    def _start_connection(self, sample, partial_start):
        self._reset_session_state()
        self.connection_id = self._new_id("connection", sample.observed_at)
        self.connection_started_at = float(sample.observed_at)
        self.connection_partial_start = bool(partial_start)
        self.last_checkpoint_at = float(sample.observed_at)
        self._connected = True
        record = self._base_record("connection_start", sample.observed_at)
        record.update(
            {
                "connection_started_at_epoch": round(self.connection_started_at, 3),
                "partial_start": self.connection_partial_start,
                "mode": str(sample.mode),
                "one_phase_mapping": self.one_phase_mapping,
            }
        )
        return record

    def note_start_attempt(self, observed_at, source):
        if not self._connected or self.first_start_attempt_at is not None:
            return []
        self.first_start_attempt_at = float(observed_at)
        self.first_start_attempt_source = str(source)
        record = self._base_record("start_attempt", observed_at)
        record.update(
            {
                "source": self.first_start_attempt_source,
                "connection_elapsed_seconds": round(
                    self.first_start_attempt_at - self.connection_started_at, 3
                ),
            }
        )
        return [record]

    def note_start_result(self, accepted, failure_stage=None):
        if not self._connected or self.first_start_attempt_at is None:
            return
        if self.first_start_accepted is not None:
            return
        self.first_start_accepted = bool(accepted)
        self.first_start_failure_stage = (
            str(failure_stage) if failure_stage is not None else None
        )

    def _counter_sample(self, value):
        counter = _finite_non_negative(value)
        if counter is None:
            self.counter_missing_samples += 1
            return
        self.counter_baseline_seen = True
        if self.last_counter_wh is not None:
            delta = counter - self.last_counter_wh
            if delta < -0.001:
                self.counter_reset_count += 1
            elif delta > 0:
                self.counter_energy_wh += delta
        self.last_counter_wh = counter

    def _physical_phase_powers(self, sample):
        values = tuple(_finite_non_negative(value) for value in sample.phase_powers_w)
        if any(value is None for value in values):
            return None
        if sample.phase_mode == 1:
            total = _finite_non_negative(sample.total_power_w)
            if total is None:
                total = sum(values)
            mapped = {"L1": 0.0, "L2": 0.0, "L3": 0.0}
            mapped[self.one_phase_mapping] = total
            return mapped
        if sample.phase_mode == 3:
            return {"L1": values[0], "L2": values[1], "L3": values[2]}
        return None

    def _integrate(self, sample):
        previous = self.last_sample
        if previous is None:
            return
        elapsed = float(sample.observed_at) - float(previous.observed_at)
        if elapsed <= 0:
            return
        previous_total = _finite_non_negative(previous.total_power_w)
        current_total = _finite_non_negative(sample.total_power_w)
        if not (
            (previous_total is not None and previous_total > 0)
            or (current_total is not None and current_total > 0)
        ):
            return
        if elapsed > self.max_integration_gap_seconds:
            self.integration_gap_seconds += elapsed
            return
        if not (previous.telemetry_fresh and sample.telemetry_fresh):
            self.integration_gap_seconds += elapsed
            return
        if previous.phase_mode != sample.phase_mode or sample.phase_mode not in (1, 3):
            self.integration_gap_seconds += elapsed
            return
        previous_powers = self._physical_phase_powers(previous)
        current_powers = self._physical_phase_powers(sample)
        if previous_powers is None or current_powers is None:
            self.integration_gap_seconds += elapsed
            return

        interval_wh = 0.0
        for phase in ("L1", "L2", "L3"):
            phase_wh = (
                (previous_powers[phase] + current_powers[phase])
                * 0.5
                * elapsed
                / 3600.0
            )
            self.integrated_by_phase_wh[phase] += phase_wh
            interval_wh += phase_wh
        key = "one_phase" if sample.phase_mode == 1 else "three_phase"
        self.integrated_by_mode_wh[key] += interval_wh
        self.integration_coverage_seconds += elapsed

    def _update_ranges(self, sample):
        power = _finite_non_negative(sample.total_power_w)
        if power is not None and power > 0:
            self.power_min_w = (
                power if self.power_min_w is None else min(self.power_min_w, power)
            )
            self.peak_power_w = max(self.peak_power_w, power)
        currents = [
            value
            for value in (
                _finite_non_negative(item) for item in sample.phase_currents_a
            )
            if value is not None and value > 0
        ]
        if currents:
            current_min = min(currents)
            current_max = max(currents)
            self.current_min_a = (
                current_min
                if self.current_min_a is None
                else min(self.current_min_a, current_min)
            )
            self.current_max_a = (
                current_max
                if self.current_max_a is None
                else max(self.current_max_a, current_max)
            )

    def _start_charge(self, sample):
        self.charging = True
        self.interval_id = self._new_id("charge", sample.observed_at)
        self.interval_started_at = float(sample.observed_at)
        self.charging_interval_count += 1
        if self.first_charge_at is None:
            self.first_charge_at = float(sample.observed_at)
        if sample.phase_mode in (1, 3):
            self.phase_modes_used.add(sample.phase_mode)
        self.phase_segment_mode = sample.phase_mode if sample.phase_mode in (1, 3) else None
        self.phase_segment_started_at = float(sample.observed_at)
        self.phase_segment_start_energy_wh = sum(self.integrated_by_mode_wh.values())
        record = self._base_record("charge_start", sample.observed_at)
        record.update(
            {
                "interval_id": self.interval_id,
                "phase_mode": sample.phase_mode,
                "power_w": _finite_non_negative(sample.total_power_w),
                "onboarding_latency_seconds": round(
                    self.first_charge_at - self.connection_started_at, 3
                ),
            }
        )
        return record

    def _close_phase_segment(self, observed_at, reason):
        if self.phase_segment_started_at is None:
            return None
        record = self._base_record("phase_segment", observed_at)
        record.update(
            {
                "interval_id": self.interval_id,
                "phase_mode": self.phase_segment_mode,
                "started_at_epoch": round(self.phase_segment_started_at, 3),
                "ended_at_epoch": round(float(observed_at), 3),
                "duration_seconds": round(
                    max(0.0, float(observed_at) - self.phase_segment_started_at), 3
                ),
                "estimated_energy_wh": round(
                    max(
                        0.0,
                        sum(self.integrated_by_mode_wh.values())
                        - self.phase_segment_start_energy_wh,
                    ),
                    6,
                ),
                "end_reason": str(reason),
            }
        )
        self.phase_segment_started_at = None
        self.phase_segment_mode = None
        return record

    def _stop_charge(self, observed_at, reason):
        records = []
        segment = self._close_phase_segment(observed_at, reason)
        if segment is not None:
            records.append(segment)
        record = self._base_record("charge_stop", observed_at)
        record.update(
            {
                "interval_id": self.interval_id,
                "started_at_epoch": round(self.interval_started_at, 3),
                "ended_at_epoch": round(float(observed_at), 3),
                "duration_seconds": round(
                    max(0.0, float(observed_at) - self.interval_started_at), 3
                ),
                "reason": str(reason),
            }
        )
        records.append(record)
        self.charging = False
        self.interval_id = None
        self.interval_started_at = None
        self.phase_segment_started_at = None
        self.phase_segment_mode = None
        return records

    def _reconciliation(self):
        estimated = sum(self.integrated_by_mode_wh.values())
        error_wh = None
        error_percent = None
        if self.counter_energy_wh > 0:
            error_wh = estimated - self.counter_energy_wh
            error_percent = error_wh / self.counter_energy_wh * 100.0
        return estimated, error_wh, error_percent

    def _snapshot_fields(self, observed_at, partial_end):
        estimated, error_wh, error_percent = self._reconciliation()
        counter_complete = bool(
            self.counter_baseline_seen
            and self.counter_reset_count == 0
            and self.counter_missing_samples == 0
            and not self.connection_partial_start
            and not partial_end
            and self.last_connected_sample_at is not None
            and float(observed_at) - self.last_connected_sample_at
            <= self.max_integration_gap_seconds
        )
        return {
            "connection_started_at_epoch": round(self.connection_started_at, 3),
            "connection_duration_seconds": round(
                max(0.0, float(observed_at) - self.connection_started_at), 3
            ),
            "partial_start": self.connection_partial_start,
            "partial_end": bool(partial_end),
            "first_start_attempt_at_epoch": (
                round(self.first_start_attempt_at, 3)
                if self.first_start_attempt_at is not None
                else None
            ),
            "first_start_attempt_source": self.first_start_attempt_source,
            "first_start_accepted": self.first_start_accepted,
            "first_start_failure_stage": self.first_start_failure_stage,
            "first_charge_at_epoch": (
                round(self.first_charge_at, 3)
                if self.first_charge_at is not None
                else None
            ),
            "onboarding_latency_seconds": (
                round(self.first_charge_at - self.connection_started_at, 3)
                if self.first_charge_at is not None
                else None
            ),
            "charging_interval_count": self.charging_interval_count,
            "interruption_count": self.interruption_count,
            "charging_active": self.charging,
            "counter_energy_wh": round(self.counter_energy_wh, 6),
            "counter_complete": counter_complete,
            "counter_reset_count": self.counter_reset_count,
            "counter_missing_samples": self.counter_missing_samples,
            "estimated_energy_wh": round(estimated, 6),
            "estimated_energy_by_mode_wh": {
                key: round(value, 6)
                for key, value in self.integrated_by_mode_wh.items()
            },
            "estimated_energy_by_phase_wh": {
                key: round(value, 6)
                for key, value in self.integrated_by_phase_wh.items()
            },
            "integration_coverage_seconds": round(
                self.integration_coverage_seconds, 3
            ),
            "integration_gap_seconds": round(self.integration_gap_seconds, 3),
            "reconciliation_error_wh": (
                round(error_wh, 6) if error_wh is not None else None
            ),
            "reconciliation_error_percent": (
                round(error_percent, 3) if error_percent is not None else None
            ),
            "phase_modes_used": sorted(self.phase_modes_used),
            "physical_phase_mapping_complete": 3 not in self.phase_modes_used,
            "phase_mapping_basis": (
                "configured_one_phase;wattpilot_order_for_three_phase"
            ),
            "current_min_a": (
                round(self.current_min_a, 3) if self.current_min_a is not None else None
            ),
            "current_max_a": (
                round(self.current_max_a, 3) if self.current_max_a is not None else None
            ),
            "power_min_w": (
                round(self.power_min_w, 3) if self.power_min_w is not None else None
            ),
            "peak_power_w": round(self.peak_power_w, 3),
            "one_phase_mapping": self.one_phase_mapping,
        }

    def _checkpoint(self, observed_at):
        record = self._base_record("checkpoint", observed_at)
        record.update(self._snapshot_fields(observed_at, partial_end=True))
        return record

    def _finish_connection(self, observed_at, reason, partial_end):
        records = []
        if self.charging:
            records.extend(self._stop_charge(observed_at, reason))
        summary = self._base_record("connection_summary", observed_at)
        summary.update(self._snapshot_fields(observed_at, partial_end=partial_end))
        summary["ended_at_epoch"] = round(float(observed_at), 3)
        summary["end_reason"] = str(reason)
        records.append(summary)
        self._connected = False
        self._reset_session_state()
        return records

    def observe(self, sample):
        if not isinstance(sample, SessionSample):
            raise TypeError("sample must be a SessionSample")
        if not isfinite(float(sample.observed_at)):
            raise ValueError("observed_at must be finite")

        records = []
        if sample.connected and not self._connected:
            records.append(
                self._start_connection(sample, partial_start=not self._has_observed)
            )
        elif not sample.connected and self._connected:
            self._integrate(sample)
            self._counter_sample(sample.energy_counter_wh)
            self.last_connected_sample_at = float(sample.observed_at)
            records.extend(
                self._finish_connection(
                    sample.observed_at, "vehicle_disconnected", partial_end=False
                )
            )
            self._has_observed = True
            return records

        self._has_observed = True
        if not self._connected:
            return records

        self._integrate(sample)
        self._counter_sample(sample.energy_counter_wh)
        self.last_connected_sample_at = float(sample.observed_at)

        total_power = _finite_non_negative(sample.total_power_w)
        measured_charging = total_power is not None and total_power > 0
        if measured_charging:
            self._update_ranges(sample)
            if sample.phase_mode in (1, 3):
                self.phase_modes_used.add(sample.phase_mode)

        if measured_charging and not self.charging:
            records.append(self._start_charge(sample))
        elif not measured_charging and self.charging:
            self.interruption_count += 1
            records.extend(self._stop_charge(sample.observed_at, "measured_power_zero"))
        elif (
            measured_charging
            and self.charging
            and sample.phase_mode in (1, 3)
            and sample.phase_mode != self.phase_segment_mode
        ):
            segment = self._close_phase_segment(sample.observed_at, "phase_changed")
            if segment is not None:
                records.append(segment)
            self.phase_segment_mode = sample.phase_mode
            self.phase_segment_started_at = float(sample.observed_at)
            self.phase_segment_start_energy_wh = sum(
                self.integrated_by_mode_wh.values()
            )

        self.last_sample = sample
        if (
            self.last_checkpoint_at is None
            or float(sample.observed_at) - self.last_checkpoint_at
            >= self.checkpoint_interval_seconds
        ):
            records.append(self._checkpoint(sample.observed_at))
            self.last_checkpoint_at = float(sample.observed_at)
        return records

    def finalize(self, observed_at, reason="service_shutdown"):
        if not self._connected:
            return []
        return self._finish_connection(observed_at, reason, partial_end=True)
