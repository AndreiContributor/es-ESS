"""Check orchestration against the installed Paho client without Venus imports."""

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# Some legacy tests replace subprocess.run on the shared module object.
RUN_SUBPROCESS = subprocess.run


class PahoClientContractTests(unittest.TestCase):
    def test_reconnect_and_connection_status_use_real_client_method_spec(self):
        # Other hardware-free tests replace paho in sys.modules. Use a fresh
        # interpreter so this test always sees the installed package.
        script = textwrap.dedent(
            """
            from unittest.mock import Mock, patch
            from paho.mqtt.client import Client
            from tests.test_es_ess_mqtt_orchestration import EsEssMqttOrchestrationTests

            assert callable(Client.reconnect)
            assert callable(Client.is_connected)
            EsEssMqttOrchestrationTests.setUpClass()
            case = EsEssMqttOrchestrationTests()
            app = case._app()
            app.mainMqttClient = Mock(spec_set=Client)
            app.localMqttClient = Mock(spec_set=Client)
            app.mainMqttClient.is_connected.return_value = True
            assert app._isMqttClientConnected(app.mainMqttClient)
            app.mainMqttClient.is_connected.assert_called_once_with()

            with patch.object(case.es_ess, "i"), patch.object(case.es_ess, "w"):
                app.onMainMqttDisconnect(None, None, 1)
                app.onLocalMqttDisconnect(None, None, 1)
            assert callable(app.mainMqttClient.reconnect)
            assert callable(app.localMqttClient.reconnect)
            """
        )
        environment = os.environ.copy()
        result = RUN_SUBPROCESS(
            [sys.executable, "-B", "-c", script],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
