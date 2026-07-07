"""Authoritative, retained runtime status for the Fronius Wattpilot service.

The Wattpilot's standard Victron ``/Status`` path deliberately remains owned by
VRM compatibility code.  This module publishes a separate, explicit contract
for dashboards, Cerbo extensions, MQTT consumers, and diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import wraps
import math
import time
from typing import Any, Callable, Dict, Iterable, Optional, Tuple


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


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    """The complete runtime-status contract at one point in time."""

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
    """Derives and publishes the public runtime-status contract.

    The existing FroniusWattpilot controller owns charging decisions.  The
    reporter only observes its stable controller fields and method outcomes;
    it never issues Wattpilot commands and therefore cannot change Manual mode
    or authorise grid/battery use.
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
        "initFinalize",
        "handleSigterm",
    )

    def __init__(self, controller: Any) -> None:
        self.controller = controller
        self.last_snapshot: Optional[RuntimeStatusSnapshot] = None
        self.last_vrm_status_name: Optional[str] = None
        self.fault_active = False
        self._fault_generation = 0
        self._dbus_paths_registered = False
        self._wattpilot_events_attached = False

    def install(self) -> "WattpilotRuntimeStatusReporter":
        """Install non-invasive instance wrappers around controller outcomes."""
        self._wrap_init_dbus_service()
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
            if method_name == "initFinalize":
                self.attach_wattpilot_events()
            self.publish()
            return result

        wrapped._runtime_status_wrapped = True  # type: ignore[attr-defined]
        setattr(self.controller, method_name, wrapped)

    def _wrap_update_method(self) -> None:
        original = getattr(self.controller, "_update", None)
        if not callable(original) or getattr(original, "_runtime_status_wrapped", False):
            return

        @wraps(original)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            generation_before_update = self._fault_generation
            try:
                return original(*args, **kwargs)
            except BaseException:
                self.mark_fault()
                self.publish()
                raise
            finally:
                # A subsequent successful controller cycle clears a previous
                # controller fault. A fault raised during this same cycle stays
                # visible until the next clean cycle.
                if self._fault_generation == generation_before_update:
                    self.fault_active = False
                self.publish()

        wrapped._runtime_status_wrapped = True  # type: ignore[attr-defined]
        setattr(self.controller, "_update", wrapped)

    def _wrap_init_dbus_service(self) -> None:
        """Ensure contract paths are installed before VeDbusService.register()."""
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
                            # Some VeDbusService implementations expose a
                            # read-only method. The post-initialisation
                            # fallback below still publishes the contract.
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

            # The fallback also supports test doubles and implementations that
            # do not expose a VeDbusService global.
            self.publish(force=True)
            return result

        wrapped._runtime_status_wrapped = True  # type: ignore[attr-defined]
        setattr(self.controller, "initDbusService", wrapped)

    def attach_wattpilot_events(self) -> None:
        """Publish promptly for Wattpilot connection and property events.

        The Wattpilot implementation exposes event callbacks on GX.  Wrapping
        ``connect`` and ``disconnect`` as a small fallback also keeps the
        contract timely for compatible Wattpilot implementations that do not
        expose the event API.  Neither wrapper changes a command or a result.
        """
        if self._wattpilot_events_attached:
            return

        wattpilot = getattr(self.controller, "wattpilot", None)
        if wattpilot is None:
            return

        attached = self._wrap_wattpilot_connection_methods(wattpilot)
        add_handler = getattr(wattpilot, "add_event_handler", None)
        if callable(add_handler):
            try:
                from Wattpilot import Event  # Imported only on the GX runtime.
            except Exception:
                Event = None

            if Event is not None:
                def event_callback(*_args: Any, **_kwargs: Any) -> None:
                    self.publish()

                for event_name in (
                    "WP_CONNECT",
                    "WP_DISCONNECT",
                    "WS_CLOSE",
                    "WP_AUTH_SUCCESS",
                    "WP_FULL_STATUS_FINISHED",
                    "WP_PROPERTY",
                ):
                    event = getattr(Event, event_name, None)
                    if event is None:
                        continue
                    try:
                        add_handler(event, event_callback)
                        attached = True
                    except Exception:
                        continue

        self._wattpilot_events_attached = attached

    def _wrap_wattpilot_connection_methods(self, wattpilot: Any) -> bool:
        """Observe direct connect/disconnect calls without changing them."""
        wrapped_any = False
        for method_name in ("connect", "disconnect"):
            original = getattr(wattpilot, method_name, None)
            if not callable(original) or getattr(original, "_runtime_status_wrapped", False):
                continue

            def make_wrapper(callable_method: Callable[..., Any]) -> Callable[..., Any]:
                @wraps(callable_method)
                def wrapped(*args: Any, **kwargs: Any) -> Any:
                    try:
                        return callable_method(*args, **kwargs)
                    finally:
                        self.publish()

                wrapped._runtime_status_wrapped = True  # type: ignore[attr-defined]
                return wrapped

            try:
                setattr(wattpilot, method_name, make_wrapper(original))
                wrapped_any = True
            except Exception:
                # Some implementations intentionally keep methods read-only;
                # their event callbacks still provide the immediate update.
                continue
        return wrapped_any

    def register_dbus_paths(self) -> None:
        service = getattr(self.controller, "dbusService", None)
        if service is None:
            return
        paths_registered = True
        for path, default in RUNTIME_STATUS_DBUS_DEFAULTS.items():
            try:
                _ensure_dbus_path(service, path, default)
            except Exception:
                # Runtime reporting must never interfere with the controller
                # if D-Bus is starting, restarting, or temporarily unhealthy.
                paths_registered = False
        self._dbus_paths_registered = paths_registered

    def mark_fault(self) -> None:
        self.fault_active = True
        self._fault_generation += 1

    def publish(self, force: bool = False) -> RuntimeStatusSnapshot:
        """Publish a best-effort snapshot without affecting charge control."""
        try:
            self.register_dbus_paths()
            snapshot = self.snapshot()
        except Exception:
            # A reporting-side failure must not propagate into an EV-control
            # callback. Keep the last coherent snapshot when possible.
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
        suffix = RUNTIME_STATUS_TOPIC_SUFFIXES[dbus_path]
        topic = "{0}/{1}".format(RUNTIME_STATUS_MQTT_PREFIX, suffix)
        try:
            publish(topic, value, retain=True)
        except TypeError:
            # Small stubs and older wrappers can expose a two-argument method.
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

        auto_mode = self._is_auto_mode()
        connected = self._wattpilot_connected()
        pending_phase = getattr(self.controller, "pendingPhaseSwitchMode", 0)
        status_name = self.last_vrm_status_name or ""

        # A physical disconnect is not a telemetry-fault diagnosis. It is a
        # normal stopped state and lets dashboards distinguish it from stale
        # grid/allowance data.
        if not connected:
            return CONTROL_STATE_STOPPED

        if pending_phase == 1 or status_name == "SwitchingTo1Phase":
            return CONTROL_STATE_SWITCHING_TO_1_PHASE
        if pending_phase == 2 or status_name == "SwitchingTo3Phase":
            return CONTROL_STATE_SWITCHING_TO_3_PHASE

        if auto_mode:
            if not telemetry_healthy:
                return CONTROL_STATE_STOPPED_FOR_STALE_TELEMETRY
            if grid_guard:
                return CONTROL_STATE_STOPPED_FOR_GRID_IMPORT
            if battery_assist:
                return CONTROL_STATE_BATTERY_ASSIST

        if self._charge_is_active(status_name):
            return (
                CONTROL_STATE_CHARGING_3_PHASE
                if phase_mode == 3
                else CONTROL_STATE_CHARGING_1_PHASE
            )

        if not auto_mode:
            return CONTROL_STATE_STOPPED

        # A deliberate Auto/Eco stop must remain visible until a subsequent
        # positive charging or waiting state replaces it. This is important for
        # a failed phase switch, where calling it a fault would be misleading.
        if status_name in ("StopCharging", "Disconnected", "Charged"):
            return CONTROL_STATE_STOPPED

        if self._has_minimum_allowance():
            return CONTROL_STATE_WAITING_FOR_STABLE_PV
        return CONTROL_STATE_WAITING_FOR_PV

    def _phase_mode(self) -> Tuple[int, str]:
        pending = getattr(self.controller, "pendingPhaseSwitchMode", 0)
        if pending in (1, 2):
            return 0, "Transition"
        phase = getattr(self.controller, "currentPhaseMode", 0)
        if phase == 1:
            return 1, "1 phase"
        if phase == 2 or phase == 3:
            return 3, "3 phases"
        return 0, "Unknown"

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
        if wattpilot is None:
            return False
        connected = getattr(wattpilot, "connected", None)
        return bool(connected)

    def _telemetry_healthy(self) -> bool:
        if not self._wattpilot_connected():
            return False
        if not self._is_auto_mode():
            return True
        if bool(getattr(self.controller, "allowGridCharging", False)):
            return True
        grid_fresh = self._call_bool("gridTelemetryIsFresh")
        if grid_fresh is None:
            grid_fresh = self._fallback_grid_freshness()
        if not grid_fresh:
            return False
        allowance_fresh = self._call_bool("allowanceIsFresh")
        if allowance_fresh is None:
            allowance_fresh = self._fallback_allowance_freshness()
        return bool(allowance_fresh)

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
        power_w = _number(getattr(wattpilot, "power", 0), 0) * 1000.0
        if power_w > 50.0:
            return True
        model_status = getattr(wattpilot, "modelStatus", None)
        model_value = getattr(model_status, "value", model_status)
        return model_value in (3, 12, 15, 19, 20)

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
    """Attach a reporter only to the FroniusWattpilot controller instance."""
    if controller.__class__.__name__ != "FroniusWattpilot":
        return None
    reporter = getattr(controller, "_runtime_status_reporter", None)
    if isinstance(reporter, WattpilotRuntimeStatusReporter):
        return reporter
    reporter = WattpilotRuntimeStatusReporter(controller).install()
    controller._runtime_status_reporter = reporter
    return reporter


def _ensure_dbus_path(service: Any, path: str, default: Any) -> None:
    """Add a D-Bus path once, including on simple mapping-based test doubles."""
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
            # A D-Bus service can reject an already-registered path. In that
            # case it is safe to continue because the path is already owned.
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
        # Do not make status observability capable of breaking charge control.
        # A later publication attempt will retry after the D-Bus service heals.
        return


def _enum_name(value: Any) -> str:
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    if isinstance(value, str):
        return value
    return ""


def _number(value: Any, default: float) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default
