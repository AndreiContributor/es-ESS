import threading
import time

from Shelly3EMGen3Client import (
    Shelly3EMGen3ConnectionError,
    Shelly3EMGen3DeviceError,
    Shelly3EMGen3PayloadError,
)
from WattpilotSiteCurrentSource import (
    PHASES,
    SiteCurrentSnapshot,
    SiteCurrentSource,
)


class Shelly3EMSiteCurrentSource(SiteCurrentSource):
    source_name = "Shelly3EMGen3"
    identity_refresh_seconds = 300

    def __init__(self, client, phase_mapping, poll_frequency_ms=1000, clock=None):
        self.client = client
        self.phase_mapping = dict(phase_mapping)
        self.worker_interval_ms = int(poll_frequency_ms)
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._last_identity_at = 0
        self._snapshot = SiteCurrentSnapshot(self.source_name)

    def read_sample(self):
        with self._lock:
            return self._snapshot.copy()

    def _set_failure(self, status, error):
        with self._lock:
            snapshot = self._snapshot.copy()
            for phase in PHASES:
                snapshot.valid[phase] = False
            snapshot.connected = False
            snapshot.status = status
            snapshot.error = str(error)
            self._snapshot = snapshot

    def poll(self):
        now = self._clock()
        try:
            if (
                self._last_identity_at <= 0
                or now - self._last_identity_at >= self.identity_refresh_seconds
            ):
                info = self.client.identify()
                self._last_identity_at = now
            else:
                info = self.client.device_info or {}

            reading = self.client.read_currents()
            channel_currents = reading["currents"]
            values = {
                site_phase: channel_currents[channel]
                for channel, site_phase in self.phase_mapping.items()
            }
            if set(values) != set(PHASES):
                raise Shelly3EMGen3PayloadError(
                    "Shelly phase mapping must cover L1, L2, and L3"
                )

            snapshot = SiteCurrentSnapshot(
                source=self.source_name,
                values=values,
                valid={phase: True for phase in PHASES},
                updated_at={phase: now for phase in PHASES},
                connected=True,
                status="Healthy",
                error="",
                device_model=info.get("model", ""),
                firmware=info.get("ver", info.get("fw_id", "")),
            )
            with self._lock:
                self._snapshot = snapshot
            return True
        except Shelly3EMGen3ConnectionError as ex:
            self._set_failure("Unavailable", ex)
        except (Shelly3EMGen3DeviceError, Shelly3EMGen3PayloadError) as ex:
            self._set_failure("Invalid", ex)
        except Exception as ex:
            self._set_failure(
                "Invalid",
                "Unexpected Shelly source failure: {0}".format(
                    ex.__class__.__name__
                ),
            )
        return False

    def close(self):
        self.client.close()
