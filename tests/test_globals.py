"""Hardware-free tests for global helpers."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


def _module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _install_runtime_stubs():
    _module(
        "Helper",
        i=lambda *args, **kwargs: None,
        c=lambda *args, **kwargs: None,
        d=lambda *args, **kwargs: None,
        w=lambda *args, **kwargs: None,
        e=lambda *args, **kwargs: None,
        t=lambda *args, **kwargs: None,
    )


class GlobalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.globals = _load_module("globals_under_test", ROOT / "Globals.py")

    def test_get_user_time_uses_structured_subprocess_environment(self):
        self.globals.userTimezone = "Europe/Bucharest"
        self.globals.subprocess.run = Mock(
            return_value=SimpleNamespace(stdout="2026-07-11 12:34:56\n")
        )

        self.assertEqual(self.globals.getUserTime(), "2026-07-11 12:34:56")

        self.globals.subprocess.run.assert_called_once()
        args, kwargs = self.globals.subprocess.run.call_args
        self.assertEqual(args[0], ["date", "+%Y-%m-%d %H:%M:%S"])
        self.assertEqual(kwargs["env"]["TZ"], ":Europe/Bucharest")
        self.assertTrue(kwargs["capture_output"])
        self.assertTrue(kwargs["text"])
        self.assertEqual(kwargs["timeout"], 3)
        self.assertNotIn("shell", kwargs)

    def test_get_user_time_rejects_shell_metacharacters(self):
        self.globals.userTimezone = 'UTC"; reboot; echo "'
        self.globals.subprocess.run = Mock()

        with self.assertRaises(ValueError):
            self.globals.getUserTime()

        self.globals.subprocess.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
