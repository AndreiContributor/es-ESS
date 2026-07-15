"""Hardware-free tests for the read-only es-ESS daily report."""

import ast
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "es-ess-daily-report.py"

SPEC = importlib.util.spec_from_file_location("es_ess_daily_report", SCRIPT)
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


class EsEssDailyReportTests(unittest.TestCase):
    target_date = "2026-07-15"

    @staticmethod
    def _line(clock, message, level="APP_DEBUG", millis="000"):
        return (
            f"2026-07-15 {clock},{millis} {level} "
            f"[TPt_0|test.audit] {message}\n"
        )

    def _records(self, lines):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "current.log"
            path.write_text("".join(lines), encoding="utf-8")
            records, total = AUDIT.load_log_records(path, self.target_date)
        self.assertEqual(total, len(lines))
        return records

    def _run(self, lines, settings=None, partial=False):
        records = self._records(lines)
        audit_input = AUDIT.AuditInput(
            target_date=self.target_date,
            log_file="current.log",
            config_file="config.ini",
            total_log_lines=len(lines),
            dated_log_lines=len(records),
            first_timestamp=records[0].timestamp.isoformat() if records else None,
            last_timestamp=records[-1].timestamp.isoformat() if records else None,
            partial_window=partial,
            analysis_cutoff=(
                records[-1].timestamp.isoformat() if records else None
            ),
            full_window_available_at=(
                "2026-07-16T00:00:00" if partial else None
            ),
        )
        return AUDIT.EsEssDailyReport(
            records,
            settings or AUDIT.AuditSettings(log_level="APP_DEBUG"),
            audit_input,
        ).run()

    @staticmethod
    def _statuses(result, check):
        return [finding.status for finding in result.findings if finding.check == check]

    @staticmethod
    def _audit(records):
        return AUDIT.EsEssDailyReport(
            records,
            AUDIT.AuditSettings(log_level="APP_DEBUG"),
            AUDIT.AuditInput(
                target_date="2026-07-15",
                log_file="current.log",
                config_file="config.ini",
            ),
        )

    def test_parser_filters_date_and_preserves_traceback_continuation(self):
        lines = [
            "2026-07-14 23:59:59,999 INFO old day\n",
            self._line("00:00:01", "Exception", "ERROR"),
            "Traceback (most recent call last):\n",
            "  File \"example.py\", line 1\n",
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "current.log"
            path.write_text("".join(lines), encoding="utf-8")
            records, total = AUDIT.load_log_records(path, self.target_date)

        self.assertEqual(total, 4)
        self.assertEqual(len(records), 1)
        self.assertIn("Traceback", records[0].message)

    def test_transient_zero_allowance_recovers_inside_grace(self):
        lines = [
            self._line(
                "08:00:00",
                "ServiceMessage: Assigned 5000W to Fronius Wattpilot - Charging 3 phase (35, Wattpilot)",
            ),
            self._line(
                "08:00:05",
                "ServiceMessage: Assigned 0W to Fronius Wattpilot - Charging 3 phase (35, Wattpilot)",
            ),
            self._line(
                "08:00:06",
                "ServiceMessage: EV allowance fell below the usable minimum. Waiting up to 30s for a refreshed distributor allowance before reducing phase or stopping.",
            ),
            self._line(
                "08:00:20",
                "ServiceMessage: Assigned 5200W to Fronius Wattpilot - Charging 3 phase (35, Wattpilot)",
            ),
            self._line("08:00:21", "Adjusting charge current to 7A on 3-phase.", "INFO"),
            self._line(
                "08:00:25", "L1/L2/L3/Bat/Soc/Feedin is -20/-15/-10/100/90/45", "INFO"
            ),
        ]
        result = self._run(
            lines,
            AUDIT.AuditSettings(
                log_level="APP_DEBUG",
                allowance_drop_grace_seconds=30,
            ),
        )

        self.assertIn("PASS", self._statuses(result, "allowance drop grace"))
        self.assertNotIn("FAIL", self._statuses(result, "allowance drop grace"))
        self.assertEqual(result.metrics["zero_watt_three_phase_assignments"], 1)

    def test_premature_phase_down_before_grace_is_failure(self):
        lines = [
            self._line(
                "09:00:00",
                "ServiceMessage: Assigned 0W to Fronius Wattpilot - Charging 3 phase (35, Wattpilot)",
            ),
            self._line(
                "09:00:01",
                "ServiceMessage: EV allowance fell below the usable minimum. Waiting up to 30s for a refreshed distributor allowance before reducing phase or stopping.",
            ),
            self._line(
                "09:00:10",
                "ServiceMessage: PV allowance dropped below the three-phase threshold. Switching to 1-phase before applying battery-assist or stop logic.",
            ),
            self._line(
                "09:00:15",
                "ServiceMessage: Wattpilot phase telemetry confirmed 1-phase charging.",
            ),
            self._line("09:00:40", "Wattpilot Modelstatus: NotCharging"),
        ]
        result = self._run(
            lines,
            AUDIT.AuditSettings(
                log_level="APP_DEBUG",
                allowance_drop_grace_seconds=30,
            ),
        )

        self.assertIn("FAIL", self._statuses(result, "allowance drop grace"))
        self.assertEqual(result.overall, "ANOMALY")

    def test_atomic_zero_followed_by_one_phase_without_grace_is_failure(self):
        lines = [
            self._line(
                "09:30:00",
                "ServiceMessage: Assigned 0W to Fronius Wattpilot - Charging 3 phase (35, Wattpilot)",
            ),
            self._line(
                "09:30:05",
                "ServiceMessage: Assigned 3600W to Fronius Wattpilot - Charging 1 phase (35, Wattpilot)",
            ),
        ]
        result = self._run(
            lines,
            AUDIT.AuditSettings(
                log_level="APP_DEBUG",
                allowance_drop_grace_seconds=30,
            ),
        )

        self.assertIn("FAIL", self._statuses(result, "allowance drop grace"))

    def test_sustained_zero_phase_down_at_grace_is_valid(self):
        lines = [
            self._line(
                "10:00:00",
                "ServiceMessage: Assigned 0W to Fronius Wattpilot - Charging 3 phase (35, Wattpilot)",
            ),
            self._line(
                "10:00:01",
                "ServiceMessage: EV allowance fell below the usable minimum. Waiting up to 30s for a refreshed distributor allowance before reducing phase or stopping.",
            ),
            self._line(
                "10:00:31",
                "ServiceMessage: PV allowance dropped below the three-phase threshold. Switching to 1-phase before applying battery-assist or stop logic.",
            ),
            self._line(
                "10:00:36",
                "ServiceMessage: Wattpilot phase telemetry confirmed 1-phase charging.",
            ),
            self._line("10:00:45", "Wattpilot Modelstatus: NotCharging"),
        ]
        result = self._run(
            lines,
            AUDIT.AuditSettings(
                log_level="APP_DEBUG",
                allowance_drop_grace_seconds=30,
            ),
        )

        self.assertIn("PASS", self._statuses(result, "allowance drop grace"))
        self.assertNotIn("FAIL", self._statuses(result, "allowance drop grace"))
        self.assertIn("PASS", self._statuses(result, "phase switching"))

    def test_grid_safety_override_can_act_before_allowance_grace(self):
        lines = [
            self._line(
                "11:00:00",
                "ServiceMessage: Assigned 0W to Fronius Wattpilot - Charging 3 phase (35, Wattpilot)",
            ),
            self._line(
                "11:00:01",
                "ServiceMessage: EV allowance fell below the usable minimum. Waiting up to 30s for a refreshed distributor allowance before reducing phase or stopping.",
            ),
            self._line(
                "11:00:08",
                "ServiceMessage: Grid import guard triggered, but PV supports 1-phase. Switching to 1-phase before stopping.",
            ),
            self._line(
                "11:00:12",
                "ServiceMessage: Wattpilot phase telemetry confirmed 1-phase charging.",
            ),
            self._line("11:00:40", "Wattpilot Modelstatus: NotCharging"),
        ]
        result = self._run(
            lines,
            AUDIT.AuditSettings(
                log_level="APP_DEBUG",
                allowance_drop_grace_seconds=30,
            ),
        )

        self.assertNotIn("FAIL", self._statuses(result, "allowance drop grace"))

    def test_current_and_battery_assist_limit_violations_fail(self):
        lines = [
            self._line(
                "12:00:00",
                "ServiceMessage: Assigned 5000W to Fronius Wattpilot - Charging 1 phase (35, Wattpilot)",
            ),
            self._line("12:00:01", "Adjusting charge current to 17A on 1-phase.", "INFO"),
            self._line(
                "12:00:02", "ServiceMessage: Battery assist active: 1200W shortfall for 10s."
            ),
        ]
        result = self._run(
            lines,
            AUDIT.AuditSettings(
                log_level="APP_DEBUG",
                max_current_per_phase=16,
                battery_assist_max_shortfall_w=1000,
            ),
        )

        self.assertIn("FAIL", self._statuses(result, "current limits"))
        self.assertIn("FAIL", self._statuses(result, "battery assist"))
        self.assertEqual(result.overall, "ANOMALY")

    def test_early_phase_up_and_low_allowance_fail(self):
        lines = [
            self._line(
                "13:00:00",
                "ServiceMessage: Assigned 4000W to Fronius Wattpilot - Charging 1 phase (35, Wattpilot)",
            ),
            self._line(
                "13:00:01",
                "3-phase PV threshold reached; waiting for stable phase-up allowance (0/600s).",
            ),
            self._line(
                "13:01:40", "ServiceMessage: Switching to 3-phase from PV surplus."
            ),
            self._line(
                "13:01:45",
                "ServiceMessage: Wattpilot phase telemetry confirmed 3-phase charging.",
            ),
        ]
        result = self._run(
            lines,
            AUDIT.AuditSettings(
                log_level="APP_DEBUG",
                three_phase_start_w=4500,
                min_phase_switch_seconds=600,
            ),
        )

        self.assertIn("FAIL", self._statuses(result, "phase timing"))
        self.assertIn("FAIL", self._statuses(result, "phase threshold"))

    def test_sustained_grid_import_without_guard_fails(self):
        lines = []
        for clock in ("14:00:00", "14:00:05", "14:00:10", "14:00:15"):
            lines.extend(
                [
                    self._line(
                        clock,
                        "ServiceMessage: Assigned 5000W to Fronius Wattpilot - Charging 3 phase (35, Wattpilot)",
                    ),
                    self._line(
                        clock,
                        "L1/L2/L3/Bat/Soc/Feedin is 150/100/100/0/90/-350",
                        "INFO",
                        "100",
                    ),
                ]
            )
        result = self._run(
            lines,
            AUDIT.AuditSettings(
                log_level="APP_DEBUG",
                grid_import_stop_w=300,
                grid_import_stop_seconds=15,
            ),
        )

        self.assertIn("FAIL", self._statuses(result, "grid import"))

    def test_runtime_error_fails_and_no_charge_is_not_observed(self):
        lines = [
            self._line("15:00:00", "Exception in worker", "ERROR"),
            "Traceback (most recent call last):\n",
        ]
        result = self._run(lines)

        self.assertIn("FAIL", self._statuses(result, "runtime errors"))
        self.assertIn("NOT_OBSERVED", self._statuses(result, "charging"))

    def test_unvalidated_wattpilot_firmware_is_a_runtime_failure(self):
        result = self._run(
            [
                self._line(
                    "15:30:00",
                    "Wattpilot firmware compatibility not confirmed. Expected 42.5, "
                    "received 43.0. All es-ESS Wattpilot commands are blocked.",
                    "WARNING",
                )
            ]
        )

        self.assertIn("FAIL", self._statuses(result, "runtime errors"))

    def test_blocked_authority_does_not_fail_for_passive_charge_status(self):
        result = self._run(
            [
                self._line(
                    "15:40:00",
                    "ServiceMessage: Ready: select Auto on GX/VRM after native controls "
                    "are disabled.",
                    "WARNING",
                ),
                self._line("15:40:05", "Wattpilot Modelstatus: Charging"),
            ]
        )

        self.assertIn("PASS", self._statuses(result, "command authority"))
        self.assertNotIn("FAIL", self._statuses(result, "command authority"))

    def test_auto_control_action_while_authority_is_blocked_fails(self):
        result = self._run(
            [
                self._line(
                    "15:50:00",
                    "ServiceMessage: Blocked: disable Use PV surplus in Solar.wattpilot.",
                    "WARNING",
                ),
                self._line(
                    "15:50:05", "Adjusting charge current to 8A on 1-phase.", "INFO"
                ),
            ]
        )

        self.assertIn("FAIL", self._statuses(result, "command authority"))

    def test_info_logging_is_incomplete_not_false_pass(self):
        lines = [self._line("16:00:00", "Initialization completed", "INFO")]
        result = self._run(lines, AUDIT.AuditSettings(log_level="INFO"))

        self.assertEqual(result.overall, "INCOMPLETE")
        self.assertIn("WARN", self._statuses(result, "log coverage"))

    def test_config_reader_uses_values_without_exposing_unrelated_secrets(self):
        config = """
[Common]
LogLevel=APP_DEBUG
MqttPassword=secret-value

[Services]
SolarOverheadDistributor=true
FroniusWattpilot=true
NoBatToEV=false

[FroniusWattpilot]
MinCurrentPerPhase=6
MaxCurrentPerPhase=16
ThreePhasePvSurplusStartW=4500
ThreePhasePvSurplusStopW=4100
MinOnOffSeconds=60
MinPhaseSwitchSeconds=600
AllowanceFreshSeconds=15
AllowanceDropGraceSeconds=30
BatteryAssistEnabled=true
BatteryAssistMaxSeconds=600
BatteryAssistMaxShortfallW=1000
AllowGridCharging=false
GridImportPositive=true
GridImportStopW=300
GridImportStopSeconds=15
StartupGraceSeconds=60
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text(config, encoding="utf-8")
            settings, warnings = AUDIT.load_settings(path)

        self.assertEqual(warnings, [])
        self.assertEqual(settings.allowance_drop_grace_seconds, 30)
        self.assertNotIn("secret-value", json.dumps(AUDIT.asdict(settings)))

    def test_default_documentation_values_are_not_treated_as_service_flags(self):
        config = """
[DEFAULT]
devComment1=This is documentation, not a boolean service flag.

[Common]
LogLevel=APP_DEBUG

[Services]
SolarOverheadDistributor=true
FroniusWattpilot=true
NoBatToEV=false
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text(config, encoding="utf-8")
            settings, warnings = AUDIT.load_settings(path)

        self.assertNotIn(
            "[Services] devcomment1 is not a valid boolean", warnings
        )
        self.assertEqual(
            settings.enabled_services,
            ["froniuswattpilot", "solaroverheaddistributor"],
        )

    def test_json_result_is_serializable(self):
        result = self._run(
            [
                self._line(
                    "17:00:00",
                    "ServiceMessage: Assigned 5000W to Fronius Wattpilot - Charging 1 phase (35, Wattpilot)",
                )
            ]
        )
        payload = json.loads(json.dumps(result.to_dict()))
        self.assertEqual(payload["schema"], 3)
        self.assertEqual(payload["inputs"]["target_date"], self.target_date)

    def test_partial_json_contains_coverage_contract(self):
        result = self._run(
            [self._line("17:10:00", "heartbeat")], partial=True
        )
        payload = result.to_dict()
        self.assertTrue(payload["inputs"]["partial_window"])
        self.assertEqual(
            payload["inputs"]["full_window_available_at"],
            "2026-07-16T00:00:00",
        )
        self.assertIn("evidence_span_percent", payload["inputs"])

    def test_script_has_no_production_control_or_network_dependencies(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        forbidden = {
            "dbus",
            "paho",
            "requests",
            "socket",
            "vedbus",
            "websocket",
        }
        self.assertEqual(imported & forbidden, set())

    def test_readonly_command_allowlist_rejects_writes_and_service_control(self):
        for command in (
            ["svc", "-d", "/service/es-ESS"],
            ["dbus", "-y", AUDIT.DEFAULT_WATTPILOT_DBUS_SERVICE, "/Mode", "SetValue"],
            ["python", "FroniusWattpilot.py"],
        ):
            ok, message = AUDIT._run_readonly_command(command)
            self.assertFalse(ok)
            self.assertIn("read-only allowlist", message)

    def test_readonly_command_allowlist_invokes_only_getvalue(self):
        completed = mock.Mock(returncode=0, stdout="1\n", stderr="")
        runner = mock.Mock(return_value=completed)
        ok, value = AUDIT._run_readonly_command(
            [
                "dbus",
                "-y",
                AUDIT.DEFAULT_WATTPILOT_DBUS_SERVICE,
                "/Connected",
                "GetValue",
            ],
            runner=runner,
        )
        self.assertTrue(ok)
        self.assertEqual(value, "1")
        self.assertEqual(runner.call_args.args[0][-1], "GetValue")

    def test_timezone_query_allowlist_accepts_only_exact_settings_path(self):
        completed = mock.Mock(
            returncode=0, stdout="'Europe/Bucharest'\n", stderr=""
        )
        runner = mock.Mock(return_value=completed)

        ok, value = AUDIT._run_readonly_command(
            [
                "dbus",
                "-y",
                AUDIT.DEFAULT_SETTINGS_DBUS_SERVICE,
                AUDIT.VENUS_TIMEZONE_DBUS_PATH,
                "GetValue",
            ],
            runner=runner,
        )
        rejected, message = AUDIT._run_readonly_command(
            [
                "dbus",
                "-y",
                AUDIT.DEFAULT_SETTINGS_DBUS_SERVICE,
                "/Settings/CGwacs/BatteryLife/State",
                "GetValue",
            ],
            runner=runner,
        )

        self.assertTrue(ok)
        self.assertEqual(value, "Europe/Bucharest")
        self.assertFalse(rejected)
        self.assertIn("read-only allowlist", message)

    def test_report_timezone_uses_bounded_venus_setting_query(self):
        completed = mock.Mock(
            returncode=0, stdout="'Europe/Bucharest'\n", stderr=""
        )
        runner = mock.Mock(return_value=completed)
        fixed_timezone = timezone(timedelta(hours=3))
        zone_factory = mock.Mock(return_value=fixed_timezone)

        name, resolved_timezone, warning = AUDIT.resolve_report_timezone(
            runner=runner,
            which=lambda command: "/usr/bin/dbus" if command == "dbus" else None,
            zone_factory=zone_factory,
        )

        self.assertEqual(name, "Europe/Bucharest")
        self.assertIs(resolved_timezone, fixed_timezone)
        self.assertIsNone(warning)
        zone_factory.assert_called_once_with("Europe/Bucharest")
        self.assertEqual(runner.call_args.kwargs["timeout"], 2)

    def test_progress_reporter_renders_stages_and_completion_to_its_stream(self):
        stream = io.StringIO()
        progress = AUDIT.ProgressReporter(enabled=True, stream=stream)
        progress.update(1, "Loading logs", 1, 2)
        progress.finish()
        rendered = stream.getvalue()
        self.assertIn("Loading logs", rendered)
        self.assertIn("100.0% Report ready", rendered)

    def test_progress_stream_does_not_contaminate_json_stdout(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        progress = AUDIT.ProgressReporter(enabled=True, stream=stderr)
        progress.update(2, "Validating evidence")
        stdout.write(json.dumps({"schema": AUDIT.SCHEMA_VERSION}))
        progress.finish()
        self.assertEqual(
            json.loads(stdout.getvalue())["schema"], AUDIT.SCHEMA_VERSION
        )
        self.assertIn("Validating evidence", stderr.getvalue())

    def test_no_progress_argument_is_available_for_automation(self):
        args = AUDIT.parse_args(["--date", "today", "--no-progress"])
        self.assertTrue(args.no_progress)

    def test_log_loader_reports_byte_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "current.log"
            path.write_text(
                "".join(
                    f"2026-07-15 12:00:{index % 60:02d},000 APP_DEBUG line {index}\n"
                    for index in range(AUDIT.LOG_PROGRESS_LINE_INTERVAL + 1)
                ),
                encoding="utf-8",
            )
            updates = []
            AUDIT.load_log_window(
                [path],
                datetime(2026, 7, 15),
                datetime(2026, 7, 16),
                progress_callback=lambda current, total, name: updates.append(
                    (current, total, name)
                ),
            )
        self.assertGreaterEqual(len(updates), 2)
        self.assertEqual(updates[-1][0], updates[-1][1])
        self.assertEqual(updates[-1][2], "current.log")

    def test_snapshot_stops_after_three_consecutive_command_timeouts(self):
        calls = []

        def runner(args, **_kwargs):
            calls.append(args)
            if args[0] == "svstat":
                return mock.Mock(returncode=0, stdout="/service/es-ESS: up\n", stderr="")
            raise AUDIT.subprocess.TimeoutExpired(args, 2)

        updates = []
        snapshot = AUDIT.capture_current_snapshot(
            runner=runner,
            which=lambda _name: "/bin/tool",
            progress_callback=lambda current, total, detail: updates.append(
                (current, total, detail)
            ),
        )
        self.assertEqual(len(calls), 4)
        self.assertTrue(
            any("remaining D-Bus snapshot paths skipped" in note for note in snapshot.notes)
        )
        self.assertEqual(set(snapshot.dbus_values.values()), {"unavailable"})
        self.assertEqual(updates[-1][0], updates[-1][1])

    def test_human_session_current_adjustments_are_compact(self):
        summary = AUDIT._summarize_current_adjustments(
            [13, 14] + [16] * 200 + [8, 6, 8, 6]
        )
        self.assertIn("206 samples", summary)
        self.assertIn("range=6..16 A", summary)
        self.assertNotIn("16, 16, 16", summary)

    def test_discovers_current_and_standard_rotated_logs_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "current.log",
                "current.log.2026-07-14",
                "current.log.2026-07-15",
                "current.log.backup",
            ):
                (root / name).write_text("", encoding="utf-8")
            discovered = AUDIT.discover_log_files(root / "current.log")
        self.assertEqual(
            [path.name for path in discovered],
            ["current.log", "current.log.2026-07-14", "current.log.2026-07-15"],
        )

    def test_load_window_crosses_midnight_and_deduplicates_rotation_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = "2026-07-15 00:00:00,000 INFO duplicate\n"
            (root / "current.log.2026-07-14").write_text(
                "2026-07-14 23:59:59,000 INFO before\n" + duplicate,
                encoding="utf-8",
            )
            (root / "current.log").write_text(
                duplicate + "2026-07-15 00:00:01,000 INFO after\n",
                encoding="utf-8",
            )
            records, total = AUDIT.load_log_window(
                [root / "current.log.2026-07-14", root / "current.log"],
                datetime(2026, 7, 14, 23, 59, 58),
                datetime(2026, 7, 15, 0, 0, 2),
            )
        self.assertEqual(total, 4)
        self.assertEqual([record.message for record in records], ["before", "duplicate", "after"])

    def test_offset_timestamp_orders_repeated_dst_hour_by_actual_instant(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "current.log"
            path.write_text(
                "2026-10-25 03:30:00,000 (UTC+3) APP_DEBUG summer occurrence\n"
                "2026-10-25 03:15:00,000 (UTC+2) APP_DEBUG winter occurrence\n",
                encoding="utf-8",
            )
            records, total = AUDIT.load_log_window(
                [path],
                datetime(2026, 10, 25, tzinfo=timezone.utc),
                datetime(2026, 10, 26, tzinfo=timezone.utc),
            )

        self.assertEqual(total, 2)
        self.assertEqual(
            [record.message for record in records],
            ["summer occurrence", "winter occurrence"],
        )
        self.assertEqual(
            (records[1].timestamp - records[0].timestamp).total_seconds(), 45 * 60
        )

    def test_fast_log_parser_preserves_offset_and_millisecond_contract(self):
        line = (
            "2026-07-15 18:42:10,123456 (UTC+5:30) APP_DEBUG "
            "[TPt_0|test] diagnostic"
        )

        parsed = AUDIT.parse_log_line(line, legacy_timezone=timezone.utc)

        self.assertIsNotNone(parsed)
        timestamp, level, message = parsed
        self.assertEqual(
            timestamp,
            datetime(
                2026,
                7,
                15,
                18,
                42,
                10,
                123000,
                tzinfo=timezone(timedelta(hours=5, minutes=30)),
            ),
        )
        self.assertEqual(level, "APP_DEBUG")
        self.assertEqual(message, "[TPt_0|test] diagnostic")

    def test_grid_correlation_uses_timestamp_index_without_scanning_charge_records(self):
        class IndexedOnly(list):
            def __iter__(self):
                raise AssertionError("charge records must not be scanned per grid sample")

        timestamp = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        record = AUDIT.LogRecord(timestamp, "APP_DEBUG", "charging", "charging")
        audit = self._audit([record])
        audit.charge_records = IndexedOnly([record])
        audit._charge_timestamps = IndexedOnly([timestamp])

        self.assertTrue(audit._charging_near(timestamp + timedelta(seconds=10)))
        self.assertFalse(audit._charging_near(timestamp + timedelta(seconds=11)))

    def test_session_build_uses_stop_index_without_rescanning_full_log(self):
        class IndexedOnly(list):
            def __iter__(self):
                raise AssertionError("full log must not be rescanned per charge sample")

        start = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        first = AUDIT.LogRecord(start, "APP_DEBUG", "charging", "first charge")
        second = AUDIT.LogRecord(
            start + timedelta(seconds=5), "APP_DEBUG", "charging", "second charge"
        )
        stop = AUDIT.LogRecord(
            start + timedelta(seconds=10),
            "APP_DEBUG",
            "Stopping Auto/Eco charging",
            "stop",
        )
        audit = self._audit([first, second, stop])
        audit.records = IndexedOnly([first, second, stop])
        audit.charge_records = [first, second]
        audit._charge_timestamps = [first.timestamp, second.timestamp]
        audit._stop_records = [stop]
        audit._stop_timestamps = [stop.timestamp]

        sessions = audit.build_sessions()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].end, stop.timestamp.isoformat())
        self.assertEqual(sessions[0].stop_reason, "insufficient allowance")

    def test_malformed_and_truncated_log_input_is_tolerated_but_not_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "current.log"
            path.write_text(
                "not a dated log line\n"
                "2026-07-15 12:00:00,000 INFO valid record\n"
                "truncated continuation without another timestamp\n",
                encoding="utf-8",
            )
            records, total = AUDIT.load_log_records(path, self.target_date)
        self.assertEqual(total, 3)
        self.assertEqual(len(records), 1)
        self.assertIn("truncated continuation", records[0].message)
        self.assertIsNotNone(
            AUDIT.coverage_problem(
                records,
                datetime(2026, 7, 15),
                datetime(2026, 7, 16),
                datetime(2026, 7, 17),
            )
        )

    def test_window_resolution_defaults_to_yesterday_and_requires_24_hours(self):
        now = datetime(2026, 7, 15, 12, 0, 0)
        label, start, end, window_type = AUDIT.resolve_window(None, None, now)
        self.assertEqual(label, "2026-07-14")
        self.assertEqual(start, datetime(2026, 7, 14))
        self.assertEqual(end, datetime(2026, 7, 15))
        self.assertEqual(window_type, "calendar-day")
        with self.assertRaises(ValueError):
            AUDIT.resolve_window(None, 23.9, now)

    def test_today_window_uses_venus_timezone_when_os_clock_is_utc(self):
        venus_timezone = timezone(timedelta(hours=3))
        os_now = datetime(2026, 7, 15, 18, 11, tzinfo=timezone.utc)

        label, start, end, window_type = AUDIT.resolve_window(
            "today",
            None,
            now=os_now,
            local_timezone=venus_timezone,
        )

        self.assertEqual(label, "2026-07-15")
        self.assertEqual(start, datetime(2026, 7, 15, tzinfo=venus_timezone))
        self.assertEqual(end, datetime(2026, 7, 16, tzinfo=venus_timezone))
        self.assertEqual(window_type, "calendar-day")

    def test_large_irrelevant_record_set_bypasses_event_regexes(self):
        start = datetime(2026, 7, 15, tzinfo=timezone.utc)
        records = [
            AUDIT.LogRecord(
                start + timedelta(milliseconds=index),
                "APP_DEBUG",
                "routine heartbeat",
                "routine heartbeat",
            )
            for index in range(20000)
        ]
        audit = self._audit(records)
        regex_names = (
            "ALLOWANCE_RE",
            "GRID_RE",
            "CURRENT_RE",
            "ASSIST_RE",
            "GRACE_RE",
            "PHASE_UP_WAIT_RE",
            "PHASE_CONFIRM_RE",
            "START_RE",
            "MODEL_CHARGING_RE",
            "RAW_COMMAND_RE",
            "RARE_ENTER_RE",
            "RARE_EXIT_RE",
        )
        spies = {}
        with contextlib.ExitStack() as stack:
            for name in regex_names:
                spy = mock.Mock(wraps=getattr(AUDIT, name))
                spies[name] = spy
                stack.enter_context(mock.patch.object(AUDIT, name, spy))
            audit.collect()

        self.assertTrue(all(spy.search.call_count == 0 for spy in spies.values()))

    def test_coverage_requires_both_full_day_boundaries(self):
        start = datetime(2026, 7, 14)
        end = start + timedelta(days=1)
        record = AUDIT.LogRecord(start + timedelta(hours=1), "INFO", "late", "late")
        problem = AUDIT.coverage_problem(
            [record], start, end, datetime(2026, 7, 15, 12)
        )
        self.assertIn("first record", problem)

    def test_coverage_metadata_reports_evidence_span_against_elapsed_day(self):
        start = datetime(2026, 7, 15)
        records = [
            AUDIT.LogRecord(start + timedelta(hours=2), "APP_DEBUG", "a", "a"),
            AUDIT.LogRecord(start + timedelta(hours=8), "APP_DEBUG", "b", "b"),
        ]
        evidence, elapsed, percent = AUDIT.calculate_coverage_metadata(
            records, start, start + timedelta(hours=10)
        )
        self.assertEqual(evidence, 6 * 3600)
        self.assertEqual(elapsed, 10 * 3600)
        self.assertEqual(percent, 60.0)

    def test_partial_today_runs_and_prints_period_coverage(self):
        now = datetime.now()
        first = now - timedelta(minutes=2)
        if first.date() != now.date():
            first = now
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.ini"
            config.write_text("[Common]\nLogLevel=APP_DEBUG\n", encoding="utf-8")
            log = root / "current.log"
            log.write_text(
                f"{first:%Y-%m-%d %H:%M:%S},000 APP_DEBUG first evidence\n"
                f"{now:%Y-%m-%d %H:%M:%S},000 APP_DEBUG latest evidence\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = AUDIT.main(
                    [
                        "--config",
                        str(config),
                        "--log-file",
                        str(log),
                        "--date",
                        "today",
                        "--no-current-snapshot",
                    ]
                )
        report = output.getvalue()
        self.assertEqual(exit_code, AUDIT.EXIT_INCOMPLETE)
        self.assertNotIn("Daily report stopped", report)
        self.assertIn("Window status: PARTIAL", report)
        self.assertIn("Evidence period:", report)
        self.assertIn("span coverage:", report)
        self.assertIn("Processing time: log load", report)
        self.assertIn("Full calendar-day report available after:", report)
        self.assertIn("[WARN] partial calendar day", report)

    def test_main_uses_resolved_venus_timezone_for_today_window(self):
        venus_timezone = timezone(timedelta(hours=3))
        now = datetime.now(venus_timezone)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.ini"
            config.write_text("[Common]\nLogLevel=APP_DEBUG\n", encoding="utf-8")
            log = root / "current.log"
            log.write_text(
                f"{now:%Y-%m-%d %H:%M:%S},000 (UTC+3) APP_DEBUG current evidence\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with mock.patch.object(
                AUDIT,
                "resolve_report_timezone",
                return_value=("Europe/Bucharest", venus_timezone, None),
            ), contextlib.redirect_stdout(output):
                exit_code = AUDIT.main(
                    [
                        "--config",
                        str(config),
                        "--log-file",
                        str(log),
                        "--date",
                        "today",
                        "--no-current-snapshot",
                    ]
                )

        report = output.getvalue()
        self.assertEqual(exit_code, AUDIT.EXIT_INCOMPLETE)
        self.assertIn("Report timezone:  Europe/Bucharest", report)
        self.assertIn(
            f"Requested period: {now:%Y-%m-%d}T00:00:00+03:00",
            report,
        )

    def test_partial_today_anomaly_overrides_incomplete_ceiling(self):
        result = self._run(
            [
                self._line("22:00:00", "heartbeat"),
                self._line("22:00:01", "worker failed", "ERROR"),
            ],
            partial=True,
        )
        self.assertEqual(result.overall, "ANOMALY")

    def test_main_stops_before_log_processing_when_app_debug_is_not_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.ini"
            config.write_text("[Common]\nLogLevel=INFO\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = AUDIT.main(["--config", str(config)])
        report = output.getvalue()
        self.assertEqual(exit_code, AUDIT.EXIT_INCOMPLETE)
        self.assertIn("Daily report stopped", report)
        self.assertIn("[Common] LogLevel=APP_DEBUG", report)
        self.assertIn("at least one complete day", report)

    def test_main_stops_when_config_is_debug_but_historical_debug_coverage_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.ini"
            config.write_text("[Common]\nLogLevel=APP_DEBUG\n", encoding="utf-8")
            log = root / "current.log"
            log.write_text(
                "2026-07-14 00:00:01,000 INFO start\n"
                "2026-07-14 23:59:59,000 INFO end\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = AUDIT.main(
                    [
                        "--config",
                        str(config),
                        "--log-file",
                        str(log),
                        "--date",
                        "2026-07-14",
                        "--no-current-snapshot",
                    ]
                )
        self.assertEqual(exit_code, AUDIT.EXIT_INCOMPLETE)
        self.assertIn("APP_DEBUG/DEBUG/TRACE records do not cover", output.getvalue())

    def test_prerequisite_json_is_machine_readable(self):
        payload = json.loads(AUDIT.render_prerequisite("missing evidence", "config.ini", True))
        self.assertEqual(payload["overall"], "INCOMPLETE")
        self.assertTrue(payload["stopped"])

    def test_rare_statuses_are_informational_when_not_observed(self):
        result = self._run(
            [
                self._line(
                    "18:00:00",
                    "ServiceMessage: Assigned 5000W to Fronius Wattpilot - Charging 1 phase (35, Wattpilot)",
                )
            ]
        )
        self.assertEqual(len(result.rare_statuses), 6)
        self.assertTrue(all(item.result == "NOT OBSERVED" for item in result.rare_statuses))
        self.assertNotEqual(result.overall, "INCOMPLETE")

    def test_all_rare_statuses_are_summarized_with_entry_and_exit(self):
        lines = []
        for offset, (status, name) in enumerate(AUDIT.RARE_STATUS_NAMES.items()):
            minute = offset * 2
            lines.append(
                self._line(
                    f"18:{minute:02d}:00",
                    f"Wattpilot special charging model status entered: model_status={status} name={name} mode=Auto selected_state=charging vehicle_connected=true charge_active=true command_authority_ok=true",
                )
            )
            lines.append(
                self._line(
                    f"18:{minute + 1:02d}:00",
                    f"Wattpilot special charging model status exited: model_status={status} name={name} next_model_status=3 observed_seconds=60",
                )
            )
        result = self._run(lines)
        self.assertEqual([item.occurrences for item in result.rare_statuses], [1] * 6)
        self.assertEqual(result.overall, "ATTENTION")

    def test_rare_status_unexpected_state_is_anomaly(self):
        result = self._run(
            [
                self._line(
                    "19:00:00",
                    "Wattpilot special charging model status entered: model_status=8 name=ChargingBecauseAutomaticStopTestLadung mode=Manual selected_state=manual_control vehicle_connected=true charge_active=true command_authority_ok=false",
                ),
                self._line(
                    "19:00:10",
                    "Wattpilot special charging model status exited: model_status=8 name=ChargingBecauseAutomaticStopTestLadung next_model_status=3 observed_seconds=10",
                ),
            ]
        )
        self.assertEqual(result.overall, "ANOMALY")

    def test_charging_session_contains_phase_current_and_stop_reason(self):
        result = self._run(
            [
                self._line(
                    "20:00:00",
                    "ServiceMessage: Assigned 5000W to Fronius Wattpilot - Charging 3 phase (35, Wattpilot)",
                ),
                self._line("20:00:05", "Adjusting charge current to 7A on 3-phase.", "INFO"),
                self._line("20:00:20", "Stopping EV charging because allowance is exhausted.", "INFO"),
            ]
        )
        self.assertEqual(len(result.sessions), 1)
        self.assertEqual(result.sessions[0].phases, [3])
        self.assertEqual(result.sessions[0].current_adjustments_a, [7])
        self.assertEqual(result.sessions[0].stop_reason, "controller stop")

    def test_session_reconstruction_distinguishes_auto_and_manual_boundaries(self):
        result = self._run(
            [
                self._line(
                    "20:10:00",
                    "Validated: es-ESS is the sole Auto/Eco command owner",
                    "INFO",
                ),
                self._line(
                    "20:10:10",
                    "ServiceMessage: Assigned 5000W to Fronius Wattpilot - Charging 1 phase (35, Wattpilot)",
                ),
                self._line("20:10:20", "Stopping EV charging because allowance is exhausted.", "INFO"),
                self._line(
                    "20:11:00",
                    "Manual mode selected. Releasing Auto/Eco command authority.",
                    "INFO",
                ),
                self._line(
                    "20:11:10",
                    "ServiceMessage: Assigned 4000W to Fronius Wattpilot - Charging 1 phase (35, Wattpilot)",
                ),
            ]
        )
        self.assertEqual([session.mode for session in result.sessions], ["Auto", "Manual"])

    def test_manual_raw_setvalue_command_is_anomaly(self):
        result = self._run(
            [
                self._line("20:30:00", "Manual mode selected. Releasing Auto/Eco command authority."),
                self._line("20:30:20", "setValue amp=8", "INFO"),
            ]
        )
        self.assertIn("FAIL", self._statuses(result, "Manual ownership"))

    def test_manual_release_command_is_allowed_immediately_after_boundary(self):
        result = self._run(
            [
                self._line("20:40:00", "Manual mode selected. Releasing Auto/Eco command authority."),
                self._line("20:40:05", "setValue psm=0", "INFO"),
            ]
        )
        self.assertNotIn("FAIL", self._statuses(result, "Manual ownership"))

    def test_snapshot_without_platform_commands_remains_read_only_and_optional(self):
        snapshot = AUDIT.capture_current_snapshot(which=lambda _name: None)
        self.assertFalse(snapshot.available)
        self.assertEqual(snapshot.service_state, "unavailable")
        self.assertTrue(snapshot.notes)

    def test_repeated_initialization_and_reconnect_events_require_attention(self):
        result = self._run(
            [
                self._line("21:40:00", "Initialization completed. es-ESS is up and running", "INFO"),
                self._line("21:40:30", "Wattpilot disconnected", "WARNING"),
                self._line("21:41:00", "Initialization completed. es-ESS is up and running", "INFO"),
                self._line("21:41:30", "Wattpilot disconnected", "WARNING"),
            ]
        )
        self.assertIn("ATTENTION", self._statuses(result, "service restarts"))
        self.assertIn("ATTENTION", self._statuses(result, "Wattpilot reconnects"))

    def test_stale_telemetry_and_battery_assist_limit_are_safety_attention(self):
        result = self._run(
            [
                self._line(
                    "21:45:00",
                    "Grid telemetry is missing, invalid, or stale. Stopping EV charging.",
                    "WARNING",
                ),
                self._line("21:45:05", "Battery assist time limit reached", "WARNING"),
            ]
        )
        self.assertEqual(result.overall, "ATTENTION")
        self.assertIn("ATTENTION", self._statuses(result, "safety interventions"))

    def test_no_grid_commissioning_profile_rejects_conflicting_services(self):
        settings = AUDIT.AuditSettings(
            log_level="APP_DEBUG",
            enabled_services=["FroniusWattpilot", "NoBatToEV"],
            allow_grid_charging=True,
        )
        result = self._run([self._line("21:50:00", "heartbeat")], settings)
        self.assertIn("FAIL", self._statuses(result, "commissioning profile"))

    def test_restart_inside_reconstructed_session_is_reported(self):
        result = self._run(
            [
                self._line(
                    "21:55:00",
                    "ServiceMessage: Assigned 5000W to Fronius Wattpilot - Charging 1 phase (35, Wattpilot)",
                ),
                self._line("21:55:20", "Initialization completed. es-ESS is up and running", "INFO"),
                self._line("21:55:40", "Adjusting charge current to 8A on 1-phase.", "INFO"),
            ]
        )
        self.assertEqual(len(result.sessions), 1)
        self.assertTrue(result.sessions[0].restart_during_session)

    def test_four_overall_results_are_reachable(self):
        good = self._run(
            [
                self._line(
                    "21:00:00",
                    "ServiceMessage: Assigned 5000W to Fronius Wattpilot - Charging 1 phase (35, Wattpilot)",
                ),
                self._line("21:00:01", "Adjusting charge current to 7A on 1-phase.", "INFO"),
            ]
        )
        attention = self._run(
            [self._line("21:10:00", "Grid import guard triggered. Stopping EV charging.", "WARNING")]
        )
        anomaly = self._run([self._line("21:20:00", "fatal worker error", "ERROR")])
        incomplete = self._run(
            [self._line("21:30:00", "Initialization completed", "INFO")],
            AUDIT.AuditSettings(log_level="INFO"),
        )
        self.assertEqual(good.overall, "GOOD")
        self.assertEqual(attention.overall, "ATTENTION")
        self.assertEqual(anomaly.overall, "ANOMALY")
        self.assertEqual(incomplete.overall, "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
