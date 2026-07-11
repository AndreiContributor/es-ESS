import configparser
from datetime import datetime
from enum import Enum
import os
import re
import subprocess
from Helper import d,w,e,i,t
#superglobals
esEssTag = "es-ESS"
esEssTagService = "esESS"
currentVersion = "26.01.07"
currentVersionString="{0} {1} beta".format(esEssTag, currentVersion)

#will be updated at startup
userTimezone = "UTC"

#RootService
esESS = None

#Enums
ServiceMessageType = Enum('ServiceMessageType', ['Operational', 'Critical', 'Error', 'Warning'])
MqttSubscriptionType = Enum('MqttSubscriptionType', ['Main', 'Local'])
_USER_TIMEZONE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./+-]*$")


def _validateUserTimezone(timezone):
   if (not isinstance(timezone, str) or _USER_TIMEZONE_PATTERN.fullmatch(timezone) is None):
      raise ValueError("Invalid configured timezone: {0}".format(timezone))

   return timezone

def getUserTime():
   timezone = _validateUserTimezone(userTimezone)
   environment = os.environ.copy()
   environment["TZ"] = ":" + timezone
   result = subprocess.run(
      ["date", "+%Y-%m-%d %H:%M:%S"],
      env=environment,
      capture_output=True,
      text=True,
      timeout=3,
   )
   usertime = result.stdout
   #d("Globals", "User time is: {0}".format(usertime))
   return usertime.strip()

#defs
def getConfig():
   config = configparser.ConfigParser()
   config.optionxform = str
   config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))

   return config
