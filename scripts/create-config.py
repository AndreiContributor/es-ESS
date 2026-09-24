#!/usr/bin/env python3
"""Interactive, hardware-free config.ini generator for es-ESS."""

import argparse
import ast
import configparser
import getpass
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from datetime import datetime
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE = ROOT / "config.sample.ini"
DEFAULT_OUTPUT = ROOT / "config.ini"

ACTIVE_SERVICES = (
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
)

DORMANT_SERVICES = frozenset(
    ("ChargeCurrentReducer", "FroniusSmartmeterRS485", "Grid2Bat", "MqttDC")
)

SECTION_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class WizardCancelled(Exception):
    """Raised when the operator cancels the wizard."""


def _finite_number(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("enter a finite number")
    return parsed


def _integer(value):
    return int(value)


def _stringify(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _validate_identifier(value):
    if not SECTION_KEY_RE.fullmatch(value):
        raise ValueError(
            "use letters, numbers, '_' or '-', starting with a letter or number"
        )
    return value


def _validate_host(value):
    value = value.strip()
    if not value or "://" in value or "@" in value or "/" in value:
        raise ValueError(
            "enter a hostname or IP address without scheme, path, or credentials"
        )
    return value


def _validate_url(value):
    if "\\" in value:
        raise ValueError("enter a URL without backslashes")
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("enter a complete http:// or https:// URL with a host")
    return value


def _validate_regex(value, require_group=False):
    compiled = re.compile(value)
    if require_group and compiled.groups != 1:
        raise ValueError("the expression must contain exactly one capture group")
    return value


def _validate_battery_reservation_expression(value):
    """Accept the same small expression language documented by the service."""
    tree = ast.parse(value, mode="eval")
    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.UAdd,
        ast.USub,
        ast.Constant,
        ast.Name,
        ast.Call,
        ast.Load,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise ValueError(
                "use only numbers, SOC, min(), max(), parentheses, and + - * /"
            )
        if isinstance(node, ast.Name) and node.id not in ("SOC", "min", "max"):
            raise ValueError("the only supported variable is SOC")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in (
                "min",
                "max",
            ):
                raise ValueError("only min() and max() calls are supported")
            if node.keywords:
                raise ValueError("min() and max() keyword arguments are not supported")
        if isinstance(node, ast.Constant) and (
            isinstance(node.value, bool) or not isinstance(node.value, (int, float))
        ):
            raise ValueError("use numeric constants only")
    return value


def _escape_for_runtime_interpolation(value):
    """ConfigParser in es-ESS treats %% as one literal percent."""
    return str(value).replace("%", "%%")


def serialized_config(config):
    """Return config text with literal percent signs safely escaped."""
    output = configparser.ConfigParser(interpolation=None)
    output.optionxform = str
    output.read_dict(
        {
            "DEFAULT": {
                key: _escape_for_runtime_interpolation(value)
                for key, value in config.defaults().items()
            }
        }
    )
    for section in config.sections():
        output.add_section(section)
        for key, value in config._sections[section].items():
            output[section][key] = _escape_for_runtime_interpolation(value)

    from io import StringIO

    buffer = StringIO()
    output.write(buffer, space_around_delimiters=False)
    return buffer.getvalue()


def load_sample(path):
    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str
    loaded = config.read(path, encoding="utf-8")
    if not loaded:
        raise FileNotFoundError("configuration sample not found: {0}".format(path))
    # Keep values in memory as the operator means them. The maintained sample
    # is runtime-ready, so any literal percent is already encoded as ``%%``.
    for key, value in list(config.defaults().items()):
        config.defaults()[key] = value.replace("%%", "%")
    for section in config.sections():
        for key, value in list(config._sections[section].items()):
            config._sections[section][key] = value.replace("%%", "%")
    return config


class ConfigWizard:
    def __init__(self, config, input_func=input, secret_func=None, output=None):
        self.config = config
        self.input = input_func
        self.secret = secret_func or getpass.getpass
        self.output = output or sys.stdout
        self.enabled = {}
        self._section_keys = set(config.sections())

    def say(self, message=""):
        print(message, file=self.output)

    def _read(self, prompt, secret=False):
        try:
            return (self.secret if secret else self.input)(prompt)
        except (EOFError, KeyboardInterrupt) as exc:
            raise WizardCancelled() from exc

    def ask(
        self,
        label,
        default=None,
        parser=None,
        validator=None,
        allow_empty=False,
        secret=False,
    ):
        parser = parser or (lambda value: value)
        while True:
            if secret:
                suffix = (
                    " [press Enter to keep current]"
                    if default not in (None, "")
                    else ""
                )
            elif default is not None:
                suffix = " [{0}]".format(default)
            else:
                suffix = ""
            raw = self._read("{0}{1}: ".format(label, suffix), secret=secret)

            if raw == "":
                if default is not None:
                    raw = str(default)
                elif allow_empty:
                    return ""
                else:
                    self.say("  A value is required.")
                    continue

            try:
                parsed = parser(raw)
                if validator is not None:
                    parsed = validator(parsed)
                return parsed
            except (TypeError, ValueError, SyntaxError, re.error) as exc:
                self.say("  Invalid value: {0}.".format(exc))

    def ask_bool(self, label, default=False):
        default_text = "Y/n" if default else "y/N"
        while True:
            raw = self._read("{0} [{1}]: ".format(label, default_text)).strip().lower()
            if raw == "":
                return bool(default)
            if raw in ("y", "yes", "true", "1"):
                return True
            if raw in ("n", "no", "false", "0"):
                return False
            self.say("  Enter yes or no.")

    def ask_choice(self, label, choices, default):
        normalized = {choice.lower(): choice for choice in choices}
        while True:
            raw = self._read(
                "{0} ({1}) [{2}]: ".format(label, "/".join(choices), default)
            ).strip()
            if raw == "":
                return default
            if raw.isdigit() and 1 <= int(raw) <= len(choices):
                return choices[int(raw) - 1]
            selected = normalized.get(raw.lower())
            if selected is not None:
                return selected
            self.say("  Choose one of: {0}.".format(", ".join(choices)))

    def ask_int(self, label, default=None, minimum=None, maximum=None):
        def validate(value):
            if minimum is not None and value < minimum:
                raise ValueError("must be at least {0}".format(minimum))
            if maximum is not None and value > maximum:
                raise ValueError("must be at most {0}".format(maximum))
            return value

        return self.ask(label, default, parser=_integer, validator=validate)

    def ask_number(
        self, label, default=None, minimum=None, maximum=None, greater_than=None
    ):
        def validate(value):
            if minimum is not None and value < minimum:
                raise ValueError("must be at least {0}".format(minimum))
            if maximum is not None and value > maximum:
                raise ValueError("must be at most {0}".format(maximum))
            if greater_than is not None and value <= greater_than:
                raise ValueError("must be greater than {0}".format(greater_than))
            return value

        return self.ask(label, default, parser=_finite_number, validator=validate)

    def ask_ca_file(self, label, default, tls_enabled, verification):
        while True:
            ca_file = self.ask(label, default, allow_empty=True).strip()
            if tls_enabled and verification == "CertificateOnly" and not ca_file:
                self.say("  A CA/certificate file is required for CertificateOnly.")
                default = None
                continue
            if (
                tls_enabled
                and verification in ("Required", "CertificateOnly")
                and ca_file
                and (not os.path.isfile(ca_file) or not os.access(ca_file, os.R_OK))
            ):
                self.say(
                    "  The CA/certificate file must exist and be readable on this device."
                )
                default = None
                continue
            return ca_file

    def current(self, section, key, fallback=None):
        if self.config.has_option(section, key):
            return self.config[section][key]
        return fallback

    def set_value(self, section, key, value):
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config[section][key] = _stringify(value)

    def set_bool(self, section, key, value):
        self.set_value(section, key, "true" if value else "false")

    def section_heading(self, title):
        self.say()
        self.say("=== {0} ===".format(title))

    def configure_common(self):
        self.section_heading("Common settings")
        section = "Common"
        log_level = self.ask_choice(
            "Log level",
            ("TRACE", "DEBUG", "APP_DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
            self.current(section, "LogLevel", "APP_DEBUG"),
        )
        self.set_value(section, "LogLevel", log_level)
        self.set_value(
            section,
            "LogRetentionDays",
            self.ask_int(
                "Log retention days", self.current(section, "LogRetentionDays", 10), 1
            ),
        )
        self.set_value(
            section,
            "NumberOfThreads",
            self.ask_int(
                "Worker thread count", self.current(section, "NumberOfThreads", 5), 1
            ),
        )
        self.set_value(
            section,
            "ServiceMessageCount",
            self.ask_int(
                "Retained service-message count",
                self.current(section, "ServiceMessageCount", 20),
                0,
            ),
        )
        self.set_value(
            section, "ConfigVersion", self.current(section, "ConfigVersion", "17")
        )
        portal = self.ask(
            "VRM portal ID (from /sbin/get-unique-id)",
            validator=lambda value: (
                value.strip()
                if value.strip()
                else (_ for _ in ()).throw(ValueError("must not be empty"))
            ),
        )
        self.set_value(section, "VRMPortalID", portal)
        self.set_value(
            section,
            "BatteryCapacityInWh",
            self.ask_int(
                "Battery capacity (Wh)",
                self.current(section, "BatteryCapacityInWh", 28000),
                1,
            ),
        )
        self.set_value(
            section,
            "BatteryMaxChargeInWh",
            self.ask_int(
                "Maximum battery charging power (W)",
                self.current(section, "BatteryMaxChargeInWh", 9000),
                0,
            ),
        )
        while True:
            default_setpoint = self.ask_number(
                "Default ESS grid setpoint (W)",
                self.current(section, "DefaultPowerSetPoint", -50),
            )
            minimum = self.ask_number(
                "Minimum approved grid setpoint (W)",
                self.current(section, "GridSetPointMinW", -50),
            )
            maximum = self.ask_number(
                "Maximum approved grid setpoint (W)",
                self.current(section, "GridSetPointMaxW", -50),
            )
            if minimum <= default_setpoint <= maximum:
                break
            self.say(
                "  The minimum must be <= the default <= the maximum. Please enter all three again."
            )
        self.set_value(section, "DefaultPowerSetPoint", default_setpoint)
        self.set_value(section, "GridSetPointMinW", minimum)
        self.set_value(section, "GridSetPointMaxW", maximum)
        self.set_value(
            section,
            "HttpRequestTimeout",
            self.ask_number(
                "Shared HTTP timeout (seconds)",
                self.current(section, "HttpRequestTimeout", 5),
                greater_than=0,
            ),
        )

    def configure_mqtt(self):
        self.section_heading("MQTT")
        section = "Mqtt"
        self.set_value(
            section,
            "Host",
            self.ask(
                "Main MQTT host",
                self.current(section, "Host", "localhost"),
                validator=_validate_host,
            ),
        )
        user = self.ask(
            "Main MQTT username (optional)",
            self.current(section, "User", ""),
            allow_empty=True,
        )
        password = self.ask(
            "Main MQTT password (hidden, optional)",
            self.current(section, "Password", "") or None,
            allow_empty=True,
            secret=True,
        )
        if bool(user) != bool(password):
            self.say(
                "  MQTT username and password must either both be set or both be empty."
            )
            if user:
                password = self.ask("Main MQTT password (hidden)", secret=True)
            else:
                user = self.ask("Main MQTT username")
        self.set_value(section, "User", user)
        self.set_value(section, "Password", password)
        self.set_value(
            section,
            "Port",
            self.ask_int(
                "Main MQTT port", self.current(section, "Port", 1883), 1, 65535
            ),
        )

        ssl_enabled = self.ask_bool(
            "Use TLS for main MQTT",
            self.current(section, "SslEnabled", "false").lower() == "true",
        )
        self.set_bool(section, "SslEnabled", ssl_enabled)
        verification = self.ask_choice(
            "Main MQTT TLS verification",
            ("Required", "CertificateOnly", "Insecure"),
            self.current(section, "SslVerification", "Required"),
        )
        ca_file = self.ask_ca_file(
            "Main MQTT CA/certificate file (optional)",
            self.current(section, "SslCaFile", ""),
            ssl_enabled,
            verification,
        )
        self.set_value(section, "SslVerification", verification)
        self.set_value(section, "SslCaFile", ca_file)

        local_ssl = self.ask_bool(
            "Use TLS for local Venus MQTT",
            self.current(section, "LocalSslEnabled", "false").lower() == "true",
        )
        self.set_bool(section, "LocalSslEnabled", local_ssl)
        local_verification = self.ask_choice(
            "Local MQTT TLS verification",
            ("Required", "CertificateOnly", "Insecure"),
            self.current(section, "LocalSslVerification", "Required"),
        )
        local_ca = self.ask_ca_file(
            "Local MQTT CA/certificate file (optional)",
            self.current(section, "LocalSslCaFile", ""),
            local_ssl,
            local_verification,
        )
        self.set_value(section, "LocalSslVerification", local_verification)
        self.set_value(section, "LocalSslCaFile", local_ca)

    def configure_services(self):
        self.section_heading("Services")
        descriptions = {
            "SolarOverheadDistributor": "PV-surplus allocation",
            "TimeToGoCalculator": "diagnostic battery time-to-go",
            "FroniusSmartmeterJSON": "Fronius HTTP grid meter",
            "MqttExporter": "D-Bus to MQTT exports",
            "FroniusWattpilot": "Wattpilot EV charger",
            "MqttTemperature": "MQTT temperature sensors",
            "NoBatToEV": "AC-out EV grid-setpoint adjustment",
            "Shelly3EMGrid": "Shelly 3EM grid meter",
            "ShellyPMInverter": "Shelly PM PV meters",
            "MqttPVInverter": "MQTT PV inverters",
        }
        for service in ACTIVE_SERVICES:
            default = self.current("Services", service, "false").lower() == "true"
            enabled = self.ask_bool(
                "Enable {0} ({1})".format(service, descriptions[service]), default
            )
            self.enabled[service] = enabled

        if (
            self.enabled["FroniusWattpilot"]
            and not self.enabled["SolarOverheadDistributor"]
        ):
            self.say(
                "  FroniusWattpilot Auto/Eco requires SolarOverheadDistributor; enabling it."
            )
            self.enabled["SolarOverheadDistributor"] = True

        for service, enabled in self.enabled.items():
            self.set_bool("Services", service, enabled)

    def configure_solar_distributor(self):
        if not self.enabled["SolarOverheadDistributor"]:
            return
        self.section_heading("SolarOverheadDistributor")
        section = "SolarOverheadDistributor"
        self.set_value(
            section,
            "VRMInstanceID",
            self.ask_int(
                "Distributor VRM instance ID",
                self.current(section, "VRMInstanceID", 1000),
                0,
            ),
        )
        self.set_value(
            section,
            "VRMInstanceID_ReservationMonitor",
            self.ask_int(
                "Reservation-monitor VRM instance ID",
                self.current(section, "VRMInstanceID_ReservationMonitor", 1001),
                0,
            ),
        )
        expression = self.ask(
            "Minimum battery-charge reservation expression",
            self.current(section, "MinBatteryCharge", "5000 - 40 * SOC"),
            validator=_validate_battery_reservation_expression,
        )
        self.set_value(section, "MinBatteryCharge", expression)
        self.set_value(
            section,
            "UpdateInterval",
            self.ask_int(
                "Distribution interval (ms)",
                self.current(section, "UpdateInterval", 5000),
                1,
            ),
        )

        http_count = self.ask_int("Number of HTTP on/off consumers to add", 0, 0)
        for index in range(http_count):
            self.configure_http_consumer(index + 1)
        mqtt_count = self.ask_int("Number of MQTT on/off consumers to add", 0, 0)
        for index in range(mqtt_count):
            self.configure_mqtt_consumer(index + 1)

    def unique_section(self, prefix, ordinal):
        while True:
            key = self.ask(
                "{0} #{1} unique key".format(prefix, ordinal),
                validator=_validate_identifier,
            )
            section = "{0}:{1}".format(prefix, key)
            if section not in self._section_keys:
                self._section_keys.add(section)
                self.config.add_section(section)
                return section
            self.say("  That section key is already in use.")

    def configure_http_consumer(self, ordinal):
        section = self.unique_section("HttpConsumer", ordinal)
        self.set_value(section, "CustomName", self.ask("Display name"))
        self.set_bool(
            section,
            "IgnoreBatReservation",
            self.ask_bool("Allow this load despite battery reservation", False),
        )
        self.set_value(
            section, "VRMInstanceID", self.ask_int("VRM instance ID", minimum=0)
        )
        self.set_value(
            section,
            "Request",
            self.ask_number("Complete load requirement (W)", minimum=0),
        )
        self.set_value(
            section,
            "Priority",
            self.ask_int("Allocation priority (lower runs first)", 100),
        )
        self.set_value(
            section,
            "PriorityShift",
            self.ask_number("Priority shift after each assignment", 0, minimum=0),
        )
        self.set_value(section, "OnUrl", self.ask("On URL", validator=_validate_url))
        self.set_value(section, "OffUrl", self.ask("Off URL", validator=_validate_url))
        self.set_value(
            section, "StatusUrl", self.ask("Status URL", validator=_validate_url)
        )
        self.set_value(
            section,
            "IsOnKeywordRegex",
            self.ask("On-state regular expression", validator=_validate_regex),
        )
        power_url = self.ask(
            "Power URL (optional)",
            allow_empty=True,
            validator=_validate_url,
        )
        self.set_value(
            section,
            "PowerUrl",
            power_url,
        )
        if power_url:
            power_regex = self.ask(
                "Power extraction regular expression (one capture group)",
                validator=lambda value: _validate_regex(value, True),
            )
        else:
            power_regex = ""
        self.set_value(section, "PowerExtractRegex", power_regex)

    def configure_mqtt_consumer(self, ordinal):
        section = self.unique_section("MqttConsumer", ordinal)
        self.set_value(section, "CustomName", self.ask("Display name"))
        self.set_bool(
            section,
            "IgnoreBatReservation",
            self.ask_bool("Allow this load despite battery reservation", False),
        )
        self.set_value(
            section, "VRMInstanceID", self.ask_int("VRM instance ID", minimum=0)
        )
        self.set_value(
            section,
            "Request",
            self.ask_number("Complete load requirement (W)", minimum=0),
        )
        self.set_value(
            section,
            "Priority",
            self.ask_int("Allocation priority (lower runs first)", 100),
        )
        self.set_value(
            section,
            "PriorityShift",
            self.ask_number("Priority shift after each assignment", 0, minimum=0),
        )
        self.set_value(section, "OnTopic", self.ask("MQTT on-command topic"))
        self.set_value(section, "OnValue", self.ask("MQTT on-command value"))
        self.set_value(section, "OffTopic", self.ask("MQTT off-command topic"))
        self.set_value(section, "OffValue", self.ask("MQTT off-command value"))
        self.set_value(section, "StatusTopic", self.ask("MQTT status topic"))
        self.set_value(
            section,
            "IsOnKeywordRegex",
            self.ask("On-state regular expression", validator=_validate_regex),
        )
        power_topic = self.ask("MQTT power topic (optional)", allow_empty=True)
        self.set_value(section, "PowerTopic", power_topic)
        if power_topic:
            power_regex = self.ask(
                "Power extraction regular expression (one capture group)",
                validator=lambda value: _validate_regex(value, True),
            )
        else:
            power_regex = ""
        self.set_value(section, "PowerExtractRegex", power_regex)

    def configure_time_to_go(self):
        if not self.enabled["TimeToGoCalculator"]:
            return
        self.section_heading("TimeToGoCalculator")
        self.set_value(
            "TimeToGoCalculator",
            "UpdateInterval",
            self.ask_int(
                "Calculation interval (ms)",
                self.current("TimeToGoCalculator", "UpdateInterval", 1000),
                1,
            ),
        )

    def configure_fronius_meter(self):
        if not self.enabled["FroniusSmartmeterJSON"]:
            return
        self.section_heading("FroniusSmartmeterJSON")
        section = "FroniusSmartmeterJSON"
        self.set_value(
            section,
            "VRMInstanceID",
            self.ask_int(
                "VRM instance ID", self.current(section, "VRMInstanceID", 40), 0
            ),
        )
        self.set_value(
            section,
            "CustomName",
            self.ask(
                "Display name",
                self.current(section, "CustomName", "Fronius Smartmeter (JSON)"),
            ),
        )
        self.set_value(
            section,
            "PollFrequencyMs",
            self.ask_int(
                "Polling interval (ms)",
                self.current(section, "PollFrequencyMs", 500),
                1,
            ),
        )
        self.set_value(
            section, "Host", self.ask("Fronius inverter host", validator=_validate_host)
        )
        self.set_value(
            section,
            "MeterID",
            self.ask_int("Fronius meter ID", self.current(section, "MeterID", 0), 0),
        )

    def configure_mqtt_exporters(self):
        if not self.enabled["MqttExporter"]:
            return
        self.section_heading("MqttExporter")
        count = self.ask_int("Number of D-Bus values to export", minimum=1)
        for ordinal in range(1, count + 1):
            section = self.unique_section("MqttExporter", ordinal)
            self.set_value(section, "Service", self.ask("D-Bus service name"))
            self.set_value(
                section,
                "DbusKey",
                self.ask(
                    "D-Bus path",
                    validator=lambda value: (
                        value
                        if value.startswith("/")
                        else (_ for _ in ()).throw(ValueError("must start with /"))
                    ),
                ),
            )
            self.set_value(section, "MqttTopic", self.ask("Destination MQTT topic"))
            self.set_value(
                section,
                "PublishType",
                self.ask_choice(
                    "Publish type",
                    ("ONCHANGE", "INTERVAL_1S", "INTERVAL_10S", "INTERVAL_60S"),
                    "ONCHANGE",
                ),
            )

    def configure_wattpilot(self):
        if not self.enabled["FroniusWattpilot"]:
            return
        self.section_heading("FroniusWattpilot")
        section = "FroniusWattpilot"
        self.say(
            "Manual mode remains user-controlled. These limits apply to Auto/Eco control."
        )
        self.set_value(
            section,
            "VRMInstanceID",
            self.ask_int(
                "EV charger VRM instance ID",
                self.current(section, "VRMInstanceID", 1007),
                0,
            ),
        )
        self.set_value(
            section,
            "VRMInstanceID_OverheadRequest",
            self.ask_int(
                "Wattpilot request VRM instance ID",
                self.current(section, "VRMInstanceID_OverheadRequest", 1006),
                0,
            ),
        )
        self.set_value(
            section,
            "MinPhaseSwitchSeconds",
            self.ask_int(
                "Minimum phase-switch stability time (seconds)",
                self.current(section, "MinPhaseSwitchSeconds", 600),
                0,
            ),
        )
        self.set_value(
            section,
            "MinOnOffSeconds",
            self.ask_int(
                "Minimum start/stop interval (seconds)",
                self.current(section, "MinOnOffSeconds", 60),
                0,
            ),
        )
        self.set_value(
            section,
            "OverheadPriority",
            self.ask_int(
                "PV-overhead priority", self.current(section, "OverheadPriority", 35)
            ),
        )
        self.set_value(
            section,
            "ResetChargedEnergyCounter",
            self.ask_choice(
                "Reset session counters",
                ("OnDisconnect", "OnConnect"),
                self.current(section, "ResetChargedEnergyCounter", "OnDisconnect"),
            ),
        )
        self.set_value(
            section,
            "Position",
            self.ask_choice(
                "Wattpilot position (0=AC-out, 1=AC-in)",
                ("0", "1"),
                self.current(section, "Position", "0"),
            ),
        )
        self.set_value(
            section, "Host", self.ask("Wattpilot host", validator=_validate_host)
        )
        self.set_value(
            section,
            "Password",
            self.ask("Wattpilot device/app-access password (hidden)", secret=True),
        )
        self.set_bool(
            section,
            "HibernateMode",
            self.ask_bool(
                "Disconnect while no vehicle is present (hibernate)",
                self.current(section, "HibernateMode", "false").lower() == "true",
            ),
        )

        while True:
            minimum = self.ask_int(
                "Minimum charging current per phase (A)",
                self.current(section, "MinCurrentPerPhase", 6),
                6,
                32,
            )
            maximum = self.ask_int(
                "Maximum charging current per phase (A)",
                self.current(section, "MaxCurrentPerPhase", 16),
                6,
                32,
            )
            if maximum >= minimum:
                break
            self.say(
                "  Maximum current must be greater than or equal to minimum current."
            )
        self.set_value(section, "MinCurrentPerPhase", minimum)
        self.set_value(section, "MaxCurrentPerPhase", maximum)
        self.set_value(
            section,
            "VehiclePhaseCapability",
            self.ask_choice(
                "Auto/Eco vehicle phase capability",
                ("Automatic", "OnePhaseOnly"),
                self.current(section, "VehiclePhaseCapability", "Automatic"),
            ),
        )

        source = self.ask_choice(
            "Whole-site current source",
            ("VenusSystem", "Shelly3EMGen3"),
            self.current(section, "SiteCurrentSource", "VenusSystem"),
        )
        self.set_value(section, "SiteCurrentSource", source)
        self.set_value(
            section,
            "SiteMaxCurrent",
            self.ask_int(
                "Maximum whole-site current per physical phase (A)",
                self.current(section, "SiteMaxCurrent", 20),
                6,
                100,
            ),
        )
        self.set_value(
            section,
            "Charger1PhaseMapping",
            self.ask_choice(
                "Physical phase used for one-phase charging",
                ("L1", "L2", "L3"),
                self.current(section, "Charger1PhaseMapping", "L1"),
            ),
        )
        site_fresh = self.ask_int(
            "Site-current freshness limit (seconds)",
            self.current(section, "SiteCurrentFreshSeconds", 15),
            1,
        )
        self.set_value(section, "SiteCurrentFreshSeconds", site_fresh)
        self.set_value(
            section,
            "SiteCurrentRecoverySeconds",
            self.ask_int(
                "Safe-headroom recovery time (seconds)",
                self.current(section, "SiteCurrentRecoverySeconds", 30),
                0,
            ),
        )

        while True:
            phase_start = self.ask_int(
                "Three-phase PV-surplus start threshold (W)",
                self.current(section, "ThreePhasePvSurplusStartW", 4500),
                0,
            )
            phase_stop = self.ask_int(
                "Three-phase PV-surplus stop threshold (W)",
                self.current(section, "ThreePhasePvSurplusStopW", 4100),
                0,
            )
            if phase_start > phase_stop:
                break
            self.say("  The start threshold must be greater than the stop threshold.")
        self.set_value(section, "ThreePhasePvSurplusStartW", phase_start)
        self.set_value(section, "ThreePhasePvSurplusStopW", phase_stop)

        self.set_bool(
            section,
            "EvPriorityOverBatteryCharge",
            self.ask_bool(
                "Give connected EV priority over battery charging",
                self.current(section, "EvPriorityOverBatteryCharge", "true").lower()
                == "true",
            ),
        )
        self.set_value(
            section,
            "EvPriorityMinSoc",
            self.ask_number(
                "Minimum SOC for EV priority (%)",
                self.current(section, "EvPriorityMinSoc", 50),
                0,
                100,
            ),
        )

        assist = self.ask_bool(
            "Enable bounded battery assist for an already-running charge",
            self.current(section, "BatteryAssistEnabled", "true").lower() == "true",
        )
        self.set_bool(section, "BatteryAssistEnabled", assist)
        self.set_value(
            section,
            "BatteryAssistSocMin",
            self.ask_number(
                "Minimum SOC for battery assist (%)",
                self.current(section, "BatteryAssistSocMin", 50),
                0,
                100,
            ),
        )
        self.set_value(
            section,
            "BatteryAssistMaxSeconds",
            self.ask_int(
                "Maximum battery-assist duration (seconds)",
                self.current(section, "BatteryAssistMaxSeconds", 600),
                1 if assist else 0,
            ),
        )
        self.set_value(
            section,
            "BatteryAssistMaxShortfallPerPhaseW",
            self.ask_number(
                "Maximum battery-assist shortfall per active phase (W)",
                self.current(section, "BatteryAssistMaxShortfallPerPhaseW", 1500),
                0,
            ),
        )
        self.set_value(
            section,
            "BatterySocFreshSeconds",
            self.ask_int(
                "Battery SOC/activity freshness limit (seconds)",
                self.current(section, "BatterySocFreshSeconds", 15),
                1,
            ),
        )

        allow_grid = self.ask_bool(
            "Allow grid-charging fallback for an already-running charge when PV is insufficient",
            self.current(section, "AllowGridCharging", "false").lower() == "true",
        )
        self.set_bool(section, "AllowGridCharging", allow_grid)
        self.set_bool(
            section,
            "GridImportPositive",
            self.ask_bool(
                "Positive grid power means import",
                self.current(section, "GridImportPositive", "true").lower() == "true",
            ),
        )
        self.set_value(
            section,
            "GridImportStopW",
            self.ask_number(
                "Grid-import stop threshold (W)",
                self.current(section, "GridImportStopW", 300),
                0,
            ),
        )
        self.set_value(
            section,
            "GridImportStopSeconds",
            self.ask_int(
                "Grid-import confirmation time (seconds)",
                self.current(section, "GridImportStopSeconds", 15),
                0,
            ),
        )
        self.set_value(
            section,
            "GridTelemetryFreshSeconds",
            self.ask_int(
                "Grid telemetry freshness limit (seconds)",
                self.current(section, "GridTelemetryFreshSeconds", 15),
                1,
            ),
        )
        self.set_value(
            section,
            "AllowanceFreshSeconds",
            self.ask_int(
                "Assigned-PV allowance freshness limit (seconds)",
                self.current(section, "AllowanceFreshSeconds", 15),
                1,
            ),
        )
        self.set_value(
            section,
            "AllowanceDropGraceSeconds",
            self.ask_int(
                "Running-charge allowance-drop grace (seconds)",
                self.current(section, "AllowanceDropGraceSeconds", 30),
                0,
            ),
        )
        self.set_value(
            section,
            "CarDisconnectConfirmSeconds",
            self.ask_int(
                "Vehicle-disconnect confirmation time (seconds)",
                self.current(section, "CarDisconnectConfirmSeconds", 15),
                0,
            ),
        )
        self.set_value(
            section,
            "SurplusDropGraceSeconds",
            self.ask_int(
                "PV-surplus drop grace (seconds)",
                self.current(section, "SurplusDropGraceSeconds", 30),
                0,
            ),
        )
        self.set_value(
            section,
            "StartupGraceSeconds",
            self.ask_int(
                "Start/phase-change telemetry grace (seconds)",
                self.current(section, "StartupGraceSeconds", 60),
                0,
            ),
        )
        self.set_value(
            section,
            "StartupTelemetryRatio",
            self.ask_number(
                "Startup telemetry ratio",
                self.current(section, "StartupTelemetryRatio", 0.80),
                greater_than=0,
                maximum=1,
            ),
        )
        self.set_value(
            section,
            "BatteryAssistRecoverySeconds",
            self.ask_int(
                "Battery-assist recovery time (seconds)",
                self.current(section, "BatteryAssistRecoverySeconds", 120),
                0,
            ),
        )
        self.set_value(
            section,
            "RawOverheadFreshSeconds",
            self.ask_int(
                "Raw PV-overhead freshness limit (seconds)",
                self.current(section, "RawOverheadFreshSeconds", 15),
                5,
            ),
        )
        complete_threshold = self.ask_number(
            "Charge-complete low-power threshold (W)",
            self.current(section, "ChargeCompletePowerThresholdW", 120),
            0,
        )
        self.set_value(section, "ChargeCompletePowerThresholdW", complete_threshold)
        self.set_value(
            section,
            "ChargeCompleteConfirmSeconds",
            self.ask_int(
                "Charge-complete confirmation time (seconds)",
                self.current(section, "ChargeCompleteConfirmSeconds", 300),
                0,
            ),
        )
        self.set_value(
            section,
            "ChargeCompleteResumePowerW",
            self.ask_number(
                "Charge-complete resume threshold (W)",
                self.current(section, "ChargeCompleteResumePowerW", 300),
                minimum=complete_threshold,
            ),
        )
        self.set_value(
            section,
            "ChargeCompleteResumeSeconds",
            self.ask_int(
                "Charge-complete resume time (seconds)",
                self.current(section, "ChargeCompleteResumeSeconds", 30),
                0,
            ),
        )

        if source == "Shelly3EMGen3":
            self.configure_shelly_site_current(site_fresh)

        if self.enabled["NoBatToEV"] and assist and not allow_grid:
            self.say()
            self.say(
                "NoBatToEV must remain disabled with battery-assist/no-grid Wattpilot control."
            )
            if self.ask_bool("Disable NoBatToEV now", True):
                self.enabled["NoBatToEV"] = False
                self.set_bool("Services", "NoBatToEV", False)
            else:
                raise WizardCancelled()

    def configure_shelly_site_current(self, site_fresh_seconds):
        self.section_heading("Dedicated Shelly 3EM Gen3 site-current source")
        section = "Shelly3EMSiteCurrent"
        self.set_value(
            section, "Host", self.ask("Shelly host", validator=_validate_host)
        )
        self.set_value(section, "Username", "admin")
        self.set_value(
            section,
            "Password",
            self.ask(
                "Shelly device password (hidden, optional if authentication is disabled)",
                allow_empty=True,
                secret=True,
            ),
        )
        self.set_value(
            section,
            "PollFrequencyMs",
            self.ask_int(
                "Shelly polling interval (ms)",
                self.current(section, "PollFrequencyMs", 1000),
                500,
            ),
        )
        self.set_value(
            section,
            "RequestTimeoutSeconds",
            self.ask_number(
                "Shelly request timeout (seconds)",
                self.current(section, "RequestTimeoutSeconds", 2),
                greater_than=0,
                maximum=10,
            ),
        )
        self.set_value(
            section,
            "TransientFailureGraceSeconds",
            self.ask_int(
                "Connection-only transient failure grace (seconds)",
                self.current(section, "TransientFailureGraceSeconds", 0),
                0,
                min(5, site_fresh_seconds),
            ),
        )
        while True:
            mapping = [
                self.ask_choice(
                    "Physical phase measured by Shelly channel {0}".format(channel),
                    ("L1", "L2", "L3"),
                    default,
                )
                for channel, default in (("A", "L1"), ("B", "L2"), ("C", "L3"))
            ]
            if sorted(mapping) == ["L1", "L2", "L3"]:
                break
            self.say("  Channels A, B and C must map one-to-one to L1, L2 and L3.")
        for channel, phase in zip(("A", "B", "C"), mapping):
            self.set_value(section, "Phase{0}".format(channel), phase)

    def configure_mqtt_temperatures(self):
        if not self.enabled["MqttTemperature"]:
            return
        self.section_heading("MqttTemperature")
        count = self.ask_int("Number of MQTT temperature sensors", minimum=1)
        for ordinal in range(1, count + 1):
            section = self.unique_section("MqttTemperature", ordinal)
            self.set_value(
                section, "VRMInstanceID", self.ask_int("VRM instance ID", minimum=0)
            )
            self.set_value(section, "CustomName", self.ask("Display name"))
            self.set_value(section, "Topic", self.ask("Temperature MQTT topic"))
            self.set_value(
                section,
                "TopicHumidity",
                self.ask("Humidity MQTT topic (optional)", allow_empty=True),
            )
            self.set_value(
                section,
                "TopicPressure",
                self.ask("Pressure MQTT topic (optional)", allow_empty=True),
            )

    def configure_no_bat_to_ev(self):
        if not self.enabled["NoBatToEV"]:
            return
        self.section_heading("NoBatToEV")
        self.set_value(
            "NoBatToEV",
            "UseRelay",
            self.ask_choice(
                "Relay gate (-1=disabled, 0=relay 0, 1=relay 1)",
                ("-1", "0", "1"),
                self.current("NoBatToEV", "UseRelay", "-1"),
            ),
        )

    def configure_shelly_grid(self):
        if not self.enabled["Shelly3EMGrid"]:
            return
        self.section_heading("Shelly3EMGrid")
        section = "Shelly3EMGrid"
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.set_value(section, "VRMInstanceID", self.ask_int("VRM instance ID", 47, 0))
        self.set_value(
            section, "CustomName", self.ask("Display name", "Shelly 3EM (Grid)")
        )
        self.set_value(
            section, "PollFrequencyMs", self.ask_int("Polling interval (ms)", 1000, 1)
        )
        self.set_value(
            section, "Username", self.ask("Shelly username", allow_empty=True)
        )
        self.set_value(
            section,
            "Password",
            self.ask(
                "Shelly password (hidden, optional)", allow_empty=True, secret=True
            ),
        )
        self.set_value(
            section, "Host", self.ask("Shelly host", validator=_validate_host)
        )
        self.set_value(
            section,
            "Metering",
            self.ask_choice("Metering mode", ("Default", "Net"), "Default"),
        )

    def configure_shelly_pm(self):
        if not self.enabled["ShellyPMInverter"]:
            return
        self.section_heading("ShellyPMInverter")
        count = self.ask_int("Number of Shelly PM inverter meters", minimum=1)
        for ordinal in range(1, count + 1):
            section = self.unique_section("ShellyPMInverter", ordinal)
            self.set_value(
                section, "VRMInstanceID", self.ask_int("VRM instance ID", minimum=0)
            )
            self.set_value(section, "CustomName", self.ask("Display name"))
            self.set_value(
                section,
                "PollFrequencyMs",
                self.ask_int("Polling interval (ms)", 1000, 1),
            )
            self.set_value(
                section, "Username", self.ask("Shelly username", allow_empty=True)
            )
            self.set_value(
                section,
                "Password",
                self.ask(
                    "Shelly password (hidden, optional)", allow_empty=True, secret=True
                ),
            )
            self.set_value(
                section, "Host", self.ask("Shelly host", validator=_validate_host)
            )
            self.set_value(
                section,
                "Phase",
                self.ask_choice("Physical phase", ("1", "2", "3"), "1"),
            )
            self.set_value(
                section,
                "Position",
                self.ask_choice("Position (0=AC-in, 1=AC-out)", ("0", "1"), "1"),
            )
            self.set_value(section, "Relay", self.ask_int("Relay ID", 0, 0))

    def configure_mqtt_pv(self):
        if not self.enabled["MqttPVInverter"]:
            return
        self.section_heading("MqttPVInverter")
        section = "MqttPvInverter"
        self.set_bool(
            section,
            "EnableZeroFeedin",
            self.ask_bool(
                "Enable experimental zero-feed-in control",
                self.current(section, "EnableZeroFeedin", "false").lower() == "true",
            ),
        )
        self.set_bool(
            section,
            "EnablePvShutdown",
            self.ask_bool(
                "Allow PV shutdown commands",
                self.current(section, "EnablePvShutdown", "false").lower() == "true",
            ),
        )
        self.set_value(
            section,
            "ZeroFeedinScaleStep",
            self.ask_number(
                "Zero-feed-in scale step",
                self.current(section, "ZeroFeedinScaleStep", 0.05),
                greater_than=0,
                maximum=1,
            ),
        )
        self.set_value(
            section,
            "ZeroFeedinDistance",
            self.ask_number(
                "Zero-feed-in buffer (W)",
                self.current(section, "ZeroFeedinDistance", 50),
                0,
            ),
        )
        self.set_value(
            section,
            "ZeroFeedinStartSoc",
            self.ask_number(
                "Zero-feed-in start SOC (%)",
                self.current(section, "ZeroFeedinStartSoc", 100),
                0,
                100,
            ),
        )
        self.set_value(
            section,
            "StaleTimeoutSeconds",
            self.ask_int(
                "MQTT inverter stale timeout (seconds)",
                self.current(section, "StaleTimeoutSeconds", 300),
                5,
            ),
        )

        count = self.ask_int("Number of MQTT PV inverters", minimum=1)
        required_topics = (
            "L1VoltageTopic",
            "L2VoltageTopic",
            "L3VoltageTopic",
            "L1PowerTopic",
            "L2PowerTopic",
            "L3PowerTopic",
            "L1CurrentTopic",
            "L2CurrentTopic",
            "L3CurrentTopic",
            "L1EnergyForwardedTopic",
            "L2EnergyForwardedTopic",
            "L3EnergyForwardedTopic",
            "TotalEnergyForwardedTopic",
            "TotalPowerTopic",
        )
        for ordinal in range(1, count + 1):
            instance = self.unique_section("MqttPVInverter", ordinal)
            self.set_value(instance, "CustomName", self.ask("Display name"))
            self.set_value(
                instance, "VRMInstanceID", self.ask_int("VRM instance ID", minimum=0)
            )
            self.set_value(
                instance,
                "Position",
                self.ask_choice("Position (0=AC-in, 1=AC-out)", ("0", "1"), "1"),
            )
            for key in required_topics:
                self.set_value(instance, key, self.ask("{0}".format(key)))
            self.set_value(
                instance,
                "DtuControlTopic",
                self.ask("Optional OpenDTU control-topic prefix", allow_empty=True),
            )

    def build(self):
        self.say("es-ESS interactive configuration wizard")
        self.say("Press Enter to accept a displayed default. Passwords are hidden.")
        self.configure_common()
        self.configure_mqtt()
        self.configure_services()
        self.configure_solar_distributor()
        self.configure_time_to_go()
        self.configure_fronius_meter()
        self.configure_mqtt_exporters()
        self.configure_wattpilot()
        self.configure_mqtt_temperatures()
        self.configure_no_bat_to_ev()
        self.configure_shelly_grid()
        self.configure_shelly_pm()
        self.configure_mqtt_pv()
        return self.config

    def summary(self, target):
        enabled = [name for name in ACTIVE_SERVICES if self.enabled.get(name)]
        self.section_heading("Summary")
        self.say("Output: {0}".format(target))
        self.say(
            "Enabled services: {0}".format(", ".join(enabled) if enabled else "none")
        )
        self.say("Credentials are intentionally omitted from this summary.")


def _secure_mode(path):
    os.chmod(str(path), 0o600)


def write_config(config, target, replace=False, now=None):
    """Atomically write a protected config, backing up an existing target."""
    target = Path(target)
    if not target.parent.is_dir():
        raise FileNotFoundError(
            "output directory does not exist: {0}".format(target.parent)
        )
    backup = None
    if target.exists():
        if not replace:
            raise FileExistsError("configuration already exists: {0}".format(target))
        timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        backup = target.with_name("{0}.{1}.backup".format(target.name, timestamp))
        if backup.exists():
            raise FileExistsError("backup already exists: {0}".format(backup))
        shutil.copy2(str(target), str(backup))
        _secure_mode(backup)

    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=".{0}.".format(target.name),
            suffix=".tmp",
            dir=str(target.parent),
            delete=False,
        ) as temp_file:
            temp_name = Path(temp_file.name)
            temp_file.write(serialized_config(config))
            temp_file.flush()
            os.fsync(temp_file.fileno())
        _secure_mode(temp_name)
        os.replace(str(temp_name), str(target))
        _secure_mode(target)
    finally:
        if temp_name is not None and temp_name.exists():
            temp_name.unlink()
    return backup


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Interactively create an es-ESS config.ini"
    )
    parser.add_argument(
        "--sample",
        type=Path,
        default=DEFAULT_SAMPLE,
        help="maintained sample configuration",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="config.ini destination"
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        config = load_sample(args.sample)
        wizard = ConfigWizard(config)
        wizard.build()
        wizard.summary(args.output)
        replacing = args.output.exists()
        if replacing:
            wizard.say(
                "An existing configuration will be backed up before replacement."
            )
        if not wizard.ask_bool("Write this configuration", False):
            raise WizardCancelled()
        backup = write_config(config, args.output, replace=replacing)
        wizard.say("Configuration written securely to {0}".format(args.output))
        if backup is not None:
            wizard.say("Previous configuration backed up to {0}".format(backup))
        return 0
    except WizardCancelled:
        print(
            "Configuration creation cancelled; no new file was written.",
            file=sys.stderr,
        )
        return 130
    except (configparser.Error, OSError, ValueError) as exc:
        print("Unable to create configuration: {0}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
