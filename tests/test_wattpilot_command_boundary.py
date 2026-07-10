"""Hardware-free regressions for Wattpilot writable command boundaries."""

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


class WattpilotCommandBoundaryTests(unittest.TestCase):
    """Lock direct D-Bus command writes to confirmed Wattpilot ECO mode."""

    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.fwp = _load_module(
            "wattpilot_command_boundary_fwp_under_test",
            ROOT / "FroniusWattpilot.py",
        )

    def _controller(self):
        controller = self.fwp.FroniusWattpilot.__new__(self.fwp.FroniusWattpilot)
        controller.minCurrentPerPhase = 6
        controller.maxCurrentPerPhase = 16
        controller.currentPhaseMode = 1
        controller.mode = self.fwp.VrmEvChargerControlMode.Auto
        controller.autostart = 1
        controller.dbusService = {
            "/Mode": self.fwp.VrmEvChargerControlMode.Auto.value,
            "/ModeLiteral": self.fwp.VrmEvChargerControlMode.Auto.name,
            "/StartStop": self.fwp.VrmEvChargerStartStop.Stop.value,
            "/StartStopLiteral": self.fwp.VrmEvChargerStartStop.Stop.name,
        }
        controller.wattpilot = SimpleNamespace(
            ampLimit=None,
            voltage1=230,
            mode=self.fwp.WattpilotControlMode.ECO,
            set_power=Mock(),
            set_phases=Mock(),
            set_start_stop=Mock(),
            set_mode=Mock(),
        )
        controller.serviceMessages = []
        controller.publishServiceMessage = (
            lambda _service, message, *args, **kwargs:
            controller.serviceMessages.append(message)
        )
        controller.dumpEvChargerInfo = Mock()
        controller.clearChargeCompleteHold = Mock()
        return controller

    def test_set_current_is_rejected_when_wattpilot_reports_manual_mode(self):
        controller = self._controller()
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default

        self.assertFalse(controller._froniusHandleChangedValue("/SetCurrent", 12))

        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_phases.assert_not_called()
        self.assertIn("/SetCurrent", controller.serviceMessages[-1])
        controller.dumpEvChargerInfo.assert_called_once()

    def test_start_stop_is_rejected_when_wattpilot_reports_manual_mode(self):
        controller = self._controller()
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default

        self.assertFalse(
            controller._froniusHandleChangedValue(
                "/StartStop",
                self.fwp.VrmEvChargerStartStop.Start.value,
            )
        )
        self.assertFalse(
            controller._froniusHandleChangedValue(
                "/StartStop",
                self.fwp.VrmEvChargerStartStop.Stop.value,
            )
        )

        controller.wattpilot.set_start_stop.assert_not_called()
        self.assertEqual(
            controller.dbusService["/StartStopLiteral"],
            self.fwp.VrmEvChargerStartStop.Stop.name,
        )
        self.assertEqual(len(controller.serviceMessages), 2)
        self.assertTrue(
            all("/StartStop" in message for message in controller.serviceMessages)
        )

    def test_missing_wattpilot_mode_telemetry_fails_closed(self):
        controller = self._controller()
        delattr(controller.wattpilot, "mode")

        self.assertFalse(controller._froniusHandleChangedValue("/SetCurrent", 12))

        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_phases.assert_not_called()
        self.assertIn("not in Auto/ECO mode", controller.serviceMessages[-1])

    def test_eco_mode_accepts_direct_current_and_start_stop_writes(self):
        controller = self._controller()

        self.assertTrue(controller._froniusHandleChangedValue("/SetCurrent", 18))

        controller.wattpilot.set_phases.assert_called_once_with(2)
        controller.wattpilot.set_power.assert_called_once_with(6)

        self.assertTrue(
            controller._froniusHandleChangedValue(
                "/StartStop",
                self.fwp.VrmEvChargerStartStop.Start.value,
            )
        )

        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.On
        )
        self.assertEqual(
            controller.dbusService["/StartStopLiteral"],
            self.fwp.VrmEvChargerStartStop.Start.name,
        )

    def test_mode_write_can_still_select_auto_and_manual(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Manual
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default

        self.assertTrue(
            controller._froniusHandleChangedValue(
                "/Mode",
                self.fwp.VrmEvChargerControlMode.Auto.value,
            )
        )

        controller.wattpilot.set_mode.assert_called_once_with(
            self.fwp.WattpilotControlMode.ECO
        )
        self.assertEqual(controller.autostart, 1)
        self.assertEqual(
            controller.dbusService["/ModeLiteral"],
            self.fwp.VrmEvChargerControlMode.Auto.name,
        )

        controller.wattpilot.set_mode.reset_mock()
        controller.mode = self.fwp.VrmEvChargerControlMode.Auto
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.ECO

        self.assertTrue(
            controller._froniusHandleChangedValue(
                "/Mode",
                self.fwp.VrmEvChargerControlMode.Manual.value,
            )
        )

        controller.wattpilot.set_mode.assert_called_once_with(
            self.fwp.WattpilotControlMode.Default
        )
        controller.wattpilot.set_phases.assert_called_once_with(0)
        controller.wattpilot.set_power.assert_called_once_with(
            controller.getEffectiveMaxCurrent()
        )
        controller.clearChargeCompleteHold.assert_called_once_with(
            "manual mode selected"
        )
        self.assertEqual(controller.autostart, 0)
        self.assertEqual(
            controller.dbusService["/ModeLiteral"],
            self.fwp.VrmEvChargerControlMode.Manual.name,
        )

    def test_observed_manual_mode_releases_auto_phase_and_current_once(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Auto
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default
        controller.wattpilot.connected = True
        controller.wattpilot.carStateReady = True
        controller.wattpilot.carConnected = True
        controller.wattpilot.power = 1.4
        controller.wattpilot.modelStatus = SimpleNamespace(value=15)
        controller.updateWattpilotTransportDashboardStatus = Mock(return_value=False)
        controller.updateEffectiveCarConnection = Mock(return_value=True)
        controller.isIdleMode = False
        controller.lastVarDump = 0
        controller.reportStartStopValue = Mock()
        controller.publishSafetyTelemetry = Mock()
        controller.gridTelemetryIsFresh = Mock(return_value=True)
        controller.selectControlState = Mock(
            return_value=(
                self.fwp.ControlStates.WattpilotControlState.CHARGING,
                None,
                None,
            )
        )
        controller.dispatchControlState = Mock(return_value=False)
        controller.reportBaseRequest = Mock()

        controller._update()

        controller.wattpilot.set_phases.assert_called_once_with(0)
        controller.wattpilot.set_power.assert_called_once_with(
            controller.getEffectiveMaxCurrent()
        )
        controller.dispatchControlState.assert_called_once_with(
            self.fwp.ControlStates.WattpilotControlState.CHARGING,
            True,
            None,
        )

        controller.wattpilot.set_phases.reset_mock()
        controller.wattpilot.set_power.reset_mock()
        controller.dispatchControlState.reset_mock()

        controller._update()

        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_not_called()
        controller.dispatchControlState.assert_called_once_with(
            self.fwp.ControlStates.WattpilotControlState.CHARGING,
            True,
            None,
        )


if __name__ == "__main__":
    unittest.main()
