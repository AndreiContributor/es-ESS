"""Hardware-free tests for Fronius smart meter JSON polling."""

import configparser
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


def _config():
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read_dict(
        {
            "FroniusSmartmeterJSON": {
                "VRMInstanceID": "40",
                "CustomName": "Fronius",
                "PollFrequencyMs": "1000",
                "Host": "fronius.local",
                "MeterID": "0",
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
    _module("esESSService", esESSService=BaseService)


def _meter_data():
    return {
        "Body": {
            "Data": {
                "Enable": 1,
                "Voltage_AC_Phase_1": 230.1,
                "Voltage_AC_Phase_2": 230.2,
                "Voltage_AC_Phase_3": 230.3,
                "Current_AC_Phase_1": 1.1,
                "Current_AC_Phase_2": 2.2,
                "Current_AC_Phase_3": 3.3,
                "PowerFactor_Phase_1": 0.91,
                "PowerFactor_Phase_2": 0.92,
                "PowerFactor_Phase_3": 0.93,
                "PowerReal_P_Phase_1": 100.1,
                "PowerReal_P_Phase_2": 200.2,
                "PowerReal_P_Phase_3": 300.3,
                "Voltage_AC_PhaseToPhase_12": 400.1,
                "Voltage_AC_PhaseToPhase_23": 400.2,
                "Voltage_AC_PhaseToPhase_31": 400.3,
                "EnergyReal_WAC_Sum_Consumed": 12345,
                "EnergyReal_WAC_Sum_Produced": 6789,
            }
        }
    }


class FroniusSmartmeterJSONTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.module = _load_module(
            "fronius_smartmeter_json_under_test",
            ROOT / "FroniusSmartmeterJSON.py",
        )

    def _service(self):
        service = self.module.FroniusSmartmeterJSON()
        service.initDbusService()
        return service

    def test_query_meter_publishes_grid_values(self):
        service = self._service()
        self.module.requests.get = Mock(return_value=FakeResponse(_meter_data()))

        service.queryMeter()

        self.assertEqual(service.dbusService["/Connected"], 1)
        self.assertEqual(service.dbusService["/Ac/L1/Power"], 100.1)
        self.assertEqual(service.dbusService["/Ac/L2/Power"], 200.2)
        self.assertEqual(service.dbusService["/Ac/L3/Power"], 300.3)
        self.assertEqual(service.dbusService["/Ac/Power"], 600.6)
        self.assertEqual(service.dbusService["/Ac/Energy/Forward"], 12.345)
        self.module.requests.get.assert_called_once_with(
            url="http://fronius.local/solar_api/v1/GetMeterRealtimeData.cgi?Scope=Device&DeviceId=0&DataCollection=MeterRealtimeData",
            timeout=0.5,
        )

    def test_repeated_timeout_sets_disconnected_without_raising(self):
        service = self._service()
        service.connectionErrors = 9
        self.module.requests.get = Mock(
            side_effect=self.module.requests.exceptions.Timeout()
        )

        service.queryMeter()

        self.assertEqual(service.dbusService["/Connected"], 0)
        self.assertIsNone(service.dbusService["/Ac/Power"])


if __name__ == "__main__":
    unittest.main()
