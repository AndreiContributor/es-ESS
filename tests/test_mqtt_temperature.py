"""Hardware-free tests for MQTT temperature sensor D-Bus mapping."""

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


class FakeDbusService(dict):
    def __init__(self, *_args, **_kwargs):
        super().__init__()
        self.registered = False

    def add_path(self, path, value, *_args, **_kwargs):
        self[path] = value

    def register(self):
        self.registered = True


def _config():
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read_dict(
        {
            "MqttTemperature:outside": {
                "VRMInstanceID": "61",
                "CustomName": "Outside",
                "Topic": "sensors/outside/temperature",
                "TopicHumidity": "sensors/outside/humidity",
                "TopicPressure": "sensors/outside/pressure",
            }
        }
    )
    return config


class BaseService:
    def __init__(self):
        self.config = _config()
        self.subscriptions = []
        self.publishServiceMessage = Mock()

    def registerMqttSubscription(self, topic, callback=None):
        self.subscriptions.append((topic, callback))


def _install_runtime_stubs():
    dbus = _module("dbus")
    dbus.__path__ = []
    dbus.service = _module("dbus.service")
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
        c=Mock(),
        d=lambda *args, **kwargs: None,
        w=lambda *args, **kwargs: None,
        e=lambda *args, **kwargs: None,
        t=lambda *args, **kwargs: None,
        dbusConnection=lambda: None,
    )
    _module("esESSService", esESSService=BaseService)


class MqttTemperatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.module = _load_module(
            "mqtt_temperature_under_test",
            ROOT / "MqttTemperature.py",
        )

    def test_topics_and_dbus_paths_are_initialized(self):
        service = self.module.MqttTemperature()

        service.initDbusService()
        service.initMqttSubscriptions()

        sensor = service.temperatureSensors["outside"]
        self.assertTrue(sensor.dbusService.registered)
        self.assertEqual(sensor.dbusService["/DeviceInstance"], 61)
        self.assertEqual(sensor.dbusService["/CustomName"], "Outside")
        self.assertEqual(
            {topic for topic, _callback in service.subscriptions},
            {
                "sensors/outside/temperature",
                "sensors/outside/humidity",
                "sensors/outside/pressure",
            },
        )

    def test_temperature_humidity_and_pressure_messages_publish_to_dbus(self):
        service = self.module.MqttTemperature()
        service.initDbusService()
        sensor = service.temperatureSensors["outside"]

        for topic, payload in (
            (sensor.valueTopic, b"21.5"),
            (sensor.humidityTopic, b"48.2"),
            (sensor.pressureTopic, b"1008.4"),
        ):
            sensor.onMqttMessage(None, None, SimpleNamespace(topic=topic, payload=payload))

        self.assertEqual(sensor.dbusService["/Temperature"], 21.5)
        self.assertEqual(sensor.dbusService["/Humidity"], 48.2)
        self.assertEqual(sensor.dbusService["/Pressure"], 1008.4)
        self.assertEqual(service.publishServiceMessage.call_count, 4)
        self.module.c.assert_not_called()


if __name__ == "__main__":
    unittest.main()
