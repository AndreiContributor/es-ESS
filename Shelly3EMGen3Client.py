import math
from urllib.parse import urlsplit


EXPECTED_MODEL = "S3EM-003CXCEU63"
EXPECTED_GENERATION = 3
EXPECTED_PROFILE = "triphase"


class Shelly3EMGen3Error(Exception):
    pass


class Shelly3EMGen3ConnectionError(Shelly3EMGen3Error):
    pass


class Shelly3EMGen3PayloadError(Shelly3EMGen3Error):
    pass


class Shelly3EMGen3DeviceError(Shelly3EMGen3Error):
    pass


def _finite_non_negative(value, field):
    if isinstance(value, bool):
        raise Shelly3EMGen3PayloadError("{0} is not a number".format(field))
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise Shelly3EMGen3PayloadError("{0} is not a number".format(field))
    if not math.isfinite(numeric) or numeric < 0:
        raise Shelly3EMGen3PayloadError(
            "{0} must be finite and non-negative".format(field)
        )
    return numeric


def _string_list(payload, field):
    value = payload.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        raise Shelly3EMGen3PayloadError("{0} must be a string list".format(field))
    return list(value)


class Shelly3EMGen3Client:
    """Bounded, read-only local RPC client for Shelly 3EM Gen3."""

    def __init__(
        self,
        host,
        username="admin",
        password="",
        timeout_seconds=2.0,
        session=None,
    ):
        self.host = self._validate_host(host)
        self.username = str(username)
        self.password = str(password)
        self.timeout_seconds = float(timeout_seconds)
        import requests  # type: ignore
        self.session = session or requests.Session()
        from requests.auth import HTTPDigestAuth  # type: ignore

        self._requests = requests
        self._digest_auth = HTTPDigestAuth(self.username, self.password)
        self.device_info = None

    @staticmethod
    def _validate_host(host):
        value = str(host).strip()
        if not value:
            raise ValueError("Shelly host is required")
        parsed = urlsplit("//{0}".format(value))
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
        ):
            raise ValueError("Shelly host must be an IP address or hostname")
        return value.rstrip("/")

    @property
    def base_url(self):
        return "http://{0}".format(self.host)

    def _get_json(self, path, authenticated):
        kwargs = {"timeout": self.timeout_seconds}
        if authenticated:
            kwargs["auth"] = self._digest_auth
        try:
            response = self.session.get(self.base_url + path, **kwargs)
            response.raise_for_status()
            payload = response.json()
        except self._requests.exceptions.RequestException as ex:
            raise Shelly3EMGen3ConnectionError(
                "Shelly RPC request failed: {0}".format(ex.__class__.__name__)
            )
        except ValueError:
            raise Shelly3EMGen3PayloadError("Shelly RPC response is not valid JSON")
        if not isinstance(payload, dict):
            raise Shelly3EMGen3PayloadError("Shelly RPC response is not an object")
        return payload

    def identify(self):
        info = self._get_json("/shelly", authenticated=False)
        if info.get("gen") != EXPECTED_GENERATION:
            raise Shelly3EMGen3DeviceError("Unexpected Shelly generation")
        if info.get("model") != EXPECTED_MODEL:
            raise Shelly3EMGen3DeviceError("Unexpected Shelly model")
        if info.get("profile") != EXPECTED_PROFILE:
            raise Shelly3EMGen3DeviceError("Shelly must use the triphase profile")
        if info.get("auth_en") is True and not self.password:
            raise Shelly3EMGen3DeviceError(
                "Shelly authentication is enabled but no password is configured"
            )
        self.device_info = dict(info)
        return dict(info)

    def read_currents(self):
        status = self._get_json(
            "/rpc/EM.GetStatus?id=0",
            authenticated=True,
        )
        if status.get("id") != 0:
            raise Shelly3EMGen3PayloadError("Unexpected EM component id")

        component_errors = _string_list(status, "errors")
        phase_errors = {
            phase: _string_list(status, "{0}_errors".format(phase))
            for phase in ("a", "b", "c")
        }
        all_errors = list(component_errors)
        for phase in ("a", "b", "c"):
            all_errors.extend(phase_errors[phase])
        if all_errors:
            raise Shelly3EMGen3DeviceError(
                "Shelly EM reports errors: {0}".format(", ".join(all_errors))
            )

        currents = {
            phase.upper(): _finite_non_negative(
                status.get("{0}_current".format(phase)),
                "{0}_current".format(phase),
            )
            for phase in ("a", "b", "c")
        }
        flags = {
            phase.upper(): _string_list(status, "{0}_flags".format(phase))
            for phase in ("a", "b", "c")
        }
        return {
            "currents": currents,
            "flags": flags,
            "raw": status,
        }

    def close(self):
        close = getattr(self.session, "close", None)
        if callable(close):
            close()
