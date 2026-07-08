"""Configuration contract tests for maintained sample configuration."""

import ast
import configparser
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


if __name__ == "__main__":
    unittest.main()
