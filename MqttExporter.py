from enum import Enum
import os
import sys
from typing import Dict
import dbus # type: ignore
import dbus.service # type: ignore
import inspect
import pprint
import os
import sys

# esEss imports
from Helper import i, c, d, w, e
import Globals
from esESSService import esESSService

class PublishType(int, Enum):
    ONCHANGE = 0
    INTERVAL_1S = 1
    INTERVAL_10S = 2
    INTERVAL_60S = 3

class MqttExporter(esESSService):
    def __init__(self):
        esESSService.__init__(self)
        self.topicExports: Dict[str, TopicExport] = {}
        self.topicExports_1s: Dict[str, TopicExport] = {}
        self.topicExports_10s: Dict[str, TopicExport] = {}
        self.topicExports_60s: Dict[str, TopicExport] = {}
        self.forwardedTopicsPastMinute = 0
        
        #Load all topics we should export from DBus to Mqtt and start listening for changes.
        #upon change, export according to the setup rules. 
        try:
            d(self, "Scanning config for export requests")

            for k in self.config.sections():
                if (k.startswith("MqttExporter:")):
                    service = self.config[k]["Service"]
                    dbuskey = self.config[k]["DbusKey"]
                    mqttTopic = self.config[k]["MqttTopic"] 
                    # publishType is string or absent, default to ONCHANGE.
                    # Parse to enum, while reading.
                    publishType = PublishType[self.config[k].get("PublishType", "ONCHANGE")]
                    key = service + dbuskey
                    self.topicExports[key] = TopicExport(service, dbuskey, mqttTopic, publishType)

                    #additionally reference in the interval based dicts for faster access.
                    if publishType == PublishType.INTERVAL_1S:
                        self.topicExports_1s[key] = self.topicExports[key]
                    elif publishType == PublishType.INTERVAL_10S:
                        self.topicExports_10s[key] = self.topicExports[key]
                    elif publishType == PublishType.INTERVAL_60S:
                        self.topicExports_60s[key] = self.topicExports[key]

            i(self, "Found {0} export requests.".format(len(self.topicExports)))
            
        except Exception as ex:
            c(self, "Exception", exc_info=ex)

    def initDbusService(self):
        pass

    def initDbusSubscriptions(self):
        for topicExport in self.topicExports.values():
            #FIXME: We can already distinguish here between comon service and full service.
            #       that would allow us to make two value change handlers that are more efficient.
            self.registerDbusSubscription(topicExport.service, topicExport.source, self._dbusValueChanged)
        
    def initWorkerThreads(self):
        self.registerWorkerThread(self.process_1s_interval, 1 * 1000)
        self.registerWorkerThread(self.process_10s_interval, 10 * 1000)
        self.registerWorkerThread(self.process_60s_interval, 60 * 1000)

    def initMqttSubscriptions(self):
        pass

    def signOfLive(self):
        i(self, "Forwarded {0} Dbus-Messages in the past minute.".format(self.forwardedTopicsPastMinute))
        self.publishServiceMessage(self, "Forwarded {0} Dbus-Messages in the past minute.".format(self.forwardedTopicsPastMinute))
        self.forwardedTopicsPastMinute = 0

    def initFinalize(self):
        pass

    def _dbusValueChanged(self, sub):
        key = "{0}{1}".format(sub.serviceName, sub.dbusPath)
        if key in self.topicExports:
            self.topicExports[key].value = sub.value # Update stored value
            if self.topicExports[key].publishType == PublishType.ONCHANGE:
                self.publishMainMqtt(self.topicExports[key].target, sub.value, 0, True)
                self.forwardedTopicsPastMinute += 1
        else:
            key = "{0}{1}".format(sub.commonServiceName, sub.dbusPath)

            if key in self.topicExports:
                self.topicExports[key].value = sub.value # Update stored value
                if self.topicExports[key].publishType == PublishType.ONCHANGE:
                    self.publishMainMqtt(self.topicExports[key].target, sub.value, 0, True)
                    self.forwardedTopicsPastMinute += 1

    def handleSigterm(self):
       pass

    def process_1s_interval(self):
        for topicExport in self.topicExports_1s.values():
            value = topicExport.value
            if value is not None:
                self.publishMainMqtt(topicExport.target, value, 0, True)
                self.forwardedTopicsPastMinute += 1
    
    def process_10s_interval(self):
        for topicExport in self.topicExports_10s.values():
            value = topicExport.value
            if value is not None:
                self.publishMainMqtt(topicExport.target, value, 0, True)
                self.forwardedTopicsPastMinute += 1
    
    def process_60s_interval(self):
        for topicExport in self.topicExports_60s.values():
            value = topicExport.value
            if value is not None:
                self.publishMainMqtt(topicExport.target, value, 0, True)
                self.forwardedTopicsPastMinute += 1

class TopicExport:
    def __init__(self, service, source, target, publishType=PublishType.ONCHANGE):
        self.commonService = ".".join(service.split('.')[:3])
        self.service = service
        self.source = source
        self.publishType = publishType
        self.value = None
        if (target.endswith("*")):
            self.target = target.replace('*', '') + source
        else:
            self.target = target
