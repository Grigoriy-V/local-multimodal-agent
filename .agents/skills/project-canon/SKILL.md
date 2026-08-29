---
name: project-canon
description: Use the canonical local-multimodal-agent documents when analyzing the system, designing changes, or writing and reviewing code. Routes work to the current product, architecture, ownership, operations, roadmap, decisions, and evidence without treating historical documents as instructions.
---

# Project Canon

Read `AGENTS.md` and `ROADMAP.md` first. Then load only the canonical material
needed for the task:

- product behavior, scope or acceptance — `docs/PRODUCT.md`;
- components, flows, state or trust boundaries — `docs/PROJECT_MAP.md`;
- code owners, symbols and tests — `docs/CODEMAP.md`;
- configuration, deployment, secrets, storage or diagnostics —
  `docs/OPERATIONS_MAP.md`;
- rationale for a durable boundary — only the relevant `DECISIONS.md` entry;
- exact prior evidence — only reports linked by the roadmap or relevant canon.

For analysis and design, identify the product outcome, current owner and
affected boundaries before proposing a change. For implementation, inspect the
owner and its focused tests before adding another abstraction, script, runtime
or workflow.

Treat architectural references in `PROJECT_MAP.md` as maturity references, not
specifications to copy. Preserve the project's product principles and existing
sound boundaries.

If canon, code and evidence disagree, report the drift and resolve it instead of
silently choosing one. Documentation does not authorize implementation,
workers, deployment or other human-gated actions.
