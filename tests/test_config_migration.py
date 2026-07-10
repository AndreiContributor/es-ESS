"""Regression tests for es-ESS configuration migrations."""

import configparser
import importlib.util
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _install_runtime_stubs():
    gi = _module("gi")
    gi_repository = _module("gi.repository", GLib=types.SimpleNamespace(timeout_add=lambda *_args: None))
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
        esEssTag="test",
        currentVersionString="test",
        MqttSubscriptionType=types.SimpleNamespace(Main=0, Local=1),
        ServiceMessageType=types.SimpleNamespace(Operational="Operational"),
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
        "es_ess_config_migration_under_test", ROOT / "es-ESS.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ConfigMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.es_ess = _load_es_ess_module()

    def _run_migration(self, config_text):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = tmp_path / "config.ini"
            config_path.write_text(
                textwrap.dedent(config_text).strip() + "\n", encoding="utf-8"
            )

            app = self.es_ess.esESS.__new__(self.es_ess.esESS)
            with patch.object(
                self.es_ess.os.path,
                "realpath",
                return_value=str(tmp_path / "es-ESS.py"),
            ):
                app._validateConfiguration()

            migrated = configparser.ConfigParser()
            migrated.optionxform = str
            migrated.read(config_path)
            backup_names = sorted(path.name for path in tmp_path.glob("config.ini.v*.backup"))
            return migrated, backup_names

    def test_existing_later_sections_do_not_break_version_6_migration(self):
        migrated, backups = self._run_migration(
            """
            [Common]
            ConfigVersion=6

            [Services]
            MqttPVInverter=true

            [NoBatToEV]
            UseRelay=4

            [MqttPvInverter]
            EnableZeroFeedin=true
            """
        )

        self.assertEqual(migrated["Common"]["ConfigVersion"], "9")
        self.assertEqual(migrated["Common"]["HttpRequestTimeout"], "5")
        self.assertEqual(migrated["NoBatToEV"]["UseRelay"], "4")
        self.assertEqual(migrated["MqttPvInverter"]["EnableZeroFeedin"], "true")
        self.assertEqual(migrated["MqttPvInverter"]["EnablePvShutdown"], "false")
        self.assertEqual(migrated["MqttPvInverter"]["ZeroFeedinScaleStep"], "0.05")
        self.assertEqual(migrated["MqttPvInverter"]["ZeroFeedinDistance"], "50")
        self.assertEqual(migrated["MqttPvInverter"]["ZeroFeedinStartSoc"], "100")
        self.assertEqual(
            backups,
            ["config.ini.v6.backup", "config.ini.v7.backup", "config.ini.v8.backup"],
        )

    def test_missing_later_sections_are_added_with_defaults(self):
        migrated, _backups = self._run_migration(
            """
            [Common]
            ConfigVersion=6

            [Services]
            MqttPVInverter=false
            """
        )

        self.assertEqual(migrated["Common"]["ConfigVersion"], "9")
        self.assertEqual(migrated["Common"]["HttpRequestTimeout"], "5")
        self.assertEqual(migrated["NoBatToEV"]["UseRelay"], "-1")
        self.assertEqual(migrated["MqttPvInverter"]["EnableZeroFeedin"], "false")
        self.assertEqual(migrated["MqttPvInverter"]["EnablePvShutdown"], "false")
        self.assertEqual(migrated["MqttPvInverter"]["ZeroFeedinScaleStep"], "0.05")
        self.assertEqual(migrated["MqttPvInverter"]["ZeroFeedinDistance"], "50")
        self.assertEqual(migrated["MqttPvInverter"]["ZeroFeedinStartSoc"], "100")

    def test_existing_service_flags_are_preserved_when_defaults_are_added(self):
        migrated, _backups = self._run_migration(
            """
            [Common]
            ConfigVersion=1

            [Services]
            Shelly3EMGrid=true
            ShellyPMInverter=true
            MqttDC=true
            MqttPVInverter=true

            [SolarOverheadDistributor]
            Strategy=legacy
            """
        )

        self.assertEqual(migrated["Common"]["ConfigVersion"], "9")
        self.assertEqual(migrated["Common"]["HttpRequestTimeout"], "5")
        self.assertEqual(migrated["Services"]["Shelly3EMGrid"], "true")
        self.assertEqual(migrated["Services"]["ShellyPMInverter"], "true")
        self.assertEqual(migrated["Services"]["MqttDC"], "true")
        self.assertEqual(migrated["Services"]["MqttPVInverter"], "true")
        self.assertFalse(migrated.has_option("SolarOverheadDistributor", "Strategy"))

    def test_existing_http_request_timeout_is_preserved(self):
        migrated, _backups = self._run_migration(
            """
            [Common]
            ConfigVersion=8
            HttpRequestTimeout=12

            [Services]
            MqttPVInverter=false
            """
        )

        self.assertEqual(migrated["Common"]["ConfigVersion"], "9")
        self.assertEqual(migrated["Common"]["HttpRequestTimeout"], "12")


if __name__ == "__main__":
    unittest.main()
