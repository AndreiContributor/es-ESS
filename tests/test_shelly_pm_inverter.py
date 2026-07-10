"""Hardware-free tests for Shelly PM inverter polling."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
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


class FakeDbusService(dict):
    def __init__(self, *_args, **_kwargs):
        super().__init__()

    def add_path(self, path, value, *args, **kwargs):
        self[path] = value

    def register(self):
        pass


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class RootService:
    def publishServiceMessage(self, *_args, **_kwargs):
        pass


def _install_runtime_stubs():
    class Timeout(Exception):
        pass

    dbus = _module("dbus")
    dbus.__path__ = []
    dbus_service = _module("dbus.service")
    dbus.service = dbus_service
    _module("vedbus", VeDbusService=FakeDbusService)
    _module("requests", exceptions=types.SimpleNamespace(Timeout=Timeout))
    _module(
        "Globals",
        esEssTagService="test",
        esEssTag="es-ESS",
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
    _module("esESSService", esESSService=object)


class ShellyPMInverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.module = _load_module(
            "shelly_pm_inverter_under_test", ROOT / "ShellyPMInverter.py"
        )

    def _device(self):
        device = self.module.ShellyPMInverterDevice(
            RootService(),
            "roof",
            {
                "CustomName": "Roof",
                "VRMInstanceID": "52",
                "PollFrequencyMs": "1000",
                "Username": "",
                "Password": "",
                "Host": "pm.local",
                "Phase": "2",
                "Position": "0",
                "Relay": "0",
            },
        )
        device.initDbusService()
        return device

    def test_query_shelly_publishes_configured_phase_values(self):
        device = self._device()
        self.module.requests.get = Mock(
            return_value=FakeResponse(
                {
                    "apower": 345.6,
                    "voltage": 231.2,
                    "current": 1.5,
                    "aenergy": {"total": 12345},
                }
            )
        )

        device.queryShelly()

        self.assertEqual(device.dbusService["/Connected"], 1)
        self.assertEqual(device.dbusService["/Ac/Power"], 345.6)
        self.assertIsNone(device.dbusService["/Ac/L1/Power"])
        self.assertEqual(device.dbusService["/Ac/L2/Power"], 345.6)
        self.assertIsNone(device.dbusService["/Ac/L3/Power"])
        self.assertEqual(device.dbusService["/Ac/Energy/Forward"], 12.345)
        self.module.requests.get.assert_called_once_with(
            url="http://pm.local/rpc/Switch.GetStatus?id=0", timeout=0.5
        )

    def test_repeated_timeout_sets_disconnected_without_raising(self):
        device = self._device()
        device.connectionErrors = 3
        self.module.requests.get = Mock(
            side_effect=self.module.requests.exceptions.Timeout()
        )

        device.queryShelly()

        self.assertEqual(device.dbusService["/Connected"], 0)
        self.assertEqual(device.dbusService["/StatusCode"], 10)
        self.assertIsNone(device.dbusService["/Ac/Power"])


if __name__ == "__main__":
    unittest.main()
