from enum import Enum
from typing import Dict
import Globals
from Helper import i, c, d, w, e
from abc import ABC, abstractmethod
from Globals import MqttSubscriptionType
from WattpilotRuntimeStatus import attach_runtime_status_reporter

#ServiceBase for all Service-Classes.
#Used to orchestrate initialization, dbus and mqtt handling in a central place.
#all relevant service-calls will be triggered by esESS during initialization.
class esESSService(ABC):
    def __init__(self):
        self.config = Globals.getConfig()
        # FroniusWattpilot owns the control loop. Attach an observer that
        # publishes the dedicated runtime-status contract without changing
        # controller commands or the VRM-compatible /Status path.
        attach_runtime_status_reporter(self)

    @abstractmethod
    def initDbusService(self):
        pass

    @abstractmethod
    def initDbusSubscriptions(self):
        pass

    def registerDbusSubscription(
        self, serviceName, dbusPath, callback=None, initialValueDefault=0
    ):
        sub = DbusSubscription(
            self, serviceName, dbusPath, callback, initialValueDefault
        )
        Globals.esESS.registerDbusSubscription(sub)
        return sub

    @abstractmethod
    def initMqttSubscriptions(self):
        pass

    def registerMqttSubscription(self, topic, qos=0, type=MqttSubscriptionType.Main, callback=None):
        if (topic is not None and topic != ""):
            sub = MqttSubscription(self, topic, qos, type, callback)
            Globals.esESS.registerMqttSubscription(sub)
            return sub
        return None

    @abstractmethod
    def initWorkerThreads(self):
        pass

    def registerWorkerThread(self, thread, interval):
        wt = WorkerThread(self, thread, interval, False)
        Globals.esESS.registerWorkerThread(wt)
        return wt

    def registerSingleThread(self, thread, interval):
        wt = WorkerThread(self, thread, interval, True)
        Globals.esESS.registerWorkerThread(wt)
        return wt

    @abstractmethod
    def initFinalize(self):
        pass

    @abstractmethod
    def handleSigterm(self):
        pass

    @abstractmethod
    def signOfLive(self):
        pass

    def publishMainMqtt(self, topic, payload, qos=0, retain=False):
        Globals.esESS.publishMainMqtt(topic, payload, qos, retain)

    def publishLocalMqtt(self, topic, payload, qos=0, retain=False):
        Globals.esESS.publishLocalMqtt(topic, payload, qos, retain)

    def publishServiceMessage(self, service, message, type=Globals.ServiceMessageType.Operational):
        Globals.esESS.publishServiceMessage(service, message, type)

    def registerGridSetPointRequest(self, request:float):
        Globals.esESS.registerGridSetPointRequest(self, request)

    def revokeGridSetPointRequest(self):
        Globals.esESS.registerGridSetPointRequest(self, None)

class WorkerThread:
    def __init__(self, service, thread, interval, onlyOnce):
        self.thread = thread
        self.interval = interval
        self.future = None
        self.service = service
        self.onlyOnce = onlyOnce

class DbusSubscription:
    def buildValueKey(serviceName, dbusPath):
        return "{0}{1}".format(".".join(serviceName.split('.')[:3]), dbusPath)

    def __init__(
        self,
        requestingService,
        serviceName,
        dbusPath,
        callback=None,
        initialValueDefault=0,
    ):
        self.commonServiceName = ".".join(serviceName.split('.')[:3])
        self.serviceName = serviceName
        self.dbusPath = dbusPath
        self.callback = callback
        self.initialValueDefault = initialValueDefault
        self.value = None
        self.requestingService = requestingService

    @property
    def valueKey(self):
        return DbusSubscription.buildValueKey(self.serviceName, self.dbusPath)

class MqttSubscription:
    def buildValueKey(type, topic):
        return "{0}{1}".format(type, topic)

    def __init__(self, requestingService, topic, qos=0, type=MqttSubscriptionType.Main, callback=None):
        self.topic = topic
        self.qos = qos
        self.type = type
        self.callback = callback
        self.value = None
        self.requestingService = requestingService

    @property
    def valueKey(self):
        return MqttSubscription.buildValueKey(self.type, self.topic)
