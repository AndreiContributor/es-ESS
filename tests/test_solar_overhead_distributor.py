"""Hardware-free SolarOverheadDistributor startup safety tests."""

import importlib.util
import sys
import threading
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
    _module("vedbus", VeDbusService=object)
    _module("requests", get=lambda *args, **kwargs: SimpleNamespace(text=""))
    _module(
        "Globals",
        esEssTagService="test",
        esEssTag="es-ESS",
        currentVersionString="test",
        esESS=SimpleNamespace(_sigTermInvoked=False),
        ServiceMessageType=SimpleNamespace(Warning="Warning"),
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
    _module("esESSService", esESSService=type("esESSService", (), {}))


class StubConsumer:
    def __init__(self, key="load", initialized=True, automatic=True):
        self.consumerKey = key
        self.isInitialized = initialized
        self.isAutomatic = automatic
        self.request = 1000
        self.minimum = 500
        self.stepSize = 500
        self.consumption = 0
        self.ignoreBatReservation = False
        self.vrmInstanceID = 42
        self.priority = 100
        self.priorityShift = 0
        self.effectivePriority = 0
        self.customName = key
        self.allowance = 123
        self.allowance_updates = []
        self.persist_calls = 0

    def checkFinalInit(self, distributor):
        pass

    def dumpFakeBMS(self):
        pass

    def updateAllowance(self, allowance, distributor):
        self.allowance = allowance
        self.allowance_updates.append(allowance)

    def _persistEnergyStats(self):
        self.persist_calls += 1


class SolarOverheadDistributorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.sod = _load_module(
            "solar_overhead_distributor_under_test",
            ROOT / "SolarOverheadDistributor.py",
        )

    def setUp(self):
        self.sod.c = Mock()
        self.sod.Globals.esESS = SimpleNamespace(_sigTermInvoked=False)

    @staticmethod
    def _dbus(value):
        return SimpleNamespace(value=value)

    def _service(self, grid=(0, 0, 0), battery_power=0, battery_soc=80):
        service = self.sod.SolarOverheadDistributor.__new__(
            self.sod.SolarOverheadDistributor
        )
        service._knownSolarOverheadConsumers = {}
        service._knownSolarOverheadConsumersLock = threading.Lock()
        service.gridL1Dbus = self._dbus(grid[0])
        service.gridL2Dbus = self._dbus(grid[1])
        service.gridL3Dbus = self._dbus(grid[2])
        service.batteryPower = self._dbus(battery_power)
        service.batterySoc = self._dbus(battery_soc)
        service.dbusService = {}
        service.lastUpdate = 0
        service.config = {"SolarOverheadDistributor": {"MinBatteryCharge": "0"}}
        service.publishMainMqtt = Mock()
        service.publishServiceMessage = Mock()
        return service

    def test_update_distribution_with_none_grid_value_zeroes_allowance(self):
        service = self._service(grid=(None, -100, -200), battery_power=0)
        consumer = StubConsumer()
        service._knownSolarOverheadConsumers[consumer.consumerKey] = consumer

        self.assertTrue(service.updateDistribution())

        self.sod.c.assert_not_called()
        self.assertEqual(service.dbusService["/Calculations/OverheadAvailable"], 0)
        self.assertEqual(service.dbusService["/Calculations/OverheadAssigned"], 0)
        self.assertEqual(service.dbusService["/Calculations/OverheadRemaining"], 0)
        self.assertEqual(consumer.allowance_updates, [0])
        service.publishServiceMessage.assert_any_call(
            service,
            "Solar overhead distribution input missing: grid L1. Publishing zero allowance.",
            "Warning",
        )

    def test_update_distribution_with_none_battery_power_zeroes_allowance(self):
        service = self._service(grid=(-100, -100, -100), battery_power=None)
        consumer = StubConsumer()
        service._knownSolarOverheadConsumers[consumer.consumerKey] = consumer

        service.updateDistribution()

        self.sod.c.assert_not_called()
        self.assertEqual(service.dbusService["/Calculations/Battery/Power"], 0)
        self.assertEqual(service.dbusService["/Calculations/OverheadAvailable"], 0)
        self.assertEqual(consumer.allowance_updates, [0])

    def test_update_distribution_with_values_publishes_expected_overhead(self):
        service = self._service(grid=(-100, -200, 50), battery_power=-50)

        service.updateDistribution()

        self.sod.c.assert_not_called()
        self.assertEqual(service.dbusService["/Calculations/Grid/TotalFeedIn"], 250)
        self.assertEqual(service.dbusService["/Calculations/OverheadAvailable"], 200)
        self.assertEqual(service.dbusService["/Calculations/OverheadAssigned"], 0)
        self.assertEqual(service.dbusService["/Calculations/OverheadRemaining"], 200)

    def test_persist_energy_stats_holds_consumer_lock_during_iteration(self):
        service = self._service()
        entered_persist = threading.Event()
        release_persist = threading.Event()
        registration_done = threading.Event()
        errors = []

        class SlowConsumer(StubConsumer):
            def _persistEnergyStats(self):
                entered_persist.set()
                release_persist.wait(timeout=2)
                super()._persistEnergyStats()

        service._knownSolarOverheadConsumers["slow"] = SlowConsumer("slow")

        def persist():
            try:
                service._persistEnergyStats()
            except Exception as exc:
                errors.append(exc)

        def register_consumer():
            try:
                with service._knownSolarOverheadConsumersLock:
                    service._knownSolarOverheadConsumers["new"] = StubConsumer("new")
                registration_done.set()
            except Exception as exc:
                errors.append(exc)

        persist_thread = threading.Thread(target=persist)
        persist_thread.start()
        self.assertTrue(entered_persist.wait(timeout=2))

        register_thread = threading.Thread(target=register_consumer)
        register_thread.start()
        self.assertFalse(registration_done.wait(timeout=0.1))

        release_persist.set()
        persist_thread.join(timeout=2)
        register_thread.join(timeout=2)

        self.assertFalse(persist_thread.is_alive())
        self.assertFalse(register_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(registration_done.is_set())
        self.assertIn("new", service._knownSolarOverheadConsumers)
        self.assertEqual(service._knownSolarOverheadConsumers["slow"].persist_calls, 1)


if __name__ == "__main__":
    unittest.main()
