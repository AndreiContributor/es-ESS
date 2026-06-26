"""Hardware-free regression coverage for PR #5 Wattpilot control fixes."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def _module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
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
    _module("Globals", esEssTagService="test", esEssTag="test")
    _module(
        "Helper",
        i=lambda *args, **kwargs: None,
        c=lambda *args, **kwargs: None,
        d=lambda *args, **kwargs: None,
        w=lambda *args, **kwargs: None,
        e=lambda *args, **kwargs: None,
        t=lambda *args, **kwargs: None,
        dbusConnection=lambda: None,
    )

    class VrmEvChargerControlMode:
        Manual = 0
        Auto = 1
        Scheduled = 2

    class WattpilotStartStop:
        Off = 0
        On = 1

    class WattpilotControlMode:
        Default = 0
        ECO = 1

    class VrmEvChargerStartStop:
        Stop = 0
        Start = 1

    _module(
        "enums",
        VrmEvChargerControlMode=VrmEvChargerControlMode,
        VrmEvChargerStatus=type("VrmEvChargerStatus", (), {}),
        VrmEvChargerStartStop=VrmEvChargerStartStop,
        WattpilotModelStatus=type("WattpilotModelStatus", (), {}),
        WattpilotStartStop=WattpilotStartStop,
        WattpilotControlMode=WattpilotControlMode,
    )
    _module("Wattpilot", Wattpilot=type("Wattpilot", (), {}))
    _module("esESSService", esESSService=type("esESSService", (), {}))


class Pr5ReviewFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.fwp = _load_module("fwp_under_test", ROOT / "FroniusWattpilot.py")
        cls.sod = _load_module(
            "sod_under_test", ROOT / "SolarOverheadDistributor.py"
        )

    def _controller(self):
        controller = self.fwp.FroniusWattpilot.__new__(self.fwp.FroniusWattpilot)
        controller.minCurrentPerPhase = 6
        controller.maxCurrentPerPhase = 16
        controller.threePhasePvSurplusStartW = 4200
        controller.threePhasePvSurplusStopW = 4140
        controller.currentPhaseMode = 1
        controller.wattpilot = SimpleNamespace(
            ampLimit=None,
            voltage1=230,
            voltage2=230,
            voltage3=230,
            carConnected=True,
            power=0,
            amp=0,
            set_power=Mock(),
            set_phases=Mock(),
        )
        controller.overheadAvailableDbus = SimpleNamespace(value=0)
        controller.publishServiceMessage = lambda *args, **kwargs: None
        controller.dumpEvChargerInfo = lambda: None
        return controller

    def test_transition_grace_expires_even_when_meter_telemetry_is_ready(self):
        controller = self._controller()
        controller.powerTransitionUntil = 100
        controller.powerTransitionExpectedW = 1000
        controller.powerTransitionTelemetryReadyAt = 0
        controller.allowanceUpdatedAt = 0
        controller.startupTelemetryRatio = 0.8
        controller.actualMeasuredPowerW = lambda: 1000
        controller.clearPowerTransitionGrace = (
            self.fwp.FroniusWattpilot.clearPowerTransitionGrace.__get__(controller)
        )

        with patch.object(self.fwp.time, "time", return_value=101):
            self.assertFalse(controller.powerTransitionGraceActive())

        self.assertEqual(controller.powerTransitionUntil, 0)

    def test_low_wattpilot_limit_never_rounds_up_to_configured_minimum(self):
        controller = self._controller()
        controller.wattpilot.ampLimit = 5
        controller.allowance = 10000

        self.assertFalse(controller.canChargeAtMinimumCurrent())
        self.assertFalse(controller.hasMinimumAllowance())
        self.assertEqual(controller.targetCurrentForPhase(1, 10000), 0)

    def test_manual_current_request_below_minimum_cap_is_stopped(self):
        controller = self._controller()
        controller.wattpilot.ampLimit = 5

        self.assertTrue(controller._froniusHandleChangedValue("/SetCurrent", 6))
        controller.wattpilot.set_power.assert_called_once_with(0)

    def test_request_is_zero_when_wattpilot_limit_is_below_minimum(self):
        controller = self._controller()
        controller.wattpilot.ampLimit = 5
        published = {}
        controller.mode = 1
        controller.chargeCompleteHold = False
        controller.noChargeSince = 0
        controller.chargeCompleteConfirmSeconds = 120
        controller.config = {
            "FroniusWattpilot": {
                "VRMInstanceID_OverheadRequest": "42",
                "OverheadPriority": "35",
            }
        }
        controller.publishMainMqtt = lambda topic, value: published.__setitem__(
            topic, value
        )
        controller.shouldIgnoreBatteryReservation = lambda: False
        controller.reportPhaseMode = lambda: None

        controller.reportBaseRequest()
        self.assertEqual(
            published["es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Request"],
            0,
        )

    def test_one_phase_request_only_advertises_three_phase_when_phase_up_is_possible(self):
        controller = self._controller()
        controller.overheadAvailableDbus.value = 3000
        self.assertEqual(controller.maxRequestVoltageForCurrentPhase(), 230)

        controller.overheadAvailableDbus.value = 5000
        self.assertEqual(controller.maxRequestVoltageForCurrentPhase(), 690)

        controller.currentPhaseMode = 2
        controller.overheadAvailableDbus.value = None
        self.assertEqual(controller.maxRequestVoltageForCurrentPhase(), 690)

    def test_reported_request_matches_current_or_reachable_phase_capacity(self):
        controller = self._controller()
        controller.mode = 1  # VrmEvChargerControlMode.Auto
        controller.chargeCompleteHold = False
        controller.noChargeSince = 0
        controller.chargeCompleteConfirmSeconds = 120
        controller.config = {
            "FroniusWattpilot": {
                "VRMInstanceID_OverheadRequest": "42",
                "OverheadPriority": "35",
            }
        }
        published = {}
        controller.publishMainMqtt = lambda topic, value: published.__setitem__(
            topic, value
        )
        controller.shouldIgnoreBatteryReservation = lambda: False
        controller.reportPhaseMode = lambda: None

        controller.overheadAvailableDbus.value = 3000
        controller.reportBaseRequest()
        self.assertEqual(
            published["es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Request"],
            3680,
        )

        controller.overheadAvailableDbus.value = 5000
        controller.reportBaseRequest()
        self.assertEqual(
            published["es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Request"],
            11040,
        )

    def test_battery_reservation_bypass_does_not_override_configured_priority(self):
        distributor = self.sod.SolarOverheadDistributor.__new__(
            self.sod.SolarOverheadDistributor
        )
        regular = SimpleNamespace(
            consumerKey="regular",
            customName="regular",
            isInitialized=True,
            isAutomatic=True,
            priority=10,
            priorityShift=0,
            ignoreBatReservation=False,
            request=1500,
            minimum=0,
            stepSize=1500,
            effectivePriority=0,
        )
        ev = SimpleNamespace(
            consumerKey="ev",
            customName="ev",
            isInitialized=True,
            isAutomatic=True,
            priority=35,
            priorityShift=0,
            ignoreBatReservation=True,
            request=1380,
            minimum=1380,
            stepSize=230,
            effectivePriority=0,
        )
        distributor._knownSolarOverheadConsumers = {"regular": regular, "ev": ev}

        assigned = distributor.doAssign(
            overhead=2500,
            overheadDistribution={"regular": 0, "ev": 0},
            minBatCharge=1000,
        )

        self.assertEqual(assigned["regular"], 1500)
        self.assertEqual(assigned["ev"], 0)


    def test_do_assign_handles_missing_consumer_entry(self):
        distributor = self.sod.SolarOverheadDistributor.__new__(
            self.sod.SolarOverheadDistributor
        )
        ev = SimpleNamespace(
            consumerKey="ev",
            customName="ev",
            isInitialized=True,
            isAutomatic=True,
            priority=35,
            priorityShift=0,
            ignoreBatReservation=True,
            request=1380,
            minimum=1380,
            stepSize=230,
            effectivePriority=0,
        )
        distributor._knownSolarOverheadConsumers = {"ev": ev}

        assigned = distributor.doAssign(
            overhead=1500,
            overheadDistribution={},
            minBatCharge=0,
        )

        self.assertEqual(assigned["ev"], 1380)


if __name__ == "__main__":
    unittest.main()
