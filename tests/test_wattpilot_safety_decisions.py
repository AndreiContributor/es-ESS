import unittest

import WattpilotSafetyDecisions as decisions


class WattpilotSafetyDecisionTests(unittest.TestCase):
    def test_grid_import_guard_starts_waits_exceeds_and_resets(self):
        started = decisions.evaluate_grid_import_guard(
            False, 200, 0, 150, 5, 100
        )
        self.assertFalse(started.limit_exceeded)
        self.assertEqual(started.next_import_since, 100)
        self.assertEqual(started.reason, decisions.GRID_IMPORT_STARTED)

        waiting = decisions.evaluate_grid_import_guard(
            False, 200, started.next_import_since, 150, 5, 104
        )
        self.assertFalse(waiting.limit_exceeded)
        self.assertEqual(waiting.next_import_since, 100)
        self.assertEqual(waiting.reason, decisions.GRID_IMPORT_WAITING)

        exceeded = decisions.evaluate_grid_import_guard(
            False, 200, started.next_import_since, 150, 5, 105
        )
        self.assertTrue(exceeded.limit_exceeded)
        self.assertEqual(exceeded.next_import_since, 100)
        self.assertEqual(exceeded.reason, decisions.GRID_IMPORT_EXCEEDED)

        reset = decisions.evaluate_grid_import_guard(
            False, 150, started.next_import_since, 150, 5, 106
        )
        self.assertFalse(reset.limit_exceeded)
        self.assertEqual(reset.next_import_since, 0)
        self.assertEqual(reset.reason, decisions.GRID_IMPORT_BELOW_THRESHOLD)

    def test_grid_import_guard_is_disabled_when_grid_charging_allowed(self):
        result = decisions.evaluate_grid_import_guard(
            True, 1000, 50, 150, 5, 100
        )
        self.assertFalse(result.limit_exceeded)
        self.assertEqual(result.next_import_since, 0)
        self.assertEqual(result.reason, decisions.GRID_IMPORT_ALLOWED)

    def test_battery_assist_recovery_requires_continuous_zero_shortfall(self):
        started = decisions.evaluate_battery_assist_recovery(
            True, 0, 0, 60, 500
        )
        self.assertTrue(started.recovery_started)
        self.assertFalse(started.clear_lockout)
        self.assertEqual(started.next_recovery_since, 500)

        waiting = decisions.evaluate_battery_assist_recovery(
            True, 0, started.next_recovery_since, 60, 559
        )
        self.assertFalse(waiting.clear_lockout)
        self.assertEqual(waiting.reason, decisions.BATTERY_RECOVERY_WAITING)

        complete = decisions.evaluate_battery_assist_recovery(
            True, 0, started.next_recovery_since, 60, 560
        )
        self.assertTrue(complete.clear_lockout)
        self.assertEqual(complete.reason, decisions.BATTERY_RECOVERY_COMPLETE)

    def test_battery_assist_recovery_interruption_resets_timer(self):
        interrupted = decisions.evaluate_battery_assist_recovery(
            True, 100, 500, 60, 550
        )
        self.assertTrue(interrupted.recovery_interrupted)
        self.assertEqual(interrupted.next_recovery_since, 0)
        self.assertEqual(interrupted.reason, decisions.BATTERY_RECOVERY_INTERRUPTED)

    def test_battery_assist_allows_running_charge_until_time_limit(self):
        started = decisions.evaluate_battery_assist(
            True, 1000, False, 2.3, 80, 60, 3000, 0, 150, 0, 300, 100
        )
        self.assertTrue(started.allow_assist)
        self.assertTrue(started.assist_started)
        self.assertFalse(started.time_limit_reached)
        self.assertEqual(started.next_assist_since, 100)

        still_active = decisions.evaluate_battery_assist(
            True, 1000, False, 2.3, 80, 60, 3000, 0, 150, 100, 300, 399
        )
        self.assertTrue(still_active.allow_assist)
        self.assertFalse(still_active.assist_started)
        self.assertEqual(still_active.reason, decisions.BATTERY_ASSIST_ACTIVE)

        timed_out = decisions.evaluate_battery_assist(
            True, 1000, False, 2.3, 80, 60, 3000, 0, 150, 100, 300, 400
        )
        self.assertFalse(timed_out.allow_assist)
        self.assertTrue(timed_out.time_limit_reached)
        self.assertEqual(timed_out.reason, decisions.BATTERY_ASSIST_TIME_LIMIT)

    def test_battery_assist_rejects_non_running_or_unsafe_conditions(self):
        cases = [
            (False, 1000, False, 2.3, 80, 60, 3000, 0, 150),
            (True, 0, False, 2.3, 80, 60, 3000, 0, 150),
            (True, 1000, True, 2.3, 80, 60, 3000, 0, 150),
            (True, 1000, False, 0, 80, 60, 3000, 0, 150),
            (True, 1000, False, 2.3, 59, 60, 3000, 0, 150),
            (True, 3001, False, 2.3, 80, 60, 3000, 0, 150),
            (True, 1000, False, 2.3, 80, 60, 3000, 151, 150),
        ]

        for case in cases:
            with self.subTest(case=case):
                result = decisions.evaluate_battery_assist(
                    *case,
                    assist_since=0,
                    max_seconds=300,
                    now=100
                )
                self.assertFalse(result.allow_assist)


if __name__ == "__main__":
    unittest.main()
