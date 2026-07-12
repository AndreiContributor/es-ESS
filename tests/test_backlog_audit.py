import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / ".agents"
    / "skills"
    / "maintain-es-ess-backlog"
    / "scripts"
    / "backlog_audit.py"
)
SPEC = importlib.util.spec_from_file_location("backlog_audit", SCRIPT)
backlog_audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(backlog_audit)


VALID_BACKLOG = """# Backlog

## Current App Analysis
Current state.

## Review Questions And Assumptions
No questions.

## Completed

### Completed 2026-01-01 - Example

- Preserved a durable implementation decision with verification evidence.

## Backlog

### P4 - Example Open Item

Goal and implementation details remain open.

## Suggested Implementation Order / PR Execution Queue
1. P4 example.

## Verification Plan
Run checks.

## Outstanding Manual Validation
- Hardware not needed.
"""


class BacklogAuditTests(unittest.TestCase):
    def _write_backlog(self, text=VALID_BACKLOG):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "BACKLOG.md"
        path.write_text(text, encoding="utf-8")
        self.addCleanup(directory.cleanup)
        return path

    def test_current_repository_backlog_passes(self):
        result = backlog_audit.audit(ROOT / "BACKLOG.md")

        self.assertEqual([], result["missing_required_sections"])
        self.assertEqual([], result["duplicate_tracked_headings"])
        self.assertGreater(result["average_words_per_completed_item"], 0)

    def test_missing_outstanding_manual_validation_fails(self):
        path = self._write_backlog(
            VALID_BACKLOG.replace("## Outstanding Manual Validation", "## Notes")
        )

        result = backlog_audit.audit(path)

        self.assertIn(
            "## Outstanding Manual Validation", result["missing_required_sections"]
        )

    def test_missing_implementation_order_fails(self):
        path = self._write_backlog(
            VALID_BACKLOG.replace(
                "## Suggested Implementation Order / PR Execution Queue",
                "## Queue",
            )
        )

        result = backlog_audit.audit(path)

        self.assertIn(
            "## Suggested Implementation Order", result["missing_required_sections"]
        )

    def test_duplicate_tracked_heading_fails(self):
        duplicate = "### Completed 2026-01-01 - Example"
        path = self._write_backlog(VALID_BACKLOG + f"\n{duplicate}\n")

        result = backlog_audit.audit(path)

        self.assertEqual([duplicate], result["duplicate_tracked_headings"])

    def test_json_output_contains_comparison_fields(self):
        path = self._write_backlog()
        output = io.StringIO()
        with patch.object(sys, "argv", ["backlog_audit.py", str(path), "--json"]):
            with contextlib.redirect_stdout(output):
                self.assertEqual(0, backlog_audit.main())

        result = json.loads(output.getvalue())
        self.assertEqual(1, result["completed_count"])
        self.assertEqual(1, result["open_count"])
        self.assertIn("completed_words", result)
        self.assertIn("average_words_per_completed_item", result)
        self.assertEqual([], result["missing_required_sections"])

    def test_missing_backlog_path_returns_parser_error(self):
        missing = ROOT / "does-not-exist" / "BACKLOG.md"
        with patch.object(sys, "argv", ["backlog_audit.py", str(missing)]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    backlog_audit.main()

        self.assertEqual(2, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
