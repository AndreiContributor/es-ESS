#!/usr/bin/env python3
"""Read-only structural audit for the es-ESS BACKLOG.md file."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


REQUIRED_SECTION_PREFIXES = (
    "## Current App Analysis",
    "## Review Questions And Assumptions",
    "## Completed",
    "## Backlog",
    "## Suggested Implementation Order",
    "## Verification Plan",
)


def _section_sizes(lines: list[str]) -> dict[str, int]:
    headings = [
        (index, line.strip())
        for index, line in enumerate(lines)
        if line.startswith("## ") and not line.startswith("### ")
    ]
    sizes: dict[str, int] = {}
    for position, (start, heading) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        sizes[heading] = end - start
    return sizes


def audit(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    completed = [line.strip() for line in lines if line.startswith("### Completed ")]
    open_items = [
        line.strip() for line in lines if re.match(r"^### P\d+\s+-\s+", line)
    ]
    tracked = completed + open_items
    duplicates = sorted(
        heading for heading, count in Counter(tracked).items() if count > 1
    )
    section_headings = [line.strip() for line in lines if line.startswith("## ")]
    missing_sections = [
        required
        for required in REQUIRED_SECTION_PREFIXES
        if not any(heading.startswith(required) for heading in section_headings)
    ]

    return {
        "path": str(path),
        "lines": len(lines),
        "words": len(re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE)),
        "completed_count": len(completed),
        "open_count": len(open_items),
        "completed_headings": completed,
        "open_headings": open_items,
        "duplicate_tracked_headings": duplicates,
        "missing_required_sections": missing_sections,
        "section_lines": _section_sizes(lines),
    }


def _print_human(result: dict[str, object]) -> None:
    print(f"Backlog: {result['path']}")
    print(f"Lines: {result['lines']}")
    print(f"Words: {result['words']}")
    print(f"Completed items: {result['completed_count']}")
    print(f"Open items: {result['open_count']}")
    print("Section lines:")
    for heading, count in result["section_lines"].items():
        print(f"  {count:4}  {heading}")
    print("Open headings:")
    for heading in result["open_headings"]:
        print(f"  {heading}")
    print("Completed headings:")
    for heading in result["completed_headings"]:
        print(f"  {heading}")
    print(
        "Duplicate tracked headings: "
        + (", ".join(result["duplicate_tracked_headings"]) or "none")
    )
    print(
        "Missing required sections: "
        + (", ".join(result["missing_required_sections"]) or "none")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backlog", nargs="?", default="BACKLOG.md", type=Path)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    if not args.backlog.is_file():
        parser.error(f"backlog file not found: {args.backlog}")

    result = audit(args.backlog)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_human(result)

    return 1 if (
        result["duplicate_tracked_headings"] or result["missing_required_sections"]
    ) else 0


if __name__ == "__main__":
    sys.exit(main())
