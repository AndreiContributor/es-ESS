---
name: es-ess-code-review
description: Review es-ESS and update BACKLOG.md with safety-focused, architecture-aware, implementation-ready findings. Use when asked to run the es-ESS code review workflow, inspect Wattpilot or service risks, review Victron Venus OS / GX integration behavior, or maintain the es-ESS implementation backlog.
---

# es-ESS Code Review

Review es-ESS as a Python service bundle for Victron Venus OS / GX devices.

Start by inspecting `README.md`, `BACKLOG.md`,
`docs/wattpilot-architecture.md`, `docs/service-inventory.md`, top-level
service modules, `config.sample.ini`, `tests/`, and service scripts such as
`install.sh`, `restart.sh`, `kill_me.sh`, `uninstall.sh`, and `service/run`.

Summarize the architecture before listing findings: runtime entry points, major
services, external integrations, test strategy, and unclear deployment details.

Prioritize safety-sensitive findings first, especially Wattpilot behavior, grid
use, battery discharge, battery assist, stale telemetry, phase switching,
configuration compatibility, reconnection behavior, and service reliability.

When a review or implementation task touches Wattpilot behavior, check
`docs/wattpilot-architecture.md` before making findings. Update it when module
responsibilities, command boundaries, safety invariants, or the public
D-Bus/MQTT runtime-status contract need to change.

When a review or implementation task touches service initialization, service
config sections, non-Wattpilot D-Bus/MQTT contracts, external device
dependencies, grid-setpoint ownership, or active/dormant service status, check
`docs/service-inventory.md` before making findings. Update it when those
boundaries change.

Before editing `BACKLOG.md`, ask concise questions only when missing information
materially affects correctness or priority. Otherwise continue with stated
assumptions.

Update `BACKLOG.md` in place. Preserve useful existing context. Add findings as
implementable backlog items with repository evidence, proposed implementation,
expected files, tests, manual validation, risks, open questions, and done
criteria.

When creating or substantially restructuring backlog content, read
`references/backlog-format.md` for the detailed review rules, backlog template,
priority order, verification expectations, and final response checklist.
