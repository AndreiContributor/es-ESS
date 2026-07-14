import unittest

import WattpilotControlState as states


class WattpilotControlStateTests(unittest.TestCase):
    def _inputs(self, **overrides):
        values = {
            "transport_unavailable": False,
            "auto_mode": True,
            "command_authority_ok": True,
            "allow_grid_charging": False,
            "grid_telemetry_fresh": True,
            "grid_import_limit_exceeded": False,
            "current_phase_mode": 1,
            "phase_down_for_pv_dip": False,
            "pending_phase_status": False,
            "effective_car_connected": True,
            "model_status_value": 4,
            "external_low_price": False,
            "phase_switching": False,
        }
        values.update(overrides)
        return states.ControlStateInputs(**values)

    def test_transport_unavailable_wins_over_every_other_state(self):
        selected = states.select_control_state(
            self._inputs(
                transport_unavailable=True,
                grid_telemetry_fresh=False,
                grid_import_limit_exceeded=True,
                current_phase_mode=2,
                phase_down_for_pv_dip=True,
                pending_phase_status=True,
                effective_car_connected=False,
                model_status_value=3,
            )
        )

        self.assertEqual(selected, states.WattpilotControlState.TRANSPORT_UNAVAILABLE)

    def test_stale_grid_telemetry_wins_before_grid_import_and_pending_phase(self):
        selected = states.select_control_state(
            self._inputs(
                grid_telemetry_fresh=False,
                grid_import_limit_exceeded=True,
                current_phase_mode=2,
                phase_down_for_pv_dip=True,
                pending_phase_status=True,
            )
        )

        self.assertEqual(selected, states.WattpilotControlState.GRID_TELEMETRY_UNSAFE)

    def test_invalid_command_authority_wins_before_grid_and_charge_states(self):
        selected = states.select_control_state(
            self._inputs(
                command_authority_ok=False,
                grid_telemetry_fresh=False,
                grid_import_limit_exceeded=True,
                model_status_value=3,
            )
        )

        self.assertEqual(
            selected,
            states.WattpilotControlState.COMMAND_AUTHORITY_BLOCKED,
        )

    def test_manual_mode_ignores_auto_command_authority_state(self):
        selected = states.select_control_state(
            self._inputs(
                auto_mode=False,
                command_authority_ok=False,
                model_status_value=3,
            )
        )

        self.assertEqual(selected, states.WattpilotControlState.CHARGING)

    def test_manual_mode_does_not_enter_auto_grid_safety_states(self):
        selected = states.select_control_state(
            self._inputs(
                auto_mode=False,
                grid_telemetry_fresh=False,
                grid_import_limit_exceeded=True,
                current_phase_mode=2,
                phase_down_for_pv_dip=True,
                model_status_value=3,
            )
        )

        self.assertEqual(selected, states.WattpilotControlState.CHARGING)

    def test_grid_import_prefers_safe_phase_down_before_stop(self):
        selected = states.select_control_state(
            self._inputs(
                grid_import_limit_exceeded=True,
                current_phase_mode=2,
                phase_down_for_pv_dip=True,
            )
        )

        self.assertEqual(selected, states.WattpilotControlState.GRID_IMPORT_PHASE_DOWN)

    def test_grid_import_stops_when_phase_down_is_not_available(self):
        selected = states.select_control_state(
            self._inputs(
                grid_import_limit_exceeded=True,
                current_phase_mode=2,
                phase_down_for_pv_dip=False,
            )
        )

        self.assertEqual(selected, states.WattpilotControlState.GRID_IMPORT_STOP)

    def test_pending_phase_switch_wins_before_disconnect_and_model_status(self):
        selected = states.select_control_state(
            self._inputs(
                pending_phase_status=True,
                effective_car_connected=False,
                model_status_value=3,
            )
        )

        self.assertEqual(selected, states.WattpilotControlState.PENDING_PHASE_SWITCH)

    def test_confirmed_disconnect_wins_before_model_status(self):
        selected = states.select_control_state(
            self._inputs(
                effective_car_connected=False,
                model_status_value=3,
            )
        )

        self.assertEqual(selected, states.WattpilotControlState.DISCONNECTED)

    def test_model_status_values_select_charging_and_not_charging(self):
        self.assertEqual(
            states.select_control_state(self._inputs(model_status_value=3)),
            states.WattpilotControlState.CHARGING,
        )
        self.assertEqual(
            states.select_control_state(self._inputs(model_status_value=24)),
            states.WattpilotControlState.NOT_CHARGING,
        )

    def test_special_model_statuses_select_external_and_phase_switching(self):
        self.assertEqual(
            states.select_control_state(
                self._inputs(external_low_price=True, model_status_value=None)
            ),
            states.WattpilotControlState.EXTERNAL_LOW_PRICE,
        )
        self.assertEqual(
            states.select_control_state(
                self._inputs(phase_switching=True, model_status_value=None)
            ),
            states.WattpilotControlState.PHASE_SWITCHING,
        )

    def test_unknown_model_status_is_explicit(self):
        selected = states.select_control_state(
            self._inputs(model_status_value=999)
        )

        self.assertEqual(selected, states.WattpilotControlState.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
