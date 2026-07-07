"""Hardware-free regression coverage for Wattpilot runtime status."""

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
    WATTPILOT_TELEMETRY_FRESH_SECONDS,
    attach_runtime_status_reporter,
)


class FakeDbusService(dict):
    def __init__(self):
        super().__init__()
        self.registered = False
        self.paths_at_registration = set()

    def add_path(self, path, value, **_kwargs):
        self[path] = value

    def register(self):
        self.registered = True
        self.paths_at_registration = set(self.keys())


def VeDbusService(*_args, **_kwargs):
    return FakeDbusService()


class WaitHelper:
    def __init__(self):
        self.calls = 0

    def waitTimeout(self, _predicate, _timeout):
        self.calls += 1
        raise AssertionError("legacy startup wait was not replaced")


# The reporter temporarily replaces this module-global object only while it
# invokes FroniusWattpilot.initFinalize().
Helper = WaitHelper()


class FakeStatus:
    def __init__(self, name):
        self.name = name


class Mode:
    VALUES = {"Manual": 0, "Auto": 1}

    def __init__(self, name):
        self.name = name
        self.value = self.VALUES.get(name, -1)


class FakeWattpilot:
    def __init__(self, connected=True, ready=True, mode="ECO"):
        self.connected = connected
        self.carStateReady = ready
        self.power = 0.0
        self.power1 = None
        self.power2 = None
        self.power3 = None
        self.mode = Mode(mode) if mode is not None else None
        self.modelStatus = SimpleNamespace(value=4)
        self.handlers = {}
        self.connect_calls = 0

    def add_event_handler(self, event, callback):
        self.handlers.setdefault(event, []).append(callback)

    def emit(self, event):
        for callback in self.handlers.get(event, []):
            callback({"event": event})

    def connect(self):
        self.connect_calls += 1

    def disconnect(self):
        self.connected = False


class FroniusWattpilot:
    """Small controller surface used by the runtime-status observer tests."""

    def __init__(self, startup_online=True):
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
        self.startup_online = startup_online
        self.init_finished = False
        self.update_calls = 0
        self.last_status_name = ""

    def initDbusService(self):
        self.dbusService = VeDbusService("com.victronenergy.evcharger.test", register=False)
        self.dbusService.add_path("/Status", 123)
        self.dbusService.add_path("/StatusLiteral", "Disconnected")
        self.dbusService.add_path("/PhaseMode", 0)
        self.dbusService.add_path("/PhaseModeLiteral", "Unknown")
        self.dbusService.register()

    def initFinalize(self):
        self.wattpilot = FakeWattpilot(
            connected=self.startup_online,
            ready=self.startup_online,
            mode="ECO" if self.startup_online else None,
        )
        self.wattpilot.connect()
        # This mimics the legacy serial 30-second waits. The reporter replaces
        # it with immediate checks for this single startup invocation.
        Helper.waitTimeout(lambda: self.wattpilot.connected, 30)
        Helper.waitTimeout(lambda: self.wattpilot.power1 is not None, 30)
        Helper.waitTimeout(lambda: self.wattpilot.carStateReady, 30)
        self.init_finished = True

    def _update(self):
        self.update_calls += 1
        self.reportVRMStatus(FakeStatus(self.last_status_name or "WaitingForSun"))

    def reportVRMStatus(self, status):
        self.last_status_name = status.name
        self.dbusService["/StatusLiteral"] = status.name

    def reportPhaseMode(self):
        pass

    def switchMode(self, _from_mode, _to_mode):
        pass

    def _froniusHandleChangedValue(self, _path, _value):
        return True

    def startFromPvAllowance(self):
        pass

    def forceStopForNoAllowance(self):
        pass

    def switchToOnePhaseForPvDip(self):
        pass

    def adjustChargeForPvAllowance(self):
        pass

    def startOrContinueBatteryAssist(self):
        pass

    def clearBatteryAssist(self):
        pass

    def recordGridTelemetry(self, _phase, _value):
        pass

    def onMqttMessage(self, *_args):
        pass

    def reconcilePendingPhaseSwitch(self):
        return None

    def wakeUpWattpilot(self):
        pass

    def handleSigterm(self):
        pass

    def failSafeStopForAutoControlFault(self):
        pass

    def gridTelemetryIsFresh(self):
        return self.grid_healthy

    def allowanceIsFresh(self):
        return self.allowance_fresh

    def hasMinimumAllowance(self):
        return self.minimum_allowance

    def publishMainMqtt(self, topic, payload, qos=0, retain=False):
        self.mqtt.append((topic, payload, qos, retain))


class WattpilotRuntimeStatusTests(unittest.TestCase):
    def setUp(self):
        Helper.calls = 0

    def make_controller(self, startup_online=True):
        controller = FroniusWattpilot(startup_online=startup_online)
        reporter = attach_runtime_status_reporter(controller)
        controller.initDbusService()
        self.assertIsNotNone(reporter)
        return controller, reporter

    def publish(self, controller, status_name="WaitingForSun"):
        controller.reportVRMStatus(FakeStatus(status_name))
        return controller._runtime_status_reporter.last_snapshot

    def assert_state(self, controller, expected, literal):
        snapshot = controller._runtime_status_reporter.last_snapshot
        self.assertEqual(snapshot.control_state, expected)
        self.assertEqual(snapshot.control_state_literal, literal)
        self.assertEqual(controller.dbusService["/ControlState"], expected)
        self.assertEqual(controller.dbusService["/ControlStateLiteral"], literal)

    def assert_phase_mode(self, controller, mode, literal):
        self.assertEqual(controller.dbusService["/PhaseMode"], mode)
        self.assertEqual(controller.dbusService["/PhaseModeLiteral"], literal)

    @staticmethod
    def set_live_phase_power(controller, l1, l2, l3):
        controller.wattpilot.power1 = l1
        controller.wattpilot.power2 = l2
        controller.wattpilot.power3 = l3
        controller.wattpilot.power = sum(value or 0 for value in (l1, l2, l3))

    @staticmethod
    def wattpilot_event_module():
        module = ModuleType("Wattpilot")
        module.Event = SimpleNamespace(WS_MESSAGE="message", WS_CLOSE="close")
        return module

    def establish_transport_baseline(self, controller, module, now=1000.0):
        controller.initFinalize()
        controller.wattpilot.connected = True
        controller.wattpilot.carStateReady = True
        controller.wattpilot.mode = Mode("ECO")
        with mock.patch("WattpilotRuntimeStatus.time.monotonic", return_value=now):
            controller.wattpilot.emit(module.Event.WS_MESSAGE)
            controller._update()

    def test_registers_contract_paths_before_dbus_registration_without_changing_status(self):
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
        self.assertTrue(required.issubset(controller.dbusService.paths_at_registration))
        self.assertEqual(controller.dbusService["/Status"], 123)
        self.assertEqual(controller.dbusService["/StatusLiteral"], "Disconnected")

    def test_every_required_control_state(self):
        def one_phase(controller):
            self.set_live_phase_power(controller, 1.4, 0.0, 0.0)

        def three_phase(controller):
            controller.currentPhaseMode = 0
            self.set_live_phase_power(controller, 1.4, 1.4, 1.4)

        cases = [
            ("Stopped", lambda c: setattr(c.mode, "name", "Manual"), "Connected", CONTROL_STATE_STOPPED),
            ("Waiting for PV", lambda c: None, "WaitingForSun", CONTROL_STATE_WAITING_FOR_PV),
            (
                "Waiting for stable PV",
                lambda c: setattr(c, "minimum_allowance", True),
                "WaitingForSun",
                CONTROL_STATE_WAITING_FOR_STABLE_PV,
            ),
            ("Charging 1 phase", one_phase, "Charging", CONTROL_STATE_CHARGING_1_PHASE),
            ("Charging 3 phases", three_phase, "Charging", CONTROL_STATE_CHARGING_3_PHASE),
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
                lambda c: (one_phase(c), setattr(c, "batteryAssistActive", True)),
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
                lambda c: (self.publish(c, "WaitingForSun"), setattr(c, "grid_healthy", False)),
                "StopCharging",
                CONTROL_STATE_STOPPED_FOR_STALE_TELEMETRY,
            ),
        ]
        for literal, arrange, status_name, expected in cases:
            with self.subTest(literal=literal):
                controller, _reporter = self.make_controller()
                arrange(controller)
                self.publish(controller, status_name)
                self.assert_state(controller, expected, literal)

        controller, _reporter = self.make_controller()
        controller.failSafeStopForAutoControlFault()
        self.assert_state(controller, CONTROL_STATE_FAULT, "Fault")

    def test_live_measured_phase_power_is_authoritative_in_manual_mode(self):
        controller, _reporter = self.make_controller()
        controller.mode = Mode("Manual")
        controller.currentPhaseMode = 0

        self.set_live_phase_power(controller, 3.4, 3.3, 3.4)
        self.publish(controller, "Charging")
        self.assert_state(controller, CONTROL_STATE_CHARGING_3_PHASE, "Charging 3 phases")
        self.assert_phase_mode(controller, 3, "3 phases")

        self.set_live_phase_power(controller, 1.4, 0.0, 0.0)
        self.publish(controller, "Charging")
        self.assert_state(controller, CONTROL_STATE_CHARGING_1_PHASE, "Charging 1 phase")
        self.assert_phase_mode(controller, 1, "1 phase")

    def test_active_one_phase_charge_never_publishes_unknown_phase_mode(self):
        """Keep the public state and phase-mode values internally consistent."""
        controller, _reporter = self.make_controller()
        controller.mode = Mode("Manual")
        controller.currentPhaseMode = 0
        # Simulate the field case: VRM has reported Charging, but this
        # Wattpilot-client revision has not yet populated all phase attributes.
        self.set_live_phase_power(controller, None, None, None)

        self.publish(controller, "Charging")

        self.assert_state(controller, CONTROL_STATE_CHARGING_1_PHASE, "Charging 1 phase")
        self.assert_phase_mode(controller, 1, "1 phase")

    def test_incomplete_live_phase_telemetry_uses_existing_controller_fallback(self):
        controller, _reporter = self.make_controller()
        controller.mode = Mode("Manual")
        controller.currentPhaseMode = 2
        self.set_live_phase_power(controller, 3.4, None, None)
        self.publish(controller, "Charging")
        self.assert_state(controller, CONTROL_STATE_CHARGING_3_PHASE, "Charging 3 phases")
        self.assert_phase_mode(controller, 3, "3 phases")

    def test_phase_transitions_and_failed_phase_switch_are_not_faults(self):
        controller, _reporter = self.make_controller()
        controller.pendingPhaseSwitchMode = 1
        self.publish(controller, "SwitchingTo1Phase")
        self.assert_state(controller, CONTROL_STATE_SWITCHING_TO_1_PHASE, "Switching to 1 phase")
        self.assert_phase_mode(controller, 0, "Transition")

        controller.pendingPhaseSwitchMode = 2
        self.publish(controller, "SwitchingTo3Phase")
        self.assert_state(controller, CONTROL_STATE_SWITCHING_TO_3_PHASE, "Switching to 3 phases")
        self.assert_phase_mode(controller, 0, "Transition")

        controller.pendingPhaseSwitchMode = 0
        controller.currentPhaseMode = 0
        self.publish(controller, "StopCharging")
        self.assert_state(controller, CONTROL_STATE_STOPPED, "Stopped")
        self.assert_phase_mode(controller, 0, "Unknown")

    def test_manual_mode_is_not_changed_by_auto_safety_flags(self):
        controller, _reporter = self.make_controller()
        controller.mode = Mode("Manual")
        controller.grid_healthy = False
        controller.gridImportSince = time.time()
        self.set_live_phase_power(controller, 1.4, 0.0, 0.0)
        self.publish(controller, "Charging")
        self.assert_state(controller, CONTROL_STATE_CHARGING_1_PHASE, "Charging 1 phase")
        self.assertEqual(controller.dbusService["/GridImportGuardActive"], 0)
        self.assertEqual(controller.dbusService["/TelemetryHealthy"], 1)

    def test_auto_startup_is_neutral_before_first_healthy_telemetry_baseline(self):
        controller, reporter = self.make_controller()
        controller.initFinalize()
        controller.grid_healthy = False
        controller.allowance_fresh = False
        controller._update()
        self.assertTrue(reporter.runtime_state_ready)
        self.assertFalse(reporter.telemetry_baseline_established)
        self.assert_state(controller, CONTROL_STATE_STOPPED, "Stopped")
        self.assertEqual(controller.dbusService["/TelemetryHealthy"], 0)

        controller.grid_healthy = True
        controller.allowance_fresh = True
        controller._update()
        self.assertTrue(reporter.telemetry_baseline_established)
        self.assert_state(controller, CONTROL_STATE_WAITING_FOR_PV, "Waiting for PV")
        self.assertEqual(controller.dbusService["/TelemetryHealthy"], 1)

    def test_offline_startup_never_waits_and_publishes_safe_state(self):
        module = self.wattpilot_event_module()
        with mock.patch.dict(sys.modules, {"Wattpilot": module}):
            controller, reporter = self.make_controller(startup_online=False)
            started = time.monotonic()
            controller.initFinalize()
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.2)
        self.assertEqual(Helper.calls, 0)
        self.assertTrue(reporter._init_finalize_completed)
        self.assertFalse(controller.wattpilot.connected)
        self.assert_state(controller, CONTROL_STATE_STOPPED, "Stopped")
        self.assertEqual(controller.dbusService["/TelemetryHealthy"], 0)
        self.assertEqual(controller.update_calls, 0)
        controller._update()
        self.assertEqual(controller.update_calls, 0)
        self.assert_state(controller, CONTROL_STATE_STOPPED, "Stopped")

    def test_offline_startup_recovers_when_wattpilot_later_becomes_ready(self):
        module = self.wattpilot_event_module()
        with mock.patch.dict(sys.modules, {"Wattpilot": module}):
            controller, _reporter = self.make_controller(startup_online=False)
            controller.initFinalize()
            controller.wattpilot.connected = True
            controller.wattpilot.carStateReady = True
            controller.wattpilot.mode = Mode("ECO")
            controller.wattpilot.emit(module.Event.WS_MESSAGE)
            controller._update()

        self.assertEqual(controller.update_calls, 1)
        self.assert_state(controller, CONTROL_STATE_WAITING_FOR_PV, "Waiting for PV")
        self.assertEqual(controller.dbusService["/TelemetryHealthy"], 1)

    def test_websocket_close_and_reconnect_publish_on_controller_updates(self):
        module = self.wattpilot_event_module()
        with mock.patch.dict(sys.modules, {"Wattpilot": module}):
            controller, _reporter = self.make_controller()
            self.establish_transport_baseline(controller, module)
            self.assert_state(controller, CONTROL_STATE_WAITING_FOR_PV, "Waiting for PV")

            before_mqtt = len(controller.mqtt)
            controller.wattpilot.connected = False
            controller.wattpilot.emit(module.Event.WS_CLOSE)
            self.assertEqual(len(controller.mqtt), before_mqtt)
            controller._update()
            self.assert_state(controller, CONTROL_STATE_STOPPED, "Stopped")
            self.assertEqual(controller.dbusService["/TelemetryHealthy"], 0)

            controller.wattpilot.connected = True
            controller.wattpilot.carStateReady = True
            controller.wattpilot.mode = Mode("ECO")
            controller.wattpilot.emit(module.Event.WS_MESSAGE)
            controller._update()
            self.assert_state(controller, CONTROL_STATE_WAITING_FOR_PV, "Waiting for PV")
            self.assertEqual(controller.dbusService["/TelemetryHealthy"], 1)

    def test_silent_transport_staleness_stops_auto_after_a_healthy_baseline(self):
        module = self.wattpilot_event_module()
        start = 1000.0
        with mock.patch.dict(sys.modules, {"Wattpilot": module}):
            controller, _reporter = self.make_controller()
            self.establish_transport_baseline(controller, module, now=start)
            self.assert_state(controller, CONTROL_STATE_WAITING_FOR_PV, "Waiting for PV")

            with mock.patch(
                "WattpilotRuntimeStatus.time.monotonic",
                return_value=start + WATTPILOT_TELEMETRY_FRESH_SECONDS + 1,
            ):
                controller._update()

            self.assert_state(
                controller,
                CONTROL_STATE_STOPPED_FOR_STALE_TELEMETRY,
                "Stopped for stale telemetry",
            )
            self.assertEqual(controller.dbusService["/TelemetryHealthy"], 0)

            with mock.patch(
                "WattpilotRuntimeStatus.time.monotonic",
                return_value=start + WATTPILOT_TELEMETRY_FRESH_SECONDS + 2,
            ):
                controller.wattpilot.emit(module.Event.WS_MESSAGE)
                controller._update()

        self.assert_state(controller, CONTROL_STATE_WAITING_FOR_PV, "Waiting for PV")
        self.assertEqual(controller.dbusService["/TelemetryHealthy"], 1)

    def test_silent_transport_staleness_reports_unhealthy_without_changing_manual_operation(self):
        module = self.wattpilot_event_module()
        start = 2000.0
        with mock.patch.dict(sys.modules, {"Wattpilot": module}):
            controller, _reporter = self.make_controller()
            self.establish_transport_baseline(controller, module, now=start)
            controller.mode = Mode("Manual")
            controller.currentPhaseMode = 0
            self.set_live_phase_power(controller, 1.4, 0.0, 0.0)
            self.publish(controller, "Charging")

            with mock.patch(
                "WattpilotRuntimeStatus.time.monotonic",
                return_value=start + WATTPILOT_TELEMETRY_FRESH_SECONDS + 1,
            ):
                controller._update()

        self.assert_state(controller, CONTROL_STATE_CHARGING_1_PHASE, "Charging 1 phase")
        self.assertEqual(controller.dbusService["/TelemetryHealthy"], 0)
        self.assertEqual(controller.dbusService["/GridImportGuardActive"], 0)

    def test_battery_assist_and_grid_guard_flags_are_explicit(self):
        controller, _reporter = self.make_controller()
        self.set_live_phase_power(controller, 1.4, 0.0, 0.0)
        controller.batteryAssistActive = True
        self.publish(controller, "Charging")
        self.assertEqual(controller.dbusService["/BatteryAssistActive"], 1)
        self.assertEqual(controller.dbusService["/GridImportGuardActive"], 0)

        controller.batteryAssistActive = False
        controller.gridImportSince = time.time()
        self.publish(controller, "StopCharging")
        self.assert_state(controller, CONTROL_STATE_STOPPED_FOR_GRID_IMPORT, "Stopped for grid import")
        self.assertEqual(controller.dbusService["/BatteryAssistActive"], 0)
        self.assertEqual(controller.dbusService["/GridImportGuardActive"], 1)

    def test_retained_mqtt_contract_contains_every_value(self):
        controller, _reporter = self.make_controller()
        self.publish(controller, "WaitingForSun")
        published = {topic: (payload, retain) for topic, payload, _qos, retain in controller.mqtt}
        expected_suffixes = {
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
            {"{0}/{1}".format(RUNTIME_STATUS_MQTT_PREFIX, suffix) for suffix in expected_suffixes},
        )
        self.assertTrue(all(retain for _payload, retain in published.values()))


if __name__ == "__main__":
    unittest.main()
