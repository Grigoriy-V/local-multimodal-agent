@AGENTS.md

## Claude-specific notes

`AGENTS.md` above contains the authoritative execution and safety rules. Nothing
in this file may add, weaken, or replace a rule in it.

A session is either a **direct session**, where the human is talking to Claude in
Claude's own interface, or a **Dispatch**, where a Codex Supervisor sent a
bounded brief through Orca. The Execution section of `AGENTS.md` distributes
work inside Codex and does not describe a direct session. In a direct session
Claude is the project agent: it owns the full loop of the approved step,
including analysis, canonical documents and review, and takes its authorization
from the human in the chat. Human gates, safety rules and record rules apply
identically in both modes.

- `.claude/settings.json` duplicates some hard rules as a mechanical backstop.
  It is not the source of any rule.
- Never invoke Orca and never spawn another agent, in either mode.
- Use `--agent claude` when writing a work-log record.

In a Dispatch, act only as the Claude Worker described in `AGENTS.md`:

- Read `ROADMAP.md` and the task-relevant canonical documents, and follow the
  bounded brief.
- Work in the current checkout, including its existing uncommitted state. The
  Codex Supervisor is responsible for exclusive write ownership while the
  Dispatch is active.
- Do not commit, push, publish, deploy, start product-runtime workers, or cross
  another human gate unless the brief contains fresh explicit authorization.
  In a direct session the human's own words are that authorization.
- Follow Orca's injected lifecycle instructions and send `worker_done` only
  after proportional validation and an honest result report.
