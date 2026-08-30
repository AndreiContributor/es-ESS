import unittest
from unittest.mock import Mock

from Shelly3EMGen3Client import (
    Shelly3EMGen3ConnectionError,
    Shelly3EMGen3DeviceError,
)
from Shelly3EMSiteCurrent import Shelly3EMSiteCurrentSource
from WattpilotSiteCurrentSource import VenusSystemSiteCurrentSource


class Shelly3EMSiteCurrentSourceTests(unittest.TestCase):
    def _source(self, client, clock):
        return Shelly3EMSiteCurrentSource(
            client,
            {"A": "L3", "B": "L1", "C": "L2"},
            poll_frequency_ms=1000,
            clock=clock,
        )

    def test_complete_poll_maps_channels_and_timestamps_all_phases(self):
        client = Mock()
        client.identify.return_value = {
            "model": "S3EM-003CXCEU63",
            "ver": "1.7.0",
        }
        client.read_currents.return_value = {
            "currents": {"A": 3.0, "B": 1.0, "C": 2.0},
            "flags": {"A": [], "B": [], "C": []},
        }
        source = self._source(client, lambda: 100.0)

        self.assertTrue(source.poll())
        sample = source.read_sample()

        self.assertEqual(sample.values, {"L1": 1.0, "L2": 2.0, "L3": 3.0})
        self.assertEqual(sample.updated_at, {"L1": 100.0, "L2": 100.0, "L3": 100.0})
        self.assertTrue(all(sample.valid.values()))
        self.assertTrue(sample.connected)
        self.assertEqual(sample.status, "Healthy")
        self.assertEqual(sample.device_model, "S3EM-003CXCEU63")

    def test_failed_poll_invalidates_without_refreshing_cached_sample_age(self):
        now = [100.0]
        client = Mock()
        client.identify.return_value = {
            "model": "S3EM-003CXCEU63",
            "ver": "1.7.0",
        }
        client.read_currents.return_value = {
            "currents": {"A": 3.0, "B": 1.0, "C": 2.0},
            "flags": {"A": [], "B": [], "C": []},
        }
        source = self._source(client, lambda: now[0])
        self.assertTrue(source.poll())

        now[0] = 101.0
        client.read_currents.side_effect = Shelly3EMGen3ConnectionError("down")
        self.assertFalse(source.poll())
        sample = source.read_sample()

        self.assertEqual(sample.values, {"L1": 1.0, "L2": 2.0, "L3": 3.0})
        self.assertEqual(sample.updated_at, {"L1": 100.0, "L2": 100.0, "L3": 100.0})
        self.assertFalse(any(sample.valid.values()))
        self.assertFalse(sample.connected)
        self.assertEqual(sample.status, "Unavailable")

    def test_invalid_device_failure_is_fail_closed(self):
        client = Mock()
        client.identify.side_effect = Shelly3EMGen3DeviceError("wrong device")
        source = self._source(client, lambda: 100.0)

        self.assertFalse(source.poll())

        sample = source.read_sample()
        self.assertEqual(sample.status, "Invalid")
        self.assertFalse(any(sample.valid.values()))
        client.read_currents.assert_not_called()

    def test_identity_is_refreshed_periodically(self):
        now = [100.0]
        client = Mock()
        client.identify.return_value = {
            "model": "S3EM-003CXCEU63",
            "ver": "1.7.0",
        }
        client.device_info = client.identify.return_value
        client.read_currents.return_value = {
            "currents": {"A": 1, "B": 2, "C": 3},
            "flags": {"A": [], "B": [], "C": []},
        }
        source = self._source(client, lambda: now[0])

        source.poll()
        now[0] = 200.0
        source.poll()
        now[0] = 401.0
        source.poll()

        self.assertEqual(client.identify.call_count, 2)

    def test_snapshot_copy_cannot_mutate_provider_state(self):
        client = Mock()
        source = self._source(client, lambda: 100.0)
        first = source.read_sample()
        first.values["L1"] = 99

        self.assertIsNone(source.read_sample().values["L1"])


class VenusSystemSiteCurrentSourceTests(unittest.TestCase):
    def test_live_reads_refresh_unchanged_zero_and_nonzero_values(self):
        subscriptions = {
            "L1": Mock(value=0),
            "L2": Mock(value=1.5),
            "L3": Mock(value=0),
        }
        source = VenusSystemSiteCurrentSource(
            subscriptions,
            lambda subscription: (True, subscription.value),
            clock=lambda: 200.0,
        )

        sample = source.read_sample()

        self.assertEqual(sample.values, {"L1": 0.0, "L2": 1.5, "L3": 0.0})
        self.assertEqual(sample.updated_at, {"L1": 200.0, "L2": 200.0, "L3": 200.0})
        self.assertTrue(all(sample.valid.values()))

    def test_failed_phase_read_invalidates_and_preserves_its_age(self):
        now = [100.0]
        subscriptions = {
            "L1": Mock(value=1),
            "L2": Mock(value=2),
            "L3": Mock(value=3),
        }

        def read(subscription):
            if now[0] == 200.0 and subscription is subscriptions["L3"]:
                return False, None
            return True, subscription.value

        source = VenusSystemSiteCurrentSource(
            subscriptions, read, clock=lambda: now[0]
        )
        source.read_sample()
        now[0] = 200.0

        sample = source.read_sample()

        self.assertFalse(sample.valid["L3"])
        self.assertEqual(sample.updated_at["L3"], 100.0)
        self.assertEqual(sample.updated_at["L1"], 200.0)
        self.assertEqual(sample.status, "Unavailable")


if __name__ == "__main__":
    unittest.main()
