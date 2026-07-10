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

    def test_phase_up_timing_waits_for_stability_then_cooldown_then_switch(self):
        first = decisions.evaluate_phase_up_timing(
            candidate_mode=0,
            candidate_since=0,
            target_phase_mode=2,
            delay_seconds=120,
            cooldown_seconds=0,
            now=100,
        )
        self.assertEqual(first.action, decisions.PHASE_UP_WAIT_STABLE)
        self.assertEqual(first.next_candidate_mode, 2)
        self.assertEqual(first.next_candidate_since, 100)
        self.assertEqual(first.stable_seconds, 0)

        stable = decisions.evaluate_phase_up_timing(
            candidate_mode=2,
            candidate_since=100,
            target_phase_mode=2,
            delay_seconds=120,
            cooldown_seconds=30,
            now=220,
        )
        self.assertEqual(stable.action, decisions.PHASE_UP_WAIT_COOLDOWN)
        self.assertEqual(stable.stable_seconds, 120)
        self.assertEqual(stable.cooldown_seconds, 30)

        ready = decisions.evaluate_phase_up_timing(
            candidate_mode=2,
            candidate_since=100,
            target_phase_mode=2,
            delay_seconds=120,
            cooldown_seconds=0,
            now=220,
        )
        self.assertEqual(ready.action, decisions.PHASE_UP_SWITCH)
        self.assertEqual(ready.next_candidate_mode, 2)
        self.assertEqual(ready.next_candidate_since, 100)

    def test_phase_up_timing_allows_immediate_switch_when_delay_is_disabled(self):
        ready = decisions.evaluate_phase_up_timing(
            candidate_mode=0,
            candidate_since=0,
            target_phase_mode=2,
            delay_seconds=0,
            cooldown_seconds=0,
            now=100,
        )
        self.assertEqual(ready.action, decisions.PHASE_UP_SWITCH)
        self.assertEqual(ready.stable_seconds, 0)


if __name__ == "__main__":
    unittest.main()
