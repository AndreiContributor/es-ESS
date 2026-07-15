"""Hardware-free contract tests for the pinned Victron D-Bus dependency."""

import ast
import json
import os
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import VelibDependency


EXPECTED_PROVENANCE = {
    "vedbus.py": "c00682415ae5690112852c6ab5554e678358a818",
    "dbusmonitor.py": "516178e9e413c23c4fb1bd114b865a88fc644e40",
    "settingsdevice.py": "897d58211e9f94fe4b795cdee06e23ab1582821b",
    "ve_utils.py": "516178e9e413c23c4fb1bd114b865a88fc644e40",
}


def _scalar_type(name, base):
    class Scalar(base):
        def __new__(cls, value=0, **_kwargs):
            return base.__new__(cls, value)

    Scalar.__name__ = name
    return Scalar


class FakeObject:
    def __init__(self, _bus, path):
        self.__dbus_object_path__ = path
        self.removed = False

    def remove_from_connection(self):
        self.removed = True


class FakeBusName:
    def __init__(self, name, bus, do_not_queue=False):
        self.name = name
        self.bus = bus
        self.do_not_queue = do_not_queue
        self.deleted = False

    def __del__(self):
        self.deleted = True


class FakeBusConnection:
    TYPE_SYSTEM = 0
    TYPE_SESSION = 1
    instances = []

    def __new__(cls, *_args, **_kwargs):
        return object.__new__(cls)

    def __init__(self, *_args, **_kwargs):
        self.signal_receivers = []
        self.__class__.instances.append(self)

    def add_signal_receiver(self, callback, **kwargs):
        self.signal_receivers.append((callback, kwargs))

    def list_names(self):
        return []


def _decorator(*_args, **_kwargs):
    def decorate(function):
        return function

    return decorate


def _install_fake_dbus():
    dbus = types.ModuleType("dbus")
    dbus.__path__ = []
    dbus.Array = type(
        "Array",
        (list,),
        {"__init__": lambda self, value=(), **_kwargs: list.__init__(self, value)},
    )
    dbus.Dictionary = type(
        "Dictionary",
        (dict,),
        {"__init__": lambda self, value=(), **_kwargs: dict.__init__(self, value)},
    )
    dbus.Signature = _scalar_type("Signature", str)
    dbus.String = _scalar_type("String", str)
    dbus.Double = _scalar_type("Double", float)
    dbus.Boolean = _scalar_type("Boolean", int)
    dbus.Int16 = _scalar_type("Int16", int)
    dbus.UInt16 = _scalar_type("UInt16", int)
    dbus.Int32 = _scalar_type("Int32", int)
    dbus.UInt32 = _scalar_type("UInt32", int)
    dbus.Int64 = _scalar_type("Int64", int)
    dbus.UInt64 = _scalar_type("UInt64", int)
    dbus.Byte = _scalar_type("Byte", int)
    dbus.ByteArray = type("ByteArray", (bytes,), {})

    class DBusException(Exception):
        def get_dbus_name(self):
            return str(self)

    dbus.exceptions = types.SimpleNamespace(DBusException=DBusException)
    dbus.bus = types.SimpleNamespace(BusConnection=FakeBusConnection)
    dbus.SystemBus = FakeBusConnection
    dbus.SessionBus = FakeBusConnection

    service = types.ModuleType("dbus.service")
    service.Object = FakeObject
    service.BusName = FakeBusName
    service.method = _decorator
    service.signal = _decorator
    dbus.service = service

    mainloop = types.ModuleType("dbus.mainloop")
    mainloop.__path__ = []
    glib = types.ModuleType("dbus.mainloop.glib")
    glib.DBusGMainLoop = lambda *_args, **_kwargs: None
    mainloop.glib = glib
    dbus.mainloop = mainloop

    gi = types.ModuleType("gi")
    gi.__path__ = []
    gi_repository = types.ModuleType("gi.repository")
    gi_repository.GLib = types.SimpleNamespace(
        idle_add=lambda function, *args: function(*args)
    )
    gi.repository = gi_repository

    sys.modules.update(
        {
            "dbus": dbus,
            "dbus.service": service,
            "dbus.mainloop": mainloop,
            "dbus.mainloop.glib": glib,
            "gi": gi,
            "gi.repository": gi_repository,
        }
    )


class VelibPinContractTests(unittest.TestCase):
    def test_manifest_hashes_and_provenance_are_valid(self):
        manifest = VelibDependency.verify_bundled_velib()
        self.assertEqual("bundled-composite", manifest["selection"])
        self.assertEqual("v3.75", manifest["validated_venus_os"])
        self.assertEqual(
            EXPECTED_PROVENANCE,
            {
                filename: metadata["upstream_commit"]
                for filename, metadata in manifest["core_files"].items()
            },
        )

    def test_all_production_vedbus_imports_activate_the_pin(self):
        production_files = []
        for path in ROOT.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imports_vedbus = any(
                isinstance(node, ast.ImportFrom) and node.module == "vedbus"
                for node in ast.walk(tree)
            )
            if imports_vedbus:
                production_files.append(path)
                source = path.read_text(encoding="utf-8")
                self.assertIn(
                    "from VelibDependency import activate_velib_python", source
                )
                self.assertIn("activate_velib_python()", source)
                self.assertNotIn(
                    "/opt/victronenergy/dbus-systemcalc-py/ext/velib_python",
                    source,
                )

        self.assertEqual(11, len(production_files))

    def test_activation_rejects_an_external_preloaded_module(self):
        original = sys.modules.get("vedbus")
        external = types.ModuleType("vedbus")
        external.__file__ = "/opt/victronenergy/velib_python/vedbus.py"
        sys.modules["vedbus"] = external
        try:
            with self.assertRaisesRegex(RuntimeError, "mixed velib_python sources"):
                VelibDependency.activate_velib_python()
        finally:
            if original is None:
                sys.modules.pop("vedbus", None)
            else:
                sys.modules["vedbus"] = original

    def test_manifest_is_machine_readable_without_runtime_imports(self):
        manifest = json.loads(
            VelibDependency.PIN_MANIFEST_PATH.read_text(encoding="utf-8")
        )
        self.assertEqual(set(EXPECTED_PROVENANCE), set(manifest["core_files"]))
        self.assertIn(
            "The MIT License",
            (VelibDependency.BUNDLED_VELIB_PATH / "LICENSE").read_text(
                encoding="utf-8"
            ),
        )

    def test_bundled_directory_matches_its_pin(self):
        self.assertEqual(
            {filename: True for filename in EXPECTED_PROVENANCE},
            VelibDependency.compare_velib_directory(
                VelibDependency.BUNDLED_VELIB_PATH
            ),
        )


class BundledVelibCompatibilityTests(unittest.TestCase):
    MODULE_NAMES = (
        "dbus",
        "dbus.service",
        "dbus.mainloop",
        "dbus.mainloop.glib",
        "gi",
        "gi.repository",
        "ve_utils",
        "vedbus",
        "dbusmonitor",
    )

    def setUp(self):
        self.original_statvfs = getattr(os, "statvfs", None)
        os.statvfs = lambda _path: types.SimpleNamespace(f_frsize=1, f_bavail=1)
        self.original_modules = {
            name: sys.modules.get(name) for name in self.MODULE_NAMES
        }
        for name in self.MODULE_NAMES:
            sys.modules.pop(name, None)
        FakeBusConnection.instances = []
        _install_fake_dbus()
        VelibDependency.activate_velib_python()

    def tearDown(self):
        for name in self.MODULE_NAMES:
            sys.modules.pop(name, None)
        for name, module in self.original_modules.items():
            if module is not None:
                sys.modules[name] = module
        if self.original_statvfs is None:
            del os.statvfs
        else:
            os.statvfs = self.original_statvfs

    def test_service_registration_paths_and_writable_callback(self):
        from vedbus import VeDbusService

        bus = FakeBusConnection()
        accepted = []
        service = VeDbusService("com.victronenergy.test", bus=bus, register=False)
        item = service.add_path(
            "/Writable",
            6,
            writeable=True,
            onchangecallback=lambda path, value: accepted.append((path, value))
            or value <= 16,
        )
        service.add_path("/Nested/Value", 1)
        service.register()

        self.assertEqual("com.victronenergy.test", service.get_name())
        self.assertEqual("com.victronenergy.test", service._dbusname.name)
        self.assertEqual(0, item.SetValue(10))
        self.assertEqual(10, service["/Writable"])
        self.assertEqual(2, item.SetValue(20))
        self.assertEqual(10, service["/Writable"])
        self.assertEqual(
            {"/Writable", "/Nested/Value"}, set(service.root.GetItems())
        )
        self.assertEqual(
            [("/Writable", 10), ("/Writable", 20)], accepted
        )

    def test_dbus_monitor_subscribes_and_scans_with_stub_bus(self):
        from dbusmonitor import DbusMonitor

        monitor = DbusMonitor({"com.victronenergy.system": {"/Dc/Battery/Power": {}}})

        self.assertEqual({}, monitor.servicesByName)
        self.assertEqual({}, monitor.get_service_list())
        self.assertGreaterEqual(len(FakeBusConnection.instances), 2)
        self.assertTrue(
            any(
                kwargs.get("signal_name") == "PropertiesChanged"
                for bus in FakeBusConnection.instances
                for _callback, kwargs in bus.signal_receivers
            )
        )


if __name__ == "__main__":
    unittest.main()
