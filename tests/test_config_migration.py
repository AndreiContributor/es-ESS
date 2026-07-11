"""Regression tests for es-ESS configuration migrations."""

import configparser
import importlib.util
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
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
            ChargeCurrentReducer=true
            FroniusSmartmeterRS485=true
            Grid2Bat=false
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
        self.assertEqual(migrated["Services"]["ChargeCurrentReducer"], "true")
        self.assertEqual(migrated["Services"]["FroniusSmartmeterRS485"], "true")
        self.assertEqual(migrated["Services"]["Grid2Bat"], "false")
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


class ConfigValueValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.es_ess = _load_es_ess_module()

    def _sample_config(self):
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(ROOT / "config.sample.ini")
        return config

    def _app_with_sample_config(self):
        app = self.es_ess.esESS.__new__(self.es_ess.esESS)
        app.config = self._sample_config()
        return app

    def test_maintained_sample_and_valid_boundaries_pass(self):
        app = self._app_with_sample_config()
        wattpilot = app.config["FroniusWattpilot"]
        wattpilot["MinCurrentPerPhase"] = "6"
        wattpilot["MaxCurrentPerPhase"] = "32"
        wattpilot["ThreePhasePvSurplusStartW"] = "4101"
        wattpilot["ThreePhasePvSurplusStopW"] = "4100"
        wattpilot["BatteryAssistSocMin"] = "0"
        wattpilot["BatteryAssistMaxSeconds"] = "1"
        wattpilot["AllowanceDropGraceSeconds"] = "0"
        wattpilot["SurplusDropGraceSeconds"] = "0"
        wattpilot["CarDisconnectConfirmSeconds"] = "0"
        wattpilot["StartupGraceSeconds"] = "0"
        app.config["SolarOverheadDistributor"]["UpdateInterval"] = "1"
        app.config["TimeToGoCalculator"]["UpdateInterval"] = "1"
        app.config["FroniusSmartmeterJSON"]["PollFrequencyMs"] = "1"
        app.config.add_section("Shelly3EMGrid")
        app.config["Shelly3EMGrid"]["PollFrequencyMs"] = "1"
        app.config.add_section("ShellyPMInverter:Roof")
        app.config["ShellyPMInverter:Roof"]["PollFrequencyMs"] = "1"

        app._validateConfigValues()

        wattpilot["BatteryAssistSocMin"] = "100"
        app._validateConfigValues()

    def test_disabled_battery_assist_allows_zero_max_seconds(self):
        app = self._app_with_sample_config()
        app.config["FroniusWattpilot"]["BatteryAssistEnabled"] = "false"
        app.config["FroniusWattpilot"]["BatteryAssistMaxSeconds"] = "0"

        app._validateConfigValues()

    def test_each_invalid_value_causes_clean_startup_failure(self):
        cases = (
            ("FroniusWattpilot", "MinCurrentPerPhase", "5"),
            ("FroniusWattpilot", "MaxCurrentPerPhase", "33"),
            ("FroniusWattpilot", "BatteryAssistSocMin", "-1"),
            ("FroniusWattpilot", "BatteryAssistSocMin", "101"),
            ("FroniusWattpilot", "BatteryAssistMaxSeconds", "0"),
            ("FroniusWattpilot", "AllowanceDropGraceSeconds", "-1"),
            ("FroniusWattpilot", "SurplusDropGraceSeconds", "-1"),
            ("FroniusWattpilot", "CarDisconnectConfirmSeconds", "-1"),
            ("FroniusWattpilot", "StartupGraceSeconds", "-1"),
            ("SolarOverheadDistributor", "UpdateInterval", "0"),
            ("TimeToGoCalculator", "UpdateInterval", "0"),
            ("FroniusSmartmeterJSON", "PollFrequencyMs", "0"),
        )

        for section, key, value in cases:
            with self.subTest(section=section, key=key, value=value):
                app = self._app_with_sample_config()
                app.config[section][key] = value
                with patch.object(self.es_ess, "c") as critical:
                    with self.assertRaises(SystemExit) as raised:
                        app._validateConfigValues()

                self.assertEqual(raised.exception.code, 1)
                self.assertIn(key, critical.call_args.args[1])

    def test_inverted_current_and_phase_ranges_are_rejected(self):
        range_cases = (
            ("MinCurrentPerPhase", "20", "MaxCurrentPerPhase", "10"),
            (
                "ThreePhasePvSurplusStartW",
                "4100",
                "ThreePhasePvSurplusStopW",
                "4100",
            ),
        )

        for first_key, first_value, second_key, second_value in range_cases:
            with self.subTest(first_key=first_key):
                app = self._app_with_sample_config()
                wattpilot = app.config["FroniusWattpilot"]
                wattpilot[first_key] = first_value
                wattpilot[second_key] = second_value
                with patch.object(self.es_ess, "c") as critical:
                    with self.assertRaises(SystemExit) as raised:
                        app._validateConfigValues()

                self.assertEqual(raised.exception.code, 1)
                self.assertIn(first_key, critical.call_args.args[1])

    def test_optional_shelly_poll_intervals_are_rejected_when_present(self):
        for section in ("Shelly3EMGrid", "ShellyPMInverter:Roof"):
            with self.subTest(section=section):
                app = self._app_with_sample_config()
                app.config.add_section(section)
                app.config[section]["PollFrequencyMs"] = "0"
                with patch.object(self.es_ess, "c") as critical:
                    with self.assertRaises(SystemExit) as raised:
                        app._validateConfigValues()

                self.assertEqual(raised.exception.code, 1)
                self.assertIn(section, critical.call_args.args[1])

    def test_non_numeric_value_is_reported_as_configuration_error(self):
        app = self._app_with_sample_config()
        app.config["FroniusWattpilot"]["MinCurrentPerPhase"] = "six"

        with patch.object(self.es_ess, "c") as critical:
            with self.assertRaises(SystemExit) as raised:
                app._validateConfigValues()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("must be an integer", critical.call_args.args[1])

    def test_non_finite_number_is_reported_as_configuration_error(self):
        app = self._app_with_sample_config()
        app.config["FroniusWattpilot"]["BatteryAssistSocMin"] = "nan"

        with patch.object(self.es_ess, "c") as critical:
            with self.assertRaises(SystemExit) as raised:
                app._validateConfigValues()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("must be a finite number", critical.call_args.args[1])

    def test_all_validation_errors_are_logged_before_exit(self):
        app = self._app_with_sample_config()
        app.config["FroniusWattpilot"]["MinCurrentPerPhase"] = "5"
        app.config["SolarOverheadDistributor"]["UpdateInterval"] = "0"

        with patch.object(self.es_ess, "c") as critical:
            with self.assertRaises(SystemExit):
                app._validateConfigValues()

        messages = [call.args[1] for call in critical.call_args_list]
        self.assertEqual(len(messages), 2)
        self.assertTrue(any("MinCurrentPerPhase" in message for message in messages))
        self.assertTrue(any("UpdateInterval" in message for message in messages))

    def test_configuration_processing_invokes_value_validation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = tmp_path / "config.ini"
            config_path.write_text(
                (ROOT / "config.sample.ini").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            app = self.es_ess.esESS.__new__(self.es_ess.esESS)
            app._validateConfigValues = Mock()

            with patch.object(
                self.es_ess.os.path,
                "realpath",
                return_value=str(tmp_path / "es-ESS.py"),
            ):
                app._validateConfiguration()

            app._validateConfigValues.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
