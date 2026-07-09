"""Startup hygiene regressions for the Wattpilot integration."""

import importlib.util
import sys
import types
import unittest
from enum import Enum
from pathlib import Path


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


class FakeWebSocketApp:
    def __init__(self, *_args, **_kwargs):
        self.closed = False

    def run_forever(self):
        return None

    def close(self):
        self.closed = True

    def send(self, _message):
        return None


def _install_wattpilot_client_stubs(info_messages):
    _module(
        "websocket",
        setdefaulttimeout=lambda _timeout: None,
        WebSocketApp=FakeWebSocketApp,
    )
    _module(
        "Helper",
        i=lambda _module, message, **_kwargs: info_messages.append(message),
        c=lambda *args, **kwargs: None,
        d=lambda *args, **kwargs: None,
        w=lambda *args, **kwargs: None,
        e=lambda *args, **kwargs: None,
        t=lambda *args, **kwargs: None,
    )

    class WattpilotStartStop(Enum):
        Neutral = 0
        Off = 1
        On = 2

    class WattpilotControlMode(Enum):
        Default = 3
        ECO = 4

    class WattpilotModelStatus(Enum):
        Idle = 1

    _module(
        "enums",
        WattpilotModelStatus=WattpilotModelStatus,
        WattpilotStartStop=WattpilotStartStop,
        WattpilotControlMode=WattpilotControlMode,
    )


def _install_fronius_startup_stubs(warnings, errors):
    paho = _module("paho")
    paho.__path__ = []
    paho_mqtt = _module("paho.mqtt")
    paho_mqtt.__path__ = []
    paho_mqtt_client = _module("paho.mqtt.client", Client=object)
    paho.mqtt = paho_mqtt
    paho_mqtt.client = paho_mqtt_client

    _module("vedbus", VeDbusService=object)
    _module(
        "Globals",
        esEssTagService="test",
        currentVersionString="test",
    )
    _module(
        "Helper",
        i=lambda *args, **kwargs: None,
        c=lambda *args, **kwargs: None,
        d=lambda *args, **kwargs: None,
        w=lambda _module, message, **_kwargs: warnings.append(message),
        e=lambda _module, message, **_kwargs: errors.append(message),
        t=lambda *args, **kwargs: None,
        dbusConnection=lambda: None,
        waitTimeout=lambda predicate, _timeout: bool(predicate()),
    )

    class VrmEvChargerControlMode(Enum):
        Manual = 0
        Auto = 1

    class VrmEvChargerStatus(Enum):
        StopCharging = 24

    class VrmEvChargerStartStop(Enum):
        Stop = 0
        Start = 1

    class WattpilotStartStop(Enum):
        Off = 1
        On = 2

    class WattpilotControlMode(Enum):
        Default = 3
        ECO = 4

    class WattpilotModelStatus(Enum):
        Idle = 1

    _module(
        "enums",
        VrmEvChargerControlMode=VrmEvChargerControlMode,
        VrmEvChargerStatus=VrmEvChargerStatus,
        VrmEvChargerStartStop=VrmEvChargerStartStop,
        WattpilotModelStatus=WattpilotModelStatus,
        WattpilotStartStop=WattpilotStartStop,
        WattpilotControlMode=WattpilotControlMode,
    )

    class FakeWattpilot:
        def __init__(self, _host, _password):
            self.connected = False
            self.power1 = None
            self.power2 = None
            self.power3 = None
            self.carStateReady = False
            self.mode = None
            self.carConnected = False
            self.phase_commands = []

        def connect(self):
            return None

        def set_phases(self, value):
            self.phase_commands.append(value)

    _module("Wattpilot", Wattpilot=FakeWattpilot)
    _module("esESSService", esESSService=type("esESSService", (), {}))


class WattpilotStartupTests(unittest.TestCase):
    def test_wattpilot_energy_counter_exists_before_first_status_update(self):
        info_messages = []
        _install_wattpilot_client_stubs(info_messages)
        wattpilot_module = _load_module(
            "wattpilot_client_startup_under_test",
            ROOT / "Wattpilot.py",
        )

        client = wattpilot_module.Wattpilot("127.0.0.1", "secret")

        self.assertIsNone(client.energyCounterSinceStart)

    def test_connect_log_names_worker_start_not_authenticated_connection(self):
        info_messages = []
        _install_wattpilot_client_stubs(info_messages)
        wattpilot_module = _load_module(
            "wattpilot_client_log_under_test",
            ROOT / "Wattpilot.py",
        )
        client = wattpilot_module.Wattpilot("127.0.0.1", "secret")

        client.connect()
        client._wst.join(0.2)

        self.assertIn("Wattpilot WebSocket worker started", info_messages)
        self.assertNotIn("Wattpilot connected", info_messages)

    def test_fronius_startup_logs_expected_deferred_readiness_as_warnings(self):
        warnings = []
        errors = []
        _install_fronius_startup_stubs(warnings, errors)
        fronius_module = _load_module(
            "fronius_startup_log_under_test",
            ROOT / "FroniusWattpilot.py",
        )
        controller = fronius_module.FroniusWattpilot.__new__(
            fronius_module.FroniusWattpilot
        )
        controller.config = {
            "FroniusWattpilot": {
                "Host": "127.0.0.1",
                "Password": "secret",
            }
        }
        controller.publishServiceMessage = lambda *args, **kwargs: None
        controller.dumpEvChargerInfo = lambda: None

        controller.initFinalize()

        self.assertEqual(errors, [])
        self.assertTrue(any("connection not ready during startup" in message for message in warnings))
        self.assertTrue(any("car state not ready during startup" in message for message in warnings))
        self.assertFalse(any("within 30 seconds" in message for message in warnings))


if __name__ == "__main__":
    unittest.main()
