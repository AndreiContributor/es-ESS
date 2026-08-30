"""Regression tests for Victron EVCS Wattpilot session D-Bus paths."""

import importlib.util
import sys
import types
import unittest
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace


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


class FakeDbusService(dict):
    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self.registered = False

    def add_path(self, path, value, **_kwargs):
        self[path] = value

    def register(self):
        self.registered = True


def _install_runtime_stubs():
    paho = _module("paho")
    paho.__path__ = []
    paho_mqtt = _module("paho.mqtt")
    paho_mqtt.__path__ = []
    paho_mqtt_client = _module("paho.mqtt.client", Client=object)
    paho.mqtt = paho_mqtt
    paho_mqtt.client = paho_mqtt_client

    _module("vedbus", VeDbusService=FakeDbusService)
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
    )

    class VrmEvChargerControlMode(IntEnum):
        Manual = 0
        Auto = 1
        Scheduled = 2

    class VrmEvChargerStatus(IntEnum):
        Disconnected = 0
        Connected = 1
        WaitingForSun = 2
        StartCharging = 3
        StopCharging = 4
        Charging = 5
        SwitchingTo1Phase = 6
        SwitchingTo3Phase = 7
        Charged = 8

    class VrmEvChargerStartStop(IntEnum):
        Stop = 0
        Start = 1

    class WattpilotStartStop(IntEnum):
        Off = 0
        On = 1

    class WattpilotControlMode(IntEnum):
        Default = 0
        ECO = 1

    _module(
        "enums",
        VrmEvChargerControlMode=VrmEvChargerControlMode,
        VrmEvChargerStatus=VrmEvChargerStatus,
        VrmEvChargerStartStop=VrmEvChargerStartStop,
        WattpilotModelStatus=type("WattpilotModelStatus", (), {}),
        WattpilotStartStop=WattpilotStartStop,
        WattpilotControlMode=WattpilotControlMode,
    )
    _module("Wattpilot", Wattpilot=type("Wattpilot", (), {}))
    _module("esESSService", esESSService=type("esESSService", (), {}))


class WattpilotSessionPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.fwp = _load_module(
            "wattpilot_session_paths_under_test",
            ROOT / "FroniusWattpilot.py",
        )

    def _controller(self):
        controller = self.fwp.FroniusWattpilot.__new__(self.fwp.FroniusWattpilot)
        controller.dbusService = {}
        controller.publishMainMqtt = lambda *args, **kwargs: None
        controller.getEffectiveMaxCurrent = lambda: 16
        controller.onePhaseVoltage = lambda: 230
        controller.consumerPowerForDistributor = lambda: 0
        controller.reportPhaseMode = lambda: None
        controller.mode = self.fwp.VrmEvChargerControlMode.Auto
        controller.autostart = 1
        controller.currentPhaseMode = 1
        controller.chargingTime = 95
        controller.config = {
            "FroniusWattpilot": {
                "ResetChargedEnergyCounter": "ondisconnect",
            }
        }
        controller.wattpilot = SimpleNamespace(
            power1=1.2,
            power2=0,
            power3=0,
            voltage1=230,
            voltage2=230,
            voltage3=230,
            amps1=5.2,
            amps2=0,
            amps3=0,
            powerFactor1=0.98,
            powerFactor2=0,
            powerFactor3=0,
            power=1.2,
            amp=6,
            ampLimit=None,
            carConnected=True,
            energyCounterSinceStart=2450,
        )
        return controller

    def test_session_paths_are_registered_at_service_initialization(self):
        controller = self.fwp.FroniusWattpilot.__new__(self.fwp.FroniusWattpilot)
        controller.config = {
            "FroniusWattpilot": {
                "Position": "0",
            }
        }
        controller.serviceName = "com.victronenergy.evcharger.test_FroniusWattpilot"
        controller.vrmInstanceID = 40
        controller.chargingTime = 0
        controller.autostart = 0
        controller.mode = self.fwp.VrmEvChargerControlMode.Manual
        controller.siteMaxCurrent = 20
        controller.charger1PhaseMapping = "L1"
        controller.siteCurrentGuardReason = "Waiting for site-current telemetry"

        controller.initDbusService()

        self.assertEqual(controller.dbusService["/Session/Energy"], 0)
        self.assertEqual(controller.dbusService["/Session/Time"], 0)
        self.assertEqual(controller.dbusService["/Ac/Energy/Forward"], 0)
        self.assertEqual(controller.dbusService["/ChargingTime"], 0)
        self.assertTrue(controller.dbusService.registered)

    def test_session_energy_matches_ac_energy_when_wattpilot_energy_is_valid(self):
        controller = self._controller()

        controller.dumpEvChargerInfo()

        self.assertEqual(controller.dbusService["/Ac/Energy/Forward"], 2.45)
        self.assertEqual(controller.dbusService["/Session/Energy"], 2.45)

    def test_session_energy_preserves_onconnect_reset_policy_value(self):
        controller = self._controller()
        controller.wattpilot.carConnected = False
        controller.config["FroniusWattpilot"]["ResetChargedEnergyCounter"] = (
            "onconnect"
        )

        controller.dumpEvChargerInfo()

        self.assertEqual(controller.dbusService["/Ac/Energy/Forward"], 2.45)
        self.assertEqual(controller.dbusService["/Session/Energy"], 2.45)

    def test_session_energy_and_time_reset_with_existing_reset_policy(self):
        controller = self._controller()
        controller.wattpilot.energyCounterSinceStart = None

        controller.dumpEvChargerInfo()

        self.assertEqual(controller.dbusService["/Ac/Energy/Forward"], 0.0)
        self.assertEqual(controller.dbusService["/Session/Energy"], 0.0)
        self.assertEqual(controller.dbusService["/ChargingTime"], 0)
        self.assertEqual(controller.dbusService["/Session/Time"], 0)
        self.assertEqual(controller.chargingTime, 0)

    def test_session_time_matches_charging_time(self):
        controller = self._controller()

        controller.dumpEvChargerInfo()

        self.assertEqual(controller.dbusService["/ChargingTime"], 95)
        self.assertEqual(controller.dbusService["/Session/Time"], 95)

    def test_session_observation_is_command_free_in_manual_mode(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Manual
        controller.siteCurrentFreshSeconds = 15
        controller.charger1PhaseMapping = "L1"
        controller.wattpilot.energyTelemetryUpdatedAt = 100
        commands = []
        controller.wattpilot.set_power = lambda value: commands.append(("amp", value))
        controller.wattpilot.set_phases = lambda value: commands.append(("psm", value))
        controller.wattpilot.set_start_stop = lambda value: commands.append(("frc", value))
        controller.sessionStatistics = self.fwp.WattpilotSessionStatistics(
            one_phase_mapping="L1"
        )
        records = []
        controller.logSessionStatisticsRecords = records.extend

        controller.recordSessionStatistics(True, now=100)
        controller.recordSessionStatistics(True, now=105)

        self.assertEqual(commands, [])
        self.assertEqual(records[0]["event"], "connection_start")
        self.assertEqual(records[1]["event"], "charge_start")
        self.assertEqual(records[1]["phase_mode"], 1)

    def test_session_observation_does_not_mutate_control_or_safety_state(self):
        controller = self._controller()
        controller.siteCurrentFreshSeconds = 15
        controller.wattpilot.energyTelemetryUpdatedAt = 100
        controller.sessionStatistics = self.fwp.WattpilotSessionStatistics()
        controller.logSessionStatisticsRecords = lambda _records: None
        controller.commandAuthorityOk = True
        controller.siteCurrentGuardBlocked = False
        controller.gridImportSince = 123
        controller.batteryAssistActive = True
        before = (
            controller.mode,
            controller.currentPhaseMode,
            controller.commandAuthorityOk,
            controller.siteCurrentGuardBlocked,
            controller.gridImportSince,
            controller.batteryAssistActive,
        )

        controller.recordSessionStatistics(True, now=100)

        after = (
            controller.mode,
            controller.currentPhaseMode,
            controller.commandAuthorityOk,
            controller.siteCurrentGuardBlocked,
            controller.gridImportSince,
            controller.batteryAssistActive,
        )
        self.assertEqual(after, before)

    def test_session_transition_and_checkpoint_log_levels_are_bounded(self):
        controller = self._controller()
        info_messages = []
        debug_messages = []
        prior_i, prior_d = self.fwp.i, self.fwp.d
        self.fwp.i = lambda _module, message: info_messages.append(message)
        self.fwp.d = lambda _module, message: debug_messages.append(message)
        try:
            controller.logSessionStatisticsRecords(
                [
                    {
                        "event_version": 1,
                        "event": "connection_start",
                        "connection_id": "connection-1",
                    },
                    {
                        "event_version": 1,
                        "event": "checkpoint",
                        "connection_id": "connection-1",
                    },
                ]
            )
        finally:
            self.fwp.i, self.fwp.d = prior_i, prior_d

        self.assertEqual(len(info_messages), 1)
        self.assertEqual(len(debug_messages), 1)
        self.assertIn('"event":"connection_start"', info_messages[0])
        self.assertIn('"event":"checkpoint"', debug_messages[0])


if __name__ == "__main__":
    unittest.main()
