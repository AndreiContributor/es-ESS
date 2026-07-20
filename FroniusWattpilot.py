
from builtins import int
from enum import Enum
from math import isfinite
import os
import platform
import sys
import time

import paho.mqtt.client as mqtt # type: ignore

# Victron D-Bus dependency
from VelibDependency import activate_velib_python
activate_velib_python()
from vedbus import VeDbusService # type: ignore

# esEss imports
import Globals
import Helper
from Helper import i, c, d, w, e, t,  dbusConnection
import WattpilotControlState as ControlStates
import WattpilotDecisionInputs as DecisionInputs
import WattpilotPhaseDecisions as PhaseDecisions
import WattpilotSafetyDecisions as SafetyDecisions
import WattpilotSiteCurrentDecisions as SiteCurrentDecisions
import RuntimeCompatibility
from Wattpilot import Wattpilot
from enums import WattpilotModelStatus, WattpilotStartStop, WattpilotControlMode, VrmEvChargerControlMode, VrmEvChargerStatus, VrmEvChargerStartStop
from esESSService import esESSService

WATTPILOT_BASE_CUSTOM_NAME = "Fronius Wattpilot"
WATTPILOT_UNAVAILABLE_STATUS_LITERAL = "Wattpilot not accessible"
WATTPILOT_UNAVAILABLE_CUSTOM_NAME = "Wattpilot not reachable"
COMMAND_AUTHORITY_UNAVAILABLE = (
    "Blocked: native Wattpilot command settings unavailable"
)
COMMAND_AUTHORITY_FIRMWARE = (
    "Blocked: Wattpilot firmware compatibility unavailable"
)
COMMAND_AUTHORITY_DISABLE_NATIVE_PV = (
    "Blocked: disable Use PV surplus in Solar.wattpilot"
)
COMMAND_AUTHORITY_DISABLE_TARIFF = (
    "Blocked: disable flexible tariff in Solar.wattpilot"
)
COMMAND_AUTHORITY_SELECT_AUTO = (
    "Ready: select Auto on GX/VRM after native controls are disabled"
)
COMMAND_AUTHORITY_VALIDATED = (
    "Validated: es-ESS is the sole Auto/Eco command owner"
)

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
        self.commandAuthorityOk = False
        self.commandAuthorityLiteral = COMMAND_AUTHORITY_UNAVAILABLE
        self._lastCommandAuthorityState = None
        self.commandAuthorityForcedOff = False
        self._lastObservedModelStatusValue = None
        self._protocolChargingStatusSince = 0
        self.minimumOnOffSeconds = int(settings["MinOnOffSeconds"])
        self.minimumPhaseSwitchSeconds = int(settings["MinPhaseSwitchSeconds"])

        # Explicit EV limits. Wattpilot's AMA value can be higher than the
        # vehicle or installation limit, therefore it is only an upper bound.
        self.minCurrentPerPhase = max(6, int(settings.get("MinCurrentPerPhase", 6)))
        self.maxCurrentPerPhase = max(
            self.minCurrentPerPhase, int(settings.get("MaxCurrentPerPhase", 16))
        )
        self.siteMaxCurrent = int(settings.get("SiteMaxCurrent", 20))
        self.charger1PhaseMapping = settings.get(
            "Charger1PhaseMapping", "L1"
        ).upper()
        self.siteCurrentFreshSeconds = max(
            1, int(settings.get("SiteCurrentFreshSeconds", 15))
        )
        self.siteCurrentRecoverySeconds = max(
            0, int(settings.get("SiteCurrentRecoverySeconds", 30))
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
        self.batteryAssistMaxShortfallPerPhaseW = float(
            settings.get("BatteryAssistMaxShortfallPerPhaseW", 1500)
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

        # Fresh raw distributor overhead may reduce or maintain an already-
        # running charge when the atomic assigned allowance is gated to 0 W.
        # It can never start charging, increase current, or cause phase-up.
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
        self.siteCurrentForcedOff = False

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
        self.batteryAssistDeficitSince = 0
        self.batteryAssistActive = False
        self.batteryAssistShortfallW = 0
        self.batteryAssistShortfallPerPhaseW = 0
        self.batteryAssistActivePhases = 0
        self.batteryAssistEffectiveLimitW = 0
        self.minimumCurrentReductionAt = 0
        self.minimumCurrentReductionPhaseMode = 0
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

        # Mandatory whole-site per-phase guard for Auto/Eco commands. The
        # recovery timer applies only to increases; reductions and stops are
        # immediate on the next controller cycle.
        self.siteCurrentRecoverySince = {1: 0, 2: 0}
        self.siteCurrentGuardBlocked = False
        self.siteCurrentGuardReason = "Waiting for site-current telemetry"
        self.siteCurrentAllowedCurrent = 0
        self.siteCurrentLimitingPhase = "Unknown"
        self.siteCurrentHeadrooms = (0.0, 0.0, 0.0)
        self.sitePhaseTransitionReductionAt = 0
        self.sitePhaseTransitionTargetMode = 0
        self.sitePhaseTransitionTargetAmps = 0

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
        self.siteCurrentL1Dbus = None
        self.siteCurrentL2Dbus = None
        self.siteCurrentL3Dbus = None
        for phase in ("L1", "L2", "L3"):
            setattr(self, "siteCurrent{0}Value".format(phase), None)
            setattr(self, "siteCurrent{0}Valid".format(phase), False)
            setattr(self, "siteCurrent{0}UpdatedAt".format(phase), 0)
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
        self.dbusService.add_path('/BatteryAssist/ShortfallPerPhase', 0)
        self.dbusService.add_path('/BatteryAssist/ActivePhases', 0)
        self.dbusService.add_path('/BatteryAssist/EffectiveLimit', 0)
        self.dbusService.add_path('/BatteryAssist/LockedOut', 0)
        self.dbusService.add_path('/BatteryAssist/RecoveryElapsed', 0)
        self.dbusService.add_path('/ChargeComplete/Hold', 0)
        self.dbusService.add_path('/ChargeComplete/Elapsed', 0)
        self.dbusService.add_path('/ChargeComplete/ResumeElapsed', 0)
        self.dbusService.add_path('/GridImport', 0)
        self.dbusService.add_path('/SiteCurrentLimit', self.siteMaxCurrent)
        self.dbusService.add_path('/Charger1PhaseMapping', self.charger1PhaseMapping)
        for phase in ("L1", "L2", "L3"):
            self.dbusService.add_path('/SiteCurrent{0}'.format(phase), 0)
            self.dbusService.add_path('/SiteCurrentAge{0}'.format(phase), -1)
            self.dbusService.add_path('/SiteHeadroom{0}'.format(phase), 0)
        self.dbusService.add_path('/SiteAllowedCurrent', 0)
        self.dbusService.add_path('/SiteLimitingPhase', 'Unknown')
        self.dbusService.add_path('/SiteCurrentTelemetryHealthy', 0)
        self.dbusService.add_path('/SiteCurrentGuardBlocked', 0)
        self.dbusService.add_path('/SiteCurrentGuardReason', self.siteCurrentGuardReason)
        self.dbusService.add_path('/SiteCurrentRecoveryElapsed', 0)

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
        self.siteCurrentL1Dbus = self.registerDbusSubscription(
            "com.victronenergy.system", "/Ac/Consumption/L1/Current",
            callback=self.onSiteCurrentL1Telemetry,
            initialValueDefault=None,
        )
        self.siteCurrentL2Dbus = self.registerDbusSubscription(
            "com.victronenergy.system", "/Ac/Consumption/L2/Current",
            callback=self.onSiteCurrentL2Telemetry,
            initialValueDefault=None,
        )
        self.siteCurrentL3Dbus = self.registerDbusSubscription(
            "com.victronenergy.system", "/Ac/Consumption/L3/Current",
            callback=self.onSiteCurrentL3Telemetry,
            initialValueDefault=None,
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

    def onSiteCurrentL1Telemetry(self, subscription):
        self.recordSiteCurrentTelemetry("L1", subscription.value)

    def onSiteCurrentL2Telemetry(self, subscription):
        self.recordSiteCurrentTelemetry("L2", subscription.value)

    def onSiteCurrentL3Telemetry(self, subscription):
        self.recordSiteCurrentTelemetry("L3", subscription.value)

    def recordSiteCurrentTelemetry(self, phase, value):
        """Record one physical whole-site current sample and receive time."""
        numeric = DecisionInputs.finite_number(value)
        valid = numeric is not None and numeric >= 0
        setattr(self, "siteCurrent{0}Value".format(phase), numeric)
        setattr(self, "siteCurrent{0}Valid".format(phase), valid)
        setattr(self, "siteCurrent{0}UpdatedAt".format(phase), time.time())

    def refreshSiteCurrentTelemetryHeartbeat(self):
        """Refresh site-current liveness even when a D-Bus value is unchanged."""
        for phase in ("L1", "L2", "L3"):
            subscription = getattr(
                self, "siteCurrent{0}Dbus".format(phase), None
            )
            if subscription is None:
                continue

            try:
                success, value = self.readDbusSubscription(subscription)
            except Exception:
                success, value = False, None

            if success:
                subscription.value = value
                self.recordSiteCurrentTelemetry(phase, value)
            else:
                setattr(self, "siteCurrent{0}Valid".format(phase), False)

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
            if (
                self.wattpilot.mode == WattpilotControlMode.ECO
                and self.wattpilotAutoControlAuthorityOk()
            ):
                self.publishServiceMessage(
                    self,
                    "Currently not charging. Negotiating automatic phase mode."
                )
                self.wattpilot.set_phases(0)  # autoselect
            elif self.wattpilot.mode == WattpilotControlMode.ECO:
                self.publishServiceMessage(
                    self,
                    "Auto/Eco phase negotiation blocked until native Wattpilot "
                    "PV and tariff controls are disabled."
                )
            else:
                self.publishServiceMessage(
                    self,
                    "Manual/default startup leaves Wattpilot phase mode unchanged."
                )

        self.dumpEvChargerInfo()

    def _froniusHandleChangedValue(self, path, value):
        i(self, "User/cerbo/vrm updated " + str(path) + " to " + str(value))

        if path == "/SetCurrent":
            requestedCurrent = int(value)
            if requestedCurrent <= 0:
                if not self.wattpilotAutoControlSelected():
                    self.rejectDirectWattpilotCommand(path)
                    return False
                self.wattpilot.set_power(0)
                self.dumpEvChargerInfo()
                return True

            if not self.wattpilotAutoControlAuthorityOk():
                self.rejectDirectWattpilotCommand(path)
                return False

            maxCurrent = self.getEffectiveMaxCurrent()

            # Never round a device-reported cap below the configured minimum
            # back up to the minimum. Doing so would command more current than
            # the Wattpilot, vehicle, or installation allows.
            if requestedCurrent <= 0 or not self.canChargeAtMinimumCurrent():
                self.wattpilot.set_power(0)
            else:
                if requestedCurrent > maxCurrent:
                    requestedPhaseMode = 2
                    ampPerPhase = int(round(requestedCurrent / 3.0))
                else:
                    requestedPhaseMode = 1
                    ampPerPhase = requestedCurrent

                ampPerPhase = min(maxCurrent, ampPerPhase)
                ampPerPhase = self.siteLimitedTargetCurrent(
                    requestedPhaseMode, ampPerPhase
                )

                if ampPerPhase < self.minCurrentPerPhase:
                    self.wattpilot.set_power(0)
                else:
                    self.commandSiteSafePhaseTransition(
                        requestedPhaseMode, ampPerPhase
                    )

        elif path == "/StartStop":
            state = VrmEvChargerStartStop(value)
            if state == VrmEvChargerStartStop.Stop:
                if not self.wattpilotAutoControlSelected():
                    self.rejectDirectWattpilotCommand(path)
                    return False
            elif not self.wattpilotAutoControlAuthorityOk():
                self.rejectDirectWattpilotCommand(path)
                return False

            self.dbusService["/StartStopLiteral"] = state.name

            if state == VrmEvChargerStartStop.Start:
                self.wattpilot.set_start_stop(WattpilotStartStop.On)
            elif state == VrmEvChargerStartStop.Stop:
                self.wattpilot.set_start_stop(WattpilotStartStop.Off)

        elif path == "/Mode":
            priorMode = self.mode
            newMode = VrmEvChargerControlMode(value)
            if not self.switchMode(priorMode, newMode):
                self.dumpEvChargerInfo()
                return False

        self.dumpEvChargerInfo()
        return True

    def wattpilotAutoControlSelected(self):
        """Return True only when Wattpilot telemetry confirms ECO control."""
        try:
            wattpilotMode = getattr(self.wattpilot, "mode", None)
        except Exception:
            return False

        return wattpilotMode == WattpilotControlMode.ECO

    def nativeCommandSettingsStatus(self):
        """Return whether firmware 42.5 native command competitors are off."""
        wattpilot = getattr(self, "wattpilot", None)
        nativePv = getattr(wattpilot, "nativePvSurplusEnabled", None)
        flexibleTariff = getattr(wattpilot, "flexibleTariffEnabled", None)

        if type(nativePv) is not bool or type(flexibleTariff) is not bool:
            return False, COMMAND_AUTHORITY_UNAVAILABLE
        if nativePv:
            return False, COMMAND_AUTHORITY_DISABLE_NATIVE_PV
        if flexibleTariff:
            return False, COMMAND_AUTHORITY_DISABLE_TARIFF
        return True, COMMAND_AUTHORITY_SELECT_AUTO

    def commandAuthorityStatus(self):
        """Return the read-only single-owner Auto/Eco authority state."""
        if not bool(getattr(self, "wattpilotFirmwareCompatible", False)):
            return False, COMMAND_AUTHORITY_FIRMWARE
        settingsOk, literal = self.nativeCommandSettingsStatus()
        if not settingsOk:
            return False, literal
        if not self.wattpilotAutoControlSelected():
            return False, COMMAND_AUTHORITY_SELECT_AUTO
        return True, COMMAND_AUTHORITY_VALIDATED

    def refreshCommandAuthorityStatus(self):
        """Publish only authority transitions; control remains in the selector."""
        ok, literal = self.commandAuthorityStatus()
        self.commandAuthorityOk = ok
        self.commandAuthorityLiteral = literal
        state = (ok, literal)
        if state != self._lastCommandAuthorityState:
            self.publishServiceMessage(self, literal)
            if ok:
                i(self, literal)
                self.commandAuthorityForcedOff = False
            else:
                w(self, literal)
            self._lastCommandAuthorityState = state
        return ok

    def wattpilotAutoControlAuthorityOk(self):
        """Require ECO plus disabled native PV and tariff command ownership."""
        ok, _literal = self.commandAuthorityStatus()
        return ok

    def rejectDirectWattpilotCommand(self, path):
        _ok, authorityLiteral = self.commandAuthorityStatus()
        self.publishServiceMessage(
            self,
            "Ignored {0} command. {1}.".format(path, authorityLiteral)
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
        # Hibernate intentionally disconnects while no EV is present. Remote
        # mode changes are unsupported during that interval; Scheduled below is
        # only a best-effort status probe, not a keep-awake/control contract.
        d("FroniusWattpilot", "Switching Mode from {0} to {1}.".format(fromMode, toMode))
        
        self.publishServiceMessage(self, "Switching Mode from {0} to {1}.".format(fromMode, toMode))

        if (
            fromMode == VrmEvChargerControlMode.Manual
            and toMode == VrmEvChargerControlMode.Auto
        ):
            if not bool(getattr(self, "wattpilotFirmwareCompatible", False)):
                settingsOk, literal = False, COMMAND_AUTHORITY_FIRMWARE
            else:
                settingsOk, literal = self.nativeCommandSettingsStatus()
            if not settingsOk:
                self.publishServiceMessage(
                    self,
                    "Auto selection rejected. {0}.".format(literal)
                )
                self.mode = fromMode
                self.dbusService["/Mode"] = fromMode.value
                self.dbusService["/ModeLiteral"] = fromMode.name
                return False

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

            return True

        elif (toMode == VrmEvChargerControlMode.Scheduled):
            #Scheduled Charge - this is not used. We use this to temorary wakeup wattpilot, if in Hibernate mode. 
            self.wakeUpWattpilot()
            self.switchMode(VrmEvChargerControlMode.Scheduled, fromMode)
        return False
         
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
        siteCurrentTelemetryFresh=True,
        siteCurrentLimitExceeded=False,
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
            command_authority_ok=self.wattpilotAutoControlAuthorityOk(),
            site_current_telemetry_fresh=siteCurrentTelemetryFresh,
            site_current_limit_exceeded=siteCurrentLimitExceeded,
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

    def selectControlState(
        self,
        effectiveCarConnected,
        gridTelemetryFresh,
        siteCurrentTelemetryFresh=True,
        siteCurrentLimitExceeded=False,
    ):
        if self.mode == VrmEvChargerControlMode.Auto and (
            not siteCurrentTelemetryFresh or siteCurrentLimitExceeded
        ):
            inputs = self.controlStateInputs(
                effectiveCarConnected=effectiveCarConnected,
                gridTelemetryFresh=gridTelemetryFresh,
                siteCurrentTelemetryFresh=siteCurrentTelemetryFresh,
                siteCurrentLimitExceeded=siteCurrentLimitExceeded,
            )
            return ControlStates.select_control_state(inputs), None, inputs

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

        if selectedState == state.COMMAND_AUTHORITY_BLOCKED:
            return self._handleCommandAuthorityBlocked()

        if selectedState == state.SITE_CURRENT_TELEMETRY_UNSAFE:
            return self._handleSiteCurrentTelemetryUnsafe()

        if selectedState == state.SITE_CURRENT_LIMIT_STOP:
            return self._handleSiteCurrentLimitStop()

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

    def _handleCommandAuthorityBlocked(self):
        if self.wattpilotReportsActiveCharge():
            self.reportVRMStatus(VrmEvChargerStatus.StopCharging)
        else:
            self.reportVRMStatus(VrmEvChargerStatus.WaitingForSun)
        self.forceStopForInvalidCommandAuthority()
        return True

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
        self.siteCurrentForcedOff = False
        self.clearBatteryAssist()
        self.clearBatteryAssistLockout("car disconnected")
        self.clearChargeCompleteHold("car disconnected")
        self.clearPowerTransitionGrace()
        self.clearPendingPhaseSwitch()
        self.clearPhaseSwitchCandidate()
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

    def modelStatusName(self, modelStatusValue):
        modelStatus = getattr(self.wattpilot, "modelStatus", None)
        name = getattr(modelStatus, "name", None)
        if name and getattr(modelStatus, "value", None) == modelStatusValue:
            return name
        try:
            return WattpilotModelStatus(modelStatusValue).name
        except (TypeError, ValueError, AttributeError):
            return "Unknown"

    def logProtocolChargingStatusTransition(self, selectedState, inputs):
        """Log rare protocol-defined charging states without duty-cycle spam."""
        currentValue = getattr(inputs, "model_status_value", None)
        previousValue = getattr(self, "_lastObservedModelStatusValue", None)
        if currentValue == previousValue:
            return

        now = time.time()
        if ControlStates.is_protocol_charging_status(previousValue):
            observedSeconds = max(
                0,
                int(now - getattr(self, "_protocolChargingStatusSince", now)),
            )
            i(
                self,
                "Wattpilot special charging model status exited: "
                "model_status={0} name={1} next_model_status={2} "
                "observed_seconds={3}.".format(
                    previousValue,
                    self.modelStatusName(previousValue),
                    currentValue if currentValue is not None else "<unavailable>",
                    observedSeconds,
                ),
            )

        if ControlStates.is_protocol_charging_status(currentValue):
            self._protocolChargingStatusSince = now
            i(
                self,
                "Wattpilot special charging model status entered: "
                "model_status={0} name={1} mode={2} selected_state={3} "
                "effective_car_connected={4} power_kw={5} "
                "command_authority_ok={6}.".format(
                    currentValue,
                    self.modelStatusName(currentValue),
                    getattr(self.mode, "name", self.mode),
                    getattr(selectedState, "value", selectedState),
                    getattr(inputs, "effective_car_connected", None),
                    getattr(getattr(self, "wattpilot", None), "power", None),
                    getattr(inputs, "command_authority_ok", None),
                ),
            )
        else:
            self._protocolChargingStatusSince = 0

        self._lastObservedModelStatusValue = currentValue

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

    def allowWattpilotCommand(self, name=None, value=None):
        """Final firmware, ownership, and site-current command boundary."""
        if not self.refreshWattpilotFirmwareCompatibility():
            return False

        # Manual mode is observation-only. The only normal es-ESS command here
        # is the one-time Auto constraint release (frc Neutral/psm Auto).
        if not self.wattpilotAutoControlSelected():
            return True

        if name == "amp" and float(value) <= 0:
            return True
        offValue = int(getattr(WattpilotStartStop.Off, "value", WattpilotStartStop.Off))
        onValue = int(getattr(WattpilotStartStop.On, "value", WattpilotStartStop.On))
        if name == "frc" and int(value) == offValue:
            return True
        if name == "psm" and int(value) == 0:
            return True
        if name == "lmo":
            return True

        requestedPhase = self.currentPhaseMode
        if name == "psm":
            requestedPhase = int(value)
        if requestedPhase not in (1, 2):
            self.siteCurrentGuardBlocked = True
            self.siteCurrentGuardReason = "Blocked command with uncertain phase mode"
            return False

        activeCharge = self.wattpilotReportsActiveCharge()
        decision = self.siteCurrentDecision(requestedPhase, activeCharge)
        self.updateSiteCurrentRecovery(requestedPhase, decision)
        if decision is None or decision.allowed_current < self.minCurrentPerPhase:
            self.siteCurrentGuardBlocked = True
            self.siteCurrentGuardReason = "Blocked command without safe site-current headroom"
            return False

        if name == "frc":
            return (
                int(value) == onValue
                and self.siteCurrentRecoveryReady(requestedPhase)
            )

        if name == "psm":
            if not activeCharge:
                return True
            current = DecisionInputs.finite_number(
                getattr(self.wattpilot, "amp", 0)
            )
            return current is None or current <= decision.allowed_current

        if name == "amp":
            requestedCurrent = int(value)
            reportedCurrent = DecisionInputs.finite_number(
                getattr(self.wattpilot, "amp", None)
            )
            # The controller may intentionally repeat the present current
            # while a site-headroom recovery timer is maturing. Reapplying the
            # recovery state machine to that no-op would treat target ==
            # current as a completed reduction and clear the timer every
            # cycle, permanently preventing the pending increase. The final
            # boundary still recalculates physical headroom; only the recovery
            # timer mutation is skipped for an exactly unchanged command.
            unchangedCurrent = (
                reportedCurrent is not None
                and float(requestedCurrent) == float(reportedCurrent)
            )
            permitted = self.siteLimitedTargetCurrent(
                requestedPhase,
                requestedCurrent,
                applyRecovery=not unchangedCurrent,
            )
            return (
                requestedCurrent >= self.minCurrentPerPhase
                and requestedCurrent <= permitted
            )

        return False

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

            self.refreshCommandAuthorityStatus()

            self.reportStartStopValue(
                VrmEvChargerStartStop.Start
                if self.wattpilot.power != 0
                else VrmEvChargerStartStop.Stop
            )

            if not self.wattpilot.carStateReady:
                d(self, "Car state not ready yet.")
                return

            siteTelemetryFresh, siteLimitExceeded = self.refreshSiteCurrentGuard()
            self.publishSafetyTelemetry()
            gridTelemetryFresh = self.gridTelemetryIsFresh()

            selectedState, pendingPhaseStatus, _inputs = self.selectControlState(
                effectiveCarConnected,
                gridTelemetryFresh,
                siteTelemetryFresh,
                siteLimitExceeded,
            )
            self.logProtocolChargingStatusTransition(selectedState, _inputs)
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
        onePhaseDecision = self.siteCurrentDecision(1, False)
        threePhaseDecision = self.siteCurrentDecision(2, False)
        self.updateSiteCurrentRecovery(1, onePhaseDecision)
        self.updateSiteCurrentRecovery(2, threePhaseDecision)

        if (
            desiredPhaseMode == 2
            and threePhaseDecision is not None
            and threePhaseDecision.allowed_current >= self.minCurrentPerPhase
            and self.siteCurrentRecoveryReady(2)
        ):
            selectedPhaseMode = 2
        elif (
            onePhaseDecision is not None
            and onePhaseDecision.allowed_current >= self.minCurrentPerPhase
            and self.targetCurrentForPhase(1, self.allowance)
            >= self.minCurrentPerPhase
            and self.siteCurrentRecoveryReady(1)
        ):
            selectedPhaseMode = 1
        else:
            self.siteCurrentGuardBlocked = True
            self.siteCurrentGuardReason = (
                "Waiting for {0} seconds of stable site-current headroom".format(
                    self.siteCurrentRecoverySeconds
                )
            )
            self.publishServiceMessage(
                self,
                "Site-current headroom is not yet safe and stable for an EV start."
            )
            self.reportVRMStatus(VrmEvChargerStatus.WaitingForSun)
            return

        targetAmps = self.siteLimitedTargetCurrent(
            selectedPhaseMode,
            self.targetCurrentForPhase(selectedPhaseMode, self.allowance),
            applyRecovery=False,
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

        self.currentPhaseMode = selectedPhaseMode
        self.wattpilot.set_phases(selectedPhaseMode)
        self.wattpilot.set_power(targetAmps)
        self.wattpilot.set_start_stop(WattpilotStartStop.On)
        self.beginPowerTransitionGrace(
            selectedPhaseMode,
            targetAmps,
            "EV start"
        )
        self.lastOnOffTime = time.time()
        self.noAllowanceForcedOff = False
        self.siteCurrentForcedOff = False
        self.allowanceBelowMinimumSince = 0
        self.surplusSince = 0
        self.surplusBelowMinimumSince = 0
        self.dbusService["/StartStop"] = VrmEvChargerStartStop.Start.value
        self.dbusService["/StartStopLiteral"] = VrmEvChargerStartStop.Start.name


    def controlAutomaticCharging(self):
        siteTelemetryFresh, siteLimitExceeded = self.refreshSiteCurrentGuard()
        if not siteTelemetryFresh or siteLimitExceeded:
            self.clearBatteryAssist()
            self.forceStopForSiteCurrentLimit()
            return VrmEvChargerStatus.StopCharging

        # Site-current protection has priority over PV allowance grace,
        # battery assist and grid fallback. Reduce before any continuation path.
        siteEnforcement = self.enforceSiteCurrentLimit()
        if not siteEnforcement:
            self.clearBatteryAssist()
            self.forceStopForSiteCurrentLimit()
            return VrmEvChargerStatus.StopCharging
        if siteEnforcement == "reduced":
            return VrmEvChargerStatus.Charging

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

        # Lockout recovery is based on the live EV demand, not merely on PV
        # being high enough for the minimum current. This remains independent
        # from whether the next command reduces or increases the setpoint.
        recoveryShortfallW = max(
            0.0,
            self.currentChargeDemandPower() - self.continuationPvAvailableW(),
        )
        self.updateBatteryAssistLockoutRecovery(recoveryShortfallW)

        # Three-phase deficits own their phase-down timing, but must reduce the
        # equal per-phase current from PV before battery/grid continuation.
        phaseDownStatus = self.controlThreePhasePvDeficit()
        if phaseDownStatus is not None:
            return phaseDownStatus

        if self.hasMinimumAllowance():
            self.allowanceBelowMinimumSince = 0
            self.clearMinimumCurrentFallbackState()
            return self.adjustChargeForPvAllowance()

        # One-phase continuation follows the same minimum-current-first rule:
        # lower the current from PV, confirm the 6 A floor, and only then allow
        # bounded battery or explicit grid assistance for the residual deficit.
        minimumFallbackStatus = self.controlMinimumCurrentFallback(1)
        if minimumFallbackStatus is not None:
            return minimumFallbackStatus

        # The control and distribution workers can run in either order. Hold a
        # still-active session briefly when allowance first drops to 0 W so a
        # fresh MQTT allowance can arrive before an irreversible Off command.
        if not self.batteryAssistLockedOut and self.allowanceStopGraceActive():
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

    def safeTargetCurrentForPhase(self, phaseMode, allowance):
        return self.siteLimitedTargetCurrent(
            phaseMode,
            self.targetCurrentForPhase(phaseMode, allowance),
        )

    def commandSiteSafePhaseTransition(self, phaseMode, targetAmps):
        """Order amp/phase commands so both the old and new mode stay safe."""
        if targetAmps < self.minCurrentPerPhase:
            self.sitePhaseTransitionReductionAt = 0
            self.sitePhaseTransitionTargetMode = 0
            self.sitePhaseTransitionTargetAmps = 0
            return False
        current = DecisionInputs.finite_number(getattr(self.wattpilot, "amp", 0))
        current = current if current is not None and current > 0 else 0
        if current > targetAmps:
            if (
                getattr(self, "sitePhaseTransitionTargetMode", 0) != phaseMode
                or getattr(self, "sitePhaseTransitionTargetAmps", 0) != targetAmps
            ):
                self.sitePhaseTransitionReductionAt = time.time()
                self.sitePhaseTransitionTargetMode = phaseMode
                self.sitePhaseTransitionTargetAmps = targetAmps
            self.wattpilot.set_power(targetAmps)
            # Wait for fresh Wattpilot current telemetry before changing phase.
            # A sent amp reduction is not proof that the wallbox applied it.
            return "reducing"

        if (
            getattr(self, "sitePhaseTransitionTargetMode", 0) == phaseMode
            and getattr(self, "sitePhaseTransitionTargetAmps", 0) == targetAmps
        ):
            energyUpdatedAt = getattr(
                self.wattpilot, "energyTelemetryUpdatedAt", 0
            )
            measuredCurrents = tuple(
                DecisionInputs.finite_number(
                    getattr(self.wattpilot, "amps{0}".format(index), None)
                )
                for index in (1, 2, 3)
            )
            telemetryConfirmsReduction = (
                energyUpdatedAt
                > getattr(self, "sitePhaseTransitionReductionAt", 0)
                and all(value is not None for value in measuredCurrents)
                and max(measuredCurrents) <= targetAmps
            )
            if not telemetryConfirmsReduction:
                return "reducing"

        self.sitePhaseTransitionReductionAt = 0
        self.sitePhaseTransitionTargetMode = 0
        self.sitePhaseTransitionTargetAmps = 0
        self.wattpilot.set_phases(phaseMode)
        self.currentPhaseMode = phaseMode
        if current <= targetAmps:
            self.wattpilot.set_power(targetAmps)
        return "switched"

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

    def activePhaseCount(self, phaseMode=None):
        phaseMode = self.currentPhaseMode if phaseMode is None else phaseMode
        if phaseMode == 1:
            return 1
        if phaseMode == 2:
            return 3
        return 0

    def minimumChargePowerForPhaseMode(self, phaseMode):
        if phaseMode == 1:
            return self.minimumChargePower()
        if phaseMode == 2:
            return self.threePhaseMinimumPower()
        return 0.0

    def continuationPvAvailableW(self):
        """Return fresh PV usable only by an already-running charge.

        Assigned allowance remains authoritative for starts, phase-up and
        current increases. Fresh raw overhead can prevent an atomic 0 W
        assignment from hiding PV that is still available while reducing an
        active session.
        """
        assignedAllowance = max(0.0, float(self.allowance))
        rawOverhead = self.rawPvOverheadW()
        if rawOverhead is None:
            return assignedAllowance
        return max(assignedAllowance, rawOverhead)

    def clearMinimumCurrentReduction(self):
        self.minimumCurrentReductionAt = 0
        self.minimumCurrentReductionPhaseMode = 0

    def clearMinimumCurrentFallbackState(self):
        self.clearMinimumCurrentReduction()
        self.batteryAssistDeficitSince = 0
        self.clearBatteryAssist()

    def minimumCurrentTelemetryConfirmed(self, phaseMode):
        if self.minimumCurrentReductionAt <= 0:
            return True
        if self.minimumCurrentReductionPhaseMode != phaseMode:
            return False

        updatedAt = getattr(self.wattpilot, "energyTelemetryUpdatedAt", 0)
        if updatedAt <= self.minimumCurrentReductionAt:
            return False

        currentNames = ("amps1",) if phaseMode == 1 else (
            "amps1", "amps2", "amps3"
        )
        currents = tuple(
            DecisionInputs.finite_number(getattr(self.wattpilot, name, None))
            for name in currentNames
        )
        return (
            all(current is not None for current in currents)
            and max(currents) <= self.minCurrentPerPhase + 0.5
        )

    def ensureMinimumCurrentBeforeFallback(self, phaseMode):
        """Reduce to the configured floor and require fresh confirmation."""
        if self.minimumCurrentReductionAt > 0:
            if self.minimumCurrentTelemetryConfirmed(phaseMode):
                self.clearMinimumCurrentReduction()
                return True
            self.wattpilot.set_power(self.minCurrentPerPhase)
            return False

        current = DecisionInputs.finite_number(getattr(self.wattpilot, "amp", None))
        if current is not None and current <= self.minCurrentPerPhase:
            return True

        self.minimumCurrentReductionAt = time.time()
        self.minimumCurrentReductionPhaseMode = phaseMode
        self.wattpilot.set_power(self.minCurrentPerPhase)
        self.publishServiceMessage(
            self,
            "PV no longer supports the current EV setpoint. Reducing to "
            "{0}A on {1} phase(s) before any battery or grid assistance.".format(
                self.minCurrentPerPhase, self.activePhaseCount(phaseMode)
            ),
        )
        return False

    def publishBatteryAssistStatus(self):
        self.publishServiceMessage(
            self,
            "Battery assist active at {0}A: {1:.0f}W total shortfall, "
            "{2:.0f}W/phase across {3} phase(s), {4:.0f}W effective limit, "
            "for {5:.0f}s.".format(
                self.minCurrentPerPhase,
                self.batteryAssistShortfallW,
                self.batteryAssistShortfallPerPhaseW,
                self.batteryAssistActivePhases,
                self.batteryAssistEffectiveLimitW,
                self.getBatteryAssistSeconds(),
            ),
        )

    def controlMinimumCurrentFallback(self, phaseMode):
        """Reduce from PV first, then bridge only the minimum-current deficit."""
        if phaseMode not in (1, 2) or self.currentPhaseMode != phaseMode:
            self.clearMinimumCurrentFallbackState()
            return None

        usablePvW = self.continuationPvAvailableW()
        pvTargetAmps = self.targetCurrentForPhase(phaseMode, usablePvW)
        current = DecisionInputs.finite_number(getattr(self.wattpilot, "amp", None))

        if pvTargetAmps >= self.minCurrentPerPhase:
            self.clearMinimumCurrentFallbackState()
            self.allowanceBelowMinimumSince = 0

            # Raw overhead may only reduce or maintain an active setpoint. It
            # must never increase current beyond the Wattpilot's present value.
            targetAmps = self.siteLimitedTargetCurrent(phaseMode, pvTargetAmps)
            if current is not None and current > 0:
                targetAmps = min(targetAmps, max(self.minCurrentPerPhase, int(current)))
            if current is None or targetAmps < current:
                self.wattpilot.set_power(targetAmps)
                i(
                    self,
                    "Reducing charge current from continuation PV to {0}A on "
                    "{1} phase(s).".format(
                        targetAmps, self.activePhaseCount(phaseMode)
                    ),
                )
            return VrmEvChargerStatus.Charging

        if self.batteryAssistDeficitSince == 0:
            self.batteryAssistDeficitSince = time.time()
            # Start the normal stop/phase-down debounce at the original PV dip,
            # not after current telemetry confirms the 6 A reduction.
            self.allowanceStopGraceActive()

        if not self.ensureMinimumCurrentBeforeFallback(phaseMode):
            return VrmEvChargerStatus.Charging

        minimumDemandW = self.minimumChargePowerForPhaseMode(phaseMode)
        shortfallW = max(0.0, minimumDemandW - usablePvW)

        if self.startOrContinueBatteryAssist(shortfallW, phaseMode):
            self.publishBatteryAssistStatus()
            return VrmEvChargerStatus.Charging

        # Explicit grid fallback is also continuation-only and may cover only
        # the residual demand at the configured minimum current.
        if self.allowGridCharging and shortfallW > 0:
            return VrmEvChargerStatus.Charging

        return None

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
            targetAmps = self.safeTargetCurrentForPhase(1, self.allowance)
            self.publishServiceMessage(
                self,
                "3-phase switch was not confirmed by Wattpilot telemetry. "
                "Falling back to 1-phase."
            )
            phaseResult = self.commandSiteSafePhaseTransition(1, targetAmps)
            if phaseResult == "reducing":
                return transitionStatus
            self.lastPhaseSwitchTime = now
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
            ControlStates.is_active_charging_status(statusValue)
            or getattr(self, "powerTransitionUntil", 0) > time.time()
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
        unnecessary phase reduction or stop when the distributor and Wattpilot
        workers execute in the opposite order for one or two cycles.
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
                "EV allowance fell below the usable minimum. Waiting up to "
                "{0}s for a refreshed distributor allowance before reducing "
                "phase or stopping.".format(
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

    def siteCurrentTelemetryIsFresh(self, requireChargerCurrent=None):
        """Return whether mandatory physical L1/L2/L3 inputs are usable."""
        now = time.time()
        for phase in ("L1", "L2", "L3"):
            if not DecisionInputs.timestamped_value_is_fresh(
                getattr(self, "siteCurrent{0}Valid".format(phase), False),
                getattr(self, "siteCurrent{0}UpdatedAt".format(phase), 0),
                self.siteCurrentFreshSeconds,
                now,
            ):
                return False

        if requireChargerCurrent is None:
            requireChargerCurrent = self.wattpilotReportsActiveCharge()
        if not requireChargerCurrent:
            return True

        updatedAt = getattr(self.wattpilot, "energyTelemetryUpdatedAt", 0)
        if updatedAt <= 0 or now - updatedAt > self.siteCurrentFreshSeconds:
            return False
        currents = tuple(
            DecisionInputs.finite_number(
                getattr(self.wattpilot, "amps{0}".format(index), None)
            )
            for index in (1, 2, 3)
        )
        return all(current is not None and current >= 0 for current in currents)

    def siteCurrentDecision(self, requestedPhaseMode, activeCharge=None):
        """Calculate site-safe current for a requested Wattpilot phase mode."""
        if activeCharge is None:
            activeCharge = self.wattpilotReportsActiveCharge()
        if not self.siteCurrentTelemetryIsFresh(activeCharge):
            return None

        measuredPhaseMode = 0
        chargerCurrents = (0, 0, 0)
        if activeCharge:
            measuredPhaseMode = getattr(self, "currentPhaseMode", 0)
            if measuredPhaseMode not in (1, 2):
                return None
            if getattr(self, "pendingPhaseSwitchMode", 0) not in (0, measuredPhaseMode):
                return None
            chargerCurrents = tuple(
                getattr(self.wattpilot, "amps{0}".format(index), None)
                for index in (1, 2, 3)
            )

        try:
            decision = SiteCurrentDecisions.evaluate_site_current(
                tuple(
                    getattr(self, "siteCurrent{0}Value".format(phase), None)
                    for phase in ("L1", "L2", "L3")
                ),
                chargerCurrents,
                measuredPhaseMode,
                requestedPhaseMode,
                self.charger1PhaseMapping,
                self.siteMaxCurrent,
            )
        except (TypeError, ValueError):
            return None

        self.siteCurrentAllowedCurrent = decision.allowed_current
        self.siteCurrentLimitingPhase = decision.limiting_phase
        self.siteCurrentHeadrooms = decision.headrooms
        return decision

    def updateSiteCurrentRecovery(self, phaseMode, decision, now=None):
        """Track continuous site-safe headroom independently by phase mode."""
        if now is None:
            now = time.time()
        recovery = getattr(self, "siteCurrentRecoverySince", {1: 0, 2: 0})
        if not isinstance(recovery, dict):
            recovery = {1: 0, 2: 0}
        if decision is None or decision.allowed_current < self.minCurrentPerPhase:
            recovery[phaseMode] = 0
        elif recovery.get(phaseMode, 0) <= 0:
            recovery[phaseMode] = now
        self.siteCurrentRecoverySince = recovery

    def siteCurrentRecoveryElapsed(self, phaseMode):
        since = getattr(self, "siteCurrentRecoverySince", {}).get(phaseMode, 0)
        return max(0, time.time() - since) if since > 0 else 0

    def siteCurrentRecoveryReady(self, phaseMode):
        return (
            self.siteCurrentRecoveryElapsed(phaseMode)
            >= self.siteCurrentRecoverySeconds
        )

    def refreshSiteCurrentGuard(self):
        """Refresh safety state before Auto/Eco state selection and commands."""
        self.refreshSiteCurrentTelemetryHeartbeat()
        active = self.wattpilotReportsActiveCharge()
        decisions = {
            phase: self.siteCurrentDecision(phase, active)
            for phase in (1, 2)
        }
        now = time.time()
        for phase, decision in decisions.items():
            self.updateSiteCurrentRecovery(phase, decision, now)

        currentPhase = self.currentPhaseMode if self.currentPhaseMode in (1, 2) else 1
        selected = decisions[currentPhase]
        telemetryFresh = selected is not None
        limitExceeded = bool(
            active
            and selected is not None
            and selected.allowed_current < self.minCurrentPerPhase
        )

        autoMode = self.mode == VrmEvChargerControlMode.Auto
        if not autoMode:
            self.siteCurrentGuardBlocked = False
            self.siteCurrentGuardReason = "Manual mode: observation only"
        elif not telemetryFresh:
            self.siteCurrentGuardBlocked = True
            self.siteCurrentGuardReason = "Site-current telemetry missing, invalid, stale, or phase-uncertain"
            self.clearPhaseSwitchCandidate()
        elif limitExceeded:
            self.siteCurrentGuardBlocked = True
            self.siteCurrentGuardReason = "No phase headroom for the 6 A charging minimum"
            self.clearPhaseSwitchCandidate()
        else:
            self.siteCurrentGuardBlocked = False
            self.siteCurrentGuardReason = "Site-current headroom available"

        threePhaseDecision = decisions[2]
        if (
            threePhaseDecision is None
            or threePhaseDecision.allowed_current < self.minCurrentPerPhase
        ):
            self.clearPhaseSwitchCandidate()

        return telemetryFresh, limitExceeded

    def siteLimitedTargetCurrent(self, phaseMode, pvTarget, applyRecovery=True):
        """Cap a PV target by physical per-phase site headroom."""
        decision = self.siteCurrentDecision(phaseMode)
        self.updateSiteCurrentRecovery(phaseMode, decision)
        if decision is None:
            return 0

        target = min(int(pvTarget), decision.allowed_current)
        if target < self.minCurrentPerPhase:
            return 0
        if not applyRecovery:
            return target

        current = DecisionInputs.finite_number(getattr(self.wattpilot, "amp", 0))
        current = int(current) if current is not None and current > 0 else 0
        if current < self.minCurrentPerPhase:
            return target if self.siteCurrentRecoveryReady(phaseMode) else 0
        since = getattr(self, "siteCurrentRecoverySince", {}).get(phaseMode, 0)
        recovery = SiteCurrentDecisions.limit_current_recovery(
            current,
            target,
            since,
            self.siteCurrentRecoverySeconds,
            time.time(),
        )
        recoveryTimers = getattr(self, "siteCurrentRecoverySince", {1: 0, 2: 0})
        recoveryTimers[phaseMode] = recovery.next_recovery_since
        self.siteCurrentRecoverySince = recoveryTimers
        return recovery.allowed_current

    def enforceSiteCurrentLimit(self):
        """Immediately reduce an active Auto charge when site headroom shrinks."""
        phaseMode = self.currentPhaseMode
        if phaseMode not in (1, 2):
            return False
        decision = self.siteCurrentDecision(phaseMode, True)
        if decision is None or decision.allowed_current < self.minCurrentPerPhase:
            return False
        current = DecisionInputs.finite_number(getattr(self.wattpilot, "amp", None))
        if current is not None and current > decision.allowed_current:
            self.siteCurrentGuardReason = "Charging current reduced by {0} headroom".format(
                decision.limiting_phase
            )
            self.siteCurrentRecoverySince[phaseMode] = 0
            self.wattpilot.set_power(decision.allowed_current)
            return "reduced"
        return "safe"

    def _handleSiteCurrentTelemetryUnsafe(self):
        self.publishServiceMessage(
            self,
            "Site-current telemetry is missing, invalid, stale, or phase-uncertain. "
            "Stopping Auto/Eco charging for safety."
        )
        self.reportVRMStatus(
            VrmEvChargerStatus.StopCharging
            if self.wattpilotReportsActiveCharge()
            else VrmEvChargerStatus.WaitingForSun,
            "Stopped for stale site-current telemetry",
        )
        self.forceStopForSiteCurrentLimit()
        return True

    def _handleSiteCurrentLimitStop(self):
        self.publishServiceMessage(
            self,
            "Whole-site phase headroom is below the 6 A EV minimum. "
            "Stopping Auto/Eco charging immediately."
        )
        self.reportVRMStatus(
            VrmEvChargerStatus.StopCharging,
            "Stopped for site current limit",
        )
        self.forceStopForSiteCurrentLimit()
        return True

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

        Current is reduced from PV first. Battery/grid continuation is eligible
        only after fresh Wattpilot telemetry confirms the configured minimum
        current on all three phases. Neither source can start a new charge,
        increase current, or cause phase-up.
        """
        if self.currentPhaseMode != 2 or not self.allowanceIsFresh():
            return None

        assignedAllowance = max(0.0, float(self.allowance))
        threePhaseThreshold = self.phaseDownThresholdW()
        if assignedAllowance >= threePhaseThreshold:
            self.allowanceBelowMinimumSince = 0
            self.clearMinimumCurrentFallbackState()
            self.clearPhaseSwitchCandidate()
            return None

        usablePvW = self.continuationPvAvailableW()
        pvTargetAmps = self.targetCurrentForPhase(2, usablePvW)
        fallbackStatus = self.controlMinimumCurrentFallback(2)

        # Fresh raw overhead can keep the running three-phase session at a PV-
        # supported current, but the helper caps it at the current setpoint so
        # raw telemetry cannot increase demand.
        if pvTargetAmps >= self.minCurrentPerPhase:
            self.clearPhaseSwitchCandidate()
            return fallbackStatus

        # A lower-current command is not proof that the wallbox applied it.
        # Stay in the present phase mode while waiting for fresh <= minimum-A
        # telemetry; the normal site-current freshness guard bounds this wait.
        if self.minimumCurrentReductionAt > 0:
            return VrmEvChargerStatus.Charging

        onePhasePvW = usablePvW
        batteryBridgeActive = self.batteryAssistActive
        fallbackAvailable = batteryBridgeActive or (
            self.allowGridCharging and fallbackStatus is not None
        )

        if not fallbackAvailable:
            # The allowance grace began at the original deficit. A completed
            # battery-assist window must not receive another grace interval.
            if (
                not self.batteryAssistLockedOut
                and self.allowanceStopGraceActive()
            ):
                return VrmEvChargerStatus.Charging

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

        # Battery assist intentionally preserves the current phase mode for its
        # bounded window. The timer may mature in the background, but only grid
        # fallback may phase down while its fallback remains active.
        if batteryBridgeActive:
            return VrmEvChargerStatus.Charging

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
        targetAmps = self.safeTargetCurrentForPhase(1, usablePv)

        self.publishServiceMessage(
            self,
            "PV allowance dropped below the three-phase threshold. "
            "Switching to 1-phase before applying battery-assist or stop logic."
        )
        phaseResult = self.commandSiteSafePhaseTransition(1, targetAmps)
        if not phaseResult:
            self.forceStopForSiteCurrentLimit()
            return VrmEvChargerStatus.StopCharging
        if phaseResult == "reducing":
            return VrmEvChargerStatus.Charging
        self.clearPhaseSwitchCandidate()
        self.lastPhaseSwitchTime = time.time()
        self.beginPhaseSwitchConfirmation(1)
        self.beginPowerTransitionGrace(
            1, targetAmps, "3-to-1 phase switch"
        )
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
        self.dbusService["/BatteryAssist/ShortfallPerPhase"] = int(
            round(self.batteryAssistShortfallPerPhaseW)
        )
        self.dbusService["/BatteryAssist/ActivePhases"] = int(
            self.batteryAssistActivePhases
        )
        self.dbusService["/BatteryAssist/EffectiveLimit"] = int(
            round(self.batteryAssistEffectiveLimitW)
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
        now = time.time()
        siteTelemetryHealthy = self.siteCurrentTelemetryIsFresh()
        sitePaths = {
            "/SiteCurrentLimit": self.siteMaxCurrent,
            "/Charger1PhaseMapping": self.charger1PhaseMapping,
            "/SiteAllowedCurrent": int(self.siteCurrentAllowedCurrent),
            "/SiteLimitingPhase": self.siteCurrentLimitingPhase,
            "/SiteCurrentTelemetryHealthy": int(siteTelemetryHealthy),
            "/SiteCurrentGuardBlocked": int(self.siteCurrentGuardBlocked),
            "/SiteCurrentGuardReason": self.siteCurrentGuardReason,
        }
        for index, phase in enumerate(("L1", "L2", "L3")):
            value = getattr(self, "siteCurrent{0}Value".format(phase), None)
            updatedAt = getattr(self, "siteCurrent{0}UpdatedAt".format(phase), 0)
            sitePaths["/SiteCurrent{0}".format(phase)] = (
                round(value, 2) if value is not None else 0
            )
            sitePaths["/SiteCurrentAge{0}".format(phase)] = (
                round(max(0, now - updatedAt), 1) if updatedAt > 0 else -1
            )
            sitePaths["/SiteHeadroom{0}".format(phase)] = round(
                self.siteCurrentHeadrooms[index], 2
            )
        diagnosticPhase = self.currentPhaseMode if self.currentPhaseMode in (1, 2) else 1
        sitePaths["/SiteCurrentRecoveryElapsed"] = int(
            round(self.siteCurrentRecoveryElapsed(diagnosticPhase))
        )
        for path, value in sitePaths.items():
            self.publishRetained(path, value)

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
        self.batteryAssistDeficitSince = 0
        self.batteryAssistActive = False
        self.batteryAssistShortfallW = 0
        self.batteryAssistShortfallPerPhaseW = 0
        self.batteryAssistActivePhases = 0
        self.batteryAssistEffectiveLimitW = 0
        self.minimumCurrentReductionAt = 0
        self.minimumCurrentReductionPhaseMode = 0

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

    def startOrContinueBatteryAssist(self, shortfallW, phaseMode=None):
        phaseMode = self.currentPhaseMode if phaseMode is None else phaseMode
        activePhases = self.activePhaseCount(phaseMode)
        if activePhases <= 0:
            self.clearBatteryAssist()
            return False

        soc = None
        gridImport = 0
        if shortfallW > 0 and not self.batteryAssistLockedOut:
            soc = self.batterySoc()
            gridImport = self.gridImportPower()

        effectiveLimitW = (
            self.batteryAssistMaxShortfallPerPhaseW * activePhases
        )
        assistSince = self.batteryAssistSince
        if assistSince == 0:
            assistSince = self.batteryAssistDeficitSince
        wasActive = self.batteryAssistActive

        decision = SafetyDecisions.evaluate_battery_assist(
            self.batteryAssistEnabled,
            shortfallW,
            self.batteryAssistLockedOut,
            self.wattpilot.power,
            soc,
            self.batteryAssistSocMin,
            effectiveLimitW,
            gridImport,
            self.gridImportStopW,
            assistSince,
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
        if not wasActive:
            self.publishServiceMessage(
                self,
                "PV dip reached the {0}A floor. Starting battery assist at "
                "{1:.0f}% SOC.".format(self.minCurrentPerPhase, soc)
            )

        self.batteryAssistActive = True
        self.batteryAssistShortfallW = shortfallW
        self.batteryAssistShortfallPerPhaseW = shortfallW / activePhases
        self.batteryAssistActivePhases = activePhases
        self.batteryAssistEffectiveLimitW = effectiveLimitW

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

    def forceStopForInvalidCommandAuthority(self):
        """Stop without phase commands when a native controller may compete."""
        self.surplusSince = 0
        self.surplusBelowMinimumSince = 0
        self.allowanceBelowMinimumSince = 0
        self.clearBatteryAssist()
        self.clearPowerTransitionGrace()
        self.clearPendingPhaseSwitch()
        self.clearPhaseSwitchCandidate()

        chargerStillActive = (
            self.wattpilot.power is not None and self.wattpilot.power > 0
        )
        needsStop = (
            not self.commandAuthorityForcedOff
            or self.wattpilot.startState != WattpilotStartStop.Off
            or chargerStillActive
        )
        if needsStop:
            self.wattpilot.set_power(0)
            self.wattpilot.set_start_stop(WattpilotStartStop.Off)
            self.lastOnOffTime = time.time()

        self.commandAuthorityForcedOff = True
        self.noAllowanceForcedOff = True
        self.currentPhaseMode = 0
        self.dbusService["/StartStop"] = VrmEvChargerStartStop.Stop.value
        self.dbusService["/StartStopLiteral"] = VrmEvChargerStartStop.Stop.name

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

    def forceStopForSiteCurrentLimit(self):
        """Stop Auto/Eco without a phase command after a site guard trip."""
        self.surplusSince = 0
        self.surplusBelowMinimumSince = 0
        self.allowanceBelowMinimumSince = 0
        self.clearBatteryAssist()
        self.clearPowerTransitionGrace()
        self.clearPendingPhaseSwitch()
        self.clearPhaseSwitchCandidate()
        self.siteCurrentRecoverySince = {1: 0, 2: 0}
        self.sitePhaseTransitionReductionAt = 0
        self.sitePhaseTransitionTargetMode = 0
        self.sitePhaseTransitionTargetAmps = 0

        chargerStillActive = (
            self.wattpilot.power is not None and self.wattpilot.power > 0
        )
        needsStop = (
            not self.siteCurrentForcedOff
            or self.wattpilot.startState != WattpilotStartStop.Off
            or chargerStillActive
        )
        if needsStop:
            self.wattpilot.set_power(0)
            self.wattpilot.set_start_stop(WattpilotStartStop.Off)
            if not self.siteCurrentForcedOff:
                self.lastOnOffTime = time.time()

        self.siteCurrentForcedOff = True
        self.noAllowanceForcedOff = True
        self.currentPhaseMode = 0
        self.dbusService["/StartStop"] = VrmEvChargerStartStop.Stop.value
        self.dbusService["/StartStopLiteral"] = VrmEvChargerStartStop.Stop.name


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

        if desiredPhaseMode == 2 and enteringPhaseMode != 2:
            threePhaseSiteDecision = self.siteCurrentDecision(2)
            self.updateSiteCurrentRecovery(2, threePhaseSiteDecision)
            if (
                threePhaseSiteDecision is None
                or threePhaseSiteDecision.allowed_current < self.minCurrentPerPhase
            ):
                self.clearPhaseSwitchCandidate()
                desiredPhaseMode = 1

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
                targetAmps = self.safeTargetCurrentForPhase(1, self.allowance)
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
                targetAmps = self.safeTargetCurrentForPhase(2, self.allowance)
                i(self, "PV surplus supports 3-phase charging. Switching to 3-phase.")
                self.publishServiceMessage(
                    self, "Switching to 3-phase from PV surplus."
                )
                phaseResult = self.commandSiteSafePhaseTransition(2, targetAmps)
                if not phaseResult:
                    self.clearPhaseSwitchCandidate()
                    return VrmEvChargerStatus.Charging
                if phaseResult == "reducing":
                    return VrmEvChargerStatus.Charging
                self.lastPhaseSwitchTime = time.time()
                self.beginPhaseSwitchConfirmation(2)
                self.beginPowerTransitionGrace(2, targetAmps, "1-to-3 phase switch")
                self.clearPhaseSwitchCandidate()
                return VrmEvChargerStatus.SwitchingTo3Phase

            if phaseUpDecision.action == PhaseDecisions.PHASE_SWITCH_READY:
                targetAmps = self.safeTargetCurrentForPhase(1, self.allowance)
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

            targetAmps = self.safeTargetCurrentForPhase(1, self.allowance)
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
        targetAmps = self.safeTargetCurrentForPhase(
            desiredPhaseMode, self.allowance
        )
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
