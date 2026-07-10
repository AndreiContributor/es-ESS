# es-ESS Backlog Format

Use this reference when creating or substantially restructuring `BACKLOG.md`.

## Required Behavior

- Read `AGENTS.md` before any review. Findings and implementations must comply
  with the delivery rules and safety invariants stated there.
- Do not assume product intent, deployment constraints, hardware behavior,
  architecture boundaries, or test expectations when they are missing.
- Ask the user concise questions before reviewing or recommending changes when
  missing information could materially affect the outcome.
- Preserve user work. Do not revert, delete, or overwrite unrelated changes.
- Prefer existing code patterns, helpers, config style, and test structure over
  new abstractions unless the review finds a clear need.
- Focus on implementation-ready findings, not broad commentary.
- Separate confirmed findings from assumptions, questions, and optional ideas.

## Repository Areas To Inspect

- `AGENTS.md` — delivery rules and working agreement (read first).
- `BACKLOG.md` — existing findings; read before adding to avoid duplicates.
- `docs/wattpilot-architecture.md` — module boundaries and safety invariants.
- `docs/service-inventory.md` — active/dormant service status and integration map.
- `README.md` — supported services, setup, configuration, and user-facing behavior.
- Top-level Python service modules, especially orchestration and enabled service
  boundaries.
- `config.sample.ini` — supported settings and documentation consistency.
- `tests/` — current regression coverage and hardware-free test patterns.
- Install and service files: `install.sh`, `restart.sh`, `kill_me.sh`,
  `uninstall.sh`, `service/run`.
- `.github/workflows/ci.yml` — CI triggers, Python version, and test steps.

## Architecture Summary

Include:

- Main runtime entry points and service lifecycle order.
- Major services, their responsibilities, and which are active vs. dormant.
- External integrations: Wattpilot WebSocket, D-Bus, main MQTT, local Venus MQTT,
  HTTP polling, and the SolarOverheadDistributor request namespace.
- Current test coverage: which active service modules have test files, which do not.
- Any architecture or deployment details that remain unclear.

## Missing Information Gate

Ask the user for missing details when they are needed to judge priority or
correctness. Useful questions include:

- Which service or feature area should be reviewed first?
- Is the review for a release, a PR, a refactor, production hardening, or bug
  discovery?
- What hardware, firmware, and Venus OS environment must be supported?
- Which behaviors must remain backward compatible?
- Are live-device, MQTT, D-Bus, or hardware-in-the-loop tests available?
- Are there known incidents, logs, user reports, or failing scenarios to focus on?

If the missing information is not blocking, continue with clearly stated
assumptions and mark the related backlog items as needing user confirmation.

## Backlog Handling

- If `BACKLOG.md` exists, read it first and update it in place.
- If `BACKLOG.md` does not exist, create a new `BACKLOG.md`.
- Do not create a duplicate backlog file unless the user explicitly asks.
- Preserve useful existing backlog items and their context, including completion
  notes and the Suggested Implementation Order.
- Mark obsolete items only when the repository review proves they are no longer
  relevant, and explain why.
- Add new findings as implementable backlog items before the Suggested
  Implementation Order section.
- Add new items to the Suggested Implementation Order at the correct priority
  position with a one-line rationale.
- Keep the backlog ordered by priority and implementation sequence.

Each backlog item must include all sections from the template below.

## Backlog Item Template

```markdown
### P{N} - {Title}

Goal:

One sentence stating what this item achieves and why it matters.

Problem:

What goes wrong today, and under which conditions. Distinguish between
crashes (always reproducible), latent bugs (trigger under specific conditions),
security risks, and documentation gaps.

Evidence:

File and line references from the current repository. Quote the relevant
code fragment when it clarifies the problem. Reference the crash class or
security pattern that applies (see SKILL.md checklist).

Implementation:

Specific steps to fix the problem. Name the function, method, or pattern to
change. State what must NOT change (safety invariants, command boundaries,
topic names, config defaults) to constrain the scope.

Files to change:

- List each file expected to require edits.

Files to add:

- List each new file expected, or "None expected."

Tests:

- Specific test cases to add, named by scenario.
- State which existing test files to extend vs. which new file to create.
- Confirm the test follows the hardware-free stub pattern from `tests/test.py`.

Expected coverage:

- What the new tests prove that was not proven before.
- Confirm existing passing tests remain unchanged.

Manual validation:

Classify as one of: log-only (safe in production), fault simulation (low-risk
window), active charging required, or hardware not needed. Then describe what
the user must observe.

Manual test steps:

1. Numbered steps the user runs on the GX device (or confirms in a unit test).

Risks and dependencies:

- What could go wrong with the proposed fix.
- Which other backlog items must land first.

Open questions:

- Decisions still needed from the user, or "None."

Done criteria:

- Bullet list of verifiable completion conditions.
- Always ends with "Full unittest suite passes."
```

## Review Priorities

Prioritize findings in this order:

1. **Crashes**: TypeError, ZeroDivisionError, RuntimeError in active worker
   threads (None arithmetic, missing lock, division by zero).
2. **Safety and device-control risks**: unintended grid usage, battery
   discharge, Manual mode interference, stale-telemetry bypass.
3. **Security**: eval() on config values, os.popen() with string interpolation,
   shell injection, config value injection into subprocesses.
4. **Runtime reliability**: MQTT reconnect routing, unbounded HTTP requests,
   connection-state guards, error recovery.
5. **Configuration defects**: undocumented active settings, dead settings,
   inverted thresholds, zero intervals, backward compatibility risks.
6. **Test gaps**: active service modules with no test file, decision logic not
   covered by hardware-free tests, integration seams without regression tests.
7. **Documentation gaps**: README/config/runtime mismatches, dormant service
   documentation, installation or debugging gaps.
8. **Maintainability**: structural improvements with clear contributor value
   (extract named methods, reduce inline complexity).

## Verification Expectations

For each proposed implementation item, specify:

- Python files to syntax-check with `python -m py_compile`.
- Targeted test files to run before the full suite.
- The full suite command: `python -m unittest discover -s tests`.
- Config contract test when `config.sample.ini` or Wattpilot key usage changes:
  `python -m unittest tests.test_config_contract`.
- Config migration test when `_validateConfiguration()` changes:
  `python -m unittest tests.test_config_migration`.
- Any tests that cannot run without hardware, MQTT, D-Bus, or Venus OS; document
  these explicitly as requiring manual validation.
- Manual user checks classified by category: log-only, fault simulation, active
  charging required, or hardware not needed.

## Suggested Implementation Order

Every `BACKLOG.md` must include a `## Suggested Implementation Order` section.
Order rules:

- Crash fixes (P2 None guards, missing locks) come first.
- Safety fixes come before security fixes.
- Security fixes come before reliability fixes.
- Reliability fixes come before test coverage additions.
- Test coverage additions come before documentation and structural improvements.
- Dormant service and doc alignment comes last.
- Items that are prerequisites for other items must precede their dependents.
- Each entry in the order is one line: `N. P{level} item title — rationale`.

## Final Response After Review

After the backlog is created or updated, respond with:

- The backlog file path.
- A short summary of the highest-priority items added or changed.
- Which open items are crashes vs. security vs. reliability vs. documentation.
- Any questions still blocking confident implementation.
- The automated verification performed (syntax check, config contract, full suite).
- The manual verification the user still needs to perform, classified by category.
