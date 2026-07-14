"""Configuration contract tests for maintained sample configuration."""

import ast
import configparser
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DORMANT_SERVICES = {
    "ChargeCurrentReducer",
    "FroniusSmartmeterRS485",
    "Grid2Bat",
    "MqttDC",
}
POLICY_CONFIG_KEYS = {
    "Common": {
        "GridSetPointMinW",
        "GridSetPointMaxW",
        "HttpRequestTimeout",
    },
    "Mqtt": {
        "SslVerification",
        "SslCaFile",
        "LocalSslVerification",
        "LocalSslCaFile",
    },
    "MqttPvInverter": {"StaleTimeoutSeconds"},
}


class _WattpilotConfigKeyVisitor(ast.NodeVisitor):
    def __init__(self):
        self.section_aliases = set()
        self.keys = set()

    def visit_Assign(self, node):
        if self._is_wattpilot_section(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.section_aliases.add(target.id)
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and self._is_section_alias(func.value)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            self.keys.add(node.args[0].value)
        self.generic_visit(node)

    def visit_Subscript(self, node):
        if (
            isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
            and (
                self._is_section_alias(node.value)
                or self._is_wattpilot_section(node.value)
            )
        ):
            self.keys.add(node.slice.value)
        self.generic_visit(node)

    def _is_section_alias(self, node):
        return isinstance(node, ast.Name) and node.id in self.section_aliases

    def _is_wattpilot_section(self, node):
        return (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "FroniusWattpilot"
        )


def _active_wattpilot_config_keys():
    source = (ROOT / "FroniusWattpilot.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    visitor = _WattpilotConfigKeyVisitor()
    visitor.visit(tree)
    return visitor.keys


def _sample_wattpilot_config_keys():
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read(ROOT / "config.sample.ini", encoding="utf-8")
    return set(config._sections["FroniusWattpilot"].keys()) - {"__name__"}


def _runtime_service_names():
    source = (ROOT / "es-ESS.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    initialize_services = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_initializeServices"
    )
    return {
        call.args[0].value
        for call in ast.walk(initialize_services)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "_checkAndEnable"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    }


def _sample_service_names():
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read(ROOT / "config.sample.ini", encoding="utf-8")
    return set(config._sections["Services"].keys()) - {"__name__"}


def _readme_active_service_names():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    global_config = readme.split("#### Global Configuration", 1)[1].split(
        "> :warning:", 1
    )[0]
    return set(
        re.findall(r"^\| \[Services\]\s*\|\s*([^|\s]+)\s*\|", global_config, re.M)
    )


class ConfigContractTests(unittest.TestCase):
    def test_wattpilot_sample_matches_active_config_keys(self):
        active_keys = _active_wattpilot_config_keys()
        sample_keys = _sample_wattpilot_config_keys()

        self.assertEqual(
            sorted(active_keys - sample_keys),
            [],
            "Active FroniusWattpilot settings missing from config.sample.ini",
        )
        self.assertEqual(
            sorted(sample_keys - active_keys),
            [],
            "Unknown FroniusWattpilot settings in config.sample.ini",
        )

    def test_active_service_flags_match_runtime_sample_and_readme(self):
        runtime_services = _runtime_service_names()

        self.assertEqual(_sample_service_names(), runtime_services)
        self.assertEqual(_readme_active_service_names(), runtime_services)

    def test_dormant_services_are_not_exposed_as_active(self):
        self.assertTrue(DORMANT_SERVICES.isdisjoint(_runtime_service_names()))
        self.assertTrue(DORMANT_SERVICES.isdisjoint(_sample_service_names()))
        self.assertTrue(DORMANT_SERVICES.isdisjoint(_readme_active_service_names()))

    def test_policy_settings_are_present_in_maintained_sample(self):
        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(ROOT / "config.sample.ini", encoding="utf-8")

        for section, required_keys in POLICY_CONFIG_KEYS.items():
            with self.subTest(section=section):
                self.assertTrue(config.has_section(section))
                self.assertEqual(
                    sorted(required_keys - set(config[section].keys())), []
                )


if __name__ == "__main__":
    unittest.main()
