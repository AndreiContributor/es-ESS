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
    class Timeout(Exception):
        pass

    _module("vedbus", VeDbusService=object)
    _module(
        "requests",
        get=lambda *args, **kwargs: SimpleNamespace(text=""),
        exceptions=SimpleNamespace(Timeout=Timeout),
    )
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

    def test_on_keyword_regex_subscription_is_registered_once(self):
        service = self.sod.SolarOverheadDistributor.__new__(
            self.sod.SolarOverheadDistributor
        )
        service.registerMqttSubscription = Mock()

        service.initMqttSubscriptions()

        topics = [
            call.args[0]
            for call in service.registerMqttSubscription.call_args_list
        ]
        self.assertEqual(
            topics.count(
                "es-ESS/SolarOverheadDistributor/Requests/+/OnKeywordRegex"
            ),
            1,
        )

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

    def _http_consumer(self):
        consumer = self.sod.SolarOverheadConsumer.__new__(
            self.sod.SolarOverheadConsumer
        )
        consumer.consumerKey = "load"
        consumer.isHttpConsumer = True
        consumer.isMqttConsumer = False
        consumer.allowance = 1000
        consumer.request = 1000
        consumer.npcState = False
        consumer.onUrl = "http://load/on"
        consumer.offUrl = "http://load/off"
        consumer.statusUrl = "http://load/status"
        consumer.powerUrl = "http://load/power"
        consumer.onKeywordRegex = "ison"
        consumer.powerExtractRegex = r"power=(\d+)"
        consumer.consumption = 0
        consumer.httpRequestTimeout = 7.5
        return consumer

    def test_http_consumer_on_status_and_power_requests_use_configured_timeout(self):
        consumer = self._http_consumer()
        self.sod.requests.get = Mock(
            side_effect=[
                SimpleNamespace(text=""),
                SimpleNamespace(text="ison"),
                SimpleNamespace(text="power=450"),
            ]
        )

        consumer.httpControl()

        self.sod.requests.get.assert_any_call(
            url="http://load/on", timeout=7.5
        )
        self.sod.requests.get.assert_any_call(
            url="http://load/status", timeout=7.5
        )
        self.sod.requests.get.assert_any_call(
            url="http://load/power", timeout=7.5
        )
        self.assertTrue(consumer.npcState)
        self.assertEqual(consumer.consumption, 450)

    def test_http_consumer_off_request_uses_configured_timeout(self):
        consumer = self._http_consumer()
        consumer.allowance = 0
        consumer.npcState = True
        self.sod.requests.get = Mock(return_value=SimpleNamespace(text=""))

        consumer.httpControl()

        self.sod.requests.get.assert_any_call(
            url="http://load/off", timeout=7.5
        )
        self.sod.requests.get.assert_any_call(
            url="http://load/status", timeout=7.5
        )

    def test_http_consumer_timeout_does_not_crash_control_path(self):
        consumer = self._http_consumer()
        self.sod.requests.get = Mock(side_effect=self.sod.requests.exceptions.Timeout())

        consumer.httpControl()

        self.sod.c.assert_called()


if __name__ == "__main__":
    unittest.main()
