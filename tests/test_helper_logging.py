"""Hardware-free tests for early Helper warning/error logging."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


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
    class BusConnection:
        TYPE_SYSTEM = 0
        TYPE_SESSION = 1

    dbus = _module("dbus")
    dbus.__path__ = []
    dbus.bus = SimpleNamespace(BusConnection=BusConnection)
    _module("vedbus", VeDbusService=object)
    _module(
        "Globals",
        esESS=None,
        ServiceMessageType=SimpleNamespace(
            Warning="Warning",
            Error="Error",
            Critical="Critical",
        ),
    )


class HelperLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _install_runtime_stubs()
        cls.module = _load_module("helper_logging_under_test", ROOT / "Helper.py")

    def setUp(self):
        self.module.Globals.esESS = None

    def test_warning_and_error_log_before_global_runtime_exists(self):
        with patch.object(self.module.logging, "warning") as warning, patch.object(
            self.module.logging, "error"
        ) as error:
            self.module.w("startup", "warning message")
            self.module.e("startup", "error message")

        warning.assert_called_once()
        error.assert_called_once()

    def test_warning_and_error_publish_when_runtime_exists(self):
        runtime = SimpleNamespace(publishServiceMessage=Mock())
        self.module.Globals.esESS = runtime

        with patch.object(self.module.logging, "warning"), patch.object(
            self.module.logging, "error"
        ):
            self.module.w("startup", "warning message")
            self.module.e("startup", "error message")

        self.assertEqual(runtime.publishServiceMessage.call_count, 2)


if __name__ == "__main__":
    unittest.main()
