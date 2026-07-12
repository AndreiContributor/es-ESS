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
        Disconnected = 0
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
            self.firmware = None
            self.carConnected = False
            self.phase_commands = []
            self.command_guard = None

        def connect(self):
            return None

        def set_command_guard(self, callback):
            self.command_guard = callback

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
        controller.validatedVenusOsVersion = "v3.73"
        controller.validatedWattpilotFirmware = "42.5"
        controller.validatedWattpilotAppVersion = "2.1.0"
        controller.actualVenusOsVersion = "v3.73"
        controller.actualWattpilotFirmware = None
        controller.wattpilotFirmwareCompatible = False
        controller._lastWattpilotCompatibilityState = None

        controller.initFinalize()

        self.assertEqual(errors, [])
        self.assertTrue(any("connection not ready during startup" in message for message in warnings))
        self.assertTrue(any("car state not ready during startup" in message for message in warnings))
        self.assertFalse(any("within 30 seconds" in message for message in warnings))

    def test_fronius_dashboard_transport_outage_updates_standard_paths(self):
        warnings = []
        errors = []
        _install_fronius_startup_stubs(warnings, errors)
        fronius_module = _load_module(
            "fronius_transport_dashboard_under_test",
            ROOT / "FroniusWattpilot.py",
        )
        controller = fronius_module.FroniusWattpilot.__new__(
            fronius_module.FroniusWattpilot
        )
        dbus_values = {}
        messages = []
        mqtt_messages = []

        def fail_command(*_args, **_kwargs):
            raise AssertionError("transport status must not issue Wattpilot commands")

        controller.wattpilotDashboardTransportUnavailable = False
        controller.isHibernateEnabled = False
        controller.isIdleMode = False
        controller.effectiveCarConnected = True
        controller.wattpilot = types.SimpleNamespace(
            connected=False,
            set_power=fail_command,
            set_phases=fail_command,
            set_start_stop=fail_command,
        )
        controller.publish = lambda path, value: dbus_values.__setitem__(path, value)
        controller.publishMainMqtt = (
            lambda topic, payload, qos=0, retain=False: mqtt_messages.append(
                (topic, payload, qos, retain)
            )
        )
        controller.publishServiceMessage = (
            lambda _service, message: messages.append(message)
        )

        self.assertTrue(controller.updateWattpilotTransportDashboardStatus())
        self.assertEqual(dbus_values["/Connected"], 0)
        self.assertEqual(dbus_values["/Status"], 0)
        self.assertEqual(
            dbus_values["/StatusLiteral"],
            fronius_module.WATTPILOT_UNAVAILABLE_STATUS_LITERAL,
        )
        self.assertEqual(
            dbus_values["/CustomName"],
            fronius_module.WATTPILOT_UNAVAILABLE_CUSTOM_NAME,
        )
        self.assertIn(
            (
                "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/CustomName",
                fronius_module.WATTPILOT_UNAVAILABLE_CUSTOM_NAME,
                0,
                False,
            ),
            mqtt_messages,
        )
        self.assertEqual(
            messages,
            ["Wattpilot is not accessible. Waiting for reconnect."],
        )

        self.assertTrue(controller.updateWattpilotTransportDashboardStatus())
        self.assertEqual(
            messages,
            ["Wattpilot is not accessible. Waiting for reconnect."],
        )

        controller.wattpilot.connected = True

        self.assertFalse(controller.updateWattpilotTransportDashboardStatus())
        self.assertEqual(dbus_values["/Connected"], 1)
        self.assertEqual(
            dbus_values["/CustomName"],
            fronius_module.WATTPILOT_BASE_CUSTOM_NAME,
        )
        self.assertEqual(
            messages,
            [
                "Wattpilot is not accessible. Waiting for reconnect.",
                "Wattpilot connection recovered.",
            ],
        )


if __name__ == "__main__":
    unittest.main()
