"""Hardware-free tests for shared grid-setpoint request combination."""

import importlib.util
import sys
import threading
import types
import unittest
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

    _module(
        "Globals",
        esEssTagService="test",
        esEssTag="es-ESS",
        currentVersionString="test",
        MqttSubscriptionType=SimpleNamespace(Main="Main", Local="Local"),
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
        MqttSubscription=object,
    )


def _load_es_ess_module():
    spec = importlib.util.spec_from_file_location(
        "es_ess_grid_setpoint_under_test", ROOT / "es-ESS.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GridSetpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.es_ess = _load_es_ess_module()

    def _app(self):
        app = self.es_ess.esESS.__new__(self.es_ess.esESS)
        app._sigTermInvoked = False
        app._gridSetPointRequests = {}
        app._gridSetPointRequestsLock = threading.Lock()
        app._gridSetPointDefault = -50
        app._gridSetPointMin = -1000
        app._gridSetPointMax = 2000
        app._gridSetPointLastClamp = None
        app._gridSetPointCurrent = -99999
        app.config = {"Common": {"VRMPortalID": "portal-id"}}
        app.publishLocalMqtt = Mock()
        return app

    @staticmethod
    def _service(name):
        return type(name, (), {})()

    def test_combines_multiple_requests_and_only_publishes_changes(self):
        app = self._app()
        first = self._service("FirstService")
        second = self._service("SecondService")
        app.registerGridSetPointRequest(first, 1000)
        app.registerGridSetPointRequest(second, 500)

        app._manageGridSetPoint()
        app._manageGridSetPoint()

        app.publishLocalMqtt.assert_called_once_with(
            "W/portal-id/settings/0/Settings/CGwacs/AcPowerSetPoint",
            '{"value": 1450}',
            1,
            False,
        )

    def test_revocation_restores_default_without_removing_request_identity(self):
        app = self._app()
        service = self._service("NoBatToEV")
        app.registerGridSetPointRequest(service, 1200)
        app._manageGridSetPoint()
        app.revokeGridSetPointRequest(service)
        app._manageGridSetPoint()

        self.assertIsNone(app._gridSetPointRequests["NoBatToEV"])
        self.assertEqual(
            app.publishLocalMqtt.call_args_list[-1].args[1], '{"value": -50}'
        )

    def test_request_mutation_uses_combiner_lock(self):
        app = self._app()
        service = self._service("NoBatToEV")
        mutation_finished = threading.Event()
        app._gridSetPointRequestsLock.acquire()

        thread = threading.Thread(
            target=lambda: (
                app.registerGridSetPointRequest(service, 1000),
                mutation_finished.set(),
            )
        )
        thread.start()
        self.assertFalse(mutation_finished.wait(timeout=0.1))

        app._gridSetPointRequestsLock.release()
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertTrue(mutation_finished.is_set())
        self.assertEqual(app._gridSetPointRequests["NoBatToEV"], 1000)

    def test_combiner_releases_lock_before_mqtt_publication(self):
        app = self._app()
        service = self._service("NoBatToEV")
        app.registerGridSetPointRequest(service, 1000)

        def publish(*_args, **_kwargs):
            self.assertTrue(app._gridSetPointRequestsLock.acquire(blocking=False))
            app._gridSetPointRequestsLock.release()

        app.publishLocalMqtt.side_effect = publish
        app._manageGridSetPoint()

        app.publishLocalMqtt.assert_called_once()

    def test_combination_error_publishes_default_fallback(self):
        app = self._app()
        service = self._service("InvalidService")
        app.registerGridSetPointRequest(service, "invalid")

        app._manageGridSetPoint()

        app.publishLocalMqtt.assert_called_once_with(
            "W/portal-id/settings/0/Settings/CGwacs/AcPowerSetPoint",
            '{"value": -50}',
            1,
            False,
        )

    def test_non_finite_combination_publishes_default_fallback(self):
        app = self._app()
        service = self._service("InvalidService")
        app.registerGridSetPointRequest(service, float("nan"))

        app._manageGridSetPoint()

        app.publishLocalMqtt.assert_called_once_with(
            "W/portal-id/settings/0/Settings/CGwacs/AcPowerSetPoint",
            '{"value": -50}',
            1,
            False,
        )

    def test_combined_setpoint_clamps_at_exact_configured_bounds(self):
        app = self._app()
        app._gridSetPointMin = -100
        app._gridSetPointMax = 100
        service = self._service("NoBatToEV")

        app.registerGridSetPointRequest(service, 151)
        app._manageGridSetPoint()
        self.assertEqual(app.publishLocalMqtt.call_args.args[1], '{"value": 100}')

        app.registerGridSetPointRequest(service, -51)
        app._manageGridSetPoint()
        self.assertEqual(app.publishLocalMqtt.call_args.args[1], '{"value": -100}')

    def test_clamp_warning_is_once_per_distinct_out_of_range_sum(self):
        app = self._app()
        app._gridSetPointMax = 100
        service = self._service("NoBatToEV")
        app.registerGridSetPointRequest(service, 200)

        with patch.object(self.es_ess, "w") as warning:
            app._manageGridSetPoint()
            app._manageGridSetPoint()
            app.registerGridSetPointRequest(service, 300)
            app._manageGridSetPoint()

        self.assertEqual(warning.call_count, 2)

    def test_in_range_setpoint_preserves_additive_behavior(self):
        app = self._app()
        app._gridSetPointMin = -500
        app._gridSetPointMax = 500
        service = self._service("NoBatToEV")
        app.registerGridSetPointRequest(service, 400)

        with patch.object(self.es_ess, "w") as warning:
            app._manageGridSetPoint()

        self.assertEqual(app.publishLocalMqtt.call_args.args[1], '{"value": 350}')
        warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
