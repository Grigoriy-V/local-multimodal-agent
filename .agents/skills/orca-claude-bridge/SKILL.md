---
name: orca-claude-bridge
description: After the human explicitly authorizes a large implementation to begin, prepare its bounded brief, run Claude Code as a supervised Orca worker, wait for it, and verify the result.
---

# Orca Claude Bridge

Use this skill when the repository routing contract assigns a large cohesive
source-code implementation batch to Claude, or when the human explicitly asks
to pass the current work to Claude, use Claude through Orca, or invoke
`$orca-claude-bridge`. Keep architecture, planning, canonical documents,
inspection, review, verification and small localized implementation in Codex
unless the human says otherwise. Routing never authorizes a worker start. Wait
until the human separately and explicitly says that the large implementation
may begin; roadmap approval or a request to begin analysis is not that signal.
After it is given, prepare the brief, acceptance criteria and checks yourself
and run the bounded `opus / medium` workflow without asking for approval of the
brief. Tell the human whenever the Claude route is used.

Use the installed `orchestration` and `orca-cli` skills. On this Windows
workstation, invoke Orca through the packaged CLI at:

```text
C:\Users\user\AppData\Local\Programs\orca\resources\bin\orca.exe
```

Do not use bare `orca` from Codex App: its PowerShell process may not inherit
the Orca PATH entry. Use this same executable for every command in one
workflow. If it is absent, stop and report the installation drift instead of
guessing another Orca build.

Before other Orca commands, load the version-matched live guide with:

```powershell
& 'C:\Users\user\AppData\Local\Programs\orca\resources\bin\orca.exe' skills get orchestration
```

The installed Claude launcher is
`C:\Users\user\AppData\Roaming\npm\claude.cmd`. It may be checked with
`--version` during preflight, but never use it to run the delegated task
directly. Orca must own the Claude process and Dispatch lifecycle.

## Preconditions and placement

- Do not start preflight or create Orca runtime resources until the human has
  explicitly authorized this large implementation to begin.
- Confirm the Orca runtime is ready and `worktree current --json`, invoked
  through the exact CLI above, resolves to the checkout Codex is using. A
  headless Orca runtime is acceptable.
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
& 'C:\Users\user\AppData\Local\Programs\orca\resources\bin\orca.exe' terminal create --worktree current --title "Codex App Orca coordinator" --command "powershell -NoLogo -NoExit" --json
```

Use that handle as the explicit coordinator identity for Run, Task, worker
start, checks, replies, and acknowledgements as required by the live guide.

## Supervised workflow

1. Inspect the repository context needed to write a reliable brief.
2. Confirm that the human explicitly authorized this large implementation to
   begin. Do not infer that from roadmap approval or a request to begin analysis.
   Then write the Task spec yourself; show it only when the human asks.
3. Create one Run and one bounded Task. The Task spec must be self-contained:
   goal, scope, accepted decisions, exclusions, relevant evidence and canonical
   documents, acceptance criteria, and required or skipped checks. Do not copy
   Orca lifecycle commands into it.
4. Start every fresh Claude worker with the single project configuration
   `--model opus --effort medium`; do not select a different configuration by
   task complexity:

   ```powershell
   & 'C:\Users\user\AppData\Local\Programs\orca\resources\bin\orca.exe' orchestration worker-start --task <task_id> --worktree current --agent claude --model opus --effort medium --json
   ```

   Confirm in the start receipt that `launch.effective` matches the requested
   model and effort and that `stage` is `input_accepted` before treating the
   worker as started. Do not replace this with a direct Claude invocation or a
   manually launched Claude terminal.
5. Require a start receipt showing that the task input was accepted. Treat
   trust, permission, or startup prompt failures as failed starts.
6. Wait through one event-driven Orca long-poll for `worker_done`, `question`,
   or `escalation`, using the live guide's current command shape and a
   15-minute timeout (currently `--timeout-ms 900000`). Do not replace it with
   repeated one-minute Orca checks. Heartbeats do not wake this wait. Answer
   bounded clarification questions without widening authority. A wait timeout
   is a liveness checkpoint, not task completion; use `worker-show` or a bounded
   `worker-read` only when a real liveness or debugging question exists.
7. After accepted `worker_done`, independently inspect the claimed files or diff
   and run proportionate verification. Compare the result with the brief and
   repository canon, not only with Claude's report.
8. Before acknowledging or releasing the settled worker, choose its next owner.
   If review finds an immediate in-scope correction, create a fresh correction
   Task and start it on the exact same Claude terminal with
   `worker-start --task <next_task_id> --terminal <handle> --json`. Do not pass
   `--model` or `--effort` when reusing a terminal; the existing session retains
   its original `opus / medium` configuration. Require the reuse receipt to show
   that the new Task input was accepted.
9. When no immediate correction remains, release the owned worker, acknowledge
   the Delivery, and close only the coordinator terminal created for this Run.

For review-only work, Claude reports findings and does not edit. If source-code
corrections are required after implementation, prepare the defects as a fresh
supervised Claude Task within the already authorized bounded workflow and
prefer the same Claude session as described above, then repeat review and
verification. Use a fresh worker only when immediate reuse is unavailable or
inappropriate. Codex must not silently implement the correction. Stop and ask
the human if a correction requires wider scope or another gate.
