"""Hardware-free regression tests for the Auto/Eco PV charging policy.

The tests load the real controller with lightweight stand-ins for Venus OS,
MQTT, and Wattpilot dependencies.  Every decision is driven by explicit,
fixed timestamps so no test requires a charger, broker, D-Bus, or battery.
"""

import importlib.util
import sys
import types
import unittest
from enum import IntEnum
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

    class VrmEvChargerControlMode:
        Manual = 0
        Auto = 1
        Scheduled = 2

    class VrmEvChargerStatus:
        Disconnected = 0
        Connected = 1
        WaitingForSun = 2
        StartCharging = 3
        StopCharging = 4
        Charging = 5
        SwitchingTo1Phase = 6
        SwitchingTo3Phase = 7
        Charged = 8

    class WattpilotStartStop:
        Off = 0
        On = 1

    class WattpilotControlMode:
        Default = 0
        ECO = 1

    class WattpilotModelStatus:
        ChargingBecauseAwattarPriceLow = object()
        NotChargingBecausePhaseSwitch = object()

    class VrmEvChargerStartStop(IntEnum):
        Stop = 0
        Start = 1

    _module(
        "enums",
        VrmEvChargerControlMode=VrmEvChargerControlMode,
        VrmEvChargerStatus=VrmEvChargerStatus,
        VrmEvChargerStartStop=VrmEvChargerStartStop,
        WattpilotModelStatus=WattpilotModelStatus,
        WattpilotStartStop=WattpilotStartStop,
        WattpilotControlMode=WattpilotControlMode,
    )
    _module("Wattpilot", Wattpilot=type("Wattpilot", (), {}))
    _module("esESSService", esESSService=type("esESSService", (), {}))


class EcoPvPolicyRegressionTests(unittest.TestCase):
    """Lock the expected Auto/Eco behavior without real hardware."""

    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.fwp = _load_module(
            "eco_pv_fwp_under_test", ROOT / "FroniusWattpilot.py"
        )

    def _controller(self):
        controller = self.fwp.FroniusWattpilot.__new__(self.fwp.FroniusWattpilot)
        controller.minCurrentPerPhase = 6
        controller.maxCurrentPerPhase = 16
        controller.threePhasePvSurplusStartW = 4200
        controller.threePhasePvSurplusStopW = 4140
        controller.phaseSwitchCandidateMode = 0
        controller.phaseSwitchCandidateSince = 0
        controller.phaseSwitchBelowThresholdSince = 0
        controller.minimumOnOffSeconds = 300
        controller.minimumPhaseSwitchSeconds = 300
        controller.lastOnOffTime = 0
        # The controller treats zero as an epoch timestamp. Use an already
        # expired value because the tests deliberately run with small clocks.
        controller.lastPhaseSwitchTime = -controller.minimumPhaseSwitchSeconds
        controller.currentPhaseMode = 1

        controller.allowance = 0
        controller.allowanceValid = True
        controller.allowanceFreshSeconds = 15
        controller.allowanceUpdatedAt = 100
        controller.allowanceBelowMinimumSince = 0
        controller.surplusSince = 0
        controller.surplusBelowMinimumSince = 0
        controller.surplusDropGraceSeconds = 20
        controller.allowanceDropGraceSeconds = 15
        controller.noAllowanceForcedOff = False
        controller.siteCurrentForcedOff = False

        controller.siteMaxCurrent = 20
        controller.charger1PhaseMapping = "L1"
        controller.siteCurrentFreshSeconds = 15
        controller.siteCurrentRecoverySeconds = 30
        controller.siteCurrentRecoverySince = {1: 1, 2: 1}
        controller.siteCurrentGuardBlocked = False
        controller.siteCurrentGuardReason = "Site-current headroom available"
        controller.siteCurrentAllowedCurrent = 16
        controller.siteCurrentLimitingPhase = "L1"
        controller.siteCurrentHeadrooms = (20, 20, 20)
        for phase in ("L1", "L2", "L3"):
            setattr(controller, "siteCurrent{0}Value".format(phase), 0)
            setattr(controller, "siteCurrent{0}Valid".format(phase), True)
            setattr(controller, "siteCurrent{0}UpdatedAt".format(phase), 100)

        controller.batteryAssistEnabled = True
        controller.batteryAssistSocMin = 60
        controller.batteryAssistMaxSeconds = 300
        controller.batteryAssistMaxShortfallPerPhaseW = 1500
        controller.batterySocFreshSeconds = 15
        controller.batteryAssistRecoverySeconds = 60
        controller.batteryAssistSince = 0
        controller.batteryAssistDeficitSince = 0
        controller.batteryAssistActive = False
        controller.batteryAssistShortfallW = 0
        controller.batteryAssistShortfallPerPhaseW = 0
        controller.batteryAssistActivePhases = 0
        controller.batteryAssistEffectiveLimitW = 0
        controller.batteryAssistLockedOut = False
        controller.batteryAssistLockoutSince = 0
        controller.batteryAssistRecoverySince = 0
        controller.minimumCurrentReductionAt = 0
        controller.minimumCurrentReductionPhaseMode = 0

        controller.allowGridCharging = False
        controller.gridImportPositive = True
        controller.gridImportStopW = 150
        controller.gridImportStopSeconds = 5
        controller.gridTelemetryFreshSeconds = 15
        controller.gridImportSince = 0

        controller.startupGraceSeconds = 60
        controller.startupTelemetryRatio = 0.8
        controller.powerTransitionUntil = 0
        controller.powerTransitionExpectedW = 0
        controller.powerTransitionReason = ""
        controller.powerTransitionTelemetryReadyAt = 0
        controller.pendingPhaseSwitchMode = 0
        controller.pendingPhaseSwitchSince = 0

        controller.rawOverheadFreshSeconds = 15
        controller.mqttRawOverheadW = None
        controller.mqttRawOverheadUpdatedAt = 0
        controller.mqttAllowanceTopic = (
            "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Allowance"
        )
        controller.mqttRawOverheadTopic = (
            "es-ESS/SolarOverheadDistributor/Calculations/OverheadAvailable"
        )

        controller.mode = self.fwp.VrmEvChargerControlMode.Auto
        controller.autostart = 1
        controller.isIdleMode = False
        controller.isHibernateEnabled = False
        controller.lastVarDump = 0
        controller.chargingTime = 0
        controller.noChargeSince = 0
        controller.chargeCompleteHold = False
        controller.chargeCompleteSince = 0
        controller.chargeCompleteResumeSince = 0
        controller.chargeCompletePowerThresholdW = 100
        controller.chargeCompleteConfirmSeconds = 120
        controller.chargeCompleteResumePowerW = 300
        controller.chargeCompleteResumeSeconds = 30

        controller.carDisconnectConfirmSeconds = 15
        controller.carDisconnectedSince = 0
        controller.lastConfirmedCarConnected = False
        controller.effectiveCarConnected = True

        controller.evPriorityOverBatteryCharge = False
        controller.evPriorityMinSoc = 0
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
        controller.config = {
            "FroniusWattpilot": {
                "VRMInstanceID_OverheadRequest": "42",
                "OverheadPriority": "35",
            }
        }

        controller.wattpilot = SimpleNamespace(
            ampLimit=None,
            firmware="42.5",
            voltage1=230,
            voltage2=230,
            voltage3=230,
            power=0,
            power1=0,
            power2=0,
            power3=0,
            amp=6,
            amps1=6,
            amps2=6,
            amps3=6,
            energyTelemetryUpdatedAt=100,
            carConnected=True,
            carStateReady=True,
            connected=True,
            startState=self.fwp.WattpilotStartStop.Off,
            mode=self.fwp.WattpilotControlMode.ECO,
            nativePvSurplusEnabled=False,
            flexibleTariffEnabled=False,
            modelStatus=SimpleNamespace(value=4),
            set_power=Mock(),
            set_phases=Mock(),
            set_start_stop=Mock(),
            set_mode=Mock(),
        )

        controller.batterySocDbus = SimpleNamespace(value=80)
        controller.batterySocValid = True
        controller.batteryPowerDbus = SimpleNamespace(value=0)
        controller.batteryTelemetryValid = True
        controller.batteryTelemetryUpdatedAt = 100
        controller.gridL1Dbus = SimpleNamespace(value=0)
        controller.gridL2Dbus = SimpleNamespace(value=0)
        controller.gridL3Dbus = SimpleNamespace(value=0)
        controller.gridL1Valid = True
        controller.gridL2Valid = True
        controller.gridL3Valid = True
        controller.gridL1UpdatedAt = 100
        controller.gridL2UpdatedAt = 100
        controller.gridL3UpdatedAt = 100
        controller.overheadAvailableDbus = SimpleNamespace(value=0)

        controller.dbusService = {"/StartStop": 0, "/StartStopLiteral": "Stop"}
        controller.publishServiceMessage = lambda *args, **kwargs: None
        controller.publishMainMqtt = lambda *args, **kwargs: None
        controller.publishRetained = lambda *args, **kwargs: None
        controller.publish = lambda *args, **kwargs: None
        controller.reportVRMStatus = lambda *args, **kwargs: None
        controller.reportPhaseMode = lambda *args, **kwargs: None
        controller.reportConsumption = lambda *args, **kwargs: None
        controller.dumpEvChargerInfo = lambda *args, **kwargs: None
        return controller

    @staticmethod
    def _fresh_grid(controller, timestamp):
        controller.gridL1Valid = True
        controller.gridL2Valid = True
        controller.gridL3Valid = True
        controller.gridL1UpdatedAt = timestamp
        controller.gridL2UpdatedAt = timestamp
        controller.gridL3UpdatedAt = timestamp

    @staticmethod
    def _fresh_site(controller, timestamp):
        for phase in ("L1", "L2", "L3"):
            setattr(controller, "siteCurrent{0}Valid".format(phase), True)
            setattr(controller, "siteCurrent{0}UpdatedAt".format(phase), timestamp)
        controller.wattpilot.energyTelemetryUpdatedAt = timestamp

    def _set_allowance(self, controller, watts, timestamp):
        controller.allowance = watts
        controller.allowanceValid = True
        controller.allowanceUpdatedAt = timestamp
        self._fresh_grid(controller, timestamp)
        self._fresh_site(controller, timestamp)

    def test_one_phase_start_waits_for_the_stable_pv_timer(self):
        controller = self._controller()
        controller.surplusSince = 100
        self._set_allowance(controller, 1380, 399)

        with patch.object(self.fwp.time, "time", return_value=399):
            controller.handleNotChargingState()

        controller.wattpilot.set_start_stop.assert_not_called()

        with patch.object(self.fwp.time, "time", return_value=400):
            controller.handleNotChargingState()

        self.assertEqual(controller.currentPhaseMode, 1)
        controller.wattpilot.set_phases.assert_called_once_with(1)
        controller.wattpilot.set_power.assert_called_once_with(6)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.On
        )

    def test_new_charge_starts_directly_on_three_phases_with_full_pv_allowance(self):
        controller = self._controller()
        controller.surplusSince = 100
        self._set_allowance(controller, 4200, 400)

        with patch.object(self.fwp.time, "time", return_value=400):
            controller.handleNotChargingState()

        self.assertEqual(controller.currentPhaseMode, 2)
        controller.wattpilot.set_phases.assert_called_once_with(2)
        controller.wattpilot.set_power.assert_called_once_with(6)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.On
        )

    def test_restart_after_a_stop_waits_for_min_on_off_seconds(self):
        controller = self._controller()
        controller.minimumOnOffSeconds = 60

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.forceStopForNoAllowance()

        controller.wattpilot.set_phases.reset_mock()
        controller.wattpilot.set_power.reset_mock()
        controller.wattpilot.set_start_stop.reset_mock()

        # PV can already be stable when the stop cooldown begins.  This test
        # isolates MinOnOffSeconds instead of adding a second, independent
        # stable-PV delay (covered by the start-timer test above).
        controller.surplusSince = 100
        self._set_allowance(controller, 1380, 159)
        with patch.object(self.fwp.time, "time", return_value=159):
            controller.handleNotChargingState()

        controller.wattpilot.set_start_stop.assert_not_called()

        self._set_allowance(controller, 1380, 160)
        with patch.object(self.fwp.time, "time", return_value=160):
            controller.handleNotChargingState()

        self.assertEqual(controller.lastOnOffTime, 160)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.On
        )

    def test_battery_assist_never_starts_a_charge_without_real_pv_allowance(self):
        controller = self._controller()
        controller.mqttRawOverheadW = 5000
        controller.mqttRawOverheadUpdatedAt = 100
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertFalse(controller.startOrContinueBatteryAssist(1000))
            controller.startFromPvAllowance()

        self.assertFalse(controller.batteryAssistActive)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()

    def test_allowance_freshness_requires_valid_recent_assigned_allowance(self):
        controller = self._controller()
        self._set_allowance(controller, 1380, 85)

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertTrue(controller.allowanceIsFresh())
            self.assertTrue(controller.hasMinimumAllowance())

        with patch.object(self.fwp.time, "time", return_value=101):
            self.assertFalse(controller.allowanceIsFresh())
            self.assertFalse(controller.hasMinimumAllowance())

        controller.allowanceValid = False
        self._fresh_grid(controller, 102)
        with patch.object(self.fwp.time, "time", return_value=102):
            self.assertFalse(controller.allowanceIsFresh())
            self.assertFalse(controller.hasMinimumAllowance())

    def test_raw_overhead_phase_down_requires_fresh_allowance_and_one_phase_minimum(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.mqttRawOverheadW = 1380
        controller.mqttRawOverheadUpdatedAt = 100

        controller.allowance = 0
        controller.allowanceValid = False
        controller.allowanceUpdatedAt = 100
        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertFalse(controller.shouldPhaseDownForPvDip())

        self._set_allowance(controller, 0, 100)
        controller.mqttRawOverheadW = 1379
        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertFalse(controller.shouldPhaseDownForPvDip())

        controller.mqttRawOverheadW = 1380
        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertTrue(controller.shouldPhaseDownForPvDip())

        self._set_allowance(controller, 4140, 100)
        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertFalse(controller.shouldPhaseDownForPvDip())

    def test_one_to_three_phase_switch_requires_real_pv_allowance(self):
        controller = self._controller()
        controller.minimumPhaseSwitchSeconds = 0
        self._set_allowance(controller, 4200, 100)

        # This test locks the PV threshold.  Cooldown behavior is covered by
        # the dedicated test below, so make it explicitly inactive here.
        with patch.object(
            controller, "getPhaseSwitchCooldownSeconds", return_value=0
        ), patch.object(self.fwp.time, "time", return_value=100):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.SwitchingTo3Phase)
        self.assertEqual(controller.currentPhaseMode, 2)
        self.assertEqual(controller.pendingPhaseSwitchMode, 2)
        controller.wattpilot.set_phases.assert_called_once_with(2)
        controller.wattpilot.set_power.assert_called_once_with(6)

    def test_one_to_three_phase_switch_is_blocked_during_cooldown(self):
        controller = self._controller()
        controller.lastPhaseSwitchTime = 100
        self._set_allowance(controller, 5000, 200)

        with patch.object(self.fwp.time, "time", return_value=200):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 1)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_called_once_with(7)

    def test_one_to_three_phase_switch_requires_shared_stable_delay(self):
        controller = self._controller()
        controller.minimumPhaseSwitchSeconds = 120
        controller.lastPhaseSwitchTime = -120
        self._set_allowance(controller, 5000, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 1)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_called_once_with(7)

        controller.wattpilot.set_power.reset_mock()
        self._set_allowance(controller, 5000, 220)
        with patch.object(self.fwp.time, "time", return_value=220):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.SwitchingTo3Phase)
        self.assertEqual(controller.currentPhaseMode, 2)
        self.assertEqual(controller.phaseSwitchCandidateMode, 0)
        controller.wattpilot.set_phases.assert_called_once_with(2)
        controller.wattpilot.set_power.assert_called_once_with(7)

    def test_transient_disconnect_preserves_phase_up_candidate(self):
        controller = self._controller()
        controller.phaseSwitchCandidateMode = 2
        controller.phaseSwitchCandidateSince = 100
        controller.phaseSwitchBelowThresholdSince = 105
        controller.lastConfirmedCarConnected = True
        controller.wattpilot.carConnected = False
        controller.wattpilot.modelStatus = SimpleNamespace(value=3)

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertTrue(controller.updateEffectiveCarConnection())
        with patch.object(self.fwp.time, "time", return_value=110):
            effective_connected = controller.updateEffectiveCarConnection()

        self.assertTrue(effective_connected)
        self.assertEqual(controller.phaseSwitchCandidateMode, 2)
        self.assertEqual(controller.phaseSwitchCandidateSince, 100)
        self.assertEqual(controller.phaseSwitchBelowThresholdSince, 105)

    def test_confirmed_disconnect_requires_a_new_phase_up_stability_timer(self):
        controller = self._controller()
        controller.minimumPhaseSwitchSeconds = 120
        controller.lastPhaseSwitchTime = -120
        self._set_allowance(controller, 4200, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.adjustChargeForPvAllowance()

        self.assertEqual(controller.phaseSwitchCandidateMode, 2)
        self.assertEqual(controller.phaseSwitchCandidateSince, 100)
        controller.phaseSwitchBelowThresholdSince = 105
        controller.wattpilot.set_power.reset_mock()

        with patch.object(self.fwp.time, "time", return_value=110):
            result = controller._handleDisconnected()

        self.assertFalse(result)
        self.assertEqual(controller.phaseSwitchCandidateMode, 0)
        self.assertEqual(controller.phaseSwitchCandidateSince, 0)
        self.assertEqual(controller.phaseSwitchBelowThresholdSince, 0)
        self.assertEqual(controller.lastPhaseSwitchTime, -120)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()

        controller.wattpilot.carConnected = True
        controller.lastConfirmedCarConnected = True
        controller.effectiveCarConnected = True
        self._set_allowance(controller, 4200, 220)
        with patch.object(self.fwp.time, "time", return_value=220):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.phaseSwitchCandidateMode, 2)
        self.assertEqual(controller.phaseSwitchCandidateSince, 220)
        controller.wattpilot.set_phases.assert_not_called()

        self._set_allowance(controller, 4200, 339)
        with patch.object(self.fwp.time, "time", return_value=339):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        controller.wattpilot.set_phases.assert_not_called()

        self._set_allowance(controller, 4200, 340)
        with patch.object(self.fwp.time, "time", return_value=340):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(
            status,
            self.fwp.VrmEvChargerStatus.SwitchingTo3Phase,
        )
        controller.wattpilot.set_phases.assert_called_once_with(2)

    def test_short_safe_phase_up_dip_preserves_candidate_timer(self):
        controller = self._controller()
        controller.minimumPhaseSwitchSeconds = 120
        controller.lastPhaseSwitchTime = -120
        self._set_allowance(controller, 4200, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.adjustChargeForPvAllowance()

        self._set_allowance(controller, 4180, 150)
        with patch.object(self.fwp.time, "time", return_value=150):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.phaseSwitchCandidateMode, 2)
        self.assertEqual(controller.phaseSwitchCandidateSince, 100)
        self.assertEqual(controller.phaseSwitchBelowThresholdSince, 150)
        controller.wattpilot.set_phases.assert_not_called()

        self._set_allowance(controller, 4200, 220)
        with patch.object(self.fwp.time, "time", return_value=220):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.SwitchingTo3Phase)
        controller.wattpilot.set_phases.assert_called_once_with(2)

    def test_mature_phase_up_candidate_waits_for_full_threshold_recovery(self):
        controller = self._controller()
        controller.minimumPhaseSwitchSeconds = 120
        controller.lastPhaseSwitchTime = -120
        self._set_allowance(controller, 4200, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.adjustChargeForPvAllowance()

        self._set_allowance(controller, 4180, 220)
        with patch.object(self.fwp.time, "time", return_value=220):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 1)
        self.assertEqual(controller.phaseSwitchCandidateSince, 100)
        controller.wattpilot.set_phases.assert_not_called()

        self._set_allowance(controller, 4200, 225)
        with patch.object(self.fwp.time, "time", return_value=225):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.SwitchingTo3Phase)
        controller.wattpilot.set_phases.assert_called_once_with(2)

    def test_phase_up_drop_grace_expiry_resets_candidate_timer(self):
        controller = self._controller()
        controller.minimumPhaseSwitchSeconds = 120
        controller.lastPhaseSwitchTime = -120
        self._set_allowance(controller, 4200, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.adjustChargeForPvAllowance()

        self._set_allowance(controller, 4180, 150)
        with patch.object(self.fwp.time, "time", return_value=150):
            controller.adjustChargeForPvAllowance()

        self._set_allowance(controller, 4180, 170)
        with patch.object(self.fwp.time, "time", return_value=170):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.phaseSwitchCandidateMode, 0)
        self.assertEqual(controller.phaseSwitchCandidateSince, 0)
        controller.wattpilot.set_phases.assert_not_called()

    def test_phase_up_dip_below_electrical_minimum_resets_immediately(self):
        controller = self._controller()
        controller.minimumPhaseSwitchSeconds = 120
        controller.lastPhaseSwitchTime = -120
        self._set_allowance(controller, 4200, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.adjustChargeForPvAllowance()

        self._set_allowance(controller, 4139, 105)
        with patch.object(self.fwp.time, "time", return_value=105):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.phaseSwitchCandidateMode, 0)
        controller.wattpilot.set_phases.assert_not_called()

    def test_real_pv_below_three_phase_threshold_keeps_one_phase(self):
        controller = self._controller()
        self._set_allowance(controller, 4199, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 1)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_called_once_with(7)

    def test_pv_reduction_precedes_battery_assist_and_cannot_phase_up(self):
        controller = self._controller()
        controller.wattpilot.power = 3.68
        controller.wattpilot.amp = 16
        self._set_allowance(controller, 1380, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertFalse(controller.batteryAssistActive)
        self.assertEqual(controller.currentPhaseMode, 1)
        controller.wattpilot.set_power.assert_called_once_with(6)
        controller.wattpilot.set_phases.assert_not_called()

    def test_pv_current_reduction_resets_phase_up_candidate_until_full_pv_recovers(self):
        controller = self._controller()
        controller.minimumPhaseSwitchSeconds = 120
        controller.lastPhaseSwitchTime = -120
        controller.wattpilot.power = 3.68
        controller.wattpilot.amp = 16
        self._set_allowance(controller, 4200, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.adjustChargeForPvAllowance()

        self.assertEqual(controller.phaseSwitchCandidateMode, 2)
        self.assertEqual(controller.phaseSwitchCandidateSince, 100)

        # PV still supports 8 A on one phase, so the controller reduces from
        # 16 A to 8 A without using the battery or issuing a phase command.
        self._set_allowance(controller, 1856, 110)
        with patch.object(self.fwp.time, "time", return_value=110):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertFalse(controller.batteryAssistActive)
        self.assertEqual(controller.phaseSwitchCandidateMode, 0)
        self.assertEqual(controller.phaseSwitchCandidateSince, 0)
        self.assertEqual(controller.phaseSwitchBelowThresholdSince, 0)
        controller.wattpilot.set_power.assert_called_with(8)
        controller.wattpilot.set_phases.assert_not_called()

        # Once fresh assigned PV recovers, a new complete phase-up stability
        # interval is required; the reduction path never preserves a candidate
        # by pretending battery assistance was active.
        controller.wattpilot.set_power.reset_mock()
        self._set_allowance(controller, 4200, 220)
        with patch.object(self.fwp.time, "time", return_value=220):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.phaseSwitchCandidateSince, 220)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_called_once_with(16)

        controller.wattpilot.set_power.reset_mock()
        controller.wattpilot.amp = 6
        self._set_allowance(controller, 4200, 221)
        with patch.object(self.fwp.time, "time", return_value=221):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        controller.wattpilot.set_phases.assert_not_called()

    def test_battery_assist_requires_active_charge_soc_and_power_limits(self):
        controller = self._controller()
        controller.wattpilot.power = 1.4
        controller.batterySocDbus.value = 59

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertFalse(controller.startOrContinueBatteryAssist(1000))

        controller.batterySocDbus.value = 80
        with patch.object(self.fwp.time, "time", return_value=101):
            self.assertFalse(controller.startOrContinueBatteryAssist(1501))

        with patch.object(self.fwp.time, "time", return_value=102):
            self.assertTrue(controller.startOrContinueBatteryAssist(1500))

        self.assertTrue(controller.batteryAssistActive)

    def test_battery_assist_shortfall_limit_scales_with_active_phases(self):
        controller = self._controller()
        controller.wattpilot.power = 4.2

        controller.currentPhaseMode = 1
        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertTrue(controller.startOrContinueBatteryAssist(1500))
        controller.clearBatteryAssist()
        with patch.object(self.fwp.time, "time", return_value=101):
            self.assertFalse(controller.startOrContinueBatteryAssist(1501))

        controller.currentPhaseMode = 2
        with patch.object(self.fwp.time, "time", return_value=102):
            self.assertTrue(controller.startOrContinueBatteryAssist(4500))
        self.assertEqual(controller.batteryAssistActivePhases, 3)
        self.assertEqual(controller.batteryAssistShortfallPerPhaseW, 1500)
        self.assertEqual(controller.batteryAssistEffectiveLimitW, 4500)
        controller.clearBatteryAssist()
        with patch.object(self.fwp.time, "time", return_value=103):
            self.assertFalse(controller.startOrContinueBatteryAssist(4501))

    def test_three_phase_assist_starts_only_after_confirmed_six_amp_reduction(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.minimumPhaseSwitchSeconds = 600
        controller.batteryAssistMaxSeconds = 600
        controller.wattpilot.power = 5.5
        controller.wattpilot.amp = 8
        controller.wattpilot.amps1 = 8
        controller.wattpilot.amps2 = 8
        controller.wattpilot.amps3 = 8
        controller.mqttRawOverheadW = 2400
        controller.mqttRawOverheadUpdatedAt = 100
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertFalse(controller.batteryAssistActive)
        self.assertEqual(controller.batteryAssistDeficitSince, 100)
        controller.wattpilot.set_power.assert_called_once_with(6)
        controller.wattpilot.set_phases.assert_not_called()

        controller.wattpilot.amp = 6
        controller.wattpilot.amps1 = 6
        controller.wattpilot.amps2 = 6
        controller.wattpilot.amps3 = 6
        controller.mqttRawOverheadUpdatedAt = 101
        self._set_allowance(controller, 0, 101)
        with patch.object(self.fwp.time, "time", return_value=101):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertTrue(controller.batteryAssistActive)
        self.assertEqual(controller.batteryAssistSince, 100)
        self.assertEqual(controller.batteryAssistShortfallW, 1740)
        self.assertEqual(controller.batteryAssistShortfallPerPhaseW, 580)
        controller.publishSafetyTelemetry()
        self.assertEqual(controller.dbusService["/BatteryAssist/Shortfall"], 1740)
        self.assertEqual(
            controller.dbusService["/BatteryAssist/ShortfallPerPhase"], 580
        )
        self.assertEqual(controller.dbusService["/BatteryAssist/ActivePhases"], 3)
        self.assertEqual(
            controller.dbusService["/BatteryAssist/EffectiveLimit"], 4500
        )
        controller.wattpilot.set_phases.assert_not_called()

    def test_one_phase_assist_starts_only_after_confirmed_six_amp_reduction(self):
        controller = self._controller()
        controller.currentPhaseMode = 1
        controller.wattpilot.power = 3.68
        controller.wattpilot.amp = 16
        controller.wattpilot.amps1 = 16
        controller.mqttRawOverheadW = 1000
        controller.mqttRawOverheadUpdatedAt = 100
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertFalse(controller.batteryAssistActive)
        controller.wattpilot.set_power.assert_called_once_with(6)

        controller.wattpilot.amp = 6
        controller.wattpilot.amps1 = 6
        controller.mqttRawOverheadUpdatedAt = 101
        self._set_allowance(controller, 0, 101)
        with patch.object(self.fwp.time, "time", return_value=101):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertTrue(controller.batteryAssistActive)
        self.assertEqual(controller.batteryAssistShortfallW, 380)
        self.assertEqual(controller.batteryAssistShortfallPerPhaseW, 380)

    def test_grid_fallback_also_reduces_to_six_amps_first(self):
        controller = self._controller()
        controller.currentPhaseMode = 1
        controller.allowGridCharging = True
        controller.batteryAssistEnabled = False
        controller.wattpilot.power = 3.68
        controller.wattpilot.amp = 16
        controller.wattpilot.amps1 = 16
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        controller.wattpilot.set_power.assert_called_once_with(6)
        controller.wattpilot.set_start_stop.assert_not_called()

    def test_battery_assist_timeout_does_not_receive_a_new_allowance_grace(self):
        controller = self._controller()
        controller.currentPhaseMode = 1
        controller.batteryAssistMaxSeconds = 600
        controller.wattpilot.power = 1.38
        controller.wattpilot.amp = 6
        controller.wattpilot.amps1 = 6
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertEqual(
                controller.controlAutomaticCharging(),
                self.fwp.VrmEvChargerStatus.Charging,
            )
        self.assertTrue(controller.batteryAssistActive)

        self._set_allowance(controller, 0, 700)
        with patch.object(self.fwp.time, "time", return_value=700):
            controller.recordBatteryPowerTelemetry(0)
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.StopCharging)
        self.assertTrue(controller.batteryAssistLockedOut)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_battery_soc_requires_valid_soc_and_fresh_battery_activity(self):
        controller = self._controller()

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.batterySocDbus.value = 80
            controller.onBatterySocTelemetry(controller.batterySocDbus)
            controller.onBatteryPowerTelemetry(controller.batteryPowerDbus)
            self.assertEqual(controller.batterySoc(), 80)

        with patch.object(self.fwp.time, "time", return_value=115):
            self.assertEqual(controller.batterySoc(), 80)

        with patch.object(self.fwp.time, "time", return_value=115.001):
            self.assertIsNone(controller.batterySoc())

        with patch.object(self.fwp.time, "time", return_value=116):
            controller.onBatteryPowerTelemetry(controller.batteryPowerDbus)
            self.assertEqual(controller.batterySoc(), 80)

        for value in (None, "invalid", float("nan"), float("inf")):
            with self.subTest(value=value), patch.object(
                self.fwp.time, "time", return_value=120
            ):
                controller.onBatteryPowerTelemetry(controller.batteryPowerDbus)
                controller.batterySocDbus.value = value
                controller.onBatterySocTelemetry(controller.batterySocDbus)
                self.assertIsNone(controller.batterySoc())

    def test_invalid_battery_activity_makes_soc_ineligible(self):
        controller = self._controller()

        for value in (None, "invalid", float("nan"), float("inf")):
            with self.subTest(value=value), patch.object(
                self.fwp.time, "time", return_value=100
            ):
                controller.batteryPowerDbus.value = value
                controller.onBatteryPowerTelemetry(controller.batteryPowerDbus)
                self.assertIsNone(controller.batterySoc())

    def test_stale_battery_activity_clears_active_battery_assist(self):
        controller = self._controller()
        controller.wattpilot.power = 2.3

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertTrue(controller.startOrContinueBatteryAssist(1000))

        with patch.object(self.fwp.time, "time", return_value=116):
            self.assertFalse(controller.startOrContinueBatteryAssist(1000))

        self.assertFalse(controller.batteryAssistActive)
        self.assertEqual(controller.batteryAssistSince, 0)
        self.assertFalse(controller.batteryAssistLockedOut)

    def test_missing_and_invalid_soc_cannot_activate_battery_assist(self):
        for value in (None, "invalid", float("nan"), float("inf")):
            with self.subTest(value=value):
                controller = self._controller()
                controller.wattpilot.power = 2.3
                controller.batterySocDbus.value = value
                with patch.object(self.fwp.time, "time", return_value=100):
                    controller.onBatterySocTelemetry(controller.batterySocDbus)
                    self.assertFalse(controller.startOrContinueBatteryAssist(1000))

                self.assertFalse(controller.batteryAssistActive)

    def test_missing_invalid_and_stale_soc_cannot_bypass_battery_reservation(self):
        controller = self._controller()
        controller.evPriorityOverBatteryCharge = True
        controller.evPriorityMinSoc = 60

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertTrue(controller.shouldIgnoreBatteryReservation())

        with patch.object(self.fwp.time, "time", return_value=116):
            self.assertFalse(controller.shouldIgnoreBatteryReservation())

        for value in (None, "invalid", float("nan")):
            with self.subTest(value=value), patch.object(
                self.fwp.time, "time", return_value=120
            ):
                controller.batteryPowerDbus.value = 0
                controller.onBatteryPowerTelemetry(controller.batteryPowerDbus)
                controller.batterySocDbus.value = value
                controller.onBatterySocTelemetry(controller.batterySocDbus)
                self.assertFalse(controller.shouldIgnoreBatteryReservation())

    def test_three_to_one_phase_switch_waits_for_shared_timer_on_battery(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.minimumPhaseSwitchSeconds = 300
        controller.lastPhaseSwitchTime = -300
        controller.batteryAssistMaxSeconds = 600
        controller.wattpilot.power = 3.6
        controller.wattpilot.amp = 6
        controller.mqttRawOverheadW = 2000
        controller.mqttRawOverheadUpdatedAt = 100
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 2)
        self.assertEqual(controller.phaseSwitchCandidateMode, 1)
        controller.wattpilot.set_phases.assert_not_called()

        controller.mqttRawOverheadUpdatedAt = 400
        self._set_allowance(controller, 0, 400)
        with patch.object(self.fwp.time, "time", return_value=400):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.SwitchingTo1Phase)
        self.assertEqual(controller.currentPhaseMode, 1)
        controller.wattpilot.set_phases.assert_called_once_with(1)
        controller.wattpilot.set_power.assert_called_once_with(7)

    def test_phase_down_timer_resets_when_three_phase_pv_recovers(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.minimumPhaseSwitchSeconds = 300
        controller.lastPhaseSwitchTime = -300
        controller.batteryAssistMaxSeconds = 600
        controller.wattpilot.power = 3.6
        controller.wattpilot.amp = 6
        controller.wattpilot.modelStatus = SimpleNamespace(value=3)
        controller.mqttRawOverheadW = 2000
        controller.mqttRawOverheadUpdatedAt = 100
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.phaseSwitchCandidateMode, 1)

        self._set_allowance(controller, 5000, 110)
        with patch.object(self.fwp.time, "time", return_value=110):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.phaseSwitchCandidateMode, 0)
        controller.wattpilot.set_phases.assert_not_called()

    def test_grid_import_guard_can_phase_down_before_shared_timer(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.wattpilot.power = 10
        controller.wattpilot.amp = 14
        controller.wattpilot.modelStatus = SimpleNamespace(value=3)
        controller.mqttRawOverheadW = 2000
        controller.mqttRawOverheadUpdatedAt = 106
        self._set_allowance(controller, 0, 106)
        controller.gridL1Dbus.value = 200
        controller.gridImportSince = 100

        with patch.object(self.fwp.time, "time", return_value=106):
            self.assertTrue(controller.gridImportLimitExceeded())
            self.assertTrue(controller.shouldPhaseDownForPvDip())
            status = controller._handleGridImportPhaseDown()
        self.assertTrue(status)
        controller.wattpilot.set_power.assert_called_once_with(8)
        controller.wattpilot.set_phases.assert_not_called()

        controller.wattpilot.amp = 8
        controller.wattpilot.amps1 = 8
        controller.wattpilot.amps2 = 8
        controller.wattpilot.amps3 = 8
        controller.wattpilot.energyTelemetryUpdatedAt = 107
        with patch.object(self.fwp.time, "time", return_value=107):
            controller._handleGridImportPhaseDown()
        controller.wattpilot.set_phases.assert_called_once_with(1)
        controller.wattpilot.set_start_stop.assert_not_called()

    def test_three_phase_deficit_reduces_to_six_before_phase_down(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.minimumPhaseSwitchSeconds = 600
        controller.wattpilot.power = 3.6
        controller.wattpilot.amp = 16
        controller.wattpilot.modelStatus = SimpleNamespace(value=3)
        controller.batterySocDbus.value = 80
        controller.batteryAssistMaxShortfallPerPhaseW = 500
        controller.mqttRawOverheadW = 2000
        controller.mqttRawOverheadUpdatedAt = 100
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 2)
        self.assertFalse(controller.batteryAssistActive)
        controller.wattpilot.set_power.assert_called_once_with(6)
        controller.wattpilot.set_phases.assert_not_called()

        controller.wattpilot.amp = 6
        controller.wattpilot.amps1 = 6
        controller.wattpilot.amps2 = 6
        controller.wattpilot.amps3 = 6
        controller.mqttRawOverheadUpdatedAt = 105
        self._set_allowance(controller, 0, 105)
        with patch.object(self.fwp.time, "time", return_value=105):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        controller.wattpilot.set_phases.assert_not_called()

        controller.mqttRawOverheadUpdatedAt = 115
        self._set_allowance(controller, 0, 115)
        with patch.object(self.fwp.time, "time", return_value=115):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.SwitchingTo1Phase)
        controller.wattpilot.set_phases.assert_called_once_with(1)

    def test_transient_zero_allowance_recovers_without_three_phase_change(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.minimumPhaseSwitchSeconds = 600
        controller.wattpilot.power = 4.0
        controller.wattpilot.amp = 16
        controller.wattpilot.modelStatus = SimpleNamespace(value=3)
        controller.batterySocDbus.value = 80
        controller.batteryAssistMaxShortfallPerPhaseW = 1000
        controller.mqttRawOverheadW = 3912
        controller.mqttRawOverheadUpdatedAt = 100
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()
            controller.publishSafetyTelemetry()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 2)
        self.assertEqual(controller.dbusService["/PvAllowance"], 0)
        self.assertEqual(controller.allowanceBelowMinimumSince, 100)
        self.assertFalse(controller.batteryAssistActive)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()

        controller.mqttRawOverheadW = 6309
        controller.mqttRawOverheadUpdatedAt = 105
        self._set_allowance(controller, 6309, 105)
        with patch.object(self.fwp.time, "time", return_value=105):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 2)
        self.assertEqual(controller.allowanceBelowMinimumSince, 0)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()

    def test_fresh_raw_overhead_can_only_maintain_three_phase_current(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.batteryAssistEnabled = False
        controller.allowGridCharging = False
        controller.wattpilot.power = 3.6
        controller.wattpilot.amp = 6
        controller.mqttRawOverheadW = 5000
        controller.mqttRawOverheadUpdatedAt = 100
        self._set_allowance(controller, 2000, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 2)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_not_called()

    def test_high_raw_overhead_does_not_start_spurious_battery_bridge(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.minimumPhaseSwitchSeconds = 300
        controller.lastPhaseSwitchTime = -300
        controller.wattpilot.power = 3.6
        controller.wattpilot.amp = 6
        controller.mqttRawOverheadW = 5000
        controller.mqttRawOverheadUpdatedAt = 100
        self._set_allowance(controller, 2000, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 2)
        self.assertFalse(controller.batteryAssistActive)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_not_called()

    def test_phase_adjustment_cannot_change_mode_without_phase_command(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.batteryAssistEnabled = False
        controller.allowGridCharging = False
        controller.wattpilot.power = 3.6
        controller.wattpilot.amp = 6
        controller.mqttRawOverheadW = 5000
        controller.mqttRawOverheadUpdatedAt = 100
        self._set_allowance(controller, 2000, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 2)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_not_called()

    def test_fresh_one_phase_allowance_can_reduce_phase_without_raw_overhead(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.batteryAssistEnabled = False
        controller.allowGridCharging = False
        controller.wattpilot.power = 3.6
        controller.wattpilot.amp = 6
        controller.mqttRawOverheadW = None
        controller.mqttRawOverheadUpdatedAt = 0
        self._set_allowance(controller, 2000, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.SwitchingTo1Phase)
        controller.wattpilot.set_phases.assert_called_once_with(1)
        controller.wattpilot.set_power.assert_called_once_with(7)

    def test_no_grid_stops_when_battery_bridge_and_one_phase_pv_are_unavailable(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.wattpilot.power = 4.2
        controller.wattpilot.amp = 6
        controller.wattpilot.modelStatus = SimpleNamespace(value=3)
        controller.batterySocDbus.value = 59
        controller.mqttRawOverheadW = 1000
        controller.mqttRawOverheadUpdatedAt = 100
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        controller.wattpilot.set_start_stop.assert_not_called()

        controller.mqttRawOverheadUpdatedAt = 115
        self._set_allowance(controller, 0, 115)
        with patch.object(self.fwp.time, "time", return_value=115):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.StopCharging)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_grid_allowed_keeps_running_three_phase_when_pv_is_below_one_phase(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.allowGridCharging = True
        controller.minimumPhaseSwitchSeconds = 300
        controller.lastPhaseSwitchTime = -300
        controller.wattpilot.power = 4.2
        controller.wattpilot.amp = 6
        controller.batterySocDbus.value = 59
        controller.mqttRawOverheadW = 1000
        controller.mqttRawOverheadUpdatedAt = 100
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.phaseSwitchCandidateMode, 1)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()

        controller.mqttRawOverheadUpdatedAt = 400
        self._set_allowance(controller, 0, 400)
        with patch.object(self.fwp.time, "time", return_value=400):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 2)
        controller.wattpilot.set_phases.assert_not_called()

    def test_grid_allowed_phase_down_waits_for_shared_timer_when_one_phase_pv_exists(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.allowGridCharging = True
        controller.minimumPhaseSwitchSeconds = 300
        controller.lastPhaseSwitchTime = -300
        controller.wattpilot.power = 3.6
        controller.wattpilot.amp = 6
        controller.batterySocDbus.value = 59
        controller.mqttRawOverheadW = 2000
        controller.mqttRawOverheadUpdatedAt = 100
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        controller.wattpilot.set_phases.assert_not_called()

        controller.mqttRawOverheadUpdatedAt = 400
        self._set_allowance(controller, 0, 400)
        with patch.object(self.fwp.time, "time", return_value=400):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.SwitchingTo1Phase)
        controller.wattpilot.set_phases.assert_called_once_with(1)
        controller.wattpilot.set_power.assert_called_once_with(7)

    def test_grid_allowed_keeps_running_one_phase_without_pv_but_does_not_start(self):
        controller = self._controller()
        controller.currentPhaseMode = 1
        controller.allowGridCharging = True
        controller.wattpilot.power = 1.4
        controller.wattpilot.amp = 6
        controller.batterySocDbus.value = 59
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        controller.wattpilot.set_start_stop.assert_not_called()

        controller.wattpilot.set_power.reset_mock()
        controller.wattpilot.set_phases.reset_mock()
        with patch.object(self.fwp.time, "time", return_value=101):
            controller.startFromPvAllowance()

        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()

    def test_battery_assist_allows_299_seconds_but_not_300_seconds(self):
        controller = self._controller()
        controller.wattpilot.power = 2.3

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertTrue(controller.startOrContinueBatteryAssist(1000))
        with patch.object(self.fwp.time, "time", return_value=399):
            controller.recordBatteryPowerTelemetry(0)
            self.assertTrue(controller.startOrContinueBatteryAssist(1000))
        with patch.object(self.fwp.time, "time", return_value=400):
            self.assertFalse(controller.startOrContinueBatteryAssist(1000))

        self.assertFalse(controller.batteryAssistActive)
        self.assertTrue(controller.batteryAssistLockedOut)

    def test_battery_assist_rejects_grid_import_above_stop_threshold(self):
        controller = self._controller()
        controller.wattpilot.power = 2.3
        controller.gridL1Dbus.value = 151

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertFalse(controller.startOrContinueBatteryAssist(1000))

        self.assertFalse(controller.batteryAssistActive)

        controller.gridL1Dbus.value = 150
        with patch.object(self.fwp.time, "time", return_value=101):
            self.assertTrue(controller.startOrContinueBatteryAssist(1000))

        self.assertTrue(controller.batteryAssistActive)

    def test_battery_assist_lockout_requires_configured_pv_recovery(self):
        controller = self._controller()
        controller.batteryAssistLockedOut = True

        with patch.object(self.fwp.time, "time", return_value=500):
            controller.updateBatteryAssistLockoutRecovery(0)
        with patch.object(self.fwp.time, "time", return_value=559):
            controller.updateBatteryAssistLockoutRecovery(0)
            self.assertTrue(controller.batteryAssistLockedOut)
        with patch.object(self.fwp.time, "time", return_value=560):
            controller.updateBatteryAssistLockoutRecovery(0)

        self.assertFalse(controller.batteryAssistLockedOut)

    def test_confirmed_disconnect_immediately_publishes_cleared_assist_lockout(self):
        controller = self._controller()
        controller.batteryAssistActive = True
        controller.batteryAssistSince = 100
        controller.batteryAssistShortfallW = 800
        controller.batteryAssistLockedOut = True
        controller.batteryAssistLockoutSince = 100
        controller.batteryAssistRecoverySince = 120
        controller.dbusService["/BatteryAssist/Active"] = 1
        controller.dbusService["/BatteryAssist/Elapsed"] = 500
        controller.dbusService["/BatteryAssist/Shortfall"] = 800
        controller.dbusService["/BatteryAssist/LockedOut"] = 1
        controller.dbusService["/BatteryAssist/RecoveryElapsed"] = 480

        with patch.object(self.fwp.time, "time", return_value=600):
            result = controller._handleDisconnected()

        self.assertFalse(result)
        self.assertFalse(controller.batteryAssistActive)
        self.assertFalse(controller.batteryAssistLockedOut)
        self.assertEqual(controller.dbusService["/BatteryAssist/Active"], 0)
        self.assertEqual(controller.dbusService["/BatteryAssist/Elapsed"], 0)
        self.assertEqual(controller.dbusService["/BatteryAssist/Shortfall"], 0)
        self.assertEqual(controller.dbusService["/BatteryAssist/LockedOut"], 0)
        self.assertEqual(
            controller.dbusService["/BatteryAssist/RecoveryElapsed"], 0
        )

    def test_grid_import_guard_timer_resets_when_import_drops_below_threshold(self):
        controller = self._controller()
        controller.gridL1Dbus.value = 200

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertFalse(controller.gridImportLimitExceeded())
        self.assertEqual(controller.gridImportSince, 100)

        controller.gridL1Dbus.value = 0
        with patch.object(self.fwp.time, "time", return_value=104):
            self.assertFalse(controller.gridImportLimitExceeded())
        self.assertEqual(controller.gridImportSince, 0)

        controller.gridL1Dbus.value = 200
        with patch.object(self.fwp.time, "time", return_value=105):
            self.assertFalse(controller.gridImportLimitExceeded())
        with patch.object(self.fwp.time, "time", return_value=110):
            self.assertTrue(controller.gridImportLimitExceeded())

    def test_grid_import_above_threshold_stops_auto_eco_charging(self):
        controller = self._controller()
        controller.wattpilot.modelStatus = SimpleNamespace(value=3)
        controller.wattpilot.power = 1.4
        controller.wattpilot.power1 = 1.4
        controller.wattpilot.amp = 6
        controller.gridL1Dbus.value = 100
        controller.gridL2Dbus.value = 100
        controller.gridL3Dbus.value = 100
        self._set_allowance(controller, 3000, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            controller._update()
        controller.wattpilot.set_start_stop.assert_not_called()

        with patch.object(self.fwp.time, "time", return_value=105):
            controller._update()

        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_invalid_native_authority_selects_safe_stop_without_phase_command(self):
        controller = self._controller()
        controller.wattpilot.nativePvSurplusEnabled = True
        controller.commandAuthorityLiteral = (
            self.fwp.COMMAND_AUTHORITY_DISABLE_NATIVE_PV
        )
        controller.wattpilot.power = 1400
        controller.wattpilot.startState = self.fwp.WattpilotStartStop.On
        controller.wattpilotReportsActiveCharge = Mock(return_value=True)
        controller.reportVRMStatus = Mock()

        selected, pending, _inputs = controller.selectControlState(
            effectiveCarConnected=True,
            gridTelemetryFresh=True,
        )
        self.assertEqual(
            selected,
            self.fwp.ControlStates.WattpilotControlState.COMMAND_AUTHORITY_BLOCKED,
        )

        self.assertTrue(
            controller.dispatchControlState(selected, True, pending)
        )
        controller.wattpilot.set_power.assert_called_once_with(0)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )
        controller.wattpilot.set_phases.assert_not_called()

    def test_current_cap_below_minimum_stops_auto_eco_charging(self):
        controller = self._controller()
        controller.wattpilot.ampLimit = 5
        controller.wattpilot.power = 1.4
        controller.wattpilot.amp = 6
        controller.wattpilot.modelStatus = SimpleNamespace(value=3)
        self._set_allowance(controller, 3000, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.StopCharging)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_stale_raw_overhead_cannot_cause_a_phase_switch(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.wattpilot.power = 2.0
        controller.wattpilot.amp = 6
        controller.wattpilot.modelStatus = SimpleNamespace(value=3)
        controller.mqttRawOverheadW = 2000
        controller.mqttRawOverheadUpdatedAt = 80
        controller.overheadAvailableDbus.value = 5000
        self._set_allowance(controller, 0, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertIsNone(controller.rawPvOverheadW())
            self.assertFalse(controller.shouldPhaseDownForPvDip())
            status = controller.controlAutomaticCharging()

        # With no fresh PV signal, either holding briefly or stopping is safe.
        # The requirement is that a stale raw-overhead value never commands a
        # 3-to-1 phase switch.
        self.assertNotEqual(status, self.fwp.VrmEvChargerStatus.SwitchingTo1Phase)
        self.assertNotIn(
            ((1,), {}),
            [
                (call.args, call.kwargs)
                for call in controller.wattpilot.set_phases.call_args_list
            ],
        )

    def test_manual_mode_does_not_apply_auto_eco_allowance_or_grid_guards(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Manual
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default
        controller.allowanceValid = False
        controller.gridL1Valid = False
        controller.wattpilot.modelStatus = SimpleNamespace(value=3)
        controller.wattpilot.power = 1.4

        controller._update()

        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()

    def test_failed_three_phase_switch_recovers_to_one_phase_safely(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.pendingPhaseSwitchMode = 2
        controller.pendingPhaseSwitchSince = 100
        controller.wattpilot.power = 3.6
        controller.wattpilot.power1 = 3.6
        controller.wattpilot.power2 = 0
        controller.wattpilot.power3 = 0
        self._set_allowance(controller, 3600, 160)

        with patch.object(self.fwp.time, "time", return_value=160):
            status = controller.reconcilePendingPhaseSwitch()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.SwitchingTo1Phase)
        self.assertEqual(controller.currentPhaseMode, 1)
        self.assertEqual(controller.pendingPhaseSwitchMode, 0)
        controller.wattpilot.set_phases.assert_called_once_with(1)
        controller.wattpilot.set_power.assert_called_once_with(7)

    def test_pending_one_phase_confirmation_stops_if_three_phase_power_remains(self):
        controller = self._controller()
        controller.currentPhaseMode = 1
        controller.pendingPhaseSwitchMode = 1
        controller.pendingPhaseSwitchSince = 100
        controller.wattpilot.power = 4.2
        controller.wattpilot.power1 = 1.4
        controller.wattpilot.power2 = 1.4
        controller.wattpilot.power3 = 1.4
        controller.wattpilot.startState = self.fwp.WattpilotStartStop.On

        with patch.object(self.fwp.time, "time", return_value=160):
            status = controller.reconcilePendingPhaseSwitch()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.StopCharging)
        self.assertEqual(controller.currentPhaseMode, 0)
        self.assertEqual(controller.pendingPhaseSwitchMode, 0)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )


if __name__ == "__main__":
    unittest.main()
