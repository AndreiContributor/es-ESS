import sys
import types
import unittest
from unittest.mock import Mock, patch

from Shelly3EMGen3Client import (
    Shelly3EMGen3Client,
    Shelly3EMGen3ConnectionError,
    Shelly3EMGen3DeviceError,
    Shelly3EMGen3PayloadError,
)


class RequestException(Exception):
    pass


class Timeout(RequestException):
    pass


class FakeHTTPDigestAuth:
    def __init__(self, username, password):
        self.username = username
        self.password = password


REQUESTS = types.ModuleType("requests")
REQUESTS.Session = Mock
REQUESTS.exceptions = types.SimpleNamespace(
    RequestException=RequestException,
    Timeout=Timeout,
)
REQUESTS_AUTH = types.ModuleType("requests.auth")
REQUESTS_AUTH.HTTPDigestAuth = FakeHTTPDigestAuth
REQUEST_MODULES = {
    "requests": REQUESTS,
    "requests.auth": REQUESTS_AUTH,
}


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error is not None:
            raise self.status_error

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def device_info(**overrides):
    payload = {
        "id": "shelly3em63g3-test",
        "model": "S3EM-003CXCEU63",
        "gen": 3,
        "profile": "triphase",
        "auth_en": False,
        "ver": "1.7.0",
    }
    payload.update(overrides)
    return payload


def em_status(**overrides):
    payload = {
        "id": 0,
        "a_current": 1.25,
        "b_current": 2.5,
        "c_current": 0,
        "a_errors": [],
        "b_errors": [],
        "c_errors": [],
        "errors": [],
        "a_flags": [],
        "b_flags": ["overcurrent"],
        "c_flags": [],
    }
    payload.update(overrides)
    return payload


class Shelly3EMGen3ClientTests(unittest.TestCase):
    def _client(self, responses, password=""):
        session = Mock()
        session.get.side_effect = [FakeResponse(value) for value in responses]
        with patch.dict(sys.modules, REQUEST_MODULES):
            client = Shelly3EMGen3Client(
                "192.0.2.40",
                password=password,
                timeout_seconds=2,
                session=session,
            )
        return client, session

    def test_identifies_expected_gen3_triphase_device(self):
        client, session = self._client([device_info()])

        result = client.identify()

        self.assertEqual(result["model"], "S3EM-003CXCEU63")
        self.assertEqual(
            session.get.call_args.args[0], "http://192.0.2.40/shelly"
        )
        self.assertNotIn("auth", session.get.call_args.kwargs)
        self.assertNotIn("@", session.get.call_args.args[0])

    def test_auth_enabled_requires_configured_password(self):
        client, _session = self._client([device_info(auth_en=True)])

        with self.assertRaisesRegex(Shelly3EMGen3DeviceError, "no password"):
            client.identify()

    def test_wrong_generation_model_or_profile_is_rejected(self):
        cases = (
            device_info(gen=2),
            device_info(model="SPEM-003CEBEU120"),
            device_info(profile="monophase"),
        )
        for payload in cases:
            with self.subTest(payload=payload):
                client, _session = self._client([payload])
                with self.assertRaises(Shelly3EMGen3DeviceError):
                    client.identify()

    def test_reads_complete_currents_and_keeps_alarm_flags_diagnostic(self):
        client, session = self._client([em_status()])

        result = client.read_currents()

        self.assertEqual(result["currents"], {"A": 1.25, "B": 2.5, "C": 0.0})
        self.assertEqual(result["flags"]["B"], ["overcurrent"])
        request = session.get.call_args
        self.assertEqual(
            request.args[0], "http://192.0.2.40/rpc/EM.GetStatus?id=0"
        )
        self.assertEqual(request.kwargs["timeout"], 2.0)
        self.assertIn("auth", request.kwargs)

    def test_component_and_phase_errors_are_rejected(self):
        for payload in (
            em_status(errors=["phase_sequence"]),
            em_status(b_errors=["out_of_range:current"]),
        ):
            with self.subTest(payload=payload):
                client, _session = self._client([payload])
                with self.assertRaises(Shelly3EMGen3DeviceError):
                    client.read_currents()

    def test_missing_negative_nonfinite_and_wrong_component_are_rejected(self):
        for payload in (
            em_status(a_current=None),
            em_status(b_current=-1),
            em_status(c_current=float("nan")),
            em_status(id=1),
        ):
            with self.subTest(payload=payload):
                client, _session = self._client([payload])
                with self.assertRaises(Shelly3EMGen3PayloadError):
                    client.read_currents()

    def test_network_and_json_failures_are_classified(self):
        session = Mock()
        session.get.side_effect = Timeout("secret")
        with patch.dict(sys.modules, REQUEST_MODULES):
            client = Shelly3EMGen3Client("192.0.2.40", session=session)
        with self.assertRaises(Shelly3EMGen3ConnectionError) as raised:
            client.identify()
        self.assertNotIn("secret", str(raised.exception))

        client, _session = self._client([ValueError("invalid json")])
        with self.assertRaises(Shelly3EMGen3PayloadError):
            client.identify()

    def test_host_rejects_urls_paths_and_credentials(self):
        for host in (
            "",
            "http://192.0.2.40",
            "admin:password@192.0.2.40",
            "192.0.2.40/rpc",
        ):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    Shelly3EMGen3Client(host)


if __name__ == "__main__":
    unittest.main()
