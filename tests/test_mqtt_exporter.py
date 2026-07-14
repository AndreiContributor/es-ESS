"""Hardware-free tests for MqttExporter publication contracts."""

import configparser
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call


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
            "MqttExporter:change": {
                "Service": "com.victronenergy.system",
                "DbusKey": "/Dc/Battery/Soc",
                "MqttTopic": "export/soc",
                "PublishType": "ONCHANGE",
            },
            "MqttExporter:one": {
                "Service": "com.victronenergy.system",
                "DbusKey": "/Ac/Grid/L1/Power",
                "MqttTopic": "export/one",
                "PublishType": "INTERVAL_1S",
            },
            "MqttExporter:ten": {
                "Service": "com.victronenergy.system",
                "DbusKey": "/Ac/Grid/L2/Power",
                "MqttTopic": "export/ten",
                "PublishType": "INTERVAL_10S",
            },
            "MqttExporter:sixty": {
                "Service": "com.victronenergy.system",
                "DbusKey": "/Ac/Grid/L3/Power",
                "MqttTopic": "export/sixty",
                "PublishType": "INTERVAL_60S",
            },
        }
    )
    return config


class BaseService:
    def __init__(self):
        self.config = _config()
        self.dbus_subscriptions = []
        self.worker_threads = []
        self.publishMainMqtt = Mock()
        self.publishServiceMessage = Mock()

    def registerDbusSubscription(self, service, path, callback=None):
        self.dbus_subscriptions.append((service, path, callback))
        return SimpleNamespace(serviceName=service, dbusPath=path, value=None)

    def registerWorkerThread(self, callback, interval):
        self.worker_threads.append((callback, interval))


def _install_runtime_stubs():
    dbus = _module("dbus")
    dbus.__path__ = []
    dbus.service = _module("dbus.service")
    _module("Globals")
    _module(
        "Helper",
        i=lambda *args, **kwargs: None,
        c=lambda *args, **kwargs: None,
        d=lambda *args, **kwargs: None,
        w=lambda *args, **kwargs: None,
        e=lambda *args, **kwargs: None,
    )
    _module("esESSService", esESSService=BaseService)


class MqttExporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.module = _load_module(
            "mqtt_exporter_under_test",
            ROOT / "MqttExporter.py",
        )

    def test_configuration_and_worker_intervals_are_registered(self):
        service = self.module.MqttExporter()

        service.initDbusSubscriptions()
        service.initWorkerThreads()

        self.assertEqual(len(service.dbus_subscriptions), 4)
        self.assertEqual([interval for _callback, interval in service.worker_threads], [1000, 10000, 60000])
        self.assertEqual(len(service.topicExports_1s), 1)
        self.assertEqual(len(service.topicExports_10s), 1)
        self.assertEqual(len(service.topicExports_60s), 1)

    def test_on_change_export_publishes_retained_value(self):
        service = self.module.MqttExporter()
        subscription = SimpleNamespace(
            serviceName="com.victronenergy.system",
            commonServiceName="com.victronenergy.system",
            dbusPath="/Dc/Battery/Soc",
            value=73,
        )

        service._dbusValueChanged(subscription)

        service.publishMainMqtt.assert_called_once_with("export/soc", 73, 0, True)
        self.assertEqual(service.forwardedTopicsPastMinute, 1)

    def test_interval_exports_publish_only_available_values(self):
        service = self.module.MqttExporter()
        service.topicExports_1s["com.victronenergy.system/Ac/Grid/L1/Power"].value = 101
        service.topicExports_10s["com.victronenergy.system/Ac/Grid/L2/Power"].value = 202

        service.process_1s_interval()
        service.process_10s_interval()
        service.process_60s_interval()

        self.assertEqual(
            service.publishMainMqtt.call_args_list,
            [
                call("export/one", 101, 0, True),
                call("export/ten", 202, 0, True),
            ],
        )
        self.assertEqual(service.forwardedTopicsPastMinute, 2)


if __name__ == "__main__":
    unittest.main()
