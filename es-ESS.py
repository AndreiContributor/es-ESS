#!/usr/bin/env python
 
# imports
import configparser
import datetime
from logging.handlers import TimedRotatingFileHandler
import signal
import sys
import os
import logging
import threading
import json
import math
import time
from builtins import Exception, int, str
from concurrent.futures import ThreadPoolExecutor
from typing import Dict
import ssl

if sys.version_info.major == 2:
    import gobject # type: ignore
else:
    from gi.repository import GLib as gobject # type: ignore

import paho.mqtt.client as mqtt # type: ignore

# victronr
sys.path.insert(1, '/data/es-ESS/velib_python-master')
from vedbus import VeDbusService # type: ignore
from dbusmonitor import DbusMonitor # type: ignore
from dbus.mainloop.glib import DBusGMainLoop # type: ignore

#esEss imports
import Globals
import Helper
import RuntimeCompatibility
from Globals import MqttSubscriptionType
from Helper import i, c, d, w, e, t
from esESSService import DbusSubscription, esESSService, WorkerThread, MqttSubscription

# Have a mainloop, so we can send/receive asynchronous calls to and from dbus
DBusGMainLoop(set_as_default=True)

class esESS:
    _shutdownPublishTimeoutSeconds = 2.0

    def __init__(self):
        # Defense in depth for callers that construct esESS directly instead
        # of using main(). Keep this outside the broad initialization handler
        # so a compatibility failure cannot leave a partly initialized object.
        self.venusOsVersion = RuntimeCompatibility.require_validated_venus_os()
        try:
            #First thing to do is check, if the current configuration matches the desired version.
            #if not, upgrade to most recent version, save changes and reload configuration file. 
            self._validateConfiguration()
            self._validateRuntimeBootstrap()
            
            self._sigTermInvoked=False
            self._shutdownMqttDisconnectsLogged = set()
            self.mainMqttClient:mqtt.Client = None
            self.localMqttClient:mqtt.Client = None
            self.mainMqttClientConnected = False
            self.localMqttClientConnected = False
            self.mqttThrottlePeriod = 0

            if ("ThrottlePeriod" in self.config["Mqtt"]):
                self.mqttThrottlePeriod = int(self.config["Mqtt"]["ThrottlePeriod"])
            
            i(self, "Initializing " + Globals.esEssTag + " (" + Globals.currentVersionString + ")")

            #init core values
            self._services: Dict[str, esESSService] = {}
            self._dbusSubscriptions: Dict[str, list[DbusSubscription]] = {}
            self._mqttSubscriptions: Dict[str, list[MqttSubscription]] = {}
            self._serviceMessageIndex: Dict[str, int] = {}
            self._dbusMonitor: DbusMonitor = None
            self._gridSetPointRequests: Dict[str, float] = {}
            self._gridSetPointRequestsLock = threading.Lock()
            self._gridSetPointDefault = float(self.config["Common"]["DefaultPowerSetPoint"])
            self._gridSetPointCurrent = -99999 #use a unreal number at first, so es-ESS will detect a change upon restart and guarantee to set default GSP.
            self._threadExecutionsMinute = 0
            
            i(self, "Initializing thread pool with a size of {0} and sleeping 20 seconds... ".format(self.config["Common"]["NumberOfThreads"]))

            #wait 20 seconds after startup, lot of services may not yet have hit dbus. 
            Helper.waitTimeout(lambda: False, 20) 

            self.threadPool = ThreadPoolExecutor(int(self.config["Common"]["NumberOfThreads"]), "TPt")

            if (self.mqttThrottlePeriod > 0):
                self._mainMqttThrottleDictLock = threading.Lock()
                self._mainMqttThrottleDict = { }
                self._localMqttThrottleDictLock = threading.Lock()
                self._localMqttThrottleDict = { }
                self._lastThrottleLog = 0
                self._messageCount = 0
                self._sendCount = 0
                self._lastLocalThrottleLog = 0
                self._localMessageCount = 0
                self._localSendCount = 0
                i(self, "Mqtt-Throttling is enabled to {0}ms".format(self.mqttThrottlePeriod))   
        except Exception as ex:
            c(self, "Exception during __init__:", exc_info=ex)
            raise

    def configureMqtt(self):
        try:
            d(self,"Using phao >= 2.0 compliant initialization...")
            self.mainMqttClient:mqtt.Client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "es-ESS-MQTT-Client")
            self.localMqttClient:mqtt.Client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "es-ESS-Local-MQTT-Client")
        except:
            d(self,"Nope... Trying phao < 2.0 compliant initialization...")
            self.mainMqttClient:mqtt.Client = mqtt.Client("es-ESS-MQTT-Client")
            self.localMqttClient:mqtt.Client = mqtt.Client("es-ESS-Local-MQTT-Client")
                
        i(Globals.esEssTag, "MQTT: Connecting to broker: {0}".format(config["Mqtt"]["Host"]))
        self.mainMqttClient.on_disconnect = self.onMainMqttDisconnect
        self.mainMqttClient.on_connect = self.onMainMqttConnect

        if 'User' in config['Mqtt'] and 'Password' in config['Mqtt'] and config['Mqtt']['User'] != '' and config['Mqtt']['Password'] != '':
            self.mainMqttClient.username_pw_set(username=config['Mqtt']['User'], password=config['Mqtt']['Password'])

        self.mainMqttClient.will_set("es-ESS/$SYS/Status", "Offline", 2, True)

        if (self.config["Mqtt"]["SslEnabled"].lower() == "true"):
            i(self, "Connecting to broker: {0}://{1}:{2}".format("tcp-ssl", config["Mqtt"]["Host"], config["Mqtt"]["Port"]))
            self.mainMqttClient.tls_set(cert_reqs=ssl.CERT_NONE)
            self.mainMqttClient.tls_insecure_set(True)
            self.mainMqttClient.connect(
                host=config["Mqtt"]["Host"],
                port=int(config["Mqtt"]["Port"])
            )
            
        else:
            i(self, "Connecting to broker: {0}://{1}:{2}".format("tcp", config["Mqtt"]["Host"], config["Mqtt"]["Port"]))
            self.mainMqttClient.connect(
                host=config["Mqtt"]["Host"],
                port=int(config["Mqtt"]["Port"])
            )

        self.mainMqttClient.loop_start()
        self.mainMqttClient.publish("es-ESS/$SYS/Status", "Online", 2, True)
        self.mainMqttClient.publish("es-ESS/$SYS/Version", Globals.currentVersionString, 2, True)
        self.mainMqttClient.publish("es-ESS/$SYS/ConnectionTime", time.time(), 2, True)
        self.mainMqttClient.publish("es-ESS/$SYS/ConnectionDateTime", str(datetime.datetime.now()), 2, True)
        self.mainMqttClient.publish("es-ESS/$SYS/Github", "https://github.com/realdognose/es-ESS", 2, True)

        #local mqtt
        self.localMqttClient.on_disconnect = self.onLocalMqttDisconnect
        self.localMqttClient.on_connect = self.onLocalMqttConnect

        if (self.config["Mqtt"]["LocalSslEnabled"].lower() == "true"):
            i(self, "Connecting to broker: {0}://{1}:{2}".format("tcp-ssl", "localhost", 8883))
            self.localMqttClient.tls_set(cert_reqs=ssl.CERT_NONE)
            self.localMqttClient.tls_insecure_set(True)
            #TODO: After a system reboot, es-ESS is starting faster than the local mqtt, which might lead to connection issues. 
            #      Either loop in a try/error, or sth.
            #      Similiar issues might occur for the dbus service, if devices are not yet registered?
            self.localMqttClient.connect(
                host="localhost",
                port=8883
            )
            
        else:
            i(self, "Connecting to broker: {0}://{1}:{2}".format("tcp", "localhost", 1883))
            self.localMqttClient.connect(
                host="localhost",
                port=1883
            )

        self.localMqttClient.loop_start()

    def onMainMqttConnect(self, client, userdata, flags, rc):
        if rc == 0:
            i(self, "Connected to MQTT broker!")
            self.mainMqttClientConnected = True

            #Check, if we need to subscribe again.
            for (key, sublist) in self._mqttSubscriptions.items():
                for sub in sublist:
                    if (sub.type == MqttSubscriptionType.Main):
                        d(self, "Restoring main MQTT subscription for Service {0} on {1} with callback: {2}".format(sub.requestingService.__class__.__name__, sub.topic, Helper.formatCallback(sub.callback)))
                        self.mainMqttClient.subscribe(sub.topic, sub.qos)
                        self.mainMqttClient.message_callback_add(sub.topic, sub.callback)
        else:
            e(self, "Failed to connect, return code %d\n", rc)
    
    def onLocalMqttConnect(self, client, userdata, flags, rc):
        if rc == 0:
            i(self, "Connected to MQTT broker!")
            self.localMqttClientConnected = True
            
            #Check, if we need to subscribe again.
            for (key, sublist) in self._mqttSubscriptions.items():
                for sub in sublist:
                    if (sub.type == MqttSubscriptionType.Local):
                        d(self, "Restoring local MQTT subscription for Service {0} on {1} with callback: {2}".format(sub.requestingService.__class__.__name__, sub.topic, Helper.formatCallback(sub.callback)))
                        self.localMqttClient.subscribe(sub.topic, sub.qos)
                        self.localMqttClient.message_callback_add(sub.topic, sub.callback)
        else:
            e(self, "Failed to connect, return code %d\n", rc)

    def _logShutdownMqttDisconnect(self, clientName):
        loggedClients = getattr(self, "_shutdownMqttDisconnectsLogged", set())
        if (clientName in loggedClients):
            return

        # Record before logging so an asynchronous callback cannot duplicate it.
        loggedClients.add(clientName)
        self._shutdownMqttDisconnectsLogged = loggedClients
        i(self, "{0} MQTT disconnect during graceful shutdown.".format(clientName))
        i(self, "{0} MQTT automatic reconnect is disabled during graceful shutdown.".format(clientName))

    def onMainMqttDisconnect(self, client, userdata, rc):
        if (self._sigTermInvoked):
            self._logShutdownMqttDisconnect("Main")
            return

        w(self, "Mqtt Disconnect.")

        if (self.mainMqttClient.reconnect):
            i(self, "Waiting for automatic reconnect.")
        else:
            w(self, "Automatic reconnect is disabled.")

    def onLocalMqttDisconnect(self, client, userdata, rc):
        if (self._sigTermInvoked):
            self._logShutdownMqttDisconnect("Local")
            return

        w(self, "Mqtt Disconnect.")

        if (self.localMqttClient.reconnect):
            i(self, "Waiting for automatic reconnect.")
        else:
            w(self, "Automatic reconnect is disabled.")

    
    def _checkAndEnable(self, clazz):
       if (self.config["Services"][clazz].lower()=="true"):
          i(self, "=========== Service {0} is enabled. ===========".format(clazz))
          imp = __import__(clazz)
          class_ = getattr(imp, clazz)
          self._services[clazz] = class_()
       else:
          i(self, "=========== Service {0} is not enabled. Skipping initialization. ===========".format(clazz))  

       self.publishMainMqtt("{0}/{1}".format(Globals.esEssTag, clazz), "Enabled" if self.config["Services"][clazz].lower()=="true" else "Disabled") 

    def _ensureConfigSection(self, section):
        if (not self.config.has_section(section)):
            self.config.add_section(section)

    def _setConfigDefault(self, section, option, value):
        self._ensureConfigSection(section)
        if (not self.config.has_option(section, option)):
            self.config[section][option] = value

    def _validateConfigValues(self):
        errors = []

        def invalid(section, key, rule, value):
            errors.append(
                "[{0}] {1} {2}; got {3!r}".format(section, key, rule, value)
            )

        def integer(section, key, default=None):
            if (not self.config.has_section(section)):
                return None

            if (not self.config.has_option(section, key)):
                if (default is None):
                    return None
                value = default
            else:
                value = self.config[section][key]

            try:
                return int(value)
            except (TypeError, ValueError):
                invalid(section, key, "must be an integer", value)
                return None

        def number(section, key, default=None):
            if (not self.config.has_section(section)):
                return None

            if (not self.config.has_option(section, key)):
                if (default is None):
                    return None
                value = default
            else:
                value = self.config[section][key]

            try:
                parsed = float(value)
            except (TypeError, ValueError):
                invalid(section, key, "must be a number", value)
                return None

            if (not math.isfinite(parsed)):
                invalid(section, key, "must be a finite number", value)
                return None
            return parsed

        if (self.config.has_section("FroniusWattpilot")):
            section = "FroniusWattpilot"
            min_current = integer(section, "MinCurrentPerPhase", 6)
            max_current = integer(section, "MaxCurrentPerPhase", 16)

            if (min_current is not None and not 6 <= min_current <= 32):
                invalid(section, "MinCurrentPerPhase", "must be between 6 and 32 A", min_current)
            if (max_current is not None and not 6 <= max_current <= 32):
                invalid(section, "MaxCurrentPerPhase", "must be between 6 and 32 A", max_current)
            if (
                min_current is not None
                and max_current is not None
                and max_current < min_current
            ):
                invalid(
                    section,
                    "MaxCurrentPerPhase",
                    "must be greater than or equal to MinCurrentPerPhase",
                    max_current,
                )

            phase_start = integer(section, "ThreePhasePvSurplusStartW", 4200)
            phase_stop = integer(section, "ThreePhasePvSurplusStopW", 4140)
            if (
                phase_start is not None
                and phase_stop is not None
                and phase_start <= phase_stop
            ):
                invalid(
                    section,
                    "ThreePhasePvSurplusStartW",
                    "must be greater than ThreePhasePvSurplusStopW",
                    phase_start,
                )

            assist_soc = number(section, "BatteryAssistSocMin", 60)
            if (assist_soc is not None and not 0 <= assist_soc <= 100):
                invalid(section, "BatteryAssistSocMin", "must be between 0 and 100", assist_soc)

            assist_enabled = self.config[section].get(
                "BatteryAssistEnabled", "false"
            ).lower() == "true"
            assist_seconds = integer(section, "BatteryAssistMaxSeconds", 300)
            if (
                assist_enabled
                and assist_seconds is not None
                and assist_seconds <= 0
            ):
                invalid(
                    section,
                    "BatteryAssistMaxSeconds",
                    "must be greater than 0 when BatteryAssistEnabled=true",
                    assist_seconds,
                )

            battery_soc_fresh_seconds = integer(
                section, "BatterySocFreshSeconds", 15
            )
            if (
                battery_soc_fresh_seconds is not None
                and battery_soc_fresh_seconds <= 0
            ):
                invalid(
                    section,
                    "BatterySocFreshSeconds",
                    "must be greater than 0",
                    battery_soc_fresh_seconds,
                )

            for key, default in (
                ("MinPhaseSwitchSeconds", 600),
                ("AllowanceDropGraceSeconds", 15),
                ("SurplusDropGraceSeconds", 20),
                ("CarDisconnectConfirmSeconds", 15),
                ("StartupGraceSeconds", 60),
            ):
                value = integer(section, key, default)
                if (value is not None and value < 0):
                    invalid(section, key, "must be greater than or equal to 0", value)

        for section, key in (
            ("SolarOverheadDistributor", "UpdateInterval"),
            ("TimeToGoCalculator", "UpdateInterval"),
            ("FroniusSmartmeterJSON", "PollFrequencyMs"),
            ("Shelly3EMGrid", "PollFrequencyMs"),
        ):
            value = integer(section, key)
            if (value is not None and value <= 0):
                invalid(section, key, "must be greater than 0", value)

        for section in self.config.sections():
            if (section.startswith("ShellyPMInverter:")):
                value = integer(section, "PollFrequencyMs")
                if (value is not None and value <= 0):
                    invalid(section, "PollFrequencyMs", "must be greater than 0", value)

        if (errors):
            for error in errors:
                c(self, "Invalid configuration: {0}".format(error))
            raise SystemExit(1)

    def _validateRuntimeBootstrap(self):
        errors = []

        required_options = {
            "Common": (
                "LogLevel",
                "NumberOfThreads",
                "ServiceMessageCount",
                "VRMPortalID",
                "DefaultPowerSetPoint",
            ),
            "Mqtt": ("Host", "Port", "SslEnabled", "LocalSslEnabled"),
            "Services": (
                "SolarOverheadDistributor",
                "TimeToGoCalculator",
                "FroniusSmartmeterJSON",
                "MqttExporter",
                "FroniusWattpilot",
                "MqttTemperature",
                "NoBatToEV",
                "Shelly3EMGrid",
                "ShellyPMInverter",
                "MqttPVInverter",
            ),
        }

        for section, options in required_options.items():
            if (not self.config.has_section(section)):
                errors.append("missing mandatory [{0}] section".format(section))
                continue

            for option in options:
                if (not self.config.has_option(section, option)):
                    errors.append(
                        "missing mandatory [{0}] {1}".format(section, option)
                    )

        def integer(section, option):
            if (
                not self.config.has_section(section)
                or not self.config.has_option(section, option)
            ):
                return

            value = self.config[section][option]
            try:
                int(value)
            except (TypeError, ValueError):
                errors.append(
                    "[{0}] {1} must be an integer; got {2!r}".format(
                        section, option, value
                    )
                )

        def number(section, option):
            if (
                not self.config.has_section(section)
                or not self.config.has_option(section, option)
            ):
                return

            value = self.config[section][option]
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                errors.append(
                    "[{0}] {1} must be a number; got {2!r}".format(
                        section, option, value
                    )
                )
                return

            if (not math.isfinite(parsed)):
                errors.append(
                    "[{0}] {1} must be a finite number; got {2!r}".format(
                        section, option, value
                    )
                )

        def boolean(section, option):
            if (
                not self.config.has_section(section)
                or not self.config.has_option(section, option)
            ):
                return

            value = self.config[section][option]
            if value.lower() not in ("true", "false"):
                errors.append(
                    "[{0}] {1} must be a boolean; got {2!r}".format(
                        section, option, value
                    )
                )

        integer("Common", "NumberOfThreads")
        integer("Common", "ServiceMessageCount")
        number("Common", "DefaultPowerSetPoint")
        integer("Mqtt", "Port")
        if (self.config.has_option("Mqtt", "ThrottlePeriod")):
            integer("Mqtt", "ThrottlePeriod")

        boolean("Mqtt", "SslEnabled")
        boolean("Mqtt", "LocalSslEnabled")
        for option in required_options["Services"]:
            boolean("Services", option)

        if (
            self.config.has_section("Common")
            and self.config.has_option("Common", "LogLevel")
        ):
            log_level = self.config["Common"]["LogLevel"].upper()
            if log_level not in (
                "TRACE",
                "DEBUG",
                "APP_DEBUG",
                "INFO",
                "WARNING",
                "ERROR",
                "CRITICAL",
            ):
                errors.append(
                    "[Common] LogLevel must be a supported logging level; got {0!r}".format(
                        self.config["Common"]["LogLevel"]
                    )
                )

        if (errors):
            for error in errors:
                c(self, "Invalid bootstrap configuration: {0}".format(error))
            raise SystemExit(1)

    def _validateConfiguration(self):
        self.config = configparser.ConfigParser()
        self.config.optionxform = str
        config_path = "%s/config.ini" % (os.path.dirname(os.path.realpath(__file__)))

        try:
            loaded_paths = self.config.read(config_path)
        except (configparser.Error, OSError) as ex:
            c(self, "Invalid configuration: unable to read {0}: {1}".format(config_path, ex))
            raise SystemExit(1)

        if (not loaded_paths):
            c(self, "Invalid configuration: file was not found or could not be read: {0}".format(config_path))
            raise SystemExit(1)

        self._secureConfigPath(config_path)

        if (not self.config.has_section("Common")):
            c(self, "Invalid configuration: missing mandatory [Common] section")
            raise SystemExit(1)

        if (not self.config.has_option("Common", "ConfigVersion")):
            c(self, "Invalid configuration: missing mandatory [Common] ConfigVersion")
            raise SystemExit(1)

        raw_loaded_version = self.config["Common"]["ConfigVersion"]
        try:
            loadedVersion = int(raw_loaded_version)
        except (TypeError, ValueError):
            c(
                self,
                "Invalid configuration: [Common] ConfigVersion must be an integer; got {0!r}".format(
                    raw_loaded_version
                ),
            )
            raise SystemExit(1)

        #Version upgrades to be berformed. A User may skip versions during the upgrade process, so 
        #make sure each change is applied incrementally. 
        version = 2
        if (loadedVersion < version):
            self._backupConfig()
            i(self, "Upgrading configuration to v{0}".format(version))
            self.config["Common"]["ConfigVersion"] = "{0}".format(version)

            #Version 2 introduced Shelly3EMGrid and ShellyPMInverter
            self._setConfigDefault("Services", "Shelly3EMGrid", "false")
            self._setConfigDefault("Services", "ShellyPMInverter", "false")
            
        version = 3
        if (loadedVersion < version):
            self._backupConfig()
            i(self, "Upgrading configuration to v{0}".format(version))
            self.config["Common"]["ConfigVersion"] = "{0}".format(version)

            #Strategy of SolarOverheadDistributor is obsolete.
            self.config.remove_option("SolarOverheadDistributor", "Strategy")

        version = 4
        if (loadedVersion < version):
            self._backupConfig()
            i(self, "Upgrading configuration to v{0}".format(version))
            self.config["Common"]["ConfigVersion"] = "{0}".format(version)

            #Introducing MqttDC
            #Create Service Control Flag, individual Entries are to be created by user.
            self._setConfigDefault("Services", "MqttDC", "false")

        version = 5
        if (loadedVersion < version):
            self._backupConfig()
            i(self, "Upgrading configuration to v{0}".format(version))
            self.config["Common"]["ConfigVersion"] = "{0}".format(version)

            #Introducing Awattar Charging for Wattpilot. 
            # gone, not required. 
        
        version = 6
        if (loadedVersion < version):
            self._backupConfig()
            i(self, "Upgrading configuration to v{0}".format(version))
            self.config["Common"]["ConfigVersion"] = "{0}".format(version)

            #Introducing MqttPVInverter
            self._setConfigDefault("Services", "MqttPVInverter", "false")    

        version = 7
        if (loadedVersion < version):
            self._backupConfig()
            i(self, "Upgrading configuration to v{0}".format(version))
            self.config["Common"]["ConfigVersion"] = "{0}".format(version)

            #Relay as toggle for NoBatToEv
            self._setConfigDefault("NoBatToEV", "UseRelay", "-1")        
        
        version = 8
        if (loadedVersion < version):
            self._backupConfig()
            i(self, "Upgrading configuration to v{0}".format(version))
            self.config["Common"]["ConfigVersion"] = "{0}".format(version)

            #MqttPVInverter DTU Settings
            self._setConfigDefault("MqttPvInverter", "EnableZeroFeedin", "false")
            self._setConfigDefault("MqttPvInverter", "EnablePvShutdown", "false")
            self._setConfigDefault("MqttPvInverter", "ZeroFeedinScaleStep", "0.05")
            self._setConfigDefault("MqttPvInverter", "ZeroFeedinDistance", "50")
            self._setConfigDefault("MqttPvInverter", "ZeroFeedinStartSoc", "100")

        version = 9
        if (loadedVersion < version):
            self._backupConfig()
            i(self, "Upgrading configuration to v{0}".format(version))
            self.config["Common"]["ConfigVersion"] = "{0}".format(version)

            #Shared timeout for bounded HTTP consumer/device requests.
            self._setConfigDefault("Common", "HttpRequestTimeout", "5")

        version = 10
        if (loadedVersion < version):
            self._backupConfig()
            i(self, "Upgrading configuration to v{0}".format(version))
            self.config["Common"]["ConfigVersion"] = "{0}".format(version)

            #MinPhaseSwitchSeconds now owns stability timing in both phase
            #directions as well as the minimum phase-command interval.
            if (self.config.has_section("FroniusWattpilot")):
                self.config.remove_option(
                    "FroniusWattpilot", "PhaseSwitchDelaySeconds"
                )

        #All required configuration changes applied. Save new file, create a backup of the existing configuration. 
        if (loadedVersion < int(self.config["Common"]["ConfigVersion"])):
            config_path = "{0}/config.ini".format(os.path.dirname(os.path.realpath(__file__)))
            with open(config_path, 'w') as configfile:
                self.config.write(configfile)
            self._secureConfigPath(config_path)
            
        else:
            i(self, "Running on most recent configuration file version: v{0}".format(loadedVersion))

        self._validateConfigValues()

    def _backupConfig(self):
        i(self, "Creating configuration v{0} backup file.".format(self.config["Common"]["ConfigVersion"]))
        backup_path = "{0}/config.ini.v{1}.backup".format(os.path.dirname(os.path.realpath(__file__)), self.config["Common"]["ConfigVersion"])
        with open(backup_path, 'w') as configfile:
            self.config.write(configfile)
        self._secureConfigPath(backup_path)

    def _secureConfigPath(self, path):
        try:
            os.chmod(path, 0o600)
        except OSError as ex:
            c(self, "Unable to restrict configuration permissions for {0}: {1}".format(path, ex))
            raise SystemExit(1)

    def initialize(self):
       self.configureMqtt()

       Helper.waitTimeout(lambda: self.mainMqttClientConnected, 30) or e(self, "Unable to connect to main mqtt wthin 30 seconds...  offline or credentials wrong?")
       Helper.waitTimeout(lambda: self.localMqttClientConnected, 30) or e(self, "Unable to connect to wattpilot wthin 30 seconds...offline or credentials wrong?")

       self.publishServiceMessage(self, "es-ESS is starting up...")

       gobject.timeout_add(60000, self._signOfLive)
       
       self._initializeServices()

       #Finally, do some mqtt reports. 
       if (self.mqttThrottlePeriod > 0):
           self.publishMainMqtt("{0}/$SYS/MqttThrottle/Status".format(Globals.esEssTag), "Enabled")
           self.publishServiceMessage(self, "Enabling Mqtt-Throttling.")
       else:
           self.publishMainMqtt("{0}/$SYS/MqttThrottle/Status".format(Globals.esEssTag), "Disabled")

    def _initializeServices(self):
        try:
            #Create Classes, if enabled.
            self.publishServiceMessage(self, "Initializing Services.")

            self._checkAndEnable("SolarOverheadDistributor")
            self._checkAndEnable("TimeToGoCalculator")
            self._checkAndEnable("FroniusSmartmeterJSON")
            self._checkAndEnable("MqttExporter")
            self._checkAndEnable("FroniusWattpilot")
            self._checkAndEnable("MqttTemperature")
            self._checkAndEnable("NoBatToEV")
            self._checkAndEnable("Shelly3EMGrid")
            self._checkAndEnable("ShellyPMInverter")
            self._checkAndEnable("MqttPVInverter")
            
            #work in progress, but onhold.
            #self._checkAndEnable("Grid2Bat")
            #self._checkAndEnable("MqttDC")
            #self._checkAndEnable("ChargeCurrentReducer")
            #self._checkAndEnable("FroniusSmartmeterRS485")

            #Init DbusSubscriptions
            dbusSubStructure = {}
            dummy = {'code': None, 'whenToLog': 'configChange', 'accessLevel': None}
            for (name, service) in self._services.items():
                self.publishServiceMessage(service, "Initializing Dbus-Subscriptions.")
                i(self, "Initializing Dbus-Subscriptions for Service {0}".format(name))
                service.initDbusSubscriptions()

            #Init own subscriptions. 
            self.timezoneDbus = DbusSubscription(self, "com.victronenergy.settings", "/Settings/System/TimeZone", self._timeZoneChanged)
            self.registerDbusSubscription(self.timezoneDbus)

            #Translate subscriptions to dbus sub format.
            for (key, sublist) in self._dbusSubscriptions.items():
                for sub in sublist:
                    (self, "Creating Dbus-Subscriptions for Service {0} on {1} with callback: {2}".format(sub.requestingService.__class__.__name__, sub.valueKey, Helper.formatCallback(sub.callback)))
                
                    if (sub.commonServiceName not in dbusSubStructure):
                        dbusSubStructure[sub.commonServiceName] = {}

                    if (sub.dbusPath not in dbusSubStructure[sub.commonServiceName]):
                        dbusSubStructure[sub.commonServiceName][sub.dbusPath] = dummy
        
            #Ignore our own services, we don't need them to be scanned. 
            ignoreServices=["com.victronenergy.battery.esESS", 
                            "com.victronenergy.settings.esESS", 
                            "com.victronenergy.temperature.esESS",
                            "com.victronenergy.grid.esESS",
                            "com.victronenergy.pvinverter.esESS"]
        
            #Initialize dbus on a seperate thred, so our services currently initializing can
            #respond to service calls during monitoring.
            self._dbusMonitor = DbusMonitor(dbusSubStructure, self._dbusValueChanged, ignoreServices=ignoreServices)
    
            #now, that we have subscribed with some generic subscriptions, 
            #we need to elevate these subscriptions to device specific ones,
            #so the get_value command can be used with success.
            for (sn, instance) in self._dbusMonitor.get_service_list().items():
                for (key, sublist) in self._dbusSubscriptions.items():
                    for sub in sublist:
                        if (sn.startswith(sub.serviceName) and sn != sub.serviceName):
                            d(self, "Elevating {0} of Service {1} to {2}".format(sub.serviceName, sub.requestingService.__class__.__name__, sn))
                            sub.serviceName = sn
      
            #manualy fetch variables one time, then on change is sufficent.
            d(self, "Initializing dbus values for first-use.")
            for (key, sublist) in self._dbusSubscriptions.items():
                for sub in sublist:
                    v = self._dbusMonitor.get_value(
                        sub.serviceName,
                        sub.dbusPath,
                        getattr(sub, "initialValueDefault", 0),
                    )
                    sub.value = v
                    d(self, "{0}{1}: Value is: {2}".format(sub.serviceName, sub.dbusPath, v))
              
                    #process callbacks, if any.
                    if (sub.callback is not None):
                        sub.callback(sub)
        
            d(self, "Dbusmonitor initalized.")

            #Init DbusServices of each Service.
            for (name, service) in self._services.items():
                i(self, "Initializing Dbus-Service for Service {0}".format(name))
                self.publishServiceMessage(service, "Initializing Dbus-Service.")
                service.initDbusService()

            for (name, service) in self._services.items():
                i(self, "Initializing Mqtt-Subscriptions for Service {0}".format(name))
                self.publishServiceMessage(service, "Initializing Mqtt-Subscriptions.")
                service.initMqttSubscriptions()               

            for (name, service) in self._services.items():
                service.initWorkerThreads()             

            #own worker threads.
            self.registerWorkerThread(WorkerThread(self, self._manageGridSetPoint, 5000, False))
      
            #Last round for every service to do some stuff :0)
            for (name, service) in self._services.items():
                d(self, "Finalizing service {0}".format(name))
                self.publishServiceMessage(service, "Initializing finished.")
                service.initFinalize()

            i(Globals.esEssTag, "Initialization completed. " + Globals.esEssTag + " (" + Globals.currentVersionString + ") is up and running.")
            self.publishServiceMessage(self, "Initializing finished.")

        except Exception as ex:
            c(self, "Exception", exc_info=ex)
    
    def _timeZoneChanged(self, sub):
        self.publishServiceMessage(self, "Timezone detected as '{0}'".format(sub.value))
        Globals.userTimezone = sub.value

    def _reportFutureException(self, future, operation):
        try:
            exception = future.exception()
            if exception is not None:
                c(self, "Exception in asynchronous operation {0}".format(operation), exc_info=exception)
        except Exception as ex:
            c(self, "Unable to inspect asynchronous operation {0}".format(operation), exc_info=ex)

    def _submitTrackedFuture(self, callback, *args):
        operation = Helper.formatCallback(callback)
        future = self.threadPool.submit(callback, *args)
        future.add_done_callback(
            lambda completedFuture: self._reportFutureException(completedFuture, operation)
        )
        return future

    def _dbusValueChanged(self, dbusServiceName, dbusPath, dict, changes, deviceInstance):
        try:
            key = DbusSubscription.buildValueKey(dbusServiceName, dbusPath)

            if key in self._dbusSubscriptions:
                for sub in self._dbusSubscriptions[key]:
                    #verify serviceinstance. if the subscription is to the more global
                    #servicename, we are fine with it.
                    if (dbusServiceName.startswith(sub.serviceName)):
                        sub.value = changes["Value"]

                        if (sub.callback is not None):
                            self._submitTrackedFuture(sub.callback, sub)

        except Exception as ex:
            c(self, "Exception", exc_info=ex)

    def publishDbusValue(self, sub:DbusSubscription, value):
        d(self, "Exporting dbus value: {0}{1} => {2}".format(sub.serviceName, sub.dbusPath, value))
        self._dbusMonitor.set_value(sub.serviceName, sub.dbusPath, value)
    
    def _runThread(self, workerThread: WorkerThread):
        try:
            if (self._sigTermInvoked):
                return False
        
            t(self, "Running thread: {0}".format(Helper.formatCallback(workerThread.thread)))
            if (workerThread.future is None or workerThread.future.done()):
                self._threadExecutionsMinute += 1
                workerThread.future = self._submitTrackedFuture(workerThread.thread)
            else:
                w(self, "Thread {0} from {1} is scheduled to run every {2}ms - Future not done, skipping call attempt. Consider lowering the execution-frequency".format(workerThread.thread.__name__,workerThread.service.__class__.__name__, workerThread.interval))
        
            if (workerThread.onlyOnce):
                return False
        
            return True
        
        except Exception as ex:
            c(self, "Exception", exc_info=ex)
            return not workerThread.onlyOnce
    
    def _signOfLive(self):
        self.publishServiceMessage(self, "Executed {0} threads in the past minute.".format(self._threadExecutionsMinute))
        i(self, "Executed {0} threads in the past minute.".format(self._threadExecutionsMinute))
        load1, load5, load15 = os.getloadavg()

        self.publishMainMqtt("{0}/$SYS/Load/1".format(Globals.esEssTag), load1, 0, False, True)
        self.publishMainMqtt("{0}/$SYS/Load/5".format(Globals.esEssTag), load5, 0, False, True)
        self.publishMainMqtt("{0}/$SYS/Load/15".format(Globals.esEssTag), load15, 0, False, True)

        self._threadExecutionsMinute = 0

        for service in self._services.values():
            service.signOfLive()

        return True
    
    def _manageGridSetPoint(self):
        try:
            if (self._sigTermInvoked):
                return
            
            gsp = self._gridSetPointDefault

            with self._gridSetPointRequestsLock:
                gridSetPointRequests = list(self._gridSetPointRequests.items())

            for (k,v) in gridSetPointRequests:
                if (v is not None):
                    d(self, "Grid Set Point request of {0} is {1}".format(k,v))
                    gsp += v
            
            #only publish, if there is a change in current GSP.
            if (gsp != self._gridSetPointCurrent):
                d(self, "Combined all GSP-Requests, new GSP is: {0}".format(gsp))
                self._gridSetPointCurrent = gsp
                self.publishLocalMqtt("W/{0}/settings/0/Settings/CGwacs/AcPowerSetPoint".format(self.config["Common"]["VRMPortalID"]), "{\"value\": " + str(gsp) + "}", 1 ,False)

        except Exception as ex:
            c(self, "Exception in grid set point control. Trying to restore default GSP.", exc_info=ex)

            #exception is bad, try to set default gsp. 
            self.publishLocalMqtt("W/{0}/settings/0/Settings/CGwacs/AcPowerSetPoint".format(self.config["Common"]["VRMPortalID"]), "{\"value\": " + str(self._gridSetPointDefault) + "}", 1 ,False)


    def registerDbusSubscription(self, sub:DbusSubscription):
        if (sub.valueKey not in self._dbusSubscriptions):
            self._dbusSubscriptions[sub.valueKey] = []
       
        self._dbusSubscriptions[sub.valueKey].append(sub)

    def registerGridSetPointRequest(self, service:esESSService, request:float):
        with self._gridSetPointRequestsLock:
            self._gridSetPointRequests[service.__class__.__name__] = request
    
    def revokeGridSetPointRequest(self, service:esESSService):
        self.registerGridSetPointRequest(service, None)
    
    def registerMqttSubscription(self, sub:MqttSubscription):
        if (sub.valueKey not in self._mqttSubscriptions):
            self._mqttSubscriptions[sub.valueKey] = []
       
        self._mqttSubscriptions[sub.valueKey].append(sub)

        d(self, "Creating Mqtt-Subscriptions for Service {0} on {1} with callback: {2}".format(sub.requestingService.__class__.__name__, sub.topic, Helper.formatCallback(sub.callback)))
        if (sub.type == MqttSubscriptionType.Main):
            self.mainMqttClient.subscribe(sub.topic, sub.qos)
            self.mainMqttClient.message_callback_add(sub.topic, sub.callback)
        elif (sub.type == MqttSubscriptionType.Local):
            self.localMqttClient.subscribe(sub.topic, sub.qos)
            self.localMqttClient.message_callback_add(sub.topic, sub.callback)

    def registerWorkerThread(self, t:WorkerThread):
        i(self, "Scheduling Workerthread {0}".format(Helper.formatCallback(t.thread)))
        self.publishServiceMessage(t.service, "Initializing Worker Thread: {0}".format(Helper.formatCallback(t.thread)))
        gobject.timeout_add(t.interval, self._runThread, t)

    def publishMainMqtt(self, topic, payload, qos=0, retain=False, forceSend=False):
        
        if (self.mqttThrottlePeriod == 0 or forceSend): 
            self.mainMqttClient.publish(topic, payload, qos, retain)
        else:
           self._messageCount += 1
           #If 2 messages for the same topic are to be published, 
           #delay the second message upto {ThrotllePeriod} milliseconds.
           #replace content as new messages arrive before sending.
           with self._mainMqttThrottleDictLock: 
            if (topic in self._mainMqttThrottleDict):
                self._mainMqttThrottleDict[topic] = (self._mainMqttThrottleDict[topic][0], payload, qos, retain)
            else:
                self._mainMqttThrottleDict[topic] = (time.time(), None, None, None)
                self.mainMqttClient.publish(topic, payload, qos, retain)
                self._sendCount +=1
           
            n = time.time()
            known = 0
            throttled = 0
            for (topic, q) in self._mainMqttThrottleDict.items():
                known +=1
                if (q[0] + self.mqttThrottlePeriod/1000 <= n and q[1] is not None):
                    self.mainMqttClient.publish(topic, q[1], q[2], q[3])
                    self._mainMqttThrottleDict[topic] = (time.time(), None, None, None)
                    self._sendCount +=1
                else:
                   if (q[1] is not None):
                        throttled+=1
            
            if (self._lastThrottleLog + 1 < n):
               self._lastThrottleLog = n
               #i(self, "Throttle-State @{0}: {1} Topics known, {2} throttled, {3} M/s incoming, {4} M/s send!".format(n, known, throttled, self._messageCount, self._sendCount))
               self.publishMainMqtt("{0}/$SYS/MqttThrottle/Main/Time".format(Globals.esEssTag), n, 0, False, True)
               self.publishMainMqtt("{0}/$SYS/MqttThrottle/Main/KnownTopics".format(Globals.esEssTag), known, 0, False, True)
               self.publishMainMqtt("{0}/$SYS/MqttThrottle/Main/ThrottledTopics".format(Globals.esEssTag), throttled, 0, False, True)
               self.publishMainMqtt("{0}/$SYS/MqttThrottle/Main/MpsRequested".format(Globals.esEssTag), self._messageCount, 0, False, True)
               self.publishMainMqtt("{0}/$SYS/MqttThrottle/Main/MpsOutgoing".format(Globals.esEssTag), self._sendCount, 0, False, True)
               self._messageCount = 0
               self._sendCount = 0
    
    def publishLocalMqtt(self, topic, payload, qos=0, retain=False, forceSend=False):
        if (self.mqttThrottlePeriod == 0 or forceSend): 
            return self.localMqttClient.publish(topic, payload, qos, retain)
    
        else:
           self._localMessageCount += 1
           #If 2 messages for the same topic are to be published, 
           #delay the second message upto {ThrotllePeriod} milliseconds.
           #replace content as new messages arrive before sending.
           with self._localMqttThrottleDictLock: 
            if (topic in self._localMqttThrottleDict):
                self._localMqttThrottleDict[topic] = (self._localMqttThrottleDict[topic][0], payload, qos, retain)
            else:
                self._localMqttThrottleDict[topic] = (time.time(), None, None, None)
                self.localMqttClient.publish(topic, payload, qos, retain)
                self._localSendCount +=1
           
            n = time.time()
            known = 0
            throttled = 0
            for (topic, q) in self._localMqttThrottleDict.items():
                known +=1
                if (q[0] + self.mqttThrottlePeriod/1000 <= n and q[1] is not None):
                    self.localMqttClient.publish(topic, q[1], q[2], q[3])
                    self._localMqttThrottleDict[topic] = (time.time(), None, None, None)
                    self._localSendCount +=1
                else:
                   if (q[1] is not None):
                        throttled+=1
            
            if (self._lastLocalThrottleLog + 1 < n):
               self._lastLocalThrottleLog = n
               #i(self, "Throttle-State @{0}: {1} Topics known, {2} throttled, {3} M/s incoming, {4} M/s send!".format(n, known, throttled, self._localMessageCount, self._localSendCount))
               self.publishMainMqtt("{0}/$SYS/MqttThrottle/Local/Time".format(Globals.esEssTag), n, 0, False, True)
               self.publishMainMqtt("{0}/$SYS/MqttThrottle/Local/KnownTopics".format(Globals.esEssTag), known, 0, False, True)
               self.publishMainMqtt("{0}/$SYS/MqttThrottle/Local/ThrottledTopics".format(Globals.esEssTag), throttled, 0, False, True)
               self.publishMainMqtt("{0}/$SYS/MqttThrottle/Local/MpsRequested".format(Globals.esEssTag), self._localMessageCount, 0, False, True)
               self.publishMainMqtt("{0}/$SYS/MqttThrottle/Local/MpsOutgoing".format(Globals.esEssTag), self._localSendCount, 0, False, True)
               self._localMessageCount = 0
               self._localSendCount = 0

        return None

    def _waitForMqttPublish(self, publish_result, timeout_seconds):
        if publish_result is None:
            w(self, "MQTT publish did not return a completion handle; continuing shutdown.")
            return False

        wait_for_publish = getattr(publish_result, "wait_for_publish", None)
        if not callable(wait_for_publish):
            w(self, "MQTT publish completion cannot be awaited; continuing shutdown.")
            return False

        try:
            wait_for_publish(timeout_seconds)
            is_published = getattr(publish_result, "is_published", None)
            if callable(is_published) and not is_published():
                w(
                    self,
                    "MQTT publish was not confirmed within {0:.1f}s; continuing shutdown.".format(
                        timeout_seconds
                    ),
                )
                return False
            return True
        except (RuntimeError, TypeError, ValueError) as ex:
            w(self, "Unable to confirm MQTT publish before shutdown: {0}".format(ex))
            return False

    def _isMqttClientConnected(self, client):
        if (client is None):
            return False

        isConnected = getattr(client, "is_connected", False)
        if (callable(isConnected)):
            return isConnected()

        return bool(isConnected)

    def publishServiceMessage(self, service, message, type=Globals.ServiceMessageType.Operational):
        if (not self._isMqttClientConnected(self.mainMqttClient)):
           #cant send service messages by now. 
           return

        serviceName = service.__class__.__name__ if not isinstance(service, str) else service
        serviceName = serviceName if not isinstance(service, esESS) else "$SYS"
        serviceName = "$SYS" if serviceName=="esESS" else serviceName

        key = "{0}{1}".format(serviceName, type)
        if (key not in self._serviceMessageIndex):
           self._serviceMessageIndex[key] = 1
        else:
           self._serviceMessageIndex[key] +=1
        
        if (self._serviceMessageIndex[key] > int(self.config["Common"]["ServiceMessageCount"]) + 1):
           self._serviceMessageIndex[key] = 1

        if (type == Globals.ServiceMessageType.Operational):
            d(self, "ServiceMessage: {0}".format(message))

        self.publishMainMqtt("{tag}/{service}/ServiceMessages/{type}/Message{id:02d}".format(tag=Globals.esEssTag, service=serviceName, type=type, id=self._serviceMessageIndex[key]), "{0} | {1}".format(Globals.getUserTime(), message) , 0, True, True)
        nextOne = self._serviceMessageIndex[key] +1
        if (nextOne > int(self.config["Common"]["ServiceMessageCount"]) + 1):
            nextOne = 1

    def handleSigterm(self, signum, frame):
        if (self._sigTermInvoked):
            i(self, "Shutdown already in progress.")
            return

        # Set this before any cleanup so a repeated signal cannot re-enter it.
        self._sigTermInvoked=True
        self.publishServiceMessage(self, "SIGTERM received. Shuting down services gracefully.")

        #restore default grid set point
        i(self, "Restoring default power set point of {0}W due to SIGTERM received.".format(self._gridSetPointDefault))
        restore_publish = self.publishLocalMqtt(
            "W/{0}/settings/0/Settings/CGwacs/AcPowerSetPoint".format(
                self.config["Common"]["VRMPortalID"]
            ),
            "{\"value\": " + str(self._gridSetPointDefault) + "}",
            1,
            False,
            True,
        )
        self._waitForMqttPublish(
            restore_publish,
            self._shutdownPublishTimeoutSeconds,
        )

        #unsubscribe any mqtt sub, so we no longer receive new messages. 
        for sublist in self._mqttSubscriptions.values():
            for sub in sublist:
                d(self, "Unsubscribing from Mqtt-Subscriptions for Service {0} on {1} with callback: {2}".format(sub.requestingService.__class__.__name__, sub.topic, Helper.formatCallback(sub.callback)))
                if (sub.type == MqttSubscriptionType.Main):
                    self.mainMqttClient.unsubscribe(sub.topic)
                elif (sub.type == MqttSubscriptionType.Local):
                    self.localMqttClient.unsubscribe(sub.topic)
        
        #dbusmonitor has no disconnect method, so we just stop forwarding the messages in the global handler.

        #tell each service to clean up as well.
        for service in self._services.values():
           try:
               service.handleSigterm()
           except Exception as ex:
               c(self, "Exception during handleSigTerm on service {0}".format(service.__class__.__name__), exc_info=ex)
           i(self, "Service {0} is in safe exit state.".format(service.__class__.__name__))

        #finally, clean up internally.
        #disconnect from mqtts
        self.mainMqttClient.reconnect = False
        self.localMqttClient.reconnect = False
        self._logShutdownMqttDisconnect("Main")
        self._logShutdownMqttDisconnect("Local")
        self.mainMqttClient.disconnect()
        self.localMqttClient.disconnect()   

        i(self, "Cleaned up. Bye.")
        self._terminateProcess()

    def _terminateProcess(self):
        # SystemExit can be swallowed by a D-Bus callback dispatcher. Flush all
        # handlers after cleanup, then terminate without Python stack unwinding.
        logging.shutdown()
        os._exit(0)

def configureLogging(config):

  logDir = "/data/log/es-ESS"
  
  if not os.path.exists(logDir):
    os.mkdir(logDir)

  logLevelTrace = 9
  logLevelApp = 11

  def trace(msg, **kwargs):
     if logging.getLogger().isEnabledFor(logLevelTrace):
        logging.log(logLevelTrace, msg, **kwargs)

  def appDebug(msg, **kwargs):
     if logging.getLogger().isEnabledFor(logLevelApp):
        logging.log(logLevelApp, msg, **kwargs)
  
  logging.addLevelName(logLevelTrace, "TRACE")
  logging.addLevelName(logLevelApp, "APP_DEBUG")

  logging.appDebug = appDebug
  logging.Logger.appDebug = appDebug

  logging.trace = trace
  logging.Logger.trace = trace

  logLevelString = config.get("Common", "LogLevel", fallback="INFO").upper()
  if logLevelString not in (
      "TRACE",
      "DEBUG",
      "APP_DEBUG",
      "INFO",
      "WARNING",
      "ERROR",
      "CRITICAL",
  ):
      logLevelString = "INFO"
  logLevel = logging.getLevelName(logLevelString)

  logging.basicConfig(format='%(asctime)s,%(msecs)d %(levelname)s %(message)s',
                      datefmt='%Y-%m-%d %H:%M:%S',
                      level=logLevel,
                      handlers=[
                        TimedRotatingFileHandler(logDir + "/current.log", when="midnight", interval=1, backupCount=14),
                        logging.StreamHandler()
                      ])
  

  import Helper
  #persist some log flags.
  

def main(config):
  # This check must run before constructing esESS: construction and
  # initialization can start MQTT clients, services, and grid-setpoint writes.
  detectedVenusVersion = RuntimeCompatibility.require_validated_venus_os()
  i(
      "Main",
      "Validated Venus OS compatibility baseline confirmed: {0}.".format(
          detectedVenusVersion
      ),
  )

  try:
      # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
      from dbus.mainloop.glib import DBusGMainLoop # type: ignore
      DBusGMainLoop(set_as_default=True)

      i("Main", "-----------------------------------------------------------------------------------------")
      i("Main", "-----------------------------------------------------------------------------------------")
      i("Main", "-----------------------------------------------------------------------------------------")
           
      Globals.esESS = esESS()
      for sig in [signal.SIGTERM, signal.SIGINT]:
        signal.signal(sig, Globals.esESS.handleSigterm)

      Globals.esESS.initialize()

      mainloop = gobject.MainLoop()
      mainloop.run()            
  except Exception as e:
    c("Main", "Exception", exc_info=e)
    raise

if __name__ == "__main__":
  # read configuration. TODO: Migrate to UI-Based configuration later.
  config = configparser.ConfigParser()
  try:
    config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
  except (configparser.Error, OSError):
    # _validateConfiguration() emits the authoritative diagnostic after basic
    # fallback logging is available.
    config = configparser.ConfigParser()
  
  configureLogging(config)

  try:
    main(config)
  except RuntimeCompatibility.CompatibilityError as compatibilityException:
     c("COMPATIBILITY", str(compatibilityException))
     sys.exit(1)
  except Exception as uncoughtException:
     c("UNCOUGHT", "Uncought exception, main() dieded.", exc_info=uncoughtException)
     sys.exit(1)
