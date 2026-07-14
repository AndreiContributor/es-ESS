"""Hardware-free tests for the command-free Wattpilot setting capture tool."""

import ast
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "wattpilot-setting-capture.py"


def _load_capture_module():
    spec = importlib.util.spec_from_file_location(
        "wattpilot_setting_capture_under_test", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    def __init__(self, event=None):
        self.firmware = "42.5"
        self.carStateReady = True
        self.carConnected = False
        self.allProps = {
            "fwv": "42.5",
            "pv_enabled_candidate": True,
            "starting_power_candidate": 1.4,
            "cak": "private-api-key",
        }
        self.event = event
        self.full_status_requests = 0

    def request_full_status(self):
        self.full_status_requests += 1
        if self.event is not None:
            self.event.set()


class WattpilotSettingCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.capture = _load_capture_module()

    def test_diff_reports_only_added_removed_and_changed_properties(self):
        before = {
            "unchanged": 1,
            "changed": False,
            "removed": 3,
        }
        after = {
            "unchanged": 1,
            "changed": True,
            "added": 4,
        }

        changes = self.capture.diff_snapshots(before, after)

        self.assertEqual(
            [(item["key"], item["change"]) for item in changes],
            [
                ("added", "added"),
                ("changed", "changed"),
                ("removed", "removed"),
            ],
        )
        self.assertNotIn("unchanged", json.dumps(changes))

    def test_sensitive_and_arbitrary_string_values_are_not_exposed(self):
        sensitive = self.capture.safe_report_value("cak", "private-api-key")
        arbitrary = self.capture.safe_report_value("candidate", "secret-value")
        safe_enum = self.capture.safe_report_value("candidate", "Disabled")

        self.assertTrue(sensitive["redacted"])
        self.assertTrue(arbitrary["redacted"])
        self.assertNotIn("private-api-key", json.dumps(sensitive))
        self.assertNotIn("secret-value", json.dumps(arbitrary))
        self.assertEqual(safe_enum, "Disabled")

    def test_snapshot_handles_nested_status_values_deterministically(self):
        first = self.capture.snapshot_properties(
            {"nested": {"b": [2, 1], "a": {"value": True}}}
        )
        second = self.capture.snapshot_properties(
            {"nested": {"a": {"value": True}, "b": [2, 1]}}
        )

        self.assertEqual(first, second)

    def test_capture_requires_validated_firmware_and_disconnected_vehicle(self):
        client = FakeClient()
        client.firmware = "42.6"
        with self.assertRaisesRegex(self.capture.CaptureError, "must be 42.5"):
            self.capture.validate_capture_state(client)

        client.firmware = "42.5"
        client.carConnected = True
        with self.assertRaisesRegex(self.capture.CaptureError, "Disconnect"):
            self.capture.validate_capture_state(client)

        client.carConnected = False
        client.carStateReady = False
        with self.assertRaisesRegex(self.capture.CaptureError, "not ready"):
            self.capture.validate_capture_state(client)

    def test_capture_requests_status_and_returns_redacted_reversible_diff(self):
        event = threading.Event()
        client = FakeClient(event)

        def change_one_setting():
            client.allProps["pv_enabled_candidate"] = False
            client.allProps["cak"] = "different-private-api-key"

        report = self.capture.capture_setting_change(
            client,
            event,
            "use-pv-on-to-off",
            change_one_setting,
            timeout_seconds=0.1,
        )

        self.assertEqual(client.full_status_requests, 1)
        self.assertEqual(report["firmware"], "42.5")
        self.assertFalse(report["vehicle_connected"])
        self.assertEqual(report["command_policy"], "all setValue requests blocked")
        changes = {item["key"]: item for item in report["changes"]}
        self.assertEqual(changes["pv_enabled_candidate"]["before"], True)
        self.assertEqual(changes["pv_enabled_candidate"]["after"], False)
        self.assertTrue(changes["cak"]["before"]["redacted"])
        self.assertNotIn("private-api-key", json.dumps(report))

    def test_capture_times_out_when_post_change_status_never_arrives(self):
        client = FakeClient(event=None)
        with self.assertRaisesRegex(self.capture.CaptureError, "Timed out"):
            self.capture.capture_setting_change(
                client,
                threading.Event(),
                "timeout",
                lambda: None,
                timeout_seconds=0.001,
            )

    def test_config_reader_disables_interpolation_and_never_returns_empty_values(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.ini"
            config_path.write_text(
                "[FroniusWattpilot]\nHost=192.0.2.1\nPassword=p%ssword\n",
                encoding="utf-8",
            )

            host, password = self.capture.load_connection_settings(config_path)

        self.assertEqual(host, "192.0.2.1")
        self.assertEqual(password, "p%ssword")

    def test_run_capture_installs_deny_all_guard_and_disconnects(self):
        instances = []

        class FakeEventType:
            WP_FULL_STATUS_FINISHED = object()

        class FakeLiveClient(FakeClient):
            def __init__(self, host, password):
                super().__init__()
                self.host = host
                self.password = password
                self.handler = None
                self.command_guard = None
                self.disconnected = False
                instances.append(self)

            def set_command_guard(self, callback):
                self.command_guard = callback

            def add_event_handler(self, event_type, callback):
                self.asserted_event_type = event_type
                self.handler = callback

            def connect(self):
                self.handler({"type": FakeEventType.WP_FULL_STATUS_FINISHED})

            def request_full_status(self):
                self.full_status_requests += 1
                self.handler({"type": FakeEventType.WP_FULL_STATUS_FINISHED})

            def disconnect(self, auto_reconnect=False):
                self.disconnected = True
                self.disconnect_auto_reconnect = auto_reconnect

        fake_wattpilot_module = types.ModuleType("Wattpilot")
        fake_wattpilot_module.Event = FakeEventType
        fake_wattpilot_module.Wattpilot = FakeLiveClient
        fake_globals_module = types.ModuleType("Globals")

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.ini"
            config_path.write_text(
                "[FroniusWattpilot]\nHost=192.0.2.2\nPassword=secret\n",
                encoding="utf-8",
            )

            def operator_change(_label):
                instances[0].allProps["pv_enabled_candidate"] = False

            with patch.dict(
                sys.modules,
                {"Globals": fake_globals_module, "Wattpilot": fake_wattpilot_module},
            ):
                with patch.object(
                    self.capture, "_operator_confirmation", side_effect=operator_change
                ):
                    report = self.capture.run_capture(
                        config_path, "use-pv-on-to-off", 0.1
                    )

        client = instances[0]
        self.assertEqual(client.host, "192.0.2.2")
        self.assertEqual(client.password, "secret")
        self.assertFalse(client.command_guard("amp", 16))
        self.assertFalse(client.command_guard("frc", 2))
        self.assertFalse(client.command_guard("psm", 2))
        self.assertTrue(client.disconnected)
        self.assertFalse(client.disconnect_auto_reconnect)
        self.assertEqual(report["changed_property_count"], 1)

    def test_script_contains_no_state_changing_wattpilot_method_calls(self):
        forbidden_calls = {
            "pairInverter",
            "send_update",
            "set_mode",
            "set_phases",
            "set_power",
            "set_start_stop",
            "unpairInverter",
        }
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        self.assertEqual(called_attributes & forbidden_calls, set())

    def test_timeout_argument_must_be_positive(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.capture.parse_args(["--label", "test", "--timeout", "0"])


if __name__ == "__main__":
    unittest.main()
