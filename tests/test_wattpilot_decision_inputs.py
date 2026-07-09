import unittest

import WattpilotDecisionInputs as inputs


class WattpilotDecisionInputsTests(unittest.TestCase):
    def test_finite_number_accepts_only_finite_values(self):
        self.assertEqual(inputs.finite_number("12.5"), 12.5)
        self.assertIsNone(inputs.finite_number(None))
        self.assertIsNone(inputs.finite_number("nan"))
        self.assertIsNone(inputs.finite_number("inf"))
        self.assertIsNone(inputs.finite_number("not-a-number"))

    def test_parse_finite_payload_handles_bytes_and_rejects_non_finite(self):
        self.assertEqual(inputs.parse_finite_payload(b" 1380 "), 1380.0)

        with self.assertRaises(ValueError):
            inputs.parse_finite_payload(b"nan")

    def test_telemetry_sample_records_validity_and_receive_time(self):
        self.assertEqual(inputs.telemetry_sample("1.2", 100), (True, 100))
        self.assertEqual(inputs.telemetry_sample("nan", 101), (False, 101))
        self.assertEqual(inputs.telemetry_sample(None, 102), (False, 102))

    def test_timestamped_freshness_preserves_cutoff_boundary(self):
        self.assertTrue(
            inputs.timestamped_value_is_fresh(True, 85, 15, 100)
        )
        self.assertFalse(
            inputs.timestamped_value_is_fresh(True, 84.999, 15, 100)
        )
        self.assertFalse(
            inputs.timestamped_value_is_fresh(False, 100, 15, 100)
        )
        self.assertFalse(
            inputs.timestamped_value_is_fresh(True, 0, 15, 100)
        )

    def test_grid_telemetry_requires_every_phase_valid_and_fresh(self):
        self.assertTrue(
            inputs.grid_telemetry_is_fresh(
                [(True, 100), (True, 99), (True, 85)], 15, 100
            )
        )
        self.assertFalse(
            inputs.grid_telemetry_is_fresh(
                [(True, 100), (False, 100), (True, 100)], 15, 100
            )
        )
        self.assertFalse(
            inputs.grid_telemetry_is_fresh(
                [(True, 100), (True, 84.999), (True, 100)], 15, 100
            )
        )

    def test_minimum_allowance_requires_fresh_assigned_allowance_and_limit(self):
        self.assertTrue(
            inputs.has_minimum_allowance(1380, True, 85, 15, 100, 1380, True)
        )
        self.assertFalse(
            inputs.has_minimum_allowance(1379, True, 85, 15, 100, 1380, True)
        )
        self.assertFalse(
            inputs.has_minimum_allowance(1380, True, 84.999, 15, 100, 1380, True)
        )
        self.assertFalse(
            inputs.has_minimum_allowance(1380, False, 100, 15, 100, 1380, True)
        )
        self.assertFalse(
            inputs.has_minimum_allowance(1380, True, 100, 15, 100, 1380, False)
        )

    def test_fresh_raw_overhead_returns_non_negative_recent_value_only(self):
        self.assertEqual(inputs.fresh_raw_overhead(2000, 85, 15, 100), 2000)
        self.assertEqual(inputs.fresh_raw_overhead(-10, 100, 15, 100), 0)
        self.assertIsNone(inputs.fresh_raw_overhead(2000, 84.999, 15, 100))
        self.assertIsNone(inputs.fresh_raw_overhead(2000, 0, 15, 100))
        self.assertIsNone(inputs.fresh_raw_overhead("nan", 100, 15, 100))


if __name__ == "__main__":
    unittest.main()
