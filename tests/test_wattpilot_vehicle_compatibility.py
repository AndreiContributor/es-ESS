"""Hardware-free tests for native Wattpilot vehicle compatibility parsing."""

import unittest

import WattpilotVehicleCompatibility as Compatibility


def complete_properties():
    return {
        "mca": 7,
        "acp": True,
        "mci": 0,
        "mcpd": 60000,
        "mcpea": None,
        "fmt": 300000,
        "su": True,
        "sua": False,
        "sumd": 10000,
        "mpwst": 120000,
        "mptwt": 600000,
        "modelStatus": 4,
    }


class WattpilotVehicleCompatibilityTests(unittest.TestCase):
    def test_complete_firmware_42_5_snapshot_is_valid(self):
        snapshot = Compatibility.parse_vehicle_compatibility(
            complete_properties(), "42.5", True
        )

        self.assertTrue(snapshot.minimum_current_valid)
        self.assertEqual(snapshot.minimum_current_a, 7)
        self.assertEqual(snapshot.minimum_charge_time_ms, 300000)
        self.assertEqual(snapshot.diagnostics_literal, "Validated")
        self.assertEqual(snapshot.missing_fields, ())
        self.assertEqual(snapshot.invalid_fields, ())

    def test_profile_owned_missing_field_is_partial_not_fabricated(self):
        properties = complete_properties()
        del properties["acp"]

        snapshot = Compatibility.parse_vehicle_compatibility(
            properties, "42.5", True
        )

        self.assertTrue(snapshot.minimum_current_valid)
        self.assertIsNone(snapshot.allow_charge_pause)
        self.assertIn("acp", snapshot.missing_fields)
        self.assertEqual(snapshot.diagnostics_literal, "Partial: missing acp")

    def test_wrong_types_and_out_of_range_current_are_invalid(self):
        properties = complete_properties()
        properties.update({"mca": 5, "acp": 1, "fmt": -1})

        snapshot = Compatibility.parse_vehicle_compatibility(
            properties, "42.5", True
        )

        self.assertFalse(snapshot.minimum_current_valid)
        self.assertIsNone(snapshot.minimum_current_a)
        self.assertEqual(snapshot.allow_charge_pause, None)
        self.assertEqual(snapshot.minimum_charge_time_ms, None)
        self.assertEqual(snapshot.invalid_fields, ("acp", "fmt", "mca"))

    def test_unvalidated_firmware_and_partial_status_cannot_supply_minimum(self):
        wrong_firmware = Compatibility.parse_vehicle_compatibility(
            complete_properties(), "42.6", True
        )
        partial_status = Compatibility.parse_vehicle_compatibility(
            complete_properties(), "42.5", False
        )

        self.assertFalse(wrong_firmware.minimum_current_valid)
        self.assertFalse(partial_status.minimum_current_valid)
        self.assertIn("firmware not validated", wrong_firmware.diagnostics_literal)
        self.assertIn("full status pending", partial_status.diagnostics_literal)

    def test_effective_minimum_uses_stricter_value_and_never_exceeds_maximum(self):
        snapshot = Compatibility.parse_vehicle_compatibility(
            complete_properties(), "42.5", True
        )

        self.assertEqual(snapshot.effective_minimum_current(6, 16), 7)
        self.assertEqual(snapshot.effective_minimum_current(8, 16), 8)
        self.assertIsNone(snapshot.effective_minimum_current(6, 6))

    def test_optional_pause_end_accepts_null_and_rejects_invalid_value(self):
        properties = complete_properties()
        snapshot = Compatibility.parse_vehicle_compatibility(
            properties, "42.5", True
        )
        self.assertIsNone(snapshot.minimum_charge_pause_ends_at_ms)
        self.assertNotIn("mcpea", snapshot.invalid_fields)

        properties["mcpea"] = "later"
        invalid = Compatibility.parse_vehicle_compatibility(
            properties, "42.5", True
        )
        self.assertIn("mcpea", invalid.invalid_fields)


if __name__ == "__main__":
    unittest.main()
