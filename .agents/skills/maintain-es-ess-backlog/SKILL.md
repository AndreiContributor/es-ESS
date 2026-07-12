---
name: maintain-es-ess-backlog
description: Refresh, review, and safely compact the es-ESS BACKLOG.md while preserving open work, completed-item identities, safety decisions, production evidence, verification history, and implementation order. Use when manually invoked to perform periodic backlog maintenance, reconcile backlog state with the repository, mark resolved or obsolete entries with evidence, remove repetition, or measure backlog growth. Use the separate es-ess-code-review skill for a deep code review that discovers new findings.
---

# Maintain es-ESS Backlog

Maintain the root `BACKLOG.md` as a concise, evidence-backed implementation
queue and durable decision record. Never trade safety history for shorter text.

## Required Reading

Read completely, in this order:

1. `AGENTS.md`.
2. `BACKLOG.md`.
3. `../es-ess-code-review/references/backlog-format.md`. If this repository
   dependency cannot be read, stop and report it instead of guessing the
   backlog format.
4. `docs/wattpilot-architecture.md` when any entry touches Wattpilot behavior,
   command ownership, runtime status, or safety invariants.
5. `docs/service-inventory.md` when any entry touches service state,
   initialization, D-Bus, MQTT, HTTP, or grid-setpoint ownership.
6. `config.sample.ini` and `README.md` when checking configuration or
   user-facing claims.

Read additional production code and tests only as needed to verify a backlog
claim. For a full repository review or discovery of new findings, also invoke
and follow `es-ess-code-review` rather than expanding this maintenance run.

## Workflow

### 1. Establish scope and baseline

- Inspect the working tree and preserve unrelated user changes.
- Run `scripts/backlog_audit.py BACKLOG.md --json` and retain the complete
  before-edit result in the turn context; do not write a baseline file merely
  for comparison.
- Classify the requested work as refresh, review, compaction, or a combination.
- Treat missing product intent, hardware behavior, supported versions, or
  validation availability as an open question when it affects correctness.

### 2. Review backlog state

- Confirm every open item still applies to the current repository.
- Check open items for duplicates, stale evidence, resolved questions,
  completed prerequisites, priority drift, and queue inconsistency.
- Do not mark an item completed without repository evidence and its required
  verification. Do not reopen a completed item without contradictory evidence.
- Mark an item obsolete only when the current repository proves it no longer
  applies; retain the item identity and state the reason.
- Separate confirmed facts, assumptions, resolved decisions, and open
  questions.

### 3. Plan before editing

For any non-trivial change, explain the proposed changes, preserved
information, risks, verification, and outstanding manual validation. Wait for
explicit user approval before editing, installing dependencies, starting
services, or running modifying commands.

### 4. Refresh and compact

Update `BACKLOG.md` in place. Do not create another backlog or history file
unless the user explicitly requests it.

Preserve for every completed item:

- Exact date and title identity.
- Main implemented outcome.
- Safety, architecture, compatibility, or command-boundary decisions.
- Production-discovered behavior and manual-validation results.
- Material test coverage and accepted limitations or follow-ups.

Safe compaction techniques:

- Consolidate repeated invariant assurances into one preamble applying to all
  completed entries.
- Replace verbose implementation narratives with outcome-focused bullets.
- Combine repetitive test-command wording while retaining what behavior was
  proven and any significant suite result.
- Replace duplicated current-state prose with short pointers to authoritative
  architecture, inventory, configuration, and README documentation.
- Mark answered questions as resolved instead of deleting their decisions.
- Keep important production follow-ups more detailed than ordinary
  documentation-only or extraction-only entries.

Do not:

- Delete or rename an open or completed item merely to reduce line count.
- Summarize away Manual-mode ownership, no-grid behavior, battery-assist bounds,
  stale-telemetry handling, phase-command synchronization, runtime compatibility,
  D-Bus/MQTT contracts, shutdown safety, or live validation evidence.
- Shorten open implementation items below the repository backlog template.
- Change code, configuration, tests, or product documentation during a
  backlog-only run unless separately planned and approved.
- Use Markdown folding as a claimed size reduction; it changes presentation,
  not file or context size.

### 5. Verify preservation

Run the audit script again and compare it with the baseline:

- Compare `lines`, `words`, `completed_words`,
  `average_words_per_completed_item`, `completed_headings`, `open_headings`,
  `missing_required_sections`, and `duplicate_tracked_headings` explicitly.
- Every pre-existing open and completed heading remains unless the approved
  plan explicitly changes its state while retaining its identity and reason.
- Required sections and the implementation queue remain present.
- Open-item template content remains implementation-ready.
- Resolved and obsolete decisions retain their evidence.
- No unexpected file changed.

Then review the full diff and run:

```text
git diff --check -- BACKLOG.md
git status --short
```

Documentation-only maintenance does not require the production unittest suite
unless the edit exposes or changes a code/config claim needing verification.

## Audit Utility

Use `scripts/backlog_audit.py` as a read-only structural check. It reports line
and word counts, completed-section compaction metrics, section sizes,
open/completed headings, duplicate identities, and missing required sections.
It never edits the backlog. Treat average completed-item size as information,
not a hard pass/fail threshold, until repository history establishes a useful
limit.

Typical invocation from the repository root:

```text
uv --cache-dir .uv-cache run --no-project python .agents/skills/maintain-es-ess-backlog/scripts/backlog_audit.py BACKLOG.md
```

Use `--json` for both the pre-edit baseline and post-edit result. Retain both
outputs in the turn context and compare the fields listed in Verify
preservation; do not rely only on total counts because one removed identity and
one added identity can cancel each other out.

## Delivery

Use this stable summary shape so maintenance runs remain comparable:

```text
Backlog maintenance result:
- Changed paths:
- Size: {before lines/words} -> {after lines/words}
- Completed identities: {before} -> {after}; preserved: {yes/no with reason}
- Open identities: {before} -> {after}; preserved: {yes/no with reason}
- Completed compaction: {before average words} -> {after average words}
- Refreshed:
- Resolved:
- Marked obsolete:
- Compacted:
- Automated checks:
- Outstanding questions:
- Manual validation: {category and steps}
- AGENTS.md update: {required/not required and reason}
```
