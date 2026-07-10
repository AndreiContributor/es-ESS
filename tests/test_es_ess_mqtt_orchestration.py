"""Hardware-free tests for es-ESS MQTT orchestration."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


class FakeMqttSubscription:
    def __init__(self, requestingService, topic, qos=0, type=None, callback=None):
        self.requestingService = requestingService
        self.topic = topic
        self.qos = qos
        self.type = type
        self.callback = callback

    @property
    def valueKey(self):
        return "{0}{1}".format(self.type, self.topic)


def _install_runtime_stubs():
    gi = _module("gi")
    gi_repository = _module(
        "gi.repository", GLib=SimpleNamespace(timeout_add=lambda *_args: None)
    )
    gi.repository = gi_repository

    paho = _module("paho")
    paho.__path__ = []
    paho_mqtt = _module("paho.mqtt")
    paho_mqtt.__path__ = []
    paho_mqtt_client = _module("paho.mqtt.client", Client=object)
    paho.mqtt = paho_mqtt
    paho_mqtt.client = paho_mqtt_client

    _module("vedbus", VeDbusService=object)
    _module("dbusmonitor", DbusMonitor=object)
    dbus = _module("dbus")
    dbus.__path__ = []
    dbus_mainloop = _module("dbus.mainloop")
    dbus_mainloop.__path__ = []
    dbus.mainloop = dbus_mainloop
    dbus_mainloop_glib = _module(
        "dbus.mainloop.glib", DBusGMainLoop=lambda *args, **kwargs: None
    )
    dbus_mainloop.glib = dbus_mainloop_glib

    mqtt_types = SimpleNamespace(Main="Main", Local="Local")
    _module(
        "Globals",
        esEssTagService="test",
        esEssTag="es-ESS",
        currentVersionString="test",
        MqttSubscriptionType=mqtt_types,
        ServiceMessageType=SimpleNamespace(Operational="Operational"),
        getUserTime=lambda: "now",
    )
    _module(
        "Helper",
        i=lambda *args, **kwargs: None,
        c=lambda *args, **kwargs: None,
        d=lambda *args, **kwargs: None,
        w=lambda *args, **kwargs: None,
        e=lambda *args, **kwargs: None,
        t=lambda *args, **kwargs: None,
        waitTimeout=lambda *args, **kwargs: False,
        formatCallback=lambda callback: getattr(callback, "__name__", str(callback)),
    )
    _module(
        "esESSService",
        DbusSubscription=object,
        esESSService=object,
        WorkerThread=object,
        MqttSubscription=FakeMqttSubscription,
    )


def _load_es_ess_module():
    spec = importlib.util.spec_from_file_location(
        "es_ess_mqtt_orchestration_under_test", ROOT / "es-ESS.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeMqttClient:
    def __init__(self, connected=True):
        self.connected = connected
        self.subscriptions = []
        self.callbacks = []
        self.publishes = []

    def is_connected(self):
        return self.connected

    def subscribe(self, topic, qos):
        self.subscriptions.append((topic, qos))

    def message_callback_add(self, topic, callback):
        self.callbacks.append((topic, callback))

    def publish(self, topic, payload, qos, retain):
        self.publishes.append((topic, payload, qos, retain))


class FakeBooleanConnectedClient(FakeMqttClient):
    def __init__(self, connected=True):
        super().__init__(connected)
        self.is_connected = connected


class EsEssMqttOrchestrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.es_ess = _load_es_ess_module()

    def _app(self, main_connected=True, local_connected=True):
        app = self.es_ess.esESS.__new__(self.es_ess.esESS)
        app.mainMqttClient = FakeMqttClient(main_connected)
        app.localMqttClient = FakeMqttClient(local_connected)
        app.mainMqttClientConnected = False
        app.localMqttClientConnected = False
        app._mqttSubscriptions = {}
        app._serviceMessageIndex = {}
        app.mqttThrottlePeriod = 0
        app.config = {"Common": {"ServiceMessageCount": "3"}}
        return app

    def _subscription(self, topic, type, qos=1):
        return self.es_ess.MqttSubscription(
            SimpleNamespace(),
            topic,
            qos,
            type,
            callback=lambda *_args: None,
        )

    def test_main_reconnect_restores_only_main_subscriptions_on_main_client(self):
        app = self._app()
        main_sub = self._subscription(
            "es-ESS/main", self.es_ess.MqttSubscriptionType.Main
        )
        local_sub = self._subscription(
            "es-ESS/local", self.es_ess.MqttSubscriptionType.Local
        )
        app._mqttSubscriptions = {
            main_sub.valueKey: [main_sub],
            local_sub.valueKey: [local_sub],
        }

        with patch.object(self.es_ess, "d") as debug_log:
            app.onMainMqttConnect(None, None, None, 0)

        self.assertEqual(app.mainMqttClient.subscriptions, [("es-ESS/main", 1)])
        self.assertEqual(app.mainMqttClient.callbacks, [("es-ESS/main", main_sub.callback)])
        self.assertEqual(app.localMqttClient.subscriptions, [])
        self.assertTrue(app.mainMqttClientConnected)
        debug_log.assert_called_once()
        self.assertIn("Restoring main MQTT subscription", debug_log.call_args.args[1])
        self.assertIn("es-ESS/main", debug_log.call_args.args[1])
        self.assertNotIn("es-ESS/local", debug_log.call_args.args[1])

    def test_local_reconnect_restores_only_local_subscriptions_on_local_client(self):
        app = self._app()
        main_sub = self._subscription(
            "es-ESS/main", self.es_ess.MqttSubscriptionType.Main
        )
        local_sub = self._subscription(
            "es-ESS/local", self.es_ess.MqttSubscriptionType.Local
        )
        app._mqttSubscriptions = {
            main_sub.valueKey: [main_sub],
            local_sub.valueKey: [local_sub],
        }

        with patch.object(self.es_ess, "d") as debug_log:
            app.onLocalMqttConnect(None, None, None, 0)

        self.assertEqual(app.localMqttClient.subscriptions, [("es-ESS/local", 1)])
        self.assertEqual(app.localMqttClient.callbacks, [("es-ESS/local", local_sub.callback)])
        self.assertEqual(app.mainMqttClient.subscriptions, [])
        self.assertTrue(app.localMqttClientConnected)
        debug_log.assert_called_once()
        self.assertIn("Restoring local MQTT subscription", debug_log.call_args.args[1])
        self.assertIn("es-ESS/local", debug_log.call_args.args[1])
        self.assertNotIn("es-ESS/main", debug_log.call_args.args[1])

    def test_initial_registration_keeps_main_and_local_clients_separate(self):
        app = self._app()
        main_sub = self._subscription(
            "es-ESS/main", self.es_ess.MqttSubscriptionType.Main
        )
        local_sub = self._subscription(
            "es-ESS/local", self.es_ess.MqttSubscriptionType.Local
        )

        app.registerMqttSubscription(main_sub)
        app.registerMqttSubscription(local_sub)

        self.assertEqual(app.mainMqttClient.subscriptions, [("es-ESS/main", 1)])
        self.assertEqual(app.localMqttClient.subscriptions, [("es-ESS/local", 1)])

    def test_service_message_is_skipped_without_main_client(self):
        app = self._app()
        app.mainMqttClient = None

        app.publishServiceMessage("UnitService", "hello")

        self.assertEqual(app._serviceMessageIndex, {})

    def test_service_message_is_skipped_when_main_client_is_disconnected(self):
        app = self._app(main_connected=False)

        app.publishServiceMessage("UnitService", "hello")

        self.assertEqual(app.mainMqttClient.publishes, [])
        self.assertEqual(app._serviceMessageIndex, {})

    def test_service_message_is_published_when_main_client_is_connected(self):
        app = self._app(main_connected=True)

        app.publishServiceMessage("UnitService", "hello")

        self.assertEqual(
            app.mainMqttClient.publishes,
            [
                (
                    "es-ESS/UnitService/ServiceMessages/Operational/Message01",
                    "now | hello",
                    0,
                    True,
                )
            ],
        )

    def test_service_message_accepts_boolean_is_connected_attribute(self):
        app = self._app()
        app.mainMqttClient = FakeBooleanConnectedClient(True)

        app.publishServiceMessage("UnitService", "hello")

        self.assertEqual(len(app.mainMqttClient.publishes), 1)


if __name__ == "__main__":
    unittest.main()
