"""Hardware-free regressions for the Wattpilot WebSocket client lifecycle."""

import importlib.util
import json
import sys
import threading
import types
import unittest
from enum import Enum
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeWebSocketApp:
    instances = []
    block_run = False
    run_started = threading.Event()
    release_run = threading.Event()
    second_run_started = threading.Event()

    @classmethod
    def reset(cls):
        cls.instances = []
        cls.block_run = False
        cls.run_started = threading.Event()
        cls.release_run = threading.Event()
        cls.second_run_started = threading.Event()

    def __init__(self, *_args, **kwargs):
        self.closed = False
        self.run_forever_calls = 0
        self.on_close = kwargs.get("on_close")
        FakeWebSocketApp.instances.append(self)

    def run_forever(self):
        self.run_forever_calls += 1
        FakeWebSocketApp.run_started.set()
        if self.run_forever_calls == 1 and self.on_close is not None:
            self.on_close(self, 1006, "closed")
        if self.run_forever_calls >= 2:
            FakeWebSocketApp.second_run_started.set()
        if FakeWebSocketApp.block_run:
            FakeWebSocketApp.release_run.wait(1)
        return None

    def close(self):
        self.closed = True

    def send(self, _message):
        return None


def _install_wattpilot_client_stubs(info_messages=None, debug_messages=None):
    FakeWebSocketApp.reset()
    info_messages = info_messages if info_messages is not None else []
    debug_messages = debug_messages if debug_messages is not None else []

    _module(
        "websocket",
        setdefaulttimeout=lambda _timeout: None,
        WebSocketApp=FakeWebSocketApp,
    )
    _module(
        "Helper",
        i=lambda _module, message, **_kwargs: info_messages.append(message),
        c=lambda *args, **kwargs: None,
        d=lambda _module, message, **_kwargs: debug_messages.append(message),
        w=lambda *args, **kwargs: None,
        e=lambda *args, **kwargs: None,
        t=lambda *args, **kwargs: None,
    )

    class WattpilotStartStop(Enum):
        Neutral = 0
        Off = 1
        On = 2

    class WattpilotControlMode(Enum):
        Default = 3
        ECO = 4

    class WattpilotModelStatus(Enum):
        Idle = 1

    _module(
        "enums",
        WattpilotModelStatus=WattpilotModelStatus,
        WattpilotStartStop=WattpilotStartStop,
        WattpilotControlMode=WattpilotControlMode,
    )


class WattpilotClientLifecycleTests(unittest.TestCase):
    def load_wattpilot_module(self, module_name):
        return _load_module(module_name, ROOT / "Wattpilot.py")

    def test_connect_starts_only_one_worker(self):
        info_messages = []
        debug_messages = []
        _install_wattpilot_client_stubs(info_messages, debug_messages)
        wattpilot_module = self.load_wattpilot_module(
            "wattpilot_client_idempotent_connect_under_test"
        )
        FakeWebSocketApp.block_run = True
        client = wattpilot_module.Wattpilot("127.0.0.1", "secret")

        client.connect()
        self.assertTrue(FakeWebSocketApp.run_started.wait(1))
        first_worker = client._wst

        client.connect()

        self.assertIs(client._wst, first_worker)
        self.assertEqual(FakeWebSocketApp.instances[0].run_forever_calls, 1)
        self.assertEqual(
            info_messages.count("Wattpilot WebSocket worker started"), 1
        )
        self.assertIn("Wattpilot WebSocket worker already running.", debug_messages)

        client.disconnect(auto_reconnect=False)
        FakeWebSocketApp.release_run.set()
        first_worker.join(1)
        self.assertFalse(first_worker.is_alive())

    def test_close_callback_does_not_call_run_forever_recursively(self):
        _install_wattpilot_client_stubs()
        wattpilot_module = self.load_wattpilot_module(
            "wattpilot_client_close_callback_under_test"
        )
        client = wattpilot_module.Wattpilot("127.0.0.1", "secret")
        close_events = []
        client.add_event_handler(
            wattpilot_module.Event.WS_CLOSE,
            lambda _event, _wsapp, code, msg: close_events.append((code, msg)),
        )

        client._Wattpilot__on_close(client._wsapp, 1000, "normal close")

        self.assertEqual(FakeWebSocketApp.instances[0].run_forever_calls, 0)
        self.assertEqual(close_events, [(1000, "normal close")])
        self.assertFalse(client.connected)

    def test_reconnect_runs_from_worker_loop_after_close_event(self):
        _install_wattpilot_client_stubs()
        wattpilot_module = self.load_wattpilot_module(
            "wattpilot_client_worker_reconnect_under_test"
        )
        client = wattpilot_module.Wattpilot("127.0.0.1", "secret")
        client._reconnect_interval = 0.01

        client.connect()

        self.assertTrue(FakeWebSocketApp.second_run_started.wait(1))
        self.assertGreaterEqual(FakeWebSocketApp.instances[0].run_forever_calls, 2)

        worker = client._wst
        client.disconnect(auto_reconnect=False)
        worker.join(1)
        self.assertFalse(worker.is_alive())

    def test_disconnect_without_auto_reconnect_stops_worker_loop(self):
        _install_wattpilot_client_stubs()
        wattpilot_module = self.load_wattpilot_module(
            "wattpilot_client_disconnect_stop_under_test"
        )
        client = wattpilot_module.Wattpilot("127.0.0.1", "secret")
        client._reconnect_interval = 30

        client.connect()
        self.assertTrue(FakeWebSocketApp.run_started.wait(1))

        worker = client._wst
        client.disconnect(auto_reconnect=False)
        worker.join(1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(FakeWebSocketApp.instances[0].run_forever_calls, 1)
        self.assertTrue(FakeWebSocketApp.instances[0].closed)

    def test_null_awattar_current_price_does_not_break_status_parsing(self):
        _install_wattpilot_client_stubs()
        wattpilot_module = self.load_wattpilot_module(
            "wattpilot_client_null_awattar_status_under_test"
        )
        client = wattpilot_module.Wattpilot("127.0.0.1", "secret")
        client._awattarCurrentPrice = 12.34

        client._Wattpilot__on_message(
            client._wsapp,
            json.dumps(
                {
                    "type": "fullStatus",
                    "partial": False,
                    "status": {"awcp": None},
                }
            ),
        )

        self.assertEqual(client.awattarCurrentPrice, 12.34)
        self.assertTrue(client.allPropsInitialized)

    def test_awattar_current_price_updates_when_marketprice_is_present(self):
        _install_wattpilot_client_stubs()
        wattpilot_module = self.load_wattpilot_module(
            "wattpilot_client_awattar_status_under_test"
        )
        client = wattpilot_module.Wattpilot("127.0.0.1", "secret")

        client._Wattpilot__on_message(
            client._wsapp,
            json.dumps(
                {
                    "type": "fullStatus",
                    "partial": False,
                    "status": {"awcp": {"marketprice": 0.42}},
                }
            ),
        )

        self.assertEqual(client.awattarCurrentPrice, 0.42)

    def test_command_guard_blocks_every_state_changing_update(self):
        _install_wattpilot_client_stubs()
        wattpilot_module = self.load_wattpilot_module(
            "wattpilot_client_command_guard_block_under_test"
        )
        client = wattpilot_module.Wattpilot("127.0.0.1", "secret")
        sent = []
        client._wsapp.send = lambda message: sent.append(message)
        client.set_command_guard(lambda _name, _value: False)

        self.assertFalse(client.send_update("amp", 6))
        self.assertFalse(client.send_update("frc", 2))
        self.assertFalse(client.send_update("psm", 1))
        self.assertFalse(client.send_update("lmo", 4))

        self.assertEqual(sent, [])
        self.assertEqual(client._Wattpilot__requestid, 0)

    def test_command_guard_allows_update_after_compatibility_confirmation(self):
        _install_wattpilot_client_stubs()
        wattpilot_module = self.load_wattpilot_module(
            "wattpilot_client_command_guard_allow_under_test"
        )
        client = wattpilot_module.Wattpilot("127.0.0.1", "secret")
        sent = []
        client._wsapp.send = lambda message: sent.append(message)
        client.set_command_guard(lambda name, value: name == "amp" and value == 6)

        self.assertTrue(client.send_update("amp", 6))

        self.assertEqual(len(sent), 1)
        self.assertEqual(client._Wattpilot__requestid, 1)


if __name__ == "__main__":
    unittest.main()
