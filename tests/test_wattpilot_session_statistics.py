"""Hardware-free tests for command-free Wattpilot session statistics."""

import unittest

from WattpilotSessionStatistics import SessionSample, WattpilotSessionStatistics


def sample(
    now,
    *,
    connected=True,
    total=0,
    phases=(0, 0, 0),
    currents=(0, 0, 0),
    phase_mode=1,
    counter=0,
    fresh=True,
    mode="Auto",
):
    return SessionSample(
        observed_at=now,
        connected=connected,
        total_power_w=total,
        phase_powers_w=phases,
        phase_currents_a=currents,
        phase_mode=phase_mode,
        energy_counter_wh=counter,
        telemetry_fresh=fresh,
        mode=mode,
    )


class WattpilotSessionStatisticsTests(unittest.TestCase):
    def test_one_phase_connection_interval_energy_and_summary(self):
        statistics = WattpilotSessionStatistics(one_phase_mapping="L2")

        records = statistics.observe(sample(100, counter=10))
        self.assertEqual(records[0]["event"], "connection_start")
        self.assertTrue(records[0]["partial_start"])
        connection_id = records[0]["connection_id"]

        records = statistics.observe(
            sample(105, total=1200, phases=(1200, 0, 0), currents=(5.2, 0, 0), counter=11)
        )
        self.assertEqual(records[0]["event"], "charge_start")
        statistics.observe(
            sample(110, total=1200, phases=(1200, 0, 0), currents=(5.2, 0, 0), counter=13)
        )
        records = statistics.observe(sample(115, connected=False, counter=13))

        events = [record["event"] for record in records]
        self.assertEqual(events, ["phase_segment", "charge_stop", "connection_summary"])
        summary = records[-1]
        self.assertEqual(summary["connection_id"], connection_id)
        self.assertEqual(summary["charging_interval_count"], 1)
        self.assertEqual(summary["counter_energy_wh"], 3)
        self.assertFalse(summary["counter_complete"])
        self.assertAlmostEqual(
            summary["estimated_energy_by_phase_wh"]["L2"], 3.333333, places=6
        )
        self.assertEqual(summary["estimated_energy_by_phase_wh"]["L1"], 0)
        self.assertEqual(summary["current_min_a"], 5.2)
        self.assertEqual(summary["power_min_w"], 1200)
        self.assertEqual(summary["peak_power_w"], 1200)
        self.assertTrue(summary["physical_phase_mapping_complete"])

    def test_complete_session_counter_is_authoritative_without_reset(self):
        statistics = WattpilotSessionStatistics()
        statistics.observe(sample(0, connected=False))
        statistics.observe(sample(5, counter=100))
        statistics.observe(
            sample(10, total=3600, phases=(1200, 1200, 1200), phase_mode=3, counter=102)
        )
        statistics.observe(
            sample(15, total=3600, phases=(1200, 1200, 1200), phase_mode=3, counter=106)
        )
        records = statistics.observe(sample(20, connected=False, counter=106))
        summary = records[-1]

        self.assertFalse(summary["partial_start"])
        self.assertFalse(summary["partial_end"])
        self.assertTrue(summary["counter_complete"])
        self.assertEqual(summary["counter_energy_wh"], 6)
        self.assertEqual(summary["phase_modes_used"], [3])

    def test_multiple_charge_intervals_are_counted_inside_one_connection(self):
        statistics = WattpilotSessionStatistics()
        statistics.observe(sample(0, connected=False))
        statistics.observe(sample(5))
        statistics.observe(sample(10, total=1000, phases=(1000, 0, 0)))
        first_stop = statistics.observe(sample(15, total=0))
        statistics.observe(sample(20, total=1000, phases=(1000, 0, 0)))
        records = statistics.observe(sample(25, connected=False))

        self.assertIn("charge_stop", [record["event"] for record in first_stop])
        self.assertEqual(records[-1]["charging_interval_count"], 2)
        self.assertEqual(records[-1]["interruption_count"], 1)

    def test_counter_decrease_is_visible_and_not_subtracted(self):
        statistics = WattpilotSessionStatistics()
        statistics.observe(sample(0, connected=False))
        statistics.observe(sample(5, counter=100))
        statistics.observe(sample(10, counter=110))
        statistics.observe(sample(15, counter=2))
        statistics.observe(sample(20, counter=5))
        summary = statistics.observe(sample(25, connected=False, counter=5))[-1]

        self.assertEqual(summary["counter_reset_count"], 1)
        self.assertEqual(summary["counter_energy_wh"], 13)
        self.assertFalse(summary["counter_complete"])

    def test_missing_non_finite_and_negative_values_do_not_create_energy(self):
        statistics = WattpilotSessionStatistics()
        statistics.observe(sample(0, connected=False))
        statistics.observe(sample(5, counter=None))
        statistics.observe(
            sample(
                10,
                total=float("nan"),
                phases=(float("nan"), -1, None),
                currents=(None, -2, float("inf")),
                counter=float("inf"),
            )
        )
        summary = statistics.observe(sample(15, connected=False))[-1]

        self.assertGreaterEqual(summary["counter_missing_samples"], 2)
        self.assertEqual(summary["counter_energy_wh"], 0)
        self.assertFalse(summary["counter_complete"])
        self.assertEqual(summary["estimated_energy_wh"], 0)
        self.assertIsNone(summary["current_min_a"])

    def test_disconnect_counter_sample_completes_the_authoritative_delta(self):
        statistics = WattpilotSessionStatistics()
        statistics.observe(sample(0, connected=False))
        statistics.observe(sample(5, counter=100))
        statistics.observe(
            sample(10, total=1000, phases=(1000, 0, 0), counter=102)
        )
        summary = statistics.observe(
            sample(15, connected=False, counter=106)
        )[-1]

        self.assertEqual(summary["counter_energy_wh"], 6)
        self.assertTrue(summary["counter_complete"])

    def test_stale_or_long_gap_is_uncovered_and_never_integrated(self):
        statistics = WattpilotSessionStatistics(max_integration_gap_seconds=15)
        statistics.observe(sample(0, connected=False))
        statistics.observe(sample(5, total=1000, phases=(1000, 0, 0)))
        statistics.observe(sample(25, total=1000, phases=(1000, 0, 0)))
        statistics.observe(
            sample(30, total=1000, phases=(1000, 0, 0), fresh=False)
        )
        summary = statistics.observe(sample(35, connected=False))[-1]

        self.assertEqual(summary["estimated_energy_wh"], 0)
        self.assertEqual(summary["integration_gap_seconds"], 30)

    def test_phase_change_closes_segment_and_keeps_mode_splits_distinct(self):
        statistics = WattpilotSessionStatistics()
        statistics.observe(sample(0, connected=False))
        statistics.observe(sample(5, total=1000, phases=(1000, 0, 0), phase_mode=1))
        statistics.observe(sample(10, total=1000, phases=(1000, 0, 0), phase_mode=1))
        records = statistics.observe(
            sample(15, total=3000, phases=(1000, 1000, 1000), phase_mode=3)
        )
        statistics.observe(
            sample(20, total=3000, phases=(1000, 1000, 1000), phase_mode=3)
        )
        summary = statistics.observe(sample(25, connected=False))[-1]

        self.assertIn("phase_segment", [record["event"] for record in records])
        self.assertGreater(summary["estimated_energy_by_mode_wh"]["one_phase"], 0)
        self.assertGreater(summary["estimated_energy_by_mode_wh"]["three_phase"], 0)
        self.assertEqual(summary["phase_modes_used"], [1, 3])
        self.assertFalse(summary["physical_phase_mapping_complete"])

    def test_start_attempt_onboarding_and_rejection_are_retained(self):
        statistics = WattpilotSessionStatistics()
        statistics.observe(sample(0, connected=False))
        statistics.observe(sample(10))
        records = statistics.note_start_attempt(12, "auto_pv")
        statistics.note_start_result(False, "phase")
        statistics.observe(sample(20, total=1400, phases=(1400, 0, 0)))
        summary = statistics.observe(sample(25, connected=False))[-1]

        self.assertEqual(records[0]["event"], "start_attempt")
        self.assertEqual(summary["first_start_attempt_source"], "auto_pv")
        self.assertFalse(summary["first_start_accepted"])
        self.assertEqual(summary["first_start_failure_stage"], "phase")
        self.assertEqual(summary["onboarding_latency_seconds"], 10)

    def test_checkpoint_is_bounded_to_one_per_connected_minute(self):
        statistics = WattpilotSessionStatistics(checkpoint_interval_seconds=60)
        statistics.observe(sample(0, connected=False))
        statistics.observe(sample(5))
        events = []
        for now in (10, 30, 64, 65, 100, 124, 125):
            events.extend(statistics.observe(sample(now)))
        checkpoints = [event for event in events if event["event"] == "checkpoint"]

        self.assertEqual([item["observed_at_epoch"] for item in checkpoints], [65, 125])

    def test_service_shutdown_marks_partial_end_and_restart_partial_start(self):
        statistics = WattpilotSessionStatistics()
        records = statistics.observe(sample(100, total=1000, phases=(1000, 0, 0)))
        self.assertTrue(records[0]["partial_start"])
        summary = statistics.finalize(110)[-1]

        self.assertTrue(summary["partial_start"])
        self.assertTrue(summary["partial_end"])
        self.assertEqual(summary["end_reason"], "service_shutdown")

    def test_records_are_non_identifying_and_contain_no_credentials(self):
        statistics = WattpilotSessionStatistics()
        record = statistics.observe(sample(100, mode="Manual"))[0]
        serialized = repr(record).lower()

        self.assertNotIn("password", serialized)
        self.assertNotIn("host", serialized)
        self.assertNotIn("vehicle", serialized)
        self.assertIn("connection_id", record)


if __name__ == "__main__":
    unittest.main()
