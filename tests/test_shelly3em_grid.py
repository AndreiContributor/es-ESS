"""Hardware-free tests for Shelly 3EM grid polling."""

import configparser
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


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


def _config():
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read_dict(
        {
            "Shelly3EMGrid": {
                "VRMInstanceID": "40",
                "CustomName": "Grid",
                "PollFrequencyMs": "1000",
                "Username": "",
                "Password": "",
                "Host": "shelly.local",
                "Metering": "Default",
            }
        }
    )
    return config


class BaseService:
    def __init__(self):
        self.config = _config()

    def publishServiceMessage(self, *_args, **_kwargs):
        pass

    def registerWorkerThread(self, *_args, **_kwargs):
        pass


def _install_runtime_stubs():
    class RequestException(Exception):
        pass

    class Timeout(RequestException):
        pass

    class ConnectionError(RequestException):
        pass

    dbus = _module("dbus")
    dbus.__path__ = []
    dbus_service = _module("dbus.service")
    dbus.service = dbus_service
    _module("vedbus", VeDbusService=FakeDbusService)
    _module(
        "requests",
        exceptions=types.SimpleNamespace(
            RequestException=RequestException,
            Timeout=Timeout,
            ConnectionError=ConnectionError,
        ),
    )
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
    _module("esESSService", esESSService=BaseService)


class Shelly3EMGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.module = _load_module("shelly3em_grid_under_test", ROOT / "Shelly3EMGrid.py")

    def _service(self):
        service = self.module.Shelly3EMGrid()
        service.initDbusService()
        return service

    def test_query_shelly_publishes_phase_power_values(self):
        service = self._service()
        self.module.requests.get = Mock(
            return_value=FakeResponse(
                {
                    "total_power": 900,
                    "emeters": [
                        {"voltage": 230, "current": 1, "power": 100, "total": 1000, "total_returned": 50},
                        {"voltage": 231, "current": 2, "power": 500, "total": 2000, "total_returned": 60},
                        {"voltage": 232, "current": 3, "power": 300, "total": 3000, "total_returned": 70},
                    ],
                }
            )
        )

        service.queryShelly()

        self.assertEqual(service.dbusService["/Connected"], 1)
        self.assertEqual(service.dbusService["/Ac/L1/Power"], 100)
        self.assertEqual(service.dbusService["/Ac/L2/Power"], 500)
        self.assertEqual(service.dbusService["/Ac/L3/Power"], 300)
        self.assertEqual(service.dbusService["/Ac/Power"], 900)
        self.module.requests.get.assert_called_once_with(
            url="http://shelly.local/status", timeout=0.5
        )

    def test_net_metering_integrates_raw_total_power(self):
        service = self._service()
        service.metering = "Net"
        service.energyForwarded = 0
        service.energyReversed = 0
        service.lastMeasurement = 0
        self.module.requests.get = Mock(
            return_value=FakeResponse(
                {
                    "total_power": 3600,
                    "emeters": [
                        {"voltage": 230, "current": 4, "power": 1000},
                        {"voltage": 231, "current": 5, "power": 1200},
                        {"voltage": 232, "current": 6, "power": 1400},
                    ],
                }
            )
        )

        with patch.object(self.module, "time", return_value=1):
            service.queryShelly()

        self.assertEqual(service.dbusService["/Ac/L2/Power"], 1200)
        self.assertEqual(service.dbusService["/Ac/Power"], 3600)
        self.assertEqual(service.energyForwarded, 1)
        self.assertEqual(service.energyReversed, 0)

    def test_repeated_timeout_sets_disconnected_without_raising(self):
        service = self._service()
        service.connectionErrors = 3
        self.module.requests.get = Mock(
            side_effect=self.module.requests.exceptions.Timeout()
        )

        service.queryShelly()

        self.assertEqual(service.dbusService["/Connected"], 0)
        self.assertIsNone(service.dbusService["/Ac/Power"])

    def test_connection_refusal_uses_existing_failure_threshold(self):
        service = self._service()
        self.module.requests.get = Mock(
            side_effect=self.module.requests.exceptions.ConnectionError("refused")
        )

        service.queryShelly()
        self.assertEqual(service.dbusService["/Connected"], 1)
        self.assertEqual(service.connectionErrors, 1)

        service.connectionErrors = 3
        service.queryShelly()
        self.assertEqual(service.dbusService["/Connected"], 0)

    def test_partial_payload_uses_existing_failure_threshold_without_partial_publish(self):
        service = self._service()
        service.connectionErrors = 3
        self.module.requests.get = Mock(
            return_value=FakeResponse(
                {
                    "total_power": 900,
                    "emeters": [
                        {"voltage": 230, "current": 1, "power": 100, "total": 1000, "total_returned": 50},
                        {"voltage": 231, "current": 2, "power": 500, "total": 2000, "total_returned": 60},
                    ],
                }
            )
        )

        service.queryShelly()

        self.assertEqual(service.dbusService["/Connected"], 0)
        self.assertIsNone(service.dbusService["/Ac/L1/Power"])


if __name__ == "__main__":
    unittest.main()
