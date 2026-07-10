"""Hardware-free regression tests for NoBatToEV startup safety."""

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
    dbus = _module("dbus")
    dbus.__path__ = []
    dbus_service = _module("dbus.service")
    dbus.service = dbus_service

    _module(
        "Helper",
        i=lambda *args, **kwargs: None,
        c=lambda *args, **kwargs: None,
        d=lambda *args, **kwargs: None,
        w=lambda *args, **kwargs: None,
        e=lambda *args, **kwargs: None,
        t=lambda *args, **kwargs: None,
    )
    _module("Globals", esESS=SimpleNamespace(_services={}))

    class esESSService:
        pass

    _module("esESSService", esESSService=esESSService)


class NoBatToEVTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.nobat = _load_module("nobattoev_under_test", ROOT / "NoBatToEV.py")

    def setUp(self):
        self.nobat.Globals.esESS = SimpleNamespace(_services={})

    @staticmethod
    def _dbus(value):
        return SimpleNamespace(value=value)

    def _service(self, ev_power=0, consumption=(0, 0, 0), pv=(0,) * 10):
        service = self.nobat.NoBatToEV.__new__(self.nobat.NoBatToEV)
        service.noPhasesDbus = self._dbus(3)
        service.relayStateUsage = -1
        service.relayState = None
        service.evChargerPowerDbus = self._dbus(ev_power)

        service.consumptionL1Dbus = self._dbus(consumption[0])
        service.consumptionL2Dbus = self._dbus(consumption[1])
        service.consumptionL3Dbus = self._dbus(consumption[2])

        service.pvOnGensetL1Dbus = self._dbus(pv[0])
        service.pvOnGensetL2Dbus = self._dbus(pv[1])
        service.pvOnGensetL3Dbus = self._dbus(pv[2])
        service.pvOnGridL1Dbus = self._dbus(pv[3])
        service.pvOnGridL2Dbus = self._dbus(pv[4])
        service.pvOnGridL3Dbus = self._dbus(pv[5])
        service.pvOnOutputL1Dbus = self._dbus(pv[6])
        service.pvOnOutputL2Dbus = self._dbus(pv[7])
        service.pvOnOutputL3Dbus = self._dbus(pv[8])
        service.pvOnDcDbus = self._dbus(pv[9])

        service.registerGridSetPointRequest = Mock()
        service.revokeGridSetPointRequest = Mock()
        return service

    def test_update_with_none_wattpilot_power_values_does_not_raise(self):
        service = self._service(consumption=(1000, 1000, 1000), pv=(100,) * 10)
        wattpilot = SimpleNamespace(power1=None, power2=0.7, power3=0.7)
        self.nobat.Globals.esESS._services = {
            "FroniusWattpilot": SimpleNamespace(wattpilot=wattpilot)
        }

        service._update()

        service.revokeGridSetPointRequest.assert_called_once_with()
        service.registerGridSetPointRequest.assert_not_called()

    def test_update_with_none_dbus_consumption_or_pv_values_does_not_raise(self):
        service = self._service(
            ev_power=1400,
            consumption=(1200, None, 1200),
            pv=(100, 100, 100, 100, 100, 100, 100, 100, 100, None),
        )

        service._update()

        service.revokeGridSetPointRequest.assert_called_once_with()
        service.registerGridSetPointRequest.assert_not_called()

    def test_update_with_ev_load_registers_expected_grid_setpoint_delta(self):
        service = self._service(
            ev_power=2000,
            consumption=(2000, 2000, 1000),
            pv=(300, 300, 300, 300, 300, 300, 300, 300, 200, 200),
        )

        service._update()

        service.registerGridSetPointRequest.assert_called_once_with(2000)
        service.revokeGridSetPointRequest.assert_not_called()

    def test_update_with_zero_ev_power_revokes_grid_setpoint(self):
        service = self._service(
            ev_power=0,
            consumption=(1000, 1000, 1000),
            pv=(100,) * 10,
        )

        service._update()

        service.revokeGridSetPointRequest.assert_called_once_with()
        service.registerGridSetPointRequest.assert_not_called()

    def test_relay_disabled_path_revokes_grid_setpoint(self):
        service = self._service(
            ev_power=2000,
            consumption=(2000, 2000, 1000),
            pv=(100,) * 10,
        )
        service.relayStateUsage = 0
        service.relayState = self._dbus(False)

        service._update()

        service.revokeGridSetPointRequest.assert_called_once_with()
        service.registerGridSetPointRequest.assert_not_called()


if __name__ == "__main__":
    unittest.main()
