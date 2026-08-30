import math
import threading
import time


PHASES = ("L1", "L2", "L3")


class SiteCurrentSnapshot:
    """Immutable-by-convention normalized site-current provider snapshot."""

    def __init__(
        self,
        source,
        values=None,
        valid=None,
        updated_at=None,
        connected=False,
        status="Initializing",
        error="",
        device_model="",
        firmware="",
    ):
        self.source = str(source)
        self.values = dict(values or {phase: None for phase in PHASES})
        self.valid = dict(valid or {phase: False for phase in PHASES})
        self.updated_at = dict(updated_at or {phase: 0 for phase in PHASES})
        self.connected = bool(connected)
        self.status = str(status)
        self.error = str(error)
        self.device_model = str(device_model)
        self.firmware = str(firmware)

    def copy(self):
        return SiteCurrentSnapshot(
            source=self.source,
            values=self.values,
            valid=self.valid,
            updated_at=self.updated_at,
            connected=self.connected,
            status=self.status,
            error=self.error,
            device_model=self.device_model,
            firmware=self.firmware,
        )

    @property
    def last_sample_at(self):
        timestamps = [
            timestamp
            for timestamp in self.updated_at.values()
            if isinstance(timestamp, (int, float)) and timestamp > 0
        ]
        return min(timestamps) if timestamps else 0


def finite_non_negative(value):
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric < 0:
        return None
    return numeric


class SiteCurrentSource:
    """Small provider boundary consumed by the Wattpilot controller."""

    source_name = "Unknown"
    worker_interval_ms = None

    def read_sample(self):
        raise NotImplementedError

    def poll(self):
        return None


class VenusSystemSiteCurrentSource(SiteCurrentSource):
    """Live-read the existing Venus system consumption-current paths."""

    source_name = "VenusSystem"

    def __init__(self, subscriptions, read_subscription, clock=None):
        self._subscriptions = dict(subscriptions)
        self._read_subscription = read_subscription
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._snapshot = SiteCurrentSnapshot(self.source_name)

    def read_sample(self):
        now = self._clock()
        with self._lock:
            snapshot = self._snapshot.copy()

        transport_failed = False
        invalid_sample = False
        for phase in PHASES:
            subscription = self._subscriptions.get(phase)
            if subscription is None:
                snapshot.valid[phase] = False
                transport_failed = True
                continue

            try:
                success, value = self._read_subscription(subscription)
            except Exception:
                success, value = False, None

            if not success:
                snapshot.valid[phase] = False
                transport_failed = True
                continue

            numeric = finite_non_negative(value)
            snapshot.values[phase] = numeric
            snapshot.valid[phase] = numeric is not None
            snapshot.updated_at[phase] = now
            invalid_sample = invalid_sample or numeric is None

        if transport_failed:
            snapshot.connected = False
            snapshot.status = "Unavailable"
            snapshot.error = "Venus site-current live read failed"
        elif invalid_sample:
            snapshot.connected = True
            snapshot.status = "Invalid"
            snapshot.error = "Venus site-current sample is invalid"
        else:
            snapshot.connected = True
            snapshot.status = "Healthy"
            snapshot.error = ""

        with self._lock:
            self._snapshot = snapshot
            return snapshot.copy()
