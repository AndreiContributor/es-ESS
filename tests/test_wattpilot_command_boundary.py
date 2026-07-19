"""Hardware-free regressions for Wattpilot writable command boundaries."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def _module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _install_runtime_stubs():
    paho = _module("paho")
    paho.__path__ = []
    paho_mqtt = _module("paho.mqtt")
    paho_mqtt.__path__ = []
    paho_mqtt_client = _module("paho.mqtt.client", Client=object)
    paho.mqtt = paho_mqtt
    paho_mqtt.client = paho_mqtt_client

    _module("vedbus", VeDbusService=object)
    _module("requests")
    _module(
        "Globals",
        esEssTagService="test",
        esEssTag="test",
        currentVersionString="test",
    )
    _module(
        "Helper",
        i=lambda *args, **kwargs: None,
        c=lambda *args, **kwargs: None,
        d=lambda *args, **kwargs: None,
        w=lambda *args, **kwargs: None,
        e=lambda *args, **kwargs: None,
        t=lambda *args, **kwargs: None,
        dbusConnection=lambda: None,
        waitTimeout=lambda *args, **kwargs: False,
    )
    _module("Wattpilot", Wattpilot=type("Wattpilot", (), {}))
    _module("esESSService", esESSService=type("esESSService", (), {}))

    sys.modules.pop("enums", None)
    _load_module("enums", ROOT / "enums.py")


class WattpilotCommandBoundaryTests(unittest.TestCase):
    """Lock direct D-Bus command writes to confirmed Wattpilot ECO mode."""

    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.fwp = _load_module(
            "wattpilot_command_boundary_fwp_under_test",
            ROOT / "FroniusWattpilot.py",
        )

    def _controller(self):
        controller = self.fwp.FroniusWattpilot.__new__(self.fwp.FroniusWattpilot)
        controller.minCurrentPerPhase = 6
        controller.maxCurrentPerPhase = 16
        controller.currentPhaseMode = 1
        controller.powerTransitionUntil = 0
        controller.mode = self.fwp.VrmEvChargerControlMode.Auto
        controller.autostart = 1
        controller.validatedVenusOsVersion = "v3.75"
        controller.validatedWattpilotFirmware = "42.5"
        controller.validatedWattpilotAppVersion = "2.1.0"
        controller.actualVenusOsVersion = "v3.75"
        controller.actualWattpilotFirmware = "42.5"
        controller.wattpilotFirmwareCompatible = True
        controller._lastWattpilotCompatibilityState = (True, "42.5")
        controller.commandAuthorityOk = True
        controller.commandAuthorityLiteral = self.fwp.COMMAND_AUTHORITY_VALIDATED
        controller._lastCommandAuthorityState = (
            True,
            self.fwp.COMMAND_AUTHORITY_VALIDATED,
        )
        controller.commandAuthorityForcedOff = False
        controller.siteMaxCurrent = 20
        controller.charger1PhaseMapping = "L1"
        controller.siteCurrentFreshSeconds = 15
        controller.siteCurrentRecoverySeconds = 30
        controller.siteCurrentRecoverySince = {
            1: self.fwp.time.time() - 31,
            2: self.fwp.time.time() - 31,
        }
        controller.siteCurrentGuardBlocked = False
        controller.siteCurrentGuardReason = "Site-current headroom available"
        controller.siteCurrentAllowedCurrent = 16
        controller.siteCurrentLimitingPhase = "L1"
        controller.siteCurrentHeadrooms = (20, 20, 20)
        for phase in ("L1", "L2", "L3"):
            setattr(controller, "siteCurrent{0}Value".format(phase), 0)
            setattr(controller, "siteCurrent{0}Valid".format(phase), True)
            setattr(
                controller,
                "siteCurrent{0}UpdatedAt".format(phase),
                self.fwp.time.time(),
            )
        controller.dbusService = {
            "/Mode": self.fwp.VrmEvChargerControlMode.Auto.value,
            "/ModeLiteral": self.fwp.VrmEvChargerControlMode.Auto.name,
            "/StartStop": self.fwp.VrmEvChargerStartStop.Stop.value,
            "/StartStopLiteral": self.fwp.VrmEvChargerStartStop.Stop.name,
        }
        controller.wattpilot = SimpleNamespace(
            ampLimit=None,
            amp=0,
            amps1=0,
            amps2=0,
            amps3=0,
            energyTelemetryUpdatedAt=self.fwp.time.time(),
            firmware="42.5",
            voltage1=230,
            mode=self.fwp.WattpilotControlMode.ECO,
            nativePvSurplusEnabled=False,
            flexibleTariffEnabled=False,
            set_power=Mock(),
            set_phases=Mock(),
            set_start_stop=Mock(),
            set_mode=Mock(),
        )
        controller.serviceMessages = []
        controller.publishServiceMessage = (
            lambda _service, message, *args, **kwargs:
            controller.serviceMessages.append(message)
        )
        controller.dumpEvChargerInfo = Mock()
        controller.clearChargeCompleteHold = Mock()
        return controller

    def test_wattpilot_firmware_mismatch_blocks_command_authorization(self):
        controller = self._controller()
        controller.wattpilot.firmware = "42.6"

        self.assertFalse(controller.allowWattpilotCommand("amp", 6))
        self.assertFalse(controller.wattpilotFirmwareCompatible)
        self.assertEqual(controller.actualWattpilotFirmware, "42.6")
        self.assertIn("All es-ESS Wattpilot commands are blocked", controller.serviceMessages[-1])

    def test_missing_wattpilot_firmware_blocks_command_authorization(self):
        controller = self._controller()
        controller.wattpilot.firmware = None

        self.assertFalse(controller.allowWattpilotCommand("frc", 2))
        self.assertFalse(controller.wattpilotFirmwareCompatible)
        self.assertIn("<unavailable>", controller.serviceMessages[-1])

    def test_set_current_is_rejected_when_wattpilot_reports_manual_mode(self):
        controller = self._controller()
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default

        self.assertFalse(controller._froniusHandleChangedValue("/SetCurrent", 12))

        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_phases.assert_not_called()
        self.assertIn("/SetCurrent", controller.serviceMessages[-1])
        controller.dumpEvChargerInfo.assert_called_once()

    def test_start_stop_is_rejected_when_wattpilot_reports_manual_mode(self):
        controller = self._controller()
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default

        self.assertFalse(
            controller._froniusHandleChangedValue(
                "/StartStop",
                self.fwp.VrmEvChargerStartStop.Start.value,
            )
        )
        self.assertFalse(
            controller._froniusHandleChangedValue(
                "/StartStop",
                self.fwp.VrmEvChargerStartStop.Stop.value,
            )
        )

        controller.wattpilot.set_start_stop.assert_not_called()
        self.assertEqual(
            controller.dbusService["/StartStopLiteral"],
            self.fwp.VrmEvChargerStartStop.Stop.name,
        )
        self.assertEqual(len(controller.serviceMessages), 2)
        self.assertTrue(
            all("/StartStop" in message for message in controller.serviceMessages)
        )

    def test_missing_wattpilot_mode_telemetry_fails_closed(self):
        controller = self._controller()
        delattr(controller.wattpilot, "mode")

        self.assertFalse(controller._froniusHandleChangedValue("/SetCurrent", 12))

        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_phases.assert_not_called()
        self.assertIn("select Auto", controller.serviceMessages[-1])

    def test_next_trip_mode_telemetry_fails_closed(self):
        controller = self._controller()
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.NextTrip

        self.assertFalse(controller._froniusHandleChangedValue("/SetCurrent", 12))
        self.assertFalse(
            controller._froniusHandleChangedValue(
                "/StartStop",
                self.fwp.VrmEvChargerStartStop.Start.value,
            )
        )

        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()
        self.assertEqual(len(controller.serviceMessages), 2)
        self.assertTrue(
            all(
                "select Auto" in message
                for message in controller.serviceMessages
            )
        )

    def test_native_pv_or_tariff_blocks_positive_auto_commands(self):
        for attribute in ("nativePvSurplusEnabled", "flexibleTariffEnabled"):
            controller = self._controller()
            setattr(controller.wattpilot, attribute, True)

            self.assertFalse(
                controller._froniusHandleChangedValue("/SetCurrent", 12)
            )
            self.assertFalse(
                controller._froniusHandleChangedValue(
                    "/StartStop",
                    self.fwp.VrmEvChargerStartStop.Start.value,
                )
            )

            controller.wattpilot.set_power.assert_not_called()
            controller.wattpilot.set_phases.assert_not_called()
            controller.wattpilot.set_start_stop.assert_not_called()

    def test_invalid_authority_still_allows_zero_current_and_safe_stop(self):
        controller = self._controller()
        controller.wattpilot.nativePvSurplusEnabled = True

        self.assertTrue(controller._froniusHandleChangedValue("/SetCurrent", 0))
        self.assertTrue(
            controller._froniusHandleChangedValue(
                "/StartStop",
                self.fwp.VrmEvChargerStartStop.Stop.value,
            )
        )

        controller.wattpilot.set_power.assert_called_once_with(0)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )
        controller.wattpilot.set_phases.assert_not_called()

    def test_auto_selection_requires_observed_disabled_native_settings(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Manual
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default
        controller.wattpilot.nativePvSurplusEnabled = True

        self.assertFalse(
            controller.switchMode(
                self.fwp.VrmEvChargerControlMode.Manual,
                self.fwp.VrmEvChargerControlMode.Auto,
            )
        )

        controller.wattpilot.set_mode.assert_not_called()
        self.assertEqual(controller.mode, self.fwp.VrmEvChargerControlMode.Manual)
        self.assertIn("Auto selection rejected", controller.serviceMessages[-1])

    def test_mode_callback_reports_rejected_auto_selection(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Manual
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default
        controller.wattpilot.nativePvSurplusEnabled = True

        accepted = controller._froniusHandleChangedValue(
            "/Mode", self.fwp.VrmEvChargerControlMode.Auto.value
        )

        self.assertFalse(accepted)
        self.assertEqual(controller.mode, self.fwp.VrmEvChargerControlMode.Manual)
        controller.wattpilot.set_mode.assert_not_called()

    def test_auto_selection_requires_validated_firmware(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Manual
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default
        controller.wattpilotFirmwareCompatible = False

        accepted = controller._froniusHandleChangedValue(
            "/Mode", self.fwp.VrmEvChargerControlMode.Auto.value
        )

        self.assertFalse(accepted)
        self.assertEqual(controller.mode, self.fwp.VrmEvChargerControlMode.Manual)
        controller.wattpilot.set_mode.assert_not_called()
        self.assertIn("firmware compatibility", controller.serviceMessages[-1])

    def test_mode_publication_correlates_matching_raw_lmo_once(self):
        controller = self._controller()
        controller.publish = Mock()
        controller.wattpilot.modeChangedAt = 100.25
        controller.wattpilot.modeUpdatedAt = 104.5

        with (
            patch.object(self.fwp, "i") as info_log,
            patch.object(self.fwp.time, "time", return_value=105.0),
        ):
            controller.reportModeTelemetry()
            controller.reportModeTelemetry()

        self.assertEqual(
            controller.publish.call_args_list,
            [
                unittest.mock.call(
                    "/Mode", self.fwp.VrmEvChargerControlMode.Auto.value
                ),
                unittest.mock.call(
                    "/ModeLiteral", self.fwp.VrmEvChargerControlMode.Auto.name
                ),
                unittest.mock.call(
                    "/Mode", self.fwp.VrmEvChargerControlMode.Auto.value
                ),
                unittest.mock.call(
                    "/ModeLiteral", self.fwp.VrmEvChargerControlMode.Auto.name
                ),
            ],
        )
        info_log.assert_called_once()
        message = info_log.call_args.args[1]
        self.assertIn("raw lmo=4 (ECO)", message)
        self.assertIn("lmo_changed_at_epoch=100.250", message)
        self.assertIn("lmo_received_at_epoch=104.500", message)
        self.assertIn("/ModeLiteral=Auto", message)
        self.assertIn("published_at_epoch=105.000", message)

    def test_missing_mode_does_not_emit_raw_mode_publication_diagnostic(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Manual
        controller.wattpilot.mode = None
        controller.publish = Mock()

        with patch.object(self.fwp, "i") as info_log:
            controller.reportModeTelemetry()

        info_log.assert_not_called()

    def _prepare_disconnected_idle_update(self, controller):
        controller.wattpilot.connected = True
        controller.wattpilot.carStateReady = True
        controller.wattpilot.carConnected = False
        controller.wattpilot.power = 0
        controller.wattpilot.modelStatus = SimpleNamespace(value=1)
        controller.updateWattpilotTransportDashboardStatus = Mock(return_value=False)
        controller.refreshWattpilotFirmwareCompatibility = Mock(return_value=True)
        controller.updateEffectiveCarConnection = Mock(return_value=False)
        controller.isIdleMode = True
        controller.isHibernateEnabled = False
        controller.lastVarDump = 100.0
        controller.reportStartStopValue = Mock()
        controller.publishSafetyTelemetry = Mock()
        controller.gridTelemetryIsFresh = Mock(return_value=True)
        controller.selectControlState = Mock(
            return_value=(
                self.fwp.ControlStates.WattpilotControlState.DISCONNECTED,
                None,
                None,
            )
        )
        controller.dispatchControlState = Mock(return_value=True)
        controller.reportBaseRequest = Mock()
        controller.publish = Mock(
            side_effect=lambda path, value: controller.dbusService.__setitem__(
                path, value
            )
        )
        controller.dumpEvChargerInfo = controller.reportModeTelemetry

    def test_disconnected_manual_transition_bypasses_idle_throttle_once(self):
        controller = self._controller()
        self._prepare_disconnected_idle_update(controller)
        controller.mode = self.fwp.VrmEvChargerControlMode.Auto
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default
        controller.wattpilot.modeChangedAt = 200.25
        controller.wattpilot.modeUpdatedAt = 200.25
        controller._lastPublishedModeDiagnostic = (
            self.fwp.WattpilotControlMode.ECO,
            150.0,
            self.fwp.VrmEvChargerControlMode.Auto,
        )

        with patch.object(self.fwp.time, "time", return_value=205.0):
            controller._update()

        self.assertEqual(
            controller.dbusService["/ModeLiteral"],
            self.fwp.VrmEvChargerControlMode.Manual.name,
        )
        controller.wattpilot.set_phases.assert_called_once_with(0)
        controller.wattpilot.set_power.assert_called_once_with(
            controller.getEffectiveMaxCurrent()
        )
        controller.dispatchControlState.assert_called_once()
        self.assertEqual(controller.lastVarDump, 205.0)
        self.assertFalse(controller.modeTelemetryNeedsControllerCycle())

        controller.wattpilot.set_phases.reset_mock()
        controller.wattpilot.set_power.reset_mock()
        controller.dispatchControlState.reset_mock()
        controller.publish.reset_mock()

        with patch.object(self.fwp.time, "time", return_value=210.0):
            controller._update()

        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_not_called()
        controller.dispatchControlState.assert_not_called()
        controller.publish.assert_not_called()
        self.assertEqual(controller.lastVarDump, 205.0)

    def test_disconnected_eco_transition_publishes_without_commands(self):
        controller = self._controller()
        self._prepare_disconnected_idle_update(controller)
        controller.mode = self.fwp.VrmEvChargerControlMode.Manual
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.ECO
        controller.wattpilot.modeChangedAt = 300.5
        controller.wattpilot.modeUpdatedAt = 300.5
        controller._lastPublishedModeDiagnostic = (
            self.fwp.WattpilotControlMode.Default,
            250.0,
            self.fwp.VrmEvChargerControlMode.Manual,
        )

        with patch.object(self.fwp.time, "time", return_value=305.0):
            controller._update()

        self.assertEqual(
            controller.dbusService["/ModeLiteral"],
            self.fwp.VrmEvChargerControlMode.Auto.name,
        )
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()
        controller.dispatchControlState.assert_called_once()
        self.assertFalse(controller.modeTelemetryNeedsControllerCycle())

    def test_eco_mode_accepts_direct_current_and_start_stop_writes(self):
        controller = self._controller()

        self.assertTrue(controller._froniusHandleChangedValue("/SetCurrent", 18))

        controller.wattpilot.set_phases.assert_called_once_with(2)
        controller.wattpilot.set_power.assert_called_once_with(6)

        self.assertTrue(
            controller._froniusHandleChangedValue(
                "/StartStop",
                self.fwp.VrmEvChargerStartStop.Start.value,
            )
        )

        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.On
        )
        self.assertEqual(
            controller.dbusService["/StartStopLiteral"],
            self.fwp.VrmEvChargerStartStop.Start.name,
        )

    def test_mode_write_can_still_select_auto_and_manual(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Manual
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default

        self.assertTrue(
            controller._froniusHandleChangedValue(
                "/Mode",
                self.fwp.VrmEvChargerControlMode.Auto.value,
            )
        )

        controller.wattpilot.set_mode.assert_called_once_with(
            self.fwp.WattpilotControlMode.ECO
        )
        self.assertEqual(controller.autostart, 1)
        self.assertEqual(
            controller.dbusService["/ModeLiteral"],
            self.fwp.VrmEvChargerControlMode.Auto.name,
        )

        controller.wattpilot.set_mode.reset_mock()
        controller.mode = self.fwp.VrmEvChargerControlMode.Auto
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.ECO

        self.assertTrue(
            controller._froniusHandleChangedValue(
                "/Mode",
                self.fwp.VrmEvChargerControlMode.Manual.value,
            )
        )

        controller.wattpilot.set_mode.assert_called_once_with(
            self.fwp.WattpilotControlMode.Default
        )
        controller.wattpilot.set_phases.assert_called_once_with(0)
        controller.wattpilot.set_power.assert_called_once_with(
            controller.getEffectiveMaxCurrent()
        )
        controller.clearChargeCompleteHold.assert_called_once_with(
            "manual mode selected"
        )
        self.assertEqual(controller.autostart, 0)
        self.assertEqual(
            controller.dbusService["/ModeLiteral"],
            self.fwp.VrmEvChargerControlMode.Manual.name,
        )

    def test_observed_manual_mode_releases_auto_phase_and_current_once(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Auto
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default
        controller.wattpilot.connected = True
        controller.wattpilot.carStateReady = True
        controller.wattpilot.carConnected = True
        controller.wattpilot.power = 1.4
        controller.wattpilot.modelStatus = SimpleNamespace(value=15)
        controller.updateWattpilotTransportDashboardStatus = Mock(return_value=False)
        controller.updateEffectiveCarConnection = Mock(return_value=True)
        controller.isIdleMode = False
        controller.lastVarDump = 0
        controller.reportStartStopValue = Mock()
        controller.publishSafetyTelemetry = Mock()
        controller.gridTelemetryIsFresh = Mock(return_value=True)
        controller.selectControlState = Mock(
            return_value=(
                self.fwp.ControlStates.WattpilotControlState.CHARGING,
                None,
                None,
            )
        )
        controller.dispatchControlState = Mock(return_value=False)
        controller.reportBaseRequest = Mock()

        controller._update()

        controller.wattpilot.set_phases.assert_called_once_with(0)
        controller.wattpilot.set_power.assert_called_once_with(
            controller.getEffectiveMaxCurrent()
        )
        controller.dispatchControlState.assert_called_once_with(
            self.fwp.ControlStates.WattpilotControlState.CHARGING,
            True,
            None,
        )

        controller.wattpilot.set_phases.reset_mock()
        controller.wattpilot.set_power.reset_mock()
        controller.dispatchControlState.reset_mock()

        controller._update()

        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_not_called()
        controller.dispatchControlState.assert_called_once_with(
            self.fwp.ControlStates.WattpilotControlState.CHARGING,
            True,
            None,
        )


if __name__ == "__main__":
    unittest.main()
