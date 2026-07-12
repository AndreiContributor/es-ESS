import tempfile
import unittest
from pathlib import Path

import RuntimeCompatibility as compatibility


class RuntimeCompatibilityTests(unittest.TestCase):
    def test_normalization_accepts_optional_v_prefix(self):
        self.assertEqual(compatibility.normalize_version("v3.73"), "3.73")
        self.assertEqual(compatibility.normalize_version(" 3.73 "), "3.73")
        self.assertTrue(compatibility.versions_match("v3.73", "3.73"))

    def test_qualifier_does_not_match_clean_release(self):
        self.assertFalse(compatibility.versions_match("v3.73~1", "v3.73"))
        self.assertFalse(compatibility.versions_match("v3.73-beta", "v3.73"))

    def test_missing_version_never_matches(self):
        self.assertFalse(compatibility.versions_match(None, "v3.73"))
        self.assertFalse(compatibility.versions_match("", "v3.73"))

    def test_reads_first_available_nonempty_version_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing"
            version = Path(temp_dir) / "version"
            version.write_text("\n v3.73 \n", encoding="utf-8")
            self.assertEqual(
                compatibility.read_venus_os_version((missing, version)),
                "v3.73",
            )

    def test_validated_venus_version_is_accepted(self):
        self.assertEqual(
            compatibility.require_validated_venus_os(actual="3.73"),
            "3.73",
        )

    def test_other_or_missing_venus_version_fails_closed(self):
        for actual in ("v3.74", "v3.73~1", None):
            with self.subTest(actual=actual):
                with self.assertRaises(compatibility.CompatibilityError):
                    compatibility.require_validated_venus_os(
                        actual=actual,
                        paths=(),
                    )

    def test_wattpilot_firmware_requires_exact_validated_release(self):
        self.assertTrue(compatibility.wattpilot_firmware_is_validated("42.5"))
        self.assertFalse(compatibility.wattpilot_firmware_is_validated("42.6"))
        self.assertFalse(compatibility.wattpilot_firmware_is_validated(None))


if __name__ == "__main__":
    unittest.main()
