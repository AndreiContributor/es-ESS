import unittest

import WattpilotPhaseDecisions as decisions


class WattpilotPhaseDecisionTests(unittest.TestCase):
    def test_phase_thresholds_clamp_to_three_phase_minimum_power(self):
        self.assertEqual(
            decisions.phase_up_threshold_w(4200, 4140),
            4200.0,
        )
        self.assertEqual(
            decisions.phase_up_threshold_w(4000, 4140),
            4140.0,
        )
        self.assertEqual(
            decisions.phase_down_threshold_w(4100, 4140),
            4140.0,
        )

    def test_desired_phase_mode_uses_hysteresis(self):
        self.assertEqual(
            decisions.desired_phase_mode(1, 4199, 4200, 4140),
            1,
        )
        self.assertEqual(
            decisions.desired_phase_mode(1, 4200, 4200, 4140),
            2,
        )
        self.assertEqual(
            decisions.desired_phase_mode(2, 4140, 4200, 4140),
            2,
        )
        self.assertEqual(
            decisions.desired_phase_mode(2, 4139, 4200, 4140),
            1,
        )

    def test_one_phase_capability_overrides_allowance_and_remembered_mode(self):
        self.assertEqual(
            decisions.desired_phase_mode(
                1, 12000, 4200, 4140, allow_three_phase=False
            ),
            1,
        )
        self.assertEqual(
            decisions.desired_phase_mode(
                2, 12000, 4200, 4140, allow_three_phase=False
            ),
            1,
        )

    def test_target_current_for_phase_respects_minimum_maximum_and_effective_limit(self):
        self.assertEqual(
            decisions.target_current_for_phase(1, 1379, 230, 690, 6, 16),
            0,
        )
        self.assertEqual(
            decisions.target_current_for_phase(1, 5000, 230, 690, 6, 16),
            16,
        )
        self.assertEqual(
            decisions.target_current_for_phase(2, 5000, 230, 690, 6, 16),
            7,
        )
        self.assertEqual(
            decisions.target_current_for_phase(1, 5000, 230, 690, 6, 5),
            0,
        )

    def test_canonical_step_round_trip_never_funds_a_partial_ampere(self):
        for phase_mode, one_step, three_step in (
            (1, 231, 693),
            (2, 231, 693),
        ):
            with self.subTest(phase_mode=phase_mode):
                step = three_step if phase_mode == 2 else one_step
                self.assertEqual(
                    decisions.target_current_for_phase(
                        phase_mode,
                        8 * step,
                        one_step,
                        three_step,
                        6,
                        16,
                    ),
                    8,
                )
                self.assertEqual(
                    decisions.target_current_for_phase(
                        phase_mode,
                        8 * step - 0.01,
                        one_step,
                        three_step,
                        6,
                        16,
                    ),
                    7,
                )

    def test_current_increase_requires_continuous_distinct_allowance_updates(self):
        started = decisions.stabilize_current_increase(
            8, 10, 2, 0, 0, 0, 0, 100, 30, 100, True
        )
        self.assertEqual(started.allowed_current, 8)
        self.assertEqual(started.reason, decisions.CURRENT_INCREASE_STARTED)

        same_message = decisions.stabilize_current_increase(
            8,
            10,
            2,
            started.next_candidate_phase_mode,
            started.next_candidate_since,
            started.next_allowance_updated_at,
            started.next_observation_count,
            100,
            30,
            130,
            True,
            candidate_support_level=started.next_candidate_support_level,
        )
        self.assertEqual(same_message.allowed_current, 8)
        self.assertEqual(same_message.reason, decisions.CURRENT_INCREASE_WAITING)

        refreshed = decisions.stabilize_current_increase(
            8,
            10,
            2,
            same_message.next_candidate_phase_mode,
            same_message.next_candidate_since,
            same_message.next_allowance_updated_at,
            same_message.next_observation_count,
            125,
            30,
            130,
            True,
            candidate_support_level=same_message.next_candidate_support_level,
        )
        self.assertEqual(refreshed.allowed_current, 9)
        self.assertEqual(refreshed.reason, decisions.CURRENT_INCREASE_READY)

    def test_current_reduction_is_immediate_and_clears_increase_candidate(self):
        reduced = decisions.stabilize_current_increase(
            9, 8, 2, 2, 100, 125, 3, 130, 30, 130, False
        )

        self.assertEqual(reduced.allowed_current, 8)
        self.assertEqual(reduced.reason, decisions.CURRENT_INCREASE_NOT_NEEDED)
        self.assertEqual(reduced.next_candidate_phase_mode, 0)
        self.assertEqual(reduced.next_candidate_since, 0)

    def test_one_step_only_support_uses_ten_minute_candidate(self):
        started = decisions.stabilize_current_increase(
            8, 9, 2, 0, 0, 0, 0, 100, 30, 100, True
        )

        self.assertEqual(started.allowed_current, 8)
        self.assertEqual(started.reason, decisions.CURRENT_INCREASE_STARTED)
        self.assertEqual(started.required_seconds, 600)
        self.assertEqual(
            started.next_candidate_support_level,
            decisions.CURRENT_INCREASE_SUPPORT_ONE_STEP,
        )

        waiting = decisions.stabilize_current_increase(
            8, 9, 2, 2, 100, 100, 1, 699, 30, 699, True,
            candidate_support_level=started.next_candidate_support_level,
        )
        self.assertEqual(waiting.allowed_current, 8)
        self.assertEqual(waiting.reason, decisions.CURRENT_INCREASE_WAITING)

        ready = decisions.stabilize_current_increase(
            8, 9, 2, 2, 100, 699, 2, 700, 30, 700, True,
            candidate_support_level=waiting.next_candidate_support_level,
        )
        self.assertEqual(ready.allowed_current, 9)
        self.assertEqual(ready.reason, decisions.CURRENT_INCREASE_READY)

        shorter_phase_setting = decisions.stabilize_current_increase(
            8, 9, 2, 0, 0, 0, 0, 100, 30, 100, True,
            slow_recovery_seconds=300,
        )
        self.assertEqual(shorter_phase_setting.required_seconds, 600)

        supported = decisions.stabilize_current_increase(
            8, 10, 2, 0, 0, 0, 0, 105, 30, 105, True
        )

        self.assertEqual(supported.allowed_current, 8)
        self.assertEqual(supported.reason, decisions.CURRENT_INCREASE_STARTED)
        self.assertEqual(supported.required_seconds, 30)

    def test_support_tier_change_restarts_candidate_without_borrowing_time(self):
        slow = decisions.stabilize_current_increase(
            8, 9, 2, 0, 0, 0, 0, 100, 30, 100, True
        )
        fast = decisions.stabilize_current_increase(
            8, 10, 2, 2, 100, 100, 1, 680, 30, 680, True,
            candidate_support_level=slow.next_candidate_support_level,
        )
        self.assertEqual(fast.allowed_current, 8)
        self.assertEqual(fast.next_candidate_since, 680)
        self.assertEqual(fast.required_seconds, 30)

        back_to_slow = decisions.stabilize_current_increase(
            8, 9, 2, 2, 680, 680, 1, 690, 30, 690, True,
            candidate_support_level=fast.next_candidate_support_level,
        )
        self.assertEqual(back_to_slow.allowed_current, 8)
        self.assertEqual(back_to_slow.next_candidate_since, 690)
        self.assertEqual(back_to_slow.required_seconds, 600)

    def test_effective_maximum_is_reachable_after_slow_stability(self):
        self.assertEqual(
            decisions.target_current_for_phase(2, 16 * 690, 230, 690, 6, 16),
            16,
        )
        started = decisions.stabilize_current_increase(
            15, 16, 2, 0, 0, 0, 0, 100, 30, 100, True,
            slow_recovery_seconds=750,
        )
        self.assertEqual(started.allowed_current, 15)
        self.assertEqual(started.required_seconds, 750)

        ready = decisions.stabilize_current_increase(
            15, 16, 2, 2, 100, 100, 1, 850, 30, 850, True,
            candidate_support_level=started.next_candidate_support_level,
            slow_recovery_seconds=750,
        )
        self.assertEqual(ready.allowed_current, 16)

    def test_one_step_support_never_bypasses_material_power_or_reduction(self):
        blocked = decisions.stabilize_current_increase(
            15, 16, 2, 2, 100, 110, 2, 700, 30, 700, False,
            candidate_support_level=decisions.CURRENT_INCREASE_SUPPORT_ONE_STEP,
        )
        self.assertEqual(blocked.allowed_current, 15)
        self.assertEqual(blocked.next_candidate_since, 0)

        reduced = decisions.stabilize_current_increase(
            15, 14, 2, 2, 100, 110, 2, 700, 30, 700, True,
            candidate_support_level=decisions.CURRENT_INCREASE_SUPPORT_ONE_STEP,
        )
        self.assertEqual(reduced.allowed_current, 14)
        self.assertEqual(reduced.next_candidate_since, 0)

    def test_zero_recovery_retains_one_amp_per_cycle_behavior(self):
        ready = decisions.stabilize_current_increase(
            8, 12, 1, 0, 0, 0, 0, 100, 0, 100, True
        )

        self.assertEqual(ready.allowed_current, 9)
        self.assertEqual(ready.reason, decisions.CURRENT_INCREASE_READY)

    def test_current_increase_is_blocked_without_material_charging_power(self):
        blocked = decisions.stabilize_current_increase(
            8, 10, 2, 2, 100, 125, 3, 130, 30, 130, False
        )

        self.assertEqual(blocked.allowed_current, 8)
        self.assertEqual(blocked.reason, decisions.CURRENT_INCREASE_BLOCKED)
        self.assertEqual(blocked.next_candidate_since, 0)

    def test_maximum_request_uses_phase_up_probe_until_cooldown(self):
        self.assertEqual(
            decisions.maximum_request_for_distributor_w(
                1, 16, 6, 230, 690, 4200, 0
            ),
            4370,
        )
        self.assertEqual(
            decisions.maximum_request_for_distributor_w(
                1, 16, 6, 230, 690, 4200, 1
            ),
            3680,
        )
        self.assertEqual(
            decisions.maximum_request_for_distributor_w(
                2, 16, 6, 230, 690, 4200, 0
            ),
            11040,
        )
        self.assertEqual(
            decisions.maximum_request_for_distributor_w(
                1, 5, 6, 230, 690, 4200, 0
            ),
            0,
        )

    def test_one_phase_capability_never_requests_phase_up_probe(self):
        self.assertEqual(
            decisions.maximum_request_for_distributor_w(
                1,
                16,
                6,
                230,
                690,
                4200,
                0,
                allow_three_phase=False,
            ),
            3680,
        )
        self.assertEqual(
            decisions.maximum_request_for_distributor_w(
                2,
                16,
                6,
                230,
                690,
                4200,
                0,
                allow_three_phase=False,
            ),
            3680,
        )

    def test_shared_phase_timing_waits_for_stability_then_cooldown_then_switch(self):
        first = decisions.evaluate_phase_switch_timing(
            candidate_mode=0,
            candidate_since=0,
            target_phase_mode=2,
            delay_seconds=120,
            cooldown_seconds=0,
            now=100,
        )
        self.assertEqual(first.action, decisions.PHASE_SWITCH_WAIT_STABLE)
        self.assertEqual(first.next_candidate_mode, 2)
        self.assertEqual(first.next_candidate_since, 100)
        self.assertEqual(first.stable_seconds, 0)

        stable = decisions.evaluate_phase_switch_timing(
            candidate_mode=2,
            candidate_since=100,
            target_phase_mode=2,
            delay_seconds=120,
            cooldown_seconds=30,
            now=220,
        )
        self.assertEqual(stable.action, decisions.PHASE_SWITCH_WAIT_COOLDOWN)
        self.assertEqual(stable.stable_seconds, 120)
        self.assertEqual(stable.cooldown_seconds, 30)

        ready = decisions.evaluate_phase_switch_timing(
            candidate_mode=2,
            candidate_since=100,
            target_phase_mode=2,
            delay_seconds=120,
            cooldown_seconds=0,
            now=220,
        )
        self.assertEqual(ready.action, decisions.PHASE_SWITCH_READY)
        self.assertEqual(ready.next_candidate_mode, 2)
        self.assertEqual(ready.next_candidate_since, 100)

    def test_shared_phase_timing_applies_to_phase_down(self):
        waiting = decisions.evaluate_phase_switch_timing(
            candidate_mode=0,
            candidate_since=0,
            target_phase_mode=1,
            delay_seconds=600,
            cooldown_seconds=0,
            now=100,
        )
        self.assertEqual(waiting.action, decisions.PHASE_SWITCH_WAIT_STABLE)
        self.assertEqual(waiting.next_candidate_mode, 1)

        ready = decisions.evaluate_phase_switch_timing(
            candidate_mode=1,
            candidate_since=100,
            target_phase_mode=1,
            delay_seconds=600,
            cooldown_seconds=0,
            now=700,
        )
        self.assertEqual(ready.action, decisions.PHASE_SWITCH_READY)

    def test_shared_phase_timing_allows_immediate_switch_when_delay_is_disabled(self):
        ready = decisions.evaluate_phase_switch_timing(
            candidate_mode=0,
            candidate_since=0,
            target_phase_mode=2,
            delay_seconds=0,
            cooldown_seconds=0,
            now=100,
        )
        self.assertEqual(ready.action, decisions.PHASE_SWITCH_READY)
        self.assertEqual(ready.stable_seconds, 0)

    def test_phase_up_drop_grace_preserves_only_short_three_phase_capable_dips(self):
        started = decisions.evaluate_phase_up_drop_grace(
            candidate_mode=2,
            allowance_w=4180,
            phase_up_threshold=4200,
            phase_down_threshold=4140,
            below_threshold_since=0,
            grace_seconds=20,
            now=100,
        )
        self.assertTrue(started.preserve_candidate)
        self.assertEqual(started.next_below_threshold_since, 100)
        self.assertEqual(started.reason, decisions.PHASE_UP_DROP_GRACE_STARTED)

        active = decisions.evaluate_phase_up_drop_grace(
            candidate_mode=2,
            allowance_w=4180,
            phase_up_threshold=4200,
            phase_down_threshold=4140,
            below_threshold_since=100,
            grace_seconds=20,
            now=119,
        )
        self.assertTrue(active.preserve_candidate)
        self.assertEqual(active.reason, decisions.PHASE_UP_DROP_GRACE_ACTIVE)

        expired = decisions.evaluate_phase_up_drop_grace(
            candidate_mode=2,
            allowance_w=4180,
            phase_up_threshold=4200,
            phase_down_threshold=4140,
            below_threshold_since=100,
            grace_seconds=20,
            now=120,
        )
        self.assertFalse(expired.preserve_candidate)
        self.assertEqual(expired.reason, decisions.PHASE_UP_DROP_GRACE_EXPIRED)

        below_minimum = decisions.evaluate_phase_up_drop_grace(
            candidate_mode=2,
            allowance_w=4139,
            phase_up_threshold=4200,
            phase_down_threshold=4140,
            below_threshold_since=0,
            grace_seconds=20,
            now=100,
        )
        self.assertFalse(below_minimum.preserve_candidate)
        self.assertEqual(
            below_minimum.reason,
            decisions.PHASE_UP_DROP_BELOW_MINIMUM,
        )

    def test_phase_up_drop_grace_clears_when_full_threshold_recovers(self):
        recovered = decisions.evaluate_phase_up_drop_grace(
            candidate_mode=2,
            allowance_w=4200,
            phase_up_threshold=4200,
            phase_down_threshold=4140,
            below_threshold_since=100,
            grace_seconds=20,
            now=110,
        )
        self.assertFalse(recovered.preserve_candidate)
        self.assertEqual(recovered.next_below_threshold_since, 0)
        self.assertEqual(recovered.reason, decisions.PHASE_UP_DROP_RECOVERED)


if __name__ == "__main__":
    unittest.main()
