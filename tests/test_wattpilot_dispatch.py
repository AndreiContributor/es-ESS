import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


def _module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _install_runtime_stubs():
    paho = _module("paho")
    paho.__path__ = []
    paho_mqtt = _module("paho.mqtt")
    paho_mqtt.__path__ = []
    paho_mqtt_client = _module("paho.mqtt.client", Client=object)
    paho.mqtt = paho_mqtt
    paho_mqtt.client = paho_mqtt_client

    _module("vedbus", VeDbusService=object)
    _module("requests")
    _module(
        "Globals",
        esEssTagService="test",
        esEssTag="test",
        currentVersionString="test",
    )
    _module(
        "Helper",
        i=lambda *args, **kwargs: None,
        c=lambda *args, **kwargs: None,
        d=lambda *args, **kwargs: None,
        w=lambda *args, **kwargs: None,
        e=lambda *args, **kwargs: None,
        t=lambda *args, **kwargs: None,
        dbusConnection=lambda: None,
        waitTimeout=lambda *args, **kwargs: False,
    )
    _module("Wattpilot", Wattpilot=type("Wattpilot", (), {}))
    _module("esESSService", esESSService=type("esESSService", (), {}))

    sys.modules.pop("enums", None)
    _load_module("enums", ROOT / "enums.py")


class WattpilotDispatchCharacterizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.fwp = _load_module(
            "wattpilot_dispatch_fwp_under_test",
            ROOT / "FroniusWattpilot.py",
        )

    def _controller(self):
        controller = self.fwp.FroniusWattpilot.__new__(self.fwp.FroniusWattpilot)
        controller.mode = self.fwp.VrmEvChargerControlMode.Auto
        controller.allowGridCharging = False
        controller.currentPhaseMode = 1
        controller.chargingTime = 0
        controller.noChargeSince = 25
        controller.surplusSince = 30
        controller.surplusBelowMinimumSince = 35
        controller.noAllowanceForcedOff = True
        controller.wattpilot = SimpleNamespace(modelStatus=SimpleNamespace(value=999))

        controller.publishServiceMessage = Mock()
        controller.wattpilotReportsActiveCharge = Mock(return_value=True)
        controller.reportVRMStatus = Mock()
        controller.forceStopForNoAllowance = Mock()
        controller.switchToOnePhaseForPvDip = Mock(
            return_value=self.fwp.VrmEvChargerStatus.SwitchingTo1Phase
        )
        controller.clearBatteryAssist = Mock()
        controller.clearBatteryAssistLockout = Mock()
        controller.clearChargeCompleteHold = Mock()
        controller.clearPowerTransitionGrace = Mock()
        controller.clearPendingPhaseSwitch = Mock()
        controller.handleChargingState = Mock()
        controller.handleNotChargingState = Mock()
        controller.handleExternalChargingState = Mock()
        return controller

    def test_every_control_state_preserves_dispatch_return_semantics(self):
        state = self.fwp.ControlStates.WattpilotControlState
        expected_results = {
            state.TRANSPORT_UNAVAILABLE: False,
            state.GRID_TELEMETRY_UNSAFE: True,
            state.GRID_IMPORT_PHASE_DOWN: True,
            state.GRID_IMPORT_STOP: True,
            state.PENDING_PHASE_SWITCH: True,
            state.DISCONNECTED: False,
            state.CHARGING: False,
            state.NOT_CHARGING: False,
            state.EXTERNAL_LOW_PRICE: False,
            state.PHASE_SWITCHING: False,
            state.UNKNOWN: False,
        }

        for selected_state, expected_result in expected_results.items():
            with self.subTest(selected_state=selected_state):
                controller = self._controller()
                result = controller.dispatchControlState(
                    selected_state,
                    True,
                    self.fwp.VrmEvChargerStatus.SwitchingTo3Phase,
                )
                self.assertEqual(result, expected_result)

    def test_every_control_state_delegates_to_its_named_handler(self):
        state = self.fwp.ControlStates.WattpilotControlState
        pending_status = self.fwp.VrmEvChargerStatus.SwitchingTo3Phase
        expected_delegations = {
            state.TRANSPORT_UNAVAILABLE: ("_handleTransportUnavailable", ()),
            state.GRID_TELEMETRY_UNSAFE: ("_handleGridTelemetryUnsafe", ()),
            state.GRID_IMPORT_PHASE_DOWN: ("_handleGridImportPhaseDown", ()),
            state.GRID_IMPORT_STOP: ("_handleGridImportStop", ()),
            state.PENDING_PHASE_SWITCH: (
                "_handlePendingPhaseSwitch",
                (pending_status,),
            ),
            state.DISCONNECTED: ("_handleDisconnected", ()),
            state.CHARGING: ("handleChargingState", ()),
            state.NOT_CHARGING: ("handleNotChargingState", ()),
            state.EXTERNAL_LOW_PRICE: ("_handleExternalLowPrice", ()),
            state.PHASE_SWITCHING: ("_handlePhaseSwitching", ()),
            state.UNKNOWN: ("_handleUnknownControlState", ()),
        }

        for selected_state, (handler_name, expected_args) in expected_delegations.items():
            with self.subTest(selected_state=selected_state):
                controller = self._controller()
                handler = Mock(return_value=False)
                setattr(controller, handler_name, handler)

                controller.dispatchControlState(
                    selected_state,
                    True,
                    pending_status,
                )

                handler.assert_called_once_with(*expected_args)

    def test_grid_telemetry_unsafe_handler_stops_active_charge(self):
        controller = self._controller()

        result = controller._handleGridTelemetryUnsafe()

        self.assertTrue(result)
        controller.publishServiceMessage.assert_called_once_with(
            controller,
            "Grid telemetry is missing, invalid, or stale. "
            "Stopping Auto/Eco charging for safety.",
        )
        controller.reportVRMStatus.assert_called_once_with(
            self.fwp.VrmEvChargerStatus.StopCharging
        )
        controller.forceStopForNoAllowance.assert_called_once_with()

    def test_disconnected_handler_preserves_all_controller_resets(self):
        controller = self._controller()

        result = controller._handleDisconnected()

        self.assertFalse(result)
        controller.reportVRMStatus.assert_called_once_with(
            self.fwp.VrmEvChargerStatus.Disconnected
        )
        self.assertEqual(controller.noChargeSince, 0)
        self.assertEqual(controller.surplusSince, 0)
        self.assertEqual(controller.surplusBelowMinimumSince, 0)
        self.assertFalse(controller.noAllowanceForcedOff)
        controller.clearBatteryAssist.assert_called_once_with()
        controller.clearBatteryAssistLockout.assert_called_once_with(
            "car disconnected"
        )
        controller.clearChargeCompleteHold.assert_called_once_with(
            "car disconnected"
        )
        controller.clearPowerTransitionGrace.assert_called_once_with()
        controller.clearPendingPhaseSwitch.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
