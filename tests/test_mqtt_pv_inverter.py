"""Hardware-free tests for MQTT PV inverter behavior."""

import configparser
import importlib.util
import sys
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


class FakeDbusService(dict):
    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self.registered = False

    def add_path(self, path, value, *args, **kwargs):
        self[path] = value

    def register(self):
        self.registered = True


def _config():
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read_dict(
        {
            "MqttPvInverter": {
                "EnableZeroFeedin": "true",
                "EnablePvShutdown": "false",
                "ZeroFeedinScaleStep": "0.05",
                "ZeroFeedinDistance": "50",
                "ZeroFeedinStartSoc": "90",
                "StaleTimeoutSeconds": "300",
            },
            "MqttPVInverter:roof": {
                "CustomName": "Roof",
                "VRMInstanceID": "51",
                "Position": "0",
                "L1VoltageTopic": "roof/l1v",
                "L2VoltageTopic": "roof/l2v",
                "L3VoltageTopic": "roof/l3v",
                "L1PowerTopic": "roof/l1p",
                "L2PowerTopic": "roof/l2p",
                "L3PowerTopic": "roof/l3p",
                "TotalPowerTopic": "roof/power",
                "L1CurrentTopic": "roof/l1c",
                "L2CurrentTopic": "roof/l2c",
                "L3CurrentTopic": "roof/l3c",
                "L1EnergyForwardedTopic": "roof/l1e",
                "L2EnergyForwardedTopic": "roof/l2e",
                "L3EnergyForwardedTopic": "roof/l3e",
                "TotalEnergyForwardedTopic": "roof/energy",
                "DtuControlTopic": "opendtu/roof",
            },
        }
    )
    return config


CONFIG = _config()


class BaseService:
    def __init__(self):
        self.config = CONFIG
        self.published = []
        self.subscriptions = []

    def publishMainMqtt(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))

    def publishServiceMessage(self, *_args, **_kwargs):
        pass

    def registerMqttSubscription(self, topic, qos=0, type=0, callback=None):
        self.subscriptions.append((topic, qos, type, callback))
        return self.subscriptions[-1]

    def registerWorkerThread(self, *_args, **_kwargs):
        pass


def _install_runtime_stubs():
    dbus = _module("dbus")
    dbus.__path__ = []
    dbus_service = _module("dbus.service")
    dbus.service = dbus_service
    _module("vedbus", VeDbusService=FakeDbusService)
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


class MqttPVInverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.module = _load_module(
            "mqtt_pv_inverter_under_test", ROOT / "MqttPVInverter.py"
        )

    def setUp(self):
        self.module.c = Mock()
        self.module.d = Mock()
        self.module.w = Mock()

    @staticmethod
    def _dbus(value):
        return SimpleNamespace(value=value)

    def _service(self):
        service = self.module.MqttPVInverter()
        inverter = service.mqttPVInverters["roof"]
        inverter.l1power = 100
        inverter.l2power = 0
        inverter.l3power = 0
        inverter._throttle = 0.5
        service.acInput0SourceDbus = self._dbus(1)
        service.acInput0ConnectedDbus = self._dbus(1)
        service.acInput1SourceDbus = self._dbus(2)
        service.acInput1ConnectedDbus = self._dbus(0)
        service.socDbus = self._dbus(100)
        service.consumptionL1Dbus = self._dbus(0)
        service.consumptionL2Dbus = self._dbus(0)
        service.consumptionL3Dbus = self._dbus(0)
        return service, inverter

    def test_zero_feedin_zero_target_publishes_zero_throttle(self):
        service, inverter = self._service()
        service.consumptionL1Dbus.value = 30

        service._dtuZeroFeedin()

        self.module.c.assert_not_called()
        self.assertEqual(inverter.throttle, 0.0)
        self.assertIn(
            ("opendtu/roof/cmd/limit_nonpersistent_relative", 0.0, 0, False),
            service.published,
        )

    def test_zero_feedin_positive_target_keeps_proportional_scaling(self):
        service, inverter = self._service()
        service.consumptionL1Dbus.value = 250

        service._dtuZeroFeedin()

        self.module.c.assert_not_called()
        self.assertEqual(inverter.throttle, 0.55)
        self.assertIn(
            ("opendtu/roof/cmd/limit_nonpersistent_relative", 55.00000000000001, 0, False),
            service.published,
        )

    def test_zero_feedin_missing_consumption_keeps_last_limit(self):
        for missing_phase in range(3):
            with self.subTest(missing_phase=missing_phase):
                service, inverter = self._service()
                subscriptions = (
                    service.consumptionL1Dbus,
                    service.consumptionL2Dbus,
                    service.consumptionL3Dbus,
                )
                subscriptions[missing_phase].value = None
                previous_publications = list(service.published)

                service._dtuZeroFeedin()

                self.assertEqual(inverter.throttle, 0.5)
                self.assertEqual(service.published, previous_publications)
                self.module.c.assert_not_called()
                self.module.d.assert_called()
                self.module.d.reset_mock()

    def test_zero_feedin_requires_explicit_connected_grid_input(self):
        scenarios = (
            (None, None, None, None),
            (1, 0, 2, 1),
            ("grid", 1, 2, 0),
            (1, "connected", 2, 0),
            (2, 1, 0, 0),
        )
        for input0_source, input0_connected, input1_source, input1_connected in scenarios:
            with self.subTest(
                input0=(input0_source, input0_connected),
                input1=(input1_source, input1_connected),
            ):
                service, inverter = self._service()
                service.acInput0SourceDbus.value = input0_source
                service.acInput0ConnectedDbus.value = input0_connected
                service.acInput1SourceDbus.value = input1_source
                service.acInput1ConnectedDbus.value = input1_connected
                previous_publications = list(service.published)

                service._dtuZeroFeedin()

                self.assertEqual(inverter.throttle, 0.5)
                self.assertEqual(service.published, previous_publications)
                self.module.c.assert_not_called()
                self.module.d.assert_called()
                self.module.d.reset_mock()

    def test_zero_feedin_accepts_connected_grid_on_second_input(self):
        service, inverter = self._service()
        service.acInput0ConnectedDbus.value = 0
        service.acInput1SourceDbus.value = 3
        service.acInput1ConnectedDbus.value = 1
        service.consumptionL1Dbus.value = 250

        service._dtuZeroFeedin()

        self.assertEqual(inverter.throttle, 0.55)
        self.assertTrue(service.published)

    def test_zero_feedin_offgrid_transition_holds_then_recovers(self):
        service, inverter = self._service()
        service.consumptionL1Dbus.value = 250

        service._dtuZeroFeedin()
        self.assertEqual(inverter.throttle, 0.55)
        publications_after_grid_control = list(service.published)

        service.acInput0ConnectedDbus.value = 0
        service._dtuZeroFeedin()
        self.assertEqual(inverter.throttle, 0.55)
        self.assertEqual(service.published, publications_after_grid_control)

        service.acInput0ConnectedDbus.value = 1
        service._dtuZeroFeedin()
        self.assertEqual(inverter.throttle, 0.6000000000000001)
        self.assertGreater(len(service.published), len(publications_after_grid_control))

    def test_zero_feedin_unexpected_error_keeps_critical_logger_callable(self):
        service, _inverter = self._service()
        service.mqttPVInverters = None

        service._dtuZeroFeedin()

        self.module.c.assert_called_once()
        self.assertIn("zero feedin calculation", self.module.c.call_args.args[1])

    def test_dbus_service_and_mqtt_subscriptions_initialize(self):
        service = self.module.MqttPVInverter()

        service.initDbusService()
        service.initMqttSubscriptions()

        inverter = service.mqttPVInverters["roof"]
        self.assertTrue(inverter.dbusService.registered)
        self.assertEqual(inverter.dbusService["/DeviceInstance"], 51)
        subscribed_topics = {entry[0] for entry in service.subscriptions}
        self.assertIn("roof/l1v", subscribed_topics)
        self.assertIn("roof/power", subscribed_topics)
        self.assertIn("roof/energy", subscribed_topics)

    def test_stale_boundary_clears_cached_power_once(self):
        service, inverter = self._service()
        service.initDbusService()
        inverter.lastMessageReceived = 100

        with patch.object(self.module.time, "time", return_value=400):
            service._checkStale()

        self.assertFalse(inverter.isStale)

        with patch.object(self.module.time, "time", return_value=401):
            service._checkStale()
            service._checkStale()

        self.assertTrue(inverter.isStale)
        self.assertEqual(inverter.total_power, 0)
        self.assertEqual(inverter.dbusService["/Connected"], 0)
        self.assertIsNone(inverter.dbusService["/Ac/L1/Power"])
        self.module.w.assert_called_once()

    def test_first_message_after_stale_recovers_and_rebuilds_power(self):
        service, inverter = self._service()
        service.initDbusService()
        inverter.setStale()
        message = SimpleNamespace(topic="roof/l1p", payload=b"125")

        inverter.onMqttMessage(None, None, message)

        self.assertFalse(inverter.isStale)
        self.assertEqual(inverter.dbusService["/Connected"], 1)
        self.assertEqual(inverter.l1power, 125)
        self.assertEqual(inverter.total_power, 125)


if __name__ == "__main__":
    unittest.main()
