# es-ESS Backlog Format

Use this reference when creating or substantially restructuring `BACKLOG.md`.

## Required Behavior

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

- `README.md` for supported services, setup, configuration, and user-facing
  behavior.
- `BACKLOG.md` if it exists.
- Top-level Python service modules, especially orchestration and enabled
  service boundaries.
- `config.sample.ini` and `config.reference.ini` for supported settings and
  documentation consistency.
- `tests/` for current regression coverage and hardware-free test patterns.
- Install/service files such as `install.sh`, `restart.sh`, `kill_me.sh`,
  `uninstall.sh`, and `service/run`.

## Architecture Summary

Include:

- Main runtime entry points.
- Major services and their responsibilities.
- External integrations such as MQTT, D-Bus, Fronius Wattpilot, Shelly devices,
  Victron Venus OS, and configuration files.
- Current test strategy and important gaps.
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
- Are there known incidents, logs, user reports, or failing scenarios to focus
  on?

If the missing information is not blocking, continue with clearly stated
assumptions and mark the related backlog items as needing user confirmation.

## Backlog Handling

- If `BACKLOG.md` exists, read it first and update it in place.
- If `BACKLOG.md` does not exist, create a new `BACKLOG.md`.
- Do not create a duplicate backlog file unless the user explicitly asks.
- Preserve useful existing backlog items and their context.
- Mark obsolete items only when the repository review proves they are no longer
  relevant, and explain why.
- Add new findings as implementable backlog items.
- Keep the backlog ordered by priority and implementation sequence.

Each backlog item must include:

- Priority, such as `P0`, `P1`, `P2`, or `P3`.
- Title.
- Problem statement.
- Evidence from the repository, with file references where possible.
- Proposed implementation.
- Code files expected to change.
- Files expected to be added.
- Tests to add or update.
- Expected coverage or behavior that the tests must prove.
- Manual validation required from the user.
- Step-by-step manual test instructions.
- Risks, dependencies, and open questions.
- Done criteria.

## Output Format

When updating or creating `BACKLOG.md`, use this structure unless the existing
file already has a clearer project-specific structure:

```markdown
# es-ESS Backlog

## Current App Analysis

## Review Questions And Assumptions

## Backlog

### P0 - Item Title

Problem:

Evidence:

Implementation:

Files to change:

Files to add:

Tests:

Expected coverage:

Manual validation:

Manual test steps:

Risks and dependencies:

Open questions:

Done criteria:

## Verification Plan

## User Manual Test Checklist
```

## Review Priorities

Prioritize findings in this order:

1. Safety, data integrity, or device-control risks.
2. Behavior that could cause unintended grid usage, battery discharge, charging
   behavior, or service instability.
3. Configuration defects, undocumented active settings, dead settings, and
   backward compatibility risks.
4. Runtime reliability, reconnection behavior, stale telemetry handling, and
   error recovery.
5. Test gaps around decision logic, config contracts, and integration seams.
6. Documentation gaps that affect installation, operation, or debugging.
7. Maintainability improvements with clear user or contributor value.

## Verification Expectations

For each proposed implementation item, specify:

- Automated tests to run, such as targeted unit tests or the full test suite.
- Syntax or import checks needed for changed Python files.
- Any tests that cannot run without hardware or a Venus OS environment.
- Manual user checks that must happen on a real or representative system.
- Rollback or observation steps when the change affects charging behavior.

## Final Response After Review

After the backlog is created or updated, respond with:

- The backlog file path.
- A short summary of the highest-priority items added or changed.
- Any questions still blocking confident implementation.
- The automated verification performed.
- The manual verification the user still needs to perform.
