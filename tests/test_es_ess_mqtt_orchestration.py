"""Hardware-free tests for es-ESS MQTT orchestration."""

import importlib.util
import sys
import types
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


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
    class FakeDbusSubscription:
        @staticmethod
        def buildValueKey(service_name, dbus_path):
            return "{0}{1}".format(
                ".".join(service_name.split(".")[:3]), dbus_path
            )

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
        DbusSubscription=FakeDbusSubscription,
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
    def __init__(self, connected=True, events=None, name="mqtt"):
        self.connected = connected
        self.reconnect = True
        self.subscriptions = []
        self.callbacks = []
        self.publishes = []
        self.unsubscriptions = []
        self.disconnects = 0
        self.events = events
        self.name = name

    def is_connected(self):
        return self.connected

    def subscribe(self, topic, qos):
        self.subscriptions.append((topic, qos))

    def message_callback_add(self, topic, callback):
        self.callbacks.append((topic, callback))

    def publish(self, topic, payload, qos, retain):
        self.publishes.append((topic, payload, qos, retain))

    def unsubscribe(self, topic):
        self.unsubscriptions.append(topic)
        if self.events is not None:
            self.events.append("{0}-unsubscribe".format(self.name))

    def disconnect(self):
        self.disconnects += 1
        if self.events is not None:
            self.events.append("{0}-disconnect".format(self.name))


class RecordingExecutor:
    def __init__(self, submit_error=None):
        self.calls = []
        self.pending = []
        self.submit_error = submit_error

    def submit(self, callback, *args):
        if self.submit_error is not None:
            raise self.submit_error
        future = Future()
        self.calls.append((callback, args))
        self.pending.append((future, callback, args))
        return future

    def run_next(self):
        future, callback, args = self.pending.pop(0)
        try:
            future.set_result(callback(*args))
        except Exception as ex:
            future.set_exception(ex)
        return future


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
        app._sigTermInvoked = False
        app._shutdownMqttDisconnectsLogged = set()
        app._mqttSubscriptions = {}
        app._dbusSubscriptions = {}
        app._services = {}
        app._serviceMessageIndex = {}
        app.mqttThrottlePeriod = 0
        app.config = {"Common": {"ServiceMessageCount": "3"}}
        return app

    def test_dbus_callback_is_submitted_without_inline_execution(self):
        app = self._app()
        app.threadPool = RecordingExecutor()
        callback = Mock()
        subscription = SimpleNamespace(
            serviceName="com.victronenergy.system",
            callback=callback,
            value=None,
        )
        key = "com.victronenergy.system/Ac/Grid/L1/Power"
        app._dbusSubscriptions = {key: [subscription]}
        with patch.object(
            self.es_ess.DbusSubscription,
            "buildValueKey",
            return_value=key,
            create=True,
        ):
            app._dbusValueChanged(
                "com.victronenergy.system",
                "/Ac/Grid/L1/Power",
                None,
                {"Value": 123},
                None,
            )

        callback.assert_not_called()
        self.assertEqual(app.threadPool.calls, [(callback, (subscription,))])
        self.assertEqual(subscription.value, 123)

        app.threadPool.run_next()

        callback.assert_called_once_with(subscription)

    def test_dbus_callback_failure_is_reported(self):
        app = self._app()
        app.threadPool = RecordingExecutor()
        callback = Mock(side_effect=RuntimeError("callback failed"))
        subscription = SimpleNamespace(
            serviceName="com.victronenergy.system",
            callback=callback,
            value=None,
        )
        key = "com.victronenergy.system/Ac/Grid/L1/Power"
        app._dbusSubscriptions = {key: [subscription]}

        with patch.object(
            self.es_ess.DbusSubscription,
            "buildValueKey",
            return_value=key,
            create=True,
        ), patch.object(self.es_ess, "c") as critical_log:
            app._dbusValueChanged(
                "com.victronenergy.system",
                "/Ac/Grid/L1/Power",
                None,
                {"Value": 123},
                None,
            )
            app.threadPool.run_next()

        critical_log.assert_called_once()
        self.assertIn("asynchronous operation", critical_log.call_args.args[1])
        self.assertIsInstance(
            critical_log.call_args.kwargs["exc_info"], RuntimeError
        )

    def test_worker_future_failure_is_reported_and_recurring_timer_remains(self):
        app = self._app()
        app.threadPool = RecordingExecutor()
        app._threadExecutionsMinute = 0
        worker = SimpleNamespace(
            thread=Mock(side_effect=RuntimeError("worker failed")),
            future=None,
            onlyOnce=False,
            interval=1000,
            service=SimpleNamespace(),
        )

        with patch.object(self.es_ess, "c") as critical_log:
            self.assertTrue(app._runThread(worker))
            app.threadPool.run_next()

        critical_log.assert_called_once()
        self.assertEqual(app._threadExecutionsMinute, 1)

    def test_scheduling_failure_keeps_recurring_timer_and_removes_one_shot(self):
        app = self._app()
        app.threadPool = RecordingExecutor(submit_error=RuntimeError("closed"))
        app._threadExecutionsMinute = 0
        recurring = SimpleNamespace(
            thread=Mock(),
            future=None,
            onlyOnce=False,
            interval=1000,
            service=SimpleNamespace(),
        )
        one_shot = SimpleNamespace(
            thread=Mock(),
            future=None,
            onlyOnce=True,
            interval=1000,
            service=SimpleNamespace(),
        )

        with patch.object(self.es_ess, "c") as critical_log:
            self.assertTrue(app._runThread(recurring))
            self.assertFalse(app._runThread(one_shot))

        self.assertEqual(critical_log.call_count, 2)

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

    def test_shutdown_disconnects_log_at_info_only(self):
        app = self._app()
        app._sigTermInvoked = True

        with patch.object(self.es_ess, "i") as info_log, patch.object(
            self.es_ess, "w"
        ) as warning_log:
            app.onMainMqttDisconnect(None, None, 0)
            app.onLocalMqttDisconnect(None, None, 0)

        self.assertEqual(info_log.call_count, 4)
        warning_log.assert_not_called()
        self.assertTrue(
            all(
                "graceful shutdown" in call.args[1]
                for call in info_log.call_args_list
            )
        )

    def test_shutdown_disconnect_logging_is_deduplicated(self):
        app = self._app()
        app._sigTermInvoked = True

        with patch.object(self.es_ess, "i") as info_log:
            app._logShutdownMqttDisconnect("Main")
            app.onMainMqttDisconnect(None, None, 0)
            app._logShutdownMqttDisconnect("Local")
            app.onLocalMqttDisconnect(None, None, 0)

        self.assertEqual(info_log.call_count, 4)
        self.assertEqual(app._shutdownMqttDisconnectsLogged, {"Main", "Local"})

    def test_unexpected_disconnects_keep_warning_severity(self):
        app = self._app()

        with patch.object(self.es_ess, "i") as info_log, patch.object(
            self.es_ess, "w"
        ) as warning_log:
            app.onMainMqttDisconnect(None, None, 1)
            app.onLocalMqttDisconnect(None, None, 1)

        self.assertEqual(warning_log.call_count, 2)
        self.assertEqual(info_log.call_count, 2)
        self.assertTrue(
            all(
                "Waiting for automatic reconnect." in call.args[1]
                for call in info_log.call_args_list
            )
        )

    def test_disabled_reconnect_outside_shutdown_logs_warnings(self):
        app = self._app()
        app.mainMqttClient.reconnect = False
        app.localMqttClient.reconnect = False

        with patch.object(self.es_ess, "i") as info_log, patch.object(
            self.es_ess, "w"
        ) as warning_log:
            app.onMainMqttDisconnect(None, None, 1)
            app.onLocalMqttDisconnect(None, None, 1)

        self.assertEqual(warning_log.call_count, 4)
        info_log.assert_not_called()

    def test_shutdown_cleanup_is_idempotent_and_termination_is_last(self):
        events = []
        app = self._app()
        app.mainMqttClient = FakeMqttClient(events=events, name="main")
        app.localMqttClient = FakeMqttClient(events=events, name="local")
        app._gridSetPointDefault = 10
        app.config = {
            "Common": {
                "ServiceMessageCount": "3",
                "VRMPortalID": "portal-id",
            }
        }
        app.publishServiceMessage = lambda *_args, **_kwargs: events.append(
            "message"
        )
        app.publishLocalMqtt = lambda *_args, **_kwargs: events.append(
            "grid-restore"
        )

        subscription = self._subscription(
            "es-ESS/main", self.es_ess.MqttSubscriptionType.Main
        )
        app._mqttSubscriptions = {subscription.valueKey: [subscription]}

        service = SimpleNamespace(
            handleSigterm=lambda: events.append("service-cleanup")
        )
        app._services = {"service": service}
        app._terminateProcess = lambda: events.append("terminate")

        def record_info(_module, message, **_kwargs):
            if message == "Main MQTT disconnect during graceful shutdown.":
                events.append("main-shutdown-info")
            elif message == "Local MQTT disconnect during graceful shutdown.":
                events.append("local-shutdown-info")
            elif message == "Cleaned up. Bye.":
                events.append("final-log")

        with patch.object(self.es_ess, "i", side_effect=record_info):
            app.handleSigterm(None, None)
            app.handleSigterm(None, None)

        self.assertEqual(events.count("grid-restore"), 1)
        self.assertEqual(events.count("main-unsubscribe"), 1)
        self.assertEqual(events.count("service-cleanup"), 1)
        self.assertEqual(events.count("main-disconnect"), 1)
        self.assertEqual(events.count("local-disconnect"), 1)
        self.assertEqual(events.count("main-shutdown-info"), 1)
        self.assertEqual(events.count("local-shutdown-info"), 1)
        self.assertEqual(events.count("terminate"), 1)
        self.assertLess(events.index("grid-restore"), events.index("service-cleanup"))
        self.assertLess(
            events.index("service-cleanup"), events.index("main-disconnect")
        )
        self.assertLess(
            events.index("main-shutdown-info"), events.index("main-disconnect")
        )
        self.assertLess(
            events.index("local-shutdown-info"), events.index("local-disconnect")
        )
        self.assertLess(events.index("local-disconnect"), events.index("final-log"))
        self.assertLess(events.index("final-log"), events.index("terminate"))

    def test_termination_uses_uninterceptable_process_exit_after_log_flush(self):
        app = self._app()

        with patch.object(self.es_ess.logging, "shutdown") as shutdown, patch.object(
            self.es_ess.os, "_exit"
        ) as process_exit:
            app._terminateProcess()

        shutdown.assert_called_once_with()
        process_exit.assert_called_once_with(0)

    def test_lifecycle_scripts_supervise_and_verify_the_original_process(self):
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        service_run = (ROOT / "service" / "run").read_text(encoding="utf-8")
        restart_script = (ROOT / "restart.sh").read_text(encoding="utf-8")

        self.assertIn("*.sh text eol=lf", attributes)
        self.assertIn("service/run text eol=lf", attributes)
        for script in (
            "install.sh",
            "restart.sh",
            "kill_me.sh",
            "uninstall.sh",
            "service/run",
        ):
            self.assertNotIn(b"\r", (ROOT / script).read_bytes())
        self.assertIn("exec python /data/es-ESS/es-ESS.py", service_run)
        self.assertIn("GRACEFUL_TIMEOUT_SECONDS=10", restart_script)
        self.assertIn('/proc/$pid/stat', restart_script)
        self.assertIn('/proc/$pid/cmdline', restart_script)
        self.assertIn('kill -s 9 "$pid"', restart_script)


if __name__ == "__main__":
    unittest.main()
