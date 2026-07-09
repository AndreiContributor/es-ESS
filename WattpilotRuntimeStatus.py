"""Authoritative runtime status for the Fronius Wattpilot service.

The standard Victron EV-charger ``/Status`` path remains owned by the existing
controller for VRM compatibility. This module publishes a separate contract for
dashboards, Cerbo extensions, MQTT consumers, and diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import logging
import math
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple


CONTROL_STATE_STOPPED = 0
CONTROL_STATE_WAITING_FOR_PV = 1
CONTROL_STATE_WAITING_FOR_STABLE_PV = 2
CONTROL_STATE_CHARGING_1_PHASE = 3
CONTROL_STATE_CHARGING_3_PHASE = 4
CONTROL_STATE_SWITCHING_TO_1_PHASE = 5
CONTROL_STATE_SWITCHING_TO_3_PHASE = 6
CONTROL_STATE_BATTERY_ASSIST = 7
CONTROL_STATE_STOPPED_FOR_GRID_IMPORT = 8
CONTROL_STATE_STOPPED_FOR_STALE_TELEMETRY = 9
CONTROL_STATE_FAULT = 10

CONTROL_STATE_LITERALS = {
    CONTROL_STATE_STOPPED: "Stopped",
    CONTROL_STATE_WAITING_FOR_PV: "Waiting for PV",
    CONTROL_STATE_WAITING_FOR_STABLE_PV: "Waiting for stable PV",
    CONTROL_STATE_CHARGING_1_PHASE: "Charging 1 phase",
    CONTROL_STATE_CHARGING_3_PHASE: "Charging 3 phases",
    CONTROL_STATE_SWITCHING_TO_1_PHASE: "Switching to 1 phase",
    CONTROL_STATE_SWITCHING_TO_3_PHASE: "Switching to 3 phases",
    CONTROL_STATE_BATTERY_ASSIST: "Battery assist",
    CONTROL_STATE_STOPPED_FOR_GRID_IMPORT: "Stopped for grid import",
    CONTROL_STATE_STOPPED_FOR_STALE_TELEMETRY: "Stopped for stale telemetry",
    CONTROL_STATE_FAULT: "Fault",
}

RUNTIME_STATUS_MQTT_PREFIX = "es-ESS/FroniusWattpilot/RuntimeStatus"

# Wattpilot reports per-phase power in kW. This is observation-only and is not
# a charging, cable, or current-limiting setting.
LIVE_PHASE_POWER_THRESHOLD_KW = 0.05

# The Wattpilot normally emits raw WebSocket messages about once per second.
# This bounded timeout is considered only after a healthy transport baseline
# has been seen and only from the normal controller update path.
WATTPILOT_TELEMETRY_FRESH_SECONDS = 60.0

RUNTIME_STATUS_DBUS_DEFAULTS = {
    "/ControlState": CONTROL_STATE_STOPPED,
    "/ControlStateLiteral": CONTROL_STATE_LITERALS[CONTROL_STATE_STOPPED],
    "/PhaseMode": 0,
    "/PhaseModeLiteral": "Unknown",
    "/BatteryAssistActive": 0,
    "/GridImportGuardActive": 0,
    "/TelemetryHealthy": 0,
}

RUNTIME_STATUS_TOPIC_SUFFIXES = {
    "/ControlState": "ControlState",
    "/ControlStateLiteral": "ControlStateLiteral",
    "/PhaseMode": "PhaseMode",
    "/PhaseModeLiteral": "PhaseModeLiteral",
    "/BatteryAssistActive": "BatteryAssistActive",
    "/GridImportGuardActive": "GridImportGuardActive",
    "/TelemetryHealthy": "TelemetryHealthy",
}

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    """The complete public runtime-status contract at one point in time."""

    control_state: int
    control_state_literal: str
    phase_mode: int
    phase_mode_literal: str
    battery_assist_active: int
    grid_import_guard_active: int
    telemetry_healthy: int

    def as_dbus_values(self) -> Dict[str, Any]:
        return {
            "/ControlState": self.control_state,
            "/ControlStateLiteral": self.control_state_literal,
            "/PhaseMode": self.phase_mode,
            "/PhaseModeLiteral": self.phase_mode_literal,
            "/BatteryAssistActive": self.battery_assist_active,
            "/GridImportGuardActive": self.grid_import_guard_active,
            "/TelemetryHealthy": self.telemetry_healthy,
        }


class WattpilotRuntimeStatusReporter:
    """Observe and publish the Wattpilot runtime-status contract.

    The existing controller remains solely responsible for charging decisions.
    This reporter does not issue commands. It publishes only from controller
    paths; raw WebSocket callbacks record timestamps only.
    """

    _TRANSITION_METHODS = (
        "reportVRMStatus",
        "reportPhaseMode",
        "switchMode",
        "_froniusHandleChangedValue",
        "startFromPvAllowance",
        "forceStopForNoAllowance",
        "switchToOnePhaseForPvDip",
        "adjustChargeForPvAllowance",
        "startOrContinueBatteryAssist",
        "clearBatteryAssist",
        "recordGridTelemetry",
        "onMqttMessage",
        "reconcilePendingPhaseSwitch",
        "wakeUpWattpilot",
        "handleSigterm",
    )

    def __init__(self, controller: Any) -> None:
        self.controller = controller
        self.last_snapshot: Optional[RuntimeStatusSnapshot] = None
        self.last_vrm_status_name: Optional[str] = None
        self.fault_active = False
        self._fault_generation = 0
        self._dbus_paths_registered = False

        # Startup is neutral until the original controller has enough Wattpilot
        # state for one normal update. This prevents a reboot while the
        # Wattpilot is unavailable from being labelled as stale telemetry.
        self.runtime_state_ready = False
        self.telemetry_baseline_established = False
        self._init_finalize_completed = False
        self._update_in_progress = False

        # Transport observations are updated only by raw event callbacks and
        # consumed only in the normal controller update path.
        self._wattpilot_events_attached = False
        self._transport_lock = threading.Lock()
        self._last_wattpilot_message_at: Optional[float] = None
        self._last_wattpilot_close_at: Optional[float] = None
        self._last_wattpilot_error_at: Optional[float] = None
        self._transport_has_healthy_baseline = False

    def install(self) -> "WattpilotRuntimeStatusReporter":
        """Install instance wrappers without changing control commands."""
        self._wrap_init_dbus_service()
        self._wrap_init_finalize_nonblocking()
        for method_name in self._TRANSITION_METHODS:
            self._wrap_method(method_name)
        self._wrap_method("failSafeStopForAutoControlFault", mark_fault=True)
        self._wrap_update_method()
        return self

    def _wrap_method(self, method_name: str, mark_fault: bool = False) -> None:
        original = getattr(self.controller, method_name, None)
        if not callable(original) or getattr(original, "_runtime_status_wrapped", False):
            return

        @wraps(original)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if method_name == "reportVRMStatus" and args:
                self.last_vrm_status_name = _enum_name(args[0])
            if mark_fault:
                self.mark_fault()
            try:
                result = original(*args, **kwargs)
            except BaseException:
                self.mark_fault()
                self.publish()
                raise
            if method_name == "reportVRMStatus" and not self._update_in_progress:
                self.runtime_state_ready = True
            self.publish()
            return result

        wrapped._runtime_status_wrapped = True  # type: ignore[attr-defined]
        setattr(self.controller, method_name, wrapped)

    def _wrap_init_finalize_nonblocking(self) -> None:
        """Run the legacy Wattpilot bootstrap without its serial waits.

        The existing implementation starts the Wattpilot client's own automatic
        reconnect loop and then waits for several fields in sequence. A GX
        restart while the wallbox is offline can therefore stall service startup
        for minutes. For this one invocation, replace only its wait helper with
        an immediate predicate check. The original method still creates the
        client and enables its existing bounded reconnect behavior.
        """
        original = getattr(self.controller, "initFinalize", None)
        if not callable(original) or getattr(original, "_runtime_status_wrapped", False):
            return

        @wraps(original)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            method_globals = getattr(getattr(original, "__func__", original), "__globals__", None)
            helper_module = method_globals.get("Helper") if isinstance(method_globals, dict) else None
            original_wait = getattr(helper_module, "waitTimeout", None)
            wait_replaced = callable(original_wait)

            def immediate_wait(predicate: Callable[[], Any], _timeout: Any) -> bool:
                try:
                    return bool(predicate())
                except Exception:
                    return False

            if wait_replaced:
                try:
                    helper_module.waitTimeout = immediate_wait
                except Exception:
                    wait_replaced = False

            try:
                result = original(*args, **kwargs)
            except Exception as ex:
                # A partly-initialized offline Wattpilot is an expected startup
                # condition, not a control fault. The normal update path and the
                # client's reconnect loop will recover when data arrives.
                _LOG.warning("Wattpilot startup deferred until the client reconnects: %s", ex)
                result = None
            finally:
                if wait_replaced:
                    try:
                        helper_module.waitTimeout = original_wait
                    except Exception:
                        pass

            self._init_finalize_completed = True
            self.attach_wattpilot_events()
            self.publish(force=True)
            return result

        wrapped._runtime_status_wrapped = True  # type: ignore[attr-defined]
        setattr(self.controller, "initFinalize", wrapped)

    def _wrap_update_method(self) -> None:
        original = getattr(self.controller, "_update", None)
        if not callable(original) or getattr(original, "_runtime_status_wrapped", False):
            return

        @wraps(original)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            self.attach_wattpilot_events()
            generation_before_update = self._fault_generation

            # Do not call the legacy controller before the client has the basic
            # fields it dereferences. This is what makes an offline startup safe
            # and keeps its D-Bus contract responsive rather than blocking.
            if not self._controller_ready_for_update():
                self.publish_controller_transport_dashboard_status()
                return self.publish()

            completed = False
            self._update_in_progress = True
            try:
                result = original(*args, **kwargs)
                completed = True
                return result
            except BaseException:
                self.mark_fault()
                self.publish()
                raise
            finally:
                self._update_in_progress = False
                if completed:
                    self.runtime_state_ready = True
                if self._fault_generation == generation_before_update:
                    self.fault_active = False
                self.publish()

        wrapped._runtime_status_wrapped = True  # type: ignore[attr-defined]
        setattr(self.controller, "_update", wrapped)

    def _controller_ready_for_update(self) -> bool:
        wattpilot = getattr(self.controller, "wattpilot", None)
        if wattpilot is None or not bool(getattr(wattpilot, "connected", False)):
            return False
        if getattr(wattpilot, "mode", None) is None:
            return False
        return bool(getattr(wattpilot, "carStateReady", False))

    def _wrap_init_dbus_service(self) -> None:
        """Ensure contract paths exist before VeDbusService.register()."""
        original = getattr(self.controller, "initDbusService", None)
        if not callable(original) or getattr(original, "_runtime_status_wrapped", False):
            return

        @wraps(original)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            method_globals = getattr(getattr(original, "__func__", original), "__globals__", None)
            original_factory = None
            factory_replaced = False

            if isinstance(method_globals, dict) and callable(method_globals.get("VeDbusService")):
                original_factory = method_globals["VeDbusService"]

                def service_factory(*factory_args: Any, **factory_kwargs: Any) -> Any:
                    service = original_factory(*factory_args, **factory_kwargs)
                    register = getattr(service, "register", None)
                    if callable(register) and not getattr(register, "_runtime_status_wrapped", False):

                        @wraps(register)
                        def register_with_runtime_status(*register_args: Any, **register_kwargs: Any) -> Any:
                            self.controller.dbusService = service
                            self.register_dbus_paths()
                            return register(*register_args, **register_kwargs)

                        register_with_runtime_status._runtime_status_wrapped = True  # type: ignore[attr-defined]
                        try:
                            service.register = register_with_runtime_status
                        except Exception:
                            pass
                    return service

                method_globals["VeDbusService"] = service_factory
                factory_replaced = True

            try:
                result = original(*args, **kwargs)
            except BaseException:
                self.mark_fault()
                self.publish()
                raise
            finally:
                if factory_replaced and isinstance(method_globals, dict):
                    method_globals["VeDbusService"] = original_factory

            self.publish(force=True)
            return result

        wrapped._runtime_status_wrapped = True  # type: ignore[attr-defined]
        setattr(self.controller, "initDbusService", wrapped)

    def attach_wattpilot_events(self) -> None:
        """Record raw transport evidence without publishing from callbacks."""
        if self._wattpilot_events_attached:
            return
        wattpilot = getattr(self.controller, "wattpilot", None)
        if wattpilot is None:
            return
        add_handler = getattr(wattpilot, "add_event_handler", None)
        if not callable(add_handler):
            return
        try:
            from Wattpilot import Event
        except Exception:
            return

        attached = False
        for event_name in ("WS_MESSAGE", "WS_CLOSE", "WS_ERROR"):
            event = getattr(Event, event_name, None)
            if event is None:
                continue

            def event_callback(*_args: Any, _event_name: str = event_name, **_kwargs: Any) -> None:
                self._record_transport_event(_event_name)

            try:
                add_handler(event, event_callback)
                attached = True
            except Exception:
                continue
        self._wattpilot_events_attached = attached

    def _record_transport_event(self, event_name: str) -> None:
        """Record an event cheaply; do not touch D-Bus, MQTT, or control here."""
        now = time.monotonic()
        with self._transport_lock:
            if event_name == "WS_MESSAGE":
                self._last_wattpilot_message_at = now
                self._transport_has_healthy_baseline = True
            elif event_name == "WS_CLOSE":
                self._last_wattpilot_close_at = now
                self._last_wattpilot_message_at = None
            elif event_name == "WS_ERROR":
                self._last_wattpilot_error_at = now
                self._last_wattpilot_message_at = None

    def transport_unavailable_for_dashboard(self) -> bool:
        """Return whether the controller should mark dashboard status offline."""
        if not self._init_finalize_completed and not self.runtime_state_ready:
            return False
        if not self._wattpilot_connected():
            return True
        return self._transport_is_stale()

    def publish_controller_transport_dashboard_status(self) -> None:
        """Let the controller update its own standard EV-charger paths."""
        method = getattr(
            self.controller, "updateWattpilotTransportDashboardStatus", None
        )
        if not callable(method):
            return
        try:
            method()
        except Exception as ex:
            _LOG.warning(
                "Wattpilot dashboard transport status update failed: %s", ex
            )

    def _transport_is_stale(self) -> bool:
        """Return true only for a silent loss after a known-good baseline."""
        if not self._wattpilot_connected() or not self.runtime_state_ready:
            return False
        if not self._wattpilot_events_attached:
            return False
        with self._transport_lock:
            if not self._transport_has_healthy_baseline:
                return False
            last = self._last_wattpilot_message_at
        if last is None:
            return False
        age = time.monotonic() - last
        return age >= WATTPILOT_TELEMETRY_FRESH_SECONDS

    def register_dbus_paths(self) -> None:
        service = getattr(self.controller, "dbusService", None)
        if service is None:
            return
        registered = True
        for path, default in RUNTIME_STATUS_DBUS_DEFAULTS.items():
            try:
                _ensure_dbus_path(service, path, default)
            except Exception:
                registered = False
        self._dbus_paths_registered = registered

    def mark_fault(self) -> None:
        self.fault_active = True
        self._fault_generation += 1

    def publish(self, force: bool = False) -> RuntimeStatusSnapshot:
        """Best-effort publication that cannot interrupt Wattpilot control."""
        try:
            self.register_dbus_paths()
            snapshot = self.snapshot()
        except Exception:
            return self.last_snapshot or self._safe_default_snapshot()

        values = snapshot.as_dbus_values()
        service = getattr(self.controller, "dbusService", None)
        if service is not None:
            for path, value in values.items():
                _set_dbus_value(service, path, value)

        if force or snapshot != self.last_snapshot:
            for path, value in values.items():
                self._publish_mqtt(path, value)
            self.last_snapshot = snapshot
        return snapshot

    @staticmethod
    def _safe_default_snapshot() -> RuntimeStatusSnapshot:
        return RuntimeStatusSnapshot(
            control_state=CONTROL_STATE_STOPPED,
            control_state_literal=CONTROL_STATE_LITERALS[CONTROL_STATE_STOPPED],
            phase_mode=0,
            phase_mode_literal="Unknown",
            battery_assist_active=0,
            grid_import_guard_active=0,
            telemetry_healthy=0,
        )

    def _publish_mqtt(self, dbus_path: str, value: Any) -> None:
        publish = getattr(self.controller, "publishMainMqtt", None)
        if not callable(publish):
            return
        topic = "{0}/{1}".format(RUNTIME_STATUS_MQTT_PREFIX, RUNTIME_STATUS_TOPIC_SUFFIXES[dbus_path])
        try:
            publish(topic, value, retain=True)
        except TypeError:
            try:
                publish(topic, value)
            except Exception:
                return
        except Exception:
            return

    def snapshot(self) -> RuntimeStatusSnapshot:
        phase_mode, phase_literal = self._phase_mode()
        telemetry_healthy = int(self._telemetry_healthy())
        grid_guard = int(self._grid_import_guard_active())
        battery_assist = int(bool(getattr(self.controller, "batteryAssistActive", False)))
        control_state = self._control_state(
            phase_mode=phase_mode,
            telemetry_healthy=bool(telemetry_healthy),
            grid_guard=bool(grid_guard),
            battery_assist=bool(battery_assist),
        )

        # The public charging-state and phase-mode fields are one contract.
        # A manual Wattpilot start can report the standard VRM "Charging"
        # status before its individual phase-power attributes are populated.
        # In that short (or client-version-specific) gap, _control_state()
        # already classifies the active charge as one phase. Publish the matching
        # phase mode instead of the contradictory "Charging 1 phase" plus
        # "Unknown" pair. Pending switches return above as transition states,
        # so this cannot mask a requested phase change.
        if control_state == CONTROL_STATE_CHARGING_1_PHASE and phase_mode != 1:
            phase_mode, phase_literal = 1, "1 phase"
        elif control_state == CONTROL_STATE_CHARGING_3_PHASE and phase_mode != 3:
            phase_mode, phase_literal = 3, "3 phases"

        return RuntimeStatusSnapshot(
            control_state=control_state,
            control_state_literal=CONTROL_STATE_LITERALS[control_state],
            phase_mode=phase_mode,
            phase_mode_literal=phase_literal,
            battery_assist_active=battery_assist,
            grid_import_guard_active=grid_guard,
            telemetry_healthy=telemetry_healthy,
        )

    def _control_state(
        self,
        phase_mode: int,
        telemetry_healthy: bool,
        grid_guard: bool,
        battery_assist: bool,
    ) -> int:
        if self.fault_active:
            return CONTROL_STATE_FAULT
        if not self.runtime_state_ready:
            return CONTROL_STATE_STOPPED

        auto_mode = self._is_auto_mode()
        if not self._wattpilot_connected():
            return CONTROL_STATE_STOPPED

        pending_phase = getattr(self.controller, "pendingPhaseSwitchMode", 0)
        status_name = self.last_vrm_status_name or ""
        if pending_phase == 1 or status_name == "SwitchingTo1Phase":
            return CONTROL_STATE_SWITCHING_TO_1_PHASE
        if pending_phase == 2 or status_name == "SwitchingTo3Phase":
            return CONTROL_STATE_SWITCHING_TO_3_PHASE

        if auto_mode:
            if not self.telemetry_baseline_established:
                return CONTROL_STATE_STOPPED
            if not telemetry_healthy:
                return CONTROL_STATE_STOPPED_FOR_STALE_TELEMETRY
            if grid_guard:
                return CONTROL_STATE_STOPPED_FOR_GRID_IMPORT
            if battery_assist:
                return CONTROL_STATE_BATTERY_ASSIST

        if self._charge_is_active(status_name):
            return CONTROL_STATE_CHARGING_3_PHASE if phase_mode == 3 else CONTROL_STATE_CHARGING_1_PHASE

        if not auto_mode:
            return CONTROL_STATE_STOPPED

        if status_name in ("StopCharging", "Disconnected", "Charged"):
            return CONTROL_STATE_STOPPED
        return CONTROL_STATE_WAITING_FOR_STABLE_PV if self._has_minimum_allowance() else CONTROL_STATE_WAITING_FOR_PV

    def _phase_mode(self) -> Tuple[int, str]:
        pending = getattr(self.controller, "pendingPhaseSwitchMode", 0)
        if pending in (1, 2):
            return 0, "Transition"

        measured = self._measured_phase_mode()
        if measured == 1:
            return 1, "1 phase"
        if measured == 3:
            return 3, "3 phases"

        phase = getattr(self.controller, "currentPhaseMode", 0)
        if phase == 1:
            return 1, "1 phase"
        if phase in (2, 3):
            return 3, "3 phases"
        return 0, "Unknown"

    def _measured_phase_mode(self) -> Optional[int]:
        wattpilot = getattr(self.controller, "wattpilot", None)
        if wattpilot is None:
            return None
        powers = tuple(
            _finite_number_or_none(getattr(wattpilot, name, None))
            for name in ("power1", "power2", "power3")
        )
        if any(power is None for power in powers):
            return None
        l1, l2, l3 = (power > LIVE_PHASE_POWER_THRESHOLD_KW for power in powers)
        if l1 and l2 and l3:
            return 3
        if l1 and not l2 and not l3:
            return 1
        return None

    def _is_auto_mode(self) -> bool:
        mode = getattr(self.controller, "mode", None)
        name = _enum_name(mode)
        if name == "Auto":
            return True
        if name == "Manual":
            return False
        try:
            return int(getattr(mode, "value", mode)) == 1
        except (TypeError, ValueError):
            pass
        wattpilot_mode = getattr(getattr(self.controller, "wattpilot", None), "mode", None)
        return _enum_name(wattpilot_mode) == "ECO"

    def _wattpilot_connected(self) -> bool:
        wattpilot = getattr(self.controller, "wattpilot", None)
        return bool(wattpilot is not None and getattr(wattpilot, "connected", False))

    def _telemetry_healthy(self) -> bool:
        if not self.runtime_state_ready or not self._wattpilot_connected():
            return False
        if self._transport_is_stale():
            return False
        if not self._is_auto_mode() or bool(getattr(self.controller, "allowGridCharging", False)):
            return True

        grid_fresh = self._call_bool("gridTelemetryIsFresh")
        if grid_fresh is None:
            grid_fresh = self._fallback_grid_freshness()
        allowance_fresh = self._call_bool("allowanceIsFresh")
        if allowance_fresh is None:
            allowance_fresh = self._fallback_allowance_freshness()

        if not self.telemetry_baseline_established:
            if grid_fresh and allowance_fresh:
                self.telemetry_baseline_established = True
            else:
                return False
        return bool(grid_fresh and allowance_fresh)

    def _fallback_grid_freshness(self) -> bool:
        fresh_seconds = max(1, _number(getattr(self.controller, "gridTelemetryFreshSeconds", 15), 15))
        now = time.time()
        for phase in ("L1", "L2", "L3"):
            if not bool(getattr(self.controller, "grid{0}Valid".format(phase), False)):
                return False
            updated = _number(getattr(self.controller, "grid{0}UpdatedAt".format(phase), 0), 0)
            if updated <= 0 or now - updated > fresh_seconds:
                return False
        return True

    def _fallback_allowance_freshness(self) -> bool:
        if not hasattr(self.controller, "allowanceValid"):
            return True
        if not bool(getattr(self.controller, "allowanceValid", False)):
            return False
        fresh_seconds = max(1, _number(getattr(self.controller, "allowanceFreshSeconds", 15), 15))
        updated = _number(getattr(self.controller, "allowanceUpdatedAt", 0), 0)
        return updated > 0 and time.time() - updated <= fresh_seconds

    def _grid_import_guard_active(self) -> bool:
        if not self._is_auto_mode() or bool(getattr(self.controller, "allowGridCharging", False)):
            return False
        explicit = getattr(self.controller, "gridImportGuardActive", None)
        if explicit is not None:
            return bool(explicit)
        return _number(getattr(self.controller, "gridImportSince", 0), 0) > 0

    def _charge_is_active(self, status_name: str) -> bool:
        if status_name in ("Charging", "StartCharging"):
            return True
        wattpilot = getattr(self.controller, "wattpilot", None)
        if _number(getattr(wattpilot, "power", 0), 0) * 1000.0 > 50.0:
            return True
        model_status = getattr(wattpilot, "modelStatus", None)
        return getattr(model_status, "value", model_status) in (3, 12, 15, 19, 20)

    def _has_minimum_allowance(self) -> bool:
        result = self._call_bool("hasMinimumAllowance")
        if result is not None:
            return result
        allowance = _number(getattr(self.controller, "allowance", 0), 0)
        minimum = _number(getattr(self.controller, "minimumChargePower", 0), 0)
        if callable(getattr(self.controller, "minimumChargePower", None)):
            try:
                minimum = _number(self.controller.minimumChargePower(), 0)
            except Exception:
                minimum = 0
        return allowance >= minimum > 0

    def _call_bool(self, method_name: str) -> Optional[bool]:
        method = getattr(self.controller, method_name, None)
        if not callable(method):
            return None
        try:
            return bool(method())
        except Exception:
            return None


def attach_runtime_status_reporter(controller: Any) -> Optional[WattpilotRuntimeStatusReporter]:
    """Attach one reporter only to the FroniusWattpilot controller."""
    if controller.__class__.__name__ != "FroniusWattpilot":
        return None
    reporter = getattr(controller, "_runtime_status_reporter", None)
    if isinstance(reporter, WattpilotRuntimeStatusReporter):
        return reporter
    reporter = WattpilotRuntimeStatusReporter(controller).install()
    controller._runtime_status_reporter = reporter
    return reporter


def _ensure_dbus_path(service: Any, path: str, default: Any) -> None:
    try:
        service[path]
        return
    except (KeyError, TypeError, AttributeError):
        pass
    add_path = getattr(service, "add_path", None)
    if callable(add_path):
        try:
            add_path(path, default)
            return
        except Exception:
            try:
                service[path]
                return
            except Exception:
                raise
    service[path] = default


def _set_dbus_value(service: Any, path: str, value: Any) -> None:
    try:
        service[path] = value
    except Exception:
        return


def _enum_name(value: Any) -> str:
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return value if isinstance(value, str) else ""


def _finite_number_or_none(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _number(value: Any, default: float) -> float:
    number = _finite_number_or_none(value)
    return default if number is None else number
