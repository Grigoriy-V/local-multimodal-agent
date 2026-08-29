@AGENTS.md

## Claude-specific notes

`AGENTS.md` above contains the authoritative execution and safety rules. Nothing
in this file may add, weaken, or replace a rule in it.

- `.claude/settings.json` duplicates some hard rules as a mechanical backstop.
  It is not the source of any rule.
- When Orca dispatches a task, act only as the Claude Worker described in
  `AGENTS.md`: read `ROADMAP.md` and the task-relevant canonical documents,
  follow the bounded brief, and do not invoke Orca or spawn another agent.
- Work in the current checkout, including its existing uncommitted state. The
  Codex Supervisor is responsible for exclusive write ownership while the
  Dispatch is active.
- Do not commit, push, publish, deploy, start product-runtime workers, or cross
  another human gate unless the brief contains fresh explicit authorization.
- Follow Orca's injected lifecycle instructions and send `worker_done` only
  after proportional validation and an honest result report.
- Use `--agent claude` when writing a work-log record.
