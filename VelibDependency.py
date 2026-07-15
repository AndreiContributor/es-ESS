"""Deterministic activation and integrity checks for bundled velib_python."""

import hashlib
import json
from pathlib import Path
import sys


APP_ROOT = Path(__file__).resolve().parent
BUNDLED_VELIB_PATH = APP_ROOT / "velib_python-master"
PIN_MANIFEST_PATH = BUNDLED_VELIB_PATH / "PINNED.json"
CORE_MODULES = ("vedbus", "dbusmonitor", "settingsdevice", "ve_utils")

_verified_manifest = None


def _canonical_sha256(path):
    """Hash text with stable LF newlines on both GX and Windows checkouts."""
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def _is_within(path, directory):
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def verify_bundled_velib():
    """Verify the pinned core files and return the parsed provenance manifest."""
    global _verified_manifest
    if _verified_manifest is not None:
        return _verified_manifest

    if not BUNDLED_VELIB_PATH.is_dir():
        raise RuntimeError(
            "Pinned velib_python directory is missing: {0}".format(
                BUNDLED_VELIB_PATH
            )
        )
    if not PIN_MANIFEST_PATH.is_file():
        raise RuntimeError(
            "Pinned velib_python manifest is missing: {0}".format(
                PIN_MANIFEST_PATH
            )
        )

    try:
        manifest = json.loads(PIN_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "Pinned velib_python manifest is unreadable: {0}".format(exc)
        ) from exc

    if manifest.get("schema_version") != 1:
        raise RuntimeError("Unsupported velib_python pin manifest schema")

    files = manifest.get("core_files")
    if not isinstance(files, dict) or set(files) != set(
        "{0}.py".format(name) for name in CORE_MODULES
    ):
        raise RuntimeError("Pinned velib_python manifest has an invalid core file set")

    for filename, metadata in files.items():
        path = BUNDLED_VELIB_PATH / filename
        expected = metadata.get("canonical_sha256") if isinstance(metadata, dict) else None
        if not path.is_file() or not isinstance(expected, str):
            raise RuntimeError(
                "Pinned velib_python file or hash is missing: {0}".format(filename)
            )
        actual = _canonical_sha256(path)
        if actual != expected:
            raise RuntimeError(
                "Pinned velib_python integrity check failed for {0}: "
                "expected {1}, got {2}".format(filename, expected, actual)
            )

    _verified_manifest = manifest
    return manifest


def activate_velib_python():
    """Make the verified bundled dependency the sole permitted import source."""
    manifest = verify_bundled_velib()

    for module_name in CORE_MODULES:
        module = sys.modules.get(module_name)
        origin = getattr(module, "__file__", None) if module is not None else None
        if origin is not None and not _is_within(Path(origin), BUNDLED_VELIB_PATH):
            raise RuntimeError(
                "Refusing mixed velib_python sources: {0} is already loaded from {1}".format(
                    module_name, origin
                )
            )

    bundled = str(BUNDLED_VELIB_PATH)
    sys.path[:] = [entry for entry in sys.path if entry != bundled]
    sys.path.insert(0, bundled)
    return manifest


def compare_velib_directory(directory):
    """Compare another velib_python directory without selecting or importing it."""
    manifest = verify_bundled_velib()
    directory = Path(directory)
    comparison = {}
    for filename, metadata in manifest["core_files"].items():
        candidate = directory / filename
        comparison[filename] = (
            None
            if not candidate.is_file()
            else _canonical_sha256(candidate) == metadata["canonical_sha256"]
        )
    return comparison


def loaded_module_origins():
    """Return observable core-module origins for read-only diagnostics."""
    return {
        name: getattr(sys.modules.get(name), "__file__", None)
        for name in CORE_MODULES
    }
