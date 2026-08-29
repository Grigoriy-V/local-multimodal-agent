---
name: orca-claude-bridge
description: Run Claude Code as a supervised Orca worker only when the human explicitly asks Codex to pass work to Claude, then wait for and verify the result.
---

# Orca Claude Bridge

Use this skill only after an explicit human request to pass the current work to
Claude, use Claude through Orca, or invoke `$orca-claude-bridge`. Do not infer
delegation merely because Claude might be useful. One explicit request
authorizes one bounded supervised workflow, including fresh correction Tasks
needed to satisfy the original brief, but not later or widened work.

Use the installed `orchestration` and `orca-cli` skills. Before issuing Orca
commands, load the version-matched live guide with
`orca skills get orchestration`; do not rely on cached command syntax when the
live guide differs.

## Preconditions and placement

- Confirm the Orca runtime is ready and `orca worktree current --json` resolves
  to the checkout Codex is using. A headless `orca serve` runtime is acceptable.
- Use `current` so Claude sees modified and untracked files. Create another
  worktree only when the human requests it or a concrete filesystem conflict
  requires it.
- Enforce one writer: while Claude's Dispatch is active, Codex must not edit the
  checkout. Resume Codex edits only after settlement.
- Preserve every repository instruction and authority boundary. Delegation does
  not authorize commits, pushes, publication, destructive actions, product
  workers, deployments, external services, or unrelated edits.

## Codex App coordinator identity

A Codex App shell is not itself an Orca-managed agent terminal. Create one quiet
coordinator terminal in the current worktree and retain its handle for the Run:

```powershell
orca terminal create --worktree current --title "Codex App Orca coordinator" --command "powershell -NoLogo -NoExit" --json
```

Use that handle as the explicit coordinator identity for Run, Task, worker
start, checks, replies, and acknowledgements as required by the live guide.

## Supervised workflow

1. Inspect the repository context needed to write a reliable brief.
2. Create one Run and one bounded Task. The Task spec must be self-contained:
   goal, scope, accepted decisions, exclusions, relevant evidence and canonical
   documents, acceptance criteria, and required or skipped checks. Do not copy
   Orca lifecycle commands into it.
3. Start a fresh Claude worker with `--worktree current`. Honor an explicitly
   requested model and effort; do not silently downgrade substantive work to a
   cheap smoke-test configuration.
4. Require a start receipt showing that the task input was accepted. Treat
   trust, permission, or startup prompt failures as failed starts.
5. Wait through Orca for `worker_done`, `question`, or `escalation`. Answer
   bounded clarification questions without widening authority. A wait timeout is
   a liveness checkpoint, not task completion.
6. After accepted `worker_done`, independently inspect the claimed files or diff
   and run proportionate verification. Compare the result with the brief and
   repository canon, not only with Claude's report.
7. Release the owned worker, acknowledge the Delivery, and close only the
   coordinator terminal created for this Run.

For review-only work, Claude reports findings and does not edit. If source-code
corrections are required after implementation, give the defects to a fresh
supervised Claude Task, repeat review and verification, and keep the work within
the original authorization. Codex must not silently implement the correction.
Stop and ask the human if correction requires wider scope or another gate.
