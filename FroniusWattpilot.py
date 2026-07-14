
from builtins import int
from enum import Enum
from math import isfinite
import os
import platform
import sys
import time

import paho.mqtt.client as mqtt # type: ignore

# victron
sys.path.insert(1, '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python')
from vedbus import VeDbusService # type: ignore

# esEss imports
import Globals
import Helper
from Helper import i, c, d, w, e, t,  dbusConnection
import WattpilotControlState as ControlStates
import WattpilotDecisionInputs as DecisionInputs
import WattpilotPhaseDecisions as PhaseDecisions
import WattpilotSafetyDecisions as SafetyDecisions
import RuntimeCompatibility
from Wattpilot import Wattpilot
from enums import WattpilotModelStatus, WattpilotStartStop, WattpilotControlMode, VrmEvChargerControlMode, VrmEvChargerStatus, VrmEvChargerStartStop
from esESSService import esESSService

WATTPILOT_BASE_CUSTOM_NAME = "Fronius Wattpilot"
WATTPILOT_UNAVAILABLE_STATUS_LITERAL = "Wattpilot not accessible"
WATTPILOT_UNAVAILABLE_CUSTOM_NAME = "Wattpilot not reachable"

class FroniusWattpilot (esESSService):
    
    def __init__(self):
        esESSService.__init__(self)
        self.vrmInstanceID = self.config['FroniusWattpilot']['VRMInstanceID']
        self.serviceType = "com.victronenergy.evcharger"
        self.serviceName = self.serviceType + "." + Globals.esEssTagService + "_FroniusWattpilot"

        settings = self.config["FroniusWattpilot"]
        self.validatedVenusOsVersion = (
            RuntimeCompatibility.VALIDATED_VENUS_OS_VERSIONS_LITERAL
        )
        self.validatedWattpilotFirmware = (
            RuntimeCompatibility.VALIDATED_WATTPILOT_FIRMWARE
        )
        self.validatedWattpilotAppVersion = (
            RuntimeCompatibility.VALIDATED_WATTPILOT_APP_VERSION
        )
        self.actualVenusOsVersion = RuntimeCompatibility.read_venus_os_version()
        self.actualWattpilotFirmware = None
        self.wattpilotFirmwareCompatible = False
        self._lastWattpilotCompatibilityState = None
        self.minimumOnOffSeconds = int(settings["MinOnOffSeconds"])
        self.minimumPhaseSwitchSeconds = int(settings["MinPhaseSwitchSeconds"])

        # Explicit EV limits. Wattpilot's AMA value can be higher than the
        # vehicle or installation limit, therefore it is only an upper bound.
        self.minCurrentPerPhase = max(6, int(settings.get("MinCurrentPerPhase", 6)))
        self.maxCurrentPerPhase = max(
            self.minCurrentPerPhase, int(settings.get("MaxCurrentPerPhase", 16))
        )

        # Phase thresholds are PV-only allowance thresholds. Battery assist does
        # not count as PV surplus and can never cause a phase-up.
        self.threePhasePvSurplusStartW = int(settings.get("ThreePhasePvSurplusStartW", 4200))
        self.threePhasePvSurplusStopW = int(settings.get("ThreePhasePvSurplusStopW", 4140))

        # PV priority over battery charging. This bypasses only the distributor's
        # battery-charge reservation; it does not authorise battery-to-EV energy.
        self.evPriorityOverBatteryCharge = settings.get(
            "EvPriorityOverBatteryCharge", "false"
        ).lower() == "true"
        self.evPriorityMinSoc = float(settings.get("EvPriorityMinSoc", 0))

        # Temporary battery bridge for an already-running charge session.
        self.batteryAssistEnabled = settings.get(
            "BatteryAssistEnabled", "false"
        ).lower() == "true"
        self.batteryAssistSocMin = float(settings.get("BatteryAssistSocMin", 60))
        self.batteryAssistMaxSeconds = int(settings.get("BatteryAssistMaxSeconds", 300))
        self.batteryAssistMaxShortfallW = float(
            settings.get("BatteryAssistMaxShortfallW", 3000)
        )
        self.batterySocFreshSeconds = max(
            1, int(settings.get("BatterySocFreshSeconds", 15))
        )
        # After the maximum bridge time is reached, require a sustained period
        # where PV fully covers the active EV demand before battery assist may
        # be used again. This prevents repeated 300-second assist windows
        # during one long cloud event.
        self.batteryAssistRecoverySeconds = max(
            0, int(settings.get("BatteryAssistRecoverySeconds", 60))
        )

        # A vehicle near its requested SOC can remain connected while drawing
        # only a small balancing or keep-alive load. In Auto mode, hold that
        # completed session instead of repeatedly re-entering PV control.
        self.chargeCompletePowerThresholdW = max(
            0.0, float(settings.get("ChargeCompletePowerThresholdW", 100))
        )
        self.chargeCompleteConfirmSeconds = max(
            5, int(settings.get("ChargeCompleteConfirmSeconds", 120))
        )
        self.chargeCompleteResumePowerW = max(
            self.chargeCompletePowerThresholdW,
            float(settings.get("ChargeCompleteResumePowerW", 300))
        )
        self.chargeCompleteResumeSeconds = max(
            5, int(settings.get("ChargeCompleteResumeSeconds", 30))
        )

        # Grid import is an emergency stop guard. Configure the sign convention
        # per site: true means positive grid power is import; false reverses it.
        self.allowGridCharging = settings.get(
            "AllowGridCharging", "false"
        ).lower() == "true"
        self.gridImportPositive = settings.get(
            "GridImportPositive", "true"
        ).lower() == "true"
        self.gridImportStopW = float(settings.get("GridImportStopW", 150))
        self.gridImportStopSeconds = int(settings.get("GridImportStopSeconds", 5))
        self.gridTelemetryFreshSeconds = max(
            1, int(settings.get("GridTelemetryFreshSeconds", 15))
        )

        # The Wattpilot reports 0 W for several seconds while a new charge
        # session or a phase switch is being negotiated. During that interval
        # the distributor would otherwise see the battery charge disappear
        # before the EV power telemetry arrives, revoke the allowance, and
        # cause an immediate false stop. Keep reporting the commanded EV
        # demand until real Wattpilot telemetry has caught up.
        self.startupGraceSeconds = int(settings.get("StartupGraceSeconds", 60))
        self.startupTelemetryRatio = float(settings.get("StartupTelemetryRatio", 0.80))

        # The distributor and Wattpilot are both updated on short polling
        # intervals. A single stale 0 W allowance or transient car-state false
        # must not immediately stop an otherwise active PV charge session.
        self.allowanceDropGraceSeconds = max(
            5, int(settings.get("AllowanceDropGraceSeconds", 15))
        )
        self.allowanceFreshSeconds = max(
            1, int(settings.get("AllowanceFreshSeconds", 15))
        )
        self.surplusDropGraceSeconds = max(
            0, int(settings.get("SurplusDropGraceSeconds", 20))
        )
        self.carDisconnectConfirmSeconds = max(
            5, int(settings.get("CarDisconnectConfirmSeconds", 15))
        )

        # Raw distributor overhead is used only to make a safe 3-to-1 phase
        # fallback when the assigned 3-phase allowance is gated to 0 W. It
        # must be fresh: an old high value must never influence live control.
        self.rawOverheadFreshSeconds = max(
            5, int(settings.get("RawOverheadFreshSeconds", 15))
        )

        self.wattpilot = None
        self.allowance = 0
        self.allowanceValid = False
        self.allowanceUpdatedAt = 0
        self.allowanceBelowMinimumSince = 0
        self.surplusSince = 0
        self.surplusBelowMinimumSince = 0
        self.noAllowanceForcedOff = False

        # Keep the last confirmed connection through a short telemetry glitch.
        # A physical false reading is only accepted as a disconnect after it
        # has been stable for CarDisconnectConfirmSeconds.
        self.carDisconnectedSince = 0
        self.lastConfirmedCarConnected = False
        self.effectiveCarConnected = False
        self.lastPhaseSwitchTime = 0
        self.phaseSwitchCandidateMode = 0
        self.phaseSwitchCandidateSince = 0
        self.phaseSwitchBelowThresholdSince = 0
        self.lastOnOffTime = 0
        self.lastVarDump = 0
        self.chargingTime = 0
        self.currentPhaseMode = 1  # 1 = one phase, 2 = Wattpilot three-phase code
        self.mode: VrmEvChargerControlMode = VrmEvChargerControlMode.Manual
        self.autostart = 0
        self.noChargeSince = 0
        self.isIdleMode = False
        self.isHibernateEnabled = settings["HibernateMode"].lower() == "true"
        self.wattpilotDashboardTransportUnavailable = False
        self.mqttAllowanceTopic = 'es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Allowance'
        # SolarOverheadDistributor already publishes its raw, pre-allocation
        # overhead on MQTT. Keep a local copy as a reliable fallback for the
        # D-Bus subscription: both services may start in either order.
        self.mqttRawOverheadTopic = (
            'es-ESS/SolarOverheadDistributor/Calculations/OverheadAvailable'
        )
        self.mqttRawOverheadW = None
        self.mqttRawOverheadUpdatedAt = 0

        self.batteryAssistSince = 0
        self.batteryAssistActive = False
        self.batteryAssistShortfallW = 0
        # A timeout lockout persists after the active assist timer is cleared.
        # It is released only after verified PV recovery or a real disconnect.
        self.batteryAssistLockedOut = False
        self.batteryAssistLockoutSince = 0
        self.batteryAssistRecoverySince = 0

        # Charge-complete hold persists for the current plugged-in session.
        # It is not a stop command: the Wattpilot remains in its present state.
        self.chargeCompleteHold = False
        self.chargeCompleteSince = 0
        self.chargeCompleteResumeSince = 0

        self.gridImportSince = 0

        # Startup / phase-transition telemetry bridge. This is not a battery
        # assist: it only prevents a false 0 W allowance while the Wattpilot
        # has accepted a valid PV command but has not yet reported real power.
        self.powerTransitionUntil = 0
        self.powerTransitionExpectedW = 0
        self.powerTransitionReason = ""
        self.powerTransitionTelemetryReadyAt = 0

        # A command to change phases is not proof that the Wattpilot or car
        # actually changed phases. Keep a short confirmation window and fall
        # back safely if phase telemetry never confirms the requested state.
        self.pendingPhaseSwitchMode = 0
        self.pendingPhaseSwitchSince = 0

        # Populated in initDbusSubscriptions().
        self.batterySocDbus = None
        self.batterySocValid = False
        self.batteryPowerDbus = None
        self.batteryTelemetryValid = False
        self.batteryTelemetryUpdatedAt = 0
        self.gridL1Dbus = None
        self.gridL2Dbus = None
        self.gridL3Dbus = None
        self.gridL1Valid = False
        self.gridL2Valid = False
        self.gridL3Valid = False
        self.gridL1UpdatedAt = 0
        self.gridL2UpdatedAt = 0
        self.gridL3UpdatedAt = 0
        # Raw PV overhead calculated by SolarOverheadDistributor. This remains
        # meaningful even when a three-phase Wattpilot request is assigned 0 W
        # because the three-phase 6 A minimum cannot be met.
        self.overheadAvailableDbus = None

    def initDbusService(self):
        self.dbusService = VeDbusService(self.serviceName, bus=dbusConnection(), register=False)

        #dump root information about our service and register paths.
        self.dbusService.add_path('/Mgmt/ProcessName', __file__)
        self.dbusService.add_path('/Mgmt/ProcessVersion', Globals.currentVersionString + ' on Python ' + platform.python_version())
        self.dbusService.add_path('/Mgmt/Connection', "dbus")

        # Create the mandatory objects (plus some extras)
        self.dbusService.add_path('/DeviceInstance', int(self.vrmInstanceID))
        self.dbusService.add_path('/ProductId', 65535)
        self.dbusService.add_path('/ProductName', WATTPILOT_BASE_CUSTOM_NAME)
        self.dbusService.add_path('/CustomName', WATTPILOT_BASE_CUSTOM_NAME)
        self.dbusService.add_path('/Latency', None)    
        self.dbusService.add_path('/FirmwareVersion', Globals.currentVersionString)
        self.dbusService.add_path('/HardwareVersion', Globals.currentVersionString)
        self.dbusService.add_path('/Connected', 1)
        self.dbusService.add_path('/Serial', "1337")
        self.dbusService.add_path('/LastUpdate', 0)
        self.dbusService.add_path('/Ac/Energy/Forward', 0)
        self.dbusService.add_path('/Session/Energy', 0)
        self.dbusService.add_path('/Ac/L1/Power', 0)
        self.dbusService.add_path('/Ac/L2/Power', 0)
        self.dbusService.add_path('/Ac/L3/Power', 0)
        self.dbusService.add_path('/Ac/L1/Voltage', 0)
        self.dbusService.add_path('/Ac/L2/Voltage', 0)
        self.dbusService.add_path('/Ac/L3/Voltage', 0)
        self.dbusService.add_path('/Ac/L1/Current', 0)
        self.dbusService.add_path('/Ac/L2/Current', 0)
        self.dbusService.add_path('/Ac/L3/Current', 0)
        self.dbusService.add_path('/Ac/L1/PowerFactor', 0)
        self.dbusService.add_path('/Ac/L2/PowerFactor', 0)
        self.dbusService.add_path('/Ac/L3/PowerFactor', 0)
        self.dbusService.add_path('/ChargingTime', self.chargingTime)
        self.dbusService.add_path('/Session/Time', self.chargingTime)
        self.dbusService.add_path('/Ac/Power', 0)
        self.dbusService.add_path('/Ac/PowerPercent', 0)
        self.dbusService.add_path('/Ac/PowerMax', 0)
        self.dbusService.add_path('/Current', 0)
        self.dbusService.add_path('/AutoStart', self.autostart, writeable=False)
        self.dbusService.add_path('/SetCurrent', 0, writeable=True, onchangecallback=self._froniusHandleChangedValue)
        self.dbusService.add_path('/Status', 0)
        self.dbusService.add_path('/MaxCurrent', 0)
        self.dbusService.add_path('/Mode', self.mode.value, writeable=True, onchangecallback=self._froniusHandleChangedValue)
        self.dbusService.add_path('/Position', int(self.config['FroniusWattpilot']['Position'])) #
        self.dbusService.add_path('/Model', "Fronius Wattpilot")
        self.dbusService.add_path('/StartStop', 0, writeable=True, onchangecallback=self._froniusHandleChangedValue)

        #Additional Stuff, not required by definition
        self.dbusService.add_path('/CarState', None)
        # PhaseMode uses the human-facing phase count: 0 = unknown/transition,
        # 1 = one phase and 3 = three phases. The internal controller uses 2
        # as its three-phase state, so do not expose that internal value here.
        self.dbusService.add_path('/PhaseMode', 0)
        self.dbusService.add_path('/PhaseModeLiteral', 'Unknown')
        self.dbusService.add_path('/ModeLiteral', VrmEvChargerControlMode(0).name)
        self.dbusService.add_path('/StatusLiteral', VrmEvChargerStatus(0).name)
        self.dbusService.add_path('/StartStopLiteral', VrmEvChargerStartStop(0).name)
        self.dbusService.add_path('/LastChargeModeLiteral', None)
        self.dbusService.add_path('/PvAllowance', 0)
        self.dbusService.add_path('/BatteryAssist/Active', 0)
        self.dbusService.add_path('/BatteryAssist/Elapsed', 0)
        self.dbusService.add_path('/BatteryAssist/Shortfall', 0)
        self.dbusService.add_path('/BatteryAssist/LockedOut', 0)
        self.dbusService.add_path('/BatteryAssist/RecoveryElapsed', 0)
        self.dbusService.add_path('/ChargeComplete/Hold', 0)
        self.dbusService.add_path('/ChargeComplete/Elapsed', 0)
        self.dbusService.add_path('/ChargeComplete/ResumeElapsed', 0)
        self.dbusService.add_path('/GridImport', 0)

        self.dbusService.register()

    def initDbusSubscriptions(self):
        self.batterySocDbus = self.registerDbusSubscription(
            "com.victronenergy.system", "/Dc/Battery/Soc",
            callback=self.onBatterySocTelemetry,
            initialValueDefault=None,
        )
        self.batteryPowerDbus = self.registerDbusSubscription(
            "com.victronenergy.system", "/Dc/Battery/Power",
            callback=self.onBatteryPowerTelemetry,
            initialValueDefault=None,
        )
        self.gridL1Dbus = self.registerDbusSubscription(
            "com.victronenergy.system", "/Ac/Grid/L1/Power",
            callback=self.onGridL1Telemetry
        )
        self.gridL2Dbus = self.registerDbusSubscription(
            "com.victronenergy.system", "/Ac/Grid/L2/Power",
            callback=self.onGridL2Telemetry
        )
        self.gridL3Dbus = self.registerDbusSubscription(
            "com.victronenergy.system", "/Ac/Grid/L3/Power",
            callback=self.onGridL3Telemetry
        )
        self.overheadAvailableDbus = self.registerDbusSubscription(
            "com.victronenergy.settings.esESS_SolarOverheadDistributor",
            "/Calculations/OverheadAvailable"
        )

    def initMqttSubscriptions(self):
        self.registerMqttSubscription(
            self.mqttAllowanceTopic, callback=self.onMqttMessage
        )
        self.registerMqttSubscription(
            self.mqttRawOverheadTopic, callback=self.onMqttMessage
        )

    def onBatterySocTelemetry(self, subscription):
        self.recordBatterySocTelemetry(subscription.value)

    def recordBatterySocTelemetry(self, value):
        """Record whether the selected system-battery SOC is usable."""
        self.batterySocValid, _ = DecisionInputs.telemetry_sample(
            value, time.time()
        )

    def onBatteryPowerTelemetry(self, subscription):
        self.recordBatteryPowerTelemetry(subscription.value)

    def recordBatteryPowerTelemetry(self, value):
        """Timestamp selected-battery activity used to trust cached SOC."""
        self.batteryTelemetryValid, self.batteryTelemetryUpdatedAt = (
            DecisionInputs.telemetry_sample(value, time.time())
        )

    def onGridL1Telemetry(self, subscription):
        self.recordGridTelemetry("L1", subscription.value)

    def onGridL2Telemetry(self, subscription):
        self.recordGridTelemetry("L2", subscription.value)

    def onGridL3Telemetry(self, subscription):
        self.recordGridTelemetry("L3", subscription.value)

    def recordGridTelemetry(self, phase, value):
        """Record validity and receive time for one required grid-power phase."""
        valid, updatedAt = DecisionInputs.telemetry_sample(value, time.time())

        setattr(self, "grid{0}Valid".format(phase), valid)
        setattr(self, "grid{0}UpdatedAt".format(phase), updatedAt)

    def onMqttMessage(self, client, userdata, msg):
        """Receive Wattpilot allowance and raw distributor-overhead updates."""
        topic = getattr(msg, "topic", None)
        try:
            value = DecisionInputs.parse_finite_payload(msg.payload)

            if topic == self.mqttAllowanceTopic:
                self.allowance = value
                self.allowanceValid = True
                self.allowanceUpdatedAt = time.time()
                return

            if topic == self.mqttRawOverheadTopic:
                self.mqttRawOverheadW = max(0.0, value)
                self.mqttRawOverheadUpdatedAt = time.time()
        except Exception as ex:
            if topic == self.mqttAllowanceTopic:
                # A malformed message must invalidate any previously assigned
                # allowance. Raw overhead is not a substitute for it.
                self.allowance = 0
                self.allowanceValid = False
                self.allowanceUpdatedAt = time.time()
            c(
                self,
                "Exception while processing Wattpilot distributor message.",
                exc_info=ex,
            )

    def initWorkerThreads(self):
        self.registerWorkerThread(self._update, 5000)

    def signOfLive(self):
        pass

    def initFinalize(self):
        #Create the Wattpilot object and connect. 
        self.wattpilot = Wattpilot(self.config["FroniusWattpilot"]["Host"], self.config["FroniusWattpilot"]["Password"])
        self.wattpilot.set_command_guard(self.allowWattpilotCommand)
        self.wattpilot._auto_reconnect = True
        self.wattpilot._reconnect_interval = 30
        self.wattpilot.connect()
        
        #Wait for some information to arrive.
        if not Helper.waitTimeout(lambda: self.wattpilot.connected, 30):
            w(
                self,
                "Wattpilot connection not ready during startup; "
                "runtime status will stay deferred until telemetry arrives."
            )
        Helper.waitTimeout(lambda: self.wattpilot.power1 is not None, 30)
        Helper.waitTimeout(lambda: self.wattpilot.power2 is not None, 30)
        Helper.waitTimeout(lambda: self.wattpilot.power3 is not None, 30)

        if not Helper.waitTimeout(lambda: self.wattpilot.carStateReady, 30):
           w(
               self,
               "Wattpilot car state not ready during startup; "
               "runtime status will stay deferred until telemetry arrives."
           )

        Helper.waitTimeout(lambda: self.wattpilot.mode is not None, 30)
        Helper.waitTimeout(lambda: self.wattpilot.firmware is not None, 30)
        self.refreshWattpilotFirmwareCompatibility()

        #determine current modes.
        if (self.wattpilot.mode == WattpilotControlMode.ECO):
            self.autostart = 1
            self.mode = VrmEvChargerControlMode.Auto
        else:
            self.autostart = 0
            self.mode = VrmEvChargerControlMode.Manual
            
        self.publishServiceMessage(self, "Mode determined as: {0}".format(self.mode))

        # Determine the current phase mode from live power when it is available.
        # Missing startup telemetry is normal while the initial full-status
        # message is still arriving, so keep the observation path None-safe.
        power1 = DecisionInputs.finite_number(self.wattpilot.power1)
        power2 = DecisionInputs.finite_number(self.wattpilot.power2)
        if self.wattpilot.carConnected and power2 is not None and power2 > 0:
            self.currentPhaseMode = 2
            self.publishServiceMessage(self, "Currently charging on 3 phases.")
        elif self.wattpilot.carConnected and power1 is not None and power1 > 0:
            self.currentPhaseMode = 1
            self.publishServiceMessage(self, "Currently charging on 1 phase.")
        else:
            self.currentPhaseMode = 0
            if self.wattpilot.mode == WattpilotControlMode.ECO:
                self.publishServiceMessage(
                    self,
                    "Currently not charging. Negotiating automatic phase mode."
                )
                self.wattpilot.set_phases(0)  # autoselect
            else:
                self.publishServiceMessage(
                    self,
                    "Manual/default startup leaves Wattpilot phase mode unchanged."
                )

        self.dumpEvChargerInfo()

    def _froniusHandleChangedValue(self, path, value):
        i(self, "User/cerbo/vrm updated " + str(path) + " to " + str(value))

        if path == "/SetCurrent":
            if not self.wattpilotAutoControlSelected():
                self.rejectDirectWattpilotCommand(path)
                return False

            requestedCurrent = int(value)
            maxCurrent = self.getEffectiveMaxCurrent()

            # Never round a device-reported cap below the configured minimum
            # back up to the minimum. Doing so would command more current than
            # the Wattpilot, vehicle, or installation allows.
            if requestedCurrent <= 0 or not self.canChargeAtMinimumCurrent():
                self.wattpilot.set_power(0)
            else:
                if requestedCurrent > maxCurrent:
                    self.currentPhaseMode = 2
                    self.wattpilot.set_phases(2)
                    ampPerPhase = int(round(requestedCurrent / 3.0))
                else:
                    self.currentPhaseMode = 1
                    self.wattpilot.set_phases(1)
                    ampPerPhase = requestedCurrent

                ampPerPhase = min(maxCurrent, ampPerPhase)

                if ampPerPhase < self.minCurrentPerPhase:
                    self.wattpilot.set_power(0)
                else:
                    self.wattpilot.set_power(ampPerPhase)

        elif path == "/StartStop":
            if not self.wattpilotAutoControlSelected():
                self.rejectDirectWattpilotCommand(path)
                return False

            state = VrmEvChargerStartStop(value)
            self.dbusService["/StartStopLiteral"] = state.name

            if state == VrmEvChargerStartStop.Start:
                self.wattpilot.set_start_stop(WattpilotStartStop.On)
            elif state == VrmEvChargerStartStop.Stop:
                self.wattpilot.set_start_stop(WattpilotStartStop.Off)

        elif path == "/Mode":
            priorMode = self.mode
            newMode = VrmEvChargerControlMode(value)
            self.switchMode(priorMode, newMode)

        self.dumpEvChargerInfo()
        return True

    def wattpilotAutoControlSelected(self):
        """Return True only when Wattpilot telemetry confirms ECO control."""
        try:
            wattpilotMode = getattr(self.wattpilot, "mode", None)
        except Exception:
            return False

        return wattpilotMode == WattpilotControlMode.ECO

    def rejectDirectWattpilotCommand(self, path):
        self.publishServiceMessage(
            self,
            "Ignored {0} command because Wattpilot is not in Auto/ECO mode.".format(
                path
            )
        )
        self.dumpEvChargerInfo()

    def releaseAutoControlLimitsForManualMode(self):
        """Release stale Auto/Eco phase and current commands once on Manual entry."""
        self.clearBatteryAssist()
        self.clearPowerTransitionGrace()
        self.clearPendingPhaseSwitch()
        self.clearPhaseSwitchCandidate()
        self.currentPhaseMode = 0

        self.publishServiceMessage(
            self,
            "Manual mode selected. Releasing Auto/Eco phase and current limits."
        )
        self.wattpilot.set_phases(0)
        self.wattpilot.set_power(self.getEffectiveMaxCurrent())

    def switchMode(self, fromMode:VrmEvChargerControlMode, toMode:VrmEvChargerControlMode):
        # TODO: When we are in hibernate mode, and attempting to switch mode, it fails, because of 
        #       Hibernate. Maybe needs resolution? WakeUp + KeepAlive? -> Would need a generally different
        #       pattern to enter / leave hibernation than the current one. 
        d("FroniusWattpilot", "Switching Mode from {0} to {1}.".format(fromMode, toMode))
        
        self.publishServiceMessage(self, "Switching Mode from {0} to {1}.".format(fromMode, toMode))

        if (toMode == VrmEvChargerControlMode.Auto or toMode == VrmEvChargerControlMode.Manual):
            self.mode = toMode
            self.dbusService["/Mode"] = toMode.value
            self.dbusService["/ModeLiteral"] = toMode.name

            if (fromMode == VrmEvChargerControlMode.Manual and toMode == VrmEvChargerControlMode.Auto):
                self.autostart = 1
                self.wattpilot.set_mode(WattpilotControlMode.ECO)

            elif (fromMode == VrmEvChargerControlMode.Auto and toMode == VrmEvChargerControlMode.Manual):
                self.autostart = 0
                self.clearChargeCompleteHold("manual mode selected")
                self.wattpilot.set_mode(WattpilotControlMode.Default)
                self.releaseAutoControlLimitsForManualMode()

        elif (toMode == VrmEvChargerControlMode.Scheduled):
            #Scheduled Charge - this is not used. We use this to temorary wakeup wattpilot, if in Hibernate mode. 
            self.wakeUpWattpilot()
            self.switchMode(VrmEvChargerControlMode.Scheduled, fromMode)
         
    def wakeUpWattpilot(self):
       if self.wattpilot.connected:
          self.isIdleMode = False
          return

       now = time.time()

       if hasattr(self, "lastReconnectAttempt"):
          if now - self.lastReconnectAttempt < 35:
             d(self, "Reconnect already attempted recently; waiting.")
             return

       self.lastReconnectAttempt = now

       self.publishServiceMessage(
          self,
          "Connecting to wattpilot to verify car status.",
       )

       self.wattpilot._auto_reconnect = True
       self.wattpilot.connect()
       self.isIdleMode = False

    def controlStateInputs(
        self,
        effectiveCarConnected=None,
        gridTelemetryFresh=True,
        gridImportLimitExceeded=False,
        phaseDownForPvDip=False,
        pendingPhaseStatus=False,
        transportUnavailable=False,
    ):
        modelStatus = getattr(self.wattpilot, "modelStatus", None)
        lowPriceStatus = getattr(
            WattpilotModelStatus, "ChargingBecauseAwattarPriceLow", None
        )
        phaseSwitchStatus = getattr(
            WattpilotModelStatus, "NotChargingBecausePhaseSwitch", None
        )
        if effectiveCarConnected is None:
            effectiveCarConnected = getattr(self, "effectiveCarConnected", False)

        return ControlStates.ControlStateInputs(
            transport_unavailable=transportUnavailable,
            auto_mode=self.mode == VrmEvChargerControlMode.Auto,
            allow_grid_charging=self.allowGridCharging,
            grid_telemetry_fresh=gridTelemetryFresh,
            grid_import_limit_exceeded=gridImportLimitExceeded,
            current_phase_mode=self.currentPhaseMode,
            phase_down_for_pv_dip=phaseDownForPvDip,
            pending_phase_status=bool(pendingPhaseStatus),
            effective_car_connected=bool(effectiveCarConnected),
            model_status_value=getattr(modelStatus, "value", None),
            external_low_price=(
                lowPriceStatus is not None
                and modelStatus == lowPriceStatus
            ),
            phase_switching=(
                phaseSwitchStatus is not None
                and modelStatus == phaseSwitchStatus
            ),
        )

    def selectControlState(self, effectiveCarConnected, gridTelemetryFresh):
        if (
            self.mode == VrmEvChargerControlMode.Auto
            and not self.allowGridCharging
            and not gridTelemetryFresh
        ):
            inputs = self.controlStateInputs(
                effectiveCarConnected=effectiveCarConnected,
                gridTelemetryFresh=gridTelemetryFresh,
            )
            return ControlStates.select_control_state(inputs), None, inputs

        gridImportLimitExceeded = False
        phaseDownForPvDip = False
        if (
            self.mode == VrmEvChargerControlMode.Auto
            and not self.allowGridCharging
            and self.gridImportLimitExceeded()
        ):
            gridImportLimitExceeded = True
            phaseDownForPvDip = (
                self.currentPhaseMode == 2
                and self.shouldPhaseDownForPvDip()
            )
            inputs = self.controlStateInputs(
                effectiveCarConnected=effectiveCarConnected,
                gridTelemetryFresh=gridTelemetryFresh,
                gridImportLimitExceeded=gridImportLimitExceeded,
                phaseDownForPvDip=phaseDownForPvDip,
            )
            return ControlStates.select_control_state(inputs), None, inputs

        pendingPhaseStatus = self.reconcilePendingPhaseSwitch()
        inputs = self.controlStateInputs(
            effectiveCarConnected=effectiveCarConnected,
            gridTelemetryFresh=gridTelemetryFresh,
            pendingPhaseStatus=pendingPhaseStatus is not None,
        )
        return ControlStates.select_control_state(inputs), pendingPhaseStatus, inputs

    def dispatchControlState(
        self,
        selectedState,
        effectiveCarConnected,
        pendingPhaseStatus,
    ):
        state = ControlStates.WattpilotControlState

        if selectedState == state.TRANSPORT_UNAVAILABLE:
            return self._handleTransportUnavailable()

        if selectedState == state.GRID_TELEMETRY_UNSAFE:
            return self._handleGridTelemetryUnsafe()

        if selectedState == state.GRID_IMPORT_PHASE_DOWN:
            return self._handleGridImportPhaseDown()

        if selectedState == state.GRID_IMPORT_STOP:
            return self._handleGridImportStop()

        if selectedState == state.PENDING_PHASE_SWITCH:
            return self._handlePendingPhaseSwitch(pendingPhaseStatus)

        if selectedState == state.DISCONNECTED:
            return self._handleDisconnected()

        if selectedState == state.CHARGING:
            self.handleChargingState()
            return False

        if selectedState == state.NOT_CHARGING:
            self.handleNotChargingState()
            return False

        if selectedState == state.EXTERNAL_LOW_PRICE:
            return self._handleExternalLowPrice()

        if selectedState == state.PHASE_SWITCHING:
            return self._handlePhaseSwitching()

        return self._handleUnknownControlState()

    def _handleTransportUnavailable(self):
        return self._handleUnknownControlState()

    def _handleGridTelemetryUnsafe(self):
        self.publishServiceMessage(
            self,
            "Grid telemetry is missing, invalid, or stale. "
            "Stopping Auto/Eco charging for safety."
        )
        if self.wattpilotReportsActiveCharge():
            self.reportVRMStatus(VrmEvChargerStatus.StopCharging)
            self.forceStopForNoAllowance()
        else:
            self.reportVRMStatus(VrmEvChargerStatus.WaitingForSun)
            self.forceStopForNoAllowance()
        return True

    def _handleGridImportPhaseDown(self):
        self.publishServiceMessage(
            self,
            "Grid import guard triggered, but PV supports 1-phase. "
            "Switching to 1-phase before stopping."
        )
        self.reportVRMStatus(self.switchToOnePhaseForPvDip())
        return True

    def _handleGridImportStop(self):
        self.publishServiceMessage(
            self,
            "Grid import guard triggered. Stopping EV charging."
        )
        self.reportVRMStatus(VrmEvChargerStatus.StopCharging)
        self.forceStopForNoAllowance()
        return True

    def _handlePendingPhaseSwitch(self, pendingPhaseStatus):
        self.reportVRMStatus(pendingPhaseStatus)
        return True

    def _handleDisconnected(self):
        self.reportVRMStatus(VrmEvChargerStatus.Disconnected)
        self.noChargeSince = 0
        self.surplusSince = 0
        self.surplusBelowMinimumSince = 0
        self.noAllowanceForcedOff = False
        self.clearBatteryAssist()
        self.clearBatteryAssistLockout("car disconnected")
        self.clearChargeCompleteHold("car disconnected")
        self.clearPowerTransitionGrace()
        self.clearPendingPhaseSwitch()
        # Safety telemetry was published before state dispatch in this duty
        # cycle. Republish the cleared values now because idle mode may defer
        # the next normal update for up to five minutes.
        self.publishSafetyTelemetry()
        return False

    def _handleExternalLowPrice(self):
        # In automatic mode this project is configured for no grid
        # charging. Manual mode remains under the user's direct control.
        if (
            self.mode == VrmEvChargerControlMode.Auto
            and not self.allowGridCharging
        ):
            self.publishServiceMessage(
                self,
                "Grid-price charging is disabled in Auto mode. Stopping EV charging."
            )
            self.reportVRMStatus(VrmEvChargerStatus.StopCharging)
            self.forceStopForNoAllowance()
        else:
            self.handleExternalChargingState("LowPrice")
        return False

    def _handlePhaseSwitching(self):
        self.chargingTime += 5
        if self.currentPhaseMode == 1:
            self.reportVRMStatus(VrmEvChargerStatus.SwitchingTo1Phase)
        elif self.currentPhaseMode == 2:
            self.reportVRMStatus(VrmEvChargerStatus.SwitchingTo3Phase)
        return False

    def _handleUnknownControlState(self):
        w(
            self,
            "Unknown Modelstatus reported: {0} - doing nothing.".format(
                self.wattpilot.modelStatus
            )
        )
        return False

    def refreshWattpilotFirmwareCompatibility(self):
        actual = None
        if self.wattpilot is not None:
            actual = getattr(self.wattpilot, "firmware", None)
        self.actualWattpilotFirmware = actual
        compatible = RuntimeCompatibility.wattpilot_firmware_is_validated(actual)
        self.wattpilotFirmwareCompatible = compatible

        state = (compatible, str(actual) if actual is not None else None)
        if state != self._lastWattpilotCompatibilityState:
            if compatible:
                message = (
                    "Wattpilot firmware compatibility confirmed: {0}."
                ).format(actual)
            else:
                message = (
                    "Wattpilot firmware compatibility not confirmed. Expected "
                    "{0}, received {1}. All es-ESS Wattpilot commands are blocked."
                ).format(
                    self.validatedWattpilotFirmware,
                    actual if actual is not None else "<unavailable>",
                )
            self.publishServiceMessage(self, message)
            if compatible:
                i(self, message)
            else:
                w(self, message)
            self._lastWattpilotCompatibilityState = state
        return compatible

    def allowWattpilotCommand(self, _name=None, _value=None):
        """Authorize commands only after exact ``fwv`` validation."""
        return self.refreshWattpilotFirmwareCompatibility()

    def _update(self):
        try:
            if self.updateWattpilotTransportDashboardStatus():
                return

            if not self.refreshWattpilotFirmwareCompatibility():
                return False

            effectiveCarConnected = self.updateEffectiveCarConnection()
            modeTelemetryPending = self.modeTelemetryNeedsControllerCycle()

            # In idle mode the charger is polled only every five minutes. While a
            # car is connected (or briefly disconnecting) we run every five
            # seconds for PV and safety control. A newly received Wattpilot mode
            # must also run on that five-second cadence so disconnected Manual
            # ownership and /ModeLiteral reporting cannot remain stale until the
            # next idle dump.
            if not (
                effectiveCarConnected
                or not self.isIdleMode
                or self.lastVarDump < (time.time() - 300)
                or not self.wattpilot.carStateReady
                or modeTelemetryPending
            ):
                return

            self.lastVarDump = time.time()
            skipIdleCheck = False

            if self.wattpilot.carStateReady:
                if not self.isIdleMode and not effectiveCarConnected:
                    self.publishServiceMessage(
                        self, "Car no longer connected. Switching to Idle-Mode."
                    )
                    if self.isHibernateEnabled:
                        self.publishServiceMessage(
                            self, "Hibernate is enabled. Disconnecting from wattpilot."
                        )
                        self.wattpilot._auto_reconnect = False
                        self.wattpilot.disconnect()

                elif self.isIdleMode:
                    if self.wattpilot.connected and effectiveCarConnected:
                        self.publishServiceMessage(
                            self, "Car connected. Switching to Operation-Mode."
                        )
                    elif not self.wattpilot.connected:
                        self.wakeUpWattpilot()
                        skipIdleCheck = True
                        if Helper.waitTimeout(lambda: self.wattpilot.carStateReady, 30):
                            if self.wattpilot.carConnected:
                                self.publishServiceMessage(
                                    self, "Car connected. Entering operation mode."
                                )

                if not skipIdleCheck:
                    self.isIdleMode = not effectiveCarConnected
            else:
                d(self, "Car State not yet ready, not performing idle checks.")

            d(
                self,
                "Wattpilot Modelstatus: {0}".format(self.wattpilot.modelStatus)
            )

            priorMode = self.mode

            # Reflect the mode selected in the Wattpilot.
            if self.wattpilot.mode == WattpilotControlMode.ECO:
                self.autostart = 1
                self.mode = VrmEvChargerControlMode.Auto
            else:
                self.autostart = 0
                self.mode = VrmEvChargerControlMode.Manual
                self.clearChargeCompleteHold("manual mode selected")
                if priorMode == VrmEvChargerControlMode.Auto:
                    self.releaseAutoControlLimitsForManualMode()

            self.reportStartStopValue(
                VrmEvChargerStartStop.Start
                if self.wattpilot.power != 0
                else VrmEvChargerStartStop.Stop
            )

            if not self.wattpilot.carStateReady:
                d(self, "Car state not ready yet.")
                return

            self.publishSafetyTelemetry()
            gridTelemetryFresh = self.gridTelemetryIsFresh()

            selectedState, pendingPhaseStatus, _inputs = self.selectControlState(
                effectiveCarConnected,
                gridTelemetryFresh,
            )
            shouldReturn = self.dispatchControlState(
                selectedState,
                effectiveCarConnected,
                pendingPhaseStatus,
            )
            if shouldReturn:
                self.reportBaseRequest()
                self.dumpEvChargerInfo()
                return

            self.reportBaseRequest()
            self.dumpEvChargerInfo()

        except Exception as ex:
            c(self, "Exception during duty-cycle.", exc_info=ex)
            if self.autoControlActive():
                self.failSafeStopForAutoControlFault()


    def handleChargingState(self):
        measuredPowerW = self.actualMeasuredPowerW()

        # Near a vehicle's target SOC, it can report a Charging model state
        # while drawing only a small balancing or keep-alive load. Use a
        # configurable threshold rather than requiring an exact 0 W reading.
        if measuredPowerW <= self.chargeCompletePowerThresholdW:
            self.noChargeSince += 5
        else:
            self.noChargeSince = 0

        if self.mode == VrmEvChargerControlMode.Auto:
            if self.chargeCompleteHold:
                if not self.updateChargeCompleteHoldResume(measuredPowerW):
                    self.clearBatteryAssist()
                    self.clearPowerTransitionGrace()
                    self.publishRetained(
                        "/LastChargeModeLiteral", "ChargeCompleteHold"
                    )
                    self.reportVRMStatus(VrmEvChargerStatus.Charged)
                    self.reportConsumption()
                    return

                # A genuine sustained resume was detected. Continue with the
                # normal Auto path in this same cycle.
                self.noChargeSince = 0

            if self.noChargeSince >= self.chargeCompleteConfirmSeconds:
                self.enterChargeCompleteHold()
                self.clearBatteryAssist()
                self.clearPowerTransitionGrace()
                self.publishRetained(
                    "/LastChargeModeLiteral", "ChargeCompleteHold"
                )
                self.reportVRMStatus(VrmEvChargerStatus.Charged)
                self.reportConsumption()
                return

        self.chargingTime += 5
        self.publishRetained("/LastChargeModeLiteral", "SolarOverhead")

        if self.mode == VrmEvChargerControlMode.Auto:
            self.reportVRMStatus(self.controlAutomaticCharging())
        else:
            d(self, "Charging in manual mode.")
            self.reportVRMStatus(VrmEvChargerStatus.Charging)

        self.reportConsumption()

    def handleExternalChargingState(self, chargeMode):
        if self.wattpilot.power is None or self.wattpilot.power <= 0:
            self.noChargeSince += 5
        else:
            self.noChargeSince = 0

        if self.noChargeSince >= 120:
            self.reportVRMStatus(VrmEvChargerStatus.Charged)
            return

        self.chargingTime += 5
        self.reportVRMStatus(VrmEvChargerStatus.Charging)
        self.reportConsumption()
        self.publishRetained("/LastChargeModeLiteral", chargeMode)

    def handleNotChargingState(self):
        # Wattpilot uses NotChargingBecauseSimulateUnplugging while it applies
        # a newly commanded start or phase change. Do not reset the five-minute
        # PV timer or issue another Off command during this short transition.
        if self.powerTransitionGraceActive():
            allowanceStatus = self.transitionAllowanceSafetyStatus(
                VrmEvChargerStatus.StartCharging
            )
            if allowanceStatus is not None:
                self.reportVRMStatus(allowanceStatus)
                return

            self.reportVRMStatus(VrmEvChargerStatus.StartCharging)
            d(
                self,
                "Waiting for Wattpilot transition telemetry: {0:.0f}W expected for {1:.0f}s.".format(
                    self.powerTransitionExpectedW,
                    max(0, self.powerTransitionUntil - time.time())
                )
            )
            return

        self.clearBatteryAssist()

        # Do not restart, phase switch, or force the charger off after a car
        # has completed charging. The hold is cleared by a real unplug event,
        # Manual mode, or a sustained meaningful charging resume.
        if self.chargeCompleteHold:
            self.publishRetained("/LastChargeModeLiteral", "ChargeCompleteHold")
            self.reportVRMStatus(VrmEvChargerStatus.Charged)
            return

        if self.mode != VrmEvChargerControlMode.Auto:
            self.reportVRMStatus(VrmEvChargerStatus.Connected)
            return

        if not self.allowGridCharging and not self.gridTelemetryIsFresh():
            self.publishServiceMessage(
                self,
                "Grid telemetry is missing, invalid, or stale. "
                "Blocking Auto/Eco charging until telemetry recovers."
            )
            self.reportVRMStatus(VrmEvChargerStatus.WaitingForSun)
            self.forceStopForNoAllowance()
            return

        # Keep a previously accumulated start timer through one short PV dip.
        # A full reset only occurs after SurplusDropGraceSeconds of genuinely
        # insufficient allowance.
        stableSeconds = self.getContinuousSurplusSeconds()

        if not self.hasMinimumAllowance():
            if self.surplusDipGraceActive():
                self.reportVRMStatus(VrmEvChargerStatus.WaitingForSun)
                d(
                    self,
                    "Brief PV allowance dip; preserving start timer for {0:.0f}s.".format(
                        max(0, self.surplusDropGraceSeconds - (
                            time.time() - self.surplusBelowMinimumSince
                        ))
                    )
                )
                return

            d(self, "Waiting for Sun in auto mode")
            self.reportVRMStatus(VrmEvChargerStatus.WaitingForSun)
            self.forceStopForNoAllowance()
            return

        onOffCooldownSeconds = self.getOnOffCooldownSeconds()

        if (
            stableSeconds >= self.minimumOnOffSeconds
            and onOffCooldownSeconds <= 0
        ):
            self.startFromPvAllowance()
        else:
            if stableSeconds < self.minimumOnOffSeconds:
                statusLiteral = (
                    "Waiting for stable PV allowance ({0:.0f}/{1}s)".format(
                        stableSeconds, self.minimumOnOffSeconds
                    )
                )
                self.reportVRMStatus(
                    VrmEvChargerStatus.WaitingForSun, statusLiteral
                )
                d(self, statusLiteral)
            else:
                statusLiteral = "Waiting for start cooldown ({0:.0f}s)".format(
                    onOffCooldownSeconds
                )
                self.reportVRMStatus(
                    VrmEvChargerStatus.WaitingForSun, statusLiteral
                )
                d(self, statusLiteral)


    def startFromPvAllowance(self):
        # Defend the command boundary as well as the caller. A start must not
        # race a missing/stale allowance or no-grid telemetry outage.
        if not self.allowanceIsFresh():
            self.publishServiceMessage(
                self,
                "Wattpilot PV allowance is missing, invalid, or stale. "
                "Not starting Auto/Eco charging."
            )
            self.reportVRMStatus(VrmEvChargerStatus.WaitingForSun)
            return

        if not self.allowGridCharging and not self.gridTelemetryIsFresh():
            self.publishServiceMessage(
                self,
                "Grid telemetry is missing, invalid, or stale. "
                "Not starting Auto/Eco charging."
            )
            self.reportVRMStatus(VrmEvChargerStatus.WaitingForSun)
            return

        desiredPhaseMode = self.desiredPhaseModeForPvAllowance()
        targetAmps = self.targetCurrentForPhase(
            desiredPhaseMode, self.allowance
        )

        if targetAmps < self.minCurrentPerPhase:
            self.publishServiceMessage(
                self,
                "PV allowance cannot satisfy the effective Wattpilot current minimum. Not starting EV charging."
            )
            self.reportVRMStatus(VrmEvChargerStatus.WaitingForSun)
            return

        self.reportVRMStatus(VrmEvChargerStatus.StartCharging)
        self.publishServiceMessage(
            self,
            "Starting to charge after {0:.0f}s of continuous PV allowance.".format(
                self.getContinuousSurplusSeconds()
            )
        )

        self.currentPhaseMode = desiredPhaseMode
        self.beginPowerTransitionGrace(
            desiredPhaseMode,
            targetAmps,
            "EV start"
        )
        self.wattpilot.set_phases(desiredPhaseMode)
        self.wattpilot.set_power(targetAmps)
        self.wattpilot.set_start_stop(WattpilotStartStop.On)
        self.lastOnOffTime = time.time()
        self.noAllowanceForcedOff = False
        self.allowanceBelowMinimumSince = 0
        self.surplusSince = 0
        self.surplusBelowMinimumSince = 0
        self.dbusService["/StartStop"] = VrmEvChargerStartStop.Start.value
        self.dbusService["/StartStopLiteral"] = VrmEvChargerStartStop.Start.name


    def controlAutomaticCharging(self):
        # No-grid operation requires current, valid L1/L2/L3 telemetry. Do not
        # wait for the allowance grace because unknown grid import is unsafe.
        if not self.allowGridCharging and not self.gridTelemetryIsFresh():
            self.clearBatteryAssist()
            self.publishServiceMessage(
                self,
                "Grid telemetry is missing, invalid, or stale. "
                "Stopping Auto/Eco charging for safety."
            )
            self.forceStopForNoAllowance()
            return VrmEvChargerStatus.StopCharging

        # Missing, invalid, and stale allowance are all insufficient. The
        # existing allowance-drop grace applies only to an already-running
        # session, never to a new start or a raw-overhead fallback.
        if not self.allowanceIsFresh():
            self.clearBatteryAssist()
            if self.allowanceStopGraceActive():
                return VrmEvChargerStatus.Charging
            self.publishServiceMessage(
                self,
                "Wattpilot PV allowance is missing, invalid, or stale. "
                "Stopping Auto/Eco charging for safety."
            )
            self.forceStopForNoAllowance()
            return VrmEvChargerStatus.StopCharging

        # Defensive guard: a completed EV session must not re-enter automatic
        # PV, phase-switch, battery-assist, or stop logic while it remains
        # plugged in.
        if self.chargeCompleteHold:
            self.clearBatteryAssist()
            return VrmEvChargerStatus.Charged

        # The Wattpilot may report a temporary 0 W allowance while it is still
        # bringing a valid new charge command online. Keep the session alive
        # until one distributor cycle has seen the real EV power telemetry.
        if self.powerTransitionGraceActive():
            d(
                self,
                "Holding EV charge during Wattpilot transition telemetry grace."
            )
            return VrmEvChargerStatus.Charging

        # Use one shared stability interval for both phase directions. During
        # a sustained three-phase PV deficit, keep the existing phase command
        # only while bounded battery assist is eligible or grid fallback is
        # explicitly allowed. A no-grid session that cannot bridge safely
        # reduces to one phase immediately when possible, otherwise it stops.
        phaseDownStatus = self.controlThreePhasePvDeficit()
        if phaseDownStatus is not None:
            return phaseDownStatus

        pvAllowance = max(0, self.allowance)
        activeDemandW = self.currentChargeDemandPower()
        shortfallW = max(0, activeDemandW - pvAllowance)

        # A completed assist window stays locked out until PV has continuously
        # covered the current EV demand for the configured recovery period.
        self.updateBatteryAssistLockoutRecovery(shortfallW)

        # A battery bridge is allowed only for a currently-running charge. It
        # holds the existing phase/current and cannot create a phase-up
        # candidate or issue a phase command. When a one-phase candidate
        # already exists, this continuation path intentionally leaves its
        # wall-clock timer unchanged through the bounded assist window. Fresh
        # assigned allowance must still recover to the full phase-up threshold
        # before adjustChargeForPvAllowance() can issue the command.
        if self.startOrContinueBatteryAssist(shortfallW):
            self.publishServiceMessage(
                self,
                "Battery assist active: {0:.0f}W shortfall for {1:.0f}s.".format(
                    shortfallW, self.getBatteryAssistSeconds()
                )
            )
            return VrmEvChargerStatus.Charging

        self.clearBatteryAssist()

        # Grid fallback is continuation-only. New Auto/Eco starts still pass
        # through startFromPvAllowance() and therefore require real PV. For an
        # already-running charge, hold the existing phase/current rather than
        # stopping when the configured site explicitly permits grid import.
        if self.allowGridCharging and shortfallW > 0:
            self.allowanceBelowMinimumSince = 0
            return VrmEvChargerStatus.Charging

        if self.hasMinimumAllowance():
            self.allowanceBelowMinimumSince = 0
            return self.adjustChargeForPvAllowance()

        # The control and distribution workers can run in either order. Hold a
        # still-active session briefly when allowance first drops to 0 W so a
        # fresh MQTT allowance can arrive before an irreversible Off command.
        if self.allowanceStopGraceActive():
            return VrmEvChargerStatus.Charging

        i(self, "NO PV allowance available after debounce, stopping charging.")
        self.forceStopForNoAllowance()
        return VrmEvChargerStatus.StopCharging


    def reportVRMStatus(self, status:VrmEvChargerStatus, statusLiteral=None):
        self.publish("/Status", status.value)
        self.publish("/StatusLiteral", statusLiteral or status.name)

    def updateWattpilotTransportDashboardStatus(self):
        unavailable = self.isWattpilotTransportUnavailableForDashboard()

        if unavailable:
            if not getattr(self, "wattpilotDashboardTransportUnavailable", False):
                self.publishServiceMessage(
                    self,
                    "Wattpilot is not accessible. Waiting for reconnect.",
                )
            self.wattpilotDashboardTransportUnavailable = True
            self.publish("/Connected", 0)
            self.reportVRMStatus(
                VrmEvChargerStatus.Disconnected,
                WATTPILOT_UNAVAILABLE_STATUS_LITERAL,
            )
            self.publishWattpilotCustomName(WATTPILOT_UNAVAILABLE_CUSTOM_NAME)
            return True

        if getattr(self, "wattpilotDashboardTransportUnavailable", False):
            self.wattpilotDashboardTransportUnavailable = False
            self.publish("/Connected", 1)
            self.publishWattpilotCustomName(WATTPILOT_BASE_CUSTOM_NAME)
            self.publishServiceMessage(
                self,
                "Wattpilot connection recovered.",
            )

        return False

    def isWattpilotTransportUnavailableForDashboard(self):
        if self.isIntentionalWattpilotIdleDisconnect():
            return False

        reporter = getattr(self, "_runtime_status_reporter", None)
        is_unavailable = getattr(
            reporter, "transport_unavailable_for_dashboard", None
        )
        if callable(is_unavailable):
            return bool(is_unavailable())

        if self.wattpilot is None:
            return False
        return not bool(getattr(self.wattpilot, "connected", False))

    def isIntentionalWattpilotIdleDisconnect(self):
        if not (
            getattr(self, "isHibernateEnabled", False)
            and getattr(self, "isIdleMode", False)
        ):
            return False
        if getattr(self, "effectiveCarConnected", False):
            return False
        if self.wattpilot is None:
            return False
        return not bool(getattr(self.wattpilot, "connected", False))

    def reportBaseRequest(self):
        if self.wattpilot.voltage1 is not None:
            minimumPower = (
                self.threePhaseMinimumPower()
                if self.currentPhaseMode == 2
                else self.minimumChargePower()
            )
            self.publishMainMqtt(
                "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Minimum",
                int(round(minimumPower))
            )

        # When a car is connected in Auto mode, allow real solar that would
        # otherwise charge the battery to be redirected to the EV. This does
        # not allow a battery-assisted start because FroniusWattpilot still
        # requires actual distributor allowance before a fresh start.
        ignoreReservation = self.shouldIgnoreBatteryReservation()
        self.publishMainMqtt(
            "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/IgnoreBatReservation",
            "true" if ignoreReservation else "false"
        )
        self.publishMainMqtt(
            "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/VRMInstanceID",
            self.config["FroniusWattpilot"]["VRMInstanceID_OverheadRequest"]
        )
        self.publishMainMqtt(
            "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/IsScriptedConsumer",
            "true"
        )
        self.publishMainMqtt(
            "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/PriorityShift",
            1
        )
        self.publishMainMqtt(
            "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Priority",
            self.config["FroniusWattpilot"]["OverheadPriority"]
        )

        if self.currentPhaseMode == 2:
            stepSize = self.threePhaseVoltage()
        else:
            stepSize = self.onePhaseVoltage()

        self.publishMainMqtt(
            "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/StepSize",
            int(round(stepSize))
        )

        effectiveCarConnected = getattr(
            self, "effectiveCarConnected", self.wattpilot.carConnected
        )
        if (
            self.mode == VrmEvChargerControlMode.Auto
            and effectiveCarConnected
            and not self.chargeCompleteHold
            and self.noChargeSince < self.chargeCompleteConfirmSeconds
            and self.canChargeAtMinimumCurrent()
        ):
            # A one-phase session must ask the distributor for enough power to
            # *decide* whether a three-phase change is possible. Previously it
            # advertised only the 1-phase maximum (~3.7 kW at 16 A), so its
            # assigned allowance could never reach the configured 3-phase
            # threshold (4.2 kW). Use a small phase-up probe instead of
            # advertising the full 3-phase maximum while still on one phase.
            maxRequest = self.maximumRequestForDistributorW()
            self.publishMainMqtt(
                "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Request",
                round(maxRequest)
            )
        else:
            self.publishMainMqtt(
                "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Request",
                0
            )

        self.publishMainMqtt(
            "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/IsAutomatic",
            "true" if self.mode == VrmEvChargerControlMode.Auto else "false"
        )

        self.reportPhaseMode()


    def reportConsumption(self):
        self.publishMainMqtt(
            "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Consumption",
            self.consumerPowerForDistributor()
        )

    def reportStartStopValue(self, v:VrmEvChargerStartStop):
        self.publish("/StartStop", v.value)
        self.publish("/StartStopLiteral", v.name)

    def reportPhaseMode(self):
        """Publish a human-readable charging-phase state for GX/VRM and MQTT.

        currentPhaseMode is an internal controller representation: 1 means
        one-phase and 2 means three-phase. Expose 1 or 3 to user interfaces
        instead, so the displayed phase count is never misleading.
        """
        charging = self.actualMeasuredPowerW() > 0

        if self.currentPhaseMode == 1:
            phaseCount = 1
            phaseLiteral = "1 phase"
        elif self.currentPhaseMode == 2:
            phaseCount = 3
            phaseLiteral = "3 phase"
        else:
            phaseCount = 0
            phaseLiteral = "Phase switching" if self.wattpilot.carConnected else "No vehicle"

        if charging:
            customName = "{0} - Charging {1}".format(
                WATTPILOT_BASE_CUSTOM_NAME, phaseLiteral
            )
        elif self.wattpilot.carConnected:
            customName = "{0} - Ready ({1})".format(
                WATTPILOT_BASE_CUSTOM_NAME, phaseLiteral
            )
        else:
            customName = "{0} - No vehicle".format(WATTPILOT_BASE_CUSTOM_NAME)

        # /CustomName is the only standard text field likely to be shown in the
        # standard GX/VRM EV charger view. /PhaseMode and /PhaseModeLiteral are
        # also published for MQTT, DBus inspection and custom dashboards.
        self.publish("/PhaseMode", phaseCount)
        self.publish("/PhaseModeLiteral", phaseLiteral)
        self.publishWattpilotCustomName(customName)

    def publishWattpilotCustomName(self, customName):
        self.publish("/CustomName", customName)

        # Keep the SolarOverheadDistributor's consumer name in sync as well.
        self.publishMainMqtt(
            "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/CustomName",
            customName
        )

    def minimumChargePower(self):
        return self.onePhaseVoltage() * self.minCurrentPerPhase

    def threePhaseMinimumPower(self):
        return self.threePhaseVoltage() * self.minCurrentPerPhase

    def allowanceIsFresh(self):
        return DecisionInputs.allowance_is_fresh(
            getattr(self, "allowanceValid", False),
            getattr(self, "allowanceUpdatedAt", 0),
            self.allowanceFreshSeconds,
            time.time(),
        )

    def hasMinimumAllowance(self):
        now = time.time()
        if not DecisionInputs.allowance_is_fresh(
            getattr(self, "allowanceValid", False),
            getattr(self, "allowanceUpdatedAt", 0),
            self.allowanceFreshSeconds,
            now,
        ):
            return False

        if not self.canChargeAtMinimumCurrent():
            return False

        return DecisionInputs.has_minimum_allowance(
            self.allowance,
            getattr(self, "allowanceValid", False),
            getattr(self, "allowanceUpdatedAt", 0),
            self.allowanceFreshSeconds,
            now,
            self.minimumChargePower(),
            True,
        )

    def onePhaseVoltage(self):
        voltage = self.wattpilot.voltage1
        return float(voltage) if voltage is not None and voltage > 0 else 230.0

    def threePhaseVoltage(self):
        voltages = [
            self.wattpilot.voltage1,
            self.wattpilot.voltage2,
            self.wattpilot.voltage3,
        ]
        if all(voltage is not None and voltage > 0 for voltage in voltages):
            return float(sum(voltages))
        return self.onePhaseVoltage() * 3.0

    def getEffectiveMaxCurrent(self):
        wattpilotLimit = self.wattpilot.ampLimit
        if wattpilotLimit is None or wattpilotLimit <= 0:
            return self.maxCurrentPerPhase
        return min(self.maxCurrentPerPhase, int(wattpilotLimit))

    def canChargeAtMinimumCurrent(self):
        """Return whether the reported/current configured limit can start EV charging."""
        return self.getEffectiveMaxCurrent() >= self.minCurrentPerPhase


    def phaseUpThresholdW(self):
        """Return the PV allocation required before changing to three phases."""
        return PhaseDecisions.phase_up_threshold_w(
            self.threePhasePvSurplusStartW,
            self.threePhaseMinimumPower(),
        )

    def maximumRequestForDistributorW(self):
        """Return the maximum allocation request for the current control state.

        When 1-phase charging is active (or is about to start), advertise a
        limited probe at the 3-phase threshold. This breaks the old feedback
        loop where a 1-phase cap prevented the allowance from ever reaching
        the threshold needed to select 3-phase. The probe is disabled during a
        configured phase-switch cooldown, so a recent 3-to-1 transition does
        not reserve unused power for five minutes.
        """
        maxCurrent = self.getEffectiveMaxCurrent()
        return PhaseDecisions.maximum_request_for_distributor_w(
            self.currentPhaseMode,
            maxCurrent,
            self.minCurrentPerPhase,
            self.onePhaseVoltage(),
            self.threePhaseVoltage(),
            self.phaseUpThresholdW(),
            self.getPhaseSwitchCooldownSeconds(),
        )

    def maxRequestVoltageForCurrentPhase(self):
        """Return the electrical voltage of the active phase mode.

        Allocation uses maximumRequestForDistributorW() so a 1-phase phase-up
        probe does not have to advertise the full 3-phase current capacity.
        """
        return (
            self.threePhaseVoltage()
            if self.currentPhaseMode == 2
            else self.onePhaseVoltage()
        )


    def desiredPhaseModeForPvAllowance(self):
        # Hysteresis: phase-up requires the configured higher threshold, while
        # phase-down happens below the configured lower threshold. Both are
        # clamped to the electrical three-phase 6 A minimum.
        return PhaseDecisions.desired_phase_mode(
            self.currentPhaseMode,
            self.allowance,
            self.phaseUpThresholdW(),
            self.phaseDownThresholdW(),
        )

    def targetCurrentForPhase(self, phaseMode, allowance):
        maxCurrent = self.getEffectiveMaxCurrent()
        return PhaseDecisions.target_current_for_phase(
            phaseMode,
            allowance,
            self.onePhaseVoltage(),
            self.threePhaseVoltage(),
            self.minCurrentPerPhase,
            maxCurrent,
        )

    def currentChargeDemandPower(self):
        actualPower = (
            float(self.wattpilot.power) * 1000
            if self.wattpilot.power is not None
            else 0
        )
        amp = self.wattpilot.amp
        if amp is None or amp <= 0:
            return actualPower

        voltage = (
            self.threePhaseVoltage()
            if self.currentPhaseMode == 2
            else self.onePhaseVoltage()
        )
        configuredDemand = float(amp) * voltage
        return max(actualPower, configuredDemand)

    def actualMeasuredPowerW(self):
        if self.wattpilot.power is None:
            return 0.0
        return max(0.0, float(self.wattpilot.power) * 1000.0)

    def beginPowerTransitionGrace(self, phaseMode, currentA, reason):
        voltage = self.threePhaseVoltage() if phaseMode == 2 else self.onePhaseVoltage()
        self.powerTransitionExpectedW = max(0.0, float(currentA) * voltage)
        self.powerTransitionUntil = time.time() + self.startupGraceSeconds
        self.powerTransitionReason = reason
        self.powerTransitionTelemetryReadyAt = 0
        self.publishServiceMessage(
            self,
            "{0} transition grace started: reporting {1:.0f}W until Wattpilot telemetry catches up.".format(
                reason,
                self.powerTransitionExpectedW
            )
        )

    def clearPowerTransitionGrace(self):
        self.powerTransitionUntil = 0
        self.powerTransitionExpectedW = 0
        self.powerTransitionReason = ""
        self.powerTransitionTelemetryReadyAt = 0

    def beginPhaseSwitchConfirmation(self, phaseMode):
        self.pendingPhaseSwitchMode = phaseMode
        self.pendingPhaseSwitchSince = time.time()

    def clearPendingPhaseSwitch(self):
        self.pendingPhaseSwitchMode = 0
        self.pendingPhaseSwitchSince = 0

    def phasePowerW(self, phase):
        value = getattr(self.wattpilot, "power{0}".format(phase), None)
        if value is None:
            return 0.0
        try:
            return max(0.0, float(value) * 1000.0)
        except (TypeError, ValueError):
            return 0.0

    def phaseTelemetryConfirmsMode(self, phaseMode):
        # Wattpilot reports phase power in kW. 100 W deliberately sits far
        # below the 6 A minimum, while avoiding noise around exactly zero.
        activeThresholdW = 100.0
        l2Active = self.phasePowerW(2) >= activeThresholdW
        l3Active = self.phasePowerW(3) >= activeThresholdW
        if phaseMode == 2:
            return l2Active and l3Active
        if phaseMode == 1:
            return not l2Active and not l3Active
        return False

    def reconcilePendingPhaseSwitch(self):
        """Confirm a requested phase switch or fail safely after grace expires.

        A phase-command acknowledgement is not enough: vehicle and Wattpilot
        telemetry must show the requested active phases. A failed 1-to-3
        change falls back to one phase and starts the configured cooldown. A
        failed 3-to-1 change stops Eco charging instead of leaving a live
        three-phase load on inadequate PV.
        """
        pending = getattr(self, "pendingPhaseSwitchMode", 0)
        if pending not in (1, 2):
            return None

        transitionStatus = (
            VrmEvChargerStatus.SwitchingTo3Phase
            if pending == 2
            else VrmEvChargerStatus.SwitchingTo1Phase
        )

        if self.phaseTelemetryConfirmsMode(pending):
            self.publishServiceMessage(
                self,
                "Wattpilot phase telemetry confirmed {0}-phase charging.".format(
                    3 if pending == 2 else 1
                )
            )
            self.clearPendingPhaseSwitch()
            return None

        allowanceStatus = self.transitionAllowanceSafetyStatus(transitionStatus)
        if allowanceStatus is not None:
            return allowanceStatus

        now = time.time()
        pendingSince = getattr(self, "pendingPhaseSwitchSince", 0)
        if pendingSince == 0:
            self.pendingPhaseSwitchSince = now
            pendingSince = now

        if now - pendingSince < self.startupGraceSeconds:
            return transitionStatus

        self.clearPowerTransitionGrace()

        if pending == 2:
            # Do not keep a false 3-phase controller state after the Wattpilot
            # or vehicle failed to provide L2/L3 power. Revert to one phase and
            # apply the assigned PV allowance only.
            targetAmps = self.targetCurrentForPhase(1, self.allowance)
            self.publishServiceMessage(
                self,
                "3-phase switch was not confirmed by Wattpilot telemetry. "
                "Falling back to 1-phase."
            )
            self.currentPhaseMode = 1
            self.lastPhaseSwitchTime = now
            self.wattpilot.set_phases(1)
            self.wattpilot.set_power(targetAmps)
            self.clearPendingPhaseSwitch()
            return VrmEvChargerStatus.SwitchingTo1Phase

        # A 3-to-1 command that is not confirmed could leave a three-phase
        # load on insufficient PV. Stop rather than risk battery/grid draw.
        self.publishServiceMessage(
            self,
            "1-phase fallback was not confirmed by Wattpilot telemetry. "
            "Stopping Eco charging for safety."
        )
        self.clearPendingPhaseSwitch()
        self.forceStopForNoAllowance()
        return VrmEvChargerStatus.StopCharging

    def powerTransitionGraceActive(self):
       if self.powerTransitionUntil == 0:
          return False

       now = time.time()

       # Expiry must be checked before the telemetry-ready branch.
       # Otherwise, a valid telemetry reading without a fresh allowance
       # can keep the grace state active forever.
       if now >= self.powerTransitionUntil:
          self.publishServiceMessage(
             self,
             "Wattpilot transition grace expired. Returning to normal PV control.",
          )
          self.clearPowerTransitionGrace()
          return False

       actualPower = self.actualMeasuredPowerW()
       expectedPower = self.powerTransitionExpectedW

       telemetryReady = (
          expectedPower <= 0
          or actualPower >= expectedPower * self.startupTelemetryRatio
       )

       if not telemetryReady:
          return True

       # Wait for one allowance update after valid charger telemetry.
       if self.powerTransitionTelemetryReadyAt == 0:
          self.powerTransitionTelemetryReadyAt = now
          d(
             self,
             "Wattpilot transition telemetry caught up: "
             "{0:.0f}W measured, {1:.0f}W expected. "
             "Waiting for refreshed allowance.".format(
                actualPower,
                expectedPower,
            ),
          )
          return True

       if self.allowanceUpdatedAt > self.powerTransitionTelemetryReadyAt:
          d(
             self,
             "Wattpilot transition allowance refreshed after telemetry caught up.",
          )
          self.clearPowerTransitionGrace()
          return False

       return True

    def consumerPowerForDistributor(self):
        actualPower = self.actualMeasuredPowerW()
        if self.powerTransitionGraceActive():
            return max(actualPower, self.powerTransitionExpectedW)
        return actualPower

    def getContinuousSurplusSeconds(self):
        now = time.time()

        if self.hasMinimumAllowance():
            self.surplusBelowMinimumSince = 0
            if self.surplusSince == 0:
                self.surplusSince = now
                self.publishServiceMessage(
                    self,
                    "PV allowance is sufficient. Waiting {0}s before starting charge.".format(
                        self.minimumOnOffSeconds
                    )
                )
            return now - self.surplusSince

        # Preserve an already-running start timer through a short dip. The
        # original code reset the full MinOnOffSeconds delay on every single
        # five-second low sample, which made charging fail to restart in
        # changeable sunshine.
        if self.surplusSince == 0:
            self.surplusBelowMinimumSince = 0
            return 0

        if self.surplusBelowMinimumSince == 0:
            self.surplusBelowMinimumSince = now
            self.publishServiceMessage(
                self,
                "PV allowance dipped below the one-phase minimum. Holding the "
                "start timer for up to {0}s.".format(
                    self.surplusDropGraceSeconds
                )
            )

        if now - self.surplusBelowMinimumSince < self.surplusDropGraceSeconds:
            return now - self.surplusSince

        self.publishServiceMessage(
            self,
            "PV allowance stayed below the one-phase minimum for {0}s. "
            "Resetting the start timer.".format(self.surplusDropGraceSeconds)
        )
        self.surplusSince = 0
        self.surplusBelowMinimumSince = 0
        return 0


    def surplusDipGraceActive(self):
        if self.surplusSince == 0 or self.surplusBelowMinimumSince == 0:
            return False
        return (
            time.time() - self.surplusBelowMinimumSince
            < self.surplusDropGraceSeconds
        )

    def wattpilotReportsActiveCharge(self):
        status = getattr(self.wattpilot, "modelStatus", None)
        statusValue = getattr(status, "value", None)
        return (
            statusValue in [3, 12, 15, 19, 20]
            or self.powerTransitionUntil > time.time()
        )

    def updateEffectiveCarConnection(self):
        """Debounce short false carConnected telemetry while preserving safety.

        The Wattpilot can emit one false car-connected update while it is still
        reporting a charging or transition state. Treat that as a telemetry
        glitch, not an unplug, so the distributor request is not reset to 0 W.
        """
        if bool(self.wattpilot.carConnected):
            if self.carDisconnectedSince != 0:
                self.publishServiceMessage(
                    self, "Wattpilot car connection telemetry recovered."
                )
            self.carDisconnectedSince = 0
            self.lastConfirmedCarConnected = True
            self.effectiveCarConnected = True
            return True

        if not self.lastConfirmedCarConnected:
            self.effectiveCarConnected = False
            return False

        if self.carDisconnectedSince == 0:
            self.carDisconnectedSince = time.time()
            self.publishServiceMessage(
                self,
                "Wattpilot reports car disconnected. Confirming for {0}s.".format(
                    self.carDisconnectConfirmSeconds
                )
            )

        if (
            time.time() - self.carDisconnectedSince
            < self.carDisconnectConfirmSeconds
        ):
            if self.wattpilotReportsActiveCharge():
                d(
                    self,
                    "Ignoring transient carConnected=false while Wattpilot reports an active charge or transition."
                )
            self.effectiveCarConnected = True
            return True

        if self.wattpilotReportsActiveCharge():
            self.publishServiceMessage(
                self,
                "Wattpilot car disconnect confirmed despite stale active charge status."
            )

        self.lastConfirmedCarConnected = False
        self.carDisconnectedSince = 0
        self.effectiveCarConnected = False
        return False

    def allowanceStopGraceActive(self):
        """Hold an active session briefly while awaiting a fresh allowance.

        The grid-import guard remains immediate. This helper only avoids an
        unnecessary stop when the distributor and Wattpilot workers execute in
        the opposite order for one or two cycles.
        """
        if self.hasMinimumAllowance() or not self.canChargeAtMinimumCurrent():
            self.allowanceBelowMinimumSince = 0
            return False

        if not self.wattpilotReportsActiveCharge():
            self.allowanceBelowMinimumSince = 0
            return False

        now = time.time()
        if self.allowanceBelowMinimumSince == 0:
            self.allowanceBelowMinimumSince = now
            self.publishServiceMessage(
                self,
                "EV allowance fell below the one-phase minimum. Waiting up to "
                "{0}s for a refreshed distributor allowance before stopping.".format(
                    self.allowanceDropGraceSeconds
                )
            )

        return (
            now - self.allowanceBelowMinimumSince
            < self.allowanceDropGraceSeconds
        )

    def transitionAllowanceSafetyStatus(self, transitionStatus):
        """Apply the normal allowance-stop grace during Auto/Eco transitions.

        Startup and phase-switch grace prevent a false zero-Wattpilot reading
        from revoking a valid command before charger telemetry catches up.
        They must not allow stale, missing, or insufficient distributor
        allowance to bypass the normal Auto/Eco stop policy. Manual mode is
        intentionally outside this guard.
        """
        if self.mode != VrmEvChargerControlMode.Auto:
            return None

        if self.hasMinimumAllowance():
            return None

        # A 3-to-1 reduction may be driven by fresh raw PV overhead because
        # the distributor can gate the three-phase assigned allowance to 0 W.
        # Permit only that already-running reduction; starts and phase-up still
        # require a fresh assigned PV allowance.
        if getattr(self, "pendingPhaseSwitchMode", 0) == 1:
            rawOverhead = self.rawPvOverheadW()
            if (
                rawOverhead is not None
                and rawOverhead >= self.minimumChargePower()
            ):
                return None

        self.clearBatteryAssist()
        if self.allowanceStopGraceActive():
            return transitionStatus

        self.publishServiceMessage(
            self,
            "Wattpilot PV allowance is missing, invalid, stale, or insufficient "
            "during a start or phase transition. Stopping Auto/Eco charging "
            "for safety."
        )
        self.forceStopForNoAllowance()
        return VrmEvChargerStatus.StopCharging

    def dbusValue(self, subscription, default=None):
        try:
            value = subscription.value
            numeric = float(value) if value is not None else None
            return numeric if numeric is not None and isfinite(numeric) else default
        except Exception:
            return default

    def gridTelemetryIsFresh(self):
        """Return whether all required grid-power inputs are valid and current."""
        samples = [
            (
                getattr(self, "grid{0}Valid".format(phase), False),
                getattr(self, "grid{0}UpdatedAt".format(phase), 0),
            )
            for phase in ("L1", "L2", "L3")
        ]
        return DecisionInputs.grid_telemetry_is_fresh(
            samples, self.gridTelemetryFreshSeconds, time.time()
        )

    def batterySoc(self):
        if not DecisionInputs.timestamped_value_is_fresh(
            getattr(self, "batteryTelemetryValid", False),
            getattr(self, "batteryTelemetryUpdatedAt", 0),
            self.batterySocFreshSeconds,
            time.time(),
        ):
            return None

        if not getattr(self, "batterySocValid", False):
            return None

        return self.dbusValue(self.batterySocDbus, None)

    def rawPvOverheadW(self):
        """Return a fresh raw PV-overhead value for 3-to-1 safety fallback.

        Raw overhead is deliberately accepted only from the timestamped MQTT
        feed. A D-Bus subscription can retain an old high value after the
        distributor or bus connection stops updating, and using that stale
        value could cause a false phase transition. Starts and phase-up always
        use the distributor's assigned allowance instead.
        """
        return DecisionInputs.fresh_raw_overhead(
            getattr(self, "mqttRawOverheadW", None),
            getattr(self, "mqttRawOverheadUpdatedAt", 0),
            self.rawOverheadFreshSeconds,
            time.time(),
        )

    def phaseDownThresholdW(self):
        return PhaseDecisions.phase_down_threshold_w(
            self.threePhasePvSurplusStopW,
            self.threePhaseMinimumPower(),
        )

    def shouldPhaseDownForPvDip(self):
        """Return True only for a confirmed, usable 3φ-to-1φ PV dip.

        The distributor publishes an assigned allowance. That value is the
        authoritative signal while it is already high enough for three-phase
        charging. The raw-overhead D-Bus subscription can briefly be stale
        after service startup, and must never override a valid multi-kW
        assignment with a false phase-down decision.

        For a genuine three-phase minimum gate, the assigned allowance becomes
        0 W while raw overhead can still be enough for one-phase charging. In
        that case, switch down only when raw overhead is both available and
        sufficient for the one-phase 6 A minimum.
        """
        if self.currentPhaseMode != 2:
            return False

        # Raw overhead is only a phase-down aid for a fresh, authoritative
        # allowance. It must never replace missing, invalid, or stale allowance.
        if not self.allowanceIsFresh():
            return False

        assignedAllowance = max(0.0, float(self.allowance))
        threePhaseThreshold = self.phaseDownThresholdW()

        # A valid 3φ-sized allocation always wins over a possibly stale raw
        # overhead subscription.
        if assignedAllowance >= threePhaseThreshold:
            self.clearPhaseSwitchCandidate()
            d(
                self,
                "Keeping 3-phase: assigned allowance {0:.0f}W is above "
                "the 3-phase threshold {1:.0f}W.".format(
                    assignedAllowance, threePhaseThreshold
                )
            )
            return False

        rawOverhead = self.rawPvOverheadW()
        if rawOverhead is None:
            self.clearPhaseSwitchCandidate()
            d(
                self,
                "Raw PV overhead is unavailable; not phase-down switching "
                "from a low allowance alone."
            )
            return False

        onePhaseMinimum = self.minimumChargePower()
        if rawOverhead < onePhaseMinimum:
            self.clearPhaseSwitchCandidate()
            d(
                self,
                "Raw PV overhead {0:.0f}W is below the one-phase minimum "
                "{1:.0f}W; not phase-down switching.".format(
                    rawOverhead, onePhaseMinimum
                )
            )
            return False

        if rawOverhead >= threePhaseThreshold:
            self.clearPhaseSwitchCandidate()
            return False
        return True

    def controlThreePhasePvDeficit(self):
        """Control an already-running three-phase charge through a PV dip.

        The same MinPhaseSwitchSeconds stability timer used for phase-up is
        used for phase-down. Battery assist may bridge the waiting interval
        only within its existing SOC, shortfall, grid-import, duration, and
        recovery limits. If grid fallback is allowed, the running charge may
        wait on grid power. Neither source can start a new charge or phase-up.
        """
        if self.currentPhaseMode != 2 or not self.allowanceIsFresh():
            return None

        assignedAllowance = max(0.0, float(self.allowance))
        threePhaseThreshold = self.phaseDownThresholdW()
        if assignedAllowance >= threePhaseThreshold:
            self.clearPhaseSwitchCandidate()
            return None

        # Assigned allowance is authoritative for deciding whether the
        # Wattpilot owns enough PV to remain on three phases. Raw overhead may
        # be slightly out of sync or include power not assigned to this
        # consumer, so it can support only the safer one-phase fallback.
        rawOverhead = self.rawPvOverheadW()
        onePhasePvW = (
            assignedAllowance
            if rawOverhead is None
            else max(assignedAllowance, rawOverhead)
        )

        shortfallW = max(
            0.0, self.currentChargeDemandPower() - onePhasePvW
        )
        self.updateBatteryAssistLockoutRecovery(shortfallW)
        batteryBridgeActive = self.startOrContinueBatteryAssist(shortfallW)
        fallbackAvailable = batteryBridgeActive or self.allowGridCharging

        if not fallbackAvailable:
            self.clearBatteryAssist()
            self.clearPhaseSwitchCandidate()
            if onePhasePvW >= self.minimumChargePower():
                return self.switchToOnePhaseForPvDip()

            self.publishServiceMessage(
                self,
                "Three-phase PV deficit cannot be bridged safely and PV is "
                "below the one-phase minimum. Stopping Auto/Eco charging."
            )
            self.forceStopForNoAllowance()
            return VrmEvChargerStatus.StopCharging

        phaseDownDecision = PhaseDecisions.evaluate_phase_switch_timing(
            self.phaseSwitchCandidateMode,
            self.phaseSwitchCandidateSince,
            1,
            self.minimumPhaseSwitchSeconds,
            self.getPhaseSwitchCooldownSeconds(),
            time.time(),
        )

        if (
            phaseDownDecision.next_candidate_mode != self.phaseSwitchCandidateMode
            or phaseDownDecision.next_candidate_since != self.phaseSwitchCandidateSince
        ):
            self.phaseSwitchCandidateMode = phaseDownDecision.next_candidate_mode
            self.phaseSwitchCandidateSince = phaseDownDecision.next_candidate_since
            self.publishServiceMessage(
                self,
                "PV no longer supports three-phase charging. Waiting {0}s "
                "before switching to one phase while the running charge is "
                "safely bridged.".format(self.minimumPhaseSwitchSeconds),
            )

        if (
            phaseDownDecision.action == PhaseDecisions.PHASE_SWITCH_READY
            and onePhasePvW >= self.minimumChargePower()
        ):
            return self.switchToOnePhaseForPvDip()

        return VrmEvChargerStatus.Charging

    def switchToOnePhaseForPvDip(self):
        if not self.allowanceIsFresh():
            if self.allowanceStopGraceActive():
                return VrmEvChargerStatus.Charging
            self.forceStopForNoAllowance()
            return VrmEvChargerStatus.StopCharging

        rawOverhead = self.rawPvOverheadW()
        assignedAllowance = max(0.0, float(self.allowance))
        # Prefer the consumer's assigned allowance whenever it can support a
        # one-phase charge. Raw overhead is only the fallback for the known
        # distributor case where a three-phase request is gated to 0 W even
        # though total PV can still sustain the one-phase minimum.
        usablePv = assignedAllowance
        if (
            assignedAllowance < self.minimumChargePower()
            and rawOverhead is not None
        ):
            usablePv = rawOverhead
        targetAmps = self.targetCurrentForPhase(1, usablePv)

        self.publishServiceMessage(
            self,
            "PV allowance dropped below the three-phase threshold. "
            "Switching to 1-phase before applying battery-assist or stop logic."
        )
        self.clearPhaseSwitchCandidate()
        self.lastPhaseSwitchTime = time.time()
        self.beginPhaseSwitchConfirmation(1)
        self.beginPowerTransitionGrace(
            1, targetAmps, "3-to-1 phase switch"
        )
        self.wattpilot.set_phases(1)
        self.currentPhaseMode = 1
        self.wattpilot.set_power(targetAmps)
        return VrmEvChargerStatus.SwitchingTo1Phase

    def gridImportPower(self):
        # GridImportPositive=true: positive values are import.
        # GridImportPositive=false: negative values are import.
        sign = 1 if self.gridImportPositive else -1
        phases = [
            self.dbusValue(self.gridL1Dbus, 0),
            self.dbusValue(self.gridL2Dbus, 0),
            self.dbusValue(self.gridL3Dbus, 0),
        ]
        return sum(max(0, sign * phase) for phase in phases)

    def publishSafetyTelemetry(self):
        allowance = self.allowance if self.allowanceIsFresh() else 0
        gridImport = self.gridImportPower() if self.gridTelemetryIsFresh() else 0
        self.dbusService["/PvAllowance"] = int(round(max(0, allowance)))
        self.dbusService["/GridImport"] = int(round(gridImport))
        self.dbusService["/BatteryAssist/Active"] = int(self.batteryAssistActive)
        self.dbusService["/BatteryAssist/Elapsed"] = int(
            round(self.getBatteryAssistSeconds())
        )
        self.dbusService["/BatteryAssist/Shortfall"] = int(
            round(self.batteryAssistShortfallW)
        )
        self.dbusService["/BatteryAssist/LockedOut"] = int(
            self.batteryAssistLockedOut
        )
        self.dbusService["/BatteryAssist/RecoveryElapsed"] = int(
            round(self.getBatteryAssistRecoverySeconds())
        )
        self.dbusService["/ChargeComplete/Hold"] = int(self.chargeCompleteHold)
        self.dbusService["/ChargeComplete/Elapsed"] = int(
            round(self.getChargeCompleteSeconds())
        )
        self.dbusService["/ChargeComplete/ResumeElapsed"] = int(
            round(self.getChargeCompleteResumeSeconds())
        )

    def gridImportLimitExceeded(self):
        gridImport = self.gridImportPower()
        decision = SafetyDecisions.evaluate_grid_import_guard(
            self.allowGridCharging,
            gridImport,
            self.gridImportSince,
            self.gridImportStopW,
            self.gridImportStopSeconds,
            time.time(),
        )
        self.gridImportSince = decision.next_import_since

        if decision.reason == SafetyDecisions.GRID_IMPORT_STARTED:
            d(
                self,
                "Grid import guard started at {0:.0f}W.".format(gridImport)
            )

        return decision.limit_exceeded

    def shouldIgnoreBatteryReservation(self):
        soc = self.batterySoc()
        return (
            self.evPriorityOverBatteryCharge
            and self.mode == VrmEvChargerControlMode.Auto
            and bool(
                getattr(self, "effectiveCarConnected", self.wattpilot.carConnected)
            )
            and soc is not None
            and soc >= self.evPriorityMinSoc
        )

    def getBatteryAssistSeconds(self):
        if self.batteryAssistSince == 0:
            return 0
        return time.time() - self.batteryAssistSince

    def getBatteryAssistRecoverySeconds(self):
        if self.batteryAssistRecoverySince == 0:
            return 0
        return time.time() - self.batteryAssistRecoverySince

    def clearBatteryAssist(self):
        # Intentionally do not clear the timeout lockout here. The active
        # timer must be cleared when a bridge ends, while the lockout has to
        # survive subsequent control cycles during the same low-PV event.
        self.batteryAssistSince = 0
        self.batteryAssistActive = False
        self.batteryAssistShortfallW = 0

    def lockBatteryAssist(self):
        self.clearBatteryAssist()
        self.batteryAssistLockedOut = True
        self.batteryAssistLockoutSince = time.time()
        self.batteryAssistRecoverySince = 0

    def clearBatteryAssistLockout(self, reason):
        wasLockedOut = self.batteryAssistLockedOut
        self.batteryAssistLockedOut = False
        self.batteryAssistLockoutSince = 0
        self.batteryAssistRecoverySince = 0

        if wasLockedOut:
            self.publishServiceMessage(
                self,
                "Battery assist lockout cleared: {0}.".format(reason)
            )

    def updateBatteryAssistLockoutRecovery(self, shortfallW):
        # A lockout means the bridge has used its full allowed time during the
        # current low-PV event. Do not open another window until PV has fully
        # covered the live EV demand for the configured recovery duration.
        decision = SafetyDecisions.evaluate_battery_assist_recovery(
            self.batteryAssistLockedOut,
            shortfallW,
            self.batteryAssistRecoverySince,
            self.batteryAssistRecoverySeconds,
            time.time(),
        )

        if decision.reason == SafetyDecisions.BATTERY_RECOVERY_NOT_LOCKED:
            return

        if decision.recovery_interrupted:
            d(
                self,
                "PV recovery interrupted before battery-assist lockout "
                "could clear."
            )
            self.batteryAssistRecoverySince = decision.next_recovery_since
            return

        if decision.recovery_started:
            self.batteryAssistRecoverySince = decision.next_recovery_since
            self.publishServiceMessage(
                self,
                "PV fully covers EV demand. Waiting {0}s before allowing "
                "battery assist again.".format(
                    self.batteryAssistRecoverySeconds
                )
            )

        if decision.clear_lockout:
            self.clearBatteryAssistLockout(
                "PV covered EV demand continuously for {0}s".format(
                    self.batteryAssistRecoverySeconds
                )
            )

    def startOrContinueBatteryAssist(self, shortfallW):
        soc = None
        gridImport = 0
        if shortfallW > 0 and not self.batteryAssistLockedOut:
            soc = self.batterySoc()
            gridImport = self.gridImportPower()

        decision = SafetyDecisions.evaluate_battery_assist(
            self.batteryAssistEnabled,
            shortfallW,
            self.batteryAssistLockedOut,
            self.wattpilot.power,
            soc,
            self.batteryAssistSocMin,
            self.batteryAssistMaxShortfallW,
            gridImport,
            self.gridImportStopW,
            self.batteryAssistSince,
            self.batteryAssistMaxSeconds,
            time.time(),
        )

        if (
            decision.reason in [
                SafetyDecisions.BATTERY_ASSIST_NO_SHORTFALL,
                SafetyDecisions.BATTERY_ASSIST_LOCKED_OUT,
                SafetyDecisions.BATTERY_ASSIST_INELIGIBLE,
            ]
        ):
            self.clearBatteryAssist()
            return False

        self.batteryAssistSince = decision.next_assist_since
        if decision.assist_started:
            self.publishServiceMessage(
                self,
                "PV dip detected. Starting battery assist at {0:.0f}% SOC.".format(soc)
            )

        self.batteryAssistActive = True
        self.batteryAssistShortfallW = shortfallW

        if decision.time_limit_reached:
            self.publishServiceMessage(
                self,
                "Battery assist time limit reached. Locking out further "
                "battery assist until PV recovery or car disconnect."
            )
            self.lockBatteryAssist()
            return False

        return True

    def getChargeCompleteSeconds(self):
        if self.chargeCompleteSince == 0:
            return 0
        return time.time() - self.chargeCompleteSince

    def getChargeCompleteResumeSeconds(self):
        if self.chargeCompleteResumeSince == 0:
            return 0
        return time.time() - self.chargeCompleteResumeSince

    def enterChargeCompleteHold(self):
        if self.chargeCompleteHold:
            return

        self.chargeCompleteHold = True
        self.chargeCompleteSince = time.time()
        self.chargeCompleteResumeSince = 0
        self.surplusSince = 0
        self.publishServiceMessage(
            self,
            "EV appears fully charged: power stayed at or below {0:.0f}W "
            "for {1}s. Holding the connected session without a stop command.".format(
                self.chargeCompletePowerThresholdW,
                self.chargeCompleteConfirmSeconds
            )
        )

    def clearChargeCompleteHold(self, reason):
        if not self.chargeCompleteHold:
            self.chargeCompleteSince = 0
            self.chargeCompleteResumeSince = 0
            return

        self.chargeCompleteHold = False
        self.chargeCompleteSince = 0
        self.chargeCompleteResumeSince = 0
        self.publishServiceMessage(
            self,
            "Charge-complete hold cleared: {0}.".format(reason)
        )

    def updateChargeCompleteHoldResume(self, measuredPowerW):
        """Return True after a completed EV session has genuinely resumed.

        Tiny balancing / keep-alive draws must not leave the hold. A sustained
        significant draw is treated as a new charging phase without requiring
        an unplug/replug.
        """
        if not self.chargeCompleteHold:
            return False

        if measuredPowerW < self.chargeCompleteResumePowerW:
            if self.chargeCompleteResumeSince != 0:
                d(
                    self,
                    "Charge-complete resume was interrupted before confirmation."
                )
            self.chargeCompleteResumeSince = 0
            return False

        if self.chargeCompleteResumeSince == 0:
            self.chargeCompleteResumeSince = time.time()
            self.publishServiceMessage(
                self,
                "EV power rose to {0:.0f}W. Waiting {1}s before leaving "
                "charge-complete hold.".format(
                    measuredPowerW,
                    self.chargeCompleteResumeSeconds
                )
            )
            return False

        if (
            self.getChargeCompleteResumeSeconds()
            >= self.chargeCompleteResumeSeconds
        ):
            self.clearChargeCompleteHold(
                "EV resumed at least {0:.0f}W for {1}s".format(
                    self.chargeCompleteResumePowerW,
                    self.chargeCompleteResumeSeconds
                )
            )
            return True

        return False

    def autoControlActive(self):
        """Return whether the Wattpilot is in the Auto/Eco control path."""
        try:
            wattpilotMode = getattr(self.wattpilot, "mode", None)
            if wattpilotMode is not None:
                return wattpilotMode == WattpilotControlMode.ECO
        except Exception:
            pass
        return (
            getattr(self, "mode", VrmEvChargerControlMode.Manual)
            == VrmEvChargerControlMode.Auto
        )

    def failSafeStopForAutoControlFault(self):
        """Best-effort stop after an unexpected Auto/Eco control exception."""
        try:
            self.publishServiceMessage(
                self,
                "Auto/Eco controller fault. EV charging was stopped for safety."
            )
        except Exception:
            pass

        try:
            self.clearBatteryAssist()
            self.clearPowerTransitionGrace()
            self.clearPendingPhaseSwitch()
        except Exception:
            pass

        # A stop command alone may leave the previous current command visible
        # to a reconnecting Wattpilot. Zero the command first, then force Off.
        try:
            self.wattpilot.set_power(0)
        except Exception:
            pass
        try:
            self.wattpilot.set_start_stop(WattpilotStartStop.Off)
        except Exception:
            pass

        self.noAllowanceForcedOff = True
        try:
            self.currentPhaseMode = 0
            self.reportVRMStatus(VrmEvChargerStatus.StopCharging)
            self.dbusService["/StartStop"] = VrmEvChargerStartStop.Stop.value
            self.dbusService["/StartStopLiteral"] = VrmEvChargerStartStop.Stop.name
        except Exception:
            pass

    def forceStopForNoAllowance(self):
        # Strict policy after the allowance debounce expires: stop and retain
        # ForceStateOff. Do not issue Neutral, because native Wattpilot ECO
        # could then restart independently.
        self.surplusSince = 0
        self.surplusBelowMinimumSince = 0
        self.allowanceBelowMinimumSince = 0
        self.clearBatteryAssist()
        self.clearPowerTransitionGrace()
        self.clearPendingPhaseSwitch()

        firstForcedOff = not self.noAllowanceForcedOff
        chargerStillActive = (
            self.wattpilot.power is not None and self.wattpilot.power > 0
        )
        needsOffCommand = (
            firstForcedOff
            or self.wattpilot.startState != WattpilotStartStop.Off
            or chargerStillActive
        )

        if needsOffCommand:
            i(self, "STOP send!")
            self.wattpilot.set_start_stop(WattpilotStartStop.Off)

            if firstForcedOff:
                self.lastOnOffTime = time.time()

            self.noAllowanceForcedOff = True
            self.dbusService["/StartStop"] = VrmEvChargerStartStop.Stop.value
            self.dbusService["/StartStopLiteral"] = VrmEvChargerStartStop.Stop.name

            if firstForcedOff:
                self.currentPhaseMode = 0
                self.wattpilot.set_phases(0)


    def getOnOffCooldownSeconds(self):
        return max(0, self.lastOnOffTime + self.minimumOnOffSeconds - time.time())

    def getPhaseSwitchCooldownSeconds(self):
        return max(
            0,
            self.lastPhaseSwitchTime
            + self.minimumPhaseSwitchSeconds
            - time.time()
        )

    def clearPhaseSwitchCandidate(self):
        self.phaseSwitchCandidateMode = 0
        self.phaseSwitchCandidateSince = 0
        self.phaseSwitchBelowThresholdSince = 0

    def preservePhaseUpCandidateThroughShortDip(self):
        """Evaluate normal-path grace for an electrically safe PV dip."""
        decision = PhaseDecisions.evaluate_phase_up_drop_grace(
            self.phaseSwitchCandidateMode,
            max(0.0, float(self.allowance)),
            self.phaseUpThresholdW(),
            self.phaseDownThresholdW(),
            getattr(self, "phaseSwitchBelowThresholdSince", 0),
            self.surplusDropGraceSeconds,
            time.time(),
        )
        self.phaseSwitchBelowThresholdSince = (
            decision.next_below_threshold_since
        )

        if decision.reason == PhaseDecisions.PHASE_UP_DROP_GRACE_STARTED:
            self.publishServiceMessage(
                self,
                "Phase-up allowance dipped below {0:.0f}W but remains above "
                "the effective three-phase floor. Preserving the candidate for up to "
                "{1}s.".format(
                    self.phaseUpThresholdW(), self.surplusDropGraceSeconds
                ),
            )
        elif decision.reason == PhaseDecisions.PHASE_UP_DROP_GRACE_EXPIRED:
            self.publishServiceMessage(
                self,
                "Phase-up allowance stayed below {0:.0f}W for {1:.0f}s. "
                "Resetting the phase-up timer.".format(
                    self.phaseUpThresholdW(), decision.drop_seconds
                ),
            )
        elif decision.reason == PhaseDecisions.PHASE_UP_DROP_BELOW_MINIMUM:
            self.publishServiceMessage(
                self,
                "Phase-up allowance fell below the effective three-phase "
                "floor. Resetting the phase-up timer.",
            )

        return decision.preserve_candidate

    def adjustChargeForPvAllowance(self):
        desiredPhaseMode = self.desiredPhaseModeForPvAllowance()
        enteringPhaseMode = self.currentPhaseMode

        if enteringPhaseMode == 0:
            enteringPhaseMode = 1

        # On the normal current-adjustment path, a one-phase phase-up candidate
        # may survive a short allocation dip only while assigned PV remains
        # above the effective three-phase-capable floor. An eligible battery-
        # assist continuation returns before this evaluation and intentionally
        # leaves an existing candidate unchanged. Either path still requires
        # the full phase-up threshold again at the command boundary.
        phaseUpDropGraceActive = False
        if desiredPhaseMode == 2:
            self.phaseSwitchBelowThresholdSince = 0
        elif enteringPhaseMode != 2:
            phaseUpDropGraceActive = (
                self.preservePhaseUpCandidateThroughShortDip()
            )
            if phaseUpDropGraceActive:
                desiredPhaseMode = 2

        # Phase-down decisions are owned by controlAutomaticCharging() before
        # current adjustment. Never change the remembered phase mode here
        # without issuing and confirming a matching phase command.
        if desiredPhaseMode == 1 and enteringPhaseMode == 2:
            d(
                self,
                "Holding three-phase state until the phase-deficit controller "
                "issues a confirmed phase command.",
            )
            return VrmEvChargerStatus.Charging

        # Phase-up is allowed only by real PV surplus and respects the phase
        # switch cooldown. While waiting, one-phase charging is capped at 16 A.
        if desiredPhaseMode == 2 and enteringPhaseMode != 2:
            phaseUpDecision = PhaseDecisions.evaluate_phase_switch_timing(
                self.phaseSwitchCandidateMode,
                self.phaseSwitchCandidateSince,
                2,
                self.minimumPhaseSwitchSeconds,
                self.getPhaseSwitchCooldownSeconds(),
                time.time(),
            )

            if (
                phaseUpDecision.next_candidate_mode != self.phaseSwitchCandidateMode
                or phaseUpDecision.next_candidate_since != self.phaseSwitchCandidateSince
            ):
                self.phaseSwitchCandidateMode = phaseUpDecision.next_candidate_mode
                self.phaseSwitchCandidateSince = phaseUpDecision.next_candidate_since
                self.publishServiceMessage(
                    self,
                    "PV threshold supports {0}-phase. Waiting {1}s before phase switching.".format(
                        3,
                        self.minimumPhaseSwitchSeconds,
                    ),
                )

            if phaseUpDecision.action == PhaseDecisions.PHASE_SWITCH_WAIT_STABLE:
                targetAmps = self.targetCurrentForPhase(1, self.allowance)
                self.currentPhaseMode = 1
                self.wattpilot.set_power(targetAmps)
                if phaseUpDropGraceActive:
                    d(
                        self,
                        "Preserving phase-up candidate through a short PV dip "
                        "({0:.0f}/{1}s stable).".format(
                            phaseUpDecision.stable_seconds,
                            self.minimumPhaseSwitchSeconds,
                        ),
                    )
                else:
                    d(
                        self,
                        "3-phase PV threshold reached; waiting for stable phase-up allowance ({0:.0f}/{1}s).".format(
                            phaseUpDecision.stable_seconds,
                            self.minimumPhaseSwitchSeconds,
                        ),
                    )
                return VrmEvChargerStatus.Charging

            if (
                phaseUpDecision.action == PhaseDecisions.PHASE_SWITCH_READY
                and self.allowance >= self.phaseUpThresholdW()
            ):
                targetAmps = self.targetCurrentForPhase(2, self.allowance)
                i(self, "PV surplus supports 3-phase charging. Switching to 3-phase.")
                self.publishServiceMessage(
                    self, "Switching to 3-phase from PV surplus."
                )
                self.lastPhaseSwitchTime = time.time()
                self.beginPhaseSwitchConfirmation(2)
                self.beginPowerTransitionGrace(2, targetAmps, "1-to-3 phase switch")
                self.wattpilot.set_phases(2)
                self.currentPhaseMode = 2
                self.clearPhaseSwitchCandidate()
                self.wattpilot.set_power(targetAmps)
                return VrmEvChargerStatus.SwitchingTo3Phase

            if phaseUpDecision.action == PhaseDecisions.PHASE_SWITCH_READY:
                targetAmps = self.targetCurrentForPhase(1, self.allowance)
                self.currentPhaseMode = 1
                self.wattpilot.set_power(targetAmps)
                d(
                    self,
                    "Phase-up timer is mature; waiting for assigned allowance "
                    "to recover to {0:.0f}W before switching.".format(
                        self.phaseUpThresholdW()
                    ),
                )
                return VrmEvChargerStatus.Charging

            targetAmps = self.targetCurrentForPhase(1, self.allowance)
            self.currentPhaseMode = 1
            self.wattpilot.set_power(targetAmps)
            d(
                self,
                "3-phase PV threshold reached; phase-up cooldown active for {0:.0f}s.".format(
                    phaseUpDecision.cooldown_seconds
                )
            )
            return VrmEvChargerStatus.Charging

        # No phase change; adjust current from PV allowance only.
        self.clearPhaseSwitchCandidate()
        self.currentPhaseMode = desiredPhaseMode
        targetAmps = self.targetCurrentForPhase(desiredPhaseMode, self.allowance)
        i(
            self,
            "Adjusting charge current to {0}A on {1}-phase.".format(
                targetAmps, 3 if desiredPhaseMode == 2 else 1
            )
        )
        self.wattpilot.set_power(targetAmps)
        return VrmEvChargerStatus.Charging

    def dumpEvChargerInfo(self):
        self.publish(
            "/Ac/L1/Power",
            self.wattpilot.power1 * 1000
            if self.wattpilot.power1 is not None
            else 0
        )
        self.publish(
            "/Ac/L2/Power",
            self.wattpilot.power2 * 1000
            if self.wattpilot.power2 is not None
            else 0
        )
        self.publish(
            "/Ac/L3/Power",
            self.wattpilot.power3 * 1000
            if self.wattpilot.power3 is not None
            else 0
        )
        self.publish(
            "/Ac/L1/Voltage",
            self.wattpilot.voltage1 if self.wattpilot.voltage1 is not None else 0
        )
        self.publish(
            "/Ac/L2/Voltage",
            self.wattpilot.voltage2 if self.wattpilot.voltage2 is not None else 0
        )
        self.publish(
            "/Ac/L3/Voltage",
            self.wattpilot.voltage3 if self.wattpilot.voltage3 is not None else 0
        )
        self.publish(
            "/Ac/L1/Current",
            self.wattpilot.amps1
            if self.wattpilot.amps1 is not None and self.wattpilot.power > 0
            else 0
        )
        self.publish(
            "/Ac/L2/Current",
            self.wattpilot.amps2
            if self.wattpilot.amps2 is not None and self.wattpilot.power > 0
            else 0
        )
        self.publish(
            "/Ac/L3/Current",
            self.wattpilot.amps3
            if self.wattpilot.amps3 is not None and self.wattpilot.power > 0
            else 0
        )
        self.publish(
            "/Ac/L1/PowerFactor",
            self.wattpilot.powerFactor1
            if self.wattpilot.powerFactor1 is not None and self.wattpilot.power > 0
            else 0
        )
        self.publish(
            "/Ac/L2/PowerFactor",
            self.wattpilot.powerFactor2
            if self.wattpilot.powerFactor2 is not None and self.wattpilot.power > 0
            else 0
        )
        self.publish(
            "/Ac/L3/PowerFactor",
            self.wattpilot.powerFactor3
            if self.wattpilot.powerFactor3 is not None and self.wattpilot.power > 0
            else 0
        )
        self.publish(
            "/Ac/Power",
            self.wattpilot.power * 1000
            if self.wattpilot.power is not None
            else 0
        )

        maxPower = 3 * self.getEffectiveMaxCurrent() * self.onePhaseVoltage()
        self.publish(
            "/Ac/PowerPercent",
            (self.wattpilot.power * 1000) / maxPower * 100.0
            if self.wattpilot.power is not None and maxPower > 0
            else 0
        )
        self.publish("/Ac/PowerMax", maxPower)

        totalCurrent = (
            (self.wattpilot.amps1 or 0)
            + (self.wattpilot.amps2 or 0)
            + (self.wattpilot.amps3 or 0)
        )
        self.publish(
            "/Current",
            totalCurrent
            if self.wattpilot.power is not None and self.wattpilot.power > 0
            else 0
        )
        self.reportModeTelemetry()

        self.publishMainMqtt(
            "es-ESS/SolarOverheadDistributor/Requests/Wattpilot/Consumption",
            self.consumerPowerForDistributor()
        )

        sessionEnergy = 0.0
        if (
            self.wattpilot.energyCounterSinceStart is not None
            and self.wattpilot.carConnected
        ):
            sessionEnergy = self.wattpilot.energyCounterSinceStart / 1000
        elif (
            self.wattpilot.energyCounterSinceStart is not None
            and not self.wattpilot.carConnected
            and self.config["FroniusWattpilot"]["ResetChargedEnergyCounter"].lower()
            == "onconnect"
        ):
            sessionEnergy = self.wattpilot.energyCounterSinceStart / 1000
        else:
            self.chargingTime = 0

        self.publish("/Ac/Energy/Forward", sessionEnergy)
        self.publish("/Session/Energy", sessionEnergy)
        self.publish("/AutoStart", self.autostart)
        self.publish("/ChargingTime", self.chargingTime)
        self.publish("/Session/Time", self.chargingTime)
        self.publish("/CarState", self.wattpilot.carConnected)
        self.reportPhaseMode()

        amp = self.wattpilot.amp or 0
        if self.currentPhaseMode == 2:
            self.publish("/SetCurrent", amp * 3)
            self.publish("/MaxCurrent", self.getEffectiveMaxCurrent() * 3)
        else:
            self.publish("/SetCurrent", amp)
            self.publish("/MaxCurrent", self.getEffectiveMaxCurrent())

    def modeTelemetryDiagnosticKey(self):
        """Return the raw-to-controller mode transition awaiting publication."""
        rawMode = getattr(self.wattpilot, "mode", None)
        if rawMode is None:
            return None

        mappedMode = (
            VrmEvChargerControlMode.Auto
            if rawMode == WattpilotControlMode.ECO
            else VrmEvChargerControlMode.Manual
        )
        return (
            rawMode,
            getattr(self.wattpilot, "modeChangedAt", None),
            mappedMode,
        )

    def modeTelemetryNeedsControllerCycle(self):
        """Keep a raw mode transition from being hidden by idle throttling."""
        diagnosticKey = self.modeTelemetryDiagnosticKey()
        return (
            diagnosticKey is not None
            and diagnosticKey
            != getattr(self, "_lastPublishedModeDiagnostic", None)
        )

    def reportModeTelemetry(self):
        """Publish controller mode and correlate it with raw ``lmo`` receipt."""
        self.publish("/Mode", self.mode.value)
        self.publish("/ModeLiteral", self.mode.name)

        diagnosticKey = self.modeTelemetryDiagnosticKey()
        if diagnosticKey is None:
            return

        rawMode, changedAt, mappedMode = diagnosticKey
        if mappedMode != self.mode:
            return

        updatedAt = getattr(self.wattpilot, "modeUpdatedAt", None)
        if diagnosticKey == getattr(self, "_lastPublishedModeDiagnostic", None):
            return

        self._lastPublishedModeDiagnostic = diagnosticKey
        i(
            self,
            "Published Wattpilot mode telemetry: raw lmo={0} ({1}), "
            "lmo_changed_at_epoch={2}, lmo_received_at_epoch={3}, "
            "/ModeLiteral={4}, published_at_epoch={5:.3f}.".format(
                getattr(rawMode, "value", "unavailable"),
                getattr(rawMode, "name", "unavailable"),
                "{0:.3f}".format(changedAt) if changedAt is not None else "unavailable",
                "{0:.3f}".format(updatedAt) if updatedAt is not None else "unavailable",
                self.mode.name,
                time.time(),
            ),
        )

    def publish(self, path, value):
        self.dbusService[path] = value
        self.publishMainMqtt("es-ESS/FroniusWattpilot{0}".format(path), value, 0)

    def publishRetained(self, path, value):
        self.dbusService[path] = value
        self.publishMainMqtt("es-ESS/FroniusWattpilot{0}".format(path), value, 0, True)

    def handleSigterm(self):
       self.publishServiceMessage(self, "SIGTERM received, sending STOP-command to wattpilot, if in auto mode.")
       
       if (self.wattpilot is not None and self.wattpilot.connected and self.mode == VrmEvChargerControlMode.Auto):
            self.wattpilot.set_start_stop(WattpilotStartStop.Off)
       
       self.wattpilot._auto_reconnect = False
       self.wattpilot.disconnect()
