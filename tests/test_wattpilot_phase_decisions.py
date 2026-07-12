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
