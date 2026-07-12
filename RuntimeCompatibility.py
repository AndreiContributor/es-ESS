"""Approved runtime-version baseline for es-ESS.

The Wattpilot control protocol and Venus OS integration surfaces are not a
stable public API. Keep the explicitly approved versions in one auditable place
and fail closed when a running system differs. A newly approved migration
target still requires the repository's documented live GX validation.

The Solar.wattpilot mobile application is not part of the local WebSocket
connection and does not expose its version to es-ESS.  Its version is therefore
an operator-verified commissioning baseline only.
"""

from __future__ import annotations

import os


# Keep every release that has an approved rollback path in this explicit set.
# Exact comparison remains intentional: beta/build qualifiers are not accepted.
VALIDATED_VENUS_OS_VERSION = "v3.73"
VALIDATED_VENUS_OS_VERSIONS = (
    VALIDATED_VENUS_OS_VERSION,
    "v3.75",
)
VALIDATED_VENUS_OS_VERSIONS_LITERAL = ", ".join(VALIDATED_VENUS_OS_VERSIONS)
VALIDATED_WATTPILOT_FIRMWARE = "42.5"
VALIDATED_WATTPILOT_APP_VERSION = "2.1.0"

VENUS_OS_VERSION_PATHS = (
    "/opt/victronenergy/version",
    "/etc/venus/version",
)


class CompatibilityError(RuntimeError):
    """Raised when the runtime is outside the validated compatibility set."""


def normalize_version(value):
    """Return a comparison-safe version string without a leading ``v``.

    Qualifiers such as ``~1`` or ``-beta`` are deliberately retained so a beta
    or patch candidate cannot silently match a validated clean release.
    """
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if normalized[:1].lower() == "v":
        normalized = normalized[1:]
    return normalized or None


def versions_match(actual, expected):
    actual_normalized = normalize_version(actual)
    expected_normalized = normalize_version(expected)
    return (
        actual_normalized is not None
        and expected_normalized is not None
        and actual_normalized == expected_normalized
    )


def version_matches_any(actual, expected_versions):
    """Return whether ``actual`` exactly matches one approved clean release."""
    return any(versions_match(actual, expected) for expected in expected_versions)


def read_venus_os_version(paths=None):
    """Read the installed Venus OS version from the first available file."""
    candidates = VENUS_OS_VERSION_PATHS if paths is None else tuple(paths)
    for path in candidates:
        try:
            if not os.path.isfile(path):
                continue
            with open(path, "r") as version_file:
                for line in version_file:
                    value = line.strip()
                    if value:
                        return value
        except (IOError, OSError):
            continue
    return None


def require_validated_venus_os(actual=None, paths=None):
    """Return the detected version or raise before es-ESS changes GX state."""
    detected = actual if actual is not None else read_venus_os_version(paths)
    if not version_matches_any(detected, VALIDATED_VENUS_OS_VERSIONS):
        raise CompatibilityError(
            "Unsupported Venus OS version {0}; es-ESS supports only {1}. "
            "No services or grid-setpoint writes were started.".format(
                detected if detected is not None else "<unavailable>",
                VALIDATED_VENUS_OS_VERSIONS_LITERAL,
            )
        )
    return detected


def wattpilot_firmware_is_validated(actual):
    return versions_match(actual, VALIDATED_WATTPILOT_FIRMWARE)
