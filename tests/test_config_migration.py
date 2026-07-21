"""Regression tests for es-ESS configuration migrations."""

import configparser
import logging
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

    def _run_invalid_configuration(self, config_text=None):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            if config_text is not None:
                (tmp_path / "config.ini").write_text(
                    textwrap.dedent(config_text).strip() + "\n", encoding="utf-8"
                )

            app = self.es_ess.esESS.__new__(self.es_ess.esESS)
            with patch.object(
                self.es_ess.os.path,
                "realpath",
                return_value=str(tmp_path / "es-ESS.py"),
            ), patch.object(self.es_ess, "c") as critical:
                with self.assertRaises(SystemExit) as raised:
                    app._validateConfiguration()

            self.assertEqual(raised.exception.code, 1)
            return [call.args[1] for call in critical.call_args_list]

    def test_missing_configuration_file_fails_cleanly(self):
        messages = self._run_invalid_configuration()

        self.assertEqual(len(messages), 1)
        self.assertIn("file was not found or could not be read", messages[0])

    def test_missing_common_section_fails_cleanly(self):
        messages = self._run_invalid_configuration(
            """
            [Mqtt]
            Host=localhost
            """
        )

        self.assertEqual(len(messages), 1)
        self.assertIn("missing mandatory [Common] section", messages[0])

    def test_missing_config_version_fails_cleanly(self):
        messages = self._run_invalid_configuration(
            """
            [Common]
            LogLevel=INFO
            """
        )

        self.assertEqual(len(messages), 1)
        self.assertIn("missing mandatory [Common] ConfigVersion", messages[0])

    def test_malformed_config_version_fails_cleanly(self):
        for value in ("ten", "10.5"):
            with self.subTest(value=value):
                messages = self._run_invalid_configuration(
                    """
                    [Common]
                    ConfigVersion={0}
                    """.format(value)
                )

                self.assertEqual(len(messages), 1)
                self.assertIn("ConfigVersion must be an integer", messages[0])

    def test_malformed_ini_fails_cleanly(self):
        messages = self._run_invalid_configuration(
            """
            [Common
            ConfigVersion=10
            """
        )

        self.assertEqual(len(messages), 1)
        self.assertIn("unable to read", messages[0])

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

        self.assertEqual(migrated["Common"]["ConfigVersion"], "15")
        self.assertEqual(migrated["Common"]["LogRetentionDays"], "10")
        self.assertEqual(migrated["Common"]["HttpRequestTimeout"], "5")
        self.assertEqual(migrated["Common"]["GridSetPointMinW"], "0")
        self.assertEqual(migrated["Common"]["GridSetPointMaxW"], "0")
        self.assertEqual(migrated["NoBatToEV"]["UseRelay"], "4")
        self.assertEqual(migrated["MqttPvInverter"]["EnableZeroFeedin"], "true")
        self.assertEqual(migrated["MqttPvInverter"]["EnablePvShutdown"], "false")
        self.assertEqual(migrated["MqttPvInverter"]["ZeroFeedinScaleStep"], "0.05")
        self.assertEqual(migrated["MqttPvInverter"]["ZeroFeedinDistance"], "50")
        self.assertEqual(migrated["MqttPvInverter"]["ZeroFeedinStartSoc"], "100")
        self.assertEqual(migrated["MqttPvInverter"]["StaleTimeoutSeconds"], "300")
        self.assertEqual(migrated["Mqtt"]["SslVerification"], "Required")
        self.assertEqual(migrated["Mqtt"]["LocalSslVerification"], "Required")
        self.assertEqual(
            backups,
            [
                "config.ini.v10.backup",
                "config.ini.v11.backup",
                "config.ini.v12.backup",
                "config.ini.v13.backup",
                "config.ini.v14.backup",
                "config.ini.v6.backup",
                "config.ini.v7.backup",
                "config.ini.v8.backup",
                "config.ini.v9.backup",
            ],
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

        self.assertEqual(migrated["Common"]["ConfigVersion"], "15")
        self.assertEqual(migrated["Common"]["LogRetentionDays"], "10")
        self.assertEqual(migrated["Common"]["HttpRequestTimeout"], "5")
        self.assertEqual(migrated["NoBatToEV"]["UseRelay"], "-1")
        self.assertEqual(migrated["MqttPvInverter"]["EnableZeroFeedin"], "false")
        self.assertEqual(migrated["MqttPvInverter"]["EnablePvShutdown"], "false")
        self.assertEqual(migrated["MqttPvInverter"]["ZeroFeedinScaleStep"], "0.05")
        self.assertEqual(migrated["MqttPvInverter"]["ZeroFeedinDistance"], "50")
        self.assertEqual(migrated["MqttPvInverter"]["ZeroFeedinStartSoc"], "100")
        self.assertEqual(migrated["MqttPvInverter"]["StaleTimeoutSeconds"], "300")

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

        self.assertEqual(migrated["Common"]["ConfigVersion"], "15")
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

        self.assertEqual(migrated["Common"]["ConfigVersion"], "15")
        self.assertEqual(migrated["Common"]["HttpRequestTimeout"], "12")

    def test_version_10_removes_obsolete_phase_switch_delay(self):
        migrated, backups = self._run_migration(
            """
            [Common]
            ConfigVersion=9
            HttpRequestTimeout=5

            [FroniusWattpilot]
            MinPhaseSwitchSeconds=600
            PhaseSwitchDelaySeconds=120
            """
        )

        self.assertEqual(migrated["Common"]["ConfigVersion"], "15")
        self.assertEqual(
            migrated["FroniusWattpilot"]["MinPhaseSwitchSeconds"], "600"
        )
        self.assertFalse(
            migrated.has_option("FroniusWattpilot", "PhaseSwitchDelaySeconds")
        )
        self.assertEqual(
            backups,
            [
                "config.ini.v10.backup",
                "config.ini.v11.backup",
                "config.ini.v12.backup",
                "config.ini.v13.backup",
                "config.ini.v14.backup",
                "config.ini.v9.backup",
            ],
        )

    def test_version_11_makes_legacy_tls_compatibility_explicit(self):
        migrated, backups = self._run_migration(
            """
            [Common]
            ConfigVersion=10
            DefaultPowerSetPoint=-50

            [Mqtt]
            SslEnabled=true
            LocalSslEnabled=false
            """
        )

        self.assertEqual(migrated["Common"]["ConfigVersion"], "15")
        self.assertEqual(migrated["Common"]["GridSetPointMinW"], "-50")
        self.assertEqual(migrated["Common"]["GridSetPointMaxW"], "-50")
        self.assertEqual(migrated["Mqtt"]["SslVerification"], "Insecure")
        self.assertEqual(migrated["Mqtt"]["LocalSslVerification"], "Required")
        self.assertEqual(migrated["Mqtt"]["SslCaFile"], "")
        self.assertEqual(
            backups,
            [
                "config.ini.v10.backup",
                "config.ini.v11.backup",
                "config.ini.v12.backup",
                "config.ini.v13.backup",
                "config.ini.v14.backup",
            ],
        )

    def test_version_12_adds_default_log_retention_without_changing_level(self):
        migrated, backups = self._run_migration(
            """
            [Common]
            ConfigVersion=11
            LogLevel=APP_DEBUG
            """
        )

        self.assertEqual(migrated["Common"]["ConfigVersion"], "15")
        self.assertEqual(migrated["Common"]["LogLevel"], "APP_DEBUG")
        self.assertEqual(migrated["Common"]["LogRetentionDays"], "10")
        self.assertEqual(
            backups,
            [
                "config.ini.v11.backup",
                "config.ini.v12.backup",
                "config.ini.v13.backup",
                "config.ini.v14.backup",
            ],
        )

    def test_version_12_preserves_existing_log_retention(self):
        migrated, _backups = self._run_migration(
            """
            [Common]
            ConfigVersion=11
            LogRetentionDays=21
            """
        )

        self.assertEqual(migrated["Common"]["LogRetentionDays"], "21")

    def test_version_13_adds_mandatory_site_current_guard_defaults(self):
        migrated, backups = self._run_migration(
            """
            [Common]
            ConfigVersion=12

            [FroniusWattpilot]
            MaxCurrentPerPhase=16
            """
        )

        self.assertEqual(migrated["Common"]["ConfigVersion"], "15")
        self.assertEqual(migrated["FroniusWattpilot"]["SiteMaxCurrent"], "20")
        self.assertEqual(
            migrated["FroniusWattpilot"]["Charger1PhaseMapping"], "L1"
        )
        self.assertEqual(
            migrated["FroniusWattpilot"]["SiteCurrentFreshSeconds"], "15"
        )
        self.assertEqual(
            migrated["FroniusWattpilot"]["SiteCurrentRecoverySeconds"], "30"
        )
        self.assertEqual(
            backups,
            [
                "config.ini.v12.backup",
                "config.ini.v13.backup",
                "config.ini.v14.backup",
            ],
        )

    def test_version_13_preserves_existing_site_current_values(self):
        migrated, _backups = self._run_migration(
            """
            [Common]
            ConfigVersion=12

            [FroniusWattpilot]
            SiteMaxCurrent=25
            Charger1PhaseMapping=L3
            SiteCurrentFreshSeconds=10
            SiteCurrentRecoverySeconds=45
            """
        )

        wattpilot = migrated["FroniusWattpilot"]
        self.assertEqual(wattpilot["SiteMaxCurrent"], "25")
        self.assertEqual(wattpilot["Charger1PhaseMapping"], "L3")
        self.assertEqual(wattpilot["SiteCurrentFreshSeconds"], "10")
        self.assertEqual(wattpilot["SiteCurrentRecoverySeconds"], "45")

    def test_version_14_replaces_aggregate_battery_shortfall_setting(self):
        migrated, backups = self._run_migration(
            """
            [Common]
            ConfigVersion=13

            [FroniusWattpilot]
            BatteryAssistMaxShortfallW=1000
            """
        )

        wattpilot = migrated["FroniusWattpilot"]
        self.assertEqual(migrated["Common"]["ConfigVersion"], "15")
        self.assertNotIn("BatteryAssistMaxShortfallW", wattpilot)
        self.assertEqual(
            wattpilot["BatteryAssistMaxShortfallPerPhaseW"], "1500"
        )
        self.assertEqual(
            backups, ["config.ini.v13.backup", "config.ini.v14.backup"]
        )

    def test_version_15_adds_extensible_site_current_source_defaults(self):
        migrated, backups = self._run_migration(
            """
            [Common]
            ConfigVersion=14

            [FroniusWattpilot]
            SiteMaxCurrent=25
            """
        )

        self.assertEqual(migrated["Common"]["ConfigVersion"], "15")
        self.assertEqual(
            migrated["FroniusWattpilot"]["SiteCurrentSource"],
            "VenusSystem",
        )
        shelly = migrated["Shelly3EMSiteCurrent"]
        self.assertEqual(shelly["Host"], "")
        self.assertEqual(shelly["Username"], "admin")
        self.assertEqual(shelly["Password"], "")
        self.assertEqual(shelly["PollFrequencyMs"], "1000")
        self.assertEqual(shelly["RequestTimeoutSeconds"], "2")
        self.assertEqual(
            [shelly["PhaseA"], shelly["PhaseB"], shelly["PhaseC"]],
            ["L1", "L2", "L3"],
        )
        self.assertEqual(backups, ["config.ini.v14.backup"])


class LoggingConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.es_ess = _load_es_ess_module()

    def _timezone_context(self, timezone):
        return Mock(
            snapshot=Mock(return_value=("Europe/Bucharest", timezone))
        )

    def _format_at(self, instant, timezone):
        record = logging.LogRecord(
            "es-ess", 11, __file__, 1, "diagnostic", (), None
        )
        record.levelname = "APP_DEBUG"
        record.created = instant.timestamp()
        record.msecs = 123
        formatter = self.es_ess.LocalTimezoneLogFormatter(
            "%(asctime)s %(levelname)s %(message)s",
            "%Y-%m-%d %H:%M:%S",
            self._timezone_context(timezone),
        )
        return formatter.format(record)

    def test_formatter_uses_venus_timezone_in_romanian_summer(self):
        instant = self.es_ess.datetime.datetime(
            2026, 7, 15, 15, 42, 10, 123000,
            tzinfo=self.es_ess.datetime.timezone.utc,
        )

        self.assertEqual(
            self._format_at(
                instant,
                self.es_ess.datetime.timezone(
                    self.es_ess.datetime.timedelta(hours=3)
                ),
            ),
            "2026-07-15 18:42:10,123 (UTC+3) APP_DEBUG diagnostic",
        )

    def test_formatter_uses_venus_timezone_in_romanian_winter(self):
        instant = self.es_ess.datetime.datetime(
            2026, 1, 15, 16, 42, 10, 123000,
            tzinfo=self.es_ess.datetime.timezone.utc,
        )

        self.assertEqual(
            self._format_at(
                instant,
                self.es_ess.datetime.timezone(
                    self.es_ess.datetime.timedelta(hours=2)
                ),
            ),
            "2026-01-15 18:42:10,123 (UTC+2) APP_DEBUG diagnostic",
        )

    def test_venus_timezone_query_reads_named_setting_with_timeout(self):
        completed = Mock(
            returncode=0,
            stdout="'Europe/Bucharest'\n",
            stderr="",
        )
        with patch.object(
            self.es_ess, "ZoneInfo", return_value=self.es_ess.datetime.timezone.utc
        ) as zone_info, patch.object(
            self.es_ess.subprocess, "run", return_value=completed
        ) as run:
            timezone_name = self.es_ess._readVenusTimezone()

        self.assertEqual(timezone_name, "Europe/Bucharest")
        zone_info.assert_called_once_with("Europe/Bucharest")
        run.assert_called_once_with(
            [
                "dbus",
                "-y",
                "com.victronenergy.settings",
                "/Settings/System/TimeZone",
                "GetValue",
            ],
            capture_output=True,
            text=True,
            timeout=3,
        )

    def test_offset_format_supports_whole_and_partial_hour_timezones(self):
        timedelta = self.es_ess.datetime.timedelta

        self.assertEqual(self.es_ess._formatUtcOffset(timedelta(hours=3)), "(UTC+3)")
        self.assertEqual(self.es_ess._formatUtcOffset(timedelta(hours=-5)), "(UTC-5)")
        self.assertEqual(
            self.es_ess._formatUtcOffset(timedelta(hours=5, minutes=30)),
            "(UTC+5:30)",
        )

    def test_retention_keeps_current_day_plus_nine_local_day_logs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_log = Path(tmp_dir) / "current.log"
            timezone = self.es_ess.datetime.timezone(
                self.es_ess.datetime.timedelta(hours=3)
            )
            timezone_context = self._timezone_context(timezone)
            handler = self.es_ess.LocalCalendarTimedRotatingFileHandler(
                str(base_log), 10, timezone_context
            )
            try:
                today = self.es_ess.datetime.datetime.now(timezone).date()
                rotated = {}
                for age in range(1, 13):
                    path = Path(
                        "{0}.{1}".format(
                            base_log,
                            (today - self.es_ess.datetime.timedelta(days=age)).isoformat(),
                        )
                    )
                    path.write_text("log\n", encoding="utf-8")
                    rotated[age] = path
                unrelated = Path(str(base_log) + ".backup")
                unrelated.write_text("keep\n", encoding="utf-8")

                failures = handler.pruneExpiredLogs()

                self.assertEqual(failures, [])
                self.assertTrue(base_log.exists())
                for age in range(1, 10):
                    self.assertTrue(rotated[age].exists(), age)
                for age in range(10, 13):
                    self.assertFalse(rotated[age].exists(), age)
                self.assertTrue(unrelated.exists())
                retained_logs = [base_log] + [rotated[age] for age in range(1, 10)]
                self.assertEqual(sum(path.exists() for path in retained_logs), 10)
            finally:
                handler.close()

    def test_rollover_uses_next_midnight_in_venus_timezone(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            timezone = self.es_ess.datetime.timezone(
                self.es_ess.datetime.timedelta(hours=3)
            )
            timezone_context = self._timezone_context(timezone)
            handler = self.es_ess.LocalCalendarTimedRotatingFileHandler(
                str(Path(tmp_dir) / "current.log"), 10, timezone_context
            )
            try:
                current = self.es_ess.datetime.datetime(
                    2026, 7, 15, 21, 30,
                    tzinfo=self.es_ess.datetime.timezone.utc,
                )
                expected = self.es_ess.datetime.datetime(
                    2026, 7, 17, 0, 0,
                    tzinfo=timezone,
                )

                self.assertEqual(
                    handler.computeRollover(current.timestamp()),
                    int(expected.timestamp()),
                )
            finally:
                handler.close()

    def test_rollover_names_completed_venus_calendar_day(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base_log = Path(tmp_dir) / "current.log"
            base_log.write_text("completed day\n", encoding="utf-8")
            timezone = self.es_ess.datetime.timezone(
                self.es_ess.datetime.timedelta(hours=3)
            )
            handler = self.es_ess.LocalCalendarTimedRotatingFileHandler(
                str(base_log), 10, self._timezone_context(timezone)
            )
            try:
                local_midnight = self.es_ess.datetime.datetime(
                    2026, 7, 16, 0, 0, tzinfo=timezone
                )
                handler.rolloverAt = int(local_midnight.timestamp())
                with patch.object(
                    handler, "getFilesToDelete", return_value=[]
                ), patch.object(
                    self.es_ess.time,
                    "time",
                    return_value=local_midnight.timestamp(),
                ):
                    handler.doRollover()

                rotated = Path(str(base_log) + ".2026-07-15")
                self.assertEqual(rotated.read_text(encoding="utf-8"), "completed day\n")
                self.assertTrue(base_log.exists())
            finally:
                handler.close()


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
        wattpilot["BatterySocFreshSeconds"] = "1"
        wattpilot["MinPhaseSwitchSeconds"] = "0"
        wattpilot["AllowanceDropGraceSeconds"] = "0"
        wattpilot["SurplusDropGraceSeconds"] = "0"
        wattpilot["CarDisconnectConfirmSeconds"] = "0"
        wattpilot["StartupGraceSeconds"] = "0"
        wattpilot["GridImportStopW"] = "0"
        wattpilot["GridImportStopSeconds"] = "0"
        wattpilot["GridTelemetryFreshSeconds"] = "1"
        wattpilot["AllowanceFreshSeconds"] = "1"
        wattpilot["RawOverheadFreshSeconds"] = "5"
        wattpilot["SiteMaxCurrent"] = "6"
        wattpilot["Charger1PhaseMapping"] = "L3"
        wattpilot["SiteCurrentFreshSeconds"] = "1"
        wattpilot["SiteCurrentRecoverySeconds"] = "0"
        wattpilot["BatteryAssistMaxShortfallPerPhaseW"] = "0"
        wattpilot["BatteryAssistRecoverySeconds"] = "0"
        wattpilot["StartupTelemetryRatio"] = "1"
        app.config["Common"]["NumberOfThreads"] = "1"
        app.config["Common"]["LogRetentionDays"] = "1"
        app.config["Common"]["HttpRequestTimeout"] = "0.1"
        app.config["Common"]["GridSetPointMinW"] = "-100"
        app.config["Common"]["GridSetPointMaxW"] = "100"
        app.config["MqttPvInverter"]["StaleTimeoutSeconds"] = "5"
        app.config["MqttPvInverter"]["ZeroFeedinScaleStep"] = "1"
        app.config["MqttPvInverter"]["ZeroFeedinDistance"] = "0"
        app.config["MqttPvInverter"]["ZeroFeedinStartSoc"] = "0"
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

    def test_maintained_sample_passes_runtime_bootstrap_validation(self):
        app = self._app_with_sample_config()

        app._validateRuntimeBootstrap()

    def test_valid_shelly_site_current_source_configuration_passes(self):
        app = self._app_with_sample_config()
        app.config["FroniusWattpilot"]["SiteCurrentSource"] = "Shelly3EMGen3"
        shelly = app.config["Shelly3EMSiteCurrent"]
        shelly["Host"] = "192.0.2.40"
        shelly["PhaseA"] = "L3"
        shelly["PhaseB"] = "L1"
        shelly["PhaseC"] = "L2"

        app._validateConfigValues()

    def test_invalid_site_current_source_name_is_rejected(self):
        app = self._app_with_sample_config()
        app.config["FroniusWattpilot"]["SiteCurrentSource"] = "Automatic"

        with patch.object(self.es_ess, "c") as critical:
            with self.assertRaises(SystemExit):
                app._validateConfigValues()

        self.assertIn("SiteCurrentSource", critical.call_args.args[1])

    def test_selected_shelly_source_requires_valid_connection_and_mapping(self):
        cases = (
            ("Host", ""),
            ("Host", "http://192.0.2.40"),
            ("Username", "operator"),
            ("PollFrequencyMs", "499"),
            ("RequestTimeoutSeconds", "0"),
            ("RequestTimeoutSeconds", "11"),
            ("PhaseC", "L2"),
        )
        for key, value in cases:
            with self.subTest(key=key, value=value):
                app = self._app_with_sample_config()
                app.config["FroniusWattpilot"][
                    "SiteCurrentSource"
                ] = "Shelly3EMGen3"
                shelly = app.config["Shelly3EMSiteCurrent"]
                shelly["Host"] = "192.0.2.40"
                if key == "PhaseC":
                    shelly["PhaseA"] = "L1"
                    shelly["PhaseB"] = "L2"
                shelly[key] = value

                with patch.object(self.es_ess, "c") as critical:
                    with self.assertRaises(SystemExit):
                        app._validateConfigValues()

                self.assertIn(key.split("/")[0], critical.call_args.args[1])

    def test_selected_shelly_source_requires_provider_section(self):
        app = self._app_with_sample_config()
        app.config["FroniusWattpilot"]["SiteCurrentSource"] = "Shelly3EMGen3"
        app.config.remove_section("Shelly3EMSiteCurrent")

        with patch.object(self.es_ess, "c") as critical:
            with self.assertRaises(SystemExit):
                app._validateConfigValues()

        self.assertIn("Shelly3EMSiteCurrent", critical.call_args.args[1])

    def test_invalid_shelly_host_credentials_are_not_logged(self):
        app = self._app_with_sample_config()
        app.config["FroniusWattpilot"]["SiteCurrentSource"] = (
            "Shelly3EMGen3"
        )
        app.config["Shelly3EMSiteCurrent"]["Host"] = (
            "admin:super-secret@192.0.2.40"
        )

        with patch.object(self.es_ess, "c") as critical:
            with self.assertRaises(SystemExit):
                app._validateConfigValues()

        message = critical.call_args.args[1]
        self.assertIn("<redacted invalid host>", message)
        self.assertNotIn("super-secret", message)

    def test_runtime_bootstrap_aggregates_missing_structure(self):
        app = self._app_with_sample_config()
        app.config.remove_option("Common", "NumberOfThreads")
        app.config.remove_option("Common", "LogRetentionDays")
        app.config.remove_section("Mqtt")
        app.config.remove_option("Services", "MqttExporter")

        with patch.object(self.es_ess, "c") as critical:
            with self.assertRaises(SystemExit) as raised:
                app._validateRuntimeBootstrap()

        self.assertEqual(raised.exception.code, 1)
        messages = [call.args[1] for call in critical.call_args_list]
        self.assertEqual(len(messages), 4)
        self.assertTrue(any("NumberOfThreads" in message for message in messages))
        self.assertTrue(any("LogRetentionDays" in message for message in messages))
        self.assertTrue(any("[Mqtt] section" in message for message in messages))
        self.assertTrue(any("MqttExporter" in message for message in messages))

    def test_runtime_bootstrap_aggregates_malformed_types(self):
        app = self._app_with_sample_config()
        app.config["Common"]["LogLevel"] = "LOUD"
        app.config["Common"]["NumberOfThreads"] = "many"
        app.config["Common"]["ServiceMessageCount"] = "many"
        app.config["Common"]["LogRetentionDays"] = "many"
        app.config["Common"]["DefaultPowerSetPoint"] = "nan"
        app.config["Mqtt"]["Port"] = "mqtt"
        app.config["Mqtt"]["SslEnabled"] = "perhaps"
        app.config["Mqtt"]["ThrottlePeriod"] = "soon"
        app.config["Services"]["FroniusWattpilot"] = "perhaps"

        with patch.object(self.es_ess, "c") as critical:
            with self.assertRaises(SystemExit) as raised:
                app._validateRuntimeBootstrap()

        self.assertEqual(raised.exception.code, 1)
        messages = [call.args[1] for call in critical.call_args_list]
        self.assertEqual(len(messages), 9)
        for key in (
            "LogLevel",
            "NumberOfThreads",
            "ServiceMessageCount",
            "LogRetentionDays",
            "DefaultPowerSetPoint",
            "Port",
            "SslEnabled",
            "ThrottlePeriod",
            "FroniusWattpilot",
        ):
            self.assertTrue(any(key in message for message in messages), key)

    def test_constructor_reraises_unexpected_initialization_failure(self):
        with patch.object(
            self.es_ess.RuntimeCompatibility,
            "require_validated_venus_os",
            return_value="v3.75",
        ), patch.object(
            self.es_ess.esESS,
            "_validateConfiguration",
            side_effect=RuntimeError("configuration failed"),
        ), patch.object(self.es_ess, "c") as critical:
            with self.assertRaisesRegex(RuntimeError, "configuration failed"):
                self.es_ess.esESS()

        critical.assert_called_once()

    def test_constructor_stops_before_wait_for_invalid_bootstrap(self):
        invalid_config = self._sample_config()
        invalid_config.remove_option("Common", "NumberOfThreads")

        def load_invalid_config(app):
            app.config = invalid_config

        with patch.object(
            self.es_ess.RuntimeCompatibility,
            "require_validated_venus_os",
            return_value="v3.75",
        ), patch.object(
            self.es_ess.esESS,
            "_validateConfiguration",
            autospec=True,
            side_effect=load_invalid_config,
        ), patch.object(
            self.es_ess.Helper, "waitTimeout"
        ) as wait_timeout, patch.object(self.es_ess, "c"):
            with self.assertRaises(SystemExit) as raised:
                self.es_ess.esESS()

        self.assertEqual(raised.exception.code, 1)
        wait_timeout.assert_not_called()

    def test_main_reraises_runtime_construction_failure(self):
        with patch.object(
            self.es_ess.RuntimeCompatibility,
            "require_validated_venus_os",
            return_value="v3.75",
        ), patch.object(
            self.es_ess,
            "esESS",
            side_effect=RuntimeError("construction failed"),
        ), patch.object(self.es_ess, "c") as critical:
            with self.assertRaisesRegex(RuntimeError, "construction failed"):
                self.es_ess.main(self._sample_config())

        critical.assert_called_once()

    def test_disabled_battery_assist_allows_zero_max_seconds(self):
        app = self._app_with_sample_config()
        app.config["FroniusWattpilot"]["BatteryAssistEnabled"] = "false"
        app.config["FroniusWattpilot"]["BatteryAssistMaxSeconds"] = "0"

        app._validateConfigValues()

    def test_missing_battery_soc_freshness_uses_compatible_default(self):
        app = self._app_with_sample_config()
        app.config.remove_option("FroniusWattpilot", "BatterySocFreshSeconds")

        app._validateConfigValues()

    def test_each_invalid_value_causes_clean_startup_failure(self):
        cases = (
            ("FroniusWattpilot", "MinCurrentPerPhase", "5"),
            ("FroniusWattpilot", "MaxCurrentPerPhase", "33"),
            ("FroniusWattpilot", "BatteryAssistSocMin", "-1"),
            ("FroniusWattpilot", "BatteryAssistSocMin", "101"),
            ("FroniusWattpilot", "BatteryAssistMaxSeconds", "0"),
            ("FroniusWattpilot", "BatterySocFreshSeconds", "0"),
            ("FroniusWattpilot", "MinPhaseSwitchSeconds", "-1"),
            ("FroniusWattpilot", "AllowanceDropGraceSeconds", "-1"),
            ("FroniusWattpilot", "SurplusDropGraceSeconds", "-1"),
            ("FroniusWattpilot", "CarDisconnectConfirmSeconds", "-1"),
            ("FroniusWattpilot", "StartupGraceSeconds", "-1"),
            ("FroniusWattpilot", "GridImportStopW", "-1"),
            ("FroniusWattpilot", "GridImportStopSeconds", "-1"),
            ("FroniusWattpilot", "GridTelemetryFreshSeconds", "0"),
            ("FroniusWattpilot", "AllowanceFreshSeconds", "0"),
            ("FroniusWattpilot", "RawOverheadFreshSeconds", "4"),
            ("FroniusWattpilot", "SiteMaxCurrent", "5"),
            ("FroniusWattpilot", "Charger1PhaseMapping", "L4"),
            ("FroniusWattpilot", "SiteCurrentFreshSeconds", "0"),
            ("FroniusWattpilot", "SiteCurrentRecoverySeconds", "-1"),
            (
                "FroniusWattpilot",
                "BatteryAssistMaxShortfallPerPhaseW",
                "-1",
            ),
            ("FroniusWattpilot", "BatteryAssistRecoverySeconds", "-1"),
            ("FroniusWattpilot", "StartupTelemetryRatio", "0"),
            ("FroniusWattpilot", "StartupTelemetryRatio", "1.01"),
            ("Common", "NumberOfThreads", "0"),
            ("Common", "LogRetentionDays", "0"),
            ("Common", "HttpRequestTimeout", "0"),
            ("MqttPvInverter", "StaleTimeoutSeconds", "4"),
            ("MqttPvInverter", "ZeroFeedinScaleStep", "0"),
            ("MqttPvInverter", "ZeroFeedinScaleStep", "1.01"),
            ("MqttPvInverter", "ZeroFeedinDistance", "-1"),
            ("MqttPvInverter", "ZeroFeedinStartSoc", "-1"),
            ("MqttPvInverter", "ZeroFeedinStartSoc", "101"),
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

    def test_grid_setpoint_bounds_must_contain_default(self):
        cases = (
            ("100", "0", "50"),
            ("0", "100", "101"),
        )
        for minimum, maximum, default in cases:
            with self.subTest(minimum=minimum, maximum=maximum, default=default):
                app = self._app_with_sample_config()
                app.config["Common"]["GridSetPointMinW"] = minimum
                app.config["Common"]["GridSetPointMaxW"] = maximum
                app.config["Common"]["DefaultPowerSetPoint"] = default
                with patch.object(self.es_ess, "c") as critical:
                    with self.assertRaises(SystemExit):
                        app._validateConfigValues()

                self.assertTrue(
                    any(
                        "GridSetPoint" in call.args[1]
                        or "DefaultPowerSetPoint" in call.args[1]
                        for call in critical.call_args_list
                    )
                )

    def test_tls_verification_modes_are_validated(self):
        app = self._app_with_sample_config()
        app.config["Mqtt"]["SslVerification"] = "sometimes"
        with patch.object(self.es_ess, "c") as critical:
            with self.assertRaises(SystemExit):
                app._validateConfigValues()
        self.assertIn("SslVerification", critical.call_args.args[1])

        app = self._app_with_sample_config()
        app.config["Mqtt"]["SslEnabled"] = "true"
        app.config["Mqtt"]["SslVerification"] = "CertificateOnly"
        app.config["Mqtt"]["SslCaFile"] = ""
        with patch.object(self.es_ess, "c") as critical:
            with self.assertRaises(SystemExit):
                app._validateConfigValues()
        self.assertIn("SslCaFile", critical.call_args.args[1])

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

    def test_configuration_processing_restricts_active_config_permissions(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            config_path = tmp_path / "config.ini"
            config_path.write_text(
                (ROOT / "config.sample.ini").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            app = self.es_ess.esESS.__new__(self.es_ess.esESS)

            with patch.object(
                self.es_ess.os.path,
                "realpath",
                return_value=str(tmp_path / "es-ESS.py"),
            ), patch.object(self.es_ess.os, "chmod") as chmod:
                app._validateConfiguration()

            self.assertTrue(
                any(
                    Path(call.args[0]) == config_path and call.args[1] == 0o600
                    for call in chmod.call_args_list
                )
            )

    def test_backup_config_is_restricted_to_owner(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            app = self.es_ess.esESS.__new__(self.es_ess.esESS)
            app.config = configparser.ConfigParser()
            app.config.read_dict({"Common": {"ConfigVersion": "10"}})
            backup_path = tmp_path / "config.ini.v10.backup"

            with patch.object(
                self.es_ess.os.path,
                "realpath",
                return_value=str(tmp_path / "es-ESS.py"),
            ), patch.object(self.es_ess.os, "chmod") as chmod:
                app._backupConfig()

            self.assertTrue(backup_path.exists())
            chmod.assert_called_once()
            called_path, called_mode = chmod.call_args.args
            self.assertEqual(Path(called_path), backup_path)
            self.assertEqual(called_mode, 0o600)


if __name__ == "__main__":
    unittest.main()
