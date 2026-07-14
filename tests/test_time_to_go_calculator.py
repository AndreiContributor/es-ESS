"""Hardware-free tests for TimeToGoCalculator telemetry handling."""

import configparser
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


def _config():
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read_dict(
        {
            "Common": {
                "BatteryCapacityInWh": "10000",
                "VRMPortalID": "portal-id",
            },
            "TimeToGoCalculator": {"UpdateInterval": "1000"},
        }
    )
    return config


class BaseService:
    def __init__(self):
        self.config = _config()


def _install_runtime_stubs():
    _module("Globals", esEssTag="es-ESS")
    _module(
        "Helper",
        i=lambda *args, **kwargs: None,
        c=Mock(),
        d=Mock(),
        w=Mock(),
        e=lambda *args, **kwargs: None,
        t=lambda *args, **kwargs: None,
    )
    _module("esESSService", esESSService=BaseService)


class TimeToGoCalculatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.module = _load_module(
            "time_to_go_calculator_under_test",
            ROOT / "TimeToGoCalculator.py",
        )

    def setUp(self):
        self.module.c.reset_mock()
        self.module.d.reset_mock()
        self.module.w.reset_mock()

    def _service(self, power=-1000, soc=80, soc_limit=20):
        service = self.module.TimeToGoCalculator()
        service.powerDbus = SimpleNamespace(value=power)
        service.socDbus = SimpleNamespace(value=soc)
        service.socLimitDbus = SimpleNamespace(value=soc_limit)
        service.publishLocalMqtt = Mock()
        service.publishMainMqtt = Mock()
        return service

    def test_each_missing_input_skips_without_critical_error(self):
        for values in ((None, 80, 20), (-1000, None, 20), (-1000, 80, None)):
            with self.subTest(values=values):
                service = self._service(*values)

                self.assertTrue(service.updateTimeToGo())

                service.publishLocalMqtt.assert_not_called()
                service.publishMainMqtt.assert_not_called()
                self.module.c.assert_not_called()
                self.module.d.assert_called()
                self.module.d.reset_mock()

    def test_discharge_calculation_publishes_existing_topics(self):
        service = self._service(power=-1000, soc=80, soc_limit=20)

        self.assertTrue(service.updateTimeToGo())

        service.publishLocalMqtt.assert_called_once_with(
            "N/portal-id/system/0/Dc/Battery/TimeToGo",
            '{"value": 21600}',
        )
        service.publishMainMqtt.assert_called_once_with(
            "es-ESS/TimeToGoCalculator/TimeToGo",
            21600,
        )

    def test_charge_calculation_recovers_after_missing_input(self):
        service = self._service(power=None, soc=80, soc_limit=20)
        service.updateTimeToGo()
        service.powerDbus.value = 1000

        self.assertTrue(service.updateTimeToGo())

        service.publishMainMqtt.assert_called_once_with(
            "es-ESS/TimeToGoCalculator/TimeToGo",
            7199,
        )


if __name__ == "__main__":
    unittest.main()
