import os
import platform
import sys
from typing import Dict
import dbus # type: ignore
import dbus.service # type: ignore
import inspect
import pprint
import math
import tempfile
from time import time
import requests # type: ignore
import os
import sys

# victron
sys.path.insert(1, '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python')
from vedbus import VeDbusService # type: ignore

# esEss imports
from Helper import i, c, d, w, e, t, dbusConnection
import Globals
from esESSService import esESSService

class Shelly3EMGrid(esESSService):
    def __init__(self):
        esESSService.__init__(self)
        self.vrmInstanceID = self.config["Shelly3EMGrid"]["VRMInstanceID"]
        self.customName = self.config["Shelly3EMGrid"]["CustomName"]
        self.pollFrequencyMs = int(self.config["Shelly3EMGrid"]["PollFrequencyMs"])
        self.shellyUsername = self.config["Shelly3EMGrid"]["Username"]
        self.shellyPassword = self.config["Shelly3EMGrid"]["Password"]
        self.shellyHost = self.config["Shelly3EMGrid"]["Host"]
        self.metering = self.config["Shelly3EMGrid"]["Metering"]
        self.connectionErrors = 0
        self.energyForwarded = 0
        self.energyReversed = 0
        self.lastMeasurement = time()

        if (self.metering == "Net"):
            self.energyForwarded = self._loadCounter("energyForwarded3EM")
            self.energyReversed = self._loadCounter("energyReversed3EM")

    def _runtimeDataPath(self):
        return os.path.join(
            os.path.dirname(os.path.realpath(__file__)), "runtimeData"
        )

    def _counterPath(self, filename):
        return os.path.join(self._runtimeDataPath(), filename)

    def _loadCounter(self, filename):
        path = self._counterPath(filename)
        if not os.path.isfile(path):
            return 0

        try:
            with open(path, "r") as counter_file:
                value = float(counter_file.read().strip())
            if not math.isfinite(value) or value < 0:
                raise ValueError("counter must be a finite non-negative number")
            i(self, "Read stored counter {0}={1}".format(filename, value))
            return value
        except (OSError, TypeError, ValueError) as ex:
            w(
                self,
                "Ignoring invalid stored Shelly counter {0}: {1}. Starting at 0.".format(
                    path, ex
                ),
            )
            return 0

    def initDbusService(self):
        self.serviceType = "com.victronenergy.grid"
        self.serviceName = self.serviceType + "." + Globals.esEssTagService + "_Shelly3EMGrid"
        self.dbusService = VeDbusService(self.serviceName, bus=dbusConnection(), register=False)
        self.publishServiceMessage(self, "Initializing dbus-service")
        
        #Mgmt-Infos
        self.dbusService.add_path('/DeviceInstance', int(self.vrmInstanceID))
        self.dbusService.add_path('/Mgmt/ProcessName', __file__)
        self.dbusService.add_path('/Mgmt/ProcessVersion', Globals.currentVersionString + ' on Python ' + platform.python_version())
        self.dbusService.add_path('/Mgmt/Connection', "dbus")

        # Create the mandatory objects
        self.dbusService.add_path('/ProductId', 45069)
        self.dbusService.add_path('/DeviceType', 345) 
        self.dbusService.add_path('/Role', "grid")
        self.dbusService.add_path('/Position', 0) 
        self.dbusService.add_path('/ProductName', "{0} Shelly3EMGrid".format(Globals.esEssTag)) 
        self.dbusService.add_path('/Latency', None)    
        self.dbusService.add_path('/FirmwareVersion', Globals.currentVersionString)
        self.dbusService.add_path('/HardwareVersion', Globals.currentVersionString)
        self.dbusService.add_path('/Connected', 1)
        self.dbusService.add_path('/Serial', "1337")
        self.dbusService.add_path('/CustomName', self.customName)

        #grid props
        self.dbusService.add_path('/Ac/Power', None)
        self.dbusService.add_path('/Ac/L1/Voltage', None)
        self.dbusService.add_path('/Ac/L2/Voltage', None)
        self.dbusService.add_path('/Ac/L3/Voltage', None)
        self.dbusService.add_path('/Ac/L1/Current', None)
        self.dbusService.add_path('/Ac/L2/Current', None)
        self.dbusService.add_path('/Ac/L3/Current', None)
        self.dbusService.add_path('/Ac/L1/Power', None)
        self.dbusService.add_path('/Ac/L2/Power', None)
        self.dbusService.add_path('/Ac/L3/Power', None)
        self.dbusService.add_path('/Ac/L1/Energy/Forward', None)
        self.dbusService.add_path('/Ac/L2/Energy/Forward', None)
        self.dbusService.add_path('/Ac/L3/Energy/Forward', None)
        self.dbusService.add_path('/Ac/L1/Energy/Reverse', None)
        self.dbusService.add_path('/Ac/L2/Energy/Reverse', None)
        self.dbusService.add_path('/Ac/L3/Energy/Reverse', None)
        self.dbusService.add_path('/Ac/Energy/Forward', None)
        self.dbusService.add_path('/Ac/Energy/Reverse', None)

        self.dbusService.register()

    def initDbusSubscriptions(self):
        pass
        
    def signOfLive(self):
        pass
    
    def initWorkerThreads(self):
        self.registerWorkerThread(self.queryShelly, self.pollFrequencyMs)

        if (self.metering == "Net"):
            self.registerWorkerThread(self.persistCounters, 5 * 60 * 1000);

    def initMqttSubscriptions(self):
        pass

    def initFinalize(self):
        pass
    
    def handleSigterm(self):
       self.persistCounters()

    def queryShelly(self):
        measurementTime = time()
        try:
            URL = "http://%s:%s@%s/status" % (self.shellyUsername, self.shellyPassword, self.shellyHost)
            URL = URL.replace(":@", "")
            
            #timeout should be half the poll frequency, so there is time to process.
            meter_r = requests.get(url = URL, timeout=(self.pollFrequencyMs/2000))
            meter_data = meter_r.json()
            if not isinstance(meter_data, dict):
                raise ValueError("response is not a JSON object")
            emeters = meter_data['emeters']
            if not isinstance(emeters, list) or len(emeters) < 3:
                raise ValueError("emeters must contain three phases")

            # Resolve the fields used by this mode before publishing anything.
            total_power = meter_data['total_power']
            phase_values = [
                {
                    'voltage': emeters[index]['voltage'],
                    'current': emeters[index]['current'],
                    'power': emeters[index]['power'],
                }
                for index in range(3)
            ]
            if self.metering == "Default":
                for index in range(3):
                    phase_values[index]['total'] = emeters[index]['total']
                    phase_values[index]['total_returned'] = emeters[index]['total_returned']

            self.dbusService['/Connected'] = 1
            self.connectionErrors = 0

            #All good, evaluate and publish on dbus.
            self.dbusService['/Ac/Power'] = total_power
            self.dbusService['/Ac/L1/Voltage'] = phase_values[0]['voltage']
            self.dbusService['/Ac/L2/Voltage'] = phase_values[1]['voltage']
            self.dbusService['/Ac/L3/Voltage'] = phase_values[2]['voltage']
            self.dbusService['/Ac/L1/Current'] = phase_values[0]['current']
            self.dbusService['/Ac/L2/Current'] = phase_values[1]['current']
            self.dbusService['/Ac/L3/Current'] = phase_values[2]['current']
            self.dbusService['/Ac/L1/Power'] = phase_values[0]['power']
            self.dbusService['/Ac/L2/Power'] = phase_values[1]['power']
            self.dbusService['/Ac/L3/Power'] = phase_values[2]['power']

            if (self.metering == "Default"):
                self.dbusService['/Ac/L1/Energy/Forward'] = (phase_values[0]['total']/1000)
                self.dbusService['/Ac/L2/Energy/Forward'] = (phase_values[1]['total']/1000)
                self.dbusService['/Ac/L3/Energy/Forward'] = (phase_values[2]['total']/1000)
                self.dbusService['/Ac/L1/Energy/Reverse'] = (phase_values[0]['total_returned']/1000)
                self.dbusService['/Ac/L2/Energy/Reverse'] = (phase_values[1]['total_returned']/1000)
                self.dbusService['/Ac/L3/Energy/Reverse'] = (phase_values[2]['total_returned']/1000)

                self.dbusService['/Ac/Energy/Forward'] = sum(value['total'] for value in phase_values)/1000.0
                self.dbusService['/Ac/Energy/Reverse'] = sum(value['total_returned'] for value in phase_values)/1000.0
            else:
                #Net metering. We use our own counters and keep track of correct saldating.
                duration = max(0.0, measurementTime - self.lastMeasurement) * 1000.0

                if (total_power >=0):
                    #Consumption
                    self.energyForwarded += total_power * (duration/(3600.0*1000.0))
                else:
                    #FeedIn
                    self.energyReversed += (total_power * -1) * (duration/(3600.0*1000.0))

                self.dbusService['/Ac/L1/Energy/Forward'] = None
                self.dbusService['/Ac/L2/Energy/Forward'] = None
                self.dbusService['/Ac/L3/Energy/Forward'] = None
                self.dbusService['/Ac/L1/Energy/Reverse'] = None
                self.dbusService['/Ac/L2/Energy/Reverse'] = None
                self.dbusService['/Ac/L3/Energy/Reverse'] = None

                self.dbusService['/Ac/Energy/Forward'] = round(self.energyForwarded / 1000.0, 2)
                self.dbusService['/Ac/Energy/Reverse'] = round(self.energyReversed / 1000.0, 2)

                d(self, "Duration: {dur} -> Counters: F/R: {f}/{r}".format(f=self.energyForwarded, r=self.energyReversed, dur=duration))
        except requests.exceptions.Timeout as ex:
            w(self, "Shelly 3EM did not response fast enough to sustain a poll frequency of {0} ms. Please adjust. After 3 failures, null will be published.".format(self.pollFrequencyMs))
            self.connError()

        except requests.exceptions.RequestException as ex:
            w(self, "Shelly 3EM request failed: {0}".format(ex))
            self.connError()

        except (KeyError, IndexError, TypeError, ValueError) as ex:
            e(self, "Shelly 3EM returned an invalid or incomplete payload: {0}".format(ex))
            self.connError()
        
        except Exception as ex:
            c(self, "Exception", exc_info=ex)
        finally:
            if self.metering == "Net":
                # Never apply the next successful power sample across an
                # interval for which no measurement was available.
                self.lastMeasurement = measurementTime

    def connError(self):
        self.connectionErrors += 1
        if (self.connectionErrors > 3):
            e(self, "More than 3 consecutive failures. Assuming Meter disconnected.")
            self.publishNone()
    
    def publishNone(self):
        self.dbusService["/Connected"] = 0
        self.dbusService['/Ac/Power'] = None
        self.dbusService['/Ac/L1/Voltage'] = None
        self.dbusService['/Ac/L2/Voltage'] = None
        self.dbusService['/Ac/L3/Voltage'] = None
        self.dbusService['/Ac/L1/Current'] = None
        self.dbusService['/Ac/L2/Current'] = None
        self.dbusService['/Ac/L3/Current'] = None
        self.dbusService['/Ac/L1/Power'] = None
        self.dbusService['/Ac/L2/Power'] = None
        self.dbusService['/Ac/L3/Power'] = None

    def persistCounters(self):
        i(self, "Saving energy counters to disk. F/R: {0}/{1}".format(self.energyForwarded, self.energyReversed))

        self._persistCounter("energyForwarded3EM", self.energyForwarded)
        self._persistCounter("energyReversed3EM", self.energyReversed)

    def _persistCounter(self, filename, value):
        runtime_path = self._runtimeDataPath()
        target_path = self._counterPath(filename)
        temporary_path = None
        try:
            persisted_value = float(value)
            if not math.isfinite(persisted_value) or persisted_value < 0:
                raise ValueError("counter must be a finite non-negative number")
            os.makedirs(runtime_path, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=runtime_path,
                prefix=".{0}.".format(filename),
                delete=False,
            ) as counter_file:
                temporary_path = counter_file.name
                counter_file.write(str(value))
                counter_file.flush()
                os.fsync(counter_file.fileno())
            os.replace(temporary_path, target_path)
            temporary_path = None
            return True
        except (OSError, TypeError, ValueError) as ex:
            e(
                self,
                "Unable to persist Shelly counter {0}: {1}".format(
                    target_path, ex
                ),
            )
            return False
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass




