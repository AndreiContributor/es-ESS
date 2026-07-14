"""Hardware-free SolarOverheadDistributor startup safety tests."""

import importlib.util
import sys
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
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
        self.isHttpConsumer = False
        self.isMqttConsumer = False
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
        self.sod.e = Mock()
        self.sod.w = Mock()
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

    def test_allowance_update_runs_outside_consumer_lock(self):
        service = self._service(grid=(None, 0, 0), battery_power=0)
        lock_states = []

        class LockCheckingConsumer(StubConsumer):
            def updateAllowance(self, allowance, distributor):
                lock_states.append(
                    service._knownSolarOverheadConsumersLock.locked()
                )
                super().updateAllowance(allowance, distributor)

        service._knownSolarOverheadConsumers["load"] = LockCheckingConsumer()

        self.assertTrue(service.updateDistribution())

        self.assertEqual(lock_states, [False])

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

    def test_http_and_mqtt_npc_allocation_requires_complete_request(self):
        for npc_attribute in ("isHttpConsumer", "isMqttConsumer"):
            with self.subTest(npc_attribute=npc_attribute):
                service = self._service()
                consumer = StubConsumer(npc_attribute)
                setattr(consumer, npc_attribute, True)
                consumer.minimum = 400
                consumer.request = 1000
                consumer.stepSize = 1000
                service._knownSolarOverheadConsumers = {
                    consumer.consumerKey: consumer
                }

                insufficient = service.doAssign(
                    overhead=999,
                    overheadDistribution={consumer.consumerKey: 0},
                    minBatCharge=0,
                )
                exact = service.doAssign(
                    overhead=1000,
                    overheadDistribution={consumer.consumerKey: 0},
                    minBatCharge=0,
                )
                excess = service.doAssign(
                    overhead=1300,
                    overheadDistribution={consumer.consumerKey: 0},
                    minBatCharge=0,
                )

                self.assertEqual(insufficient[consumer.consumerKey], 0)
                self.assertEqual(exact[consumer.consumerKey], 1000)
                self.assertEqual(excess[consumer.consumerKey], 1000)

    def test_npc_allocation_caps_increment_to_remaining_request(self):
        service = self._service()
        consumer = StubConsumer("http")
        consumer.isHttpConsumer = True
        consumer.minimum = 400
        consumer.request = 1000
        consumer.stepSize = 1000
        service._knownSolarOverheadConsumers = {consumer.consumerKey: consumer}

        assigned = service.doAssign(
            overhead=600,
            overheadDistribution={consumer.consumerKey: 400},
            minBatCharge=0,
        )

        self.assertEqual(assigned[consumer.consumerKey], 1000)

    def test_npc_atomic_request_respects_battery_reservation_and_bypass(self):
        service = self._service()
        consumer = StubConsumer("http")
        consumer.isHttpConsumer = True
        consumer.minimum = 400
        consumer.request = 1000
        consumer.stepSize = 1000
        service._knownSolarOverheadConsumers = {consumer.consumerKey: consumer}

        reserved = service.doAssign(
            overhead=1500,
            overheadDistribution={consumer.consumerKey: 0},
            minBatCharge=600,
        )
        consumer.ignoreBatReservation = True
        bypassed = service.doAssign(
            overhead=1000,
            overheadDistribution={consumer.consumerKey: 0},
            minBatCharge=600,
        )

        self.assertEqual(reserved[consumer.consumerKey], 0)
        self.assertEqual(bypassed[consumer.consumerKey], 1000)

    def test_ineligible_high_priority_npc_does_not_reserve_partial_power(self):
        service = self._service()
        npc = StubConsumer("pool-pump")
        npc.isHttpConsumer = True
        npc.priority = 10
        npc.minimum = 400
        npc.request = 1000
        npc.stepSize = 1000
        heater = StubConsumer("heater")
        heater.isMqttConsumer = True
        heater.priority = 20
        heater.minimum = 200
        heater.request = 500
        heater.stepSize = 500
        service._knownSolarOverheadConsumers = {
            npc.consumerKey: npc,
            heater.consumerKey: heater,
        }

        assigned = service.doAssign(
            overhead=800,
            overheadDistribution={npc.consumerKey: 0, heater.consumerKey: 0},
            minBatCharge=0,
        )

        self.assertEqual(assigned[npc.consumerKey], 0)
        self.assertEqual(assigned[heater.consumerKey], 500)

    def test_scripted_consumer_keeps_minimum_first_allocation(self):
        service = self._service()
        scripted = StubConsumer("scripted")
        scripted.minimum = 400
        scripted.request = 1000
        scripted.stepSize = 1000
        service._knownSolarOverheadConsumers = {
            scripted.consumerKey: scripted
        }

        assigned = service.doAssign(
            overhead=800,
            overheadDistribution={scripted.consumerKey: 0},
            minBatCharge=0,
        )

        self.assertEqual(assigned[scripted.consumerKey], 400)

    def test_update_distribution_publishes_atomic_npc_allowance(self):
        service = self._service(grid=(-1000, 0, 0), battery_power=0)
        consumer = StubConsumer("http")
        consumer.isHttpConsumer = True
        consumer.minimum = 400
        consumer.request = 1000
        consumer.stepSize = 1000
        service._knownSolarOverheadConsumers[consumer.consumerKey] = consumer

        service.updateDistribution()

        self.assertEqual(consumer.allowance_updates, [1000])
        self.assertEqual(
            service.dbusService["/Calculations/OverheadAssigned"], 1000
        )
        self.assertEqual(
            service.dbusService["/Calculations/OverheadRemaining"], 0
        )

    def test_min_battery_charge_expression_supports_safe_soc_arithmetic(self):
        service = self._service(
            grid=(-2000, -2000, -2000),
            battery_power=0,
            battery_soc=50,
        )
        service.config = {
            "SolarOverheadDistributor": {
                "MinBatteryCharge": "max(0, (80 - SOC) * 100)"
            }
        }

        service.updateDistribution()

        self.sod.c.assert_not_called()
        self.sod.e.assert_not_called()
        self.assertEqual(service.dbusService["/Calculations/Battery/Reservation"], 3000)

    def test_min_battery_charge_none_soc_falls_back_to_zero_with_warning(self):
        service = self._service(
            grid=(-100, -100, -100),
            battery_power=0,
            battery_soc=None,
        )
        service.config = {
            "SolarOverheadDistributor": {"MinBatteryCharge": "SOC * 100"}
        }

        service.updateDistribution()

        self.sod.c.assert_not_called()
        self.sod.e.assert_not_called()
        self.sod.w.assert_any_call(
            service,
            "Battery SOC is unavailable. Using MinBatteryCharge=0.",
        )
        self.assertEqual(service.dbusService["/Calculations/Battery/Reservation"], 0)

    def test_min_battery_charge_malicious_expression_is_rejected(self):
        with patch.object(self.sod.os, "system") as system_mock:
            with self.assertRaises(ValueError):
                self.sod._evaluateMinBatteryChargeExpression(
                    "__import__('os').system('echo unsafe')",
                    80,
                )

            system_mock.assert_not_called()

    def test_min_battery_charge_boolean_literal_is_rejected(self):
        with self.assertRaises(ValueError):
            self.sod._evaluateMinBatteryChargeExpression("True + 1", 80)

    def test_min_battery_charge_invalid_expression_falls_back_to_zero(self):
        service = self._service(
            grid=(-100, -100, -100),
            battery_power=0,
            battery_soc=80,
        )
        service.config = {
            "SolarOverheadDistributor": {
                "MinBatteryCharge": "__import__('os').system('echo unsafe')"
            }
        }

        service.updateDistribution()

        self.sod.c.assert_not_called()
        self.sod.e.assert_called()
        self.assertEqual(service.dbusService["/Calculations/Battery/Reservation"], 0)

    def test_persist_energy_stats_releases_consumer_lock_before_io(self):
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
        self.assertTrue(registration_done.wait(timeout=0.5))

        release_persist.set()
        persist_thread.join(timeout=2)
        register_thread.join(timeout=2)

        self.assertFalse(persist_thread.is_alive())
        self.assertFalse(register_thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(registration_done.is_set())
        self.assertIn("new", service._knownSolarOverheadConsumers)
        self.assertEqual(service._knownSolarOverheadConsumers["slow"].persist_calls, 1)

    def test_npc_validation_runs_endpoint_work_outside_consumer_lock(self):
        service = self._service()
        lock_states = []
        consumer = StubConsumer("http")
        consumer.isInitialized = True
        consumer.isHttpConsumer = True
        consumer.isMqttConsumer = False
        consumer.validateHttpStatus = lambda _expected: lock_states.append(
            service._knownSolarOverheadConsumersLock.locked()
        )
        consumer.httpControl = lambda: lock_states.append(
            service._knownSolarOverheadConsumersLock.locked()
        )
        service._knownSolarOverheadConsumers[consumer.consumerKey] = consumer
        service.dumpConsumerBms = Mock()

        self.assertTrue(service._validateNpcConsumerStates())

        self.assertEqual(lock_states, [False, False])

    def test_mqtt_consumer_lookup_and_update_share_one_lock_scope(self):
        service = self._service()
        lock_states = []

        class LockCheckingConsumer:
            def setValue(self, _topic, _message):
                lock_states.append(service._knownSolarOverheadConsumersLock.locked())

        service._knownSolarOverheadConsumers["load"] = LockCheckingConsumer()

        service.onMqttMessage(
            None,
            None,
            SimpleNamespace(
                topic="es-ESS/SolarOverheadDistributor/Requests/load/Request",
                payload=b"500",
            ),
        )

        self.assertEqual(lock_states, [True])
        self.sod.c.assert_not_called()

    def test_dbus_consumption_accepts_missing_request(self):
        consumer = self.sod.SolarOverheadConsumer.__new__(
            self.sod.SolarOverheadConsumer
        )
        consumer.dbusService = {}
        consumer.consumption = 250
        consumer.request = None

        consumer.dbusReportConsumption()

        self.assertEqual(consumer.dbusService["/Dc/0/Power"], 250)
        self.assertEqual(consumer.dbusService["/Soc"], 0)

    def test_energy_today_topic_publishes_today_value(self):
        consumer = self._http_consumer()
        consumer.isAutomatic = False
        consumer.energyToday = 1.25
        consumer.energyYesterday = 2.5
        consumer.energyTotal = 9.75
        consumer.runtimeToday = 10
        consumer.runtimeYesterday = 20
        consumer.runtimeTotal = 30
        consumer.calculateEnergy = Mock()
        consumer.dbusReportConsumption = Mock()
        sod = SimpleNamespace(
            publishMainMqtt=Mock(),
            parseAndPubHttpConsumer=Mock(),
        )

        with patch.object(self.sod.Globals, "getUserTime", return_value="now", create=True):
            consumer.updateAllowance(500, sod)

        sod.publishMainMqtt.assert_any_call(
            "es-ESS/SolarOverheadDistributor/Requests/load/Energy/energyToday",
            1.25,
            1,
            True,
        )

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

    def _mqtt_consumer(self):
        consumer = self.sod.SolarOverheadConsumer.__new__(
            self.sod.SolarOverheadConsumer
        )
        consumer.consumerKey = "load"
        consumer.isHttpConsumer = False
        consumer.isMqttConsumer = True
        consumer.allowance = 1000
        consumer.request = 1000
        consumer.npcState = False
        consumer.onTopic = "load/set"
        consumer.onValue = "on"
        consumer.offTopic = "load/set"
        consumer.offValue = "off"
        consumer.statusTopic = "load/status"
        consumer.powerTopic = "load/power"
        consumer.onKeywordRegex = "on"
        consumer.powerExtractRegex = r"power=(\d+)"
        consumer.consumption = 0
        return consumer

    def test_mqtt_status_match_updates_state_and_zero_allowance_turns_off(self):
        consumer = self._mqtt_consumer()
        self.sod.Globals.esESS.publishMainMqtt = Mock()

        consumer.onMqttMessage(
            None,
            None,
            SimpleNamespace(topic="load/status", payload=b"on"),
        )
        self.assertTrue(consumer.npcState)
        self.sod.e.assert_not_called()

        consumer.allowance = 0
        consumer.mqttControl()

        self.sod.Globals.esESS.publishMainMqtt.assert_called_once_with(
            "load/set", "off"
        )

    def test_mqtt_full_allowance_turns_on(self):
        consumer = self._mqtt_consumer()
        self.sod.Globals.esESS.publishMainMqtt = Mock()

        consumer.mqttControl()

        self.sod.Globals.esESS.publishMainMqtt.assert_called_once_with(
            "load/set", "on"
        )

    def test_malformed_mqtt_power_keeps_last_valid_state_and_is_visible(self):
        consumer = self._mqtt_consumer()
        consumer.npcState = True
        consumer.consumption = 450
        consumer.powerExtractRegex = r"power=\d+"

        consumer.onMqttMessage(
            None,
            None,
            SimpleNamespace(topic="load/power", payload=b"power=500"),
        )

        self.assertTrue(consumer.npcState)
        self.assertEqual(consumer.consumption, 450)
        self.sod.e.assert_called_once()
        self.assertIn("Keeping the last valid state", self.sod.e.call_args.args[1])

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
