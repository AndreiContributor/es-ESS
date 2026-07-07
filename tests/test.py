"""Hardware-free regression coverage for Wattpilot PV-control behavior."""

import importlib.util
import sys
import types
import unittest
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def _module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
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
    _module("Globals", esEssTagService="test", esEssTag="test", currentVersionString="test")
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

    class VrmEvChargerStartStop(IntEnum):
        Stop = 0
        Start = 1

    _module(
        "enums",
        VrmEvChargerControlMode=VrmEvChargerControlMode,
        VrmEvChargerStatus=VrmEvChargerStatus,
        VrmEvChargerStartStop=VrmEvChargerStartStop,
        WattpilotModelStatus=type("WattpilotModelStatus", (), {}),
        WattpilotStartStop=WattpilotStartStop,
        WattpilotControlMode=WattpilotControlMode,
    )
    _module("Wattpilot", Wattpilot=type("Wattpilot", (), {}))
    _module("esESSService", esESSService=type("esESSService", (), {}))


class WattpilotControlRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.fwp = _load_module("fwp_under_test", ROOT / "FroniusWattpilot.py")
        cls.sod = _load_module(
            "sod_under_test", ROOT / "SolarOverheadDistributor.py"
        )

    def _controller(self):
        controller = self.fwp.FroniusWattpilot.__new__(self.fwp.FroniusWattpilot)
        controller.minCurrentPerPhase = 6
        controller.maxCurrentPerPhase = 16
        controller.threePhasePvSurplusStartW = 4200
        controller.threePhasePvSurplusStopW = 4140
        controller.minimumPhaseSwitchSeconds = 0
        controller.minimumOnOffSeconds = 300
        controller.lastPhaseSwitchTime = 0
        controller.lastOnOffTime = 0
        controller.currentPhaseMode = 1
        controller.allowance = 0
        controller.allowanceValid = True
        controller.allowanceFreshSeconds = 15
        controller.allowanceUpdatedAt = self.fwp.time.time()
        controller.allowanceBelowMinimumSince = 0
        controller.surplusSince = 0
        controller.surplusBelowMinimumSince = 0
        controller.surplusDropGraceSeconds = 20
        controller.allowanceDropGraceSeconds = 15
        controller.carDisconnectConfirmSeconds = 15
        controller.carDisconnectedSince = 0
        controller.lastConfirmedCarConnected = False
        controller.effectiveCarConnected = True
        controller.powerTransitionUntil = 0
        controller.powerTransitionExpectedW = 0
        controller.powerTransitionReason = ""
        controller.powerTransitionTelemetryReadyAt = 0
        controller.startupGraceSeconds = 60
        controller.startupTelemetryRatio = 0.8
        controller.pendingPhaseSwitchMode = 0
        controller.pendingPhaseSwitchSince = 0
        controller.rawOverheadFreshSeconds = 15
        controller.mqttAllowanceTopic = (
            "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Allowance"
        )
        controller.mqttRawOverheadTopic = (
            "es-ESS/SolarOverheadDistributor/Calculations/OverheadAvailable"
        )
        controller.mqttRawOverheadW = None
        controller.mqttRawOverheadUpdatedAt = 0
        controller.mode = 1
        controller.isIdleMode = False
        controller.isHibernateEnabled = False
        controller.lastVarDump = 0
        controller.chargingTime = 0
        controller.autostart = 1
        controller.noChargeSince = 0
        controller.noAllowanceForcedOff = False
        controller.chargeCompleteHold = False
        controller.chargeCompleteConfirmSeconds = 120
        controller.chargeCompletePowerThresholdW = 100
        controller.chargeCompleteResumePowerW = 300
        controller.chargeCompleteResumeSeconds = 30
        controller.chargeCompleteSince = 0
        controller.chargeCompleteResumeSince = 0
        controller.batteryAssistEnabled = True
        controller.batteryAssistSocMin = 60
        controller.batteryAssistMaxSeconds = 300
        controller.batteryAssistMaxShortfallW = 3000
        controller.batteryAssistRecoverySeconds = 60
        controller.batteryAssistSince = 0
        controller.batteryAssistActive = False
        controller.batteryAssistShortfallW = 0
        controller.batteryAssistLockedOut = False
        controller.batteryAssistLockoutSince = 0
        controller.batteryAssistRecoverySince = 0
        controller.allowGridCharging = False
        controller.gridImportPositive = True
        controller.gridImportStopW = 150
        controller.gridImportStopSeconds = 5
        controller.gridTelemetryFreshSeconds = 15
        controller.gridImportSince = 0
        controller.evPriorityOverBatteryCharge = True
        controller.evPriorityMinSoc = 0
        controller.config = {
            "FroniusWattpilot": {
                "VRMInstanceID_OverheadRequest": "42",
                "OverheadPriority": "35",
            }
        }
        controller.wattpilot = SimpleNamespace(
            ampLimit=None,
            voltage1=230,
            voltage2=230,
            voltage3=230,
            power=0,
            power1=0,
            power2=0,
            power3=0,
            amp=0,
            carConnected=True,
            carStateReady=True,
            connected=True,
            startState=0,
            mode=1,
            modelStatus=SimpleNamespace(value=4),
            set_power=Mock(),
            set_phases=Mock(),
            set_start_stop=Mock(),
            set_mode=Mock(),
        )
        controller.batterySocDbus = SimpleNamespace(value=80)
        controller.batteryPowerDbus = SimpleNamespace(value=0)
        controller.gridL1Dbus = SimpleNamespace(value=0)
        controller.gridL2Dbus = SimpleNamespace(value=0)
        controller.gridL3Dbus = SimpleNamespace(value=0)
        controller.gridL1Valid = True
        controller.gridL2Valid = True
        controller.gridL3Valid = True
        freshGridTime = self.fwp.time.time()
        controller.gridL1UpdatedAt = freshGridTime
        controller.gridL2UpdatedAt = freshGridTime
        controller.gridL3UpdatedAt = freshGridTime
        controller.overheadAvailableDbus = SimpleNamespace(value=0)
        controller.dbusService = {"/StartStop": 0, "/StartStopLiteral": "Stop"}
        controller.publishServiceMessage = lambda *args, **kwargs: None
        controller.publishMainMqtt = lambda *args, **kwargs: None
        controller.publishRetained = lambda *args, **kwargs: None
        controller.publish = lambda *args, **kwargs: None
        controller.reportPhaseMode = lambda: None
        controller.reportConsumption = lambda: None
        controller.reportVRMStatus = lambda *args, **kwargs: None
        controller.dumpEvChargerInfo = lambda: None
        return controller

    def _record_reported_request(self, controller):
        published = {}
        controller.publishMainMqtt = lambda topic, value: published.__setitem__(
            topic, value
        )
        controller.shouldIgnoreBatteryReservation = lambda: False
        controller.reportPhaseMode = lambda: None
        controller.reportBaseRequest()
        return published[
            "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Request"
        ]

    # Existing regressions -------------------------------------------------

    def test_transition_grace_expires_even_when_meter_telemetry_is_ready(self):
        controller = self._controller()
        controller.powerTransitionUntil = 100
        controller.powerTransitionExpectedW = 1000
        controller.actualMeasuredPowerW = lambda: 1000

        with patch.object(self.fwp.time, "time", return_value=101):
            self.assertFalse(controller.powerTransitionGraceActive())

        self.assertEqual(controller.powerTransitionUntil, 0)

    def test_low_wattpilot_limit_never_rounds_up_to_configured_minimum(self):
        controller = self._controller()
        controller.wattpilot.ampLimit = 5
        controller.allowance = 10000

        self.assertFalse(controller.canChargeAtMinimumCurrent())
        self.assertFalse(controller.hasMinimumAllowance())
        self.assertEqual(controller.targetCurrentForPhase(1, 10000), 0)

    def test_manual_current_request_below_minimum_cap_is_stopped(self):
        controller = self._controller()
        controller.wattpilot.ampLimit = 5

        self.assertTrue(controller._froniusHandleChangedValue("/SetCurrent", 6))
        controller.wattpilot.set_power.assert_called_once_with(0)

    def test_request_is_zero_when_wattpilot_limit_is_below_minimum(self):
        controller = self._controller()
        controller.wattpilot.ampLimit = 5

        self.assertEqual(self._record_reported_request(controller), 0)

    def test_request_voltage_reflects_the_active_phase_mode(self):
        controller = self._controller()
        self.assertEqual(controller.maxRequestVoltageForCurrentPhase(), 230)

        controller.currentPhaseMode = 2
        self.assertEqual(controller.maxRequestVoltageForCurrentPhase(), 690)

    def test_reported_request_uses_a_limited_three_phase_probe(self):
        controller = self._controller()

        self.assertEqual(self._record_reported_request(controller), 4370)
        controller.currentPhaseMode = 2
        self.assertEqual(self._record_reported_request(controller), 11040)

    def test_phase_up_probe_respects_phase_switch_cooldown(self):
        controller = self._controller()
        controller.minimumPhaseSwitchSeconds = 300
        controller.lastPhaseSwitchTime = 100

        with patch.object(self.fwp.time, "time", return_value=101):
            self.assertEqual(controller.maximumRequestForDistributorW(), 3680)

        with patch.object(self.fwp.time, "time", return_value=400):
            self.assertEqual(controller.maximumRequestForDistributorW(), 4370)

    def test_raw_overhead_uses_only_fresh_timestamped_mqtt(self):
        controller = self._controller()
        controller.mqttRawOverheadW = 5200
        controller.mqttRawOverheadUpdatedAt = 100
        controller.overheadAvailableDbus.value = 7000  # deliberately stale/untrusted

        with patch.object(self.fwp.time, "time", return_value=115):
            self.assertEqual(controller.rawPvOverheadW(), 5200)

        with patch.object(self.fwp.time, "time", return_value=116):
            self.assertIsNone(controller.rawPvOverheadW())

    def test_active_charge_waits_for_fresh_allowance_before_stop(self):
        controller = self._controller()
        controller.wattpilot.power = 2.0
        controller.wattpilot.modelStatus = SimpleNamespace(value=3)
        controller.allowance = 0

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertTrue(controller.allowanceStopGraceActive())
        with patch.object(self.fwp.time, "time", return_value=114):
            self.assertTrue(controller.allowanceStopGraceActive())
        with patch.object(self.fwp.time, "time", return_value=115):
            self.assertFalse(controller.allowanceStopGraceActive())

    def test_one_false_car_connection_does_not_drop_consumer_request(self):
        controller = self._controller()
        controller.lastConfirmedCarConnected = True
        controller.wattpilot.carConnected = False
        controller.wattpilot.modelStatus = SimpleNamespace(value=4)

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertTrue(controller.updateEffectiveCarConnection())
        with patch.object(self.fwp.time, "time", return_value=110):
            self.assertTrue(controller.updateEffectiveCarConnection())
        with patch.object(self.fwp.time, "time", return_value=115):
            self.assertFalse(controller.updateEffectiveCarConnection())

    def test_charging_status_overrides_transient_false_connection(self):
        controller = self._controller()
        controller.lastConfirmedCarConnected = True
        controller.wattpilot.carConnected = False
        controller.wattpilot.modelStatus = SimpleNamespace(value=3)

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertTrue(controller.updateEffectiveCarConnection())
        with patch.object(self.fwp.time, "time", return_value=200):
            self.assertTrue(controller.updateEffectiveCarConnection())

    def test_stable_pv_wait_reports_countdown_status_literal(self):
        controller = self._controller()
        controller.allowance = 1380
        controller.reportVRMStatus = Mock()

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.handleNotChargingState()

        controller.reportVRMStatus.assert_called_once_with(
            self.fwp.VrmEvChargerStatus.WaitingForSun,
            "Waiting for stable PV allowance (0/300s)",
        )

    def test_short_pv_dip_does_not_reset_start_timer(self):
        controller = self._controller()
        controller.allowance = 1380

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertEqual(controller.getContinuousSurplusSeconds(), 0)

        controller.allowance = 0
        with patch.object(self.fwp.time, "time", return_value=105):
            self.assertEqual(controller.getContinuousSurplusSeconds(), 5)
        with patch.object(self.fwp.time, "time", return_value=124):
            self.assertEqual(controller.getContinuousSurplusSeconds(), 24)
        with patch.object(self.fwp.time, "time", return_value=125):
            self.assertEqual(controller.getContinuousSurplusSeconds(), 0)

    def test_battery_reservation_bypass_does_not_override_configured_priority(self):
        distributor = self.sod.SolarOverheadDistributor.__new__(
            self.sod.SolarOverheadDistributor
        )
        regular = SimpleNamespace(
            consumerKey="regular",
            customName="regular",
            isInitialized=True,
            isAutomatic=True,
            priority=10,
            priorityShift=0,
            ignoreBatReservation=False,
            request=1500,
            minimum=0,
            stepSize=1500,
            effectivePriority=0,
        )
        ev = SimpleNamespace(
            consumerKey="ev",
            customName="ev",
            isInitialized=True,
            isAutomatic=True,
            priority=35,
            priorityShift=0,
            ignoreBatReservation=True,
            request=1380,
            minimum=1380,
            stepSize=230,
            effectivePriority=0,
        )
        distributor._knownSolarOverheadConsumers = {"regular": regular, "ev": ev}

        assigned = distributor.doAssign(
            overhead=2500,
            overheadDistribution={"regular": 0, "ev": 0},
            minBatCharge=1000,
        )

        self.assertEqual(assigned["regular"], 1500)
        self.assertEqual(assigned["ev"], 0)

    def test_do_assign_handles_missing_consumer_entry(self):
        distributor = self.sod.SolarOverheadDistributor.__new__(
            self.sod.SolarOverheadDistributor
        )
        ev = SimpleNamespace(
            consumerKey="ev",
            customName="ev",
            isInitialized=True,
            isAutomatic=True,
            priority=35,
            priorityShift=0,
            ignoreBatReservation=True,
            request=1380,
            minimum=1380,
            stepSize=230,
            effectivePriority=0,
        )
        distributor._knownSolarOverheadConsumers = {"ev": ev}

        assigned = distributor.doAssign(
            overhead=1500,
            overheadDistribution={},
            minBatCharge=0,
        )

        self.assertEqual(assigned["ev"], 1380)

    # New phase and safety regressions ------------------------------------

    def test_phase_up_switches_to_three_phases_with_real_pv_allowance(self):
        controller = self._controller()
        controller.allowance = 4200

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.SwitchingTo3Phase)
        self.assertEqual(controller.currentPhaseMode, 2)
        self.assertEqual(controller.pendingPhaseSwitchMode, 2)
        controller.wattpilot.set_phases.assert_called_once_with(2)
        controller.wattpilot.set_power.assert_called_once_with(6)

    def test_phase_up_is_blocked_during_the_300_second_cooldown(self):
        controller = self._controller()
        controller.allowance = 5000
        controller.minimumPhaseSwitchSeconds = 300
        controller.lastPhaseSwitchTime = 100

        with patch.object(self.fwp.time, "time", return_value=200):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 1)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_called_once_with(16)

    def test_raw_overhead_cannot_cause_a_false_phase_up(self):
        controller = self._controller()
        controller.allowance = 4199
        controller.mqttRawOverheadW = 10000
        controller.mqttRawOverheadUpdatedAt = 100

        with patch.object(self.fwp.time, "time", return_value=101):
            status = controller.adjustChargeForPvAllowance()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.Charging)
        self.assertEqual(controller.currentPhaseMode, 1)
        controller.wattpilot.set_phases.assert_not_called()
        controller.wattpilot.set_power.assert_called_once_with(16)

    def test_three_to_one_fallback_uses_fresh_raw_pv_overhead(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.allowance = 0
        controller.mqttRawOverheadW = 2000
        controller.mqttRawOverheadUpdatedAt = 100

        with patch.object(self.fwp.time, "time", return_value=110):
            self.assertTrue(controller.shouldPhaseDownForPvDip())
            status = controller.switchToOnePhaseForPvDip()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.SwitchingTo1Phase)
        self.assertEqual(controller.currentPhaseMode, 1)
        self.assertEqual(controller.pendingPhaseSwitchMode, 1)
        controller.wattpilot.set_phases.assert_called_once_with(1)
        controller.wattpilot.set_power.assert_called_once_with(8)

    def test_stale_raw_overhead_cannot_trigger_a_phase_down(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.allowance = 0
        controller.mqttRawOverheadW = 2000
        controller.mqttRawOverheadUpdatedAt = 100
        controller.overheadAvailableDbus.value = 2000  # intentionally stale

        with patch.object(self.fwp.time, "time", return_value=116):
            self.assertIsNone(controller.rawPvOverheadW())
            self.assertFalse(controller.shouldPhaseDownForPvDip())

    def test_grid_import_guard_stops_with_positive_import_convention(self):
        controller = self._controller()
        controller.gridImportPositive = True
        controller.gridL1Dbus.value = 200

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertFalse(controller.gridImportLimitExceeded())
        with patch.object(self.fwp.time, "time", return_value=105):
            self.assertTrue(controller.gridImportLimitExceeded())

        controller.gridL1Dbus.value = -200
        with patch.object(self.fwp.time, "time", return_value=106):
            self.assertFalse(controller.gridImportLimitExceeded())

    def test_grid_import_guard_stops_with_negative_import_convention(self):
        controller = self._controller()
        controller.gridImportPositive = False
        controller.gridL1Dbus.value = -200

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertFalse(controller.gridImportLimitExceeded())
        with patch.object(self.fwp.time, "time", return_value=105):
            self.assertTrue(controller.gridImportLimitExceeded())

        controller.gridL1Dbus.value = 200
        with patch.object(self.fwp.time, "time", return_value=106):
            self.assertFalse(controller.gridImportLimitExceeded())

    def test_battery_assist_stops_exactly_at_the_300_second_limit(self):
        controller = self._controller()
        controller.wattpilot.power = 2.0

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertTrue(controller.startOrContinueBatteryAssist(1000))
        with patch.object(self.fwp.time, "time", return_value=399):
            self.assertTrue(controller.startOrContinueBatteryAssist(1000))
        with patch.object(self.fwp.time, "time", return_value=400):
            self.assertFalse(controller.startOrContinueBatteryAssist(1000))

        self.assertTrue(controller.batteryAssistLockedOut)
        self.assertFalse(controller.batteryAssistActive)

    def test_battery_assist_lockout_requires_full_pv_recovery_for_60_seconds(self):
        controller = self._controller()
        controller.batteryAssistLockedOut = True

        with patch.object(self.fwp.time, "time", return_value=500):
            controller.updateBatteryAssistLockoutRecovery(0)
            self.assertTrue(controller.batteryAssistLockedOut)
        with patch.object(self.fwp.time, "time", return_value=559):
            controller.updateBatteryAssistLockoutRecovery(0)
            self.assertTrue(controller.batteryAssistLockedOut)
        with patch.object(self.fwp.time, "time", return_value=560):
            controller.updateBatteryAssistLockoutRecovery(0)
            self.assertFalse(controller.batteryAssistLockedOut)

    def test_interrupted_battery_recovery_restarts_its_60_second_timer(self):
        controller = self._controller()
        controller.batteryAssistLockedOut = True

        with patch.object(self.fwp.time, "time", return_value=500):
            controller.updateBatteryAssistLockoutRecovery(0)
        with patch.object(self.fwp.time, "time", return_value=550):
            controller.updateBatteryAssistLockoutRecovery(100)
            self.assertEqual(controller.batteryAssistRecoverySince, 0)
        with patch.object(self.fwp.time, "time", return_value=551):
            controller.updateBatteryAssistLockoutRecovery(0)
        with patch.object(self.fwp.time, "time", return_value=610):
            controller.updateBatteryAssistLockoutRecovery(0)
            self.assertTrue(controller.batteryAssistLockedOut)
        with patch.object(self.fwp.time, "time", return_value=611):
            controller.updateBatteryAssistLockoutRecovery(0)
            self.assertFalse(controller.batteryAssistLockedOut)

    def test_unconfirmed_three_phase_switch_reverts_to_one_phase(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.minimumPhaseSwitchSeconds = 300
        controller.pendingPhaseSwitchMode = 2
        controller.pendingPhaseSwitchSince = 100
        controller.allowance = 3600
        controller.wattpilot.power = 3.6
        controller.wattpilot.power1 = 3.6
        controller.wattpilot.power2 = 0
        controller.wattpilot.power3 = 0

        with patch.object(self.fwp.time, "time", return_value=160):
            status = controller.reconcilePendingPhaseSwitch()
            request = controller.maximumRequestForDistributorW()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.SwitchingTo1Phase)
        self.assertEqual(controller.currentPhaseMode, 1)
        self.assertEqual(controller.pendingPhaseSwitchMode, 0)
        self.assertEqual(request, 3680)
        controller.wattpilot.set_phases.assert_called_once_with(1)
        controller.wattpilot.set_power.assert_called_once_with(15)

    def test_confirmed_three_phase_switch_keeps_three_phase_state(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.pendingPhaseSwitchMode = 2
        controller.pendingPhaseSwitchSince = 100
        controller.wattpilot.power2 = 1.4
        controller.wattpilot.power3 = 1.4

        with patch.object(self.fwp.time, "time", return_value=101):
            self.assertIsNone(controller.reconcilePendingPhaseSwitch())

        self.assertEqual(controller.currentPhaseMode, 2)
        self.assertEqual(controller.pendingPhaseSwitchMode, 0)
        controller.wattpilot.set_phases.assert_not_called()

    def test_unconfirmed_one_phase_fallback_stops_eco_charging_safely(self):
        controller = self._controller()
        controller.currentPhaseMode = 1
        controller.pendingPhaseSwitchMode = 1
        controller.pendingPhaseSwitchSince = 100
        controller.wattpilot.power = 4.2
        controller.wattpilot.power1 = 1.4
        controller.wattpilot.power2 = 1.4
        controller.wattpilot.power3 = 1.4
        controller.wattpilot.startState = 1

        with patch.object(self.fwp.time, "time", return_value=160):
            status = controller.reconcilePendingPhaseSwitch()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.StopCharging)
        self.assertEqual(controller.currentPhaseMode, 0)
        controller.wattpilot.set_start_stop.assert_called_once_with(0)


    def test_stale_allowance_during_start_transition_stops_after_grace(self):
        controller = self._controller()
        controller.allowance = 5000
        controller.allowanceUpdatedAt = 80
        controller.powerTransitionUntil = 160
        controller.powerTransitionExpectedW = 1400
        controller.wattpilot.power = 0
        controller.wattpilot.startState = self.fwp.WattpilotStartStop.On
        self._set_grid_telemetry_time(controller, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.handleNotChargingState()
        controller.wattpilot.set_start_stop.assert_not_called()

        with patch.object(self.fwp.time, "time", return_value=115):
            controller.handleNotChargingState()

        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )
        self.assertEqual(controller.powerTransitionUntil, 0)

    def test_missing_allowance_during_start_transition_stops_after_grace(self):
        controller = self._controller()
        controller.allowanceValid = False
        controller.allowanceUpdatedAt = 0
        controller.powerTransitionUntil = 160
        controller.powerTransitionExpectedW = 1400
        controller.wattpilot.power = 0
        controller.wattpilot.startState = self.fwp.WattpilotStartStop.On
        self._set_grid_telemetry_time(controller, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.handleNotChargingState()
        controller.wattpilot.set_start_stop.assert_not_called()

        with patch.object(self.fwp.time, "time", return_value=115):
            controller.handleNotChargingState()

        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_stale_allowance_during_pending_phase_switch_stops_after_grace(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.pendingPhaseSwitchMode = 2
        controller.pendingPhaseSwitchSince = 100
        controller.powerTransitionUntil = 160
        controller.allowance = 5000
        controller.allowanceUpdatedAt = 80
        controller.wattpilot.power = 3.6
        controller.wattpilot.power1 = 3.6
        controller.wattpilot.startState = self.fwp.WattpilotStartStop.On
        self._set_grid_telemetry_time(controller, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertEqual(
                controller.reconcilePendingPhaseSwitch(),
                self.fwp.VrmEvChargerStatus.SwitchingTo3Phase,
            )
        controller.wattpilot.set_start_stop.assert_not_called()

        with patch.object(self.fwp.time, "time", return_value=115):
            self.assertEqual(
                controller.reconcilePendingPhaseSwitch(),
                self.fwp.VrmEvChargerStatus.StopCharging,
            )

        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )
        self.assertEqual(controller.pendingPhaseSwitchMode, 0)

    def test_stale_allowance_blocks_unconfirmed_three_phase_fallback_command(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.pendingPhaseSwitchMode = 2
        controller.pendingPhaseSwitchSince = 80
        controller.allowance = 3600
        controller.allowanceUpdatedAt = 80
        controller.wattpilot.power = 3.6
        controller.wattpilot.power1 = 3.6
        controller.wattpilot.modelStatus.value = 3
        controller.wattpilot.startState = self.fwp.WattpilotStartStop.On
        self._set_grid_telemetry_time(controller, 100)

        with patch.object(self.fwp.time, "time", return_value=140):
            self.assertEqual(
                controller.reconcilePendingPhaseSwitch(),
                self.fwp.VrmEvChargerStatus.SwitchingTo3Phase,
            )
        controller.wattpilot.set_power.assert_not_called()

        with patch.object(self.fwp.time, "time", return_value=155):
            self.assertEqual(
                controller.reconcilePendingPhaseSwitch(),
                self.fwp.VrmEvChargerStatus.StopCharging,
            )

        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_manual_transition_is_unaffected_by_missing_allowance(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Manual
        controller.allowanceValid = False
        controller.allowanceUpdatedAt = 0
        controller.powerTransitionUntil = 160
        controller.powerTransitionExpectedW = 1400
        controller.wattpilot.power = 0
        controller.wattpilot.startState = self.fwp.WattpilotStartStop.On

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.handleNotChargingState()

        controller.wattpilot.set_start_stop.assert_not_called()


    # Telemetry freshness fail-safe regressions ---------------------------

    def _set_grid_telemetry_time(self, controller, timestamp):
        controller.gridL1Valid = True
        controller.gridL2Valid = True
        controller.gridL3Valid = True
        controller.gridL1UpdatedAt = timestamp
        controller.gridL2UpdatedAt = timestamp
        controller.gridL3UpdatedAt = timestamp

    def test_stale_allowance_blocks_a_new_auto_start(self):
        controller = self._controller()
        controller.allowance = 5000
        controller.allowanceUpdatedAt = 80
        controller.minimumOnOffSeconds = 0
        controller.startFromPvAllowance = Mock()
        self._set_grid_telemetry_time(controller, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.handleNotChargingState()

        controller.startFromPvAllowance.assert_not_called()
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_missing_allowance_blocks_a_new_auto_start(self):
        controller = self._controller()
        controller.allowance = 5000
        controller.allowanceValid = False
        controller.allowanceUpdatedAt = 0
        controller.minimumOnOffSeconds = 0
        controller.startFromPvAllowance = Mock()
        self._set_grid_telemetry_time(controller, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.handleNotChargingState()

        controller.startFromPvAllowance.assert_not_called()
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_stale_allowance_stops_active_charge_after_grace(self):
        controller = self._controller()
        controller.allowance = 5000
        controller.allowanceUpdatedAt = 80
        controller.wattpilot.modelStatus.value = 3
        controller.wattpilot.power = 1.4
        controller.wattpilot.startState = self.fwp.WattpilotStartStop.On
        self._set_grid_telemetry_time(controller, 100)

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertEqual(
                controller.controlAutomaticCharging(),
                self.fwp.VrmEvChargerStatus.Charging,
            )
        with patch.object(self.fwp.time, "time", return_value=115):
            self.assertEqual(
                controller.controlAutomaticCharging(),
                self.fwp.VrmEvChargerStatus.StopCharging,
            )

        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_missing_grid_telemetry_blocks_a_new_auto_start(self):
        controller = self._controller()
        controller.allowance = 5000
        controller.minimumOnOffSeconds = 0
        controller.gridL2Valid = False
        controller.startFromPvAllowance = Mock()

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.handleNotChargingState()

        controller.startFromPvAllowance.assert_not_called()
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_stale_grid_telemetry_blocks_a_new_auto_start(self):
        controller = self._controller()
        controller.allowance = 5000
        controller.minimumOnOffSeconds = 0
        controller.startFromPvAllowance = Mock()
        self._set_grid_telemetry_time(controller, 80)

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.handleNotChargingState()

        controller.startFromPvAllowance.assert_not_called()
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_stale_grid_telemetry_stops_active_auto_charge_immediately(self):
        controller = self._controller()
        controller.allowance = 5000
        controller.wattpilot.modelStatus.value = 3
        controller.wattpilot.power = 1.4
        controller.wattpilot.startState = self.fwp.WattpilotStartStop.On
        self._set_grid_telemetry_time(controller, 80)

        with patch.object(self.fwp.time, "time", return_value=100):
            status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.StopCharging)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_missing_grid_telemetry_stops_active_auto_charge_immediately(self):
        controller = self._controller()
        controller.allowance = 5000
        controller.wattpilot.modelStatus.value = 3
        controller.wattpilot.power = 1.4
        controller.wattpilot.startState = self.fwp.WattpilotStartStop.On
        controller.gridL1Valid = False

        status = controller.controlAutomaticCharging()

        self.assertEqual(status, self.fwp.VrmEvChargerStatus.StopCharging)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )

    def test_grid_telemetry_callbacks_track_validity_and_update_time(self):
        controller = self._controller()
        with patch.object(self.fwp.time, "time", return_value=100):
            controller.onGridL1Telemetry(SimpleNamespace(value="12.5"))
            controller.onGridL2Telemetry(SimpleNamespace(value="nan"))
            controller.onGridL3Telemetry(SimpleNamespace(value=None))

        self.assertTrue(controller.gridL1Valid)
        self.assertFalse(controller.gridL2Valid)
        self.assertFalse(controller.gridL3Valid)
        self.assertEqual(controller.gridL1UpdatedAt, 100)
        self.assertEqual(controller.gridL2UpdatedAt, 100)
        self.assertEqual(controller.gridL3UpdatedAt, 100)

    def test_invalid_allowance_message_invalidates_previous_allowance(self):
        controller = self._controller()
        controller.allowance = 5000
        controller.allowanceValid = True
        message = SimpleNamespace(
            topic=controller.mqttAllowanceTopic,
            payload=b"not-a-number",
        )

        with patch.object(self.fwp.time, "time", return_value=100):
            controller.onMqttMessage(None, None, message)

        self.assertFalse(controller.allowanceValid)
        self.assertEqual(controller.allowance, 0)
        self.assertEqual(controller.allowanceUpdatedAt, 100)

    def test_raw_overhead_does_not_replace_stale_allowance(self):
        controller = self._controller()
        controller.currentPhaseMode = 2
        controller.allowance = 0
        controller.allowanceUpdatedAt = 80
        controller.mqttRawOverheadW = 2000
        controller.mqttRawOverheadUpdatedAt = 100

        with patch.object(self.fwp.time, "time", return_value=100):
            self.assertFalse(controller.shouldPhaseDownForPvDip())

    def test_unexpected_auto_controller_exception_sends_safe_stop(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Auto
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.ECO
        controller.updateEffectiveCarConnection = Mock(
            side_effect=RuntimeError("simulated controller failure")
        )
        messages = []
        controller.publishServiceMessage = lambda _service, message: messages.append(message)

        controller._update()

        controller.wattpilot.set_power.assert_called_once_with(0)
        controller.wattpilot.set_start_stop.assert_called_once_with(
            self.fwp.WattpilotStartStop.Off
        )
        self.assertTrue(any("controller fault" in message.lower() for message in messages))

    def test_manual_mode_is_unaffected_by_missing_control_telemetry(self):
        controller = self._controller()
        controller.mode = self.fwp.VrmEvChargerControlMode.Manual
        controller.wattpilot.mode = self.fwp.WattpilotControlMode.Default
        controller.wattpilot.modelStatus.value = 3
        controller.wattpilot.power = 1.4
        controller.allowanceValid = False
        controller.gridL1Valid = False

        controller._update()

        controller.wattpilot.set_power.assert_not_called()
        controller.wattpilot.set_start_stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
