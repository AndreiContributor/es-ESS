"""Hardware-free tests for the read-only Wattpilot session capture."""

import importlib.util
import contextlib
import io
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "wattpilot-session-capture.py"


def _load_capture_module():
    spec = importlib.util.spec_from_file_location(
        "wattpilot_session_capture_under_test", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeProxy:
    def __init__(self, values):
        self.values = iter(values)
        self.method_requests = []

    def get_dbus_method(self, name, interface):
        self.method_requests.append((name, interface))

        def get_value():
            value = next(self.values)
            if isinstance(value, Exception):
                raise value
            return value

        return get_value


class FakeBus:
    def __init__(self, proxies):
        self.proxies = iter(proxies)
        self.get_object_calls = []

    def get_object(self, service, path):
        self.get_object_calls.append((service, path))
        return next(self.proxies)


class RepeatingProxy:
    def __init__(self, value):
        self.value = value

    def get_dbus_method(self, _name, _interface):
        return lambda: self.value


class MappingBus:
    def get_object(self, _service, path):
        values = {
            "/Connected": 1,
            "/ModeLiteral": "Auto",
            "/ControlStateLiteral": "Charging 1 phase",
            "/PhaseModeLiteral": "1 phase",
            "/StatusLiteral": "Charging",
            "/SetCurrent": 10,
            "/Current": 10,
            "/PvAllowance": 2400,
            "/Ac/Power": 2300,
            "/TelemetryHealthy": 1,
            "/CommandAuthorityOk": 1,
            "/SiteCurrentSource": "Shelly3EMGen3",
            "/SiteCurrentSourceConnected": 1,
            "/SiteCurrentSourceStatus": "Healthy",
            "/SiteCurrentSourceError": "",
            "/SiteCurrentSourceLastSampleAge": 0.2,
            "/Charger1PhaseMapping": "L3",
            "/SiteCurrentL1": 3.1,
            "/SiteCurrentL2": 4.2,
            "/SiteCurrentL3": 12.3,
            "/SiteCurrentAgeL1": 0.2,
            "/SiteCurrentAgeL2": 0.2,
            "/SiteCurrentAgeL3": 0.2,
            "/SiteHeadroomL1": 21.9,
            "/SiteHeadroomL2": 20.8,
            "/SiteHeadroomL3": 12.7,
            "/SiteAllowedCurrent": 12,
            "/SiteLimitingPhase": "L3",
            "/SiteCurrentTelemetryHealthy": 1,
            "/SiteCurrentGuardBlocked": 0,
            "/SiteCurrentGuardReason": "",
            "/SiteCurrentRecoveryElapsed": 60,
            "/GridImportGuardActive": 0,
            "/BatteryAssistActive": 0,
        }
        return RepeatingProxy(values.get(path, 100))


def sample(epoch, power, phase="1 phase", **values):
    return {
        "epoch": float(epoch),
        "read_seconds": values.pop("read_seconds", 0.05),
        "ev_power_w": power,
        "phase_mode": phase,
        "telemetry_healthy": values.pop("telemetry_healthy", 1),
        "command_authority_ok": values.pop("command_authority_ok", 1),
        "site_source_connected": values.pop("site_source_connected", 1),
        "site_current_telemetry_healthy": values.pop(
            "site_current_telemetry_healthy", 1
        ),
        "site_guard": values.pop("site_guard", 0),
        "grid_guard": values.pop("grid_guard", 0),
        "battery_assist": values.pop("battery_assist", 0),
        **values,
    }


class WattpilotSessionCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.capture = _load_capture_module()

    def test_dbus_reader_reuses_read_method_and_requests_only_get_value(self):
        proxy = FakeProxy([10, 11])
        bus = FakeBus([proxy])
        reader = self.capture.DbusReader(bus)

        self.assertEqual(reader.get("service", "/Current"), 10)
        self.assertEqual(reader.get("service", "/Current"), 11)

        self.assertEqual(bus.get_object_calls, [("service", "/Current")])
        self.assertEqual(
            proxy.method_requests,
            [("GetValue", self.capture.BUS_ITEM_INTERFACE)],
        )
        self.assertEqual(sum(reader.failures.values()), 0)

    def test_capture_has_no_statistics_module_dependency(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertNotIn("import statistics", source)
        self.assertEqual(self.capture.arithmetic_mean([1.0, 2.0, 6.0]), 3.0)
        with self.assertRaises(ValueError):
            self.capture.arithmetic_mean([])

    def test_dbus_reader_discards_failed_proxy_until_next_sample(self):
        failing = FakeProxy([RuntimeError("service restarted")])
        recovered = FakeProxy([12])
        bus = FakeBus([failing, recovered])
        reader = self.capture.DbusReader(bus)

        self.assertIsNone(reader.get("service", "/Current"))
        self.assertEqual(reader.get("service", "/Current"), 12)
        self.assertEqual(len(bus.get_object_calls), 2)
        self.assertEqual(reader.failures[("service", "/Current")], 1)

    def test_integration_uses_actual_timestamps_not_requested_interval(self):
        samples = [
            sample(0, 1000, ev_l1_power_w=1000),
            sample(40, 1000, ev_l1_power_w=1000),
            sample(80, 0, phase="Unknown", ev_l1_power_w=0),
        ]

        result = self.capture.analyze_samples(
            samples, requested_interval=10, max_gap_seconds=60
        )

        self.assertAlmostEqual(result["charging_seconds"], 60)
        self.assertAlmostEqual(result["energy_kwh"], 1 / 60)
        self.assertEqual(result["late_interval_count"], 2)
        self.assertEqual(result["skipped_gap_count"], 0)

    def test_long_sampling_gap_is_reported_and_not_extrapolated(self):
        samples = [sample(0, 1000), sample(40, 1000)]

        result = self.capture.analyze_samples(
            samples, requested_interval=10, max_gap_seconds=30
        )

        self.assertEqual(result["skipped_gap_count"], 1)
        self.assertEqual(result["skipped_gap_seconds"], 40)
        self.assertEqual(result["charging_seconds"], 0)
        self.assertEqual(result["energy_kwh"], 0)

    def test_phase_duration_uses_elapsed_time_and_splits_transition(self):
        samples = [
            sample(0, 1000, phase="1 phase"),
            sample(10, 1000, phase="1 phase"),
            sample(20, 1000, phase="3 phases"),
        ]

        result = self.capture.analyze_samples(
            samples, requested_interval=10, max_gap_seconds=30
        )

        self.assertEqual(result["one_phase_seconds"], 15)
        self.assertEqual(result["three_phase_seconds"], 5)

    def test_transition_tracker_does_not_call_baseline_or_new_trip_a_phase_change(self):
        events = []
        tracker = self.capture.TransitionTracker(
            lambda epoch, event, detail: events.append((epoch, event, detail))
        )

        tracker.update(sample(0, 1000, phase="1 phase", target_total_a=10))
        tracker.update(sample(10, 1000, phase="Transition", target_total_a=10))
        tracker.update(sample(20, 1000, phase="3 phases", target_total_a=18))
        tracker.update(sample(30, 0, phase="Unknown", target_total_a=6))
        tracker.update(sample(40, 1000, phase="1 phase", target_total_a=10))

        self.assertEqual(tracker.counts["MEASURED_CHARGING_START"], 1)
        self.assertEqual(tracker.counts["MEASURED_CHARGING_STOP"], 1)
        self.assertEqual(tracker.counts["PHASE_UP_CONFIRMED"], 1)
        self.assertEqual(tracker.counts["PHASE_DOWN_CONFIRMED"], 0)

    def test_log_analysis_reports_counts_rates_intervals_and_candidates(self):
        log = "\n".join(
            (
                "2000-01-02 10:00:00,000 (UTC+0) INFO Adjusting charge current to 10A on 3-phase.",
                "2000-01-02 10:00:10,000 (UTC+0) INFO Adjusting charge current to 10A on 3-phase.",
                "2000-01-02 10:00:15,000 (UTC+0) APP_DEBUG Wattpilot current setpoint already confirmed; accepting guarded no-op at 10A.",
                "2000-01-02 10:00:20,000 (UTC+0) INFO Switching to 3-phase from PV surplus.",
                "2000-01-02 10:00:25,000 (UTC+0) WARNING Wattpilot site-current source failure: source=synthetic.",
                "2000-01-02 10:00:30,000 (UTC+0) INFO Wattpilot site-current source recovered: source=synthetic.",
                "2000-01-02 10:00:35,000 (UTC+0) WARNING Site-current telemetry is missing, invalid, stale, or phase-uncertain. Stopping Auto/Eco charging for safety.",
                "2000-01-02 10:00:40,000 (UTC+0) WARNING Thread pollSiteCurrentSource from Synthetic is scheduled to run every 1000ms - Future not done, skipping call attempt.",
                "2000-01-02 10:00:45,000 (UTC+0) INFO Wattpilot phase telemetry confirmed 3-phase charging.",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.log"
            path.write_text(log + "\n", encoding="utf-8")

            result = self.capture.analyze_log(path, duration_seconds=3600)

        current = result["current_adjustments"]
        self.assertEqual(current["count"], 2)
        self.assertEqual(current["rate_per_hour"], 2)
        self.assertEqual(current["average_interval_seconds"], 10)
        self.assertEqual(result["guarded_current_noops"]["count"], 1)
        self.assertEqual(result["phase_up_actions"]["count"], 1)
        self.assertEqual(result["site_source_failures"]["count"], 1)
        self.assertEqual(result["site_source_recoveries"]["count"], 1)
        self.assertEqual(result["site_current_safety_stops"]["count"], 1)
        self.assertEqual(result["site_poll_skips"]["count"], 1)
        self.assertEqual(result["phase_confirmations"]["count"], 1)
        self.assertEqual(result["consecutive_same_adjustment_candidates"], 1)

    def test_capture_fields_include_selected_source_and_separate_venus_values(self):
        ev_fields = dict(self.capture.EV_FIELDS)
        system_fields = dict(self.capture.SYSTEM_FIELDS)

        self.assertEqual(
            ev_fields["selected_site_l3_current_a"], "/SiteCurrentL3"
        )
        self.assertEqual(
            ev_fields["charger_one_phase_mapping"], "/Charger1PhaseMapping"
        )
        self.assertEqual(
            system_fields["venus_consumption_l3_power_w"],
            "/Ac/Consumption/L3/Power",
        )

    def test_log_follower_ignores_history_and_handles_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "current.log"
            destination = root / "captured.log"
            source.write_text("old history\n", encoding="utf-8")
            follower = self.capture.LogFollower(source, destination)
            follower.start()

            with source.open("a", encoding="utf-8") as handle:
                handle.write("new line\n")
            follower.poll()
            source.write_text("after rotation\n", encoding="utf-8")
            follower.poll()
            follower.close()

            captured = destination.read_text(encoding="utf-8")

        self.assertNotIn("old history", captured)
        self.assertIn("new line", captured)
        self.assertIn("after rotation", captured)

    def test_short_capture_writes_samples_transitions_and_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "current.log"
            output = root / "capture"
            log.write_text("existing history\n", encoding="utf-8")
            args = self.capture.build_parser().parse_args(
                [
                    "--duration",
                    "0.04",
                    "--interval",
                    "0.01",
                    "--max-gap",
                    "0.1",
                    "--output-dir",
                    str(output),
                    "--log-file",
                    str(log),
                ]
            )

            with contextlib.redirect_stdout(io.StringIO()):
                result = self.capture.run_capture(args, bus=MappingBus())

            samples = (output / "samples.tsv").read_text(encoding="utf-8")
            transitions = (output / "transitions.tsv").read_text(
                encoding="utf-8"
            )
            summary = (output / "summary.txt").read_text(encoding="utf-8")

        self.assertEqual(result, 0)
        self.assertGreaterEqual(len(samples.splitlines()), 3)
        self.assertIn("CAPTURE_BASELINE", transitions)
        self.assertIn("actual timestamp integration", summary)
        self.assertIn("Source observed:          Shelly3EMGen3", summary)
        self.assertIn("One-phase mapping:        L3", summary)
        self.assertIn("Selected-source L3 current", summary)
        self.assertIn("Venus consumption L3 power", summary)
        self.assertIn("D-Bus read failures: 0", summary)

    def test_public_source_keeps_capture_command_free(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertNotIn("SetValue", source)
        self.assertNotIn("dbus-send", source)
        self.assertNotIn("set_power(", source)
        self.assertNotIn("set_phases(", source)
        self.assertNotIn("set_start_stop(", source)


if __name__ == "__main__":
    unittest.main()
