import unittest

import WattpilotSiteCurrentDecisions as decisions


class WattpilotSiteCurrentDecisionTests(unittest.TestCase):
    def test_three_phase_uses_smallest_headroom(self):
        result = decisions.evaluate_site_current(
            site_currents=(18, 8, 9),
            charger_currents=(8, 8, 8),
            measured_phase_mode=2,
            requested_phase_mode=2,
            one_phase_mapping="L1",
            site_max_current=20,
        )

        self.assertEqual(result.charger_contribution, (8, 8, 8))
        self.assertEqual(result.non_ev_currents, (10, 0, 1))
        self.assertEqual(result.headrooms, (10, 20, 19))
        self.assertEqual(result.allowed_current, 10)
        self.assertEqual(result.limiting_phase, "L1")

    def test_three_phase_allows_sixteen_when_house_load_is_four(self):
        result = decisions.evaluate_site_current(
            site_currents=(20, 20, 20),
            charger_currents=(16, 16, 16),
            measured_phase_mode=2,
            requested_phase_mode=2,
            one_phase_mapping="L1",
            site_max_current=20,
        )

        self.assertEqual(result.non_ev_currents, (4, 4, 4))
        self.assertEqual(result.allowed_current, 16)

    def test_unequal_three_phase_measurement_is_conservative(self):
        result = decisions.evaluate_site_current(
            site_currents=(17, 13, 11),
            charger_currents=(9, 8, 7),
            measured_phase_mode=2,
            requested_phase_mode=2,
            one_phase_mapping="L1",
            site_max_current=20,
        )

        self.assertEqual(result.charger_contribution, (7, 7, 7))
        self.assertEqual(result.non_ev_currents, (10, 6, 4))
        self.assertEqual(result.allowed_current, 10)

    def test_one_phase_uses_configured_physical_phase(self):
        result = decisions.evaluate_site_current(
            site_currents=(11, 18, 9),
            charger_currents=(8, 0, 0),
            measured_phase_mode=1,
            requested_phase_mode=1,
            one_phase_mapping="L2",
            site_max_current=20,
        )

        self.assertEqual(result.charger_contribution, (0, 8, 0))
        self.assertEqual(result.non_ev_currents, (11, 10, 9))
        self.assertEqual(result.allowed_current, 10)
        self.assertEqual(result.limiting_phase, "L2")

    def test_allowed_current_can_fall_below_wattpilot_minimum(self):
        result = decisions.evaluate_site_current(
            site_currents=(15.1, 4, 4),
            charger_currents=(0, 0, 0),
            measured_phase_mode=0,
            requested_phase_mode=1,
            one_phase_mapping="L1",
            site_max_current=20,
        )

        self.assertEqual(result.allowed_current, 4)

    def test_invalid_or_unsafe_inputs_are_rejected(self):
        invalid_cases = (
            ((1, 2), (0, 0, 0), 0, 1, "L1", 20),
            ((1, -1, 2), (0, 0, 0), 0, 1, "L1", 20),
            ((1, 2, 3), (0, float("nan"), 0), 0, 1, "L1", 20),
            ((1, 2, 3), (0, 0, 0), 3, 1, "L1", 20),
            ((1, 2, 3), (0, 0, 0), 0, 3, "L1", 20),
            ((1, 2, 3), (0, 0, 0), 0, 1, "L4", 20),
            ((1, 2, 3), (0, 0, 0), 0, 1, "L1", 0),
        )

        for args in invalid_cases:
            with self.subTest(args=args):
                with self.assertRaises((TypeError, ValueError)):
                    decisions.evaluate_site_current(*args)

    def test_recovery_reduces_immediately_then_waits_and_ramps(self):
        reduced = decisions.limit_current_recovery(12, 8, 100, 30, 110)
        self.assertEqual(reduced.allowed_current, 8)
        self.assertEqual(reduced.next_recovery_since, 0)

        started = decisions.limit_current_recovery(8, 12, 0, 30, 200)
        self.assertEqual(started.allowed_current, 8)
        self.assertEqual(started.next_recovery_since, 200)

        waiting = decisions.limit_current_recovery(8, 12, 200, 30, 229)
        self.assertEqual(waiting.allowed_current, 8)
        self.assertEqual(waiting.recovery_elapsed, 29)

        first_step = decisions.limit_current_recovery(8, 12, 200, 30, 230)
        self.assertEqual(first_step.allowed_current, 9)

        second_step = decisions.limit_current_recovery(9, 12, 200, 30, 235)
        self.assertEqual(second_step.allowed_current, 10)

    def test_new_reduction_resets_recovery(self):
        result = decisions.limit_current_recovery(10, 9, 200, 30, 235)
        self.assertEqual(result.allowed_current, 9)
        self.assertEqual(result.next_recovery_since, 0)


if __name__ == "__main__":
    unittest.main()
