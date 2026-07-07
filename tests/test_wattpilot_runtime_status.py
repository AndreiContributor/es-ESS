"""Hardware-free coverage for the Fronius Wattpilot runtime-status contract."""

import sys
import time
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from WattpilotRuntimeStatus import (
    CONTROL_STATE_BATTERY_ASSIST,
    CONTROL_STATE_CHARGING_1_PHASE,
    CONTROL_STATE_CHARGING_3_PHASE,
    CONTROL_STATE_FAULT,
    CONTROL_STATE_STOPPED,
    CONTROL_STATE_STOPPED_FOR_GRID_IMPORT,
    CONTROL_STATE_STOPPED_FOR_STALE_TELEMETRY,
    CONTROL_STATE_SWITCHING_TO_1_PHASE,
    CONTROL_STATE_SWITCHING_TO_3_PHASE,
    CONTROL_STATE_WAITING_FOR_PV,
    CONTROL_STATE_WAITING_FOR_STABLE_PV,
    RUNTIME_STATUS_MQTT_PREFIX,
    attach_runtime_status_reporter,
)


class FakeDbusService(dict):
    def __init__(self):
        super().__init__()
        self.added_paths = []
        self.registered = False
        self.paths_at_registration = set()

    def add_path(self, path, value, **_kwargs):
        self.added_paths.append(path)
        self[path] = value

    def register(self):
        self.registered = True
        self.paths_at_registration = set(self.keys())


def VeDbusService(*_args, **_kwargs):
    """Module-global factory so the reporter can observe registration timing."""
    return FakeDbusService()


class FakeStatus:
    def __init__(self, name):
        self.name = name


class Mode:
    def __init__(self, name):
        self.name = name


class FakeWattpilot:
    def __init__(self):
        self.connected = True
        self.power = 0.0
        self.mode = Mode("ECO")
        self.modelStatus = SimpleNamespace(value=4)
        self.handlers = {}

    def add_event_handler(self, event, callback):
        self.handlers.setdefault(event, []).append(callback)

    def emit(self, event):
        for callback in self.handlers.get(event, []):
            callback({"event": event})

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False


class FroniusWattpilot:
    """A deliberately small controller shape consumed by the reporter."""

    def __init__(self):
        self.dbusService = None
        self.mqtt = []
        self.mode = Mode("Auto")
        self.allowGridCharging = False
        self.grid_healthy = True
        self.allowance_fresh = True
        self.minimum_allowance = False
        self.currentPhaseMode = 1
        self.pendingPhaseSwitchMode = 0
        self.batteryAssistActive = False
        self.gridImportSince = 0
        self.wattpilot = FakeWattpilot()
        self.runtime_status_calls = []

    def initDbusService(self):
        self.dbusService = VeDbusService("com.victronenergy.evcharger.test", register=False)
        self.dbusService.add_path("/Status", 123)
        self.dbusService.add_path("/PhaseMode", 0)
        self.dbusService.add_path("/PhaseModeLiteral", "Unknown")
        self.dbusService.register()

    def initFinalize(self):
        self.wattpilot.connect()

    def reportVRMStatus(self, status):
        self.runtime_status_calls.append(status.name)

    def reportPhaseMode(self):
        self.runtime_status_calls.append("phase")

    def gridTelemetryIsFresh(self):
        return self.grid_healthy

    def allowanceIsFresh(self):
        return self.allowance_fresh

    def hasMinimumAllowance(self):
        return self.minimum_allowance

    def failSafeStopForAutoControlFault(self):
        self.runtime_status_calls.append("fault")

    def _update(self):
        self.runtime_status_calls.append("update")

    def publishMainMqtt(self, topic, payload, qos=0, retain=False):
        self.mqtt.append((topic, payload, qos, retain))


class WattpilotRuntimeStatusTests(unittest.TestCase):
    def make_controller(self):
        controller = FroniusWattpilot()
        reporter = attach_runtime_status_reporter(controller)
        controller.initDbusService()
        self.assertIsNotNone(reporter)
        return controller, reporter

    def publish(self, controller, status_name="Connected"):
        controller.reportVRMStatus(FakeStatus(status_name))
        return controller._runtime_status_reporter.last_snapshot

    def assert_state(self, controller, expected, literal):
        snapshot = controller._runtime_status_reporter.last_snapshot
        self.assertEqual(snapshot.control_state, expected)
        self.assertEqual(snapshot.control_state_literal, literal)
        self.assertEqual(controller.dbusService["/ControlState"], expected)
        self.assertEqual(controller.dbusService["/ControlStateLiteral"], literal)

    def test_registers_all_paths_before_registration_without_changing_vrm_status(self):
        controller, _reporter = self.make_controller()
        required = {
            "/ControlState",
            "/ControlStateLiteral",
            "/PhaseMode",
            "/PhaseModeLiteral",
            "/BatteryAssistActive",
            "/GridImportGuardActive",
            "/TelemetryHealthy",
        }
        self.assertTrue(required.issubset(controller.dbusService.keys()))
        self.assertTrue(required.issubset(controller.dbusService.paths_at_registration))
        self.assertEqual(controller.dbusService["/Status"], 123)

    def test_every_required_control_state(self):
        cases = [
            ("Stopped", lambda c: setattr(c.mode, "name", "Manual"), "Connected", CONTROL_STATE_STOPPED),
            ("Waiting for PV", lambda c: None, "Connected", CONTROL_STATE_WAITING_FOR_PV),
            (
                "Waiting for stable PV",
                lambda c: setattr(c, "minimum_allowance", True),
                "Connected",
                CONTROL_STATE_WAITING_FOR_STABLE_PV,
            ),
            (
                "Charging 1 phase",
                lambda c: setattr(c.wattpilot, "power", 1.4),
                "Charging",
                CONTROL_STATE_CHARGING_1_PHASE,
            ),
            (
                "Charging 3 phases",
                lambda c: (setattr(c, "currentPhaseMode", 2), setattr(c.wattpilot, "power", 4.2)),
                "Charging",
                CONTROL_STATE_CHARGING_3_PHASE,
            ),
            (
                "Switching to 1 phase",
                lambda c: setattr(c, "pendingPhaseSwitchMode", 1),
                "SwitchingTo1Phase",
                CONTROL_STATE_SWITCHING_TO_1_PHASE,
            ),
            (
                "Switching to 3 phases",
                lambda c: setattr(c, "pendingPhaseSwitchMode", 2),
                "SwitchingTo3Phase",
                CONTROL_STATE_SWITCHING_TO_3_PHASE,
            ),
            (
                "Battery assist",
                lambda c: (setattr(c.wattpilot, "power", 1.4), setattr(c, "batteryAssistActive", True)),
                "Charging",
                CONTROL_STATE_BATTERY_ASSIST,
            ),
            (
                "Stopped for grid import",
                lambda c: setattr(c, "gridImportSince", time.time()),
                "StopCharging",
                CONTROL_STATE_STOPPED_FOR_GRID_IMPORT,
            ),
            (
                "Stopped for stale telemetry",
                lambda c: setattr(c, "grid_healthy", False),
                "StopCharging",
                CONTROL_STATE_STOPPED_FOR_STALE_TELEMETRY,
            ),
        ]
        for literal, arrange, status_name, state in cases:
            with self.subTest(literal=literal):
                controller, _reporter = self.make_controller()
                arrange(controller)
                self.publish(controller, status_name)
                self.assert_state(controller, state, literal)

        controller, _reporter = self.make_controller()
        controller.failSafeStopForAutoControlFault()
        self.assert_state(controller, CONTROL_STATE_FAULT, "Fault")

    def test_one_and_three_phase_transitions_publish_unknown_phase_during_switch(self):
        controller, _reporter = self.make_controller()
        controller.pendingPhaseSwitchMode = 1
        self.publish(controller, "SwitchingTo1Phase")
        self.assertEqual(controller.dbusService["/PhaseMode"], 0)
        self.assertEqual(controller.dbusService["/PhaseModeLiteral"], "Transition")
        self.assert_state(controller, CONTROL_STATE_SWITCHING_TO_1_PHASE, "Switching to 1 phase")

        controller.pendingPhaseSwitchMode = 2
        self.publish(controller, "SwitchingTo3Phase")
        self.assert_state(controller, CONTROL_STATE_SWITCHING_TO_3_PHASE, "Switching to 3 phases")

    def test_failed_phase_switch_is_stopped_not_misreported_as_fault(self):
        controller, _reporter = self.make_controller()
        controller.currentPhaseMode = 0
        controller.pendingPhaseSwitchMode = 0
        self.publish(controller, "StopCharging")
        self.assert_state(controller, CONTROL_STATE_STOPPED, "Stopped")
        self.assertEqual(controller.dbusService["/PhaseMode"], 0)

    def test_disconnect_then_reconnect_updates_health_and_state_immediately(self):
        controller, _reporter = self.make_controller()
        controller.initFinalize()

        controller.wattpilot.disconnect()
        self.assert_state(controller, CONTROL_STATE_STOPPED, "Stopped")
        self.assertEqual(controller.dbusService["/TelemetryHealthy"], 0)

        controller.wattpilot.connect()
        self.assert_state(controller, CONTROL_STATE_WAITING_FOR_PV, "Waiting for PV")
        self.assertEqual(controller.dbusService["/TelemetryHealthy"], 1)

    def test_wattpilot_events_publish_after_finalize(self):
        controller, _reporter = self.make_controller()
        module = ModuleType("Wattpilot")
        module.Event = SimpleNamespace(
            WP_CONNECT="connect",
            WP_DISCONNECT="disconnect",
            WS_CLOSE="close",
            WP_AUTH_SUCCESS="auth",
            WP_FULL_STATUS_FINISHED="full",
            WP_PROPERTY="property",
        )
        with mock.patch.dict(sys.modules, {"Wattpilot": module}):
            controller.initFinalize()
            self.assertIn(module.Event.WP_DISCONNECT, controller.wattpilot.handlers)
            controller.wattpilot.connected = False
            controller.wattpilot.emit(module.Event.WP_DISCONNECT)
            self.assert_state(controller, CONTROL_STATE_STOPPED, "Stopped")
            self.assertEqual(controller.dbusService["/TelemetryHealthy"], 0)

            controller.wattpilot.connected = True
            controller.wattpilot.emit(module.Event.WP_AUTH_SUCCESS)
            self.assert_state(controller, CONTROL_STATE_WAITING_FOR_PV, "Waiting for PV")
            self.assertEqual(controller.dbusService["/TelemetryHealthy"], 1)

    def test_stale_telemetry_stops_auto_but_not_manual_mode(self):
        controller, _reporter = self.make_controller()
        controller.grid_healthy = False
        self.publish(controller, "StopCharging")
        self.assert_state(
            controller,
            CONTROL_STATE_STOPPED_FOR_STALE_TELEMETRY,
            "Stopped for stale telemetry",
        )
        self.assertEqual(controller.dbusService["/TelemetryHealthy"], 0)

        controller.mode = Mode("Manual")
        controller.wattpilot.power = 1.4
        controller.gridImportSince = time.time()
        self.publish(controller, "Charging")
        self.assert_state(controller, CONTROL_STATE_CHARGING_1_PHASE, "Charging 1 phase")
        self.assertEqual(controller.dbusService["/GridImportGuardActive"], 0)

    def test_battery_assist_and_grid_guard_flags_are_explicit(self):
        controller, _reporter = self.make_controller()
        controller.wattpilot.power = 1.4
        controller.batteryAssistActive = True
        self.publish(controller, "Charging")
        self.assertEqual(controller.dbusService["/BatteryAssistActive"], 1)
        self.assertEqual(controller.dbusService["/GridImportGuardActive"], 0)

        controller.batteryAssistActive = False
        controller.gridImportSince = time.time()
        self.publish(controller, "StopCharging")
        self.assertEqual(controller.dbusService["/BatteryAssistActive"], 0)
        self.assertEqual(controller.dbusService["/GridImportGuardActive"], 1)

    def test_retained_mqtt_contract_contains_every_value(self):
        controller, _reporter = self.make_controller()
        self.publish(controller, "Connected")
        published = {topic: (payload, retain) for topic, payload, _qos, retain in controller.mqtt}
        expected_topics = {
            "ControlState",
            "ControlStateLiteral",
            "PhaseMode",
            "PhaseModeLiteral",
            "BatteryAssistActive",
            "GridImportGuardActive",
            "TelemetryHealthy",
        }
        self.assertEqual(
            set(published),
            {"{0}/{1}".format(RUNTIME_STATUS_MQTT_PREFIX, suffix) for suffix in expected_topics},
        )
        self.assertTrue(all(retain for _payload, retain in published.values()))


if __name__ == "__main__":
    unittest.main()
